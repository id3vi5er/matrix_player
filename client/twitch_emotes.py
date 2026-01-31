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

# --- Image Processing (Adapted from main.py) ---
def process_image_to_bytes(img_src, bg_color=(0,0,0,255)):
    """
    Converts a PIL Image to raw RGB565 or RGB888 bytes for streaming.
    The ESP32 expects 64x64 RGB888 (3 bytes per pixel) based on main.py analysis.
    """
    # Create a black background
    new_bg = Image.new("RGBA", (64, 64), bg_color)
    
    # Resize Logic: Fit (Contain)
    img = img_src.convert("RGBA")
    img.thumbnail((64, 64), Image.Resampling.LANCZOS)
    
    # Center
    x = (64 - img.width) // 2
    y = (64 - img.height) // 2
    new_bg.paste(img, (x, y), img)
    
    # Convert to RGB (Drop Alpha)
    final_img = new_bg.convert("RGB")
    return final_img.tobytes()

class DisplayController:
    def __init__(self, ip):
        self.ip = ip
        self.ws_url = f"ws://{ip}/ws"
        self.ws = None
        self.connected = False
        self.can_send = True
        self.image_queue = queue.Queue()
        self.current_image_bytes = None
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        
    def start(self):
        self.thread.start()

    def _run_loop(self):
        while not self.stop_event.is_set():
            try:
                print(f"[Display] Connecting to {self.ws_url}...")
                self.ws = websocket.WebSocketApp(
                    self.ws_url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close
                )
                self.ws.run_forever()
                time.sleep(2) # Retry delay
            except Exception as e:
                print(f"[Display] Connection error: {e}")
                time.sleep(5)

    def _on_open(self, ws):
        print("[Display] Connected to ESP32")
        self.connected = True
        # Enable stream mode
        ws.send(json.dumps({"cmd": "stream"}))
        self.can_send = True
        
        # Start the sender loop in a separate thread/loop check
        threading.Thread(target=self._stream_sender, daemon=True).start()

    def _on_message(self, ws, message):
        # Check for binary ACK 'K' (0x4B)
        if isinstance(message, bytes):
            if len(message) == 1 and message[0] == 0x4B:
                self.can_send = True
                # print("ACK")

    def _on_error(self, ws, error):
        print(f"[Display] Error: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        print("[Display] Disconnected")
        self.connected = False

    def _stream_sender(self):
        """Loop that sends frames when allowed"""
        last_frame_time = 0
        while self.connected:
            if not self.image_queue.empty():
                # Get new image to show
                self.current_image_bytes = self.image_queue.get()
            
            # Use current image or idle (black/default)
            data_to_send = self.current_image_bytes
            
            if data_to_send and self.can_send:
                try:
                    self.ws.send(data_to_send, opcode=websocket.ABNF.OPCODE_BINARY)
                    self.can_send = False
                    last_frame_time = time.time()
                except Exception as e:
                    print(f"[Display] Send error: {e}")
                    break
            
            # Timeout/Keepalive reset
            if not self.can_send and (time.time() - last_frame_time > 2.0):
                self.can_send = True
            
            time.sleep(0.01) # Max 100 FPS loop

    def show_image(self, pil_image):
        """Convert and queue image for display"""
        try:
            raw_bytes = process_image_to_bytes(pil_image)
            # Clear queue to jump to latest
            with self.image_queue.mutex:
                self.image_queue.queue.clear()
            self.image_queue.put(raw_bytes)
        except Exception as e:
            print(f"[Display] Error processing image: {e}")

class TwitchBot:
    def __init__(self, channel, token, username, display_controller):
        self.channel = channel
        self.token = token
        self.username = username
        self.display = display_controller
        self.ws_url = "wss://irc-ws.chat.twitch.tv:443"
        self.ws = None
        self.last_emote_time = 0

    def start(self):
        # websocket.enableTrace(True)
        self.ws = websocket.WebSocketApp(
            self.ws_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close
        )
        self.ws.run_forever()

    def _on_open(self, ws):
        print(f"[Twitch] Connecting to #{self.channel}...")
        ws.send(f"PASS {self.token}")
        ws.send(f"NICK {self.username}")
        ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands")
        ws.send(f"JOIN #{self.channel.lower()}")

    def _on_message(self, ws, message):
        # Handle PING
        if message.startswith("PING"):
            ws.send("PONG :tmi.twitch.tv")
            return

        try:
            # Parse tags
            if "PRIVMSG" in message:
                self._handle_chat(message)
        except Exception as e:
            print(f"[Twitch] Parse error: {e}")

    def _handle_chat(self, raw_msg):
        # Example format:
        # @badge-info=...;emotes=25:0-4,12-16/1902:6-10;... :user!user@... PRIVMSG #channel :Kappa Keepo
        
        parts = raw_msg.split(" ", 1)
        if len(parts) < 2: return
        
        tags_str = parts[0]
        if not tags_str.startswith("@"): return # Should not happen with CAP REQ tags
        
        tags = {}
        for tag in tags_str[1:].split(";"):
            if "=" in tag:
                k, v = tag.split("=", 1)
                tags[k] = v
        
        emotes_str = tags.get("emotes")
        if emotes_str:
            # "25:0-4,12-16/1902:6-10"
            # Get the first emote ID found
            emote_id = emotes_str.split("/")[0].split(":")[0]
            print(f"[Twitch] Emote detected! ID: {emote_id}")
            self._fetch_and_display_emote(emote_id)

    def _fetch_and_display_emote(self, emote_id):
        # Fetch image
        url = f"https://static-cdn.jtvnw.net/emoticons/v2/{emote_id}/default/dark/3.0"
        try:
            r = requests.get(url, timeout=2)
            if r.status_code == 200:
                img = Image.open(io.BytesIO(r.content))
                print(f"[System] Displaying emote {emote_id}")
                self.display.show_image(img)
                self.last_emote_time = time.time()
                
                # Reset to idle after X seconds (handled by a timer or checking timestamp in loop)
                threading.Timer(CONFIG.get("show_duration", 3.0), self._check_reset).start()
            else:
                print(f"[System] Failed to download emote: {r.status_code}")
        except Exception as e:
            print(f"[System] Download error: {e}")

    def _check_reset(self):
        # If no new emote has been shown in the last X seconds, show idle
        if time.time() - self.last_emote_time >= CONFIG.get("show_duration", 3.0):
            self._show_idle()

    def _show_idle(self):
        idle_path = CONFIG.get("idle_image", "idle.png")
        if os.path.exists(idle_path):
            try:
                img = Image.open(idle_path)
                self.display.show_image(img)
            except:
                pass
        else:
            # Create a default black image if idle missing
            img = Image.new("RGB", (64, 64), (0,0,0))
            self.display.show_image(img)

    def _on_error(self, ws, error):
        print(f"[Twitch] Error: {error}")

    def _on_close(self, ws, *args):
        print("[Twitch] Connection closed")

if __name__ == "__main__":
    # Validate config
    if CONFIG["twitch_channel"] == "YOUR_CHANNEL_NAME":
        print("Please configure 'config.json' with your Twitch details.")
        sys.exit(0)

    # 1. Start Display Controller
    display = DisplayController(CONFIG["esp32_ip"])
    display.start()

    # 2. Start Twitch Bot
    bot = TwitchBot(
        CONFIG["twitch_channel"], 
        CONFIG["twitch_oauth_token"], 
        CONFIG["twitch_username"], 
        display
    )
    
    # Show initial idle
    bot._show_idle()
    
    try:
        bot.start()
    except KeyboardInterrupt:
        print("Exiting...")
        sys.exit(0)
