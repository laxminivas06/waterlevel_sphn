#!/usr/bin/env python3
"""
scripts/init_db.py - Comprehensive Database Initializer & Migration Tool
HydroSense IoT - Smart Water Tank Monitoring System v2.0

Creates the 6 core production tables:
1. users
2. tanks
3. devices
4. telemetry
5. alerts
6. backup_records
Along with legacy backward compatibility tables/views, high-concurrency WAL mode PRAGMAs,
and factory seed data.
"""

import argparse
import os
import sqlite3
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from app.config import DATABASE_PATH as DEFAULT_DB_PATH
except ImportError:
    DEFAULT_DB_PATH = os.path.abspath(os.path.join(PROJECT_ROOT, "data", "water_leveler.db"))


SCHEMA_DDL = """
PRAGMA foreign_keys = ON;

-- ----------------------------------------------------------------------------
-- 1. Users Table
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL CHECK (length(trim(username)) > 0),
    password_hash TEXT NOT NULL,
    email TEXT,
    role TEXT NOT NULL DEFAULT 'operator' CHECK (role IN ('admin', 'operator', 'viewer')),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ----------------------------------------------------------------------------
-- 2. Tanks Table (Multi-tank support, cylindrical & rectangular geometry)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tanks (
    tank_id TEXT PRIMARY KEY NOT NULL CHECK (length(trim(tank_id)) > 0),
    tank_name TEXT NOT NULL CHECK (length(trim(tank_name)) > 0),
    shape TEXT NOT NULL DEFAULT 'cylinder' CHECK (shape IN ('cylinder', 'rectangle', 'custom')),
    tank_height_cm REAL NOT NULL DEFAULT 200.0 CHECK (tank_height_cm > 0.0),
    sensor_offset_cm REAL NOT NULL DEFAULT 15.0 CHECK (sensor_offset_cm >= 0.0),
    total_capacity_litres REAL NOT NULL DEFAULT 1000.0 CHECK (total_capacity_litres > 0.0),
    length_cm REAL,
    width_cm REAL,
    radius_cm REAL,
    safe_max_percent REAL NOT NULL DEFAULT 95.0 CHECK (safe_max_percent > 0.0 AND safe_max_percent <= 100.0),
    critical_low_percent REAL NOT NULL DEFAULT 10.0 CHECK (critical_low_percent >= 0.0),
    low_percent REAL NOT NULL DEFAULT 25.0 CHECK (low_percent > critical_low_percent),
    high_percent REAL NOT NULL DEFAULT 85.0 CHECK (high_percent > low_percent),
    offline_threshold_seconds INTEGER NOT NULL DEFAULT 300 CHECK (offline_threshold_seconds >= 10),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ----------------------------------------------------------------------------
-- 3. Devices Table (Multi-device support, mapped to tanks)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY NOT NULL CHECK (length(trim(device_id)) > 0),
    device_name TEXT NOT NULL CHECK (length(trim(device_name)) > 0),
    tank_id TEXT REFERENCES tanks(tank_id) ON DELETE SET NULL,
    api_key TEXT NOT NULL CHECK (length(trim(api_key)) > 0),
    ip_address TEXT,
    firmware_version TEXT DEFAULT '2.0.0',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    last_seen TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);

-- ----------------------------------------------------------------------------
-- 4. Telemetry Table (Core high-frequency time-series measurements)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    tank_id TEXT NOT NULL,
    distance_cm REAL NOT NULL CHECK (distance_cm >= 0.0),
    water_height REAL NOT NULL,
    water_percentage REAL NOT NULL,
    water_volume REAL NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('CRITICAL LOW', 'LOW', 'NORMAL', 'HIGH', 'OVERLOADED', 'SENSOR FAULT')),
    timestamp TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    date TEXT NOT NULL CHECK (length(date) = 10 AND date LIKE '____-__-__'),
    raw_payload TEXT,
    FOREIGN KEY (tank_id) REFERENCES tanks(tank_id) ON DELETE CASCADE,
    FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_telemetry_tank_ts ON telemetry (tank_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_telemetry_device_ts ON telemetry (device_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_telemetry_date ON telemetry (date);
CREATE INDEX IF NOT EXISTS idx_telemetry_status ON telemetry (status);

-- ----------------------------------------------------------------------------
-- 5. Alerts Table (Section 7 and 11)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tank_id TEXT,
    device_id TEXT,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'warning' CHECK (severity IN ('critical', 'warning', 'info')),
    message TEXT NOT NULL,
    is_acknowledged INTEGER NOT NULL DEFAULT 0 CHECK (is_acknowledged IN (0, 1)),
    acknowledged_at TEXT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (tank_id) REFERENCES tanks(tank_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_alerts_ack ON alerts (is_acknowledged, timestamp);
CREATE INDEX IF NOT EXISTS idx_alerts_tank ON alerts (tank_id, timestamp);

-- ----------------------------------------------------------------------------
-- 6. Backup Records Table (Section 11)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backup_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL CHECK (length(trim(filename)) > 0),
    file_path TEXT NOT NULL CHECK (length(trim(file_path)) > 0),
    record_count INTEGER NOT NULL DEFAULT 0 CHECK (record_count >= 0),
    file_size_bytes INTEGER NOT NULL DEFAULT 0 CHECK (file_size_bytes >= 0),
    backup_type TEXT NOT NULL DEFAULT 'automated' CHECK (backup_type IN ('automated', 'manual', 'scheduled')),
    status TEXT NOT NULL DEFAULT 'success' CHECK (status IN ('success', 'failed')),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_backup_records_created ON backup_records (created_at);

-- ----------------------------------------------------------------------------
-- 7. Legacy Compatibility Tables (to support older routes seamlessly)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tank_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    tank_height_cm REAL NOT NULL DEFAULT 200.0,
    total_height_cm REAL DEFAULT 200.0,
    sensor_offset_cm REAL NOT NULL DEFAULT 15.0,
    total_capacity_litres REAL NOT NULL DEFAULT 1000.0,
    warning_low_percent REAL DEFAULT 20.0,
    warning_normal_percent REAL DEFAULT 50.0,
    low_threshold_percent REAL DEFAULT 20.0,
    critical_low_threshold_percent REAL DEFAULT 10.0,
    offline_threshold_seconds INTEGER NOT NULL DEFAULT 300,
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS water_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    distance_cm REAL NOT NULL,
    water_level_cm REAL NOT NULL,
    water_percentage REAL NOT NULL,
    water_litres REAL NOT NULL,
    timestamp TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    date TEXT NOT NULL,
    raw_reading_json TEXT
);

CREATE TABLE IF NOT EXISTS backup_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    filepath TEXT,
    backup_type TEXT NOT NULL,
    file_format TEXT NOT NULL DEFAULT 'json',
    format TEXT DEFAULT 'json',
    file_size_bytes INTEGER NOT NULL DEFAULT 0,
    records_count INTEGER NOT NULL DEFAULT 0,
    record_count INTEGER DEFAULT 0,
    status TEXT NOT NULL,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

DEFAULT_SEED_SQL = """
-- Default Users
INSERT OR IGNORE INTO users (id, username, password_hash, email, role)
VALUES (1, 'admin', 'pbkdf2:sha256:600000$hydrosense$admin', 'admin@hydrosense.local', 'admin');

-- Default Tanks (Cylindrical Overhead + Rectangular Sump)
INSERT OR IGNORE INTO tanks (
    tank_id, tank_name, shape, tank_height_cm, sensor_offset_cm,
    total_capacity_litres, radius_cm, safe_max_percent,
    critical_low_percent, low_percent, high_percent, offline_threshold_seconds
) VALUES (
    'SV_BLOCK_OVER_TANK', 'SV Block Overhead Tank', 'cylinder',
    200.0, 15.0, 1000.0, 39.89, 95.0,
    10.0, 25.0, 85.0, 300
);

INSERT OR IGNORE INTO tanks (
    tank_id, tank_name, shape, tank_height_cm, sensor_offset_cm,
    total_capacity_litres, length_cm, width_cm, safe_max_percent,
    critical_low_percent, low_percent, high_percent, offline_threshold_seconds
) VALUES (
    'GROUND_SUMP_TANK_01', 'Ground Sump Storage', 'rectangle',
    180.0, 10.0, 2500.0, 150.0, 100.0, 95.0,
    10.0, 25.0, 85.0, 300
);

-- Default Devices
INSERT OR IGNORE INTO devices (
    device_id, device_name, tank_id, api_key, firmware_version, is_active
) VALUES (
    'SV_BLOCK_OVER_TANK', 'NodeMCU SV Overhead Sensor', 'SV_BLOCK_OVER_TANK', 'water_secret_key_2026', '2.1.0', 1
);

INSERT OR IGNORE INTO devices (
    device_id, device_name, tank_id, api_key, firmware_version, is_active
) VALUES (
    'esp32_tank_01', 'ESP32 Sump Ultrasonic Monitor', 'GROUND_SUMP_TANK_01', 'water_secret_key_2026', '2.1.0', 1
);

-- Seed initial tank_settings for legacy backward compatibility
INSERT OR IGNORE INTO tank_settings (
    id, tank_height_cm, total_height_cm, sensor_offset_cm,
    total_capacity_litres, warning_low_percent, warning_normal_percent,
    low_threshold_percent, critical_low_threshold_percent, offline_threshold_seconds
) VALUES (
    1, 200.0, 200.0, 15.0, 1000.0, 25.0, 85.0, 25.0, 10.0, 300
);
"""


def log_message(msg: str, verbose: bool = True, quiet: bool = False):
    if not quiet and verbose:
        print(f"[init_db] {msg}")


def configure_pragmas(conn: sqlite3.Connection, db_path: str, verbose: bool = False, quiet: bool = False):
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("PRAGMA busy_timeout = 30000;")
    if db_path != ":memory:":
        cursor.execute("PRAGMA journal_mode = WAL;")
        mode = cursor.fetchone()[0]
        cursor.execute("PRAGMA synchronous = NORMAL;")
        log_message(f"Journal mode configured: {mode}", verbose, quiet)


def apply_schema(conn: sqlite3.Connection, verbose: bool = False, quiet: bool = False):
    log_message("Applying database DDL schema...", verbose, quiet)
    conn.executescript(SCHEMA_DDL)
    
    # Run idempotent column migrations for existing tables
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(devices);")
    existing_dev_cols = {row[1] for row in cursor.fetchall()}
    if "tank_id" not in existing_dev_cols:
        cursor.execute("ALTER TABLE devices ADD COLUMN tank_id TEXT REFERENCES tanks(tank_id) ON DELETE SET NULL;")
    if "ip_address" not in existing_dev_cols:
        cursor.execute("ALTER TABLE devices ADD COLUMN ip_address TEXT;")
    if "firmware_version" not in existing_dev_cols:
        cursor.execute("ALTER TABLE devices ADD COLUMN firmware_version TEXT DEFAULT '2.0.0';")
    
    conn.commit()
    log_message("Database schema created successfully.", verbose, quiet)


def seed_database(conn: sqlite3.Connection, verbose: bool = False, quiet: bool = False):
    log_message("Seeding factory default records...", verbose, quiet)
    conn.executescript(DEFAULT_SEED_SQL)
    conn.commit()
    log_message("Database seeding complete.", verbose, quiet)


def init_db(
    db_path: str = None,
    reset: bool = False,
    seed: bool = False,
    verbose: bool = False,
    quiet: bool = False,
) -> int:
    resolved_path = db_path or DEFAULT_DB_PATH
    log_message(f"Connecting to database at: {resolved_path}", verbose, quiet)

    if resolved_path != ":memory:":
        parent_dir = os.path.dirname(resolved_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

    try:
        conn = sqlite3.connect(resolved_path, timeout=30.0)
        configure_pragmas(conn, resolved_path, verbose, quiet)

        if reset:
            log_message("Resetting existing database schema...", verbose, quiet)
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys = OFF;")
            drop_tables = [
                "telemetry", "alerts", "backup_records", "devices", "tanks", "users",
                "water_readings", "tank_settings", "backup_logs"
            ]
            for t in drop_tables:
                cursor.execute(f"DROP TABLE IF EXISTS {t};")
            cursor.execute("PRAGMA foreign_keys = ON;")
            conn.commit()
            log_message("Schema reset complete.", verbose, quiet)

        apply_schema(conn, verbose, quiet)

        if seed:
            seed_database(conn, verbose, quiet)

        conn.close()
        log_message("Database initialization completed successfully.", verbose, quiet)
        return 0
    except Exception as e:
        print(f"[init_db ERROR] Failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HydroSense IoT Database Initializer")
    parser.add_argument("--db-path", default=None, help="Path to database file")
    parser.add_argument("--reset", action="store_true", help="Drop all existing tables before init")
    parser.add_argument("--seed", action="store_true", help="Seed default tanks, devices and admin")
    parser.add_argument("--verbose", "-v", action="store_true", default=True, help="Verbose log output")
    parser.add_argument("--quiet", "-q", action="store_true", help="Quiet mode")

    args = parser.parse_args()
    exit_code = init_db(
        db_path=args.db_path,
        reset=args.reset,
        seed=args.seed,
        verbose=args.verbose and not args.quiet,
        quiet=args.quiet,
    )
    sys.exit(exit_code)
