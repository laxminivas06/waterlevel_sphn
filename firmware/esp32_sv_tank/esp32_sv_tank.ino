/**
 * ============================================================================
 * SV_BLOCK_OVER_TANK - Smart Water Tank Level Monitor Firmware
 * Compatible with ESP32 (WROOM-32 / ESP32-S / NodeMCU-32S) and ESP8266 (NodeMCU / D1 mini)
 *
 * Web Application: HydroSense IoT / Smart Water Tank Indicator
 * Endpoints Supported:
 *   - GET  /api/tanks?tanks=SV_BLOCK_OVER_TANK:<val>&distance=<cm>
 *   - POST /api/water-level (JSON Telemetry)
 * ============================================================================
 */

#include <Arduino.h>

// ----------------------------------------------------------------------------
// Board Architecture Selector (Auto-detected by Arduino IDE)
// ----------------------------------------------------------------------------
#if defined(ESP32)
  #include <WiFi.h>
  #include <HTTPClient.h>
  #include <WiFiClientSecure.h>
  #define BOARD_TYPE "ESP32"
  #define LED_PIN 2           // Built-in LED on GPIO 2
#elif defined(ESP8266)
  #include <ESP8266WiFi.h>
  #include <ESP8266HTTPClient.h>
  #include <WiFiClientSecureBearSSL.h>
  #define BOARD_TYPE "ESP8266"
  #define LED_PIN D4          // Built-in LED on D4 (GPIO 2)
#else
  #error "Unsupported board! Please select ESP32 or ESP8266 board in Arduino IDE."
#endif

// ----------------------------------------------------------------------------
// 1. Wi-Fi Configuration - EDIT THESE WITH YOUR NETWORK DETAILS
// ----------------------------------------------------------------------------
const char* ssid = "YOUR_WIFI_SSID";             // Replace with your 2.4GHz Wi-Fi name
const char* password = "YOUR_WIFI_PASSWORD";     // Replace with your Wi-Fi password

// ----------------------------------------------------------------------------
// 2. Server Configuration
// ----------------------------------------------------------------------------
// For Local Network Testing: Use your PC's local IP address (e.g., http://192.168.1.100:5000/api/tanks)
// For Cloud / Hosted: Use your domain (e.g., https://your-app.vercel.app/api/tanks or https://water-tank-indicator-jade.vercel.app/api/tanks)
const char* serverUrl = "http://192.168.1.100:5000/api/tanks";

// Tank Identifier
const char* tankName = "SV_BLOCK_OVER_TANK";

// Distance scale factor used in your original hardware setup (1.81)
const float SCALE_FACTOR = 1.81;

// Reporting interval in milliseconds (default: 5000 ms = 5 seconds)
const unsigned long SEND_INTERVAL_MS = 5000;

// ----------------------------------------------------------------------------
// 3. Hardware Pin Mapping
// ----------------------------------------------------------------------------
// ESP32: GPIO 12 for TRIG, GPIO 14 for ECHO
// ESP8266: D6 (GPIO 12) for TRIG, D5 (GPIO 14) for ECHO
const int trigPin = 12;
const int echoPin = 14;

// ----------------------------------------------------------------------------
// Global Variables
// ----------------------------------------------------------------------------
unsigned long lastSendTime = 0;

// ----------------------------------------------------------------------------
// Ultrasonic Distance Measurement Function (with 3-pulse median filter)
// ----------------------------------------------------------------------------
float readUltrasonicDistance() {
  float samples[3];

  for (int i = 0; i < 3; i++) {
    digitalWrite(trigPin, LOW);
    delayMicroseconds(2);
    digitalWrite(trigPin, HIGH);
    delayMicroseconds(10);
    digitalWrite(trigPin, LOW);

    // Timeout of 30ms (~500 cm max range)
    long duration = pulseIn(echoPin, HIGH, 30000UL);
    if (duration == 0) {
      samples[i] = 200.0; // Fallback distance if pulse timed out
    } else {
      samples[i] = (duration * 0.0343f) / 2.0f; // Distance in cm
    }
    delay(20);
  }

  // Median sort of 3 samples to eliminate outlier noise
  if (samples[0] > samples[1]) { float t = samples[0]; samples[0] = samples[1]; samples[1] = t; }
  if (samples[1] > samples[2]) { float t = samples[1]; samples[1] = samples[2]; samples[2] = t; }
  if (samples[0] > samples[1]) { float t = samples[0]; samples[0] = samples[1]; samples[1] = t; }

  return samples[1]; // Return median sample
}

// ----------------------------------------------------------------------------
// Wi-Fi Connection Management
// ----------------------------------------------------------------------------
void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;

  Serial.println();
  Serial.print("[WiFi] Connecting to: ");
  Serial.println(ssid);

  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    digitalWrite(LED_PIN, !digitalRead(LED_PIN)); // Toggle LED while connecting
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    digitalWrite(LED_PIN, HIGH); // LED ON
    Serial.println();
    Serial.println("[WiFi] Connected successfully!");
    Serial.print("[WiFi] IP Address: ");
    Serial.println(WiFi.localIP());
  } else {
    digitalWrite(LED_PIN, LOW); // LED OFF
    Serial.println();
    Serial.println("[WiFi] Connection failed! Will retry next cycle.");
  }
}

// ----------------------------------------------------------------------------
// Send Telemetry to Web Application Server
// ----------------------------------------------------------------------------
bool sendTelemetry(float distanceCm) {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
    if (WiFi.status() != WL_CONNECTED) return false;
  }

  // Calculate scaled value
  float scaledVal = distanceCm * SCALE_FACTOR;

  // Build target URL compatible with /api/tanks
  // Format: http://<server>/api/tanks?tanks=SV_BLOCK_OVER_TANK:<val>&distance=<cm>
  String fullUrl = String(serverUrl);
  if (fullUrl.indexOf('?') == -1) {
    fullUrl += "?tanks=";
  } else {
    fullUrl += "&tanks=";
  }
  fullUrl += String(tankName) + ":" + String(scaledVal, 2);
  fullUrl += "&distance=" + String(distanceCm, 2);

  Serial.println("----------------------------------------------");
  Serial.print("[HTTP] Target URL: ");
  Serial.println(fullUrl);

  HTTPClient http;
  bool isHttps = fullUrl.startsWith("https://");

#if defined(ESP32)
  if (isHttps) {
    WiFiClientSecure secureClient;
    secureClient.setInsecure(); // Accept self-signed / cloud certificates
    http.begin(secureClient, fullUrl);
  } else {
    WiFiClient client;
    http.begin(client, fullUrl);
  }
#elif defined(ESP8266)
  if (isHttps) {
    std::unique_ptr<BearSSL::WiFiClientSecure> client(new BearSSL::WiFiClientSecure);
    client->setInsecure();
    http.begin(*client, fullUrl);
  } else {
    WiFiClient client;
    http.begin(client, fullUrl);
  }
#endif

  http.setTimeout(8000);
  http.addHeader("User-Agent", "ESP-WaterLeveler/" BOARD_TYPE);

  Serial.println("[HTTP] Sending GET request...");
  int httpCode = http.GET();

  bool success = false;
  if (httpCode > 0) {
    Serial.printf("[HTTP] GET Response code: %d\n", httpCode);
    if (httpCode == HTTP_CODE_OK || httpCode == HTTP_CODE_MOVED_PERMANENTLY) {
      String responsePayload = http.getString();
      Serial.print("[HTTP] Server Response: ");
      Serial.println(responsePayload);
      success = true;

      // Quick double-blink LED to show successful packet delivery
      digitalWrite(LED_PIN, LOW);
      delay(60);
      digitalWrite(LED_PIN, HIGH);
      delay(60);
      digitalWrite(LED_PIN, LOW);
      delay(60);
      digitalWrite(LED_PIN, HIGH);
    }
  } else {
    Serial.printf("[HTTP] GET failed, error: %s\n", http.errorToString(httpCode).c_str());
  }

  http.end();
  return success;
}

// ----------------------------------------------------------------------------
// Setup Hook
// ----------------------------------------------------------------------------
void setup() {
  Serial.begin(9600);
  delay(1000);

  Serial.println();
  Serial.println("==============================================");
  Serial.println("           SV_OVER TANK PROJECT");
  Serial.printf("        Board: %s | Firmware v2.0\n", BOARD_TYPE);
  Serial.println("==============================================");

  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  pinMode(trigPin, OUTPUT);
  pinMode(echoPin, INPUT);
  digitalWrite(trigPin, LOW);

  connectWiFi();
}

// ----------------------------------------------------------------------------
// Main Loop
// ----------------------------------------------------------------------------
void loop() {
  unsigned long currentMillis = millis();

  if (currentMillis - lastSendTime >= SEND_INTERVAL_MS || lastSendTime == 0) {
    lastSendTime = currentMillis;

    // 1. Measure ultrasonic sensor distance
    float distance = readUltrasonicDistance();

    Serial.println();
    Serial.print("Distance: ");
    Serial.print(distance, 2);
    Serial.println(" cm");
    Serial.print("Scaled Value (x1.81): ");
    Serial.println(distance * SCALE_FACTOR, 2);

    // 2. Transmit reading to web application
    sendTelemetry(distance);
  }

  delay(20);
}

