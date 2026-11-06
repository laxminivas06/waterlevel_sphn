"""
tests/adversarial/test_m1_challenger2_persistence.py - Adversarial Challenger 2 Test Suite

Empirically probes:
1. Data persistence across multiple re-initializations (init_db without --reset must NOT erase existing telemetry).
2. Timestamp and date boundary cases (leap years, daylight saving time shifts, empty/None dates, dates beyond 15 days, epoch edge cases).
3. Foreign key cascading deletion behavior (deleting a device deletes its water_readings).
4. In-memory SQLite connection isolation vs disk database sharing & WAL snapshot isolation.
5. Extreme boundary values, singleton violations, and SQL injection defense.
"""

from datetime import datetime, timedelta
import math
import os
import sqlite3
import sys
import tempfile
import pytest

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.database import create_connection, get_db, get_db_context, resolve_db_path
from app.models import (
    get_device, verify_api_key, authenticate_device, update_last_seen, get_all_devices, register_device,
    get_tank_settings, update_tank_settings,
    insert_water_reading, get_latest_reading, get_readings_by_date, get_daily_stats, compare_dates, get_today_summary,
    insert_backup_log, get_backup_logs, get_backup_by_filename, get_total_readings_count
)
from scripts.init_db import init_db, apply_schema, seed_database, reset_database


# ==============================================================================
# SECTION 1: Persistence Across Re-initializations and Server Restarts
# ==============================================================================

class TestPersistenceAcrossReinitAndRestarts:
    """Verifies that running init_db without --reset does NOT erase telemetry or custom entities."""

    def test_reinit_without_reset_preserves_telemetry(self, tmp_path):
        db_path = str(tmp_path / "persist_test.db")
        # Step 1: Initial creation and seeding
        assert init_db(db_path, reset=False, seed=True, quiet=True) == 0

        # Step 2: Insert telemetry records and custom device
        conn = create_connection(db_path)
        register_device("custom_sensor_1", "custom_key_1", "Custom Sensor 1", db=conn)
        
        reading1 = {
            "device_id": "custom_sensor_1",
            "distance_cm": 50.0,
            "water_level_cm": 150.0,
            "water_percentage": 75.0,
            "water_litres": 750.0,
            "timestamp": "2026-11-06 10:00:00",
            "date": "2026-11-06"
        }
        reading2 = {
            "device_id": "esp32_tank_01",
            "distance_cm": 30.0,
            "water_level_cm": 170.0,
            "water_percentage": 85.0,
            "water_litres": 850.0,
            "timestamp": "2026-11-06 11:00:00",
            "date": "2026-11-06"
        }
        insert_water_reading(reading1, db=conn)
        insert_water_reading(reading2, db=conn)
        conn.close()

        # Step 3: Run init_db WITHOUT --reset (simulating re-deployment or container restart)
        assert init_db(db_path, reset=False, seed=True, quiet=True) == 0

        # Step 4: Verify data is completely intact
        conn2 = create_connection(db_path)
        dev = get_device("custom_sensor_1", db=conn2)
        assert dev is not None, "Custom device must survive re-initialization"
        assert dev["device_name"] == "Custom Sensor 1"

        readings = get_readings_by_date("2026-11-06", db=conn2)
        assert len(readings) == 2, f"Expected 2 readings to survive re-init, got {len(readings)}"
        assert readings[0]["water_percentage"] == 75.0
        assert readings[1]["water_percentage"] == 85.0
        assert get_total_readings_count(db=conn2) == 2

        conn2.close()

    def test_repeated_reinit_idempotence(self, tmp_path):
        """Repeated sequential init_db invocations must not corrupt or multiply data."""
        db_path = str(tmp_path / "repeated_reinit.db")
        assert init_db(db_path, reset=False, seed=True, quiet=True) == 0

        conn = create_connection(db_path)
        insert_water_reading({
            "device_id": "esp32_tank_01",
            "distance_cm": 40.0,
            "water_level_cm": 160.0,
            "water_percentage": 80.0,
            "water_litres": 800.0,
            "timestamp": "2026-11-06 12:00:00",
            "date": "2026-11-06"
        }, db=conn)
        conn.close()

        # Execute init_db 5 times sequentially without --reset
        for i in range(5):
            res = init_db(db_path, reset=False, seed=True, quiet=True)
            assert res == 0, f"Init iteration {i} failed"

        conn2 = create_connection(db_path)
        assert get_total_readings_count(db=conn2) == 1
        settings = get_tank_settings(db=conn2)
        assert settings["total_capacity_litres"] == 1000.0
        conn2.close()

    def test_simulated_process_restart_with_wal(self, tmp_path):
        """Simulate closing all connections, shutting down process, and reopening DB."""
        db_path = str(tmp_path / "wal_restart.db")
        init_db(db_path, reset=False, seed=True, quiet=True)

        # Connection batch 1
        conn1 = create_connection(db_path)
        for i in range(10):
            insert_water_reading({
                "device_id": "esp32_tank_01",
                "distance_cm": float(20 + i),
                "water_level_cm": float(180 - i),
                "water_percentage": float(90 - i),
                "water_litres": float(900 - i * 10),
                "timestamp": f"2026-11-06 12:{i:02d}:00",
                "date": "2026-11-06"
            }, db=conn1)
        conn1.close()

        # Connection batch 2 (simulated restart after all connections closed)
        conn2 = create_connection(db_path)
        assert get_total_readings_count(db=conn2) == 10
        latest = get_latest_reading(db=conn2)
        assert latest["water_percentage"] == 81.0  # 90 - 9
        conn2.close()

    def test_reset_flag_cleanly_resets_schema_and_telemetry(self, tmp_path):
        """Passing --reset drops and recreates everything cleanly."""
        db_path = str(tmp_path / "reset_test.db")
        init_db(db_path, reset=False, seed=True, quiet=True)

        conn = create_connection(db_path)
        insert_water_reading({
            "device_id": "esp32_tank_01",
            "distance_cm": 40.0,
            "water_level_cm": 160.0,
            "water_percentage": 80.0,
            "water_litres": 800.0,
            "timestamp": "2026-11-06 12:00:00",
            "date": "2026-11-06"
        }, db=conn)
        assert get_total_readings_count(db=conn) == 1
        conn.close()

        # Reset database
        assert init_db(db_path, reset=True, seed=True, quiet=True) == 0

        conn2 = create_connection(db_path)
        # Seed exists, but previous reading is wiped
        assert get_total_readings_count(db=conn2) == 0
        assert get_device("esp32_tank_01", db=conn2) is not None
        conn2.close()


# ==============================================================================
# SECTION 2: Timestamp and Date Boundary Cases
# ==============================================================================

class TestTimestampAndDateBoundaries:
    """Probes leap years, timezones, malformed dates, 15-day cutoffs, and epoch extremes."""

    @pytest.fixture
    def test_db(self, tmp_path):
        db_path = str(tmp_path / "date_test.db")
        init_db(db_path, reset=True, seed=True, quiet=True)
        conn = create_connection(db_path)
        yield conn
        conn.close()

    def test_leap_year_february_29(self, test_db):
        """Leap year dates (2024-02-29, 2028-02-29, 2000-02-29) must be accepted."""
        leap_dates = ["2024-02-29", "2028-02-29", "2000-02-29"]
        for d in leap_dates:
            res = insert_water_reading({
                "device_id": "esp32_tank_01",
                "distance_cm": 50.0,
                "water_level_cm": 150.0,
                "water_percentage": 75.0,
                "water_litres": 750.0,
                "timestamp": f"{d} 12:00:00",
                "date": d
            }, db=test_db)
            assert res["status"] == "success"

            readings = get_readings_by_date(d, db=test_db)
            assert len(readings) == 1
            assert readings[0]["date"] == d

    def test_iso8601_timestamps_and_dst(self, test_db):
        """ISO8601 formats with T, Z, and offsets must be handled properly."""
        iso_timestamps = [
            ("2026-11-06T14:40:00Z", "2026-11-06"),
            ("2026-03-29T02:00:00+01:00", "2026-03-29"),
            ("2026-10-25T03:00:00+02:00", "2026-10-25"),
            ("2026-11-06 23:59:59.999", "2026-11-06"),
        ]
        for ts, expected_date in iso_timestamps:
            res = insert_water_reading({
                "device_id": "esp32_tank_01",
                "distance_cm": 45.0,
                "water_level_cm": 155.0,
                "water_percentage": 77.5,
                "water_litres": 775.0,
                "timestamp": ts,
                "date": expected_date
            }, db=test_db)
            assert res["status"] == "success"

        readings = get_readings_by_date("2026-11-06", db=test_db)
        assert len(readings) == 2

    def test_empty_or_none_dates_and_timestamps(self, test_db):
        """When date/timestamp is empty or omitted, models must fallback gracefully or reject invalid DDL."""
        # Case A: None date and timestamp -> automatically populated with current timestamp
        res1 = insert_water_reading({
            "device_id": "esp32_tank_01",
            "distance_cm": 50.0,
            "water_level_cm": 150.0,
            "water_percentage": 75.0,
            "water_litres": 750.0,
            "timestamp": None,
            "date": None
        }, db=test_db)
        assert res1["status"] == "success"
        assert len(res1["date"]) == 10

        # Case B: Empty string date "" -> fallback to timestamp[:10]
        res2 = insert_water_reading({
            "device_id": "esp32_tank_01",
            "distance_cm": 50.0,
            "water_level_cm": 150.0,
            "water_percentage": 75.0,
            "water_litres": 750.0,
            "timestamp": "2026-11-06 14:00:00",
            "date": ""
        }, db=test_db)
        assert res2["status"] == "success"
        assert res2["date"] == "2026-11-06"

    def test_malformed_date_format_rejected_by_check_constraint(self, test_db):
        """Schema check constraint (length(date) = 10 AND date LIKE '____-__-__') must reject invalid dates."""
        invalid_dates = [
            "2026/11/06",   # Slash instead of dash
            "06-11-2026",   # DD-MM-YYYY format
            "2026-1-1",     # 8 chars
            "2026-11-006",  # 11 chars
            "invalid-dt",   # Not date
            "",             # Empty (if raw insert bypasses python fallback)
        ]

        for bad_date in invalid_dates:
            # Direct SQL execution to test DDL constraint resilience
            with pytest.raises(sqlite3.IntegrityError):
                test_db.execute(
                    """
                    INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, timestamp, date)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("esp32_tank_01", 50.0, 150.0, 75.0, 750.0, "2026-11-06 12:00:00", bad_date)
                )

    def test_dates_beyond_15_days_filtering(self, test_db):
        """Verify that get_daily_stats strictly respects the 15-day retention/aggregation boundary."""
        today = datetime.now()
        dates_to_insert = [
            (today - timedelta(days=20)).strftime("%Y-%m-%d"), # 20 days ago (OUTSIDE 15-day window)
            (today - timedelta(days=16)).strftime("%Y-%m-%d"), # 16 days ago (OUTSIDE 15-day window)
            (today - timedelta(days=14)).strftime("%Y-%m-%d"), # 14 days ago (INSIDE 15-day window)
            (today - timedelta(days=7)).strftime("%Y-%m-%d"),  # 7 days ago (INSIDE 15-day window)
            (today - timedelta(days=1)).strftime("%Y-%m-%d"),  # yesterday (INSIDE)
            today.strftime("%Y-%m-%d"),                        # today (INSIDE)
        ]

        for d in dates_to_insert:
            insert_water_reading({
                "device_id": "esp32_tank_01",
                "distance_cm": 50.0,
                "water_level_cm": 150.0,
                "water_percentage": 75.0,
                "water_litres": 750.0,
                "timestamp": f"{d} 12:00:00",
                "date": d
            }, db=test_db)

        # Query past 15 days
        stats_15 = get_daily_stats(days=15, db=test_db)
        stat_dates_15 = {s["date"] for s in stats_15}

        # Verify: 14 days ago, 7 days ago, yesterday, today are present
        assert (today - timedelta(days=14)).strftime("%Y-%m-%d") in stat_dates_15
        assert (today - timedelta(days=7)).strftime("%Y-%m-%d") in stat_dates_15
        assert (today - timedelta(days=1)).strftime("%Y-%m-%d") in stat_dates_15
        assert today.strftime("%Y-%m-%d") in stat_dates_15

        # Verify: 16 and 20 days ago are NOT present in 15-day stats
        assert (today - timedelta(days=16)).strftime("%Y-%m-%d") not in stat_dates_15
        assert (today - timedelta(days=20)).strftime("%Y-%m-%d") not in stat_dates_15

        # Query past 30 days - 20 days ago should now be included
        stats_30 = get_daily_stats(days=30, db=test_db)
        stat_dates_30 = {s["date"] for s in stats_30}
        assert (today - timedelta(days=20)).strftime("%Y-%m-%d") in stat_dates_30

        # But get_readings_by_date CAN still retrieve the 20-day-old record specifically (retention intact)
        old_date = (today - timedelta(days=20)).strftime("%Y-%m-%d")
        old_readings = get_readings_by_date(old_date, db=test_db)
        assert len(old_readings) == 1

    def test_epoch_extremes(self, test_db):
        """Tests boundaries: Unix epoch (1970-01-01), Y2038 (2038-01-19), year 9999."""
        extreme_dates = [
            ("1970-01-01", "1970-01-01 00:00:00"),
            ("2038-01-19", "2038-01-19 03:14:07"),
            ("9999-12-31", "9999-12-31 23:59:59")
        ]
        for d, ts in extreme_dates:
            res = insert_water_reading({
                "device_id": "esp32_tank_01",
                "distance_cm": 50.0,
                "water_level_cm": 150.0,
                "water_percentage": 75.0,
                "water_litres": 750.0,
                "timestamp": ts,
                "date": d
            }, db=test_db)
            assert res["status"] == "success"

            readings = get_readings_by_date(d, db=test_db)
            assert len(readings) == 1
            assert readings[0]["timestamp"] == ts


# ==============================================================================
# SECTION 3: Foreign Key Cascading Deletion Behavior
# ==============================================================================

class TestForeignKeyCascadingDeletion:
    """Verifies that deleting a device deletes all associated telemetry records via ON DELETE CASCADE."""

    @pytest.fixture
    def fk_db(self, tmp_path):
        db_path = str(tmp_path / "fk_cascade.db")
        init_db(db_path, reset=True, seed=True, quiet=True)
        conn = create_connection(db_path)
        yield conn
        conn.close()

    def test_device_deletion_cascades_to_water_readings(self, fk_db):
        # Register a second device
        register_device("device_to_delete", "del_key_123", "Deletable Sensor", db=fk_db)

        # Insert readings for both devices
        for dev_id in ["esp32_tank_01", "device_to_delete"]:
            for i in range(3):
                insert_water_reading({
                    "device_id": dev_id,
                    "distance_cm": 50.0 + i,
                    "water_level_cm": 150.0 - i,
                    "water_percentage": 75.0 - i,
                    "water_litres": 750.0 - i * 10,
                    "timestamp": f"2026-11-06 10:{i:02d}:00",
                    "date": "2026-11-06"
                }, db=fk_db)

        # Confirm total readings = 6
        assert get_total_readings_count(db=fk_db) == 6

        # Delete device_to_delete
        cursor = fk_db.cursor()
        cursor.execute("DELETE FROM devices WHERE device_id = ?", ("device_to_delete",))
        fk_db.commit()

        # Check: device_to_delete is gone
        assert get_device("device_to_delete", db=fk_db) is None

        # Check: all 3 readings for device_to_delete were cascade-deleted!
        cur = fk_db.cursor()
        cur.execute("SELECT COUNT(*) FROM water_readings WHERE device_id = 'device_to_delete'")
        assert cur.fetchone()[0] == 0, "Water readings for deleted device must be cascade-deleted"

        # Check: esp32_tank_01 readings are completely preserved!
        cur.execute("SELECT COUNT(*) FROM water_readings WHERE device_id = 'esp32_tank_01'")
        assert cur.fetchone()[0] == 3, "Readings for surviving device must remain untouched"
        assert get_total_readings_count(db=fk_db) == 3

    def test_pragma_foreign_keys_enforced_on_all_connections(self, tmp_path):
        """Verifies that create_connection() always activates foreign keys."""
        db_path = str(tmp_path / "pragma_fk.db")
        init_db(db_path, reset=True, seed=True, quiet=True)

        conn = create_connection(db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys;")
        fk_enabled = cur.fetchone()[0]
        assert fk_enabled == 1, "PRAGMA foreign_keys must be 1 on create_connection"

        # Direct INSERT with non-existent foreign key MUST fail
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, timestamp, date)
                VALUES ('ghost_device', 50.0, 150.0, 75.0, 750.0, '2026-11-06 12:00:00', '2026-11-06')
                """
            )
        conn.close()

    def test_device_deactivation_does_not_cascade_delete(self, fk_db):
        """Deactivating a device (is_active = 0) must retain all its historical telemetry."""
        register_device("device_retire", "retire_key", "Retiring Device", is_active=1, db=fk_db)
        insert_water_reading({
            "device_id": "device_retire",
            "distance_cm": 50.0,
            "water_level_cm": 150.0,
            "water_percentage": 75.0,
            "water_litres": 750.0,
            "timestamp": "2026-11-06 12:00:00",
            "date": "2026-11-06"
        }, db=fk_db)

        # Deactivate
        fk_db.execute("UPDATE devices SET is_active = 0 WHERE device_id = 'device_retire'")
        fk_db.commit()

        # Telemetry must still be accessible
        cur = fk_db.cursor()
        cur.execute("SELECT COUNT(*) FROM water_readings WHERE device_id = 'device_retire'")
        assert cur.fetchone()[0] == 1


# ==============================================================================
# SECTION 4: In-Memory SQLite Isolation vs Disk Database & Concurrency
# ==============================================================================

class TestMemoryVsDiskIsolation:
    """Verifies isolation of :memory: connections vs shared disk DB and WAL concurrency."""

    def test_in_memory_connections_are_completely_isolated(self):
        """Two separate :memory: connections do not share state."""
        conn1 = create_connection(":memory:")
        apply_schema(conn1)
        seed_database(conn1)

        # conn1 has devices table
        cur1 = conn1.cursor()
        cur1.execute("SELECT COUNT(*) FROM devices")
        assert cur1.fetchone()[0] == 1

        # conn2 connects to :memory: (independent instance)
        conn2 = create_connection(":memory:")
        cur2 = conn2.cursor()
        # conn2 has no tables yet
        cur2.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur2.fetchall()]
        assert "devices" not in tables, "Separate :memory: connections must be completely isolated"

        conn1.close()
        conn2.close()

    def test_disk_connections_share_state(self, tmp_path):
        """Two connections to the same disk DB file see the same committed state."""
        db_path = str(tmp_path / "shared_disk.db")
        init_db(db_path, reset=True, seed=True, quiet=True)

        conn_writer = create_connection(db_path)
        conn_reader = create_connection(db_path)

        insert_water_reading({
            "device_id": "esp32_tank_01",
            "distance_cm": 50.0,
            "water_level_cm": 150.0,
            "water_percentage": 75.0,
            "water_litres": 750.0,
            "timestamp": "2026-11-06 12:00:00",
            "date": "2026-11-06"
        }, db=conn_writer)

        # Reader immediately sees writer's committed change
        cur = conn_reader.cursor()
        cur.execute("SELECT COUNT(*) FROM water_readings")
        assert cur.fetchone()[0] == 1

        conn_writer.close()
        conn_reader.close()

    def test_wal_snapshot_isolation_concurrent_read_write(self, tmp_path):
        """In WAL mode, reader is not blocked by an uncommitted write transaction."""
        db_path = str(tmp_path / "wal_concurrency.db")
        init_db(db_path, reset=True, seed=True, quiet=True)

        conn_writer = create_connection(db_path)
        conn_reader = create_connection(db_path)

        # Seed initial reading
        insert_water_reading({
            "device_id": "esp32_tank_01",
            "distance_cm": 60.0,
            "water_level_cm": 140.0,
            "water_percentage": 70.0,
            "water_litres": 700.0,
            "timestamp": "2026-11-06 10:00:00",
            "date": "2026-11-06"
        }, db=conn_writer)

        # Start uncommitted write transaction on conn_writer
        cursor_w = conn_writer.cursor()
        cursor_w.execute(
            """
            INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, timestamp, date)
            VALUES ('esp32_tank_01', 40.0, 160.0, 80.0, 800.0, '2026-11-06 11:00:00', '2026-11-06')
            """
        )
        # Note: conn_writer has NOT committed yet!

        # conn_reader performs non-blocking read under WAL snapshot isolation
        cursor_r = conn_reader.cursor()
        cursor_r.execute("SELECT COUNT(*) FROM water_readings")
        # Under WAL snapshot isolation, reader sees only 1 committed row without blocking
        count = cursor_r.fetchone()[0]
        assert count == 1, "WAL snapshot isolation should see 1 committed row before writer commit"

        # Commit writer
        conn_writer.commit()

        # Reader now sees 2
        cursor_r.execute("SELECT COUNT(*) FROM water_readings")
        assert cursor_r.fetchone()[0] == 2

        conn_writer.close()
        conn_reader.close()


# ==============================================================================
# SECTION 5: Hostile Inputs, Singleton Violation, and SQL Injection Probes
# ==============================================================================

class TestHostileInputsAndConstraints:
    """Probes boundary values, singleton constraints, and SQL injection strings."""

    @pytest.fixture
    def db(self, tmp_path):
        db_path = str(tmp_path / "hostile.db")
        init_db(db_path, reset=True, seed=True, quiet=True)
        conn = create_connection(db_path)
        yield conn
        conn.close()

    def test_singleton_tank_settings_constraint(self, db):
        """Attempting to insert a row with id != 1 must fail the CHECK(id = 1) constraint."""
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                """
                INSERT INTO tank_settings (id, tank_height_cm, total_capacity_litres)
                VALUES (2, 300.0, 2000.0)
                """
            )

    def test_tank_settings_negative_values_rejected(self, db):
        """Updating tank settings with negative height or capacity must fail."""
        with pytest.raises(ValueError):
            update_tank_settings({"tank_height_cm": 0.0}, db=db)

        with pytest.raises(ValueError):
            update_tank_settings({"total_capacity_litres": -100.0}, db=db)

        with pytest.raises(ValueError):
            update_tank_settings({"offline_threshold_seconds": 5}, db=db)  # min 10s

    def test_telemetry_out_of_range_rejected(self, db):
        """Physical measurements out of valid bounds must fail."""
        # Percentage > 100.0
        with pytest.raises(ValueError):
            insert_water_reading({
                "device_id": "esp32_tank_01",
                "distance_cm": 10.0,
                "water_level_cm": 190.0,
                "water_percentage": 100.01,
                "water_litres": 1000.1,
                "date": "2026-11-06"
            }, db=db)

        # Negative distance
        with pytest.raises(ValueError):
            insert_water_reading({
                "device_id": "esp32_tank_01",
                "distance_cm": -0.1,
                "water_level_cm": 190.0,
                "water_percentage": 95.0,
                "water_litres": 950.0,
                "date": "2026-11-06"
            }, db=db)

        # Empty device ID
        with pytest.raises(ValueError):
            insert_water_reading({
                "device_id": "   ",
                "distance_cm": 10.0,
                "water_level_cm": 190.0,
                "water_percentage": 95.0,
                "water_litres": 950.0,
                "date": "2026-11-06"
            }, db=db)

    def test_sql_injection_defense_in_device_id_and_api_key(self, db):
        """Attacking DAL with SQL injection strings must be safely escaped by parameterized queries."""
        sql_injections = [
            "' OR '1'='1",
            "esp32_tank_01'; DROP TABLE devices; --",
            "'; DELETE FROM water_readings; --",
            "' UNION SELECT * FROM devices --"
        ]

        for payload in sql_injections:
            # Querying device with injection payload
            dev = get_device(payload, db=db)
            assert dev is None, f"Injection '{payload}' must return None, not breach table"

            # Authenticating with injection payload
            ok, err, d = authenticate_device(payload, payload, db=db)
            assert ok is False

            # Verify devices table and water_readings still exist and are healthy
            cur = db.cursor()
            cur.execute("SELECT COUNT(*) FROM devices")
            assert cur.fetchone()[0] >= 1
