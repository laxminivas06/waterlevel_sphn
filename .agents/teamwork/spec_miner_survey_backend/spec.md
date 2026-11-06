# Backend, Database, Backup, and Deployment Authoritative Specification
**Document Version:** 1.0.0  
**Author:** spec_miner_survey_backend  
**Target Architecture:** Python 3 (Flask), SQLite 3, PythonAnywhere WSGI hosting, standalone scheduled tasks.  
**Compliance Standards:** REST / JSON, HTTP/1.1 RFC 9110, POSIX cron/scheduled tasks, PEP 3333 WSGI.

---

## 1. Executive Summary & Architecture Overview

The backend subsystem serves as the central hub of the IoT Smart Water Tank Level Monitoring System. It has four core responsibilities:
1. **Sensor Ingestion:** Ingests telemetry packets from the ESP32 NodeMCU microcontroller via authenticated HTTP `POST` requests, validates physical and mathematical boundaries, timestamps readings, and records them in SQLite.
2. **Dashboard & Analytics API:** Serves real-time readings, online/offline device connectivity status, 15-day historical aggregate metrics, intraday granular curves, day-to-day comparisons, and tank configuration settings.
3. **Automated Daily Backup Subsystem:** Provides scheduled data exports (CSV and JSON) stored in a persistent local directory (`backups/`) and logged in the database, with automated age-based rotation (30-day retention) and on-demand manual triggering/download from the dashboard.
4. **PythonAnywhere Deployment Infrastructure:** Tailored for seamless zero-daemon execution on PythonAnywhere via WSGI (`wsgi.py`), standalone scheduled task CLI runners, robust path resolution avoiding relative working-directory traps, and explicit HTTPS SSL configuration.

---

## 2. Features Discovered

| # | Category | Feature | Description | Inputs | Outputs | Error Behavior | Discovered Via |
|---|----------|---------|-------------|--------|---------|----------------|----------------|
| 1 | Database | SQLite Relational Schema | Four core normalized tables: `water_readings`, `devices`, `tank_settings`, `backup_logs` with foreign keys, checks, and defaults. | Schema DDL execution | Tables created in SQLite DB file | `sqlite3.OperationalError` if path/syntax invalid | R2 & Acceptance Criteria |
| 2 | Database | High-Performance Indexing | Optimized composite B-Tree indexes on timestamps, date partition, device-time pairing, and backup log timestamps. | DDL Index statements | B-Tree index structures | `sqlite3.OperationalError` | R2 Acceptance Criteria |
| 3 | Database | Idempotent DB Initializer | CLI script `init_db.py` to create schema, apply migrations, and seed default singleton settings and default device. | CLI flags `--db-path`, `--reset` | Exit 0, DB initialized with default records | Exit 1 with error log if permissions fail | R6 Acceptance Criteria |
| 4 | Ingestion API | Telemetry Ingestion (`POST /api/water-level`) | Ingestion endpoint receiving sensor readings from ESP32 with validation, timestamping, and last-seen update. | JSON payload with device_id, distance, water_level, percentage, litres + API Key | HTTP 201 Created with reading_id and timestamp | 400 (Bad payload), 401 (Unauthorized), 422 (Out of range) | R2 & Sensor Data Ingestion AC |
| 5 | Authentication | Dual-Mode Device Authentication | Validates device API key provided either via HTTP header `X-API-Key` or JSON body field `api_key`. | Header `X-API-Key` or body `api_key` | Authenticated request context | HTTP 401 Unauthorized (`{"error": "Unauthorized: Invalid or missing API key"}`) | R2 Acceptance Criteria |
| 6 | Telemetry | Physical Range Validation | Validates sensor values against physical tank physics: `percentage` in [0, 100], `litres` >= 0, `distance` >= 0, `water_level` >= 0. | Numeric telemetry fields | Parsed float values | HTTP 422 Unprocessable Entity with descriptive field message | R2 Acceptance Criteria |
| 7 | Device Status | Online/Offline Status Tracking | Evaluates if device is currently online based on `(now - last_seen) <= offline_threshold_seconds` (default 300s). | Device record `last_seen` timestamp | `"status": "online"` or `"offline"`, seconds elapsed | If no readings ever, status is `"offline"` | R2 & Dashboard AC |
| 8 | Dashboard API | Current Status & Summary (`GET /api/water-level/current`) | Returns the most recent sensor reading, current device connectivity status, tank metrics, and today's statistical summary. | Optional query param `?device_id=xxx` | HTTP 200 JSON with reading, device, tank, today_summary | HTTP 200 with `reading: null` if empty DB | R3 & Dashboard AC |
| 9 | Analytics API | 15-Day Historical Daily Aggregates (`GET /api/history/daily-stats`) | Aggregates daily min, max, average levels, percentage, and litres for the past N days (default 15). | Optional `?days=15&device_id=xxx` | HTTP 200 JSON with array of daily summary objects | HTTP 400 if days < 1 or days > 90 | R4 & Acceptance Criteria |
| 10 | Analytics API | Intraday Date Readings Query (`GET /api/history/readings`) | Retrieves all sequential timestamped telemetry data points for any selected date to plot Chart.js time-series. | Query param `?date=YYYY-MM-DD` | HTTP 200 JSON with readings array and day min/max/avg | HTTP 400 if date format invalid | R4 Acceptance Criteria |
| 11 | Analytics API | Day-to-Day Comparison (`GET /api/history/compare`) | Compares water levels, consumption trends, and net differences between two specific calendar dates. | Query params `?date1=YYYY-MM-DD&date2=YYYY-MM-DD` | HTTP 200 JSON with date1 stats, date2 stats, and difference | HTTP 400 if missing or invalid date params | R4 Acceptance Criteria |
| 12 | Settings API | Tank Settings Read (`GET /api/settings`) | Returns current tank physical configuration, sensor offset, total capacity, and threshold boundaries. | None | HTTP 200 JSON with tank settings object | HTTP 500 if database table missing | R2 Acceptance Criteria |
| 13 | Settings API | Tank Settings Update (`PUT /api/settings`) | Updates tank height, sensor offset, capacity, offline timeout, and alert thresholds with strict boundary checks. | JSON body with updated configuration parameters | HTTP 200 JSON with updated settings | HTTP 400 (malformed) or 422 (invalid values) | R2 Acceptance Criteria |
| 14 | Backup System | Standalone Backup Script (`backup.py`) | Autonomous CLI runner exporting SQLite records to CSV/JSON files in `backups/` without requiring persistent daemons. | CLI args `--format`, `--db-path`, `--output-dir`, `--retention-days` | Exit 0, generated backup file, logged in DB | Exit 1, error logged to stderr and `backup_logs` | R5 & PythonAnywhere AC |
| 15 | Backup System | Multi-Format Export Support | Supports exporting telemetry data to both structured JSON and universal CSV formats. | `--format csv` / `json` / `both` | Timestamped `.json` / `.csv` files | HTTP 400 if requested format unsupported | R5 Acceptance Criteria |
| 16 | Backup System | Automated Retention Rotation | Automatically deletes backup files older than `retention_days` (default 30 days) to prevent disk exhaustion. | System clock and directory scan | Purged expired files | Non-fatal logging if permission denied | R5 Acceptance Criteria |
| 17 | Backup API | Manual Backup Trigger (`POST /api/backup/create`) | Allows triggering an immediate on-demand database backup from dashboard UI without SSH/CLI access. | Optional JSON `{"format": "both"}` | HTTP 201 Created with backup details and download URL | HTTP 500 if disk write fails | R5 Acceptance Criteria |
| 18 | Backup API | Backup Inventory List (`GET /api/backup/list`) | Lists all past backup logs with status, file size, record count, and download availability. | Optional `?limit=50` | HTTP 200 JSON with array of backup entries | HTTP 500 on DB error | R5 Acceptance Criteria |
| 19 | Backup API | Secure Backup Download (`GET /api/backup/download/<filename>`) | Serves backup file as attachment with path traversal sanitization and validation against known log entries. | URL filename parameter | File attachment with `Content-Disposition` | HTTP 400 (Traversal attack), 404 (File not found) | R5 Acceptance Criteria |
| 20 | Deployment | PythonAnywhere WSGI Adapter (`wsgi.py`) | WSGI entrypoint exposing `application` callable with absolute project path injection into `sys.path`. | WSGI HTTP request from uWSGI/Nginx | WSGI response stream | 500 Internal Server Error if module fails | R6 Acceptance Criteria |
| 21 | Deployment | Pinned Dependencies (`requirements.txt`) | Lightweight dependency manifest pinned to exact compatible versions for fast virtualenv install on PythonAnywhere. | `pip install -r requirements.txt` | Installed packages | Exit code != 0 if dependency resolution fails | R6 Acceptance Criteria |
| 22 | System | Health Probe (`GET /api/health`) | Quick liveness check verifying database connection, application uptime, and filesystem access. | None | HTTP 200 JSON `{"status": "healthy", "database": "connected"}` | HTTP 503 Service Unavailable if DB unreachable | R6 Acceptance Criteria |

---

## 3. Edge Cases & Boundary Conditions

| # | Feature | Input / Condition | Observed / Documented Behavior |
|---|---------|-------------------|--------------------------------|
| 1 | `POST /api/water-level` | Request without `X-API-Key` header and without `api_key` in JSON body | Returns HTTP `401 Unauthorized` (`{"error": "Unauthorized: Missing API key"}`). Reading is rejected; no DB row inserted. |
| 2 | `POST /api/water-level` | Request with incorrect or unregistered API key | Returns HTTP `401 Unauthorized` (`{"error": "Unauthorized: Invalid API key"}`). Reading is rejected. |
| 3 | `POST /api/water-level` | Request for a registered device where `is_active = 0` | Returns HTTP `403 Forbidden` (`{"error": "Forbidden: Device is deactivated"}`). |
| 4 | `POST /api/water-level` | Request with Content-Type other than `application/json` or unparseable JSON syntax | Returns HTTP `400 Bad Request` (`{"error": "Malformed JSON payload"}`). |
| 5 | `POST /api/water-level` | Missing one or more required keys (`device_id`, `distance_cm`, `water_level_cm`, `water_percentage`, `water_litres`) | Returns HTTP `400 Bad Request` (`{"error": "Missing required field: <key>"}`). |
| 6 | `POST /api/water-level` | String or boolean passed for numeric fields (e.g., `"distance_cm": "forty"`, `"water_percentage": true`) | Returns HTTP `422 Unprocessable Entity` (`{"error": "Field 'distance_cm' must be a valid finite number"}`). |
| 7 | `POST /api/water-level` | `NaN` or `Infinity` passed for numeric fields | Returns HTTP `422 Unprocessable Entity` (`{"error": "Numeric values must be finite"}`). |
| 8 | `POST /api/water-level` | Negative values for distance (`distance_cm: -5.0`) or level (`water_level_cm: -1.0`) | Returns HTTP `422 Unprocessable Entity` (`{"error": "distance_cm and water_level_cm must be non-negative"}`). |
| 9 | `POST /api/water-level` | `water_percentage` outside physical limits (`-0.1` or `100.1`) | Returns HTTP `422 Unprocessable Entity` (`{"error": "water_percentage must be between 0.0 and 100.0"}`). |
| 10 | `POST /api/water-level` | `water_litres` negative (`water_litres: -10.0`) | Returns HTTP `422 Unprocessable Entity` (`{"error": "water_litres cannot be negative"}`). |
| 11 | `POST /api/water-level` | `water_litres` exceeds tank capacity | Accepted with warning or capped: physical water can temporarily touch overflow. Reading is saved; tank status marked overflow/critical. |
| 12 | `GET /api/water-level/current` | Database is fresh with zero recorded readings | Returns HTTP `200 OK` with `"reading": null`, `"device": {"status": "offline", "last_seen": null}`, `"today_summary": {"reading_count": 0, "min_litres": 0, "max_litres": 0, "avg_litres": 0}`. Dashboard handles null gracefully without crashing. |
| 13 | `GET /api/water-level/current` | Device last communicated 301 seconds ago (threshold is 300 seconds) | Returns `"device": {"status": "offline", "seconds_since_last_seen": 301}`. |
| 14 | `GET /api/history/daily-stats` | Database has only 3 days of data but `days=15` requested | Returns HTTP `200 OK` with 3 available summary entries sorted chronologically (`ASC`). |
| 15 | `GET /api/history/daily-stats` | Invalid `days` parameter (e.g. `days=abc` or `days=-5` or `days=1000`) | Returns HTTP `400 Bad Request` (`{"error": "days parameter must be an integer between 1 and 90"}`). |
| 16 | `GET /api/history/readings` | Requested date has 0 readings (e.g. historical date before installation) | Returns HTTP `200 OK` with `"reading_count": 0`, `"readings": []`, and summary values set to `null` or `0.0`. |
| 17 | `GET /api/history/readings` | Malformed date string (e.g. `2026-02-31` or `invalid-date`) | Returns HTTP `400 Bad Request` (`{"error": "date parameter must be in YYYY-MM-DD format"}`). |
| 18 | `GET /api/history/compare` | Querying comparison where one or both dates have 0 records | Returns HTTP `200 OK` with empty stats for that date and `"comparison": {"trend": "insufficient_data"}`. |
| 19 | `GET /api/history/compare` | `date1` and `date2` are identical dates | Returns HTTP `200 OK` with `avg_difference_litres: 0.0` and `trend: "neutral"`. |
| 20 | `PUT /api/settings` | Setting `critical_low_threshold_percent >= low_threshold_percent` (e.g. critical 25%, low 20%) | Returns HTTP `422 Unprocessable Entity` (`{"error": "critical_low_threshold_percent must be strictly less than low_threshold_percent"}`). |
| 21 | `PUT /api/settings` | Setting negative tank height or total capacity <= 0 | Returns HTTP `422 Unprocessable Entity` (`{"error": "tank_height_cm and total_capacity_litres must be positive"}`). |
| 22 | `GET /api/backup/download/<filename>` | Filename with directory traversal attack (`../../etc/passwd` or `..\\app.py`) | Returns HTTP `400 Bad Request` (`{"error": "Invalid filename parameter"}`). No filesystem access attempted outside `backups/`. |
| 23 | `GET /api/backup/download/<filename>` | Legitimate filename format but file deleted from disk | Returns HTTP `404 Not Found` (`{"error": "Backup file not found on disk"}`). |
| 24 | `backup.py` CLI Runner | SQLite database locked by concurrent web request | SQLite connection configured with `timeout=30.0` and `PRAGMA busy_timeout = 30000;`. Retries transparently rather than crashing. |
| 25 | PythonAnywhere WSGI | Working directory at WSGI boot is `/var/www` or `/home/<user>` | SQLite path must be resolved using absolute path (`os.path.abspath(os.path.join(os.path.dirname(__file__), 'water_leveler.db'))`) preventing permission errors in `/var/www`. |

---

## 4. SQLite Database Schema Specification

### 4.1 Schema DDL (`schema.sql`)

```sql
-- Enforce foreign key constraints
PRAGMA foreign_keys = ON;

-- 1. Devices Table
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    api_key TEXT NOT NULL,
    device_name TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    last_seen TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 2. Tank Settings Table (Singleton pattern: id is constrained to 1)
CREATE TABLE IF NOT EXISTS tank_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    tank_height_cm REAL NOT NULL DEFAULT 200.0 CHECK (tank_height_cm > 0),
    sensor_offset_cm REAL NOT NULL DEFAULT 15.0 CHECK (sensor_offset_cm >= 0),
    total_capacity_litres REAL NOT NULL DEFAULT 1000.0 CHECK (total_capacity_litres > 0),
    offline_threshold_seconds INTEGER NOT NULL DEFAULT 300 CHECK (offline_threshold_seconds >= 30),
    low_threshold_percent REAL NOT NULL DEFAULT 20.0 CHECK (low_threshold_percent >= 0 AND low_threshold_percent <= 100),
    critical_low_threshold_percent REAL NOT NULL DEFAULT 10.0 CHECK (critical_low_threshold_percent >= 0 AND critical_low_threshold_percent < low_threshold_percent),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 3. Water Readings Telemetry Table
CREATE TABLE IF NOT EXISTS water_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    distance_cm REAL NOT NULL CHECK (distance_cm >= 0),
    water_level_cm REAL NOT NULL CHECK (water_level_cm >= 0),
    water_percentage REAL NOT NULL CHECK (water_percentage >= 0.0 AND water_percentage <= 100.0),
    water_litres REAL NOT NULL CHECK (water_litres >= 0.0),
    timestamp TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    date TEXT NOT NULL,
    FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE
);

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_water_readings_timestamp ON water_readings (timestamp);
CREATE INDEX IF NOT EXISTS idx_water_readings_date ON water_readings (date);
CREATE INDEX IF NOT EXISTS idx_water_readings_device_time ON water_readings (device_id, timestamp);

-- 4. Backup Logs Table
CREATE TABLE IF NOT EXISTS backup_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backup_type TEXT NOT NULL CHECK (backup_type IN ('scheduled', 'manual')),
    file_format TEXT NOT NULL CHECK (file_format IN ('csv', 'json', 'both')),
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL CHECK (file_size_bytes >= 0),
    records_count INTEGER NOT NULL CHECK (records_count >= 0),
    status TEXT NOT NULL CHECK (status IN ('success', 'failed')),
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_backup_logs_created_at ON backup_logs (created_at);
```

### 4.2 Seed Data (`seed.sql` / `init_db.py`)
```sql
-- Default Singleton Configuration
INSERT OR IGNORE INTO tank_settings (
    id, 
    tank_height_cm, 
    sensor_offset_cm, 
    total_capacity_litres, 
    offline_threshold_seconds, 
    low_threshold_percent, 
    critical_low_threshold_percent
) VALUES (
    1, 
    200.0, 
    15.0, 
    1000.0, 
    300, 
    20.0, 
    10.0
);

-- Default Device Provisioning
INSERT OR IGNORE INTO devices (
    device_id, 
    api_key, 
    device_name, 
    is_active
) VALUES (
    'esp32_tank_01', 
    'water_secret_key_2026', 
    'Main Tank Sensor', 
    1
);
```

---

## 5. REST API Interface Contracts

### 5.1 Endpoint Summary

| Method | Endpoint | Auth Required | Description |
|--------|----------|---------------|-------------|
| `POST` | `/api/water-level` | Device Key (`X-API-Key` or JSON) | Ingests sensor reading from ESP32 |
| `GET` | `/api/water-level/current` | None | Latest reading, device connectivity, tank state |
| `GET` | `/api/water-level/latest` | None | Alias for `/api/water-level/current` |
| `GET` | `/api/history/daily-stats` | None | 15-day aggregate statistics (min, max, avg) |
| `GET` | `/api/history/readings` | None | Intraday readings for a specific date (`YYYY-MM-DD`) |
| `GET` | `/api/history/compare` | None | Comparison between two dates (`date1`, `date2`) |
| `GET` | `/api/settings` | None | Current tank and threshold configurations |
| `PUT` | `/api/settings` | Optional / Admin Key | Update tank dimensions & alert thresholds |
| `POST` | `/api/backup/create` | None | Triggers immediate manual backup generation |
| `GET` | `/api/backup/list` | None | Lists historical backup event logs |
| `GET` | `/api/backup/download/<name>` | None | Downloads generated backup file |
| `GET` | `/api/devices` | None | List registered devices & online status |
| `GET` | `/api/health` | None | System and SQLite health probe |

---

### 5.2 Detailed Endpoint Specifications

#### 1. Ingest Sensor Reading
- **Route:** `POST /api/water-level`
- **Headers:** 
  - `Content-Type: application/json`
  - `X-API-Key: <device_api_key>` (optional if included in JSON body)
- **Request Body:**
  ```json
  {
    "device_id": "esp32_tank_01",
    "distance_cm": 42.5,
    "water_level_cm": 157.5,
    "water_percentage": 78.75,
    "water_litres": 787.5,
    "api_key": "water_secret_key_2026"
  }
  ```
- **Responses:**
  - `201 Created`:
    ```json
    {
      "status": "success",
      "message": "Water level reading recorded successfully",
      "reading_id": 512,
      "timestamp": "2026-11-06 20:30:15"
    }
    ```
  - `400 Bad Request`:
    ```json
    {
      "status": "error",
      "error": "Missing required field: distance_cm"
    }
    ```
  - `401 Unauthorized`:
    ```json
    {
      "status": "error",
      "error": "Unauthorized: Invalid or missing API key"
    }
    ```
  - `403 Forbidden`:
    ```json
    {
      "status": "error",
      "error": "Forbidden: Device 'esp32_tank_01' is deactivated"
    }
    ```
  - `422 Unprocessable Entity`:
    ```json
    {
      "status": "error",
      "error": "water_percentage must be between 0.0 and 100.0"
    }
    ```

#### 2. Get Current Status & Reading
- **Route:** `GET /api/water-level/current`
- **Query Parameters:** `device_id` (optional, string)
- **Response (`200 OK`):**
  ```json
  {
    "status": "success",
    "reading": {
      "id": 512,
      "device_id": "esp32_tank_01",
      "distance_cm": 42.5,
      "water_level_cm": 157.5,
      "water_percentage": 78.75,
      "water_litres": 787.5,
      "timestamp": "2026-11-06 20:30:15",
      "date": "2026-11-06"
    },
    "device": {
      "device_id": "esp32_tank_01",
      "device_name": "Main Tank Sensor",
      "status": "online",
      "last_seen": "2026-11-06 20:30:15",
      "seconds_since_last_seen": 15
    },
    "tank": {
      "tank_height_cm": 200.0,
      "sensor_offset_cm": 15.0,
      "total_capacity_litres": 1000.0,
      "remaining_litres": 212.5,
      "low_threshold_percent": 20.0,
      "critical_low_threshold_percent": 10.0,
      "level_status": "normal",
      "status_color": "green"
    },
    "today_summary": {
      "date": "2026-11-06",
      "min_litres": 720.0,
      "max_litres": 850.0,
      "avg_litres": 792.3,
      "readings_count": 120
    }
  }
  ```

#### 3. 15-Day Historical Daily Statistics
- **Route:** `GET /api/history/daily-stats`
- **Query Parameters:**
  - `days`: integer (optional, default `15`, range `1..90`)
  - `device_id`: string (optional)
- **Response (`200 OK`):**
  ```json
  {
    "status": "success",
    "days_requested": 15,
    "stats": [
      {
        "date": "2026-10-23",
        "reading_count": 288,
        "min_level_cm": 110.0,
        "max_level_cm": 185.0,
        "avg_level_cm": 153.2,
        "min_percentage": 55.0,
        "max_percentage": 92.5,
        "avg_percentage": 76.6,
        "min_litres": 550.0,
        "max_litres": 925.0,
        "avg_litres": 766.0
      }
    ]
  }
  ```

#### 4. Intraday Sequential Readings
- **Route:** `GET /api/history/readings`
- **Query Parameters:**
  - `date`: string `YYYY-MM-DD` (optional, default today)
  - `device_id`: string (optional)
- **Response (`200 OK`):**
  ```json
  {
    "status": "success",
    "date": "2026-11-06",
    "reading_count": 2,
    "summary": {
      "min_litres": 750.0,
      "max_litres": 787.5,
      "avg_litres": 768.75,
      "min_percentage": 75.0,
      "max_percentage": 78.75,
      "avg_percentage": 76.88
    },
    "readings": [
      {
        "id": 511,
        "timestamp": "2026-11-06 20:25:15",
        "distance_cm": 50.0,
        "water_level_cm": 150.0,
        "water_percentage": 75.0,
        "water_litres": 750.0
      },
      {
        "id": 512,
        "timestamp": "2026-11-06 20:30:15",
        "distance_cm": 42.5,
        "water_level_cm": 157.5,
        "water_percentage": 78.75,
        "water_litres": 787.5
      }
    ]
  }
  ```

#### 5. Day-to-Day Comparison
- **Route:** `GET /api/history/compare`
- **Query Parameters:**
  - `date1`: string `YYYY-MM-DD` (required)
  - `date2`: string `YYYY-MM-DD` (required)
- **Response (`200 OK`):**
  ```json
  {
    "status": "success",
    "date1": {
      "date": "2026-11-05",
      "reading_count": 288,
      "min_litres": 710.0,
      "max_litres": 880.0,
      "avg_litres": 810.0,
      "avg_percentage": 81.0
    },
    "date2": {
      "date": "2026-11-06",
      "reading_count": 120,
      "min_litres": 720.0,
      "max_litres": 850.0,
      "avg_litres": 792.3,
      "avg_percentage": 79.23
    },
    "comparison": {
      "avg_difference_litres": -17.7,
      "avg_difference_percentage": -1.77,
      "trend": "decreasing"
    }
  }
  ```

#### 6. Settings Configuration
- **Route:** `GET /api/settings`
  - Returns current settings singleton row (`tank_height_cm`, `sensor_offset_cm`, `total_capacity_litres`, `offline_threshold_seconds`, `low_threshold_percent`, `critical_low_threshold_percent`).
- **Route:** `PUT /api/settings`
  - Request body:
    ```json
    {
      "tank_height_cm": 220.0,
      "sensor_offset_cm": 15.0,
      "total_capacity_litres": 1200.0,
      "offline_threshold_seconds": 300,
      "low_threshold_percent": 25.0,
      "critical_low_threshold_percent": 12.0
    }
    ```
  - Validates boundaries and persists changes to SQLite row `id = 1`.

#### 7. Backup Operations
- **Route:** `POST /api/backup/create`
  - Request body (optional): `{"format": "json"}` / `{"format": "csv"}` / `{"format": "both"}`
  - Generates backup file(s) in `backups/`, writes log to `backup_logs`.
  - Returns:
    ```json
    {
      "status": "success",
      "backup_id": 14,
      "filename": "backup_20261106_203015.json",
      "file_format": "json",
      "records_count": 1420,
      "file_size_bytes": 145022,
      "download_url": "/api/backup/download/backup_20261106_203015.json"
    }
    ```
- **Route:** `GET /api/backup/list`
  - Returns array of past backup operations from `backup_logs` with download status.
- **Route:** `GET /api/backup/download/<filename>`
  - Sanitizes `<filename>` (rejects `..` or illegal path characters), verifies file exists inside `backups/`, and streams the file with header:
    `Content-Disposition: attachment; filename="<filename>"`

---

## 6. Automated Daily Backup Subsystem Specification

### 6.1 CLI Script Specification (`backup.py`)
- **Execution Mode:** Standalone Python script executable from terminal, cron, or PythonAnywhere Scheduled Tasks runner.
- **Persistent Location:** Subdirectory `backups/` in project root. Must be created automatically if missing (`os.makedirs(..., exist_ok=True)`).
- **CLI Options:**
  - `--format`: Format to export (`csv`, `json`, or `both`; default: `both`).
  - `--db-path`: Path to SQLite database file (default: resolves to project root `water_leveler.db`).
  - `--output-dir`: Output directory for generated backups (default: resolves to project root `backups/`).
  - `--retention-days`: Maximum age in days to retain backup files before deletion (default: `30`).
  - `--type`: Log backup origin (`scheduled` or `manual`; default: `scheduled`).

### 6.2 Data Export Schema
- **JSON Structure (`backup_YYYYMMDD_HHMMSS.json`):**
  ```json
  {
    "backup_metadata": {
      "version": "1.0",
      "created_at": "2026-11-06T20:30:15",
      "type": "scheduled",
      "records_count": 512
    },
    "tank_settings": [ ... ],
    "devices": [ ... ],
    "water_readings": [
      {
        "id": 1,
        "device_id": "esp32_tank_01",
        "distance_cm": 42.5,
        "water_level_cm": 157.5,
        "water_percentage": 78.75,
        "water_litres": 787.5,
        "timestamp": "2026-11-06 20:30:15",
        "date": "2026-11-06"
      }
    ]
  }
  ```
- **CSV Structure (`backup_YYYYMMDD_HHMMSS.csv`):**
  Header row: `id,device_id,distance_cm,water_level_cm,water_percentage,water_litres,timestamp,date`
  Data rows: standard RFC 4180 CSV encoding.

### 6.3 Retention Policy and Cleanup
- During every backup execution, the script iterates over files in `backups/`.
- For any file whose modification time is older than `retention_days * 86400` seconds:
  - File is safely unlinked (`os.remove`).
  - Logged to stdout/stderr.

### 6.4 PythonAnywhere Scheduled Task Integration
- Under PythonAnywhere's **Tasks** tab, configure a daily scheduled task at `01:00 UTC`:
  ```bash
  /home/<username>/.virtualenvs/water_leveler/bin/python /home/<username>/water_leveler/backup.py --format both --retention-days 30
  ```
- Guaranteed to run reliably without persistent daemon memory leaks or background thread starvation.

---

## 7. PythonAnywhere Deployment Specification

### 7.1 Target File Layout
```
c:\Users\IDEAL\Documents\ANtigravity\water_leveler\   (Local source repository)
│
├── app.py                     # Main Flask application with API & UI routes
├── config.py                  # Absolute path resolution & environment defaults
├── init_db.py                 # SQLite schema creation & idempotent seed script
├── backup.py                  # Standalone daily backup & retention CLI runner
├── wsgi.py                    # WSGI entrypoint exposing 'application'
├── schema.sql                 # Pure SQLite DDL schema
├── requirements.txt           # Minimal pinned dependencies
├── README.md                  # Comprehensive setup & architecture documentation
│
├── backups/                   # Dedicated directory for persistent backups
│   └── .gitkeep
│
├── static/                    # Frontend assets
│   ├── css/
│   │   └── styles.css         # Modern responsive CSS (Dark/Light ready)
│   └── js/
│       ├── app.js             # Dashboard polling, UI interactivity, API calls
│       └── chart.min.js       # Chart.js library (or CDN fallback)
│
├── templates/                 # Jinja2 HTML templates
│   ├── index.html             # Main dashboard (cards, tank gauge, history, backup)
│   └── 404.html               # Custom error page
│
└── tests/                     # Validation & test scripts
    ├── test_api.py            # API contract & validation tests
    └── simulate_esp32.py      # Automated sensor payload simulation script
```

### 7.2 Pinned Dependencies (`requirements.txt`)
```txt
Flask>=3.0.0,<3.2.0
Werkzeug>=3.0.0,<3.2.0
requests>=2.31.0,<2.33.0
pytest>=8.0.0,<9.0.0
```
*(Standard Python libraries `sqlite3`, `csv`, `json`, `os`, `sys`, `datetime`, `argparse`, `logging` are built-in and require no pip installation).*

### 7.3 WSGI Configuration Specification (`wsgi.py` / `/var/www/..._wsgi.py`)
```python
import os
import sys

# 1. Inject application root directory into Python module search path
project_home = '/home/<your-username>/water_leveler'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# 2. Expose the WSGI callable strictly as 'application'
from app import app as application
```

### 7.4 Database Path Resolution Guard (`config.py`)
To prevent `sqlite3.OperationalError` when executed under WSGI (where `os.getcwd()` defaults to `/var/www` or `/home/<username>`), the database path must be resolved relative to the file:
```python
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE_PATH = os.environ.get('DATABASE_PATH', os.path.join(BASE_DIR, 'water_leveler.db'))
BACKUP_DIR = os.environ.get('BACKUP_DIR', os.path.join(BASE_DIR, 'backups'))
```

### 7.5 Step-by-Step PythonAnywhere Deployment Guide

1. **Sign Up / Login:**
   - Create a PythonAnywhere account at `www.pythonanywhere.com` (username e.g., `watertank`).
2. **Open Bash Console & Clone Project:**
   ```bash
   cd /home/watertank
   git clone <repo-url> water_leveler
   cd water_leveler
   ```
3. **Create & Populate Virtualenv:**
   ```bash
   mkvirtualenv --python=python3.10 water_leveler
   pip install -r requirements.txt
   ```
4. **Initialize SQLite Database:**
   ```bash
   python init_db.py
   # Confirms tables and default seed records created in water_leveler.db
   ```
5. **Configure Web App on PythonAnywhere:**
   - Navigate to the **Web** tab.
   - Click **Add a new web app** -> Select **Manual configuration** -> Select **Python 3.10**.
   - Set **Virtualenv** path: `/home/watertank/.virtualenvs/water_leveler`.
   - Set **Source code** path: `/home/watertank/water_leveler`.
   - Set **Working directory**: `/home/watertank/water_leveler`.
   - Under **Static files**:
     - URL: `/static/`
     - Directory: `/home/watertank/water_leveler/static`
   - Edit **WSGI configuration file**: Replace default content with:
     ```python
     import os
     import sys
     project_home = '/home/watertank/water_leveler'
     if project_home not in sys.path:
         sys.path.insert(0, project_home)
     from app import app as application
     ```
   - Enable **Force HTTPS**: Switch the toggle to `ON`.
   - Click the green **Reload watertank.pythonanywhere.com** button.
6. **Configure Automated Daily Backup Scheduled Task:**
   - Navigate to the **Tasks** tab.
   - Under **Scheduled tasks**, create a task to run daily at `01:00 UTC`:
     ```bash
     /home/watertank/.virtualenvs/water_leveler/bin/python /home/watertank/water_leveler/backup.py --format both --retention-days 30
     ```
7. **Verify Deployment:**
   - Open `https://watertank.pythonanywhere.com/api/health` -> verify status is healthy.
   - Open `https://watertank.pythonanywhere.com` -> verify dashboard loads with animated water tank.
