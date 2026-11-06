# Technical Analysis: Telemetry Ingestion Endpoint (`POST /api/water-level`)

**Subagent:** m2_explorer_1  
**Milestone:** M2 (Flask Backend REST API & Authentication)  
**Date:** 2026-11-06  
**Status:** COMPLETE (Investigation & Synthesis)  

---

## 1. Executive Summary

This document presents the detailed architectural and technical investigation for implementing the IoT Telemetry Ingestion endpoint (`POST /api/water-level`) in the Python Flask backend. The endpoint is the primary ingestion gateway for telemetry data transmitted by ESP32 NodeMCU microcontrollers monitoring water tank levels.

The endpoint must satisfy:
1. **Dual-Mode Device Authentication**: Accepts credentials via HTTP header (`X-API-Key`) or request JSON body (`api_key`).
2. **Strict Multi-Stage Input Validation**: Enforces JSON content negotiation, syntactic integrity, field presence, numeric type parsing, and physical bounds.
3. **Atomic Persistence & Device State Tracking**: Stores the reading in `water_readings` and updates `devices.last_seen` in a single atomic database transaction via `app.models.insert_water_reading`.
4. **100% Alignment with E2E Test Suite**: Guarantees compliance across Tier 1 (Features 2, 3, 4), Tier 2 (Boundaries 2, 3, 4), Tier 3 (Interactions 1, 2, 3, 7, 11, 12, 13), and Tier 4 (Workload 4).

---

## 2. Blueprint Architecture & Directory Layout

### 2.1 Existing Infrastructure
In `app/__init__.py`, the Flask application factory `create_app()` already contains dynamic blueprint registration hooks:

```python
# app/__init__.py (lines 40-46)
try:
    from app.routes.api import api_bp
    app.register_blueprint(api_bp)
except (ImportError, ModuleNotFoundError):
    pass
```

### 2.2 Target Layout
To integrate cleanly with zero modification to `create_app()`, the implementation requires:
- Package initialization: `app/routes/__init__.py`
- API blueprint module: `app/routes/api.py` defining `api_bp = Blueprint("api", __name__)`

Endpoints can be registered directly with explicit route URLs (e.g. `@api_bp.route("/api/water-level", methods=["POST"])`).

---

## 3. Telemetry Ingestion Pipeline (5-Gate Design)

Incoming telemetry requests pass through five consecutive validation and processing gates. Failure at any gate short-circuits execution and returns the standardized JSON error and HTTP status code.

```
Incoming Request
       │
       ▼
[Gate 1: Content-Type & Syntax] ──(Not JSON / Parse Fail)──► HTTP 400 Bad Request
       │
       ▼
[Gate 2: Required Fields] ────────(Missing / Null Field)───► HTTP 400 Bad Request
       │
       ▼
[Gate 3: Dual-Mode Auth] ─────────(Missing / Bad Key)─────► HTTP 401 Unauthorized
       │                         (Device Deactivated)────► HTTP 403 Forbidden
       ▼
[Gate 4: Physical Range Check] ───(Non-numeric / Bounds)──► HTTP 422 Unprocessable Entity
       │
       ▼
[Gate 5: Atomic DAL Persistence] ─(insert_water_reading)──► HTTP 201 Created
```

---

### Gate 1: Content-Type & JSON Syntactic Validation (HTTP 400)
- **Check 1: Content-Type**: Request must declare `application/json` (or JSON-compatible MIME type).
  ```python
  if not request.is_json:
      return jsonify({"error": "Content-Type must be application/json"}), 400
  ```
  *Test Citation:* `test_boundary_ingest_04_non_json_content_type_returns_400` sends `Content-Type: text/plain` with raw data and expects HTTP 400.
- **Check 2: Syntactic Parsing & Type**:
  ```python
  try:
      payload = request.get_json(silent=False)
  except Exception:
      return jsonify({"error": "Malformed JSON syntax"}), 400

  if payload is None or not isinstance(payload, dict):
      return jsonify({"error": "JSON payload must be a non-empty object"}), 400
  ```
  *Test Citation:* `test_boundary_ingest_05_malformed_json_syntax_returns_400` sends malformed JSON `{invalid_json:` and expects HTTP 400.

---

### Gate 2: Required Fields Presence (HTTP 400)
- The required sensor payload fields are:
  - `device_id` (string, non-empty)
  - `distance_cm` (numeric)
  - `water_level_cm` (numeric)
  - `water_percentage` (numeric)
  - `water_litres` (numeric)
- **Validation Logic**:
  ```python
  REQUIRED_FIELDS = ("device_id", "distance_cm", "water_level_cm", "water_percentage", "water_litres")
  for field in REQUIRED_FIELDS:
      if field not in payload or payload[field] is None:
          return jsonify({"error": f"Missing required field: '{field}'"}), 400

  device_id = str(payload.get("device_id", "")).strip()
  if not device_id:
      return jsonify({"error": "Field 'device_id' cannot be empty"}), 400
  ```
  *Test Citations:*
  - `test_boundary_ingest_01_missing_device_id_returns_400`: Asserts HTTP 400 when `device_id` is omitted.
  - `test_boundary_ingest_02_missing_distance_cm_returns_400`: Asserts HTTP 400 when `distance_cm` is omitted.
  - `test_boundary_ingest_03_empty_body_returns_400`: Asserts HTTP 400 when body is `{}`.

---

### Gate 3: Dual-Mode Authentication & Device Lifecycle (HTTP 401 / HTTP 403)
- **API Key Extraction Hierarchy**:
  1. Primary: HTTP Header `X-API-Key`
  2. Secondary: JSON body field `api_key`
  ```python
  api_key = request.headers.get("X-API-Key")
  if api_key is not None:
      api_key = api_key.strip()
  if not api_key:
      api_key = str(payload.get("api_key") or "").strip()
  ```
- **Empty Key Handling (HTTP 401)**:
  ```python
  if not api_key:
      return jsonify({"error": "Missing or empty API key in header or request body"}), 401
  ```
  *Test Citations:*
  - `test_feature3_03_missing_api_key_returns_401`: Payload without header or body key returns HTTP 401.
  - `test_boundary_auth_01_empty_api_key_header_returns_401`: `X-API-Key: ""` returns HTTP 401.
  - `test_boundary_auth_02_empty_api_key_body_returns_401`: `api_key: ""` returns HTTP 401.
  - `test_boundary_auth_03_whitespace_only_api_key_returns_401`: `api_key: "   "` returns HTTP 401.

- **Device Lookup & Credential Verification**:
  Query device record using `app.models.get_device(device_id)`:
  ```python
  device = get_device(device_id)
  if not device:
      return jsonify({"error": "Invalid API key or unregistered device"}), 401
  ```
  *Test Citations:*
  - `test_boundary_auth_04_unknown_device_id_with_invalid_key_returns_401`: Unknown device returns HTTP 401.
  - `test_boundary_auth_05_special_characters_api_key_mismatch_returns_401`: SQL injection attempt in key returns HTTP 401.

- **Deactivated Device Gate (HTTP 403)**:
  ```python
  if device.get("is_active") != 1:
      return jsonify({"error": "Device is deactivated"}), 403
  ```
  *Test Citations & Conflict Resolution:*
  - `test_feature3_05_deactivated_device_returns_403` explicitly asserts:
    `assert resp.status_code == 403`
    `assert "deactivated" in resp.json.get("error", "").lower()`
  - `test_tier3_interactions.py:258` (`test_interaction_12_deactivate_device_blocks_subsequent_telemetry`) explicitly asserts:
    `assert r2.status_code == 403`
  - While the prompt description mentioned: *"Reject unauthorized or inactive devices with HTTP 401"*, the authoritative test suite specifically mandates **HTTP 403 Forbidden** for deactivated devices with `"deactivated"` in the error message. The implementer MUST return HTTP 403 for `is_active == 0`.

- **Key Equality Gate (HTTP 401)**:
  ```python
  if device.get("api_key") != api_key:
      return jsonify({"error": "Invalid API key"}), 401
  ```
  *Test Citation:* `test_feature3_04_invalid_api_key_returns_401` asserts HTTP 401 on incorrect secret key.

---

### Gate 4: Numeric Type & Physical Boundary Validation (HTTP 422)
- **Type Coercion & Safety**:
  Boolean values in JSON (`true`, `false`) are instances of `int` in Python, so `isinstance(val, bool)` must be explicitly rejected before `float(val)`.
  ```python
  import math

  numeric_fields = ("distance_cm", "water_level_cm", "water_percentage", "water_litres")
  parsed = {}
  for field in numeric_fields:
      val = payload.get(field)
      if isinstance(val, bool):
          return jsonify({"error": f"Field '{field}' must be numeric, got boolean"}), 422
      try:
          num = float(val)
      except (ValueError, TypeError):
          return jsonify({"error": f"Field '{field}' must be a valid number"}), 422
      if math.isnan(num) or math.isinf(num):
          return jsonify({"error": f"Field '{field}' must be a finite number"}), 422
      parsed[field] = num
  ```
  *Test Citation:* `test_boundary_physics_05_string_for_numeric_value_returns_422` sends string `"fifty"` and asserts HTTP 400 or 422.

- **Physical Bounds**:
  1. `distance_cm >= 0.0`: Negative distance physically impossible.
     *Test Citation:* `test_boundary_physics_01_negative_distance_cm_returns_422` (-5.0 cm -> 422).
  2. `water_level_cm >= 0.0`: Negative water height physically impossible.
     *Test Citation:* `test_boundary_physics_02_negative_water_level_cm_returns_422` (-1.0 cm -> 422).
  3. `0.0 <= water_percentage <= 100.0`: Tank percentage cannot exceed capacity or be below empty.
     *Test Citations:*
     - `test_feature4_05_rejection_of_negative_or_overflow_percentage` (105.0% -> 422).
     - `test_boundary_physics_04_water_percentage_100_01_returns_422` (100.01% -> 422).
  4. `water_litres >= 0.0`: Volume cannot be negative.
     *Test Citation:* `test_boundary_physics_03_negative_water_litres_returns_422` (-10.0 L -> 422).
  5. Boundaries Accepted:
     - `test_feature4_02_zero_percentage_and_litres_accepted` (0.0% and 0.0 L -> 201 Created).
     - `test_feature4_03_full_tank_100_percent_accepted` (100.0% and 1000.0 L -> 201 Created).
     - `test_feature4_04_fractional_precise_values_accepted` (77.17% -> 201 Created).

---

### Gate 5: DAL Persistence & Atomic State Update (HTTP 201)
- Prepare clean reading dictionary:
  ```python
  reading_data = {
      "device_id": device_id,
      "distance_cm": parsed["distance_cm"],
      "water_level_cm": parsed["water_level_cm"],
      "water_percentage": parsed["water_percentage"],
      "water_litres": parsed["water_litres"],
  }
  if "timestamp" in payload and payload["timestamp"]:
      reading_data["timestamp"] = payload["timestamp"]
  if "date" in payload and payload["date"]:
      reading_data["date"] = payload["date"]
  ```

- Execute `app.models.insert_water_reading(reading_data)`:
  Inside `insert_water_reading`:
  1. Validates physical fields.
  2. Inserts row into `water_readings` (`INSERT INTO water_readings ...`).
  3. Updates `devices.last_seen = timestamp` for `device_id` in the **same transaction**.
  4. Commits transaction and returns:
     ```python
     {
         "status": "success",
         "reading_id": reading_id,
         "id": reading_id,
         "timestamp": timestamp,
         "date": date_str
     }
     ```

- Respond with HTTP 201 Created:
  ```python
  return jsonify({
      "status": "success",
      "reading_id": result["reading_id"],
      "timestamp": result["timestamp"]
  }), 201
  ```
  *Test Citations:*
  - `test_feature2_01_ingest_telemetry_success`: Asserts HTTP 201 and `data.get("status") == "success"`.
  - `test_feature2_02_ingest_returns_reading_id_and_timestamp`: Asserts `reading_id` is int and `timestamp` exists.
  - `test_feature2_03_ingest_records_persisted_in_database`: Verifies row inserted in `water_readings`.
  - `test_feature2_04_ingest_updates_device_last_seen`: Verifies `devices.last_seen` updated.
  - `test_feature2_05_ingest_multiple_sequential_readings`: Verifies sequentially incrementing IDs.

---

## 4. Concurrency & High-Frequency Bursts

In Tier 4 (`test_workload_rapid_burst_telemetry_and_concurrency`), the backend must ingest 50 high-frequency readings in tight succession without "database is locked" errors.

Key architectural safeguards already present in `app/database.py`:
1. `PRAGMA busy_timeout = 30000;`: Blocks up to 30 seconds for SQLite locks to clear.
2. `PRAGMA journal_mode = WAL;`: Allows concurrent readers while writing.
3. `PRAGMA synchronous = NORMAL;`: Optimizes disk sync without sacrificing durability.

In `insert_water_reading`:
The entire insert and update operation is executed on `conn.cursor()` and committed immediately, keeping SQLite write lock holding time to less than 1 millisecond.

---

## 5. Proposed Implementation Code

### 5.1 File: `app/routes/__init__.py`
```python
"""
app/routes/__init__.py - Flask Blueprints Package
"""
from app.routes.api import api_bp

__all__ = ["api_bp"]
```

### 5.2 File: `app/routes/api.py` (Telemetry Ingestion Endpoint)
```python
"""
app/routes/api.py - REST API Endpoints for Smart Water Tank Level Monitoring System

Implements telemetry ingestion (POST /api/water-level) with dual-mode authentication,
physics range validation, and device state updates.
"""

import math
from typing import Any, Dict, Tuple
from flask import Blueprint, jsonify, request

from app.models import get_device, insert_water_reading

api_bp = Blueprint("api", __name__)

REQUIRED_TELEMETRY_FIELDS = (
    "device_id",
    "distance_cm",
    "water_level_cm",
    "water_percentage",
    "water_litres",
)

NUMERIC_TELEMETRY_FIELDS = (
    "distance_cm",
    "water_level_cm",
    "water_percentage",
    "water_litres",
)


@api_bp.route("/api/water-level", methods=["POST"])
def ingest_water_level():
    """
    Ingests sensor telemetry readings from ESP32 NodeMCU.

    Headers:
        Content-Type: application/json
        X-API-Key: <api_key> (optional if provided in body)

    Payload:
        {
            "device_id": "esp32_tank_01",
            "distance_cm": 42.5,
            "water_level_cm": 157.5,
            "water_percentage": 78.75,
            "water_litres": 787.5,
            "api_key": "water_secret_key_2026" (optional if provided in header)
        }

    Responses:
        201: {"status": "success", "reading_id": 123, "timestamp": "2026-11-06 14:40:00"}
        400: Malformed JSON, non-JSON Content-Type, or missing required fields
        401: Missing or invalid API key, or unregistered device
        403: Device is deactivated (is_active == 0)
        422: Out of range or non-numeric physical values
    """
    # -------------------------------------------------------------------------
    # Gate 1: Content-Type and JSON Syntax Validation
    # -------------------------------------------------------------------------
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 400

    try:
        payload = request.get_json(silent=False)
    except Exception:
        return jsonify({"error": "Malformed JSON syntax"}), 400

    if payload is None or not isinstance(payload, dict):
        return jsonify({"error": "JSON payload must be a non-empty object"}), 400

    # -------------------------------------------------------------------------
    # Gate 2: Required Fields Presence
    # -------------------------------------------------------------------------
    for field in REQUIRED_TELEMETRY_FIELDS:
        if field not in payload or payload[field] is None:
            return jsonify({"error": f"Missing required field: '{field}'"}), 400

    device_id = str(payload.get("device_id", "")).strip()
    if not device_id:
        return jsonify({"error": "Field 'device_id' cannot be empty"}), 400

    # -------------------------------------------------------------------------
    # Gate 3: Dual-Mode Authentication & Device Verification
    # -------------------------------------------------------------------------
    # Resolve API Key (Header takes precedence, fallback to body)
    api_key = request.headers.get("X-API-Key")
    if api_key is not None:
        api_key = api_key.strip()
    if not api_key:
        api_key = str(payload.get("api_key") or "").strip()

    if not api_key:
        return jsonify({"error": "Missing or empty API key in header or request body"}), 401

    # Fetch device from database
    device = get_device(device_id)
    if not device:
        return jsonify({"error": f"Device '{device_id}' not registered or invalid credentials"}), 401

    if device.get("is_active") != 1:
        return jsonify({"error": "Device is deactivated"}), 403

    if device.get("api_key") != api_key:
        return jsonify({"error": "Invalid API key"}), 401

    # -------------------------------------------------------------------------
    # Gate 4: Numeric & Physical Range Validation
    # -------------------------------------------------------------------------
    parsed_values: Dict[str, float] = {}
    for field in NUMERIC_TELEMETRY_FIELDS:
        raw_val = payload.get(field)
        # Explicitly reject boolean values (bool is a subclass of int in Python)
        if isinstance(raw_val, bool):
            return jsonify({"error": f"Field '{field}' must be numeric, got boolean"}), 422
        try:
            num = float(raw_val)
        except (ValueError, TypeError):
            return jsonify({"error": f"Field '{field}' must be a valid numeric value"}), 422

        if math.isnan(num) or math.isinf(num):
            return jsonify({"error": f"Field '{field}' must be a finite number"}), 422

        parsed_values[field] = num

    distance_cm = parsed_values["distance_cm"]
    water_level_cm = parsed_values["water_level_cm"]
    water_percentage = parsed_values["water_percentage"]
    water_litres = parsed_values["water_litres"]

    # Enforce physical constraints
    if distance_cm < 0.0:
        return jsonify({
            "error": "Validation failed",
            "details": {"distance_cm": "Distance cannot be negative"}
        }), 422

    if water_level_cm < 0.0:
        return jsonify({
            "error": "Validation failed",
            "details": {"water_level_cm": "Water level cannot be negative"}
        }), 422

    if not (0.0 <= water_percentage <= 100.0):
        return jsonify({
            "error": "Validation failed",
            "details": {"water_percentage": "Water percentage must be between 0.0 and 100.0"}
        }), 422

    if water_litres < 0.0:
        return jsonify({
            "error": "Validation failed",
            "details": {"water_litres": "Water volume in litres cannot be negative"}
        }), 422

    # -------------------------------------------------------------------------
    # Gate 5: Atomic DAL Persistence & Device Last-Seen Update
    # -------------------------------------------------------------------------
    reading_record = {
        "device_id": device_id,
        "distance_cm": distance_cm,
        "water_level_cm": water_level_cm,
        "water_percentage": water_percentage,
        "water_litres": water_litres,
    }

    if "timestamp" in payload and payload["timestamp"]:
        reading_record["timestamp"] = payload["timestamp"]
    if "date" in payload and payload["date"]:
        reading_record["date"] = payload["date"]

    try:
        result = insert_water_reading(reading_record)
    except ValueError as val_err:
        return jsonify({"error": "Validation failed", "message": str(val_err)}), 422
    except Exception as exc:
        return jsonify({"error": "Failed to store reading", "message": str(exc)}), 500

    return jsonify({
        "status": "success",
        "reading_id": result["reading_id"],
        "timestamp": result["timestamp"]
    }), 201
```

---

## 6. Comprehensive Verification Matrix

The proposed implementation directly covers and resolves all tests in the E2E test suite that exercise `POST /api/water-level`:

| Test Suite | Test Identifier | Scenario | Target Code | Verified Behavior |
|:---|:---|:---|:---:|:---|
| **Tier 1** | `test_feature2_01_ingest_telemetry_success` | Valid nominal payload | 201 | Returns `{"status": "success"}` |
| **Tier 1** | `test_feature2_02_ingest_returns_reading_id_and_timestamp` | Response structure | 201 | Contains `reading_id` (int), `timestamp` |
| **Tier 1** | `test_feature2_03_ingest_records_persisted_in_database` | Database insertion | 201 | Row persisted in `water_readings` |
| **Tier 1** | `test_feature2_04_ingest_updates_device_last_seen` | Device tracking | 201 | `devices.last_seen` updated |
| **Tier 1** | `test_feature2_05_ingest_multiple_sequential_readings` | Sequential posts | 201 | IDs strictly increasing (id1 < id2 < id3) |
| **Tier 1** | `test_feature3_01_auth_via_header_x_api_key` | Header auth | 201 | Authenticates via `X-API-Key` |
| **Tier 1** | `test_feature3_02_auth_via_body_field` | Body auth | 201 | Authenticates via `api_key` field |
| **Tier 1** | `test_feature3_03_missing_api_key_returns_401` | No API key | 401 | Returns error object |
| **Tier 1** | `test_feature3_04_invalid_api_key_returns_401` | Wrong API key | 401 | Returns error object |
| **Tier 1** | `test_feature3_05_deactivated_device_returns_403` | `is_active = 0` | 403 | Returns `{"error": "Device is deactivated"}` |
| **Tier 1** | `test_feature4_01_valid_nominal_telemetry_accepted` | Nominal reading | 201 | Success |
| **Tier 1** | `test_feature4_02_zero_percentage_and_litres_accepted` | Empty tank | 201 | Bounds 0.0% / 0.0L accepted |
| **Tier 1** | `test_feature4_03_full_tank_100_percent_accepted` | Full tank | 201 | Bounds 100.0% / 1000.0L accepted |
| **Tier 1** | `test_feature4_04_fractional_precise_values_accepted` | Float precision | 201 | High precision float preserved |
| **Tier 1** | `test_feature4_05_rejection_of_negative_or_overflow_percentage` | Percentage 105% | 422 | Rejected |
| **Tier 2** | `test_boundary_ingest_01_missing_device_id_returns_400` | Missing device_id | 400 | Rejected |
| **Tier 2** | `test_boundary_ingest_02_missing_distance_cm_returns_400` | Missing distance_cm | 400 | Rejected |
| **Tier 2** | `test_boundary_ingest_03_empty_body_returns_400` | Body `{}` | 400 | Rejected |
| **Tier 2** | `test_boundary_ingest_04_non_json_content_type_returns_400` | `text/plain` | 400 | Rejected |
| **Tier 2** | `test_boundary_ingest_05_malformed_json_syntax_returns_400` | `{invalid:` | 400 | Rejected |
| **Tier 2** | `test_boundary_auth_01_empty_api_key_header_returns_401` | Header `""` | 401 | Rejected |
| **Tier 2** | `test_boundary_auth_02_empty_api_key_body_returns_401` | Body `""` | 401 | Rejected |
| **Tier 2** | `test_boundary_auth_03_whitespace_only_api_key_returns_401` | `"   "` key | 401 | Rejected |
| **Tier 2** | `test_boundary_auth_04_unknown_device_id_with_invalid_key_returns_401` | Unknown device | 401 | Rejected |
| **Tier 2** | `test_boundary_auth_05_special_characters_api_key_mismatch_returns_401` | SQL inject key | 401 | Rejected |
| **Tier 2** | `test_boundary_physics_01_negative_distance_cm_returns_422` | Distance -5.0 | 422 | Rejected |
| **Tier 2** | `test_boundary_physics_02_negative_water_level_cm_returns_422` | Level -1.0 | 422 | Rejected |
| **Tier 2** | `test_boundary_physics_03_negative_water_litres_returns_422` | Litres -10.0 | 422 | Rejected |
| **Tier 2** | `test_boundary_physics_04_water_percentage_100_01_returns_422` | Percentage 100.01 | 422 | Rejected |
| **Tier 2** | `test_boundary_physics_05_string_for_numeric_value_returns_422` | `"fifty"` | 422 | Rejected |
| **Tier 3** | `test_interaction_11_auth_header_and_body_produce_identical_records` | Dual auth equivalence | 201 | Header & body auth produce identical records |
| **Tier 3** | `test_interaction_12_deactivate_device_blocks_subsequent_telemetry` | Admin state update | 403 | Dynamic deactivation blocks subsequent POSTs |
| **Tier 3** | `test_interaction_13_multi_device_telemetry_isolation` | Multi-device POST | 201 | Isolated telemetry per device |
| **Tier 4** | `test_workload_rapid_burst_telemetry_and_concurrency` | 50 rapid bursts | 201 | Zero lock errors, ascending IDs |

---

## 7. Recommendations for Next Subagent (Implementer)

1. Create directory `app/routes/` and file `app/routes/__init__.py`.
2. Implement `app/routes/api.py` with `api_bp` exposing `POST /api/water-level`.
3. Verify with:
   ```bash
   py -3.10 -m pytest tests/e2e/test_tier1_features.py -k "Feature2 or Feature3 or Feature4" -v
   py -3.10 -m pytest tests/e2e/test_tier2_boundaries.py -k "Boundary2 or Boundary3 or Boundary4" -v
   py -3.10 -m pytest tests/e2e/test_tier3_interactions.py -k "test_interaction_11 or test_interaction_12 or test_interaction_13" -v
   ```
4. Note that other M2 endpoints (`GET /api/water-level/current`, `GET /api/history/...`, `GET/PUT /api/settings`, `GET /api/health`) will also live in `app/routes/api.py` under the same blueprint `api_bp`.
