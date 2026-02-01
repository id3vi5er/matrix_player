#include "NetworkManager.h"
#include <Update.h>

NetworkManager::NetworkManager(DisplayManager* disp, FileManager* fm)
    : server(80), ws("/ws"), display(disp), fileMgr(fm) {}

void NetworkManager::begin() {
    WiFi.disconnect(true, true);  // Clear old credentials
    delay(100);
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);         // Disable power saving for better stability

    WiFi.begin(WIFI_SSID, WIFI_PASS);
    Serial.printf("Connecting to WiFi '%s'\n", WIFI_SSID);
    
    unsigned long startAttemptTime = millis();
    
    // Try to connect for 10 seconds
    while (WiFi.status() != WL_CONNECTED && millis() - startAttemptTime < 10000) {
        delay(500);
        Serial.print(".");
    }

    if(WiFi.status() == WL_CONNECTED){
        Serial.println("\nConnected!");
        Serial.println("IP: " + WiFi.localIP().toString());
    } else {
        Serial.printf("\nWiFi Connection Failed! Status: %d\n", WiFi.status());
        Serial.println(" (0=IDLE, 1=NO_SSID, 3=CONNECTED, 4=CONNECT_FAILED, 5=CONNECTION_LOST, 6=DISCONNECTED)");
        // Don't block further execution, just return or setup AP mode if desired (omitted for now)
    }

    // WebSocket
    ws.onEvent([this](AsyncWebSocket *server, AsyncWebSocketClient *client, AwsEventType type, void *arg, uint8_t *data, size_t len){
        this->onWsEvent(server, client, type, arg, data, len);
    });
    server.addHandler(&ws);

    // Firmware Update (OTA)
    server.on("/update", HTTP_POST, [this](AsyncWebServerRequest *request){
        bool shouldReboot = !Update.hasError();
        AsyncWebServerResponse *response = request->beginResponse(200, "text/plain", shouldReboot ? "OK" : "FAIL");
        response->addHeader("Connection", "close");
        request->send(response);
        if(shouldReboot) {
            Serial.println("OTA Complete. Rebooting...");
            delay(100);
            ESP.restart();
        }
    }, [this](AsyncWebServerRequest *request, String filename, size_t index, uint8_t *data, size_t len, bool final){
        if(!index){
            Serial.printf("OTA Start: %s\n", filename.c_str());
            // Stop display AND interrupts to prevent flash conflicts
            this->display->stop();
            this->display->stopDMA();
            
            // Start update (use max sketch space)
            if(!Update.begin(UPDATE_SIZE_UNKNOWN)){ 
                Update.printError(Serial);
                this->display->resumeDMA(); // Resume if init fails
            }
        }
        if(!Update.hasError()){
            if(Update.write(data, len) != len){
                Update.printError(Serial);
            }
        }
        if(final){
            if(Update.end(true)){
                Serial.printf("OTA Success: %u bytes\n", index+len);
            } else {
                Update.printError(Serial);
                this->display->resumeDMA(); // Resume if end fails
            }
        }
    });

    // Upload
    server.on("/upload", HTTP_POST, [](AsyncWebServerRequest *request){
        request->send(200, "text/plain", "OK");
    }, [this](AsyncWebServerRequest *request, String filename, size_t index, uint8_t *data, size_t len, bool final){
        static File uploadFile;
        static size_t totalBytes = 0;

        if(!index){
            totalBytes = 0;
            String folder = "";
            if (request->hasHeader("X-Playlist")) {
                folder = request->getHeader("X-Playlist")->value();
            }
            if (folder == "" || folder == "ALL") folder = "Default";
            
            String path = "/" + folder;
            if (!LittleFS.exists(path)) LittleFS.mkdir(path);
            
            String fullPath = path + "/" + filename;
            fullPath.replace("//", "/");
            
            if(Serial) Serial.printf("Upload Start: %s\n", fullPath.c_str());
            
            uploadFile = this->fileMgr->open(fullPath, "w");
            if(!uploadFile){
                 if(Serial) Serial.printf("Upload Error: Failed to open %s for writing\n", fullPath.c_str());
            }
        }
        if(uploadFile){
            size_t written = uploadFile.write(data, len);
            totalBytes += written;
            if (written != len) {
                if(Serial) Serial.printf("Upload WRITE ERROR: Requested %u, wrote %u\n", len, written);
            }
            delay(1); // Yield to prevent Flash write saturation/watchdog issues
        }
        if(final){
            if(uploadFile) {
                uploadFile.close();
                if(Serial) Serial.printf("Upload Finished. Total size: %u bytes\n", totalBytes);
            }
        }
    });

    // Serve static files from LittleFS (for Preview)
    server.serveStatic("/", LittleFS, "/");

    // ArduinoOTA Setup (for PlatformIO)
    ArduinoOTA.onStart([this]() {
        String type;
        if (ArduinoOTA.getCommand() == U_FLASH) type = "sketch";
        else type = "filesystem";
        Serial.println("Start updating " + type);
        this->display->stop();
        this->display->stopDMA();
    });
    ArduinoOTA.onEnd([]() { Serial.println("\nEnd"); });
    ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
        // Serial output slows down OTA significantly
        // Serial.printf("Progress: %u%%\r", (progress / (total / 100)));
    });
    ArduinoOTA.onError([this](ota_error_t error) {
        Serial.printf("Error[%u]: ", error);
        if (error == OTA_AUTH_ERROR) Serial.println("Auth Failed");
        else if (error == OTA_BEGIN_ERROR) Serial.println("Begin Failed");
        else if (error == OTA_CONNECT_ERROR) Serial.println("Connect Failed");
        else if (error == OTA_RECEIVE_ERROR) Serial.println("Receive Failed");
        else if (error == OTA_END_ERROR) Serial.println("End Failed");
        
        this->display->resumeDMA(); // Resume on error
    });
    ArduinoOTA.begin();

    server.begin();
    
    lastWifiCheckTime = millis();
}

void NetworkManager::loop() {
    ws.cleanupClients();
    ArduinoOTA.handle();
    
    // Check WiFi Status periodically
    if (millis() - lastWifiCheckTime > WIFI_CHECK_INTERVAL) {
        lastWifiCheckTime = millis();
        if (WiFi.status() != WL_CONNECTED) {
            Serial.println("WiFi Connection Lost. Retrying...");
            WiFi.disconnect();
            WiFi.begin(WIFI_SSID, WIFI_PASS);
            
            unsigned long startAttempt = millis();
            // Retry for 10 seconds, but keep display running
            while (WiFi.status() != WL_CONNECTED && millis() - startAttempt < 10000) {
                if (display) display->loop();
                delay(10);
            }
            
            if (WiFi.status() == WL_CONNECTED) {
                Serial.println("WiFi Reconnected!");
                Serial.println("IP: " + WiFi.localIP().toString());
            } else {
                Serial.println("WiFi Reconnect Failed. Will try again later.");
            }
        }
    }
    
    // Check async deletion completion and update progress display
    if (deletionInProgress) {
        DeleteState state = fileMgr->getDeleteState();
        unsigned long now = millis();

        // Throttled progress display update (max 10 FPS, min 1% change) - only if NOT silent
        if (!deletionSilent && state == DEL_DELETING && now - lastProgressUpdate >= PROGRESS_UPDATE_INTERVAL) {
            float progress = fileMgr->getDeleteProgress();
            if (progress - lastDisplayedProgress >= 0.01f || progress >= 1.0f) {
                display->showDeleteProgress("Deleting...", progress);
                lastDisplayedProgress = progress;
                lastProgressUpdate = now;
            }
        }

        if (state == DEL_COMPLETE) {
            Serial.println("NetworkManager: Deletion complete!");
            if (!deletionSilent) {
                display->hideDeleteProgress();
            }
            lastDisplayedProgress = -1.0f;

            // Notify the requesting client
            AsyncWebSocketClient* client = ws.client(deletionClientId);
            if (client && client->status() == WS_CONNECTED) {
                client->text("{\"cmd\":\"deletion_complete\"}");
                sendList(client);
            }

            fileMgr->resetDeleteState();
            deletionInProgress = false;
            deletionSilent = false;
        }
        else if (state == DEL_ERROR) {
            Serial.println("NetworkManager: Deletion failed!");
            if (!deletionSilent) {
                display->hideDeleteProgress();
            }
            lastDisplayedProgress = -1.0f;

            AsyncWebSocketClient* client = ws.client(deletionClientId);
            if (client && client->status() == WS_CONNECTED) {
                String errMsg = "{\"cmd\":\"deletion_failed\",\"error\":\"" +
                                fileMgr->getDeleteError() + "\"}";
                client->text(errMsg);
            }

            fileMgr->resetDeleteState();
            deletionInProgress = false;
            deletionSilent = false;
        }
    }

    if (shouldSendList) {
        shouldSendList = false;
        if (pendingListClientId != 0) {
            AsyncWebSocketClient* client = ws.client(pendingListClientId);
            if (client) {
                sendList(client);
            }
        }
    }
}

void NetworkManager::onWsEvent(AsyncWebSocket *server, AsyncWebSocketClient *client, AwsEventType type, void *arg, uint8_t *data, size_t len) {
    if (type == WS_EVT_DATA) {
        AwsFrameInfo *info = (AwsFrameInfo*)arg;
        
        // Text Frame (Command) - typically small, ensure it's final
        if (info->opcode == WS_TEXT) {
            if (info->final && info->index == 0 && info->len == len) {
                 handleJson(client, data, len);
            }
        } 
        // Binary Frame (Stream) - handle fragments
        else if (info->opcode == WS_BINARY) {
            if (display->handleStreamChunk(data, len, info->index, info->len)) {
                // Send 1-byte ACK safely
                if (client->status() == WS_CONNECTED) {
                    uint8_t ack = 'K';
                    client->binary(&ack, 1);
                }
            }
        }
    }
}

void NetworkManager::handleJson(AsyncWebSocketClient *client, uint8_t *data, size_t len) {
    // Use heap allocation for JSON to keep stack usage minimal in the network task
    DynamicJsonDocument* docPtr = new DynamicJsonDocument(512);
    DynamicJsonDocument& doc = *docPtr;
    
    DeserializationError err = deserializeJson(doc, data, len);
    if (err) {
        delete docPtr;
        return;
    }

    String cmd = doc["cmd"];
    
    if (cmd == "brightness") {
        display->setBrightness(doc["val"]);
    } 
    else if (cmd == "duration") {
        display->setLoopDuration(doc["val"]);
    }
    else if (cmd == "rotate") {
        display->setRotation(doc["val"]);
    }
    else if (cmd == "shuffle") {
        display->setShuffle(doc["val"]);
    }
    else if (cmd == "text") {
        String txt = doc["text"];
        bool scroll = doc["scroll"];
        JsonArray color = doc["color"];
        if (color.size() == 3) {
            display->setTextColor(color[0], color[1], color[2]);
        }
        display->showText(txt, scroll);
    }
    else if (cmd == "stream") {
        display->startStreaming();
    }
    else if (cmd == "play") {
        String file = doc["file"];
        if (file == "ALL") {
            display->playAll(doc["playlist"].as<String>());
        } else {
            display->playFile(file);
        }
    }
    else if (cmd == "set_playlist") {
        display->setPlaylist(doc["name"]);
        pendingListClientId = client->id();
        shouldSendList = true;
    }
    else if (cmd == "stop") {
        display->stop();
    }
    else if (cmd == "list") {
        pendingListClientId = client->id();
        shouldSendList = true;
    }
    else if (cmd == "delete") {
        String file = doc["file"];
        Serial.printf("Delete Request: %s\n", file.c_str());
        
        // Stop display if the file to be deleted is currently playing
        if (display->getCurrentFile() == file) {
            display->forceStop();
        }
        
        if (fileMgr->removeFile(file)) {
            Serial.println("Delete Success");
        } else {
            Serial.println("Delete FAILED");
        }
        pendingListClientId = client->id();
        shouldSendList = true; 
    }
    else if (cmd == "delete_playlist") {
        String pl = doc["name"];
        Serial.printf("Delete Playlist Request: %s\n", pl.c_str());

        // Check if deletion already in progress
        if (deletionInProgress) {
            client->text("{\"cmd\":\"deletion_failed\",\"error\":\"Deletion already in progress\"}");
            delete docPtr;
            return;
        }

        // Force stop to release any open file handles
        display->forceStop();
        delay(50); // Allow FS to sync

        // Start async deletion (returns immediately)
        if (fileMgr->startPlaylistDeletion(pl, false)) {  // false = with progress bar
            deletionInProgress = true;
            deletionSilent = false;
            deletionClientId = client->id();
            lastDisplayedProgress = 0.0f;
            lastProgressUpdate = millis();
            display->showDeleteProgress("Deleting...", 0.0f);
            client->text("{\"cmd\":\"deletion_started\",\"name\":\"" + pl + "\"}");
        } else {
            client->text("{\"cmd\":\"deletion_failed\",\"error\":\"" +
                         fileMgr->getDeleteError() + "\"}");
        }
        // NOTE: Do NOT send list here - wait for completion
    }
    else if (cmd == "silent_delete_playlist") {
        String pl = doc["name"];
        Serial.printf("Silent Delete Playlist Request: %s\n", pl.c_str());

        // Check if deletion already in progress
        if (deletionInProgress) {
            client->text("{\"cmd\":\"deletion_failed\",\"error\":\"Deletion already in progress\"}");
            delete docPtr;
            return;
        }

        // Force stop to release any open file handles
        display->forceStop();
        delay(50); // Allow FS to sync

        // Start async deletion (returns immediately) - SILENT mode (no progress bar)
        if (fileMgr->startPlaylistDeletion(pl, true)) {  // true = silent
            deletionInProgress = true;
            deletionSilent = true;  // NO showDeleteProgress()!
            deletionClientId = client->id();
            client->text("{\"cmd\":\"deletion_started\",\"name\":\"" + pl + "\",\"silent\":true}");
        } else {
            client->text("{\"cmd\":\"deletion_failed\",\"error\":\"" +
                         fileMgr->getDeleteError() + "\"}");
        }
        // NOTE: Do NOT send list here - wait for completion
    }

    delete docPtr;
}

void NetworkManager::sendList(AsyncWebSocketClient *client) {
    // 1. Send Start + Playlists + Stats
    DynamicJsonDocument doc(2048);
    doc["cmd"] = "list_start";
    doc["total"] = fileMgr->getTotalSpace();
    doc["used"] = fileMgr->getUsedSpace();

    JsonArray playlistArr = doc.createNestedArray("playlists");
    std::vector<String> playlists = fileMgr->listPlaylists();
    for (const auto& p : playlists) playlistArr.add(p);
    
    String output;
    serializeJson(doc, output);
    client->text(output);

    // 2. Stream Files using Callback
    const size_t CHUNK_SIZE = 50; 
    std::vector<String> buffer;
    buffer.reserve(CHUNK_SIZE);

    // Pass "ALL" (or empty string if logic was adapted) to start recursively from root
    fileMgr->listGifs("ALL", [&](const String& file){
        buffer.push_back(file);
        if (buffer.size() >= CHUNK_SIZE) {
            DynamicJsonDocument chunkDoc(4096);
            chunkDoc["cmd"] = "list_chunk";
            JsonArray fileArr = chunkDoc.createNestedArray("files");
            for(const auto& f : buffer) fileArr.add(f);
            
            String chunkOut;
            serializeJson(chunkDoc, chunkOut);
            client->text(chunkOut);
            buffer.clear();
            delay(5); // Yield to keep network stable
        }
    });

    // Send remaining files
    if (!buffer.empty()) {
        DynamicJsonDocument chunkDoc(4096);
        chunkDoc["cmd"] = "list_chunk";
        JsonArray fileArr = chunkDoc.createNestedArray("files");
        for(const auto& f : buffer) fileArr.add(f);
        
        String chunkOut;
        serializeJson(chunkDoc, chunkOut);
        client->text(chunkOut);
    }

    // 3. Send End Signal
    client->text("{\"cmd\":\"list_end\"}");
}

void NetworkManager::broadcastStatus(const String& filename) {
    // Simple JSON construction
    String json = "{\"cmd\":\"status\",\"file\":\"" + filename + "\"}";
    ws.textAll(json);
}