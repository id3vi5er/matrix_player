# Concept: Live-Stream Compression (Delta + RLE)

## 1. Current State Analysis
- **Format**: RGB888, 64x64 pixels = 12,288 bytes per frame.
- **Protocol**: WebSocket binary frames with 1-byte ACK ('K').
- **Fragmentation**: Handled by `DisplayManager::handleStreamChunk` using `index` and `totalLen`.
- **Buffering**: Triple buffering (`netBuffer`, `readyBuffer`, `drawBuffer`) in `DisplayManager`.

## 2. Requirements & Libraries
- **PSRAM**: ESP32-S3 OPI PSRAM is available and used.
- **Memory**: Approx. 24KB additional RAM needed for `prevFrameBuffer` and `assemblyBuffer`.
- **Libraries**: No new libraries required. Standard C++ and Python logic.

## 3. Data Format Specification
Header Byte (1 Byte): `[Version(2b) | Type(1b) | RLE(1b) | Reserved(4b)]`
- Version: `00`
- Type: `0 = Full Frame`, `1 = Delta Frame`
- RLE: `0 = Raw`, `1 = RLE Compressed`

| Header | Mode | Description |
| :--- | :--- | :--- |
| `0x00` | **Full Raw** | 12,288 bytes of raw RGB888 data (legacy compatible + header). |
| `0x10` | **Full RLE** | RLE encoded full frame. |
| `0x20` | **Delta Sparse** | Only changed pixels: `[Count(2b LE)] + Count * [Pos(2b LE) + RGB(3b)]`. |
| `0x30` | **Reserved** | Potential for Delta+RLE. |

**Position Encoding**: `(y << 8) | x` (2 bytes).

## 4. Implementation Plan

### Phase 1: Client-Side (Python)
- **File**: `client/main.py`
- **Class `FrameCompressor`**:
  - Maintains `prev_frame`.
  - `compress(rgb_data)`: Decides between Full Raw, Full RLE, and Delta Sparse.
  - `_rle_encode(data)`: Simple RLE (RunLength byte + RGB).
  - `_get_delta(data)`: Compares with `prev_frame`, returns list of `(idx, color)`.
- **Integration**:
  - Update `send_stream_frame` to use `FrameCompressor`.
  - Handle "First Frame" and "Interval Sync" (force Full Frame every 100 frames).

### Phase 2: Firmware-Side (C++)
- **File**: `src/DisplayManager.h`
  - Add `assemblyBuffer` and `prevFrameBuffer`.
  - Add decompression methods.
- **File**: `src/DisplayManager.cpp`
  - `begin()`: Allocate new buffers in PSRAM.
  - `handleStreamChunk()`: 
    - Assemble chunks into `assemblyBuffer`.
    - Upon completion, parse header and decompress into `netBuffer`.
    - If Delta: Copy `prevFrameBuffer` to `netBuffer` first (or apply changes directly to a copy).
    - Update `prevFrameBuffer` with final frame.
    - Swap `netBuffer` with `readyBuffer`.

### Phase 3: Robustness
- Handle decompression errors (fallback to previous frame).
- Ensure thread safety during buffer swaps.
- Reset compressor state on stream start/stop.

## 5. Verification Checkpoints
1. **CLI Test**: Run a standalone Python script to compress/decompress a test image and verify pixel parity.
2. **Firmware Build**: Verify PSRAM allocation and basic loop stability.
3. **Integration (Raw+Header)**: Send Full Raw with header `0x00`, verify display works.
4. **Integration (RLE)**: Send solid color RLE, verify low bandwidth and correct display.
5. **Integration (Delta)**: Verify cursor movement uses significantly less bandwidth.

---
*Note on RLE*: A RunLength of 0 is not used. 1-255 pixels.
*Note on Delta Sparse*: If `Count * 5 + 3 > 12288`, fallback to Full Frame.
