#include "FileManager.h"
#include "TestGif.h"

bool FileManager::begin() {
    return LittleFS.begin(true);
}

void FileManager::createTestGifIfEmpty() {
    // Optimization: Don't scan all files. Just check if the test file exists.
    if (!LittleFS.exists("/Default/test.gif")) {
        Serial.println("FileManager: test.gif missing. Creating...");
        // Ensure /Default directory exists
        if (!LittleFS.exists("/Default")) LittleFS.mkdir("/Default");
        File f = LittleFS.open("/Default/test.gif", "w");
        if (f) {
            f.write(test_gif_data, test_gif_len);
            f.close();
            Serial.println("FileManager: 'test.gif' created in /Default.");
        } else {
            Serial.println("FileManager: Failed to create 'test.gif'");
        }
    }
}

std::vector<String> FileManager::listGifs(const String& playlist) {
    std::vector<String> files;
    String folderPath = playlist;
    
    bool recursive = (playlist == "" || playlist == "ALL");
    if (recursive) folderPath = "/";
    if (!folderPath.startsWith("/")) folderPath = "/" + folderPath;

    File root = LittleFS.open(folderPath);
    if (!root || !root.isDirectory()) return files;

    File file = root.openNextFile();
    while (file) {
        String name = String(file.name());
        String fullPath;
        if (name.startsWith("/")) {
            fullPath = name;
        } else {
            fullPath = folderPath;
            if (!fullPath.endsWith("/")) fullPath += "/";
            fullPath += name;
        }
        fullPath.replace("//", "/");

        if (file.isDirectory()) {
            if (recursive) {
                std::vector<String> subFiles = listGifs(fullPath);
                files.insert(files.end(), subFiles.begin(), subFiles.end());
            }
        } else {
            if (fullPath.endsWith(".gif") || fullPath.endsWith(".GIF")) {
                if (fullPath.indexOf("test.gif") < 0 || files.size() == 0) {
                    files.push_back(fullPath);
                }
            }
        }
        file = root.openNextFile();
        delay(1); // Yield to prevent WDT timeout during large directory listing
    }
    
    // Cleanup: If we have multiple files and the default test.gif is in there, remove it
    if (files.size() > 1) {
        for (auto it = files.begin(); it != files.end(); ) {
            if (it->endsWith("/test.gif")) {
                it = files.erase(it);
            } else {
                ++it;
            }
        }
    }
    return files;
}

void FileManager::listGifs(const String& playlist, std::function<void(const String&)> callback) {
    String folderPath = playlist;
    
    bool recursive = (playlist == "" || playlist == "ALL");
    if (recursive) folderPath = "/";
    if (!folderPath.startsWith("/")) folderPath = "/" + folderPath;

    File root = LittleFS.open(folderPath);
    if (!root || !root.isDirectory()) return;

    File file = root.openNextFile();
    while (file) {
        String name = String(file.name());
        String fullPath;
        if (name.startsWith("/")) {
            fullPath = name;
        } else {
            fullPath = folderPath;
            if (!fullPath.endsWith("/")) fullPath += "/";
            fullPath += name;
        }
        fullPath.replace("//", "/");

        if (file.isDirectory()) {
            if (recursive) {
                listGifs(fullPath, callback);
            }
        } else {
            if (fullPath.endsWith(".gif") || fullPath.endsWith(".GIF")) {
                callback(fullPath);
            }
        }
        file = root.openNextFile();
        delay(1); // Yield
    }
}

std::vector<String> FileManager::listPlaylists() {
    std::vector<String> playlists;
    playlists.push_back("ALL"); // Default option

    File root = LittleFS.open("/");
    if (!root || !root.isDirectory()) return playlists;

    File file = root.openNextFile();
    while (file) {
        if (file.isDirectory()) {
            String dname = String(file.name());
            // Normalize: remove leading slash if present
            if (dname.startsWith("/")) dname = dname.substring(1);
            if (dname != "" && dname != "System Volume Information") {
                playlists.push_back(dname);
            }
        }
        file = root.openNextFile();
    }
    return playlists;
}

size_t FileManager::getTotalSpace() {
    return LittleFS.totalBytes();
}

size_t FileManager::getUsedSpace() {
    return LittleFS.usedBytes();
}

File FileManager::open(const String& path, const char* mode) {
    return LittleFS.open(path, mode);
}

bool FileManager::removeFile(const String& path) {
    if (!LittleFS.exists(path)) {
        Serial.printf("FileManager: Cannot remove %s, file does not exist.\n", path.c_str());
        return false;
    }
    bool success = LittleFS.remove(path);
    if (success) {
        Serial.printf("FileManager: Removed %s\n", path.c_str());
    } else {
        Serial.printf("FileManager: FAILED to remove %s\n", path.c_str());
    }
    return success;
}

bool FileManager::removePlaylist(const String& playlist) {
    String folder = playlist;
    if (!folder.startsWith("/")) folder = "/" + folder;

    // Protection: Do not delete root or Default folder
    if (folder == "/" || folder == "/Default") {
        Serial.println("FileManager: Deletion of ROOT or /Default is protected.");
        return false;
    }

    if (!LittleFS.exists(folder)) return false;

    // Step 1: Collect all files to delete (avoid deleting while iterating)
    std::vector<String> filesToDelete;
    File root = LittleFS.open(folder);
    if (!root || !root.isDirectory()) return false;

    File file = root.openNextFile();
    while (file) {
        String name = String(file.name());
        String fullPath;
        if (name.startsWith("/")) fullPath = name;
        else {
            fullPath = folder;
            if (!fullPath.endsWith("/")) fullPath += "/";
            fullPath += name;
        }
        fullPath.replace("//", "/");

        if (!file.isDirectory()) {
            filesToDelete.push_back(fullPath);
        }
        file = root.openNextFile();
    }
    root.close(); // Close directory handle

    // Step 2: Delete collected files
    for (const auto& fPath : filesToDelete) {
        Serial.printf("FileManager: Deleting content %s\n", fPath.c_str());
        if (!LittleFS.remove(fPath)) {
             Serial.printf("FileManager: Failed to remove %s\n", fPath.c_str());
        }
        delay(1); // Yield to prevent WDT timeout during bulk deletion
    }

    // Step 3: Remove empty directory
    if (LittleFS.rmdir(folder)) {
        Serial.printf("FileManager: Playlist folder %s deleted.\n", folder.c_str());
        return true;
    } else {
        Serial.printf("FileManager: Failed to delete folder %s\n", folder.c_str());
        return false;
    }
}

// ============================================================================
// Async Playlist Deletion Methods
// ============================================================================

bool FileManager::startPlaylistDeletion(const String& playlist, bool silent) {
    // Reject if already deleting
    if (deleteState != DEL_IDLE) {
        Serial.println("FileManager: Deletion already in progress!");
        deleteError = "Deletion already in progress";
        return false;
    }

    // Store silent flag
    deletionSilent = silent;

    String folder = playlist;
    if (!folder.startsWith("/")) folder = "/" + folder;

    // Protection: Do not delete root or Default folder
    if (folder == "/" || folder == "/Default") {
        Serial.println("FileManager: Deletion of ROOT or /Default is protected.");
        deleteError = "Protected folder";
        deleteState = DEL_ERROR;
        return false;
    }

    if (!LittleFS.exists(folder)) {
        deleteError = "Folder not found";
        deleteState = DEL_ERROR;
        return false;
    }

    // Collect files (this is relatively fast - just listing, not deleting)
    pendingDeleteFiles.clear();
    File root = LittleFS.open(folder);
    if (!root || !root.isDirectory()) {
        deleteError = "Not a directory";
        deleteState = DEL_ERROR;
        return false;
    }

    File file = root.openNextFile();
    while (file) {
        String name = String(file.name());
        String fullPath;
        if (name.startsWith("/")) fullPath = name;
        else {
            fullPath = folder;
            if (!fullPath.endsWith("/")) fullPath += "/";
            fullPath += name;
        }
        fullPath.replace("//", "/");

        if (!file.isDirectory()) {
            pendingDeleteFiles.push_back(fullPath);
        }
        file = root.openNextFile();
        delay(1); // Yield during collection
    }
    root.close();

    // Setup state for incremental deletion
    pendingDeleteFolder = folder;
    deleteIndex = 0;
    deletedCount = 0;
    deleteTotal = pendingDeleteFiles.size();
    deleteState = DEL_DELETING;

    Serial.printf("FileManager: Started async deletion of %d files in %s\n",
                  deleteTotal, folder.c_str());
    return true;
}

void FileManager::loop() {
    if (deleteState != DEL_DELETING) return;

    // Delete up to FILES_PER_LOOP files per iteration
    int deleted = 0;
    while (deleteIndex < pendingDeleteFiles.size() && deleted < FILES_PER_LOOP) {
        const String& fPath = pendingDeleteFiles[deleteIndex];

        Serial.printf("FileManager: Deleting [%d/%d] %s\n",
                      deleteIndex + 1, deleteTotal, fPath.c_str());

        if (LittleFS.remove(fPath)) {
            deletedCount++;
        } else {
            Serial.printf("FileManager: Failed to remove %s\n", fPath.c_str());
        }

        deleteIndex++;
        deleted++;
        delay(1); // Small yield between files
    }

    // Check if all files processed
    if (deleteIndex >= pendingDeleteFiles.size()) {
        // Try to remove the empty directory
        if (LittleFS.rmdir(pendingDeleteFolder)) {
            Serial.printf("FileManager: Playlist folder %s deleted. (%d/%d files)\n",
                          pendingDeleteFolder.c_str(), deletedCount, deleteTotal);
            deleteState = DEL_COMPLETE;
        } else {
            Serial.printf("FileManager: Failed to remove folder %s\n",
                          pendingDeleteFolder.c_str());
            deleteError = "rmdir failed";
            deleteState = DEL_ERROR;
        }

        // Clear vectors to free memory
        pendingDeleteFiles.clear();
        pendingDeleteFiles.shrink_to_fit();
    }
}

float FileManager::getDeleteProgress() const {
    if (deleteTotal == 0) return 0.0f;
    return (float)deleteIndex / (float)deleteTotal;
}

void FileManager::resetDeleteState() {
    deleteState = DEL_IDLE;
    pendingDeleteFiles.clear();
    pendingDeleteFiles.shrink_to_fit();
    pendingDeleteFolder = "";
    deleteIndex = 0;
    deletedCount = 0;
    deleteTotal = 0;
    deleteError = "";
    deletionSilent = false;
}