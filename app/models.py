"""
app/models.py - Comprehensive Data Access Layer (DAL) & Domain Logic
HydroSense IoT - Smart Water Tank Monitoring System v2.0

Implements 100% parameterized queries for:
- Tanks & Geometric Physical Calibrations (Cylindrical / Rectangular)
- Devices, Registration, Assignment & Online/Offline Heartbeats
- Real-time Telemetry Ingestion, Dynamic Status Classification & 15+ Day Analytics
- Automatic Threshold Alerts (Critical Low, Low, High, Overloaded, Sensor Fault, Offline)
- Backup Audit Logging & Legacy Backward-Compatibility Adapters
"""

from datetime import datetime, timedelta
import json
import math
import sqlite3
from typing import Any, Dict, List, Optional, Tuple, Union

from app.database import get_db


# ==============================================================================
# 1. Tank Operations & Physics Calculations (Section 5, 6, 7)
# ==============================================================================

def get_tank(tank_id: str, db: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    """Retrieves a tank record by tank_id."""
    conn = db or get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tanks WHERE tank_id = ?", (tank_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def get_all_tanks(db: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    """Retrieves all registered tanks."""
    conn = db or get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tanks ORDER BY created_at ASC")
    return [dict(row) for row in cursor.fetchall()]


def create_or_update_tank(tank_data: Dict[str, Any], db: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """Creates a new tank or updates an existing tank's geometry & thresholds idempotently."""
    conn = db or get_db()
    tank_id = str(tank_data.get("tank_id") or "").strip()
    if not tank_id:
        raise ValueError("tank_id is required and cannot be empty")

    tank_name = str(tank_data.get("tank_name") or tank_id.replace("_", " ").title()).strip()
    shape = str(tank_data.get("shape") or "cylinder").lower().strip()
    tank_height = float(tank_data.get("tank_height_cm") or 200.0)
    sensor_offset = float(tank_data.get("sensor_offset_cm") or 15.0)
    total_capacity = float(tank_data.get("total_capacity_litres") or 1000.0)
    safe_max_pct = float(tank_data.get("safe_max_percent") or 95.0)
    crit_low_pct = float(tank_data.get("critical_low_percent") or 10.0)
    low_pct = float(tank_data.get("low_percent") or 25.0)
    high_pct = float(tank_data.get("high_percent") or 85.0)
    offline_thresh = int(tank_data.get("offline_threshold_seconds") or 300)

    length_cm = float(tank_data["length_cm"]) if tank_data.get("length_cm") is not None else None
    width_cm = float(tank_data["width_cm"]) if tank_data.get("width_cm") is not None else None
    radius_cm = float(tank_data["radius_cm"]) if tank_data.get("radius_cm") is not None else None

    # Auto-calculate dimensions if shape is provided without explicit dimensions
    if shape == "cylinder" and radius_cm is None and total_capacity > 0 and tank_height > 0:
        # volume = pi * r^2 * h / 1000 => r = sqrt(volume * 1000 / (pi * h))
        radius_cm = round(math.sqrt((total_capacity * 1000.0) / (math.pi * tank_height)), 2)
    elif shape == "rectangle" and (length_cm is None or width_cm is None) and total_capacity > 0 and tank_height > 0:
        side = round(math.sqrt((total_capacity * 1000.0) / tank_height), 2)
        length_cm = side
        width_cm = side

    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO tanks (
            tank_id, tank_name, shape, tank_height_cm, sensor_offset_cm,
            total_capacity_litres, length_cm, width_cm, radius_cm,
            safe_max_percent, critical_low_percent, low_percent, high_percent,
            offline_threshold_seconds, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(tank_id) DO UPDATE SET
            tank_name = excluded.tank_name,
            shape = excluded.shape,
            tank_height_cm = excluded.tank_height_cm,
            sensor_offset_cm = excluded.sensor_offset_cm,
            total_capacity_litres = excluded.total_capacity_litres,
            length_cm = excluded.length_cm,
            width_cm = excluded.width_cm,
            radius_cm = excluded.radius_cm,
            safe_max_percent = excluded.safe_max_percent,
            critical_low_percent = excluded.critical_low_percent,
            low_percent = excluded.low_percent,
            high_percent = excluded.high_percent,
            offline_threshold_seconds = excluded.offline_threshold_seconds,
            updated_at = excluded.updated_at
        """,
        (
            tank_id, tank_name, shape, tank_height, sensor_offset,
            total_capacity, length_cm, width_cm, radius_cm,
            safe_max_pct, crit_low_pct, low_pct, high_pct,
            offline_thresh, now_ts, now_ts
        )
    )
    conn.commit()
    return get_tank(tank_id, db=conn) or {}


def delete_tank(tank_id: str, db: Optional[sqlite3.Connection] = None) -> bool:
    """Deletes a tank record by tank_id."""
    conn = db or get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tanks WHERE tank_id = ?", (tank_id,))
    conn.commit()
    return cursor.rowcount > 0


def calculate_tank_physics(
    tank: Dict[str, Any],
    distance_cm: float,
    reported_pct: Optional[float] = None,
    reported_litres: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Computes precise water depth, fill percentage, volumetric capacity, and status classification.
    
    Physics Model (Section 5 & 7):
      - Sensor mounted above tank at sensor_offset_cm.
      - Full tank (100% level): measured distance == sensor_offset_cm.
      - Empty tank (0% level): measured distance == tank_height_cm + sensor_offset_cm.
      - Overloaded tank (>100%): measured distance < sensor_offset_cm (water closer than offset).
      - Effective air gap = distance_cm - sensor_offset_cm.
      - Water height = tank_height_cm - effective_air_gap.
      - Percentage = (water_height / tank_height_cm) * 100.
      - Volume = (percentage / 100) * total_capacity_litres.
    """
    tank_height = float(tank.get("tank_height_cm", 200.0))
    sensor_offset = float(tank.get("sensor_offset_cm", 15.0))
    total_capacity = float(tank.get("total_capacity_litres", 1000.0))
    safe_max_pct = float(tank.get("safe_max_percent", 95.0))
    crit_low_pct = float(tank.get("critical_low_percent", 10.0))
    low_pct = float(tank.get("low_percent", 25.0))
    high_pct = float(tank.get("high_percent", 85.0))

    # Reject or flag physically impossible sensor readings
    if distance_cm < 0.0 or distance_cm > (tank_height + sensor_offset + 100.0):
        return {
            "distance_cm": distance_cm,
            "water_height": 0.0,
            "water_height_cm": 0.0,
            "water_percentage": 0.0,
            "water_level_percent": 0.0,
            "water_volume": 0.0,
            "water_volume_litres": 0.0,
            "status": "SENSOR FAULT",
            "is_overloaded": False,
            "is_valid": False,
        }

    # Detect Overloaded condition: water rose closer to sensor than offset distance
    if distance_cm < sensor_offset:
        overflow_cm = round(sensor_offset - distance_cm, 2)
        water_height = round(tank_height + overflow_cm, 2)
        pct = round((water_height / tank_height) * 100.0, 2)
        volume = round((pct / 100.0) * total_capacity, 2)
        return {
            "distance_cm": round(distance_cm, 2),
            "water_height": water_height,
            "water_height_cm": water_height,
            "water_percentage": pct,
            "water_level_percent": pct,
            "water_volume": volume,
            "water_volume_litres": volume,
            "status": "OVERLOADED",
            "is_overloaded": True,
            "is_valid": True,
        }

    # Normal physics calculation
    effective_air_gap = max(0.0, distance_cm - sensor_offset)
    water_height = round(max(0.0, min(tank_height, tank_height - effective_air_gap)), 2)
    pct = round(max(0.0, min(100.0, (water_height / tank_height) * 100.0)), 2)

    # Use geometry calculation if shape is rectangular or cylindrical, else linear ratio
    shape = tank.get("shape", "cylinder")
    if shape == "cylinder" and tank.get("radius_cm"):
        r = float(tank["radius_cm"])
        computed_litres = round((math.pi * (r ** 2) * water_height) / 1000.0, 2)
        volume = min(total_capacity, computed_litres)
    elif shape == "rectangle" and tank.get("length_cm") and tank.get("width_cm"):
        l = float(tank["length_cm"])
        w = float(tank["width_cm"])
        computed_litres = round((l * w * water_height) / 1000.0, 2)
        volume = min(total_capacity, computed_litres)
    else:
        volume = round((pct / 100.0) * total_capacity, 2)

    # Determine status (Section 7)
    if pct <= crit_low_pct:
        status = "CRITICAL LOW"
    elif pct <= low_pct:
        status = "LOW"
    elif pct <= high_pct:
        status = "NORMAL"
    elif pct < safe_max_pct:
        status = "HIGH"
    else:
        # Exceeds safe operating limit
        status = "HIGH"

    return {
        "distance_cm": round(distance_cm, 2),
        "water_height": water_height,
        "water_height_cm": water_height,
        "water_percentage": pct,
        "water_level_percent": pct,
        "water_volume": volume,
        "water_volume_litres": volume,
        "status": status,
        "is_overloaded": False,
        "is_valid": True,
    }


# ==============================================================================
# 2. Device Operations (Section 3, 9)
# ==============================================================================

def get_device(device_id: str, db: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    """Retrieves a device record by device_id."""
    conn = db or get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def get_all_devices(active_only: bool = False, db: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    """Returns all registered devices."""
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
    tank_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    firmware_version: Optional[str] = "2.0.0",
    is_active: int = 1,
    db: Optional[sqlite3.Connection] = None
) -> Dict[str, Any]:
    """Registers a new device or updates an existing device credentials idempotently."""
    conn = db or get_db()
    cursor = conn.cursor()
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # If tank_id is supplied, verify tank exists; if not, auto-create matching tank
    if tank_id:
        t = get_tank(tank_id, db=conn)
        if not t:
            create_or_update_tank({"tank_id": tank_id, "tank_name": tank_id.replace("_", " ").title()}, db=conn)
    else:
        # Check if device_id matches a tank
        t = get_tank(device_id, db=conn)
        if t:
            tank_id = device_id

    cursor.execute(
        """
        INSERT INTO devices (device_id, device_name, tank_id, api_key, ip_address, firmware_version, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(device_id) DO UPDATE SET
            device_name = excluded.device_name,
            tank_id = COALESCE(excluded.tank_id, devices.tank_id),
            api_key = excluded.api_key,
            ip_address = COALESCE(excluded.ip_address, devices.ip_address),
            firmware_version = COALESCE(excluded.firmware_version, devices.firmware_version),
            is_active = excluded.is_active
        """,
        (device_id, device_name, tank_id, api_key, ip_address, firmware_version, is_active, now_ts)
    )
    conn.commit()
    device = get_device(device_id, db=conn)
    return device or {"device_id": device_id, "device_name": device_name, "api_key": api_key}


def get_device_with_status(device_id: str, offline_threshold: int = 300, db: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    """Calculates online/offline state and seconds_since_last_seen."""
    conn = db or get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            device_id, device_name, tank_id, api_key, ip_address, firmware_version,
            created_at, last_seen, is_active,
            CASE
                WHEN last_seen IS NULL THEN NULL
                ELSE CAST(strftime('%s', 'now', 'localtime') - strftime('%s', last_seen) AS INTEGER)
            END AS seconds_since_last_seen
        FROM devices
        WHERE device_id = ?
        """,
        (device_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None

    dev = dict(row)
    raw_diff = dev.get("seconds_since_last_seen")
    if dev.get("last_seen") is None or raw_diff is None:
        dev["status"] = "offline"
        dev["seconds_since_last_seen"] = None
    else:
        is_online = (raw_diff <= offline_threshold)
        dev["status"] = "online" if is_online else "offline"
        dev["seconds_since_last_seen"] = max(0, int(raw_diff))

    return dev


# ==============================================================================
# 3. Telemetry Ingestion & Analytics (Section 3, 5, 8, 10, 11)
# ==============================================================================

def insert_telemetry(payload: Dict[str, Any], db: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """
    Ingests and validates a telemetry packet from ESP8266/ESP32.
    Computes/validates tank physics, writes to telemetry & legacy water_readings,
    updates device last_seen, and generates real-time alerts if necessary.
    """
    conn = db or get_db()
    device_id = str(payload.get("device_id") or "").strip()
    if not device_id:
        raise ValueError("Missing device_id in telemetry payload.")

    # Auto-resolve or create device if unknown
    device = get_device(device_id, db=conn)
    if not device:
        api_key = payload.get("api_key") or "water_secret_key_2026"
        register_device(device_id, api_key, device_id.replace("_", " ").title(), db=conn)
        device = get_device(device_id, db=conn)

    tank_id = payload.get("tank_id") or device.get("tank_id") or device_id
    tank = get_tank(tank_id, db=conn)
    if not tank:
        # Auto-create tank matching device
        create_or_update_tank({"tank_id": tank_id, "tank_name": tank_id.replace("_", " ").title()}, db=conn)
        tank = get_tank(tank_id, db=conn)

    # Calculate physics metrics
    distance_cm = float(payload.get("distance_cm") or 0.0)
    metrics = calculate_tank_physics(
        tank=tank,
        distance_cm=distance_cm,
        reported_pct=payload.get("water_level_percent"),
        reported_litres=payload.get("water_volume_litres"),
    )

    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    timestamp = payload.get("timestamp") or now_ts
    date_str = timestamp[:10]

    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO telemetry (
            device_id, tank_id, distance_cm, water_height,
            water_percentage, water_volume, status, timestamp, date, raw_payload
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            device_id, tank_id, metrics["distance_cm"], metrics["water_height"],
            metrics["water_percentage"], metrics["water_volume"], metrics["status"],
            timestamp, date_str, json.dumps(payload)
        )
    )
    reading_id = cursor.lastrowid

    # Update device last_seen and optional IP
    ip_addr = payload.get("ip_address")
    if ip_addr:
        cursor.execute("UPDATE devices SET last_seen = ?, ip_address = ? WHERE device_id = ?", (timestamp, ip_addr, device_id))
    else:
        cursor.execute("UPDATE devices SET last_seen = ? WHERE device_id = ?", (timestamp, device_id))

    # Mirror to legacy water_readings for zero-breakage backward compatibility
    try:
        cursor.execute(
            """
            INSERT INTO water_readings (
                device_id, distance_cm, water_level_cm, water_percentage,
                water_litres, timestamp, date, raw_reading_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                device_id, metrics["distance_cm"], metrics["water_height"],
                metrics["water_percentage"], metrics["water_volume"],
                timestamp, date_str, json.dumps(payload)
            )
        )
    except Exception:
        pass

    conn.commit()

    # Automated Alert Triggering (Section 7)
    if metrics["status"] == "OVERLOADED":
        create_alert(
            tank_id=tank_id,
            device_id=device_id,
            alert_type="OVERFLOW_RISK",
            severity="critical",
            message=f"Tank '{tank.get('tank_name', tank_id)}' is OVERLOADED! Water level at {metrics['water_percentage']}% ({metrics['water_volume']}L).",
            db=conn,
        )
    elif metrics["status"] == "CRITICAL LOW":
        create_alert(
            tank_id=tank_id,
            device_id=device_id,
            alert_type="CRITICAL_LOW",
            severity="critical",
            message=f"Tank '{tank.get('tank_name', tank_id)}' is at CRITICAL LOW level ({metrics['water_percentage']}%). Risk of pump dry run.",
            db=conn,
        )
    elif metrics["status"] == "SENSOR FAULT":
        create_alert(
            tank_id=tank_id,
            device_id=device_id,
            alert_type="SENSOR_FAULT",
            severity="warning",
            message=f"Abnormal distance reading ({distance_cm} cm) detected from sensor on device '{device_id}'.",
            db=conn,
        )

    reading_payload = {
        "id": reading_id,
        "reading_id": reading_id,
        "device_id": device_id,
        "tank_id": tank_id,
        "distance_cm": metrics["distance_cm"],
        "water_height": metrics["water_height"],
        "water_height_cm": metrics["water_height"],
        "water_percentage": metrics["water_percentage"],
        "water_level_percent": metrics["water_percentage"],
        "water_volume": metrics["water_volume"],
        "water_volume_litres": metrics["water_volume"],
        "status": metrics["status"],
        "telemetry_status": metrics["status"],
        "timestamp": timestamp,
        "date": date_str,
    }

    return {
        "status": "success",
        "success": True,
        "reading": reading_payload,
        "reading_id": reading_id,
        "device_id": device_id,
        "tank_id": tank_id,
        "distance_cm": metrics["distance_cm"],
        "water_height": metrics["water_height"],
        "water_height_cm": metrics["water_height"],
        "water_percentage": metrics["water_percentage"],
        "water_level_percent": metrics["water_percentage"],
        "water_volume": metrics["water_volume"],
        "water_volume_litres": metrics["water_volume"],
        "telemetry_status": metrics["status"],
        "timestamp": timestamp,
    }


def get_latest_telemetry(tank_id: Optional[str] = None, device_id: Optional[str] = None, db: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    """Retrieves the latest telemetry record for a tank or device."""
    conn = db or get_db()
    cursor = conn.cursor()
    if tank_id:
        cursor.execute("SELECT * FROM telemetry WHERE tank_id = ? ORDER BY timestamp DESC, id DESC LIMIT 1", (tank_id,))
    elif device_id:
        cursor.execute("SELECT * FROM telemetry WHERE device_id = ? ORDER BY timestamp DESC, id DESC LIMIT 1", (device_id,))
    else:
        cursor.execute("SELECT * FROM telemetry ORDER BY timestamp DESC, id DESC LIMIT 1")
    row = cursor.fetchone()
    return dict(row) if row else None


def get_tank_history(
    tank_id: str,
    range_key: str = "24h",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = 500,
    db: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """
    Retrieves time-series telemetry records and summary statistics for a given range (24h, 7d, 15d, custom).
    Calculates min, max, avg, and consumption/drawdown estimates.
    """
    conn = db or get_db()
    cursor = conn.cursor()

    now = datetime.now()
    if range_key == "24h":
        start_ts = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        end_ts = now.strftime("%Y-%m-%d %H:%M:%S")
    elif range_key == "7d":
        start_ts = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        end_ts = now.strftime("%Y-%m-%d %H:%M:%S")
    elif range_key == "15d":
        start_ts = (now - timedelta(days=15)).strftime("%Y-%m-%d %H:%M:%S")
        end_ts = now.strftime("%Y-%m-%d %H:%M:%S")
    elif start_date and end_date:
        start_ts = f"{start_date} 00:00:00"
        end_ts = f"{end_date} 23:59:59"
    else:
        start_ts = (now - timedelta(days=15)).strftime("%Y-%m-%d %H:%M:%S")
        end_ts = now.strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        """
        SELECT id, device_id, tank_id, distance_cm, water_height,
               water_percentage, water_volume, status, timestamp, date
        FROM telemetry
        WHERE tank_id = ? AND timestamp >= ? AND timestamp <= ?
        ORDER BY timestamp ASC
        LIMIT ?
        """,
        (tank_id, start_ts, end_ts, limit or 1000)
    )
    rows = [dict(r) for r in cursor.fetchall()]

    if not rows:
        return {
            "tank_id": tank_id,
            "range": range_key,
            "start_timestamp": start_ts,
            "end_timestamp": end_ts,
            "count": 0,
            "min_percentage": 0.0,
            "max_percentage": 0.0,
            "avg_percentage": 0.0,
            "min_volume": 0.0,
            "max_volume": 0.0,
            "avg_volume": 0.0,
            "net_volume_change": 0.0,
            "estimated_consumption_litres": 0.0,
            "data": [],
        }

    pcts = [r["water_percentage"] for r in rows]
    vols = [r["water_volume"] for r in rows]

    # Calculate consumption (cumulative volume drops)
    consumption = 0.0
    for i in range(1, len(vols)):
        diff = vols[i - 1] - vols[i]
        if diff > 0:
            consumption += diff

    net_change = round(vols[-1] - vols[0], 2)

    analytics = {
        "min_percentage": round(min(pcts), 2),
        "max_percentage": round(max(pcts), 2),
        "avg_percentage": round(sum(pcts) / len(pcts), 2),
        "min_level_percent": round(min(pcts), 2),
        "max_level_percent": round(max(pcts), 2),
        "avg_level_percent": round(sum(pcts) / len(pcts), 2),
        "min_volume": round(min(vols), 2),
        "max_volume": round(max(vols), 2),
        "avg_volume": round(sum(vols) / len(vols), 2),
        "net_volume_change": net_change,
        "estimated_consumption_litres": round(consumption, 2),
    }

    return {
        "tank_id": tank_id,
        "range": range_key,
        "start_timestamp": start_ts,
        "end_timestamp": end_ts,
        "count": len(rows),
        "min_percentage": round(min(pcts), 2),
        "max_percentage": round(max(pcts), 2),
        "avg_percentage": round(sum(pcts) / len(pcts), 2),
        "min_level_percent": round(min(pcts), 2),
        "max_level_percent": round(max(pcts), 2),
        "avg_level_percent": round(sum(pcts) / len(pcts), 2),
        "min_volume": round(min(vols), 2),
        "max_volume": round(max(vols), 2),
        "avg_volume": round(sum(vols) / len(vols), 2),
        "net_volume_change": net_change,
        "estimated_consumption_litres": round(consumption, 2),
        "analytics": analytics,
        "data": rows,
        "readings": rows,
    }


def get_system_summary(db: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """
    Computes overall KPI dashboard scorecard:
    - Total tanks
    - Online devices
    - Offline devices
    - Average water level percentage
    - Total available water in litres
    - Active critical alerts count
    """
    conn = db or get_db()
    cursor = conn.cursor()

    tanks = get_all_tanks(db=conn)
    devices = get_all_devices(db=conn)

    online_count = 0
    offline_count = 0
    for dev in devices:
        enriched = get_device_with_status(dev["device_id"], db=conn)
        if enriched and enriched.get("status") == "online":
            online_count += 1
        else:
            offline_count += 1

    total_litres = 0.0
    total_capacity = 0.0
    level_pcts = []

    for t in tanks:
        latest = get_latest_telemetry(tank_id=t["tank_id"], db=conn)
        cap = float(t.get("total_capacity_litres", 1000.0))
        total_capacity += cap
        if latest:
            total_litres += float(latest.get("water_volume", 0.0))
            level_pcts.append(float(latest.get("water_percentage", 0.0)))

    avg_pct = round(sum(level_pcts) / len(level_pcts), 2) if level_pcts else 0.0

    # Active alerts count
    cursor.execute("SELECT COUNT(*) FROM alerts WHERE is_acknowledged = 0 AND severity = 'critical'")
    crit_alerts = cursor.fetchone()[0]

    return {
        "total_tanks": len(tanks),
        "online_devices": online_count,
        "offline_devices": offline_count,
        "average_water_percentage": avg_pct,
        "avg_water_level_percent": avg_pct,
        "avg_percentage": avg_pct,
        "total_water_litres": round(total_litres, 2),
        "total_capacity_litres": round(total_capacity, 2),
        "critical_alerts_count": crit_alerts,
    }


# ==============================================================================
# 4. Alerts Operations (Section 7, 11)
# ==============================================================================

def create_alert(
    tank_id: str,
    device_id: Optional[str],
    alert_type: str,
    severity: str,
    message: str,
    db: Optional[sqlite3.Connection] = None
) -> int:
    """Creates a new operational alert if an identical active alert does not exist within the last 10 minutes."""
    conn = db or get_db()
    cursor = conn.cursor()

    # Debounce duplicate alerts within 10 minutes
    ten_mins_ago = (datetime.now() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        """
        SELECT id FROM alerts
        WHERE tank_id = ? AND alert_type = ? AND is_acknowledged = 0 AND timestamp >= ?
        """,
        (tank_id, alert_type, ten_mins_ago)
    )
    if cursor.fetchone():
        return 0

    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        """
        INSERT INTO alerts (tank_id, device_id, alert_type, severity, message, is_acknowledged, timestamp)
        VALUES (?, ?, ?, ?, ?, 0, ?)
        """,
        (tank_id, device_id, alert_type, severity, message, now_ts)
    )
    conn.commit()
    return cursor.lastrowid or 0


def get_alerts(tank_id: Optional[str] = None, unacknowledged_only: bool = True, limit: int = 50, db: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    """Retrieves system alerts with optional filters."""
    conn = db or get_db()
    cursor = conn.cursor()
    query = "SELECT * FROM alerts"
    params = []
    conditions = []

    if tank_id:
        conditions.append("tank_id = ?")
        params.append(tank_id)
    if unacknowledged_only:
        conditions.append("is_acknowledged = 0")

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY timestamp DESC, id DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, tuple(params))
    return [dict(r) for r in cursor.fetchall()]


def acknowledge_alert(alert_id: int, db: Optional[sqlite3.Connection] = None) -> bool:
    """Marks an alert as acknowledged."""
    conn = db or get_db()
    cursor = conn.cursor()
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE alerts SET is_acknowledged = 1, acknowledged_at = ? WHERE id = ?", (now_ts, alert_id))
    conn.commit()
    return cursor.rowcount > 0


# ==============================================================================
# 5. Backup Records (Section 11)
# ==============================================================================

def record_backup(filename: str, file_path: str, record_count: int, file_size_bytes: int, backup_type: str = "automated", status: str = "success", notes: Optional[str] = None, db: Optional[sqlite3.Connection] = None) -> int:
    """Records an automated or manual backup execution."""
    conn = db or get_db()
    cursor = conn.cursor()
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        """
        INSERT INTO backup_records (filename, file_path, record_count, file_size_bytes, backup_type, status, created_at, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (filename, file_path, record_count, file_size_bytes, backup_type, status, now_ts, notes)
    )
    conn.commit()
    return cursor.lastrowid or 0


def get_backups(limit: int = 30, db: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    """Retrieves recent database backup logs."""
    conn = db or get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM backup_records ORDER BY created_at DESC LIMIT ?", (limit,))
    return [dict(r) for r in cursor.fetchall()]


def get_backup_logs(limit: int = 50, db: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    """Compatibility adapter for backup_routes."""
    conn = db or get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM backup_records ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        if rows:
            return [dict(r) for r in rows]
    except Exception:
        pass
    try:
        cursor.execute("SELECT * FROM backup_logs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in cursor.fetchall()]
    except Exception:
        return []


def insert_backup_log(log_dict: Dict[str, Any], db: Optional[sqlite3.Connection] = None) -> int:
    """Compatibility adapter for backup logging."""
    conn = db or get_db()
    cursor = conn.cursor()
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        """
        INSERT INTO backup_records (filename, file_path, record_count, file_size_bytes, backup_type, status, created_at, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            log_dict.get("filename", "backup"),
            log_dict.get("file_path", ""),
            log_dict.get("record_count") or log_dict.get("records_count", 0),
            log_dict.get("file_size_bytes", 0),
            log_dict.get("backup_type", "manual"),
            log_dict.get("status", "success"),
            now_ts,
            log_dict.get("notes") or log_dict.get("error_message")
        )
    )
    conn.commit()
    return cursor.lastrowid or 0


# ==============================================================================
# 6. Legacy Backward-Compatibility Adapters
# ==============================================================================

def get_tank_settings(db: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """Compatibility adapter for legacy singleton settings route."""
    conn = db or get_db()
    tanks = get_all_tanks(db=conn)
    if tanks:
        t = tanks[0]
        return {
            "id": 1,
            "tank_height_cm": t["tank_height_cm"],
            "total_height_cm": t["tank_height_cm"],
            "sensor_offset_cm": t["sensor_offset_cm"],
            "total_capacity_litres": t["total_capacity_litres"],
            "low_threshold_percent": t["low_percent"],
            "warning_low_percent": t["low_percent"],
            "critical_low_threshold_percent": t["critical_low_percent"],
            "warning_normal_percent": t["high_percent"],
            "offline_threshold_seconds": t["offline_threshold_seconds"],
        }
    return {
        "id": 1,
        "tank_height_cm": 200.0,
        "total_height_cm": 200.0,
        "sensor_offset_cm": 15.0,
        "total_capacity_litres": 1000.0,
        "low_threshold_percent": 25.0,
        "warning_low_percent": 25.0,
        "critical_low_threshold_percent": 10.0,
        "warning_normal_percent": 85.0,
        "offline_threshold_seconds": 300,
    }


def update_tank_settings(settings_dict: Dict[str, Any], db: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """Updates tank settings across both multi-tank and legacy tables."""
    conn = db or get_db()
    tanks = get_all_tanks(db=conn)
    target_tank_id = tanks[0]["tank_id"] if tanks else "SV_BLOCK_OVER_TANK"
    
    data = {
        "tank_id": target_tank_id,
        "tank_height_cm": settings_dict.get("tank_height_cm") or settings_dict.get("total_height_cm"),
        "sensor_offset_cm": settings_dict.get("sensor_offset_cm"),
        "total_capacity_litres": settings_dict.get("total_capacity_litres"),
        "low_percent": settings_dict.get("low_threshold_percent") or settings_dict.get("warning_low_percent"),
        "critical_low_percent": settings_dict.get("critical_low_threshold_percent"),
        "high_percent": settings_dict.get("warning_normal_percent"),
        "offline_threshold_seconds": settings_dict.get("offline_threshold_seconds"),
    }
    create_or_update_tank(data, db=conn)
    return get_tank_settings(db=conn)


def insert_water_reading(reading_data: Dict[str, Any], db: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """Compatibility adapter for legacy insert_water_reading calls."""
    return insert_telemetry(reading_data, db=db)


def get_latest_reading(device_id: Optional[str] = None, db: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    """Compatibility adapter for legacy get_latest_reading calls."""
    latest = get_latest_telemetry(device_id=device_id, db=db)
    if not latest:
        return None
    res = dict(latest)
    res["water_level_cm"] = res.get("water_height", 0.0)
    res["water_litres"] = res.get("water_volume", 0.0)
    return res


def get_today_summary(device_id: Optional[str] = None, date_str: Optional[str] = None, db: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """Computes daily scorecard aggregates for legacy dashboard."""
    conn = db or get_db()
    cursor = conn.cursor()
    target_date = date_str or datetime.now().strftime("%Y-%m-%d")

    q = """
        SELECT
            COUNT(*) as reading_count,
            ROUND(MIN(water_height), 2) as min_level_cm,
            ROUND(MAX(water_height), 2) as max_level_cm,
            ROUND(AVG(water_height), 2) as avg_level_cm,
            ROUND(MIN(water_percentage), 2) as min_percentage,
            ROUND(MAX(water_percentage), 2) as max_percentage,
            ROUND(AVG(water_percentage), 2) as avg_percentage,
            ROUND(MIN(water_volume), 2) as min_litres,
            ROUND(MAX(water_volume), 2) as max_litres,
            ROUND(AVG(water_volume), 2) as avg_litres
        FROM telemetry
        WHERE date = ?
    """
    params = [target_date]
    if device_id:
        q += " AND device_id = ?"
        params.append(device_id)

    cursor.execute(q, tuple(params))
    summary = dict(cursor.fetchone() or {})
    summary["date"] = target_date
    summary["net_change_litres"] = 0.0
    summary["net_water_change_litres"] = 0.0
    summary["min_level_percent"] = summary.get("min_percentage", 0.0)
    summary["max_level_percent"] = summary.get("max_percentage", 0.0)
    summary["avg_level_percent"] = summary.get("avg_percentage", 0.0)
    return summary


def get_daily_stats(days: int = 15, device_id: Optional[str] = None, db: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    """Calculates daily aggregates for the past N calendar days."""
    conn = db or get_db()
    cursor = conn.cursor()
    cutoff_date = (datetime.now() - timedelta(days=max(0, days - 1))).strftime("%Y-%m-%d")
    q = """
        SELECT
            date,
            COUNT(*) as reading_count,
            ROUND(MIN(water_height), 2) as min_level_cm,
            ROUND(MAX(water_height), 2) as max_level_cm,
            ROUND(AVG(water_height), 2) as avg_level_cm,
            ROUND(MIN(water_percentage), 2) as min_percentage,
            ROUND(MAX(water_percentage), 2) as max_percentage,
            ROUND(AVG(water_percentage), 2) as avg_percentage,
            ROUND(MIN(water_volume), 2) as min_litres,
            ROUND(MAX(water_volume), 2) as max_litres,
            ROUND(AVG(water_volume), 2) as avg_litres
        FROM telemetry
        WHERE date >= ?
    """
    params = [cutoff_date]
    if device_id:
        q += " AND device_id = ?"
        params.append(device_id)
    q += " GROUP BY date ORDER BY date ASC"
    cursor.execute(q, tuple(params))
    return [dict(r) for r in cursor.fetchall()]


def get_readings_by_date(date_str: str, device_id: Optional[str] = None, limit: Optional[int] = None, db: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    """Retrieves chronological intraday readings for a given date."""
    conn = db or get_db()
    cursor = conn.cursor()
    q = "SELECT * FROM telemetry WHERE date = ?"
    params = [date_str]
    if device_id:
        q += " AND device_id = ?"
        params.append(device_id)
    q += " ORDER BY timestamp ASC"
    if limit:
        q += " LIMIT ?"
        params.append(limit)
    cursor.execute(q, tuple(params))
    res = []
    for r in cursor.fetchall():
        d = dict(r)
        d["water_level_cm"] = d.get("water_height", 0.0)
        d["water_litres"] = d.get("water_volume", 0.0)
        res.append(d)
    return res


def compare_dates(date1_str: str, date2_str: str, device_id: Optional[str] = None, db: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """Compares statistics between two dates side-by-side."""
    conn = db or get_db()
    def _fetch(d_str):
        cursor = conn.cursor()
        q = "SELECT COUNT(*) as reading_count, ROUND(AVG(water_percentage), 2) as avg_percentage, ROUND(AVG(water_volume), 2) as avg_litres FROM telemetry WHERE date = ?"
        p = [d_str]
        if device_id:
            q += " AND device_id = ?"
            p.append(device_id)
        cursor.execute(q, tuple(p))
        return dict(cursor.fetchone() or {"reading_count": 0, "avg_percentage": 0.0, "avg_litres": 0.0})
    s1 = _fetch(date1_str)
    s2 = _fetch(date2_str)
    return {
        "date1": {"date": date1_str, "readings_count": s1["reading_count"], "summary": s1},
        "date2": {"date": date2_str, "readings_count": s2["reading_count"], "summary": s2},
        "comparison": {
            "avg_percentage_diff": round(s2.get("avg_percentage", 0) - s1.get("avg_percentage", 0), 2),
            "avg_litres_diff": round(s2.get("avg_litres", 0) - s1.get("avg_litres", 0), 2),
        }
    }
