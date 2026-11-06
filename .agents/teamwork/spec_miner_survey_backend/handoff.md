# Handoff Report: Backend API, SQLite Database, Automated Backup & PythonAnywhere Deployment Specifications

**Agent:** spec_miner_survey_backend  
**Recipient:** Orchestrator (e67aac6c-272b-4420-b5de-866caa2cc5fb)  
**Date:** 2026-11-06T14:42:00Z  
**Type:** Hard Handoff (Specification Survey Complete)

---

### 1. Observation

1. **Original Request Review:**
   - Inspected `ORIGINAL_REQUEST.md` lines 15–29 and lines 32–54.
   - Identified explicit requirements:
     - R2: Flask Backend API with SQLite database (`water_readings`, `devices`, `tank_settings`, `backup_logs`), date indexing, device API key protection, validation rejecting invalid/impossible values, device online/offline status tracking based on configurable timeout.
     - R5: Automated daily backup system for SQLite records exportable to CSV/JSON, compatible with PythonAnywhere scheduled tasks without persistent daemons, local storage in `backups/`, and manual backup download option.
     - R6: PythonAnywhere deployment package with WSGI configuration (`wsgi.py`), database setup/initialization script (`init_db.py`), pinned `requirements.txt`, and deployment documentation for HTTPS.

2. **Local Environment Capabilities:**
   - Ran `python --version` -> verified `Python 3.11.15`.
   - Ran `python -c "import sqlite3..."` -> verified `sqlite3 version: 3.53.1` with full support for foreign key pragma, check constraints, indexes, and datetime operations.
   - Ran test scripts probing:
     - SQLite DDL schema creation and execution (exited with code 0).
     - 15-day aggregate query (`GROUP BY date`, `MIN`, `MAX`, `AVG`) handling populated days as well as empty dates returning `(0, None, None, None)`.
     - Device connectivity timeout evaluation (online when `now - last_seen <= 300`, offline when `> 300` or `None`).
     - Filename sanitization rejecting directory traversal patterns (`..`, `/`, `\`).
     - Automated backup retention purging files older than 30 days while preserving recent ones.
     - Idempotent seed insertion using `INSERT OR IGNORE`.

3. **Created Artifact:**
   - Created comprehensive specification file at:
     `c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\spec_miner_survey_backend\spec.md`
   - Document contains:
     - 22 enumerated features in the Features Discovered table.
     - 25 specific edge cases and observed/expected behaviors in the Edge Cases table.
     - Complete SQLite DDL schema with check constraints and composite indexes.
     - 13 detailed REST API contracts with headers, JSON schemas, and HTTP status codes (200, 201, 400, 401, 403, 404, 422, 500).
     - Standalone backup subsystem specification with CLI arguments and JSON/CSV data structures.
     - PythonAnywhere deployment package specification (WSGI configuration, absolute path resolution, directory layout, pinned requirements, and step-by-step setup guide).

---

### 2. Logic Chain

1. **From Acceptance Criteria to SQLite Schema Design:**
   - Observation: Requirement R2 mandates tracking readings, devices, tank settings, and backup logs with date indexing.
   - Inference: `water_readings` requires `FOREIGN KEY (device_id) REFERENCES devices(device_id)`.
   - Inference: Storing both `timestamp` (ISO string with time) and `date` (`YYYY-MM-DD`) with B-Tree indexes on `timestamp`, `date`, and `(device_id, timestamp)` enables instantaneous 15-day range queries and daily aggregation without expensive datetime string manipulation during `GROUP BY`.
   - Inference: `tank_settings` must follow the singleton pattern (`id INTEGER PRIMARY KEY CHECK (id = 1)`) so the web dashboard and sensor ingestion always refer to a consistent source of truth for tank dimensions, sensor offset, and alert thresholds.

2. **From Ingestion Requirements to API Contract:**
   - Observation: R2 requires `POST /api/water-level` protected by a device API key, validating incoming readings and rejecting invalid/impossible values with 400, 401, 422.
   - Inference: Device authentication must support both header `X-API-Key` and JSON body `api_key` to accommodate microcontroller firmware constraints.
   - Inference: Physics constraints dictate `distance_cm >= 0`, `water_level_cm >= 0`, `0.0 <= water_percentage <= 100.0`, and `water_litres >= 0.0`. Missing fields yield 400, unauthorized keys yield 401, deactivated devices yield 403, and numeric range violations yield 422.

3. **From PythonAnywhere Constraints to Backup & WSGI Architecture:**
   - Observation: PythonAnywhere free tier and web apps do not permit persistent background daemons (e.g. infinite `while True` threads are killed when workers cycle or time out).
   - Inference: R5's automated backup must be architected as a standalone CLI script (`backup.py`) scheduled via PythonAnywhere's "Tasks" tab (cron-like runner executing once daily).
   - Observation: WSGI execution on PythonAnywhere sets `os.getcwd()` to `/var/www` or `/home/<username>`, which breaks relative paths like `sqlite3.connect('water_leveler.db')`.
   - Inference: `config.py` must resolve all file paths (database and backups) relative to `os.path.abspath(os.path.dirname(__file__))`.
   - Inference: `wsgi.py` must expose the callable as `application` (`from app import app as application`), as required by PythonAnywhere's WSGI server.

---

### 3. Caveats

1. **Authentication Scope:** Device authentication is implemented via shared API keys stored in `devices`. User dashboard authentication (passwords/sessions) was not explicitly requested in the prompt, so dashboard viewing endpoints are public/read-only by default. If admin auth is required for settings updates (`PUT /api/settings`), an optional admin key or HTTP Basic auth can be layered without schema changes.
2. **Timezone Uniformity:** SQLite timestamps default to `datetime('now', 'localtime')`. In production on PythonAnywhere, UTC is recommended to maintain consistency across DST shifts.

---

### 4. Conclusion

The specification survey for Backend API, SQLite Database, Automated Daily Backup Subsystem, and PythonAnywhere Deployment Package (R2, R5, R6) is complete, fully probed, and authoritatively documented in `spec.md`. The design is directly actionable, lightweight, self-contained, and compliant with all project acceptance criteria.

---

### 5. Verification Method

To verify the specifications and schemas:
1. **Schema & DDL Independent Verification:**
   Run the following Python one-liner in terminal:
   ```bash
   python -c "import sqlite3; text = open(r'c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\spec_miner_survey_backend\spec.md', encoding='utf-8').read(); b = chr(96)*3; ddl = text.split(b + 'sql')[1].split(b)[0]; seed = text.split(b + 'sql')[2].split(b)[0]; con = sqlite3.connect(':memory:'); con.executescript(ddl); con.executescript(seed); print('Verification SUCCESS: Schema and Seed executed cleanly!'); print('Tables:', con.execute('SELECT name FROM sqlite_master WHERE type=\'table\'').fetchall())"
   ```
2. **Inspection:**
   - Review feature table in `spec.md` § 2 (22 features).
   - Review edge cases in `spec.md` § 3 (25 edge cases).
   - Inspect API endpoints in `spec.md` § 5.
   - Inspect PythonAnywhere deployment guide in `spec.md` § 7.5.
