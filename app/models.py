"""
app/models.py - Comprehensive Data Access Layer (DAL)

Implements 100% parameterized queries for devices, tank settings, water readings,
analytics aggregations, and backup logs. Supports alias normalization, atomic
multi-statement transactions, and seamless execution inside or outside Flask.
"""

from datetime import datetime, timedelta
import json
import sqlite3
from typing import Any, Dict, List, Optional, Tuple, Union

from app.database import get_db


# ==============================================================================
# 1. Device Operations
# ==============================================================================

def get_device(device_id: str, db: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    """
    Retrieves a device record by device_id.
    """
    conn = db or get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT device_id, device_name, api_key, created_at, last_seen, is_active FROM devices WHERE device_id = ?",
        (device_id,)
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def verify_api_key(device_id: str, api_key: str, db: Optional[sqlite3.Connection] = None) -> bool:
    """
    Verifies that the device exists, is active, and matches the provided API key.
    """
    if not device_id or not api_key:
        return False
    device = get_device(device_id, db=db)
    if not device:
        return False
    if device.get("is_active") != 1:
        return False
    return device.get("api_key") == api_key


def authenticate_device(
    device_id: str,
    api_key: str,
    db: Optional[sqlite3.Connection] = None
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    Detailed authentication helper returning (is_authenticated, error_reason, device_dict).
    """
    if not device_id:
        return False, "Missing device_id", None
    if not api_key:
        return False, "Missing api_key", None

    device = get_device(device_id, db=db)
    if not device:
        return False, "Device not found", None
    if device.get("is_active") != 1:
        return False, "Device is inactive", device
    if device.get("api_key") != api_key:
        return False, "Invalid API key", None

    return True, None, device


def update_last_seen(
    device_id: str,
    timestamp: Optional[str] = None,
    db: Optional[sqlite3.Connection] = None
) -> bool:
    """
    Updates the last_seen timestamp of a device.
    """
    conn = db or get_db()
    ts = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE devices SET last_seen = ? WHERE device_id = ?",
        (ts, device_id)
    )
    conn.commit()
    return cursor.rowcount > 0


def get_all_devices(
    active_only: bool = False,
    db: Optional[sqlite3.Connection] = None
) -> List[Dict[str, Any]]:
    """
    Returns all registered devices.
    """
    conn = db or get_db()
    cursor = conn.cursor()
    if active_only:
        cursor.execute("SELECT * FROM devices WHERE is_active = 1 ORDER BY created_at ASC")
    else:
        cursor.execute("SELECT * FROM devices ORDER BY created_at ASC")
    return [dict(row) for row in cursor.fetchall()]


def register_device(
    device_id: str,
    api_key: str,
    device_name: str,
    is_active: int = 1,
    db: Optional[sqlite3.Connection] = None
) -> Dict[str, Any]:
    """
    Registers a new device or updates an existing device credentials idempotently.
    """
    conn = db or get_db()
    cursor = conn.cursor()
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        """
        INSERT INTO devices (device_id, api_key, device_name, is_active, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(device_id) DO UPDATE SET
            api_key = excluded.api_key,
            device_name = excluded.device_name,
            is_active = excluded.is_active
        """,
        (device_id, api_key, device_name, is_active, now_ts)
    )
    conn.commit()
    device = get_device(device_id, db=conn)
    return device or {"device_id": device_id, "api_key": api_key, "device_name": device_name}


# ==============================================================================
# 2. Tank Settings Operations (Singleton: id=1)
# ==============================================================================

def get_tank_settings(db: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """
    Retrieves the global singleton tank settings with complete attribute aliasing.
    """
    conn = db or get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tank_settings WHERE id = 1")
    row = cursor.fetchone()

    if not row:
        # Fallback: ensure default singleton row exists
        now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("PRAGMA table_info(tank_settings);")
        existing_cols = {r[1] for r in cursor.fetchall()}
        if "total_height_cm" in existing_cols:
            cursor.execute(
                """
                INSERT OR IGNORE INTO tank_settings (
                    id, tank_height_cm, total_height_cm, sensor_offset_cm,
                    total_capacity_litres, warning_low_percent, warning_normal_percent,
                    low_threshold_percent, critical_low_threshold_percent, offline_threshold_seconds,
                    updated_at
                ) VALUES (1, 200.0, 200.0, 15.0, 1000.0, 20.0, 50.0, 20.0, 10.0, 300, ?)
                """,
                (now_ts,)
            )
        else:
            cursor.execute(
                """
                INSERT OR IGNORE INTO tank_settings (
                    id, tank_height_cm, sensor_offset_cm,
                    total_capacity_litres, low_threshold_percent,
                    critical_low_threshold_percent, offline_threshold_seconds,
                    updated_at
                ) VALUES (1, 200.0, 15.0, 1000.0, 20.0, 10.0, 300, ?)
                """,
                (now_ts,)
            )
        conn.commit()
        cursor.execute("SELECT * FROM tank_settings WHERE id = 1")
        row = cursor.fetchone()

    data = dict(row) if row else {}

    # Normalize aliases across frontend, backend, and firmware nomenclatures
    height = data.get("tank_height_cm") or data.get("total_height_cm") or 200.0
    data["tank_height_cm"] = float(height)
    data["total_height_cm"] = float(height)

    low_pct = data.get("low_threshold_percent") or data.get("warning_low_percent") or 20.0
    data["low_threshold_percent"] = float(low_pct)
    data["warning_low_percent"] = float(low_pct)

    data["warning_normal_percent"] = float(data.get("warning_normal_percent", 50.0))
    data["critical_low_threshold_percent"] = float(data.get("critical_low_threshold_percent", 10.0))
    data["sensor_offset_cm"] = float(data.get("sensor_offset_cm", 15.0))
    data["total_capacity_litres"] = float(data.get("total_capacity_litres", 1000.0))
    data["offline_threshold_seconds"] = int(data.get("offline_threshold_seconds", 300))

    return data


def update_tank_settings(
    settings_dict: Dict[str, Any],
    db: Optional[sqlite3.Connection] = None
) -> Dict[str, Any]:
    """
    Updates the global singleton tank settings with boundary validation and column whitelist.
    """
    conn = db or get_db()
    current = get_tank_settings(db=conn)

    # Reconcile alias inputs
    new_height = settings_dict.get("tank_height_cm")
    if new_height is None:
        new_height = settings_dict.get("total_height_cm", current["tank_height_cm"])

    new_offset = settings_dict.get("sensor_offset_cm", current["sensor_offset_cm"])
    new_capacity = settings_dict.get("total_capacity_litres", current["total_capacity_litres"])
    new_timeout = settings_dict.get("offline_threshold_seconds", current["offline_threshold_seconds"])

    new_low_pct = settings_dict.get("low_threshold_percent")
    if new_low_pct is None:
        new_low_pct = settings_dict.get("warning_low_percent", current["low_threshold_percent"])

    new_normal_pct = settings_dict.get("warning_normal_percent", current["warning_normal_percent"])
    new_critical_pct = settings_dict.get("critical_low_threshold_percent", current["critical_low_threshold_percent"])

    # Physical Boundary Validations
    try:
        new_height = float(new_height)
        new_offset = float(new_offset)
        new_capacity = float(new_capacity)
        new_timeout = int(new_timeout)
        new_low_pct = float(new_low_pct)
        new_normal_pct = float(new_normal_pct)
        new_critical_pct = float(new_critical_pct)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Numeric validation failed for settings parameters: {e}")

    if new_height <= 0.0:
        raise ValueError("Tank height must be strictly positive.")
    if new_offset < 0.0:
        raise ValueError("Sensor offset cannot be negative.")
    if new_capacity <= 0.0:
        raise ValueError("Total capacity must be strictly positive.")
    if new_timeout < 10:
        raise ValueError("Offline threshold seconds must be at least 10 seconds.")
    if not (0.0 <= new_low_pct <= 100.0):
        raise ValueError("Low threshold percent must be between 0.0 and 100.0.")
    if not (0.0 <= new_normal_pct <= 100.0):
        raise ValueError("Normal threshold percent must be between 0.0 and 100.0.")

    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(tank_settings);")
    existing_cols = {r[1] for r in cursor.fetchall()}

    fields = ["tank_height_cm = ?", "sensor_offset_cm = ?", "total_capacity_litres = ?",
              "offline_threshold_seconds = ?", "low_threshold_percent = ?",
              "critical_low_threshold_percent = ?", "updated_at = ?"]
    params = [new_height, new_offset, new_capacity, new_timeout, new_low_pct, new_critical_pct, now_ts]

    if "total_height_cm" in existing_cols:
        fields.append("total_height_cm = ?")
        params.append(new_height)
    if "warning_low_percent" in existing_cols:
        fields.append("warning_low_percent = ?")
        params.append(new_low_pct)
    if "warning_normal_percent" in existing_cols:
        fields.append("warning_normal_percent = ?")
        params.append(new_normal_pct)

    params.append(1)
    cursor.execute(f"UPDATE tank_settings SET {', '.join(fields)} WHERE id = ?", tuple(params))
    conn.commit()
    return get_tank_settings(db=conn)


# ==============================================================================
# 3. Water Readings Telemetry Operations
# ==============================================================================

def insert_water_reading(
    reading_data: Dict[str, Any],
    db: Optional[sqlite3.Connection] = None
) -> Dict[str, Any]:
    """
    Inserts a validated telemetry reading and atomically updates the device's last_seen.
    """
    conn = db or get_db()
    device_id = reading_data.get("device_id")
    if not device_id or not str(device_id).strip():
        raise ValueError("Missing or empty device_id in telemetry payload.")

    try:
        distance_cm = float(reading_data["distance_cm"])
        water_level_cm = float(reading_data["water_level_cm"])
        water_percentage = float(reading_data["water_percentage"])
        water_litres = float(reading_data["water_litres"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid physical measurement values in payload: {exc}")

    # Enforce physical bounds before DB insertion
    if distance_cm < 0.0:
        raise ValueError(f"distance_cm cannot be negative: {distance_cm}")
    if water_level_cm < 0.0:
        raise ValueError(f"water_level_cm cannot be negative: {water_level_cm}")
    if not (0.0 <= water_percentage <= 100.0):
        raise ValueError(f"water_percentage must be between 0.0 and 100.0: {water_percentage}")
    if water_litres < 0.0:
        raise ValueError(f"water_litres cannot be negative: {water_litres}")

    timestamp = reading_data.get("timestamp") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_str = reading_data.get("date") or timestamp[:10]
    raw_json = reading_data.get("raw_reading_json")
    if raw_json is None and isinstance(reading_data, dict):
        raw_json = json.dumps(reading_data)

    cursor = conn.cursor()
    try:
        cursor.execute("PRAGMA table_info(water_readings);")
        wr_cols = {r[1] for r in cursor.fetchall()}
        if "raw_reading_json" in wr_cols:
            cursor.execute(
                """
                INSERT INTO water_readings (
                    device_id, distance_cm, water_level_cm, water_percentage,
                    water_litres, timestamp, date, raw_reading_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (device_id, distance_cm, water_level_cm, water_percentage, water_litres, timestamp, date_str, raw_json)
            )
        else:
            cursor.execute(
                """
                INSERT INTO water_readings (
                    device_id, distance_cm, water_level_cm, water_percentage,
                    water_litres, timestamp, date
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (device_id, distance_cm, water_level_cm, water_percentage, water_litres, timestamp, date_str)
            )
        reading_id = cursor.lastrowid

        # Automatically update device last_seen timestamp in the same transaction
        cursor.execute(
            "UPDATE devices SET last_seen = ? WHERE device_id = ?",
            (timestamp, device_id)
        )

        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise exc

    return {
        "status": "success",
        "reading_id": reading_id,
        "id": reading_id,
        "timestamp": timestamp,
        "date": date_str
    }


def get_latest_reading(
    device_id: Optional[str] = None,
    db: Optional[sqlite3.Connection] = None
) -> Optional[Dict[str, Any]]:
    """
    Retrieves the most recent water reading (overall or for a specific device).
    """
    conn = db or get_db()
    cursor = conn.cursor()
    if device_id:
        cursor.execute(
            "SELECT * FROM water_readings WHERE device_id = ? ORDER BY timestamp DESC, id DESC LIMIT 1",
            (device_id,)
        )
    else:
        cursor.execute(
            "SELECT * FROM water_readings ORDER BY timestamp DESC, id DESC LIMIT 1"
        )
    row = cursor.fetchone()
    return dict(row) if row else None


def get_readings_by_date(
    date_str: str,
    device_id: Optional[str] = None,
    limit: Optional[int] = None,
    db: Optional[sqlite3.Connection] = None
) -> List[Dict[str, Any]]:
    """
    Retrieves chronological intraday readings for a given date (YYYY-MM-DD).
    """
    conn = db or get_db()
    cursor = conn.cursor()
    query = "SELECT * FROM water_readings WHERE date = ?"
    params = [date_str]

    if device_id:
        query += " AND device_id = ?"
        params.append(device_id)

    query += " ORDER BY timestamp ASC, id ASC"

    if limit is not None and limit > 0:
        query += " LIMIT ?"
        params.append(limit)

    cursor.execute(query, tuple(params))
    return [dict(row) for row in cursor.fetchall()]


# ==============================================================================
# 4. Historical Analytics & Aggregates
# ==============================================================================

def get_daily_stats(
    days: int = 15,
    device_id: Optional[str] = None,
    db: Optional[sqlite3.Connection] = None
) -> List[Dict[str, Any]]:
    """
    Calculates daily minimum, maximum, and average metrics for the past N calendar days.
    """
    conn = db or get_db()
    cursor = conn.cursor()

    cutoff_date = (datetime.now() - timedelta(days=max(0, days - 1))).strftime("%Y-%m-%d")

    query = """
        SELECT
            date,
            COUNT(*) as reading_count,
            ROUND(MIN(water_level_cm), 2) as min_level_cm,
            ROUND(MAX(water_level_cm), 2) as max_level_cm,
            ROUND(AVG(water_level_cm), 2) as avg_level_cm,
            ROUND(MIN(water_percentage), 2) as min_percentage,
            ROUND(MAX(water_percentage), 2) as max_percentage,
            ROUND(AVG(water_percentage), 2) as avg_percentage,
            ROUND(MIN(water_litres), 2) as min_litres,
            ROUND(MAX(water_litres), 2) as max_litres,
            ROUND(AVG(water_litres), 2) as avg_litres
        FROM water_readings
        WHERE date >= ?
    """
    params = [cutoff_date]

    if device_id:
        query += " AND device_id = ?"
        params.append(device_id)

    query += " GROUP BY date ORDER BY date ASC"

    cursor.execute(query, tuple(params))
    return [dict(row) for row in cursor.fetchall()]


def compare_dates(
    date1_str: str,
    date2_str: str,
    device_id: Optional[str] = None,
    db: Optional[sqlite3.Connection] = None
) -> Dict[str, Any]:
    """
    Compares telemetry statistics between two dates side-by-side.
    """
    conn = db or get_db()

    def _fetch_single_day(target_date: str) -> Dict[str, Any]:
        cursor = conn.cursor()
        q = """
            SELECT
                COUNT(*) as reading_count,
                ROUND(MIN(water_level_cm), 2) as min_level_cm,
                ROUND(MAX(water_level_cm), 2) as max_level_cm,
                ROUND(AVG(water_level_cm), 2) as avg_level_cm,
                ROUND(MIN(water_percentage), 2) as min_percentage,
                ROUND(MAX(water_percentage), 2) as max_percentage,
                ROUND(AVG(water_percentage), 2) as avg_percentage,
                ROUND(MIN(water_litres), 2) as min_litres,
                ROUND(MAX(water_litres), 2) as max_litres,
                ROUND(AVG(water_litres), 2) as avg_litres
            FROM water_readings
            WHERE date = ?
        """
        p = [target_date]
        if device_id:
            q += " AND device_id = ?"
            p.append(device_id)
        cursor.execute(q, tuple(p))
        row = cursor.fetchone()
        res = dict(row) if row else {}
        if not res.get("reading_count"):
            res["reading_count"] = 0
            res["min_level_cm"] = 0.0
            res["max_level_cm"] = 0.0
            res["avg_level_cm"] = 0.0
            res["min_percentage"] = 0.0
            res["max_percentage"] = 0.0
            res["avg_percentage"] = 0.0
            res["min_litres"] = 0.0
            res["max_litres"] = 0.0
            res["avg_litres"] = 0.0
        return res

    stats1 = _fetch_single_day(date1_str)
    stats2 = _fetch_single_day(date2_str)

    count1 = stats1.get("reading_count", 0)
    count2 = stats2.get("reading_count", 0)

    if count1 == 0 or count2 == 0:
        avg_pct_diff = 0.0
        avg_litres_diff = 0.0
        max_litres_diff = 0.0
        trend = "insufficient_data"
    else:
        avg_pct_diff = round(stats2["avg_percentage"] - stats1["avg_percentage"], 2)
        avg_litres_diff = round(stats2["avg_litres"] - stats1["avg_litres"], 2)
        max_litres_diff = round(stats2["max_litres"] - stats1["max_litres"], 2)
        if avg_litres_diff > 0:
            trend = "increasing"
        elif avg_litres_diff < 0:
            trend = "decreasing"
        else:
            trend = "neutral"

    return {
        "date1": {
            "date": date1_str,
            "readings_count": count1,
            "summary": stats1
        },
        "date2": {
            "date": date2_str,
            "readings_count": count2,
            "summary": stats2
        },
        "comparison": {
            "avg_percentage_diff": avg_pct_diff,
            "avg_litres_diff": avg_litres_diff,
            "max_litres_diff": max_litres_diff,
            "trend": trend
        }
    }


def get_today_summary(
    device_id: Optional[str] = None,
    date_str: Optional[str] = None,
    db: Optional[sqlite3.Connection] = None
) -> Dict[str, Any]:
    """
    Computes today's summary scorecard including reading count, min/max/avg, and net change in litres.
    """
    conn = db or get_db()
    cursor = conn.cursor()
    target_date = date_str or datetime.now().strftime("%Y-%m-%d")

    q = """
        SELECT
            COUNT(*) as reading_count,
            ROUND(MIN(water_level_cm), 2) as min_level_cm,
            ROUND(MAX(water_level_cm), 2) as max_level_cm,
            ROUND(AVG(water_level_cm), 2) as avg_level_cm,
            ROUND(MIN(water_percentage), 2) as min_percentage,
            ROUND(MAX(water_percentage), 2) as max_percentage,
            ROUND(AVG(water_percentage), 2) as avg_percentage,
            ROUND(MIN(water_litres), 2) as min_litres,
            ROUND(MAX(water_litres), 2) as max_litres,
            ROUND(AVG(water_litres), 2) as avg_litres
        FROM water_readings
        WHERE date = ?
    """
    params = [target_date]
    if device_id:
        q += " AND device_id = ?"
        params.append(device_id)

    cursor.execute(q, tuple(params))
    summary = dict(cursor.fetchone() or {})
    count = summary.get("reading_count") or 0
    summary["date"] = target_date

    # Net change calculation: difference between latest and earliest reading of the day
    net_change_litres = 0.0
    if count > 1:
        # Earliest reading
        eq = "SELECT water_litres FROM water_readings WHERE date = ?"
        ep = [target_date]
        if device_id:
            eq += " AND device_id = ?"
            ep.append(device_id)
        eq += " ORDER BY timestamp ASC, id ASC LIMIT 1"
        cursor.execute(eq, tuple(ep))
        earliest_row = cursor.fetchone()

        # Latest reading
        lq = "SELECT water_litres FROM water_readings WHERE date = ?"
        lp = [target_date]
        if device_id:
            lq += " AND device_id = ?"
            lp.append(device_id)
        lq += " ORDER BY timestamp DESC, id DESC LIMIT 1"
        cursor.execute(lq, tuple(lp))
        latest_row = cursor.fetchone()

        if earliest_row and latest_row:
            net_change_litres = round(latest_row["water_litres"] - earliest_row["water_litres"], 2)

    summary["net_change_litres"] = net_change_litres
    return summary


# ==============================================================================
# 5. Backup Log Operations
# ==============================================================================

def insert_backup_log(
    backup_type: str,
    file_format: str,
    filename: str,
    file_path: str,
    file_size_bytes: int,
    records_count: int,
    status: str,
    error_message: Optional[str] = None,
    db: Optional[sqlite3.Connection] = None
) -> int:
    """
    Inserts an audit record into backup_logs and returns the new log id.
    """
    conn = db or get_db()
    cursor = conn.cursor()
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        """
        INSERT INTO backup_logs (
            backup_type, file_format, format, filename,
            file_path, filepath, file_size_bytes, records_count, record_count,
            status, error_message, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            backup_type, file_format, file_format, filename,
            file_path, file_path, file_size_bytes, records_count, records_count,
            status, error_message, now_ts
        )
    )
    conn.commit()
    return cursor.lastrowid


def get_backup_logs(
    limit: int = 50,
    offset: int = 0,
    db: Optional[sqlite3.Connection] = None
) -> List[Dict[str, Any]]:
    """
    Retrieves recent backup audit log records ordered newest first.
    """
    conn = db or get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM backup_logs ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        (limit, offset)
    )
    return [dict(row) for row in cursor.fetchall()]


def get_backup_by_filename(
    filename: str,
    db: Optional[sqlite3.Connection] = None
) -> Optional[Dict[str, Any]]:
    """
    Queries backup logs by exact filename for secure path verification before downloading.
    """
    conn = db or get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM backup_logs WHERE filename = ? ORDER BY id DESC LIMIT 1",
        (filename,)
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def get_total_readings_count(db: Optional[sqlite3.Connection] = None) -> int:
    """
    Returns the total count of telemetry records stored in water_readings.
    """
    conn = db or get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM water_readings")
    row = cursor.fetchone()
    return int(row[0]) if row else 0
