import sys
import threading
import json
import time
import requests
import io
import os
import queue
from PIL import Image, ImageSequence, ImageOps
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLineEdit, QPushButton, QLabel, QSlider, QGroupBox, QTextEdit, 
                             QMessageBox, QProgressBar, QComboBox, QCheckBox, QDoubleSpinBox)
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtCore import Qt, pyqtSignal, QObject
import websocket

# --- Global Config Loader ---
def load_config():
    if os.path.exists("config.json"):
        with open("config.json", "r") as f:
            return json.load(f)
    print("Config file not found. Please create config.json based on config.json.example")
    return {"esp32_ip": "192.168.178.155", "twitch_channel": "", "twitch_oauth_token": "", "twitch_username": "", "show_duration": 3.0, "always_show_last_emote": False, "idle_image": "idle.png"}

def save_config(cfg):
    try:
        with open("config.json", "w") as f:
            json.dump(cfg, f, indent=4)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False

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

# --- Logic Classes (adapted for GUI) ---

class WorkerSignals(QObject):
    log = pyqtSignal(str)
    connected_matrix = pyqtSignal(bool)
    connected_twitch = pyqtSignal(bool)
    storage_update = pyqtSignal(int, int) # total, used
    playlists_update = pyqtSignal(list)

class MatrixController:
    def __init__(self, ip, signals):
        self.ip = ip
        self.ws_url = f"ws://{ip}/ws"
        self.upload_url = f"http://{ip}/upload"
        self.ws = None
        self.connected = False
        self.known_files = set() 
        self.signals = signals
        
        self.ws_thread = threading.Thread(target=self._run_ws, daemon=True)
        self.ready_event = threading.Event()
        
        self.emote_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)

    def start(self):
        self.ws_thread.start()
        self.worker_thread.start()
        self.signals.log.emit("[Matrix] Connecting...")

    def update_ip(self, new_ip):
        self.ip = new_ip
        self.ws_url = f"ws://{new_ip}/ws"
        self.upload_url = f"http://{new_ip}/upload"
        # Reconnect logic would be needed here, or just restart app.
        # For simplicity, we assume IP is set at start or requires restart for WS.

    def _process_queue(self):
        self.signals.log.emit("[Matrix] Worker waiting for file list...")
        self.ready_event.wait()
        self.signals.log.emit("[Matrix] Worker ready.")
        
        while True:
            try:
                emote_data = self.emote_queue.get()
                emote_type = emote_data.get('type', 'twitch')
                
                if emote_type == 'idle':
                    self._handle_idle()
                elif emote_type == 'custom':
                    self._handle_custom_emote(emote_data['name'], emote_data['url'])
                else:
                    self._handle_single_emote(emote_data['id'])
                
                time.sleep(2.0) 
                self.emote_queue.task_done()
            except Exception as e:
                self.signals.log.emit(f"[Matrix] Worker Error: {e}")

    def queue_emote(self, emote_id):
        self.emote_queue.put({'type': 'twitch', 'id': emote_id, 'time': time.time()})

    def queue_custom_emote(self, name, url):
        self.emote_queue.put({'type': 'custom', 'name': name, 'url': url, 'time': time.time()})

    def queue_idle(self):
        self.emote_queue.put({'type': 'idle', 'id': "__IDLE__", 'time': time.time()})

    def _handle_custom_emote(self, name, url):
        safe_name = "".join(x for x in name if x.isalnum())
        filename = f"f_{safe_name}.gif" # We always save as GIF on ESP
        target_path = f"/twitch/{filename}"
        
        if target_path in self.known_files:
            self.signals.log.emit(f"[System] Playing cached: {filename}")
            self.play_file(target_path)
            return

        self.signals.log.emit(f"[System] Processing Custom: {name}")
        
        # Download with Fallback
        img_data = None
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                img_data = r.content
            elif r.status_code == 404 and url.endswith(".gif"):
                # Fallback to WEBP
                fallback_url = url.replace(".gif", ".webp")
                self.signals.log.emit(f"[System] 404 on GIF, trying WEBP: {fallback_url}")
                r = requests.get(fallback_url, timeout=5)
                if r.status_code == 200:
                    img_data = r.content
                elif r.status_code == 404:
                     # Fallback to PNG
                    fallback_url = url.replace(".gif", ".png")
                    self.signals.log.emit(f"[System] 404 on WEBP, trying PNG: {fallback_url}")
                    r = requests.get(fallback_url, timeout=5)
                    if r.status_code == 200:
                        img_data = r.content

            if img_data:
                img = Image.open(io.BytesIO(img_data))
                gif_io = process_to_gif_bytes(img)
                
                if self.upload_file(filename, gif_io):
                    self.play_file(target_path)
                else:
                    self.signals.log.emit(f"[System] Upload failed: {filename}")
            else:
                self.signals.log.emit(f"[System] Download failed: {r.status_code}")
        except Exception as e:
            self.signals.log.emit(f"[System] Error: {e}")

    def _handle_idle(self):
        idle_name = CONFIG.get("idle_image", "idle.png")
        local_path = idle_name
        if os.path.exists(local_path):
            try:
                img = Image.open(local_path)
                self.ensure_and_play("idle.gif", img)
            except Exception as e:
                self.signals.log.emit(f"Error showing idle: {e}")
        else:
            self.play_file("/twitch/idle.gif")

    def _handle_single_emote(self, emote_id):
        filename = f"t_{emote_id}.gif"
        target_path = f"/twitch/{filename}"
        
        if target_path in self.known_files:
            self.signals.log.emit(f"[System] Playing cached: {filename}")
            self.play_file(target_path)
            return

        self.signals.log.emit(f"[System] Processing new: {emote_id}")
        url = f"https://static-cdn.jtvnw.net/emoticons/v2/{emote_id}/default/dark/3.0"
        try:
            r = requests.get(url, timeout=3)
            if r.status_code == 200:
                img = Image.open(io.BytesIO(r.content))
                gif_io = process_to_gif_bytes(img)
                
                if self.upload_file(filename, gif_io):
                    self.play_file(target_path)
                else:
                    self.signals.log.emit(f"[System] Upload failed: {filename}")
            else:
                self.signals.log.emit(f"[System] Download failed: {r.status_code}")
        except Exception as e:
            self.signals.log.emit(f"[System] Error: {e}")

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
        self.signals.log.emit("[Matrix] WebSocket Connected")
        self.signals.connected_matrix.emit(True)
        self.connected = True
        ws.send(json.dumps({"cmd": "list"}))

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            cmd = data.get('cmd')
            if cmd == 'list_start':
                total = data.get('total', 0)
                used = data.get('used', 0)
                if total > 0:
                    self.signals.storage_update.emit(total, used)
                
                playlists = data.get('playlists', [])
                if playlists:
                    self.signals.playlists_update.emit(playlists)
            
            if cmd == 'list' or cmd == 'list_end' or cmd == 'list_start':
                files = data.get('files', [])
                for f in files: self.known_files.add(f)
                if cmd != 'list_start':
                    self.ready_event.set()
            elif cmd == 'list_chunk':
                files = data.get('files', [])
                for f in files: self.known_files.add(f)
        except:
            pass

    def _on_error(self, ws, error):
        pass 

    def _on_close(self, ws, *args):
        self.connected = False
        self.signals.connected_matrix.emit(False)
        self.signals.log.emit("[Matrix] Disconnected")

    def upload_file(self, filename, file_bytes_io):
        try:
            headers = {"X-Playlist": "twitch"}
            files = {'file': (filename, file_bytes_io, 'image/gif')}
            r = requests.post(self.upload_url, files=files, headers=headers, timeout=20)
            if r.status_code == 200:
                self.known_files.add(f"/twitch/{filename}")
                return True
            return False
        except Exception as e:
            self.signals.log.emit(f"[Matrix] Upload error: {e}")
            return False

    def play_file(self, filename):
        if not filename.startswith("/"):
            if not filename.startswith("twitch/"):
                filename = "/twitch/" + filename
            else:
                filename = "/" + filename
        
        if self.connected:
            self.ws.send(json.dumps({"cmd": "play", "file": filename}))

    def send_cmd(self, cmd, payload):
        if self.connected:
            payload["cmd"] = cmd
            self.ws.send(json.dumps(payload))

    def purge_twitch_folder(self):
        if self.connected:
            self.signals.log.emit("[System] Purging /twitch/ folder on ESP32...")
            self.send_cmd("delete_playlist", {"name": "twitch"})
            # Clear local cache of twitch files
            self.known_files = {f for f in self.known_files if not f.startswith("/twitch/") and not f.startswith("twitch/")}
            self.signals.log.emit("[System] Cache cleared.")

    def ensure_and_play(self, filename, image_data):
        target_path = f"/twitch/{filename}"
        if target_path not in self.known_files:
             gif_io = process_to_gif_bytes(image_data)
             if self.upload_file(filename, gif_io):
                 self.play_file(target_path)
        else:
             self.play_file(target_path)

class TwitchBot:
    def __init__(self, channel, token, username, matrix_controller, signals):
        self.channel = channel
        self.token = token
        self.username = username
        self.matrix = matrix_controller
        self.signals = signals
        self.ws_url = "wss://irc-ws.chat.twitch.tv:443"
        self.last_emote_time = 0
        self.idle_timer = None
        self.ws = None
        self.running = False
        self.thread = None
        self.custom_emotes = {} # Code -> URL (FFZ & 7TV)

    def update_credentials(self, channel, token, username):
        self.channel = channel
        self.token = token
        self.username = username
        if self.running:
            self.restart()

    def start(self):
        if self.running: return
        self.running = True
        
        # Load Custom Emotes (FFZ, 7TV)
        self.custom_emotes = {} # Clear
        threading.Thread(target=self._load_all_emotes, daemon=True).start()
        
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        # Initial Idle - Queued to avoid blocking UI
        self.matrix.queue_idle()

    def _load_all_emotes(self):
        # Globals
        self.load_7tv_global_emotes()
        self.load_ffz_global_emotes()
        self.load_bttv_global_emotes()
        
        if not self.channel: return
        uid = self.resolve_user_id(self.channel)
        if uid:
            self.load_7tv_emotes(uid)
            self.load_bttv_emotes(uid)
        
        self.load_ffz_emotes(self.channel)

    # ... (7TV Global kept as is) ...

    def load_7tv_global_emotes(self):
        print("[7TV] Fetching Global Emotes...")
        try:
            r = requests.get("https://7tv.io/v3/emote-sets/global", timeout=5)
            if r.status_code == 200:
                data = r.json()
                emotes = data.get('emotes', [])
                count = 0
                for e in emotes:
                    name = e['name']
                    host = e['data']['host']['url']
                    if host.startswith("//"): host = "https:" + host
                    img_url = f"{host}/2x.gif"
                    self.custom_emotes[name] = img_url
                    count += 1
                print(f"[7TV] Loaded {count} Global Emotes.")
        except Exception as e:
            print(f"[7TV] Global Error: {e}")

    def load_ffz_global_emotes(self):
        print("[FFZ] Fetching Global Emotes...")
        try:
            r = requests.get("https://api.frankerfacez.com/v1/set/global", timeout=5)
            if r.status_code == 200:
                data = r.json()
                count = 0
                for set_id in data.get('default_sets', []):
                    emote_set = data['sets'].get(str(set_id), {})
                    for emote in emote_set.get('emoticons', []):
                        name = emote['name']
                        urls = emote['urls']
                        img_url = urls.get('4') or urls.get('2') or urls.get('1')
                        if img_url:
                            if img_url.startswith("//"): img_url = "https:" + img_url
                            self.custom_emotes[name] = img_url
                            count += 1
                print(f"[FFZ] Loaded {count} Global Emotes.")
        except Exception as e:
            print(f"[FFZ] Global Error: {e}")

    def load_bttv_global_emotes(self):
        print("[BTTV] Fetching Global Emotes...")
        try:
            r = requests.get("https://api.betterttv.net/3/cached/emotes/global", timeout=5)
            if r.status_code == 200:
                emotes = r.json()
                for e in emotes:
                    name = e['code']
                    eid = e['id']
                    # BTTV CDN: https://cdn.betterttv.net/emote/{id}/2x
                    self.custom_emotes[name] = f"https://cdn.betterttv.net/emote/{eid}/2x"
                print(f"[BTTV] Loaded {len(emotes)} Global Emotes.")
        except Exception as e:
            print(f"[BTTV] Global Error: {e}")

    def load_bttv_emotes(self, user_id):
        print(f"[BTTV] Fetching emotes for ID {user_id}...")
        try:
            r = requests.get(f"https://api.betterttv.net/3/cached/users/twitch/{user_id}", timeout=5)
            if r.status_code == 200:
                data = r.json()
                emotes = data.get('channelEmotes', []) + data.get('sharedEmotes', [])
                for e in emotes:
                    name = e['code']
                    eid = e['id']
                    self.custom_emotes[name] = f"https://cdn.betterttv.net/emote/{eid}/2x"
                print(f"[BTTV] Loaded {len(emotes)} emotes.")
        except Exception as e:
            print(f"[BTTV] Error: {e}")

    def resolve_user_id(self, username):
        try:
            r = requests.get(f"https://api.ivr.fi/v2/twitch/user?login={username.lower()}", timeout=5)
            if r.status_code == 200:
                data = r.json()
                if data and len(data) > 0:
                    return data[0]['id']
        except Exception as e:
            print(f"[System] ID Resolve Error: {e}")
        return None

    def load_7tv_emotes(self, user_id):
        print(f"[7TV] Fetching emotes for ID {user_id}...")
        try:
            url = f"https://7tv.io/v3/users/twitch/{user_id}"
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                emote_set = data.get('emote_set', {})
                emotes = emote_set.get('emotes', [])
                for e in emotes:
                    name = e['name']
                    # Use 2x GIF version if possible (7TV CDN handles conversion)
                    # Host example: //cdn.7tv.app/emote/ID
                    host = e['data']['host']['url']
                    if host.startswith("//"): host = "https:" + host
                    img_url = f"{host}/2x.gif" 
                    self.custom_emotes[name] = img_url
                print(f"[7TV] Loaded {len(emotes)} emotes.")
            else:
                print(f"[7TV] API Error: {r.status_code}")
        except Exception as e:
            print(f"[7TV] Error: {e}")

    def load_ffz_emotes(self, channel_name):
        # self.custom_emotes is shared
        print(f"[FFZ] Fetching emotes for {channel_name}...")
        try:
            url = f"https://api.frankerfacez.com/v1/room/{channel_name.lower()}"
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                if 'sets' in data:
                    count = 0
                    for set_id, emote_set in data['sets'].items():
                        for emote in emote_set.get('emoticons', []):
                            name = emote['name']
                            if name in self.custom_emotes: continue # 7TV priority? Or overwrite?
                            
                            urls = emote['urls']
                            img_url = urls.get('4') or urls.get('2') or urls.get('1')
                            if img_url:
                                if img_url.startswith("//"): img_url = "https:" + img_url
                                self.custom_emotes[name] = img_url
                                count += 1
                    print(f"[FFZ] Loaded {count} emotes.")
        except Exception as e:
            print(f"[FFZ] Error loading emotes: {e}")

    def stop(self):
        self.running = False
        if self.ws:
            self.ws.close()

    def restart(self):
        self.stop()
        time.sleep(1)
        self.start()

    def _run(self):
        self.ws = websocket.WebSocketApp(
            self.ws_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close
        )
        self.ws.run_forever()

    def _on_open(self, ws):
        self.signals.log.emit(f"[Twitch] Connected. Joining #{self.channel}...")
        self.signals.connected_twitch.emit(True)
        ws.send(f"PASS {self.token}")
        ws.send(f"NICK {self.username}")
        ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands")
        ws.send(f"JOIN #{self.channel.lower()}")

    def _on_error(self, ws, error):
        self.signals.log.emit(f"[Twitch] Error: {error}")

    def _on_close(self, ws, *args):
        self.signals.connected_twitch.emit(False)
        self.signals.log.emit("[Twitch] Disconnected")

    def _on_message(self, ws, message):
        if message.startswith("PING"):
            ws.send("PONG :tmi.twitch.tv")
            return
        if "PRIVMSG" in message:
            self._handle_chat(message)

    def _handle_chat(self, raw_msg):
        # Format: @tags :user!user@... PRIVMSG #channel :Message Text
        parts = raw_msg.split(" ", 1)
        if len(parts) < 2 or not parts[0].startswith("@"): return # Require tags
        
        # Parse Tags
        tags = {}
        tag_part = parts[0][1:]
        for tag in tag_part.split(";"):
            if "=" in tag:
                k, v = tag.split("=", 1)
                tags[k] = v
        
        # Extract Message Content (find second colon)
        # @... :user... PRIVMSG #channel :THIS IS THE MESSAGE
        try:
            msg_content = raw_msg.split("PRIVMSG", 1)[1].split(":", 1)[1].strip()
        except:
            return

        # 1. Native Twitch Emotes (via Tags)
        emotes_str = tags.get("emotes")
        if emotes_str:
            emote_groups = emotes_str.split("/")
            for group in emote_groups:
                if ":" in group:
                    emote_id = group.split(":")[0]
                    self.signals.log.emit(f"[Twitch] Emote: {emote_id}")
                    self._process_emote(emote_id)

        # 2. FFZ/7TV Emotes (via Text Parsing)
        # Scan words
        words = msg_content.split(" ")
        for word in words:
            if word in self.custom_emotes:
                url = self.custom_emotes[word]
                self.signals.log.emit(f"[Custom] Emote: {word}")
                self._process_emote_url(word, url)

    def _process_emote(self, emote_id):
        # Native Twitch Handler
        self.last_emote_time = time.time()
        self.matrix.queue_emote(emote_id)
        self._reset_timer()

    def _process_emote_url(self, name, url):
        # Handler for external URLs (FFZ)
        self.last_emote_time = time.time()
        # Create a pseudo-ID for FFZ to use the same queue logic
        # We need to tell MatrixController that this is a custom URL, not a Twitch ID.
        # Simple hack: Pass tuple/dict instead of just ID? 
        # Or extend MatrixController.
        self.matrix.queue_custom_emote(name, url)
        self._reset_timer()

    def _reset_timer(self):
        if self.idle_timer:
            self.idle_timer.cancel()
        
        # Dynamic check from CONFIG (which is updated by GUI)
        if CONFIG.get("always_show_last_emote", False):
            return

        duration = CONFIG.get("show_duration", 3.0)
        self.idle_timer = threading.Timer(duration, self._show_idle)
        self.idle_timer.start()

    def _show_idle(self):
        self.matrix.queue_idle()

    def _on_error(self, ws, error):
        self.signals.log.emit(f"[Twitch] Error: {error}")

    def _on_close(self, ws, *args):
        self.signals.connected_twitch.emit(False)
        self.signals.log.emit("[Twitch] Disconnected")

# --- GUI ---

class TwitchGui(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Twitch Matrix Bot")
        self.resize(500, 680)
        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e1e; color: #e0e0e0; font-family: 'Segoe UI'; }
            QGroupBox { border: 1px solid #3a3a3a; margin-top: 12px; background-color: #252526; font-weight: bold; color: #cccccc; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QLineEdit, QTextEdit, QComboBox, QDoubleSpinBox { background-color: #333; border: 1px solid #444; color: white; border-radius: 4px; padding: 4px; }
            QPushButton { background-color: #3a3a3a; border: 1px solid #444; border-radius: 4px; padding: 6px; color: white; }
            QPushButton:hover { background-color: #4a4a4a; }
            QPushButton:pressed { background-color: #2a2a2a; }
            QLabel, QCheckBox { color: #ccc; }
            QProgressBar { border: 1px solid #444; border-radius: 4px; text-align: center; background-color: #333; color: white; height: 18px; font-size: 11px; font-weight: bold;}
            QProgressBar::chunk { background-color: #007acc; border-radius: 3px; }
        """)

        self.signals = WorkerSignals()
        self.signals.log.connect(self.log_msg)
        self.signals.connected_matrix.connect(self.update_matrix_status)
        self.signals.connected_twitch.connect(self.update_twitch_status)
        self.signals.storage_update.connect(self.update_storage)
        self.signals.playlists_update.connect(self.update_playlists)

        self.matrix = MatrixController(CONFIG["esp32_ip"], self.signals)
        self.bot = TwitchBot(CONFIG["twitch_channel"], CONFIG["twitch_oauth_token"], CONFIG["twitch_username"], self.matrix, self.signals)

        self.init_ui()
        self.matrix.start()
        if self.bot.token and self.bot.channel:
            self.bot.start()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # 1. Twitch Config
        gb_twitch = QGroupBox("Twitch Settings")
        l_twitch = QVBoxLayout()
        
        h_chan = QHBoxLayout()
        h_chan.addWidget(QLabel("Channel:"))
        self.txt_channel = QLineEdit(CONFIG["twitch_channel"])
        self.btn_connect = QPushButton("Connect / Update")
        self.btn_connect.clicked.connect(self.update_twitch)
        h_chan.addWidget(self.txt_channel)
        h_chan.addWidget(self.btn_connect)
        
        self.lbl_status_twitch = QLabel("Twitch: Disconnected")
        self.lbl_status_twitch.setStyleSheet("color: #ce3030;")
        
        l_twitch.addLayout(h_chan)
        l_twitch.addWidget(self.lbl_status_twitch)
        gb_twitch.setLayout(l_twitch)
        layout.addWidget(gb_twitch)

        # 2. Bot Behavior
        gb_behav = QGroupBox("Bot Behavior")
        l_behav = QVBoxLayout()
        
        h_dur = QHBoxLayout()
        h_dur.addWidget(QLabel("Show Duration (sec):"))
        self.spin_duration = QDoubleSpinBox()
        self.spin_duration.setRange(0.5, 60.0)
        self.spin_duration.setValue(CONFIG.get("show_duration", 3.0))
        self.spin_duration.valueChanged.connect(self.update_config_values)
        h_dur.addWidget(self.spin_duration)
        l_behav.addLayout(h_dur)
        
        self.cb_always_show = QCheckBox("Always Show Last Emote (Disable Idle)")
        self.cb_always_show.setChecked(CONFIG.get("always_show_last_emote", False))
        self.cb_always_show.toggled.connect(self.update_config_values)
        l_behav.addWidget(self.cb_always_show)
        
        self.btn_save_cfg = QPushButton("Save Config")
        self.btn_save_cfg.clicked.connect(self.save_configuration)
        l_behav.addWidget(self.btn_save_cfg)
        
        gb_behav.setLayout(l_behav)
        layout.addWidget(gb_behav)

        # 3. Matrix Control
        gb_matrix = QGroupBox("Matrix Control")
        l_matrix = QVBoxLayout()
        
        self.lbl_status_matrix = QLabel("Matrix: Disconnected")
        self.lbl_status_matrix.setStyleSheet("color: #ce3030;")
        
        h_bright = QHBoxLayout()
        h_bright.addWidget(QLabel("Brightness:"))
        self.slider_bright = QSlider(Qt.Orientation.Horizontal)
        self.slider_bright.setRange(0, 255)
        self.slider_bright.setValue(128)
        self.slider_bright.valueChanged.connect(self.set_brightness)
        h_bright.addWidget(self.slider_bright)
        
        self.storage_bar = QProgressBar()
        self.storage_bar.setValue(0)
        self.storage_bar.setFormat("Storage: ? / ? MB")

        h_play = QHBoxLayout()
        self.combo_playlist = QComboBox()
        self.combo_playlist.addItem("Default")
        self.btn_playlist = QPushButton("Play Loop (Stop Bot)")
        self.btn_playlist.clicked.connect(self.start_playlist)
        h_play.addWidget(self.combo_playlist, 1)
        h_play.addWidget(self.btn_playlist)
        
        self.btn_purge = QPushButton("Purge Twitch Cache (Delete /twitch/)")
        self.btn_purge.setStyleSheet("background-color: #702020;") # Dark Red
        self.btn_purge.clicked.connect(self.purge_cache)

        l_matrix.addWidget(self.lbl_status_matrix)
        l_matrix.addLayout(h_bright)
        l_matrix.addWidget(self.storage_bar)
        l_matrix.addLayout(h_play)
        l_matrix.addWidget(self.btn_purge)
        gb_matrix.setLayout(l_matrix)
        layout.addWidget(gb_matrix)

        # 4. Log
        gb_log = QGroupBox("Event Log")
        l_log = QVBoxLayout()
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        l_log.addWidget(self.txt_log)
        gb_log.setLayout(l_log)
        layout.addWidget(gb_log)

    def log_msg(self, msg):
        self.txt_log.append(msg)
        sb = self.txt_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def update_storage(self, total, used):
        self.storage_bar.setMaximum(total)
        self.storage_bar.setValue(used)
        self.storage_bar.setFormat(f"Storage: {used/(1024*1024):.1f} / {total/(1024*1024):.1f} MB")

    def update_playlists(self, playlists):
        current = self.combo_playlist.currentText()
        self.combo_playlist.clear()
        self.combo_playlist.addItems(playlists)
        if current in playlists:
            self.combo_playlist.setCurrentText(current)

    def update_matrix_status(self, connected):
        if connected:
            self.lbl_status_matrix.setText(f"Matrix: Connected ({self.matrix.ip})")
            self.lbl_status_matrix.setStyleSheet("color: #4caf50;")
        else:
            self.lbl_status_matrix.setText("Matrix: Disconnected")
            self.lbl_status_matrix.setStyleSheet("color: #ce3030;")

    def update_twitch_status(self, connected):
        if connected:
            self.lbl_status_twitch.setText(f"Twitch: Connected (#{self.bot.channel})")
            self.lbl_status_twitch.setStyleSheet("color: #4caf50;")
        else:
            self.lbl_status_twitch.setText("Twitch: Disconnected")
            self.lbl_status_twitch.setStyleSheet("color: #ce3030;")

    def update_twitch(self):
        new_channel = self.txt_channel.text()
        if new_channel:
            self.bot.update_credentials(new_channel, CONFIG["twitch_oauth_token"], CONFIG["twitch_username"])
            CONFIG["twitch_channel"] = new_channel

    def update_config_values(self):
        CONFIG["show_duration"] = self.spin_duration.value()
        CONFIG["always_show_last_emote"] = self.cb_always_show.isChecked()
        # Note: TwitchBot uses CONFIG directly in _reset_timer, so changes apply immediately

    def save_configuration(self):
        self.update_config_values()
        if save_config(CONFIG):
            self.log_msg("[System] Configuration saved.")
        else:
            self.log_msg("[System] Error saving configuration.")

    def set_brightness(self):
        val = self.slider_bright.value()
        self.matrix.send_cmd("brightness", {"val": val})

    def start_playlist(self):
        if self.bot.idle_timer: self.bot.idle_timer.cancel()
        
        playlist = self.combo_playlist.currentText()
        self.matrix.send_cmd("play", {"file": "ALL", "playlist": playlist})
        self.log_msg(f"[System] Manual Playlist '{playlist}' Override started.")

    def purge_cache(self):
        reply = QMessageBox.question(self, "Confirm Purge", 
                                     "Delete ALL files in /twitch/ folder on ESP32?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.matrix.purge_twitch_folder()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = TwitchGui()
    win.show()
    sys.exit(app.exec())