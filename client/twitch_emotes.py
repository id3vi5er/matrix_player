import websocket
import threading
import json
import time
import requests
import io
import sys
import os
import queue
from PIL import Image, ImageOps, ImageSequence

# --- Global Config Loader ---
def load_config():
    if os.path.exists("config.json"):
        with open("config.json", "r") as f:
            return json.load(f)
    print("Config file not found. Please create config.json based on config.json.example")
    sys.exit(1)

CONFIG = load_config()

# --- Image Processing ---
def process_to_gif_bytes(img_src):
    """
    Converts PIL Image (or sequence) to an optimized 64x64 GIF byte stream.
    Handles resizing (Fit/Contain), centering, and background.
    """
    frames = []
    durations = []
    
    # Check if animated
    is_animated = getattr(img_src, "is_animated", False)
    iterator = ImageSequence.Iterator(img_src) if is_animated else [img_src]

    for frame in iterator:
        # 1. Convert to RGBA
        rgba = frame.convert("RGBA")
        
        # 2. Resize (Fit)
        rgba.thumbnail((64, 64), Image.Resampling.LANCZOS)
        
        # 3. Create Black Background & Center
        bg = Image.new("RGBA", (64, 64), (0, 0, 0, 255))
        x = (64 - rgba.width) // 2
        y = (64 - rgba.height) // 2
        bg.paste(rgba, (x, y), rgba)
        
        # 4. Quantize for GIF (Adaptive Palette)
        # Dither=None often looks cleaner for pixel art/icons, but ADAPTIVE is good for photos
        p_img = bg.convert("P", palette=Image.Palette.ADAPTIVE)
        
        frames.append(p_img)
        durations.append(frame.info.get('duration', 100)) # Default 100ms

    # Save to Bytes
    out = io.BytesIO()
    if len(frames) > 0:
        frames[0].save(
            out, 
            format='GIF', 
            save_all=True, 
            append_images=frames[1:], 
            duration=durations, 
            loop=0, 
            disposal=2
        )
    out.seek(0)
    return out

class MatrixController:
    def __init__(self, ip):
        self.ip = ip
        self.ws_url = f"ws://{ip}/ws"
        self.upload_url = f"http://{ip}/upload"
        self.ws = None
        self.connected = False
        self.known_files = set() # Cache of files on ESP32
        self.thread = threading.Thread(target=self._run_ws, daemon=True)
        self.ready_event = threading.Event()

    def start(self):
        self.thread.start()
        # Wait for connection and file list
        print("[Matrix] Connecting...")
        self.ready_event.wait(timeout=5)

    def _run_ws(self):
        while True:
            try:
                self.ws = websocket.WebSocketApp(
                    self.ws_url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close
                )
                self.ws.run_forever()
                time.sleep(5)
            except Exception:
                time.sleep(5)

    def _on_open(self, ws):
        print("[Matrix] WebSocket Connected")
        self.connected = True
        # Request file list to build cache
        ws.send(json.dumps({"cmd": "list"}))

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            cmd = data.get('cmd')
            
            if cmd == 'list' or cmd == 'list_end':
                files = data.get('files', [])
                for f in files:
                    self.known_files.add(f)
                print(f"[Matrix] File list updated. {len(self.known_files)} files known.")
                self.ready_event.set()
                
            elif cmd == 'list_chunk':
                files = data.get('files', [])
                for f in files:
                    self.known_files.add(f)
                    
        except:
            pass

    def _on_error(self, ws, error):
        pass # print(f"[Matrix] WS Error: {error}")

    def _on_close(self, ws, *args):
        self.connected = False
        print("[Matrix] Disconnected")

    def upload_file(self, filename, file_bytes_io):
        """Uploads a file via HTTP POST"""
        print(f"[Matrix] Uploading {filename}...")
        try:
            files = {'file': (filename, file_bytes_io, 'image/gif')}
            r = requests.post(self.upload_url, files=files, timeout=10)
            if r.status_code == 200:
                self.known_files.add(f"/{filename}")
                return True
            else:
                print(f"[Matrix] Upload failed: {r.status_code}")
                return False
        except Exception as e:
            print(f"[Matrix] Upload error: {e}")
            return False

    def play_file(self, filename):
        """Sends Play command via WebSocket"""
        if not filename.startswith("/"):
            filename = "/" + filename
        
        if self.connected:
            self.ws.send(json.dumps({"cmd": "play", "file": filename}))
            # print(f"[Matrix] Playing {filename}")

    def ensure_and_play(self, filename, image_data):
        """Checks if file exists, uploads if not, then plays."""
        target_name = f"/{filename}"
        if target_name not in self.known_files:
            # Prepare bytes
            gif_io = process_to_gif_bytes(image_data)
            success = self.upload_file(filename, gif_io)
            if not success:
                return
        
        self.play_file(filename)

class TwitchBot:
    def __init__(self, channel, token, username, matrix_controller):
        self.channel = channel
        self.token = token
        self.username = username
        self.matrix = matrix_controller
        self.ws_url = "wss://irc-ws.chat.twitch.tv:443"
        self.last_emote_time = 0
        self.idle_timer = None

    def start(self):
        # Initial Idle
        self._show_idle()
        
        ws = websocket.WebSocketApp(
            self.ws_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error
        )
        ws.run_forever()

    def _on_open(self, ws):
        print(f"[Twitch] Connected. Joining #{self.channel}...")
        ws.send(f"PASS {self.token}")
        ws.send(f"NICK {self.username}")
        ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands")
        ws.send(f"JOIN #{self.channel.lower()}")

    def _on_message(self, ws, message):
        if message.startswith("PING"):
            ws.send("PONG :tmi.twitch.tv")
            return

        if "PRIVMSG" in message:
            self._handle_chat(message)

    def _handle_chat(self, raw_msg):
        # Parse for Emotes
        parts = raw_msg.split(" ", 1)
        if len(parts) < 2 or not parts[0].startswith("@"): return
        
        tags = {}
        for tag in parts[0][1:].split(";"):
            if "=" in tag:
                k, v = tag.split("=", 1)
                tags[k] = v
        
        emotes_str = tags.get("emotes")
        if emotes_str:
            # Get first emote ID
            emote_id = emotes_str.split("/")[0].split(":")[0]
            print(f"[Twitch] Emote detected: {emote_id}")
            self._process_emote(emote_id)

    def _process_emote(self, emote_id):
        self.last_emote_time = time.time()
        
        # 1. Check if we have it on the Matrix already
        filename = f"t_{emote_id}.gif"
        if f"/{filename}" in self.matrix.known_files:
            print(f"[System] Cached: {filename}")
            self.matrix.play_file(filename)
            self._reset_timer()
            return

        # 2. If not, fetch and upload
        url = f"https://static-cdn.jtvnw.net/emoticons/v2/{emote_id}/default/dark/3.0"
        try:
            r = requests.get(url, timeout=3)
            if r.status_code == 200:
                img = Image.open(io.BytesIO(r.content))
                self.matrix.ensure_and_play(filename, img)
                self._reset_timer()
        except Exception as e:
            print(f"[System] Download failed: {e}")

    def _reset_timer(self):
        if self.idle_timer:
            self.idle_timer.cancel()
        
        duration = CONFIG.get("show_duration", 3.0)
        self.idle_timer = threading.Timer(duration, self._show_idle)
        self.idle_timer.start()

    def _show_idle(self):
        idle_name = CONFIG.get("idle_image", "idle.png")
        
        # Try to find local file to upload if missing on ESP
        local_path = idle_name
        if os.path.exists(local_path):
            img = Image.open(local_path)
            self.matrix.ensure_and_play(idle_name, img)
        else:
            # Just try to play it, maybe it's already there
            self.matrix.play_file(idle_name)

    def _on_error(self, ws, error):
        print(f"[Twitch] Error: {error}")

if __name__ == "__main__":
    if CONFIG["twitch_channel"] == "YOUR_CHANNEL_NAME":
        print("Please configure 'config.json'.")
        sys.exit(0)

    matrix = MatrixController(CONFIG["esp32_ip"])
    matrix.start()

    bot = TwitchBot(
        CONFIG["twitch_channel"], 
        CONFIG["twitch_oauth_token"], 
        CONFIG["twitch_username"], 
        matrix
    )
    
    try:
        bot.start()
    except KeyboardInterrupt:
        sys.exit(0)
