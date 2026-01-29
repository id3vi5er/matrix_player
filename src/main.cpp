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

  display.playAll(DEFAULT_PLAYLIST);
}

void loop() {
  display.loop();
  network->loop();
  if (mqtt) mqtt->loop();
}
