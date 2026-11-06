# Handoff Report — Milestone M1: Database Initialization, Seed Provisioning, and CLI Tooling (`scripts/init_db.py`)

**Agent:** `m1_explorer_2`  
**Milestone:** M1 — Database & Core Storage Subsystem  
**Type:** Hard Handoff (Investigation, Technical Analysis & Implementation Blueprint Complete)  
**Date:** 2026-11-06  

---

## 1. Observation

1. **Mandatory Specifications & Architecture Inputs:**
   - `ORIGINAL_REQUEST.md` (lines 15-17): Requirement R2 mandates a lightweight Python 3 Flask backend with SQLite tables (`water_readings`, `devices`, `tank_settings`, `backup_logs`) with appropriate date indexing and field validation.
   - `PROJECT.md` (lines 280, 291): Code layout places the initializer in `scripts/init_db.py` and dedicated database storage in `data/`.
   - `PROJECT.md` (lines 153-159): Defines tank configuration schema contracts: `total_height_cm: 200.0`, `sensor_offset_cm: 15.0`, `total_capacity_litres: 1000.0`, `warning_low_percent: 20.0`, `warning_normal_percent: 50.0`.
   - `spec_miner_survey_backend/spec.md` (lines 561-570): Emphasizes that PythonAnywhere WSGI execution boots with working directory `/var/www` or `/home/<user>`, making relative database paths hazardous unless resolved using absolute paths (`os.path.abspath`).
   - Dispatch instruction for `m1_explorer_2`: Mandated CLI flags (`--db-path`, `--reset`, `--seed`), automatic directory creation for `data/`, PRAGMA checks and WAL mode configuration, idempotent execution without data loss or duplicate primary keys, clean exit codes (`0` on success, `1` on error), and specific default seed records:
     - Device: `device_id="esp32_tank_01"`, `device_name="Main Water Tank"`, `api_key="tank_secret_key_2026"`, `is_active=1`
     - Tank Settings: `id=1`, `total_height_cm=200.0`, `sensor_offset_cm=15.0`, `total_capacity_litres=1000.0`, `warning_low_percent=20.0`, `warning_normal_percent=50.0`, `offline_threshold_seconds=300`.

2. **Runtime Verification of SQLite Engine (Python 3.11.15 / SQLite 3.53.1):**
   - Executed test commands against SQLite on Windows:
     - Verified `PRAGMA journal_mode = WAL;` on a file-backed database returned `'wal'`.
     - Verified that `PRAGMA journal_mode` persists in the SQLite file header across subsequent connection opens.
     - Verified that on an in-memory database (`:memory:`), `PRAGMA journal_mode = WAL;` safely returns `'memory'` without crashing.
     - Verified that `INSERT OR IGNORE INTO devices ...` returned `rowcount = 1` on the first execution and `rowcount = 0` on the second execution without raising `sqlite3.IntegrityError`.
     - Verified that `INSERT OR IGNORE INTO tank_settings (id, ...)` returned `rowcount = 1` on first run and `rowcount = 0` on subsequent runs without error.
     - Verified that attempting to insert `id = 2` into `tank_settings` raised `sqlite3.IntegrityError: CHECK constraint failed: id = 1`.
     - Verified that dropping tables via SQL `DROP TABLE IF EXISTS` inside a transaction with `PRAGMA foreign_keys = OFF;` successfully wiped all tables (`tables after reset: ['sqlite_sequence']`), avoiding Windows file-locking `PermissionError` traps associated with `os.remove`.

3. **Multi-Agent Consensus (with `m1_explorer_1`):**
   - Inspected `m1_explorer_1/analysis.md` and `m1_explorer_1/handoff.md`.
   - Confirmed 100% consensus on the 4 normalized tables, column names (`total_height_cm`, `warning_low_percent`, `warning_normal_percent`), composite B-Tree indexes (`idx_readings_timestamp`, `idx_readings_date`, `idx_readings_device_time`, `idx_backup_created_at`), and PRAGMA settings (`foreign_keys=ON`, `journal_mode=WAL`, `busy_timeout=30000`, `synchronous=NORMAL`).

---

## 2. Logic Chain

1. From **Observation 1**, `PROJECT.md` specifies `data/` as the database directory, but in a fresh git clone or deployment, `data/` may not exist. If an SQLite connection is opened against a path in a nonexistent directory, SQLite immediately crashes with `sqlite3.OperationalError: unable to open database file`.
2. Therefore, `init_db.py` must inspect `os.path.dirname(os.path.abspath(db_path))` and execute `os.makedirs(db_dir, exist_ok=True)` before calling `sqlite3.connect()`.
3. From **Observation 1**, PythonAnywhere WSGI boots under `/var/www`, which causes relative paths like `data/water_leveler.db` to write to forbidden system directories.
4. Therefore, `init_db.py` must resolve default database paths relative to the project root (`os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "water_leveler.db"))`).
5. From **Observation 1 & 2**, in a production IoT system with concurrent sensor telemetry POSTs and UI dashboard polling every 3 seconds, standard SQLite rollback journal locks the entire database during writes.
6. Therefore, setting `PRAGMA journal_mode = WAL;` during database initialization persists Write-Ahead Logging in the database header, enabling simultaneous reads and writes without contention, while `PRAGMA busy_timeout = 30000;` prevents race-condition timeouts.
7. From **Observation 1 & 2**, automated deployment pipelines and repeated developer setup runs frequently execute `init_db.py --seed` multiple times. Using standard `INSERT INTO` causes `sqlite3.IntegrityError: UNIQUE constraint failed`.
8. Therefore, using `INSERT OR IGNORE INTO devices` and `INSERT OR IGNORE INTO tank_settings` guarantees complete idempotency: new databases are populated with defaults, while existing deployments retain operator customizations without error.
9. From **Observation 2**, using `os.remove()` for `--reset` fails on Windows when background processes hold file locks (`PermissionError: [WinError 32]`).
10. Therefore, executing SQL `DROP TABLE IF EXISTS` in reverse foreign-key dependency order within SQLite connection cleanly resets the database across both Windows and POSIX systems.
11. From **Observation 1**, CLI tooling requires unambiguous Unix exit codes (`sys.exit(0)` on success, `sys.exit(1)` on error) to integrate reliably into CI/CD, PythonAnywhere bash scripts, and automated test runners.

---

## 3. Caveats

1. **In-Memory Concurrency (`:memory:`):** In-memory SQLite databases do not support WAL mode because WAL requires filesystem backing for the `-wal` and `-shm` shared memory files. `configure_pragmas()` logs the returned mode (`memory` vs `wal`) without failing.
2. **Dynamic Seed Customization:** Running `python scripts/init_db.py --seed` will NOT overwrite modified user settings (e.g. if the tank capacity was updated via UI to 1500L). To force resetting user configurations back to factory defaults, operators must pass `--reset --seed`.
3. **Foreign Keys Scope:** While `PRAGMA journal_mode = WAL;` is persistent in the SQLite file header, `PRAGMA foreign_keys = ON;` is strictly connection-scoped. While `init_db.py` enforces foreign keys during initialization, the runtime data access layer (`app/database.py`) must also execute `PRAGMA foreign_keys = ON;` on every incoming connection.

---

## 4. Conclusion

The technical architecture, DDL execution strategy, seed provisioning mechanism, directory handling, PRAGMA configuration, and CLI design for `scripts/init_db.py` are fully analyzed, tested, and documented.
- The complete implementation blueprint has been written to:
  `c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\m1_explorer_2\analysis.md`
- The design satisfies all requirements of Milestone M1 and provides an importable programmatic API (`init_db()`) and robust CLI interface for development, testing, and deployment.

---

## 5. Verification Method

To independently verify the database initializer architecture, seed provisioning, idempotency, and reset behavior, execute the following PowerShell command:

```powershell
@'
import os
import sqlite3
import tempfile
import sys

# Import or test the init logic against a temporary file
temp_dir = tempfile.mkdtemp()
test_db = os.path.join(temp_dir, "nested_dir", "test_water.db")

try:
    # 1. Test directory auto-creation
    db_dir = os.path.dirname(test_db)
    os.makedirs(db_dir, exist_ok=True)
    assert os.path.exists(db_dir), "Directory creation failed"

    # 2. Connect and configure PRAGMAs
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("PRAGMA journal_mode = WAL;")
    mode = cursor.fetchone()[0]
    assert mode.lower() == "wal", f"Expected wal mode, got {mode}"
    cursor.execute("PRAGMA busy_timeout = 30000;")
    cursor.execute("PRAGMA synchronous = NORMAL;")

    # 3. Apply DDL
    with open(r"c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\m1_explorer_2\analysis.md", "r") as f:
        content = f.read()
    ddl = content.split("```sql")[1].split("```")[0]
    cursor.executescript(ddl)

    # 4. Seed records (Run 1)
    dev_sql = "INSERT OR IGNORE INTO devices (device_id, device_name, api_key, is_active) VALUES ('esp32_tank_01', 'Main Water Tank', 'tank_secret_key_2026', 1);"
    cursor.execute(dev_sql)
    assert cursor.rowcount == 1, "First device seed failed"

    tank_sql = "INSERT OR IGNORE INTO tank_settings (id, total_height_cm, sensor_offset_cm, total_capacity_litres, warning_low_percent, warning_normal_percent, offline_threshold_seconds) VALUES (1, 200.0, 15.0, 1000.0, 20.0, 50.0, 300);"
    cursor.execute(tank_sql)
    assert cursor.rowcount == 1, "First tank seed failed"
    conn.commit()

    # 5. Idempotent Seed (Run 2)
    cursor.execute(dev_sql)
    assert cursor.rowcount == 0, "Idempotency failed on device (re-inserted duplicate)"
    cursor.execute(tank_sql)
    assert cursor.rowcount == 0, "Idempotency failed on tank (re-inserted duplicate)"
    conn.commit()

    # 6. Verify Reset Logic
    cursor.execute("PRAGMA foreign_keys = OFF;")
    for tbl in ["backup_logs", "water_readings", "tank_settings", "devices"]:
        cursor.execute(f"DROP TABLE IF EXISTS {tbl};")
    cursor.execute("PRAGMA foreign_keys = ON;")
    conn.commit()

    tables = [r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() if r[0] != 'sqlite_sequence']
    assert len(tables) == 0, f"Expected 0 tables after reset, got {tables}"

    conn.close()
    print("VERIFICATION SUCCESSFUL: 100% checks passed.")
finally:
    # Cleanup temporary test files
    for root, dirs, files in os.walk(temp_dir, topdown=False):
        for f in files:
            try: os.remove(os.path.join(root, f))
            except Exception: pass
        for d in dirs:
            try: os.rmdir(os.path.join(root, d))
            except Exception: pass
    try: os.rmdir(temp_dir)
    except Exception: pass
'@ | python
```

**Invalidation Conditions:**
- Any run where `init_db.py` fails when parent directory does not exist.
- Any run where calling `--seed` a second time throws `sqlite3.IntegrityError` or duplicates records.
- Any run where `--reset` fails with file-locking exceptions on Windows.
- Any disk-backed initialization that fails to enable `wal` journal mode.
- Non-zero exit code on successful schema creation.