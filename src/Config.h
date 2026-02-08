#pragma once
#include "Secrets.h"

// --- WiFi Settings ---
// WIFI_SSID and WIFI_PASS are defined in Secrets.h
// Copy src/Secrets_example.h to src/Secrets.h if missing.

// --- Matrix Pinout (ESP32-S3) ---
#define R1_PIN 42
#define G1_PIN 41
#define B1_PIN 40
#define R2_PIN 38
#define G2_PIN 39
#define B2_PIN 13 // Changed from 35 (PSRAM conflict) to 13
#define A_PIN 4
#define B_PIN 5
#define C_PIN 6
#define D_PIN 7
#define E_PIN 15
#define CLK_PIN 16
#define LAT_PIN 17
#define OE_PIN 1

// --- Matrix Specs ---
#define PANEL_RES_X 64
#define PANEL_RES_Y 64
#define PANEL_CHAIN 1

// --- Defaults ---
#define DEFAULT_BRIGHTNESS 150
#define DEFAULT_LOOP_DURATION 6000 // ms
#define DEFAULT_ROTATION 1 // 0-3 (0°, 90°, 180°, 270°)
#define DEFAULT_PLAYLIST "Default" // "ALL" for everything, or folder name e.g. "Party"
#define DEFAULT_FONT_SIZE 1 // 1 = 5x7 px, 2 = 10x14 px, etc.

// --- HA-Screen Mode Defaults ---
#define HA_SCREEN_MAX_OVERLAYS 2
#define HA_SCREEN_DEFAULT_COLOR 0xFFFF  // White (RGB565)
#define HA_SCREEN_DEFAULT_SIZE 1        // Font size

// --- MQTT Settings ---
#define MQTT_TOPIC_PREFIX "ledmatrix"
#define MQTT_RECONNECT_INTERVAL 5000

