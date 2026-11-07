# HydroSense IoT - Universal Firmware Guide

There is now **only one single sketch file** in this directory:
📁 [`esp8266_nodemcu_water_leveler/esp8266_nodemcu_water_leveler.ino`](file:///c:/Users/laxmi/OneDrive/Documents/apps/water/waterlevel_sphn/firmware/esp8266_nodemcu_water_leveler/esp8266_nodemcu_water_leveler.ino)

This single file works automatically on:
- **ESP8266 NodeMCU** (ESP-12E / ESP-12F / WeMos D1 Mini)
- **ESP32** (WROOM-32 / NodeMCU-32S / DOIT DevKit V1)

---

## Quick Start (3 Steps)

1. Open [`esp8266_nodemcu_water_leveler.ino`](file:///c:/Users/laxmi/OneDrive/Documents/apps/water/waterlevel_sphn/firmware/esp8266_nodemcu_water_leveler/esp8266_nodemcu_water_leveler.ino) in Arduino IDE.
2. Edit your 2.4 GHz Wi-Fi credentials at lines 47–48:
   ```cpp
   const char* WIFI_SSID     = "YOUR_WIFI_NAME";
   const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
   ```
3. Select your board from **Tools > Board** in Arduino IDE, and click **Upload (Ctrl+U)**.

---

## Hardware Pin Connections

| Ultrasonic Sensor (HC-SR04 / JSN-SR04T) | ESP8266 NodeMCU Pin | ESP32 Pin |
| :--- | :--- | :--- |
| **VCC** (5V) | **VIN** (5V USB rail) | **VIN** (5V USB rail) |
| **GND** | **GND** | **GND** |
| **TRIG** | **D6** (GPIO 12) | **GPIO 12** |
| **ECHO** | **D5** (GPIO 14) | **GPIO 14** |

> **Tip for 5V Ultrasonic Sensors**: For 5V sensors like JSN-SR04T, use a simple voltage divider (1kΩ and 2kΩ resistors) between sensor ECHO and board pin to step down 5V to 3.3V safely.

---

## Arduino IDE Board Settings

- **For ESP8266 NodeMCU**:
  - Board: `NodeMCU 1.0 (ESP-12E Module)`
  - Upload Speed: `115200`
- **For ESP32**:
  - Board: `ESP32 Dev Module`
  - Upload Speed: `921600` (or `115200`)

---

## Built-in Features
- **Production Server**: Pre-configured to `https://waterlevelersphn.pythonanywhere.com/api/v1/telemetry`
- **Zero Extra Libraries**: Uses only standard ESP8266/ESP32 core packages.
- **SSL Auto-Negotiation**: Handles PythonAnywhere Let's Encrypt certificates automatically.
- **5-Sample Median Noise Filter**: Removes false echoes and water ripples.
- **Automatic Reconnection**: Reconnects to Wi-Fi with exponential backoff if signal drops.
