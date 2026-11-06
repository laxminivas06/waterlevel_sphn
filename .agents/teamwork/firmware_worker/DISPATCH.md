## 2026-11-06T15:40:48Z
You are firmware_worker, a Worker subagent responsible for implementing Milestone M5 (ESP32 Firmware Source & Compilation).
Your assigned working directory is: c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\firmware_worker\

MANDATORY FIRST STEP:
Read:
1. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\ORIGINAL_REQUEST.md
2. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\PROJECT.md
3. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\explorer_survey_firmware\survey.md
4. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\explorer_survey_firmware\handoff.md

EXCLUSIVE FILE OWNERSHIP:
All files inside c:\Users\IDEAL\Documents\ANtigravity\water_leveler\firmware\esp32_water_leveler\:
- esp32_water_leveler.ino
- config.h
- sensor_filter.h
- sensor_filter.cpp
- tank_math.h
- tank_math.cpp

REQUIREMENTS:
1. `config.h`:
   - Configurable Wi-Fi credentials (WIFI_SSID, WIFI_PASSWORD)
   - Backend API URL (`http://<SERVER_IP>:5000/api/water-level`)
   - Device credentials: `DEVICE_ID = "esp32_tank_01"`, `API_KEY = "water_secret_key_2026"`
   - Sensor pins: `PIN_TRIGGER = 5`, `PIN_ECHO = 18`
   - Reading interval: `TELEMETRY_INTERVAL_MS = 5000`
   - Tank geometry: `TANK_HEIGHT_CM = 200.0`, `SENSOR_OFFSET_CM = 15.0`, `TOTAL_CAPACITY_LITRES = 1000.0`
2. `sensor_filter.h` & `sensor_filter.cpp`:
   - 5-stage ultrasonic noise rejection:
     * Burst sampling N=9
     * Physical screening (reject out of range 2cm - 400cm)
     * Median filter to eliminate spikes
     * Delta-outlier rejection
     * Exponential Moving Average (EMA) smoothing ($\alpha = 0.35$)
3. `tank_math.h` & `tank_math.cpp`:
   - Calculates effective air gap, water_level_cm, water_percentage clamped to [0.0, 100.0]%, and water_litres based on tank geometry (rectangular or cylindrical).
4. `esp32_water_leveler.ino`:
   - Non-blocking Wi-Fi state machine with exponential backoff (5s to 60s) reconnection.
   - HTTP/HTTPS POST transmission to `/api/water-level` with dual-mode API key (HTTP header `X-API-Key` and JSON body `api_key`).
   - Circular retry queue (up to 20 readings) buffered when Wi-Fi is temporarily lost, flushed upon reconnection.
   - STRICT SAFETY GUARANTEE: Zero motor, pump, or relay control pins or functions (strictly monitoring only).
5. Compilation Verification:
   - Compile using `arduino-cli`:
     `& "C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe" compile --fqbn esp32:esp32:esp32 firmware/esp32_water_leveler`
   - Verify that compilation completes with exit code 0 and zero syntax errors.
6. Write `handoff.md` and send completion message to caller via send_message.
