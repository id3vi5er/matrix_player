# MQTT Integrations-Konzept für ESP32-S3 Matrix

Dieses Dokument beschreibt das Konzept zur Integration von MQTT in das bestehende Matrix-Projekt, um eine nahtlose Steuerung über HomeAssistant (HA) zu ermöglichen.

## 1. Ziele
- Steuerung der Wiedergabe (Play/Stop/Pause).
- Auswahl von Playlists (Ordnern) und spezifischen Dateien.
- Steuerung der Hardware-Parameter (Helligkeit, Display an/aus).
- Rückmeldung des aktuellen Status an HA (Dateiname, Status).
- **Performance-Optimierung**: Minimale CPU-Last, Vermeidung von Blockaden durch große Payloads.

## 2. MQTT API Design (Topics)
Basispfad: `ledmatrix` (konfigurierbar)

### Empfang (Commands) - `ledmatrix/set/...`
| Subtopic | Payload | Beschreibung |
| :--- | :--- | :--- |
| `state` | `ON` / `OFF` | Schaltet das Display (Schwarzbild) oder stoppt Rendering. |
| `brightness` | `0` - `255` | Setzt die Helligkeit global. |
| `mode` | `Playlist` / `Static` / `HA-Screen` | **NEU** - Wechselt den Display-Modus. |
| `ha_background` | `/Pfad/Datei.gif` | **NEU** - Setzt Hintergrund für HA-Screen Modus. |
| `overlay1_text` | `String` | **NEU** - Text für Overlay 1 (leer = versteckt). |
| `overlay1_x` / `_y` | `0-64` | **NEU** - Position für Overlay 1. |
| `overlay1_color` | `R,G,B` / JSON | **NEU** - Farbe für Overlay 1. |
| `overlay1_size` | `1-8` | **NEU** - Schriftgröße für Overlay 1. |
| `overlay2_...` | ... | **NEU** - Gleiche Parameter für Overlay 2. |
| `playlist` | `Name` | Wechselt die Playlist (Ordnername). `ALL` für alle. |
| `file` | `Ordner/Datei.gif` | Spielt eine spezifische Datei ab. |
| `shuffle` | `ON` / `OFF` | Aktiviert/Deaktiviert Zufallswiedergabe. |
| `duration` | `ms` | Setzt die Anzeigedauer pro Bild (Loop-Modus). |
| `text` | `Nachricht` | Zeigt Text sofort an (Laufschrift). |

### Senden (Status) - `ledmatrix/status/...`
| Subtopic | Payload | Beschreibung |
| :--- | :--- | :--- |
| `state` | JSON | Erweitertes JSON: `{"state":"ON", "mode":"HA-Screen", "ha_background":"...", "overlay1_text":"...", ...}` |
| `availability`| `online`/`offline` | LWT (Last Will and Testament) für HA. |

## 3. Architektur & Performance
Um die CPU-Last gering zu halten und den `DisplayManager` (kritisch für flüssige Animationen) nicht zu stören, wird eine asynchrone bzw. entkoppelte Architektur gewählt.

### MqttManager Klasse
Eine neue Klasse `MqttManager` wird erstellt, die unabhängig von `NetworkManager` (Webserver) agiert, aber ähnliche Ressourcen nutzt.

- **Non-Blocking**: Nutzung von `PubSubClient::loop()` in der `main.cpp` loop. Wichtig: Die Loop muss extrem kurz sein (< 2-3ms), um das Display-Multiplexing nicht zu stören.
- **Entkopplung**: Eingehende MQTT-Nachrichten führen **nicht** direkt zu Dateisystem-Operationen. Stattdessen werden Flags oder Commands in den `DisplayManager` (via `pendingCmd`) injiziert. Der `DisplayManager` arbeitet diese sicher im eigenen Zyklus ab.
- **Listen-Caching & Limits**:
  - **Problem**: Das Senden einer Liste mit 1000 Dateinamen sprengt das MQTT-Paketlimit (typisch 128b - 4kb) und blockiert den ESP beim JSON-Erstellen.
  - **Lösung**:
    - Wir senden **keine Dateilisten** proaktiv über MQTT.
    - HA sendet einfach den Ordnernamen (Playlist). Der ESP prüft intern, ob der Ordner existiert.
    - Falls eine Dateiliste in HA zwingend nötig ist (z.B. Dropdown), sollte dies über eine separate `command`-Anfrage geschehen, die eine Liste in "Chunks" (gestückelte Nachrichten) zurücksendet, oder bevorzugt über die existierende REST-API (Webserver) abgerufen werden, da MQTT dafür nicht ideal ist.

## 4. Notwendige Code-Änderungen

### A. `platformio.ini`
Hinzufügen der Library:
```ini
lib_deps =
    ...
    knolleary/PubSubClient @ ^2.8
```

### B. `src/Config.h` & `src/Secrets.h`
Neue Definitionen für MQTT Broker:
```cpp
#define MQTT_BROKER "192.168.1.x"
#define MQTT_PORT 1883
#define MQTT_USER "homeassistant"
#define MQTT_PASS "secret"
#define MQTT_TOPIC_PREFIX "ledmatrix"
```

### C. `src/MqttManager.h/cpp` (Neu)
- Implementiert `PubSubClient`.
- Callback-Funktion parst Topics und Payloads.
- **Pfad-Handling**: Fügt automatisch führende `/` hinzu, falls diese im Payload fehlen (z.B. `Games/mario.gif` -> `/Games/mario.gif`).
- Ruft `displayManager->setPlaylist()`, `displayManager->setBrightness()` etc. auf.
- Sendet periodisch (oder bei Änderung) Status-Updates.
- **Optimierung**: Nutzt `displayManager->setFileChangeCallback`, um sofort bei Bildwechsel den neuen Status an HA zu pushen.

### D. `src/main.cpp`
- Initialisierung des `MqttManager`.
- Aufruf von `mqttMgr.loop()` in der Hauptschleife.

### E. `src/DisplayManager`
- Keine großen Änderungen nötig, da `pendingCmd` bereits Thread-Safe/Loop-Safe implementiert ist.

## 6. Home Assistant Auto-Discovery (Dynamisches Dropdown)
Damit die Playlist-Namen automatisch als Dropdown in HA erscheinen, nutzt der ESP das **MQTT Discovery** Protokoll.

### Ablauf beim Start (onConnect):
1.  `FileManager::listPlaylists()` wird aufgerufen, um alle Ordner zu scannen.
2.  Ein Discovery-Payload wird an `homeassistant/select/esp32_matrix_playlist/config` gesendet.
3.  Dieser Payload enthält das Feld `options`, welches mit den gefundenen Ordnernamen gefüllt ist (z.B. `["ALL", "Pokemon", "Mario"]`).

### Beispiel Discovery Payload:
```json
{
  "name": "Matrix Playlist",
  "unique_id": "esp32_matrix_playlist",
  "command_topic": "ledmatrix/set/playlist",
  "state_topic": "ledmatrix/status/playlist",
  "options": ["ALL", "Mario", "Pokemon", "Xmas"],
  "device": {
    "identifiers": ["esp32-matrix-s3"],
    "name": "ESP32 RGB Matrix",
    "model": "64x64 Panel",
    "manufacturer": "DIY"
  }
}
```
Dies ersetzt die statische YAML-Konfiguration für die Playlist-Auswahl. Andere Entities (Light, Switch) können ebenfalls per Discovery angelegt werden.