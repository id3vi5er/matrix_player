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
    void broadcastStatus(const String& filename);

private:
    AsyncWebServer server;
    AsyncWebSocket ws;
    DisplayManager* display;
    FileManager* fileMgr;

    void onWsEvent(AsyncWebSocket *server, AsyncWebSocketClient *client, AwsEventType type, void *arg, uint8_t *data, size_t len);
    void handleJson(AsyncWebSocketClient *client, uint8_t *data, size_t len);
    void sendList(AsyncWebSocketClient *client);
};
