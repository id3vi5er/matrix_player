#pragma once
#include <WiFi.h>
#include <ESPAsyncWebServer.h>
#include <AsyncJson.h>
#include <ArduinoJson.h>
#include <ArduinoOTA.h>
#include "Config.h"
#include "DisplayManager.h"
#include "FileManager.h"

class NetworkManager {
public:
    NetworkManager(DisplayManager* disp, FileManager* fm);
    void begin();
    void loop();
    void sendList(AsyncWebSocketClient *client);
    void broadcastStatus(const String& filename);

private:
    AsyncWebServer server;
    AsyncWebSocket ws;
    DisplayManager* display;
    FileManager* fileMgr;
    
    // Deferred list sending
    bool shouldSendList = false;
    uint32_t pendingListClientId = 0; // ID of client to send to (0 = all? or specific)

    // Wifi Retry Logic
    unsigned long lastWifiCheckTime = 0;
    const unsigned long WIFI_CHECK_INTERVAL = 60000; // 60s

    void onWsEvent(AsyncWebSocket *server, AsyncWebSocketClient *client, AwsEventType type, void *arg, uint8_t *data, size_t len);
    void handleJson(AsyncWebSocketClient *client, uint8_t *data, size_t len);
};
