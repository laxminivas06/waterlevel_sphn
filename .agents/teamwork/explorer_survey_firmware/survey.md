# Technical Survey & Firmware Architecture Specification: ESP32 Water Level Monitoring System (R1)

**Author:** explorer_survey_firmware (Firmware & Sensor Explorer)  
**Date:** 2026-11-06  
**Target Milestone:** Survey & Specifications  
**Governing Documents:** `.agents/teamwork/ORIGINAL_REQUEST.md`, System Requirements R1-R6  

---

## 1. Executive Summary & Problem Scope

The objective of Requirement R1 is to engineer production-ready, fault-tolerant firmware for an **ESP32 NodeMCU microcontroller** to perform continuous, automated water-level measurements in residential, commercial, or industrial storage tanks. The firmware is strictly constrained to **monitoring only**: it contains **no motor, pump, or relay control logic**, preventing unintentional actuation, hazardous dry runs, or overflow risks.

### Core Capabilities
1. **Accurate Ultrasonic Telemetry**: High-precision distance measurement using ultrasonic echo timing, supporting both standard indoor (HC-SR04) and industrial waterproof (JSN-SR04T) sensors.
2. **Multi-Stage Acoustic Noise Filtering**: Robust rejection of false echoes, acoustic multipath reflections off tank walls, water agitation ripples, and transient dropouts using a combination of burst sampling, physical range screening, statistical median filtering, delta-outlier pruning, and exponential moving average (EMA) smoothing.
3. **Multi-Geometry Tank Mathematics**: Real-time conversion of raw distance readings into:
   - Distance to liquid surface ($D$, in cm)
   - Water level ($H_{water}$, in cm)
   - Fill percentage ($P_{fill}$, $0.0\% - 100.0\%$)
   - Liquid volume ($V_{litres}$, in litres) for Rectangular Cuboids, Vertical Cylinders, and Horizontal Cylinders.
4. **Resilient Network Communication**: Non-blocking asynchronous Wi-Fi state machine with automatic reconnection and exponential backoff, coupled with HTTPS POST transmission to PythonAnywhere backend endpoints (`/api/water-level`), complete with API key authentication, transmission retry buffering, and watchdog protection.

---

## 2. Hardware Architecture & Electrical Design

### 2.1 Microcontroller Selection: ESP32 NodeMCU
The ESP32 (ESP32-WROOM-32 / NodeMCU-32S) provides substantial technical advantages for IoT telemetry:
- **Core Architecture**: Xtensa® dual-core 32-bit LX6 microprocessor operating at 160MHz or 240MHz, offering microsecond-level hardware timer resolution for acoustic pulse timing (`pulseIn()` or ESP32 high-resolution timer `esp_timer_get_time()`).
- **Memory**: 520 KB internal SRAM allows in-memory buffering of telemetry readings during Wi-Fi outages.
- **Wireless Subsystem**: Integrated 802.11 b/g/n 2.4 GHz Wi-Fi with WPA/WPA2-PSK security.
- **Hardware Watchdog Timer (WDT)**: Integrated interrupt watchdog and task watchdog ensure autonomous recovery from unhandled network stalls or bus lockups.

### 2.2 Ultrasonic Sensor Comparison: JSN-SR04T vs. HC-SR04

| Parameter | HC-SR04 (Standard) | JSN-SR04T (Waterproof Industrial) | Recommendation |
| :--- | :--- | :--- | :--- |
| **Enclosure / Environmental** | Open transducer cones; susceptible to condensation and moisture corrosion | IP67 sealed waterproof probe on 2.5m/5m coaxial lead; separate transceiver board | **JSN-SR04T is strongly recommended for water tanks.** HC-SR04 for bench prototyping. |
| **Operating Voltage** | 5.0 V DC (some clones work at 3.3V, but range degrades) | 3.0 V to 5.5 V DC (v2.0 requires 5V for acoustic emission; v3.0 supports 3.3V) | Run transceiver module from 5V (VIN / USB 5V bus) to guarantee maximum ultrasonic power. |
| **Effective Range** | 2 cm to 400 cm | 20 cm to 600 cm | JSN-SR04T covers up to 6-meter tank depths. |
| **Blind Zone (Dead Band)** | ~2 cm to 3 cm | **20 cm to 25 cm** | **Critical**: Sensor transducer must be mounted at least 20 cm above the maximum water level ($H_{offset} \ge 20 \text{ cm}$). |
| **Beam Angle** | ~15° conical beam | ~45° to 75° wide cone | Wider beam requires central placement on tank lid to prevent premature echoes off side walls or baffles. |
| **Echo Output Logic Level** | 5.0 V TTL | 5.0 V TTL (when powered at 5V) | **Mandatory Level Shifter or Voltage Divider** before connecting to ESP32 GPIO! |

### 2.3 Electrical Schematics & Level Shifting

ESP32 GPIO pins operate at **3.3V CMOS logic** and are **NOT 5V-tolerant**. Connecting an ultrasonic sensor's 5V Echo pin directly to an ESP32 pin can cause permanent gate oxide degradation or latch-up.

#### Voltage Divider on Echo Pin
A standard passive resistor divider steps down the 5.0V Echo output to a safe 3.33V level:
```
                5V Power Rail (ESP32 VIN / External 5V)
                        │
                  ┌─────┴─────┐
                  │ Sensor    │
                  │ JSN-SR04T │
                  │ / HC-SR04 │
                  └─────┬─────┘
    ESP32 GPIO 5 ───────┤ TRIG (3.3V logic high triggers 5V sensor reliably >2.4V)
                        │
                        │ ECHO (5.0V pulse output)
                        │
                       ┌┴┐
                       │ │ R1 = 1.0 kΩ (1% tolerance)
                       └┬┘
                        ├───> ESP32 GPIO 18 (Safe 3.33V logic input)
                       ┌┴┐
                       │ │ R2 = 2.0 kΩ (or 1.8 kΩ / 2.2 kΩ)
                       └┬┘
                        │
                       ─┴─ GND (Common Ground between ESP32 and Sensor)
```

**Voltage calculation**:
$$V_{out} = V_{in} \times \frac{R_2}{R_1 + R_2} = 5.0\text{V} \times \frac{2000}{1000 + 2000} = 3.33\text{V}$$
*(Alternative: $R_1 = 2.2\text{ k}\Omega$, $R_2 = 3.3\text{ k}\Omega \implies V_{out} = 5.0 \times \frac{3300}{5500} = 3.0\text{V}$, also cleanly above the $0.75 \times V_{DD} = 2.475\text{V}$ high-level threshold).*

### 2.4 Complete Pinout Mapping

| ESP32 Pin | Function | Direction | Electrical Notes |
| :--- | :--- | :--- | :--- |
| **GPIO 5** | `PIN_TRIG` | OUTPUT | 10 µs active-HIGH pulse initiates ultrasonic burst. Default LOW. |
| **GPIO 18** | `PIN_ECHO` | INPUT | Measures pulse width proportional to time of flight. Connected through 1kΩ/2kΩ voltage divider. |
| **GPIO 2** | `PIN_STATUS_LED`| OUTPUT | Onboard blue LED. Single blink on successful reading/post; rapid flash on Wi-Fi connect; solid on fatal error. |
| **VIN / 5V** | 5V Power Out | POWER | Supplies 5V DC to JSN-SR04T / HC-SR04 transceiver module (when powered via USB 5V). |
| **GND** | Ground | POWER | Common reference ground for ESP32 and sensor. |

#### Strict Safety Mandate: Monitoring Only
- **Zero Motor / Relay Pins**: No GPIO pins are configured, declared, or toggled for actuators, pumps, solenoids, or mechanical relays.
- **Code Audit Guarantee**: The firmware contains no relay driver classes, no PWM motor control code, and no pump switching logic.

---

## 3. Sensor Reading Pipeline & Signal Processing

### 3.1 Physics of Measurement & Acoustic Timing
An ultrasonic ping is initiated by emitting a $10\,\mu\text{s}$ digital `HIGH` pulse on `PIN_TRIG`. The sensor transmits an 8-cycle $40\,\text{kHz}$ ultrasonic wave and drives `PIN_ECHO` `HIGH` until the reflected wave returns:
$$\Delta t = \text{Time of Flight (round trip duration in microseconds)}$$

#### Temperature-Compensated Speed of Sound
The speed of sound in dry air varies with ambient temperature $T$ (°C):
$$v_{sound}(T) = 331.3 + (0.606 \times T) \quad [\text{m/s}]$$
Converted to $\text{cm}/\mu\text{s}$:
$$v_{sound}(T) = \frac{331.3 + 0.606 \times T}{10,000} \quad [\text{cm}/\mu\text{s}]$$
For a default ambient temperature of $25.0^\circ\text{C}$:
$$v_{sound}(25^\circ\text{C}) = 331.3 + (0.606 \times 25.0) = 346.45\text{ m/s} = 0.034645\text{ cm}/\mu\text{s}$$
The one-way distance to the water surface is:
$$D = \frac{\Delta t \times v_{sound}(T)}{2} = \Delta t \times 0.0173225 \quad [\text{cm}]$$

### 3.2 Signal Degradation Factors in Water Tanks
Water storage tanks present unique acoustic challenges:
1. **Wall Echo Multipath**: Acoustic waves reflect off tank sidewalls, ladders, or structural ribs, producing premature echo returns.
2. **Surface Agitation**: Inflow currents and turbulence produce angled reflections that scatter sound away from the receiver, causing pulse timeouts ($0\,\mu\text{s}$ or max timeout).
3. **Moisture Droplets**: Condensation on the transducer face causes momentary acoustic attenuation or erratic near-zero readings.
4. **Sensor Blind Zone Deadband**: If water rises within $20\,\text{cm}$ of a JSN-SR04T probe, the transducer is still ringing when the echo arrives, returning false $200+\,\text{cm}$ or erratic values.

### 3.3 Multi-Stage Filtering Algorithm Architecture

To produce rock-solid, jitter-free water level readings, the firmware executes a 5-stage digital filtering pipeline:

```
[Raw Ultrasonic Pings]
       │
       ▼ (Stage 1: Burst Sampling, N=9 pulses spaced 45ms apart)
[Burst Vector d[0..8]]
       │
       ▼ (Stage 2: Range & Timeout Validation: discard d <= 0 or d > D_max)
[Valid Samples Subarray]
       │
       ▼ (Stage 3: Statistical Median Filter: sort valid samples, pick middle value)
[Candidate Median D_med]
       │
       ▼ (Stage 4: Outlier Pruning: reject samples where |d_i - D_med| > Delta_max)
[Pruned Samples Array -> Arithmetic Mean of remaining]
       │
       ▼ (Stage 5: Inter-Cycle Exponential Moving Average: S_t = alpha*Y_t + (1-alpha)*S_{t-1})
[Stable Filtered Distance D_filtered]
```

#### Detailed Stage Specifications
1. **Stage 1 — Burst Sampling**: At each measurement interval (e.g. every 30 seconds), the firmware does not rely on a single ping. It samples a burst of $N = 9$ successive pings. A **$45\,\text{ms}$ inter-ping pause** allows residual acoustic reverberations inside the tank to dissipate completely before the next pulse.
2. **Stage 2 — Range Gate Screening**: Each raw pulse is checked against physical plausibility:
   $$D_{min\_valid} = D_{blind\_zone} \times 0.8 \quad (\approx 15\,\text{cm for JSN-SR04T})$$
   $$D_{max\_valid} = (H_{tank} + H_{offset}) \times 1.25$$
   Any sample outside $[D_{min\_valid}, D_{max\_valid}]$ (including $0\,\mu\text{s}$ timeouts) is immediately discarded as invalid.
3. **Stage 3 — Statistical Median Filtering**: Valid samples are sorted in ascending order. The median value $D_{med}$ is selected. Unlike an arithmetic mean, the median completely ignores catastrophic outliers (e.g., if 8 samples read $\approx 45\,\text{cm}$ and 1 sample reads $380\,\text{cm}$ due to echo loss, the mean would be distorted to $82\,\text{cm}$, whereas the median remains cleanly at $45\,\text{cm}$).
4. **Stage 4 — Delta Outlier Pruning**: All valid samples in the burst with $|d_i - D_{med}| \le \Delta_{threshold}$ (where $\Delta_{threshold} = 5.0\,\text{cm}$) are retained, and their average is computed to refine sub-centimeter resolution:
   $$D_{burst} = \frac{1}{M}\sum_{k=1}^{M} d_k$$
5. **Stage 5 — Exponential Moving Average (EMA)**: To prevent abrupt visual jumping across consecutive telemetry cycles, an EMA filter is applied:
   $$D_{filtered}(t) = \alpha \cdot D_{burst}(t) + (1 - \alpha) \cdot D_{filtered}(t-1)$$
   With $\alpha = 0.35$, steady-state noise is suppressed while tank filling/draining events are tracked within 2 to 3 reading intervals. (On initial system boot or after prolonged offline state, $\alpha = 1.0$ is forced to lock onto the current level instantly).

---

## 4. Tank Geometry & Volume Mathematics

### 4.1 Tank Coordinate Reference Frame

```
  ┌───────────────────────────────────────────┐  ▲
  │   [ Ultrasonic Sensor Face ]              │  │
  │                   │                       │  │ H_offset (Sensor mounting height above 100% line)
  │~~~~~~~~~~~~~~~~~~~▼~~~~~~~~~~~~~~~~~~~~~~~│  ▼  (e.g., 25 cm >= 20 cm blind zone)
  │===========================================│ ─── 100% Water Fill Line (H_water = H_tank)
  │                                           │  ▲
  │                                           │  │
  │                                           │  │
  │           WATER IN TANK                   │  │ H_water (Actual water column height in cm)
  │                                           │  │
  │                                           │  │
  │                                           │  │
  │                                           │  │ H_tank (Total usable internal height in cm)
  │                                           │  ▼
  └───────────────────────────────────────────┘ ─── 0% Water Fill Line (Tank Bottom)
```

### 4.2 Derived Level & Percentage Equations

1. **Water Level in Centimetres ($H_{water}$)**:
   $$H_{water} = (H_{tank} + H_{offset}) - D_{filtered}$$
2. **Boundary Clamping & Physical Constraints**:
   - **Full / Overflow Condition**: If $D_{filtered} \le H_{offset}$, the water level has reached or exceeded the nominal maximum height:
     $$H_{water} = H_{tank}$$
   - **Blind Zone Warning**: If $D_{filtered} < D_{blind\_zone}$, a diagnostic warning flag `blind_zone_alert = true` is flagged, indicating water is within the uncalibrated sensor dead zone.
   - **Empty Condition**: If $D_{filtered} \ge (H_{tank} + H_{offset})$, the tank is dry:
     $$H_{water} = 0.0\,\text{cm}$$
   - Intermediate values are clamped strictly:
     $$H_{water} = \max(0.0, \min(H_{tank}, H_{water}))$$
3. **Water Percentage ($P_{water}$)**:
   $$P_{water} = \left(\frac{H_{water}}{H_{tank}}\right) \times 100.0$$
   Clamped strictly to $[0.0, 100.0]\%$, formatted to 1 decimal place.

### 4.3 Volumetric Formulas by Tank Shape

#### Shape 1: Rectangular Cuboid Tank
- **Parameters**: Length $L$ ($\text{cm}$), Width $W$ ($\text{cm}$), Height $H_{tank}$ ($\text{cm}$).
- **Formula**:
  $$V_{water} = \frac{L \times W \times H_{water}}{1000.0} \quad [\text{Litres}]$$
- **Total Capacity**:
  $$V_{capacity} = \frac{L \times W \times H_{tank}}{1000.0} \quad [\text{Litres}]$$

#### Shape 2: Vertical Cylindrical Tank (Common Overhead / Sintex Tank)
- **Parameters**: Internal Radius $R$ ($\text{cm}$) or Diameter $D_{tank}$ ($\text{cm}$, where $R = D_{tank}/2$), Height $H_{tank}$ ($\text{cm}$).
- **Formula**:
  $$V_{water} = \frac{\pi \times R^2 \times H_{water}}{1000.0} \quad [\text{Litres}]$$
- **Total Capacity**:
  $$V_{capacity} = \frac{\pi \times R^2 \times H_{tank}}{1000.0} \quad [\text{Litres}]$$

#### Shape 3: Horizontal Cylindrical Tank
- **Parameters**: Internal Radius $R$ ($\text{cm}$), Length $L$ ($\text{cm}$).
- **Cross-Sectional Liquid Area**:
  The liquid cross-section is a circular segment of height $H_{water}$ in a circle of radius $R$:
  $$A(H_{water}) = R^2 \arccos\left(\frac{R - H_{water}}{R}\right) - (R - H_{water})\sqrt{2R \cdot H_{water} - H_{water}^2} \quad [\text{cm}^2]$$
  *(Where $\arccos$ evaluates in radians).*
- **Volume**:
  $$V_{water} = \frac{A(H_{water}) \times L}{1000.0} \quad [\text{Litres}]$$

---

## 5. Networking & Telemetry Architecture

### 5.1 Asynchronous Wi-Fi Reconnection State Machine
Synchronous blocking calls like `while (WiFi.status() != WL_CONNECTED) delay(500);` cause ESP32 lockups, trigger hardware watchdog resets, and halt sensor telemetry.

The firmware implements a **non-blocking Finite State Machine (FSM)**:

```
    ┌──────────────────────┐
    │     WIFI_IDLE        │
    └──────────┬───────────┘
               │ WiFi.begin()
               ▼
    ┌──────────────────────┐
    │   WIFI_CONNECTING    │◄─────────────────┐
    └──────────┬───────────┘                  │
        │      │                              │
        │Timeout                              │
        │(15s) │ Connected                    │
        │      ▼                              │
        │   ┌──────────────────────┐          │ Backoff elapsed
        │   │    WIFI_CONNECTED    │          │
        │   └──────────┬───────────┘          │
        │              │ Connection Lost      │
        ▼              ▼                      │
    ┌───────────────────────────────────┐     │
    │        WIFI_WAIT_RETRY            ├─────┘
    │  Exponential Backoff: 5s -> 60s   │
    └───────────────────────────────────┘
```

#### Reconnection Logic Specifications
1. **Connection Timeout**: Maximum duration in `WIFI_CONNECTING` before fallback is 15 seconds.
2. **Exponential Backoff with Jitter**:
   $$\text{Backoff Interval} = \min(60\,\text{s}, 5\,\text{s} \times 2^{\text{attempt}}) + \text{random}(0, 2000\,\text{ms})$$
   Prevents Wi-Fi router packet flooding when recovering from access point reboots.
3. **Asynchronous Check in Main Loop**: Sensor readings continue to be processed and filtered on schedule even when Wi-Fi is disconnected.

### 5.2 Offline Reading Buffer / Retry Queue
When Wi-Fi or backend connectivity is temporarily down:
- The firmware stores the latest readings in a **circular FIFO queue** of size $K = 20$ in ESP32 SRAM.
- Each buffered element stores: `timestamp_offset`, `distance_cm`, `water_level_cm`, `water_percentage`, `water_litres`.
- When connectivity is restored, the buffered queue is flushed to the backend API or the latest consolidated telemetry packet is immediately dispatched.

### 5.3 HTTPS Client Configuration for PythonAnywhere
PythonAnywhere web applications mandate HTTPS (`https://<username>.pythonanywhere.com`).
The ESP32 uses `WiFiClientSecure` to negotiate TLS 1.2 / TLS 1.3:
```cpp
#include <WiFiClientSecure.h>
#include <HTTPClient.h>

WiFiClientSecure secureClient;
// Option A: Skip strict CA cert chain verification to preserve 30KB+ SRAM
secureClient.setInsecure();

// Option B: Provide ISRG Root X1 (Let's Encrypt CA root) for hardened enterprise setups
// secureClient.setCACert(LETS_ENCRYPT_CA_CERT);
```
- Timeout is configured to $8000\,\text{ms}$ (`client.setTimeout(8000)`) to prevent stalled socket connections from delaying the main loop.

---

## 6. HTTP API Payload & Backend Contract

### 6.1 Target Ingestion Endpoint
- **URL**: `https://<pythonanywhere_host>/api/water-level`
- **Method**: `POST`
- **Headers**:
  ```http
  Content-Type: application/json
  X-API-Key: <configured_device_api_key>
  User-Agent: ESP32-WaterLeveler/1.0
  ```

### 6.2 Strict JSON Payload Schema
The payload is designed to be fully compatible with Requirement R2 and `spec_miner_survey_backend`:

```json
{
  "device_id": "esp32_water_leveler_01",
  "distance_cm": 45.2,
  "water_level_cm": 154.8,
  "water_percentage": 77.4,
  "water_litres": 1548.0,
  "api_key": "YOUR_SECRET_DEVICE_KEY"
}
```

#### Dual Authentication Compatibility
To ensure maximum compatibility with the backend API implementation:
1. `X-API-Key` is passed in the **HTTP Header**.
2. `api_key` is also included in the **JSON request body**.
This guarantees immediate acceptance regardless of whether the Flask backend inspects `request.headers.get('X-API-Key')` or `request.json.get('api_key')`.

### 6.3 HTTP Response Handling & Retry Strategy

| HTTP Status Code | Firmware Action |
| :--- | :--- |
| **200 OK / 201 Created** | Transmission successful. Blink Status LED (100ms). Reset error and retry counters. Flush buffer item. |
| **400 Bad Request / 422 Unprocessable** | Payload validation rejected by backend (e.g. negative distance or impossible percentage). Log payload over Serial. **Do not retry identical invalid packet.** |
| **401 Unauthorized / 403 Forbidden** | API Key rejected by backend. Log fatal auth error over Serial. Rapid flash Status LED. Pause transmission for 5 minutes. |
| **500 Internal Error / 502 / 503 / 504** | Backend transient server error. Push reading to retry queue. Retry with backoff. |
| **Connection Timeout / Socket Error** | Network dropped or PythonAnywhere request timeout. Mark device as offline; enter retry state. |

---

## 7. Firmware Configuration Parameters Catalog

The firmware encapsulates all hardware, network, tank geometry, and calibration constants in a dedicated header file (`config.h`), enabling field customization without code modifications:

```cpp
#ifndef CONFIG_H
#define CONFIG_H

// ==========================================
// 1. Wi-Fi & Network Credentials
// ==========================================
#define WIFI_SSID           "YOUR_WIFI_SSID"
#define WIFI_PASSWORD       "YOUR_WIFI_PASSWORD"
#define WIFI_CONNECT_TIMEOUT_MS 15000
#define WIFI_RETRY_INTERVAL_MS   5000

// ==========================================
// 2. Backend API Configuration
// ==========================================
#define API_BASE_URL        "https://yourusername.pythonanywhere.com"
#define API_ENDPOINT        "/api/water-level"
#define API_KEY             "your_secret_device_api_key_123"
#define DEVICE_ID           "esp32_water_leveler_01"
#define HTTP_TIMEOUT_MS     8000

// ==========================================
// 3. Hardware Pinout Configuration
// ==========================================
#define PIN_TRIG            5    // Output to ultrasonic TRIG
#define PIN_ECHO            18   // Input from ultrasonic ECHO (via 1k/2k divider)
#define PIN_STATUS_LED      2    // Built-in Blue LED

// ==========================================
// 4. Sensor Timing & Environmental Calibration
// ==========================================
#define READING_INTERVAL_MS 30000 // Telemetry period (30 seconds)
#define BURST_SAMPLE_COUNT  9     // Samples per burst measurement
#define BURST_DELAY_MS      45    // Inter-pulse settling delay in ms
#define AMBIENT_TEMP_C      25.0f // Ambient temperature for speed of sound (25°C)
#define SENSOR_BLIND_ZONE_CM 20.0f// JSN-SR04T blind zone: 20cm; HC-SR04: 3cm

// ==========================================
// 5. Tank Geometry Configuration
// ==========================================
// Shape selection: 1 = RECTANGULAR, 2 = VERTICAL_CYLINDER, 3 = HORIZONTAL_CYLINDER
#define TANK_SHAPE          2

#define TANK_HEIGHT_CM      200.0f // Internal depth from bottom to 100% water line
#define SENSOR_OFFSET_CM    25.0f  // Transducer face distance above 100% water line

// Dimensions for Rectangular Tank (TANK_SHAPE == 1)
#define TANK_LENGTH_CM      120.0f
#define TANK_WIDTH_CM       100.0f

// Dimensions for Cylindrical Tank (TANK_SHAPE == 2 or 3)
#define TANK_RADIUS_CM      56.42f // Radius (r = sqrt(10000/pi) ~= 56.42 cm for 2000L tank)
#define TANK_CYL_LENGTH_CM  200.0f // Used if HORIZONTAL_CYLINDER

// ==========================================
// 6. Signal Filtering Parameters
// ==========================================
#define FILTER_DELTA_MAX_CM 5.0f  // Max deviation from median allowed in burst
#define FILTER_EMA_ALPHA    0.35f // Exponential smoothing factor (0.0 to 1.0)

#endif // CONFIG_H
```

---

## 8. Modular Firmware Architecture & Source Structure

To adhere to embedded engineering best practices, the firmware is structured into clean, decoupled modules:

```
water_leveler_firmware/
├── water_leveler_firmware.ino   # Main setup(), loop(), task orchestrator
├── config.h                     # User configuration, pins, credentials, geometry
├── SensorManager.h              # Ultrasonic pulse generation, burst sampling
├── SensorManager.cpp            # Median filter, outlier pruning, EMA filter
├── TankCalculator.h             # Tank geometry models, volume & percentage math
├── TankCalculator.cpp           # Cuboid and cylinder volumetric algorithms
├── NetworkManager.h             # Non-blocking Wi-Fi state machine
├── NetworkManager.cpp           # HTTPS client, JSON serializer, retry queue
└── StatusLED.h                  # Diagnostic LED pattern controller
```

### Module Responsibilities
- **`SensorManager`**: Issues the $10\,\mu\text{s}$ trigger pulse, reads echo microseconds, computes temperature-compensated distance, performs burst sampling, applies median and outlier pruning, and maintains the inter-epoch EMA state.
- **`TankCalculator`**: Pure mathematical engine. Consumes `distance_cm` and outputs `water_level_cm`, `water_percentage`, and `water_litres` based on configured geometry.
- **`NetworkManager`**: Manages the non-blocking Wi-Fi FSM, encapsulates JSON payloads using `ArduinoJson` (or a lightweight zero-allocation `snprintf` serializer), dispatches HTTPS POST requests, parses response codes, and manages the retry ring buffer.
- **`StatusLED`**: Non-blocking LED flasher (`millis()` based) to give instant visual feedback on device state without stalling timing.

---

## 9. Verification & Toolchain Integration

### 9.1 Local Compiler & Build Verification
Local environment reconnaissance confirmed:
- **Arduino CLI Executable**: `C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe`
- **Installed ESP32 Cores**: `esp32:esp32 3.3.11` and `arduino:esp32 2.0.18-arduino.5`
- **Installed Library**: `ArduinoJson 7.4.3`

During implementation, the firmware can be compiled and validated against the exact ESP32 core using:
```powershell
& "C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe" compile `
    --fqbn esp32:esp32:esp32 `
    --warnings all `
    --output-dir .\build `
    .\water_leveler_firmware
```

### 9.2 Host-Side Simulation & Payload Verification Harness
To verify sensor calculation logic and payload compatibility before physical flashing:
A Python-based simulation script (`tests/simulate_firmware_payload.py`) will be provided to:
1. Replicate the C++ mathematical formulas for rectangular and cylindrical tanks.
2. Simulate synthetic sensor burst readings (including jitter, noise spikes, and dropouts) and verify that the median + outlier filter rejects 100% of bogus spikes.
3. Transmit generated JSON payloads to the Flask API endpoint (`POST /api/water-level`) to verify end-to-end backend ingestion compatibility.

---

## 10. Architectural Recommendations & Next Steps

1. **Adopt JSN-SR04T Sensor with Raised Mounting Collar**:
   Because JSN-SR04T has a $20\,\text{cm}$ blind zone, the physical sensor mount should be placed in an elevated collar or tube at least $25\,\text{cm}$ above the overflow line ($H_{offset} = 25.0\,\text{cm}$). This guarantees that even when the tank is at 100% capacity, the distance to the water surface ($25\,\text{cm}$) remains outside the blind zone.
2. **Dual-Path Authentication**:
   Always send the API key both in the `X-API-Key` HTTP header and in the JSON body (`api_key`). This guarantees seamless compatibility with any backend validation pattern.
3. **Zero-Actuation Design Guarantee**:
   The firmware code will contain zero references to motors, pumps, relays, or actuators. All logic is strictly unidirectional read-and-report.
4. **Resilient HTTPS on PythonAnywhere**:
   Because PythonAnywhere enforces HTTPS on all web apps, `WiFiClientSecure` with `setInsecure()` is the recommended standard configuration for the ESP32 firmware, minimizing RAM overhead and avoiding TLS certificate expiry issues.
