#include "NetworkManager.h"
#include "MqttManager.h"

FileManager fileMgr;
DisplayManager display;
NetworkManager* network = nullptr;
MqttManager* mqtt = nullptr;

void setup() {
  Serial.begin(115200);
  
  if (!fileMgr.begin()) {
    Serial.println("LittleFS Mount Failed");
  }
  fileMgr.createTestGifIfEmpty();

  display.begin(&fileMgr);
  
  network = new NetworkManager(&display, &fileMgr);
  network->begin();

  mqtt = new MqttManager(&display, &fileMgr);
  mqtt->begin();

  // Register Callback for File Changes
  display.setFileChangeCallback([](String file){
      if (network) network->broadcastStatus(file);
      if (mqtt) mqtt->sendStatus();
  });

  display.playAll(DEFAULT_PLAYLIST);
}

void loop() {
  fileMgr.loop();  // Process async file operations (e.g., deletion)
  display.loop();
  network->loop();
  if (mqtt) mqtt->loop();
}
