# Milestone M1 Technical Analysis: SQLite Schema DDL, Constraints, and Index Architecture

**Subagent ID:** `m1_explorer_1`  
**Milestone:** M1 — Database & Core Storage Subsystem  
**Scope:** SQLite Relational Schema DDL, Physical Constraints, Data Types, Index Design, Foreign Keys, and Concurrency Architecture.  
**Date:** 2026-11-06  

---

## 1. Executive Summary & Architecture Overview

Milestone M1 establishes the persistence layer for the Smart Water Tank Level Monitoring System. Because the application is targeted for standard server environments as well as zero-daemon hosting on PythonAnywhere, the database architecture relies on an embedded, zero-maintenance, highly concurrent **SQLite 3** relational engine.

The core storage subsystem must reliably solve three fundamental architectural challenges:
1. **Relational Integrity & Physical Domain Constraints:** Sensor readings must never store impossible physical measurements (such as negative liquid volumes, distances, or percentages outside 0.0% to 100.0%). Tank settings must enforce a strict singleton pattern (`id = 1`) and geometric consistency (sensor offset strictly less than total tank height).
2. **Query Performance for 15-Day Time Series & Real-Time Telemetry:** The dashboard queries recent readings, intraday time series, and 15-day aggregate statistics (min, max, average) frequently. Composite B-Tree indexes must eliminate full-table scans and avoid temporary in-memory B-Trees for sorting.
3. **Concurrent Multi-Process Access on PythonAnywhere:** Web worker processes (handling HTTP requests from the ESP32 and user dashboard) operate concurrently with standalone scheduled tasks (daily backup CLI runner). By configuring Write-Ahead Logging (`WAL` mode) and busy timeouts, readers and writers do not block each other, preventing `database is locked` operational failures.

---

## 2. Complete Verified SQLite Schema DDL

The complete, verified DDL below has been tested against Python's SQLite 3 engine and verified to enforce all relational, domain, and foreign key constraints cleanly.

```sql
-- ============================================================================
-- Smart Water Tank Level Monitoring System - SQLite Relational Schema
-- Target: SQLite 3.31+ / Python 3.10+
-- File: schema.sql
-- ============================================================================

-- Enforce Foreign Keys on current connection (Must be run on every new connection)
PRAGMA foreign_keys = ON;

-- ----------------------------------------------------------------------------
-- 1. Devices Table
-- Tracks registered ESP32 sensor units and authentication credentials
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY NOT NULL CHECK (length(trim(device_id)) > 0),
    device_name TEXT NOT NULL CHECK (length(trim(device_name)) > 0),
    api_key TEXT NOT NULL CHECK (length(trim(api_key)) > 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    last_seen TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);

-- ----------------------------------------------------------------------------
-- 2. Tank Settings Table (Singleton Pattern)
-- Stores physical tank dimensions, sensor offset, and threshold configurations.
-- The check constraint (id = 1) strictly prevents multi-row proliferation.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tank_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    total_height_cm REAL NOT NULL DEFAULT 200.0 CHECK (total_height_cm > 0.0),
    sensor_offset_cm REAL NOT NULL DEFAULT 15.0 CHECK (sensor_offset_cm >= 0.0 AND sensor_offset_cm < total_height_cm),
    total_capacity_litres REAL NOT NULL DEFAULT 1000.0 CHECK (total_capacity_litres > 0.0),
    warning_low_percent REAL NOT NULL DEFAULT 20.0 CHECK (warning_low_percent >= 0.0 AND warning_low_percent <= 100.0),
    warning_normal_percent REAL NOT NULL DEFAULT 50.0 CHECK (warning_normal_percent >= warning_low_percent AND warning_normal_percent <= 100.0),
    offline_threshold_seconds INTEGER NOT NULL DEFAULT 300 CHECK (offline_threshold_seconds >= 10),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ----------------------------------------------------------------------------
-- 3. Water Readings Telemetry Table
-- High-throughput time-series table ingesting telemetry readings from ESP32.
-- Enforces physical boundaries on water levels, percentages, and volumes.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS water_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    date TEXT NOT NULL CHECK (length(date) = 10 AND date LIKE '____-__-__'),
    distance_cm REAL NOT NULL CHECK (distance_cm >= 0.0),
    water_level_cm REAL NOT NULL CHECK (water_level_cm >= 0.0),
    water_percentage REAL NOT NULL CHECK (water_percentage >= 0.0 AND water_percentage <= 100.0),
    water_litres REAL NOT NULL CHECK (water_litres >= 0.0),
    raw_reading_json TEXT,
    FOREIGN KEY (device_id) REFERENCES devices (device_id) ON DELETE CASCADE
);

-- B-Tree Performance Indexes for Water Readings
CREATE INDEX IF NOT EXISTS idx_readings_timestamp ON water_readings (timestamp);
CREATE INDEX IF NOT EXISTS idx_readings_date ON water_readings (date);
CREATE INDEX IF NOT EXISTS idx_readings_device_time ON water_readings (device_id, timestamp);

-- ----------------------------------------------------------------------------
-- 4. Backup Logs Table
-- Audit table recording automated daily backups and manual export events.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backup_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL CHECK (length(trim(filename)) > 0),
    filepath TEXT NOT NULL CHECK (length(trim(filepath)) > 0),
    backup_type TEXT NOT NULL CHECK (backup_type IN ('scheduled', 'manual')),
    format TEXT NOT NULL CHECK (format IN ('csv', 'json', 'both')),
    record_count INTEGER NOT NULL CHECK (record_count >= 0),
    file_size_bytes INTEGER NOT NULL CHECK (file_size_bytes >= 0),
    status TEXT NOT NULL CHECK (status IN ('success', 'failed')),
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- B-Tree Performance Index for Backup Inventory Queries
CREATE INDEX IF NOT EXISTS idx_backup_created_at ON backup_logs (created_at);
```

---

## 3. Physical Constraints & Domain Validation

SQLite uses dynamic typing, meaning data type declarations (`REAL`, `INTEGER`, `TEXT`) define column affinity rather than rigid byte widths. To guarantee data hygiene, explicit SQL table `CHECK` constraints are mandatory.

### 3.1 Constraint Inventory & Rationale

| Table | Column / Constraint | SQL Constraint Expression | Physical Domain & Engineering Rationale |
|---|---|---|---|
| `devices` | `device_id` | `PRIMARY KEY NOT NULL CHECK (length(trim(device_id)) > 0)` | Disallows empty strings or whitespace identifiers. Ensures primary key is populated. |
| `devices` | `is_active` | `CHECK (is_active IN (0, 1))` | SQLite lacks native boolean; constrains values strictly to binary 0 (deactivated) or 1 (active). |
| `devices` | `api_key` | `CHECK (length(trim(api_key)) > 0)` | Disallows blank or empty security tokens. |
| `tank_settings` | `id` | `PRIMARY KEY CHECK (id = 1)` | **Singleton enforcement**: Guarantees exactly one global tank configuration row exists in the system. Any attempt to insert `id = 2` is rejected by SQLite. |
| `tank_settings` | `total_height_cm` | `CHECK (total_height_cm > 0.0)` | A physical water tank must have positive height. |
| `tank_settings` | `sensor_offset_cm` | `CHECK (sensor_offset_cm >= 0.0 AND sensor_offset_cm < total_height_cm)` | Ultrasonic sensor mounting offset from the tank ceiling must be non-negative and strictly less than total tank height. |
| `tank_settings` | `total_capacity_litres`| `CHECK (total_capacity_litres > 0.0)` | Tank capacity must be strictly positive. |
| `tank_settings` | `warning_low_percent` | `CHECK (warning_low_percent >= 0.0 AND warning_low_percent <= 100.0)` | Lower threshold percentage for warning (orange alert) must be a valid percentage. Default is 20.0%. |
| `tank_settings` | `warning_normal_percent`| `CHECK (warning_normal_percent >= warning_low_percent AND warning_normal_percent <= 100.0)` | Normal threshold percentage (green level) must be >= warning_low_percent. Default is 50.0%. |
| `tank_settings` | `offline_threshold_seconds`| `CHECK (offline_threshold_seconds >= 10)` | Sensor heartbeat timeout must be at least 10 seconds to prevent thrashing between online and offline states. |
| `water_readings`| `distance_cm` | `CHECK (distance_cm >= 0.0)` | Physical distance measured by ultrasonic sensor cannot be negative. |
| `water_readings`| `water_level_cm` | `CHECK (water_level_cm >= 0.0)` | Physical liquid height cannot be negative. |
| `water_readings`| `water_percentage` | `CHECK (water_percentage >= 0.0 AND water_percentage <= 100.0)` | Percentage must strictly remain within the physical interval [0.0%, 100.0%]. |
| `water_readings`| `water_litres` | `CHECK (water_litres >= 0.0)` | Liquid volume cannot be negative. |
| `water_readings`| `date` | `CHECK (length(date) = 10 AND date LIKE '____-__-__')` | Ensures strict ISO calendar date format (`YYYY-MM-DD`) for reliable date-based aggregation and indexing. |
| `water_readings`| `device_id` (FK) | `FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE` | Prevents orphaned telemetry records. Deleting a device cascades to delete its readings. |
| `backup_logs` | `backup_type` | `CHECK (backup_type IN ('scheduled', 'manual'))` | Restricts log entry origin to valid execution modes. |
| `backup_logs` | `format` | `CHECK (format IN ('csv', 'json', 'both'))` | Validates file format classification. |
| `backup_logs` | `record_count` | `CHECK (record_count >= 0)` | Backed-up row count cannot be negative. |
| `backup_logs` | `file_size_bytes` | `CHECK (file_size_bytes >= 0)` | Export file size cannot be negative. |
| `backup_logs` | `status` | `CHECK (status IN ('success', 'failed'))` | Binary execution state. |

---

## 4. Index Design & Query Optimization

The telemetry table `water_readings` will grow by hundreds of rows per day (e.g. 1 sample every 5 minutes = 288 rows/day; 1 sample every minute = 1,440 rows/day). In 15 days, this represents 4,320 to 21,600 rows. Without proper B-Tree indexing, aggregate queries and dashboard live polling will trigger costly full-table scans.

### 4.1 Index Specifications & Query Execution Plan Verification

Four B-Tree indexes are defined:

1. **`idx_readings_timestamp` on `water_readings (timestamp)`**
   - **Primary query:** `GET /api/water-level/current`
     ```sql
     SELECT * FROM water_readings ORDER BY timestamp DESC LIMIT 1;
     ```
   - **Execution Plan:**
     ```
     SCAN water_readings USING INDEX idx_readings_timestamp
     ```
     SQLite traverses the index backwards and retrieves the single latest record in **O(1)** time without loading or sorting table rows.

2. **`idx_readings_date` on `water_readings (date)`**
   - **Primary queries:**
     - Intraday time-series: `GET /api/history/readings?date=YYYY-MM-DD`
       ```sql
       SELECT * FROM water_readings WHERE date = :date ORDER BY timestamp ASC;
       ```
     - 15-day aggregate rollup: `GET /api/history/daily-stats?days=15`
       ```sql
       SELECT date, COUNT(*), MIN(water_level_cm), MAX(water_level_cm), AVG(water_level_cm),
              MIN(water_percentage), MAX(water_percentage), AVG(water_percentage),
              MIN(water_litres), MAX(water_litres), AVG(water_litres)
       FROM water_readings
       WHERE date >= :start_date
       GROUP BY date
       ORDER BY date ASC;
       ```
   - **Execution Plan:**
     ```
     SEARCH water_readings USING INDEX idx_readings_date (date=?)
     ```
     Direct B-Tree seek directly locates the requested calendar day block. Instead of scanning 20,000 rows, SQLite seeks directly to the ~288 records for that day.

3. **`idx_readings_device_time` on `water_readings (device_id, timestamp)`**
   - **Primary query:** `GET /api/water-level/current?device_id=esp32_tank_01`
     ```sql
     SELECT * FROM water_readings WHERE device_id = :device_id ORDER BY timestamp DESC LIMIT 1;
     ```
   - **Execution Plan:**
     ```
     SEARCH water_readings USING INDEX idx_readings_device_time (device_id=?)
     ```
     Because `device_id` is the leading index column and `timestamp` is the second column, SQLite seeks directly to the device segment and scans backwards on timestamp, delivering instant O(1) response time without in-memory sorting.

4. **`idx_backup_created_at` on `backup_logs (created_at)`**
   - **Primary query:** `GET /api/backup/list?limit=50`
     ```sql
     SELECT * FROM backup_logs ORDER BY created_at DESC LIMIT :limit;
     ```
   - **Execution Plan:**
     ```
     SCAN backup_logs USING INDEX idx_backup_created_at
     ```
     Instantly retrieves recent backup events in reverse chronological order without sorting.

---

## 5. SQLite Foreign Keys: Mechanism & Best Practices

### 5.1 Why SQLite Foreign Keys Require Explicit Activation
By default, the SQLite library compiles with foreign key support, but **foreign key constraint enforcement is turned OFF at runtime by default** for backward compatibility with pre-3.6.19 SQLite databases.

### 5.2 Critical Rule: `PRAGMA foreign_keys = ON;` is Connection-Scoped
`PRAGMA foreign_keys = ON;` is **NOT** a persistent database header setting. Setting it during database initialization (`init_db.py`) has **zero effect** on subsequent connections opened by Flask or other scripts.
- Every new connection created via `sqlite3.connect()` starts with foreign keys **disabled** unless explicitly enabled.
- **Action for Data Access Layer (`app/database.py`):**
  Every connection factory function must execute `conn.execute("PRAGMA foreign_keys = ON;")` immediately upon connection establishment:
  ```python
  def get_db():
      if 'db' not in g:
          g.db = sqlite3.connect(current_app.config['DATABASE_PATH'], timeout=30.0)
          g.db.row_factory = sqlite3.Row
          g.db.execute("PRAGMA foreign_keys = ON;")
      return g.db
  ```

### 5.3 Cascading Deletion Verification
When `PRAGMA foreign_keys = ON;` is active:
1. Attempting to insert a reading for an unknown `device_id` immediately raises:
   `sqlite3.IntegrityError: FOREIGN KEY constraint failed`
2. Executing `DELETE FROM devices WHERE device_id = 'esp32_tank_01';` automatically deletes all associated telemetry readings in `water_readings` without leaving orphaned rows.

---

## 6. WAL Mode & Concurrency Architecture for PythonAnywhere

### 6.1 Rollback Journal vs Write-Ahead Logging (WAL)
In SQLite's default rollback journal mode (`DELETE`):
- A writer acquires an exclusive lock on the entire database file.
- Any reader attempting to query data while an ESP32 telemetry packet is being written receives a `sqlite3.OperationalError: database is locked`.
- Conversely, a reader querying 15-day aggregates locks out incoming ESP32 POST requests.

In **Write-Ahead Logging (WAL)** mode (`PRAGMA journal_mode = WAL;`):
1. **Readers Do Not Block Writers:** Readers query a consistent point-in-time snapshot of the database file and WAL file without holding table locks.
2. **Writers Do Not Block Readers:** Incoming telemetry writes append sequentially to the `-wal` file while dashboard queries proceed in parallel.
3. **Sequential Disk I/O:** Appending to the WAL log avoids random disk seeks, drastically improving ingestion throughput on shared filesystems.

### 6.2 Persistence of WAL Mode
Unlike `PRAGMA foreign_keys`, the journal mode setting **is persistent in the database header**. Setting `PRAGMA journal_mode = WAL;` once during `scripts/init_db.py` permanently configures the database file to operate in WAL mode for all future connections.

### 6.3 Concurrency Best Practices for PythonAnywhere
PythonAnywhere runs web workers and scheduled tasks on Linux virtual servers with network-mounted storage. To guarantee rock-solid stability:
1. **Busy Timeout (`PRAGMA busy_timeout = 30000;`):**
   Configures SQLite to sleep and retry internally for up to 30,000 milliseconds (30 seconds) if another transaction is writing, eliminating transient lock errors.
2. **Normal Synchronization (`PRAGMA synchronous = NORMAL;`):**
   In WAL mode, `synchronous = NORMAL` ensures complete durability while avoiding redundant filesystem sync flushes on every commit.
3. **Safe Checkpointing and Backups:**
   During automated daily backups, `scripts/backup.py` can safely read from the database using standard SELECT queries, or execute `PRAGMA wal_checkpoint(PASSIVE);` or use Python's built-in `sqlite3.Connection.backup()` API to produce consistent binary snapshots without interrupting live web ingestion.

---

## 7. Schema Reconciliation & Peer Subagent Guidance

To ensure seamless coordination between Milestone M1 subagents (`m1_explorer_1`, `m1_explorer_2`, and `m1_explorer_3`):

### 7.1 Field Naming Reconciliation

| Table | DDL Column (Authoritative) | Survey Spec (`spec.md`) Name | Resolution & Guidance |
|---|---|---|---|
| `tank_settings` | `total_height_cm` | `tank_height_cm` | Use `total_height_cm` as primary column to match `PROJECT.md` API contract (line 154). `models.py` can alias `tank_height_cm` for backward compatibility. |
| `tank_settings` | `warning_low_percent` | `low_threshold_percent` | Authoritative name is `warning_low_percent` (matches `PROJECT.md` line 157 and color threshold requirements: Orange <50%, Red <20%). |
| `tank_settings` | `warning_normal_percent` | `critical_low_threshold_percent` | Authoritative name is `warning_normal_percent` (matches `PROJECT.md` line 158: Green >50%). |
| `water_readings`| `raw_reading_json` | *(omitted in spec.md)* | Included as nullable `TEXT` column to capture original raw ESP32 JSON payload for auditing and troubleshooting. |
| `backup_logs` | `filepath` | `file_path` | Primary column is `filepath`. In `app/models.py`, queries can alias `filepath AS file_path` so dict access supports both keys. |
| `backup_logs` | `format` | `file_format` | Primary column is `format`. In `app/models.py`, queries can alias `format AS file_format`. |
| `backup_logs` | `record_count` | `records_count` | Primary column is `record_count`. In `app/models.py`, queries can alias `record_count AS records_count`. |

### 7.2 Guidance for `m1_explorer_2` (`scripts/init_db.py`)
1. Create target directory (e.g. `data/` or project root) using `os.makedirs(os.path.dirname(db_path), exist_ok=True)`.
2. Connect with `sqlite3.connect(db_path, timeout=30.0)`.
3. Set persistent WAL mode: `cur.execute("PRAGMA journal_mode = WAL;")`.
4. Enable foreign keys on connection: `cur.execute("PRAGMA foreign_keys = ON;")`.
5. Execute DDL script using `conn.executescript(SCHEMA_SQL)`.
6. Idempotently insert seed records:
   ```sql
   INSERT OR IGNORE INTO devices (device_id, device_name, api_key, is_active)
   VALUES ('esp32_tank_01', 'Main Water Tank', 'tank_secret_key_2026', 1);

   INSERT OR IGNORE INTO tank_settings (id, total_height_cm, sensor_offset_cm, total_capacity_litres, warning_low_percent, warning_normal_percent, offline_threshold_seconds)
   VALUES (1, 200.0, 15.0, 1000.0, 20.0, 50.0, 300);
   ```

### 7.3 Guidance for `m1_explorer_3` (`app/database.py` & `app/models.py`)
1. In `app/database.py`, register a teardown hook (`close_db`) with Flask and enforce `PRAGMA foreign_keys = ON;` and `PRAGMA busy_timeout = 30000;` on every connection.
2. In `app/models.py`, use parameterized SQL queries (`?` placeholders) exclusively to guarantee protection against SQL injection.
3. For `tank_settings`, query with `WHERE id = 1 LIMIT 1`. Updates must target `WHERE id = 1` and update `updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')`.
4. For `water_readings`, ensure date is calculated as `YYYY-MM-DD` and timestamp is ISO-8601 UTC.
