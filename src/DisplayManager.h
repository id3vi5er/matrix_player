#pragma once
#include <ESP32-HUB75-MatrixPanel-I2S-DMA.h>
#include <AnimatedGIF.h>
#include <vector>
#include <mutex>
#include <atomic>
#include <functional>
#include "Config.h"
#include "FileManager.h"

#include <set>

// Text Overlay Structure for HA-Screen Mode
struct TextOverlay {
    String text = "";    // Text content (empty = don't draw)
    int16_t x = 0;       // X position (0-64)
    int16_t y = 0;       // Y position (0-64)
    uint16_t color = 0xFFFF; // RGB565 color (Default white)
    uint8_t size = 1;    // Font size 1-8 (default 5x7 font)
    bool enabled = false; // Overlay active?
};

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

    // HA-Screen Mode
    void setMode(const String& mode);
    void setHABackground(const String& path);
    void setOverlayText(uint8_t index, const String& text);
    void setOverlayPosition(uint8_t index, int16_t x, int16_t y);
    void setOverlayColor(uint8_t index, uint16_t color);
    void setOverlaySize(uint8_t index, uint8_t size);

    // Hardware Control for OTA
    void stopDMA() { if(dma) dma->stopDMAoutput(); }
    void resumeDMA() { if(dma) dma->begin(); }
    
    String getCurrentFile() { return currentFile; }
    uint8_t getBrightness() { return currentBrightness; }
    String getCurrentPlaylist() { return currentPlaylist; }
    bool getShuffle() { return isShuffle; }
    unsigned long getLoopDuration() { return loopDurationMs; }
    bool getIsPlaying() { return isPlaying || isHAScreenMode; }
    bool getSingleMode() { return singleMode; }

    // HA-Screen Getters
    bool isInHAScreenMode() { return isHAScreenMode; }
    String getHABackground() { return haScreenBackgroundFile; }
    String getOverlayText(uint8_t index) { return (index < 2) ? overlays[index].text : ""; }
    int16_t getOverlayX(uint8_t index) { return (index < 2) ? overlays[index].x : 0; }
    int16_t getOverlayY(uint8_t index) { return (index < 2) ? overlays[index].y : 0; }
    uint16_t getOverlayColor(uint8_t index) { return (index < 2) ? overlays[index].color : 0xFFFF; }
    uint8_t getOverlaySize(uint8_t index) { return (index < 2) ? overlays[index].size : 1; }

    // Streaming
    void startStreaming();
    bool handleStreamChunk(uint8_t* data, size_t len, size_t index, size_t totalLen);

    // Decompression
    bool decompressFrame(uint8_t* data, size_t len, uint8_t* output, size_t outputSize);
    bool decompressDeltaFrame(uint8_t* data, size_t len, uint8_t* output, size_t outputSize);
    bool decompressRLEFrame(uint8_t* data, size_t len, uint8_t* output, size_t outputSize);

    // Text
    void showText(const String& text, bool scroll = false);
    void setTextColor(uint8_t r, uint8_t g, uint8_t b);
    void setTextSize(uint8_t size);

    // Delete Progress Bar
    void showDeleteProgress(const String& label, float progress);
    void hideDeleteProgress();
    
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
    uint8_t textSize = DEFAULT_FONT_SIZE;
    int textX = 0;
    int textWidth = 0;
    unsigned long lastScrollTime = 0;

    // State Backup (for returning from Text/Progress Mode)
    bool savedIsPlaying = false;
    bool savedSingleMode = false;
    String savedCurrentFile;
    String savedCurrentPlaylist;

    // Delete Progress Bar State
    bool isDeleteProgressMode = false;
    float deleteProgress = 0.0f;
    String deleteLabel;

    // Streaming (Triple Buffering)
    uint8_t* netBuffer = nullptr;   // Network writes here
    uint8_t* readyBuffer = nullptr; // Latest complete frame
    uint8_t* drawBuffer = nullptr;  // Currently being drawn
    bool newFrameAvailable = false; // Flag if readyBuffer has new content
    std::mutex streamMutex;         // Protects swapping readyBuffer <-> netBuffer/drawBuffer
    std::atomic<bool> allowIncomingStream{false}; // Allows Network Task to write to buffer even if Loop hasn't switched mode yet

    // Decompression state
    uint8_t* prevFrameBuffer = nullptr;  // For delta frames (12KB)
    bool compressionEnabled = true;

    // Pending Commands (from other tasks)
    bool cmdPending = false;
    enum CmdType {
        CMD_NONE, CMD_PLAY_SINGLE, CMD_PLAY_ALL, CMD_STOP, CMD_SET_DURATION,
        CMD_SET_ROTATION, CMD_START_STREAM, CMD_SET_BRIGHTNESS, CMD_SHOW_TEXT,
        CMD_SET_PLAYLIST, CMD_SET_SHUFFLE, CMD_SET_TEXT_COLOR, CMD_SET_FONT_SIZE,
        CMD_SET_MODE, CMD_SET_HA_BACKGROUND, CMD_SET_OVERLAY_TEXT,
        CMD_SET_OVERLAY_POSITION, CMD_SET_OVERLAY_COLOR, CMD_SET_OVERLAY_SIZE
    };
    CmdType pendingCmd = CMD_NONE;
    String pendingParam;
    unsigned long pendingVal = 0;
    int pendingInt = 0;
    bool pendingBool = false; // For scroll flag
    uint8_t pendingR, pendingG, pendingB; // For Color Command

    // HA-Screen Pending Commands
    String pendingMode;
    int pendingOverlayIndex = 0;
    String pendingOverlayText;
    int pendingOverlayX = -1;
    int pendingOverlayY = -1;
    uint16_t pendingOverlayColor = 0xFFFF;
    uint8_t pendingOverlaySize = 1;

    // State
    uint8_t currentBrightness = DEFAULT_BRIGHTNESS; // Track locally since library has no getter
    bool isPlaying = false;
    bool isStreaming = false;
    bool singleMode = false;
    bool isShuffle = false;

    // HA-Screen Mode State
    bool isHAScreenMode = false;
    String haScreenBackgroundFile;
    TextOverlay overlays[2];

    std::vector<String> playlist; // Current file list (one folder)
    std::vector<String> metaPlaylist; // List of folders to play
    int metaPlaylistIndex = -1;
    
    String currentPlaylist = "ALL";
    int playlistIndex = 0;
    String currentFile;
    String pendingFileNotification = ""; // For thread-safe callbacks
    FileChangeCallback onFileChange = nullptr;
    
    // Timing
    unsigned long loopDurationMs = DEFAULT_LOOP_DURATION;
    unsigned long currentGifStartTime = 0;
    unsigned long nextGifFrameTime = 0;
    
    // RAM Playback
    uint8_t* currentGifData = nullptr;
    void freeGifData();

    // Internal Logic
    void loadNextInPlaylist();
    void loadPlaylistFolder(const String& folder);
    void _playFile(const String& path);
    void _playAll(const String& playlistName = "");
    void _stop();
    void _showText(const String& text, bool scroll);

    // HA-Screen Private Methods
    void _setMode(const String& mode);
    void _startHAScreen(const String& backgroundPath);
    void _drawOverlays();

    // GIF Callbacks
    static void GIFDraw(GIFDRAW *pDraw);
    static void* GIFOpenFile(const char *fname, int32_t *pSize);
    static void GIFCloseFile(void *pHandle);
    static int32_t GIFReadFile(GIFFILE *pFile, uint8_t *pBuf, int32_t iLen);
    static int32_t GIFSeekFile(GIFFILE *pFile, int32_t iPosition);
};