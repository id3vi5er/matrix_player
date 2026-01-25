#include "FileManager.h"
#include "TestGif.h"

bool FileManager::begin() {
    return LittleFS.begin(true);
}

void FileManager::createTestGifIfEmpty() {
    std::vector<String> gifs = listGifs();
    if (gifs.empty()) {
        Serial.println("FileManager: No GIFs found. Creating 'test.gif'...");
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
            Serial.printf("FileManager: Deleting content %s\n", fullPath.c_str());
            LittleFS.remove(fullPath);
        }
        file = root.openNextFile();
    }
    root.close(); // Close before rmdir

    if (LittleFS.rmdir(folder)) {
        Serial.printf("FileManager: Playlist folder %s deleted.\n", folder.c_str());
        return true;
    } else {
        Serial.printf("FileManager: Failed to delete folder %s\n", folder.c_str());
        return false;
    }
}