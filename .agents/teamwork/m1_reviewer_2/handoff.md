# Handoff Report — Milestone M1 Independent Review & Adversarial Audit

**Agent:** `m1_reviewer_2`  
**Role:** Reviewer & Adversarial Critic  
**Milestone:** M1 — Database & Core Storage Subsystem  
**Type:** Hard Handoff (Full Review & Adversarial Stress-Testing Complete)  
**Date:** 2026-11-06  

---

## 1. Observation

1. **Schema and Storage Specifications**:
   - `ORIGINAL_REQUEST.md` (lines 15-17): R2 specifies SQLite backend with `water_readings`, `devices`, `tank_settings`, and `backup_logs` tables with date indexing and validation rejecting impossible values.
   - `PROJECT.md` (lines 38-42, 119-185, 252-256): Specifies singleton `tank_settings` (`id=1`), 100% parameterized queries, dual-mode API key authentication, and WSGI compatibility.
   - `TEST_INFRA.md` (lines 9-25): Feature 1 and Boundary 1 require 100% pass across schema and constraint suites.

2. **Source Code Implementation Inspection**:
   - `app/config.py` (lines 12-25): Uses `os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))` for `PROJECT_ROOT`, deriving `DATA_DIR`, `BACKUP_DIR`, and `DATABASE_PATH` as absolute paths.
   - `scripts/init_db.py` (lines 28-107): Defines authoritative DDL with:
     - `tank_settings`: `id INTEGER PRIMARY KEY CHECK (id = 1)`, `tank_height_cm > 0.0`, `total_capacity_litres > 0.0`, `warning_low_percent >= 0.0 AND <= 100.0`.
     - `water_readings`: `distance_cm >= 0.0`, `water_level_cm >= 0.0`, `water_percentage >= 0.0 AND <= 100.0`, `water_litres >= 0.0`, `CHECK (length(date) = 10 AND date LIKE '____-__-__')`, `FOREIGN KEY (device_id) REFERENCES devices (device_id) ON DELETE CASCADE`.
     - B-Tree composite indexes for both naming conventions: `idx_water_readings_timestamp`, `idx_water_readings_date`, `idx_water_readings_device_time`, `idx_readings_timestamp`, `idx_readings_date`, `idx_readings_device_time`, `idx_backup_logs_created_at`, `idx_backup_created_at`.
     - Seed SQL idempotently provisions default device `esp32_tank_01` and tank settings singleton `id=1`.
     - Auto-creates parent directories (`os.makedirs(db_dir, exist_ok=True)`).
     - `--reset` safely drops tables in reverse foreign key order within a transaction, preventing Windows file-lock errors.
   - `app/database.py` (lines 55-144):
     - `create_connection()` executes `PRAGMA foreign_keys = ON;`, `PRAGMA busy_timeout = 30000;`, and `PRAGMA journal_mode = WAL; PRAGMA synchronous = NORMAL;`. Sets `conn.row_factory = sqlite3.Row`.
     - `get_db()` binds to `flask.g.db` when inside Flask request context with `app.teardown_appcontext(close_db)`, or returns a standalone connection when outside Flask context.
     - `get_db_context()` context manager provides auto-commit on success, rollback on exception, and guaranteed connection closure.
   - `app/models.py` (lines 1-674):
     - 100% parameterized queries (`?`). Zero SQL string concatenations.
     - Validates domain constraints on incoming telemetry and settings updates.
     - Atomically updates device `last_seen` during `insert_water_reading()`.
     - Normalizes aliases for `total_height_cm` / `tank_height_cm` and `warning_low_percent` / `low_threshold_percent`.
   - `tests/unit/test_m1_core.py` (lines 1-364):
     - 25 comprehensive unit tests covering configuration, DDL, CLI flags, connection lifecycle, and CRUD model operations.

3. **Tool Invocations & Direct Verifications**:
   - `python scripts/init_db.py --reset --seed --verbose`:
     Exited code `0`. Schema reset and created, WAL configured, seed records created.
   - `py -3.10 -m pytest tests/e2e/test_tier1_features.py -k "TestFeature1SqliteSchema" -v`:
     `5 passed, 65 deselected in 0.18s` (100% pass rate).
   - `py -3.10 -m pytest tests/e2e/test_tier2_boundaries.py -k "TestBoundary1DbConstraints or TestBoundary14RuntimeEnvironment" -v`:
     `10 passed, 60 deselected in 0.30s` (100% pass rate).
   - `py -3.10 -m pytest tests/unit/test_m1_core.py -v`:
     `25 passed in 0.17s` (100% pass rate).
   - Adversarial stress tests (12 attack scenarios, including singleton violation, out-of-range percentage, negative volume, bad date format, foreign key violation, cascade deletion, transaction rollback, and external directory execution) all passed without error.

4. **Integrity Audit**:
   - Inspected source code for hardcoded test outputs, mock facades, skipped tasks, or self-certifying artifacts. None found. Real SQL operations are executed against real SQLite databases in every function.

---

## 2. Logic Chain

1. From **Observation 1**, PythonAnywhere deployments require absolute path resolution to prevent directory traps where the process working directory is `/var/www`.
2. From **Observation 2**, `app/config.py` anchors all paths (`PROJECT_ROOT`, `DATA_DIR`, `BACKUP_DIR`, `DATABASE_PATH`) using `os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))`. Furthermore, running `init_db.py` from `$env:TEMP` verified that the script correctly targets the project directory without creating misplaced folders.
3. From **Observation 1 & 2**, the singleton requirement on `tank_settings` must prevent multiple configuration states. `CHECK (id = 1)` in SQLite DDL combined with primary key semantics makes inserting `id != 1` or duplicate `id = 1` impossible.
4. From **Observation 2 & 3**, out-of-range water measurements (percentage `< 0` or `> 100`, volume `< 0`) are rejected at both the SQLite DDL layer via `CHECK` constraints and the Python DAL layer via `ValueError` exceptions before insertion.
5. From **Observation 2 & 3**, dual-mode connection handling was verified: `get_db()` caches on `flask.g.db` during active app contexts, while returning standalone connections and supporting context-managed transactions (`get_db_context()`) outside Flask.
6. From **Observation 3**, all required verification commands exited with code 0 and all tests passed (25 unit tests + 15 targeted E2E tests).
7. From **Observation 4**, zero integrity violations exist. The implementation is genuine, complete, and thoroughly tested.
8. Therefore, the verdict for Milestone M1 is **APPROVE**.

---

## 3. Caveats

1. **Python Command Note**: In the current shell environment, invoking `python` directly uses the default virtualenv which lacks `pytest`. Using `py -3.10 -m pytest` executes tests cleanly using Python 3.10 where all project dependencies and pytest are installed.
2. **Unimplemented Downstream Milestones**: Tier 1 and Tier 2 tests for Features 2-12 (REST API endpoints and CLI backup runners) are planned for M2 and M3. Their current failure/404 responses are expected and do not affect Milestone M1.
3. **No Caveats on Persistence or Schema**: All M1 deliverables are fully functional and robust.

---

## 4. Conclusion

Milestone M1 (Database & Core Storage Subsystem) is thoroughly verified, robust against edge cases and adversarial scenarios, adheres strictly to project specifications and PythonAnywhere hosting constraints, and contains zero integrity violations.

**Verdict: APPROVE**

---

## 5. Verification Method

To independently verify this evaluation:

1. **Database Schema Initialization**:
   ```powershell
   python scripts/init_db.py --reset --seed --verbose
   ```
   *Expected:* Exit code `0`, WAL mode confirmed, tables and seed records created.

2. **Feature 1 Schema E2E Tests**:
   ```powershell
   py -3.10 -m pytest tests/e2e/test_tier1_features.py -k "TestFeature1SqliteSchema" -v
   ```
   *Expected:* `5 passed in <0.5s`.

3. **Boundary 1 & Boundary 14 Constraints & Runtime Tests**:
   ```powershell
   py -3.10 -m pytest tests/e2e/test_tier2_boundaries.py -k "TestBoundary1DbConstraints or TestBoundary14RuntimeEnvironment" -v
   ```
   *Expected:* `10 passed in <0.5s`.

4. **Milestone M1 Core Unit Tests**:
   ```powershell
   py -3.10 -m pytest tests/unit/test_m1_core.py -v
   ```
   *Expected:* `25 passed in <0.5s`.

**Invalidation Conditions:**
- Any test failure in `TestFeature1SqliteSchema`, `TestBoundary1DbConstraints`, `TestBoundary14RuntimeEnvironment`, or `test_m1_core.py`.
- Any relative path resolution failure under arbitrary working directories.
- Acceptance of non-singleton tank settings or out-of-bounds telemetry measurements.
