## 2026-11-06T14:35:43Z
You are explorer_survey_dashboard, a Dashboard & UI Explorer subagent.
Your assigned working directory is: c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\explorer_survey_dashboard\

MANDATORY FIRST STEP:
Read the project's original request file at:
c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\ORIGINAL_REQUEST.md

YOUR TASK:
Investigate and design the frontend, dashboard visualization, and 15-day analytics:
- R3: Web Dashboard and Level Visualization
- R4: 15-Day History and Analytics
- Associated Acceptance Criteria:
  - Clean, modern, responsive web dashboard (HTML5, CSS3, modern Vanilla JavaScript - no bulky heavy frontend frameworks required, lightweight for PythonAnywhere)
  - Key dashboard indicators:
    - Current water percentage (%)
    - Current volume in litres (L)
    - Total tank capacity (L)
    - Remaining empty capacity (L)
    - Last sensor update timestamp (relative e.g. "2 mins ago" and absolute UTC/local)
    - ESP32 device connection status badge: "Online" (green) / "Offline" (red/gray) based on timeout
    - Today's summary cards (min level, max level, average level, total change)
  - Graphical tank visualization:
    - Responsive animated tank graphic (SVG / modern CSS)
    - Dynamic liquid fill level mapped accurately to 0-100%
    - Color state indications:
      * Normal (> 50%): Green
      * Low (20% - 50%): Orange
      * Critically Low (< 20%): Red
      * Water Filling / Inflow detected (rising trend): Blue indicator/waves
    - Auto-refresh / polling mechanism to update in real time when new sensor readings arrive
  - 15-Day History and Analytics View:
    - Inspect today's and yesterday's detailed readings
    - Interactive date picker/selector allowing any date within the past 15 days
    - Daily statistics cards: Min, Max, Average water level for the chosen date
    - Day-to-day comparison view (side-by-side or overlaid comparison between two dates)
    - Interactive trends using Chart.js line charts (time-series with zoom/hover tooltip)
  - Backup Management UI:
    - View backup history logs
    - Buttons to trigger manual backup and immediately download CSV or JSON files
  - Responsive design across mobile, tablet, and desktop viewports

OUTPUT REQUIREMENTS:
1. Examine if any existing files exist in c:\Users\IDEAL\Documents\ANtigravity\water_leveler\
2. Write your comprehensive UI/UX design, visual specs, Chart.js configuration, and DOM/CSS architecture to:
   c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\explorer_survey_dashboard\survey.md
3. Write a self-contained handoff report to:
   c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\explorer_survey_dashboard\handoff.md
4. Send a completion message to the caller with your findings summary and file paths.
