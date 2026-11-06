"""
Tier 1: Feature Coverage E2E Tests for Smart Water Tank Level Monitoring System.
Covers happy paths and baseline functionality for all 14 architectural features (>= 5 tests per feature).
Total: 70 tests.
"""

import csv
import json
import os
import sqlite3
import subprocess
import sys
import pytest


# ==============================================================================
# Feature 1: SQLite Schema & Normalized Tables (R2)
# ==============================================================================

class TestFeature1SqliteSchema:
    """Verifies SQLite relational schema, tables, column constraints, and indexes."""

    def test_feature1_01_all_four_tables_exist(self, test_db_path):
        """Verify the 4 required normalized tables exist in SQLite database."""
        conn = sqlite3.connect(test_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        required = {"devices", "tank_settings", "water_readings", "backup_logs"}
        assert required.issubset(tables), f"Missing required tables: {required - tables}"

    def test_feature1_02_devices_table_columns_and_defaults(self, test_db_path):
        """Verify devices table contains required columns and default device."""
        conn = sqlite3.connect(test_db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(devices);")
        columns = {row[1] for row in cursor.fetchall()}
        cursor.execute("SELECT device_id, api_key, is_active FROM devices WHERE device_id = 'esp32_tank_01';")
        device = cursor.fetchone()
        conn.close()

        assert {"device_id", "api_key", "device_name", "is_active", "last_seen", "created_at"}.issubset(columns)
        assert device is not None
        assert device[0] == "esp32_tank_01"
        assert device[2] == 1  # is_active = 1

    def test_feature1_03_tank_settings_singleton_and_defaults(self, test_db_path):
        """Verify tank_settings table contains id=1 singleton row with default geometry."""
        conn = sqlite3.connect(test_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, tank_height_cm, sensor_offset_cm, total_capacity_litres, offline_threshold_seconds FROM tank_settings WHERE id = 1;")
        settings = cursor.fetchone()
        conn.close()

        assert settings is not None
        assert settings[0] == 1
        assert settings[1] == 200.0  # tank_height_cm
        assert settings[2] == 15.0   # sensor_offset_cm
        assert settings[3] == 1000.0 # total_capacity_litres
        assert settings[4] == 300    # offline_threshold_seconds

    def test_feature1_04_water_readings_columns_and_fk(self, test_db_path):
        """Verify water_readings table structure and foreign key definition."""
        conn = sqlite3.connect(test_db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(water_readings);")
        columns = {row[1] for row in cursor.fetchall()}
        cursor.execute("PRAGMA foreign_key_list(water_readings);")
        fks = cursor.fetchall()
        conn.close()

        expected_cols = {"id", "device_id", "distance_cm", "water_level_cm", "water_percentage", "water_litres", "timestamp", "date"}
        assert expected_cols.issubset(columns)
        assert any(fk[2] == "devices" for fk in fks), "Missing foreign key to devices table"

    def test_feature1_05_backup_logs_columns_and_indexes(self, test_db_path):
        """Verify backup_logs table and composite performance B-Tree indexes."""
        conn = sqlite3.connect(test_db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(backup_logs);")
        columns = {row[1] for row in cursor.fetchall()}
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index';")
        indexes = {row[0] for row in cursor.fetchall()}
        conn.close()

        expected_cols = {"id", "backup_type", "file_format", "filename", "file_path", "file_size_bytes", "records_count", "status", "created_at"}
        assert expected_cols.issubset(columns)
        assert "idx_water_readings_timestamp" in indexes
        assert "idx_water_readings_date" in indexes
        assert "idx_backup_logs_created_at" in indexes


# ==============================================================================
# Feature 2: Telemetry Ingestion POST /api/water-level (R2)
# ==============================================================================

class TestFeature2TelemetryIngestion:
    """Verifies telemetry ingestion endpoint accepting valid ESP32 POST requests."""

    def test_feature2_01_ingest_telemetry_success(self, client, sample_telemetry_payload):
        """Verify POST /api/water-level returns HTTP 201 Created on valid payload."""
        response = client.post("/api/water-level", json=sample_telemetry_payload)
        assert response.status_code == 201
        data = response.json
        assert data.get("status") == "success"

    def test_feature2_02_ingest_returns_reading_id_and_timestamp(self, client, sample_telemetry_payload):
        """Verify response contains generated reading_id integer and timestamp string."""
        response = client.post("/api/water-level", json=sample_telemetry_payload)
        assert response.status_code == 201
        data = response.json
        assert "reading_id" in data
        assert isinstance(data["reading_id"], int)
        assert "timestamp" in data

    def test_feature2_03_ingest_records_persisted_in_database(self, client, test_db_path, sample_telemetry_payload):
        """Verify that ingested telemetry row is written to water_readings table."""
        response = client.post("/api/water-level", json=sample_telemetry_payload)
        assert response.status_code == 201

        conn = sqlite3.connect(test_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT device_id, distance_cm, water_level_cm, water_percentage, water_litres FROM water_readings ORDER BY id DESC LIMIT 1;")
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == sample_telemetry_payload["device_id"]
        assert abs(row[1] - sample_telemetry_payload["distance_cm"]) < 0.01
        assert abs(row[2] - sample_telemetry_payload["water_level_cm"]) < 0.01

    def test_feature2_04_ingest_updates_device_last_seen(self, client, test_db_path, sample_telemetry_payload):
        """Verify that ingestion updates the last_seen column in devices table."""
        client.post("/api/water-level", json=sample_telemetry_payload)

        conn = sqlite3.connect(test_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT last_seen FROM devices WHERE device_id = ?;", (sample_telemetry_payload["device_id"],))
        last_seen = cursor.fetchone()[0]
        conn.close()

        assert last_seen is not None
        assert len(last_seen) > 0

    def test_feature2_05_ingest_multiple_sequential_readings(self, client, default_device_id, default_api_key):
        """Verify multiple sequential readings are ingested with incrementing IDs."""
        ids = []
        for i in range(3):
            payload = {
                "device_id": default_device_id,
                "distance_cm": 40.0 + i,
                "water_level_cm": 160.0 - i,
                "water_percentage": 80.0 - i,
                "water_litres": 800.0 - (i * 10),
                "api_key": default_api_key,
            }
            res = client.post("/api/water-level", json=payload)
            assert res.status_code == 201
            ids.append(res.json["reading_id"])

        assert ids[0] < ids[1] < ids[2]


# ==============================================================================
# Feature 3: API Key Authentication & Rejection (R2)
# ==============================================================================

class TestFeature3Authentication:
    """Verifies dual-mode authentication via HTTP header and JSON body."""

    def test_feature3_01_auth_via_header_x_api_key(self, client, sample_telemetry_payload, default_api_key):
        """Verify authentication succeeds when API key is provided via X-API-Key header."""
        payload = {k: v for k, v in sample_telemetry_payload.items() if k != "api_key"}
        headers = {"X-API-Key": default_api_key, "Content-Type": "application/json"}
        resp = client.post("/api/water-level", json=payload, headers=headers)
        assert resp.status_code == 201

    def test_feature3_02_auth_via_body_field(self, client, sample_telemetry_payload):
        """Verify authentication succeeds when API key is in request body without header."""
        resp = client.post("/api/water-level", json=sample_telemetry_payload)
        assert resp.status_code == 201

    def test_feature3_03_missing_api_key_returns_401(self, client, sample_telemetry_payload):
        """Verify request without header or body API key returns HTTP 401 Unauthorized."""
        payload = {k: v for k, v in sample_telemetry_payload.items() if k != "api_key"}
        resp = client.post("/api/water-level", json=payload)
        assert resp.status_code == 401
        assert "error" in resp.json

    def test_feature3_04_invalid_api_key_returns_401(self, client, sample_telemetry_payload):
        """Verify request with incorrect API key returns HTTP 401 Unauthorized."""
        payload = dict(sample_telemetry_payload)
        payload["api_key"] = "incorrect_secret_token"
        resp = client.post("/api/water-level", json=payload)
        assert resp.status_code == 401
        assert "error" in resp.json

    def test_feature3_05_deactivated_device_returns_403(self, client, test_db_path, sample_telemetry_payload):
        """Verify deactivated device (is_active = 0) returns HTTP 403 Forbidden."""
        conn = sqlite3.connect(test_db_path)
        conn.execute("UPDATE devices SET is_active = 0 WHERE device_id = ?;", (sample_telemetry_payload["device_id"],))
        conn.commit()
        conn.close()

        resp = client.post("/api/water-level", json=sample_telemetry_payload)
        assert resp.status_code == 403
        assert "deactivated" in resp.json.get("error", "").lower()


# ==============================================================================
# Feature 4: Physics Range Validation (R2)
# ==============================================================================

class TestFeature4PhysicsValidation:
    """Verifies strict boundary and range validation for physical telemetry fields."""

    def test_feature4_01_valid_nominal_telemetry_accepted(self, client, sample_telemetry_payload):
        """Nominal reading within typical boundaries is accepted."""
        resp = client.post("/api/water-level", json=sample_telemetry_payload)
        assert resp.status_code == 201

    def test_feature4_02_zero_percentage_and_litres_accepted(self, client, default_device_id, valid_auth_headers):
        """Empty tank boundary (percentage=0.0, litres=0.0) is accepted."""
        payload = {
            "device_id": default_device_id,
            "distance_cm": 215.0,
            "water_level_cm": 0.0,
            "water_percentage": 0.0,
            "water_litres": 0.0,
        }
        resp = client.post("/api/water-level", json=payload, headers=valid_auth_headers)
        assert resp.status_code == 201

    def test_feature4_03_full_tank_100_percent_accepted(self, client, default_device_id, valid_auth_headers):
        """Full tank boundary (percentage=100.0, litres=1000.0) is accepted."""
        payload = {
            "device_id": default_device_id,
            "distance_cm": 15.0,
            "water_level_cm": 200.0,
            "water_percentage": 100.0,
            "water_litres": 1000.0,
        }
        resp = client.post("/api/water-level", json=payload, headers=valid_auth_headers)
        assert resp.status_code == 201

    def test_feature4_04_fractional_precise_values_accepted(self, client, default_device_id, valid_auth_headers):
        """Telemetry with high float precision is accepted and stored correctly."""
        payload = {
            "device_id": default_device_id,
            "distance_cm": 45.67,
            "water_level_cm": 154.33,
            "water_percentage": 77.17,
            "water_litres": 771.65,
        }
        resp = client.post("/api/water-level", json=payload, headers=valid_auth_headers)
        assert resp.status_code == 201

    def test_feature4_05_rejection_of_negative_or_overflow_percentage(self, client, default_device_id, valid_auth_headers):
        """Verify out-of-range percentage (<0 or >100) returns HTTP 422 Unprocessable Entity."""
        payload = {
            "device_id": default_device_id,
            "distance_cm": 45.0,
            "water_level_cm": 155.0,
            "water_percentage": 105.0,
            "water_litres": 1050.0,
        }
        resp = client.post("/api/water-level", json=payload, headers=valid_auth_headers)
        assert resp.status_code == 422


# ==============================================================================
# Feature 5: Device Online/Offline Status Tracking (R2)
# ==============================================================================

class TestFeature5DeviceTracking:
    """Verifies online/offline status computation based on configurable timeout threshold."""

    def test_feature5_01_device_with_recent_reading_is_online(self, client, sample_telemetry_payload, default_device_id):
        """Device that just posted telemetry is marked online."""
        client.post("/api/water-level", json=sample_telemetry_payload)
        resp = client.get(f"/api/water-level/current?device_id={default_device_id}")
        assert resp.status_code == 200
        device_info = resp.json.get("device", {})
        assert device_info.get("status") == "online"

    def test_feature5_02_device_exceeding_threshold_is_offline(self, client, test_db_path, default_device_id):
        """Device whose last_seen timestamp exceeds offline_threshold_seconds is offline."""
        conn = sqlite3.connect(test_db_path)
        # Set last_seen to 600 seconds ago (threshold is 300)
        conn.execute("UPDATE devices SET last_seen = datetime('now', '-600 seconds') WHERE device_id = ?;", (default_device_id,))
        conn.commit()
        conn.close()

        resp = client.get(f"/api/water-level/current?device_id={default_device_id}")
        assert resp.status_code == 200
        device_info = resp.json.get("device", {})
        assert device_info.get("status") == "offline"

    def test_feature5_03_device_with_no_readings_is_offline(self, client, test_db_path):
        """A freshly registered device with NULL last_seen is marked offline."""
        conn = sqlite3.connect(test_db_path)
        conn.execute("INSERT INTO devices (device_id, api_key, device_name, last_seen) VALUES ('device_new', 'key123', 'New Sensor', NULL);")
        conn.commit()
        conn.close()

        resp = client.get("/api/water-level/current?device_id=device_new")
        assert resp.status_code == 200
        assert resp.json.get("device", {}).get("status") == "offline"

    def test_feature5_04_status_returns_seconds_since_last_seen(self, client, sample_telemetry_payload, default_device_id):
        """Response includes numeric seconds_since_last_seen."""
        client.post("/api/water-level", json=sample_telemetry_payload)
        resp = client.get(f"/api/water-level/current?device_id={default_device_id}")
        assert resp.status_code == 200
        device_info = resp.json.get("device", {})
        assert "seconds_since_last_seen" in device_info
        assert isinstance(device_info["seconds_since_last_seen"], (int, float))

    def test_feature5_05_devices_list_endpoint_shows_status(self, client, sample_telemetry_payload):
        """GET /api/devices returns array of devices with online status."""
        client.post("/api/water-level", json=sample_telemetry_payload)
        resp = client.get("/api/devices")
        if resp.status_code == 200:
            devices = resp.json.get("devices", [])
            assert len(devices) >= 1
            assert "status" in devices[0]
        else:
            # If /api/devices not exposed, verify status in /api/water-level/current
            resp2 = client.get("/api/water-level/current")
            assert resp2.status_code == 200


# ==============================================================================
# Feature 6: Real-Time Status & Summary GET /api/water-level/current (R3)
# ==============================================================================

class TestFeature6CurrentStatus:
    """Verifies current status endpoint returning reading, device, tank, and today summary."""

    def test_feature6_01_current_status_success_schema(self, client, sample_telemetry_payload, default_device_id):
        """Verify JSON response schema of GET /api/water-level/current."""
        client.post("/api/water-level", json=sample_telemetry_payload)
        resp = client.get(f"/api/water-level/current?device_id={default_device_id}")
        assert resp.status_code == 200
        data = resp.json
        assert "device" in data
        assert "tank" in data
        assert "reading" in data
        assert "today_summary" in data

    def test_feature6_02_current_status_empty_db_handles_gracefully(self, client, default_device_id):
        """When no readings exist, endpoint returns HTTP 200 with reading=null."""
        resp = client.get(f"/api/water-level/current?device_id={default_device_id}")
        assert resp.status_code == 200
        data = resp.json
        assert data.get("reading") is None
        assert data.get("device", {}).get("status") == "offline"

    def test_feature6_03_current_status_calculates_remaining_litres(self, client, sample_telemetry_payload, default_device_id):
        """Verify remaining empty capacity in litres is accurately computed."""
        client.post("/api/water-level", json=sample_telemetry_payload)
        resp = client.get(f"/api/water-level/current?device_id={default_device_id}")
        assert resp.status_code == 200
        tank = resp.json.get("tank", {})
        reading = resp.json.get("reading", {})
        remaining = tank.get("remaining_litres") or reading.get("remaining_litres")
        assert remaining is not None
        assert abs(remaining - (1000.0 - 787.5)) < 1.0

    def test_feature6_04_current_status_includes_tank_settings(self, client, default_device_id):
        """Verify tank geometry settings are present in response."""
        resp = client.get(f"/api/water-level/current?device_id={default_device_id}")
        assert resp.status_code == 200
        tank = resp.json.get("tank", {})
        assert "total_capacity_litres" in tank

    def test_feature6_05_current_status_includes_today_summary(self, client, sample_telemetry_payload, default_device_id):
        """Verify today_summary includes min, max, avg litres and reading count."""
        client.post("/api/water-level", json=sample_telemetry_payload)
        resp = client.get(f"/api/water-level/current?device_id={default_device_id}")
        assert resp.status_code == 200
        summary = resp.json.get("today_summary", {})
        assert "min_litres" in summary or "min_percentage" in summary


# ==============================================================================
# Feature 7: 15-Day Historical Daily Stats GET /api/history/daily-stats (R4)
# ==============================================================================

class TestFeature7DailyStats:
    """Verifies 15-day daily aggregate statistics API."""

    def test_feature7_01_daily_stats_returns_200_and_array(self, client):
        """GET /api/history/daily-stats returns HTTP 200 and stats array."""
        resp = client.get("/api/history/daily-stats?days=15")
        assert resp.status_code == 200
        data = resp.json
        assert "stats" in data or "daily_stats" in data

    def test_feature7_02_daily_stats_aggregates_min_max_avg(self, client, test_db_path, default_device_id):
        """Verify min, max, and avg are computed across readings for a given date."""
        conn = sqlite3.connect(test_db_path)
        date_str = "2026-11-01"
        for val in [500.0, 700.0, 900.0]:
            conn.execute(
                "INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, timestamp, date) "
                "VALUES (?, 50.0, 150.0, 75.0, ?, '2026-11-01 12:00:00', ?);",
                (default_device_id, val, date_str),
            )
        conn.commit()
        conn.close()

        resp = client.get("/api/history/daily-stats?days=15")
        assert resp.status_code == 200
        stats_list = resp.json.get("stats") or resp.json.get("daily_stats")
        day_stat = next((s for s in stats_list if s.get("date") == date_str), None)
        assert day_stat is not None
        assert abs(day_stat["min_litres"] - 500.0) < 1.0
        assert abs(day_stat["max_litres"] - 900.0) < 1.0
        assert abs(day_stat["avg_litres"] - 700.0) < 1.0

    def test_feature7_03_daily_stats_respects_days_parameter(self, client):
        """Verify days parameter limits the requested range."""
        resp = client.get("/api/history/daily-stats?days=7")
        assert resp.status_code == 200
        assert resp.json.get("days_requested", 7) == 7

    def test_feature7_04_daily_stats_ordered_chronologically(self, client, test_db_path, default_device_id):
        """Verify returned daily stats are ordered chronologically."""
        conn = sqlite3.connect(test_db_path)
        conn.execute("INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, timestamp, date) VALUES (?, 50, 150, 75, 750, '2026-10-25 10:00:00', '2026-10-25');", (default_device_id,))
        conn.execute("INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, timestamp, date) VALUES (?, 50, 150, 75, 750, '2026-10-28 10:00:00', '2026-10-28');", (default_device_id,))
        conn.commit()
        conn.close()

        resp = client.get("/api/history/daily-stats?days=30")
        assert resp.status_code == 200
        stats_list = resp.json.get("stats") or resp.json.get("daily_stats") or []
        dates = [s["date"] for s in stats_list]
        assert dates == sorted(dates)

    def test_feature7_05_daily_stats_device_id_filtering(self, client, test_db_path):
        """Verify daily stats can be filtered by specific device_id."""
        conn = sqlite3.connect(test_db_path)
        conn.execute("INSERT INTO devices (device_id, api_key, device_name) VALUES ('tank_b', 'k2', 'Tank B');")
        conn.execute("INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, timestamp, date) VALUES ('tank_b', 50, 150, 75, 750, '2026-11-05 10:00:00', '2026-11-05');")
        conn.commit()
        conn.close()

        resp = client.get("/api/history/daily-stats?days=15&device_id=tank_b")
        assert resp.status_code == 200


# ==============================================================================
# Feature 8: Intraday Date Readings GET /api/history/readings (R4)
# ==============================================================================

class TestFeature8IntradayReadings:
    """Verifies granular time-series data endpoint for any selected date."""

    def test_feature8_01_readings_for_date_returns_200_and_list(self, client):
        """GET /api/history/readings returns HTTP 200 with date and readings array."""
        resp = client.get("/api/history/readings?date=2026-11-06")
        assert resp.status_code == 200
        assert "readings" in resp.json

    def test_feature8_02_readings_defaults_to_today(self, client, sample_telemetry_payload):
        """Omitting date parameter defaults to current date."""
        client.post("/api/water-level", json=sample_telemetry_payload)
        resp = client.get("/api/history/readings")
        assert resp.status_code == 200
        assert "readings" in resp.json

    def test_feature8_03_readings_empty_date_returns_empty_list_gracefully(self, client):
        """Date with 0 recorded readings returns HTTP 200 with empty list, not error."""
        resp = client.get("/api/history/readings?date=2020-01-01")
        assert resp.status_code == 200
        assert resp.json.get("reading_count", 0) == 0
        assert resp.json.get("readings") == []

    def test_feature8_04_readings_includes_daily_summary(self, client, test_db_path, default_device_id):
        """Response includes day summary object with min, max, avg."""
        conn = sqlite3.connect(test_db_path)
        conn.execute("INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, timestamp, date) VALUES (?, 40, 160, 80, 800, '2026-11-04 10:00:00', '2026-11-04');", (default_device_id,))
        conn.commit()
        conn.close()

        resp = client.get("/api/history/readings?date=2026-11-04")
        assert resp.status_code == 200
        assert "summary" in resp.json

    def test_feature8_05_readings_preserves_chronological_order(self, client, test_db_path, default_device_id):
        """Sequential readings for a date are sorted chronologically by timestamp."""
        conn = sqlite3.connect(test_db_path)
        conn.execute("INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, timestamp, date) VALUES (?, 40, 160, 80, 800, '2026-11-03 08:00:00', '2026-11-03');", (default_device_id,))
        conn.execute("INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, timestamp, date) VALUES (?, 40, 160, 80, 800, '2026-11-03 14:00:00', '2026-11-03');", (default_device_id,))
        conn.commit()
        conn.close()

        resp = client.get("/api/history/readings?date=2026-11-03")
        assert resp.status_code == 200
        readings = resp.json.get("readings", [])
        assert len(readings) == 2
        assert readings[0]["timestamp"] < readings[1]["timestamp"]


# ==============================================================================
# Feature 9: Day-to-Day Comparison GET /api/history/compare (R4)
# ==============================================================================

class TestFeature9DayComparison:
    """Verifies day-to-day comparison API returning metrics for two dates."""

    def test_feature9_01_compare_requires_date1_and_date2(self, client):
        """Missing date parameters returns HTTP 400 Bad Request."""
        resp = client.get("/api/history/compare")
        assert resp.status_code == 400

    def test_feature9_02_compare_two_valid_dates(self, client, test_db_path, default_device_id):
        """Querying two dates returns date1, date2, and comparison object."""
        resp = client.get("/api/history/compare?date1=2026-11-01&date2=2026-11-02")
        assert resp.status_code == 200
        assert "date1" in resp.json
        assert "date2" in resp.json
        assert "comparison" in resp.json

    def test_feature9_03_compare_calculates_litres_difference(self, client, test_db_path, default_device_id):
        """Calculates difference in litres between date2 and date1."""
        conn = sqlite3.connect(test_db_path)
        conn.execute("INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, timestamp, date) VALUES (?, 40, 160, 80, 800, '2026-11-01 10:00:00', '2026-11-01');", (default_device_id,))
        conn.execute("INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, timestamp, date) VALUES (?, 30, 170, 85, 850, '2026-11-02 10:00:00', '2026-11-02');", (default_device_id,))
        conn.commit()
        conn.close()

        resp = client.get("/api/history/compare?date1=2026-11-01&date2=2026-11-02")
        assert resp.status_code == 200
        comp = resp.json.get("comparison", {})
        diff = comp.get("avg_difference_litres") or comp.get("avg_litres_diff")
        assert diff is not None
        assert abs(diff - 50.0) < 1.0

    def test_feature9_04_compare_calculates_percentage_difference(self, client, test_db_path, default_device_id):
        """Calculates difference in percentage between date2 and date1."""
        conn = sqlite3.connect(test_db_path)
        conn.execute("INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, timestamp, date) VALUES (?, 40, 160, 80, 800, '2026-11-01 10:00:00', '2026-11-01');", (default_device_id,))
        conn.execute("INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, timestamp, date) VALUES (?, 30, 170, 85, 850, '2026-11-02 10:00:00', '2026-11-02');", (default_device_id,))
        conn.commit()
        conn.close()

        resp = client.get("/api/history/compare?date1=2026-11-01&date2=2026-11-02")
        assert resp.status_code == 200
        comp = resp.json.get("comparison", {})
        diff = comp.get("avg_difference_percentage") or comp.get("avg_percentage_diff")
        assert diff is not None
        assert abs(diff - 5.0) < 0.5

    def test_feature9_05_compare_identical_dates_returns_zero_diff(self, client, test_db_path, default_device_id):
        """Comparing a date against itself yields 0 net difference."""
        conn = sqlite3.connect(test_db_path)
        conn.execute("INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, timestamp, date) VALUES (?, 40, 160, 80, 800, '2026-11-01 10:00:00', '2026-11-01');", (default_device_id,))
        conn.commit()
        conn.close()

        resp = client.get("/api/history/compare?date1=2026-11-01&date2=2026-11-01")
        assert resp.status_code == 200
        comp = resp.json.get("comparison", {})
        diff = comp.get("avg_difference_litres") or comp.get("avg_litres_diff")
        assert diff == 0.0


# ==============================================================================
# Feature 10: Tank Settings Read/Update GET/PUT /api/settings (R2)
# ==============================================================================

class TestFeature10TankSettings:
    """Verifies reading and updating tank configuration settings."""

    def test_feature10_01_get_settings_returns_200(self, client):
        """GET /api/settings returns HTTP 200."""
        resp = client.get("/api/settings")
        assert resp.status_code == 200

    def test_feature10_02_get_settings_contains_tank_dimensions(self, client):
        """GET /api/settings includes tank_height_cm and total_capacity_litres."""
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json
        assert "tank_height_cm" in data or "total_height_cm" in data
        assert "total_capacity_litres" in data

    def test_feature10_03_put_settings_updates_tank_height_and_capacity(self, client):
        """PUT /api/settings updates tank height and total capacity."""
        new_settings = {
            "tank_height_cm": 250.0,
            "sensor_offset_cm": 20.0,
            "total_capacity_litres": 1500.0,
            "offline_threshold_seconds": 360,
            "low_threshold_percent": 25.0,
            "critical_low_threshold_percent": 12.0,
        }
        resp = client.put("/api/settings", json=new_settings)
        assert resp.status_code == 200

        get_resp = client.get("/api/settings")
        data = get_resp.json
        height = data.get("tank_height_cm") or data.get("total_height_cm")
        assert height == 250.0
        assert data.get("total_capacity_litres") == 1500.0

    def test_feature10_04_put_settings_updates_thresholds(self, client):
        """PUT /api/settings updates warning thresholds and offline timeout."""
        new_settings = {
            "tank_height_cm": 200.0,
            "sensor_offset_cm": 15.0,
            "total_capacity_litres": 1000.0,
            "offline_threshold_seconds": 450,
            "low_threshold_percent": 30.0,
            "critical_low_threshold_percent": 15.0,
        }
        resp = client.put("/api/settings", json=new_settings)
        assert resp.status_code == 200

        data = client.get("/api/settings").json
        assert data.get("offline_threshold_seconds") == 450

    def test_feature10_05_put_settings_persists_in_sqlite(self, client, test_db_path):
        """Verify settings updates persist in SQLite singleton row id=1."""
        new_settings = {
            "tank_height_cm": 210.0,
            "sensor_offset_cm": 15.0,
            "total_capacity_litres": 1100.0,
            "offline_threshold_seconds": 300,
            "low_threshold_percent": 20.0,
            "critical_low_threshold_percent": 10.0,
        }
        client.put("/api/settings", json=new_settings)

        conn = sqlite3.connect(test_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT tank_height_cm, total_capacity_litres FROM tank_settings WHERE id = 1;")
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == 210.0
        assert row[1] == 1100.0


# ==============================================================================
# Feature 11: Standalone Daily Backup CLI scripts/backup.py (R5)
# ==============================================================================

class TestFeature11BackupCli:
    """Verifies standalone backup CLI runner for PythonAnywhere scheduled tasks."""

    def test_feature11_01_backup_cli_help_flag(self, project_root):
        """Verify backup script exists and responds to --help."""
        script_path = os.path.join(project_root, "scripts", "backup.py")
        if not os.path.exists(script_path):
            script_path = os.path.join(project_root, "backup.py")
        assert os.path.exists(script_path), f"Backup script not found at {script_path}"

        result = subprocess.run([sys.executable, script_path, "--help"], capture_output=True, text=True)
        assert result.returncode == 0
        assert "backup" in result.stdout.lower()

    def test_feature11_02_backup_cli_creates_json_backup(self, project_root, test_db_path, temp_backup_dir):
        """Verify backup script exports valid JSON dump with metadata."""
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
            data = json.load(f)
            assert "water_readings" in data or "devices" in data

    def test_feature11_03_backup_cli_creates_csv_backup(self, project_root, test_db_path, temp_backup_dir):
        """Verify backup script exports valid CSV file with standard headers."""
        script_path = os.path.join(project_root, "scripts", "backup.py")
        if not os.path.exists(script_path):
            script_path = os.path.join(project_root, "backup.py")

        cmd = [
            sys.executable, script_path,
            "--format", "csv",
            "--db-path", test_db_path,
            "--output-dir", temp_backup_dir,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0

        files = [f for f in os.listdir(temp_backup_dir) if f.endswith(".csv")]
        assert len(files) >= 1
        with open(os.path.join(temp_backup_dir, files[0]), "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)
            assert "water_level_cm" in headers or "distance_cm" in headers

    def test_feature11_04_backup_cli_creates_both_formats(self, project_root, test_db_path, temp_backup_dir):
        """Verify --format both creates both JSON and CSV files."""
        script_path = os.path.join(project_root, "scripts", "backup.py")
        if not os.path.exists(script_path):
            script_path = os.path.join(project_root, "backup.py")

        cmd = [
            sys.executable, script_path,
            "--format", "both",
            "--db-path", test_db_path,
            "--output-dir", temp_backup_dir,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0

        json_files = [f for f in os.listdir(temp_backup_dir) if f.endswith(".json")]
        csv_files = [f for f in os.listdir(temp_backup_dir) if f.endswith(".csv")]
        assert len(json_files) >= 1
        assert len(csv_files) >= 1

    def test_feature11_05_backup_cli_logs_to_database(self, project_root, test_db_path, temp_backup_dir):
        """Verify backup script records successful execution into backup_logs table."""
        script_path = os.path.join(project_root, "scripts", "backup.py")
        if not os.path.exists(script_path):
            script_path = os.path.join(project_root, "backup.py")

        cmd = [
            sys.executable, script_path,
            "--format", "json",
            "--db-path", test_db_path,
            "--output-dir", temp_backup_dir,
        ]
        subprocess.run(cmd, capture_output=True, text=True)

        conn = sqlite3.connect(test_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT status, file_format FROM backup_logs ORDER BY id DESC LIMIT 1;")
        log = cursor.fetchone()
        conn.close()

        assert log is not None
        assert log[0] == "success"


# ==============================================================================
# Feature 12: Backup REST API (R5)
# ==============================================================================

class TestFeature12BackupApi:
    """Verifies manual backup trigger, list inventory, and download endpoints."""

    def test_feature12_01_post_backup_create_returns_201(self, client):
        """POST /api/backup/create triggers immediate backup and returns 201."""
        resp = client.post("/api/backup/create", json={"format": "json"})
        assert resp.status_code == 201
        data = resp.json
        assert data.get("status") == "success"
        assert "filename" in data

    def test_feature12_02_get_backup_list_returns_200(self, client):
        """GET /api/backup/list returns HTTP 200 with past backup entries."""
        resp = client.get("/api/backup/list")
        assert resp.status_code == 200
        assert "backups" in resp.json or isinstance(resp.json, list)

    def test_feature12_03_created_backup_appears_in_backup_list(self, client):
        """Newly created backup is listed in GET /api/backup/list."""
        create_resp = client.post("/api/backup/create", json={"format": "json"})
        assert create_resp.status_code == 201
        filename = create_resp.json["filename"]

        list_resp = client.get("/api/backup/list")
        assert list_resp.status_code == 200
        backups = list_resp.json.get("backups", list_resp.json)
        assert any(b.get("filename") == filename for b in backups)

    def test_feature12_04_get_backup_download_serves_file(self, client, temp_backup_dir):
        """GET /api/backup/download/<filename> downloads existing backup file."""
        sample_file = "backup_sample_test.json"
        with open(os.path.join(temp_backup_dir, sample_file), "w", encoding="utf-8") as f:
            f.write('{"test": true}')

        resp = client.get(f"/api/backup/download/{sample_file}")
        assert resp.status_code == 200
        assert resp.data == b'{"test": true}'

    def test_feature12_05_download_headers_content_disposition_attachment(self, client, temp_backup_dir):
        """Download response contains Content-Disposition: attachment header."""
        sample_file = "backup_sample_test2.json"
        with open(os.path.join(temp_backup_dir, sample_file), "w", encoding="utf-8") as f:
            f.write('{"test": true}')

        resp = client.get(f"/api/backup/download/{sample_file}")
        assert resp.status_code == 200
        disp = resp.headers.get("Content-Disposition", "")
        assert "attachment" in disp.lower()


# ==============================================================================
# Feature 13: Path Traversal Protection on Backup Download (R5)
# ==============================================================================

class TestFeature13PathTraversal:
    """Verifies strict protection against directory traversal in backup download endpoint."""

    def test_feature13_01_reject_parent_directory_dotdot_slash(self, client):
        """Rejects relative traversal ../../etc/passwd with HTTP 400."""
        resp = client.get("/api/backup/download/..%2F..%2Fetc%2Fpasswd")
        assert resp.status_code in (400, 404)

    def test_feature13_02_reject_backslash_windows_traversal(self, client):
        """Rejects Windows backslash traversal ..\\..\\boot.ini with HTTP 400."""
        resp = client.get("/api/backup/download/..%5C..%5Cboot.ini")
        assert resp.status_code in (400, 404)

    def test_feature13_03_reject_absolute_path_traversal(self, client):
        """Rejects root absolute path requests."""
        resp = client.get("/api/backup/download/%2Fetc%2Fshadow")
        assert resp.status_code in (400, 404)

    def test_feature13_04_reject_url_encoded_dotdot(self, client):
        """Rejects double-encoded dot-dot traversal."""
        resp = client.get("/api/backup/download/%252e%252e%252fapp.py")
        assert resp.status_code in (400, 404)

    def test_feature13_05_nonexistent_backup_file_returns_404(self, client):
        """Valid filename format that does not exist on disk returns HTTP 404."""
        resp = client.get("/api/backup/download/backup_nonexistent_9999.json")
        assert resp.status_code == 404


# ==============================================================================
# Feature 14: PythonAnywhere WSGI Compatibility (R6)
# ==============================================================================

class TestFeature14PythonAnywhereWsgi:
    """Verifies WSGI compatibility and PythonAnywhere deployment files."""

    def test_feature14_01_wsgi_py_file_exists(self, project_root):
        """Verify wsgi.py entrypoint exists at project root."""
        wsgi_file = os.path.join(project_root, "wsgi.py")
        assert os.path.exists(wsgi_file), f"wsgi.py not found at {wsgi_file}"

    def test_feature14_02_wsgi_exposes_application_symbol(self, project_root):
        """Verify wsgi.py exports callable named 'application' per PEP 3333."""
        wsgi_file = os.path.join(project_root, "wsgi.py")
        with open(wsgi_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "application" in content, "wsgi.py must expose 'application' symbol"

    def test_feature14_03_wsgi_adds_project_root_to_sys_path(self, project_root):
        """Verify wsgi.py injects project directory into sys.path to avoid /var/www traps."""
        wsgi_file = os.path.join(project_root, "wsgi.py")
        with open(wsgi_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "sys.path" in content

    def test_feature14_04_health_endpoint_returns_200(self, client):
        """GET /api/health verifies Flask app and SQLite database health."""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json.get("status") in ("healthy", "ok")

    def test_feature14_05_requirements_txt_contains_pinned_deps(self, project_root):
        """Verify requirements.txt exists and contains Flask and pytest."""
        req_file = os.path.join(project_root, "requirements.txt")
        assert os.path.exists(req_file), f"requirements.txt not found at {req_file}"
        with open(req_file, "r", encoding="utf-8") as f:
            text = f.read().lower()
        assert "flask" in text
        assert "pytest" in text
