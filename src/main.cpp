#include <Arduino.h>
#include "Config.h"
#include "DisplayManager.h"
#include "NetworkManager.h"
#include "FileManager.h"
#include <esp_task_wdt.h>

DisplayManager displayMgr;
FileManager fileMgr;
NetworkManager netMgr(&displayMgr, &fileMgr);

void setup() {
    // Increase WDT timeout to 30 seconds to handle large file operations
    esp_task_wdt_init(30, true);
    
    Serial.begin(115200);
    delay(2000); 
    Serial.println("\n--- BOOT ---");

    if (psramFound()) {
        Serial.printf("PSRAM: %d bytes\n", ESP.getPsramSize());
    } else {
        Serial.println("ERR: PSRAM not found!");
    }

    Serial.println("Initializing FileManager...");
    if (!fileMgr.begin()) {
        Serial.println("LittleFS Mount Failed");
    }
    
    fileMgr.createTestGifIfEmpty();

    Serial.println("Initializing NetworkManager...");
    netMgr.begin();

    Serial.println("Initializing DisplayManager...");
    displayMgr.begin(&fileMgr);
    
    // Sync Display -> Network
    displayMgr.setFileChangeCallback([](String f){
        netMgr.broadcastStatus(f);
    });
    
    Serial.println("Starting playback...");
    displayMgr.playAll();
    Serial.println("Setup complete.");
}

void loop() {
    displayMgr.loop();
    netMgr.loop();
    delay(1); // Small delay to prevent CPU starvation of WiFi task
}
