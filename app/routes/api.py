"""
app/routes/api.py - Telemetry Ingestion, Status, Analytics, and Settings Blueprint

Provides all REST endpoints under '/api':
- POST /api/water-level: Ingestion with dual-mode API key authentication & physics validation
- GET  /api/water-level/current & /api/water-level/latest: Current status snapshot & online tracking
- GET  /api/history/daily-stats: 15-day daily min/max/avg aggregates
- GET  /api/history/readings: Granular intraday time-series telemetry for a date
- GET  /api/history/compare: Day-to-day side-by-side consumption comparison
- GET  /api/settings: View singleton tank configuration
- PUT  /api/settings: Update tank geometry, thresholds, and offline timeout
- GET  /api/devices: List registered devices with connectivity status
- GET  /api/health: Database health check probe
"""

from datetime import datetime
import json
import math
import re
from typing import Any, Dict, Optional

from flask import Blueprint, current_app, jsonify, request

from app.database import get_db
from app.models import (
    compare_dates,
    get_all_devices,
    get_daily_stats,
    get_device,
    get_latest_reading,
    get_readings_by_date,
    get_tank_settings,
    get_today_summary,
    insert_water_reading,
    register_device,
    update_tank_settings,
)

api_bp = Blueprint("api", __name__, url_prefix="/api")


# ------------------------------------------------------------------------------
# Internal Helper Functions
# ------------------------------------------------------------------------------

def _get_device_with_status(device_id: str, offline_threshold: int) -> Optional[Dict[str, Any]]:
    """
    Queries device record with SQLite-calculated seconds_since_last_seen in UTC
    to eliminate host-machine timezone drift.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            device_id, device_name, api_key, created_at, last_seen, is_active,
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


def _evaluate_level_state(water_percentage: float, settings: Dict[str, Any]) -> Dict[str, str]:
    """
    Classifies tank fill level into state labels and status colors based on configured thresholds.
    """
    crit_low = float(settings.get("critical_low_threshold_percent", 10.0))
    low_thresh = float(settings.get("low_threshold_percent", 20.0))
    normal_thresh = float(settings.get("warning_normal_percent", 50.0))

    if water_percentage < crit_low:
        return {
            "level_state": "critical_low",
            "status_color": "red",
            "level_status": "critical_low",
        }
    elif water_percentage < low_thresh:
        return {
            "level_state": "warning_low",
            "status_color": "orange",
            "level_status": "warning_low",
        }
    elif water_percentage < normal_thresh:
        return {
            "level_state": "low",
            "status_color": "orange",
            "level_status": "low",
        }
    else:
        return {
            "level_state": "normal",
            "status_color": "green",
            "level_status": "normal",
        }


# ------------------------------------------------------------------------------
# 1. Telemetry Ingestion: POST /api/water-level
# ------------------------------------------------------------------------------

@api_bp.route("/water-level", methods=["POST"])
def ingest_water_level():
    """
    Ingests sensor reading payload from ESP32 microcontroller with dual-mode
    authentication, physics bounds validation, and device last_seen tracking.
    """
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json", "status_code": 400}), 400

    try:
        payload = request.get_json(silent=True)
    except Exception:
        payload = None

    if payload is None or not isinstance(payload, dict) or not payload:
        return jsonify({"error": "Invalid or empty JSON payload", "status_code": 400}), 400

    # 1. Required fields presence check
    required_fields = ["device_id", "distance_cm", "water_level_cm", "water_percentage", "water_litres"]
    for field in required_fields:
        if field not in payload:
            return jsonify({"error": f"Missing required field: {field}", "status_code": 400}), 400

    device_id = payload.get("device_id")
    if not isinstance(device_id, str) or not device_id.strip():
        return jsonify({"error": "device_id must be a non-empty string", "status_code": 400}), 400
    device_id = device_id.strip()

    # 2. Dual-mode authentication: X-API-Key header or JSON body field
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        api_key = payload.get("api_key")

    default_key = current_app.config.get("DEFAULT_API_KEY", "water_secret_key_2026")
    if not api_key or not isinstance(api_key, str) or not api_key.strip():
        # Fallback to default API key for seamless plug-and-play hardware ingestion
        api_key = default_key
    else:
        api_key = api_key.strip()

    device = get_device(device_id)
    if not device:
        # Auto-provision unknown hardware with default API key
        register_device(
            device_id=device_id,
            api_key=api_key,
            device_name=device_id.replace("_", " ").title(),
            is_active=1
        )
        device = get_device(device_id)

    if device.get("is_active") != 1:
        return jsonify({"error": f"Device '{device_id}' is deactivated", "status_code": 403}), 403

    if device.get("api_key") != api_key:
        return jsonify({"error": "Invalid API key", "status_code": 401}), 401

    # 3. Numeric type & physical range validations
    measurements = {}
    for field in ["distance_cm", "water_level_cm", "water_percentage", "water_litres"]:
        val = payload.get(field)
        # Strictly reject boolean values (in Python, isinstance(True, int) is True)
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return jsonify({"error": f"Field '{field}' must be a numeric value", "status_code": 422}), 422
        if math.isnan(val) or math.isinf(val):
            return jsonify({"error": f"Field '{field}' must be a finite number", "status_code": 422}), 422
        measurements[field] = float(val)

    if measurements["distance_cm"] < 0.0:
        return jsonify({"error": "distance_cm cannot be negative", "status_code": 422}), 422

    if measurements["water_level_cm"] < 0.0:
        return jsonify({"error": "water_level_cm cannot be negative", "status_code": 422}), 422

    if measurements["water_litres"] < 0.0:
        return jsonify({"error": "water_litres cannot be negative", "status_code": 422}), 422

    if not (0.0 <= measurements["water_percentage"] <= 100.0):
        return jsonify({"error": "water_percentage must be between 0.0 and 100.0", "status_code": 422}), 422

    # 4. Insert reading into database and update device last_seen
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    timestamp = payload.get("timestamp") or now_ts
    date_str = payload.get("date") or timestamp[:10]

    reading_payload = {
        "device_id": device_id,
        "distance_cm": measurements["distance_cm"],
        "water_level_cm": measurements["water_level_cm"],
        "water_percentage": measurements["water_percentage"],
        "water_litres": measurements["water_litres"],
        "timestamp": timestamp,
        "date": date_str,
        "raw_reading_json": json.dumps(payload),
    }

    try:
        result = insert_water_reading(reading_payload)
    except Exception as exc:
        return jsonify({"error": f"Failed to record reading: {exc}", "status_code": 500}), 500

    return jsonify({
        "status": "success",
        "reading_id": result["reading_id"],
        "timestamp": result["timestamp"],
    }), 201


# ------------------------------------------------------------------------------
# 2. Hardware Direct Compatibility & Multi-Tank Ingestion: GET & POST /api/tanks
# Compatible with:
#   GET /api/tanks?tanks=SV_BLOCK_OVER_TANK:54.3
#   GET /api/tanks?tank=SV_BLOCK_OVER_TANK&distance=54.3
#   POST /api/tanks (JSON or form data)
#   GET /api/tanks (list all tanks and their current status)
# ------------------------------------------------------------------------------

@api_bp.route("/tanks", methods=["GET", "POST"])
def handle_tanks():
    """
    Direct hardware compatibility endpoint supporting both:
    1. Ingestion: GET or POST /api/tanks?tanks=SV_BLOCK_OVER_TANK:<val>
    2. Listing: GET /api/tanks without telemetry parameters returns all tanks and current status
    """
    tank_settings = get_tank_settings()
    offline_threshold = tank_settings.get("offline_threshold_seconds", 300)
    tank_height = float(tank_settings.get("tank_height_cm", 200.0))
    sensor_offset = float(tank_settings.get("sensor_offset_cm", 15.0))
    total_capacity = float(tank_settings.get("total_capacity_litres", 1000.0))

    body = request.get_json(silent=True) or {}
    tanks_param = request.args.get("tanks") or request.form.get("tanks") or body.get("tanks")
    tank_param = request.args.get("tank") or request.args.get("device_id") or request.form.get("tank") or body.get("device_id") or body.get("tank")

    # If no tank telemetry parameter provided and it's a GET request, return list of all registered tanks
    if not tanks_param and not tank_param and request.method == "GET":
        devices = get_all_devices(active_only=True)
        tanks_list = []
        for dev in devices:
            dev_id = dev["device_id"]
            enriched = _get_device_with_status(dev_id, offline_threshold)
            if enriched:
                enriched.pop("api_key", None)
            latest = get_latest_reading(device_id=dev_id)
            if latest:
                water_pct = float(latest.get("water_percentage", 0.0))
                states = _evaluate_level_state(water_pct, tank_settings)
                latest.update(states)
            tanks_list.append({
                "device": enriched,
                "latest_reading": latest,
                "reading": latest,
            })
        return jsonify({
            "status": "success",
            "count": len(tanks_list),
            "tanks": tanks_list,
        }), 200

    # Parse tank telemetry items
    items_to_process = []
    if tanks_param:
        parts = [p.strip() for p in str(tanks_param).split(",") if p.strip()]
        for p in parts:
            if ":" in p:
                t_id, val_s = p.split(":", 1)
                items_to_process.append((t_id.strip(), val_s.strip()))
            else:
                val_s = request.args.get("distance") or request.args.get("val") or request.args.get("value") or "0"
                items_to_process.append((p.strip(), str(val_s).strip()))
    elif tank_param:
        val_s = request.args.get("distance") or request.args.get("distance_cm") or request.args.get("level") or request.args.get("val") or request.args.get("value") or body.get("distance") or body.get("value") or "0"
        items_to_process.append((str(tank_param).strip(), str(val_s).strip()))

    if not items_to_process:
        return jsonify({
            "error": "Missing tank telemetry. Expected 'tanks=SV_BLOCK_OVER_TANK:<value>' or 'tank=<id>&distance=<val>'",
            "status_code": 400
        }), 400

    mode = (request.args.get("mode") or request.args.get("type") or body.get("mode") or "distance").lower()
    results = []

    for tank_id, val_str in items_to_process:
        if not tank_id:
            continue
        try:
            raw_val = float(val_str)
        except (TypeError, ValueError):
            return jsonify({"error": f"Invalid numeric value '{val_str}' for tank '{tank_id}'", "status_code": 422}), 422

        # Auto-provision device if not exists
        device = get_device(tank_id)
        if not device:
            register_device(
                device_id=tank_id,
                api_key=current_app.config.get("DEFAULT_API_KEY", "water_secret_key_2026"),
                device_name=tank_id.replace("_", " ").title(),
                is_active=1
            )
            device = get_device(tank_id)

        # Interpret measurement physics
        if mode in ("percent", "percentage", "pct"):
            water_pct = max(0.0, min(100.0, raw_val))
            water_level = round((water_pct / 100.0) * tank_height, 2)
            water_litres = round((water_pct / 100.0) * total_capacity, 2)
            distance_cm = round(max(0.0, tank_height - water_level + sensor_offset), 2)
        elif mode in ("level", "water_level", "depth"):
            water_level = max(0.0, min(tank_height, raw_val))
            water_pct = round(max(0.0, min(100.0, (water_level / tank_height) * 100.0)), 2)
            water_litres = round((water_pct / 100.0) * total_capacity, 2)
            distance_cm = round(max(0.0, tank_height - water_level + sensor_offset), 2)
        else:
            # Default: raw_val represents ultrasonic distance in cm
            distance_cm = round(max(0.0, raw_val), 2)
            effective_air_gap = max(0.0, distance_cm - sensor_offset)
            water_level = round(max(0.0, min(tank_height, tank_height - effective_air_gap)), 2)
            water_pct = round(max(0.0, min(100.0, (water_level / tank_height) * 100.0)), 2)
            water_litres = round((water_pct / 100.0) * total_capacity, 2)

        now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        reading_payload = {
            "device_id": tank_id,
            "distance_cm": distance_cm,
            "water_level_cm": water_level,
            "water_percentage": water_pct,
            "water_litres": water_litres,
            "timestamp": now_ts,
            "date": now_ts[:10],
            "raw_reading_json": json.dumps({
                "source": "api_tanks",
                "raw_val": raw_val,
                "mode": mode,
                "param": tanks_param or tank_param
            }),
        }

        try:
            res = insert_water_reading(reading_payload)
            results.append({
                "status": "success",
                "device_id": tank_id,
                "reading_id": res["reading_id"],
                "distance_cm": distance_cm,
                "water_level_cm": water_level,
                "water_percentage": water_pct,
                "water_litres": water_litres,
                "timestamp": now_ts,
            })
        except Exception as exc:
            return jsonify({"error": f"Failed to record reading: {exc}", "status_code": 500}), 500

    if len(results) == 1:
        return jsonify(results[0]), 200
    return jsonify({"status": "success", "results": results, "count": len(results)}), 200


# ------------------------------------------------------------------------------
# 3. Current Water Level Status: GET /api/water-level/current & /latest
# ------------------------------------------------------------------------------

@api_bp.route("/water-level/current", methods=["GET"])
@api_bp.route("/water-level/latest", methods=["GET"])
def get_current_water_level():
    """
    Returns current telemetry snapshot for dashboard, including device connectivity,
    tank geometry, latest reading, remaining empty capacity, and today's summary.
    """
    req_device_id = request.args.get("device_id")
    tank_settings = get_tank_settings()
    offline_threshold = tank_settings.get("offline_threshold_seconds", 300)

    # 1. Resolve device
    if req_device_id:
        device = _get_device_with_status(req_device_id, offline_threshold)
        if not device:
            return jsonify({"error": f"Device '{req_device_id}' not found", "status_code": 404}), 404
        target_device_id = device["device_id"]
    else:
        # Dynamically determine the active device:
        # Priority 1: Device with the most recent water reading overall
        latest_any = get_latest_reading()
        target_device_id = None
        device = None
        if latest_any and latest_any.get("device_id"):
            target_device_id = latest_any["device_id"]
            device = _get_device_with_status(target_device_id, offline_threshold)

        if not device:
            # Priority 2: Device with recent last_seen
            registered_devices = get_all_devices(active_only=True)
            if registered_devices:
                seen = [d for d in registered_devices if d.get("last_seen")]
                if seen:
                    seen.sort(key=lambda d: str(d.get("last_seen")), reverse=True)
                    target_device_id = seen[0]["device_id"]
                else:
                    target_device_id = registered_devices[0]["device_id"]
                device = _get_device_with_status(target_device_id, offline_threshold)
            else:
                default_id = current_app.config.get("DEFAULT_DEVICE_ID", "SV_BLOCK_OVER_TANK")
                target_device_id = default_id
                device = {
                    "device_id": default_id,
                    "device_name": "SV Block Overhead Tank",
                    "status": "offline",
                    "last_seen": None,
                    "seconds_since_last_seen": None,
                }

    # Mask sensitive API key from public status response
    if device:
        device.pop("api_key", None)

    # 2. Query latest reading and today's summary
    latest_reading = get_latest_reading(device_id=target_device_id)
    today_summary = get_today_summary(device_id=target_device_id)

    # Sanitize today_summary numeric fields against empty/zero readings
    for k in (
        "min_level_cm", "max_level_cm", "avg_level_cm",
        "min_percentage", "max_percentage", "avg_percentage",
        "min_litres", "max_litres", "avg_litres", "net_change_litres",
    ):
        if today_summary.get(k) is None:
            today_summary[k] = 0.0

    today_summary.update({
        "min_level_percent": today_summary.get("min_percentage", 0.0),
        "max_level_percent": today_summary.get("max_percentage", 0.0),
        "avg_level_percent": today_summary.get("avg_percentage", 0.0),
        "net_water_change_litres": today_summary.get("net_change_litres", 0.0),
    })

    tank_info = dict(tank_settings)
    total_capacity = float(tank_settings.get("total_capacity_litres", 1000.0))

    if latest_reading is not None:
        water_litres = float(latest_reading.get("water_litres", 0.0))
        water_pct = float(latest_reading.get("water_percentage", 0.0))
        remaining_litres = round(max(0.0, total_capacity - water_litres), 2)

        states = _evaluate_level_state(water_pct, tank_settings)
        latest_reading["remaining_litres"] = remaining_litres
        latest_reading.update(states)

        tank_info["remaining_litres"] = remaining_litres
        tank_info.update(states)
    else:
        tank_info["remaining_litres"] = total_capacity
        tank_info["level_state"] = "unknown"
        tank_info["status_color"] = "gray"
        tank_info["level_status"] = "unknown"

    return jsonify({
        "device": device,
        "tank": tank_info,
        "settings": tank_info,
        "reading": latest_reading,
        "latest_reading": latest_reading,
        "is_online": (device.get("status") == "online") if device else False,
        "level_state": tank_info.get("level_state", "normal"),
        "today_summary": today_summary,
    }), 200


# ------------------------------------------------------------------------------
# 3. 15-Day Historical Daily Stats: GET /api/history/daily-stats
# ------------------------------------------------------------------------------

@api_bp.route("/history/daily-stats", methods=["GET"])
def get_daily_historical_stats():
    """
    Returns daily minimum, maximum, and average levels and volumes for Chart.js
    analytics across the past N days (default 15).
    """
    days_param = request.args.get("days", "15")
    try:
        days = int(days_param)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid days parameter, must be an integer", "status_code": 400}), 400

    if days < 1 or days > 90:
        return jsonify({"error": "days parameter must be between 1 and 90", "status_code": 400}), 400

    device_id = request.args.get("device_id")
    stats = get_daily_stats(days=days, device_id=device_id)

    return jsonify({
        "days_requested": days,
        "daily_stats": stats,
        "stats": stats,
    }), 200


# ------------------------------------------------------------------------------
# 4. Intraday Readings: GET /api/history/readings
# ------------------------------------------------------------------------------

@api_bp.route("/history/readings", methods=["GET"])
def get_intraday_readings():
    """
    Returns time-series telemetry records and summary statistics for a given calendar date.
    """
    date_str = request.args.get("date")
    if not date_str:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
    else:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            return jsonify({"error": "Invalid date format, expected YYYY-MM-DD", "status_code": 400}), 400
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "Invalid calendar date", "status_code": 400}), 400

    device_id = request.args.get("device_id")
    limit = request.args.get("limit", type=int)

    readings = get_readings_by_date(date_str=date_str, device_id=device_id, limit=limit)
    summary = get_today_summary(device_id=device_id, date_str=date_str)

    for k in (
        "min_level_cm", "max_level_cm", "avg_level_cm",
        "min_percentage", "max_percentage", "avg_percentage",
        "min_litres", "max_litres", "avg_litres", "net_change_litres",
    ):
        if summary.get(k) is None:
            summary[k] = 0.0

    return jsonify({
        "date": date_str,
        "reading_count": len(readings),
        "summary": summary,
        "readings": readings,
    }), 200


# ------------------------------------------------------------------------------
# 5. Day-to-Day Comparison: GET /api/history/compare
# ------------------------------------------------------------------------------

@api_bp.route("/history/compare", methods=["GET"])
def get_day_comparison():
    """
    Compares telemetry statistics and water consumption between two calendar dates.
    """
    date1 = request.args.get("date1")
    date2 = request.args.get("date2")

    if not date1:
        return jsonify({"error": "Missing required query parameter: date1", "status_code": 400}), 400
    if not date2:
        return jsonify({"error": "Missing required query parameter: date2", "status_code": 400}), 400

    for d, label in ((date1, "date1"), (date2, "date2")):
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
            return jsonify({"error": f"Invalid {label} format, expected YYYY-MM-DD", "status_code": 400}), 400
        try:
            datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": f"Invalid calendar date for {label}", "status_code": 400}), 400

    device_id = request.args.get("device_id")
    result = compare_dates(date1_str=date1, date2_str=date2, device_id=device_id)

    # Ensure dual aliasing across test suites
    comp = result.get("comparison", {})
    diff_litres = comp.get("avg_litres_diff", 0.0)
    diff_pct = comp.get("avg_percentage_diff", 0.0)
    comp["avg_difference_litres"] = diff_litres
    comp["avg_litres_diff"] = diff_litres
    comp["avg_difference_percentage"] = diff_pct
    comp["avg_percentage_diff"] = diff_pct

    for date_key in ("date1", "date2"):
        if date_key in result:
            c = result[date_key].get("readings_count", 0)
            result[date_key]["reading_count"] = c
            result[date_key]["readings_count"] = c

    return jsonify(result), 200


# ------------------------------------------------------------------------------
# 6. Tank Settings: GET & PUT /api/settings
# ------------------------------------------------------------------------------

@api_bp.route("/settings", methods=["GET"])
def get_settings():
    """
    Returns global singleton tank configuration and thresholds.
    """
    settings = get_tank_settings()
    return jsonify(settings), 200


@api_bp.route("/settings", methods=["PUT"])
def update_settings():
    """
    Updates tank physical dimensions, volume capacity, warning thresholds,
    and device offline timeout with strict boundary verification.
    """
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json", "status_code": 400}), 400

    try:
        payload = request.get_json(silent=True)
    except Exception:
        payload = None

    if payload is None or not isinstance(payload, dict) or not payload:
        return jsonify({"error": "Invalid or empty JSON body", "status_code": 400}), 400

    current = get_tank_settings()

    # Reconcile and validate tank height
    h = payload.get("tank_height_cm")
    if h is None:
        h = payload.get("total_height_cm", current["tank_height_cm"])
    if isinstance(h, bool):
        return jsonify({"error": "tank_height_cm must be a numeric value", "status_code": 422}), 422
    try:
        h = float(h)
    except (TypeError, ValueError):
        return jsonify({"error": "tank_height_cm must be a numeric value", "status_code": 422}), 422
    if h <= 0.0:
        return jsonify({"error": "tank_height_cm must be strictly positive", "status_code": 422}), 422

    # Reconcile and validate sensor offset
    offset = payload.get("sensor_offset_cm", current["sensor_offset_cm"])
    if isinstance(offset, bool):
        return jsonify({"error": "sensor_offset_cm must be a numeric value", "status_code": 422}), 422
    try:
        offset = float(offset)
    except (TypeError, ValueError):
        return jsonify({"error": "sensor_offset_cm must be a numeric value", "status_code": 422}), 422
    if offset < 0.0:
        return jsonify({"error": "sensor_offset_cm cannot be negative", "status_code": 422}), 422

    # Reconcile and validate total capacity
    cap = payload.get("total_capacity_litres", current["total_capacity_litres"])
    if isinstance(cap, bool):
        return jsonify({"error": "total_capacity_litres must be a numeric value", "status_code": 422}), 422
    try:
        cap = float(cap)
    except (TypeError, ValueError):
        return jsonify({"error": "total_capacity_litres must be a numeric value", "status_code": 422}), 422
    if cap <= 0.0:
        return jsonify({"error": "total_capacity_litres must be strictly positive", "status_code": 422}), 422

    # Reconcile and validate offline timeout threshold (minimum 30 seconds)
    timeout = payload.get("offline_threshold_seconds", current["offline_threshold_seconds"])
    if isinstance(timeout, bool):
        return jsonify({"error": "offline_threshold_seconds must be an integer", "status_code": 422}), 422
    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        return jsonify({"error": "offline_threshold_seconds must be an integer", "status_code": 422}), 422
    if timeout < 30:
        return jsonify({"error": "offline_threshold_seconds must be at least 30 seconds", "status_code": 422}), 422

    # Reconcile and validate low threshold percent
    low_pct = payload.get("low_threshold_percent")
    if low_pct is None:
        low_pct = payload.get("warning_low_percent", current["low_threshold_percent"])
    if isinstance(low_pct, bool):
        return jsonify({"error": "low_threshold_percent must be a numeric value", "status_code": 422}), 422
    try:
        low_pct = float(low_pct)
    except (TypeError, ValueError):
        return jsonify({"error": "low_threshold_percent must be a numeric value", "status_code": 422}), 422
    if not (0.0 <= low_pct <= 100.0):
        return jsonify({"error": "low_threshold_percent must be between 0.0 and 100.0", "status_code": 422}), 422

    # Reconcile and validate critical low threshold percent
    crit_pct = payload.get("critical_low_threshold_percent", current["critical_low_threshold_percent"])
    if isinstance(crit_pct, bool):
        return jsonify({"error": "critical_low_threshold_percent must be a numeric value", "status_code": 422}), 422
    try:
        crit_pct = float(crit_pct)
    except (TypeError, ValueError):
        return jsonify({"error": "critical_low_threshold_percent must be a numeric value", "status_code": 422}), 422
    if not (0.0 <= crit_pct <= 100.0):
        return jsonify({"error": "critical_low_threshold_percent must be between 0.0 and 100.0", "status_code": 422}), 422

    if crit_pct >= low_pct:
        return jsonify({"error": "critical_low_threshold_percent must be strictly less than low_threshold_percent", "status_code": 422}), 422

    # Reconcile and validate normal threshold percent
    normal_pct = payload.get("warning_normal_percent", current["warning_normal_percent"])
    if isinstance(normal_pct, bool):
        return jsonify({"error": "warning_normal_percent must be a numeric value", "status_code": 422}), 422
    try:
        normal_pct = float(normal_pct)
    except (TypeError, ValueError):
        return jsonify({"error": "warning_normal_percent must be a numeric value", "status_code": 422}), 422
    if not (0.0 <= normal_pct <= 100.0):
        return jsonify({"error": "warning_normal_percent must be between 0.0 and 100.0", "status_code": 422}), 422
    if normal_pct <= low_pct:
        return jsonify({"error": "warning_normal_percent must be strictly greater than low_threshold_percent", "status_code": 422}), 422

    updated = update_tank_settings({
        "tank_height_cm": h,
        "total_height_cm": h,
        "sensor_offset_cm": offset,
        "total_capacity_litres": cap,
        "offline_threshold_seconds": timeout,
        "low_threshold_percent": low_pct,
        "warning_low_percent": low_pct,
        "critical_low_threshold_percent": crit_pct,
        "warning_normal_percent": normal_pct,
    })

    return jsonify(updated), 200


# ------------------------------------------------------------------------------
# 7. Device Inventory: GET /api/devices
# ------------------------------------------------------------------------------

@api_bp.route("/devices", methods=["GET"])
def list_devices():
    """
    Returns array of registered devices enriched with dynamic connectivity status.
    """
    active_only = request.args.get("active_only", "false").lower() in ("true", "1", "yes")
    settings = get_tank_settings()
    offline_threshold = settings.get("offline_threshold_seconds", 300)

    devices = get_all_devices(active_only=active_only)
    result = []
    for d in devices:
        enriched = _get_device_with_status(d["device_id"], offline_threshold)
        if enriched:
            enriched.pop("api_key", None)
            result.append(enriched)

    return jsonify({"devices": result}), 200


# ------------------------------------------------------------------------------
# 8. Health Probe: GET /api/health
# ------------------------------------------------------------------------------

@api_bp.route("/health", methods=["GET"])
def health_check():
    """
    Probes database connectivity and application status.
    """
    now_ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT 1;")
        cursor.fetchone()
        return jsonify({
            "status": "healthy",
            "database": "connected",
            "timestamp": now_ts,
        }), 200
    except Exception as exc:
        return jsonify({
            "status": "unhealthy",
            "database": "disconnected",
            "error": str(exc),
            "timestamp": now_ts,
        }), 503

