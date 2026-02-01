# 📟 Projektverlauf: ESP32-64x64 RGB Matrix

## 🗓 Stand: 01. Februar 2026

### 🎮 Twitch Bot & r/place Canvas
1.  **Twitch Bot Client (`twitch_emotes.py`):**
    *   **Emote History:** GUI-Widget für die letzten 20 Emotes mit Zeitstempel und asynchron geladenen Vorschaubildern (Caching im Thread).
    *   **Blacklist System:** Emotes per Rechtsklick blockieren. Persistente Speicherung in `blacklist.json`. Verhindert Spam und unerwünschte Inhalte.
    *   **Rolling Storage (LRU):** Automatische Speicherverwaltung für den `/twitch/` Ordner. Konfigurierbarer Schwellenwert (z.B. ab 80% voll löschen bis 50%). GUI-Anzeige mit MB- und Prozent-Werten.
    *   **Auto-Refresh:** Automatisches Synchronisieren der Dateiliste und Speicherstatistik (konfigurierbarer Timer).
    *   **Sync Protection:** Wiedergabe pausiert kurzzeitig während des Empfangs der Dateiliste, um Konflikte zu vermeiden.
    *   **Flash-Haltbarkeit:** Simulation ergab >1000 Jahre Lebensdauer auch bei intensiver Nutzung.

2.  **r/place Pixel Game:**
    *   **Interaktives Canvas:** 64x64 Leinwand, die von Twitch-Usern bemalt werden kann. Ersetzt das Idle-Bild.
    *   **Befehle:**
        *   `!px <x> <y> <color>`: Einzelnen Pixel setzen.
        *   `!ln <x1> <y1> <x2> <y2> <color>`: Linie zeichnen.
        *   `!cr <x> <y> <r> <color>`: Kreis zeichnen.
    *   **Smart Upload:** Das Canvas wird nur bei Änderungen (`dirty flag`) hochgeladen, um Bandbreite und Flash zu schonen.
    *   **Priorisierung:** Emotes unterbrechen das Canvas (High Priority). Nach Ablauf des Emotes wird automatisch das aktuelle Canvas wieder angezeigt.
    *   **GUI:** Live-Vorschau des Canvas im Client, Reset-Button und Force-Upload.

### 🛠 Firmware & System Optimierungen
3.  **Live-Stream Fixes:**
    *   **Latenz:** "Buffer Bloat" behoben durch Timeout-Logik im Client und sofortige Datenannahme in der Firmware (`allowIncomingStream`). Stream läuft nun synchron.
    *   **Stream Settings:** Neues Einstellungsmenü im Client für Crop, Scale (Fit/Fill/Stretch) und Zoom während des Streams (mit Live-Vorschau).
    *   **FPS:** Geglättete FPS-Anzeige im Client.

4.  **GIF Wiedergabe:**
    *   **Seek-Fix:** `GIFSeekFile` korrigiert (Return -1 bei Fehler), was das Abbrechen von Animationen behebt.
    *   **Disposal Method:** Client konvertiert nun standardmäßig mit `Disposal=1` (Overlay) für flüssigere Darstellung auf der Matrix.

5.  **Robustheit:**
    *   **Async Deletion:** Löschen großer Playlisten (oder des Twitch-Ordners) blockiert nicht mehr den Main-Loop (WDT Resets behoben).
    *   **Thread Safety:** Sauberer Shutdown von Threads im Python-Client (`closeEvent`).

### 📚 Dokumentation
6.  **README Overhaul:**
    *   Neuer Header mit Badges.
    *   Inhaltsverzeichnis.
    *   OAuth Token Anleitung (twitchtokengenerator.com).
    *   Screenshots aktualisiert.
    *   Roadmap Verweis auf `todo.md`.

## 🗓 Stand: 25. Januar 2026

### 🚀 Implementierte Features
1. **Playlist-System:**
   - LittleFS-Struktur unterstützt nun Unterordner (z.B. `/Default/`, `/Urlaub/`).
   - `FileManager` wurde erweitert, um Ordner als Playlisten zu listen und Inhalte gezielt abzurufen.
   - `DisplayManager` kann nun zwischen Playlisten wechseln und filtert die Wiedergabe entsprechend.

2. **Stapelverarbeitung (Batch Upload):**
   - Der Python-Client erlaubt die Auswahl mehrerer Dateien im `UploadDialog`.
   - Ein "Playlist / Tag"-Feld im Dialog bestimmt den Zielordner auf dem ESP32.
   - Der Client konvertiert alle Bilder mit den Einstellungen des ersten Bildes und lädt sie sequenziell hoch.

3. **Pfad- & Cache-Optimierung:**
   - Absolute Pfad-Handhabung in der Firmware korrigiert (Vermeidung von Doppelslashes).
   - Cache-Busting im Client durch Zeitstempel-Parameter (`?t=...`) für Vorschaubilder implementiert.

### 🚀 Implementierte Features & Fixes (25. Januar 2026 - Update)
... (vorherige Punkte) ...
4. **Pfad-Rekonstruktion Fix:**
   - `FileManager::listGifs` korrigiert: Dateipfade in Unterordnern werden nun korrekt mit dem Ordnernamen rekonstruiert, unabhängig davon, ob `file.name()` den vollen Pfad oder nur den Dateinamen liefert. Dies behebt das Problem der "schwarzen Bilder" (da Dateien nun gefunden werden) und das fehlgeschlagene Löschen.
5. **Client-Cache Deaktivierung:**
   - Lokaler Bild-Cache im Python-Client für die Remote-Vorschau deaktiviert. Zusammen mit dem URL-Zeitstempel stellt dies sicher, dass nach einem Upload oder Dateiwechsel sofort das aktuelle Bild angezeigt wird.
6. **Robustheit beim Löschen:**
   - Zusätzliche Logging-Ausgaben und Existenz-Prüfungen in `FileManager::removeFile` hinzugefügt.

7. **Playlist Löschen:**
   - Feature implementiert, um ganze Playlisten (Ordner inkl. Inhalt) über den Client zu löschen.
   - Schutz für Root und `/Default` Ordner eingebaut.
   - UI Button und Sicherheitsabfrage im Client hinzugefügt.

8. **Shuffle Modus:**
   - Zufallswiedergabe für Playlisten implementiert.
   - Firmware: Logik in `loadNextInPlaylist` und neues Kommando.
   - Client: Checkbox "Shuffle Playlist" in den Geräteeinstellungen.

9. **Erhöhte Bilddauer:**
   - Maximale Anzeigedauer im Client von 300s (5 Min) auf 86400s (24 Std) erhöht.

10. **Stabilitäts-Updates:**
    - `delay(1)` zum Main-Loop hinzugefügt, um "Network Starvation" zu verhindern.
    - Sicherheits-Verzögerung (10ms) beim Neustart eines GIFs eingebaut, um CPU-Spikes bei defekten/kurzen Dateien zu vermeiden.

### ⚠️ Gelöste Probleme
- [x] **Schwarze Bilder:** Behoben durch korrekte Pfad-Handhabung.
- [x] **Löschen fehlgeschlagen:** Behoben (Pfad-Mismatch war die Ursache).
- [x] **Vorschau-Verzögerung:** Optimiert durch Cache-Deaktivierung im Client.
- [x] **Playlist-Filter:** Client filtert nun Dateiliste passend zur gewählten Playlist.
- [x] **Playlist Loop:** Button-Text und Verhalten klargestellt.
- [x] **Bildwechsel-Flackern:** Optimiert durch "Open -> Clear -> Draw Frame 0" Logik.
- [x] **Upload Timeouts:** Timeout im Client auf 60s erhöht.
- [x] **Große Dateilisten:** Firmware JSON-Buffer auf 32KB erhöht und Client gegen `None`-Werte gehärtet.

### 🛠 Nächste Schritte
1. **Testen:** Shuffle Modus ausprobieren.
2. **MQTT Integration:** Start der im `todo.md` geplanten Home Assistant Anbindung.


### 📌 Wichtige Pin-Belegungen (ESP32-S3)
| Signal | GPIO | Signal | GPIO |
| :--- | :--- | :--- | :--- |
| **R1** | 42 | **A** | 4 |
| **G1** | 41 | **B** | 5 |
| **B1** | 40 | **C** | 6 |
| **R2** | 38 | **D** | 7 |
| **G2** | 39 | **E** | 15 |
| **B2** | 13 | **LAT** | 17 |
| **CLK** | 16 | **OE** | 1 |