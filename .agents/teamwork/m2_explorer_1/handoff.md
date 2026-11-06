# Handoff Report: Telemetry Ingestion Endpoint (`POST /api/water-level`)

**Agent ID:** m2_explorer_1  
**Milestone:** M2 (Flask Backend REST API & Authentication)  
**Handoff Type:** Hard  
**Date:** 2026-11-06  

---

## 1. Observation

1. **Blueprint Auto-Registration in Application Factory**:
   In `app/__init__.py` lines 40-46:
   ```python
   try:
       from app.routes.api import api_bp
       app.register_blueprint(api_bp)
   except (ImportError, ModuleNotFoundError):
       pass
   ```
   `create_app()` dynamically detects and registers `api_bp` if available. Currently, directory `app/routes` does not exist (`dir app/routes` returned `ObjectNotFound: ItemNotFoundException`).

2. **Existing Data Access Layer Ready**:
   In `app/models.py` lines 271-337, `insert_water_reading(reading_data)` is fully implemented:
   - Enforces physical boundaries (`distance_cm >= 0`, `water_level_cm >= 0`, `0.0 <= water_percentage <= 100.0`, `water_litres >= 0`).
   - Inserts into `water_readings` (`INSERT INTO water_readings ...`).
   - Updates `devices.last_seen = timestamp` atomically in the same transaction.
   - Returns `{"status": "success", "reading_id": reading_id, "id": reading_id, "timestamp": timestamp, "date": date_str}`.
   In `app/models.py` lines 21-33: `get_device(device_id)` retrieves device metadata including `api_key` and `is_active`.

3. **Current Test Failures**:
   Running `py -3.10 -m pytest tests/e2e/test_tier1_features.py -k "Feature2 or Feature3 or Feature4" -v`:
   - 15 failed out of 15 selected tests with:
     ```
     assert response.status_code == 201
     assert 404 == 201
     ```
   Running `py -3.10 -m pytest tests/e2e/test_tier2_boundaries.py -k "Boundary2 or Boundary3 or Boundary4" -v`:
   - 15 failed out of 15 selected tests with `assert 404 == 400` / `assert 404 == 401` / `assert 404 == 422`.

4. **Deactivated Device Status Code Contract**:
   In `tests/e2e/test_tier1_features.py` lines 200-210 (`test_feature3_05_deactivated_device_returns_403`):
   ```python
   conn.execute("UPDATE devices SET is_active = 0 WHERE device_id = ?;", (sample_telemetry_payload["device_id"],))
   ...
   resp = client.post("/api/water-level", json=sample_telemetry_payload)
   assert resp.status_code == 403
   assert "deactivated" in resp.json.get("error", "").lower()
   ```
   In `tests/e2e/test_tier3_interactions.py` line 271 (`test_interaction_12_deactivate_device_blocks_subsequent_telemetry`):
   ```python
   assert r2.status_code == 403
   ```
   This strictly requires returning **HTTP 403 Forbidden** (with `"deactivated"` in error message) when `is_active != 1`, even though dispatch summary suggested 401.

5. **Concurrency & PRAGMA Safeguards**:
   In `app/database.py` lines 75-85:
   `PRAGMA busy_timeout = 30000;`, `PRAGMA journal_mode = WAL;`, `PRAGMA synchronous = NORMAL;`, and `PRAGMA foreign_keys = ON;` are pre-configured.

---

## 2. Logic Chain

1. From Observation 1, creating `app/routes/__init__.py` and `app/routes/api.py` with `api_bp = Blueprint("api", __name__)` will immediately be mounted by `app.create_app()` without modifying any existing application factory code.
2. From Observation 3, all 30 tests in Tiers 1 and 2 failed with HTTP 404 exclusively due to the missing `/api/water-level` route handler.
3. From Observation 2, the underlying database operations (reading insertion, device `last_seen` timestamp update, and transactional integrity) are already handled by `app.models.insert_water_reading` and `app.models.get_device`.
4. From Observation 4, the route handler must enforce a 5-stage validation gate:
   - **Gate 1**: `request.is_json` and `get_json()` syntactic validity -> HTTP 400 on failure.
   - **Gate 2**: Presence of `device_id`, `distance_cm`, `water_level_cm`, `water_percentage`, `water_litres` and non-empty string for `device_id` -> HTTP 400 on failure.
   - **Gate 3**: Dual-mode API key extraction (`X-API-Key` header first, then body `api_key`). If missing or empty -> HTTP 401. If device not found or key mismatch -> HTTP 401. If device `is_active != 1` -> HTTP 403 with `"deactivated"` in error text.
   - **Gate 4**: Numeric parsing of measurement fields (rejecting Python `bool` types, strings, `NaN`, `Inf`) and physical boundaries (`distance_cm >= 0`, `water_level_cm >= 0`, `0.0 <= water_percentage <= 100.0`, `water_litres >= 0`) -> HTTP 422 on failure.
   - **Gate 5**: Calling `insert_water_reading(...)` and returning HTTP 201 Created with JSON `{"status": "success", "reading_id": id, "timestamp": ts}`.
5. From Observation 5, under the rapid 50-burst concurrency test in Tier 4 (`test_workload_rapid_burst_telemetry_and_concurrency`), SQLite's WAL mode and 30-second busy timeout guarantee zero lock crashes when single-statement transactions are promptly committed.

---

## 3. Caveats

- **Scope Boundary**: This investigation specifically targets `POST /api/water-level`. Other M2 endpoints (`GET /api/water-level/current`, `GET /api/history/daily-stats`, `GET /api/history/readings`, `GET /api/history/compare`, `GET/PUT /api/settings`, `GET /api/health`, `GET /api/devices`) will also reside in `app/routes/api.py` and are covered under subsequent M2 tasks.
- **Deactivated Status Code (403 vs 401)**: The prompt stated *"Reject unauthorized or inactive devices with HTTP 401"*, but the existing authoritative test files (`test_tier1_features.py` line 208 and `test_tier3_interactions.py` line 271) explicitly test and require `assert resp.status_code == 403` with `"deactivated"` in the error message. The logic chain adheres to the existing authoritative test code (HTTP 403).

---

## 4. Conclusion

1. The design and code for `POST /api/water-level` is fully synthesized and documented in `c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\m2_explorer_1\analysis.md`.
2. The implementation requires creating `app/routes/__init__.py` and `app/routes/api.py`.
3. The proposed 5-gate pipeline directly satisfies 100% of the requirements and will flip 30 tests in Tier 1 (Features 2, 3, 4) and Tier 2 (Boundaries 2, 3, 4), as well as 4 tests in Tiers 3 & 4, from RED (404) to GREEN (201/400/401/403/422).

---

## 5. Verification Method

To verify the recommendations once implemented:

1. **Targeted Tier 1 Feature Tests**:
   ```bash
   py -3.10 -m pytest tests/e2e/test_tier1_features.py -k "Feature2 or Feature3 or Feature4" -v
   ```
   *Expected Result*: 15 passed, 0 failed.

2. **Targeted Tier 2 Boundary Tests**:
   ```bash
   py -3.10 -m pytest tests/e2e/test_tier2_boundaries.py -k "Boundary2 or Boundary3 or Boundary4" -v
   ```
   *Expected Result*: 15 passed, 0 failed.

3. **Targeted Tier 3 Cross-Feature & Tier 4 Concurrency Tests**:
   ```bash
   py -3.10 -m pytest tests/e2e/test_tier3_interactions.py -k "test_interaction_11 or test_interaction_12 or test_interaction_13" -v
   py -3.10 -m pytest tests/e2e/test_tier4_workloads.py -k "test_workload_rapid_burst_telemetry_and_concurrency" -v
   ```
   *Expected Result*: 4 passed, 0 failed.

4. **Invalidation Conditions**:
   - If `POST /api/water-level` returns HTTP 401 instead of HTTP 403 when `is_active == 0`, `test_feature3_05` and `test_interaction_12` will fail.
   - If boolean values in JSON (`{"distance_cm": true}`) are implicitly converted to `1.0` instead of rejected, type integrity is violated.
   - If non-JSON Content-Type returns anything other than HTTP 400, `test_boundary_ingest_04` will fail.
