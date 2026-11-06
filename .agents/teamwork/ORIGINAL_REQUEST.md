# Original User Request

## Approved Task Prompt — 2026-11-06T14:32:49Z

Develop a complete IoT-based Smart Water Tank Level Monitoring System using an ESP32 NodeMCU microcontroller and a Python Flask web application to monitor water levels automatically and display real-time and historical water-level information through a web application, deployable on PythonAnywhere.

Working directory: c:\Users\IDEAL\Documents\ANtigravity\water_leveler
Integrity mode: development

## Requirements

### R1. ESP32 Sensor Measurement and Firmware
Develop ESP32 NodeMCU firmware that reads a water-level measurement sensor (ultrasonic or compatible) at configurable intervals, calculates water level in centimetres, water level percentage, and water quantity in litres based on configured tank dimensions, and transmits readings to the backend API over Wi-Fi via HTTP POST requests with automatic retry on failure. The system is strictly for monitoring and must not control pumps or motors.

### R2. Flask Backend API and Database Storage
Develop a lightweight Python 3 Flask backend using SQLite (`water_readings`, `devices`, `tank_settings`, `backup_logs` tables with appropriate date indexing) deployable on PythonAnywhere. Provide endpoints (including `POST /api/water-level`) protected by a device API key, validating incoming readings and rejecting invalid or impossible values. Track device status (online/offline based on configurable timeout) and last communication timestamps.

### R3. Web Dashboard and Level Visualization
Provide a clean, modern, responsive web dashboard (HTML5, CSS3, JavaScript) displaying current water percentage, volume in litres, tank capacity, remaining capacity, last sensor update time, device connection status, and today's summary. Include a graphical tank visualization that fills dynamically with color indications (green for normal, orange for low, red for critically low, blue for water fill) and updates automatically when new readings arrive.

### R4. 15-Day History and Analytics
Maintain historical water-level data for at least 15 days. Provide history and analytics views enabling users to inspect today's and yesterday's readings, select any date within the past 15 days, compare water levels across days, view minimum/maximum/average stats, and display water-level trends using Chart.js interactive line charts.

### R5. Automated Daily Backup System
Implement an automated daily backup system for SQLite records exportable to CSV or JSON, compatible with PythonAnywhere scheduled tasks without relying on always-running background daemons. Store backups in a dedicated local backup directory on PythonAnywhere ensuring records persist across server restarts, and provide a manual backup download option from the dashboard.

### R6. PythonAnywhere Deployment Package
Provide a complete deployment package for PythonAnywhere, including Flask WSGI configuration, SQLite database setup and initialization script, `requirements.txt`, static CSS/JS assets, and step-by-step deployment instructions using the deployed HTTPS domain.

## Acceptance Criteria

### Sensor Data Ingestion & API
- [ ] API endpoint `POST /api/water-level` accepts valid JSON payloads containing device_id, distance_cm, water_level_cm, water_percentage, and water_litres when authenticated with a valid API key.
- [ ] Backend validates sensor readings, rejects invalid/out-of-range values and unauthorized requests, and timestamps accepted readings.
- [ ] Automated test script simulates ESP32 HTTP POST payloads against the API and verifies successful ingestion and error rejection.
- [ ] ESP32 firmware source code compiles cleanly without syntax errors and implements Wi-Fi reconnection and transmission retry logic.

### Database & Historical Retention
- [ ] SQLite database schema includes `water_readings`, `devices`, `tank_settings`, and `backup_logs` tables with indexes on timestamp/date fields.
- [ ] Historical readings persist across application and server restarts.
- [ ] Querying records for any date within the previous 15 days returns timestamped readings and calculated daily min, max, and average levels.

### Dashboard & UI
- [ ] Dashboard displays current water level percentage, litres, total capacity, remaining empty capacity, last sensor update time, ESP32 connection status (online/offline), and today's summary.
- [ ] Graphical tank visualization displays current fill level with color indicators (green for normal, orange for low, red for critically low, blue for water fill).
- [ ] Analytics and History sections render interactive Chart.js line charts with date filtering and day-to-day comparison.
- [ ] Dashboard layout is responsive across mobile, tablet, and desktop viewports.

### Backup System
- [ ] Daily backup script executes standalone as a PythonAnywhere scheduled task and generates exportable CSV or JSON backup files in a dedicated backup directory.
- [ ] Dashboard backup section displays backup logs and provides an option to manually trigger and download backups.

### PythonAnywhere Readiness
- [ ] Project includes WSGI configuration, requirements.txt, database initialization script, and deployment documentation.

## Follow-up — 2026-11-06T15:23:40Z

https://github.com/laxminivas06/waterlevel_sphn.git
make sure push all this to this

