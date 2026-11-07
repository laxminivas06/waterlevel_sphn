# HydroSense IoT – Smart Water Tank Monitoring System v2.0

![HydroSense IoT System](https://img.shields.io/badge/HydroSense-IoT_v2.0-0ea5e9.svg)
![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.1-emerald.svg)
![Microcontroller](https://img.shields.io/badge/Hardware-ESP8266%20%7C%20ESP32-red.svg)
![Platform](https://img.shields.io/badge/Deploy-PythonAnywhere-indigo.svg)
![Tests](https://img.shields.io/badge/Tests-19%2F19%20Passing-brightgreen.svg)

HydroSense IoT is an enterprise-grade, full-stack Internet of Things (IoT) water tank telemetry and SCADA monitoring platform. Designed for residential, institutional, and industrial multi-tank installations, it receives real-time ultrasonic depth measurements from ESP8266 NodeMCU and ESP32 microcontrollers, computes precise volumetric water levels, maintains 15+ days of analytics, triggers automated operational alerts (Critical Low, Overflow Risk, Sensor Fault, Device Disconnected), and presents a fluid SCADA dashboard.

---

## 1. System Architecture

```
                                    +-----------------------------------------+
                                    |         Ultrasonic Sensors              |
                                    |    (HC-SR04 / JSN-SR04T Waterproof)     |
                                    +--------------------+--------------------+
                                                         | 10µs Trigger / Echo
                                    +--------------------v--------------------+
                                    |   Microcontroller Firmware (v2.0)       |
                                    |   - ESP8266 NodeMCU (ESP-12E/F)         |
                                    |   - ESP32 (WROOM-32 / NodeMCU-32S)      |
                                    |   - 5-Sample Median Noise Filter        |
                                    |   - Non-blocking Wi-Fi Reconnection     |
                                    +--------------------+--------------------+
                                                         |
                                                         | HTTPS POST (JSON)
                                                         | BearSSL / TLS 1.3
                                                         v
                  +-------------------------------------------------------------------------+
                  |               PythonAnywhere Cloud Backend (Flask 3.1)                  |
                  |             https://waterlevelersphn.pythonanywhere.com                 |
                  |                                                                         |
                  |  +--------------------+  +-----------------------+  +----------------+  |
                  |  |  REST API v1 Core  |  | Volumetric Physics    |  | Token Auth &   |  |
                  |  |  /api/v1/telemetry |  | Cylinder & Rectangle  |  | Rate Limiting  |  |
                  |  +---------+----------+  +-----------+-----------+  +-------+--------+  |
                  +------------|-------------------------|----------------------|-----------+
                               |                         |                      |
                               v                         v                      v
                  +-------------------------------------------------------------------------+
                  |                  Relational SQLite Database (WAL Mode)                  |
                  |  - users        - tanks        - devices                                |
                  |  - telemetry    - alerts       - backup_records                         |
                  +-------------------------------------------------------------------------+
                                                         |
                                 +-----------------------+-----------------------+
                                 |                                               |
                                 v                                               v
                  +-------------------------------+               +-------------------------------+
                  |  Single-Page SCADA Dashboard  |               |  Automated Backup Engine      |
                  |  - React 18 & Tailwind CSS    |               |  - Daily JSON & CSV Snapshots |
                  |  - Dual Sinusoidal Wave Tank  |               |  - 30-Day Auto Retention      |
                  |  - Chart.js 15-Day Analytics  |               |  - Zero-Daemon Scheduled Task |
                  |  - Multi-Tank & Device Admin  |               +-------------------------------+
                  +-------------------------------+
```

---

## 2. Water Level Physics & Volumetric Engine

The system strictly avoids hardcoded or fabricated readings. Every percentage, volume, and depth metric is derived from physical sensor geometry.

### 2.1 Geometry Model
* $H_{tank}$: Internal physical height of the tank from bottom to full water line (cm).
* $d_{offset}$: Sensor offset gap above the 100% full water mark (cm).
* $d_{meas}$: Ultrasonic distance measured from transducer face to water surface (cm).
* $C_{total}$: Configured total storage capacity in Litres.

```
       [ Ultrasonic Sensor ] ───┬─── Top of mounting bracket
                 │              │
                 │ d_offset     │
                 ▼              │
    ═════ 100% Full Line ═══════╡
    │                           │
    │ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ┤ ◄── Water Surface (Air Gap = d_meas - d_offset)
    │                           │
    │        Water Depth        │ H_tank
    │         (h_water)         │
    │                           │
    │                           │
    └───────────────────────────┴─── Tank Floor
```

### 2.2 Mathematical Formulas

$$\text{Effective Air Gap} = \max\left(0,\, d_{meas} - d_{offset}\right)$$

$$h_{water} = \text{clamp}\left(0,\, H_{tank},\, H_{tank} - \text{Effective Air Gap}\right)$$

$$\text{Water Percentage (\%)} = \left(\frac{h_{water}}{H_{tank}}\right) \times 100$$

### 2.3 Tank Shape Support
1. **Cylindrical Tanks**:
   $$V = \min\left(C_{total},\, \frac{\pi \cdot r^2 \cdot h_{water}}{1000}\right) \quad [\text{Litres}]$$
2. **Rectangular Tanks**:
   $$V = \min\left(C_{total},\, \frac{L \times W \times h_{water}}{1000}\right) \quad [\text{Litres}]$$
3. **General / Custom Shape**:
   $$V = \left(\frac{\text{Water Percentage}}{100}\right) \times C_{total} \quad [\text{Litres}]$$

### 2.4 Overload vs Full Tank Physics
* **Full Tank ($100\%$)**: Water level reaches the safe full mark ($d_{meas} = d_{offset}$). Status is `HIGH`.
* **Overloaded Tank**: Water exceeds the full line and rises into the sensor offset buffer zone ($d_{meas} < d_{offset}$). The system classifies this as `OVERLOADED`, flags `is_overloaded = true`, and triggers an immediate `OVERFLOW_RISK` operational alert.
* **Sensor Fault**: Measured distance exceeds physical bounds ($d_{meas} > H_{tank} + d_{offset} + 100\text{ cm}$) or reading is disconnected ($d_{meas} \le 0$).

---

## 3. Operational Statuses & Automated Alerts

| Status | Water Level Range | SCADA Badge Color | Automated Event |
| :--- | :--- | :--- | :--- |
| **OVERLOADED** | $d_{meas} < d_{offset}$ or overflow | Crimson Alert (`#dc2626`) | Triggers `OVERFLOW_RISK` critical alarm |
| **CRITICAL LOW** | $0\% - 10\%$ | Rose Red (`#ef4444`) | Triggers `CRITICAL_LOW` alarm (pump dry-run prevention) |
| **LOW** | $10\% - 25\%$ | Amber Orange (`#f59e0b`) | Warning notification on dashboard |
| **NORMAL** | $25\% - 85\%$ | Emerald Green (`#10b981`) | Normal operating state |
| **HIGH** | $85\% - 100\%$ | Violet Blue (`#8b5cf6`) | Optimal storage capacity reached |
| **SENSOR FAULT** | Out of bounds / disconnected | Muted Slate (`#94a3b8`) | Triggers `SENSOR_FAULT` system alert |
| **DEVICE OFFLINE** | No telemetry within timeout | Warning Orange (`#f97316`) | Triggers `DEVICE_OFFLINE` system alert |

---

## 4. Hardware Wiring & Pinout Guide

### 4.1 ESP8266 NodeMCU (Amica / CP2102 / CH340)

> [!IMPORTANT]
> The HC-SR04 Echo pin outputs 5V TTL. The ESP8266 GPIO pins are 3.3V logic. Use a 1kΩ / 2kΩ resistor voltage divider on the Echo line to protect the ESP8266 pin. The waterproof JSN-SR04T 3.3V edition can be wired directly.

```
       ESP8266 NodeMCU                   HC-SR04 / JSN-SR04T
       +---------------+                 +-----------------+
       |           VIN | ──────────────> | VCC (5V DC)     |
       |           GND | ──────────────> | GND             |
       |     D6 (GPIO12)| ──────────────> | TRIG            |
       |               |                 |                 |
       |     D5 (GPIO14)| <──[ 1kΩ ]───── | ECHO            |
       |               |        │        +-----------------+
       |               |      [ 2kΩ ]
       |               |        │
       |           GND | ───────┴────────
       +---------------+
```

### 4.2 ESP32 (WROOM-32 / NodeMCU-32S)

```
       ESP32 NodeMCU                     HC-SR04 / JSN-SR04T
       +---------------+                 +-----------------+
       |            5V | ──────────────> | VCC (5V DC)     |
       |           GND | ──────────────> | GND             |
       |       GPIO 12 | ──────────────> | TRIG            |
       |       GPIO 14 | <──[ 1kΩ ]───── | ECHO            |
       |               |        │        +-----------------+
       |               |      [ 2kΩ ]
       |               |        │
       |           GND | ───────┴────────
       +---------------+
```

---

## 5. Microcontroller Firmware Setup

Firmware is located in:
* `firmware/esp8266_nodemcu_water_leveler/esp8266_nodemcu_water_leveler.ino` (ESP8266 NodeMCU & ESP32 dual-compatible)
* `firmware/esp32_sv_tank/esp32_sv_tank.ino` (Direct ESP32 sketch)

### 5.1 Required Arduino Libraries
1. `ESP8266WiFi` (Built-in with ESP8266 Board Package by ESP8266 Community)
2. `ESP8266HTTPClient` (Built-in)
3. `WiFiClientSecureBearSSL` (Built-in)

### 5.2 Board Manager URLs (Arduino IDE)
* **ESP8266**: `http://arduino.esp8266.com/stable/package_esp8266com_index.json`
* **ESP32**: `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`

### 5.3 Firmware Configuration Checklist
Open `firmware/esp8266_nodemcu_water_leveler/esp8266_nodemcu_water_leveler.ino` and update the user configuration block:

```cpp
// --- Wi-Fi Network Credentials ---
const char* WIFI_SSID           = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD       = "YOUR_WIFI_PASSWORD";

// --- Backend API Configuration ---
const char* API_URL             = "https://waterlevelersphn.pythonanywhere.com/api/v1/telemetry";
const char* DEVICE_ID           = "SV_BLOCK_OVER_TANK";
const char* API_KEY             = "water_secret_key_2026";

// --- Tank Physical Dimensions (cm) ---
const float TANK_HEIGHT_CM      = 200.0f;  // Internal height
const float SENSOR_OFFSET_CM    = 15.0f;   // Distance above 100% full mark
const float TANK_CAPACITY_L     = 1000.0f; // Litres

// --- Telemetry Timing ---
const unsigned long SEND_INTERVAL_MS = 10000UL; // 10 seconds
```

---

## 6. Complete REST API v1 Reference

All endpoints return JSON and use standard HTTP response codes (`200`, `201`, `400`, `401`, `404`, `500`).

### 6.1 Telemetry Ingestion
* **Endpoint**: `POST /api/v1/telemetry`
* **Headers**: `Content-Type: application/json`, `X-API-Key: <token>` (or `Authorization: Bearer <token>`)
* **Request Body**:
  ```json
  {
    "device_id": "SV_BLOCK_OVER_TANK",
    "distance_cm": 65.5,
    "water_level_percent": 74.75,
    "water_volume_litres": 747.5,
    "status": "NORMAL"
  }
  ```
* **Success Response (`201 Created`)**:
  ```json
  {
    "status": "success",
    "success": true,
    "reading": {
      "id": 142,
      "device_id": "SV_BLOCK_OVER_TANK",
      "tank_id": "SV_BLOCK_OVER_TANK",
      "distance_cm": 65.5,
      "water_height_cm": 149.5,
      "water_level_percent": 74.75,
      "water_volume_litres": 747.5,
      "status": "NORMAL",
      "timestamp": "2026-11-07 21:56:48"
    }
  }
  ```

### 6.2 Tank Management
* **List Tanks**: `GET /api/v1/tanks` — Returns all tanks enriched with latest volume, fill %, online/offline state, and remaining empty litres.
* **Create Tank**: `POST /api/v1/tanks` — Create or update tank geometry:
  ```json
  {
    "tank_id": "GROUND_SUMP_02",
    "tank_name": "East Wing Sump",
    "shape": "rectangle",
    "tank_height_cm": 180.0,
    "sensor_offset_cm": 12.0,
    "total_capacity_litres": 2500.0,
    "length_cm": 150.0,
    "width_cm": 100.0
  }
  ```
* **Get Tank Detail**: `GET /api/v1/tanks/{tank_id}`
* **Get Latest Telemetry**: `GET /api/v1/tanks/{tank_id}/latest`
* **Delete Tank**: `DELETE /api/v1/tanks/{tank_id}`

### 6.3 Historical Analytics
* **Endpoint**: `GET /api/v1/tanks/{tank_id}/history`
* **Query Parameters**:
  * `range`: `24h` (default), `7d`, `15d`, `custom`
  * `start_date`: `YYYY-MM-DD` (for custom range)
  * `end_date`: `YYYY-MM-DD`
  * `limit`: max points (default 500)
* **Response**:
  ```json
  {
    "tank_id": "SV_BLOCK_OVER_TANK",
    "range": "15d",
    "count": 1280,
    "analytics": {
      "min_level_percent": 18.2,
      "max_level_percent": 96.4,
      "avg_level_percent": 68.7,
      "min_volume": 182.0,
      "max_volume": 964.0,
      "avg_volume": 687.0,
      "net_volume_change": -45.0,
      "estimated_consumption_litres": 1420.5
    },
    "readings": [ ... ]
  }
  ```

### 6.4 Device Management
* **List Devices**: `GET /api/v1/devices` — Lists microcontrollers with dynamic online/offline calculation based on last heartbeat.
* **Register Device**: `POST /api/v1/devices`:
  ```json
  {
    "device_id": "SV_BLOCK_OVER_TANK",
    "device_name": "SV Block Overhead Sensor",
    "tank_id": "SV_BLOCK_OVER_TANK",
    "api_key": "water_secret_key_2026",
    "firmware_version": "2.1.0"
  }
  ```

### 6.5 System Alerts
* **List Active Alerts**: `GET /api/v1/alerts?unacknowledged=true`
* **Acknowledge Alert**: `POST /api/v1/alerts/{alert_id}/ack`

### 6.6 KPI Summary & Simulator
* **System Summary**: `GET /api/v1/system/summary` — Returns 6-metric KPI scorecard (`total_tanks`, `online_devices`, `offline_devices`, `avg_water_level_percent`, `total_water_litres`, `critical_alerts_count`).
* **Manual Simulator**: `POST /api/v1/simulate` — Injects simulated readings via `water_level_percent` (slider) or `distance_cm` without physical hardware.
* **Health Probe**: `GET /api/v1/health` — Returns DB connection status and server timestamp.

### 6.7 Zero-Breakage Legacy Backward Compatibility
The backend maintains 100% backward compatibility with older hardware code:
* `GET /api/tanks?tanks=SV_BLOCK_OVER_TANK:181.0` (Old ESP8266 URL parameter format)
* `GET /api/water-level/current` & `GET /api/water-level/latest`
* `GET /api/water-level` & `POST /api/water-level`
* `GET /api/settings` & `PUT /api/settings`

---

## 7. PythonAnywhere Production Deployment

Follow this step-by-step procedure to deploy HydroSense IoT on PythonAnywhere (`waterlevelersphn.pythonanywhere.com`).

### Step 1: Clone Repository & Set Up Directory
Open a **Bash Console** in PythonAnywhere:
```bash
cd /home/waterlevelersphn
# Clone or pull your repository
git clone https://github.com/yourusername/waterlevel_sphn.git
cd /home/waterlevelersphn/waterlevel_sphn
```

### Step 2: Create Python 3.10+ Virtual Environment
```bash
mkvirtualenv --python=/usr/bin/python3.10 hydrosense_env
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 3: Initialize Database & Seed Tanks
```bash
python scripts/init_db.py --seed
```
This initializes `data/water_leveler.db` with all 6 tables and default tanks.

### Step 4: Configure WSGI File
Navigate to the **Web** tab in PythonAnywhere dashboard. Click on your WSGI configuration file (`/var/www/waterlevelersphn_pythonanywhere_com_wsgi.py`) and replace its contents with:

```python
import os
import sys

# Resilient directory auto-detection (handles waterlevel_sphn and waterleveler_sphn)
CANDIDATE_PATHS = [
    '/home/waterlevelersphn/waterlevel_sphn',
    '/home/waterlevelersphn/waterleveler_sphn',
]

project_home = next((p for p in CANDIDATE_PATHS if os.path.isdir(p)), CANDIDATE_PATHS[0])

if project_home not in sys.path:
    sys.path.insert(0, project_home)

os.chdir(project_home)

# Import the WSGI callable 'application'
from wsgi import application  # noqa
```

### Step 5: Configure Static Files Mapping
In the **Web** tab under **Static files**, configure:
* **URL**: `/static/`
* **Directory**: `/home/waterlevelersphn/waterlevel_sphn/app/static/`

### Step 6: Reload Web App
Click the green **Reload waterlevelersphn.pythonanywhere.com** button.
Visit `https://waterlevelersphn.pythonanywhere.com/api/v1/health` to confirm `status: "healthy"`.

---

## 8. Automated Backups & Data Retention

HydroSense IoT includes an automated backup subsystem that maintains compliance with the 15-day telemetry retention rule.

### 8.1 Manual Backup CLI
Run a manual snapshot anytime:
```bash
python scripts/backup.py --format both
```
Backups are saved to `backups/` and registered in the `backup_records` table.

### 8.2 Scheduled Daily Backup on PythonAnywhere
In the **Tasks** tab of PythonAnywhere, add a Daily Scheduled Task:
* **Hour**: `02:00` UTC
* **Command**:
  ```bash
  /home/waterlevelersphn/.virtualenvs/hydrosense_env/bin/python /home/waterlevelersphn/waterlevel_sphn/scripts/backup.py --format both
  ```
This takes a midnight snapshot and automatically prunes snapshots older than 30 days.

---

## 9. Verification & Automated Test Suite

HydroSense IoT includes a 19-point automated test suite verifying all 12 operational scenarios.

Run the test suite:
```bash
python -m unittest tests/test_hydrosense.py -v
```

### Test Suite Execution Output
```
test_alert_acknowledgement ... ok
test_critical_low_alert_generation ... ok
test_device_registration ... ok
test_health_check ... ok
test_history_retrieval_and_ranges ... ok
test_legacy_get_tanks ... ok
test_legacy_water_level_endpoints ... ok
test_overload_alert_generation ... ok
test_physics_cylindrical_tank ... ok
test_simulator_reading ... ok
test_system_summary ... ok
test_tank_creation_and_listing ... ok
test_telemetry_embedded_api_key ... ok
test_telemetry_missing_distance ... ok
test_telemetry_negative_distance ... ok
test_telemetry_success ... ok
test_telemetry_unauthorized_key ... ok
test_telemetry_unknown_device ... ok
test_wsgi_entrypoint ... ok

----------------------------------------------------------------------
Ran 19 tests in 0.846s

OK (19/19 Passing)
```

---

## 10. License & Safety Disclaimer

* **Strict Safety Design**: HydroSense IoT is engineered strictly for non-invasive sensing and monitoring. It contains zero electrical relay triggers or motor controls, eliminating the risk of accidental dry pump burning or valve failure.
* **License**: MIT License. Designed and maintained for production IoT telemetry.
