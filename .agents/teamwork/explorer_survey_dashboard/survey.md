# Frontend Dashboard, Tank Visualization & 15-Day Analytics Survey

**Author**: `explorer_survey_dashboard` (Dashboard & UI Explorer)  
**Date**: 2026-11-06  
**Status**: Comprehensive Specification  
**Target Platform**: PythonAnywhere Flask Web App (Modern Desktop, Tablet, and Mobile Viewports)

---

## 1. Executive Summary & Design Principles

The Smart Water Tank Level Monitoring System frontend is designed to provide real-time situational awareness, intuitive fluid physical visualization, and 15-day longitudinal analytics for residential, commercial, or agricultural water storage.

### Core Architectural Decisions:
1. **Zero-Build Vanilla Architecture**: Modern ES6+ JavaScript, semantic HTML5, and modular CSS3. No Node.js build pipelines (Webpack, Vite, npm scripts) are required on PythonAnywhere. Assets are served directly by Flask's static handler, maximizing performance, reducing PythonAnywhere CPU quota usage, and eliminating runtime deployment failures.
2. **Dynamic Vector Tank Visualization**: Pure SVG + CSS3 keyframe animations. The liquid fill level maps linearly to physical sensor data (0% to 100%), with dual-layered sinusoidal animated wave crests, real-time color state transitions, and high-contrast in-tank typography.
3. **Resilient Adaptive Polling Engine**: Client-side fetch polling with delta detection, Page Visibility API throttling (pauses/slows when tab is backgrounded), and automatic exponential backoff on network interruptions.
4. **Rich 15-Day Time-Series Analytics with Chart.js 4.x**: Responsive interactive line charts with smooth curves, dynamic threshold annotations, hover tooltips, date filtering (today, yesterday, past 15 days), and overlaid day-to-day comparative visualization.
5. **Direct Backup Management UI**: Integrated monitoring of automated daily backups with single-click manual export and download in CSV or JSON formats.
6. **Mobile-First Responsive Layout**: CSS Grid and Flexbox layout scaling seamlessly from 320px mobile smartphones up to 4K desktop monitors.

---

## 2. Visual Design System & Color Palette

The interface adopts a high-contrast industrial aesthetic with dark/clean slate tones (`#0f172a`), crisp card surfaces (`#1e293b`), subtle borders (`#334155`), and luminous status accents.

### Color Tokens & Semantic States:

| Semantic State | Condition | Primary Color | Secondary / Gradient End | Glow / Background Tint |
| :--- | :--- | :--- | :--- | :--- |
| **Normal Level** | `percentage > 50%` | `#10b981` (Emerald 500) | `#059669` (Emerald 600) | `rgba(16, 185, 129, 0.15)` |
| **Low Level** | `20% <= percentage <= 50%` | `#f59e0b` (Amber 500) | `#d97706` (Amber 600) | `rgba(245, 158, 11, 0.15)` |
| **Critically Low** | `percentage < 20%` | `#ef4444` (Red 500) | `#dc2626` (Red 600) | `rgba(239, 68, 68, 0.20)` |
| **Filling / Inflow** | `trend == 'rising'` or `+L/min > threshold` | `#06b6d4` (Cyan 500) | `#2563eb` (Blue 600) | `rgba(6, 182, 212, 0.25)` |
| **Device Online** | `last_ping <= timeout` (e.g. 10m) | `#10b981` (Pulse Green) | `#34d399` (Light Green) | `rgba(16, 185, 129, 0.30)` |
| **Device Offline** | `last_ping > timeout` | `#64748b` (Slate Gray) | `#475569` (Dark Slate) | `rgba(100, 116, 139, 0.15)` |

### CSS Variables Root Definition:
```css
:root {
  /* Surface & Base Colors */
  --bg-primary: #0f172a;
  --bg-secondary: #1e293b;
  --bg-tertiary: #334155;
  --border-color: #334155;
  --text-primary: #f8fafc;
  --text-secondary: #94a3b8;
  --text-muted: #64748b;

  /* State Colors */
  --color-normal: #10b981;
  --color-normal-end: #059669;
  --color-normal-bg: rgba(16, 185, 129, 0.12);

  --color-low: #f59e0b;
  --color-low-end: #d97706;
  --color-low-bg: rgba(245, 158, 11, 0.12);

  --color-critical: #ef4444;
  --color-critical-end: #dc2626;
  --color-critical-bg: rgba(239, 68, 68, 0.15);

  --color-filling: #06b6d4;
  --color-filling-end: #2563eb;
  --color-filling-bg: rgba(6, 182, 212, 0.18);

  /* Device Status */
  --status-online: #10b981;
  --status-offline: #f43f5e;

  /* Layout & Spacing */
  --card-radius: 14px;
  --transition-smooth: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  --shadow-card: 0 4px 6px -1px rgba(0, 0, 0, 0.3), 0 2px 4px -2px rgba(0, 0, 0, 0.25);
  --shadow-glow: 0 0 15px rgba(6, 182, 212, 0.35);
}
```

---

## 3. Dynamic Tank Graphic Visualization (R3)

### 3.1 Physical Tank Anatomy & SVG Architecture
The tank graphic represents a vertical cylindrical storage tank with an industrial rounded profile, level calibration markings, fluid surface meniscus waves, and center overlay readouts.

```
+----------------------------------------------------+
|               [ Sensor Transmitter ]               |
|                   +-------------+                  |
|                   |  HC-SR04 /  |                  |
|                   |  JSN-SR04T  |                  |
|                   +------+------+                  |
|                          | Ultrasonic Ping         |
|                          v                         |
|     +----------------------------------------+     |
|100% | - - - - - - - - - - - - - - - - - - -  |     |
|     |  Wave Meniscus: ~~~~~~ ~~~~~~ ~~~~~~   |     |
| 75% | - - - - - - - - - - - - - - - - - - -  |     |
|     |                                        |     |
|     |             [ 78.4 % ]                 |     |
| 50% | - - - -   [ 1,568 Litres ]   - - - - - |     |
|     |            [ 141.2 cm ]                |     |
| 25% | - - - - - - - - - - - - - - - - - - -  |     |
|     |                                        |     |
|  0% +----------------------------------------+     |
|     |               Tank Base                |     |
+----------------------------------------------------+
```

### 3.2 SVG Markup Specification
The SVG container uses a viewBox of `0 0 240 320`. The liquid rectangle is clipped by the tank's inner shape (`<clipPath id="tank-clip">`) so the fluid stays strictly inside the rounded tank walls.

```xml
<svg id="tank-svg" class="tank-svg" viewBox="0 0 240 320" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <!-- Dynamic Linear Gradients for States -->
    <linearGradient id="grad-normal" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#10b981" />
      <stop offset="100%" stop-color="#059669" />
    </linearGradient>
    <linearGradient id="grad-low" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#fbbf24" />
      <stop offset="100%" stop-color="#ea580c" />
    </linearGradient>
    <linearGradient id="grad-critical" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#f87171" />
      <stop offset="100%" stop-color="#dc2626" />
    </linearGradient>
    <linearGradient id="grad-filling" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#38bdf8" />
      <stop offset="100%" stop-color="#1d4ed8" />
    </linearGradient>

    <!-- Glass reflections and tank body border gradients -->
    <linearGradient id="tank-glass-reflect" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="0.12" />
      <stop offset="15%" stop-color="#ffffff" stop-opacity="0.03" />
      <stop offset="85%" stop-color="#000000" stop-opacity="0.05" />
      <stop offset="100%" stop-color="#ffffff" stop-opacity="0.08" />
    </linearGradient>

    <!-- Tank Boundary Clip Path -->
    <clipPath id="tank-clip">
      <!-- Dimensions: x=35, y=30, width=170, height=250, rx=18, ry=18 -->
      <rect x="35" y="30" width="170" height="250" rx="18" ry="18" />
    </clipPath>
  </defs>

  <!-- Tank Top Fixture / Cap -->
  <rect x="80" y="14" width="80" height="16" rx="5" fill="#334155" stroke="#475569" stroke-width="2" />
  <!-- Sensor Ping Beacon (Pulsing Green Dot when active) -->
  <circle id="sensor-beacon" cx="120" cy="22" r="3.5" fill="#10b981" />

  <!-- Tank Outer Shell Background (empty volume space) -->
  <rect x="35" y="30" width="170" height="250" rx="18" fill="#111827" stroke="#334155" stroke-width="3" />

  <!-- Liquid Container Clipped to Tank Boundaries -->
  <g clip-path="url(#tank-clip)">
    <!-- Base Liquid Rectangle: Height and Y are dynamically updated -->
    <!-- y = 30 + 250 * (1 - pct/100); height = 250 * (pct/100) -->
    <rect id="liquid-body" x="35" y="92.5" width="170" height="187.5" fill="url(#grad-normal)" />

    <!-- Animated Dual Sinusoidal Surface Waves -->
    <g id="wave-container" transform="translate(0, 92.5)">
      <!-- Back Wave -->
      <path class="wave wave-back" d="M-100,0 C-50,-8 0,8 50,0 C100,-8 150,8 200,0 C250,-8 300,8 350,0 L350,50 L-100,50 Z" />
      <!-- Front Wave -->
      <path class="wave wave-front" d="M-100,0 C-60,8 -20,-8 20,0 C60,8 100,-8 140,0 C180,8 220,-8 260,0 C300,8 340,-8 380,0 L380,50 L-100,50 Z" />
    </g>

    <!-- Inflow Stream Effect (Visible only when filling is active) -->
    <g id="inflow-stream" class="inflow-effect" opacity="0">
      <line x1="120" y1="30" x2="120" y2="280" stroke="#38bdf8" stroke-width="4" stroke-dasharray="8 6" class="inflow-line" />
      <circle cx="120" cy="180" r="4" fill="#67e8f9" class="inflow-bubble b1" />
      <circle cx="114" cy="210" r="3" fill="#67e8f9" class="inflow-bubble b2" />
      <circle cx="126" cy="240" r="5" fill="#67e8f9" class="inflow-bubble b3" />
    </g>

    <!-- Glass Reflection Layer -->
    <rect x="35" y="30" width="170" height="250" fill="url(#tank-glass-reflect)" pointer-events="none" />
  </g>

  <!-- Level Graduation Rulers (Ticks & Labels) -->
  <g class="tank-graduation" stroke="#64748b" stroke-width="1.5">
    <!-- 100% Mark (y=30) -->
    <line x1="26" y1="30" x2="35" y2="30" />
    <text x="22" y="34" font-size="9" fill="#94a3b8" text-anchor="end">100%</text>

    <!-- 75% Mark (y=92.5) -->
    <line x1="28" y1="92.5" x2="35" y2="92.5" />
    <text x="22" y="96" font-size="8" fill="#64748b" text-anchor="end">75%</text>

    <!-- 50% Mark (y=155) -->
    <line x1="26" y1="155" x2="35" y2="155" />
    <text x="22" y="159" font-size="9" fill="#94a3b8" text-anchor="end">50%</text>

    <!-- 25% Mark (y=217.5) -->
    <line x1="28" y1="217.5" x2="35" y2="217.5" />
    <text x="22" y="221" font-size="8" fill="#64748b" text-anchor="end">25%</text>

    <!-- 0% Mark (y=280) -->
    <line x1="26" y1="280" x2="35" y2="280" />
    <text x="22" y="284" font-size="9" fill="#94a3b8" text-anchor="end">0%</text>
  </g>

  <!-- Tank Base Support Stand -->
  <rect x="70" y="282" width="100" height="12" rx="3" fill="#334155" stroke="#475569" stroke-width="1.5" />
  <rect x="55" y="294" width="130" height="6" rx="2" fill="#1e293b" />

  <!-- Center Floating Readouts (High-contrast, crisp drop-shadow) -->
  <g class="tank-readouts" text-anchor="middle">
    <!-- Large Percentage Text -->
    <text id="tank-text-pct" x="120" y="145" class="tank-readout-pct">0%</text>
    <!-- Litres Readout -->
    <text id="tank-text-litres" x="120" y="172" class="tank-readout-sub">0 L / 0 L</text>
    <!-- Water Height Readout -->
    <text id="tank-text-height" x="120" y="192" class="tank-readout-cm">0.0 cm</text>
    <!-- Filling Trend Badge -->
    <g id="tank-badge-filling" opacity="0">
      <rect x="75" y="206" width="90" height="20" rx="10" fill="#0284c7" />
      <text x="120" y="220" font-size="10" font-weight="bold" fill="#ffffff">▲ INFLOW</text>
    </g>
  </g>
</svg>
```

### 3.3 CSS Animation & Fluid Dynamics
Smooth fluid dynamics are achieved via CSS transforms:

```css
/* Animated Wave Crests */
.wave {
  position: absolute;
  fill: inherit;
  transition: transform 0.8s cubic-bezier(0.4, 0, 0.2, 1);
}

.wave-back {
  opacity: 0.45;
  animation: wave-slide-back 6s linear infinite;
}

.wave-front {
  opacity: 0.80;
  animation: wave-slide-front 3.5s linear infinite;
}

@keyframes wave-slide-back {
  0%   { transform: translateX(0); }
  100% { transform: translateX(-150px); }
}

@keyframes wave-slide-front {
  0%   { transform: translateX(-150px); }
  100% { transform: translateX(0); }
}

/* Fast turbulent animation when filling */
.is-filling .wave-back {
  animation-duration: 2.2s;
}
.is-filling .wave-front {
  animation-duration: 1.4s;
}

/* Inflow Waterfall Stream Animation */
@keyframes stream-flow {
  0%   { stroke-dashoffset: 0; }
  100% { stroke-dashoffset: -40; }
}

.inflow-line {
  animation: stream-flow 0.8s linear infinite;
}

/* Upward bubbling particles */
@keyframes bubble-rise {
  0%   { transform: translateY(0); opacity: 0.8; }
  100% { transform: translateY(-70px); opacity: 0; }
}

.inflow-bubble.b1 { animation: bubble-rise 1.5s ease-in infinite 0.1s; }
.inflow-bubble.b2 { animation: bubble-rise 1.8s ease-in infinite 0.5s; }
.inflow-bubble.b3 { animation: bubble-rise 1.2s ease-in infinite 0.9s; }

/* Tank Readout Typography */
.tank-readout-pct {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 38px;
  font-weight: 800;
  fill: #ffffff;
  filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.8));
}

.tank-readout-sub {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 14px;
  font-weight: 600;
  fill: #e2e8f0;
  filter: drop-shadow(0 1px 3px rgba(0, 0, 0, 0.8));
}

.tank-readout-cm {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 11px;
  font-weight: 500;
  fill: #cbd5e1;
  filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.8));
}
```

### 3.4 Tank Controller JavaScript Mapping
The mapping converts 0–100% water level into exact SVG coordinates (`y` and `height`), smoothly transitions the height, selects the active gradient, and manages the inflow state.

```javascript
class TankVisualizer {
  constructor(svgElement) {
    this.svg = svgElement;
    this.liquidBody = svgElement.querySelector('#liquid-body');
    this.waveContainer = svgElement.querySelector('#wave-container');
    this.textPct = svgElement.querySelector('#tank-text-pct');
    this.textLitres = svgElement.querySelector('#tank-text-litres');
    this.textHeight = svgElement.querySelector('#tank-text-height');
    this.inflowStream = svgElement.querySelector('#inflow-stream');
    this.badgeFilling = svgElement.querySelector('#tank-badge-filling');

    // Physical geometry bounds inside SVG (viewBox height 320)
    this.TANK_TOP_Y = 30;
    this.TANK_HEIGHT = 250;
    this.TANK_BOTTOM_Y = 280;
  }

  update({ percentage, litres, capacity, water_level_cm, isFilling }) {
    // Clamp percentage 0 - 100
    const pct = Math.max(0, Math.min(100, Number(percentage) || 0));
    const fillHeight = (pct / 100) * this.TANK_HEIGHT;
    const targetY = this.TANK_BOTTOM_Y - fillHeight;

    // 1. Smoothly interpolate / set attributes
    this.liquidBody.setAttribute('y', targetY);
    this.liquidBody.setAttribute('height', fillHeight);
    this.waveContainer.setAttribute('transform', `translate(0, ${targetY})`);

    // 2. Select appropriate color gradient
    let gradUrl = 'url(#grad-normal)';
    let stateColor = '#10b981';

    if (isFilling) {
      gradUrl = 'url(#grad-filling)';
      stateColor = '#06b6d4';
    } else if (pct < 20) {
      gradUrl = 'url(#grad-critical)';
      stateColor = '#ef4444';
    } else if (pct <= 50) {
      gradUrl = 'url(#grad-low)';
      stateColor = '#f59e0b';
    }

    this.liquidBody.setAttribute('fill', gradUrl);

    // 3. Update Text Content
    this.textPct.textContent = `${pct.toFixed(1)}%`;
    this.textLitres.textContent = `${Math.round(litres).toLocaleString()} L / ${Math.round(capacity).toLocaleString()} L`;
    this.textHeight.textContent = `${(Number(water_level_cm) || 0).toFixed(1)} cm depth`;

    // 4. Update Inflow Visuals
    if (isFilling) {
      this.svg.classList.add('is-filling');
      this.inflowStream.setAttribute('opacity', '1');
      this.badgeFilling.setAttribute('opacity', '1');
    } else {
      this.svg.classList.remove('is-filling');
      this.inflowStream.setAttribute('opacity', '0');
      this.badgeFilling.setAttribute('opacity', '0');
    }

    return stateColor;
  }
}
```

---

## 4. Key Indicators & Dashboard Layout (R3)

### 4.1 Header Bar & Device Status Badge
- **Brand & Tank Selector**: "HydroSense IoT" with tank selector dropdown (if multi-tank or default to Tank #1).
- **ESP32 Device Connection Status Badge**:
  - `Online` (Green `#10b981` pulsing badge): Last update was `< 10 minutes ago` (configurable timeout).
  - `Offline` (Red/Slate `#f43f5e` / `#64748b` badge): Last update was `> 10 minutes ago`.
  - Tooltip: Displays exact last ping time and timeout threshold.
- **Last Sensor Update Timestamp**:
  - Live Relative Counter: e.g. "Updated 25s ago" (updated client-side every second without server poll).
  - Absolute Subtitle: "2026-11-06 14:32:10 UTC (Local: 20:02:10 IST)".
- **Quick Action Bar**:
  - Manual Refresh Button (rotates icon on click).
  - Audio Alarm / Notification Mute Toggle.

### 4.2 Primary Metrics Grid (4 Key Metric Cards)
Each card features a high-visibility metric number, iconography, and secondary context:

```
+-------------------+ +-------------------+ +-------------------+ +-------------------+
| WATER LEVEL       | | WATER VOLUME      | | REMAINING HEADROOM| | ESP32 TELEMETRY   |
| [ 78.4 % ]        | | [ 1,568 L ]       | | [ 432 L ]         | | [ ONLINE ]        |
| Normal / Healthy  | | of 2,000 L Cap    | | 21.6% Available   | | Ping: 42s ago     |
| [||||||||||  ]    | | Sensor: 38.8 cm   | | Est. Runout: 3.2d | | RSSI: -65 dBm     |
+-------------------+ +-------------------+ +-------------------+ +-------------------+
```

1. **Card 1: Current Water Percentage (%)**:
   - Primary: Large bold `78.4%`
   - Status Pill: `Normal` (Green) / `Low` (Orange) / `Critically Low` (Red) / `Filling` (Blue).
   - Micro Progress Bar: 0 to 100% color-coded mini bar.
2. **Card 2: Current Water Volume in Litres (L)**:
   - Primary: `1,568 L`
   - Secondary: `Total Capacity: 2,000 L`
   - Third line: Water column height `141.2 cm`.
3. **Card 3: Remaining Empty Capacity (L)**:
   - Primary: `432 L`
   - Secondary: `21.6% Headroom Available`
   - Sensor distance to water surface: `38.8 cm` (air gap).
4. **Card 4: ESP32 Device Health & Connectivity**:
   - Primary Status: `Online` (Pulsing green dot) / `Offline`.
   - Device ID: `esp32_water_tank_01`
   - Wi-Fi Signal Strength (RSSI): `-65 dBm (Strong)`
   - Communication Protocol: `HTTP POST / Wi-Fi 802.11b/g/n`

### 4.3 Today's Summary Row (R3 Acceptance Criteria)
A dedicated 4-metric summary bar providing instant operational insights for the current calendar day (00:00 to current time):

```
+-----------------------------------------------------------------------------------+
| TODAY'S OPERATIONAL SUMMARY (2026-11-06)                                          |
|                                                                                   |
|  MINIMUM LEVEL       MAXIMUM LEVEL       AVERAGE LEVEL       NET WATER CHANGE     |
|  [ 34.2 % ]          [ 94.0 % ]          [ 72.8 % ]          [ +480 L ]           |
|  684 L at 05:22      1,880 L at 11:15    1,456 L (Day Avg)   ▲ Inflow > Outflow   |
+-----------------------------------------------------------------------------------+
```

- **Daily Min**: Lowest reading captured today, timestamp, and litres.
- **Daily Max**: Peak level achieved today, timestamp, and litres.
- **Daily Average**: Arithmetic mean of all valid readings captured today.
- **Total Net Change**: Calculated as `Current Litres - First Reading of Today (00:00)`. Displays positive (+L with green/blue up-arrow) or negative (-L with orange down-arrow).

---

## 5. 15-Day History and Analytics View (R4)

### 5.1 Interactive Date Filtering & Navigation
The history module enables seamless exploration across the 15-day rolling storage window:

- **Quick-Select Date Pills**:
  - `Today` (Instant focus on today's readings)
  - `Yesterday` (Previous calendar day)
  - `Last 7 Days` (Aggregated 7-day trend)
  - `Past 15 Days` (Full retention window)
- **HTML5 Date Picker**:
  - `<input type="date" id="history-date-picker">`
  - Dynamically bounded: `max = today_iso`, `min = (today - 15 days)_iso`.
  - On change: triggers AJAX request to fetch time-series data for the selected date.
- **Data Resolution / Aggregation Selector**:
  - `Raw Readings` (Every individual sensor ping, e.g. every 1-5 mins)
  - `15-Min Averages` (Smooths minor sloshing / noise)
  - `Hourly Averages` (Ideal for multi-day 15-day trend views)
- **Metric Unit Toggle**:
  - `Water Percentage (%)`
  - `Volume in Litres (L)`
  - `Distance / Level in Centimetres (cm)`

### 5.2 Chosen Date Daily Statistics Cards
When any specific date is selected (e.g., 2026-11-04), a dedicated statistics panel displays:
1. **Min Level & Time**: e.g., `24.0% (480 L)` at `06:14 AM`
2. **Max Level & Time**: e.g., `92.5% (1,850 L)` at `10:45 AM`
3. **Daily Average**: e.g., `68.2% (1,364 L)`
4. **Estimated Daily Water Consumption**: Sum of negative reading deltas throughout the day (e.g., `1,120 Litres consumed`).
5. **Fill / Inflow Events**: Count of distinct rising slopes (e.g., `1 Major Refill (+1,370 L)`).

### 5.3 Interactive Chart.js Line Chart Architecture
Chart.js v4.4.x (vendored locally in `app/static/vendor/chart.umd.min.js`) provides responsive, GPU-accelerated canvas charting.

#### Chart Configuration Specification:
```javascript
function createAnalyticsChart(canvasElement, initialData) {
  const ctx = canvasElement.getContext('2d');

  // Create subtle glowing gradient fill under curve
  const gradient = ctx.createLinearGradient(0, 0, 0, 350);
  gradient.addColorStop(0, 'rgba(6, 182, 212, 0.45)');   // Cyan top
  gradient.addColorStop(0.7, 'rgba(6, 182, 212, 0.08)'); // Fade out
  gradient.addColorStop(1, 'rgba(6, 182, 212, 0.0)');

  return new Chart(ctx, {
    type: 'line',
    data: {
      labels: initialData.timestamps, // ISO strings or HH:mm formatted
      datasets: [
        {
          label: 'Water Level (%)',
          data: initialData.percentages,
          borderColor: '#06b6d4',
          borderWidth: 2.5,
          pointRadius: initialData.timestamps.length > 100 ? 0 : 3,
          pointHoverRadius: 6,
          pointBackgroundColor: '#38bdf8',
          pointBorderColor: '#ffffff',
          pointBorderWidth: 2,
          tension: 0.3, // Smooth natural bezier curves
          fill: true,
          backgroundColor: gradient,
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: 'index',
        intersect: false,
      },
      plugins: {
        legend: {
          display: true,
          position: 'top',
          labels: { color: '#94a3b8', font: { size: 12, weight: '500' } }
        },
        tooltip: {
          backgroundColor: 'rgba(15, 23, 42, 0.95)',
          titleColor: '#f8fafc',
          bodyColor: '#cbd5e1',
          borderColor: '#334155',
          borderWidth: 1,
          padding: 12,
          displayColors: false,
          callbacks: {
            title: (items) => {
              const date = new Date(items[0].label);
              return date.toLocaleString();
            },
            label: (context) => {
              const val = context.parsed.y;
              const idx = context.dataIndex;
              const litres = initialData.litres ? initialData.litres[idx] : null;
              const cm = initialData.distance_cm ? initialData.distance_cm[idx] : null;
              
              let lines = [`Level: ${val.toFixed(1)} %`];
              if (litres !== null) lines.push(`Volume: ${Math.round(litres).toLocaleString()} L`);
              if (cm !== null) lines.push(`Sensor Dist: ${cm.toFixed(1)} cm`);
              return lines;
            }
          }
        }
      },
      scales: {
        x: {
          grid: { color: 'rgba(51, 65, 85, 0.4)' },
          ticks: { color: '#94a3b8', maxRotation: 0, autoSkip: true, maxTicksLimit: 12 }
        },
        y: {
          min: 0,
          max: 100,
          grid: { color: 'rgba(51, 65, 85, 0.4)' },
          ticks: {
            color: '#94a3b8',
            callback: (v) => `${v}%`
          }
        }
      }
    }
  });
}
```

#### Level Threshold Annotation Lines:
Horizontal guideline markers on the canvas indicate critical operating boundaries:
- **High / Full Line (80%)**: Dotted Green line (`#10b981`)
- **Low Warning Line (50%)**: Dotted Orange line (`#f59e0b`)
- **Critical Threshold Line (20%)**: Dashed Red line (`#ef4444`)

---

## 6. Day-to-Day Comparison View (R4 Acceptance Criteria)

The Day-to-Day Comparison View enables homeowners and plant managers to analyze consumption patterns, leakages, and refill schedules by comparing any two dates side-by-side or overlaid.

```
+---------------------------------------------------------------------------------------+
| DAY-TO-DAY COMPARISON ANALYTICS                                                       |
| [ Compare Date 1: 2026-11-06 (Today) ]  vs  [ Compare Date 2: 2026-11-05 (Yesterday) ]|
+---------------------------------------------------------------------------------------+
| COMPARISON SUMMARY                                                                    |
| METRIC                    | DATE 1 (TODAY)     | DATE 2 (YESTERDAY) | VARIANCE / DELTA|
| Average Water Level       | 74.5 % (1,490 L)   | 68.2 % (1,364 L)   | ▲ +6.3 % (+126L)|
| Minimum Level Reached     | 38.0 % (760 L)     | 24.5 % (490 L)     | ▲ +13.5% (+270L)|
| Maximum Level Reached     | 95.0 % (1,900 L)   | 92.0 % (1,840 L)   | ▲ +3.0 % (+60 L)|
| Est. Daily Water Usage    | 820 Litres         | 1,150 Litres       | ▼ -330 L (-28%) |
+---------------------------------------------------------------------------------------+
| OVERLAID 24-HOUR TIME-OF-DAY COMPARISON CHART                                         |
| 100% |                                                                                |
|      |        /---------\ Date 1 (Cyan Solid: Today)                                  |
|  50% |       /           \ - - - - - Date 2 (Amber Dashed: Yesterday)                 |
|      |  ----/             \------                                                     |
|   0% +--------------------------------------------------------------------------      |
|      00:00   03:00   06:00   09:00   12:00   15:00   18:00   21:00   23:59            |
+---------------------------------------------------------------------------------------+
```

### 6.1 Dual-Day Overlaid Chart Specification
To compare two disparate calendar days on a single synchronized X-axis:
1. **X-Axis Normalization**: Both days are mapped to a standardized 24-hour time-of-day timeline: `00:00` to `23:59`.
2. **Dataset 1 (Date A / Today)**:
   - Stroke: Cyan `#06b6d4`, solid line (2.5px).
   - Label: `Date A (e.g. 2026-11-06)`.
3. **Dataset 2 (Date B / Yesterday or Selected)**:
   - Stroke: Amber `#f59e0b` or Purple `#a855f7`, dashed line `[6, 4]`.
   - Label: `Date B (e.g. 2026-11-05)`.
4. **Synchronized Hover Tooltip**:
   - Hovering at `14:30` shows both Date A and Date B levels at 14:30 simultaneously, displaying the exact delta difference (+% and +Litres).

---

## 7. Backup Management UI (R5)

The Backup Management interface connects directly with the Flask backup subsystem and the PythonAnywhere scheduled backup runner.

### 7.1 Architecture & Components

```
+-----------------------------------------------------------------------------------+
| BACKUP SUBSYSTEM MANAGEMENT                                                       |
| Scheduled Runner: Standalone PythonAnywhere Task (Daily 02:00 UTC)                |
| Persistence Directory: /home/username/water_leveler/backups/                      |
+-----------------------------------------------------------------------------------+
| MANUAL BACKUP GENERATION                                                          |
| Export Format: (o) CSV   ( ) JSON                                                 |
| Scope:         (o) Complete History   ( ) Last 15 Days Only                       |
| [ ⬇ Generate & Download Backup Now ]                                             |
+-----------------------------------------------------------------------------------+
| BACKUP HISTORY LOGS (Recent 10 Backups)                                           |
| TIMESTAMP (UTC)      | FILENAME                       | FORMAT | RECORDS | SIZE  | ACTIONS     |
| 2026-11-06 02:00:05  | backup_20261106_020005.csv     | CSV    | 4,320   | 184 KB| [ Download ]|
| 2026-11-05 02:00:04  | backup_20261105_020004.csv     | CSV    | 2,880   | 122 KB| [ Download ]|
| 2026-11-04 18:22:10  | backup_manual_20261104.json    | JSON   | 2,400   | 310 KB| [ Download ]|
+-----------------------------------------------------------------------------------+
```

### 7.2 Manual Backup Workflow:
1. User clicks **"Generate & Download Backup Now"**.
2. Button enters loading state with spinning spinner icon (`Generating archive...`).
3. Client issues `POST /api/backups/create` with JSON payload `{ format: "csv", scope: "all" }`.
4. Backend executes standalone export, writes file to `backups/`, inserts record into `backup_logs` table, and returns `{ success: true, download_url: "/api/backups/download/<filename>" }`.
5. Frontend triggers immediate native browser file download via temporary hidden `<a download>` anchor.
6. The backup history log table automatically reloads and displays the new backup record with a green confirmation toast alert: *"Backup successfully created and downloaded (184 KB)"*.

---

## 8. Client-Side DOM & JavaScript Architecture

### 8.1 Modular Directory & File Organization
```
water_leveler/
├── app/
│   ├── static/
│   │   ├── css/
│   │   │   ├── main.css            # CSS variables, typography, reset, grid
│   │   │   ├── tank.css            # Tank SVG animations, fluid waves, glow
│   │   │   ├── cards.css           # Metrics cards, badges, statistics rows
│   │   │   └── tables.css          # History tables, comparison tables, backups
│   │   ├── js/
│   │   │   ├── app.js              # Application entry, tab navigation, notifications
│   │   │   ├── api.js              # Fetch wrapper, error handling, retry logic
│   │   │   ├── polling.js          # Polling engine with Page Visibility backoff
│   │   │   ├── tank-visualizer.js  # Tank SVG controller & fluid dynamics
│   │   │   ├── analytics.js        # Date picker, stats calculations, comparison
│   │   │   ├── chart-controller.js # Chart.js instance manager & zoom/tooltips
│   │   │   └── backups.js          # Backup generation & download manager
│   │   └── vendor/
│   │       └── chart.umd.min.js    # Vendored Chart.js 4.4.x (zero build step)
│   └── templates/
│       ├── base.html               # Semantic HTML5 base layout, nav, scripts
│       └── index.html              # Main dashboard view with modular sections/tabs
```

### 8.2 Real-Time Polling Engine with Visibility Throttling
PythonAnywhere web worker quotas and CPU seconds require strict polling discipline. A tab left open overnight must not waste daily CPU quotas.

```javascript
// app/static/js/polling.js
class PollingEngine {
  constructor({ url, intervalMs = 5000, onData, onError }) {
    this.url = url;
    this.intervalMs = intervalMs;
    this.onData = onData;
    this.onError = onError;
    this.timerId = null;
    this.isPolling = false;
    this.lastReadingId = null;
    this.consecutiveFailures = 0;

    this.initVisibilityListener();
  }

  start() {
    if (this.isPolling) return;
    this.isPolling = true;
    this.poll();
  }

  stop() {
    this.isPolling = false;
    if (this.timerId) {
      clearTimeout(this.timerId);
      this.timerId = null;
    }
  }

  async poll() {
    if (!this.isPolling) return;

    try {
      const response = await fetch(this.url, {
        headers: { 'Accept': 'application/json' },
        cache: 'no-cache'
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      this.consecutiveFailures = 0;

      // Delta detection: Trigger UI update if reading changed
      if (!this.lastReadingId || this.lastReadingId !== data.id) {
        this.lastReadingId = data.id;
        this.onData(data, true); // data changed
      } else {
        this.onData(data, false); // ping heartbeat only
      }
    } catch (err) {
      this.consecutiveFailures++;
      this.onError(err, this.consecutiveFailures);
    } finally {
      // Schedule next poll with adaptive delay
      if (this.isPolling) {
        const nextDelay = this.calculateNextDelay();
        this.timerId = setTimeout(() => this.poll(), nextDelay);
      }
    }
  }

  calculateNextDelay() {
    // If tab is in background, throttle to 30 seconds
    if (document.visibilityState === 'hidden') {
      return 30000;
    }
    // Exponential backoff on network failures (5s -> 10s -> 20s -> 30s)
    if (this.consecutiveFailures > 0) {
      return Math.min(30000, this.intervalMs * Math.pow(2, this.consecutiveFailures - 1));
    }
    return this.intervalMs;
  }

  initVisibilityListener() {
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') {
        // Tab brought to foreground: immediately trigger fresh poll
        this.stop();
        this.start();
      }
    });
  }
}
```

### 8.3 Inflow / Filling Trend Detection
To identify when water is actively filling the tank (e.g. municipal water supply active or borehole pump running):
- Inflow condition:
  $$\Delta L = \text{Current Litres} - \text{Litres (3 readings ago)}$$
  $$\Delta t = \text{Time elapsed in minutes}$$
  $$\text{Flow Rate} = \frac{\Delta L}{\Delta t}$$
- If $\text{Flow Rate} \ge +5.0 \text{ L/min}$ or $\Delta \text{percentage} \ge +1.0\%$, the system sets `isFilling = true`.
- Dynamic UI response:
  - SVG tank switches to blue water gradient (`#grad-filling`).
  - Surface wave animations accelerate.
  - Inflow stream particles animate.
  - Card displays animated badge: `▲ Inflow Detected (+28 L/min)`.

---

## 9. Frontend REST API Contract Expectations

To ensure seamless coordination with `spec_miner_survey_backend`, the frontend relies on the following clean REST endpoint contracts:

### 9.1 `GET /api/water-level/latest`
Returns the most recent verified sensor reading, tank dimensions, and device connectivity state.

**Response (200 OK)**:
```json
{
  "status": "success",
  "data": {
    "id": 1420,
    "device_id": "esp32_tank_01",
    "timestamp": "2026-11-06T14:35:10Z",
    "distance_cm": 38.8,
    "water_level_cm": 141.2,
    "water_percentage": 78.4,
    "water_litres": 1568.0,
    "tank_capacity_litres": 2000.0,
    "remaining_litres": 432.0,
    "device_online": true,
    "seconds_since_last_ping": 25,
    "flow_trend": "rising",
    "flow_rate_lpm": 24.5
  }
}
```

### 9.2 `GET /api/analytics/today`
Returns summary statistics for the current calendar day.

**Response (200 OK)**:
```json
{
  "status": "success",
  "data": {
    "date": "2026-11-06",
    "min_level": { "percentage": 34.2, "litres": 684.0, "timestamp": "2026-11-06T05:22:00Z" },
    "max_level": { "percentage": 94.0, "litres": 1880.0, "timestamp": "2026-11-06T11:15:00Z" },
    "avg_percentage": 72.8,
    "avg_litres": 1456.0,
    "net_change_litres": 480.0,
    "readings_count": 288
  }
}
```

### 9.3 `GET /api/history?date=YYYY-MM-DD&resolution=raw|15m|hourly`
Returns timestamped time-series records for any selected date in the 15-day retention window.

**Response (200 OK)**:
```json
{
  "status": "success",
  "data": {
    "date": "2026-11-04",
    "summary": {
      "min_percentage": 24.0,
      "max_percentage": 92.5,
      "avg_percentage": 68.2,
      "total_consumption_litres": 1120.0
    },
    "points": [
      {
        "timestamp": "2026-11-04T00:00:00Z",
        "time_str": "00:00",
        "water_percentage": 62.0,
        "water_litres": 1240.0,
        "distance_cm": 68.4
      }
    ]
  }
}
```

### 9.4 `GET /api/history/compare?date1=YYYY-MM-DD&date2=YYYY-MM-DD`
Returns synchronized comparison datasets for the two dates normalized to time-of-day.

**Response (200 OK)**:
```json
{
  "status": "success",
  "data": {
    "date1": {
      "date": "2026-11-06",
      "summary": { "avg_pct": 74.5, "min_pct": 38.0, "max_pct": 95.0, "consumption_l": 820 },
      "points": [{ "time_slot": "14:00", "pct": 78.4, "litres": 1568 }]
    },
    "date2": {
      "date": "2026-11-05",
      "summary": { "avg_pct": 68.2, "min_pct": 24.5, "max_pct": 92.0, "consumption_l": 1150 },
      "points": [{ "time_slot": "14:00", "pct": 66.0, "litres": 1320 }]
    },
    "comparison": {
      "delta_avg_pct": 6.3,
      "delta_consumption_l": -330
    }
  }
}
```

### 9.5 `GET /api/backups` and `POST /api/backups/create`
Manages backup history and initiates manual backups.

**POST /api/backups/create Response (200 OK)**:
```json
{
  "status": "success",
  "message": "Backup generated successfully",
  "filename": "water_level_backup_20261106_143800.csv",
  "records_count": 4320,
  "file_size_bytes": 188416,
  "download_url": "/api/backups/download/water_level_backup_20261106_143800.csv"
}
```

---

## 10. Responsive Layout Specifications

### 10.1 Viewport Breakpoints
- **Mobile (< 640px)**: Single column fluid layout. Tank visualizer scales to max 260px width. Metric cards stack in 2x2 grid. Navigation tabs collapse into clean scrollable horizontal pill row or compact drawer. Touch targets $\ge 44 \times 44\text{ px}$.
- **Tablet (640px - 1024px)**: 2-column split. Left column: Tank visualization + live quick indicators. Right column: 4-card metric grid + Today's summary cards. History charts occupy full container width below.
- **Desktop (> 1024px)**: Multi-column grid. Left 35% pane hosts the industrial tank graphic and live sensor status. Right 65% pane hosts the live metrics grid, today's summary statistics, and interactive Chart.js analytics toolbar.

### 10.2 HTML5 DOM Layout Hierarchy
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>HydroSense - Smart Water Tank Monitor</title>
  <link rel="stylesheet" href="/static/css/main.css">
  <link rel="stylesheet" href="/static/css/tank.css">
  <link rel="stylesheet" href="/static/css/cards.css">
  <link rel="stylesheet" href="/static/css/tables.css">
</head>
<body class="theme-dark">
  <div class="app-container">
    <!-- Header Navigation -->
    <header class="app-header">
      <div class="header-brand">
        <div class="brand-logo">💧</div>
        <h1>HydroSense <span class="brand-sub">IoT Water Leveler</span></h1>
      </div>
      <div class="header-status">
        <div id="badge-device-status" class="status-badge status-online">
          <span class="status-dot"></span>
          <span class="status-label">ESP32 Online</span>
        </div>
        <div id="text-last-updated" class="status-timestamp">Updated: just now</div>
        <button id="btn-refresh-now" class="btn btn-icon" title="Refresh Now">🔄</button>
      </div>
    </header>

    <!-- Navigation Tabs -->
    <nav class="app-nav">
      <button class="nav-tab active" data-tab="tab-dashboard">Dashboard</button>
      <button class="nav-tab" data-tab="tab-analytics">15-Day Analytics</button>
      <button class="nav-tab" data-tab="tab-compare">Day Comparison</button>
      <button class="nav-tab" data-tab="tab-backups">Backups</button>
    </nav>

    <!-- Main Content Area -->
    <main class="app-main">
      <!-- TAB 1: Real-time Dashboard View -->
      <section id="tab-dashboard" class="tab-pane active">
        <div class="dashboard-grid">
          <!-- Left Visualizer Card -->
          <div class="card card-tank">
            <h2 class="card-title">Tank Live Level</h2>
            <div class="tank-wrapper">
              <!-- SVG Tank Graphic Included Here -->
            </div>
          </div>

          <!-- Right Telemetry & Metrics -->
          <div class="dashboard-metrics-pane">
            <div class="metrics-grid">
              <!-- Metric Card 1: Percentage -->
              <div class="card metric-card" id="card-pct">
                <span class="metric-label">Water Percentage</span>
                <div class="metric-value" id="val-pct">-- %</div>
                <div class="metric-status" id="pill-level-status">Normal</div>
              </div>
              <!-- Metric Card 2: Volume -->
              <div class="card metric-card" id="card-volume">
                <span class="metric-label">Water Volume</span>
                <div class="metric-value" id="val-litres">-- L</div>
                <span class="metric-sub" id="val-capacity">of 2,000 L Capacity</span>
              </div>
              <!-- Metric Card 3: Headroom -->
              <div class="card metric-card" id="card-headroom">
                <span class="metric-label">Remaining Empty</span>
                <div class="metric-value" id="val-headroom">-- L</div>
                <span class="metric-sub" id="val-distance">Sensor Gap: -- cm</span>
              </div>
              <!-- Metric Card 4: Device Health -->
              <div class="card metric-card" id="card-device">
                <span class="metric-label">Device Connectivity</span>
                <div class="metric-value" id="val-device-state">Active</div>
                <span class="metric-sub" id="val-device-ping">Last ping: --</span>
              </div>
            </div>

            <!-- Today's Summary Row (R3) -->
            <div class="card summary-card">
              <h3 class="card-title">Today's Summary</h3>
              <div class="summary-grid">
                <div class="summary-item">
                  <span class="sub-label">Min Level</span>
                  <strong id="today-min">-- %</strong>
                  <small id="today-min-time">--</small>
                </div>
                <div class="summary-item">
                  <span class="sub-label">Max Level</span>
                  <strong id="today-max">-- %</strong>
                  <small id="today-max-time">--</small>
                </div>
                <div class="summary-item">
                  <span class="sub-label">Average</span>
                  <strong id="today-avg">-- %</strong>
                  <small id="today-avg-l">-- L</small>
                </div>
                <div class="summary-item">
                  <span class="sub-label">Net Change</span>
                  <strong id="today-net">-- L</strong>
                  <small id="today-trend">--</small>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- TAB 2: 15-Day Analytics View -->
      <section id="tab-analytics" class="tab-pane">
        <div class="analytics-toolbar card">
          <div class="filter-group">
            <button class="btn btn-pill active" data-range="today">Today</button>
            <button class="btn btn-pill" data-range="yesterday">Yesterday</button>
            <button class="btn btn-pill" data-range="7d">Last 7 Days</button>
            <button class="btn btn-pill" data-range="15d">Past 15 Days</button>
            <div class="date-input-wrapper">
              <label for="history-date">Select Date:</label>
              <input type="date" id="history-date" class="form-control">
            </div>
          </div>
          <div class="action-group">
            <button id="btn-export-chart-png" class="btn btn-secondary">📷 Export PNG</button>
            <button id="btn-export-day-csv" class="btn btn-secondary">📄 Export CSV</button>
          </div>
        </div>

        <!-- Selected Date Stats Row -->
        <div class="card selected-day-stats">
          <h3 id="analytics-date-heading">Analytics for Chosen Date</h3>
          <div class="summary-grid" id="analytics-stats-grid">
            <!-- Dynamic stats filled by analytics.js -->
          </div>
        </div>

        <!-- Interactive Chart Card -->
        <div class="card chart-card">
          <div class="chart-container" style="position: relative; height: 380px;">
            <canvas id="analyticsChart"></canvas>
          </div>
        </div>
      </section>

      <!-- TAB 3: Day-to-Day Comparison View -->
      <section id="tab-compare" class="tab-pane">
        <div class="card comparison-toolbar">
          <div class="compare-selectors">
            <div class="form-group">
              <label for="compare-date-1">Date 1 (Primary):</label>
              <input type="date" id="compare-date-1" class="form-control">
            </div>
            <span class="vs-badge">VS</span>
            <div class="form-group">
              <label for="compare-date-2">Date 2 (Comparison):</label>
              <input type="date" id="compare-date-2" class="form-control">
            </div>
            <button id="btn-run-compare" class="btn btn-primary">Compare Days</button>
          </div>
        </div>

        <!-- Comparison Scorecard Table -->
        <div class="card comparison-results">
          <table class="table-compare" id="compare-table">
            <thead>
              <tr>
                <th>Metric</th>
                <th id="th-date-1">Date 1</th>
                <th id="th-date-2">Date 2</th>
                <th>Variance (Delta)</th>
              </tr>
            </thead>
            <tbody id="compare-tbody">
              <!-- Dynamically generated rows -->
            </tbody>
          </table>
        </div>

        <!-- Overlaid Comparison Chart -->
        <div class="card chart-card">
          <h3 class="card-title">Overlaid 24-Hour Comparison</h3>
          <div class="chart-container" style="position: relative; height: 380px;">
            <canvas id="compareChart"></canvas>
          </div>
        </div>
      </section>

      <!-- TAB 4: Backups Management View -->
      <section id="tab-backups" class="tab-pane">
        <div class="card backup-actions-card">
          <h3>Create Manual Backup</h3>
          <p class="text-secondary">Export water level sensor records directly to CSV or JSON format.</p>
          <div class="backup-form">
            <div class="form-inline">
              <label>Format:</label>
              <select id="backup-format" class="form-control">
                <option value="csv">CSV (Spreadsheet compatible)</option>
                <option value="json">JSON (Full document)</option>
              </select>
            </div>
            <div class="form-inline">
              <label>Scope:</label>
              <select id="backup-scope" class="form-control">
                <option value="all">All Historical Records</option>
                <option value="15d">Past 15 Days</option>
              </select>
            </div>
            <button id="btn-trigger-backup" class="btn btn-success">⬇ Create & Download Backup</button>
          </div>
        </div>

        <div class="card backup-logs-card">
          <h3>Backup History</h3>
          <div class="table-responsive">
            <table class="table-backups" id="backups-table">
              <thead>
                <tr>
                  <th>Timestamp (UTC)</th>
                  <th>Filename</th>
                  <th>Format</th>
                  <th>Records</th>
                  <th>Size</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody id="backups-tbody">
                <!-- Dynamically populated -->
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </main>

    <!-- Footer -->
    <footer class="app-footer">
      <span>HydroSense IoT Water Leveler &bull; PythonAnywhere Deployment</span>
    </footer>
  </div>

  <!-- Local Vendored Chart.js (with CDN fallback if needed) -->
  <script src="/static/vendor/chart.umd.min.js"></script>
  <!-- Application Scripts -->
  <script src="/static/js/api.js"></script>
  <script src="/static/js/tank-visualizer.js"></script>
  <script src="/static/js/chart-controller.js"></script>
  <script src="/static/js/polling.js"></script>
  <script src="/static/js/analytics.js"></script>
  <script src="/static/js/backups.js"></script>
  <script src="/static/js/app.js"></script>
</body>
</html>
```

---

## 11. Offline Fallback, Performance & Edge Cases

### 11.1 Network Disconnection Handling
- When consecutive poll failures reach 3:
  - Header badge transitions to `Reconnecting...` (Yellow badge).
  - Tank graphic maintains last known reading but softens glow to reflect paused live feed.
  - Non-blocking toast notification alerts user: *"Connection to server interrupted. Reconnecting automatically..."*
- When connection restores:
  - Badge switches back to `Online` (Green).
  - Immediate poll executes, syncing all UI elements.

### 11.2 Empty Database / First-Run Initialization
- If the database contains 0 readings:
  - Metric values display `Waiting for first sensor reading...`.
  - Tank level shows 0% with dashed water surface.
  - A friendly setup guidance card guides the user to verify ESP32 Wi-Fi configuration and API URL.

### 11.3 Extreme Outlier & Sensor Error Protection
- Physical constraints validated client-side:
  - Water percentage clamped between `0.0%` and `100.0%`.
  - Negative litres clamped to `0.0 L`.
  - Values exceeding tank capacity clamped to `capacity L` with a warning indicator.
  - If sensor reports erratic jumps (e.g. 10% to 90% in 5 seconds without pump capacity), the system flags reading with a minor warning icon.

---

## 12. Verification and Testing Strategy for Implementers

| Component | Target Acceptance Criteria | Verification Method |
| :--- | :--- | :--- |
| **Tank Graphic** | Linear fill mapping 0-100%, smooth wave animation, color state transitions | Simulate readings across 5%, 35%, 75%, and filling states via browser console `window.tankVisualizer.update(...)`. |
| **Polling Engine** | Auto-updates every 5s, throttles on background tab | Verify network tab activity; minimize browser tab and observe poll delay throttle to 30s. |
| **Today's Summary** | Accurately calculates Min, Max, Avg, and Net Change | Verify calculation against SQLite database query for today's timestamps. |
| **15-Day Chart** | Date picker restricted to 15 days, smooth curve, tooltip with %, L, and cm | Select multiple dates; verify Chart.js renders data without canvas redraw memory leaks. |
| **Day Comparison** | Side-by-side table + overlaid 24h dual line chart | Compare today vs yesterday; inspect synchronized tooltips and delta calculations. |
| **Backup UI** | Instant CSV/JSON generation and immediate browser download | Click "Create & Download Backup"; verify file download initiates and record appears in history table. |
| **Responsive UI** | Mobile, tablet, and desktop display consistency | Test viewports in Chrome DevTools (360px, 768px, 1280px, 1920px). |

---

## 13. Summary of Deliverables & Next Steps

This survey establishes the complete blueprint for R3 (Web Dashboard and Level Visualization) and R4 (15-Day History and Analytics), along with R5's Backup Management UI:
1. Pure zero-build Vanilla JS, HTML5, CSS3, and Chart.js 4.x stack suited for PythonAnywhere.
2. Complete SVG markup, CSS animations, and JavaScript controller for the dynamic tank graphic.
3. Fully specified API contracts compatible with Flask backend architecture.
4. Complete DOM layout and CSS styling guidelines ready for implementation.
