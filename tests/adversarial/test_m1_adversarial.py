"""
tests/adversarial/test_m1_adversarial.py - Empirical Adversarial Challenge Suite for M1

Rigorous adversarial challenge and stress testing covering:
1. High concurrency read/write stress testing SQLite WAL mode with multiple threads.
2. Constraint violation attacks (negative litres, out-of-bounds percentage, missing FKs, non-singleton IDs, malformed dates, invalid enums).
3. SQL injection attempts against DAL models across all query surfaces.
4. Database file lock contention simulation, WAL non-blocking readers, timeout behavior, and crash/rollback recovery.
"""

import concurrent.futures
import math
import os
import sqlite3
import sys
import threading
import time
import pytest

# Ensure project root is importable
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.database import create_connection, get_db_context
from app.models import (
    get_device, verify_api_key, authenticate_device, update_last_seen, get_all_devices, register_device,
    get_tank_settings, update_tank_settings,
    insert_water_reading, get_latest_reading, get_readings_by_date, get_daily_stats, compare_dates, get_today_summary,
    insert_backup_log, get_backup_logs, get_backup_by_filename, get_total_readings_count
)
from scripts.init_db import init_db


@pytest.fixture
def file_db(tmp_path):
    """Provides a fresh, initialized file-backed SQLite database in WAL mode."""
    db_file = str(tmp_path / "wal_stress.db")
    code = init_db(db_file, reset=True, seed=True, quiet=True)
    assert code == 0, "Failed to initialize test database"
    return db_file


# ==============================================================================
# Challenge 1: High Concurrency Read/Write WAL Mode Stress
# ==============================================================================

class TestWalConcurrencyStress:
    """Stress tests SQLite WAL mode under heavy multi-threaded concurrent workloads."""

    def test_concurrent_writers_and_readers(self, file_db):
        """
        Simulate 10 concurrent writer threads and 5 concurrent reader threads.
        - Writers insert 50 readings each (500 total).
        - Readers continuously query latest readings, daily stats, and settings.
        - Verifies WAL mode eliminates 'database is locked' errors and guarantees 0 lost writes.
        """
        num_writers = 10
        writes_per_thread = 50
        num_readers = 5
        read_iterations = 60
        stop_readers = threading.Event()
        errors = []

        def writer_task(worker_id):
            try:
                for i in range(writes_per_thread):
                    reading = {
                        "device_id": "esp32_tank_01",
                        "distance_cm": float(20.0 + (i % 30)),
                        "water_level_cm": float(180.0 - (i % 30)),
                        "water_percentage": float(50.0 + (i % 40)),
                        "water_litres": float(500.0 + (i % 40) * 10),
                        "timestamp": f"2026-11-06 12:{worker_id:02d}:{i:02d}",
                        "date": "2026-11-06"
                    }
                    with get_db_context(file_db) as conn:
                        insert_water_reading(reading, db=conn)
            except Exception as e:
                errors.append(f"Writer-{worker_id} error: {e}")

        def reader_task(worker_id):
            try:
                iters = 0
                while not stop_readers.is_set() and iters < read_iterations:
                    iters += 1
                    with get_db_context(file_db) as conn:
                        _ = get_latest_reading(db=conn)
                        _ = get_tank_settings(db=conn)
                        _ = get_today_summary(date_str="2026-11-06", db=conn)
                        _ = get_daily_stats(days=7, db=conn)
                    time.sleep(0.005)
            except Exception as e:
                errors.append(f"Reader-{worker_id} error: {e}")

        # Start readers and writers concurrently
        threads = []
        for r in range(num_readers):
            t = threading.Thread(target=reader_task, args=(r,), name=f"Reader-{r}")
            threads.append(t)

        for w in range(num_writers):
            t = threading.Thread(target=writer_task, args=(w,), name=f"Writer-{w}")
            threads.append(t)

        for t in threads:
            t.start()

        # Wait for all writers to finish
        for t in threads:
            if "Writer" in t.name:
                t.join(timeout=30.0)

        # Signal readers to stop and wait
        stop_readers.set()
        for t in threads:
            if "Reader" in t.name:
                t.join(timeout=10.0)

        assert not errors, f"Concurrency errors occurred: {errors}"

        # Verify all 500 writes are accounted for in the database
        with get_db_context(file_db) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM water_readings")
            count = cur.fetchone()[0]
            assert count == num_writers * writes_per_thread, (
                f"Lost updates detected: expected {num_writers * writes_per_thread}, got {count}"
            )

            # Integrity check
            cur.execute("PRAGMA integrity_check;")
            integrity = cur.fetchone()[0]
            assert integrity == "ok", f"Integrity check failed: {integrity}"

    def test_concurrent_device_registration_and_settings_updates(self, file_db):
        """Simulate concurrent device registration and tank settings updates."""
        errors = []

        def register_task(idx):
            try:
                with get_db_context(file_db) as conn:
                    register_device(
                        device_id=f"esp32_concurrent_{idx}",
                        api_key=f"key_{idx}",
                        device_name=f"Tank Device {idx}",
                        is_active=1,
                        db=conn
                    )
            except Exception as e:
                errors.append(f"Register-{idx} error: {e}")

        def settings_task(idx):
            try:
                with get_db_context(file_db) as conn:
                    update_tank_settings(
                        {"total_capacity_litres": 1000.0 + (idx * 10)},
                        db=conn
                    )
            except Exception as e:
                errors.append(f"Settings-{idx} error: {e}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(register_task, i) for i in range(20)]
            futures += [executor.submit(settings_task, i) for i in range(20)]
            concurrent.futures.wait(futures)

        assert not errors, f"Errors in concurrent registration/settings: {errors}"

        with get_db_context(file_db) as conn:
            devices = get_all_devices(db=conn)
            # 1 initial seed device + 20 concurrent devices = 21
            assert len(devices) == 21


# ==============================================================================
# Challenge 2: Constraint Violation Attacks
# ==============================================================================

class TestConstraintViolationAttacks:
    """Stress tests physical domain constraints, schema checks, and foreign keys."""

    def test_attack_negative_litres(self, file_db):
        """Negative litres must be rejected at both DAL model layer and SQLite CHECK constraint."""
        for bad_litres in [-0.0001, -1.0, -999.0, -1e6]:
            with pytest.raises((ValueError, sqlite3.IntegrityError)):
                with get_db_context(file_db) as conn:
                    insert_water_reading({
                        "device_id": "esp32_tank_01",
                        "distance_cm": 20.0,
                        "water_level_cm": 180.0,
                        "water_percentage": 90.0,
                        "water_litres": bad_litres,
                        "date": "2026-11-06"
                    }, db=conn)

            # Direct SQL bypass attempt
            with pytest.raises(sqlite3.IntegrityError):
                with get_db_context(file_db) as conn:
                    conn.execute(
                        "INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, date) "
                        "VALUES ('esp32_tank_01', 20.0, 180.0, 90.0, ?, '2026-11-06')",
                        (bad_litres,)
                    )

    def test_attack_out_of_bounds_percentage(self, file_db):
        """Water percentage < 0.0 or > 100.0 must be rejected."""
        for bad_pct in [-0.01, -100.0, 100.0001, 105.0, 999.0]:
            with pytest.raises((ValueError, sqlite3.IntegrityError)):
                with get_db_context(file_db) as conn:
                    insert_water_reading({
                        "device_id": "esp32_tank_01",
                        "distance_cm": 20.0,
                        "water_level_cm": 180.0,
                        "water_percentage": bad_pct,
                        "water_litres": 900.0,
                        "date": "2026-11-06"
                    }, db=conn)

            # Direct SQL bypass attempt
            with pytest.raises(sqlite3.IntegrityError):
                with get_db_context(file_db) as conn:
                    conn.execute(
                        "INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, date) "
                        "VALUES ('esp32_tank_01', 20.0, 180.0, ?, 900.0, '2026-11-06')",
                        (bad_pct,)
                    )

    def test_attack_negative_distance_and_level(self, file_db):
        """Negative distance_cm or water_level_cm must be rejected."""
        with pytest.raises((ValueError, sqlite3.IntegrityError)):
            with get_db_context(file_db) as conn:
                insert_water_reading({
                    "device_id": "esp32_tank_01",
                    "distance_cm": -5.0,
                    "water_level_cm": 180.0,
                    "water_percentage": 90.0,
                    "water_litres": 900.0,
                    "date": "2026-11-06"
                }, db=conn)

        with pytest.raises((ValueError, sqlite3.IntegrityError)):
            with get_db_context(file_db) as conn:
                insert_water_reading({
                    "device_id": "esp32_tank_01",
                    "distance_cm": 20.0,
                    "water_level_cm": -1.0,
                    "water_percentage": 90.0,
                    "water_litres": 900.0,
                    "date": "2026-11-06"
                }, db=conn)

    def test_attack_missing_foreign_key(self, file_db):
        """Inserting a reading with a non-existent device_id must be rejected by foreign key constraint."""
        for ghost_id in ["ghost_sensor_999", "non_existent", "unknown_esp"]:
            with pytest.raises(sqlite3.IntegrityError):
                with get_db_context(file_db) as conn:
                    insert_water_reading({
                        "device_id": ghost_id,
                        "distance_cm": 20.0,
                        "water_level_cm": 180.0,
                        "water_percentage": 90.0,
                        "water_litres": 900.0,
                        "date": "2026-11-06"
                    }, db=conn)

            # Direct SQL insertion bypass attempt
            with pytest.raises(sqlite3.IntegrityError):
                with get_db_context(file_db) as conn:
                    conn.execute(
                        "INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, date) "
                        "VALUES (?, 20.0, 180.0, 90.0, 900.0, '2026-11-06')",
                        (ghost_id,)
                    )

    def test_attack_non_singleton_tank_settings(self, file_db):
        """tank_settings is strictly a singleton table (id=1); any other id must be rejected."""
        for bad_id in [0, 2, 3, -1, 999]:
            with pytest.raises(sqlite3.IntegrityError):
                with get_db_context(file_db) as conn:
                    conn.execute(
                        "INSERT INTO tank_settings (id, tank_height_cm, total_capacity_litres) "
                        "VALUES (?, 200.0, 1000.0)",
                        (bad_id,)
                    )

    def test_attack_tank_settings_physical_boundaries(self, file_db):
        """Updating tank settings with invalid physics must fail."""
        invalid_payloads = [
            {"tank_height_cm": -10.0},
            {"total_height_cm": 0.0},
            {"sensor_offset_cm": -1.0},
            {"total_capacity_litres": -500.0},
            {"total_capacity_litres": 0.0},
            {"offline_threshold_seconds": 5},   # < 10 threshold
            {"warning_low_percent": -5.0},
            {"warning_low_percent": 105.0},
            {"warning_normal_percent": -1.0},
            {"warning_normal_percent": 101.0},
        ]
        for payload in invalid_payloads:
            with pytest.raises((ValueError, sqlite3.IntegrityError)):
                with get_db_context(file_db) as conn:
                    update_tank_settings(payload, db=conn)

    def test_attack_malformed_reading_dates(self, file_db):
        """Reading date must strictly match YYYY-MM-DD pattern."""
        malformed_dates = [
            "2026-1-1",
            "26-11-06",
            "not-a-date",
            "2026/11/06",
            "2026.11.06",
            "2026-11-06 12:00:00"
        ]
        for bad_date in malformed_dates:
            with pytest.raises(sqlite3.IntegrityError):
                with get_db_context(file_db) as conn:
                    conn.execute(
                        "INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, date) "
                        "VALUES ('esp32_tank_01', 20.0, 180.0, 90.0, 900.0, ?)",
                        (bad_date,)
                    )

    def test_attack_invalid_devices_constraints(self, file_db):
        """Devices table must reject blank device_id, blank api_key, and invalid is_active flags."""
        with pytest.raises(sqlite3.IntegrityError):
            with get_db_context(file_db) as conn:
                conn.execute("INSERT INTO devices (device_id, device_name, api_key) VALUES ('', 'Name', 'key')")

        with pytest.raises(sqlite3.IntegrityError):
            with get_db_context(file_db) as conn:
                conn.execute("INSERT INTO devices (device_id, device_name, api_key) VALUES ('dev_1', '', 'key')")

        with pytest.raises(sqlite3.IntegrityError):
            with get_db_context(file_db) as conn:
                conn.execute("INSERT INTO devices (device_id, device_name, api_key) VALUES ('dev_1', 'Name', '')")

        with pytest.raises(sqlite3.IntegrityError):
            with get_db_context(file_db) as conn:
                conn.execute("INSERT INTO devices (device_id, device_name, api_key, is_active) VALUES ('dev_2', 'Name', 'k', 5)")

    def test_attack_invalid_backup_logs_constraints(self, file_db):
        """Backup logs must enforce check constraints on type, format, size, count, and status."""
        invalid_backup_statements = [
            # Blank filename
            "INSERT INTO backup_logs (filename, file_path, backup_type, status) VALUES ('', '/path', 'manual', 'success')",
            # Blank file_path
            "INSERT INTO backup_logs (filename, file_path, backup_type, status) VALUES ('file.json', '', 'manual', 'success')",
            # Invalid backup_type
            "INSERT INTO backup_logs (filename, file_path, backup_type, status) VALUES ('f.json', '/p', 'unsupported_type', 'success')",
            # Invalid file_format
            "INSERT INTO backup_logs (filename, file_path, backup_type, file_format, status) VALUES ('f.json', '/p', 'manual', 'xml', 'success')",
            # Negative file_size_bytes
            "INSERT INTO backup_logs (filename, file_path, backup_type, file_size_bytes, status) VALUES ('f.json', '/p', 'manual', -10, 'success')",
            # Negative records_count
            "INSERT INTO backup_logs (filename, file_path, backup_type, records_count, status) VALUES ('f.json', '/p', 'manual', -1, 'success')",
            # Invalid status
            "INSERT INTO backup_logs (filename, file_path, backup_type, status) VALUES ('f.json', '/p', 'manual', 'pending')",
        ]
        for sql in invalid_backup_statements:
            with pytest.raises(sqlite3.IntegrityError):
                with get_db_context(file_db) as conn:
                    conn.execute(sql)


# ==============================================================================
# Challenge 3: SQL Injection Attacks Against DAL Models
# ==============================================================================

class TestSqlInjectionAttacks:
    """Attacks all DAL query methods using SQL injection vectors."""

    INJECTION_PAYLOADS = [
        "' OR '1'='1",
        "' OR 1=1 --",
        "'; DROP TABLE water_readings; --",
        "'; DROP TABLE devices; --",
        "' UNION SELECT 1, 'hacked_device', 'hacked_key', 'now', 'now', 1 --",
        "admin'--",
        "' OR ''='",
        "1' OR '1' = '1' /*",
        "1; UPDATE tank_settings SET tank_height_cm = 99999 WHERE id=1; --"
    ]

    def test_sql_injection_device_queries(self, file_db):
        """Verify get_device, verify_api_key, and authenticate_device resist SQL injection."""
        for payload in self.INJECTION_PAYLOADS:
            with get_db_context(file_db) as conn:
                # get_device should return None (payload treated as literal string)
                dev = get_device(payload, db=conn)
                assert dev is None, f"get_device leaked data on payload: {payload}"

                # verify_api_key should return False
                assert verify_api_key(payload, payload, db=conn) is False
                assert verify_api_key("esp32_tank_01", payload, db=conn) is False

                # authenticate_device should return False
                auth_ok, _, _ = authenticate_device(payload, payload, db=conn)
                assert auth_ok is False
                auth_ok2, _, _ = authenticate_device("esp32_tank_01", payload, db=conn)
                assert auth_ok2 is False

        # Verify devices table was NOT dropped
        with get_db_context(file_db) as conn:
            assert get_device("esp32_tank_01", db=conn) is not None

    def test_sql_injection_device_updates(self, file_db):
        """Verify update_last_seen and register_device resist SQL injection."""
        for payload in self.INJECTION_PAYLOADS:
            with get_db_context(file_db) as conn:
                # update_last_seen with injection device_id
                res = update_last_seen(payload, timestamp="2026-11-06 12:00:00", db=conn)
                assert res is False

                # update_last_seen with injection timestamp
                res2 = update_last_seen("esp32_tank_01", timestamp=payload, db=conn)
                assert res2 is True  # Parameterized insert stores payload literally as text

        # Verify tank_settings was NOT modified by injection
        with get_db_context(file_db) as conn:
            settings = get_tank_settings(db=conn)
            assert settings["tank_height_cm"] == 200.0

    def test_sql_injection_telemetry_reads(self, file_db):
        """Verify get_latest_reading and get_readings_by_date resist SQL injection."""
        for payload in self.INJECTION_PAYLOADS:
            with get_db_context(file_db) as conn:
                # get_latest_reading with injection device_id
                reading = get_latest_reading(device_id=payload, db=conn)
                assert reading is None

                # get_readings_by_date with injection date_str
                readings = get_readings_by_date(date_str=payload, db=conn)
                assert isinstance(readings, list)
                assert len(readings) == 0

                # get_readings_by_date with injection device_id
                readings2 = get_readings_by_date(date_str="2026-11-06", device_id=payload, db=conn)
                assert len(readings2) == 0

        # Verify water_readings table still exists
        with get_db_context(file_db) as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='water_readings'")
            assert cur.fetchone() is not None

    def test_sql_injection_analytics_queries(self, file_db):
        """Verify get_daily_stats, compare_dates, and get_today_summary resist SQL injection."""
        for payload in self.INJECTION_PAYLOADS:
            with get_db_context(file_db) as conn:
                # get_daily_stats with injection device_id
                stats = get_daily_stats(days=15, device_id=payload, db=conn)
                assert isinstance(stats, list)
                assert len(stats) == 0

                # compare_dates with injection date strings
                comp = compare_dates(payload, "2026-11-06", db=conn)
                assert comp["date1"]["readings_count"] == 0

                # get_today_summary with injection device_id
                summ = get_today_summary(device_id=payload, db=conn)
                assert summ["reading_count"] == 0

    def test_sql_injection_backup_queries(self, file_db):
        """Verify backup DAL methods resist SQL injection."""
        for payload in self.INJECTION_PAYLOADS:
            with get_db_context(file_db) as conn:
                log = get_backup_by_filename(payload, db=conn)
                assert log is None


# ==============================================================================
# Challenge 4: File Lock Contention Simulation & Crash Recovery
# ==============================================================================

class TestLockContentionAndCrashRecovery:
    """Simulates active lock contention, concurrent readers during writes, and crash rollback."""

    def test_wal_readers_not_blocked_by_active_write_transaction(self, file_db):
        """
        Critical WAL guarantee: A long-running write transaction must NOT block concurrent readers.
        - Connection 1 opens an EXCLUSIVE transaction and modifies data without committing immediately.
        - Connection 2 immediately executes SELECT queries on the same tables.
        - Under WAL mode, Connection 2 reads cleanly without delay or lock errors.
        """
        write_conn = create_connection(file_db)
        read_completed = threading.Event()
        read_result = {}
        read_error = []

        try:
            # Step 1: Writer begins immediate transaction and writes a reading
            write_cur = write_conn.cursor()
            write_cur.execute("BEGIN IMMEDIATE;")
            write_cur.execute(
                "INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, date) "
                "VALUES ('esp32_tank_01', 40.0, 160.0, 80.0, 800.0, '2026-11-06')"
            )

            # Step 2: Reader runs concurrently in its own thread while write transaction is uncommitted
            def reader_thread():
                try:
                    start_time = time.time()
                    read_conn = create_connection(file_db)
                    try:
                        # Reader queries tank settings and latest reading
                        cur = read_conn.cursor()
                        cur.execute("SELECT * FROM tank_settings WHERE id = 1")
                        row = cur.fetchone()
                        read_result["tank_height_cm"] = row["tank_height_cm"]

                        # Reader queries readings (should see committed snapshot, not uncommitted write)
                        cur.execute("SELECT COUNT(*) FROM water_readings")
                        read_result["readings_count"] = cur.fetchone()[0]
                        read_result["duration"] = time.time() - start_time
                        read_completed.set()
                    finally:
                        read_conn.close()
                except Exception as e:
                    read_error.append(str(e))
                    read_completed.set()

            t = threading.Thread(target=reader_thread)
            t.start()
            t.join(timeout=3.0)

            assert read_completed.is_set(), "Reader was blocked by active write transaction!"
            assert not read_error, f"Reader encountered error: {read_error}"
            assert read_result["tank_height_cm"] == 200.0
            # Read isolation: reader does not see uncommitted write
            assert read_result["readings_count"] == 0
            # Concurrency performance: reader finished immediately (<0.5s), not waiting for busy_timeout
            assert read_result["duration"] < 1.0

            # Commit the write transaction
            write_conn.commit()

            # Now reader sees the committed record
            with get_db_context(file_db) as verify_conn:
                cur = verify_conn.cursor()
                cur.execute("SELECT COUNT(*) FROM water_readings")
                assert cur.fetchone()[0] == 1

        finally:
            write_conn.close()

    def test_busy_timeout_writer_contention_and_resolution(self, file_db):
        """
        Verifies busy_timeout (30000ms):
        When Writer A holds an exclusive lock for 300ms, Writer B waits and succeeds once Writer A commits.
        """
        writer_a = create_connection(file_db)
        b_finished = threading.Event()
        b_error = []

        try:
            # Writer A acquires immediate lock
            cur_a = writer_a.cursor()
            cur_a.execute("BEGIN IMMEDIATE;")
            cur_a.execute("UPDATE devices SET device_name = 'Locked Name' WHERE device_id = 'esp32_tank_01'")

            def writer_b_action():
                try:
                    writer_b = create_connection(file_db)
                    try:
                        # Writer B attempts write transaction — will wait on busy_timeout
                        cur_b = writer_b.cursor()
                        cur_b.execute("BEGIN IMMEDIATE;")
                        cur_b.execute("UPDATE devices SET device_name = 'Writer B Name' WHERE device_id = 'esp32_tank_01'")
                        writer_b.commit()
                        b_finished.set()
                    finally:
                        writer_b.close()
                except Exception as e:
                    b_error.append(str(e))
                    b_finished.set()

            tb = threading.Thread(target=writer_b_action)
            tb.start()

            # Hold lock for 300ms then commit
            time.sleep(0.3)
            writer_a.commit()

            # Writer B should now complete successfully
            tb.join(timeout=5.0)

            assert b_finished.is_set(), "Writer B timed out or failed to complete"
            assert not b_error, f"Writer B raised error: {b_error}"

            # Verify Writer B's update took effect
            cur_check = writer_a.cursor()
            cur_check.execute("SELECT device_name FROM devices WHERE device_id = 'esp32_tank_01'")
            assert cur_check.fetchone()[0] == "Writer B Name"

        finally:
            writer_a.close()

    def test_transaction_rollback_on_failure_preserves_consistency(self, file_db):
        """Simulate a failure/crash mid-transaction and verify atomic rollback."""
        with get_db_context(file_db) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM water_readings")
            initial_count = cur.fetchone()[0]

        # Attempt transaction that crashes after partial insert
        try:
            with get_db_context(file_db) as conn:
                conn.execute(
                    "INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, date) "
                    "VALUES ('esp32_tank_01', 30.0, 170.0, 85.0, 850.0, '2026-11-06')"
                )
                # Simulated crash/unhandled exception
                raise RuntimeError("Simulated process crash mid-transaction")
        except RuntimeError:
            pass

        # Verify rollback was clean and count is unchanged
        with get_db_context(file_db) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM water_readings")
            assert cur.fetchone()[0] == initial_count

            # Integrity check
            cur.execute("PRAGMA integrity_check;")
            assert cur.fetchone()[0] == "ok"


# ==============================================================================
# Challenge 5: Special Payloads, Unicode, & Data Volume Stress
# ==============================================================================

class TestSpecialPayloadsAndUnicode:
    """Verifies robustness against non-ASCII, Unicode emojis, XSS payloads, and large data blobs."""

    def test_unicode_and_emojis_in_device_and_readings(self, file_db):
        """Device names and metadata containing non-ASCII / Unicode characters."""
        unicode_name = "Water Tank 🌊 (Hauptwassertank #1 💧) - Español & 中文"
        unicode_device_id = "esp32_ökologisch_01"

        with get_db_context(file_db) as conn:
            reg = register_device(
                device_id=unicode_device_id,
                api_key="key_üñîçødé_2026",
                device_name=unicode_name,
                db=conn
            )
            assert reg["device_name"] == unicode_name

            # Retrieve device
            dev = get_device(unicode_device_id, db=conn)
            assert dev is not None
            assert dev["device_name"] == unicode_name

            # Insert reading with unicode
            res = insert_water_reading({
                "device_id": unicode_device_id,
                "distance_cm": 35.5,
                "water_level_cm": 164.5,
                "water_percentage": 82.25,
                "water_litres": 822.5,
                "date": "2026-11-06",
                "raw_reading_json": '{"sensor": "JSN-SR04T 🌊", "note": "Überwachung läuft"}'
            }, db=conn)
            assert res["status"] == "success"

            latest = get_latest_reading(device_id=unicode_device_id, db=conn)
            assert "Überwachung" in latest["raw_reading_json"]

    def test_xss_and_html_injection_stored_literally(self, file_db):
        """Stored XSS vectors must be stored verbatim without executing or breaking SQL."""
        xss_payload = "<script>alert('pwned')</script><img src=x onerror=alert(1)>"
        with get_db_context(file_db) as conn:
            register_device(
                device_id="xss_device_01",
                api_key="xss_key_123",
                device_name=xss_payload,
                db=conn
            )
            dev = get_device("xss_device_01", db=conn)
            assert dev["device_name"] == xss_payload

    def test_large_raw_json_blob_storage(self, file_db):
        """Stress test storing a large ~150KB JSON payload in raw_reading_json and verify exact retrieval."""
        large_dict = {"reading_id": "large_test", "samples": [float(i) for i in range(20000)]}
        large_json = str(large_dict)

        with get_db_context(file_db) as conn:
            res = insert_water_reading({
                "device_id": "esp32_tank_01",
                "distance_cm": 50.0,
                "water_level_cm": 150.0,
                "water_percentage": 75.0,
                "water_litres": 750.0,
                "date": "2026-11-06",
                "raw_reading_json": large_json
            }, db=conn)
            assert res["status"] == "success"

            latest = get_latest_reading(device_id="esp32_tank_01", db=conn)
            assert len(latest["raw_reading_json"]) >= 100000
            assert latest["raw_reading_json"] == large_json


# ==============================================================================
# Challenge 6: Heavy WAL Concurrency and Checkpoint
# ==============================================================================

class TestHeavyWalConcurrencyAndCheckpoint:
    """Stress test with 20 worker threads and explicit WAL checkpoint TRUNCATE."""

    def test_high_thread_burst_and_checkpoint(self, file_db):
        """20 worker threads simultaneously perform 25 inserts each, followed by WAL checkpoint."""
        num_threads = 20
        inserts_per_thread = 25
        errors = []

        def worker(tid):
            try:
                for i in range(inserts_per_thread):
                    with get_db_context(file_db) as conn:
                        insert_water_reading({
                            "device_id": "esp32_tank_01",
                            "distance_cm": 25.0,
                            "water_level_cm": 175.0,
                            "water_percentage": 87.5,
                            "water_litres": 875.0,
                            "timestamp": f"2026-11-06 14:{tid:02d}:{i:02d}",
                            "date": "2026-11-06"
                        }, db=conn)
            except Exception as e:
                errors.append(f"Worker {tid} error: {e}")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30.0)

        assert not errors, f"Errors during heavy burst: {errors}"

        # Verify total readings
        with get_db_context(file_db) as conn:
            count = get_total_readings_count(db=conn)
            assert count == num_threads * inserts_per_thread

            # Perform WAL checkpoint TRUNCATE
            cur = conn.cursor()
            cur.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            checkpoint_result = cur.fetchone()
            # PRAGMA wal_checkpoint returns (busy, log_frames, checkpointed_frames)
            assert checkpoint_result[0] == 0, f"Checkpoint failed with busy flag: {checkpoint_result}"

            # Verify integrity post-checkpoint
            cur.execute("PRAGMA integrity_check;")
            assert cur.fetchone()[0] == "ok"


# ==============================================================================
# Challenge 7: Empty State Resilience
# ==============================================================================

class TestEmptyStateResilience:
    """Verifies that all query and summary methods degrade gracefully on empty tables."""

    def test_empty_readings_table_queries(self, file_db):
        """All reading/analytics queries must return empty structures, not raise exceptions."""
        with get_db_context(file_db) as conn:
            # Clear all readings if any
            conn.execute("DELETE FROM water_readings;")
            conn.commit()

            # Latest reading -> None
            assert get_latest_reading(db=conn) is None
            assert get_latest_reading(device_id="esp32_tank_01", db=conn) is None

            # Readings by date -> []
            assert get_readings_by_date("2026-11-06", db=conn) == []

            # Daily stats -> []
            assert get_daily_stats(days=15, db=conn) == []

            # Compare dates -> safe zeroes
            comp = compare_dates("2026-11-05", "2026-11-06", db=conn)
            assert comp["date1"]["readings_count"] == 0
            assert comp["date2"]["readings_count"] == 0
            assert comp["comparison"]["trend"] == "insufficient_data"

            # Today's summary -> safe zeroes
            summ = get_today_summary(date_str="2026-11-06", db=conn)
            assert summ["reading_count"] == 0
            assert summ["net_change_litres"] == 0.0

            # Total readings count -> 0
            assert get_total_readings_count(db=conn) == 0

            # Backup logs on empty -> []
            assert get_backup_logs(db=conn) == []
            assert get_backup_by_filename("nonexistent.json", db=conn) is None

