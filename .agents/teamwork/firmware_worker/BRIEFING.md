# BRIEFING — 2026-11-06T15:42:00Z

## Mission
Implement Milestone M5: ESP32 Firmware Source & Compilation for IoT Water Level Monitoring. Complete modular firmware in `firmware/esp32_water_leveler/`, verify clean compilation with arduino-cli for ESP32 target, and document handoff.

## 🔒 My Identity
- Archetype: worker
- Roles: implementer, qa
- Working directory: c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\firmware_worker\
- Original parent: e67aac6c-272b-4420-b5de-866caa2cc5fb
- Milestone: M5

## 🔒 Key Constraints
- Exclusive file ownership: `firmware/esp32_water_leveler/*`
- STRICT SAFETY GUARANTEE: Zero motor, pump, or relay control pins or functions (strictly monitoring only).
- Configurable Wi-Fi, backend URL, device credentials, pins, intervals, geometry in `config.h`.
- 5-stage ultrasonic noise rejection in `sensor_filter`.
- Tank geometry math in `tank_math`.
- Non-blocking Wi-Fi state machine with backoff, HTTP/HTTPS POST transmission with dual-mode API key, circular retry queue (up to 20 readings) in `esp32_water_leveler.ino`.
- Compile verification using `arduino-cli` with `--fqbn esp32:esp32:esp32`.

## Current Parent
- Conversation ID: e67aac6c-272b-4420-b5de-866caa2cc5fb
- Updated: not yet

## Task Summary
- **What to build**: Production-grade ESP32 firmware for ultrasonic water level sensing with noise filtering, tank math, telemetry transmission, and offline buffering.
- **Success criteria**: Zero compilation errors under `arduino-cli compile --fqbn esp32:esp32:esp32 firmware/esp32_water_leveler`, all requirements met, clean architecture.
- **Interface contracts**: Backend POST `/api/water-level` JSON schema: `{ device_id, api_key, distance_cm, water_level_cm, water_percentage, water_litres, raw_distance_cm, wifi_rssi, uptime_sec }` (plus headers `Content-Type: application/json`, `X-API-Key`).
- **Code layout**: `firmware/esp32_water_leveler/`

## Key Decisions Made
- [TBD]

## Artifact Index
- `.agents/teamwork/firmware_worker/DISPATCH.md` — Dispatch requirements
- `.agents/teamwork/firmware_worker/progress.md` — Progress heartbeat
- `.agents/teamwork/firmware_worker/handoff.md` — Handoff report

## Change Tracker
- **Files modified**: None yet
- **Build status**: Pending
- **Pending issues**: None

## Quality Status
- **Build/test result**: Pending compilation
- **Lint status**: N/A
- **Tests added/modified**: N/A
