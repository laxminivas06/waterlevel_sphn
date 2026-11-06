# Milestone M1 Independent Review & Adversarial Evaluation

**Reviewer:** `m1_reviewer_2`  
**Milestone:** M1 — Database & Core Storage Subsystem  
**Date:** 2026-11-06  
**Verdict:** **APPROVE**  

---

## 1. Executive Summary

Milestone M1 (Database & Core Storage Subsystem) has been independently reviewed, audited, and stress-tested. The implementation covers all required components:
- Authoritative SQLite relational schema with 4 normalized tables (`devices`, `tank_settings`, `water_readings`, `backup_logs`).
- B-Tree composite performance indexing across timestamp, date, device/time, and backup audit logs.
- PythonAnywhere deployment safety via guaranteed absolute path resolution in `app/config.py`, `app/database.py`, and `scripts/init_db.py`.
- Singleton constraint (`id = 1`) on `tank_settings` enforced at both the SQLite DDL layer (`CHECK (id = 1)`) and DAL layer (`app/models.py`).
- Strict domain constraints on physical measurements (percentage `0.0 - 100.0`, litres `>= 0.0`, distance `>= 0.0`, level `>= 0.0`) enforced at both DDL and DAL.
- Dual-mode connection factory in `app/database.py` supporting both request-bound Flask lifecycle (`g.db` with automatic `close_db` teardown) and standalone CLI/runner contexts (`get_db_context()`).
- High-concurrency database PRAGMAs: `foreign_keys = ON;`, `busy_timeout = 30000;`, `journal_mode = WAL;`, `synchronous = NORMAL;`.
- 100% test pass rate across 25 unit tests and 15 targeted E2E tests (5 schema tests, 5 boundary constraint tests, 5 runtime environment tests).

**Integrity Audit Result:** Zero integrity violations detected. No hardcoded test outputs, no mock facades, no skipped tasks, and no self-certifying claims. All implementations execute genuine SQLite DDL/DML with 100% parameterization.

---

## 2. Review Findings & Verification Dimensions

### 2.1 Correctness & Schema Integrity
- **Singleton Constraint (`tank_settings`)**:
  - DDL: `id INTEGER PRIMARY KEY CHECK (id = 1)`. Rejects any row where `id != 1` (`sqlite3.IntegrityError`), and rejects any duplicate row with `id = 1` due to PRIMARY KEY uniqueness.
  - DAL: `get_tank_settings()` queries `WHERE id = 1` with self-healing default insertion if missing. `update_tank_settings()` updates strictly `WHERE id = 1`.
- **Domain Constraints**:
  - `water_percentage`: SQLite constraint `CHECK (water_percentage >= 0.0 AND water_percentage <= 100.0)`. Python DAL check raises `ValueError` if `< 0.0` or `> 100.0`.
  - `water_litres`: SQLite constraint `CHECK (water_litres >= 0.0)`. Python DAL check raises `ValueError` if `< 0.0`.
  - `distance_cm` and `water_level_cm`: SQLite constraints `CHECK (>= 0.0)`. Python DAL check raises `ValueError` if `< 0.0`.
  - `date`: SQLite constraint `CHECK (length(date) = 10 AND date LIKE '____-__-__')` ensures strict ISO-8601 YYYY-MM-DD date storage.
- **Referential Integrity**:
  - `water_readings.device_id` defines `FOREIGN KEY (device_id) REFERENCES devices (device_id) ON DELETE CASCADE`.
  - `PRAGMA foreign_keys = ON;` is executed on every connection in `create_connection()`, preventing orphan telemetry insertion and enabling cascading deletion.

### 2.2 PythonAnywhere Deployment Safety
- PythonAnywhere WSGI scripts typically execute with current working directory set to `/var/www` or `/home/<username>`. Using relative paths like `data/water_leveler.db` causes fatal permission or missing file errors.
- `app/config.py`:
  - `BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))`
  - `PROJECT_ROOT = BASE_DIR`
  - `DATA_DIR = os.path.abspath(os.path.join(PROJECT_ROOT, "data"))`
  - `BACKUP_DIR = os.path.abspath(os.path.join(PROJECT_ROOT, "backups"))`
  - `DATABASE_PATH` resolves via `os.path.abspath` whether sourced from environment variable or canonical default.
- `scripts/init_db.py`:
  - Automatically resolves project directory and creates parent directory `data/` if it does not exist (`os.makedirs(db_dir, exist_ok=True)`).
  - Tested running from outside the project directory (`pushd $env:TEMP; py -3.10 ...scripts/init_db.py; popd`); successfully initialized database at project location without creating misplaced directories.

### 2.3 Dual-Mode Connection Lifecycle
- `app/database.py`:
  - Inside Flask context: `has_app_context() and g is not None` evaluates to True. Binds connection to `g.db`, caches per-request, and closes connection on request completion via `app.teardown_appcontext(close_db)`.
  - Outside Flask context (CLI scripts, background runners, test functions): returns fresh standalone `sqlite3.Connection` via `create_connection(db_path)`.
  - `get_db_context(db_path)` context manager wraps connections in automatic transaction commit on exit, rollback on exception, and guaranteed connection closure.

### 2.4 Concurrency & Locking Mitigation
- Configures `PRAGMA busy_timeout = 30000;` on all connections.
- Configures `PRAGMA journal_mode = WAL;` and `PRAGMA synchronous = NORMAL;` on all file-backed SQLite connections.
- Enables non-blocking concurrent reads during active telemetry writes and CLI backup executions, preventing intermittent SQLite database lock exceptions.

---

## 3. Adversarial Stress-Test Results

| Scenario | Tested Condition | Expected Result | Actual Result | Status |
|---|---|---|---|:---:|
| 1. Singleton Violation | Insert row with `id=2` into `tank_settings` | `sqlite3.IntegrityError` | Rejected by `CHECK (id = 1)` | **PASS** |
| 2. Upper Percentage Violation | Insert reading with `water_percentage = 100.1` | `sqlite3.IntegrityError` / `ValueError` | Rejected by `CHECK` & DAL | **PASS** |
| 3. Lower Percentage Violation | Insert reading with `water_percentage = -0.5` | `sqlite3.IntegrityError` / `ValueError` | Rejected by `CHECK` & DAL | **PASS** |
| 4. Negative Volume Violation | Insert reading with `water_litres = -5.0` | `sqlite3.IntegrityError` / `ValueError` | Rejected by `CHECK` & DAL | **PASS** |
| 5. Invalid Date Format | Insert reading with `date = 'bad-date'` | `sqlite3.IntegrityError` | Rejected by `CHECK (length(date) = 10 AND date LIKE '____-__-__')` | **PASS** |
| 6. Foreign Key Enforcement | Insert reading for non-existent `device_id` | `sqlite3.IntegrityError` | Rejected by FK constraint | **PASS** |
| 7. Cascade Deletion | Delete device with associated readings | Cascades cleanly | 0 orphan readings remain | **PASS** |
| 8. Backup Log Constraint | Insert backup log with `backup_type = 'invalid'` | `sqlite3.IntegrityError` | Rejected by `CHECK (backup_type IN ('scheduled', 'manual'))` | **PASS** |
| 9. Directory Autocreation | Run `init_db.py` targeting deeply nested path | Creates parent dirs | Created directories and DB file cleanly | **PASS** |
| 10. External Execution | Run `init_db.py` from `$env:TEMP` | Canonical path resolution | Created DB in project root, zero stray temp files | **PASS** |
| 11. Dual-Mode Context | Compare `get_db()` outside vs inside Flask | Standalone: distinct conns; Flask: cached `g.db` | Verified identical reference in `g.db`, distinct outside | **PASS** |
| 12. Transaction Rollback | Raise exception within `get_db_context` | Uncommitted mutations reverted | State unchanged after exception | **PASS** |

---

## 4. Test Verification Summary

Commands executed and results:

1. **Database Initialization & Seeding**:
   - Command: `python scripts/init_db.py --reset --seed --verbose`
   - Result: Exit code `0`. Schema created, WAL configured, seed records created.
2. **Feature 1 Schema E2E Tests**:
   - Command: `py -3.10 -m pytest tests/e2e/test_tier1_features.py -k "TestFeature1SqliteSchema" -v`
   - Result: `5 passed, 65 deselected in 0.18s` (100% pass rate).
3. **Boundary 1 & Boundary 14 E2E Tests**:
   - Command: `py -3.10 -m pytest tests/e2e/test_tier2_boundaries.py -k "TestBoundary1DbConstraints or TestBoundary14RuntimeEnvironment" -v`
   - Result: `10 passed, 60 deselected in 0.30s` (100% pass rate).
4. **Milestone M1 Core Unit Tests**:
   - Command: `py -3.10 -m pytest tests/unit/test_m1_core.py -v`
   - Result: `25 passed in 0.17s` (100% pass rate).

---

## 5. Review Verdict

**VERDICT: APPROVE**

Milestone M1 implementation meets all architectural, functional, security, and deployment criteria with zero integrity violations and exemplary engineering quality. Ready for Milestone M2.
