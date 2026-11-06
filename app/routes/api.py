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
                ELSE CAST(strftime('%s', 'now') - strftime('%s', last_seen) AS INTEGER)
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

    if not api_key or not isinstance(api_key, str) or not api_key.strip():
        return jsonify({"error": "Missing or empty API key", "status_code": 401}), 401
    api_key = api_key.strip()

    device = get_device(device_id)
    if not device:
        return jsonify({"error": "Unknown device or invalid API key", "status_code": 401}), 401

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
    now_utc = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    timestamp = payload.get("timestamp") or now_utc
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
# 2. Current Water Level Status: GET /api/water-level/current & /latest
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
        default_id = current_app.config.get("DEFAULT_DEVICE_ID", "esp32_tank_01")
        device = _get_device_with_status(default_id, offline_threshold)
        if not device:
            registered_devices = get_all_devices(active_only=True)
            if registered_devices:
                target_device_id = registered_devices[0]["device_id"]
                device = _get_device_with_status(target_device_id, offline_threshold)
            else:
                target_device_id = default_id
                device = {
                    "device_id": default_id,
                    "device_name": "Main Water Tank",
                    "status": "offline",
                    "last_seen": None,
                    "seconds_since_last_seen": None,
                }
        else:
            target_device_id = device["device_id"]

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
        "reading": latest_reading,
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

