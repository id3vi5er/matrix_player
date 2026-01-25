# MQTT & Home Assistant Integration Plan

## 1. Konfiguration & Abhängigkeiten

### `platformio.ini`
*   [ ] Library hinzufügen: `knolleary/PubSubClient`
*   [ ] Build Flag hinzufügen: `-DMQTT_MAX_PACKET_SIZE=1024` (Wichtig für HA Discovery JSON!)

### `src/Config.h`
*   [ ] MQTT Credentials definieren:
    ```cpp
    #define MQTT_SERVER "192.168.178.12"
    #define MQTT_PORT 1883
    #define MQTT_USER "nils"
    #define MQTT_PASS "degen1967"
    #define MQTT_CLIENT_ID "ESP32_Matrix_Panel"
    ```

## 2. MQTT Topics (Schema)

Definition der Topics als Konstanten (z.B. in `NetworkManager.h` oder `Config.h`):

```cpp
// Base: sensor/matrix/...
const char* TOPIC_MATRIX_SWITCH_SET =   "sensor/matrix/light/switch";        // Payload: "ON" / "OFF"
const char* TOPIC_MATRIX_BRIGHT_SET =   "sensor/matrix/light/brightness/set";// Payload: 0-255
const char* TOPIC_MATRIX_STATUS =       "sensor/matrix/light/status";        // Payload: "ON" / "OFF"
const char* TOPIC_MATRIX_BRIGHT =       "sensor/matrix/light/brightness";    // Payload: 0-255
const char* TOPIC_MATRIX_FILE_SET =     "sensor/matrix/file/set";            // Payload: Filename
const char* TOPIC_MATRIX_FILE_STATUS =  "sensor/matrix/file/status";         // Payload: Filename
const char* TOPIC_AVAILABILITY =        "sensor/matrix/availability";        // Payload: "online" / "offline"
```

## 3. `src/NetworkManager.h` Erweiterungen

*   [ ] Includes: `<PubSubClient.h>`, `<WiFi.h>`
*   [ ] Member Variablen:
    *   `WiFiClient wifiClient;`
    *   `PubSubClient mqttClient;`
    *   `unsigned long lastMqttReconnectAttempt = 0;`
*   [ ] Methoden Deklarationen:
    *   `void connectMQTT();`
    *   `void mqttCallback(char* topic, uint8_t* payload, unsigned int length);`
    *   `void publishDiscovery();` (Sendet HA Config)
    *   `void updateHAAttributes();` (Sendet aktuellen Status/Helligkeit)

## 4. `src/NetworkManager.cpp` Implementierung

### A. Setup (Konstruktor/Begin)
*   [ ] `mqttClient.setServer(MQTT_SERVER, MQTT_PORT);`
*   [ ] `mqttClient.setCallback([this](...){ this->mqttCallback(...); });`

### B. Loop Logik
*   [ ] In `NetworkManager::loop()`:
    *   Prüfen ob verbunden: `if (!mqttClient.connected()) connectMQTT();`
    *   `mqttClient.loop();` aufrufen.

### C. Verbindungsaufbau (`connectMQTT`)
*   [ ] Non-Blocking Reconnect Logik (alle 5 Sekunden versuchen).
*   [ ] Connect mit Last Will:
    `mqttClient.connect(id, user, pass, TOPIC_AVAILABILITY, 0, true, "offline");`
*   [ ] Bei Erfolg:
    *   `mqttClient.publish(TOPIC_AVAILABILITY, "online", true);`
    *   `mqttClient.subscribe(TOPIC_MATRIX_SWITCH_SET);`
    *   `mqttClient.subscribe(TOPIC_MATRIX_BRIGHT_SET);`
    *   `mqttClient.subscribe(TOPIC_MATRIX_FILE_SET);`
    *   `publishDiscovery();` aufrufen.

### D. Callback Logik (`mqttCallback`)
*   [ ] Topic Vergleich (`strcmp`).
*   [ ] **Switch Set:**
    *   Wenn Payload "ON": `display->playAll()` (oder Resume).
    *   Wenn Payload "OFF": `display->stop()` & `display->clearScreen()`.
    *   Status Update senden an `TOPIC_MATRIX_STATUS`.
*   [ ] **Brightness Set:**
    *   Payload zu Int parsen (`atoi`).
    *   `display->setBrightness(val)`.
    *   Status Update an `TOPIC_MATRIX_BRIGHT`.
*   [ ] **File Set:**
    *   Payload als String (Dateiname).
    *   `display->playFile(filename)`.

### E. Home Assistant Discovery (`publishDiscovery`)
*   [ ] Senden von JSON an `homeassistant/light/matrix_panel/config`.
    *   JSON muss `command_topic` (..SWITCH_SET), `brightness_command_topic` (..BRIGHT_SET) etc. enthalten.
    *   Muss auf `TOPIC_AVAILABILITY` verweisen.
*   [ ] Senden von JSON an `homeassistant/select/matrix_file/config`.
    *   Muss Liste aller Dateien (`options: [...]`) enthalten (via `fileMgr->listGifs()`).

### F. Status Sync
*   [ ] Verknüpfung mit `display->setFileChangeCallback`:
    *   Wenn Datei wechselt -> `mqttClient.publish(TOPIC_MATRIX_FILE_STATUS, filename);`
*   [ ] Bei Web-Upload -> `publishDiscovery()` erneut aufrufen (um Dateiliste in HA zu aktualisieren).

## 5. Feature: Text & Laufschrift

### A. MQTT Topics
```cpp
const char* TOPIC_MATRIX_TEXT_SET =     "sensor/matrix/text/set";            // Payload: "Hallo Welt"
const char* TOPIC_MATRIX_TEXT_MODE =    "sensor/matrix/text/mode";           // Payload: "SCROLL", "STATIC", "LINES"
const char* TOPIC_MATRIX_TEXT_COLOR =   "sensor/matrix/text/color";          // Payload: Hex "#FF0000"
```

### B. `DisplayManager` Erweiterung
*   [ ] Fonts einbinden (via Adafruit GFX, z.B. `TomThumb` für kleine Screens oder Standard-Font).
*   [ ] Neue Methoden:
    *   `setText(String text, uint16_t color, bool scroll);`
    *   `loopText();` (wird im Haupt-Loop aufgerufen für Scrolling-Berechnung).
*   [ ] State-Management:
    *   Modus-Umschaltung: Wenn Text gesetzt wird, `isPlaying` (GIF) stoppen.
    *   `isTextMode` Flag einführen.

### C. Home Assistant Discovery (Text)
*   [ ] Discovery für `homeassistant/text/matrix_text/config` (Input Text).
*   [ ] Discovery für `homeassistant/select/matrix_text_mode/config` (Modus Auswahl).
