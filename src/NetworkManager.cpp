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
            // Stop display to prevent flash conflicts
            this->display->stop();
            
            // Start update (use max sketch space)
            if(!Update.begin(UPDATE_SIZE_UNKNOWN)){ 
                Update.printError(Serial);
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
            }
        }
    });

    // Upload
    server.on("/upload", HTTP_POST, [](AsyncWebServerRequest *request){
        request->send(200, "text/plain", "OK");
    }, [this](AsyncWebServerRequest *request, String filename, size_t index, uint8_t *data, size_t len, bool final){
        static File uploadFile;
        if(!index){
            String folder = "";
            if (request->hasHeader("X-Playlist")) {
                folder = request->getHeader("X-Playlist")->value();
            }
            if (folder == "" || folder == "ALL") folder = "Default";
            
            String path = "/" + folder;
            if (!LittleFS.exists(path)) LittleFS.mkdir(path);
            
            // Construct full path
            String fullPath = path + "/" + filename;
            fullPath.replace("//", "/");
            
            Serial.printf("Upload Start: %s\n", fullPath.c_str());
            
            uploadFile = this->fileMgr->open(fullPath, "w");
            if(!uploadFile){
                 Serial.printf("Upload Error: Failed to open %s for writing\n", fullPath.c_str());
            }
        }
        if(uploadFile){
            uploadFile.write(data, len);
        }
        if(final){
            if(uploadFile) {
                uploadFile.close();
                Serial.println("Upload End.");
                // Notify clients to refresh list
                ws.textAll("{\"cmd\":\"reload\"}");
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
    });
    ArduinoOTA.onEnd([]() { Serial.println("\nEnd"); });
    ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
        // Serial output slows down OTA significantly
        // Serial.printf("Progress: %u%%\r", (progress / (total / 100)));
    });
    ArduinoOTA.onError([](ota_error_t error) {
        Serial.printf("Error[%u]: ", error);
        if (error == OTA_AUTH_ERROR) Serial.println("Auth Failed");
        else if (error == OTA_BEGIN_ERROR) Serial.println("Begin Failed");
        else if (error == OTA_CONNECT_ERROR) Serial.println("Connect Failed");
        else if (error == OTA_RECEIVE_ERROR) Serial.println("Receive Failed");
        else if (error == OTA_END_ERROR) Serial.println("End Failed");
    });
    ArduinoOTA.begin();

    server.begin();
}

void NetworkManager::loop() {
    ws.cleanupClients();
    ArduinoOTA.handle();
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
        sendList(client);
    }
    else if (cmd == "stop") {
        display->stop();
    }
    else if (cmd == "list") {
        sendList(client);
    }
    else if (cmd == "delete") {
        String file = doc["file"];
        Serial.printf("Delete Request: %s\n", file.c_str());
        
        // Stop display if the file to be deleted is currently playing
        if (display->getCurrentFile() == file) {
            display->stop();
        }
        
        if (fileMgr->removeFile(file)) {
            Serial.println("Delete Success");
        } else {
            Serial.println("Delete FAILED");
        }
        sendList(client); 
    }
    else if (cmd == "delete_playlist") {
        String pl = doc["name"];
        Serial.printf("Delete Playlist Request: %s\n", pl.c_str());
        
        // Stop if currently playing from this playlist
        // Simple check: if current playlist name matches
        // Note: DisplayManager logic might need a check, but stopping generic is safer
        display->stop();

        if (fileMgr->removePlaylist(pl)) {
            Serial.println("Playlist Delete Success");
        } else {
            Serial.println("Playlist Delete FAILED");
        }
        sendList(client);
    }
    
    delete docPtr;
}

void NetworkManager::sendList(AsyncWebSocketClient *client) {
    std::vector<String> files = fileMgr->listGifs();
    std::vector<String> playlists = fileMgr->listPlaylists();
    
    // Increase buffer size to handle many files (32KB should be enough for hundreds of files)
    DynamicJsonDocument doc(32768); 
    doc["cmd"] = "list";
    
    doc["total"] = fileMgr->getTotalSpace();
    doc["used"] = fileMgr->getUsedSpace();

    JsonArray fileArr = doc.createNestedArray("files");
    for (const auto& f : files) fileArr.add(f);

    JsonArray playlistArr = doc.createNestedArray("playlists");
    for (const auto& p : playlists) playlistArr.add(p);
    
    String output;
    serializeJson(doc, output);
    client->text(output);
}

void NetworkManager::broadcastStatus(const String& filename) {
    // Simple JSON construction
    String json = "{\"cmd\":\"status\",\"file\":\"" + filename + "\"}";
    ws.textAll(json);
}