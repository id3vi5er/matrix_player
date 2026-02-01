# MQTT & Home Assistant Integration Plan (COMPLETED)

All planned MQTT and Home Assistant features have been successfully implemented. The system now supports:
- Full auto-discovery in Home Assistant (Light, Select, Text, Number, Switch).
- Remote control of brightness, playlist, shuffle, loop duration, and text display.
- Real-time status updates.

## Pending Tasks & Known Issues

### 1. Stability & Bugs
*   [x] **DONE:** **Delete Large Playlists:** Yields and task handling implemented to prevent WDT reboots during long LittleFS operations.
*   [x] **DONE:** **Upload Reliability:** Throttling and retry logic improved stability.
*   [ ] **Stream Lag:** Live stream is stable but latency could be further reduced by optimizing the compression/encoding on the client side (maybe simple RLE?).

### 2. Client / GUI Features
*   [x] **DONE:** **Rolling Storage UI:** Configuration for threshold/target, MB display, and auto-refresh interval.
*   [x] **DONE:** **Auto-Refresh:** Timer-based synchronization of file list and storage stats.
*   [ ] **Playlist Management in GUI:** Currently, creating new playlists requires manually typing a folder name during upload. A "Create Folder" button or drag-and-drop into a tree view would be better.
*   [ ] **Preview Cache:** The client re-downloads images for preview every time. A local LRU cache for thumbnails would speed up the library view.

### 3. Firmware Features
*   [ ] **OTA via GUI:** The "Update Firmware" button exists but the backend logic for file selection and POST request needs rigorous testing.
*   [ ] **Transition Effects:** Currently, GIFs cut hard to the next one. Simple fade-to-black or cross-dissolve would look nicer.

### 4. Twitch Integration
*   [x] **DONE:** Standalone GUI (`twitch_emotes.py`).
*   [x] **DONE:** FFZ / 7TV / BTTV Support.
*   [x] **DONE:** Config UI.
*   [x] **DONE:** Emote History (with Thumbnails).
*   [x] **DONE:** Connection Toggle (Disconnect button).
*   [x] **DONE:** Blacklist System (GUI, Right-click block, JSON persistence).
*   [x] **DONE:** Sync Protection (Queue blocks during file list update).
*   [ ] **Feature:** "Hype Train" mode (special visual effects on the matrix when a Hype Train starts).
*   [ ] **Feature:** Filter emotes (Sub-only, Keywords).

## 5. Future Twitch Features (Brainstorming)

### Interactive Events
*   [ ] **🔥 Emote-Combo / Hype-Meter:** Detect spam of the same emote (e.g. 10x in 5s) and trigger a special "COMBO!" animation or blink effect.
*   [ ] **🎰 Emote-Slotmachine:** Chat command `!roll` that cycles through random emotes and stops on one (win/loss mechanic).
*   [ ] **🎨 r/place Pixel-Canvas:** Users set pixels via chat commands (`!pixel x y color`). The bot maintains a local image and uploads it to the matrix upon changes.

### Alerts & Moderation
*   [ ] **🚨 Raid Welcome:** Detect raids via PubSub/Chat, fetch the raider's profile picture from Twitch API, crop it to circle/square 64x64, and display it with a welcome text.

## 6. Hardware Expansion

### Micro-SD Card Support
*   [ ] **Task:** Integrate a Micro-SD card reader to handle larger amounts of animated Twitch emotes and GIFs, bypassing the LittleFS size limitations.
*   **Pin Mapping (ESP32-S3):**
    | SD Pin | Function | ESP32 GPIO / Connection | Notes |
    | :--- | :--- | :--- | :--- |
    | Pin 1 | DAT2 | NC | Optional 10k Pull-up |
    | Pin 2 | DAT3/CD | 3.3V | 10kΩ Pull-up only, NOT to ESP |
    | Pin 3 | CMD | GPIO 10 | + 10kΩ Pull-up to 3.3V |
    | Pin 4 | VDD | 3.3V | + 100nF & 10µF Caps |
    | Pin 5 | CLK | GPIO 9 | Direct to ESP32 |
    | Pin 6 | VSS (GND) | GND | Ground |
    | Pin 7 | DAT0 | GPIO 11 | + 10kΩ Pull-up to 3.3V |
    | Pin 8 | DAT1 | NC | Optional 10k Pull-up |
    | CD/SW | Case Switch | GPIO 12 | Switches to GND |

## 7. Memory & Storage Optimization (Software)
*   [x] **DONE:** PSRAM Buffering (Pre-load GIF to PSRAM for glitch-free playback).
*   [x] **DONE:** **Rolling Cache Strategy:** Automatic management of LittleFS space (LRU/LFU) for Twitch emotes is implemented.
*   [ ] **Performance Goals:**
    *   Minimize LittleFS interaction.
    *   Target Cache-Hit-Rate > 90%.
    *   Dynamic Cache Sizing.
