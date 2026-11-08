#!/usr/bin/env python3
"""
scripts/backup.py - Standalone Daily Backup Subsystem for PythonAnywhere (JSON Edition)

Provides autonomous database backup execution suitable for PythonAnywhere
scheduled tasks (no always-running daemons required). Exports records
to JSON and CSV formats into a persistent backups directory, enforces a 30-day
retention policy, and logs execution audit records into the database.
"""

import argparse
import csv
from datetime import datetime
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# Ensure project root is available in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.config import Config
from app.database import get_db, JsonDatabase

DEFAULT_DB_PATH = Config.DATABASE_PATH
DEFAULT_BACKUP_DIR = Config.BACKUP_DIR


def verify_json_db(db_path: str) -> None:
    """
    Validates that db_path exists, is a valid JSON file, and can be parsed.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file not found: {db_path}")

    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Database file {db_path} root must be a JSON object")


def export_json(
    database: JsonDatabase,
    output_path: str
) -> Tuple[int, int]:
    """
    Exports full database state to a structured JSON backup file:
    - tanks
    - devices
    - telemetry
    - alerts
    - users
    - legacy water_readings & tank_settings
    Returns (record_count, file_size_bytes).
    """
    data = database.get_data()

    tanks = data.get("tanks", [])
    devices = data.get("devices", [])
    telemetry = data.get("telemetry", [])
    alerts = data.get("alerts", [])
    users = data.get("users", [])
    settings = data.get("tank_settings", {})
    readings = data.get("water_readings", [])

    total_records = len(telemetry) or len(readings)

    backup_payload = {
        "metadata": {
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "version": "2.1.0",
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
        json.dump(backup_payload, f, indent=2, ensure_ascii=False)

    file_size = os.path.getsize(output_path)
    return total_records, file_size


def restore_backup(
    backup_path: str,
    db_path: str = DEFAULT_DB_PATH
) -> Dict[str, Any]:
    """
    Restores database records from a JSON backup file.
    Recovers tanks, devices, telemetry, alerts, users, and settings.
    """
    if not os.path.exists(backup_path):
        raise FileNotFoundError(f"Backup file not found: {backup_path}")

    with open(backup_path, "r", encoding="utf-8") as f:
        backup_data = json.load(f)

    database = get_db(db_path)
    current_data = database.get_data()
    restored_counts = {}

    for key in ("tanks", "devices", "telemetry", "alerts", "users", "water_readings"):
        if key in backup_data and isinstance(backup_data[key], list):
            current_data[key] = backup_data[key]
            restored_counts[key] = len(backup_data[key])

    if "tank_settings" in backup_data:
        current_data["tank_settings"] = backup_data["tank_settings"]
        restored_counts["tank_settings"] = 1

    database.save()

    return {
        "status": "success",
        "message": f"Successfully restored database from {backup_path}",
        "restored_counts": restored_counts,
    }


def export_csv(
    database: JsonDatabase,
    output_path: str
) -> Tuple[int, int]:
    """
    Exports telemetry records to universal CSV format.
    Returns (record_count, file_size_bytes).
    """
    data = database.get_data()
    readings = data.get("water_readings") or data.get("telemetry", [])
    total_records = len(readings)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "id", "device_id", "distance_cm", "water_level_cm",
            "water_percentage", "water_litres", "timestamp", "date"
        ])
        for r in readings:
            writer.writerow([
                r.get("id"),
                r.get("device_id"),
                r.get("distance_cm"),
                r.get("water_level_cm", r.get("water_height")),
                r.get("water_percentage"),
                r.get("water_litres", r.get("water_volume")),
                r.get("timestamp"),
                r.get("date"),
            ])

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
    database: JsonDatabase,
    backup_type: str,
    file_format: str,
    filename: str,
    file_path: str,
    file_size_bytes: int,
    records_count: int,
    status: str,
    error_message: Optional[str] = None
) -> None:
    """Inserts an audit log into backup_records with schema compatibility."""
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    record = {
        "backup_type": backup_type,
        "file_format": file_format,
        "filename": filename,
        "file_path": file_path,
        "file_size_bytes": file_size_bytes,
        "record_count": records_count,
        "records_count": records_count,
        "status": status,
        "error_message": error_message,
        "notes": error_message,
        "created_at": now_ts,
    }
    database.insert("backup_records", record)
    database.insert("backup_logs", record)


def run_backup(
    db_path: str = DEFAULT_DB_PATH,
    output_dir: str = DEFAULT_BACKUP_DIR,
    file_format: str = "both",
    retention_days: int = 45,
    backup_type: str = "scheduled"
) -> Dict[str, Any]:
    """
    Executes database backup, retention rotation, and audit logging.
    Returns summary dictionary.
    """
    if file_format not in ("json", "csv", "both"):
        raise ValueError(f"Unsupported format '{file_format}'. Must be 'json', 'csv', or 'both'.")

    if retention_days < 0:
        raise ValueError(f"retention-days must be non-negative (received {retention_days})")

    verify_json_db(db_path)

    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    database = get_db(db_path)
    created_files = []
    primary_filename = ""
    primary_size = 0
    records_count = 0

    try:
        if file_format in ("json", "both"):
            json_filename = f"backup_{ts}.json"
            json_path = os.path.join(output_dir, json_filename)
            count, size = export_json(database, json_path)
            log_backup_to_db(
                database, backup_type=backup_type, file_format="json",
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
            count, size = export_csv(database, csv_path)
            log_backup_to_db(
                database, backup_type=backup_type, file_format="csv",
                filename=csv_filename, file_path=csv_path,
                file_size_bytes=size, records_count=count, status="success"
            )
            created_files.append({"filename": csv_filename, "path": csv_path, "size": size, "format": "csv"})
            if not primary_filename:
                primary_filename = csv_filename
                primary_size = size
                records_count = count

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
                database, backup_type=backup_type, file_format=file_format,
                filename=primary_filename or f"failed_{ts}",
                file_path=os.path.join(output_dir, primary_filename or f"failed_{ts}"),
                file_size_bytes=0, records_count=0, status="failed", error_message=str(e)
            )
        except Exception:
            pass
        raise e


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HydroSense IoT Automated Backup Runner")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, help="Path to database JSON file")
    parser.add_argument("--output-dir", default=DEFAULT_BACKUP_DIR, help="Directory to save backup files")
    parser.add_argument("--format", choices=["json", "csv", "both"], default="both", help="Export format")
    parser.add_argument("--retention-days", type=int, default=45, help="Days to retain backup files")
    parser.add_argument("--type", choices=["scheduled", "manual"], default="scheduled", help="Backup trigger type")

    args = parser.parse_args()

    try:
        summary = run_backup(
            db_path=args.db_path,
            output_dir=args.output_dir,
            file_format=args.format,
            retention_days=args.retention_days,
            backup_type=args.type
        )
        print(f"[backup SUCCESS] Created {summary['filename']} ({summary['records_count']} records, {summary['file_size_bytes']} bytes)")
        sys.exit(0)
    except Exception as exc:
        print(f"[backup ERROR] Execution failed: {exc}", file=sys.stderr)
        sys.exit(1)
