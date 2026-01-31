#include "DisplayManager.h"

MatrixPanel_I2S_DMA* DisplayManager::dma = nullptr;
std::set<void*> DisplayManager::validFiles;

// --- Callbacks for AnimatedGIF ---
void* DisplayManager::GIFOpenFile(const char *fname, int32_t *pSize) {
    File f = LittleFS.open(fname);
    if (f) {
        *pSize = f.size();
        File* fPtr = new File(f);
        validFiles.insert((void*)fPtr);
        Serial.printf("GIFOpen: %s -> %p (Size: %d bytes)\n", fname, fPtr, *pSize);
        return (void*)fPtr;
    }
    Serial.printf("GIFOpen FAILED: %s\n", fname);
    return NULL;
}

void DisplayManager::GIFCloseFile(void *pHandle) {
    if (!pHandle) return;
    
    if (validFiles.find(pHandle) != validFiles.end()) {
        File *f = static_cast<File*>(pHandle);
        Serial.printf("GIFClose: %p\n", f);
        f->close();
        delete f;
        validFiles.erase(pHandle);
    } else {
        Serial.printf("GIFClose: Ignored invalid/double-free handle %p\n", pHandle);
    }
}

int32_t DisplayManager::GIFReadFile(GIFFILE *pFile, uint8_t *pBuf, int32_t iLen) {
    File *f = static_cast<File*>(pFile->fHandle);
    if (f) {
        // Safe Read Workaround for PSRAM/Alignment issues:
        // Read into internal stack buffer first, then copy.
        // iLen is usually small (chunk size).
        if (iLen > 256) {
            // Direct read for large chunks (hope for the best or implement loop)
            // But GIF chunks are usually small (255 bytes).
            return f->read(pBuf, iLen); 
        }
        
        uint8_t tempBuf[256]; // Stack buffer (Internal RAM)
        int32_t r = f->read(tempBuf, iLen);
        if (r > 0) {
            memcpy(pBuf, tempBuf, r);
        }
        
        if (r != iLen) {
             if(Serial) Serial.printf("GIFRead Error: Requested %d, got %d\n", iLen, r);
        }
        return r;
    }
    return 0;
}

int32_t DisplayManager::GIFSeekFile(GIFFILE *pFile, int32_t iPosition) {
    File *f = static_cast<File*>(pFile->fHandle);
    if (f) {
        if (f->seek(iPosition)) return iPosition;
        Serial.printf("GIFSeek Error: Pos %d failed. Size: %d\n", iPosition, f->size());
    }
    return -1;
}

void DisplayManager::GIFDraw(GIFDRAW *pDraw) {
    if (!dma) return;
    
    uint8_t *s = pDraw->pPixels;
    uint16_t *usPalette = pDraw->pPalette;
    int y = pDraw->iY + pDraw->y;
    int iWidth = pDraw->iWidth;
    int x_offset = pDraw->iX;

    // Safety: Skip lines outside the matrix
    if (y < 0 || y >= PANEL_RES_Y) return;

    // Handle Transparency and Background
    // Method 2: Restore to background color
    if (pDraw->ucDisposalMethod == 2) { 
        for (int x = 0; x < iWidth; x++) {
            if (s[x] == pDraw->ucTransparent) s[x] = pDraw->ucBackground;
        }
        pDraw->ucHasTransparency = 0;
    }

    // Draw scanline
    for (int x = 0; x < iWidth; x++) {
        int real_x = x_offset + x;
        if (real_x < 0 || real_x >= PANEL_RES_X) continue;

        if (pDraw->ucHasTransparency && s[x] == pDraw->ucTransparent) continue;
        dma->drawPixel(real_x, y, usPalette[s[x]]);
    }
}

// ... Class Implementation ...

void DisplayManager::begin(FileManager* fm) {
    fileMgr = fm;
    
    Serial.println("DisplayManager: Configuring HUB75...");
    HUB75_I2S_CFG mxconfig(PANEL_RES_X, PANEL_RES_Y, PANEL_CHAIN);
    mxconfig.gpio.r1 = R1_PIN; mxconfig.gpio.g1 = G1_PIN; mxconfig.gpio.b1 = B1_PIN;
    mxconfig.gpio.r2 = R2_PIN; mxconfig.gpio.g2 = G2_PIN; mxconfig.gpio.b2 = B2_PIN;
    mxconfig.gpio.a = A_PIN; mxconfig.gpio.b = B_PIN; mxconfig.gpio.c = C_PIN;
    mxconfig.gpio.d = D_PIN; mxconfig.gpio.e = E_PIN;
    mxconfig.gpio.lat = LAT_PIN; mxconfig.gpio.oe = OE_PIN; mxconfig.gpio.clk = CLK_PIN;
    
    Serial.println("DisplayManager: Allocating DMA object...");
    dma = new MatrixPanel_I2S_DMA(mxconfig);
    
    Serial.println("DisplayManager: Calling dma->begin()...");
    if(dma->begin())
        Serial.println("DisplayManager: DMA begin success");
    else
        Serial.println("DisplayManager: DMA begin FAILED");

    dma->setBrightness8(DEFAULT_BRIGHTNESS);
    dma->setRotation(DEFAULT_ROTATION);
    dma->clearScreen();

    // Allocate 3 Buffers for Triple Buffering (36KB total)
    // Use PSRAM (SPIRAM) to save internal SRAM for GIF decoding
    size_t bufSize = PANEL_RES_X * PANEL_RES_Y * 3;
    netBuffer   = (uint8_t*)heap_caps_malloc(bufSize, MALLOC_CAP_SPIRAM);
    readyBuffer = (uint8_t*)heap_caps_malloc(bufSize, MALLOC_CAP_SPIRAM);
    drawBuffer  = (uint8_t*)heap_caps_malloc(bufSize, MALLOC_CAP_SPIRAM);

    if (!netBuffer || !readyBuffer || !drawBuffer) {
        Serial.println("DisplayManager: Failed to allocate PSRAM buffers! Trying internal RAM...");
        netBuffer   = (uint8_t*)heap_caps_malloc(bufSize, MALLOC_CAP_8BIT);
        readyBuffer = (uint8_t*)heap_caps_malloc(bufSize, MALLOC_CAP_8BIT);
        drawBuffer  = (uint8_t*)heap_caps_malloc(bufSize, MALLOC_CAP_8BIT);
    }

    if (!netBuffer || !readyBuffer || !drawBuffer) {
        Serial.println("DisplayManager: Failed to allocate internal RAM buffers!");
    }
    
    Serial.println("DisplayManager: Init GIF Decoder...");
    gif.begin(LITTLE_ENDIAN_PIXELS);
    Serial.println("DisplayManager: Init done.");
}

void DisplayManager::setBrightness(uint8_t val) {
    std::lock_guard<std::mutex> lk(cmdMutex);
    pendingCmd = CMD_SET_BRIGHTNESS;
    pendingInt = val;
    cmdPending = true;
}

void DisplayManager::setLoopDuration(unsigned long ms) {
    std::lock_guard<std::mutex> lk(cmdMutex);
    pendingCmd = CMD_SET_DURATION;
    pendingVal = ms;
    cmdPending = true;
}

void DisplayManager::setRotation(int r) {
    std::lock_guard<std::mutex> lk(cmdMutex);
    pendingCmd = CMD_SET_ROTATION;
    pendingInt = r;
    cmdPending = true;
}

void DisplayManager::setPlaylist(const String& name) {
    std::lock_guard<std::mutex> lk(cmdMutex);
    pendingCmd = CMD_SET_PLAYLIST;
    pendingParam = name;
    cmdPending = true;
}

void DisplayManager::setShuffle(bool enabled) {
    std::lock_guard<std::mutex> lk(cmdMutex);
    pendingCmd = CMD_SET_SHUFFLE;
    pendingBool = enabled;
    cmdPending = true;
}

void DisplayManager::startStreaming() {
    std::lock_guard<std::mutex> lk(cmdMutex);
    pendingCmd = CMD_START_STREAM;
    cmdPending = true;
    allowIncomingStream = true; // Accept data immediately
}

void DisplayManager::showText(const String& text, bool scroll) {
    std::lock_guard<std::mutex> lk(cmdMutex);
    pendingCmd = CMD_SHOW_TEXT;
    pendingParam = text;
    pendingBool = scroll;
    cmdPending = true;
}

void DisplayManager::setTextColor(uint8_t r, uint8_t g, uint8_t b) {
    std::lock_guard<std::mutex> lk(cmdMutex);
    pendingCmd = CMD_SET_TEXT_COLOR;
    pendingR = r;
    pendingG = g;
    pendingB = b;
    cmdPending = true;
}

void DisplayManager::setTextSize(uint8_t size) {
    std::lock_guard<std::mutex> lk(cmdMutex);
    pendingCmd = CMD_SET_FONT_SIZE;
    pendingInt = size;
    cmdPending = true;
}

// Handling fragmented WebSocket frames safely
bool DisplayManager::handleStreamChunk(uint8_t* data, size_t len, size_t index, size_t totalLen) {
    if (!allowIncomingStream || !netBuffer) return false;
    
    size_t bufferSize = PANEL_RES_X * PANEL_RES_Y * 3;
    if (index + len > bufferSize) return false;

    memcpy(netBuffer + index, data, len);

    // Frame complete?
    if (index + len == totalLen) {
        // Swap netBuffer and readyBuffer
        std::lock_guard<std::mutex> lk(streamMutex);
        std::swap(netBuffer, readyBuffer);
        newFrameAvailable = true;
        return true; // Notify caller to send ACK
    }
    return false;
}

// --- Thread-Safe Public Commands ---

void DisplayManager::playFile(const String& path) {
    std::lock_guard<std::mutex> lk(cmdMutex);
    pendingCmd = CMD_PLAY_SINGLE;
    pendingParam = path;
    cmdPending = true;
}

void DisplayManager::playAll(const String& playlist) {
    std::lock_guard<std::mutex> lk(cmdMutex);
    pendingCmd = CMD_PLAY_ALL;
    pendingParam = playlist;
    cmdPending = true;
}

void DisplayManager::stop() {
    std::lock_guard<std::mutex> lk(cmdMutex);
    pendingCmd = CMD_STOP;
    cmdPending = true;
}

void DisplayManager::forceStop() {
    // Synchronously stop everything to release file handles immediately
    // We lock the cmdMutex to ensure the loop doesn't try to draw while we close
    std::lock_guard<std::mutex> lk(cmdMutex);
    std::lock_guard<std::mutex> gifLk(gifMutex);
    
    // Reset state
    allowIncomingStream = false;
    isStreaming = false;
    isPlaying = false;
    isTextMode = false;
    
    // Close file immediately
    gif.close();
    
    // We don't clear screen here to avoid delaying the network response, 
    // but we ensure the file handle is free.
    Serial.println("DisplayManager: Force Stopped.");
}

// --- Internal Logic (Main Loop Context) ---

void DisplayManager::freeGifData() {
    if (currentGifData) {
        free(currentGifData);
        currentGifData = nullptr;
    }
}

void DisplayManager::_playFile(const String& path) {
    std::lock_guard<std::mutex> gifLk(gifMutex);
    isStreaming = false;
    isTextMode = false;
    singleMode = true;
    currentFile = path;
    gif.close(); 
    freeGifData(); // Free old file
    
    // Load file to RAM (PSRAM preferred)
    File f = LittleFS.open(path);
    if (!f) {
        if(Serial) Serial.printf("Failed to open file: %s\n", path.c_str());
        return;
    }
    size_t len = f.size();
    if (len == 0) {
        f.close();
        return;
    }
    
    // Allocate buffer
    currentGifData = (uint8_t*)heap_caps_malloc(len, MALLOC_CAP_SPIRAM);
    if (!currentGifData) {
        // Fallback to internal RAM if small enough? Or fail.
        currentGifData = (uint8_t*)malloc(len);
    }
    
    if (!currentGifData) {
        if(Serial) Serial.println("Failed to allocate RAM for GIF!");
        f.close();
        return;
    }
    
    // Read all
    f.read(currentGifData, len);
    f.close();
    
    gif.begin(LITTLE_ENDIAN_PIXELS); 
    // Open from memory
    if (gif.open(currentGifData, len, GIFDraw)) {
        isPlaying = true;
        currentGifStartTime = millis();
        if(Serial) Serial.printf("Playing RAM: %s (%d bytes)\n", path.c_str(), len);
        
        dma->clearScreen();
        int tDelay = 0;
        if (gif.playFrame(false, &tDelay)) {
             if (tDelay < 1) tDelay = 1;
             nextGifFrameTime = millis() + tDelay;
        } else {
             nextGifFrameTime = millis();
        }
        pendingFileNotification = path;
    } else {
        if(Serial) Serial.printf("Failed to open GIF from RAM. Error: %d\n", gif.getLastError());
        freeGifData();
    }
}

void DisplayManager::_playAll(const String& playlistName) {
    std::lock_guard<std::mutex> gifLk(gifMutex);

    isStreaming = false;
    isTextMode = false;
    singleMode = false;
    if (playlistName != "") currentPlaylist = playlistName;
    
    // 1. Build Meta-Playlist (List of Folders)
    metaPlaylist.clear();
    
    if (currentPlaylist == "ALL") {
        std::vector<String> all = fileMgr->listPlaylists();
        for(const auto& p : all) {
            // Filter system folders and "ALL" keyword
            if(p != "ALL" && p != "System Volume Information") {
                metaPlaylist.push_back(p);
            }
        }
        
        // Shuffle Folders
        if (isShuffle && metaPlaylist.size() > 1) {
             for (int i = 0; i < metaPlaylist.size(); i++) {
                 int r = random(i, metaPlaylist.size());
                 std::swap(metaPlaylist[i], metaPlaylist[r]);
             }
        }
    } else {
        // Single Folder Mode
        metaPlaylist.push_back(currentPlaylist);
    }
    
    if (metaPlaylist.empty()) {
        _stop();
        Serial.println("No playlists found.");
        return;
    }
    
    metaPlaylistIndex = 0;
    loadPlaylistFolder(metaPlaylist[0]);
}

void DisplayManager::loadPlaylistFolder(const String& folder) {
    // Note: Called from _playAll or loadNextInPlaylist, so gifMutex is already locked (or should be)
    // However, listGifs interacts with FS, which is slow but safe.
    
    Serial.printf("Loading Playlist Folder: %s\n", folder.c_str());
    playlist = fileMgr->listGifs(folder);
    
    if (playlist.empty()) {
        Serial.println("Empty folder, skipping...");
        // Handle empty folder by forcing next immediately? 
        // We'll let loadNextInPlaylist handle empty logic if possible, or just recurse.
        // For safety, just stop if *everything* is empty, but here we just return.
        // loadNextInPlaylist will see empty playlist and try to move on.
    } else {
        // Shuffle Files
        if (isShuffle && playlist.size() > 1) {
            for (int i = 0; i < playlist.size(); i++) {
                int r = random(i, playlist.size());
                std::swap(playlist[i], playlist[r]);
            }
        }
    }
    
    playlistIndex = -1; 
    loadNextInPlaylist();
}

void DisplayManager::_stop() {
    std::lock_guard<std::mutex> gifLk(gifMutex);
    allowIncomingStream = false;
    isStreaming = false;
    isPlaying = false;
    isTextMode = false;
    gif.close();
    freeGifData();
    dma->clearScreen();
}

void DisplayManager::loadNextInPlaylist() {
    // 1. Check if we need to loop or change folder
    playlistIndex++;
    
    if (playlist.empty() || playlistIndex >= playlist.size()) {
        // End of current folder
        
        if (metaPlaylist.size() > 1) {
             // Move to next folder
             metaPlaylistIndex++;
             if (metaPlaylistIndex >= metaPlaylist.size()) {
                 metaPlaylistIndex = 0; // Loop Meta Playlist
                 // Reshuffle folders on loop? Optional.
             }
             loadPlaylistFolder(metaPlaylist[metaPlaylistIndex]);
             return; // loadPlaylistFolder calls loadNextInPlaylist
        } else {
            // Single Folder Loop
            playlistIndex = 0;
            if (playlist.empty()) return; // Safety
            
            // Reshuffle for variation on repeat
            if (isShuffle && playlist.size() > 1) {
                for (int i = 0; i < playlist.size(); i++) {
                    int r = random(i, playlist.size());
                    std::swap(playlist[i], playlist[r]);
                }
            }
        }
    }
    
    currentFile = playlist[playlistIndex];
    
    // std::lock_guard<std::mutex> gifLk(gifMutex); // Caller must hold lock!
    gif.close();
    freeGifData(); // Clear old data
    
    // Load to RAM
    File f = LittleFS.open(currentFile);
    if (f) {
        size_t len = f.size();
        currentGifData = (uint8_t*)heap_caps_malloc(len, MALLOC_CAP_SPIRAM);
        if (!currentGifData) currentGifData = (uint8_t*)malloc(len);
        
        if (currentGifData) {
            f.read(currentGifData, len);
            f.close();
            
            gif.begin(LITTLE_ENDIAN_PIXELS);
            if (gif.open(currentGifData, len, GIFDraw)) {
                isPlaying = true;
                currentGifStartTime = millis();
                if(Serial) Serial.printf("[%s] Playing RAM: %s\n", metaPlaylist[metaPlaylistIndex].c_str(), currentFile.c_str());
                
                dma->clearScreen();
                int tDelay = 0;
                if (gif.playFrame(false, &tDelay)) {
                     if (tDelay < 1) tDelay = 1;
                     nextGifFrameTime = millis() + tDelay;
                } else {
                     nextGifFrameTime = millis();
                }
                pendingFileNotification = currentFile; 
                return; // Success
            }
        } else {
            f.close();
        }
    }
    
    if(Serial) Serial.printf("Skipping broken GIF: %s\n", currentFile.c_str());
    loadNextInPlaylist(); // Recursive retry
}

void DisplayManager::_showText(const String& text, bool scroll) {
    if (text == "") {
        // --- Restore Previous State ---
        if (isTextMode) {
            isTextMode = false;
            dma->clearScreen();
            
            Serial.println("DisplayManager: Text cleared. Restoring previous state...");
            
            if (savedIsPlaying) {
                if (savedSingleMode) {
                    _playFile(savedCurrentFile);
                } else {
                    // Restore playlist mode
                    // We set the playlist back but we might want to continue where we left off?
                    // For simplicity, we just restart the playlist or resume if we could.
                    // _playAll resets everything. Let's try to be smart.
                    
                    // Restore internal flags
                    singleMode = false;
                    currentPlaylist = savedCurrentPlaylist;
                    
                    // We need to restart the GIF that was playing
                    _playFile(savedCurrentFile); 
                    
                    // Important: _playFile sets singleMode=true. We must correct it back to false
                    // so the loop logic knows to continue the playlist.
                    singleMode = false; 
                }
            } else {
                // Was stopped
                _stop();
            }
        }
        return;
    }

    // --- Enter Text Mode ---
    
    // Only save state if we are NOT already in text mode (to avoid overwriting backup with text mode state)
    if (!isTextMode) {
        Serial.println("DisplayManager: Saving state before showing text...");
        savedIsPlaying = isPlaying;
        savedSingleMode = singleMode;
        savedCurrentFile = currentFile;
        savedCurrentPlaylist = currentPlaylist;
        
        // Stop current animation without clearing variables we just saved
        // _stop() clears isPlaying, so we saved it just in time.
        _stop(); 
    }

    isTextMode = true;
    textMessage = text;
    textScroll = scroll;
    
    // Setup Font
    dma->setTextSize(textSize); // Standard 5x7 or scaled
    dma->setTextWrap(false); // Important for scrolling
    
    // Calculate Bounds
    int16_t x1, y1;
    uint16_t w, h;
    dma->getTextBounds(textMessage, 0, 0, &x1, &y1, &w, &h);
    textWidth = w;
    
    if (textScroll) {
        textX = PANEL_RES_X; // Start from right
        lastScrollTime = millis();
    } else {
        // Static Text: Draw ONCE here, do nothing in loop
        textX = (PANEL_RES_X - (int)w) / 2;
        dma->setTextColor(textColor);
        // Center vertically: (64 - 8) / 2 = 28
        dma->setCursor(textX, (PANEL_RES_Y - 7) / 2); 
        dma->print(textMessage);
    }
}

void DisplayManager::loop() {
    // 1. Check for pending commands safely
    CmdType cmdToExec = CMD_NONE;
    String paramToExec;
    unsigned long valToExec = 0;
    int intToExec = 0;
    bool boolToExec = false;
    uint8_t rExec, gExec, bExec;
    
    {
        std::lock_guard<std::mutex> lk(cmdMutex);
        if (cmdPending) {
            cmdToExec = pendingCmd;
            paramToExec = pendingParam;
            valToExec = pendingVal;
            intToExec = pendingInt;
            boolToExec = pendingBool;
            rExec = pendingR; gExec = pendingG; bExec = pendingB;
            cmdPending = false;
            pendingCmd = CMD_NONE; 
        }
    }

    // 2. Execute command
    if (cmdToExec != CMD_NONE) {
        switch (cmdToExec) {
            case CMD_PLAY_SINGLE: _playFile(paramToExec); break;
            case CMD_PLAY_ALL:    _playAll(paramToExec); break;
            case CMD_STOP:        _stop(); break;
            case CMD_SET_DURATION: 
                loopDurationMs = valToExec; 
                break;
            case CMD_SET_BRIGHTNESS:
                currentBrightness = (uint8_t)intToExec;
                if (dma) dma->setBrightness8(currentBrightness);
                break;
            case CMD_SET_ROTATION:
                if (dma) {
                    dma->setRotation(intToExec);
                    dma->clearScreen(); 
                }
                break;
            case CMD_START_STREAM:
                _stop(); // Stop any GIF
                isStreaming = true;
                allowIncomingStream = true;
                break;
            case CMD_SHOW_TEXT:
                _showText(paramToExec, boolToExec);
                break;
            case CMD_SET_PLAYLIST:
                currentPlaylist = paramToExec;
                if (!singleMode && isPlaying) _playAll(); // Restart playlist with new filter
                break;
            case CMD_SET_SHUFFLE:
                isShuffle = boolToExec;
                Serial.printf("Shuffle Mode: %d\n", isShuffle);
                break;
            case CMD_SET_TEXT_COLOR:
                if (dma) textColor = dma->color565(rExec, gExec, bExec);
                break;
            case CMD_SET_FONT_SIZE:
                textSize = (uint8_t)intToExec;
                if (textSize < 1) textSize = 1;
                break;
            default: break;
        }
    }

    // 3. Play Frame
    if (isStreaming) {
        bool hasNewFrame = false;
        
        // 1. Check for new frame and swap buffers (Atomic & Fast)
        {
            std::lock_guard<std::mutex> lk(streamMutex);
            if (newFrameAvailable) {
                std::swap(readyBuffer, drawBuffer);
                newFrameAvailable = false;
                hasNewFrame = true;
            }
        }

        // 2. Draw frame (Slow operation - outside mutex!)
        if (hasNewFrame && drawBuffer) {
            int idx = 0;
            for (int y = 0; y < PANEL_RES_Y; y++) {
                for (int x = 0; x < PANEL_RES_X; x++) {
                    uint8_t r = drawBuffer[idx++];
                    uint8_t g = drawBuffer[idx++];
                    uint8_t b = drawBuffer[idx++];
                    dma->drawPixelRGB888(x, y, r, g, b);
                }
            }
        }
        yield();
    }
    else if (isTextMode && textScroll) { // Update only if scrolling
        unsigned long now = millis();
        // Scroll speed: 50ms delay = 20 FPS
        if (now - lastScrollTime > 50) { 
            lastScrollTime = now;
            
            textX--;
            if (textX < -textWidth) {
                textX = PANEL_RES_X; // Loop
            }
            
            dma->clearScreen();
            dma->setTextColor(textColor);
            dma->setCursor(textX, (PANEL_RES_Y - 7) / 2); 
            dma->print(textMessage);
        }
        yield();
    }
    else if (isPlaying && !isStreaming) {
        if (millis() >= nextGifFrameTime) {
            std::lock_guard<std::mutex> gifLk(gifMutex);
            if (!isPlaying) return;

            int tDelay = 0;
            int result = gif.playFrame(false, &tDelay);
            
            if (result == 1) { 
                // Frame decoded
                if (tDelay < 1) tDelay = 1; // Minimum 1ms
                nextGifFrameTime = millis() + tDelay;
            } 
            else if (result == 0) { 
                // End of animation reached
                unsigned long now = millis();
                unsigned long elapsed = now - currentGifStartTime;
                
                // Fail-Safe: If duration is broken/zero, force defaults
                if (loopDurationMs < 1000) {
                    if(Serial) Serial.printf("Warning: loopDurationMs was %lu, forcing to 10000\n", loopDurationMs);
                    loopDurationMs = 10000;
                }

                if(Serial) Serial.printf("GIF End: elapsed=%lu / %lu ms. Single: %d\n", elapsed, loopDurationMs, singleMode);

                if (singleMode || (elapsed < loopDurationMs)) {
                    // Loop again
                    gif.reset();
                    nextGifFrameTime = millis() + 1;
                } else {
                    // Time is up, next GIF
                    if(Serial) Serial.println("Time up. Next GIF.");
                    loadNextInPlaylist();
                }
            }
            else {
                // Error (-1)
                int err = gif.getLastError();
                // 6 = GIF_EARLY_EOF. Often harmless for looped animations if file is slightly truncated.
                // If we are supposed to loop (time not up), try to reset instead of skipping.
                unsigned long now = millis();
                unsigned long elapsed = now - currentGifStartTime;
                
                if (err == 6 && (singleMode || elapsed < loopDurationMs)) {
                     if(Serial) Serial.printf("GIF Early EOF (6). Looping... (%lu/%lu)\n", elapsed, loopDurationMs);
                     gif.reset();
                     nextGifFrameTime = millis() + 50; 
                }
                else {
                    if(Serial) Serial.printf("GIF Decode Error: %d, skipping...\n", err);
                    if (singleMode) {
                        gif.reset();
                        nextGifFrameTime = millis() + 2000; // Wait 2s on fatal error
                    } else {
                        loadNextInPlaylist();
                    }
                }
            }
        }
        yield(); 
    }

    // 4. Handle Notification (Outside Mutex to avoid deadlock with Network Task)
    String notifyPath = "";
    {
        // We can peek/clear it safely. Since string copy is cheap.
        // Actually, we need to protect access to pendingFileNotification string?
        // It's modified under gifMutex/cmdMutex context?
        // _playFile uses gifMutex. loadNextInPlaylist uses gifMutex (via caller).
        // So it's protected by gifMutex.
        // We should lock gifMutex to read it.
        std::lock_guard<std::mutex> gifLk(gifMutex);
        if (pendingFileNotification != "") {
            notifyPath = pendingFileNotification;
            pendingFileNotification = "";
        }
    }
    
    if (notifyPath != "" && onFileChange) {
        onFileChange(notifyPath);
    }
}