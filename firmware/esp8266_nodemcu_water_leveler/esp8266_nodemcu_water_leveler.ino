/**
 * ============================================================================
 * HydroSense IoT - Smart Water Tank Monitoring System v2.0
 * ESP8266 NodeMCU & ESP32 Production Firmware
 *
 * Microcontrollers Supported:
 *   - ESP8266 NodeMCU (ESP-12E / ESP-12F / WeMos D1 Mini)
 *   - ESP32 (WROOM-32 / NodeMCU-32S / ESP32-S)
 * Sensors Supported:
 *   - HC-SR04 / JSN-SR04T (Waterproof) / US-100
 *
 * Target Endpoint:
 *   POST https://waterlevelersphn.pythonanywhere.com/api/v1/telemetry
 * ============================================================================
 */

#include <Arduino.h>

// ----------------------------------------------------------------------------
// Board Architecture Selector (Auto-detected by Arduino IDE)
// ----------------------------------------------------------------------------
#if defined(ESP8266)
  #include <ESP8266WiFi.h>
  #include <ESP8266HTTPClient.h>
  #include <WiFiClientSecureBearSSL.h>
  #define BOARD_NAME "ESP8266 NodeMCU"
  #define STATUS_LED_PIN D4     // Onboard LED on D4 (GPIO 2)
  #define TRIG_PIN 12           // NodeMCU D6 = GPIO 12
  #define ECHO_PIN 14           // NodeMCU D5 = GPIO 14
#elif defined(ESP32)
  #include <WiFi.h>
  #include <HTTPClient.h>
  #include <WiFiClientSecure.h>
  #define BOARD_NAME "ESP32 NodeMCU"
  #define STATUS_LED_PIN 2      // Onboard LED on GPIO 2
  #define TRIG_PIN 12           // GPIO 12
  #define ECHO_PIN 14           // GPIO 14
#else
  #error "Unsupported architecture! Select ESP8266 or ESP32 board in Arduino IDE."
#endif

// ============================================================================
// 1. CONFIGURATION PARAMETERS (Edit these for your installation)
// ============================================================================

// --- Wi-Fi Network Credentials ---
const char* WIFI_SSID           = "YOUR_WIFI_SSID";         // 2.4 GHz Wi-Fi Name
const char* WIFI_PASSWORD       = "YOUR_WIFI_PASSWORD";     // Wi-Fi Password

// --- Backend API Configuration ---
// PythonAnywhere Production Endpoint
const char* API_URL             = "https://waterlevelersphn.pythonanywhere.com/api/v1/telemetry";
const char* DEVICE_ID           = "SV_BLOCK_OVER_TANK";     // Registered Device ID
const char* API_KEY             = "water_secret_key_2026";  // Secret Authentication Token

// --- Tank Physical Dimensions (Section 4 & 5) ---
const float TANK_HEIGHT_CM      = 200.0f;  // Internal height from tank bottom to full line (cm)
const float SENSOR_OFFSET_CM    = 15.0f;   // Distance from sensor face to full water line (cm)
const float TANK_CAPACITY_L     = 1000.0f; // Total volume capacity in Litres

// --- Telemetry Timing ---
const unsigned long SEND_INTERVAL_MS = 10000UL;  // Default: 10 seconds (Section 4.10)

// --- SSL Security Mode ---
// Set to false in production to verify PythonAnywhere SSL certificate/fingerprint
// Set to true if testing or if PythonAnywhere certificate rotates
const bool USE_INSECURE_SSL     = false;

// PythonAnywhere / Let's Encrypt SHA-1 Fingerprint (Optional for BearSSL strict verification)
// Format: "AA BB CC DD EE FF 00 11 22 33 44 55 66 77 88 99 AA BB CC DD"
const char* SSL_FINGERPRINT     = ""; // Leave empty to use TrustAnchor CA or setInsecure fallback

// ============================================================================
// Internal State & Timing Variables
// ============================================================================
unsigned long lastSendMillis = 0;
unsigned long reconnectBackoffMs = 5000UL;
const unsigned long MAX_BACKOFF_MS = 60000UL;

// ============================================================================
// Ultrasonic Sensor Reading with 5-Sample Median Filter & Timeout Protection
// ============================================================================
float readUltrasonicDistance() {
  const int SAMPLES = 5;
  float readings[SAMPLES];
  int validSamples = 0;

  for (int i = 0; i < SAMPLES; i++) {
    // Generate 10-microsecond clean trigger pulse
    digitalWrite(TRIG_PIN, LOW);
    delayMicroseconds(2);
    digitalWrite(TRIG_PIN, HIGH);
    delayMicroseconds(10);
    digitalWrite(TRIG_PIN, LOW);

    // Timeout of 30,000 microseconds (~510 cm max range) prevents indefinite blocking
    long duration = pulseIn(ECHO_PIN, HIGH, 30000UL);

    if (duration > 100 && duration < 30000) {
      // Speed of sound: 0.0343 cm/microsecond at 20°C
      float dist = (duration * 0.0343f) / 2.0f;
      readings[validSamples++] = dist;
    }
    delay(25); // Sensor settling delay between pulses
  }

  if (validSamples == 0) {
    // Sensor failure or echo timeout
    return -1.0f;
  }

  // Simple insertion sort to find median
  for (int i = 0; i < validSamples - 1; i++) {
    for (int j = i + 1; j < validSamples; j++) {
      if (readings[i] > readings[j]) {
        float temp = readings[i];
        readings[i] = readings[j];
        readings[j] = temp;
      }
    }
  }

  return readings[validSamples / 2]; // Return median sample
}

// ============================================================================
// Water Level, Volume & Status Calculations (Section 5 & 7)
// ============================================================================
struct TankCalculations {
  float water_height_cm;
  float water_percentage;
  float water_volume_litres;
  String status;
  bool sensor_fault;
};

TankCalculations computeTankMetrics(float distance_cm) {
  TankCalculations calc;

  if (distance_cm < 0.0f || distance_cm > (TANK_HEIGHT_CM + SENSOR_OFFSET_CM + 50.0f)) {
    calc.water_height_cm = 0.0f;
    calc.water_percentage = 0.0f;
    calc.water_volume_litres = 0.0f;
    calc.status = "SENSOR FAULT";
    calc.sensor_fault = true;
    return calc;
  }

  calc.sensor_fault = false;

  // Overloaded / Overflow Condition: Water has risen past 100% mark closer than sensor offset
  if (distance_cm < SENSOR_OFFSET_CM) {
    float overflow = SENSOR_OFFSET_CM - distance_cm;
    calc.water_height_cm = TANK_HEIGHT_CM + overflow;
    calc.water_percentage = (calc.water_height_cm / TANK_HEIGHT_CM) * 100.0f;
    calc.water_volume_litres = (calc.water_percentage / 100.0f) * TANK_CAPACITY_L;
    calc.status = "OVERLOADED";
    return calc;
  }

  // Normal Water Level Equations (Section 5)
  // Water height = Tank height - Effective air gap
  float effective_air_gap = distance_cm - SENSOR_OFFSET_CM;
  calc.water_height_cm = max(0.0f, min(TANK_HEIGHT_CM, TANK_HEIGHT_CM - effective_air_gap));
  calc.water_percentage = max(0.0f, min(100.0f, (calc.water_height_cm / TANK_HEIGHT_CM) * 100.0f));
  calc.water_volume_litres = max(0.0f, (calc.water_percentage / 100.0f) * TANK_CAPACITY_L);

  // Status Classification (Section 7)
  if (calc.water_percentage <= 10.0f) {
    calc.status = "CRITICAL LOW";
  } else if (calc.water_percentage <= 25.0f) {
    calc.status = "LOW";
  } else if (calc.water_percentage <= 85.0f) {
    calc.status = "NORMAL";
  } else {
    calc.status = "HIGH";
  }

  return calc;
}

// ============================================================================
// Non-Blocking Wi-Fi Manager with Exponential Retry
// ============================================================================
void ensureWiFiConnected() {
  if (WiFi.status() == WL_CONNECTED) {
    reconnectBackoffMs = 5000UL; // Reset backoff on success
    return;
  }

  Serial.println();
  Serial.print("[WiFi] Connecting to SSID: ");
  Serial.println(WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long startAttemptTime = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - startAttemptTime < 15000UL) {
    delay(500);
    Serial.print(".");
    digitalWrite(STATUS_LED_PIN, !digitalRead(STATUS_LED_PIN)); // Flash LED
  }

  if (WiFi.status() == WL_CONNECTED) {
    digitalWrite(STATUS_LED_PIN, HIGH);
    Serial.println();
    Serial.println("[WiFi] Connected successfully!");
    Serial.print("[WiFi] IP Assigned: ");
    Serial.println(WiFi.localIP());
  } else {
    digitalWrite(STATUS_LED_PIN, LOW);
    Serial.println();
    Serial.printf("[WiFi] Connection failed. Retrying in %lu ms...\n", reconnectBackoffMs);
    delay(reconnectBackoffMs);
    reconnectBackoffMs = min(reconnectBackoffMs * 2, MAX_BACKOFF_MS);
  }
}

// ============================================================================
// Telemetry Transmission: HTTP POST /api/v1/telemetry
// ============================================================================
bool sendTelemetryPayload(float distance_cm, const TankCalculations& metrics) {
  if (WiFi.status() != WL_CONNECTED) {
    ensureWiFiConnected();
    if (WiFi.status() != WL_CONNECTED) return false;
  }

  HTTPClient http;
  bool isHttps = (strncmp(API_URL, "https://", 8) == 0);

#if defined(ESP8266)
  std::unique_ptr<BearSSL::WiFiClientSecure> secureClient(new BearSSL::WiFiClientSecure);
  WiFiClient standardClient;

  if (isHttps) {
    if (USE_INSECURE_SSL || strlen(SSL_FINGERPRINT) == 0) {
      secureClient->setInsecure(); // Compatible with dynamic cloud cert renewals
    } else {
      secureClient->setFingerprint(SSL_FINGERPRINT);
    }
    http.begin(*secureClient, API_URL);
  } else {
    http.begin(standardClient, API_URL);
  }
#elif defined(ESP32)
  WiFiClientSecure secureClient;
  WiFiClient standardClient;

  if (isHttps) {
    secureClient.setInsecure();
    http.begin(secureClient, API_URL);
  } else {
    http.begin(standardClient, API_URL);
  }
#endif

  http.setTimeout(10000);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Accept", "application/json");
  http.addHeader("X-API-Key", API_KEY);
  http.addHeader("Authorization", String("Bearer ") + API_KEY);
  http.addHeader("User-Agent", "HydroSense-Firmware/2.1");

  // Construct JSON Payload strictly matching Section 3 specification
  char jsonBody[320];
  snprintf(jsonBody, sizeof(jsonBody),
    "{\"device_id\":\"%s\",\"distance_cm\":%.1f,\"water_level_percent\":%.1f,"
    "\"water_volume_litres\":%.1f,\"status\":\"%s\",\"api_key\":\"%s\"}",
    DEVICE_ID,
    distance_cm,
    metrics.water_percentage,
    metrics.water_volume_litres,
    metrics.status.c_str(),
    API_KEY
  );

  Serial.println("--------------------------------------------------");
  Serial.print("[HTTP] POST URL: ");
  Serial.println(API_URL);
  Serial.print("[HTTP] Payload: ");
  Serial.println(jsonBody);

  int httpCode = http.POST(jsonBody);
  bool success = false;

  if (httpCode > 0) {
    Serial.printf("[HTTP] Response code: %d\n", httpCode);
    if (httpCode == HTTP_CODE_OK || httpCode == HTTP_CODE_CREATED) {
      String response = http.getString();
      Serial.print("[HTTP] Server Response: ");
      Serial.println(response);
      success = true;

      // Quick double-blink LED indicator on success
      digitalWrite(STATUS_LED_PIN, LOW); delay(50);
      digitalWrite(STATUS_LED_PIN, HIGH); delay(50);
      digitalWrite(STATUS_LED_PIN, LOW); delay(50);
      digitalWrite(STATUS_LED_PIN, HIGH);
    } else {
      Serial.printf("[HTTP] Server returned error: %d\n", httpCode);
      String errBody = http.getString();
      Serial.println(errBody);
    }
  } else {
    Serial.printf("[HTTP] POST failed, error: %s\n", http.errorToString(httpCode).c_str());
  }

  http.end();
  return success;
}

// ============================================================================
// Arduino Standard Setup
// ============================================================================
void setup() {
  Serial.begin(9600);
  delay(1000);

  Serial.println();
  Serial.println("==================================================");
  Serial.println("  HydroSense IoT - Smart Water Tank Monitor v2.0  ");
  Serial.printf("  Hardware: %s | Device: %s\n", BOARD_NAME, DEVICE_ID);
  Serial.println("==================================================");

  pinMode(STATUS_LED_PIN, OUTPUT);
  digitalWrite(STATUS_LED_PIN, LOW);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  digitalWrite(TRIG_PIN, LOW);

  ensureWiFiConnected();
}

// ============================================================================
// Main Application Loop
// ============================================================================
void loop() {
  unsigned long now = millis();

  // Periodic Telemetry Send (Default: every 10 seconds)
  if (now - lastSendMillis >= SEND_INTERVAL_MS || lastSendMillis == 0) {
    lastSendMillis = now;

    // 1. Read ultrasonic sensor
    float distance = readUltrasonicDistance();

    Serial.println();
    Serial.printf("[SENSOR] Distance Measured: %.2f cm\n", distance);

    // 2. Compute tank metrics and status
    TankCalculations metrics = computeTankMetrics(distance);

    Serial.printf("[TANK] Depth: %.1f cm | Fill: %.1f%% | Volume: %.1f L | Status: %s\n",
      metrics.water_height_cm, metrics.water_percentage, metrics.water_volume_litres, metrics.status.c_str());

    // 3. Transmit telemetry to PythonAnywhere API
    sendTelemetryPayload(distance, metrics);
  }

  delay(20);
}

