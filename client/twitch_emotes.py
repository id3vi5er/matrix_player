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
        
        self.ws_thread = threading.Thread(target=self._run_ws, daemon=True)
        self.ready_event = threading.Event()
        
        # Emote Queue to prevent upload flooding
        self.emote_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.last_play_time = 0

    def start(self):
        self.ws_thread.start()
        self.worker_thread.start()
        
        print("[Matrix] Connecting...")
        self.ready_event.wait(timeout=5)

    def _process_queue(self):
        while True:
            try:
                # Wait for next emote (blocking)
                emote_data = self.emote_queue.get()
                emote_id = emote_data['id']
                
                # Check if we should play idle instead? No, idle is handled by TwitchBot timer.
                
                self._handle_single_emote(emote_id)
                
                # Minimum display time per emote (prevent skipping too fast)
                time.sleep(2.0) 
                
                self.emote_queue.task_done()
            except Exception as e:
                print(f"[Matrix] Worker Error: {e}")

    def queue_emote(self, emote_id):
        self.emote_queue.put({'id': emote_id, 'time': time.time()})

    def _handle_single_emote(self, emote_id):
        filename = f"t_{emote_id}.gif"
        target_path = f"/twitch/{filename}"
        
        # 1. Check Cache
        if target_path in self.known_files:
            print(f"[System] Playing cached: {filename}")
            self.play_file(target_path)
            return

        # 2. Download & Upload
        print(f"[System] Processing new emote: {emote_id}")
        url = f"https://static-cdn.jtvnw.net/emoticons/v2/{emote_id}/default/dark/3.0"
        try:
            r = requests.get(url, timeout=3)
            if r.status_code == 200:
                img = Image.open(io.BytesIO(r.content))
                
                # Convert
                gif_io = process_to_gif_bytes(img)
                
                # Upload with retry
                if self.upload_file(filename, gif_io):
                    self.play_file(target_path)
                else:
                    print(f"[System] Upload failed for {filename}")
            else:
                print(f"[System] Failed to download from Twitch: {r.status_code}")
        except Exception as e:
            print(f"[System] Error handling emote: {e}")

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
        pass 

    def _on_close(self, ws, *args):
        self.connected = False
        print("[Matrix] Disconnected")

    def upload_file(self, filename, file_bytes_io):
        """Uploads a file via HTTP POST"""
        print(f"[Matrix] Uploading {filename} to /twitch/...")
        try:
            headers = {"X-Playlist": "twitch"}
            files = {'file': (filename, file_bytes_io, 'image/gif')}
            
            # Increased timeout for stability
            r = requests.post(self.upload_url, files=files, headers=headers, timeout=20)
            if r.status_code == 200:
                self.known_files.add(f"/twitch/{filename}")
                return True
            else:
                print(f"[Matrix] Upload failed: {r.status_code}")
                return False
        except Exception as e:
            print(f"[Matrix] Upload error: {e}")
            return False

    def play_file(self, filename):
        if not filename.startswith("/"):
            if not filename.startswith("twitch/"):
                filename = "/twitch/" + filename
            else:
                filename = "/" + filename
        
        if self.connected:
            self.ws.send(json.dumps({"cmd": "play", "file": filename}))

    def ensure_and_play(self, filename, image_data):
        # Legacy/Direct method - redirects to queue logic or handles idle
        # For idle image, we might want direct upload if not exists
        target_path = f"/twitch/{filename}"
        if target_path not in self.known_files:
             gif_io = process_to_gif_bytes(image_data)
             if self.upload_file(filename, gif_io):
                 self.play_file(target_path)
        else:
             self.play_file(target_path)
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
            # The emotes tag format is: id:start-end,start-end/id:start-end
            # We split by / to get each emote type
            emote_groups = emotes_str.split("/")
            for group in emote_groups:
                if ":" in group:
                    emote_id = group.split(":")[0]
                    print(f"[Twitch] Emote detected: {emote_id}")
                    self._process_emote(emote_id)

    def _process_emote(self, emote_id):
        self.last_emote_time = time.time()
        print(f"[Twitch] Queued: {emote_id}")
        self.matrix.queue_emote(emote_id)
        self._reset_timer()

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
            try:
                img = Image.open(local_path)
                # Upload as idle.gif to twitch folder
                self.matrix.ensure_and_play("idle.gif", img)
            except Exception as e:
                print(f"Error showing idle: {e}")
        else:
            # Just try to play it, maybe it's already there (legacy)
            # Default to twitch folder version
            self.matrix.play_file("/twitch/idle.gif")

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
