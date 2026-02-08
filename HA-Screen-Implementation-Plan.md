# HA-Screen Mode: Flexibles Grafik-Terminal für 64x64 LED Matrix

## Context

Das 64x64 LED Matrix Display wird aktuell über Home Assistant und MQTT gesteuert und zeigt entweder GIF-Animationen (Playlist/Single-File-Modus), Live-Streaming oder temporäre Texte an. Diese Modi sind **mutually exclusive** - nur einer kann aktiv sein.

**Problem**: Für flexible Home Assistant Dashboards (z.B. Wetter, Raum-Status, Benachrichtigungen) wird ein Modus benötigt, der einen animierten Hintergrund mit mehreren Text-Overlays kombiniert, deren Inhalt und Position zur Laufzeit über MQTT gesteuert werden kann.

**Lösung**: Ein neuer "HA-Screen" Modus, der:
- Einen GIF-Hintergrund anzeigt (nutzt bestehende GIF-Engine)
- 2 text-overlays darüber rendert (Position, Text, Farbe per MQTT konfigurierbar)
- Vollständig über MQTT steuerbar ist (keine Code-Änderungen für neue Inhalte nötig)

---

## Recommended Approach

### Architecture Decision: Post-Frame Overlay Compositing

Kein separater Frame-Buffer - stattdessen wird nach jedem GIF-Frame direkt auf den DMA-Buffer gezeichnet:
1. GIF-Frame wird gerendert (bestehende AnimatedGIF-Engine)
2. Text-Overlays werden darüber gezeichnet (Adafruit GFX)
3. Display zeigt das kombinierte Ergebnis

**Vorteile**: Minimaler Speicherverbrauch (~200 Bytes), nutzt bewährte Komponenten, einfach zu implementieren.

### Mode System Enhancement

Neues **einheitliches Mode-Switching-System** mit MQTT Topic `/set/mode`:
- `"Playlist"` - Bestehender Playlist-Modus (zyklisch durch alle GIFs)
- `"Static"` - Bestehender Single-File-Modus (ein GIF wiederholt)
- `"HA-Screen"` - **NEUER** Modus (Hintergrund-GIF + 2 Text-Overlays)

---

## Implementation Plan

### Data Structures

#### 1. TextOverlay Struct (DisplayManager.h)
```cpp
struct TextOverlay {
    String text;        // Text-Inhalt (leer = nicht zeichnen)
    int16_t x;          // X-Position (0-64)
    int16_t y;          // Y-Position (0-64)
    uint16_t color;     // RGB565 Farbe
    uint8_t size;       // Schriftgröße 1-8 (Standard 5x7 Font)
    bool enabled;       // Overlay aktiv?
};
```

#### 2. DisplayManager State Variables
```cpp
// HA-Screen Mode
bool isHAScreenMode = false;
String haScreenBackgroundFile;  // Pfad zum Hintergrund-GIF
TextOverlay overlays[2];        // 2 Text-Overlays

// Pending Commands (erweitert)
CMD_START_HA_SCREEN,
CMD_SET_HA_BACKGROUND,
CMD_SET_OVERLAY_TEXT,
CMD_SET_OVERLAY_POSITION,
CMD_SET_OVERLAY_COLOR,
CMD_SET_OVERLAY_SIZE,
CMD_SET_MODE

// Command Parameters
int pendingOverlayIndex;     // 0 oder 1
String pendingOverlayText;
int pendingOverlayX, pendingOverlayY;
uint16_t pendingOverlayColor;
uint8_t pendingOverlaySize;
String pendingMode;          // "Playlist", "Static", "HA-Screen"
```

---

## Critical Files to Modify

### 1. [src/DisplayManager.h](src/DisplayManager.h)
**Änderungen:**
- Add `TextOverlay` struct definition (nach Zeile 8)
- Add HA-Screen state variables (nach Zeile 121)
- Add overlay getter methods for status reporting (public section):
  ```cpp
  bool isInHAScreenMode() { return isHAScreenMode; }
  String getHABackground() { return haScreenBackgroundFile; }
  String getOverlayText(uint8_t index) { return overlays[index].text; }
  int16_t getOverlayX(uint8_t index) { return overlays[index].x; }
  int16_t getOverlayY(uint8_t index) { return overlays[index].y; }
  uint16_t getOverlayColor(uint8_t index) { return overlays[index].color; }
  uint8_t getOverlaySize(uint8_t index) { return overlays[index].size; }
  ```
- Add overlay management methods (public section, nach Zeile 31):
  ```cpp
  void setMode(const String& mode);
  void setHABackground(const String& path);
  void setOverlayText(uint8_t index, const String& text);
  void setOverlayPosition(uint8_t index, int16_t x, int16_t y);
  void setOverlayColor(uint8_t index, uint16_t color);
  void setOverlaySize(uint8_t index, uint8_t size);
  ```
- Extend `CmdType` enum (Zeile 107):
  ```cpp
  CMD_SET_MODE, CMD_SET_HA_BACKGROUND, CMD_SET_OVERLAY_TEXT,
  CMD_SET_OVERLAY_POSITION, CMD_SET_OVERLAY_COLOR, CMD_SET_OVERLAY_SIZE
  ```
- Add pending command variables (nach Zeile 113)

### 2. [src/DisplayManager.cpp](src/DisplayManager.cpp)
**Änderungen:**

#### New Public Methods (Thread-Safe Command Queueing)
```cpp
void DisplayManager::setMode(const String& mode) {
    std::lock_guard<std::mutex> lk(cmdMutex);
    pendingCmd = CMD_SET_MODE;
    pendingMode = mode;
    cmdPending = true;
}

void DisplayManager::setHABackground(const String& path) {
    std::lock_guard<std::mutex> lk(cmdMutex);
    pendingCmd = CMD_SET_HA_BACKGROUND;
    pendingParam = path;
    cmdPending = true;
}

void DisplayManager::setOverlayText(uint8_t index, const String& text) {
    std::lock_guard<std::mutex> lk(cmdMutex);
    pendingCmd = CMD_SET_OVERLAY_TEXT;
    pendingOverlayIndex = index;
    pendingOverlayText = text;
    cmdPending = true;
}

void DisplayManager::setOverlayPosition(uint8_t index, int16_t x, int16_t y) {
    std::lock_guard<std::mutex> lk(cmdMutex);
    pendingCmd = CMD_SET_OVERLAY_POSITION;
    pendingOverlayIndex = index;
    pendingOverlayX = x;
    pendingOverlayY = y;
    cmdPending = true;
}

void DisplayManager::setOverlayColor(uint8_t index, uint16_t color) {
    std::lock_guard<std::mutex> lk(cmdMutex);
    pendingCmd = CMD_SET_OVERLAY_COLOR;
    pendingOverlayIndex = index;
    pendingOverlayColor = color;
    cmdPending = true;
}

void DisplayManager::setOverlaySize(uint8_t index, uint8_t size) {
    std::lock_guard<std::mutex> lk(cmdMutex);
    pendingCmd = CMD_SET_OVERLAY_SIZE;
    pendingOverlayIndex = index;
    pendingOverlaySize = size;
    cmdPending = true;
}
```

#### Command Handler in loop() (add to existing switch/if-else)
```cpp
else if (cmdToExec == CMD_SET_MODE) {
    _setMode(paramToExec);  // Private implementation
}
else if (cmdToExec == CMD_SET_HA_BACKGROUND) {
    if (isHAScreenMode) {
        _startHAScreen(paramToExec);  // Reload with new background
    } else {
        haScreenBackgroundFile = paramToExec;  // Just save for later
    }
}
else if (cmdToExec == CMD_SET_OVERLAY_TEXT) {
    if (pendingOverlayIndex < 2) {
        overlays[pendingOverlayIndex].text = pendingOverlayText;
        overlays[pendingOverlayIndex].enabled = (pendingOverlayText != "");
    }
}
else if (cmdToExec == CMD_SET_OVERLAY_POSITION) {
    if (pendingOverlayIndex < 2) {
        if (pendingOverlayX >= 0) overlays[pendingOverlayIndex].x = pendingOverlayX;
        if (pendingOverlayY >= 0) overlays[pendingOverlayIndex].y = pendingOverlayY;
    }
}
else if (cmdToExec == CMD_SET_OVERLAY_COLOR) {
    if (pendingOverlayIndex < 2) {
        overlays[pendingOverlayIndex].color = pendingOverlayColor;
    }
}
else if (cmdToExec == CMD_SET_OVERLAY_SIZE) {
    if (pendingOverlayIndex < 2) {
        overlays[pendingOverlayIndex].size = pendingOverlaySize;
    }
}
```

#### New Private Implementation Method
```cpp
void DisplayManager::_setMode(const String& mode) {
    if (mode == "Playlist") {
        _playAll();  // Existing function
    }
    else if (mode == "Static") {
        // Play current file or last file
        if (currentFile != "") {
            _playFile(currentFile);
        }
    }
    else if (mode == "HA-Screen") {
        _startHAScreen(haScreenBackgroundFile);
    }
}

void DisplayManager::_startHAScreen(const String& backgroundPath) {
    // Save current state (like _showText does)
    if (!isHAScreenMode) {
        savedIsPlaying = isPlaying;
        savedSingleMode = singleMode;
        savedCurrentFile = currentFile;
        savedCurrentPlaylist = currentPlaylist;
    }

    // Clear other modes
    _stop();
    isHAScreenMode = true;

    // Initialize overlays with defaults if not already set
    for (int i = 0; i < 2; i++) {
        if (overlays[i].color == 0) overlays[i].color = 0xFFFF; // White
        if (overlays[i].size == 0) overlays[i].size = 1;
        overlays[i].enabled = (overlays[i].text != "");
    }

    // Save background file
    haScreenBackgroundFile = backgroundPath;

    // Validate file exists
    if (backgroundPath == "" || !fileMgr->fileExists(backgroundPath)) {
        Serial.printf("HA-Screen: Background file not found: %s\n", backgroundPath.c_str());
        // Fall back to black screen or use default
        return;
    }

    // Start GIF playback of background
    _playFile(backgroundPath);
}
```

#### Rendering Logic in loop() (add new branch after existing mode checks)
```cpp
else if (isHAScreenMode) {
    // HA-Screen Mode: GIF Background + Text Overlays
    if (millis() >= nextGifFrameTime) {
        std::lock_guard<std::mutex> lk(gifMutex);

        // Render GIF frame (existing logic)
        int32_t tDelay = 0;
        if (gif.playFrame(false, &tDelay) > 0) {
            nextGifFrameTime = millis() + (tDelay > 0 ? tDelay : 100);
        } else {
            // GIF loop finished, restart
            gif.reset();
            nextGifFrameTime = millis() + loopDurationMs;
        }

        // Render text overlays on top
        _drawOverlays();
    }
}
```

#### New Overlay Rendering Method
```cpp
void DisplayManager::_drawOverlays() {
    for (int i = 0; i < 2; i++) {
        if (!overlays[i].enabled) continue;
        if (overlays[i].text == "") continue;

        // Clamp position to display bounds
        int16_t x = constrain(overlays[i].x, 0, PANEL_RES_X - 1);
        int16_t y = constrain(overlays[i].y, 0, PANEL_RES_Y - 1);

        // Set text properties
        dma->setFont();  // Reset to default 5x7 font
        dma->setTextSize(overlays[i].size);
        dma->setTextColor(overlays[i].color);
        dma->setTextWrap(false);

        // Draw text
        dma->setCursor(x, y);
        dma->print(overlays[i].text);
    }
}
```

#### Update _stop() to handle HA-Screen
```cpp
void DisplayManager::_stop() {
    // ... existing code ...

    // Add at end:
    if (isHAScreenMode) {
        isHAScreenMode = false;
        // Optionally restore previous mode (like text mode does)
    }
}
```

### 3. [src/Config.h](src/Config.h)
**Ergänzungen** (nach Zeile 34):
```cpp
// --- HA-Screen Mode Defaults ---
#define HA_SCREEN_MAX_OVERLAYS 2
#define HA_SCREEN_DEFAULT_COLOR 0xFFFF  // White (RGB565)
#define HA_SCREEN_DEFAULT_SIZE 1        // Font size
```

### 4. [src/MqttManager.h](src/MqttManager.h)
**Änderungen** (add new topic declarations):
```cpp
String topicSetMode;
String topicSetHABackground;
String topicSetOverlay1Text;
String topicSetOverlay1X;
String topicSetOverlay1Y;
String topicSetOverlay1Color;
String topicSetOverlay1Size;
String topicSetOverlay2Text;
String topicSetOverlay2X;
String topicSetOverlay2Y;
String topicSetOverlay2Color;
String topicSetOverlay2Size;
```

### 5. [src/MqttManager.cpp](src/MqttManager.cpp)
**Änderungen:**

#### Constructor - Initialize Topics (nach Zeile 12)
```cpp
topicSetMode = String(MQTT_TOPIC_PREFIX) + "/set/mode";
topicSetHABackground = String(MQTT_TOPIC_PREFIX) + "/set/ha_background";
topicSetOverlay1Text = String(MQTT_TOPIC_PREFIX) + "/set/overlay1_text";
topicSetOverlay1X = String(MQTT_TOPIC_PREFIX) + "/set/overlay1_x";
topicSetOverlay1Y = String(MQTT_TOPIC_PREFIX) + "/set/overlay1_y";
topicSetOverlay1Color = String(MQTT_TOPIC_PREFIX) + "/set/overlay1_color";
topicSetOverlay1Size = String(MQTT_TOPIC_PREFIX) + "/set/overlay1_size";
topicSetOverlay2Text = String(MQTT_TOPIC_PREFIX) + "/set/overlay2_text";
topicSetOverlay2X = String(MQTT_TOPIC_PREFIX) + "/set/overlay2_x";
topicSetOverlay2Y = String(MQTT_TOPIC_PREFIX) + "/set/overlay2_y";
topicSetOverlay2Color = String(MQTT_TOPIC_PREFIX) + "/set/overlay2_color";
topicSetOverlay2Size = String(MQTT_TOPIC_PREFIX) + "/set/overlay2_size";
```

#### Callback Handler (add to existing callback function, nach Zeile 136)
```cpp
else if (top == topicSetMode) {
    display->setMode(msg);  // "Playlist", "Static", or "HA-Screen"
}
else if (top == topicSetHABackground) {
    if (!msg.startsWith("/")) msg = "/" + msg;
    display->setHABackground(msg);
}
else if (top == topicSetOverlay1Text) {
    display->setOverlayText(0, msg);
}
else if (top == topicSetOverlay1X) {
    display->setOverlayPosition(0, msg.toInt(), -1);  // -1 = keep Y unchanged
}
else if (top == topicSetOverlay1Y) {
    display->setOverlayPosition(0, -1, msg.toInt());  // -1 = keep X unchanged
}
else if (top == topicSetOverlay1Color) {
    // Same format as textcolor: "r,g,b" or JSON
    uint16_t color = parseColorToRGB565(msg);  // Helper function
    display->setOverlayColor(0, color);
}
else if (top == topicSetOverlay1Size) {
    display->setOverlaySize(0, msg.toInt());
}
// Repeat for overlay2
else if (top == topicSetOverlay2Text) {
    display->setOverlayText(1, msg);
}
else if (top == topicSetOverlay2X) {
    display->setOverlayPosition(1, msg.toInt(), -1);
}
else if (top == topicSetOverlay2Y) {
    display->setOverlayPosition(1, -1, msg.toInt());
}
else if (top == topicSetOverlay2Color) {
    uint16_t color = parseColorToRGB565(msg);
    display->setOverlayColor(1, color);
}
else if (top == topicSetOverlay2Size) {
    display->setOverlaySize(1, msg.toInt());
}
```

#### Helper Function (add as private method in MqttManager.cpp)
```cpp
uint16_t MqttManager::parseColorToRGB565(const String& msg) {
    int r=255, g=255, b=255;

    if (msg.startsWith("{")) {
        // JSON format: {"r":255,"g":0,"b":0}
        StaticJsonDocument<200> doc;
        deserializeJson(doc, msg);
        r = doc["r"] | 255;
        g = doc["g"] | 255;
        b = doc["b"] | 255;
    } else {
        // CSV format: "255,0,0"
        int firstComma = msg.indexOf(',');
        int secondComma = msg.indexOf(',', firstComma + 1);
        if (firstComma > 0 && secondComma > 0) {
            r = msg.substring(0, firstComma).toInt();
            g = msg.substring(firstComma + 1, secondComma).toInt();
            b = msg.substring(secondComma + 1).toInt();
        }
    }

    // Convert RGB888 to RGB565
    return dma->color565(r, g, b);
}
```

#### Update sendStatus() (modify existing function, ab Zeile 143)
```cpp
void MqttManager::sendStatus() {
    if (!client.connected()) return;

    StaticJsonDocument<1024> doc;  // Increase size from 512
    doc["state"] = display->getIsPlaying() ? "ON" : "OFF";
    doc["brightness"] = display->getBrightness();
    doc["playlist"] = display->getCurrentPlaylist();
    doc["file"] = display->getCurrentFile();
    doc["shuffle"] = display->getShuffle() ? "ON" : "OFF";
    doc["duration"] = display->getLoopDuration();

    // Add mode information
    String mode = "Playlist";
    if (display->isInHAScreenMode()) {
        mode = "HA-Screen";
        doc["ha_background"] = display->getHABackground();

        // Overlay 1
        doc["overlay1_text"] = display->getOverlayText(0);
        doc["overlay1_x"] = display->getOverlayX(0);
        doc["overlay1_y"] = display->getOverlayY(0);

        // Overlay 2
        doc["overlay2_text"] = display->getOverlayText(1);
        doc["overlay2_x"] = display->getOverlayX(1);
        doc["overlay2_y"] = display->getOverlayY(1);
    } else if (display->getSingleMode()) {
        mode = "Static";
    }
    doc["mode"] = mode;

    String output;
    serializeJson(doc, output);
    client.publish(topicStatusState.c_str(), output.c_str(), true);
}
```

**Note**: Add `getSingleMode()` getter to DisplayManager.h if not exists:
```cpp
bool getSingleMode() { return singleMode; }
```

### 6. [mqtt.yaml](mqtt.yaml) - Home Assistant Configuration
**Vollständige neue Entities hinzufügen:**

```yaml
mqtt:
  # --- Mode Selector ---
  select:
    - name: "Matrix Display Mode"
      unique_id: "esp32_matrix_display_mode"
      state_topic: "ledmatrix/status/state"
      command_topic: "ledmatrix/set/mode"
      value_template: "{{ value_json.mode }}"
      options:
        - "Playlist"
        - "Static"
        - "HA-Screen"
      icon: "mdi:monitor-dashboard"
      availability:
        - topic: "ledmatrix/status/availability"

  # --- HA-Screen Background ---
  text:
    - name: "Matrix HA Background File"
      unique_id: "esp32_matrix_ha_background"
      command_topic: "ledmatrix/set/ha_background"
      state_topic: "ledmatrix/status/state"
      value_template: "{{ value_json.ha_background | default('') }}"
      icon: "mdi:image"
      availability:
        - topic: "ledmatrix/status/availability"

  # --- Overlay 1 ---
    - name: "Matrix Overlay 1 Text"
      unique_id: "esp32_matrix_overlay1_text"
      command_topic: "ledmatrix/set/overlay1_text"
      state_topic: "ledmatrix/status/state"
      value_template: "{{ value_json.overlay1_text | default('') }}"
      icon: "mdi:text-box"
      availability:
        - topic: "ledmatrix/status/availability"

    - name: "Matrix Overlay 2 Text"
      unique_id: "esp32_matrix_overlay2_text"
      command_topic: "ledmatrix/set/overlay2_text"
      state_topic: "ledmatrix/status/state"
      value_template: "{{ value_json.overlay2_text | default('') }}"
      icon: "mdi:text-box"
      availability:
        - topic: "ledmatrix/status/availability"

  # --- Overlay Positions ---
  number:
    - name: "Matrix Overlay 1 X Position"
      unique_id: "esp32_matrix_overlay1_x"
      command_topic: "ledmatrix/set/overlay1_x"
      state_topic: "ledmatrix/status/state"
      value_template: "{{ value_json.overlay1_x | default(0) }}"
      min: 0
      max: 64
      step: 1
      mode: box
      icon: "mdi:arrow-left-right"
      availability:
        - topic: "ledmatrix/status/availability"

    - name: "Matrix Overlay 1 Y Position"
      unique_id: "esp32_matrix_overlay1_y"
      command_topic: "ledmatrix/set/overlay1_y"
      state_topic: "ledmatrix/status/state"
      value_template: "{{ value_json.overlay1_y | default(0) }}"
      min: 0
      max: 64
      step: 1
      mode: box
      icon: "mdi:arrow-up-down"
      availability:
        - topic: "ledmatrix/status/availability"

    - name: "Matrix Overlay 2 X Position"
      unique_id: "esp32_matrix_overlay2_x"
      command_topic: "ledmatrix/set/overlay2_x"
      state_topic: "ledmatrix/status/state"
      value_template: "{{ value_json.overlay2_x | default(0) }}"
      min: 0
      max: 64
      step: 1
      mode: box
      icon: "mdi:arrow-left-right"
      availability:
        - topic: "ledmatrix/status/availability"

    - name: "Matrix Overlay 2 Y Position"
      unique_id: "esp32_matrix_overlay2_y"
      command_topic: "ledmatrix/set/overlay2_y"
      state_topic: "ledmatrix/status/state"
      value_template: "{{ value_json.overlay2_y | default(0) }}"
      min: 0
      max: 64
      step: 1
      mode: box
      icon: "mdi:arrow-up-down"
      availability:
        - topic: "ledmatrix/status/availability"

    - name: "Matrix Overlay 1 Font Size"
      unique_id: "esp32_matrix_overlay1_size"
      command_topic: "ledmatrix/set/overlay1_size"
      min: 1
      max: 8
      step: 1
      mode: box
      icon: "mdi:format-size"
      availability:
        - topic: "ledmatrix/status/availability"

    - name: "Matrix Overlay 2 Font Size"
      unique_id: "esp32_matrix_overlay2_size"
      command_topic: "ledmatrix/set/overlay2_size"
      min: 1
      max: 8
      step: 1
      mode: box
      icon: "mdi:format-size"
      availability:
        - topic: "ledmatrix/status/availability"

  # --- Overlay Colors (optional - kann auch über RGB light entity gemacht werden) ---
  text:
    - name: "Matrix Overlay 1 Color"
      unique_id: "esp32_matrix_overlay1_color"
      command_topic: "ledmatrix/set/overlay1_color"
      icon: "mdi:palette"
      availability:
        - topic: "ledmatrix/status/availability"

    - name: "Matrix Overlay 2 Color"
      unique_id: "esp32_matrix_overlay2_color"
      command_topic: "ledmatrix/set/overlay2_color"
      icon: "mdi:palette"
      availability:
        - topic: "ledmatrix/status/availability"
```

---

## Complete MQTT Topic Reference

### Command Topics (Subscribe: `ledmatrix/set/...`)

| Topic | Payload | Description |
|-------|---------|-------------|
| `mode` | `"Playlist"` / `"Static"` / `"HA-Screen"` | **NEU** - Wechselt Display-Modus |
| `ha_background` | `"/path/to/file.gif"` | **NEU** - Setzt Hintergrund-GIF für HA-Screen |
| `overlay1_text` | `"string"` | **NEU** - Text für Overlay 1 (leer = versteckt) |
| `overlay1_x` | `0-64` | **NEU** - X-Position Overlay 1 |
| `overlay1_y` | `0-64` | **NEU** - Y-Position Overlay 1 |
| `overlay1_color` | `"255,0,0"` oder `{"r":255,"g":0,"b":0}` | **NEU** - RGB-Farbe Overlay 1 |
| `overlay1_size` | `1-8` | **NEU** - Schriftgröße Overlay 1 |
| `overlay2_text` | `"string"` | **NEU** - Text für Overlay 2 |
| `overlay2_x` | `0-64` | **NEU** - X-Position Overlay 2 |
| `overlay2_y` | `0-64` | **NEU** - Y-Position Overlay 2 |
| `overlay2_color` | `"255,0,0"` oder JSON | **NEU** - RGB-Farbe Overlay 2 |
| `overlay2_size` | `1-8` | **NEU** - Schriftgröße Overlay 2 |
| `state` | `"ON"` / `"OFF"` | Existing - Play/Stop |
| `brightness` | `0-255` | Existing - Helligkeit |
| `playlist` | `"foldername"` | Existing - Playlist wechseln |
| `file` | `"/path/to/file.gif"` | Existing - Einzelne Datei abspielen |
| `shuffle` | `"ON"` / `"OFF"` | Existing - Shuffle-Modus |
| `duration` | `milliseconds` | Existing - Loop-Dauer |
| `text` | `"string"` | Existing - Temporärer Text-Modus |
| `textcolor` | RGB | Existing - Textfarbe |
| `fontsize` | `1-8` | Existing - Text-Modus Schriftgröße |

### Status Topic (Publish: `ledmatrix/status/state`)

**Erweitertes JSON mit HA-Screen Feldern:**
```json
{
  "state": "ON",
  "brightness": 150,
  "mode": "HA-Screen",
  "playlist": "Default",
  "file": "/Default/test.gif",
  "shuffle": "ON",
  "duration": 6000,
  "ha_background": "/weather/sunny.gif",
  "overlay1_text": "Living Room",
  "overlay1_x": 2,
  "overlay1_y": 8,
  "overlay2_text": "23.5°C",
  "overlay2_x": 2,
  "overlay2_y": 56
}
```

---

## Verification & Testing Plan

### Phase 1: Build & Flash
1. Compile firmware mit PlatformIO
2. Flash auf ESP32-S3
3. Verify serial output zeigt keine Errors

### Phase 2: Basic Mode Switching
1. Publish `ledmatrix/set/mode` = `"Playlist"` → Verify Playlist läuft
2. Publish `ledmatrix/set/mode` = `"Static"` → Verify Single-File Mode
3. Publish `ledmatrix/set/mode` = `"HA-Screen"` → Verify kein Crash

### Phase 3: HA-Screen Background
1. Upload test GIF zu ESP32 (z.B. `/weather/sunny.gif`)
2. Publish `ledmatrix/set/ha_background` = `"/weather/sunny.gif"`
3. Publish `ledmatrix/set/mode` = `"HA-Screen"`
4. Verify: Background GIF wird angezeigt und loopt

### Phase 4: Overlay 1 Configuration
1. Publish `ledmatrix/set/overlay1_text` = `"Hello"`
2. Publish `ledmatrix/set/overlay1_x` = `10`
3. Publish `ledmatrix/set/overlay1_y` = `20`
4. Verify: Text "Hello" erscheint bei Position (10, 20)
5. Publish `ledmatrix/set/overlay1_text` = `""` (leer)
6. Verify: Text verschwindet

### Phase 5: Overlay 2 Configuration
1. Publish `ledmatrix/set/overlay2_text` = `"World"`
2. Publish `ledmatrix/set/overlay2_x` = `10`
3. Publish `ledmatrix/set/overlay2_y` = `30`
4. Verify: Text "World" erscheint bei Position (10, 30)

### Phase 6: Color & Size Configuration
1. Publish `ledmatrix/set/overlay1_color` = `"255,0,0"` (rot)
2. Verify: Overlay 1 ist jetzt rot
3. Publish `ledmatrix/set/overlay2_size` = `2`
4. Verify: Overlay 2 ist jetzt größer (10x14 statt 5x7)

### Phase 7: Status Reporting
1. Subscribe to `ledmatrix/status/state`
2. Change overlay settings via MQTT
3. Verify: Status JSON enthält alle overlay-Werte korrekt

### Phase 8: Runtime Updates
1. Während HA-Screen läuft:
   - Update overlay text → Verify: Sofortige Änderung
   - Update position → Verify: Text bewegt sich
   - Change background → Verify: Neues GIF lädt

### Phase 9: Mode Persistence
1. Switch: HA-Screen → Playlist → HA-Screen
2. Verify: Overlay-Einstellungen bleiben erhalten
3. Verify: Background-File wird erinnert

### Phase 10: Edge Cases
1. Publish invalid position (negative, > 64) → Verify: Clamped to 0-64
2. Set background to non-existent file → Verify: Error logged, kein Crash
3. Rapid-fire MQTT messages → Verify: Alle werden verarbeitet (command queue)
4. Empty overlay text → Verify: Wird nicht gezeichnet

### Phase 11: Home Assistant Integration
1. Reload HA MQTT integration
2. Verify: Alle neuen Entities erscheinen
3. Test Dropdown "Matrix Display Mode" → Verify: Mode wechselt
4. Test Number inputs für Position → Verify: Text bewegt sich
5. Test Text inputs → Verify: Content ändert sich

### Example Home Assistant Automation Test
```yaml
automation:
  - alias: "Test Matrix Weather Display"
    trigger:
      - platform: time_pattern
        minutes: "/1"  # Every minute for testing
    action:
      - service: mqtt.publish
        data:
          topic: "ledmatrix/set/mode"
          payload: "HA-Screen"
      - service: mqtt.publish
        data:
          topic: "ledmatrix/set/ha_background"
          payload: "/weather/sunny.gif"
      - service: mqtt.publish
        data:
          topic: "ledmatrix/set/overlay1_text"
          payload: "{{ now().strftime('%H:%M') }}"
      - service: mqtt.publish
        data:
          topic: "ledmatrix/set/overlay2_text"
          payload: "{{ states('sensor.temperature') }}°C"
```

---

## Implementation Sequence

1. **DisplayManager.h** - Data structures & method declarations
2. **Config.h** - Add HA-Screen defaults
3. **DisplayManager.cpp** - Core logic (command handlers, rendering, overlay drawing)
4. **MqttManager.h** - Topic declarations
5. **MqttManager.cpp** - Topic initialization, callbacks, status reporting
6. **mqtt.yaml** - Home Assistant entities
7. **Build & Test** - Follow verification plan above

---

## Potential Challenges & Mitigations

### Challenge 1: GIF Frame Timing
**Risk**: Overlays might slow down rendering
**Mitigation**: Text drawing is < 1ms. Existing frame timing unchanged.

### Challenge 2: Memory Constraints
**Risk**: Additional state variables
**Impact**: ~200 bytes for overlay state (negligible on ESP32-S3 with PSRAM)

### Challenge 3: RGB888 to RGB565 Conversion
**Risk**: Color accuracy loss
**Mitigation**: Use existing `dma->color565(r, g, b)` helper function

### Challenge 4: Text Clipping at Edges
**Risk**: Text position near edge might render off-screen
**Mitigation**: Use `constrain()` to clamp X/Y to 0-63 range

### Challenge 5: Overlay Persistence Across Mode Changes
**Risk**: User expects overlay settings to persist
**Solution**: Store overlay state globally, don't clear on mode switch

---

## Future Enhancement Ideas (Out of Scope)

- **4-6 Overlays**: Extend array size
- **Icon Overlays**: Small image sprites (8x8, 16x16)
- **Fade Effects**: Smooth transitions for text changes
- **Auto-Center**: Alignment options (left, center, right)
- **Custom Fonts**: TomThumb, FreeSans for variety
- **Overlay Priorities**: Z-order control
- **Background Playlist**: Cycle through multiple GIFs as background
- **Text Animation**: Scroll, blink, fade effects per overlay

---

## Summary

Diese Implementierung erweitert das LED Matrix Display um einen flexiblen HA-Screen Modus:
- ✅ **Nicht-invasiv**: Nutzt bewährte Komponenten (GIF-Engine, Adafruit GFX)
- ✅ **Pattern-konsistent**: Folgt existing command queue & thread-safe architecture
- ✅ **Speicher-effizient**: ~200 Bytes overhead, keine zusätzlichen Frame-Buffer
- ✅ **Runtime-konfigurierbar**: Alle Parameter via MQTT steuerbar
- ✅ **Home Assistant ready**: Vollständige Integration mit mqtt.yaml Entities

**Geschätzte Implementierungszeit**: 2-3 Stunden für erfahrenen Entwickler
**Risiko**: Niedrig - baut auf existing, proven code patterns auf
