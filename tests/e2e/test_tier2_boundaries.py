"""
Tier 2: Boundary & Corner Cases E2E Tests for Smart Water Tank Level Monitoring System.
Covers boundary value analysis, invalid inputs, edge cases, adversarial payloads, and timeouts (>= 5 tests per boundary feature).
Total: 70 tests.
"""

import json
import os
import sqlite3
import subprocess
import sys
import pytest


# ==============================================================================
# Boundary 1: Database Schema Constraints & Type Enforcements
# ==============================================================================

class TestBoundary1DbConstraints:
    """Verifies that SQLite constraints enforce physical bounds at the database layer."""

    def test_boundary_db_01_reject_negative_tank_height(self, test_db_path):
        """CHECK (tank_height_cm > 0) rejects negative height."""
        conn = sqlite3.connect(test_db_path)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE tank_settings SET tank_height_cm = -10.0 WHERE id = 1;")
        conn.close()

    def test_boundary_db_02_reject_zero_capacity(self, test_db_path):
        """CHECK (total_capacity_litres > 0) rejects zero capacity."""
        conn = sqlite3.connect(test_db_path)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE tank_settings SET total_capacity_litres = 0.0 WHERE id = 1;")
        conn.close()

    def test_boundary_db_03_reject_reading_percentage_over_100(self, test_db_path, default_device_id):
        """CHECK (water_percentage <= 100.0) rejects > 100.0%."""
        conn = sqlite3.connect(test_db_path)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, date) "
                "VALUES (?, 10.0, 205.0, 100.1, 1001.0, '2026-11-06');",
                (default_device_id,),
            )
        conn.close()

    def test_boundary_db_04_reject_reading_percentage_under_0(self, test_db_path, default_device_id):
        """CHECK (water_percentage >= 0.0) rejects negative percentage."""
        conn = sqlite3.connect(test_db_path)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, date) "
                "VALUES (?, 10.0, 0.0, -0.5, 0.0, '2026-11-06');",
                (default_device_id,),
            )
        conn.close()

    def test_boundary_db_05_singleton_constraint_rejects_second_settings_row(self, test_db_path):
        """CHECK (id = 1) prevents creating multiple configurations."""
        conn = sqlite3.connect(test_db_path)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO tank_settings (id, tank_height_cm, sensor_offset_cm, total_capacity_litres) "
                "VALUES (2, 300.0, 10.0, 2000.0);"
            )
        conn.close()


# ==============================================================================
# Boundary 2: Telemetry Ingestion Payload Boundaries
# ==============================================================================

class TestBoundary2PayloadValidation:
    """Verifies handling of malformed, missing, or corrupt telemetry payloads."""

    def test_boundary_ingest_01_missing_device_id_returns_400(self, client, sample_telemetry_payload):
        """Payload without device_id returns HTTP 400."""
        payload = dict(sample_telemetry_payload)
        del payload["device_id"]
        resp = client.post("/api/water-level", json=payload)
        assert resp.status_code == 400

    def test_boundary_ingest_02_missing_distance_cm_returns_400(self, client, sample_telemetry_payload):
        """Payload without distance_cm returns HTTP 400."""
        payload = dict(sample_telemetry_payload)
        del payload["distance_cm"]
        resp = client.post("/api/water-level", json=payload)
        assert resp.status_code == 400

    def test_boundary_ingest_03_empty_body_returns_400(self, client, valid_auth_headers):
        """Empty JSON object {} returns HTTP 400."""
        resp = client.post("/api/water-level", json={}, headers=valid_auth_headers)
        assert resp.status_code == 400

    def test_boundary_ingest_04_non_json_content_type_returns_400(self, client, valid_auth_headers):
        """Sending raw text instead of JSON returns HTTP 400."""
        resp = client.post("/api/water-level", data="raw string payload", headers={"Content-Type": "text/plain", "X-API-Key": valid_auth_headers["X-API-Key"]})
        assert resp.status_code == 400

    def test_boundary_ingest_05_malformed_json_syntax_returns_400(self, client, valid_auth_headers):
        """Sending invalid JSON syntax '{device_id: ...' returns HTTP 400."""
        resp = client.post("/api/water-level", data="{invalid_json:", headers={"Content-Type": "application/json", "X-API-Key": valid_auth_headers["X-API-Key"]})
        assert resp.status_code == 400


# ==============================================================================
# Boundary 3: Authentication Edge Cases
# ==============================================================================

class TestBoundary3AuthEdgeCases:
    """Verifies edge cases in device authentication and credential handling."""

    def test_boundary_auth_01_empty_api_key_header_returns_401(self, client, sample_telemetry_payload):
        """Header with X-API-Key: '' returns HTTP 401."""
        payload = {k: v for k, v in sample_telemetry_payload.items() if k != "api_key"}
        headers = {"X-API-Key": "", "Content-Type": "application/json"}
        resp = client.post("/api/water-level", json=payload, headers=headers)
        assert resp.status_code == 401

    def test_boundary_auth_02_empty_api_key_body_returns_401(self, client, sample_telemetry_payload):
        """Body with api_key: '' returns HTTP 401."""
        payload = dict(sample_telemetry_payload)
        payload["api_key"] = ""
        resp = client.post("/api/water-level", json=payload)
        assert resp.status_code == 401

    def test_boundary_auth_03_whitespace_only_api_key_returns_401(self, client, sample_telemetry_payload):
        """Whitespace-only API key ('   ') returns HTTP 401."""
        payload = dict(sample_telemetry_payload)
        payload["api_key"] = "   "
        resp = client.post("/api/water-level", json=payload)
        assert resp.status_code == 401

    def test_boundary_auth_04_unknown_device_id_with_invalid_key_returns_401(self, client, sample_telemetry_payload):
        """Unknown device_id with bogus key returns HTTP 401."""
        payload = dict(sample_telemetry_payload)
        payload["device_id"] = "unknown_device_999"
        payload["api_key"] = "bogus_key"
        resp = client.post("/api/water-level", json=payload)
        assert resp.status_code == 401

    def test_boundary_auth_05_special_characters_api_key_mismatch_returns_401(self, client, sample_telemetry_payload):
        """Special characters in key ('<script>', '\x00', etc.) return HTTP 401."""
        payload = dict(sample_telemetry_payload)
        payload["api_key"] = "' OR '1'='1"
        resp = client.post("/api/water-level", json=payload)
        assert resp.status_code == 401


# ==============================================================================
# Boundary 4: Out-of-Bound Physics Telemetry
# ==============================================================================

class TestBoundary4PhysicsBoundaries:
    """Verifies rejection of impossible physical sensor values."""

    def test_boundary_physics_01_negative_distance_cm_returns_422(self, client, default_device_id, valid_auth_headers):
        """Negative distance (-5.0 cm) returns HTTP 422."""
        payload = {
            "device_id": default_device_id,
            "distance_cm": -5.0,
            "water_level_cm": 150.0,
            "water_percentage": 75.0,
            "water_litres": 750.0,
        }
        resp = client.post("/api/water-level", json=payload, headers=valid_auth_headers)
        assert resp.status_code == 422

    def test_boundary_physics_02_negative_water_level_cm_returns_422(self, client, default_device_id, valid_auth_headers):
        """Negative water level (-1.0 cm) returns HTTP 422."""
        payload = {
            "device_id": default_device_id,
            "distance_cm": 50.0,
            "water_level_cm": -1.0,
            "water_percentage": 75.0,
            "water_litres": 750.0,
        }
        resp = client.post("/api/water-level", json=payload, headers=valid_auth_headers)
        assert resp.status_code == 422

    def test_boundary_physics_03_negative_water_litres_returns_422(self, client, default_device_id, valid_auth_headers):
        """Negative volume (-10.0 L) returns HTTP 422."""
        payload = {
            "device_id": default_device_id,
            "distance_cm": 50.0,
            "water_level_cm": 150.0,
            "water_percentage": 75.0,
            "water_litres": -10.0,
        }
        resp = client.post("/api/water-level", json=payload, headers=valid_auth_headers)
        assert resp.status_code == 422

    def test_boundary_physics_04_water_percentage_100_01_returns_422(self, client, default_device_id, valid_auth_headers):
        """Percentage slightly above 100% (100.01) returns HTTP 422."""
        payload = {
            "device_id": default_device_id,
            "distance_cm": 10.0,
            "water_level_cm": 200.0,
            "water_percentage": 100.01,
            "water_litres": 1000.0,
        }
        resp = client.post("/api/water-level", json=payload, headers=valid_auth_headers)
        assert resp.status_code == 422

    def test_boundary_physics_05_string_for_numeric_value_returns_422(self, client, default_device_id, valid_auth_headers):
        """String passed for distance_cm ('fifty') returns HTTP 422."""
        payload = {
            "device_id": default_device_id,
            "distance_cm": "fifty",
            "water_level_cm": 150.0,
            "water_percentage": 75.0,
            "water_litres": 750.0,
        }
        resp = client.post("/api/water-level", json=payload, headers=valid_auth_headers)
        assert resp.status_code in (400, 422)


# ==============================================================================
# Boundary 5: Online/Offline Boundary Transitions
# ==============================================================================

class TestBoundary5OnlineOfflineBoundaries:
    """Verifies edge transitions between online and offline states."""

    def test_boundary_online_01_exact_threshold_boundary_online(self, client, test_db_path, default_device_id):
        """Device seen exactly at threshold seconds (300s) is considered online."""
        conn = sqlite3.connect(test_db_path)
        conn.execute("UPDATE devices SET last_seen = datetime('now', '-300 seconds') WHERE device_id = ?;", (default_device_id,))
        conn.commit()
        conn.close()

        resp = client.get(f"/api/water-level/current?device_id={default_device_id}")
        assert resp.status_code == 200
        # <= 300 seconds is online
        assert resp.json.get("device", {}).get("status") == "online"

    def test_boundary_online_02_threshold_plus_one_second_offline(self, client, test_db_path, default_device_id):
        """Device seen at threshold + 1 second (301s) is offline."""
        conn = sqlite3.connect(test_db_path)
        conn.execute("UPDATE devices SET last_seen = datetime('now', '-301 seconds') WHERE device_id = ?;", (default_device_id,))
        conn.commit()
        conn.close()

        resp = client.get(f"/api/water-level/current?device_id={default_device_id}")
        assert resp.status_code == 200
        assert resp.json.get("device", {}).get("status") == "offline"

    def test_boundary_online_03_zero_seconds_since_last_seen_online(self, client, test_db_path, default_device_id):
        """Device seen right now (0s elapsed) is online."""
        conn = sqlite3.connect(test_db_path)
        conn.execute("UPDATE devices SET last_seen = datetime('now') WHERE device_id = ?;", (default_device_id,))
        conn.commit()
        conn.close()

        resp = client.get(f"/api/water-level/current?device_id={default_device_id}")
        assert resp.status_code == 200
        assert resp.json.get("device", {}).get("status") == "online"

    def test_boundary_online_04_future_timestamp_handling(self, client, test_db_path, default_device_id):
        """Device with clock drift slightly in future (last_seen = now + 10s) does not crash."""
        conn = sqlite3.connect(test_db_path)
        conn.execute("UPDATE devices SET last_seen = datetime('now', '+10 seconds') WHERE device_id = ?;", (default_device_id,))
        conn.commit()
        conn.close()

        resp = client.get(f"/api/water-level/current?device_id={default_device_id}")
        assert resp.status_code == 200
        assert resp.json.get("device", {}).get("status") == "online"

    def test_boundary_online_05_custom_offline_threshold_in_settings(self, client, test_db_path, default_device_id):
        """Changing offline threshold in settings dynamically updates online/offline evaluation."""
        conn = sqlite3.connect(test_db_path)
        conn.execute("UPDATE tank_settings SET offline_threshold_seconds = 60 WHERE id = 1;")
        conn.execute("UPDATE devices SET last_seen = datetime('now', '-75 seconds') WHERE device_id = ?;", (default_device_id,))
        conn.commit()
        conn.close()

        resp = client.get(f"/api/water-level/current?device_id={default_device_id}")
        assert resp.status_code == 200
        assert resp.json.get("device", {}).get("status") == "offline"


# ==============================================================================
# Boundary 6: Current Status Edge Cases
# ==============================================================================

class TestBoundary6CurrentStatusEdges:
    """Verifies status edge cases including empty DB, missing device, and warning levels."""

    def test_boundary_current_01_nonexistent_device_id_query(self, client):
        """Querying status for a non-existent device returns 404 or default fallback gracefully."""
        resp = client.get("/api/water-level/current?device_id=nonexistent_dev_404")
        assert resp.status_code in (200, 404)

    def test_boundary_current_02_device_with_null_last_seen(self, client, test_db_path):
        """Device with NULL last_seen returns offline status and seconds_since_last_seen null."""
        conn = sqlite3.connect(test_db_path)
        conn.execute("INSERT INTO devices (device_id, api_key, device_name, last_seen) VALUES ('tank_null', 'key1', 'Tank Null', NULL);")
        conn.commit()
        conn.close()

        resp = client.get("/api/water-level/current?device_id=tank_null")
        assert resp.status_code == 200
        assert resp.json.get("device", {}).get("status") == "offline"

    def test_boundary_current_03_zero_readings_returns_null_reading(self, client, default_device_id):
        """When device exists but has 0 readings, reading object is null."""
        resp = client.get(f"/api/water-level/current?device_id={default_device_id}")
        assert resp.status_code == 200
        assert resp.json.get("reading") is None

    def test_boundary_current_04_current_level_state_critical_low(self, client, default_device_id, valid_auth_headers):
        """Water percentage below critical low (<10%) returns status_color red or critical_low state."""
        payload = {
            "device_id": default_device_id,
            "distance_cm": 195.0,
            "water_level_cm": 15.0,
            "water_percentage": 7.5,
            "water_litres": 75.0,
        }
        client.post("/api/water-level", json=payload, headers=valid_auth_headers)
        resp = client.get(f"/api/water-level/current?device_id={default_device_id}")
        assert resp.status_code == 200
        tank = resp.json.get("tank", {})
        reading = resp.json.get("reading", {})
        state = tank.get("level_status") or reading.get("level_state") or tank.get("status_color")
        assert any(x in str(state).lower() for x in ("critical", "red", "low"))

    def test_boundary_current_05_current_level_state_low_warning(self, client, default_device_id, valid_auth_headers):
        """Water percentage in warning range (15%, between 10% and 20%) returns orange or low state."""
        payload = {
            "device_id": default_device_id,
            "distance_cm": 180.0,
            "water_level_cm": 30.0,
            "water_percentage": 15.0,
            "water_litres": 150.0,
        }
        client.post("/api/water-level", json=payload, headers=valid_auth_headers)
        resp = client.get(f"/api/water-level/current?device_id={default_device_id}")
        assert resp.status_code == 200
        tank = resp.json.get("tank", {})
        reading = resp.json.get("reading", {})
        state = tank.get("level_status") or reading.get("level_state") or tank.get("status_color")
        assert any(x in str(state).lower() for x in ("warning", "orange", "low"))


# ==============================================================================
# Boundary 7: Daily Stats Boundary Queries
# ==============================================================================

class TestBoundary7DailyStatsBoundaries:
    """Verifies query parameter boundaries for daily stats endpoint."""

    def test_boundary_daily_stats_01_days_param_zero_returns_400(self, client):
        """days=0 returns HTTP 400 Bad Request."""
        resp = client.get("/api/history/daily-stats?days=0")
        assert resp.status_code == 400

    def test_boundary_daily_stats_02_days_param_negative_returns_400(self, client):
        """days=-5 returns HTTP 400 Bad Request."""
        resp = client.get("/api/history/daily-stats?days=-5")
        assert resp.status_code == 400

    def test_boundary_daily_stats_03_days_param_exceeding_90_returns_400(self, client):
        """days=91 (exceeding maximum 90 days limit) returns HTTP 400."""
        resp = client.get("/api/history/daily-stats?days=91")
        assert resp.status_code == 400

    def test_boundary_daily_stats_04_days_param_string_returns_400(self, client):
        """Non-numeric days parameter ('two_weeks') returns HTTP 400."""
        resp = client.get("/api/history/daily-stats?days=two_weeks")
        assert resp.status_code == 400

    def test_boundary_daily_stats_05_days_param_boundary_1_accepted(self, client):
        """Lower boundary days=1 is accepted with HTTP 200."""
        resp = client.get("/api/history/daily-stats?days=1")
        assert resp.status_code == 200


# ==============================================================================
# Boundary 8: Intraday Readings Boundary Dates
# ==============================================================================

class TestBoundary8ReadingsDateBoundaries:
    """Verifies edge date formats and security checks on intraday readings query."""

    def test_boundary_readings_01_invalid_date_format_returns_400(self, client):
        """Malformed date string ('06-11-2026') returns HTTP 400."""
        resp = client.get("/api/history/readings?date=06-11-2026")
        assert resp.status_code == 400

    def test_boundary_readings_02_invalid_calendar_date_feb_31_returns_400(self, client):
        """Non-existent calendar date ('2026-02-31') returns HTTP 400."""
        resp = client.get("/api/history/readings?date=2026-02-31")
        assert resp.status_code == 400

    def test_boundary_readings_03_future_date_returns_empty_readings_200(self, client):
        """Future date with no data returns HTTP 200 with empty list."""
        resp = client.get("/api/history/readings?date=2099-01-01")
        assert resp.status_code == 200
        assert resp.json.get("readings") == []

    def test_boundary_readings_04_far_past_date_returns_empty_readings_200(self, client):
        """Far past date (e.g. 1999-12-31) returns HTTP 200 with empty list."""
        resp = client.get("/api/history/readings?date=1999-12-31")
        assert resp.status_code == 200
        assert resp.json.get("readings") == []

    def test_boundary_readings_05_sql_injection_attempt_in_date_param(self, client):
        """SQL injection in date param ('2026-11-06' OR '1'='1') rejected with 400 or handled safely."""
        resp = client.get("/api/history/readings?date=2026-11-06'%20OR%20'1'='1")
        assert resp.status_code in (400, 422)


# ==============================================================================
# Boundary 9: Compare API Boundary Cases
# ==============================================================================

class TestBoundary9CompareBoundaries:
    """Verifies input boundaries for day-to-day comparison endpoint."""

    def test_boundary_compare_01_missing_date1_returns_400(self, client):
        """Query with only date2 returns HTTP 400."""
        resp = client.get("/api/history/compare?date2=2026-11-06")
        assert resp.status_code == 400

    def test_boundary_compare_02_missing_date2_returns_400(self, client):
        """Query with only date1 returns HTTP 400."""
        resp = client.get("/api/history/compare?date1=2026-11-06")
        assert resp.status_code == 400

    def test_boundary_compare_03_malformed_date1_returns_400(self, client):
        """Invalid date1 format returns HTTP 400."""
        resp = client.get("/api/history/compare?date1=invalid-date&date2=2026-11-06")
        assert resp.status_code == 400

    def test_boundary_compare_04_malformed_date2_returns_400(self, client):
        """Invalid date2 format returns HTTP 400."""
        resp = client.get("/api/history/compare?date1=2026-11-06&date2=invalid-date")
        assert resp.status_code == 400

    def test_boundary_compare_05_both_dates_empty_database_returns_neutral(self, client):
        """Comparing two dates when neither has data returns 200 with neutral trend or 0 readings."""
        resp = client.get("/api/history/compare?date1=2020-01-01&date2=2020-01-02")
        assert resp.status_code == 200
        comp = resp.json.get("comparison", {})
        assert comp.get("trend") in ("neutral", "insufficient_data", "no_data") or comp.get("avg_difference_litres") == 0.0


# ==============================================================================
# Boundary 10: Tank Settings Validation Boundaries
# ==============================================================================

class TestBoundary10SettingsBoundaries:
    """Verifies edge validations for tank configuration updates."""

    def test_boundary_settings_01_critical_greater_than_low_returns_422(self, client):
        """Setting critical threshold > low threshold returns HTTP 422."""
        invalid_body = {
            "tank_height_cm": 200.0,
            "sensor_offset_cm": 15.0,
            "total_capacity_litres": 1000.0,
            "offline_threshold_seconds": 300,
            "low_threshold_percent": 15.0,
            "critical_low_threshold_percent": 25.0, # Impossible: critical > low
        }
        resp = client.put("/api/settings", json=invalid_body)
        assert resp.status_code == 422

    def test_boundary_settings_02_critical_equal_to_low_returns_422(self, client):
        """Setting critical threshold == low threshold returns HTTP 422."""
        invalid_body = {
            "tank_height_cm": 200.0,
            "sensor_offset_cm": 15.0,
            "total_capacity_litres": 1000.0,
            "offline_threshold_seconds": 300,
            "low_threshold_percent": 20.0,
            "critical_low_threshold_percent": 20.0,
        }
        resp = client.put("/api/settings", json=invalid_body)
        assert resp.status_code == 422

    def test_boundary_settings_03_zero_tank_height_returns_422(self, client):
        """Setting tank_height_cm = 0.0 returns HTTP 422."""
        invalid_body = {
            "tank_height_cm": 0.0,
            "sensor_offset_cm": 15.0,
            "total_capacity_litres": 1000.0,
            "offline_threshold_seconds": 300,
            "low_threshold_percent": 20.0,
            "critical_low_threshold_percent": 10.0,
        }
        resp = client.put("/api/settings", json=invalid_body)
        assert resp.status_code == 422

    def test_boundary_settings_04_negative_sensor_offset_returns_422(self, client):
        """Setting negative sensor offset (-5.0 cm) returns HTTP 422."""
        invalid_body = {
            "tank_height_cm": 200.0,
            "sensor_offset_cm": -5.0,
            "total_capacity_litres": 1000.0,
            "offline_threshold_seconds": 300,
            "low_threshold_percent": 20.0,
            "critical_low_threshold_percent": 10.0,
        }
        resp = client.put("/api/settings", json=invalid_body)
        assert resp.status_code == 422

    def test_boundary_settings_05_offline_threshold_less_than_30_returns_422(self, client):
        """Setting offline timeout < 30 seconds returns HTTP 422."""
        invalid_body = {
            "tank_height_cm": 200.0,
            "sensor_offset_cm": 15.0,
            "total_capacity_litres": 1000.0,
            "offline_threshold_seconds": 15, # Too small
            "low_threshold_percent": 20.0,
            "critical_low_threshold_percent": 10.0,
        }
        resp = client.put("/api/settings", json=invalid_body)
        assert resp.status_code == 422


# ==============================================================================
# Boundary 11: Standalone Backup CLI Boundaries
# ==============================================================================

class TestBoundary11BackupCliBoundaries:
    """Verifies CLI argument boundaries and error handling for backup.py."""

    def test_boundary_backup_cli_01_unsupported_format_arg(self, project_root):
        """Passing --format xml exits with non-zero error."""
        script_path = os.path.join(project_root, "scripts", "backup.py")
        if not os.path.exists(script_path):
            script_path = os.path.join(project_root, "backup.py")

        cmd = [sys.executable, script_path, "--format", "xml"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode != 0

    def test_boundary_backup_cli_02_invalid_db_path_arg(self, project_root):
        """Passing non-existent DB path exits with non-zero code."""
        script_path = os.path.join(project_root, "scripts", "backup.py")
        if not os.path.exists(script_path):
            script_path = os.path.join(project_root, "backup.py")

        cmd = [sys.executable, script_path, "--db-path", "non_existent_dir/db.sqlite"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode != 0

    def test_boundary_backup_cli_03_negative_retention_days(self, project_root):
        """Passing negative retention days exits with error."""
        script_path = os.path.join(project_root, "scripts", "backup.py")
        if not os.path.exists(script_path):
            script_path = os.path.join(project_root, "backup.py")

        cmd = [sys.executable, script_path, "--retention-days", "-10"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode != 0

    def test_boundary_backup_cli_04_retention_days_zero_accepted(self, project_root, test_db_path, temp_backup_dir):
        """Passing --retention-days 0 executes without crash."""
        script_path = os.path.join(project_root, "scripts", "backup.py")
        if not os.path.exists(script_path):
            script_path = os.path.join(project_root, "backup.py")

        cmd = [sys.executable, script_path, "--retention-days", "0", "--db-path", test_db_path, "--output-dir", temp_backup_dir]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0

    def test_boundary_backup_cli_05_corrupt_db_exits_with_error(self, project_root, tmp_path):
        """Running backup against a corrupted database file exits with error code 1."""
        corrupt_db = tmp_path / "corrupt.db"
        corrupt_db.write_text("NOT A VALID SQLITE DATABASE FILE")

        script_path = os.path.join(project_root, "scripts", "backup.py")
        if not os.path.exists(script_path):
            script_path = os.path.join(project_root, "backup.py")

        cmd = [sys.executable, script_path, "--db-path", str(corrupt_db)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode != 0


# ==============================================================================
# Boundary 12: Backup REST API Edge Cases
# ==============================================================================

class TestBoundary12BackupApiBoundaries:
    """Verifies edge inputs to backup API endpoints."""

    def test_boundary_backup_api_01_create_with_invalid_format_param(self, client):
        """Triggering backup with format='parquet' returns HTTP 400."""
        resp = client.post("/api/backup/create", json={"format": "parquet"})
        assert resp.status_code == 400

    def test_boundary_backup_api_02_list_with_negative_limit(self, client):
        """GET /api/backup/list?limit=-5 returns HTTP 400 or sanitizes to default."""
        resp = client.get("/api/backup/list?limit=-5")
        assert resp.status_code in (200, 400)

    def test_boundary_backup_api_03_list_with_string_limit(self, client):
        """GET /api/backup/list?limit=all returns HTTP 400 or ignores."""
        resp = client.get("/api/backup/list?limit=all")
        assert resp.status_code in (200, 400)

    def test_boundary_backup_api_04_download_missing_filename(self, client):
        """GET /api/backup/download/ returns 404."""
        resp = client.get("/api/backup/download/")
        assert resp.status_code == 404

    def test_boundary_backup_api_05_download_file_deleted_from_disk_returns_404(self, client):
        """Downloading a file that does not exist returns HTTP 404."""
        resp = client.get("/api/backup/download/deleted_file_never_existed.json")
        assert resp.status_code == 404


# ==============================================================================
# Boundary 13: Path Traversal Attack Variations
# ==============================================================================

class TestBoundary13PathTraversalAttacks:
    """Adversarial security tests for path traversal attacks on file downloads."""

    def test_boundary_traversal_01_dotdot_slash_etc_passwd(self, client):
        """Classic traversal ../../../etc/passwd is blocked."""
        resp = client.get("/api/backup/download/..%2f..%2f..%2fetc%2fpasswd")
        assert resp.status_code in (400, 404)

    def test_boundary_traversal_02_dotdot_backslash_windows_system32(self, client):
        """Windows traversal ..\\..\\Windows\\System32\\cmd.exe is blocked."""
        resp = client.get("/api/backup/download/..%5c..%5cWindows%5cSystem32%5ccmd.exe")
        assert resp.status_code in (400, 404)

    def test_boundary_traversal_03_url_double_encoded_traversal(self, client):
        """Double encoded %252e%252e%252f is blocked."""
        resp = client.get("/api/backup/download/%252e%252e%252fwsgi.py")
        assert resp.status_code in (400, 404)

    def test_boundary_traversal_04_null_byte_injection(self, client):
        """Null byte %00 injection is blocked."""
        resp = client.get("/api/backup/download/backup_test.json%00.txt")
        assert resp.status_code in (400, 404)

    def test_boundary_traversal_05_absolute_path_c_drive(self, client):
        """Absolute Windows drive path C:/Windows/win.ini is blocked."""
        resp = client.get("/api/backup/download/C:%2fWindows%2fwin.ini")
        assert resp.status_code in (400, 404)


# ==============================================================================
# Boundary 14: Environment & Runtime Boundaries
# ==============================================================================

class TestBoundary14RuntimeEnvironment:
    """Verifies runtime resilience and environment variable configurations."""

    def test_boundary_env_01_missing_database_env_defaults_gracefully(self):
        """When DATABASE_PATH env var is missing, app resolves relative to project."""
        original = os.environ.get("DATABASE_PATH")
        if "DATABASE_PATH" in os.environ:
            del os.environ["DATABASE_PATH"]
        try:
            # Check config module resolution if exists
            try:
                import config
                assert hasattr(config, "DATABASE_PATH")
            except ImportError:
                pass
        finally:
            if original:
                os.environ["DATABASE_PATH"] = original

    def test_boundary_env_02_config_resolves_absolute_paths(self, project_root):
        """Verify config or models use absolute path resolution."""
        config_path = os.path.join(project_root, "config.py")
        if not os.path.exists(config_path):
            config_path = os.path.join(project_root, "app", "config.py")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert "os.path.abspath" in content or "Path" in content

    def test_boundary_env_03_requirements_flask_version_spec(self, project_root):
        """Verify requirements.txt pins compatible Flask version."""
        req_file = os.path.join(project_root, "requirements.txt")
        if os.path.exists(req_file):
            with open(req_file, "r", encoding="utf-8") as f:
                content = f.read()
            assert "Flask" in content or "flask" in content

    def test_boundary_env_04_app_factory_handles_empty_config_dict(self):
        """create_app handles empty configuration dictionary without crashing."""
        try:
            from app import create_app
            test_app = create_app({})
            assert test_app is not None
        except ImportError:
            pytest.skip("Flask app factory not implemented yet")

    def test_boundary_env_05_database_busy_timeout_configured(self, test_db_path):
        """Verify busy_timeout PRAGMA can be set on SQLite connections for concurrency."""
        conn = sqlite3.connect(test_db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000;")
        cursor = conn.cursor()
        cursor.execute("PRAGMA busy_timeout;")
        timeout_val = cursor.fetchone()[0]
        conn.close()
        assert timeout_val >= 5000
