#pragma once
#include <ESP32-HUB75-MatrixPanel-I2S-DMA.h>
#include <AnimatedGIF.h>
#include <vector>
#include <mutex>
#include <functional>
#include "Config.h"
#include "FileManager.h"

#include <set>

class DisplayManager {
public:
    typedef std::function<void(String)> FileChangeCallback;

    void begin(FileManager* fm);
    void loop();
    
    void setFileChangeCallback(FileChangeCallback cb) { onFileChange = cb; }

    // Commands (Thread-Safe)
    void setBrightness(uint8_t val);
    void setLoopDuration(unsigned long ms);
    void setRotation(int r); // 0-3
    void setPlaylist(const String& name);
    void setShuffle(bool enabled);
    void playFile(const String& path); // Single Mode
    void playAll(const String& playlist = ""); // Loop Mode (reloads file list)
    void stop();
    void forceStop(); // Synchronous stop for deletion
    
    String getCurrentFile() { return currentFile; }

    // Streaming
    void startStreaming();
    bool handleStreamChunk(uint8_t* data, size_t len, size_t index, size_t totalLen);

    // Text
    void showText(const String& text, bool scroll = false);
    void setTextColor(uint8_t r, uint8_t g, uint8_t b);
    
    // Static Access for C-Callbacks
    static MatrixPanel_I2S_DMA* dma;
    static std::set<void*> validFiles; // Track open file handles for safety

private:
    FileManager* fileMgr;
    AnimatedGIF gif;
    std::mutex cmdMutex;
    std::mutex gifMutex; // Protects AnimatedGIF object
    
    // Text State
    bool isTextMode = false;
    String textMessage;
    bool textScroll = false;
    uint16_t textColor = 0xFFFF; // White
    int textX = 0;
    int textWidth = 0;
    unsigned long lastScrollTime = 0;

    // Streaming (Triple Buffering)
    uint8_t* netBuffer = nullptr;   // Network writes here
    uint8_t* readyBuffer = nullptr; // Latest complete frame
    uint8_t* drawBuffer = nullptr;  // Currently being drawn
    bool newFrameAvailable = false; // Flag if readyBuffer has new content
    std::mutex streamMutex;         // Protects swapping readyBuffer <-> netBuffer/drawBuffer
    
    // Pending Commands (from other tasks)
    bool cmdPending = false;
    enum CmdType { CMD_NONE, CMD_PLAY_SINGLE, CMD_PLAY_ALL, CMD_STOP, CMD_SET_DURATION, CMD_SET_ROTATION, CMD_START_STREAM, CMD_SET_BRIGHTNESS, CMD_SHOW_TEXT, CMD_SET_PLAYLIST, CMD_SET_SHUFFLE };
    CmdType pendingCmd = CMD_NONE;
    String pendingParam;
    unsigned long pendingVal = 0;
    int pendingInt = 0;
    bool pendingBool = false; // For scroll flag

    // State
    bool isPlaying = false;
    bool isStreaming = false;
    bool singleMode = false;
    bool isShuffle = false;
    std::vector<String> playlist;
    String currentPlaylist = "ALL";
    int playlistIndex = 0;
    String currentFile;
    String pendingFileNotification = ""; // For thread-safe callbacks
    FileChangeCallback onFileChange = nullptr;
    
    // Timing
    unsigned long loopDurationMs = DEFAULT_LOOP_DURATION;
    unsigned long currentGifStartTime = 0;
    unsigned long nextGifFrameTime = 0;

    // Internal Logic
    void loadNextInPlaylist();
    void _playFile(const String& path);
    void _playAll(const String& playlistName = "");
    void _stop();
    void _showText(const String& text, bool scroll);
    
    // GIF Callbacks
    static void GIFDraw(GIFDRAW *pDraw);
    static void* GIFOpenFile(const char *fname, int32_t *pSize);
    static void GIFCloseFile(void *pHandle);
    static int32_t GIFReadFile(GIFFILE *pFile, uint8_t *pBuf, int32_t iLen);
    static int32_t GIFSeekFile(GIFFILE *pFile, int32_t iPosition);
};