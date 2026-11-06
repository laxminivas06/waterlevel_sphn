# Technical Analysis: Python Data Access Layer (`app/database.py` & `app/models.py`)

**Document Version:** 1.0.0  
**Subagent:** m1_explorer_3  
**Milestone:** M1 — Database & Core Storage Subsystem  
**Scope:** Architecture, Connection Lifecycle, Parameterized SQL Models, Transactions, and Defensive Error Handling.

---

## 1. Executive Summary & Purpose

The Data Access Layer (DAL) is the foundation of the IoT Smart Water Tank Level Monitoring System. It sits between the SQLite storage engine and all consumer layers:
1. **Sensor Ingestion API (`POST /api/water-level`)**: Requires fast, low-latency writes with foreign key enforcement and synchronized `last_seen` timestamping.
2. **Dashboard & Analytics API (`/api/water-level/current`, `/api/history/*`)**: Requires aggregate queries (min, max, average, day comparison, today summary) with dictionary serialization.
3. **Automated Backup CLI (`scripts/backup.py`)**: Requires standalone execution outside Flask, with audit logging to `backup_logs`.
4. **PythonAnywhere Deployment**: Demands robust path resolution immune to WSGI working-directory traps, thread safety, and zero daemon dependencies.

This analysis provides the complete design, architectural decisions, and production-ready implementation blueprints for `app/database.py` and `app/models.py`.

---

## 2. File Architecture & Separation of Concerns

```
app/
├── __init__.py           # Application Factory (create_app)
├── config.py             # Environment configuration & absolute path resolution
├── database.py           # SQLite connection lifecycle, PRAGMAs, teardown, Flask hook
└── models.py             # Domain query functions, parameterized SQL, business transactions
```

### Separation Principle
- **`app/database.py`**: Manages *how* we connect, configure, and teardown connections.
  - Owns connection pooling/caching in Flask `g` or standalone context.
  - Applies mandatory PRAGMA statements (`foreign_keys`, `journal_mode`, `busy_timeout`).
  - Sets `row_factory = sqlite3.Row`.
  - Provides transaction context manager `get_db_context()`.
  - Registers Flask application teardown hooks.
- **`app/models.py`**: Manages *what* queries and business logic are executed on the data.
  - Completely agnostic to whether it is running inside Flask or CLI (functions accept optional `db=None`).
  - Implements parameterized SQL (`?` placeholders) with 0% string formatting.
  - Handles transaction commits and rollbacks defensively.
  - Converts `sqlite3.Row` objects to JSON-serializable dictionaries.

---

## 3. Connection Lifecycle Deep Dive (`app/database.py`)

### 3.1 Dual-Mode Execution: Flask Context vs Standalone CLI

A critical requirement is that the database layer must operate seamlessly in two distinct environments:
1. **Inside Flask Request / App Context**:
   - Web requests (`POST /api/water-level`, `GET /api/water-level/current`).
   - Connection is stored on `flask.g.db` for the duration of the request.
   - Connection is closed automatically when the request finishes via `app.teardown_appcontext(close_db)`.
   - Reusing `g.db` avoids repeated connection overhead across route handlers and middleware within the same request.
2. **Outside Flask Context (Standalone CLI & Scripts)**:
   - Standalone daily backup script (`scripts/backup.py` executed via PythonAnywhere scheduled tasks).
   - Database initialization script (`scripts/init_db.py`).
   - Telemetry simulator (`scripts/simulate_esp32.py`).
   - Unit tests running without Flask app context.
   - `get_db(db_path=None)` detects when `not has_app_context()` and opens a fresh connection.
   - A dedicated context manager `get_db_context(db_path=None)` automatically executes `conn.commit()` on success, `conn.rollback()` on exception, and ensures `conn.close()` is always called in a `finally` block.

```python
def get_db(db_path=None):
    if has_app_context():
        if 'db' not in g or g.db is None:
            g.db = create_connection(db_path)
        return g.db
    else:
        return create_connection(db_path)
```

### 3.2 PythonAnywhere Path Resolution Strategy

When deploying to PythonAnywhere via WSGI (`wsgi.py`), the process current working directory (`os.getcwd()`) can default to `/var/www` or `/home/<user>`. Relative paths like `sqlite3.connect("water_leveler.db")` will attempt to write to `/var/www/water_leveler.db` and throw `sqlite3.OperationalError: unable to open database file (permission denied)`.

To resolve this defensively:
1. Database path resolution follows strict precedence:
   - Explicit parameter: `db_path` (if provided).
   - Flask config: `current_app.config.get('DATABASE_PATH')` (if inside app context).
   - Environment variable: `os.environ.get('DATABASE_PATH')`.
   - Canonical absolute default: `os.path.join(PROJECT_ROOT, 'data', 'water_leveler.db')` or `os.path.join(PROJECT_ROOT, 'water_leveler.db')`.
2. Parent directory safety:
   Before opening a connection, the code executes:
   `os.makedirs(os.path.dirname(os.path.abspath(resolved_path)), exist_ok=True)`
   guaranteeing the directory exists.

### 3.3 Mandatory PRAGMAs & High-Concurrency Tuning

Every new connection must be configured immediately upon creation:

| PRAGMA Statement | Value / Mode | Why It Is Mandatory |
|------------------|--------------|---------------------|
| `PRAGMA foreign_keys = ON;` | `ON` | **Crucial:** SQLite has foreign keys **disabled by default** on every new connection. Without this, invalid `device_id` values in `water_readings` are inserted silently without raising errors. |
| `PRAGMA journal_mode = WAL;` | `WAL` | Write-Ahead Logging allows **concurrent readers** while a write is occurring. Essential when `backup.py` reads historical records while the ESP32 is actively posting telemetry. |
| `PRAGMA busy_timeout = 30000;` | `30000` (30s) | Sets a 30-second wait before raising `database is locked`. Prevents intermittent locks between web threads and CLI tasks. |
| `PRAGMA synchronous = NORMAL;` | `NORMAL` | In WAL mode, `NORMAL` synchronizes at WAL checkpoints rather than every transaction, improving write speed by ~5-10x while preserving durability. |

### 3.4 Explicit `row_factory = sqlite3.Row`

Setting `conn.row_factory = sqlite3.Row` provides:
- Access by column name: `row['device_id']`, `row['water_level_cm']`.
- Access by index: `row[0]`, `row[1]`.
- Fast dictionary conversion: `dict(row)` for Flask `jsonify` serialization.
- Iteration over keys: `[k for k in row.keys()]`.

---

## 4. Domain Data Access Layer Deep Dive (`app/models.py`)

### 4.1 Schema Reconciliation & Key Aliasing

Reviewing `PROJECT.md` vs `spec_miner_survey_backend/spec.md` reveals minor terminology variations in tank settings columns:
- `tank_height_cm` (spec.md) vs `total_height_cm` (PROJECT.md)
- `low_threshold_percent` (spec.md) vs `warning_low_percent` (PROJECT.md)
- `critical_low_threshold_percent` (spec.md) vs `warning_critical_percent`

**Architectural Decision:**
The canonical SQLite schema uses the standard names:
- `tank_height_cm REAL NOT NULL DEFAULT 200.0`
- `sensor_offset_cm REAL NOT NULL DEFAULT 15.0`
- `total_capacity_litres REAL NOT NULL DEFAULT 1000.0`
- `offline_threshold_seconds INTEGER NOT NULL DEFAULT 300`
- `low_threshold_percent REAL NOT NULL DEFAULT 20.0`
- `critical_low_threshold_percent REAL NOT NULL DEFAULT 10.0`

In `app/models.py`, `get_tank_settings()` populates alias keys so consumers accessing either key succeed:
```python
result['total_height_cm'] = result['tank_height_cm']
result['warning_low_percent'] = result['low_threshold_percent']
result['warning_normal_percent'] = 50.0  # normal fill boundary
```
This ensures 100% interoperability with all frontend dashboard components and firmware contracts.

---

### 4.2 Comprehensive Function Specifications

#### 1. Device Operations

##### `get_device(device_id: str, db=None) -> Optional[dict]`
- **SQL:** `SELECT * FROM devices WHERE device_id = ?`
- **Returns:** Dictionary of device row (`device_id`, `api_key`, `device_name`, `is_active`, `last_seen`, `created_at`), or `None` if not found.
- **Safety:** Parameterized `?` binding.

##### `verify_api_key(device_id: str, api_key: str, db=None) -> bool`
- **SQL:** `SELECT api_key, is_active FROM devices WHERE device_id = ?`
- **Logic:**
  - If device not found: return `False`.
  - If `is_active != 1`: return `False`.
  - Return `device['api_key'] == api_key`.

##### `authenticate_device(device_id: str, api_key: str, db=None) -> tuple[bool, Optional[str], Optional[dict]]`
- **Purpose:** Detailed authentication helper for REST API routes to distinguish between 401 (bad key), 403 (deactivated), and 404/401 (not found).
- **Returns:** `(is_authenticated, error_message, device_dict)`.

##### `update_last_seen(device_id: str, timestamp: Optional[str] = None, db=None) -> bool`
- **SQL:** `UPDATE devices SET last_seen = ? WHERE device_id = ?`
- **Timestamp Default:** If `timestamp` is None, uses `datetime.now().strftime('%Y-%m-%d %H:%M:%S')`.
- **Commit:** Automatically commits transaction.

##### `get_all_devices(active_only: bool = False, db=None) -> list[dict]`
- **SQL:** `SELECT * FROM devices [WHERE is_active = 1] ORDER BY created_at ASC`

##### `register_device(device_id: str, api_key: str, device_name: str, is_active: int = 1, db=None) -> dict`
- **SQL:** `INSERT INTO devices (device_id, api_key, device_name, is_active) VALUES (?, ?, ?, ?) ON CONFLICT(device_id) DO UPDATE SET api_key=excluded.api_key, device_name=excluded.device_name`

---

#### 2. Tank Settings Operations (Singleton ID=1)

##### `get_tank_settings(db=None) -> dict`
- **SQL:** `SELECT * FROM tank_settings WHERE id = 1`
- **Default Fallback:** If row 1 is missing, defensively inserts and returns default configuration.
- **Returns:** Normalized dictionary with aliases (`tank_height_cm`, `total_height_cm`, `low_threshold_percent`, `warning_low_percent`, etc.).

##### `update_tank_settings(settings_dict: dict, db=None) -> dict`
- **Validation Rules:**
  - `tank_height_cm` / `total_height_cm`: numeric, `> 0`.
  - `sensor_offset_cm`: numeric, `>= 0`.
  - `total_capacity_litres`: numeric, `> 0`.
  - `offline_threshold_seconds`: integer, `>= 30`.
  - `low_threshold_percent`: numeric, `0.0 <= low <= 100.0`.
  - `critical_low_threshold_percent`: numeric, `0.0 <= critical < low`.
- **SQL Injection Guard:** Column whitelist validation:
  `ALLOWED_SETTINGS_COLUMNS = {'tank_height_cm', 'sensor_offset_cm', 'total_capacity_litres', 'offline_threshold_seconds', 'low_threshold_percent', 'critical_low_threshold_percent'}`
- **SQL:** Dynamic parameterized `UPDATE tank_settings SET col1=?, col2=?, updated_at = datetime('now', 'localtime') WHERE id = 1`.
- **Returns:** Refreshed settings dictionary.

---

#### 3. Water Reading Operations (Telemetry Ingestion)

##### `insert_water_reading(reading_data: dict, db=None) -> dict`
- **Input Parameters:**
  - `device_id`: str (required)
  - `distance_cm`: float (required, `>= 0`)
  - `water_level_cm`: float (required, `>= 0`)
  - `water_percentage`: float (required, `0.0 <= p <= 100.0`)
  - `water_litres`: float (required, `>= 0`)
  - `timestamp`: optional str (defaults to `datetime.now().strftime('%Y-%m-%d %H:%M:%S')`)
  - `date`: optional str (defaults to `timestamp[:10]` or `datetime.now().strftime('%Y-%m-%d')`)
  - `raw_reading_json`: optional str (for debug audit if column exists)
- **Atomic Operations in Single Transaction:**
  1. Insert into `water_readings`:
     `INSERT INTO water_readings (device_id, distance_cm, water_level_cm, water_percentage, water_litres, timestamp, date) VALUES (?, ?, ?, ?, ?, ?, ?)`
  2. Update device `last_seen`:
     `UPDATE devices SET last_seen = ? WHERE device_id = ?`
  3. `conn.commit()`
- **Error Handling:** If device does not exist, SQLite raises `sqlite3.IntegrityError` (foreign key constraint failure). The transaction is rolled back and re-raised for the route to catch.
- **Returns:** `{"id": cur.lastrowid, "timestamp": timestamp, "date": date, "status": "success"}`.

##### `get_latest_reading(device_id: Optional[str] = None, db=None) -> Optional[dict]`
- **SQL:**
  - With device_id: `SELECT * FROM water_readings WHERE device_id = ? ORDER BY timestamp DESC, id DESC LIMIT 1`
  - Without device_id: `SELECT * FROM water_readings ORDER BY timestamp DESC, id DESC LIMIT 1`
- **Empty State:** Returns `None` if zero records exist (dashboard handles gracefully).

##### `get_readings_by_date(date_str: str, device_id: Optional[str] = None, limit: Optional[int] = None, db=None) -> list[dict]`
- **SQL:**
  `SELECT * FROM water_readings WHERE date = ? [AND device_id = ?] ORDER BY timestamp ASC, id ASC [LIMIT ?]`
- **Returns:** Chronological array of intraday telemetry records for plotting Chart.js curves.

---

#### 4. Historical Analytics & Summary Aggregates

##### `get_daily_stats(days: int = 15, device_id: Optional[str] = None, db=None) -> list[dict]`
- **Calculation in Python:**
  `cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')`
- **SQL:**
  ```sql
  SELECT 
      date,
      COUNT(*) as reading_count,
      ROUND(MIN(water_level_cm), 2) as min_level_cm,
      ROUND(MAX(water_level_cm), 2) as max_level_cm,
      ROUND(AVG(water_level_cm), 2) as avg_level_cm,
      ROUND(MIN(water_percentage), 2) as min_percentage,
      ROUND(MAX(water_percentage), 2) as max_percentage,
      ROUND(AVG(water_percentage), 2) as avg_percentage,
      ROUND(MIN(water_litres), 2) as min_litres,
      ROUND(MAX(water_litres), 2) as max_litres,
      ROUND(AVG(water_litres), 2) as avg_litres
  FROM water_readings
  WHERE date >= ?
    [AND device_id = ?]
  GROUP BY date
  ORDER BY date ASC
  ```
- **Performance:** Directly utilizes the composite B-Tree index `idx_water_readings_date`.

##### `compare_dates(date1_str: str, date2_str: str, device_id: Optional[str] = None, db=None) -> dict`
- **Logic:**
  1. Executes aggregate query for `date1_str`.
  2. Executes aggregate query for `date2_str`.
  3. Computes net differentials:
     - `avg_difference_litres = round(date2.avg_litres - date1.avg_litres, 2)`
     - `avg_difference_percentage = round(date2.avg_percentage - date1.avg_percentage, 2)`
     - `max_difference_litres = round(date2.max_litres - date1.max_litres, 2)`
  4. Determines trend:
     - If either day has 0 records: `"insufficient_data"`
     - If diff > 0: `"increasing"`
     - If diff < 0: `"decreasing"`
     - If diff == 0: `"neutral"`
- **Response Format:** Returns full breakdown of `date1`, `date2`, and `comparison` metrics.

##### `get_today_summary(device_id: Optional[str] = None, date_str: Optional[str] = None, db=None) -> dict`
- **Logic:**
  - Date defaults to current date `datetime.now().strftime('%Y-%m-%d')`.
  - Computes count, min, max, average for litres, percentage, and level.
  - Computes net change:
    - Earliest reading of the day: `SELECT water_litres FROM water_readings WHERE date = ? ORDER BY timestamp ASC, id ASC LIMIT 1`
    - Latest reading of the day: `SELECT water_litres FROM water_readings WHERE date = ? ORDER BY timestamp DESC, id DESC LIMIT 1`
    - `net_change_litres = round(latest['water_litres'] - earliest['water_litres'], 2)`
    - If count <= 1: `net_change_litres = 0.0`.

---

#### 5. Backup Log Operations

##### `insert_backup_log(...) -> int`
- **SQL:**
  ```sql
  INSERT INTO backup_logs (
      backup_type, file_format, filename, file_path, 
      file_size_bytes, records_count, status, error_message, created_at
  ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
  ```
- **Returns:** Generated log ID (`cur.lastrowid`).

##### `get_backup_logs(limit: int = 50, offset: int = 0, db=None) -> list[dict]`
- **SQL:**
  `SELECT * FROM backup_logs ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?`

##### `get_backup_by_filename(filename: str, db=None) -> Optional[dict]`
- **SQL:**
  `SELECT * FROM backup_logs WHERE filename = ? ORDER BY id DESC LIMIT 1`
- **Security Purpose:** When a user requests `GET /api/backup/download/<filename>`, the route queries this function first. If the file is not in `backup_logs` with `status == 'success'`, the download is rejected immediately, thwarting arbitrary file disclosure.

---

## 5. Security & Defensive Programming Architecture

### 5.1 Parameterized SQL Queries
No SQL string concatenation or f-strings are permitted. Every variable is passed via SQLite `?` placeholders:
```python
# CORRECT:
cur.execute("SELECT * FROM water_readings WHERE device_id = ? AND date = ?", (device_id, date_str))

# FORBIDDEN (VULNERABLE TO SQL INJECTION):
cur.execute(f"SELECT * FROM water_readings WHERE device_id = '{device_id}'")
```

### 5.2 Whitelist Column Validation for Dynamic Updates
In `update_tank_settings(settings_dict)`, columns are dynamically mapped. To prevent SQL injection through malicious dictionary keys, the function strictly validates each key against an explicit set:
```python
ALLOWED_KEYS = {
    'tank_height_cm', 'sensor_offset_cm', 'total_capacity_litres',
    'offline_threshold_seconds', 'low_threshold_percent', 'critical_low_threshold_percent'
}
for key in settings_dict:
    if key not in ALLOWED_KEYS and key not in ALIASES:
        raise ValueError(f"Invalid settings field: {key}")
```

### 5.3 Defensive Transaction Management
All mutating operations (INSERT, UPDATE, DELETE) follow the atomic commit/rollback pattern:
```python
conn = db or get_db()
try:
    # SQL operations...
    conn.commit()
except Exception as e:
    conn.rollback()
    raise e
```
This guarantees that if an error occurs midway through an operation (e.g. updating device last_seen after inserting a reading), the database never enters an inconsistent or corrupted state.

---

## 6. Implementation Blueprint: `app/database.py`

```python
"""
app/database.py - SQLite Connection Lifecycle & Database Management
Handles Flask request context integration, standalone CLI connections,
PRAGMA configuration, WAL mode, foreign key enforcement, and teardown handlers.
"""

import os
import sqlite3
from contextlib import contextmanager
from typing import Optional

try:
    from flask import current_app, g, has_app_context
except ImportError:
    # Support standalone execution when Flask is not loaded in current scope
    current_app = None
    g = None
    has_app_context = lambda: False


def get_project_root() -> str:
    """Returns absolute path to the water_leveler project root directory."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_default_db_path() -> str:
    """
    Returns the resolved absolute path to the SQLite database.
    Order of precedence:
    1. DATABASE_PATH environment variable
    2. Flask current_app.config['DATABASE_PATH'] (if in Flask context)
    3. Project root: data/water_leveler.db (or water_leveler.db)
    """
    if has_app_context() and current_app and 'DATABASE_PATH' in current_app.config:
        return current_app.config['DATABASE_PATH']
    
    env_path = os.environ.get('DATABASE_PATH')
    if env_path:
        return os.path.abspath(env_path)

    # Default to data/water_leveler.db in project root
    root_dir = get_project_root()
    data_dir = os.path.join(root_dir, 'data')
    return os.path.join(data_dir, 'water_leveler.db')


def create_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Creates and configures a fresh SQLite connection.
    Enforces foreign keys, WAL mode, 30s busy timeout, and sqlite3.Row factory.
    """
    path = db_path or get_default_db_path()
    
    # Ensure parent directory exists (vital for data/ directory and PythonAnywhere)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    
    conn = sqlite3.connect(
        path,
        timeout=30.0,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
    )
    conn.row_factory = sqlite3.Row
    
    # Mandatory PRAGMAs
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    
    return conn


def get_db(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Retrieves or establishes the SQLite connection.
    - If inside a Flask application context: caches connection in g.db.
    - If running standalone (CLI / test runner): returns a fresh connection.
    """
    if has_app_context():
        if 'db' not in g or g.db is None:
            g.db = create_connection(db_path)
        return g.db
    else:
        return create_connection(db_path)


def close_db(e: Optional[BaseException] = None) -> None:
    """
    Flask teardown handler. Closes g.db if open.
    """
    if has_app_context():
        db = g.pop('db', None)
        if db is not None:
            db.close()


@contextmanager
def get_db_context(db_path: Optional[str] = None):
    """
    Context manager for standalone scripts (backup.py, init_db.py, test fixtures).
    Automatically commits on success, rolls back on error, and closes connection.
    """
    if has_app_context():
        conn = get_db(db_path)
        yield conn
    else:
        conn = create_connection(db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init_app(app) -> None:
    """
    Registers database lifecycle teardown hooks with the Flask application.
    """
    app.teardown_appcontext(close_db)
```

---

## 7. Implementation Blueprint: `app/models.py`

```python
"""
app/models.py - Python Data Access Layer for Smart Water Tank Leveler
Contains parameterized SQL operations for Devices, Tank Settings,
Water Readings Telemetry, Historical Analytics, and Backup Logs.
"""

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union
import sqlite3

from app.database import get_db


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    """Converts a sqlite3.Row into a standard JSON-serializable Python dictionary."""
    if row is None:
        return None
    return dict(row)


def rows_to_dict_list(rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
    """Converts a list of sqlite3.Row objects into a list of dictionaries."""
    return [dict(r) for r in rows]


# ============================================================================
# 1. Device Operations
# ============================================================================

def get_device(device_id: str, db: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    """
    Retrieves a single device by device_id.
    Returns dictionary or None if device does not exist.
    """
    conn = db or get_db()
    cur = conn.execute(
        "SELECT device_id, api_key, device_name, is_active, last_seen, created_at "
        "FROM devices WHERE device_id = ?",
        (device_id,)
    )
    return row_to_dict(cur.fetchone())


def verify_api_key(device_id: str, api_key: str, db: Optional[sqlite3.Connection] = None) -> bool:
    """
    Verifies if device exists, is active, and the provided api_key matches.
    """
    device = get_device(device_id, db=db)
    if not device:
        return False
    if device.get('is_active') != 1:
        return False
    return device.get('api_key') == api_key


def authenticate_device(
    device_id: str, api_key: str, db: Optional[sqlite3.Connection] = None
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    Detailed device authentication returning (is_authenticated, error_reason, device_dict).
    Useful for differentiating 401 Unauthorized vs 403 Forbidden.
    """
    device = get_device(device_id, db=db)
    if not device:
        return False, "Device not registered", None
    if device.get('is_active') != 1:
        return False, f"Device '{device_id}' is deactivated", device
    if device.get('api_key') != api_key:
        return False, "Invalid API key", None
    return True, None, device


def update_last_seen(
    device_id: str, timestamp: Optional[str] = None, db: Optional[sqlite3.Connection] = None
) -> bool:
    """
    Updates device last_seen timestamp.
    Defaults to current local timestamp if none provided.
    """
    conn = db or get_db()
    ts = timestamp or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        cur = conn.execute(
            "UPDATE devices SET last_seen = ? WHERE device_id = ?",
            (ts, device_id)
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception:
        conn.rollback()
        raise


def get_all_devices(
    active_only: bool = False, db: Optional[sqlite3.Connection] = None
) -> List[Dict[str, Any]]:
    """Returns list of registered devices."""
    conn = db or get_db()
    if active_only:
        cur = conn.execute(
            "SELECT device_id, device_name, is_active, last_seen, created_at "
            "FROM devices WHERE is_active = 1 ORDER BY created_at ASC"
        )
    else:
        cur = conn.execute(
            "SELECT device_id, device_name, is_active, last_seen, created_at "
            "FROM devices ORDER BY created_at ASC"
        )
    return rows_to_dict_list(cur.fetchall())


def register_device(
    device_id: str,
    api_key: str,
    device_name: str,
    is_active: int = 1,
    db: Optional[sqlite3.Connection] = None
) -> Dict[str, Any]:
    """Creates or updates a device record idempotently."""
    conn = db or get_db()
    try:
        conn.execute(
            """INSERT INTO devices (device_id, api_key, device_name, is_active)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(device_id) DO UPDATE SET
                   api_key = excluded.api_key,
                   device_name = excluded.device_name,
                   is_active = excluded.is_active""",
            (device_id, api_key, device_name, is_active)
        )
        conn.commit()
        return get_device(device_id, db=conn)
    except Exception:
        conn.rollback()
        raise


# ============================================================================
# 2. Tank Settings Operations (Singleton ID=1)
# ============================================================================

DEFAULT_TANK_SETTINGS = {
    'tank_height_cm': 200.0,
    'sensor_offset_cm': 15.0,
    'total_capacity_litres': 1000.0,
    'offline_threshold_seconds': 300,
    'low_threshold_percent': 20.0,
    'critical_low_threshold_percent': 10.0
}


def get_tank_settings(db: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """
    Retrieves singleton tank settings.
    Includes harmonized alias keys for cross-component compatibility.
    """
    conn = db or get_db()
    cur = conn.execute("SELECT * FROM tank_settings WHERE id = 1")
    row = cur.fetchone()
    if row is None:
        # Auto-seed default singleton if missing
        try:
            conn.execute(
                """INSERT INTO tank_settings (
                    id, tank_height_cm, sensor_offset_cm, total_capacity_litres,
                    offline_threshold_seconds, low_threshold_percent, critical_low_threshold_percent
                ) VALUES (1, ?, ?, ?, ?, ?, ?)""",
                (
                    DEFAULT_TANK_SETTINGS['tank_height_cm'],
                    DEFAULT_TANK_SETTINGS['sensor_offset_cm'],
                    DEFAULT_TANK_SETTINGS['total_capacity_litres'],
                    DEFAULT_TANK_SETTINGS['offline_threshold_seconds'],
                    DEFAULT_TANK_SETTINGS['low_threshold_percent'],
                    DEFAULT_TANK_SETTINGS['critical_low_threshold_percent']
                )
            )
            conn.commit()
            cur = conn.execute("SELECT * FROM tank_settings WHERE id = 1")
            row = cur.fetchone()
        except Exception:
            conn.rollback()
            raise

    settings = row_to_dict(row)
    # Populate interoperability aliases
    settings['total_height_cm'] = settings['tank_height_cm']
    settings['warning_low_percent'] = settings['low_threshold_percent']
    settings['warning_normal_percent'] = 50.0  # normal fill reference
    return settings


def update_tank_settings(
    settings_dict: Dict[str, Any], db: Optional[sqlite3.Connection] = None
) -> Dict[str, Any]:
    """
    Updates singleton tank settings with strict whitelist and range validation.
    """
    conn = db or get_db()
    current = get_tank_settings(db=conn)

    # Normalize alias input keys
    norm = dict(settings_dict)
    if 'total_height_cm' in norm and 'tank_height_cm' not in norm:
        norm['tank_height_cm'] = norm['total_height_cm']
    if 'warning_low_percent' in norm and 'low_threshold_percent' not in norm:
        norm['low_threshold_percent'] = norm['warning_low_percent']

    # Whitelist check
    allowed_columns = {
        'tank_height_cm', 'sensor_offset_cm', 'total_capacity_litres',
        'offline_threshold_seconds', 'low_threshold_percent', 'critical_low_threshold_percent'
    }

    updates = {}
    for col in allowed_columns:
        if col in norm:
            val = norm[col]
            if val is not None:
                updates[col] = float(val) if col != 'offline_threshold_seconds' else int(val)

    if not updates:
        return current

    # Merge candidate values to validate combined constraints
    candidate = {**current, **updates}

    # Physical boundary validations
    if candidate['tank_height_cm'] <= 0:
        raise ValueError("tank_height_cm must be strictly positive")
    if candidate['sensor_offset_cm'] < 0:
        raise ValueError("sensor_offset_cm must be non-negative")
    if candidate['total_capacity_litres'] <= 0:
        raise ValueError("total_capacity_litres must be strictly positive")
    if candidate['offline_threshold_seconds'] < 30:
        raise ValueError("offline_threshold_seconds must be at least 30 seconds")
    if not (0.0 <= candidate['low_threshold_percent'] <= 100.0):
        raise ValueError("low_threshold_percent must be between 0.0 and 100.0")
    if not (0.0 <= candidate['critical_low_threshold_percent'] < candidate['low_threshold_percent']):
        raise ValueError("critical_low_threshold_percent must be between 0 and strictly less than low_threshold_percent")

    # Build parameterized query safely
    set_clauses = [f"{col} = ?" for col in updates.keys()]
    set_clauses.append("updated_at = datetime('now', 'localtime')")
    sql = f"UPDATE tank_settings SET {', '.join(set_clauses)} WHERE id = 1"
    params = list(updates.values())

    try:
        conn.execute(sql, params)
        conn.commit()
        return get_tank_settings(db=conn)
    except Exception:
        conn.rollback()
        raise


# ============================================================================
# 3. Water Reading Operations (Ingestion & Intraday)
# ============================================================================

def insert_water_reading(
    reading_data: Dict[str, Any], db: Optional[sqlite3.Connection] = None
) -> Dict[str, Any]:
    """
    Inserts a validated water reading and updates device last_seen atomically.
    Raises sqlite3.IntegrityError if foreign key fails or check constraint violated.
    """
    conn = db or get_db()
    
    device_id = reading_data['device_id']
    distance_cm = float(reading_data['distance_cm'])
    water_level_cm = float(reading_data['water_level_cm'])
    water_percentage = float(reading_data['water_percentage'])
    water_litres = float(reading_data['water_litres'])
    
    ts = reading_data.get('timestamp') or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    date_str = reading_data.get('date') or ts[:10]

    try:
        cur = conn.execute(
            """INSERT INTO water_readings 
               (device_id, distance_cm, water_level_cm, water_percentage, water_litres, timestamp, date)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (device_id, distance_cm, water_level_cm, water_percentage, water_litres, ts, date_str)
        )
        reading_id = cur.lastrowid

        # Update device last_seen in same atomic transaction
        conn.execute(
            "UPDATE devices SET last_seen = ? WHERE device_id = ?",
            (ts, device_id)
        )
        
        conn.commit()
        return {
            'status': 'success',
            'reading_id': reading_id,
            'timestamp': ts,
            'date': date_str,
            'device_id': device_id
        }
    except Exception:
        conn.rollback()
        raise


def get_latest_reading(
    device_id: Optional[str] = None, db: Optional[sqlite3.Connection] = None
) -> Optional[Dict[str, Any]]:
    """
    Returns the most recent reading. Returns None if table is empty.
    """
    conn = db or get_db()
    if device_id:
        cur = conn.execute(
            "SELECT * FROM water_readings WHERE device_id = ? "
            "ORDER BY timestamp DESC, id DESC LIMIT 1",
            (device_id,)
        )
    else:
        cur = conn.execute(
            "SELECT * FROM water_readings "
            "ORDER BY timestamp DESC, id DESC LIMIT 1"
        )
    return row_to_dict(cur.fetchone())


def get_readings_by_date(
    date_str: str,
    device_id: Optional[str] = None,
    limit: Optional[int] = None,
    db: Optional[sqlite3.Connection] = None
) -> List[Dict[str, Any]]:
    """
    Returns intraday chronological readings for a given calendar date (YYYY-MM-DD).
    """
    conn = db or get_db()
    params: List[Any] = [date_str]
    sql = "SELECT * FROM water_readings WHERE date = ?"
    if device_id:
        sql += " AND device_id = ?"
        params.append(device_id)
    sql += " ORDER BY timestamp ASC, id ASC"
    if limit and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)

    cur = conn.execute(sql, params)
    return rows_to_dict_list(cur.fetchall())


# ============================================================================
# 4. Historical Analytics & Summary Aggregates
# ============================================================================

def get_daily_stats(
    days: int = 15,
    device_id: Optional[str] = None,
    db: Optional[sqlite3.Connection] = None
) -> List[Dict[str, Any]]:
    """
    Aggregates daily min, max, and avg levels, percentages, and litres
    for the past N days.
    """
    conn = db or get_db()
    cutoff_date = (datetime.now() - timedelta(days=max(1, days))).strftime('%Y-%m-%d')
    params: List[Any] = [cutoff_date]

    sql = """
        SELECT 
            date,
            COUNT(*) as reading_count,
            ROUND(MIN(water_level_cm), 2) as min_level_cm,
            ROUND(MAX(water_level_cm), 2) as max_level_cm,
            ROUND(AVG(water_level_cm), 2) as avg_level_cm,
            ROUND(MIN(water_percentage), 2) as min_percentage,
            ROUND(MAX(water_percentage), 2) as max_percentage,
            ROUND(AVG(water_percentage), 2) as avg_percentage,
            ROUND(MIN(water_litres), 2) as min_litres,
            ROUND(MAX(water_litres), 2) as max_litres,
            ROUND(AVG(water_litres), 2) as avg_litres
        FROM water_readings
        WHERE date >= ?
    """
    if device_id:
        sql += " AND device_id = ?"
        params.append(device_id)

    sql += " GROUP BY date ORDER BY date ASC"

    cur = conn.execute(sql, params)
    return rows_to_dict_list(cur.fetchall())


def get_single_date_summary(
    date_str: str,
    device_id: Optional[str] = None,
    db: Optional[sqlite3.Connection] = None
) -> Dict[str, Any]:
    """Helper aggregating summary statistics for one single calendar date."""
    conn = db or get_db()
    params: List[Any] = [date_str]
    sql = """
        SELECT 
            COUNT(*) as reading_count,
            ROUND(MIN(water_level_cm), 2) as min_level_cm,
            ROUND(MAX(water_level_cm), 2) as max_level_cm,
            ROUND(AVG(water_level_cm), 2) as avg_level_cm,
            ROUND(MIN(water_percentage), 2) as min_percentage,
            ROUND(MAX(water_percentage), 2) as max_percentage,
            ROUND(AVG(water_percentage), 2) as avg_percentage,
            ROUND(MIN(water_litres), 2) as min_litres,
            ROUND(MAX(water_litres), 2) as max_litres,
            ROUND(AVG(water_litres), 2) as avg_litres
        FROM water_readings
        WHERE date = ?
    """
    if device_id:
        sql += " AND device_id = ?"
        params.append(device_id)

    row = conn.execute(sql, params).fetchone()
    res = dict(row) if row else {}
    res['date'] = date_str
    
    # Ensure zero values if no readings exist
    if not res.get('reading_count'):
        res['reading_count'] = 0
        res['min_level_cm'] = 0.0
        res['max_level_cm'] = 0.0
        res['avg_level_cm'] = 0.0
        res['min_percentage'] = 0.0
        res['max_percentage'] = 0.0
        res['avg_percentage'] = 0.0
        res['min_litres'] = 0.0
        res['max_litres'] = 0.0
        res['avg_litres'] = 0.0

    return res


def compare_dates(
    date1_str: str,
    date2_str: str,
    device_id: Optional[str] = None,
    db: Optional[sqlite3.Connection] = None
) -> Dict[str, Any]:
    """
    Compares telemetry statistics between two specific calendar dates.
    Calculates differences and trend directions.
    """
    conn = db or get_db()
    stat1 = get_single_date_summary(date1_str, device_id=device_id, db=conn)
    stat2 = get_single_date_summary(date2_str, device_id=device_id, db=conn)

    has_data = (stat1['reading_count'] > 0 and stat2['reading_count'] > 0)
    
    if has_data:
        diff_litres = round(stat2['avg_litres'] - stat1['avg_litres'], 2)
        diff_percentage = round(stat2['avg_percentage'] - stat1['avg_percentage'], 2)
        diff_max_litres = round(stat2['max_litres'] - stat1['max_litres'], 2)
        if diff_litres > 0:
            trend = "increasing"
        elif diff_litres < 0:
            trend = "decreasing"
        else:
            trend = "neutral"
    else:
        diff_litres = 0.0
        diff_percentage = 0.0
        diff_max_litres = 0.0
        trend = "insufficient_data"

    return {
        'status': 'success',
        'date1': stat1,
        'date2': stat2,
        'comparison': {
            'avg_difference_litres': diff_litres,
            'avg_litres_diff': diff_litres,  # alias
            'avg_difference_percentage': diff_percentage,
            'avg_percentage_diff': diff_percentage,  # alias
            'max_difference_litres': diff_max_litres,
            'max_litres_diff': diff_max_litres,  # alias
            'trend': trend
        }
    }


def get_today_summary(
    device_id: Optional[str] = None,
    date_str: Optional[str] = None,
    db: Optional[sqlite3.Connection] = None
) -> Dict[str, Any]:
    """
    Computes today's scorecard: reading count, min/max/avg, and net consumption/change.
    """
    conn = db or get_db()
    target_date = date_str or datetime.now().strftime('%Y-%m-%d')
    summary = get_single_date_summary(target_date, device_id=device_id, db=conn)

    # Net change calculation: latest reading water_litres - first reading water_litres
    params: List[Any] = [target_date]
    sql_base = "SELECT water_litres FROM water_readings WHERE date = ?"
    if device_id:
        sql_base += " AND device_id = ?"
        params.append(device_id)

    first_cur = conn.execute(sql_base + " ORDER BY timestamp ASC, id ASC LIMIT 1", params)
    first_row = first_cur.fetchone()

    last_cur = conn.execute(sql_base + " ORDER BY timestamp DESC, id DESC LIMIT 1", params)
    last_row = last_cur.fetchone()

    if first_row and last_row:
        net_change = round(last_row['water_litres'] - first_row['water_litres'], 2)
    else:
        net_change = 0.0

    summary['net_change_litres'] = net_change
    return summary


# ============================================================================
# 5. Backup Log Operations
# ============================================================================

def insert_backup_log(
    backup_type: str,
    file_format: str,
    filename: str,
    file_path: str,
    file_size_bytes: int,
    records_count: int,
    status: str,
    error_message: Optional[str] = None,
    created_at: Optional[str] = None,
    db: Optional[sqlite3.Connection] = None
) -> int:
    """
    Logs a backup event (scheduled or manual, success or failure).
    Returns inserted log ID.
    """
    conn = db or get_db()
    ts = created_at or datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        cur = conn.execute(
            """INSERT INTO backup_logs (
                backup_type, file_format, filename, file_path,
                file_size_bytes, records_count, status, error_message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                backup_type, file_format, filename, file_path,
                file_size_bytes, records_count, status, error_message, ts
            )
        )
        conn.commit()
        return cur.lastrowid
    except Exception:
        conn.rollback()
        raise


def get_backup_logs(
    limit: int = 50,
    offset: int = 0,
    db: Optional[sqlite3.Connection] = None
) -> List[Dict[str, Any]]:
    """Returns list of past backup logs ordered chronologically descending."""
    conn = db or get_db()
    cur = conn.execute(
        "SELECT * FROM backup_logs ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        (limit, offset)
    )
    return rows_to_dict_list(cur.fetchall())


def get_backup_by_filename(
    filename: str,
    db: Optional[sqlite3.Connection] = None
) -> Optional[Dict[str, Any]]:
    """
    Retrieves a backup log entry by filename.
    Essential security lookup to verify download requests before serving files.
    """
    conn = db or get_db()
    cur = conn.execute(
        "SELECT * FROM backup_logs WHERE filename = ? ORDER BY id DESC LIMIT 1",
        (filename,)
    )
    return row_to_dict(cur.fetchone())


def get_total_readings_count(db: Optional[sqlite3.Connection] = None) -> int:
    """Returns total record count in water_readings table."""
    conn = db or get_db()
    cur = conn.execute("SELECT COUNT(*) as total FROM water_readings")
    row = cur.fetchone()
    return row['total'] if row else 0
```

---

## 8. Unit Testing & Verification Strategy

The following test suites must be executed to verify the DAL implementation:

1. **Connection Lifecycle Tests (`tests/test_database.py`)**:
   - `test_create_connection_pragmas`: Verifies `foreign_keys == ON`, `journal_mode == WAL`, and `busy_timeout >= 30000`.
   - `test_get_db_standalone`: Tests standalone connection without Flask context.
   - `test_get_db_flask_appcontext`: Tests reusing connection across `g.db` and teardown closing.
   - `test_get_db_context_manager`: Tests `get_db_context()` commits on clean exit and rolls back on exception.
2. **Device Operations Tests (`tests/test_models_devices.py`)**:
   - `test_get_device_found_and_not_found`
   - `test_verify_api_key_valid_and_invalid`
   - `test_authenticate_device_active_vs_deactivated`
   - `test_update_last_seen_persists`
3. **Tank Settings Operations Tests (`tests/test_models_settings.py`)**:
   - `test_get_tank_settings_singleton_and_aliases`
   - `test_update_tank_settings_valid`
   - `test_update_tank_settings_invalid_boundary_rejected` (negative height, critical >= low)
4. **Water Reading & Analytics Tests (`tests/test_models_readings.py`)**:
   - `test_insert_water_reading_foreign_key_violation` (rejects unprovisioned device)
   - `test_insert_water_reading_updates_last_seen_atomically`
   - `test_get_latest_reading_empty_and_populated`
   - `test_get_readings_by_date`
   - `test_get_daily_stats_15_days`
   - `test_compare_dates_increasing_decreasing_empty`
   - `test_today_summary_net_change`
5. **Backup Logs Operations Tests (`tests/test_models_backup.py`)**:
   - `test_insert_and_retrieve_backup_log`
   - `test_get_backup_by_filename_lookup`
   - `test_backup_log_status_check_constraints`

---

## 9. Conclusion & Recommendations

1. **Adopt Dual-Mode DAL Architecture**: `app/database.py` with `has_app_context()` detection guarantees that both web routes and scheduled CLI tasks share identical database logic without duplication or connection leaks.
2. **Strict Foreign Key Enforcement**: By enforcing `PRAGMA foreign_keys = ON;` on every single connection, orphaned readings and corrupted states are prevented at the database engine level.
3. **Alias Harmonization**: Providing dual aliases (`tank_height_cm` / `total_height_cm`, `low_threshold_percent` / `warning_low_percent`) eliminates subtle runtime bugs between backend endpoints, JavaScript UI widgets, and ESP32 firmware.
4. **Transaction Integrity**: Wrapping telemetry ingestion and device `last_seen` timestamping in a single atomic transaction ensures consistency and high write throughput.
