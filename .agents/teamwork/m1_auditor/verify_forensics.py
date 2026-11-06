#!/usr/bin/env python3
"""
verify_forensics.py - Independent Empirical Integrity Verification Script
Executed by m1_auditor to forensically verify Milestone M1 implementation.
"""

import os
import sys
import tempfile
import sqlite3
import json

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.config import Config, DATABASE_PATH
from app.database import create_connection, get_db_context
import app.models as models
from scripts.init_db import init_db

print("=== CHECK 1: DISK DATABASE DIRECTORY & PERSISTENCE ===")
print(f"DATABASE_PATH: {DATABASE_PATH}")
print(f"Exists on disk: {os.path.exists(DATABASE_PATH)}")
if os.path.exists(DATABASE_PATH):
    size = os.path.getsize(DATABASE_PATH)
    print(f"File size on disk: {size} bytes")
    conn = sqlite3.connect(DATABASE_PATH)
    cur = conn.cursor()
    cur.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table', 'index') ORDER BY type, name;")
    for name, otype in cur.fetchall():
        print(f"  [{otype}] {name}")
    cur.execute("SELECT COUNT(*) FROM devices;")
    print(f"Devices count: {cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM tank_settings;")
    print(f"Tank settings count: {cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM water_readings;")
    print(f"Water readings count: {cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM backup_logs;")
    print(f"Backup logs count: {cur.fetchone()[0]}")
    conn.close()

print("\n=== CHECK 2: FRESH DISK CREATION, INIT_DB & PRAGMAS ===")
with tempfile.TemporaryDirectory() as tmp_dir:
    test_db = os.path.join(tmp_dir, "forensic_test.db")
    ret = init_db(test_db, reset=True, seed=True, quiet=True)
    assert ret == 0, "init_db failed on new file"
    assert os.path.exists(test_db), "test_db not created on disk"
    assert os.path.getsize(test_db) > 0, "test_db is empty"

    conn = create_connection(test_db)
    cur = conn.cursor()

    cur.execute("PRAGMA foreign_keys;")
    fk_val = cur.fetchone()[0]
    print(f"PRAGMA foreign_keys: {fk_val} (expected: 1)")
    assert fk_val == 1, f"foreign_keys is {fk_val}"

    cur.execute("PRAGMA journal_mode;")
    jm_val = cur.fetchone()[0]
    print(f"PRAGMA journal_mode: {jm_val} (expected: wal)")
    assert jm_val.lower() == "wal", f"journal_mode is {jm_val}"

    cur.execute("PRAGMA busy_timeout;")
    bt_val = cur.fetchone()[0]
    print(f"PRAGMA busy_timeout: {bt_val} (expected: >= 30000)")
    assert bt_val >= 30000, f"busy_timeout is {bt_val}"
    conn.close()

print("\n=== CHECK 3: SQL CHECK CONSTRAINTS ENFORCEMENT AT ENGINE LEVEL ===")
with tempfile.TemporaryDirectory() as tmp_dir:
    test_db = os.path.join(tmp_dir, "constraints_test.db")
    init_db(test_db, reset=True, seed=True, quiet=True)
    conn = sqlite3.connect(test_db)
    conn.execute("PRAGMA foreign_keys = ON;")

    # 3.1: Reject negative tank_height_cm
    try:
        conn.execute("UPDATE tank_settings SET tank_height_cm = -10.0 WHERE id = 1;")
        print("FAIL: Negative tank_height_cm was NOT rejected!")
        assert False
    except sqlite3.IntegrityError as e:
        print(f"PASS: Negative tank_height_cm rejected ({e})")

    # 3.2: Reject zero capacity
    try:
        conn.execute("UPDATE tank_settings SET total_capacity_litres = 0.0 WHERE id = 1;")
        print("FAIL: Zero total_capacity_litres was NOT rejected!")
        assert False
    except sqlite3.IntegrityError as e:
        print(f"PASS: Zero total_capacity_litres rejected ({e})")

    # 3.3: Reject percentage > 100
    try:
        conn.execute(
            "INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, date) VALUES (?, 10.0, 190.0, 101.5, 1015.0, '2026-11-06');",
            ("esp32_tank_01",)
        )
        print("FAIL: Percentage > 100 was NOT rejected!")
        assert False
    except sqlite3.IntegrityError as e:
        print(f"PASS: Percentage > 100 rejected ({e})")

    # 3.4: Reject percentage < 0
    try:
        conn.execute(
            "INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, date) VALUES (?, 10.0, 0.0, -5.0, 0.0, '2026-11-06');",
            ("esp32_tank_01",)
        )
        print("FAIL: Percentage < 0 was NOT rejected!")
        assert False
    except sqlite3.IntegrityError as e:
        print(f"PASS: Percentage < 0 rejected ({e})")

    # 3.5: Reject negative distance_cm
    try:
        conn.execute(
            "INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, date) VALUES (?, -1.0, 100.0, 50.0, 500.0, '2026-11-06');",
            ("esp32_tank_01",)
        )
        print("FAIL: Negative distance_cm was NOT rejected!")
        assert False
    except sqlite3.IntegrityError as e:
        print(f"PASS: Negative distance_cm rejected ({e})")

    # 3.6: Reject second tank_settings row (Singleton id=1)
    try:
        conn.execute(
            "INSERT INTO tank_settings (id, tank_height_cm, sensor_offset_cm, total_capacity_litres) VALUES (2, 300.0, 10.0, 2000.0);"
        )
        print("FAIL: Second tank_settings row was NOT rejected!")
        assert False
    except sqlite3.IntegrityError as e:
        print(f"PASS: Second tank_settings row rejected ({e})")

    # 3.7: Reject water reading referencing non-existent device (FK constraint)
    try:
        conn.execute(
            "INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, date) VALUES ('fake_device_99', 10.0, 100.0, 50.0, 500.0, '2026-11-06');"
        )
        print("FAIL: Foreign key violation was NOT rejected!")
        assert False
    except sqlite3.IntegrityError as e:
        print(f"PASS: Foreign key violation rejected ({e})")

    conn.close()

print("\n=== CHECK 4: REAL DYNAMIC COMPUTATION (NO HARDCODED MOCKS) ===")
with tempfile.TemporaryDirectory() as tmp_dir:
    test_db = os.path.join(tmp_dir, "dyn_test.db")
    init_db(test_db, reset=True, seed=True, quiet=True)
    conn = create_connection(test_db)

    # Insert random custom numbers to verify mathematical queries
    custom_device = "custom_sensor_xyz"
    models.register_device(custom_device, "key_xyz", "Custom Sensor", 1, db=conn)

    # 3 distinct readings on date 2026-11-01:
    # 1. 20% (200L, level 40cm) at 09:00:00
    # 2. 60% (600L, level 120cm) at 12:00:00
    # 3. 70% (700L, level 140cm) at 18:00:00
    r1 = {
        "device_id": custom_device, "distance_cm": 160.0, "water_level_cm": 40.0,
        "water_percentage": 20.0, "water_litres": 200.0, "timestamp": "2026-11-01 09:00:00",
        "date": "2026-11-01"
    }
    r2 = {
        "device_id": custom_device, "distance_cm": 80.0, "water_level_cm": 120.0,
        "water_percentage": 60.0, "water_litres": 600.0, "timestamp": "2026-11-01 12:00:00",
        "date": "2026-11-01"
    }
    r3 = {
        "device_id": custom_device, "distance_cm": 60.0, "water_level_cm": 140.0,
        "water_percentage": 70.0, "water_litres": 700.0, "timestamp": "2026-11-01 18:00:00",
        "date": "2026-11-01"
    }
    models.insert_water_reading(r1, db=conn)
    models.insert_water_reading(r2, db=conn)
    models.insert_water_reading(r3, db=conn)

    # Check daily stats dynamically computed
    stats = models.get_daily_stats(days=30, device_id=custom_device, db=conn)
    print("Daily stats result:", stats)
    assert len(stats) == 1
    s = stats[0]
    assert s["date"] == "2026-11-01"
    assert s["reading_count"] == 3
    assert s["min_percentage"] == 20.0
    assert s["max_percentage"] == 70.0
    assert abs(s["avg_percentage"] - 50.0) < 0.01  # (20 + 60 + 70)/3 = 50.0
    assert s["min_litres"] == 200.0
    assert s["max_litres"] == 700.0
    assert abs(s["avg_litres"] - 500.0) < 0.01   # (200 + 600 + 700)/3 = 500.0
    print("PASS: get_daily_stats computed exact min, max, avg aggregates dynamically!")

    # Check today's summary net change calculation
    summary = models.get_today_summary(device_id=custom_device, date_str="2026-11-01", db=conn)
    print("Today summary result:", summary)
    assert summary["reading_count"] == 3
    assert summary["net_change_litres"] == 500.0 # 700.0 (last) - 200.0 (first) = 500.0
    print("PASS: get_today_summary computed net change dynamically!")

    # Check latest reading
    latest = models.get_latest_reading(device_id=custom_device, db=conn)
    assert latest["water_percentage"] == 70.0
    print("PASS: get_latest_reading retrieved correct most recent reading!")

    conn.close()

print("\n=== ALL FORENSIC INTEGRITY CHECKS PASSED ===")
