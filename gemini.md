# 📟 ESP32-S3 RGB Matrix Ecosystem - Index

## 📖 Projektübersicht
Dieses Projekt ermöglicht die Steuerung einer **64x64 RGB LED Matrix (HUB75)** mit einem **ESP32-S3**. Es kombiniert eine performante C++ Firmware (Arduino/PlatformIO) mit einem Desktop-Client (Python/PyQt6) zur Bildkonvertierung und Fernsteuerung.

## 🏗️ Systemarchitektur

### 🔧 Firmware (ESP32-S3)
Die Firmware verwaltet die Matrix-Ansteuerung, GIF-Dekodierung und die Netzwerkkommunikation.
- **Framework:** Arduino (PlatformIO)
- **Hauptkomponenten:**
  - `src/main.cpp`: Einstiegspunkt, Initialisierung und Hauptschleife.
  - `src/DisplayManager`: Kapselt die `ESP32-HUB75-MatrixPanel-I2S-DMA` Library und die GIF-Wiedergabelogik.
  - `src/FileManager`: Handhabung von LittleFS (Upload, Löschen, Auflisten von GIFs).
  - `src/NetworkManager`: WiFi-Verbindung, Webserver (Dateiupload) und WebSockets (Echtzeitbefehle).
  - `src/Config.h`: Zentrale Konfiguration für Pins, WiFi und Matrix-Parameter.

### 💻 Desktop Client (Python)
Eine moderne GUI zur Verwaltung des Panels.
- **Framework:** PyQt6
- **Features:**
  - Automatisches Skalieren und Konvertieren von Bildern in optimierte 64x64 GIFs.
  - Upload-Manager für den ESP32.
  - Echtzeit-Steuerung (Helligkeit, Play/Pause, Playlist).
- **Dateien:**
  - `client/main.py`: Die Hauptanwendung.
  - `client/requirements.txt`: Python-Abhängigkeiten.

## 🛠️ Hardware & Pinout (ESP32-S3)
Konfiguriert in `src/Config.h`.

| Signal | GPIO | Signal | GPIO |
| :--- | :--- | :--- | :--- |
| **R1** | 42 | **A** | 4 |
| **G1** | 41 | **B** | 5 |
| **B1** | 40 | **C** | 6 |
| **R2** | 38 | **D** | 7 |
| **G2** | 39 | **E** | 15 |
| **B2** | 13 | **LAT** | 17 |
| **CLK** | 16 | **OE** | 1 |

*Hinweis: B2 wurde auf GPIO 13 verschoben, um Konflikte mit dem PSRAM zu vermeiden.*

## 🚀 Wichtige Abhängigkeiten

### ESP32 Libraries
- `ESP32-HUB75-MatrixPanel-I2S-DMA` (Matrix Ansteuerung)
- `AnimatedGIF` (GIF Dekodierung)
- `ESPAsyncWebServer` & `AsyncTCP` (Netzwerk)
- `ArduinoJson` (API Kommunikation)

### Python Libraries
- `PyQt6` (GUI)
- `Pillow` (Bildverarbeitung)
- `requests` (HTTP Upload)
- `websocket-client` (Echtzeit-Steuerung)

## 📂 Projektstruktur
```text
.
├── client/              # Python Desktop App
│   └── main.py
├── src/                 # ESP32 Source Code
│   ├── main.cpp
│   ├── DisplayManager.cpp
│   └── NetworkManager.cpp
├── include/             # Header Files
├── partitions.csv       # ESP32 Partition Table (16MB Flash)
├── platformio.ini       # Build Configuration
└── README.md            # Dokumentation
```

## 📋 Build-Anweisungen
1. **Firmware:** In PlatformIO `Upload` klicken. Für das Filesystem `Upload Filesystem Image` nutzen.
2. **Client:** `pip install -r client/requirements.txt` und dann `python client/main.py`.
