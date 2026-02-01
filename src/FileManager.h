#pragma once
#include <Arduino.h>
#include <LittleFS.h>
#include <vector>
#include <functional>

// Async Deletion State Machine
enum DeleteState { DEL_IDLE, DEL_DELETING, DEL_COMPLETE, DEL_ERROR };

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

    // Async Deletion Methods
    void loop();
    bool startPlaylistDeletion(const String& playlist, bool silent = false);
    DeleteState getDeleteState() const { return deleteState; }
    float getDeleteProgress() const;
    void resetDeleteState();
    String getDeleteError() const { return deleteError; }
    bool isDeletionSilent() const { return deletionSilent; }

private:
    bool isGif(const String& filename);

    // Async Deletion State
    DeleteState deleteState = DEL_IDLE;
    std::vector<String> pendingDeleteFiles;
    String pendingDeleteFolder;
    size_t deleteIndex = 0;
    size_t deletedCount = 0;
    size_t deleteTotal = 0;
    String deleteError;
    bool deletionSilent = false;
    static const int FILES_PER_LOOP = 3;
};