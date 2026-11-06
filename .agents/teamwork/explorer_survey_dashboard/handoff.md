# Handoff Report: Frontend Dashboard, Tank Visualization & 15-Day Analytics Survey

**Agent**: `explorer_survey_dashboard` (Dashboard & UI Explorer)  
**Date**: 2026-11-06  
**Status**: Survey Complete (Hard Handoff)  
**Target File**: `c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\explorer_survey_dashboard\survey.md`

---

## 1. Observation

1. **Original Request Analysis**:
   - `c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\ORIGINAL_REQUEST.md` (lines 18-23, lines 43-48):
     > **R3. Web Dashboard and Level Visualization**:
     > "Provide a clean, modern, responsive web dashboard (HTML5, CSS3, JavaScript) displaying current water percentage, volume in litres, tank capacity, remaining capacity, last sensor update time, device connection status, and today's summary. Include a graphical tank visualization that fills dynamically with color indications (green for normal, orange for low, red for critically low, blue for water fill) and updates automatically when new readings arrive."
     > **R4. 15-Day History and Analytics**:
     > "Maintain historical water-level data for at least 15 days. Provide history and analytics views enabling users to inspect today's and yesterday's readings, select any date within the past 15 days, compare water levels across days, view minimum/maximum/average stats, and display water-level trends using Chart.js interactive line charts."
     > **R5. Automated Daily Backup System (UI Requirement)**:
     > "provide a manual backup download option from the dashboard... Dashboard backup section displays backup logs and provides an option to manually trigger and download backups."
2. **Workspace & Environment Inspection**:
   - Executed PowerShell command:
     `Get-ChildItem -Path . -Force -Recurse | Select-Object FullName, Length, LastWriteTime`
     Result: Workspace contains only `.agents/teamwork` coordination metadata; no production source files exist in the root yet.
   - Executed version check:
     `python --version; node --version`
     Result: `Python 3.11.15`, `v24.14.0`.
3. **Peer Subagent Coordination**:
   - `spec_miner_survey_backend/DISPATCH.md` (lines 10-37): Outlines SQLite database schema (`water_readings`, `devices`, `tank_settings`, `backup_logs`), device authentication via `X-API-Key`, sensor ingestion (`POST /api/water-level`), and endpoints needed for dashboard, history, day comparison, and backups.
   - `explorer_survey_firmware/DISPATCH.md` (lines 12-24): Confirms firmware telemetry will report `distance_cm`, `water_level_cm`, `water_percentage`, `water_litres` to the backend.

---

## 2. Logic Chain

1. **Lightweight PythonAnywhere Deployment Strategy**:
   - *Observation*: PythonAnywhere serves Flask applications via WSGI worker processes with strict daily CPU quotas and limited support for long-running Node.js background daemons.
   - *Deduction*: Adopting bulky frontend frameworks (React/Vue/Angular) requiring Webpack/Vite build steps would add unnecessary deployment complexity, memory bloat, and build maintenance overhead.
   - *Decision*: A zero-build modern Vanilla JavaScript (ES6+), semantic HTML5, and modular CSS3 architecture served directly via Flask's static handler is the cleanest, fastest, and most resilient solution. Chart.js 4.4.x is vendored locally in `app/static/vendor/chart.umd.min.js` to eliminate external runtime CDN dependencies.
2. **Dynamic Tank Graphic Visualization Engine**:
   - *Observation*: Acceptance criteria mandate an animated graphical tank with fluid fill mapping (0-100%) and 4 distinct color states: Normal Green (>50%), Low Orange (20-50%), Critically Low Red (<20%), and Filling Blue.
   - *Deduction*: Canvas-based tanks require continuous `requestAnimationFrame` render loops which consume device battery on mobile devices.
   - *Decision*: An SVG-based vector graphic (viewBox `0 0 240 320`) with a `<clipPath id="tank-clip">` bounds the fluid to the rounded tank walls. Dual sinusoidal wave paths (`.wave-back` and `.wave-front`) animate continuously using hardware-accelerated CSS keyframes (`transform: translateX(...)`). Linear gradients dynamically switch based on level thresholds, and an inflow rate detector ($\ge +5$ L/min) activates the blue gradient (`#grad-filling`) and waterfall stream particles.
3. **Resilient Polling Engine with Battery/CPU Preservation**:
   - *Observation*: Real-time updates must reflect new sensor data as it arrives, but continuously polling every 5 seconds when a user leaves the browser tab open indefinitely wastes PythonAnywhere web worker quotas.
   - *Deduction*: Polling must be intelligent and reactive to user presence and network stability.
   - *Decision*: Designed `PollingEngine` utilizing the Page Visibility API (`document.visibilityState`). Polling runs at 5-second intervals when active, automatically throttles to 30 seconds when backgrounded, immediately syncs upon foreground reactivation, and employs exponential backoff (up to 30s) during transient network outages.
4. **15-Day Analytics & Day-to-Day Comparison View**:
   - *Observation*: Acceptance criteria require inspecting today's and yesterday's detailed readings, selecting any date in the past 15 days, viewing Min/Max/Avg daily stats, and comparing water levels between any two days.
   - *Deduction*: Comparing two calendar days requires aligning disparate absolute dates onto a common temporal scale.
   - *Decision*: Designed a dual-day comparison view where both days are mapped to a normalized 24-hour time-of-day X-axis (`00:00` to `23:59`). The primary day renders as a solid Cyan line, and the comparison day renders as a dashed Amber line, with synchronized crosshair tooltips and a side-by-side metric scorecard showing percentage and litre deltas.
5. **Backup Management UI**:
   - *Observation*: R5 requires manual trigger and immediate download of CSV or JSON backups from the web interface.
   - *Decision*: Implemented UI controls for format selection (`CSV` vs `JSON`), scope selection (`All Records` vs `Past 15 Days`), a manual "Generate & Download" button with loading state that triggers native browser downloads via temporary hidden anchor elements, and a live backup history table.

---

## 3. Caveats

1. **Sensor Update Frequency Assumption**:
   - The UI defaults to an offline threshold of 10 minutes (`device_online: false` if no ping in 10 minutes). If the ESP32 firmware is configured with an update interval $> 10$ minutes (e.g. 15 or 30 minutes in low-power battery setups), the threshold configuration in the settings must be updated accordingly.
2. **Chart.js Local Vendoring**:
   - For 100% offline development and air-gapped deployment, `chart.umd.min.js` should be placed in `app/static/vendor/chart.umd.min.js`. The template includes a CDN fallback to ensure functionality if the local file is omitted during initial testing.
3. **Backend API Decoupling**:
   - The frontend specifications in `survey.md` define the precise JSON schema contracts (`GET /api/water-level/latest`, `GET /api/analytics/today`, `GET /api/history`, `GET /api/history/compare`, `GET /api/backups`, `POST /api/backups/create`). The backend implementation agent must ensure endpoint responses match these structures.

---

## 4. Conclusion

The comprehensive architectural survey for **R3 (Web Dashboard and Level Visualization)**, **R4 (15-Day History and Analytics)**, and **R5 (Backup Management UI)** has been completed and documented in:
`c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\explorer_survey_dashboard\survey.md`

The survey provides:
- Complete visual design system, color palette, and CSS variable tokens.
- Complete SVG markup, CSS wave animations, and JavaScript controller for the dynamic tank visualization.
- Complete specification for key indicators, telemetry badges, and Today's Summary Row.
- Complete Chart.js 4.x configuration for 15-day analytics, daily zoom, and normalized 24-hour day-to-day comparison.
- Complete Backup Management UI for manual CSV/JSON export and history log display.
- Resilient client-side polling engine with Page Visibility throttling.
- Fully documented REST API contracts and HTML5 DOM hierarchy.

The design is lightweight, requires zero build tools, is fully responsive across mobile/tablet/desktop, and is ready for implementation by the builder agents.

---

## 5. Verification Method

To independently verify the survey and specifications:
1. **Verify Survey Deliverables**:
   Run PowerShell command:
   ```powershell
   Test-Path c:\Users\IDEAL\Documents\ANtigravity\water_leveler\.agents\teamwork\explorer_survey_dashboard\survey.md
   ```
2. **Inspect Survey Coverage**:
   Read `survey.md` and verify each required section:
   - Section 2: Visual Design System & Color Tokens
   - Section 3: Dynamic SVG Tank Graphic & CSS Fluid Dynamics
   - Section 4: Key Indicators & Today's Summary Row (R3)
   - Section 5: 15-Day History & Analytics View (R4)
   - Section 6: Day-to-Day Comparison View (R4)
   - Section 7: Backup Management UI (R5)
   - Section 8: Polling Engine & Visibility Backoff
   - Section 9: REST API Contract Specifications
   - Section 10: HTML5 DOM Layout Hierarchy
3. **Invalidation Conditions**:
   - The specifications are invalidated if the backend API contracts deviate without updating the frontend endpoints, or if PythonAnywhere runtime imposes constraints preventing standard Flask static file delivery.
