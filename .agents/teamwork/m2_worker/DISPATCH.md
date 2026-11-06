## 2026-11-06T15:24:48Z

You are m2_worker, a Worker subagent responsible for implementing Milestone M2 (Flask Backend REST API & Authentication).
Your assigned working directory is: c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\m2_worker\

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

MANDATORY FIRST STEP:
Read:
1. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\ORIGINAL_REQUEST.md
2. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\PROJECT.md
3. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\TEST_INFRA.md
4. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\TEST_READY.md
5. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\m2_explorer_1\handoff.md
6. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\m2_explorer_2\analysis.md
7. Existing code: app/models.py, app/database.py, app/config.py, app/__init__.py

EXCLUSIVE FILE OWNERSHIP:
- c:\Users\IDEAL\Documents\ANtigravity\water_leveler\app\routes\__init__.py
- c:\Users\IDEAL\Documents\ANtigravity\water_leveler\app\routes\api.py
- c:\Users\IDEAL\Documents\ANtigravity\water_leveler\app\__init__.py (update to register api blueprint and JSON error handlers)

IMPLEMENTATION REQUIREMENTS:
1. `app/routes/api.py`:
   Create Flask Blueprint `api_bp = Blueprint('api', __name__, url_prefix='/api')` with all REST endpoints:
   - `POST /api/water-level`:
     * Validates JSON content type and required fields (`device_id`, `distance_cm`, `water_level_cm`, `water_percentage`, `water_litres`).
     * Dual-mode auth: checks `X-API-Key` header or `api_key` in JSON body. Returns 401 if missing/invalid, 403 if device deactivated (`is_active=0`).
     * Validates numeric types and physics ranges (`distance_cm >= 0`, `water_level_cm >= 0`, `0.0 <= water_percentage <= 100.0`, `water_litres >= 0`). Rejects booleans as numbers (`isinstance(v, bool)` check). Returns 422 Unprocessable Entity with error details.
     * Inserts via `app.models.insert_water_reading()` and updates device `last_seen`.
     * Returns HTTP 201 Created: `{"status": "success", "reading_id": id, "timestamp": iso_ts}`.
   - `GET /api/water-level/current` (and `@api_bp.route('/water-level/latest')` alias):
     * Query param `?device_id=...` (defaults to `DEFAULT_DEVICE_ID` or first active device). Returns 404 if explicit non-existent device requested.
     * Evaluates device connectivity: `status="online"` if `(now - last_seen) <= offline_threshold_seconds`, else `"offline"`.
     * Returns JSON structure with `device`, `tank`, `reading`, `today_summary`.
   - `GET /api/history/daily-stats`:
     * Query param `?days=15` (1-90, default 15). Returns daily aggregates array via `app.models.get_daily_stats()`.
   - `GET /api/history/readings`:
     * Query param `?date=YYYY-MM-DD`. Validates format (400 if bad). Returns intraday readings array and summary via `app.models.get_readings_by_date()`.
   - `GET /api/history/compare`:
     * Query params `?date1=YYYY-MM-DD&date2=YYYY-MM-DD`. Validates format (400 if bad or missing). Returns date1, date2, and difference metrics via `app.models.compare_dates()`.
   - `GET /api/settings`:
     * Returns tank settings dictionary via `app.models.get_tank_settings()`.
   - `PUT /api/settings`:
     * Accepts JSON body to update tank settings. Validates physical limits (height > 0, capacity > 0, 0 <= low < normal <= 100, timeout > 0). Returns 400 on malformed, 422 on boundary failure, 200 on success with updated settings.
   - `GET /api/devices`:
     * Returns list of devices with online/offline status.
   - `GET /api/health`:
     * Checks database connectivity. Returns HTTP 200 `{"status": "healthy", "database": "connected", "timestamp": "..."}` or 503 if DB error.

2. `app/__init__.py`:
   - Application factory `create_app(test_config=None)`:
     * Loads config.
     * Registers database teardown hook.
     * Registers `api_bp` blueprint.
     * Registers JSON error handlers for 400, 404, 405, 422, 500 so client gets JSON `{"error": "...", "status_code": ...}` instead of default HTML error pages.

3. VERIFICATION:
   - Run: `python -m pytest tests/e2e/test_tier1_features.py -k "TestFeature2 or TestFeature3 or TestFeature4 or TestFeature5 or TestFeature6 or TestFeature7 or TestFeature8 or TestFeature9 or TestFeature10" -v`
   - Run: `python -m pytest tests/e2e/test_tier2_boundaries.py -k "TestBoundary2 or TestBoundary3 or TestBoundary4 or TestBoundary5 or TestBoundary6 or TestBoundary7 or TestBoundary8 or TestBoundary9 or TestBoundary10" -v`
   - Run: `python -m pytest tests/e2e/test_tier3_interactions.py -k "test_interaction_01 or test_interaction_02" -v`
   - Document all verification results in `handoff.md`.

OUTPUT REQUIREMENTS:
- Write `handoff.md` in your working directory with full verification evidence.
- Send completion message to caller via send_message.

