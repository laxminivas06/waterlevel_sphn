## 2026-11-06T14:35:24Z
From: e67aac6c-272b-4420-b5de-866caa2cc5fb
Priority: MESSAGE_PRIORITY_HIGH

You are explorer_survey_firmware, a Firmware & Sensor Explorer subagent.
Your assigned working directory is: c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\explorer_survey_firmware\

MANDATORY FIRST STEP:
Read the project's original request file at:
c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\ORIGINAL_REQUEST.md

YOUR TASK:
Investigate and produce a comprehensive technical survey and specification for:
- R1: ESP32 Sensor Measurement and Firmware
- Associated Acceptance Criteria:
  - API endpoint payload compatibility
  - ESP32 firmware source code compiles cleanly without syntax errors
  - Wi-Fi reconnection and transmission retry logic
  - Sensor reading calculations: distance in cm, water level in cm, percentage (0-100%), volume in litres based on configurable tank dimensions
  - Noise reduction / moving average / outlier rejection for ultrasonic sensor (e.g., HC-SR04 / JSN-SR04T)
  - HTTP POST requests with JSON payload to backend API with API key authentication
  - Strictly monitoring only: absolutely NO motor, pump, or relay control logic
  - Complete configuration parameters: Wi-Fi credentials, API URL, device_id, api_key, reading interval, tank dimensions (total height, sensor offset, sensor blind zone, tank length/width/radius/shape)

OUTPUT REQUIREMENTS:
1. Examine if any existing files exist in c:\Users\IDEAL\Documents\ANtigravity\water_leveler\
2. Write your comprehensive analysis and architectural recommendations to:
   c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\explorer_survey_firmware\survey.md
3. Write a self-contained handoff report to:
   c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\explorer_survey_firmware\handoff.md
4. Send a completion message to the caller with your findings summary and file paths.
