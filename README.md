# Smart Water Tank Level Monitoring System (HydroSense IoT)

A robust, full-stack IoT water level monitoring system designed for residential, commercial, and industrial tanks. Featuring an ESP32 NodeMCU microcontroller with ultrasonic sensing, a lightweight Flask REST backend deployable on PythonAnywhere, an interactive HTML5/SVG dynamic visualizer dashboard, and automated SQLite backup capabilities.

---

## Architecture Overview

```
+--------------------+        HTTP/HTTPS POST        +-----------------------------+
|   ESP32 NodeMCU    | ────────────────────────────> |   Flask Backend & SQLite    |
| (JSN-SR04T/HC-SR04)|   X-API-Key / Ingestion API   |  (REST APIs, Analytics DB)  |
+--------------------+                               +--------------┬--------------+
                                                                    │
                                                     +──────────────┴──────────────+
                                                     |    Responsive Web UI        |
                                                     | (SVG Fluid Tank, Chart.js)  |
                                                     +-----------------------------+
```

1. **IoT Firmware (`firmware/esp32_water_leveler/`)**:
   - Reads ultrasonic sensor (HC-SR04 / JSN-SR04T) with a 5-stage digital filter (burst sampling $N=9$, physical screening, statistical median filter, delta outlier rejection, and exponential moving average).
   - Computes distance, water level (cm), percentage ($0-100\%$), and volume (Litres).
   - Non-blocking Wi-Fi state machine with exponential backoff (5s–60s) and a 20-sample circular retry buffer.
   - Dual-path authentication (`X-API-Key` header and JSON body `api_key`).
   - **Strict Safety Guarantee**: Monitoring only; zero motor, pump, or relay control pins/circuits.

2. **Flask Backend & Storage (`app/`, `wsgi.py`)**:
   - Application factory pattern with blueprints for core APIs, views, and backups.
   - SQLite relational storage with indexed tables (`water_readings`, `devices`, `tank_settings`, `backup_logs`).
   - Ingestion (`POST /api/water-level`), Current status (`GET /api/water-level/current`), 15-day analytics (`GET /api/history/daily-stats`), intraday readings (`GET /api/history/readings`), day comparison (`GET /api/history/compare`), and tank settings (`GET/PUT /api/settings`).

3. **Web Dashboard (`app/templates/index.html`, `app/static/`)**:
   - Zero-build vanilla HTML5, CSS3, and modern JavaScript.
   - SVG animated tank visualization with dynamic liquid level, dual sinusoidal wave motion, and 4 color states (Green >50%, Orange 20-50%, Red <20%, Blue for filling).
   - Live telemetry cards, Today's Summary scorecard, 15-day historical trend line charts (Chart.js), and side-by-side day comparison.
   - Resilient polling engine with Page Visibility API throttling (3s active / 30s background).

4. **Automated Backup Subsystem (`scripts/backup.py`, `app/routes/backup_routes.py`)**:
   - Standalone CLI runner executable via scheduled tasks without persistent daemons.
   - Dual-format export (JSON and CSV) stored in `backups/`.
   - 30-day automated retention rotation and DB audit logging.
   - Manual backup creation and secure browser download endpoints.

---

## Project Structure

```
water_leveler/
├── app/
│   ├── routes/
│   │   ├── api.py               # Telemetry ingestion, history & settings APIs
│   │   ├── backup_routes.py     # Backup creation, listing & download APIs
│   │   └── views.py             # Dashboard view route
│   ├── static/
│   │   ├── css/style.css        # Responsive dashboard styling & wave animations
│   │   └── js/
│   │       ├── analytics.js     # Chart.js graphs, date picker & comparison
│   │       ├── dashboard.js     # Live poller, cards & settings manager
│   │       └── tank_visualizer.js # Dynamic SVG tank controller
│   ├── templates/
│   │   └── index.html           # Main dashboard template
│   ├── config.py                # Configuration classes (Dev, Test, Prod)
│   ├── database.py              # SQLite connection lifecycle & thread safety
│   ├── models.py                # Data access layer & parameterized queries
│   └── __init__.py              # Flask application factory
├── firmware/
│   └── esp32_water_leveler/
│       ├── config.h             # Wi-Fi, API URL, sensor pins & tank dimensions
│       ├── esp32_water_leveler.ino # Main Arduino sketch & Wi-Fi state machine
│       ├── sensor_filter.h      # 5-stage digital filter declaration
│       ├── sensor_filter.cpp    # Median, outlier pruning & EMA filter logic
│       ├── tank_math.h          # Tank geometry math declaration
│       └── tank_math.cpp        # Volumetric and fill percentage algorithms
├── scripts/
│   ├── backup.py                # Standalone backup CLI (JSON/CSV exports)
│   ├── init_db.py               # Idempotent DB schema creator & seeder
│   └── simulate_esp32.py        # ESP32 telemetry simulator CLI
├── backups/                     # Persistent backup export directory
├── data/                        # SQLite storage directory
├── requirements.txt             # Pinned Python dependencies
├── wsgi.py                      # WSGI entrypoint for PythonAnywhere & local dev
└── README.md
```

---

## Quickstart Guide

### 1. Requirements & Installation
Python 3.10+ recommended:
```bash
pip install -r requirements.txt
```

### 2. Initialize Database
Initialize the SQLite schema and seed factory settings:
```bash
python scripts/init_db.py --seed
```

### 3. Run the Web Application
```bash
python wsgi.py
```
Open your browser and navigate to:
```
http://127.0.0.1:5000/
```

### 4. Simulate ESP32 Telemetry
In a separate terminal, simulate sensor readings from an ESP32:
```bash
# Send 5 readings with auto-calculated tank physics
python scripts/simulate_esp32.py --count 5 --auto-calc

# Run continuous simulation with realistic sensor jitter
python scripts/simulate_esp32.py --continuous --interval 3.0 --auto-calc --variance 2.0
```

### 5. Create Standalone Backups
```bash
python scripts/backup.py --format both
```

---

## ESP32 Hardware & Flashing

- **Microcontroller**: ESP32 NodeMCU (WROOM-32 / 32S)
- **Ultrasonic Sensor**: JSN-SR04T (waterproof) or HC-SR04
- **Pinout**:
  - `GPIO 5` -> Sensor TRIG
  - `GPIO 18` <- Sensor ECHO (via 1kΩ / 2kΩ voltage divider to protect 3.3V GPIO)
  - `GPIO 2` -> Built-in diagnostic status LED
- **Compilation**:
  Configure your Wi-Fi credentials in `firmware/esp32_water_leveler/config.h`, then compile with Arduino IDE or Arduino CLI:
  ```bash
  arduino-cli compile --fqbn esp32:esp32:esp32 firmware/esp32_water_leveler
  ```
