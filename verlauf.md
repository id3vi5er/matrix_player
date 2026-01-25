# 📟 Projektverlauf: ESP32-64x64 RGB Matrix

## 🗓 Stand: 25. Januar 2026

### 🚀 Implementierte Features (Heute)
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
