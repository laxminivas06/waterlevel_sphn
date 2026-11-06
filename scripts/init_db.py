#!/usr/bin/env python3
"""
scripts/init_db.py - Database Initializer & Seed Provisioning CLI

Creates the SQLite relational schema with WAL mode, foreign keys, physical domain
constraints, composite B-Tree indexes, and idempotently provisions factory seed data.

Usage:
    python scripts/init_db.py [--db-path PATH] [--reset] [--seed] [--verbose] [--quiet]
"""

import argparse
import os
import sqlite3
import sys

# Ensure project root is importable
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from app.config import DATABASE_PATH as DEFAULT_DB_PATH
except ImportError:
    DEFAULT_DB_PATH = os.path.abspath(os.path.join(PROJECT_ROOT, "data", "water_leveler.db"))


SCHEMA_DDL = """
-- Foreign Key referential integrity enforcement
PRAGMA foreign_keys = ON;

-- ----------------------------------------------------------------------------
-- 1. Devices Table
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY NOT NULL CHECK (length(trim(device_id)) > 0),
    device_name TEXT NOT NULL CHECK (length(trim(device_name)) > 0),
    api_key TEXT NOT NULL CHECK (length(trim(api_key)) > 0),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    last_seen TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);

-- ----------------------------------------------------------------------------
-- 2. Tank Settings Table (Singleton Pattern: id=1)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tank_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    tank_height_cm REAL NOT NULL DEFAULT 200.0 CHECK (tank_height_cm > 0.0),
    total_height_cm REAL DEFAULT 200.0 CHECK (total_height_cm IS NULL OR total_height_cm > 0.0),
    sensor_offset_cm REAL NOT NULL DEFAULT 15.0 CHECK (sensor_offset_cm >= 0.0),
    total_capacity_litres REAL NOT NULL DEFAULT 1000.0 CHECK (total_capacity_litres > 0.0),
    warning_low_percent REAL DEFAULT 20.0 CHECK (warning_low_percent >= 0.0 AND warning_low_percent <= 100.0),
    warning_normal_percent REAL DEFAULT 50.0 CHECK (warning_normal_percent >= 0.0 AND warning_normal_percent <= 100.0),
    low_threshold_percent REAL DEFAULT 20.0 CHECK (low_threshold_percent >= 0.0 AND low_threshold_percent <= 100.0),
    critical_low_threshold_percent REAL DEFAULT 10.0,
    offline_threshold_seconds INTEGER NOT NULL DEFAULT 300 CHECK (offline_threshold_seconds >= 10),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ----------------------------------------------------------------------------
-- 3. Water Readings Telemetry Table
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS water_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    distance_cm REAL NOT NULL CHECK (distance_cm >= 0.0),
    water_level_cm REAL NOT NULL CHECK (water_level_cm >= 0.0),
    water_percentage REAL NOT NULL CHECK (water_percentage >= 0.0 AND water_percentage <= 100.0),
    water_litres REAL NOT NULL CHECK (water_litres >= 0.0),
    timestamp TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    date TEXT NOT NULL CHECK (length(date) = 10 AND date LIKE '____-__-__'),
    raw_reading_json TEXT,
    FOREIGN KEY (device_id) REFERENCES devices (device_id) ON DELETE CASCADE
);

-- B-Tree Indexes for Water Readings (both naming conventions supported)
CREATE INDEX IF NOT EXISTS idx_water_readings_timestamp ON water_readings (timestamp);
CREATE INDEX IF NOT EXISTS idx_water_readings_date ON water_readings (date);
CREATE INDEX IF NOT EXISTS idx_water_readings_device_time ON water_readings (device_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_readings_timestamp ON water_readings (timestamp);
CREATE INDEX IF NOT EXISTS idx_readings_date ON water_readings (date);
CREATE INDEX IF NOT EXISTS idx_readings_device_time ON water_readings (device_id, timestamp);

-- ----------------------------------------------------------------------------
-- 4. Backup Logs Table
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backup_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL CHECK (length(trim(filename)) > 0),
    file_path TEXT NOT NULL CHECK (length(trim(file_path)) > 0),
    filepath TEXT,
    backup_type TEXT NOT NULL CHECK (backup_type IN ('scheduled', 'manual')),
    file_format TEXT NOT NULL DEFAULT 'json' CHECK (file_format IN ('csv', 'json', 'both')),
    format TEXT DEFAULT 'json',
    file_size_bytes INTEGER NOT NULL DEFAULT 0 CHECK (file_size_bytes >= 0),
    records_count INTEGER NOT NULL DEFAULT 0 CHECK (records_count >= 0),
    record_count INTEGER DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('success', 'failed')),
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- B-Tree Indexes for Backup Logs (both naming conventions supported)
CREATE INDEX IF NOT EXISTS idx_backup_logs_created_at ON backup_logs (created_at);
CREATE INDEX IF NOT EXISTS idx_backup_created_at ON backup_logs (created_at);
"""

DEFAULT_SEED_SQL = """
-- Default Device Seed (Idempotent)
INSERT OR IGNORE INTO devices (
    device_id, device_name, api_key, is_active
) VALUES (
    'esp32_tank_01', 'Main Water Tank', 'water_secret_key_2026', 1
);

-- Default Tank Settings Seed (Singleton id=1, Idempotent)
INSERT OR IGNORE INTO tank_settings (
    id, tank_height_cm, total_height_cm, sensor_offset_cm,
    total_capacity_litres, warning_low_percent, warning_normal_percent,
    low_threshold_percent, critical_low_threshold_percent, offline_threshold_seconds
) VALUES (
    1, 200.0, 200.0, 15.0,
    1000.0, 20.0, 50.0,
    20.0, 10.0, 300
);
"""


def log_message(msg: str, verbose: bool = True, quiet: bool = False):
    """Outputs messages according to verbosity preferences."""
    if not quiet and verbose:
        print(f"[init_db] {msg}")


def configure_pragmas(conn: sqlite3.Connection, db_path: str, verbose: bool = False, quiet: bool = False):
    """Configures high-concurrency PRAGMAs for production and testing."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("PRAGMA busy_timeout = 30000;")

    # Apply persistent WAL mode to file-backed databases
    if db_path != ":memory:":
        cursor.execute("PRAGMA journal_mode = WAL;")
        mode = cursor.fetchone()[0]
        cursor.execute("PRAGMA synchronous = NORMAL;")
        log_message(f"Journal mode configured: {mode}", verbose, quiet)
    else:
        cursor.execute("PRAGMA journal_mode = MEMORY;")
        log_message("In-memory SQLite connection configured.", verbose, quiet)


def reset_database(conn: sqlite3.Connection, verbose: bool = False, quiet: bool = False):
    """Drops existing tables cleanly without triggering Windows file-lock errors."""
    log_message("Resetting existing database schema...", verbose, quiet)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = OFF;")
    
    # Drop in reverse foreign key order
    drop_tables = ["backup_logs", "water_readings", "tank_settings", "devices"]
    for table in drop_tables:
        cursor.execute(f"DROP TABLE IF EXISTS {table};")

    # Drop explicit indexes
    drop_indexes = [
        "idx_water_readings_timestamp", "idx_water_readings_date", "idx_water_readings_device_time",
        "idx_readings_timestamp", "idx_readings_date", "idx_readings_device_time",
        "idx_backup_logs_created_at", "idx_backup_created_at"
    ]
    for idx in drop_indexes:
        cursor.execute(f"DROP INDEX IF EXISTS {idx};")

    cursor.execute("PRAGMA foreign_keys = ON;")
    conn.commit()
    log_message("Schema reset complete.", verbose, quiet)


def apply_schema(conn: sqlite3.Connection, verbose: bool = False, quiet: bool = False):
    """Applies the authoritative DDL statements."""
    log_message("Applying database DDL schema...", verbose, quiet)
    conn.executescript(SCHEMA_DDL)
    conn.commit()
    log_message("Database schema created successfully.", verbose, quiet)


def seed_database(conn: sqlite3.Connection, verbose: bool = False, quiet: bool = False):
    """Applies factory seed data idempotently."""
    log_message("Seeding factory default records...", verbose, quiet)
    conn.executescript(DEFAULT_SEED_SQL)
    conn.commit()
    log_message("Database seeding complete.", verbose, quiet)


def init_db(
    db_path: str = None,
    reset: bool = False,
    seed: bool = False,
    verbose: bool = False,
    quiet: bool = False
) -> int:
    """
    Initializes the SQLite database.

    Args:
        db_path: Path to the target SQLite database file.
        reset: If True, drops existing tables before re-creating.
        seed: If True, populates default device and tank settings.
        verbose: If True, prints informative progress logs.
        quiet: If True, suppresses non-error output.

    Returns:
        0 on success, 1 on error.
    """
    target_path = db_path or DEFAULT_DB_PATH

    try:
        # Create parent directory automatically if file-backed
        if target_path != ":memory:":
            db_dir = os.path.dirname(os.path.abspath(target_path))
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
                log_message(f"Created directory: {db_dir}", verbose, quiet)

        log_message(f"Connecting to database at: {target_path}", verbose, quiet)
        conn = sqlite3.connect(target_path, timeout=30.0)

        try:
            configure_pragmas(conn, target_path, verbose=verbose, quiet=quiet)

            if reset:
                reset_database(conn, verbose=verbose, quiet=quiet)

            apply_schema(conn, verbose=verbose, quiet=quiet)

            if seed:
                seed_database(conn, verbose=verbose, quiet=quiet)

            log_message("Database initialization completed successfully.", verbose, quiet)
            return 0
        finally:
            conn.close()

    except Exception as exc:
        sys.stderr.write(f"[init_db ERROR] Failed to initialize database: {exc}\n")
        return 1


def parse_arguments() -> argparse.Namespace:
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Initialize and seed SQLite database for Smart Water Tank Level Monitoring System."
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help=f"Target database file path (default: {DEFAULT_DB_PATH})"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop and recreate all tables and indexes."
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Seed initial device and singleton tank settings."
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output logging."
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress all standard output."
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    exit_code = init_db(
        db_path=args.db_path,
        reset=args.reset,
        seed=args.seed,
        verbose=args.verbose,
        quiet=args.quiet
    )
    sys.exit(exit_code)
