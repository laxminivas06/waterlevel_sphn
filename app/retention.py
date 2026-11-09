"""
app/retention.py - Automated 15-Day Backup & 45-Day Data Retention Subsystem
HydroSense IoT - Smart Water Tank Monitoring System v2.0
Sphoorthy Engineering College

Specifications:
1. Reliable Storage: Ensures all incoming telemetry readings are permanently stored.
2. 15-Day Automated Backups: Automatically creates a dedicated backup folder in `backups/`
   every 15 days containing a complete database dump, telemetry JSON, CSV, and metadata.
3. 45-Day Data Retention: Automatically and permanently deletes telemetry readings older
   than 45 days from the active database, preventing unbounded database growth while
   preserving historical data in backup archives.
"""

from datetime import datetime, timedelta
import json
import logging
import os
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple

from app.config import Config
from app.database import get_db, JsonDatabase
from app.time_utils import get_ist_now, get_ist_now_str

logger = logging.getLogger("hydrosense.retention")

BACKUP_CADENCE_DAYS = 15
RETENTION_DAYS = 45

# In-memory throttle to avoid checking every single second on high-frequency packets
_LAST_MAINTENANCE_CHECK: float = 0.0
_CHECK_INTERVAL_SECONDS: float = 60.0  # Check every 60 seconds during telemetry ingestion


def create_15_day_backup_snapshot(
    db: Optional[Any] = None,
    backup_dir: Optional[str] = None,
    backup_type: str = "automated_15_days"
) -> Dict[str, Any]:
    """
    Creates a dedicated timestamped backup folder in `backups/` containing:
    - `database.json`: Complete database JSON dump
    - `telemetry.json`: All telemetry records
    - `telemetry.csv`: Universal CSV export of telemetry readings
    - `metadata.json`: Backup details, timestamp, and records count
    Also creates a root JSON archive file for backward compatibility with downloads.
    """
    database = db if isinstance(db, JsonDatabase) else get_db()
    target_dir = backup_dir or Config.BACKUP_DIR
    os.makedirs(target_dir, exist_ok=True)

    now = get_ist_now()
    ts_str = now.strftime("%Y%m%d_%H%M%S")
    folder_name = f"backup_{ts_str}"
    backup_folder_path = os.path.join(target_dir, folder_name)
    os.makedirs(backup_folder_path, exist_ok=True)

    data = database.get_data()
    telemetry = data.get("telemetry", [])

    # 1. Save database.json in folder
    db_json_path = os.path.join(backup_folder_path, "database.json")
    with open(db_json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # 2. Save telemetry.json in folder
    telemetry_json_path = os.path.join(backup_folder_path, "telemetry.json")
    with open(telemetry_json_path, "w", encoding="utf-8") as f:
        json.dump(telemetry, f, indent=2, ensure_ascii=False)

    # 3. Save telemetry.csv in folder
    import csv
    telemetry_csv_path = os.path.join(backup_folder_path, "telemetry.csv")
    with open(telemetry_csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "id", "device_id", "tank_id", "distance_cm", "water_height",
            "water_percentage", "water_volume", "status", "timestamp", "date"
        ])
        for r in telemetry:
            writer.writerow([
                r.get("id"),
                r.get("device_id"),
                r.get("tank_id"),
                r.get("distance_cm"),
                r.get("water_height", r.get("water_level_cm")),
                r.get("water_percentage"),
                r.get("water_volume", r.get("water_litres")),
                r.get("status"),
                r.get("timestamp"),
                r.get("date"),
            ])

    # 4. Save metadata.json
    total_size = sum(
        os.path.getsize(os.path.join(backup_folder_path, f))
        for f in os.listdir(backup_folder_path)
        if os.path.isfile(os.path.join(backup_folder_path, f))
    )
    metadata = {
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "backup_folder": folder_name,
        "backup_type": backup_type,
        "cadence_days": BACKUP_CADENCE_DAYS,
        "retention_policy_days": RETENTION_DAYS,
        "records_count": len(telemetry),
        "total_size_bytes": total_size,
    }
    with open(os.path.join(backup_folder_path, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    # 5. Copy root archive file for direct download endpoint compatibility
    single_file_name = f"backup_{ts_str}.json"
    single_file_path = os.path.join(target_dir, single_file_name)
    shutil.copyfile(db_json_path, single_file_path)

    # Log to backup_records in database
    record = {
        "backup_type": backup_type,
        "file_format": "folder",
        "filename": folder_name,
        "file_path": backup_folder_path,
        "file_size_bytes": total_size,
        "records_count": len(telemetry),
        "record_count": len(telemetry),
        "status": "success",
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    }
    database.insert("backup_records", record)
    database.insert("backup_logs", record)

    # Update system metadata
    meta = database.get("system_metadata", {})
    meta["last_automated_backup_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
    meta["last_backup_folder"] = folder_name
    database.set("system_metadata", meta)
    database.save()

    logger.info(f"Created 15-day backup folder: {folder_name} ({len(telemetry)} records)")

    return {
        "status": "success",
        "folder_name": folder_name,
        "folder_path": backup_folder_path,
        "filename": single_file_name,
        "records_count": len(telemetry),
        "size_bytes": total_size,
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
    }


def purge_telemetry_older_than(days: int = RETENTION_DAYS, db: Optional[Any] = None) -> Dict[str, Any]:
    """
    Permanently deletes telemetry and water_readings records older than `days` (default 45 days).
    Persists changes permanently to disk.
    """
    database = db if isinstance(db, JsonDatabase) else get_db()
    cutoff_dt = get_ist_now() - timedelta(days=days)
    cutoff_ts_str = cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")
    cutoff_date_str = cutoff_dt.strftime("%Y-%m-%d")

    data = database.get_data()
    telemetry = data.get("telemetry", [])
    water_readings = data.get("water_readings", [])

    initial_telemetry_count = len(telemetry)
    initial_readings_count = len(water_readings)

    def is_retained(rec: Dict[str, Any]) -> bool:
        ts = rec.get("timestamp")
        dt_str = rec.get("date")
        if ts:
            try:
                if str(ts) < cutoff_ts_str:
                    return False
                return True
            except Exception:
                pass
        if dt_str:
            try:
                if str(dt_str) < cutoff_date_str:
                    return False
                return True
            except Exception:
                pass
        return True

    retained_telemetry = [r for r in telemetry if is_retained(r)]
    retained_readings = [r for r in water_readings if is_retained(r)]

    purged_telemetry = initial_telemetry_count - len(retained_telemetry)
    purged_readings = initial_readings_count - len(retained_readings)

    if purged_telemetry > 0 or purged_readings > 0:
        database.set("telemetry", retained_telemetry)
        database.set("water_readings", retained_readings)

        # Record metadata
        meta = database.get("system_metadata", {})
        meta["last_purge_at"] = get_ist_now_str()
        meta["last_purged_count"] = purged_telemetry
        meta["retention_days"] = days
        database.set("system_metadata", meta)

        database.save()
        logger.info(f"Permanently purged {purged_telemetry} telemetry records older than {days} days (cutoff {cutoff_ts_str}).")

    return {
        "status": "success",
        "retention_days": days,
        "cutoff_timestamp": cutoff_ts_str,
        "purged_telemetry_count": purged_telemetry,
        "purged_readings_count": purged_readings,
        "retained_telemetry_count": len(retained_telemetry),
    }


def check_and_run_automated_maintenance(
    db: Optional[Any] = None,
    backup_cadence_days: int = BACKUP_CADENCE_DAYS,
    retention_days: int = RETENTION_DAYS,
    backup_dir: Optional[str] = None,
    force: bool = False
) -> Dict[str, Any]:
    """
    Checks if 15 days have passed since the last automated backup.
    If due or forced: creates a 15-day backup folder in backups/.
    Then permanently purges records older than 45 days.
    """
    database = db if isinstance(db, JsonDatabase) else get_db()
    now = get_ist_now()

    # Determine last backup time
    backup_records = database.get("backup_records", [])
    auto_backups = [
        b for b in backup_records
        if str(b.get("backup_type", "")).startswith("automated") and b.get("status") == "success"
    ]
    last_backup_time = None

    if auto_backups:
        sorted_b = sorted(auto_backups, key=lambda x: str(x.get("created_at", "")), reverse=True)
        try:
            last_backup_time = datetime.strptime(sorted_b[0]["created_at"], "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    if not last_backup_time:
        meta = database.get("system_metadata", {})
        last_meta = meta.get("last_automated_backup_at")
        if last_meta:
            try:
                last_backup_time = datetime.strptime(last_meta, "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

    backup_needed = False
    if force or not last_backup_time:
        backup_needed = True
    else:
        days_since_backup = (now - last_backup_time).total_seconds() / 86400.0
        if days_since_backup >= backup_cadence_days:
            backup_needed = True

    backup_result = None
    if backup_needed:
        try:
            backup_result = create_15_day_backup_snapshot(backup_dir=backup_dir, db=database)
        except Exception as e:
            logger.error(f"Automated 15-day backup failed: {e}")
            backup_result = {"status": "error", "error": str(e)}

    # Always enforce 45-day retention purge
    purge_result = None
    try:
        purge_result = purge_telemetry_older_than(days=retention_days, db=database)
    except Exception as e:
        logger.error(f"45-day telemetry purge failed: {e}")
        purge_result = {"status": "error", "error": str(e)}

    is_backup_ok = backup_needed and bool(backup_result and backup_result.get("status") == "success")
    folder_name = (backup_result or {}).get("folder_name")
    purged_count = (purge_result or {}).get("purged_telemetry_count", 0)

    return {
        "status": "success",
        "success": True,
        "backup_performed": backup_needed,
        "backup_created": is_backup_ok,
        "backup_folder": folder_name,
        "purged_records": purged_count,
        "backup": backup_result,
        "purge": purge_result,
        "checked_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    }


def trigger_scheduled_maintenance_if_due(db: Optional[Any] = None) -> None:
    """
    Lightweight maintenance hook called during telemetry ingestion.
    Throttled to run at most once per minute to avoid overhead.
    """
    global _LAST_MAINTENANCE_CHECK
    now_mono = time.monotonic()
    if (now_mono - _LAST_MAINTENANCE_CHECK) < _CHECK_INTERVAL_SECONDS:
        return

    _LAST_MAINTENANCE_CHECK = now_mono
    try:
        check_and_run_automated_maintenance(db=db)
    except Exception as e:
        logger.warning(f"Background maintenance cycle warning: {e}")
