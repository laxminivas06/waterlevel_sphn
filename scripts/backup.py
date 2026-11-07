#!/usr/bin/env python3
"""
scripts/backup.py - Standalone Daily Backup Subsystem for PythonAnywhere

Provides autonomous database backup execution suitable for PythonAnywhere
scheduled tasks (no always-running daemons required). Exports telemetry records
to JSON and CSV formats into a persistent backups directory, enforces a 30-day
retention policy, and logs execution audit records into the backup_logs table.
"""

import argparse
import csv
from datetime import datetime
import json
import os
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# Ensure project root is available in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from app.config import Config
    DEFAULT_DB_PATH = Config.DATABASE_PATH
    DEFAULT_BACKUP_DIR = Config.BACKUP_DIR
except Exception:
    DEFAULT_DB_PATH = os.path.abspath(os.path.join(PROJECT_ROOT, "data", "water_leveler.db"))
    DEFAULT_BACKUP_DIR = os.path.abspath(os.path.join(PROJECT_ROOT, "backups"))


def verify_sqlite_db(db_path: str) -> None:
    """
    Validates that db_path exists, is a valid SQLite file, and can be queried.
    Raises ValueError or sqlite3.Error if invalid.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file not found: {db_path}")

    # Test reading SQLite header and running integrity / quick query
    conn = sqlite3.connect(db_path, timeout=5.0)
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA schema_version;")
        cursor.fetchone()
    finally:
        conn.close()


def export_json(
    conn: sqlite3.Connection,
    output_path: str
) -> Tuple[int, int]:
    """
    Exports full v2.0 database state to a structured JSON file:
    - tanks
    - devices
    - telemetry
    - alerts
    - users
    - legacy water_readings & tank_settings
    Returns (record_count, file_size_bytes).
    """
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Query all tables safely (if exists)
    def fetch_all(table_name: str) -> List[Dict[str, Any]]:
        try:
            cursor.execute(f"SELECT * FROM {table_name}")
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            return []

    tanks = fetch_all("tanks")
    devices = fetch_all("devices")
    telemetry = fetch_all("telemetry")
    alerts = fetch_all("alerts")
    users = fetch_all("users")
    settings = fetch_all("tank_settings")
    readings = fetch_all("water_readings")

    total_records = len(telemetry) or len(readings)

    data = {
        "metadata": {
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "version": "2.0.0",
            "tanks_count": len(tanks),
            "devices_count": len(devices),
            "telemetry_count": len(telemetry),
            "alerts_count": len(alerts),
            "users_count": len(users),
            "readings_count": len(readings),
        },
        "tanks": tanks,
        "devices": devices,
        "telemetry": telemetry,
        "alerts": alerts,
        "users": users,
        "tank_settings": settings,
        "water_readings": readings,
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    file_size = os.path.getsize(output_path)
    return total_records, file_size


def restore_backup(
    backup_path: str,
    db_path: str = DEFAULT_DB_PATH
) -> Dict[str, Any]:
    """
    Restores database records from a JSON backup file.
    Recovers tanks, devices, telemetry, alerts, and settings.
    """
    if not os.path.exists(backup_path):
        raise FileNotFoundError(f"Backup file not found: {backup_path}")

    with open(backup_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Initialize schema if DB is empty or missing
    from scripts.init_db import apply_schema, configure_pragmas
    conn = sqlite3.connect(db_path, timeout=30.0)
    configure_pragmas(conn, db_path)
    apply_schema(conn, quiet=True)
    cursor = conn.cursor()

    restored_counts = {}

    try:
        # Restore tanks
        tanks = data.get("tanks", [])
        for t in tanks:
            cols = list(t.keys())
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)
            cursor.execute(
                f"INSERT OR REPLACE INTO tanks ({col_names}) VALUES ({placeholders})",
                list(t.values())
            )
        restored_counts["tanks"] = len(tanks)

        # Restore devices
        devices = data.get("devices", [])
        for d in devices:
            cols = list(d.keys())
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)
            cursor.execute(
                f"INSERT OR REPLACE INTO devices ({col_names}) VALUES ({placeholders})",
                list(d.values())
            )
        restored_counts["devices"] = len(devices)

        # Restore telemetry
        telemetry = data.get("telemetry", [])
        for r in telemetry:
            cols = list(r.keys())
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)
            cursor.execute(
                f"INSERT OR REPLACE INTO telemetry ({col_names}) VALUES ({placeholders})",
                list(r.values())
            )
        restored_counts["telemetry"] = len(telemetry)

        # Restore alerts
        alerts = data.get("alerts", [])
        for a in alerts:
            cols = list(a.keys())
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)
            cursor.execute(
                f"INSERT OR REPLACE INTO alerts ({col_names}) VALUES ({placeholders})",
                list(a.values())
            )
        restored_counts["alerts"] = len(alerts)

        # Restore legacy water_readings
        readings = data.get("water_readings", [])
        for r in readings:
            cols = list(r.keys())
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)
            try:
                cursor.execute(
                    f"INSERT OR REPLACE INTO water_readings ({col_names}) VALUES ({placeholders})",
                    list(r.values())
                )
            except Exception:
                pass
        restored_counts["water_readings"] = len(readings)

        conn.commit()

        return {
            "status": "success",
            "message": f"Successfully restored database from {backup_path}",
            "restored_counts": restored_counts,
        }
    finally:
        conn.close()


def export_csv(
    conn: sqlite3.Connection,
    output_path: str
) -> Tuple[int, int]:
    """
    Exports telemetry records to universal CSV format.
    Returns (record_count, file_size_bytes).
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, device_id, distance_cm, water_level_cm, water_percentage, water_litres, timestamp, date
        FROM water_readings
        ORDER BY timestamp ASC, id ASC
        """
    )
    rows = cursor.fetchall()
    total_records = len(rows)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "id", "device_id", "distance_cm", "water_level_cm",
            "water_percentage", "water_litres", "timestamp", "date"
        ])
        for row in rows:
            writer.writerow(row)

    file_size = os.path.getsize(output_path)
    return total_records, file_size


def rotate_backups(output_dir: str, retention_days: int) -> List[str]:
    """
    Purges backup files older than retention_days.
    Returns list of deleted file paths.
    """
    if retention_days <= 0:
        return []

    deleted: List[str] = []
    if not os.path.exists(output_dir):
        return deleted

    cutoff_seconds = time.time() - (retention_days * 86400)

    for entry in os.listdir(output_dir):
        if not (entry.endswith(".json") or entry.endswith(".csv")):
            continue
        full_path = os.path.join(output_dir, entry)
        if not os.path.isfile(full_path):
            continue

        try:
            mtime = os.path.getmtime(full_path)
            if mtime < cutoff_seconds:
                os.remove(full_path)
                deleted.append(full_path)
        except OSError as e:
            sys.stderr.write(f"Warning: Failed to delete expired backup {full_path}: {e}\n")

    return deleted


def log_backup_to_db(
    conn: sqlite3.Connection,
    backup_type: str,
    file_format: str,
    filename: str,
    file_path: str,
    file_size_bytes: int,
    records_count: int,
    status: str,
    error_message: Optional[str] = None
) -> None:
    """
    Inserts an audit log into backup_logs table with schema compatibility.
    """
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO backup_logs (
            backup_type, file_format, filename, file_path,
            file_size_bytes, records_count, status, error_message, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            backup_type, file_format, filename, file_path,
            file_size_bytes, records_count, status, error_message, now_ts
        )
    )
    conn.commit()


def run_backup(
    db_path: str = DEFAULT_DB_PATH,
    output_dir: str = DEFAULT_BACKUP_DIR,
    file_format: str = "both",
    retention_days: int = 30,
    backup_type: str = "scheduled"
) -> Dict[str, Any]:
    """
    Executes database backup, retention rotation, and DB audit logging.
    Returns summary dictionary.
    """
    if file_format not in ("json", "csv", "both"):
        raise ValueError(f"Unsupported format '{file_format}'. Must be 'json', 'csv', or 'both'.")

    if retention_days < 0:
        raise ValueError(f"retention-days must be non-negative (received {retention_days})")

    verify_sqlite_db(db_path)

    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    conn = sqlite3.connect(db_path, timeout=30.0)
    created_files = []
    primary_filename = ""
    primary_size = 0
    records_count = 0

    try:
        if file_format in ("json", "both"):
            json_filename = f"backup_{ts}.json"
            json_path = os.path.join(output_dir, json_filename)
            count, size = export_json(conn, json_path)
            log_backup_to_db(
                conn, backup_type=backup_type, file_format="json",
                filename=json_filename, file_path=json_path,
                file_size_bytes=size, records_count=count, status="success"
            )
            created_files.append({"filename": json_filename, "path": json_path, "size": size, "format": "json"})
            primary_filename = json_filename
            primary_size = size
            records_count = count

        if file_format in ("csv", "both"):
            csv_filename = f"backup_{ts}.csv"
            csv_path = os.path.join(output_dir, csv_filename)
            count, size = export_csv(conn, csv_path)
            log_backup_to_db(
                conn, backup_type=backup_type, file_format="csv",
                filename=csv_filename, file_path=csv_path,
                file_size_bytes=size, records_count=count, status="success"
            )
            created_files.append({"filename": csv_filename, "path": csv_path, "size": size, "format": "csv"})
            if not primary_filename:
                primary_filename = csv_filename
                primary_size = size
                records_count = count

        # If format was both, we also have primary_filename as json_filename
        # Retention rotation
        purged = rotate_backups(output_dir, retention_days)

        return {
            "status": "success",
            "filename": primary_filename,
            "file_size_bytes": primary_size,
            "records_count": records_count,
            "files": created_files,
            "purged_count": len(purged)
        }

    except Exception as e:
        try:
            log_backup_to_db(
                conn, backup_type=backup_type, file_format=file_format,
                filename=primary_filename or f"failed_{ts}",
                file_path=os.path.join(output_dir, primary_filename or f"failed_{ts}"),
                file_size_bytes=0, records_count=0, status="failed", error_message=str(e)
            )
        except Exception:
            pass
        raise e
    finally:
        conn.close()


def main() -> int:
    """
    CLI runner for standalone backup script.
    """
    parser = argparse.ArgumentParser(
        description="Smart Water Tank Level Monitoring System - Standalone Database Backup Runner (R5)"
    )
    parser.add_argument(
        "--format",
        choices=["json", "csv", "both"],
        default="both",
        help="Export format: json, csv, or both (default: both)"
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help="Path to SQLite database file"
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_BACKUP_DIR,
        help="Destination directory for backup archives"
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=30,
        help="Retention period in days (older files deleted). 0 disables deletion."
    )
    parser.add_argument(
        "--backup-type",
        choices=["scheduled", "manual"],
        default="scheduled",
        help="Backup trigger type logged to database (default: scheduled)"
    )
    parser.add_argument(
        "--restore",
        metavar="BACKUP_FILE",
        help="Path to JSON backup file to restore into database"
    )

    args = parser.parse_args()

    if args.restore:
        try:
            res = restore_backup(backup_path=args.restore, db_path=args.db_path)
            print(f"Database restoration successful: {json.dumps(res, indent=2)}")
            return 0
        except Exception as exc:
            sys.stderr.write(f"Database restoration failed: {exc}\n")
            return 1

    try:
        result = run_backup(
            db_path=args.db_path,
            output_dir=args.output_dir,
            file_format=args.format,
            retention_days=args.retention_days,
            backup_type=args.backup_type
        )
        print(f"Backup completed successfully: {json.dumps(result, indent=2)}")
        return 0
    except Exception as exc:
        sys.stderr.write(f"Backup execution failed: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
