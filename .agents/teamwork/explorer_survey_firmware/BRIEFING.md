# BRIEFING — 2026-11-06T14:39:30Z

## Mission
Investigate and produce comprehensive technical survey, architectural recommendations, and firmware specifications for R1 (ESP32 Sensor Measurement and Firmware).

## 🔒 My Identity
- Archetype: explorer
- Roles: Firmware & Sensor Explorer
- Working directory: c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\explorer_survey_firmware\
- Original parent: e67aac6c-272b-4420-b5de-866caa2cc5fb
- Milestone: Survey & Specifications

## 🔒 Key Constraints
- Read-only investigation — do NOT implement production firmware in root yet
- Strictly monitoring only — absolutely NO motor, pump, or relay control logic
- API endpoint payload compatibility with Flask backend (POST /api/water-level)
- Ultrasonic sensor noise filtering and outlier rejection
- All agent metadata in .agents/teamwork/explorer_survey_firmware/ only

## Current Parent
- Conversation ID: e67aac6c-272b-4420-b5de-866caa2cc5fb
- Updated: 2026-11-06T14:39:30Z

## Investigation State
- **Explored paths**:
  - `c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\ORIGINAL_REQUEST.md`
  - Workspace root directory files and directories
  - `c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\spec_miner_survey_backend\DISPATCH.md`
  - `c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\explorer_survey_dashboard\DISPATCH.md`
  - Toolchain binaries: `C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe`
- **Key findings**:
  - Workspace root is greenfield (only `.agents/teamwork/` metadata present).
  - ESP32 toolchain is already present on host: `esp32:esp32 3.3.11`, `arduino:esp32 2.0.18-arduino.5`, and `ArduinoJson 7.4.3`.
  - Backend API contract expects `POST /api/water-level` with `device_id`, `distance_cm`, `water_level_cm`, `water_percentage`, `water_litres`, authenticated via `X-API-Key` and/or payload `api_key`.
  - JSN-SR04T has a 20cm blind zone requiring physical offset mounting ($H_{offset} \ge 20\,\text{cm}$).
  - 5-stage filter architecture (Burst sampling -> Range check -> Median filter -> Delta outlier pruning -> EMA) eliminates acoustic reverberation and dropout noise.
- **Unexplored areas**: None within survey scope. Ready for handoff.

## Key Decisions Made
- Confirmed strictly monitoring-only architecture: zero pin assignments or code logic for relays, motors, or pumps.
- Selected JSN-SR04T as primary recommendation for water resistance, while maintaining drop-in compatibility with HC-SR04.
- Specified 1kΩ / 2kΩ voltage divider on Echo pin to step 5.0V echo pulses safely down to 3.33V for ESP32 GPIO 18.
- Specified dual-path API key transmission (HTTP Header `X-API-Key` and JSON body `api_key`) to guarantee 100% backend compatibility.
- Designed non-blocking Wi-Fi state machine with exponential backoff (5s to 60s) and an in-memory 20-sample circular retry queue.
- Recommended `WiFiClientSecure.setInsecure()` for PythonAnywhere HTTPS compatibility without large root certificate bundle overhead.

## Artifact Index
- `c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\explorer_survey_firmware\survey.md` — Comprehensive technical survey & architectural specifications
- `c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\explorer_survey_firmware\handoff.md` — 5-component handoff report
- `c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\explorer_survey_firmware\progress.md` — Progress and heartbeat tracking
- `c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\explorer_survey_firmware\DISPATCH.md` — Task dispatch log
