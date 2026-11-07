/**
 * ============================================================================
 * SV_OVER TANK PROJECT - Smart Water Tank Level Monitor Firmware
 * Single-File Production Sketch for ESP8266 NodeMCU & ESP32
 *
 * Microcontrollers Supported:
 *   - ESP8266 NodeMCU (ESP-12E / ESP-12F / WeMos D1 Mini)
 *   - ESP32 (WROOM-32 / NodeMCU-32S / ESP32 Dev Module)
 *
 * Ultrasonic Sensor Supported:
 *   - HC-SR04 / JSN-SR04T (Waterproof) / US-100
 *
 * Target Backend:
 *   GET https://waterlevelersphn.pythonanywhere.com/api/tanks?tanks=SV_BLOCK_OVER_TANK:<val>
 * ============================================================================
 */

#include <Arduino.h>

#if defined(ESP8266)
  #include <ESP8266WiFi.h>
  #include <ESP8266HTTPClient.h>
  #include <WiFiClientSecureBearSSL.h>
  #define STATUS_LED D4
#elif defined(ESP32)
  #include <WiFi.h>
  #include <HTTPClient.h>
  #include <WiFiClientSecure.h>
  #define STATUS_LED 2
#else
  #error "Unsupported board! Select ESP8266 or ESP32 in Arduino IDE."
#endif

// ============================================================================
// 1. Wi-Fi Credentials - EDIT WITH YOUR NETWORK DETAILS
// ============================================================================
const char* ssid     = "YOUR_WIFI_SSID";     // 2.4 GHz Wi-Fi Name
const char* password = "YOUR_WIFI_PASSWORD"; // Wi-Fi Password

// ============================================================================
// 2. Server Configuration & Hardware Calibration
// ============================================================================
// PythonAnywhere Production Server URL
const char* serverUrl = "https://waterlevelersphn.pythonanywhere.com/api/tanks";

// Tank Identifier in HydroSense Dashboard
const char* tankName = "SV_BLOCK_OVER_TANK";

// Distance scale factor from your hardware calibration (1.81)
const float SCALE_FACTOR = 1.81;

// Hardware Pinout (NodeMCU: D6 = GPIO 12 for TRIG, D5 = GPIO 14 for ECHO)
const int trigPin = 12;
const int echoPin = 14;

void setup() {
  Serial.begin(9600);
  pinMode(STATUS_LED, OUTPUT);
  pinMode(trigPin, OUTPUT);
  pinMode(echoPin, INPUT);
  digitalWrite(STATUS_LED, HIGH); // Off initially (active-low on ESP8266)
  delay(1000);

  Serial.println();
  Serial.println("=========================================");
  Serial.println("       SV_OVER TANK PROJECT v2.0         ");
  Serial.println("=========================================");

  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi ..");
  while (WiFi.status() != WL_CONNECTED) {
    Serial.print('.');
    digitalWrite(STATUS_LED, !digitalRead(STATUS_LED)); // Flash LED while connecting
    delay(500);
  }

  digitalWrite(STATUS_LED, LOW); // Solid ON when connected
  Serial.println();
  Serial.println("[WiFi] Connected!");
  Serial.print("[WiFi] IP Address: ");
  Serial.println(WiFi.localIP());
}

void loop() {
  // 1. Trigger 10µs ultrasonic pulse
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  // 2. Measure pulse duration & calculate distance
  long duration = pulseIn(echoPin, HIGH, 30000UL); // 30ms timeout prevents hanging
  float distance = (duration * 0.034f) / 2.0f;     // Speed of sound is 0.034 cm/us

  Serial.print("Distance: ");
  Serial.print(distance);
  Serial.print(" cm (Scaled: ");
  Serial.print(distance * SCALE_FACTOR);
  Serial.println(")");

  // 3. Transmit reading to PythonAnywhere API
  if (WiFi.status() == WL_CONNECTED) {
    float scaledDistance = distance * SCALE_FACTOR;
    String url = String(serverUrl) + "?tanks=" + String(tankName) + ":" + String(scaledDistance, 2);

    Serial.print("[HTTPS] begin: ");
    Serial.println(url);

#if defined(ESP8266)
    std::unique_ptr<BearSSL::WiFiClientSecure> client(new BearSSL::WiFiClientSecure);
    client->setInsecure(); // Handles Let's Encrypt certificates smoothly
    HTTPClient https;
    if (https.begin(*client, url)) {
#elif defined(ESP32)
    WiFiClientSecure client;
    client.setInsecure();
    HTTPClient https;
    if (https.begin(client, url)) {
#endif
      Serial.print("[HTTPS] GET...\n");
      int httpCode = https.GET();

      if (httpCode > 0) {
        Serial.printf("[HTTPS] GET... code: %d\n", httpCode);

        if (httpCode == HTTP_CODE_OK || httpCode == HTTP_CODE_MOVED_PERMANENTLY) {
          String payload = https.getString();
          Serial.println("[HTTPS] Server Response: " + payload);

          // Quick LED flash on successful data transmission
          digitalWrite(STATUS_LED, HIGH);
          delay(80);
          digitalWrite(STATUS_LED, LOW);
        }
      } else {
        Serial.printf("[HTTPS] GET... failed, error: %s\n", https.errorToString(httpCode).c_str());
      }

      https.end();
    } else {
      Serial.println("[HTTPS] Unable to connect");
    }
  } else {
    Serial.println("[WiFi] Disconnected! Reconnecting...");
    WiFi.begin(ssid, password);
  }

  delay(10000); // 10-second transmission interval
}
