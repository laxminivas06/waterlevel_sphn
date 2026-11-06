# Project: Smart Water Tank Level Monitoring System

## Architecture
The system follows a decoupled, robust IoT telemetry and web architecture designed for lightweight, zero-daemon deployment on PythonAnywhere:
1. **IoT Firmware (ESP32 NodeMCU)**:
   - Reads ultrasonic sensor (HC-SR04 / JSN-SR04T) with 5-stage digital filtering (burst sampling, median filter, delta rejection, EMA smoothing).
   - Computes physical distance, water level (cm), percentage (0-100%), and volume (Litres) based on calibrated tank geometry.
   - Non-blocking Wi-Fi state machine with exponential backoff and circular retry queue.
   - Transmits telemetry packets via HTTPS POST to backend with API key authentication.
   - Strictly monitoring only: zero pump or motor control circuitry/logic.
2. **Backend API & Database (Python Flask & SQLite)**:
   - Python 3 Flask application structured with application factory and blueprints.
   - SQLite relational storage with normalized tables (`devices`, `tank_settings`, `water_readings`, `backup_logs`) and high-performance composite B-Tree indexes.
   - Ingestion endpoint (`POST /api/water-level`) with dual-mode API key authentication, physics validation, and device last-seen timestamping.
   - Real-time status API (`GET /api/water-level/current`), 15-day analytics aggregates (`GET /api/history/daily-stats`), intraday time-series (`GET /api/history/readings`), and day comparison (`GET /api/history/compare`).
3. **Automated Standalone Backup Subsystem**:
   - Standalone CLI runner `scripts/backup.py` executable via PythonAnywhere Scheduled Tasks.
   - Dual-format export (JSON full dump and CSV readings) stored in persistent `backups/` directory.
   - Automated 30-day age retention rotation and DB audit logging.
   - Web API endpoints for on-demand backup generation and secure browser download.
4. **Responsive Web Dashboard & Level Visualization**:
   - Clean, modern HTML5, CSS3, and Vanilla JavaScript UI (zero-build overhead).
   - Pure SVG animated tank visualization with dynamic liquid level, dual sinusoidal wave motion, and 4 state colors (Green >50%, Orange 20-50%, Red <20%, Blue for filling).
   - Dynamic telemetry cards, Today's Summary scorecard, 15-day historical date picker, day-to-day comparison, and interactive Chart.js line charts.
   - Resilient polling engine with Page Visibility API throttling (3s active / 30s background) to respect PythonAnywhere CPU limits.
5. **PythonAnywhere Deployment**:
   - WSGI adapter (`wsgi.py`) with absolute path resolution.
   - Pinned dependencies in `requirements.txt`.
   - Idempotent database initializer (`scripts/init_db.py`).
   - Complete HTTPS deployment documentation (`DEPLOYMENT.md`).

---

## Feature Inventory
Every feature from the Survey phase is enumerated below with its assigned milestone.

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | SQLite Relational Schema | 4 normalized tables (`devices`, `tank_settings`, `water_readings`, `backup_logs`) with constraints & FKs | M1 | Backend Spec |
| 2 | High-Performance Indexing | B-Tree indexes on timestamp, date, (device_id, timestamp), and backup log created_at | M1 | Backend Spec |
| 3 | Idempotent DB Initializer | CLI script `init_db.py` to create schema, apply migrations, seed default singleton settings & device | M1 | Backend Spec |
| 4 | Database Data Access Layer | Thread-safe connection handling, parameterized queries, and dictionary row factory | M1 | Backend Spec |
| 5 | Telemetry Ingestion API | `POST /api/water-level` endpoint accepting telemetry with timestamping & device status update | M2 | Backend Spec |
| 6 | Dual-Mode Authentication | Device API key authentication via HTTP header `X-API-Key` or JSON body `api_key` | M2 | Backend Spec |
| 7 | Physical Range Validation | Strict validation rejecting invalid/out-of-range readings (percentage 0-100, litres >= 0, etc.) | M2 | Backend Spec |
| 8 | Online/Offline Status Tracking | Evaluates device connectivity based on configurable timeout threshold (default 300s) | M2 | Backend Spec |
| 9 | Current Status & Summary API | `GET /api/water-level/current` returning latest reading, connection status, metrics, today's summary | M2 | Backend Spec |
| 10 | 15-Day Historical Daily Aggregates | `GET /api/history/daily-stats` returning min, max, avg levels & volume for past N days (15 default) | M2 | Backend Spec |
| 11 | Intraday Date Readings API | `GET /api/history/readings` returning time-series telemetry for any selected date in past 15 days | M2 | Backend Spec |
| 12 | Day-to-Day Comparison API | `GET /api/history/compare` returning side-by-side metrics and net differences between 2 dates | M2 | Backend Spec |
| 13 | Tank Settings API | `GET /api/settings` and `PUT /api/settings` for viewing/updating tank dimensions & thresholds | M2 | Backend Spec |
| 14 | Health Probe API | `GET /api/health` verifying database connectivity and application health | M2 | Backend Spec |
| 15 | Standalone Backup Script | CLI runner `backup.py` for PythonAnywhere scheduled tasks without persistent daemons | M3 | Backend Spec |
| 16 | Multi-Format Export Support | Export telemetry records to structured JSON and universal CSV formats | M3 | Backend Spec |
| 17 | Automated Retention Rotation | Purges backup files older than configured retention period (default 30 days) | M3 | Backend Spec |
| 18 | Manual Backup Trigger API | `POST /api/backup/create` to trigger immediate on-demand backup from dashboard | M3 | Backend Spec |
| 19 | Backup Inventory List API | `GET /api/backup/list` listing past backups with size, record count, and download status | M3 | Backend Spec |
| 20 | Secure Backup Download API | `GET /api/backup/download/<filename>` serving backup files with directory traversal protection | M3 | Backend Spec |
| 21 | PythonAnywhere WSGI Adapter | `wsgi.py` exposing `application` with absolute path injection to avoid `/var/www` traps | M3 | Backend Spec |
| 22 | Pinned Dependencies | Lightweight `requirements.txt` (Flask, Werkzeug, requests, pytest) | M3 | Backend Spec |
| 23 | Step-by-Step Deployment Docs | `DEPLOYMENT.md` covering WSGI setup, virtualenv, static files, and HTTPS domain config | M3 | Backend Spec |
| 24 | Responsive Dashboard Layout | Modern HTML5/CSS3 dashboard layout responsive on mobile, tablet, and desktop | M4 | Dashboard Survey |
| 25 | SVG Animated Tank Visualization | Pure SVG graphic with dynamic liquid level, dual sinusoidal wave animation, and responsive sizing | M4 | Dashboard Survey |
| 26 | Dynamic Tank Color States | 4 color states: Green (>50%), Orange (20-50%), Red (<20%), Blue (water filling/rising) | M4 | Dashboard Survey |
| 27 | Key Metrics Telemetry Cards | Current percentage, litres, capacity, remaining capacity, last update, device status badge | M4 | Dashboard Survey |
| 28 | Today's Summary Scorecard | Daily Min, Max, Average water levels, and net consumption/change | M4 | Dashboard Survey |
| 29 | Resilient Live Polling Engine | Auto-refreshing telemetry with Page Visibility API throttling (3s active / 30s background) | M4 | Dashboard Survey |
| 30 | 15-Day History Date Selector | Date picker/selector enabling historical inspection of any date within previous 15 days | M4 | Dashboard Survey |
| 31 | Interactive Chart.js Trends | Time-series line chart displaying intraday water level fluctuations with hover tooltips | M4 | Dashboard Survey |
| 32 | Day-to-Day Comparison View | Side-by-side metric scorecards & normalized 24-hour overlaid dual-line chart | M4 | Dashboard Survey |
| 33 | Backup Management UI | Dashboard section to view backup logs, trigger manual backups, and download CSV/JSON files | M4 | Dashboard Survey |
| 34 | Settings Configuration Modal | UI modal/form to inspect and update tank height, offset, capacity, and warning thresholds | M4 | Dashboard Survey |
| 35 | ESP32 NodeMCU Firmware Architecture | Clean C++/Arduino firmware modularized into main sketch, config, filtering, and math | M5 | Firmware Survey |
| 36 | Ultrasonic Sensor Driver | Driver for HC-SR04 / JSN-SR04T with precise microsecond timing and timeout safety | M5 | Firmware Survey |
| 37 | 5-Stage Digital Noise Filtering | Burst sampling (N=9), median filter, delta outlier rejection, EMA smoothing | M5 | Firmware Survey |
| 38 | Geometric Level & Volume Math | Calculations for water level (cm), percentage (0-100%), and litres based on tank geometry | M5 | Firmware Survey |
| 39 | Non-Blocking Wi-Fi State Machine | Robust Wi-Fi connection handling with exponential backoff reconnection | M5 | Firmware Survey |
| 40 | HTTPS POST Client with Retry Queue | Telemetry transmission with dual API key, JSON serialization, and 20-sample retry ring buffer | M5 | Firmware Survey |
| 41 | Strict Monitoring Safety Guarantee | Zero pump, motor, or relay control pins/logic (strictly monitoring only) | M5 | Firmware Survey |
| 42 | Configurable Firmware Parameters | Centralized configuration for Wi-Fi credentials, API URL, device_id, api_key, tank dimensions | M5 | Firmware Survey |
| 43 | 100% E2E Test Suite Pass | Verification against full opaque-box E2E test suite (Tiers 1-4) | M6 | Orchestrator Plan |
| 44 | Tier 5 Adversarial Coverage Hardening | Challenger-driven white-box testing & gap remediation | M6 | Orchestrator Plan |

---

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Database & Core Storage Subsystem | SQLite schema, indexing, idempotent DB initializer, CRUD helper | none | DONE |
| M2 | Flask Backend REST API & Authentication | Ingestion endpoint, validation, auth, device tracking, analytics & settings APIs | M1 | DONE |
| M3 | Backup Subsystem & Deployment Package | Standalone `backup.py` CLI, backup REST APIs, WSGI config, requirements, deployment guide | M1, M2 | PLANNED |
| M4 | Web Dashboard & Interactive Analytics UI | Responsive UI, SVG tank visualizer with 4 color states, Chart.js analytics, backup UI | M2, M3 | PLANNED |
| M5 | ESP32 Firmware Source & Compilation | C++/Arduino firmware, sensor filter, volumetric math, Wi-Fi retry queue, compile verification | M2 | PLANNED |
| M6 | E2E Test Verification & Adversarial Hardening | Phase 1: Pass 100% E2E suite (Tiers 1-4); Phase 2: Tier 5 adversarial coverage hardening | M1-M5, TEST_READY.md | PLANNED |

---

## Dual Track: E2E Testing Track
Runs in parallel with implementation milestones. Derives test cases independently from `ORIGINAL_REQUEST.md`.
- Test harness & runner (`tests/e2e/test_runner.py`)
- Simulated ESP32 telemetry client (`scripts/simulate_esp32.py`)
- Tier 1: Feature Coverage (>=5 tests per feature)
- Tier 2: Boundary & Corner Cases (>=5 tests per boundary feature)
- Tier 3: Cross-Feature Interactions (pairwise combinations)
- Tier 4: Real-World Application Scenarios (realistic workloads)
- Publishes `TEST_READY.md` upon completion.

---

## Interface Contracts

### 1. ESP32 Firmware ↔ Backend Ingestion API (`POST /api/water-level`)
- **URL**: `POST /api/water-level`
- **Headers**:
  - `Content-Type: application/json`
  - `X-API-Key: <device_api_key>` (optional if present in JSON body)
- **JSON Payload**:
  ```json
  {
    "device_id": "esp32_tank_01",
    "distance_cm": 45.2,
    "water_level_cm": 154.8,
    "water_percentage": 77.4,
    "water_litres": 774.0,
    "api_key": "secret_key_here"
  }
  ```
- **Validation Rules**:
  - `device_id`: string, 1-64 chars, exists in `devices` table or auto-registered if valid key.
  - `distance_cm`: numeric, >= 0.0
  - `water_level_cm`: numeric, >= 0.0
  - `water_percentage`: numeric, 0.0 to 100.0
  - `water_litres`: numeric, >= 0.0
- **Responses**:
  - `201 Created`: `{"status": "success", "reading_id": 123, "timestamp": "2026-11-06T14:40:00Z"}`
  - `400 Bad Request`: `{"error": "Invalid JSON or missing fields"}`
  - `401 Unauthorized`: `{"error": "Invalid or missing API key"}`
  - `422 Unprocessable Entity`: `{"error": "Validation failed", "details": {"water_percentage": "Must be between 0 and 100"}}`

### 2. Frontend ↔ Current Status API (`GET /api/water-level/current`)
- **URL**: `GET /api/water-level/current?device_id=esp32_tank_01`
- **Response `200 OK`**:
  ```json
  {
    "device": {
      "device_id": "esp32_tank_01",
      "device_name": "Main Water Tank",
      "status": "online",
      "last_seen": "2026-11-06T14:40:00Z",
      "seconds_since_last_seen": 15
    },
    "tank": {
      "total_height_cm": 200.0,
      "sensor_offset_cm": 15.0,
      "total_capacity_litres": 1000.0,
      "warning_low_percent": 20.0,
      "warning_normal_percent": 50.0
    },
    "reading": {
      "id": 123,
      "timestamp": "2026-11-06T14:40:00Z",
      "distance_cm": 45.2,
      "water_level_cm": 154.8,
      "water_percentage": 77.4,
      "water_litres": 774.0,
      "remaining_litres": 226.0,
      "level_state": "normal"
    },
    "today_summary": {
      "date": "2026-11-06",
      "reading_count": 48,
      "min_level_cm": 120.0,
      "max_level_cm": 160.0,
      "avg_level_cm": 145.2,
      "min_percentage": 60.0,
      "max_percentage": 80.0,
      "avg_percentage": 72.6,
      "min_litres": 600.0,
      "max_litres": 800.0,
      "avg_litres": 726.0,
      "net_change_litres": 34.0
    }
  }
  ```

### 3. Frontend ↔ 15-Day Historical Daily Aggregates (`GET /api/history/daily-stats`)
- **URL**: `GET /api/history/daily-stats?days=15`
- **Response `200 OK`**:
  ```json
  {
    "days_requested": 15,
    "daily_stats": [
      {
        "date": "2026-11-06",
        "reading_count": 52,
        "min_percentage": 60.0,
        "max_percentage": 80.0,
        "avg_percentage": 72.6,
        "min_litres": 600.0,
        "max_litres": 800.0,
        "avg_litres": 726.0
      }
    ]
  }
  ```

### 4. Frontend ↔ Intraday Date Readings (`GET /api/history/readings`)
- **URL**: `GET /api/history/readings?date=YYYY-MM-DD`
- **Response `200 OK`**:
  ```json
  {
    "date": "2026-11-06",
    "reading_count": 144,
    "summary": { "min_percentage": 60.0, "max_percentage": 80.0, "avg_percentage": 72.6 },
    "readings": [
      { "id": 1, "timestamp": "2026-11-06T00:00:00Z", "water_percentage": 65.0, "water_litres": 650.0, "water_level_cm": 130.0 }
    ]
  }
  ```

### 5. Frontend ↔ Day Comparison (`GET /api/history/compare`)
- **URL**: `GET /api/history/compare?date1=YYYY-MM-DD&date2=YYYY-MM-DD`
- **Response `200 OK`**:
  ```json
  {
    "date1": { "date": "2026-11-05", "summary": {...}, "readings_count": 140 },
    "date2": { "date": "2026-11-06", "summary": {...}, "readings_count": 144 },
    "comparison": {
      "avg_percentage_diff": 4.2,
      "avg_litres_diff": 42.0,
      "max_litres_diff": 30.0
    }
  }
  ```

### 6. Standalone Backup Runner ↔ Database & Filesystem (`scripts/backup.py`)
- **CLI Invocations**:
  - `python scripts/backup.py --format both --retention-days 30`
  - `python scripts/backup.py --format json`
  - `python scripts/backup.py --format csv`
- **Exit Codes**:
  - `0`: Success (backup file created and logged to `backup_logs`)
  - `1`: Failure (error written to stderr and logged to `backup_logs` with status `FAILED`)

---

## Code Layout
```
c:\Users\IDEAL\Documents\ANtigravity\water_leveler\
├── .agents/                      # Multi-agent coordination metadata
├── app/                          # Flask application package
│   ├── __init__.py               # App factory (create_app)
│   ├── config.py                 # Configuration with absolute path resolution
│   ├── database.py               # SQLite connection & schema helpers
│   ├── models.py                 # Database access functions & queries
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── api.py                # Sensor ingestion & telemetry REST endpoints
│   │   ├── backup_routes.py      # Backup trigger, list, and download endpoints
│   │   └── views.py              # Dashboard HTML view route
│   ├── static/
│   │   ├── css/
│   │   │   └── style.css         # Dashboard responsive styles & animations
│   │   └── js/
│   │       ├── dashboard.js      # Main dashboard & polling controller
│   │       ├── tank_visualizer.js # Dynamic SVG tank graphic & color controller
│   │       └── analytics.js      # 15-day history & Chart.js integration
│   └── templates/
│       └── index.html            # Single-page responsive dashboard template
├── firmware/
│   └── esp32_water_leveler/
│       ├── esp32_water_leveler.ino # Main Arduino/ESP32 sketch
│       ├── config.h              # Centralized hardware & network config
│       ├── sensor_filter.h       # 5-stage digital filter declaration
│       ├── sensor_filter.cpp     # Median filter & EMA smoothing
│       ├── tank_math.h           # Geometry & volumetric math declaration
│       └── tank_math.cpp         # Percentage & litres calculation
├── scripts/
│   ├── init_db.py                # Database initializer & seed script
│   ├── backup.py                 # Standalone daily backup runner
│   └── simulate_esp32.py         # ESP32 telemetry simulator for testing
├── tests/
│   └── e2e/
│       ├── test_runner.py        # E2E test runner
│       ├── test_tier1_features.py
│       ├── test_tier2_boundaries.py
│       ├── test_tier3_interactions.py
│       └── test_tier4_workloads.py
├── backups/                      # Dedicated persistent backup storage
├── data/                         # SQLite database storage directory
├── wsgi.py                       # PythonAnywhere WSGI entrypoint
├── requirements.txt              # Pinned Python dependencies
├── DEPLOYMENT.md                 # PythonAnywhere step-by-step deployment guide
└── PROJECT.md                    # Single source of truth index
```

