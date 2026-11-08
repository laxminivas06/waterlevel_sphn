"""
app/routes/api.py - Comprehensive RESTful API Blueprint v2.0
HydroSense IoT - Smart Water Tank Monitoring System

Implements all specifications from Section 10 & 3:
- POST /api/v1/telemetry: Core IoT sensor telemetry ingestion with authentication & bounds validation
- GET  /api/v1/tanks: List all monitored tanks with live readings, statuses & connectivity
- GET  /api/v1/tanks/<tank_id>: Single tank geometry & threshold settings
- POST /api/v1/tanks: Create or update tank geometry (cylinder / rectangle)
- DEL  /api/v1/tanks/<tank_id>: Remove tank record
- GET  /api/v1/tanks/<tank_id>/latest: Latest telemetry reading for specific tank
- GET  /api/v1/tanks/<tank_id>/history: 24h, 7d, 15d & custom time-series history + drawdown analytics
- GET  /api/v1/devices: Inventory of registered ESP8266/ESP32 microcontrollers
- POST /api/v1/devices: Register or reassign microcontrollers
- GET  /api/v1/alerts: System operational alerts (overflow, critical low, sensor faults, offline)
- POST /api/v1/alerts/<id>/ack: Acknowledge active alert
- GET  /api/v1/system/summary: High-level KPI dashboard scorecard
- POST /api/v1/simulate: Testing simulator to submit readings without hardware (Section 14)
- GET  /api/v1/health: Database & service health probe
- Legacy routes preserved for zero-breakage backward compatibility (/api/tanks, /api/water-level)
"""

from datetime import datetime
import json
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from flask import Blueprint, current_app, jsonify, request

from app.database import get_db
from app.models import (
    acknowledge_alert,
    calculate_tank_physics,
    compare_dates,
    create_alert,
    create_or_update_tank,
    delete_tank,
    get_alerts,
    get_all_devices,
    get_all_tanks,
    get_daily_stats,
    get_device,
    get_device_with_status,
    get_latest_reading,
    get_latest_telemetry,
    get_readings_by_date,
    get_system_summary,
    get_tank,
    get_tank_history,
    get_tank_settings,
    get_today_summary,
    insert_telemetry,
    insert_water_reading,
    register_device,
    update_tank_settings,
)

api_bp = Blueprint("api", __name__, url_prefix="/api")


# ------------------------------------------------------------------------------
# Helpers: Authentication & Status Helpers
# ------------------------------------------------------------------------------

def _authenticate_request(device_id: Optional[str] = None, payload: Optional[Dict[str, Any]] = None) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Validates API key from 'Authorization: Bearer <token>', 'X-API-Key' header,
    or JSON payload field 'api_key'. Rejects unauthorized requests per Section 10.
    """
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()

    if not token:
        token = request.headers.get("X-API-Key")

    if not token and payload and isinstance(payload, dict):
        token = payload.get("api_key")

    default_key = current_app.config.get("DEFAULT_API_KEY", "water_secret_key_2026")

    if not token or not str(token).strip():
        return False, "Missing API key in Authorization header, X-API-Key, or body", None

    token = str(token).strip()

    device = None
    if device_id:
        device = get_device(device_id)
        if device:
            expected_key = device.get("api_key") or default_key
            if token == expected_key or token == default_key:
                return True, "Authenticated", device
            return False, "Invalid API key for device", device

    if token == default_key:
        return True, "Authenticated with default key", device

    return False, "Invalid API key", None


def _get_status_color(status: str) -> str:
    """Maps operational status to SCADA theme color."""
    mapping = {
        "NORMAL": "#10b981",       # Emerald green
        "LOW": "#f59e0b",          # Amber orange
        "CRITICAL LOW": "#ef4444", # Rose red
        "HIGH": "#8b5cf6",         # Violet blue
        "OVERLOADED": "#dc2626",   # Crimson alert red
        "SENSOR FAULT": "#94a3b8", # Muted slate
    }
    return mapping.get(status, "#06b6d4")


# ==============================================================================
# SECTION 10: CORE REST API v1 ENDPOINTS
# ==============================================================================

# ------------------------------------------------------------------------------
# 1. IoT Telemetry Ingestion: POST /api/v1/telemetry
# ------------------------------------------------------------------------------

@api_bp.route("/v1/telemetry", methods=["POST"])
def ingest_telemetry_v1():
    """
    Primary endpoint for ESP8266 and ESP32 hardware telemetry.
    Accepts JSON payload:
      {
        "device_id": "SV_BLOCK_OVER_TANK",
        "distance_cm": 25.5,
        "water_level_percent": 75,
        "water_volume_litres": 750,
        "status": "NORMAL"
      }
    """
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json", "status_code": 400}), 400

    payload = request.get_json(silent=True)
    if not payload or not isinstance(payload, dict):
        return jsonify({"error": "Invalid or empty JSON body", "status_code": 400}), 400

    # 1. Device ID presence check
    device_id = payload.get("device_id")
    if not device_id or not str(device_id).strip():
        return jsonify({"error": "Missing required field: device_id", "status_code": 400}), 400
    device_id = str(device_id).strip()

    # Reject unknown devices per Section 10
    device = get_device(device_id)
    if not device:
        return jsonify({"error": f"Unknown or unregistered device: '{device_id}'", "status_code": 404}), 404

    # 2. Authentication check
    is_auth, auth_msg, _ = _authenticate_request(device_id=device_id, payload=payload)
    if not is_auth:
        return jsonify({"error": f"Unauthorized: {auth_msg}", "status_code": 401}), 401

    # 3. Distance presence and numeric validation
    distance_cm = payload.get("distance_cm")
    if distance_cm is None:
        return jsonify({"error": "Missing required field: distance_cm", "status_code": 400}), 400
    try:
        distance_cm = float(distance_cm)
    except (TypeError, ValueError):
        return jsonify({"error": "distance_cm must be a valid number", "status_code": 400}), 400

    if distance_cm < 0.0:
        return jsonify({"error": "distance_cm cannot be negative", "status_code": 400}), 400

    # 4. Optional IP address extraction
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    payload["ip_address"] = client_ip.split(",")[0].strip() if client_ip else None

    try:
        result = insert_telemetry(payload)
        return jsonify(result), 201
    except Exception as exc:
        return jsonify({"error": f"Failed to record telemetry: {exc}", "status_code": 500}), 500


# ------------------------------------------------------------------------------
# 2. Tanks Management: GET & POST /api/v1/tanks
# ------------------------------------------------------------------------------

@api_bp.route("/v1/tanks", methods=["GET"])
def list_tanks_v1():
    """
    Returns array of all registered water tanks enriched with:
    - Latest telemetry reading
    - Remaining empty capacity (Litres)
    - Online/offline device state
    - Visual status color code
    """
    tanks = get_all_tanks()
    enriched = []

    for t in tanks:
        tank_id = t["tank_id"]
        latest = get_latest_telemetry(tank_id=tank_id)
        offline_thresh = t.get("offline_threshold_seconds", 300)

        # Find matching device
        devices = get_all_devices()
        matched_dev = next((d for d in devices if d.get("tank_id") == tank_id or d.get("device_id") == tank_id), None)
        dev_status = "offline"
        seconds_ago = None

        if matched_dev:
            dev_enriched = get_device_with_status(matched_dev["device_id"], offline_threshold=offline_thresh)
            if dev_enriched:
                dev_status = dev_enriched.get("status", "offline")
                seconds_ago = dev_enriched.get("seconds_since_last_seen")

        cap = float(t.get("total_capacity_litres", 1000.0))
        if latest:
            vol = float(latest.get("water_volume", 0.0))
            pct = float(latest.get("water_percentage", 0.0))
            status_text = latest.get("status", "NORMAL")
            rem_litres = round(max(0.0, cap - vol), 2)
            color = _get_status_color(status_text)
        else:
            vol = 0.0
            pct = 0.0
            status_text = "NO DATA"
            rem_litres = cap
            color = "#64748b"

        enriched.append({
            "tank": t,
            "tank_id": tank_id,
            "tank_name": t.get("tank_name", tank_id),
            "shape": t.get("shape", "cylinder"),
            "tank_height_cm": t.get("tank_height_cm"),
            "sensor_offset_cm": t.get("sensor_offset_cm"),
            "total_capacity_litres": cap,
            "current_percentage": pct,
            "current_volume_litres": vol,
            "remaining_litres": rem_litres,
            "status": status_text,
            "status_color": color,
            "is_overloaded": (status_text == "OVERLOADED"),
            "device_id": matched_dev["device_id"] if matched_dev else None,
            "device_status": dev_status,
            "is_online": (dev_status == "online"),
            "seconds_since_last_seen": seconds_ago,
            "last_updated": latest.get("timestamp") if latest else None,
            "latest_reading": latest,
        })

    return jsonify({"tanks": enriched, "count": len(enriched), "status": "success"}), 200


@api_bp.route("/v1/tanks", methods=["POST"])
def create_tank_v1():
    """Creates a new tank or updates an existing tank's dimensions and telemetry."""
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json", "status_code": 400}), 400

    data = request.get_json(silent=True) or {}
    tank_id = data.get("tank_id")
    if not tank_id or not str(tank_id).strip():
        return jsonify({"error": "Missing required field: tank_id", "status_code": 400}), 400

    try:
        tank = create_or_update_tank(data)

        # If occupied litres or level was set in settings, immediately record telemetry
        occ_litres = data.get("liters_occupied") or data.get("occupied_litres") or data.get("water_volume_litres")
        occ_pct = data.get("water_level_percent") or data.get("water_percentage")
        if occ_litres is not None or occ_pct is not None:
            telemetry_payload = {
                "device_id": str(tank_id).strip(),
                "tank_id": str(tank_id).strip(),
            }
            if occ_litres is not None:
                telemetry_payload["water_volume_litres"] = float(occ_litres)
            if occ_pct is not None:
                telemetry_payload["water_level_percent"] = float(occ_pct)
            insert_telemetry(telemetry_payload)

        return jsonify({"tank": tank, "status": "success"}), 201
    except Exception as exc:
        return jsonify({"error": str(exc), "status_code": 422}), 422


@api_bp.route("/v1/tanks/<tank_id>", methods=["GET"])
def get_tank_v1(tank_id: str):
    """Retrieves single tank details, geometry & threshold configuration."""
    tank = get_tank(tank_id)
    if not tank:
        return jsonify({"error": f"Tank '{tank_id}' not found", "status_code": 404}), 404
    latest = get_latest_telemetry(tank_id=tank_id)
    return jsonify({"tank": tank, "latest_reading": latest, "status": "success"}), 200


@api_bp.route("/v1/tanks/<tank_id>", methods=["DELETE"])
def delete_tank_v1(tank_id: str):
    """Deletes a tank."""
    deleted = delete_tank(tank_id)
    if not deleted:
        return jsonify({"error": f"Tank '{tank_id}' not found", "status_code": 404}), 404
    return jsonify({"status": "success", "message": f"Tank '{tank_id}' removed"}), 200


@api_bp.route("/v1/tanks/<tank_id>/latest", methods=["GET"])
def get_tank_latest_v1(tank_id: str):
    """Returns the most recent telemetry reading for a specific tank."""
    tank = get_tank(tank_id)
    if not tank:
        return jsonify({"error": f"Tank '{tank_id}' not found", "status_code": 404}), 404

    latest = get_latest_telemetry(tank_id=tank_id)
    if not latest:
        return jsonify({
            "tank_id": tank_id,
            "reading": None,
            "status": "NO DATA",
            "message": "No telemetry readings recorded for this tank yet"
        }), 200

    status_text = latest.get("status", "NORMAL")
    latest["status_color"] = _get_status_color(status_text)
    return jsonify({"tank_id": tank_id, "reading": latest, "status": "success"}), 200


@api_bp.route("/v1/tanks/<tank_id>/history", methods=["GET"])
def get_tank_history_v1(tank_id: str):
    """
    Returns time-series telemetry records and summary statistics for Chart.js / Recharts.
    Query params:
      - range: 24h (default), 7d, 15d, custom
      - start_date: YYYY-MM-DD
      - end_date: YYYY-MM-DD
      - limit: max data points (default: 500)
    """
    tank = get_tank(tank_id)
    if not tank:
        return jsonify({"error": f"Tank '{tank_id}' not found", "status_code": 404}), 404

    range_key = request.args.get("range", "24h").lower()
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    limit = request.args.get("limit", 500, type=int)

    history = get_tank_history(
        tank_id=tank_id,
        range_key=range_key,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    return jsonify(history), 200


# ------------------------------------------------------------------------------
# 3. Device Management: GET & POST /api/v1/devices
# ------------------------------------------------------------------------------

@api_bp.route("/v1/devices", methods=["GET"])
def list_devices_v1():
    """Lists registered microcontrollers with dynamic online/offline connectivity."""
    devices = get_all_devices()
    result = []
    for d in devices:
        enriched = get_device_with_status(d["device_id"])
        if enriched:
            enriched.pop("api_key", None)  # Mask API token from public view
            result.append(enriched)
    return jsonify({"devices": result, "count": len(result), "status": "success"}), 200


@api_bp.route("/v1/devices", methods=["POST"])
def register_device_v1():
    """Registers a new ESP8266 or ESP32 microcontroller or updates tank assignment."""
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json", "status_code": 400}), 400

    data = request.get_json(silent=True) or {}
    device_id = data.get("device_id")
    if not device_id or not str(device_id).strip():
        return jsonify({"error": "Missing required field: device_id", "status_code": 400}), 400

    device_name = data.get("device_name") or device_id.replace("_", " ").title()
    api_key = data.get("api_key") or "water_secret_key_2026"
    tank_id = data.get("tank_id")
    ip_address = data.get("ip_address")
    firmware_version = data.get("firmware_version", "2.0.0")

    device = register_device(
        device_id=device_id,
        api_key=api_key,
        device_name=device_name,
        tank_id=tank_id,
        ip_address=ip_address,
        firmware_version=firmware_version,
    )
    return jsonify({"device": device, "status": "success", "success": True}), 201


# ------------------------------------------------------------------------------
# 4. System Alerts: GET & POST /api/v1/alerts
# ------------------------------------------------------------------------------

@api_bp.route("/v1/alerts", methods=["GET"])
def list_alerts_v1():
    """Lists system alerts (Overflow, Critical Low, Sensor Fault, Disconnected)."""
    tank_id = request.args.get("tank_id")
    unack = request.args.get("unacknowledged", "true").lower() in ("true", "1", "yes")
    limit = request.args.get("limit", 50, type=int)

    alerts = get_alerts(tank_id=tank_id, unacknowledged_only=unack, limit=limit)
    return jsonify({"alerts": alerts, "count": len(alerts), "status": "success"}), 200


@api_bp.route("/v1/alerts/<int:alert_id>/ack", methods=["POST"])
def acknowledge_alert_v1(alert_id: int):
    """Marks an active alert as acknowledged."""
    ack = acknowledge_alert(alert_id)
    if not ack:
        return jsonify({"error": f"Alert #{alert_id} not found", "status_code": 404}), 404
    return jsonify({"status": "success", "message": f"Alert #{alert_id} acknowledged"}), 200


# ------------------------------------------------------------------------------
# 5. System KPI Summary: GET /api/v1/system/summary
# ------------------------------------------------------------------------------

@api_bp.route("/v1/system/summary", methods=["GET"])
def system_summary_v1():
    """Returns top-level KPI scorecard for the SCADA dashboard."""
    summary = get_system_summary()
    res = dict(summary)
    res["summary"] = summary
    return jsonify(res), 200


# ------------------------------------------------------------------------------
# 6. Manual Hardware Simulator (Section 14): POST /api/v1/simulate
# ------------------------------------------------------------------------------

@api_bp.route("/v1/simulate", methods=["POST"])
def simulate_reading_v1():
    """
    Testing endpoint allowing users and QA suites to submit sensor readings
    directly from the UI without physical microcontroller hardware.
    Supports either distance_cm or water_level_percent.
    """
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json", "status_code": 400}), 400

    data = request.get_json(silent=True) or {}
    tank_id = data.get("tank_id", "SV_BLOCK_OVER_TANK")
    device_id = data.get("device_id", tank_id)

    tank = get_tank(tank_id) or get_tank("SV_BLOCK_OVER_TANK")
    tank_h = float(tank.get("tank_height_cm", 200.0)) if tank else 200.0
    sensor_offset = float(tank.get("sensor_offset_cm", 15.0)) if tank else 15.0

    distance_cm = data.get("distance_cm")
    pct_input = data.get("water_level_percent") if data.get("water_level_percent") is not None else data.get("water_percentage")

    if distance_cm is None and pct_input is not None:
        try:
            target_pct = float(pct_input)
            target_water_h = (target_pct / 100.0) * tank_h
            distance_cm = round(max(0.0, sensor_offset + (tank_h - target_water_h)), 2)
        except (TypeError, ValueError):
            distance_cm = 45.0
    elif distance_cm is None:
        # Default to a healthy 45 cm reading
        distance_cm = 45.0

    try:
        distance_cm = float(distance_cm)
    except (TypeError, ValueError):
        return jsonify({"error": "distance_cm must be numeric", "status_code": 400}), 400

    payload = {
        "device_id": device_id,
        "tank_id": tank_id,
        "distance_cm": distance_cm,
        "source": "manual_simulator",
    }
    result = insert_telemetry(payload)
    return jsonify(result), 201


# ------------------------------------------------------------------------------
# 7. System Health Probe: GET /api/v1/health
# ------------------------------------------------------------------------------

@api_bp.route("/v1/health", methods=["GET"])
@api_bp.route("/health", methods=["GET"])
def health_check_v1():
    """Probes JSON database and API operational status."""
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        db = get_db()
        tank_count = len(db.get("tanks", []))
        telemetry_count = len(db.get("telemetry", []))

        return jsonify({
            "status": "healthy",
            "database": "connected",
            "tanks_configured": tank_count,
            "telemetry_records": telemetry_count,
            "timestamp": now_ts,
            "version": "2.1.0",
        }), 200
    except Exception as exc:
        return jsonify({
            "status": "unhealthy",
            "database": "disconnected",
            "error": str(exc),
            "timestamp": now_ts,
        }), 503


# ==============================================================================
# SECTION 16: LEGACY BACKWARD COMPATIBILITY ROUTES
# ==============================================================================

@api_bp.route("/tanks", methods=["GET", "POST"])
def handle_legacy_tanks():
    """
    Maintains 100% compatibility with older hardware requests like:
      GET /api/tanks?tanks=SV_BLOCK_OVER_TANK:2
      GET /api/tanks?tanks=SV_BLOCK_OVER_TANK:54.3
      GET /api/tanks
    """
    tanks_param = request.args.get("tanks") or request.form.get("tanks")
    tank_param = request.args.get("tank") or request.args.get("device_id")

    if not tanks_param and not tank_param and request.method == "GET":
        return list_tanks_v1()

    # Parse parameters
    items = []
    if tanks_param:
        for p in str(tanks_param).split(","):
            if ":" in p:
                t_id, val_s = p.split(":", 1)
                items.append((t_id.strip(), val_s.strip()))
            else:
                val_s = request.args.get("distance") or request.args.get("val") or "45.0"
                items.append((p.strip(), str(val_s).strip()))
    elif tank_param:
        val_s = request.args.get("distance") or request.args.get("distance_cm") or "45.0"
        items.append((str(tank_param).strip(), str(val_s).strip()))

    results = []
    for t_id, val_str in items:
        try:
            raw_val = float(val_str)
        except ValueError:
            continue

        payload = {
            "device_id": t_id,
            "tank_id": t_id,
        }

        # Value handling:
        # If the value is in 0..100, treat directly as percentage level
        # (Resolves percentage inversion: 2% sent must show 2%, not 98%)
        if 0.0 <= raw_val <= 100.0:
            payload["water_level_percent"] = raw_val
            payload["distance_cm"] = raw_val
        else:
            payload["distance_cm"] = raw_val

        # Support optional query parameters if explicitly specified
        explicit_pct = request.args.get("percent") or request.args.get("percentage") or request.args.get("water_level_percent")
        if explicit_pct is not None:
            try:
                payload["water_level_percent"] = float(explicit_pct)
            except ValueError:
                pass

        explicit_litres = request.args.get("litres") or request.args.get("liters") or request.args.get("water_volume_litres") or request.args.get("liters_occupied")
        if explicit_litres is not None:
            try:
                payload["water_volume_litres"] = float(explicit_litres)
            except ValueError:
                pass

        res = insert_telemetry(payload)
        results.append(res)

    if len(results) == 1:
        return jsonify(results[0]), 200
    return jsonify({"status": "success", "results": results}), 200


@api_bp.route("/water-level", methods=["GET", "POST"])
def legacy_water_level_post():
    """Legacy /api/water-level adapter (POST to record, GET to retrieve readings)."""
    if request.method == "POST":
        return ingest_telemetry_v1()
    limit = request.args.get("limit", 20, type=int)
    device_id = request.args.get("device_id")
    history = get_tank_history(tank_id=device_id or "SV_BLOCK_OVER_TANK", range_key="24h", limit=limit)
    readings = history.get("data", [])
    return jsonify({"readings": readings, "data": readings, "count": len(readings), "water_levels": readings, "status": "success"}), 200


@api_bp.route("/water-level/current", methods=["GET"])
@api_bp.route("/water-level/latest", methods=["GET"])
def legacy_water_level_current():
    """Legacy GET /api/water-level/current snapshot."""
    req_device_id = request.args.get("tank_id") or request.args.get("device_id")
    tanks = get_all_tanks()

    if req_device_id:
        target_tank = get_tank(req_device_id) or (tanks[0] if tanks else {})
    else:
        target_tank = tanks[0] if tanks else {}

    tank_id = target_tank.get("tank_id", "SV_BLOCK_OVER_TANK")
    latest = get_latest_telemetry(tank_id=tank_id)
    device = get_device_with_status(tank_id) or {
        "device_id": tank_id,
        "device_name": target_tank.get("tank_name", tank_id),
        "status": "offline",
        "last_seen": None,
    }

    cap = float(target_tank.get("total_capacity_litres", 1000.0))
    vol = float(latest.get("water_volume", 0.0)) if latest else 0.0
    pct = float(latest.get("water_percentage", 0.0)) if latest else 0.0
    status_text = latest.get("status", "NORMAL") if latest else "NO DATA"

    tank_info = dict(target_tank)
    tank_info["remaining_litres"] = round(max(0.0, cap - vol), 2)
    tank_info["level_state"] = status_text.lower().replace(" ", "_")
    tank_info["status_color"] = _get_status_color(status_text)

    if latest:
        latest["remaining_litres"] = tank_info["remaining_litres"]
        latest["water_level_cm"] = latest.get("water_height", 0.0)
        latest["water_litres"] = vol
        latest["water_level"] = pct

    today = get_today_summary(device_id=tank_id)

    return jsonify({
        "device": device,
        "tank": tank_info,
        "settings": tank_info,
        "reading": latest,
        "latest_reading": latest,
        "water_level": pct,
        "water_percentage": pct,
        "water_level_percent": pct,
        "water_litres": vol,
        "water_volume_litres": vol,
        "distance": latest.get("distance_cm") if latest else None,
        "distance_cm": latest.get("distance_cm") if latest else None,
        "is_online": (device.get("status") == "online"),
        "level_state": tank_info["level_state"],
        "today_summary": today,
    }), 200


@api_bp.route("/settings", methods=["GET", "PUT"])
def legacy_settings():
    """Legacy singleton tank settings adapter."""
    if request.method == "GET":
        return jsonify(get_tank_settings()), 200
    data = request.get_json(silent=True) or {}
    updated = update_tank_settings(data)
    return jsonify(updated), 200


@api_bp.route("/history/daily-stats", methods=["GET"])
def legacy_daily_stats():
    days = request.args.get("days", 15, type=int)
    device_id = request.args.get("device_id")
    stats = get_daily_stats(days=days, device_id=device_id)
    return jsonify({"stats": stats, "daily_stats": stats, "days_requested": days}), 200


@api_bp.route("/history/readings", methods=["GET"])
def legacy_readings():
    date_str = request.args.get("date") or datetime.now().strftime("%Y-%m-%d")
    device_id = request.args.get("device_id")
    readings = get_readings_by_date(date_str, device_id)
    return jsonify({"date": date_str, "reading_count": len(readings), "readings": readings}), 200


@api_bp.route("/history/compare", methods=["GET"])
def legacy_compare():
    d1 = request.args.get("date1", datetime.now().strftime("%Y-%m-%d"))
    d2 = request.args.get("date2", datetime.now().strftime("%Y-%m-%d"))
    return jsonify(compare_dates(d1, d2)), 200
