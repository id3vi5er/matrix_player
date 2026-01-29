#pragma once
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "Config.h"
#include "DisplayManager.h"
#include "FileManager.h"

class MqttManager {
public:
    MqttManager(DisplayManager* disp, FileManager* fm);
    void begin();
    void loop();
    
    void sendStatus();
    void sendDiscovery();

private:
    WiFiClient espClient;
    PubSubClient client;
    DisplayManager* display;
    FileManager* fileMgr;

    unsigned long lastReconnectAttempt = 0;
    unsigned long lastStatusUpdate = 0;
    const unsigned long STATUS_UPDATE_INTERVAL = 30000; // 30s auto-update

    // Delayed status update to allow DisplayManager to process commands
    bool shouldSendStatus = false;
    unsigned long statusUpdateTriggerTime = 0;
    const unsigned long STATUS_DELAY_MS = 100; 

    void callback(char* topic, byte* payload, unsigned int length);
    bool reconnect();
    
    // Topics
    String topicSetState;
    String topicSetBrightness;
    String topicSetPlaylist;
    String topicSetFile;
    String topicSetShuffle;
    String topicSetDuration;
    String topicSetText;
    String topicSetTextColor;
    String topicSetFontSize;
    
    String topicStatusState;
    String topicStatusAvailability;
};
