#pragma once
#include <Arduino.h>
#include <LittleFS.h>
#include <vector>
#include <functional>

class FileManager {
public:
    bool begin();
    std::vector<String> listGifs(const String& playlist = "");
    void listGifs(const String& playlist, std::function<void(const String&)> callback);
    std::vector<String> listPlaylists();
    File open(const String& path, const char* mode);
    bool removeFile(const String& path);
    bool removePlaylist(const String& playlist);
    void createTestGifIfEmpty();
    
    size_t getTotalSpace();
    size_t getUsedSpace();

private:
    bool isGif(const String& filename);
};