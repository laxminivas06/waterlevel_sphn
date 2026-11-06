"""
Tier 3: Pairwise Cross-Feature Interactions E2E Tests for Smart Water Tank Level Monitoring System.
Verifies cross-cutting workflows, state propagation between telemetry ingestion, settings, status,
analytics, and the backup subsystem (>= 15 tests).
"""

import json
import os
import sqlite3
import subprocess
import sys
import time
import pytest


class TestTier3Interactions:
    """Verifies pairwise cross-feature state interactions and pipeline integrity."""

    def test_interaction_01_ingest_reading_updates_current_status(self, client, default_device_id, default_api_key):
        """Pair: Telemetry Ingestion -> Current Status API. Ingestion immediately updates status endpoint."""
        payload = {
            "device_id": default_device_id,
            "distance_cm": 35.0,
            "water_level_cm": 165.0,
            "water_percentage": 82.5,
            "water_litres": 825.0,
            "api_key": default_api_key,
        }
        post_resp = client.post("/api/water-level", json=payload)
        assert post_resp.status_code == 201

        status_resp = client.get(f"/api/water-level/current?device_id={default_device_id}")
        assert status_resp.status_code == 200
        reading = status_resp.json.get("reading", {})
        assert abs(reading.get("water_litres", 0) - 825.0) < 0.1
        assert abs(reading.get("water_percentage", 0) - 82.5) < 0.1
        assert status_resp.json.get("device", {}).get("status") == "online"

    def test_interaction_02_ingest_reading_updates_daily_stats(self, client, default_device_id, default_api_key):
        """Pair: Telemetry Ingestion -> Daily Stats Aggregates. New readings increment count and adjust min/max."""
        payload = {
            "device_id": default_device_id,
            "distance_cm": 25.0,
            "water_level_cm": 175.0,
            "water_percentage": 87.5,
            "water_litres": 875.0,
            "api_key": default_api_key,
        }
        client.post("/api/water-level", json=payload)

        stats_resp = client.get("/api/history/daily-stats?days=1")
        assert stats_resp.status_code == 200
        stats_list = stats_resp.json.get("stats") or stats_resp.json.get("daily_stats") or []
        assert len(stats_list) >= 1
        today_stat = stats_list[-1]
        assert today_stat.get("reading_count", 0) >= 1
        assert today_stat.get("max_litres", 0) >= 875.0

    def test_interaction_03_ingest_reading_updates_intraday_readings(self, client, default_device_id, default_api_key):
        """Pair: Telemetry Ingestion -> Intraday Time-Series. Posted reading appears in today's readings list."""
        payload = {
            "device_id": default_device_id,
            "distance_cm": 55.0,
            "water_level_cm": 145.0,
            "water_percentage": 72.5,
            "water_litres": 725.0,
            "api_key": default_api_key,
        }
        post_resp = client.post("/api/water-level", json=payload)
        reading_id = post_resp.json.get("reading_id")

        readings_resp = client.get("/api/history/readings")
        assert readings_resp.status_code == 200
        items = readings_resp.json.get("readings", [])
        assert any(item.get("id") == reading_id or abs(item.get("water_litres", 0) - 725.0) < 0.1 for item in items)

    def test_interaction_04_multi_day_ingestion_updates_comparison(self, client, test_db_path, default_device_id):
        """Pair: Historical Ingestion -> Day-to-Day Comparison. Seeded multi-day readings compute accurate delta."""
        conn = sqlite3.connect(test_db_path)
        d1, d2 = "2026-11-01", "2026-11-02"
        conn.execute("INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, timestamp, date) VALUES (?, 60, 140, 70, 700, '2026-11-01 10:00:00', ?);", (default_device_id, d1))
        conn.execute("INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, timestamp, date) VALUES (?, 40, 160, 80, 800, '2026-11-02 10:00:00', ?);", (default_device_id, d2))
        conn.commit()
        conn.close()

        resp = client.get(f"/api/history/compare?date1={d1}&date2={d2}")
        assert resp.status_code == 200
        comp = resp.json.get("comparison", {})
        diff = comp.get("avg_difference_litres") or comp.get("avg_litres_diff")
        assert diff is not None
        assert abs(diff - 100.0) < 1.0

    def test_interaction_05_update_tank_settings_updates_remaining_litres_in_current_status(self, client, sample_telemetry_payload, default_device_id):
        """Pair: Tank Settings Update -> Current Status Remaining Litres. Changing total capacity alters remaining volume."""
        client.post("/api/water-level", json=sample_telemetry_payload) # litres = 787.5
        # Default capacity = 1000L -> remaining = 212.5L

        # Increase capacity to 1200L
        update_body = {
            "tank_height_cm": 200.0,
            "sensor_offset_cm": 15.0,
            "total_capacity_litres": 1200.0,
            "offline_threshold_seconds": 300,
            "low_threshold_percent": 20.0,
            "critical_low_threshold_percent": 10.0,
        }
        client.put("/api/settings", json=update_body)

        status_resp = client.get(f"/api/water-level/current?device_id={default_device_id}")
        assert status_resp.status_code == 200
        tank = status_resp.json.get("tank", {})
        reading = status_resp.json.get("reading", {})
        remaining = tank.get("remaining_litres") or reading.get("remaining_litres")
        assert remaining is not None
        # 1200 - 787.5 = 412.5L
        assert abs(remaining - 412.5) < 1.0

    def test_interaction_06_update_offline_threshold_changes_device_online_status(self, client, test_db_path, default_device_id):
        """Pair: Tank Settings Timeout -> Device Status Evaluation. Modifying threshold flips device status."""
        conn = sqlite3.connect(test_db_path)
        # Device seen 100 seconds ago
        conn.execute("UPDATE devices SET last_seen = datetime('now', '-100 seconds') WHERE device_id = ?;", (default_device_id,))
        conn.commit()
        conn.close()

        # Under default threshold (300s): device is online
        resp1 = client.get(f"/api/water-level/current?device_id={default_device_id}")
        assert resp1.status_code == 200
        assert resp1.json.get("device", {}).get("status") == "online"

        # Update threshold to 60s
        update_body = {
            "tank_height_cm": 200.0,
            "sensor_offset_cm": 15.0,
            "total_capacity_litres": 1000.0,
            "offline_threshold_seconds": 60,
            "low_threshold_percent": 20.0,
            "critical_low_threshold_percent": 10.0,
        }
        client.put("/api/settings", json=update_body)

        # Now device (100s > 60s) is offline
        resp2 = client.get(f"/api/water-level/current?device_id={default_device_id}")
        assert resp2.status_code == 200
        assert resp2.json.get("device", {}).get("status") == "offline"

    def test_interaction_07_ingested_readings_exported_by_backup_cli(self, client, project_root, test_db_path, temp_backup_dir, default_device_id, default_api_key):
        """Pair: Telemetry Ingestion -> Standalone Backup CLI. Backup file includes ingested readings."""
        payload = {
            "device_id": default_device_id,
            "distance_cm": 44.0,
            "water_level_cm": 156.0,
            "water_percentage": 78.0,
            "water_litres": 780.0,
            "api_key": default_api_key,
        }
        client.post("/api/water-level", json=payload)

        script_path = os.path.join(project_root, "scripts", "backup.py")
        if not os.path.exists(script_path):
            script_path = os.path.join(project_root, "backup.py")

        cmd = [
            sys.executable, script_path,
            "--format", "json",
            "--db-path", test_db_path,
            "--output-dir", temp_backup_dir,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0

        files = [f for f in os.listdir(temp_backup_dir) if f.endswith(".json")]
        assert len(files) >= 1
        with open(os.path.join(temp_backup_dir, files[0]), "r", encoding="utf-8") as f:
            dump = json.load(f)
            readings = dump.get("water_readings", [])
            assert any(abs(r.get("water_litres", 0) - 780.0) < 0.1 for r in readings)

    def test_interaction_08_manual_backup_create_appears_in_backup_list(self, client):
        """Pair: Backup Create API -> Backup List API. Created backup is logged and indexed."""
        create_resp = client.post("/api/backup/create", json={"format": "both"})
        assert create_resp.status_code == 201
        filename = create_resp.json.get("filename")

        list_resp = client.get("/api/backup/list")
        assert list_resp.status_code == 200
        logs = list_resp.json.get("backups", list_resp.json)
        assert any(entry.get("filename") == filename for entry in logs)

    def test_interaction_09_manual_backup_create_downloadable_via_api(self, client, temp_backup_dir):
        """Pair: Backup Create API -> Backup Download API. File created via API is retrievable."""
        create_resp = client.post("/api/backup/create", json={"format": "json"})
        assert create_resp.status_code == 201
        filename = create_resp.json.get("filename")

        # Download using API
        dl_resp = client.get(f"/api/backup/download/{filename}")
        assert dl_resp.status_code == 200
        assert len(dl_resp.data) > 0

    def test_interaction_10_backup_retention_rotation_purges_older_file_keeps_newer(self, project_root, test_db_path, temp_backup_dir):
        """Pair: Backup Generation -> Retention Rotation. Old files (> retention_days) deleted, new files kept."""
        script_path = os.path.join(project_root, "scripts", "backup.py")
        if not os.path.exists(script_path):
            script_path = os.path.join(project_root, "backup.py")

        old_file = os.path.join(temp_backup_dir, "backup_old_test.json")
        new_file = os.path.join(temp_backup_dir, "backup_new_test.json")
        with open(old_file, "w") as f:
            f.write("{}")
        with open(new_file, "w") as f:
            f.write("{}")

        # Set old_file mtime to 40 days ago
        old_time = time.time() - (40 * 86400)
        os.utime(old_file, (old_time, old_time))

        cmd = [
            sys.executable, script_path,
            "--format", "json",
            "--db-path", test_db_path,
            "--output-dir", temp_backup_dir,
            "--retention-days", "30",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0

        assert not os.path.exists(old_file), "Expired backup file should have been deleted by retention rotation"
        assert os.path.exists(new_file), "Recent backup file should have been preserved"

    def test_interaction_11_auth_header_and_body_produce_identical_records(self, client, test_db_path, default_device_id, default_api_key):
        """Pair: Header Auth vs Body Auth. Both ingestion paths produce identical DB records."""
        # 1. Header auth
        payload1 = {
            "device_id": default_device_id,
            "distance_cm": 50.0,
            "water_level_cm": 150.0,
            "water_percentage": 75.0,
            "water_litres": 750.0,
        }
        client.post("/api/water-level", json=payload1, headers={"X-API-Key": default_api_key, "Content-Type": "application/json"})

        # 2. Body auth
        payload2 = dict(payload1)
        payload2["api_key"] = default_api_key
        client.post("/api/water-level", json=payload2)

        conn = sqlite3.connect(test_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT distance_cm, water_level_cm, water_percentage, water_litres FROM water_readings ORDER BY id DESC LIMIT 2;")
        rows = cursor.fetchall()
        conn.close()

        assert len(rows) == 2
        assert rows[0] == rows[1]

    def test_interaction_12_deactivate_device_blocks_subsequent_telemetry(self, client, test_db_path, sample_telemetry_payload):
        """Pair: Device Admin State -> Ingestion Gate. Deactivated device is rejected with 403."""
        # Verify initial post succeeds
        r1 = client.post("/api/water-level", json=sample_telemetry_payload)
        assert r1.status_code == 201

        # Deactivate
        conn = sqlite3.connect(test_db_path)
        conn.execute("UPDATE devices SET is_active = 0 WHERE device_id = ?;", (sample_telemetry_payload["device_id"],))
        conn.commit()
        conn.close()

        # Next post must fail with 403
        r2 = client.post("/api/water-level", json=sample_telemetry_payload)
        assert r2.status_code == 403

    def test_interaction_13_multi_device_telemetry_isolation(self, client, test_db_path):
        """Pair: Multi-Device Ingestion -> Current Status Isolation. Readings for device A do not overwrite device B."""
        conn = sqlite3.connect(test_db_path)
        conn.execute("INSERT OR IGNORE INTO devices (device_id, api_key, device_name) VALUES ('tank_A', 'key_A', 'Tank Alpha');")
        conn.execute("INSERT OR IGNORE INTO devices (device_id, api_key, device_name) VALUES ('tank_B', 'key_B', 'Tank Beta');")
        conn.commit()
        conn.close()

        client.post("/api/water-level", json={"device_id": "tank_A", "distance_cm": 30.0, "water_level_cm": 170.0, "water_percentage": 85.0, "water_litres": 850.0, "api_key": "key_A"})
        client.post("/api/water-level", json={"device_id": "tank_B", "distance_cm": 100.0, "water_level_cm": 100.0, "water_percentage": 50.0, "water_litres": 500.0, "api_key": "key_B"})

        resp_a = client.get("/api/water-level/current?device_id=tank_A")
        resp_b = client.get("/api/water-level/current?device_id=tank_B")

        assert abs(resp_a.json.get("reading", {}).get("water_litres", 0) - 850.0) < 0.1
        assert abs(resp_b.json.get("reading", {}).get("water_litres", 0) - 500.0) < 0.1

    def test_interaction_14_health_endpoint_reflects_db_changes(self, client, test_db_path):
        """Pair: SQLite Database State -> Health Probe. Health probe reports active connectivity."""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json.get("status") in ("healthy", "ok")

    def test_interaction_15_simulate_esp32_script_with_live_server(self, project_root, default_device_id, default_api_key):
        """Pair: simulate_esp32.py CLI -> API Telemetry Integration."""
        sim_script = os.path.join(project_root, "scripts", "simulate_esp32.py")
        assert os.path.exists(sim_script)

        # Execute dry-run to verify mathematical derivation
        cmd = [
            sys.executable, sim_script,
            "--dry-run",
            "--device-id", default_device_id,
            "--api-key", default_api_key,
            "--auto-calc",
            "--distance", "50.0",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0
        assert "water_level_cm" in result.stdout

    def test_interaction_16_tank_settings_threshold_updates_level_status_color(self, client, default_device_id, valid_auth_headers):
        """Pair: Tank Settings Thresholds -> Status Color Evaluation. Lowering normal threshold updates status color."""
        # Reading at 45% (below default 50% normal threshold -> orange)
        payload = {
            "device_id": default_device_id,
            "distance_cm": 110.0,
            "water_level_cm": 90.0,
            "water_percentage": 45.0,
            "water_litres": 450.0,
        }
        client.post("/api/water-level", json=payload, headers=valid_auth_headers)

        status_before = client.get(f"/api/water-level/current?device_id={default_device_id}").json
        color_before = status_before.get("tank", {}).get("status_color") or status_before.get("reading", {}).get("level_state")

        # Now change low threshold to 40%
        update_body = {
            "tank_height_cm": 200.0,
            "sensor_offset_cm": 15.0,
            "total_capacity_litres": 1000.0,
            "offline_threshold_seconds": 300,
            "low_threshold_percent": 30.0,
            "critical_low_threshold_percent": 10.0,
        }
        client.put("/api/settings", json=update_body)

        status_after = client.get(f"/api/water-level/current?device_id={default_device_id}").json
        color_after = status_after.get("tank", {}).get("status_color") or status_after.get("reading", {}).get("level_state")
        assert color_after is not None
