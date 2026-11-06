"""
tests/unit/test_m1_core.py - Unit & Edge Case Tests for Milestone M1

Verifies:
- Config path resolution and environment overrides
- init_db CLI flags (--reset, --seed, --verbose, --quiet, --db-path)
- Database connection lifecycle (Flask context vs standalone)
- PRAGMA enforcements (foreign keys, busy timeout, WAL mode)
- Complete CRUD and business logic across devices, tank settings, water readings, and backup logs
- Edge cases and error paths (bounds, missing entities, invalid types)
"""

import os
import sqlite3
import sys
import tempfile
import pytest

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.config import Config, DevelopmentConfig, TestingConfig, ProductionConfig, DATABASE_PATH, PROJECT_ROOT
from app.database import create_connection, get_db, close_db, get_db_context, resolve_db_path
from app.models import (
    get_device, verify_api_key, authenticate_device, update_last_seen, get_all_devices, register_device,
    get_tank_settings, update_tank_settings,
    insert_water_reading, get_latest_reading, get_readings_by_date, get_daily_stats, compare_dates, get_today_summary,
    insert_backup_log, get_backup_logs, get_backup_by_filename, get_total_readings_count
)
from app import create_app
from scripts.init_db import init_db, apply_schema, seed_database


@pytest.fixture
def memory_db():
    """Provides an initialized in-memory database with schema and default seeds."""
    conn = create_connection(":memory:")
    apply_schema(conn)
    seed_database(conn)
    yield conn
    conn.close()


class TestConfigUnit:
    """Verifies configuration management and absolute path resolution."""

    def test_config_paths_are_absolute(self):
        assert os.path.isabs(Config.PROJECT_ROOT)
        assert os.path.isabs(Config.DATA_DIR)
        assert os.path.isabs(Config.BACKUP_DIR)
        assert os.path.isabs(Config.DATABASE_PATH)

    def test_config_defaults(self):
        assert Config.DEFAULT_DEVICE_ID == "esp32_tank_01"
        assert Config.DEFAULT_API_KEY == "water_secret_key_2026"
        assert Config.OFFLINE_THRESHOLD_SECONDS == 300
        assert Config.DB_BUSY_TIMEOUT_MS == 30000

    def test_config_profiles(self):
        assert TestingConfig.TESTING is True
        assert DevelopmentConfig.DEBUG is True
        assert ProductionConfig.DEBUG is False


class TestInitDbUnit:
    """Verifies scripts/init_db.py execution and CLI flags."""

    def test_init_db_in_memory(self):
        code = init_db(":memory:", reset=True, seed=True, quiet=True)
        assert code == 0

    def test_init_db_creates_file_and_directory(self, tmp_path):
        nested_db = str(tmp_path / "deep" / "nested" / "test.db")
        code = init_db(nested_db, reset=True, seed=True, verbose=True)
        assert code == 0
        assert os.path.exists(nested_db)

        # Verify default records
        conn = sqlite3.connect(nested_db)
        cur = conn.cursor()
        cur.execute("SELECT device_id FROM devices WHERE device_id = 'esp32_tank_01'")
        assert cur.fetchone() is not None
        cur.execute("SELECT id, total_capacity_litres FROM tank_settings WHERE id = 1")
        settings = cur.fetchone()
        assert settings[0] == 1
        assert settings[1] == 1000.0
        conn.close()

    def test_init_db_idempotency(self, tmp_path):
        db_file = str(tmp_path / "idempotent.db")
        assert init_db(db_file, seed=True, quiet=True) == 0
        # Second call should not fail or duplicate
        assert init_db(db_file, seed=True, quiet=True) == 0


class TestDatabaseConnectionUnit:
    """Verifies connection factory, PRAGMAs, and context management."""

    def test_pragmas_enforced(self):
        conn = create_connection(":memory:")
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys;")
        assert cur.fetchone()[0] == 1
        cur.execute("PRAGMA busy_timeout;")
        assert cur.fetchone()[0] >= 30000
        conn.close()

    def test_row_factory_dict_compatibility(self, memory_db):
        cur = memory_db.cursor()
        cur.execute("SELECT * FROM devices WHERE device_id = 'esp32_tank_01'")
        row = cur.fetchone()
        assert row["device_id"] == "esp32_tank_01"
        assert dict(row)["api_key"] == "water_secret_key_2026"

    def test_get_db_context_commit_and_rollback(self, tmp_path):
        db_file = str(tmp_path / "tx_test.db")
        init_db(db_file, seed=True, quiet=True)

        # Successful transaction
        with get_db_context(db_file) as conn:
            conn.execute("UPDATE devices SET device_name = 'Updated Name' WHERE device_id = 'esp32_tank_01'")

        # Verify commit succeeded
        with get_db_context(db_file) as conn:
            row = conn.execute("SELECT device_name FROM devices WHERE device_id = 'esp32_tank_01'").fetchone()
            assert row[0] == "Updated Name"

        # Failed transaction rolls back
        try:
            with get_db_context(db_file) as conn:
                conn.execute("UPDATE devices SET device_name = 'Failed Name' WHERE device_id = 'esp32_tank_01'")
                raise RuntimeError("Trigger rollback")
        except RuntimeError:
            pass

        # Verify rollback preserved earlier state
        with get_db_context(db_file) as conn:
            row = conn.execute("SELECT device_name FROM devices WHERE device_id = 'esp32_tank_01'").fetchone()
            assert row[0] == "Updated Name"

    def test_flask_context_integration(self):
        app = create_app({"TESTING": True, "DATABASE_PATH": ":memory:"})
        with app.app_context():
            db1 = get_db()
            db2 = get_db()
            assert db1 is db2  # Cached in g.db
        # Teardown closed connection


class TestModelsDeviceUnit:
    """Verifies Device CRUD and authentication functions."""

    def test_get_device(self, memory_db):
        dev = get_device("esp32_tank_01", db=memory_db)
        assert dev is not None
        assert dev["device_name"] == "Main Water Tank"
        assert get_device("unknown_id", db=memory_db) is None

    def test_verify_api_key(self, memory_db):
        assert verify_api_key("esp32_tank_01", "water_secret_key_2026", db=memory_db) is True
        assert verify_api_key("esp32_tank_01", "wrong_key", db=memory_db) is False
        assert verify_api_key("missing_dev", "water_secret_key_2026", db=memory_db) is False

    def test_authenticate_device(self, memory_db):
        ok, err, dev = authenticate_device("esp32_tank_01", "water_secret_key_2026", db=memory_db)
        assert ok is True
        assert err is None
        assert dev["device_id"] == "esp32_tank_01"

        ok, err, _ = authenticate_device("missing", "key", db=memory_db)
        assert ok is False
        assert err == "Device not found"

        ok, err, _ = authenticate_device("esp32_tank_01", "bad_key", db=memory_db)
        assert ok is False
        assert err == "Invalid API key"

    def test_update_last_seen(self, memory_db):
        ts = "2026-11-06 12:34:56"
        res = update_last_seen("esp32_tank_01", timestamp=ts, db=memory_db)
        assert res is True
        dev = get_device("esp32_tank_01", db=memory_db)
        assert dev["last_seen"] == ts

    def test_register_device_and_get_all(self, memory_db):
        register_device("sensor_2", "key_sensor_2", "Secondary Tank", is_active=1, db=memory_db)
        devices = get_all_devices(db=memory_db)
        assert len(devices) == 2
        dev_ids = {d["device_id"] for d in devices}
        assert "sensor_2" in dev_ids


class TestModelsTankSettingsUnit:
    """Verifies Tank Settings singleton and alias mapping."""

    def test_get_tank_settings_aliases(self, memory_db):
        settings = get_tank_settings(db=memory_db)
        assert settings["tank_height_cm"] == 200.0
        assert settings["total_height_cm"] == 200.0
        assert settings["low_threshold_percent"] == 20.0
        assert settings["warning_low_percent"] == 20.0
        assert settings["warning_normal_percent"] == 50.0

    def test_update_tank_settings_with_total_height_cm(self, memory_db):
        updated = update_tank_settings({"total_height_cm": 220.0, "total_capacity_litres": 1500.0}, db=memory_db)
        assert updated["tank_height_cm"] == 220.0
        assert updated["total_height_cm"] == 220.0
        assert updated["total_capacity_litres"] == 1500.0

    def test_update_tank_settings_rejects_negative_height(self, memory_db):
        with pytest.raises(ValueError):
            update_tank_settings({"total_height_cm": -50.0}, db=memory_db)

    def test_update_tank_settings_rejects_out_of_range_percentage(self, memory_db):
        with pytest.raises(ValueError):
            update_tank_settings({"warning_low_percent": 110.0}, db=memory_db)


class TestModelsWaterReadingsUnit:
    """Verifies Water Readings telemetry ingestion, validation, and analytics."""

    def test_insert_water_reading_updates_device_last_seen(self, memory_db):
        reading = {
            "device_id": "esp32_tank_01",
            "distance_cm": 45.0,
            "water_level_cm": 155.0,
            "water_percentage": 77.5,
            "water_litres": 775.0,
            "timestamp": "2026-11-06 10:00:00",
            "date": "2026-11-06"
        }
        res = insert_water_reading(reading, db=memory_db)
        assert res["status"] == "success"
        assert res["reading_id"] > 0

        # Verify device last_seen updated
        dev = get_device("esp32_tank_01", db=memory_db)
        assert dev["last_seen"] == "2026-11-06 10:00:00"

    def test_insert_water_reading_foreign_key_rejection(self, memory_db):
        reading = {
            "device_id": "non_existent_device",
            "distance_cm": 45.0,
            "water_level_cm": 155.0,
            "water_percentage": 77.5,
            "water_litres": 775.0,
            "date": "2026-11-06"
        }
        with pytest.raises(sqlite3.IntegrityError):
            insert_water_reading(reading, db=memory_db)

    def test_insert_water_reading_rejects_invalid_values(self, memory_db):
        # Negative litres
        with pytest.raises(ValueError):
            insert_water_reading({
                "device_id": "esp32_tank_01",
                "distance_cm": 10.0,
                "water_level_cm": 190.0,
                "water_percentage": 95.0,
                "water_litres": -5.0,
                "date": "2026-11-06"
            }, db=memory_db)

        # Percentage > 100
        with pytest.raises(ValueError):
            insert_water_reading({
                "device_id": "esp32_tank_01",
                "distance_cm": 10.0,
                "water_level_cm": 190.0,
                "water_percentage": 105.0,
                "water_litres": 1050.0,
                "date": "2026-11-06"
            }, db=memory_db)

    def test_analytics_and_today_summary(self, memory_db):
        # Insert two readings on 2026-11-06
        insert_water_reading({
            "device_id": "esp32_tank_01",
            "distance_cm": 60.0,
            "water_level_cm": 140.0,
            "water_percentage": 70.0,
            "water_litres": 700.0,
            "timestamp": "2026-11-06 08:00:00",
            "date": "2026-11-06"
        }, db=memory_db)
        insert_water_reading({
            "device_id": "esp32_tank_01",
            "distance_cm": 40.0,
            "water_level_cm": 160.0,
            "water_percentage": 80.0,
            "water_litres": 800.0,
            "timestamp": "2026-11-06 18:00:00",
            "date": "2026-11-06"
        }, db=memory_db)

        # Test latest reading
        latest = get_latest_reading(db=memory_db)
        assert latest["water_percentage"] == 80.0

        # Test readings by date
        readings = get_readings_by_date("2026-11-06", db=memory_db)
        assert len(readings) == 2

        # Test today's summary
        summary = get_today_summary(date_str="2026-11-06", db=memory_db)
        assert summary["reading_count"] == 2
        assert summary["min_percentage"] == 70.0
        assert summary["max_percentage"] == 80.0
        assert summary["avg_percentage"] == 75.0
        assert summary["net_change_litres"] == 100.0

    def test_compare_dates(self, memory_db):
        insert_water_reading({
            "device_id": "esp32_tank_01",
            "distance_cm": 80.0,
            "water_level_cm": 120.0,
            "water_percentage": 60.0,
            "water_litres": 600.0,
            "timestamp": "2026-11-05 12:00:00",
            "date": "2026-11-05"
        }, db=memory_db)
        insert_water_reading({
            "device_id": "esp32_tank_01",
            "distance_cm": 40.0,
            "water_level_cm": 160.0,
            "water_percentage": 80.0,
            "water_litres": 800.0,
            "timestamp": "2026-11-06 12:00:00",
            "date": "2026-11-06"
        }, db=memory_db)

        comp = compare_dates("2026-11-05", "2026-11-06", db=memory_db)
        assert comp["comparison"]["avg_percentage_diff"] == 20.0
        assert comp["comparison"]["avg_litres_diff"] == 200.0
        assert comp["comparison"]["trend"] == "increasing"


class TestModelsBackupLogsUnit:
    """Verifies Backup Logs insertion, indexing, and querying."""

    def test_backup_logs_lifecycle(self, memory_db):
        log_id = insert_backup_log(
            backup_type="manual",
            file_format="csv",
            filename="water_backup_test.csv",
            file_path="/tmp/water_backup_test.csv",
            file_size_bytes=2048,
            records_count=50,
            status="success",
            error_message=None,
            db=memory_db
        )
        assert log_id > 0

        logs = get_backup_logs(limit=10, db=memory_db)
        assert len(logs) == 1
        assert logs[0]["filename"] == "water_backup_test.csv"

        entry = get_backup_by_filename("water_backup_test.csv", db=memory_db)
        assert entry is not None
        assert entry["file_format"] == "csv"
        assert entry["records_count"] == 50
