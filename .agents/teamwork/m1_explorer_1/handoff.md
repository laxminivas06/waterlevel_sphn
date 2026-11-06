# Handoff Report — Milestone M1: SQLite Schema DDL, Constraints, and Index Architecture

**Agent:** `m1_explorer_1`  
**Milestone:** M1 — Database & Core Storage Subsystem  
**Type:** Hard Handoff (Investigation & Architecture Design Complete)  
**Date:** 2026-11-06  

---

## 1. Observation

1. **Mandatory Specifications & Interface Contracts:**
   - In `ORIGINAL_REQUEST.md` (lines 15-17): Requirement R2 mandates SQLite with `water_readings`, `devices`, `tank_settings`, `backup_logs` tables with date indexing and validation rejecting invalid or impossible values.
   - In `PROJECT.md` (lines 119-128, 153-159): Interface contracts define tank settings schema with `total_height_cm`, `sensor_offset_cm`, `total_capacity_litres`, `warning_low_percent`, and `warning_normal_percent`.
   - In `PROJECT.md` (line 64): Tank visualization requirements specify 4 status colors: Green (>50%), Orange (20-50%), Red (<20%), Blue (filling), which maps directly to `warning_low_percent = 20.0` and `warning_normal_percent = 50.0`.
   - In `spec_miner_survey_backend/spec.md` (lines 84-143): Survey draft schema used legacy column names `tank_height_cm`, `low_threshold_percent`, and `critical_low_threshold_percent`, but omitted `raw_reading_json`.
   - In Dispatch instruction for `m1_explorer_1`: Mandated 4 normalized tables with exact physical check constraints, composite B-Tree indexes (`idx_readings_timestamp`, `idx_readings_date`, `idx_readings_device_time`, `idx_backup_created_at`), ISO-8601 timestamps, date (`YYYY-MM-DD`), and `raw_reading_json` column.

2. **SQLite Runtime Behavior & Verification:**
   - System SQLite version is `3.53.1` (Python 3.10+ standard library `sqlite3`).
   - Executed verification script against in-memory SQLite:
     ```python
     conn.execute("PRAGMA foreign_keys = ON;")
     ```
     - Validated that `PRAGMA foreign_keys` defaults to `0` (disabled) on fresh SQLite connections and must be activated per-connection.
     - Validated that inserting a reading for a non-existent device raises `sqlite3.IntegrityError: FOREIGN KEY constraint failed`.
     - Validated that `ON DELETE CASCADE` removes all linked readings when a parent device row is deleted (`Readings count after delete: 0`).
     - Validated that `CHECK (water_percentage >= 0.0 AND water_percentage <= 100.0)` raises `CHECK constraint failed` when `-1.0` or `105.0` is inserted.
     - Validated that `tank_settings` table constraint `CHECK (id = 1)` raises `CHECK constraint failed` on attempting to insert `id = 2`.
   - Executed `EXPLAIN QUERY PLAN` on the defined indexes:
     - `SELECT * FROM water_readings ORDER BY timestamp DESC LIMIT 1`:
       Result: `SCAN water_readings USING INDEX idx_readings_timestamp` (O(1) index scan, zero sort buffer).
     - `SELECT * FROM water_readings WHERE date = '2026-11-06'`:
       Result: `SEARCH water_readings USING INDEX idx_readings_date (date=?)`.
     - `SELECT * FROM water_readings WHERE device_id = 'esp32_tank_01' ORDER BY timestamp DESC LIMIT 1`:
       Result: `SEARCH water_readings USING INDEX idx_readings_device_time (device_id=?)`.
     - `SELECT * FROM backup_logs ORDER BY created_at DESC LIMIT 10`:
       Result: `SCAN backup_logs USING INDEX idx_backup_created_at`.

3. **Pragmas & Concurrency on PythonAnywhere:**
   - Confirmed pragma execution in test database:
     `FK: 1, Journal: wal, BusyTimeout: 30000, Sync: 1`.
   - `PRAGMA journal_mode = WAL;` is persistent across connections in the SQLite database header.
   - `PRAGMA foreign_keys = ON;` is strictly connection-scoped and must be executed in every connection factory call.

---

## 2. Logic Chain

1. From **Observation 1**, `ORIGINAL_REQUEST.md` and `PROJECT.md` require rejection of impossible physical values at the database level as well as the API level.
2. Therefore, SQL-level `CHECK` constraints are designed on `water_readings` (`distance_cm >= 0.0`, `water_level_cm >= 0.0`, `water_percentage BETWEEN 0.0 AND 100.0`, `water_litres >= 0.0`, `date LIKE '____-__-__'`).
3. From **Observation 1**, `tank_settings` represents physical geometry for a single tank. If multiple rows were inserted, queries without `LIMIT 1` would produce ambiguous results. Enforcing `id INTEGER PRIMARY KEY CHECK (id = 1)` guarantees singleton integrity at the storage engine level.
4. From **Observation 1 & 2**, `PROJECT.md` defines four visual color bands (Red <20%, Orange 20-50%, Green >50%). Reconciling `tank_settings` column names to `warning_low_percent` (20.0%) and `warning_normal_percent` (50.0%) aligns the database schema directly with the dashboard UI specification.
5. From **Observation 2**, query plans prove that `idx_readings_timestamp`, `idx_readings_date`, `idx_readings_device_time`, and `idx_backup_created_at` completely eliminate full-table scans for all four core dashboard read pathways.
6. From **Observation 3**, because SQLite disables foreign keys by default on each new connection, `app/database.py` and all standalone runners must execute `PRAGMA foreign_keys = ON;` immediately after `sqlite3.connect()`.
7. From **Observation 3**, configuring `PRAGMA journal_mode = WAL;` during `init_db.py` enables concurrent reads from the web dashboard while the ESP32 is posting telemetry or `backup.py` is exporting data, while `PRAGMA busy_timeout = 30000;` prevents transient lock timeouts.

---

## 3. Caveats

1. **SQLite In-Memory vs File Differences:** In-memory SQLite (`:memory:`) does not use WAL mode (WAL requires a persistent filesystem to create `-wal` and `-shm` files). WAL mode testing was verified against a temporary disk-backed file (`test_verify.db`), confirming `wal` mode persistence.
2. **Date Storage Format:** SQLite does not have a dedicated `DATE` type. Storing `date` as `TEXT` with strict format constraint `CHECK (length(date) = 10 AND date LIKE '____-__-__')` ensures alphabetical sort order matches chronological sort order.
3. **Column Name Aliasing in Python Models:** To support any legacy calls expecting `tank_height_cm` or `low_threshold_percent` from early survey specs, `app/models.py` should map these keys to the canonical columns (`total_height_cm`, `warning_low_percent`).

---

## 4. Conclusion

The SQLite schema DDL, domain constraints, B-Tree indexes, and concurrency configuration for Milestone M1 are fully verified and ready for implementation.
- Detailed technical analysis and complete DDL are documented in:
  `c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\m1_explorer_1\analysis.md`
- The schema satisfies all requirements of R2 and R6, provides complete data integrity guarantees, and establishes O(1)/O(log N) query performance.

---

## 5. Verification Method

To independently verify the schema DDL, constraints, foreign keys, and indexes, execute the following command in PowerShell:

```powershell
@'
import sqlite3

conn = sqlite3.connect(':memory:')
conn.execute('PRAGMA foreign_keys = ON;')

# 1. Test DDL Execution
with open(r'c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\m1_explorer_1\analysis.md', 'r') as f:
    content = f.read()
ddl = content.split('```sql')[1].split('```')[0]
conn.executescript(ddl)

# 2. Test Device Insertion & Seed
conn.execute("INSERT INTO devices (device_id, device_name, api_key) VALUES ('esp32_tank_01', 'Tank 1', 'secret');")
conn.execute("INSERT INTO tank_settings (id, total_height_cm, total_capacity_litres) VALUES (1, 200.0, 1000.0);")

# 3. Test Singleton Violation
try:
    conn.execute("INSERT INTO tank_settings (id, total_height_cm) VALUES (2, 250.0);")
    assert False, "Singleton failure"
except sqlite3.IntegrityError:
    pass

# 4. Test Out-of-Range Percentage Violation
try:
    conn.execute("INSERT INTO water_readings (device_id, date, distance_cm, water_level_cm, water_percentage, water_litres) VALUES ('esp32_tank_01', '2026-11-06', 50, 150, 150.0, 750);")
    assert False, "Percentage range check failure"
except sqlite3.IntegrityError:
    pass

# 5. Test Foreign Key Violation
try:
    conn.execute("INSERT INTO water_readings (device_id, date, distance_cm, water_level_cm, water_percentage, water_litres) VALUES ('unknown_dev', '2026-11-06', 50, 150, 75.0, 750);")
    assert False, "Foreign key failure"
except sqlite3.IntegrityError:
    pass

print("SCHEMA VERIFICATION SUCCESSFUL: 100% checks passed.")
'@ | python
```

**Invalidation Conditions:**
- Any constraint allowing `water_percentage` outside `[0.0, 100.0]`.
- Failure of `tank_settings` to reject rows where `id != 1`.
- Failure of `water_readings` to reject unknown `device_id` when foreign keys are enabled.
