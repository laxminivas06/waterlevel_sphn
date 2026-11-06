/**
 * config.h - Smart Water Tank Level Monitoring System Configuration
 *
 * Central configuration header defining Wi-Fi credentials, backend API endpoints,
 * hardware pin mapping, ultrasonic sensor filter settings, and tank geometry parameters.
 *
 * ============================================================================
 * STRICT SAFETY GUARANTEE:
 * This system is STRICTLY for monitoring. There are NO motor, pump, or relay
 * control pins, functions, or actuation logic present in this codebase.
 * ============================================================================
 */

#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h>

// ============================================================================
// 1. Wi-Fi Network Credentials & Connection Settings
// ============================================================================
#define WIFI_SSID               "YOUR_WIFI_SSID"
#define WIFI_PASSWORD           "YOUR_WIFI_PASSWORD"
#define WIFI_CONNECT_TIMEOUT_MS 15000UL      // Max wait for initial Wi-Fi connection
#define WIFI_BACKOFF_MIN_MS     5000UL       // Initial reconnect backoff delay (5s)
#define WIFI_BACKOFF_MAX_MS     60000UL      // Maximum exponential reconnect backoff (60s)

// ============================================================================
// 2. Backend API Endpoint & Device Authentication
// ============================================================================
// Configured server endpoint (HTTP or HTTPS supported)
#define BACKEND_API_URL         "http://192.168.1.100:5000/api/water-level"
#define DEVICE_ID               "esp32_tank_01"
#define API_KEY                 "water_secret_key_2026"
#define HTTP_TIMEOUT_MS         8000UL       // Socket timeout for HTTP/HTTPS requests
#define RETRY_QUEUE_CAPACITY    20           // Circular buffer size for offline telemetry packets

// ============================================================================
// 3. Hardware Pinout Configuration
// ============================================================================
#define PIN_TRIGGER             5            // ESP32 GPIO 5 -> Ultrasonic TRIG
#define PIN_ECHO                18           // ESP32 GPIO 18 <- Ultrasonic ECHO (via 1k/2k voltage divider)
#define PIN_STATUS_LED          2            // ESP32 GPIO 2 -> On-board diagnostic LED

// NOTE: Zero actuator pins. No relay, pump, or motor output pins configured.

// ============================================================================
// 4. Ultrasonic Sensor & 5-Stage Digital Filter Parameters
// ============================================================================
#define TELEMETRY_INTERVAL_MS   5000UL       // Telemetry reporting period (5 seconds)
#define BURST_SAMPLE_COUNT      9            // Stage 1: Burst count N=9
#define BURST_SAMPLE_DELAY_MS   40UL         // Inter-pulse settling delay (ms)
#define SENSOR_MIN_DISTANCE_CM  2.0f         // Stage 2: Physical screening lower bound (cm)
#define SENSOR_MAX_DISTANCE_CM  400.0f       // Stage 2: Physical screening upper bound (cm)
#define OUTLIER_DELTA_MAX_CM    8.0f         // Stage 4: Outlier delta cutoff around median (cm)
#define EMA_ALPHA               0.35f        // Stage 5: Exponential moving average factor
#define AMBIENT_TEMPERATURE_C  25.0f        // Default ambient temperature for speed of sound

// ============================================================================
// 5. Tank Geometry & Volumetric Calibration
// ============================================================================
// Tank shapes:
//   0 = TANK_SHAPE_RECTANGULAR       (Cuboid / rectangular tank)
//   1 = TANK_SHAPE_VERTICAL_CYLINDER (Vertical Sintex / overhead cylindrical tank)
//   2 = TANK_SHAPE_HORIZONTAL_CYLINDER (Horizontal cylindrical tanker)
#define TANK_SHAPE_RECTANGULAR          0
#define TANK_SHAPE_VERTICAL_CYLINDER    1
#define TANK_SHAPE_HORIZONTAL_CYLINDER  2

#define DEFAULT_TANK_SHAPE              TANK_SHAPE_VERTICAL_CYLINDER

#define TANK_HEIGHT_CM          200.0f       // Usable internal height of tank (cm)
#define SENSOR_OFFSET_CM        15.0f        // Sensor transducer mounting offset above 100% water line (cm)
#define TOTAL_CAPACITY_LITRES   1000.0f      // Total rated volume capacity (Litres)

// Optional explicit geometric dimensions (used when exact physical modeling is selected)
#define TANK_LENGTH_CM          100.0f       // Rectangular length or horizontal cylinder length (cm)
#define TANK_WIDTH_CM           100.0f       // Rectangular width (cm)
#define TANK_RADIUS_CM          39.89f       // Cylindrical radius (cm) [sqrt(1000*1000 / (pi * 200)) ~ 39.89 cm]

// ============================================================================
// 6. Serial Debug Logging Configuration
// ============================================================================
#define SERIAL_BAUD_RATE        115200
#define DEBUG_LOG_ENABLED       1

#if DEBUG_LOG_ENABLED
  #define DEBUG_PRINT(...)    Serial.print(__VA_ARGS__)
  #define DEBUG_PRINTLN(...)  Serial.println(__VA_ARGS__)
  #define DEBUG_PRINTF(...)   Serial.printf(__VA_ARGS__)
#else
  #define DEBUG_PRINT(...)
  #define DEBUG_PRINTLN(...)
  #define DEBUG_PRINTF(...)
#endif

#endif // CONFIG_H
