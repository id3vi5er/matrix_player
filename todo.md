# MQTT & Home Assistant Integration Plan (COMPLETED)

All planned MQTT and Home Assistant features have been successfully implemented. The system now supports:
- Full auto-discovery in Home Assistant (Light, Select, Text, Number, Switch).
- Remote control of brightness, playlist, shuffle, loop duration, and text display.
- Real-time status updates.

## Pending Tasks & Known Issues

### 1. Stability & Bugs
*   [ ] **Delete Large Playlists:** Deleting a folder with many files (e.g. >50 GIFs) can cause the ESP32 to trigger a Watchdog Timeout (WDT) and reboot. This is due to the synchronous `LittleFS.remove` loop blocking the main thread for too long.
    *   *Solution Idea:* Yield (`delay(1)`) more frequently in the delete loop or move deletion to a separate FreeRTOS task.
*   [ ] **Upload Reliability:** While greatly improved by `delay(1)` throttling, very large files or bad network conditions can still occasionally fail.
*   [ ] **Stream Lag:** Live stream is stable but latency could be further reduced by optimizing the compression/encoding on the client side (maybe simple RLE?).

### 2. Client / GUI Features
*   [ ] **Playlist Management in GUI:** Currently, creating new playlists requires manually typing a folder name during upload. A "Create Folder" button or drag-and-drop into a tree view would be better.
*   [ ] **Preview Cache:** The client re-downloads images for preview every time. A local LRU cache for thumbnails would speed up the library view.

### 3. Firmware Features
*   [ ] **OTA via GUI:** The "Update Firmware" button exists but the backend logic for file selection and POST request needs rigorous testing.
*   [ ] **Transition Effects:** Currently, GIFs cut hard to the next one. Simple fade-to-black or cross-dissolve would look nicer.

### 4. Twitch Integration
*   [x] **DONE:** Standalone GUI (`twitch_emotes.py`).
*   [x] **DONE:** FFZ / 7TV / BTTV Support.
*   [x] **DONE:** Config UI.
*   [ ] **Feature:** Allow filtering emotes (e.g. only from Subs, or only specific keywords).
*   [ ] **Feature:** "Hype Train" mode (special visual effects on the matrix when a Hype Train starts).

## 5. Future Twitch Features (Brainstorming)

### Interactive Events
*   [ ] **🔥 Emote-Combo / Hype-Meter:** Detect spam of the same emote (e.g. 10x in 5s) and trigger a special "COMBO!" animation or blink effect.
*   [ ] **🎰 Emote-Slotmachine:** Chat command `!roll` that cycles through random emotes and stops on one (win/loss mechanic).
*   [ ] **🎨 r/place Pixel-Canvas:** Users set pixels via chat commands (`!pixel x y color`). The bot maintains a local image and uploads it to the matrix upon changes.

### Alerts & Moderation

*   [ ] **🚨 Raid Welcome:** Detect raids via PubSub/Chat, fetch the raider's profile picture from Twitch API, crop it to circle/square 64x64, and display it with a welcome text.

*   [ ] **🛡️ Blacklist:** A local file (`blacklist.txt`) to block specific emote IDs or names (anti-troll / NSFW protection).



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

    *   [ ] **Rolling Cache Strategy:** Solve storage limits without SD card by automatically managing LittleFS space.

        *   **Implementation:** LRU-Cache for emote usage counters.

        *   **Deletion Logic:** Delete file with lowest usage (LFU) or oldest access (LRU) when space is low.

    *   [ ] **PSRAM Buffering:** Use PSRAM as the primary buffer for emote data to minimize LittleFS read/write operations.

    *   [ ] **Performance Goals:**

        *   Minimize LittleFS interaction.

        *   Target Cache-Hit-Rate > 90%.

        *   Dynamic Cache Sizing.
