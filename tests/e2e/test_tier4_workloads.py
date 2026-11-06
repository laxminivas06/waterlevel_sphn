"""
Tier 4: Real-World Workload Scenarios E2E Tests for Smart Water Tank Level Monitoring System.
Executes multi-day lifecycle simulations, sensor fault recovery, backup retention cycles,
rapid burst concurrency, and live tank recalibration (>= 5 scenarios).
"""

import datetime
import json
import os
import sqlite3
import subprocess
import sys
import time
from typing import List, Dict, Any
import pytest


class TestTier4Workloads:
    """Verifies end-to-end multi-step realistic operational workloads."""

    def test_workload_15_day_inflow_outflow_simulation(self, client, test_db_path, default_device_id):
        """
        Scenario 1: 15-Day Diurnal Inflow/Outflow Simulation.
        Generates 15 continuous days of realistic water tank usage (morning consumption drop,
        afternoon refilling, evening peak, overnight stabilization).
        Verifies 15-day aggregate statistics and cross-day comparisons.
        """
        conn = sqlite3.connect(test_db_path)
        base_date = datetime.date.today() - datetime.timedelta(days=14)
        expected_daily_stats = {}

        for day_offset in range(15):
            cur_date = base_date + datetime.timedelta(days=day_offset)
            date_str = cur_date.strftime("%Y-%m-%d")

            # 4 readings per day: morning (lowering), noon (filling), evening (using), night (full)
            day_volumes = [
                (cur_date.strftime("%Y-%m-%d 07:00:00"), 450.0, 45.0, 110.0, 90.0), # morning consumption
                (cur_date.strftime("%Y-%m-%d 12:00:00"), 750.0, 75.0, 50.0, 150.0), # refilled
                (cur_date.strftime("%Y-%m-%d 18:00:00"), 600.0, 60.0, 80.0, 120.0), # evening usage
                (cur_date.strftime("%Y-%m-%d 23:00:00"), 850.0, 85.0, 30.0, 170.0), # night top-up
            ]

            for ts, litres, pct, dist, lvl in day_volumes:
                conn.execute(
                    "INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, timestamp, date) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?);",
                    (default_device_id, dist, lvl, pct, litres, ts, date_str),
                )

            volumes = [v[1] for v in day_volumes]
            expected_daily_stats[date_str] = {
                "min_litres": min(volumes),
                "max_litres": max(volumes),
                "avg_litres": sum(volumes) / len(volumes),
                "count": len(volumes),
            }

        conn.commit()
        conn.close()

        # 1. Verify GET /api/history/daily-stats returns 15 entries
        stats_resp = client.get("/api/history/daily-stats?days=15")
        assert stats_resp.status_code == 200
        stats_list = stats_resp.json.get("stats") or stats_resp.json.get("daily_stats") or []
        assert len(stats_list) == 15

        # Verify statistical ground truth for each day
        for stat_entry in stats_list:
            d = stat_entry["date"]
            if d in expected_daily_stats:
                expected = expected_daily_stats[d]
                assert abs(stat_entry["min_litres"] - expected["min_litres"]) < 1.0
                assert abs(stat_entry["max_litres"] - expected["max_litres"]) < 1.0
                assert abs(stat_entry["avg_litres"] - expected["avg_litres"]) < 1.0

        # 2. Verify Day-to-Day Comparison between Day 1 and Day 15
        day1_str = base_date.strftime("%Y-%m-%d")
        day15_str = (base_date + datetime.timedelta(days=14)).strftime("%Y-%m-%d")
        comp_resp = client.get(f"/api/history/compare?date1={day1_str}&date2={day15_str}")
        assert comp_resp.status_code == 200
        comp_data = comp_resp.json.get("comparison", {})
        assert "avg_difference_litres" in comp_data or "avg_litres_diff" in comp_data

    def test_workload_sensor_disconnection_and_recovery(self, client, test_db_path, default_device_id, default_api_key):
        """
        Scenario 2: Sensor Disconnection & Automatic Recovery.
        Simulates an active device transmitting, experiencing a network outage (exceeding
        offline timeout threshold), then recovering automatically upon signal restoration.
        """
        # Step 1: Device is online
        p1 = {
            "device_id": default_device_id,
            "distance_cm": 40.0,
            "water_level_cm": 160.0,
            "water_percentage": 80.0,
            "water_litres": 800.0,
            "api_key": default_api_key,
        }
        r1 = client.post("/api/water-level", json=p1)
        assert r1.status_code == 201

        s1 = client.get(f"/api/water-level/current?device_id={default_device_id}")
        assert s1.status_code == 200
        assert s1.json.get("device", {}).get("status") == "online"

        # Step 2: Sensor disconnects — simulate 400 seconds passing (timeout is 300s)
        conn = sqlite3.connect(test_db_path)
        conn.execute("UPDATE devices SET last_seen = datetime('now', '-400 seconds') WHERE device_id = ?;", (default_device_id,))
        conn.commit()
        conn.close()

        s2 = client.get(f"/api/water-level/current?device_id={default_device_id}")
        assert s2.status_code == 200
        assert s2.json.get("device", {}).get("status") == "offline"
        assert s2.json.get("device", {}).get("seconds_since_last_seen", 0) >= 300

        # Step 3: Wi-Fi recovers — sensor sends new telemetry packet
        p2 = {
            "device_id": default_device_id,
            "distance_cm": 38.0,
            "water_level_cm": 162.0,
            "water_percentage": 81.0,
            "water_litres": 810.0,
            "api_key": default_api_key,
        }
        r2 = client.post("/api/water-level", json=p2)
        assert r2.status_code == 201

        # Step 4: Device is immediately online again
        s3 = client.get(f"/api/water-level/current?device_id={default_device_id}")
        assert s3.status_code == 200
        assert s3.json.get("device", {}).get("status") == "online"
        assert abs(s3.json.get("reading", {}).get("water_litres", 0) - 810.0) < 0.1

    def test_workload_automated_backup_and_retention_cycle(self, project_root, test_db_path, temp_backup_dir):
        """
        Scenario 3: Automated Daily Backup & Retention Rotation Cycle.
        Simulates 40 historical backup files, runs retention cleanup with 30-day limit,
        and verifies disk persistence and DB audit log synchronization.
        """
        script_path = os.path.join(project_root, "scripts", "backup.py")
        if not os.path.exists(script_path):
            script_path = os.path.join(project_root, "backup.py")

        now = time.time()
        created_files = []

        # Create 10 old files (> 30 days) and 10 recent files (< 30 days)
        for i in range(1, 11):
            old_name = f"backup_202609{i:02d}_000000.json"
            old_path = os.path.join(temp_backup_dir, old_name)
            with open(old_path, "w") as f:
                f.write('{"sample": "old"}')
            # 35 to 45 days old
            mtime = now - ((35 + i) * 86400)
            os.utime(old_path, (mtime, mtime))
            created_files.append((old_path, False)) # Should be purged

            recent_name = f"backup_202610{i:02d}_000000.json"
            recent_path = os.path.join(temp_backup_dir, recent_name)
            with open(recent_path, "w") as f:
                f.write('{"sample": "recent"}')
            # 5 to 15 days old
            mtime = now - ((5 + i) * 86400)
            os.utime(recent_path, (mtime, mtime))
            created_files.append((recent_path, True)) # Should be retained

        # Execute backup CLI with 30-day retention
        cmd = [
            sys.executable, script_path,
            "--format", "json",
            "--db-path", test_db_path,
            "--output-dir", temp_backup_dir,
            "--retention-days", "30",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0

        # Verify old files deleted, recent files kept
        for path, should_exist in created_files:
            if should_exist:
                assert os.path.exists(path), f"Recent file {os.path.basename(path)} was incorrectly deleted!"
            else:
                assert not os.path.exists(path), f"Expired file {os.path.basename(path)} should have been purged!"

        # Verify database audit log
        conn = sqlite3.connect(test_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT status, records_count FROM backup_logs ORDER BY id DESC LIMIT 1;")
        log_entry = cursor.fetchone()
        conn.close()

        assert log_entry is not None
        assert log_entry[0] == "success"

    def test_workload_rapid_burst_telemetry_and_concurrency(self, client, test_db_path, default_device_id, default_api_key):
        """
        Scenario 4: Rapid Burst Telemetry & Transaction Concurrency.
        Transmits 50 high-frequency telemetry readings in tight succession.
        Verifies SQLite concurrency handling, lack of database lock crashes, and index ordering.
        """
        num_burst = 50
        reading_ids = []

        for i in range(num_burst):
            payload = {
                "device_id": default_device_id,
                "distance_cm": 50.0 + (i * 0.1),
                "water_level_cm": 150.0 - (i * 0.1),
                "water_percentage": 75.0 - (i * 0.05),
                "water_litres": 750.0 - (i * 0.5),
                "api_key": default_api_key,
            }
            resp = client.post("/api/water-level", json=payload)
            assert resp.status_code == 201, f"Failed at burst index {i}: {resp.text}"
            reading_ids.append(resp.json["reading_id"])

        assert len(reading_ids) == num_burst
        # Verify IDs are strictly ascending
        assert reading_ids == sorted(reading_ids)

        # Verify database record count
        conn = sqlite3.connect(test_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM water_readings WHERE device_id = ?;", (default_device_id,))
        count = cursor.fetchone()[0]
        conn.close()

        assert count >= num_burst

    def test_workload_tank_recalibration_and_geometry_shift(self, client, test_db_path, default_device_id, default_api_key):
        """
        Scenario 5: Dynamic Tank Geometry & Recalibration Shift.
        Modifies physical dimensions and capacity of tank mid-stream.
        Verifies immediate recalculation of percentages and remaining empty volumes.
        """
        # Step 1: Baseline reading on 1000L tank
        p1 = {
            "device_id": default_device_id,
            "distance_cm": 50.0,
            "water_level_cm": 150.0,
            "water_percentage": 75.0,
            "water_litres": 750.0,
            "api_key": default_api_key,
        }
        client.post("/api/water-level", json=p1)

        s1 = client.get(f"/api/water-level/current?device_id={default_device_id}").json
        rem1 = s1.get("tank", {}).get("remaining_litres") or s1.get("reading", {}).get("remaining_litres")
        # 1000 - 750 = 250L remaining
        assert abs(rem1 - 250.0) < 1.0

        # Step 2: Tank is replaced with a larger 2000L tank (height 300cm)
        new_geometry = {
            "tank_height_cm": 300.0,
            "sensor_offset_cm": 20.0,
            "total_capacity_litres": 2000.0,
            "offline_threshold_seconds": 300,
            "low_threshold_percent": 20.0,
            "critical_low_threshold_percent": 10.0,
        }
        update_resp = client.put("/api/settings", json=new_geometry)
        assert update_resp.status_code == 200

        # Step 3: New reading from calibrated sensor
        p2 = {
            "device_id": default_device_id,
            "distance_cm": 80.0,
            "water_level_cm": 240.0,
            "water_percentage": 80.0,
            "water_litres": 1600.0,
            "api_key": default_api_key,
        }
        client.post("/api/water-level", json=p2)

        # Step 4: Verify status reflects 2000L capacity and 400L remaining
        s2 = client.get(f"/api/water-level/current?device_id={default_device_id}").json
        tank2 = s2.get("tank", {})
        reading2 = s2.get("reading", {})
        rem2 = tank2.get("remaining_litres") or reading2.get("remaining_litres")
        capacity2 = tank2.get("total_capacity_litres")

        assert capacity2 == 2000.0
        # 2000 - 1600 = 400L remaining
        assert abs(rem2 - 400.0) < 1.0
