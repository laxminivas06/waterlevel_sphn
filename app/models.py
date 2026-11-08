"""
app/models.py - Comprehensive Data Access Layer (DAL) & Domain Logic
HydroSense IoT - Smart Water Tank Monitoring System v2.0 (Pure JSON Database Edition)

Implements pure JSON flat-file storage for:
- Tanks & Geometric Physical Calibrations (Cylindrical / Rectangular)
- Devices, Registration, Assignment & Online/Offline Heartbeats
- Real-time Telemetry Ingestion, Dynamic Status Classification & 15+ Day Analytics
- Automatic Threshold Alerts (Critical Low, Low, High, Overloaded, Sensor Fault, Offline)
- Backup Audit Logging & Legacy Backward-Compatibility Adapters
"""

import copy
from datetime import datetime, timedelta
import json
import math
from typing import Any, Dict, List, Optional, Tuple, Union

from werkzeug.security import generate_password_hash, check_password_hash

from app.database import get_db, JsonDatabase


# ==============================================================================
# 1. Tank Operations & Physics Calculations (Section 5, 6, 7)
# ==============================================================================

def get_tank(tank_id: str, db: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """Retrieves a tank record by tank_id."""
    database = db if isinstance(db, JsonDatabase) else get_db()
    tanks = database.get("tanks", [])
    for t in tanks:
        if t.get("tank_id") == tank_id:
            return copy.deepcopy(t)
    return None


def get_all_tanks(db: Optional[Any] = None) -> List[Dict[str, Any]]:
    """Retrieves all registered tanks sorted by created_at."""
    database = db if isinstance(db, JsonDatabase) else get_db()
    tanks = database.get("tanks", [])
    # Return copies sorted by created_at ASC
    sorted_tanks = sorted(tanks, key=lambda x: str(x.get("created_at", "")))
    return [copy.deepcopy(t) for t in sorted_tanks]


def create_or_update_tank(tank_data: Dict[str, Any], db: Optional[Any] = None) -> Dict[str, Any]:
    """Creates a new tank or updates an existing tank's geometry & thresholds idempotently."""
    database = db if isinstance(db, JsonDatabase) else get_db()
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
        radius_cm = round(math.sqrt((total_capacity * 1000.0) / (math.pi * tank_height)), 2)
    elif shape == "rectangle" and (length_cm is None or width_cm is None) and total_capacity > 0 and tank_height > 0:
        side = round(math.sqrt((total_capacity * 1000.0) / tank_height), 2)
        length_cm = side
        width_cm = side

    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    tanks = database.get("tanks", [])
    found_idx = None
    for idx, t in enumerate(tanks):
        if t.get("tank_id") == tank_id:
            found_idx = idx
            break

    if found_idx is not None:
        existing = tanks[found_idx]
        if tank_data.get("tank_name"):
            existing["tank_name"] = str(tank_data["tank_name"]).strip()
        if tank_data.get("shape"):
            existing["shape"] = shape
        if tank_data.get("tank_height_cm") is not None:
            existing["tank_height_cm"] = tank_height
        if tank_data.get("sensor_offset_cm") is not None:
            existing["sensor_offset_cm"] = sensor_offset
        if tank_data.get("total_capacity_litres") is not None:
            existing["total_capacity_litres"] = total_capacity
        if radius_cm is not None:
            existing["radius_cm"] = radius_cm
        if length_cm is not None:
            existing["length_cm"] = length_cm
        if width_cm is not None:
            existing["width_cm"] = width_cm
        if tank_data.get("safe_max_percent") is not None:
            existing["safe_max_percent"] = safe_max_pct
        if tank_data.get("critical_low_percent") is not None:
            existing["critical_low_percent"] = crit_low_pct
        if tank_data.get("low_percent") is not None:
            existing["low_percent"] = low_pct
        if tank_data.get("high_percent") is not None:
            existing["high_percent"] = high_pct
        if tank_data.get("offline_threshold_seconds") is not None:
            existing["offline_threshold_seconds"] = offline_thresh
        existing["updated_at"] = now_ts
        database.save()
        return copy.deepcopy(existing)
    else:
        new_tank = {
            "tank_id": tank_id,
            "tank_name": tank_name,
            "shape": shape,
            "tank_height_cm": tank_height,
            "sensor_offset_cm": sensor_offset,
            "total_capacity_litres": total_capacity,
            "length_cm": length_cm,
            "width_cm": width_cm,
            "radius_cm": radius_cm,
            "safe_max_percent": safe_max_pct,
            "critical_low_percent": crit_low_pct,
            "low_percent": low_pct,
            "high_percent": high_pct,
            "offline_threshold_seconds": offline_thresh,
            "created_at": now_ts,
            "updated_at": now_ts,
        }
        tanks.append(new_tank)
        database.save()
        return copy.deepcopy(new_tank)


def delete_tank(tank_id: str, db: Optional[Any] = None) -> bool:
    """Deletes a tank record by tank_id."""
    database = db if isinstance(db, JsonDatabase) else get_db()
    deleted = database.delete("tanks", lambda t: t.get("tank_id") == tank_id)
    return deleted > 0


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

    # 1. If explicit water level percentage was reported, directly respect it (e.g. 2% is 2%, not inverted)
    if reported_pct is not None:
        try:
            pct = round(max(0.0, min(105.0, float(reported_pct))), 2)
            water_height = round((pct / 100.0) * tank_height, 2)
            effective_air_gap = max(0.0, tank_height - water_height)
            calc_dist = round(effective_air_gap + sensor_offset, 2)
            dist_val = distance_cm if (distance_cm > 0 and distance_cm != float(reported_pct)) else calc_dist

            if reported_litres is not None and float(reported_litres) > 0:
                volume = round(float(reported_litres), 2)
            else:
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

            if pct > 100.0:
                status = "OVERLOADED"
                is_overloaded = True
            elif pct <= crit_low_pct:
                status = "CRITICAL LOW"
                is_overloaded = False
            elif pct <= low_pct:
                status = "LOW"
                is_overloaded = False
            elif pct <= high_pct:
                status = "NORMAL"
                is_overloaded = False
            else:
                status = "HIGH"
                is_overloaded = False

            return {
                "distance_cm": dist_val,
                "water_height": water_height,
                "water_height_cm": water_height,
                "water_percentage": pct,
                "water_level_percent": pct,
                "water_volume": volume,
                "water_volume_litres": volume,
                "status": status,
                "is_overloaded": is_overloaded,
                "is_valid": True,
            }
        except (ValueError, TypeError):
            pass

    # 2. If explicit occupied litres was reported without percent, calculate percentage directly
    if reported_litres is not None and float(reported_litres) >= 0 and reported_pct is None:
        try:
            volume = round(float(reported_litres), 2)
            pct = round(min(105.0, (volume / total_capacity) * 100.0), 2)
            water_height = round((pct / 100.0) * tank_height, 2)
            effective_air_gap = max(0.0, tank_height - water_height)
            calc_dist = round(effective_air_gap + sensor_offset, 2)

            if pct > 100.0:
                status = "OVERLOADED"
                is_overloaded = True
            elif pct <= crit_low_pct:
                status = "CRITICAL LOW"
                is_overloaded = False
            elif pct <= low_pct:
                status = "LOW"
                is_overloaded = False
            elif pct <= high_pct:
                status = "NORMAL"
                is_overloaded = False
            else:
                status = "HIGH"
                is_overloaded = False

            return {
                "distance_cm": distance_cm if distance_cm > 0 else calc_dist,
                "water_height": water_height,
                "water_height_cm": water_height,
                "water_percentage": pct,
                "water_level_percent": pct,
                "water_volume": volume,
                "water_volume_litres": volume,
                "status": status,
                "is_overloaded": is_overloaded,
                "is_valid": True,
            }
        except (ValueError, TypeError):
            pass

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

def get_device(device_id: str, db: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """Retrieves a device record by device_id."""
    database = db if isinstance(db, JsonDatabase) else get_db()
    devices = database.get("devices", [])
    for d in devices:
        if d.get("device_id") == device_id:
            return copy.deepcopy(d)
    return None


def get_all_devices(active_only: bool = False, db: Optional[Any] = None) -> List[Dict[str, Any]]:
    """Returns all registered devices."""
    database = db if isinstance(db, JsonDatabase) else get_db()
    devices = database.get("devices", [])
    if active_only:
        filtered = [d for d in devices if d.get("is_active") == 1]
    else:
        filtered = devices
    sorted_devs = sorted(filtered, key=lambda x: str(x.get("created_at", "")))
    return [copy.deepcopy(d) for d in sorted_devs]


def register_device(
    device_id: str,
    api_key: str,
    device_name: str,
    tank_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    firmware_version: Optional[str] = "2.0.0",
    is_active: int = 1,
    db: Optional[Any] = None
) -> Dict[str, Any]:
    """Registers a new device or updates an existing device credentials idempotently."""
    database = db if isinstance(db, JsonDatabase) else get_db()
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # If tank_id is supplied, verify tank exists; if not, auto-create matching tank
    if tank_id:
        t = get_tank(tank_id, db=database)
        if not t:
            create_or_update_tank({"tank_id": tank_id, "tank_name": tank_id.replace("_", " ").title()}, db=database)
    else:
        t = get_tank(device_id, db=database)
        if t:
            tank_id = device_id

    devices = database.get("devices", [])
    found = None
    for d in devices:
        if d.get("device_id") == device_id:
            found = d
            break

    if found is not None:
        found["device_name"] = device_name
        if tank_id is not None:
            found["tank_id"] = tank_id
        found["api_key"] = api_key
        if ip_address is not None:
            found["ip_address"] = ip_address
        if firmware_version is not None:
            found["firmware_version"] = firmware_version
        found["is_active"] = is_active
        database.save()
        return copy.deepcopy(found)
    else:
        new_dev = {
            "device_id": device_id,
            "device_name": device_name,
            "tank_id": tank_id,
            "api_key": api_key,
            "ip_address": ip_address,
            "firmware_version": firmware_version,
            "is_active": is_active,
            "created_at": now_ts,
            "last_seen": None,
        }
        devices.append(new_dev)
        database.save()
        return copy.deepcopy(new_dev)


def get_device_with_status(device_id: str, offline_threshold: int = 300, db: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """Calculates online/offline state and seconds_since_last_seen."""
    database = db if isinstance(db, JsonDatabase) else get_db()
    dev = get_device(device_id, db=database)
    if not dev:
        return None

    last_seen_str = dev.get("last_seen")
    if not last_seen_str:
        dev["status"] = "offline"
        dev["seconds_since_last_seen"] = None
        return dev

    try:
        # Parse last seen timestamp
        clean_ts = last_seen_str.replace("T", " ")[:19]
        last_seen_dt = datetime.strptime(clean_ts, "%Y-%m-%d %H:%M:%S")
        diff_sec = int((datetime.now() - last_seen_dt).total_seconds())
        diff_sec = max(0, diff_sec)

        is_online = (diff_sec <= offline_threshold)
        dev["status"] = "online" if is_online else "offline"
        dev["seconds_since_last_seen"] = diff_sec
    except Exception:
        dev["status"] = "offline"
        dev["seconds_since_last_seen"] = None

    return dev


# ==============================================================================
# 3. Telemetry Ingestion & Analytics (Section 3, 5, 8, 10, 11)
# ==============================================================================

def insert_telemetry(payload: Dict[str, Any], db: Optional[Any] = None) -> Dict[str, Any]:
    """
    Ingests and validates a telemetry packet from ESP8266/ESP32.
    Computes/validates tank physics, writes to telemetry & legacy water_readings,
    updates device last_seen, and generates real-time alerts if necessary.
    """
    database = db if isinstance(db, JsonDatabase) else get_db()
    device_id = str(payload.get("device_id") or "").strip()
    if not device_id:
        raise ValueError("Missing device_id in telemetry payload.")

    # Auto-resolve or create device if unknown
    device = get_device(device_id, db=database)
    if not device:
        api_key = payload.get("api_key") or "water_secret_key_2026"
        register_device(device_id, api_key, device_id.replace("_", " ").title(), db=database)
        device = get_device(device_id, db=database)

    tank_id = payload.get("tank_id") or (device.get("tank_id") if device else None) or device_id
    tank = get_tank(tank_id, db=database)
    if not tank:
        create_or_update_tank({"tank_id": tank_id, "tank_name": tank_id.replace("_", " ").title()}, db=database)
        tank = get_tank(tank_id, db=database)

    # Extract any reported percentage or occupied litres from known aliases
    raw_pct = (
        payload.get("water_level_percent")
        if payload.get("water_level_percent") is not None
        else payload.get("water_percentage")
        if payload.get("water_percentage") is not None
        else payload.get("percentage")
        if payload.get("percentage") is not None
        else payload.get("percent")
    )
    reported_pct = None
    if raw_pct is not None:
        try:
            reported_pct = float(raw_pct)
        except (ValueError, TypeError):
            reported_pct = None

    raw_litres = (
        payload.get("water_volume_litres")
        if payload.get("water_volume_litres") is not None
        else payload.get("water_litres")
        if payload.get("water_litres") is not None
        else payload.get("water_volume")
        if payload.get("water_volume") is not None
        else payload.get("liters_occupied")
        if payload.get("liters_occupied") is not None
        else payload.get("occupied_litres")
    )
    reported_litres = None
    if raw_litres is not None:
        try:
            reported_litres = float(raw_litres)
        except (ValueError, TypeError):
            reported_litres = None

    # Calculate physics metrics
    distance_cm = float(payload.get("distance_cm") or 0.0)
    metrics = calculate_tank_physics(
        tank=tank,
        distance_cm=distance_cm,
        reported_pct=reported_pct,
        reported_litres=reported_litres,
    )

    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    timestamp = payload.get("timestamp") or now_ts
    date_str = timestamp[:10]

    record = {
        "device_id": device_id,
        "tank_id": tank_id,
        "distance_cm": metrics["distance_cm"],
        "water_height": metrics["water_height"],
        "water_percentage": metrics["water_percentage"],
        "water_volume": metrics["water_volume"],
        "status": metrics["status"],
        "timestamp": timestamp,
        "date": date_str,
        "raw_payload": json.dumps(payload),
    }
    reading_id = database.insert("telemetry", record)

    # Update device last_seen and ip_address
    ip_addr = payload.get("ip_address")
    devices = database.get("devices", [])
    for d in devices:
        if d.get("device_id") == device_id:
            d["last_seen"] = timestamp
            if ip_addr:
                d["ip_address"] = ip_addr
            break

    # Mirror to legacy water_readings
    legacy_record = {
        "device_id": device_id,
        "distance_cm": metrics["distance_cm"],
        "water_level_cm": metrics["water_height"],
        "water_percentage": metrics["water_percentage"],
        "water_litres": metrics["water_volume"],
        "timestamp": timestamp,
        "date": date_str,
        "raw_reading_json": json.dumps(payload),
    }
    database.insert("water_readings", legacy_record)
    database.save()

    # Automated Alert Triggering (Section 7)
    if metrics["status"] == "OVERLOADED" or metrics["water_percentage"] >= float(tank.get("safe_max_percent", 95.0)):
        create_alert(
            tank_id=tank_id,
            device_id=device_id,
            alert_type="OVERFLOW_RISK",
            severity="critical",
            message=f"Tank '{tank.get('tank_name', tank_id)}' is OVERLOADED! Water level at {metrics['water_percentage']}% ({metrics['water_volume']}L).",
            db=database,
        )
        # Dispatch SMTP Overfill Email to all configured recipients
        try:
            from app.email_notifier import trigger_overfill_email_alert
            trigger_overfill_email_alert(tank, metrics, db=database)
        except Exception:
            pass
    elif metrics["status"] == "CRITICAL LOW":
        create_alert(
            tank_id=tank_id,
            device_id=device_id,
            alert_type="CRITICAL_LOW",
            severity="critical",
            message=f"Tank '{tank.get('tank_name', tank_id)}' is at CRITICAL LOW level ({metrics['water_percentage']}%). Risk of pump dry run.",
            db=database,
        )
    elif metrics["status"] == "SENSOR FAULT":
        create_alert(
            tank_id=tank_id,
            device_id=device_id,
            alert_type="SENSOR_FAULT",
            severity="warning",
            message=f"Abnormal distance reading ({distance_cm} cm) detected from sensor on device '{device_id}'.",
            db=database,
        )

    # Automated 15-Day Backup & 45-Day Data Retention Subsystem
    try:
        from app.retention import trigger_scheduled_maintenance_if_due
        trigger_scheduled_maintenance_if_due(db=database)
    except Exception:
        pass

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


def get_latest_telemetry(tank_id: Optional[str] = None, device_id: Optional[str] = None, db: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """Retrieves the latest telemetry record for a tank or device."""
    database = db if isinstance(db, JsonDatabase) else get_db()
    telemetry = database.get("telemetry", [])

    candidates = telemetry
    if tank_id:
        candidates = [t for t in candidates if t.get("tank_id") == tank_id]
    elif device_id:
        candidates = [t for t in candidates if t.get("device_id") == device_id]

    if not candidates:
        return None

    # Sort descending by timestamp, id
    candidates = sorted(candidates, key=lambda x: (str(x.get("timestamp", "")), int(x.get("id") or 0)), reverse=True)
    return copy.deepcopy(candidates[0])


def get_tank_history(
    tank_id: str,
    range_key: str = "24h",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = 500,
    db: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Retrieves time-series telemetry records and summary statistics for a given range (24h, 7d, 15d, custom).
    Calculates min, max, avg, and consumption/drawdown estimates.
    """
    database = db if isinstance(db, JsonDatabase) else get_db()
    telemetry = database.get("telemetry", [])

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

    filtered = [
        t for t in telemetry
        if t.get("tank_id") == tank_id and start_ts <= str(t.get("timestamp", "")) <= end_ts
    ]

    # Sort chronological (ascending)
    filtered = sorted(filtered, key=lambda x: (str(x.get("timestamp", "")), int(x.get("id") or 0)))
    if limit:
        filtered = filtered[:limit]

    rows = [copy.deepcopy(r) for r in filtered]

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

    pcts = [float(r.get("water_percentage", 0.0)) for r in rows]
    vols = [float(r.get("water_volume", 0.0)) for r in rows]

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


def get_system_summary(db: Optional[Any] = None) -> Dict[str, Any]:
    """
    Computes overall KPI dashboard scorecard:
    - Total tanks
    - Online devices
    - Offline devices
    - Average water level percentage
    - Total available water in litres
    - Active critical alerts count
    """
    database = db if isinstance(db, JsonDatabase) else get_db()
    tanks = get_all_tanks(db=database)
    devices = get_all_devices(db=database)

    online_count = 0
    offline_count = 0
    for dev in devices:
        enriched = get_device_with_status(dev["device_id"], db=database)
        if enriched and enriched.get("status") == "online":
            online_count += 1
        else:
            offline_count += 1

    total_litres = 0.0
    total_capacity = 0.0
    level_pcts = []

    for t in tanks:
        latest = get_latest_telemetry(tank_id=t["tank_id"], db=database)
        cap = float(t.get("total_capacity_litres", 1000.0))
        total_capacity += cap
        if latest:
            total_litres += float(latest.get("water_volume", 0.0))
            level_pcts.append(float(latest.get("water_percentage", 0.0)))

    avg_pct = round(sum(level_pcts) / len(level_pcts), 2) if level_pcts else 0.0

    alerts = database.get("alerts", [])
    crit_alerts = sum(1 for a in alerts if int(a.get("is_acknowledged", 0)) == 0 and a.get("severity") == "critical")

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
    db: Optional[Any] = None
) -> int:
    """Creates a new operational alert if an identical active alert does not exist within the last 10 minutes."""
    database = db if isinstance(db, JsonDatabase) else get_db()
    now_dt = datetime.now()
    now_ts = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    ten_mins_ago = (now_dt - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")

    alerts = database.get("alerts", [])
    # Debounce duplicate unacknowledged alerts within 10 minutes
    for a in alerts:
        if (
            a.get("tank_id") == tank_id
            and a.get("alert_type") == alert_type
            and int(a.get("is_acknowledged", 0)) == 0
            and str(a.get("timestamp", "")) >= ten_mins_ago
        ):
            return 0

    record = {
        "tank_id": tank_id,
        "device_id": device_id,
        "alert_type": alert_type,
        "severity": severity,
        "message": message,
        "is_acknowledged": 0,
        "acknowledged_at": None,
        "timestamp": now_ts,
    }
    alert_id = database.insert("alerts", record)
    return alert_id


def get_alerts(tank_id: Optional[str] = None, unacknowledged_only: bool = True, limit: int = 50, db: Optional[Any] = None) -> List[Dict[str, Any]]:
    """Retrieves system alerts with optional filters."""
    database = db if isinstance(db, JsonDatabase) else get_db()
    alerts = database.get("alerts", [])

    filtered = alerts
    if tank_id:
        filtered = [a for a in filtered if a.get("tank_id") == tank_id]
    if unacknowledged_only:
        filtered = [a for a in filtered if int(a.get("is_acknowledged", 0)) == 0]

    # Sort descending by timestamp, id
    filtered = sorted(filtered, key=lambda x: (str(x.get("timestamp", "")), int(x.get("id") or 0)), reverse=True)
    return [copy.deepcopy(a) for a in filtered[:limit]]


def acknowledge_alert(alert_id: int, db: Optional[Any] = None) -> bool:
    """Marks an alert as acknowledged."""
    database = db if isinstance(db, JsonDatabase) else get_db()
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    count = database.update(
        "alerts",
        lambda a: int(a.get("id") or 0) == alert_id,
        {"is_acknowledged": 1, "acknowledged_at": now_ts}
    )
    return count > 0


# ==============================================================================
# 5. Backup Records (Section 11)
# ==============================================================================

def record_backup(
    filename: str,
    file_path: str,
    record_count: int,
    file_size_bytes: int,
    backup_type: str = "automated",
    status: str = "success",
    notes: Optional[str] = None,
    db: Optional[Any] = None
) -> int:
    """Records an automated or manual backup execution."""
    database = db if isinstance(db, JsonDatabase) else get_db()
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    record = {
        "filename": filename,
        "file_path": file_path,
        "record_count": record_count,
        "file_size_bytes": file_size_bytes,
        "backup_type": backup_type,
        "status": status,
        "created_at": now_ts,
        "notes": notes,
    }
    return database.insert("backup_records", record)


def get_backups(limit: int = 30, db: Optional[Any] = None) -> List[Dict[str, Any]]:
    """Retrieves recent database backup logs."""
    database = db if isinstance(db, JsonDatabase) else get_db()
    backups = database.get("backup_records", [])
    sorted_backups = sorted(backups, key=lambda x: str(x.get("created_at", "")), reverse=True)
    return [copy.deepcopy(b) for b in sorted_backups[:limit]]


def get_backup_logs(limit: int = 50, db: Optional[Any] = None) -> List[Dict[str, Any]]:
    """Compatibility adapter for backup_routes."""
    database = db if isinstance(db, JsonDatabase) else get_db()
    records = database.get("backup_records", [])
    if records:
        sorted_records = sorted(records, key=lambda x: str(x.get("created_at", "")), reverse=True)
        return [copy.deepcopy(r) for r in sorted_records[:limit]]
    logs = database.get("backup_logs", [])
    sorted_logs = sorted(logs, key=lambda x: str(x.get("created_at", "")), reverse=True)
    return [copy.deepcopy(l) for l in sorted_logs[:limit]]


def insert_backup_log(log_dict: Dict[str, Any], db: Optional[Any] = None) -> int:
    """Compatibility adapter for backup logging."""
    database = db if isinstance(db, JsonDatabase) else get_db()
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    record = {
        "filename": log_dict.get("filename", "backup"),
        "file_path": log_dict.get("file_path", ""),
        "record_count": log_dict.get("record_count") or log_dict.get("records_count", 0),
        "file_size_bytes": log_dict.get("file_size_bytes", 0),
        "backup_type": log_dict.get("backup_type", "manual"),
        "status": log_dict.get("status", "success"),
        "created_at": now_ts,
        "notes": log_dict.get("notes") or log_dict.get("error_message"),
    }
    return database.insert("backup_records", record)


# ==============================================================================
# 6. Legacy Backward-Compatibility Adapters
# ==============================================================================

def get_tank_settings(db: Optional[Any] = None) -> Dict[str, Any]:
    """Compatibility adapter for legacy singleton settings route."""
    database = db if isinstance(db, JsonDatabase) else get_db()
    tanks = get_all_tanks(db=database)
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


def update_tank_settings(settings_dict: Dict[str, Any], db: Optional[Any] = None) -> Dict[str, Any]:
    """Updates tank settings across both multi-tank and legacy tables."""
    database = db if isinstance(db, JsonDatabase) else get_db()
    tanks = get_all_tanks(db=database)
    target_tank_id = tanks[0]["tank_id"] if tanks else "SV_BLOCK_OVER_TANK"

    data = {
        "tank_id": target_tank_id,
        "tank_name": settings_dict.get("tank_name"),
        "tank_height_cm": settings_dict.get("tank_height_cm") or settings_dict.get("total_height_cm"),
        "sensor_offset_cm": settings_dict.get("sensor_offset_cm"),
        "total_capacity_litres": settings_dict.get("total_capacity_litres"),
        "low_percent": settings_dict.get("low_threshold_percent") or settings_dict.get("warning_low_percent"),
        "critical_low_percent": settings_dict.get("critical_low_threshold_percent"),
        "high_percent": settings_dict.get("warning_normal_percent"),
        "offline_threshold_seconds": settings_dict.get("offline_threshold_seconds"),
    }
    clean_data = {k: v for k, v in data.items() if v is not None}
    create_or_update_tank(clean_data, db=database)

    # If occupied litres or percentage is provided in settings, immediately record a telemetry reading
    occ_litres = settings_dict.get("liters_occupied") or settings_dict.get("occupied_litres") or settings_dict.get("water_volume_litres")
    occ_pct = settings_dict.get("water_level_percent") or settings_dict.get("water_percentage")
    if occ_litres is not None or occ_pct is not None:
        telemetry_payload = {
            "device_id": target_tank_id,
            "tank_id": target_tank_id,
        }
        if occ_litres is not None:
            telemetry_payload["water_volume_litres"] = float(occ_litres)
        if occ_pct is not None:
            telemetry_payload["water_level_percent"] = float(occ_pct)
        insert_telemetry(telemetry_payload, db=database)

    # If email notification recipients are specified, update email_settings
    if "recipient_emails" in settings_dict or "notification_emails" in settings_dict:
        try:
            from app.email_notifier import update_email_settings
            emails_val = settings_dict.get("recipient_emails") or settings_dict.get("notification_emails")
            if emails_val:
                update_email_settings({"recipient_emails": emails_val}, db=database)
        except Exception:
            pass

    return get_tank_settings(db=database)


def insert_water_reading(reading_data: Dict[str, Any], db: Optional[Any] = None) -> Dict[str, Any]:
    """Compatibility adapter for legacy insert_water_reading calls."""
    return insert_telemetry(reading_data, db=db)


def get_latest_reading(device_id: Optional[str] = None, db: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """Compatibility adapter for legacy get_latest_reading calls."""
    latest = get_latest_telemetry(device_id=device_id, db=db)
    if not latest:
        return None
    res = dict(latest)
    res["water_level_cm"] = res.get("water_height", 0.0)
    res["water_litres"] = res.get("water_volume", 0.0)
    return res


def get_today_summary(device_id: Optional[str] = None, date_str: Optional[str] = None, db: Optional[Any] = None) -> Dict[str, Any]:
    """Computes daily scorecard aggregates for legacy dashboard."""
    database = db if isinstance(db, JsonDatabase) else get_db()
    telemetry = database.get("telemetry", [])
    target_date = date_str or datetime.now().strftime("%Y-%m-%d")

    records = [t for t in telemetry if t.get("date") == target_date]
    if device_id:
        records = [t for t in records if t.get("device_id") == device_id]

    if not records:
        return {
            "date": target_date,
            "reading_count": 0,
            "min_level_cm": 0.0,
            "max_level_cm": 0.0,
            "avg_level_cm": 0.0,
            "min_percentage": 0.0,
            "max_percentage": 0.0,
            "avg_percentage": 0.0,
            "min_litres": 0.0,
            "max_litres": 0.0,
            "avg_litres": 0.0,
            "net_change_litres": 0.0,
            "net_water_change_litres": 0.0,
            "min_level_percent": 0.0,
            "max_level_percent": 0.0,
            "avg_level_percent": 0.0,
        }

    h_list = [float(r.get("water_height", 0.0)) for r in records]
    p_list = [float(r.get("water_percentage", 0.0)) for r in records]
    v_list = [float(r.get("water_volume", 0.0)) for r in records]

    return {
        "date": target_date,
        "reading_count": len(records),
        "min_level_cm": round(min(h_list), 2),
        "max_level_cm": round(max(h_list), 2),
        "avg_level_cm": round(sum(h_list) / len(h_list), 2),
        "min_percentage": round(min(p_list), 2),
        "max_percentage": round(max(p_list), 2),
        "avg_percentage": round(sum(p_list) / len(p_list), 2),
        "min_litres": round(min(v_list), 2),
        "max_litres": round(max(v_list), 2),
        "avg_litres": round(sum(v_list) / len(v_list), 2),
        "net_change_litres": 0.0,
        "net_water_change_litres": 0.0,
        "min_level_percent": round(min(p_list), 2),
        "max_level_percent": round(max(p_list), 2),
        "avg_level_percent": round(sum(p_list) / len(p_list), 2),
    }


def get_daily_stats(days: int = 15, device_id: Optional[str] = None, db: Optional[Any] = None) -> List[Dict[str, Any]]:
    """Calculates daily aggregates for the past N calendar days."""
    database = db if isinstance(db, JsonDatabase) else get_db()
    telemetry = database.get("telemetry", [])
    cutoff_date = (datetime.now() - timedelta(days=max(0, days - 1))).strftime("%Y-%m-%d")

    records = [t for t in telemetry if str(t.get("date", "")) >= cutoff_date]
    if device_id:
        records = [t for t in records if t.get("device_id") == device_id]

    # Group by date
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for r in records:
        d = r.get("date", "")
        by_date.setdefault(d, []).append(r)

    results = []
    for d in sorted(by_date.keys()):
        group = by_date[d]
        h_list = [float(r.get("water_height", 0.0)) for r in group]
        p_list = [float(r.get("water_percentage", 0.0)) for r in group]
        v_list = [float(r.get("water_volume", 0.0)) for r in group]

        results.append({
            "date": d,
            "reading_count": len(group),
            "min_level_cm": round(min(h_list), 2),
            "max_level_cm": round(max(h_list), 2),
            "avg_level_cm": round(sum(h_list) / len(h_list), 2),
            "min_percentage": round(min(p_list), 2),
            "max_percentage": round(max(p_list), 2),
            "avg_percentage": round(sum(p_list) / len(p_list), 2),
            "min_litres": round(min(v_list), 2),
            "max_litres": round(max(v_list), 2),
            "avg_litres": round(sum(v_list) / len(v_list), 2),
        })

    return results


def get_readings_by_date(date_str: str, device_id: Optional[str] = None, limit: Optional[int] = None, db: Optional[Any] = None) -> List[Dict[str, Any]]:
    """Retrieves chronological intraday readings for a given date."""
    database = db if isinstance(db, JsonDatabase) else get_db()
    telemetry = database.get("telemetry", [])

    records = [t for t in telemetry if t.get("date") == date_str]
    if device_id:
        records = [t for t in records if t.get("device_id") == device_id]

    records = sorted(records, key=lambda x: str(x.get("timestamp", "")))
    if limit:
        records = records[:limit]

    res = []
    for r in records:
        d = copy.deepcopy(r)
        d["water_level_cm"] = d.get("water_height", 0.0)
        d["water_litres"] = d.get("water_volume", 0.0)
        res.append(d)
    return res


def compare_dates(date1_str: str, date2_str: str, device_id: Optional[str] = None, db: Optional[Any] = None) -> Dict[str, Any]:
    """Compares statistics between two dates side-by-side."""
    database = db if isinstance(db, JsonDatabase) else get_db()
    telemetry = database.get("telemetry", [])

    def _fetch(d_str):
        recs = [t for t in telemetry if t.get("date") == d_str]
        if device_id:
            recs = [t for t in recs if t.get("device_id") == device_id]
        if not recs:
            return {"reading_count": 0, "avg_percentage": 0.0, "avg_litres": 0.0}
        p_list = [float(r.get("water_percentage", 0.0)) for r in recs]
        v_list = [float(r.get("water_volume", 0.0)) for r in recs]
        return {
            "reading_count": len(recs),
            "avg_percentage": round(sum(p_list) / len(p_list), 2),
            "avg_litres": round(sum(v_list) / len(v_list), 2),
        }

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


# ==============================================================================
# 9. User Authentication & Profile Management
# ==============================================================================

def get_user_by_username(username: str, db: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """Retrieves a user record by username or email (case-insensitive)."""
    if not username:
        return None
    database = db if isinstance(db, JsonDatabase) else get_db()
    users = database.get("users", [])
    clean_username = username.strip().lower()
    for u in users:
        if (
            str(u.get("username", "")).strip().lower() == clean_username
            or str(u.get("email", "")).strip().lower() == clean_username
        ):
            return copy.deepcopy(u)
    return None


def get_user_by_id(user_id: int, db: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """Retrieves a user record by user_id."""
    database = db if isinstance(db, JsonDatabase) else get_db()
    users = database.get("users", [])
    for u in users:
        if u.get("id") == user_id:
            return copy.deepcopy(u)
    return None


def verify_user_password(user: Dict[str, Any], password: str) -> bool:
    """Verifies user password using secure password hashing with fallback to initial default."""
    if not user or not password:
        return False
    stored_hash = user.get("password_hash", "")
    if not stored_hash:
        return False
    # If initial development placeholder hash, allow admin123
    if stored_hash == "pbkdf2:sha256:600000$hydrosense$admin" and password == "admin123":
        return True
    try:
        return check_password_hash(stored_hash, password)
    except Exception:
        return False


def update_user_password(user_id: int, new_password: str, db: Optional[Any] = None) -> bool:
    """Updates user password with secure hash."""
    if not new_password or len(new_password) < 4:
        raise ValueError("Password must be at least 4 characters long.")
    database = db if isinstance(db, JsonDatabase) else get_db()
    users = database.get("users", [])
    for u in users:
        if u.get("id") == user_id:
            u["password_hash"] = generate_password_hash(new_password)
            u["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            database.set("users", users)
            return True
    return False


def sanitize_user(user: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Removes sensitive credentials (password_hash) from user dict before API exposure."""
    if not user:
        return None
    clean = copy.deepcopy(user)
    clean.pop("password_hash", None)
    return clean

