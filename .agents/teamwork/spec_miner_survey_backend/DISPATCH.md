## 2026-11-06T14:35:34Z
You are spec_miner_survey_backend, a Backend & API Spec Miner subagent.
Your assigned working directory is: c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\spec_miner_survey_backend\

MANDATORY FIRST STEP:
Read the project's original request file at:
c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\ORIGINAL_REQUEST.md

YOUR TASK:
Investigate authoritative specifications, requirements, and edge cases for:
- R2: Flask Backend API and Database Storage
- R5: Automated Daily Backup System
- R6: PythonAnywhere Deployment Package
- Associated Acceptance Criteria:
  - Database schema: SQLite tables (`water_readings`, `devices`, `tank_settings`, `backup_logs`), data types, constraints, indexes on timestamp and date fields.
  - API endpoint `POST /api/water-level`:
    - Expected payload: device_id, distance_cm, water_level_cm, water_percentage, water_litres
    - Authentication via Device API Key (header `X-API-Key` or JSON field)
    - Strict input validation: non-null, valid numeric types, physical range limits (e.g., percentage 0-100, litres >= 0, positive distances), rejection of malformed or out-of-range readings with appropriate HTTP status codes (400, 401, 422).
    - Device status tracking: online/offline calculation based on configurable timeout threshold (e.g., 5 or 10 minutes without ping).
  - Endpoints needed for dashboard and analytics:
    - Current latest reading & device status
    - 15-day historical query endpoint with daily min, max, average statistics
    - Day comparison endpoint
    - Settings get/update endpoint
    - Manual backup trigger and download endpoints
  - Automated Daily Backup System:
    - Standalone python backup script runnable directly via PythonAnywhere Scheduled Tasks (cron-like runner, no persistent background daemons)
    - Export format: CSV and JSON
    - Storage in dedicated directory `backups/` persisting across server restarts
    - Logging backup events into `backup_logs` table
  - PythonAnywhere Deployment Package:
    - WSGI configuration file (`wsgi.py` / `pythonanywhere_wsgi.py`)
    - `requirements.txt` with exact pinned lightweight dependencies (Flask, etc.)
    - Database initialization script (`init_db.py` or CLI command)
    - Step-by-step deployment guide for PythonAnywhere web app configuration with HTTPS domain.

OUTPUT REQUIREMENTS:
1. Examine if any existing files exist in c:\Users\IDEAL\Documents\ANtigravity\water_leveler\
2. Write your complete specifications, schema DDL, endpoint contracts, and deployment architecture to:
   c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\spec_miner_survey_backend\spec.md
3. Write a self-contained handoff report to:
   c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\spec_miner_survey_backend\handoff.md
4. Send a completion message to the caller with your findings summary and file paths.
