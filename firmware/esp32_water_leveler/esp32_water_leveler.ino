/**
 * esp32_water_leveler.ino - ESP32 Smart Water Tank Level Monitoring System
 *
 * STRICT SAFETY GUARANTEE:
 * This system is strictly for monitoring. It contains zero pump, motor, or relay
 * control pins or actuation logic.
 */

#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>

#include "config.h"
#include "sensor_filter.h"
#include "tank_math.h"

// ============================================================================
// State Machine & Circular Retry Queue Definitions
// ============================================================================
enum WiFiState {
    WIFI_STATE_DISCONNECTED,
    WIFI_STATE_CONNECTING,
    WIFI_STATE_CONNECTED
};

struct BufferedReading {
    float distance_cm;
    float water_level_cm;
    float water_percentage;
    float water_litres;
    unsigned long timestamp_ms;
};

// Global Subsystems
SensorFilter sensorFilter;
TankMath tankMath;

// Wi-Fi & Telemetry Timing
WiFiState wifiState = WIFI_STATE_DISCONNECTED;
unsigned long wifiConnectStartMs = 0;
unsigned long lastWifiRetryMs = 0;
unsigned long currentBackoffMs = WIFI_BACKOFF_MIN_MS;
unsigned long lastTelemetryMs = 0;

// Retry Buffer Queue
BufferedReading retryQueue[RETRY_QUEUE_CAPACITY];
int queueHead = 0;
int queueTail = 0;
int queueCount = 0;

void enqueueReading(const TankMetrics& m) {
    if (queueCount >= RETRY_QUEUE_CAPACITY) {
        // Discard oldest sample
        queueHead = (queueHead + 1) % RETRY_QUEUE_CAPACITY;
        queueCount--;
    }
    retryQueue[queueTail].distance_cm = m.distance_cm;
    retryQueue[queueTail].water_level_cm = m.water_level_cm;
    retryQueue[queueTail].water_percentage = m.water_percentage;
    retryQueue[queueTail].water_litres = m.water_litres;
    retryQueue[queueTail].timestamp_ms = millis();

    queueTail = (queueTail + 1) % RETRY_QUEUE_CAPACITY;
    queueCount++;
}

bool dequeueReading(BufferedReading* outReading) {
    if (queueCount <= 0) return false;

    *outReading = retryQueue[queueHead];
    queueHead = (queueHead + 1) % RETRY_QUEUE_CAPACITY;
    queueCount--;
    return true;
}

// ============================================================================
// Non-Blocking Wi-Fi Management
// ============================================================================
void handleWiFi() {
    unsigned long now = millis();

    switch (wifiState) {
        case WIFI_STATE_DISCONNECTED:
            if (now - lastWifiRetryMs >= currentBackoffMs || lastWifiRetryMs == 0) {
                DEBUG_PRINTLN("[WiFi] Initiating connection to SSID...");
                WiFi.disconnect(true);
                WiFi.mode(WIFI_STA);
                WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
                wifiConnectStartMs = now;
                wifiState = WIFI_STATE_CONNECTING;
            }
            break;

        case WIFI_STATE_CONNECTING:
            if (WiFi.status() == WL_CONNECTED) {
                DEBUG_PRINT("[WiFi] Connected! IP Address: ");
                DEBUG_PRINTLN(WiFi.localIP());
                wifiState = WIFI_STATE_CONNECTED;
                currentBackoffMs = WIFI_BACKOFF_MIN_MS; // Reset backoff
                digitalWrite(PIN_STATUS_LED, HIGH);
            } else if (now - wifiConnectStartMs >= WIFI_CONNECT_TIMEOUT_MS) {
                DEBUG_PRINTLN("[WiFi] Connection timeout. Backing off...");
                WiFi.disconnect(true);
                wifiState = WIFI_STATE_DISCONNECTED;
                lastWifiRetryMs = now;
                // Exponential backoff
                currentBackoffMs = min(currentBackoffMs * 2, (unsigned long)WIFI_BACKOFF_MAX_MS);
                digitalWrite(PIN_STATUS_LED, LOW);
            }
            break;

        case WIFI_STATE_CONNECTED:
            if (WiFi.status() != WL_CONNECTED) {
                DEBUG_PRINTLN("[WiFi] Connection lost. Entering disconnected state.");
                wifiState = WIFI_STATE_DISCONNECTED;
                lastWifiRetryMs = now;
                digitalWrite(PIN_STATUS_LED, LOW);
            }
            break;
    }
}

// ============================================================================
// Telemetry Transmission
// ============================================================================
bool sendTelemetryPayload(float distance_cm, float water_level_cm, float water_percentage, float water_litres) {
    if (WiFi.status() != WL_CONNECTED) {
        return false;
    }

    HTTPClient http;
    bool isHttps = (strncmp(BACKEND_API_URL, "https://", 8) == 0);

    if (isHttps) {
        WiFiClientSecure secureClient;
        secureClient.setInsecure(); // PythonAnywhere HTTPS compatibility
        http.begin(secureClient, BACKEND_API_URL);
    } else {
        WiFiClient client;
        http.begin(client, BACKEND_API_URL);
    }

    http.setTimeout(HTTP_TIMEOUT_MS);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("Accept", "application/json");
    http.addHeader("X-API-Key", API_KEY);
    http.addHeader("User-Agent", "ESP32-WaterLeveler/1.0");

    // Construct JSON body with dual API key
    char payload[256];
    snprintf(payload, sizeof(payload),
             "{\"device_id\":\"%s\",\"api_key\":\"%s\",\"distance_cm\":%.2f,"
             "\"water_level_cm\":%.2f,\"water_percentage\":%.2f,\"water_litres\":%.2f}",
             DEVICE_ID, API_KEY, distance_cm, water_level_cm, water_percentage, water_litres);

    DEBUG_PRINT("[HTTP] POST payload: ");
    DEBUG_PRINTLN(payload);

    int httpCode = http.POST(payload);
    DEBUG_PRINTF("[HTTP] Response code: %d\n", httpCode);

    bool success = (httpCode == 200 || httpCode == 201);
    http.end();

    if (success) {
        // Blink LED to indicate successful transmission
        digitalWrite(PIN_STATUS_LED, LOW);
        delay(50);
        digitalWrite(PIN_STATUS_LED, HIGH);
    }

    return success;
}

void flushRetryQueue() {
    while (queueCount > 0 && WiFi.status() == WL_CONNECTED) {
        BufferedReading r;
        if (dequeueReading(&r)) {
            DEBUG_PRINTLN("[HTTP] Flushing buffered telemetry sample...");
            if (!sendTelemetryPayload(r.distance_cm, r.water_level_cm, r.water_percentage, r.water_litres)) {
                // Failed to flush: push back and stop flushing this cycle
                TankMetrics m;
                m.distance_cm = r.distance_cm;
                m.water_level_cm = r.water_level_cm;
                m.water_percentage = r.water_percentage;
                m.water_litres = r.water_litres;
                enqueueReading(m);
                break;
            }
        }
    }
}

// ============================================================================
// Arduino Standard Hooks
// ============================================================================
void setup() {
    Serial.begin(SERIAL_BAUD_RATE);
    delay(1000);
    DEBUG_PRINTLN("\n==========================================");
    DEBUG_PRINTLN("  ESP32 Smart Water Tank Level Monitor");
    DEBUG_PRINTLN("  STRICTLY MONITORING ONLY");
    DEBUG_PRINTLN("==========================================");

    pinMode(PIN_STATUS_LED, OUTPUT);
    digitalWrite(PIN_STATUS_LED, LOW);

    sensorFilter.init(PIN_TRIGGER, PIN_ECHO);
    DEBUG_PRINTLN("[Setup] Ultrasonic sensor pins initialized.");
}

void loop() {
    // 1. Maintain non-blocking Wi-Fi FSM
    handleWiFi();

    // 2. Periodic Sensor Measurement
    unsigned long now = millis();
    if (now - lastTelemetryMs >= TELEMETRY_INTERVAL_MS || lastTelemetryMs == 0) {
        lastTelemetryMs = now;

        // Perform 5-stage filtered distance measurement
        float filteredDistance = sensorFilter.measureFilteredDistance();
        DEBUG_PRINTF("[Sensor] Filtered distance: %.2f cm\n", filteredDistance);

        // Compute tank volumetric physics
        TankMetrics metrics = tankMath.calculate(filteredDistance);
        DEBUG_PRINTF("[Tank] Level: %.2f cm | Pct: %.2f%% | Vol: %.2f L\n",
                     metrics.water_level_cm, metrics.water_percentage, metrics.water_litres);

        // Attempt transmission if connected
        if (wifiState == WIFI_STATE_CONNECTED) {
            // First flush any queued offline samples
            flushRetryQueue();

            bool sent = sendTelemetryPayload(metrics.distance_cm, metrics.water_level_cm,
                                             metrics.water_percentage, metrics.water_litres);
            if (!sent) {
                DEBUG_PRINTLN("[HTTP] Transmission failed. Buffering sample.");
                enqueueReading(metrics);
            }
        } else {
            DEBUG_PRINTLN("[WiFi] Not connected. Buffering telemetry sample.");
            enqueueReading(metrics);
        }
    }

    // Cooperative yield
    delay(10);
}
