#include "MqttManager.h"

MqttManager::MqttManager(DisplayManager* disp, FileManager* fm) : display(disp), fileMgr(fm), client(espClient) {
    topicSetState = String(MQTT_TOPIC_PREFIX) + "/set/state";
    topicSetBrightness = String(MQTT_TOPIC_PREFIX) + "/set/brightness";
    topicSetPlaylist = String(MQTT_TOPIC_PREFIX) + "/set/playlist";
    topicSetFile = String(MQTT_TOPIC_PREFIX) + "/set/file";
    topicSetShuffle = String(MQTT_TOPIC_PREFIX) + "/set/shuffle";
    topicSetDuration = String(MQTT_TOPIC_PREFIX) + "/set/duration";
    topicSetText = String(MQTT_TOPIC_PREFIX) + "/set/text";
    topicSetTextColor = String(MQTT_TOPIC_PREFIX) + "/set/textcolor";
    topicSetFontSize = String(MQTT_TOPIC_PREFIX) + "/set/fontsize";

    topicStatusState = String(MQTT_TOPIC_PREFIX) + "/status/state";
    topicStatusAvailability = String(MQTT_TOPIC_PREFIX) + "/status/availability";
}

void MqttManager::begin() {
    client.setServer(MQTT_BROKER, MQTT_PORT);
    // Increase buffer size to handle large Discovery JSON (default is often too small)
    client.setBufferSize(2048); 
    
    client.setCallback([this](char* topic, byte* payload, unsigned int length) {
        this->callback(topic, payload, length);
    });

    // Register callback in DisplayManager to push status on file change
    display->setFileChangeCallback([this](String filename) {
        this->sendStatus();
    });
}

void MqttManager::loop() {
    if (!client.connected()) {
        unsigned long now = millis();
        if (now - lastReconnectAttempt > MQTT_RECONNECT_INTERVAL) {
            lastReconnectAttempt = now;
            if (reconnect()) {
                lastReconnectAttempt = 0;
            }
        }
    } else {
        client.loop();
        
        // Periodic status update
        unsigned long now = millis();
        if (now - lastStatusUpdate > STATUS_UPDATE_INTERVAL) {
            lastStatusUpdate = now;
            sendStatus();
        }

        // Handle delayed status update (waiting for DisplayManager to apply changes)
        if (shouldSendStatus && (now - statusUpdateTriggerTime > STATUS_DELAY_MS)) {
            shouldSendStatus = false;
            sendStatus();
        }
    }
}

bool MqttManager::reconnect() {
    Serial.print("Attempting MQTT connection...");
    String clientId = "ESP32Matrix-";
    clientId += String(random(0xffff), HEX);

    if (client.connect(clientId.c_str(), MQTT_USER, MQTT_PASS, topicStatusAvailability.c_str(), 1, true, "offline")) {
        Serial.println("connected");
        client.publish(topicStatusAvailability.c_str(), "online", true);
        
        client.subscribe((String(MQTT_TOPIC_PREFIX) + "/set/#").c_str());
        
        sendDiscovery();
        sendStatus();
        return true;
    } else {
        Serial.print("failed, rc=");
        Serial.print(client.state());
        Serial.println(" try again in 5 seconds");
        return false;
    }
}

void MqttManager::callback(char* topic, byte* payload, unsigned int length) {
    String top = String(topic);
    String msg;
    for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];

    Serial.printf("MQTT [%s]: %s\n", topic, msg.c_str());

    if (top == topicSetState) {
        if (msg == "ON") display->playAll();
        else if (msg == "OFF") display->stop();
    }
    else if (top == topicSetBrightness) {
        display->setBrightness(msg.toInt());
    }
    else if (top == topicSetPlaylist) {
        display->setPlaylist(msg);
    }
    else if (top == topicSetFile) {
        // Path normalization: ensure starts with /
        if (!msg.startsWith("/")) msg = "/" + msg;
        display->playFile(msg);
    }
    else if (top == topicSetShuffle) {
        display->setShuffle(msg == "ON");
    }
    else if (top == topicSetDuration) {
        display->setLoopDuration(msg.toInt());
    }
    else if (top == topicSetText) {
        display->showText(msg, true);
    }
    else if (top == topicSetFontSize) {
        display->setTextSize(msg.toInt());
    }
    else if (top == topicSetTextColor) {
        // Expected format: "255,0,0" OR JSON {"r":255,"g":0,"b":0}
        int r=255, g=255, b=255;
        if (msg.startsWith("{")) {
            StaticJsonDocument<200> doc;
            deserializeJson(doc, msg);
            r = doc["r"] | 255;
            g = doc["g"] | 255;
            b = doc["b"] | 255;
        } else {
            // Comma separated
            int firstComma = msg.indexOf(',');
            int secondComma = msg.indexOf(',', firstComma + 1);
            if (firstComma > 0 && secondComma > 0) {
                r = msg.substring(0, firstComma).toInt();
                g = msg.substring(firstComma + 1, secondComma).toInt();
                b = msg.substring(secondComma + 1).toInt();
            }
        }
        display->setTextColor(r, g, b);
    }
    
    // Trigger delayed status update to ensure DisplayManager has processed the command
    shouldSendStatus = true;
    statusUpdateTriggerTime = millis();
}

void MqttManager::sendStatus() {
    if (!client.connected()) return;

    StaticJsonDocument<512> doc;
    doc["state"] = display->getIsPlaying() ? "ON" : "OFF";
    doc["brightness"] = display->getBrightness();
    doc["playlist"] = display->getCurrentPlaylist();
    doc["file"] = display->getCurrentFile();
    doc["shuffle"] = display->getShuffle() ? "ON" : "OFF";
    doc["duration"] = display->getLoopDuration();

    String output;
    serializeJson(doc, output);
    client.publish(topicStatusState.c_str(), output.c_str(), true);
}

void MqttManager::sendDiscovery() {
    if (!client.connected()) return;

    // Discovery for Playlist Select
    String discoveryTopic = "homeassistant/select/ledmatrix_playlist/config";
    StaticJsonDocument<1024> doc;
    doc["name"] = "Matrix Playlist";
    doc["unique_id"] = "ledmatrix_playlist";
    doc["cmd_t"] = topicSetPlaylist;
    doc["stat_t"] = topicStatusState;
    doc["val_tpl"] = "{{ value_json.playlist }}";
    
    JsonArray options = doc.createNestedArray("options");
    std::vector<String> playlists = fileMgr->listPlaylists();
    for (const auto& p : playlists) {
        options.add(p);
    }

    JsonObject device = doc.createNestedObject("device");
    device["ids"] = "ledmatrix_s3";
    device["name"] = "LED Matrix S3";
    device["mdl"] = "64x64 RGB Matrix";
    device["mf"] = "ESP32-S3";

    String output;
    serializeJson(doc, output);
    
    Serial.printf("MQTT Discovery Payload (%d bytes): %s\n", output.length(), output.c_str());
    
    bool success = client.publish(discoveryTopic.c_str(), output.c_str(), true);
    if (success) {
        Serial.println("MQTT Discovery sent successfully.");
    } else {
        Serial.println("MQTT Discovery sending FAILED! (Check Buffer Size)");
    }
    
    // We could add more discovery here (Light, Switch etc.) 
    // but the user asked for the dropdown focus.
}
