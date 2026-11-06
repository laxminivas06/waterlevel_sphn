## 2026-11-06T15:40:27Z
You are app_runner_worker, a Worker subagent responsible for completing the web dashboard, backup system, and running the Flask application.
Your assigned working directory is: c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\app_runner_worker\

MANDATORY FIRST STEP:
Read:
1. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\ORIGINAL_REQUEST.md
2. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\PROJECT.md
3. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\explorer_survey_dashboard\survey.md
4. c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\spec_miner_survey_backend\spec.md

YOUR TASKS:
1. Implement Dashboard View Route:
   - `app/routes/views.py`: Blueprint `views_bp = Blueprint('views', __name__)` with route `@views_bp.route('/')` rendering `index.html`.
2. Implement Backup System & Routes:
   - `scripts/backup.py`: Autonomous CLI script supporting `--format both`, CSV & JSON export to persistent `backups/` directory, 30-day retention rotation, and DB logging to `backup_logs`.
   - `app/routes/backup_routes.py`: Blueprint `backup_bp = Blueprint('backup', __name__, url_prefix='/api/backup')` with endpoints:
     * `POST /api/backup/create`: triggers backup export and returns backup metadata.
     * `GET /api/backup/list`: lists past backups from `backup_logs`.
     * `GET /api/backup/download/<filename>`: serves backup file with path-traversal sanitization.
3. Update `app/__init__.py`:
   - Register `views_bp` and `backup_bp`.
4. Implement Dashboard Template & Frontend Assets:
   - `app/templates/index.html`: Complete, modern, responsive HTML5 dashboard displaying:
     * Header with device status badge (Online/Offline) and last updated timestamp
     * Main Grid: Dynamic SVG Tank Visualizer with fluid levels & color states (Green >50%, Orange 20-50%, Red <20%, Blue when filling)
     * Metric Cards: Water Percentage (%), Volume in Litres (L), Total Capacity, Remaining Headroom, Sensor Distance
     * Today's Summary: Min, Max, Average water level, and net change
     * 15-Day History & Analytics Section: Interactive date picker, Chart.js time-series trend line chart, and daily stats
     * Day-to-Day Comparison Section: Side-by-side comparison scorecards and overlaid comparison chart
     * Backup Management Section: Table of backup logs, "Create Manual Backup" button, and direct CSV/JSON download buttons
     * Settings Modal/View: Inspect tank height, offset, capacity, warning thresholds
   - `app/static/css/style.css`: Modern responsive CSS3 layout, clean typography, dynamic tank animations with dual sinusoidal waves, color transitions, mobile/tablet/desktop breakpoints.
   - `app/static/js/tank_visualizer.js`: SVG water level mapping and color state manager.
   - `app/static/js/dashboard.js`: Resilient polling engine (3s active / 30s background via Page Visibility API), metric card updater, today summary updater.
   - `app/static/js/analytics.js`: Chart.js integration, date picker event handlers, 15-day aggregate fetcher, comparison chart renderer, manual backup creator & table renderer.
5. Create `wsgi.py` and `requirements.txt`:
   - `wsgi.py`: Exposes `application = create_app()` with absolute sys.path configuration.
   - `requirements.txt`: Pinned dependencies (Flask, Werkzeug, requests, pytest).
6. Seed Initial Data & Run the Application:
   - Run `python scripts/init_db.py --seed` to ensure database and default device exist.
   - Run `python scripts/simulate_esp32.py --count 5 --auto-calc` to populate recent telemetry so the dashboard displays live water data immediately.
   - Start the Flask web application running on port 5000 in the background (using PowerShell Start-Process or python wsgi.py as a daemon/background task).
   - Verify that `http://127.0.0.1:5000/` and `http://127.0.0.1:5000/api/health` return HTTP 200 OK.
7. Write `handoff.md` and report back with application status and URL!
