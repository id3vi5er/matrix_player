# ESP32-S3 RGB Matrix Ecosystem

Dieses Projekt ist ein vollständiges Ökosystem zur Steuerung einer 64x64 HUB75 RGB LED Matrix mit einem ESP32-S3. Es umfasst eine hochperformante Firmware mit PSRAM-gestützter GIF-Wiedergabe sowie eine moderne Desktop-App zur Steuerung und automatischen Bildkonvertierung.

## 🚀 Features

### Firmware (ESP32-S3)
*   **Smooth GIF Playback:** Nutzt die `AnimatedGIF` Library und nutzt den OPI PSRAM des S3 für flüssige Dekodierung.
*   **Dual Mode:** Umschalten zwischen Einzelbild-Loop und Playlist-Modus (spielt alle GIFs im Flash ab).
*   **Web-Technologie:** Integrierter Async-Webserver für Datei-Uploads und WebSockets für Echtzeit-Steuerung.
*   **LittleFS:** Effiziente Dateiverwaltung auf dem 16MB Flash-Speicher.

### Desktop Client (Python & PyQt6)
*   **Auto-Converter:** Lädt PNG, JPG, BMP oder GIFs und konvertiert sie automatisch in das optimierte 64x64 GIF-Format.
*   **Remote Management:** Dateien auf dem ESP32 auflisten, löschen und abspielen.
*   **Echtzeit-Steuerung:** Helligkeitsregelung und Wiedergabesteuerung via WebSocket.
*   **Dark Mode:** Modernes User-Interface basierend auf PyQt6.

## 🛠 Hardware Setup

### Komponenten
*   ESP32-S3 (Empfohlen: N16R8 mit 16MB Flash / 8MB OPI PSRAM).
*   64x64 RGB LED Matrix (HUB75).
*   Externes 5V Netzteil (mind. 4A empfohlen).

### Verkabelung (Pin-Mapping)
Das Mapping entspricht dem Standard der `ESP32-HUB75-MatrixPanel-I2S-DMA` Library für den S3:

| Signal | GPIO | Signal | GPIO |
| :--- | :--- | :--- | :--- |
| **R1** | 42 | **A** | 45 |
| **G1** | 41 | **B** | 48 |
| **B1** | 40 | **C** | 47 |
| **R2** | 38 | **D** | 21 |
| **G2** | 39 | **E** | 14 |
| **B2** | 37 | **LAT** | 2 |
| **CLK** | 15 | **OE** | 1 |

## 💻 Installation

### 1. Firmware (PlatformIO)
1.  Öffne das Projekt in VS Code mit PlatformIO.
2.  Passe in `include/Config.h` deine WiFi-Daten (`SSID` / `PASS`) an.
3.  Wähle das Board `esp32-s3-devkitc-1`.
4.  Führe **Upload** aus.
5.  (Optional) Nutze **Upload Filesystem Image**, um LittleFS vorab zu beschreiben.

### 2. Desktop Client
1.  Navigiere in den Ordner `client/`.
2.  Installiere die Abhängigkeiten:
    ```bash
    pip install -r requirements.txt
    ```
3.  Starte die App:
    ```bash
    python main.py
    ```

## 📖 Bedienung
1.  **Verbinden:** Gib die IP-Adresse des ESP32 (siehe Serial Monitor) in der App ein und klicke auf "Connect".
2.  **Upload:** Klicke auf "Select Image & Upload". Jedes Bild wird automatisch auf 64x64 skaliert und als GIF konvertiert.
3.  **Wiedergabe:** Doppelklicke eine Datei in der Liste für Einzelwiedergabe oder klicke "Loop All" für eine Playlist.
4.  **Helligkeit:** Nutze den Slider, um die Matrix-Helligkeit in Echtzeit anzupassen.

## ⚠️ Wichtige Hinweise
*   **PSRAM:** Der Code ist für OPI PSRAM optimiert. Falls dein Board kein PSRAM hat, muss der Buffer-Modus in der Library angepasst werden (Gefahr von Heap-Overflow bei großen GIFs).
*   **Stromversorgung:** Betreibe die Matrix niemals nur über den USB-Port des ESP32, da die Stromspitzen den Controller beschädigen können.

---
*Entwickelt für ESP32-S3 & HUB75 Matrix Panels.*
