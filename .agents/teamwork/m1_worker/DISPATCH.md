## 2026-11-06T14:54:08Z
You are m1_worker, a Worker subagent responsible for implementing Milestone M1 (Database & Core Storage Subsystem).
Your assigned working directory is: c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\m1_worker\

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

MANDATORY FIRST STEP:
Read:
1. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\ORIGINAL_REQUEST.md
2. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\PROJECT.md
3. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\TEST_INFRA.md
4. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\m1_explorer_1\handoff.md
5. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\m1_explorer_2\handoff.md
6. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\m1_explorer_3\handoff.md

EXCLUSIVE FILE OWNERSHIP:
You own and must implement:
- c:\Users\IDEAL\Documents\ANtigravity\water_leveler\app\__init__.py
- c:\Users\IDEAL\Documents\ANtigravity\water_leveler\app\config.py
- c:\Users\IDEAL\Documents\ANtigravity\water_leveler\app\database.py
- c:\Users\IDEAL\Documents\ANtigravity\water_leveler\app\models.py
- c:\Users\IDEAL\Documents\ANtigravity\water_leveler\scripts\init_db.py

IMPLEMENTATION REQUIREMENTS:
1. `app/config.py`:
   - Absolute database path resolution avoiding PythonAnywhere `/var/www` current working directory permission traps.
   - Default DB path: `PROJECT_ROOT/data/water_leveler.db`.
   - Dedicated `backups/` directory path.
   - Configurable settings defaults (timeout 300s, default device id `esp32_tank_01`, default api key `water_secret_key_2026`).

2. `scripts/init_db.py`:
   - Full CLI runner with `--db-path`, `--reset`, `--seed`, `--verbose`, `--quiet`.
   - Creates `data/` directory automatically (`os.makedirs(..., exist_ok=True)`).
   - Creates 4 normalized tables (`devices`, `tank_settings`, `water_readings`, `backup_logs`) with full check constraints and foreign keys.
   - Creates composite B-Tree indexes (`idx_readings_timestamp`, `idx_readings_date`, `idx_readings_device_time`, `idx_backup_created_at`).
   - Configures persistent `PRAGMA journal_mode = WAL;`, `PRAGMA busy_timeout = 30000;`, `PRAGMA synchronous = NORMAL;`.
   - Idempotently seeds default device `esp32_tank_01` (name: 'Main Water Tank', api_key: 'water_secret_key_2026', is_active: 1) and singleton `tank_settings` id=1 (total_height_cm=200.0, sensor_offset_cm=15.0, total_capacity_litres=1000.0, warning_low_percent=20.0, warning_normal_percent=50.0, offline_threshold_seconds=300).
   - Returns exit code 0 on success, 1 on error.

3. `app/database.py`:
   - Dual-mode connection factory: binds to `flask.g.db` when inside Flask app context (with `close_db` registered on teardown), and returns standalone connection when outside Flask (CLI scripts, background tasks).
   - Provides `get_db(db_path=None)` and `get_db_context(db_path=None)` context manager.
   - Enforces `PRAGMA foreign_keys = ON;`, `PRAGMA busy_timeout = 30000;`, and `conn.row_factory = sqlite3.Row` on every connection.

4. `app/models.py`:
   - Comprehensive CRUD functions with parameterized queries:
     * Device: `get_device(device_id)`, `verify_api_key(device_id, api_key)`, `authenticate_device(...)`, `update_last_seen(device_id)`, `get_all_devices()`, `register_device(...)`
     * Tank Settings: `get_tank_settings()`, `update_tank_settings(settings_dict)` (supporting attribute aliases `tank_height_cm` / `total_height_cm`, `low_threshold_percent` / `warning_low_percent`)
     * Water Readings: `insert_water_reading(reading_data)` (automatically updating device last_seen), `get_latest_reading(device_id=None)`, `get_readings_by_date(date_str)`, `get_daily_stats(days=15)`, `compare_dates(date1_str, date2_str)`, `get_today_summary(device_id=None)`
     * Backup Logs: `insert_backup_log(...)`, `get_backup_logs(limit=50)`, `get_backup_by_filename(filename)`

5. VERIFICATION:
   - Run `python scripts/init_db.py --reset --seed` to initialize the database and verify exit code 0.
   - Run tests targeting Feature 1 and Boundary 1 using `pytest tests/e2e/test_tier1_features.py -k Feature1` and `pytest tests/e2e/test_tier2_boundaries.py -k Boundary1`.
   - Document commands and results in your handoff report.

OUTPUT REQUIREMENTS:
- Write `handoff.md` in your working directory with Observation, Logic Chain, Caveats, Conclusion, and Verification Method.
- Send completion message to caller via send_message.
