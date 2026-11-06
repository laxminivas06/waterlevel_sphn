# Milestone M2 Technical Analysis: Status and 15-Day Analytics Endpoints

**Subagent:** `m2_explorer_2`  
**Date:** 2026-11-06  
**Scope:** Status API (`/api/water-level/current`, `/api/water-level/latest`), 15-Day Historical Analytics (`/api/history/daily-stats`, `/api/history/readings`, `/api/history/compare`), Device Online/Offline Tracking, and Edge Case Handling.

---

## 1. Executive Summary & Architectural Role

Milestone M2 implements the REST API layer for the Smart Water Tank Level Monitoring System. While `m2_explorer_1` focuses on sensor telemetry ingestion (`POST /api/water-level`) and `m2_explorer_3` focuses on configuration (`/api/settings`) and health probes (`/api/health`), this analysis establishes the technical specification for the **monitoring and analytics core**:

1. **Real-Time Current Status API (`GET /api/water-level/current` & alias `/api/water-level/latest`)**:
   Delivers the unified snapshot required by the dashboard: device connectivity state, current tank geometry and capacity, latest sensor telemetry reading, calculated remaining empty capacity, color-coded level state, and today's summary statistics.
2. **15-Day Historical Daily Aggregates API (`GET /api/history/daily-stats`)**:
   Supplies daily aggregated min/max/average levels and volumes for Chart.js bar/line trends across the past N days (default 15).
3. **Intraday Date Readings API (`GET /api/history/readings`)**:
   Provides high-resolution time-series readings for any single calendar date (with YYYY-MM-DD validation) and associated diurnal summary.
4. **Day-to-Day Comparison API (`GET /api/history/compare`)**:
   Compares water consumption and levels between any two calendar dates side-by-side with net differential statistics and trend classification.
5. **Device Inventory Status API (`GET /api/devices`)**:
   Exposes registered devices with dynamic online/offline connectivity and elapsed communication duration.

---

## 2. Detailed Endpoint Interface Contracts

### 2.1. Real-Time Status: `GET /api/water-level/current` (and `GET /api/water-level/latest`)

- **HTTP Method**: `GET`
- **Path**: `/api/water-level/current` (Alias: `/api/water-level/latest`)
- **Query Parameters**:
  - `device_id` *(optional, string)*: Target device identifier.
    - If omitted: Resolves to `DEFAULT_DEVICE_ID` from Flask config (`"esp32_tank_01"`), or the first registered device.
    - If specified but does not exist in `devices` table: Return `HTTP 404 Not Found` with `{"error": "Device '...' not found"}` (satisfies `test_boundary_current_01_nonexistent_device_id_query`).
- **Success Status**: `200 OK`
- **Response Structure (Nominal with Readings)**:
  ```json
  {
    "device": {
      "device_id": "esp32_tank_01",
      "device_name": "Main Water Tank",
      "status": "online",
      "last_seen": "2026-11-06 14:40:00",
      "seconds_since_last_seen": 15
    },
    "tank": {
      "id": 1,
      "tank_height_cm": 200.0,
      "total_height_cm": 200.0,
      "sensor_offset_cm": 15.0,
      "total_capacity_litres": 1000.0,
      "warning_low_percent": 20.0,
      "low_threshold_percent": 20.0,
      "warning_normal_percent": 50.0,
      "critical_low_threshold_percent": 10.0,
      "offline_threshold_seconds": 300,
      "remaining_litres": 226.0,
      "level_state": "normal",
      "status_color": "green",
      "level_status": "normal"
    },
    "reading": {
      "id": 123,
      "device_id": "esp32_tank_01",
      "timestamp": "2026-11-06 14:40:00",
      "distance_cm": 45.2,
      "water_level_cm": 154.8,
      "water_percentage": 77.4,
      "water_litres": 774.0,
      "remaining_litres": 226.0,
      "level_state": "normal",
      "status_color": "green",
      "level_status": "normal"
    },
    "today_summary": {
      "date": "2026-11-06",
      "reading_count": 48,
      "min_level_cm": 120.0,
      "max_level_cm": 160.0,
      "avg_level_cm": 145.2,
      "min_percentage": 60.0,
      "max_percentage": 80.0,
      "avg_percentage": 72.6,
      "min_litres": 600.0,
      "max_litres": 800.0,
      "avg_litres": 726.0,
      "net_change_litres": 34.0
    }
  }
  ```
- **Empty Database / Zero Readings Behavior** (`test_feature6_02`, `test_boundary_current_03`):
  - Returns `HTTP 200 OK`.
  - `reading`: `null`.
  - `device.status`: `"offline"` (or evaluated from `last_seen`).
  - `device.seconds_since_last_seen`: `null` (if `last_seen` is NULL).
  - `tank.remaining_litres`: Defaults to `total_capacity_litres` (e.g. `1000.0`).
  - `tank.level_state`: `"unknown"`, `tank.status_color`: `"gray"`.
  - `today_summary`: `reading_count = 0`, with all numeric min/max/avg metrics defaulted to `0.0` (not `null`).

---

### 2.2. 15-Day Historical Daily Stats: `GET /api/history/daily-stats`

- **HTTP Method**: `GET`
- **Path**: `/api/history/daily-stats`
- **Query Parameters**:
  - `days` *(optional, default: 15)*: Number of past days to aggregate.
    - Must be a valid integer. If non-numeric (e.g. `two_weeks`): Return `HTTP 400 Bad Request` (`{"error": "Invalid days parameter, must be an integer"}`).
    - Boundary rule: `days` must be >= 1 and <= 90.
      - `days=0` or `days=-5`: Return `HTTP 400 Bad Request` (`{"error": "days parameter must be between 1 and 90"}`).
      - `days=91`: Return `HTTP 400 Bad Request` (`{"error": "days parameter must not exceed 90 days"}`).
      - `days=1`: Accepted (`HTTP 200 OK`).
  - `device_id` *(optional, string)*: Filter aggregates to a specific device.
- **Success Status**: `200 OK`
- **Response Structure**:
  ```json
  {
    "days_requested": 15,
    "daily_stats": [
      {
        "date": "2026-10-23",
        "reading_count": 48,
        "min_level_cm": 110.0,
        "max_level_cm": 170.0,
        "avg_level_cm": 142.5,
        "min_percentage": 55.0,
        "max_percentage": 85.0,
        "avg_percentage": 71.25,
        "min_litres": 550.0,
        "max_litres": 850.0,
        "avg_litres": 712.5
      }
    ],
    "stats": [
      {
        "date": "2026-10-23",
        "reading_count": 48,
        "min_level_cm": 110.0,
        "max_level_cm": 170.0,
        "avg_level_cm": 142.5,
        "min_percentage": 55.0,
        "max_percentage": 85.0,
        "avg_percentage": 71.25,
        "min_litres": 550.0,
        "max_litres": 850.0,
        "avg_litres": 712.5
      }
    ]
  }
  ```
  *(Note: Both `"daily_stats"` and `"stats"` are populated with identical lists to satisfy all test fixture access patterns).*
- **Chronological Sorting**: Elements are strictly ordered by `date ASC`.
- **Empty Result**: If no readings exist in the window, returns `{"days_requested": days, "daily_stats": [], "stats": []}` with `HTTP 200 OK`.

---

### 2.3. Intraday Date Readings: `GET /api/history/readings`

- **HTTP Method**: `GET`
- **Path**: `/api/history/readings`
- **Query Parameters**:
  - `date` *(optional, default: current calendar date `YYYY-MM-DD`)*:
    - Format validation: Regex `^\d{4}-\d{2}-\d{2}$`. If invalid (e.g. `06-11-2026`, SQL injection `2026-11-06' OR '1'='1`): Return `HTTP 400 Bad Request` (`{"error": "Invalid date format, expected YYYY-MM-DD"}`).
    - Calendar validation: `datetime.strptime(date, "%Y-%m-%d")`. If invalid date (e.g. `2026-02-31`): Return `HTTP 400 Bad Request` (`{"error": "Invalid calendar date"}`).
    - Future dates (e.g. `2099-01-01`) or far past dates (`1999-12-31`): Accepted with `HTTP 200 OK`, returning empty readings array.
  - `device_id` *(optional, string)*: Filter readings by device.
  - `limit` *(optional, integer)*: Maximum records to return.
- **Success Status**: `200 OK`
- **Response Structure**:
  ```json
  {
    "date": "2026-11-06",
    "reading_count": 2,
    "summary": {
      "date": "2026-11-06",
      "reading_count": 2,
      "min_level_cm": 140.0,
      "max_level_cm": 160.0,
      "avg_level_cm": 150.0,
      "min_percentage": 70.0,
      "max_percentage": 80.0,
      "avg_percentage": 75.0,
      "min_litres": 700.0,
      "max_litres": 800.0,
      "avg_litres": 750.0,
      "net_change_litres": 100.0
    },
    "readings": [
      {
        "id": 1,
        "device_id": "esp32_tank_01",
        "distance_cm": 60.0,
        "water_level_cm": 140.0,
        "water_percentage": 70.0,
        "water_litres": 700.0,
        "timestamp": "2026-11-06 08:00:00",
        "date": "2026-11-06"
      },
      {
        "id": 2,
        "device_id": "esp32_tank_01",
        "distance_cm": 40.0,
        "water_level_cm": 160.0,
        "water_percentage": 80.0,
        "water_litres": 800.0,
        "timestamp": "2026-11-06 14:00:00",
        "date": "2026-11-06"
      }
    ]
  }
  ```
- **Ordering**: Strict chronological ordering `ORDER BY timestamp ASC, id ASC`.

---

### 2.4. Day-to-Day Comparison: `GET /api/history/compare`

- **HTTP Method**: `GET`
- **Path**: `/api/history/compare`
- **Query Parameters**:
  - `date1` *(required, string `YYYY-MM-DD`)*: Base comparison date.
  - `date2` *(required, string `YYYY-MM-DD`)*: Target comparison date.
  - Validation:
    - Missing `date1` or `date2`: Return `HTTP 400 Bad Request` (`{"error": "Missing required query parameter: date1"}` or `date2`).
    - Format mismatch or invalid calendar (e.g. `invalid-date`): Return `HTTP 400 Bad Request`.
  - `device_id` *(optional, string)*: Target device filter.
- **Success Status**: `200 OK`
- **Response Structure**:
  ```json
  {
    "date1": {
      "date": "2026-11-01",
      "reading_count": 1,
      "readings_count": 1,
      "summary": {
        "date": "2026-11-01",
        "reading_count": 1,
        "min_level_cm": 160.0,
        "max_level_cm": 160.0,
        "avg_level_cm": 160.0,
        "min_percentage": 80.0,
        "max_percentage": 80.0,
        "avg_percentage": 80.0,
        "min_litres": 800.0,
        "max_litres": 800.0,
        "avg_litres": 800.0
      }
    },
    "date2": {
      "date": "2026-11-02",
      "reading_count": 1,
      "readings_count": 1,
      "summary": {
        "date": "2026-11-02",
        "reading_count": 1,
        "min_level_cm": 170.0,
        "max_level_cm": 170.0,
        "avg_level_cm": 170.0,
        "min_percentage": 85.0,
        "max_percentage": 85.0,
        "avg_percentage": 85.0,
        "min_litres": 850.0,
        "max_litres": 850.0,
        "avg_litres": 850.0
      }
    },
    "comparison": {
      "avg_difference_litres": 50.0,
      "avg_litres_diff": 50.0,
      "avg_difference_percentage": 5.0,
      "avg_percentage_diff": 5.0,
      "max_litres_diff": 50.0,
      "trend": "increasing"
    }
  }
  ```
  *(Note: Keys `avg_difference_litres` and `avg_litres_diff` as well as `avg_difference_percentage` and `avg_percentage_diff` are dual-aliased to guarantee compatibility with all test assertions).*
- **Comparison Trend Classification**:
  - If `reading_count == 0` for either date: `trend = "insufficient_data"`, differences = `0.0`.
  - If `date1 == date2`: Differences = `0.0`, `trend = "neutral"`.
  - If `avg_litres_diff > 0`: `trend = "increasing"`.
  - If `avg_litres_diff < 0`: `trend = "decreasing"`.
  - If `avg_litres_diff == 0`: `trend = "neutral"`.

---

### 2.5. Registered Devices: `GET /api/devices`

- **HTTP Method**: `GET`
- **Path**: `/api/devices`
- **Query Parameters**:
  - `active_only` *(optional, boolean default false)*
- **Success Status**: `200 OK`
- **Response Structure**:
  ```json
  {
    "devices": [
      {
        "device_id": "esp32_tank_01",
        "device_name": "Main Tank Sensor",
        "is_active": 1,
        "last_seen": "2026-11-06 14:40:00",
        "status": "online",
        "seconds_since_last_seen": 12,
        "created_at": "2026-11-06 14:00:00"
      }
    ]
  }
  ```
  *(Satisfies `test_feature5_05_devices_list_endpoint_shows_status`).*

---

## 3. Core Business Logic Engines

### 3.1. Device Online/Offline Engine & UTC SQLite Synchronization

#### The Core Problem
In tests (`test_tier1_features.py:292`, `test_tier2_boundaries.py:228`, `test_tier4_workloads.py:109`), test fixtures update device state using SQLite's built-in date functions:
```sql
UPDATE devices SET last_seen = datetime('now', '-300 seconds') WHERE device_id = ?;
UPDATE devices SET last_seen = datetime('now', '-301 seconds') WHERE device_id = ?;
UPDATE devices SET last_seen = datetime('now', '+10 seconds') WHERE device_id = ?;
```
SQLite's `datetime('now')` generates timestamps in UTC (`%Y-%m-%d %H:%M:%S`).
If the backend calculates elapsed seconds using Python's local `datetime.now()`, in timezones ahead of UTC (such as India Standard Time, UTC+5:30), the elapsed duration would erroneously appear as `19,800 + seconds` (5.5 hours!), immediately marking all online devices as offline.

#### The Verified Solution
1. **Compute `seconds_since_last_seen` natively within SQLite**:
   ```sql
   SELECT
       device_id, device_name, api_key, created_at, last_seen, is_active,
       CASE
           WHEN last_seen IS NULL THEN NULL
           ELSE CAST(strftime('%s', 'now') - strftime('%s', last_seen) AS INTEGER)
       END AS seconds_since_last_seen
   FROM devices
   WHERE device_id = ?
   ```
   Because both `strftime('%s', 'now')` and `strftime('%s', last_seen)` are evaluated by the SQLite engine itself in UTC, timezone drift is completely eliminated.
2. **Fallback / Parsing Rules**:
   - If `last_seen IS NULL`:
     - `status = "offline"`
     - `seconds_since_last_seen = None`
   - If `last_seen` exists:
     - `raw_seconds_diff = row["seconds_since_last_seen"]`
     - Online check: `is_online = (raw_seconds_diff <= offline_threshold_seconds)`
       - Exactly 300s: `300 <= 300` -> **`online`** (`test_boundary_online_01`)
       - 301s: `301 <= 300` -> False -> **`offline`** (`test_boundary_online_02`)
       - 0s: `0 <= 300` -> **`online`** (`test_boundary_online_03`)
       - Clock drift / Future timestamp (-10s): `-10 <= 300` -> **`online`** (`test_boundary_online_04`)
     - Normalized `seconds_since_last_seen`:
       - If `raw_seconds_diff < 0`: clamp to `0` (so future timestamp returns `0`, non-negative integer).
       - Else: `int(raw_seconds_diff)`.
     - `status = "online" if is_online else "offline"`.
   - Dynamic threshold: `offline_threshold_seconds` is loaded directly from `tank_settings` (id=1) on every request, ensuring that PUT `/api/settings` immediately alters connectivity evaluation (`test_boundary_online_05`, `test_interaction_06`).

---

### 3.2. Level State & 4-Color Indicator Classification Matrix

The system dynamically classifies tank level states into 4 status colors based on `tank_settings`:
- `critical_low_threshold_percent` (default 10.0%)
- `low_threshold_percent` (default 20.0%)
- `warning_normal_percent` (default 50.0%)

```python
def compute_level_state(
    water_percentage: float,
    tank_settings: Dict[str, Any]
) -> Tuple[str, str, str]:
    """
    Returns (level_state, status_color, level_status).
    """
    crit_low = float(tank_settings.get("critical_low_threshold_percent", 10.0))
    low_thresh = float(tank_settings.get("low_threshold_percent", 20.0))
    normal_thresh = float(tank_settings.get("warning_normal_percent", 50.0))

    if water_percentage < crit_low:
        # e.g., 7.5% -> critical, red, low
        return "critical_low", "red", "critical_low"
    elif water_percentage < low_thresh:
        # e.g., 15.0% -> warning, orange, low
        return "warning_low", "orange", "warning_low"
    elif water_percentage < normal_thresh:
        # e.g., 45.0% -> low / warning, orange
        return "low", "orange", "low"
    else:
        # e.g., >= 50.0% -> normal, green
        return "normal", "green", "normal"
```

#### Multi-Key Compliance
To guarantee compatibility with all test assertions and frontend expectations:
- In `reading`: include `level_state`, `status_color`, `level_status`, and `remaining_litres`.
- In `tank`: include `level_state`, `status_color`, `level_status`, and `remaining_litres`.
- Remaining litres calculation:
  ```python
  remaining_litres = round(max(0.0, total_capacity_litres - water_litres), 2)
  ```
  When `total_capacity_litres` is updated via settings, `remaining_litres` immediately recalculates against the latest reading (`test_interaction_05`, `test_tier4_workloads:250`).

---

## 4. Recommended Route Implementation (`app/routes/api.py`)

Here is the exact code specification for the Status and History endpoints:

```python
"""
app/routes/api.py - Telemetry, Status, and Historical Analytics Blueprint
"""

from datetime import datetime, timedelta
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
)

api_bp = Blueprint("api", __name__, url_prefix="/api")


# ------------------------------------------------------------------------------
# Helper Functions
# ------------------------------------------------------------------------------

def _get_device_with_status(device_id: str, offline_threshold: int) -> Optional[Dict[str, Any]]:
    """
    Queries device with SQLite-calculated seconds_since_last_seen in UTC.
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
        (device_id,)
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


def _evaluate_level_state(percentage: float, settings: Dict[str, Any]) -> Dict[str, str]:
    crit_low = float(settings.get("critical_low_threshold_percent", 10.0))
    low_thresh = float(settings.get("low_threshold_percent", 20.0))
    normal_thresh = float(settings.get("warning_normal_percent", 50.0))

    if percentage < crit_low:
        return {"level_state": "critical_low", "status_color": "red", "level_status": "critical_low"}
    elif percentage < low_thresh:
        return {"level_state": "warning_low", "status_color": "orange", "level_status": "warning_low"}
    elif percentage < normal_thresh:
        return {"level_state": "low", "status_color": "orange", "level_status": "low"}
    else:
        return {"level_state": "normal", "status_color": "green", "level_status": "normal"}


# ------------------------------------------------------------------------------
# 1. Status Endpoints: /api/water-level/current and /api/water-level/latest
# ------------------------------------------------------------------------------

@api_bp.route("/water-level/current", methods=["GET"])
@api_bp.route("/water-level/latest", methods=["GET"])
def get_current_water_level():
    req_device_id = request.args.get("device_id")
    tank_settings = get_tank_settings()
    offline_threshold = tank_settings.get("offline_threshold_seconds", 300)

    # Resolve target device
    if req_device_id:
        device = _get_device_with_status(req_device_id, offline_threshold)
        if not device:
            return jsonify({"error": f"Device '{req_device_id}' not found"}), 404
    else:
        default_id = current_app.config.get("DEFAULT_DEVICE_ID", "esp32_tank_01")
        device = _get_device_with_status(default_id, offline_threshold)
        if not device:
            # Fallback for unseeded/blank database
            device = {
                "device_id": default_id,
                "device_name": "Main Water Tank",
                "status": "offline",
                "last_seen": None,
                "seconds_since_last_seen": None,
            }

    dev_id = device["device_id"]
    reading = get_latest_reading(device_id=dev_id)
    today_summary = get_today_summary(device_id=dev_id)

    # Sanitize today_summary for empty readings
    for k in ("min_level_cm", "max_level_cm", "avg_level_cm", "min_percentage",
              "max_percentage", "avg_percentage", "min_litres", "max_litres", "avg_litres", "net_change_litres"):
        if today_summary.get(k) is None:
            today_summary[k] = 0.0

    tank_info = dict(tank_settings)
    total_capacity = float(tank_settings.get("total_capacity_litres", 1000.0))

    if reading is not None:
        water_litres = float(reading.get("water_litres", 0.0))
        water_pct = float(reading.get("water_percentage", 0.0))
        remaining = round(max(0.0, total_capacity - water_litres), 2)

        states = _evaluate_level_state(water_pct, tank_settings)
        reading["remaining_litres"] = remaining
        reading.update(states)

        tank_info["remaining_litres"] = remaining
        tank_info.update(states)
    else:
        tank_info["remaining_litres"] = total_capacity
        tank_info["level_state"] = "unknown"
        tank_info["status_color"] = "gray"
        tank_info["level_status"] = "unknown"

    return jsonify({
        "device": device,
        "tank": tank_info,
        "reading": reading,
        "today_summary": today_summary
    }), 200


# ------------------------------------------------------------------------------
# 2. 15-Day Historical Daily Aggregates: /api/history/daily-stats
# ------------------------------------------------------------------------------

@api_bp.route("/history/daily-stats", methods=["GET"])
def get_daily_historical_stats():
    days_param = request.args.get("days", "15")
    try:
        days = int(days_param)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid days parameter, must be an integer"}), 400

    if days < 1 or days > 90:
        return jsonify({"error": "days parameter must be between 1 and 90"}), 400

    device_id = request.args.get("device_id")
    stats = get_daily_stats(days=days, device_id=device_id)

    return jsonify({
        "days_requested": days,
        "daily_stats": stats,
        "stats": stats
    }), 200


# ------------------------------------------------------------------------------
# 3. Intraday Readings: /api/history/readings
# ------------------------------------------------------------------------------

@api_bp.route("/history/readings", methods=["GET"])
def get_intraday_readings():
    date_str = request.args.get("date")
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    else:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            return jsonify({"error": "Invalid date format, expected YYYY-MM-DD"}), 400
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "Invalid calendar date"}), 400

    device_id = request.args.get("device_id")
    limit = request.args.get("limit", type=int)

    readings = get_readings_by_date(date_str=date_str, device_id=device_id, limit=limit)
    summary = get_today_summary(device_id=device_id, date_str=date_str)

    for k in ("min_level_cm", "max_level_cm", "avg_level_cm", "min_percentage",
              "max_percentage", "avg_percentage", "min_litres", "max_litres", "avg_litres", "net_change_litres"):
        if summary.get(k) is None:
            summary[k] = 0.0

    return jsonify({
        "date": date_str,
        "reading_count": len(readings),
        "summary": summary,
        "readings": readings
    }), 200


# ------------------------------------------------------------------------------
# 4. Day-to-Day Comparison: /api/history/compare
# ------------------------------------------------------------------------------

@api_bp.route("/history/compare", methods=["GET"])
def get_day_comparison():
    date1_str = request.args.get("date1")
    date2_str = request.args.get("date2")

    if not date1_str:
        return jsonify({"error": "Missing required query parameter: date1"}), 400
    if not date2_str:
        return jsonify({"error": "Missing required query parameter: date2"}), 400

    for d, label in ((date1_str, "date1"), (date2_str, "date2")):
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
            return jsonify({"error": f"Invalid {label} format, expected YYYY-MM-DD"}), 400
        try:
            datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": f"Invalid calendar date for {label}"}), 400

    device_id = request.args.get("device_id")
    result = compare_dates(date1_str=date1_str, date2_str=date2_str, device_id=device_id)

    # Ensure dual aliasing on comparison keys
    comp = result.get("comparison", {})
    comp["avg_difference_litres"] = comp.get("avg_litres_diff", 0.0)
    comp["avg_difference_percentage"] = comp.get("avg_percentage_diff", 0.0)

    # Ensure dual aliasing on date reading counts
    for date_key in ("date1", "date2"):
        if date_key in result:
            c = result[date_key].get("readings_count", 0)
            result[date_key]["reading_count"] = c
            result[date_key]["readings_count"] = c

    return jsonify(result), 200


# ------------------------------------------------------------------------------
# 5. Device Inventory: /api/devices
# ------------------------------------------------------------------------------

@api_bp.route("/devices", methods=["GET"])
def list_devices():
    active_only = request.args.get("active_only", "false").lower() in ("true", "1", "yes")
    settings = get_tank_settings()
    offline_threshold = settings.get("offline_threshold_seconds", 300)

    devices = get_all_devices(active_only=active_only)
    result = []
    for d in devices:
        enriched = _get_device_with_status(d["device_id"], offline_threshold)
        if enriched:
            # Mask sensitive API key from public list
            enriched.pop("api_key", None)
            result.append(enriched)

    return jsonify({"devices": result}), 200
```

---

## 5. Recommended DAL Refinement (`app/models.py`)

In `app/models.py`, `compare_dates` should be enhanced to include both `avg_difference_litres` and `avg_difference_percentage` aliases directly:

```python
# In app/models.py -> compare_dates()
    return {
        "date1": {
            "date": date1_str,
            "readings_count": count1,
            "reading_count": count1,
            "summary": stats1
        },
        "date2": {
            "date": date2_str,
            "readings_count": count2,
            "reading_count": count2,
            "summary": stats2
        },
        "comparison": {
            "avg_difference_litres": avg_litres_diff,
            "avg_litres_diff": avg_litres_diff,
            "avg_difference_percentage": avg_pct_diff,
            "avg_percentage_diff": avg_pct_diff,
            "max_litres_diff": max_litres_diff,
            "trend": trend
        }
    }
```

Also, in `get_today_summary()`, ensure that when `reading_count == 0`, all min/max/avg fields default to `0.0` rather than `None`.

---

## 6. Test Traceability Matrix

| Feature / Boundary / Interaction | Target Test Case | Covered Requirement |
|---|---|---|
| **Feature 5 (Online/Offline)** | `test_feature5_01` (recent reading is online) | Online state on fresh telemetry |
| | `test_feature5_02` (exceeding threshold is offline) | Offline state past threshold |
| | `test_feature5_03` (NULL last_seen is offline) | Uninitialized device handling |
| | `test_feature5_04` (numeric seconds_since_last_seen) | Integer elapsed duration in response |
| | `test_feature5_05` (GET /api/devices list) | Device inventory endpoint |
| **Feature 6 (Current Status)** | `test_feature6_01` (response schema validation) | Full status JSON schema |
| | `test_feature6_02` (empty DB handles gracefully) | `reading=null`, `device.status=offline` |
| | `test_feature6_03` (remaining litres calculation) | `capacity - water_litres` accuracy |
| | `test_feature6_04` (tank settings presence) | Tank geometry & thresholds in response |
| | `test_feature6_05` (today summary metrics) | Scorecard with min/max/avg metrics |
| **Feature 7 (Daily Stats)** | `test_feature7_01` (HTTP 200 & array) | Historical daily stats list |
| | `test_feature7_02` (min/max/avg statistical accuracy) | Accurate aggregations per day |
| | `test_feature7_03` (respects days parameter) | `days_requested` matching query |
| | `test_feature7_04` (chronological order ASC) | ASC date ordering |
| | `test_feature7_05` (device_id filtering) | Multi-device isolation |
| **Feature 8 (Intraday Readings)** | `test_feature8_01` (HTTP 200 & readings list) | Time-series readings for date |
| | `test_feature8_02` (defaults to today) | Default date resolution |
| | `test_feature8_03` (empty date returns empty array) | Graceful empty array on 0 readings |
| | `test_feature8_04` (includes day summary) | Intraday summary scorecard |
| | `test_feature8_05` (chronological sorting ASC) | Timestamp order preservation |
| **Feature 9 (Day Comparison)** | `test_feature9_01` (requires date1 & date2) | 400 Bad Request on missing params |
| | `test_feature9_02` (compare two dates schema) | Side-by-side comparison structure |
| | `test_feature9_03` (litres delta calculation) | `date2 - date1` volume net change |
| | `test_feature9_04` (percentage delta calculation)| `date2 - date1` percentage net change |
| | `test_feature9_05` (identical dates returns 0) | Zero difference & neutral trend |
| **Boundary 5 (Timeout Edges)** | `test_boundary_online_01` (300s exact boundary) | `<=` threshold remains online |
| | `test_boundary_online_02` (301s boundary + 1s) | `>` threshold triggers offline |
| | `test_boundary_online_03` (0s elapsed) | Immediate 0s online check |
| | `test_boundary_online_04` (future timestamp +10s) | Clock drift robustness, returns online |
| | `test_boundary_online_05` (dynamic threshold update)| Settings threshold update reflects live |
| **Boundary 6 (Status Edges)** | `test_boundary_current_01` (non-existent device) | HTTP 404 on unknown device ID |
| | `test_boundary_current_02` (NULL last_seen) | Offline status & seconds_since=null |
| | `test_boundary_current_03` (0 readings) | Reading is null |
| | `test_boundary_current_04` (critical low <10%) | `level_state="critical_low"`, red |
| | `test_boundary_current_05` (warning low 15%) | `level_state="warning_low"`, orange |
| **Boundary 7 (Daily Stats)** | `test_boundary_daily_stats_01` (`days=0`) | HTTP 400 Bad Request |
| | `test_boundary_daily_stats_02` (`days=-5`) | HTTP 400 Bad Request |
| | `test_boundary_daily_stats_03` (`days=91`) | HTTP 400 Bad Request (exceeds 90) |
| | `test_boundary_daily_stats_04` (`days=two_weeks`) | HTTP 400 Bad Request (non-numeric) |
| | `test_boundary_daily_stats_05` (`days=1`) | HTTP 200 OK (lower boundary) |
| **Boundary 8 (Readings Date)** | `test_boundary_readings_01` (`06-11-2026`) | HTTP 400 Bad Request (wrong format) |
| | `test_boundary_readings_02` (`2026-02-31`) | HTTP 400 Bad Request (invalid date) |
| | `test_boundary_readings_03` (future date `2099`) | HTTP 200 OK with empty readings |
| | `test_boundary_readings_04` (past date `1999`) | HTTP 200 OK with empty readings |
| | `test_boundary_readings_05` (SQL injection attempt)| HTTP 400 Bad Request rejection |
| **Boundary 9 (Compare Edges)** | `test_boundary_compare_01` (missing date1) | HTTP 400 Bad Request |
| | `test_boundary_compare_02` (missing date2) | HTTP 400 Bad Request |
| | `test_boundary_compare_03` (malformed date1) | HTTP 400 Bad Request |
| | `test_boundary_compare_04` (malformed date2) | HTTP 400 Bad Request |
| | `test_boundary_compare_05` (empty DB compare) | HTTP 200 OK with neutral/insufficient |
| **Tier 3 (Interactions)** | `test_interaction_01` (Ingest -> Current Status) | Ingestion updates status immediately |
| | `test_interaction_02` (Ingest -> Daily Stats) | Readings update daily stats |
| | `test_interaction_03` (Ingest -> Intraday Readings)| Readings update today list |
| | `test_interaction_04` (Ingest -> Compare) | Multi-day readings update comparison |
| | `test_interaction_05` (Settings -> Remaining Litres)| Changing capacity alters remaining volume |
| | `test_interaction_06` (Settings -> Device Timeout)| Changing timeout flips online/offline |
| | `test_interaction_13` (Multi-Tank Status Isolation) | Different devices maintain separate status |
| | `test_interaction_16` (Settings -> Level Status Color)| Threshold update changes status color |
| **Tier 4 (Workloads)** | `test_workload_15_day_inflow_outflow_simulation` | 15-day diurnal flow math & comparison |
| | `test_workload_sensor_disconnection_and_recovery` | Offline at 400s -> recovery to online |
| | `test_workload_tank_geometry_and_calibration_shift` | Live geometry shift updates remaining L |
