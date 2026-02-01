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
                             QMessageBox, QProgressBar, QComboBox, QCheckBox, QDoubleSpinBox,
                             QListWidget, QListWidgetItem, QMenu, QTabWidget, QDialog)
from PyQt6.QtGui import QFont, QColor, QPixmap, QIcon, QImage
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QThread, QSize, QTimer
import websocket

# --- Pixel Canvas Logic ---
def load_config():
    if os.path.exists("config.json"):
        with open("config.json", "r") as f:
            return json.load(f)
    print("Config file not found. Please create config.json based on config.json.example")
    return {
        "esp32_ip": "192.168.178.155", 
        "twitch_channel": "", 
        "twitch_oauth_token": "", 
        "twitch_username": "", 
        "show_duration": 3.0, 
        "always_show_last_emote": False, 
        "idle_image": "idle.png", 
        "storage_refresh_interval": 60,
        "storage_threshold": 80,
        "storage_target": 50,
        "rolling_storage_enabled": True
    }

def save_config(cfg):
    try:
        with open("config.json", "w") as f:
            json.dump(cfg, f, indent=4)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False

CONFIG = load_config()

# --- Blacklist Loader ---
BLACKLIST_FILE = "blacklist.json"

def load_blacklist():
    if os.path.exists(BLACKLIST_FILE):
        try:
            with open(BLACKLIST_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {"twitch_ids": [], "custom_names": [], "enabled": True}

def save_blacklist(bl):
    try:
        with open(BLACKLIST_FILE, "w") as f:
            json.dump(bl, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving blacklist: {e}")
        return False

BLACKLIST = load_blacklist()

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

# --- Pixel Canvas Logic ---
COLOR_MAP = {
    "red": (255, 0, 0), "rot": (255, 0, 0),
    "green": (0, 255, 0), "grün": (0, 255, 0),
    "blue": (0, 0, 255), "blau": (0, 0, 255),
    "black": (0, 0, 0), "schwarz": (0, 0, 0),
    "white": (255, 255, 255), "weiß": (255, 255, 255),
    "yellow": (255, 255, 0), "gelb": (255, 255, 0),
    "cyan": (0, 255, 255), "türkis": (0, 255, 255),
    "magenta": (255, 0, 255), "pink": (255, 0, 255),
    "orange": (255, 165, 0), "purple": (128, 0, 128), "lila": (128, 0, 128),
    "gray": (128, 128, 128), "grau": (128, 128, 128)
}

class PixelCanvas:
    def __init__(self, filename="canvas.png"):
        self.filename = filename
        self.width = 64
        self.height = 64
        self.is_dirty = False
        self.image = Image.new("RGB", (self.width, self.height), (0, 0, 0))
        self.load()

    def load(self):
        if os.path.exists(self.filename):
            try:
                loaded = Image.open(self.filename)
                if loaded.size == (self.width, self.height):
                    self.image = loaded.convert("RGB")
            except Exception as e:
                print(f"Error loading canvas: {e}")

    def save(self):
        try:
            self.image.save(self.filename)
        except Exception as e:
            print(f"Error saving canvas: {e}")

    def set_pixel(self, x, y, color_val):
        # x, y are 1-based from chat -> convert to 0-based
        ix = x - 1
        iy = y - 1
        
        if not (0 <= ix < self.width and 0 <= iy < self.height):
            return False

        # Parse Color
        rgb = None
        color_val = color_val.lower()
        
        if color_val in COLOR_MAP:
            rgb = COLOR_MAP[color_val]
        elif color_val.startswith("#") or len(color_val) == 6:
            try:
                c = color_val.lstrip("#")
                rgb = tuple(int(c[i:i+2], 16) for i in (0, 2, 4))
            except:
                pass
        
        if rgb:
            current = self.image.getpixel((ix, iy))
            if current != rgb:
                self.image.putpixel((ix, iy), rgb)
                self.is_dirty = True
                return True
        return False

    def reset(self):
        self.image = Image.new("RGB", (self.width, self.height), (0, 0, 0))
        self.is_dirty = True
        self.save()

# --- Logic Classes (adapted for GUI) ---

class ImageLoader(QThread):
    loaded = pyqtSignal(str, QPixmap) # url, pixmap

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            r = requests.get(self.url, timeout=5)
            if r.status_code == 200:
                data = r.content
                pixmap = QPixmap()
                pixmap.loadFromData(data)
                self.loaded.emit(self.url, pixmap)
        except:
            pass

class WorkerSignals(QObject):
    log = pyqtSignal(str)
    connected_matrix = pyqtSignal(bool)
    connected_twitch = pyqtSignal(bool)
    storage_update = pyqtSignal(int, int) # total, used
    playlists_update = pyqtSignal(list)
    emote_received = pyqtSignal(str, str, str) # name, type, id/url
    canvas_updated = pyqtSignal()

class MatrixController:
    def __init__(self, ip, signals):
        self.ip = ip
        self.ws_url = f"ws://{ip}/ws"
        self.upload_url = f"http://{ip}/upload"
        self.ws = None
        self.connected = False
        self.known_files = set() 
        self.signals = signals

        # Metadata for Rolling Storage
        self.emote_stats = {}  # {"/twitch/foo.gif": {"last_used": timestamp, "size": bytes}}
        self.total_storage = 0
        self.used_storage = 0
        self.is_syncing = False # Block queue during file list sync
        
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
                # Wait if syncing file list
                if self.is_syncing:
                    time.sleep(0.1)
                    continue

                emote_data = self.emote_queue.get(block=False) # Non-blocking get to allow loop check
                
                # Rolling Storage Check
                if CONFIG.get("rolling_storage_enabled", True) and self.total_storage > 0:
                    threshold = CONFIG.get("storage_threshold", 80) / 100.0
                    usage_ratio = self.used_storage / self.total_storage
                    if usage_ratio >= threshold:
                        self.signals.log.emit(f"[Rolling] Storage at {usage_ratio*100:.0f}%, cleaning up...")
                        self._cleanup_old_emotes()

                emote_type = emote_data.get('type', 'twitch')
                
                if emote_type == 'idle':
                    self._handle_idle()
                elif emote_type == 'canvas':
                    self._handle_canvas_idle()
                elif emote_type == 'custom':
                    self._handle_custom_emote(emote_data['name'], emote_data['url'])
                else:
                    self._handle_single_emote(emote_data['id'])
                
                time.sleep(2.0) 
                self.emote_queue.task_done()
            except queue.Empty:
                time.sleep(0.1)
            except Exception as e:
                self.signals.log.emit(f"[Matrix] Worker Error: {e}")

    def queue_emote(self, emote_id):
        self.emote_queue.put({'type': 'twitch', 'id': emote_id, 'time': time.time()})

    def queue_custom_emote(self, name, url):
        self.emote_queue.put({'type': 'custom', 'name': name, 'url': url, 'time': time.time()})

    def queue_idle(self):
        # Determine if we should show canvas or standard idle
        mode = 'canvas' if CONFIG.get("canvas_enabled", False) else 'idle'
        self.emote_queue.put({'type': mode, 'id': "__IDLE__", 'time': time.time()})

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

    def _handle_canvas_idle(self):
        # Just play the place.gif file. The Bot thread handles uploading it if dirty.
        self.play_file("/twitch/place.gif")

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
                self.is_syncing = True
                total = data.get('total', 0)
                used = data.get('used', 0)
                self.total_storage = total
                self.used_storage = used
                if total > 0:
                    self.signals.storage_update.emit(total, used)
                
                playlists = data.get('playlists', [])
                if playlists:
                    self.signals.playlists_update.emit(playlists)
            
            if cmd == 'list' or cmd == 'list_end' or cmd == 'list_start':
                files = data.get('files', [])
                for f in files: 
                    self.known_files.add(f)
                    # Initialize stats for existing files if missing
                    if f.startswith("/twitch/") and f not in self.emote_stats:
                        self.emote_stats[f] = {"last_used": time.time(), "size": 0}
                if cmd != 'list_start':
                    self.ready_event.set()
                
                if cmd == 'list_end':
                    self.is_syncing = False

            elif cmd == 'list_chunk':
                files = data.get('files', [])
                for f in files: 
                    self.known_files.add(f)
                    if f.startswith("/twitch/") and f not in self.emote_stats:
                        self.emote_stats[f] = {"last_used": time.time(), "size": 0}
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
            file_size = file_bytes_io.getbuffer().nbytes
            headers = {"X-Playlist": "twitch"}
            files = {'file': (filename, file_bytes_io, 'image/gif')}
            r = requests.post(self.upload_url, files=files, headers=headers, timeout=20)
            if r.status_code == 200:
                target_path = f"/twitch/{filename}"
                self.known_files.add(target_path)
                
                # Update Stats
                self.emote_stats[target_path] = {
                    "last_used": time.time(),
                    "size": file_size
                }
                self.used_storage += file_size # Optimistic update

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
            # Update last_used timestamp
            if filename in self.emote_stats:
                self.emote_stats[filename]["last_used"] = time.time()
            elif filename.startswith("/twitch/"):
                # Initialize new file without size (will be updated on list or upload)
                self.emote_stats[filename] = {"last_used": time.time(), "size": 0}

            self.ws.send(json.dumps({"cmd": "play", "file": filename}))

    def send_cmd(self, cmd, payload):
        if self.connected:
            payload["cmd"] = cmd
            self.ws.send(json.dumps(payload))

    def purge_twitch_folder(self):
        if self.connected:
            self.signals.log.emit("[System] Purging /twitch/ folder on ESP32 (silent)...")
            self.send_cmd("silent_delete_playlist", {"name": "twitch"})
            # Clear local cache of twitch files
            self.known_files = {f for f in self.known_files if not f.startswith("/twitch/") and not f.startswith("twitch/")}
            self.emote_stats.clear()
            self.signals.log.emit("[System] Cache cleared.")

    def _cleanup_old_emotes(self, space_needed=0):
        """Deletes oldest emotes until enough space is free."""
        if not CONFIG.get("rolling_storage_enabled", True):
            return True

        threshold = CONFIG.get("storage_threshold", 80) / 100.0
        target = CONFIG.get("storage_target", 50) / 100.0

        if self.total_storage == 0:
            return False

        usage_ratio = self.used_storage / self.total_storage

        # Check if cleanup is needed
        if usage_ratio < threshold and space_needed == 0:
            return True

        target_usage = self.total_storage * target
        bytes_to_free = self.used_storage - target_usage
        if space_needed > 0:
            bytes_to_free = max(bytes_to_free, space_needed)

        if bytes_to_free <= 0:
            return True

        # Sort by last_used (oldest first)
        twitch_files = [(f, s) for f, s in self.emote_stats.items()
                        if f.startswith("/twitch/") and f != "/twitch/idle.gif"]
        twitch_files.sort(key=lambda x: x[1].get("last_used", 0))

        freed = 0
        files_to_delete = []

        for filepath, stats in twitch_files:
            if freed >= bytes_to_free:
                break
            files_to_delete.append(filepath)
            freed += stats.get("size", 5000) # Fallback 5KB

        # Delete files
        for filepath in files_to_delete:
            self.signals.log.emit(f"[Rolling] Deleting: {filepath}")
            self.send_cmd("delete", {"file": filepath})
            self.known_files.discard(filepath)
            if filepath in self.emote_stats:
                self.used_storage -= self.emote_stats[filepath].get("size", 0)
                del self.emote_stats[filepath]
            time.sleep(0.05) # Yield

        self.signals.log.emit(f"[Rolling] Freed ~{freed / 1024:.1f} KB")
        return True

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
        
        # Pixel Canvas
        self.canvas = PixelCanvas()
        self.canvas_timer = None

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
        
        # Start Canvas Update Loop
        self.canvas_timer = threading.Thread(target=self._run_canvas_loop, daemon=True)
        self.canvas_timer.start()

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
        # Stop Timer
        if self.idle_timer:
            self.idle_timer.cancel()

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
    def _run_canvas_loop(self):
        while self.running:
            if CONFIG.get("canvas_enabled", False) and self.canvas.is_dirty:
                self.canvas.save() # Persist
                
                # Upload to ESP
                try:
                    # Convert to GIF bytes
                    gif_io = process_to_gif_bytes(self.canvas.image)
                    if self.matrix.upload_file("place.gif", gif_io):
                        self.canvas.is_dirty = False
                        self.signals.canvas_updated.emit() # Notify GUI
                except Exception as e:
                    self.signals.log.emit(f"[Canvas] Upload Error: {e}")
            
            time.sleep(2.0) # Check every 2 seconds

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

        # 0. Canvas Command (!px x y color)
        if CONFIG.get("canvas_enabled", False) and msg_content.startswith("!px"):
            parts = msg_content.split()
            if len(parts) >= 4:
                try:
                    x = int(parts[1])
                    y = int(parts[2])
                    color = parts[3]
                    if self.canvas.set_pixel(x, y, color):
                        # self.signals.log.emit(f"[Canvas] Pixel {x},{y} set to {color}")
                        pass
                except:
                    pass
            return # Don't process as emote if it's a command? Or allow both? 
                   # Usually commands shouldn't trigger emotes unless we want to.

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
        if BLACKLIST.get("enabled", True) and emote_id in BLACKLIST.get("twitch_ids", []):
            self.signals.log.emit(f"[Blocked] Twitch Emote: {emote_id}")
            return

        self.last_emote_time = time.time()
        self.matrix.queue_emote(emote_id)
        self._reset_timer()
        
        self.signals.emote_received.emit(emote_id, "twitch", emote_id)

    def _process_emote_url(self, name, url):
        # Handler for external URLs (FFZ)
        if BLACKLIST.get("enabled", True) and name in BLACKLIST.get("custom_names", []):
            self.signals.log.emit(f"[Blocked] Custom Emote: {name}")
            return

        self.last_emote_time = time.time()
        # Create a pseudo-ID for FFZ to use the same queue logic
        # We need to tell MatrixController that this is a custom URL, not a Twitch ID.
        # Simple hack: Pass tuple/dict instead of just ID? 
        # Or extend MatrixController.
        self.matrix.queue_custom_emote(name, url)
        self._reset_timer()

        self.signals.emote_received.emit(name, "custom", url)

    def _reset_timer(self):
        if self.idle_timer:
            self.idle_timer.cancel()
        
        # If Canvas is enabled, we IGNORE "always_show_last_emote" and ALWAYS return to canvas
        if not CONFIG.get("canvas_enabled", False):
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

class BlacklistEditorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Blacklist")
        self.resize(400, 300)

        layout = QVBoxLayout(self)

        # Tabs for Twitch IDs and Custom Names
        self.tabs = QTabWidget()

        # Tab 1: Twitch IDs
        self.twitch_list = QListWidget()
        self.twitch_list.addItems(BLACKLIST.get("twitch_ids", []))
        tab1 = QWidget()
        l1 = QVBoxLayout(tab1)
        l1.addWidget(self.twitch_list)
        btn_remove_twitch = QPushButton("Remove Selected")
        btn_remove_twitch.clicked.connect(lambda: self.remove_selected(self.twitch_list, "twitch_ids"))
        l1.addWidget(btn_remove_twitch)
        self.tabs.addTab(tab1, "Twitch IDs")

        # Tab 2: Custom Names
        self.custom_list = QListWidget()
        self.custom_list.addItems(BLACKLIST.get("custom_names", []))
        tab2 = QWidget()
        l2 = QVBoxLayout(tab2)
        l2.addWidget(self.custom_list)
        btn_remove_custom = QPushButton("Remove Selected")
        btn_remove_custom.clicked.connect(lambda: self.remove_selected(self.custom_list, "custom_names"))
        l2.addWidget(btn_remove_custom)
        self.tabs.addTab(tab2, "Custom Names")

        layout.addWidget(self.tabs)

        # Close Button
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

    def remove_selected(self, list_widget, key):
        items = list_widget.selectedItems()
        for item in items:
            value = item.text()
            if value in BLACKLIST[key]:
                BLACKLIST[key].remove(value)
            list_widget.takeItem(list_widget.row(item))
        save_blacklist(BLACKLIST)

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
        self.signals.emote_received.connect(self.add_emote_to_history)
        self.signals.canvas_updated.connect(self.update_canvas_preview)

        self.matrix = MatrixController(CONFIG["esp32_ip"], self.signals)
        self.bot = TwitchBot(CONFIG["twitch_channel"], CONFIG["twitch_oauth_token"], CONFIG["twitch_username"], self.matrix, self.signals)

        self.image_cache = {} # URL -> QPixmap
        self.active_loaders = []
        
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_storage_info)

        self.init_ui()
        self.matrix.start()
        self.update_canvas_preview() # Initial preview
        self.start_refresh_timer()
        # Auto-connect disabled per user request
        # if self.bot.token and self.bot.channel:
        #     self.bot.start()

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
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self.toggle_connection)
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

        # 2.5 Rolling Storage Settings
        gb_storage = QGroupBox("Rolling Storage")
        l_storage = QVBoxLayout()

        # Storage Bar (Moved from Matrix Control)
        self.storage_bar = QProgressBar()
        self.storage_bar.setValue(0)
        self.storage_bar.setFormat("Storage: ? / ? MB")
        l_storage.addWidget(self.storage_bar)

        # Threshold Slider (when to start cleanup)
        h_threshold = QHBoxLayout()
        h_threshold.addWidget(QLabel("Cleanup Start:"))
        self.slider_threshold = QSlider(Qt.Orientation.Horizontal)
        self.slider_threshold.setRange(50, 95)  # 50% - 95%
        self.slider_threshold.setValue(CONFIG.get("storage_threshold", 80))
        self.lbl_threshold = QLabel(f"{self.slider_threshold.value()}%")
        self.slider_threshold.valueChanged.connect(self.update_storage_labels)
        self.slider_threshold.valueChanged.connect(self.update_config_values)
        h_threshold.addWidget(self.slider_threshold)
        h_threshold.addWidget(self.lbl_threshold)
        l_storage.addLayout(h_threshold)

        # Target Slider (cleanup target level)
        h_target = QHBoxLayout()
        h_target.addWidget(QLabel("Cleanup Target:"))
        self.slider_target = QSlider(Qt.Orientation.Horizontal)
        self.slider_target.setRange(20, 70)  # 20% - 70%
        self.slider_target.setValue(CONFIG.get("storage_target", 50))
        self.lbl_target = QLabel(f"{self.slider_target.value()}%")
        self.slider_target.valueChanged.connect(self.update_storage_labels)
        self.slider_target.valueChanged.connect(self.update_config_values)
        h_target.addWidget(self.slider_target)
        h_target.addWidget(self.lbl_target)
        l_storage.addLayout(h_target)

        # Enable/Disable Checkbox
        self.cb_rolling_enabled = QCheckBox("Enable Rolling Storage")
        self.cb_rolling_enabled.setChecked(CONFIG.get("rolling_storage_enabled", True))
        self.cb_rolling_enabled.toggled.connect(self.update_config_values)
        l_storage.addWidget(self.cb_rolling_enabled)
        
        # Refresh Interval
        h_refresh = QHBoxLayout()
        h_refresh.addWidget(QLabel("Refresh Interval (sec):"))
        self.spin_refresh = QDoubleSpinBox()
        self.spin_refresh.setRange(10.0, 300.0)
        self.spin_refresh.setValue(CONFIG.get("storage_refresh_interval", 60.0))
        self.spin_refresh.valueChanged.connect(self.update_config_values)
        h_refresh.addWidget(self.spin_refresh)
        l_storage.addLayout(h_refresh)

        gb_storage.setLayout(l_storage)
        layout.addWidget(gb_storage)

        # 2.6 r/place Canvas
        gb_canvas = QGroupBox("r/place Canvas (!px x y color)")
        l_canvas = QVBoxLayout()
        
        # Preview Label
        self.lbl_canvas_preview = QLabel()
        self.lbl_canvas_preview.setFixedSize(128, 128)
        self.lbl_canvas_preview.setStyleSheet("border: 1px solid #444; background-color: black;")
        self.lbl_canvas_preview.setScaledContents(True)
        l_canvas.addWidget(self.lbl_canvas_preview, 0, Qt.AlignmentFlag.AlignCenter)

        self.cb_canvas_enabled = QCheckBox("Enable Pixel Game (Replaces Idle Image)")
        self.cb_canvas_enabled.setChecked(CONFIG.get("canvas_enabled", False))
        self.cb_canvas_enabled.toggled.connect(self.update_config_values)
        l_canvas.addWidget(self.cb_canvas_enabled)
        
        h_canv_btn = QHBoxLayout()
        self.btn_reset_canvas = QPushButton("Reset Canvas")
        self.btn_reset_canvas.clicked.connect(self.reset_canvas)
        h_canv_btn.addWidget(self.btn_reset_canvas)
        
        self.btn_upload_canvas = QPushButton("Force Upload")
        self.btn_upload_canvas.clicked.connect(self.force_upload_canvas)
        h_canv_btn.addWidget(self.btn_upload_canvas)
        
        l_canvas.addLayout(h_canv_btn)
        gb_canvas.setLayout(l_canvas)
        layout.addWidget(gb_canvas)

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
        l_matrix.addLayout(h_play)
        l_matrix.addWidget(self.btn_purge)
        gb_matrix.setLayout(l_matrix)
        layout.addWidget(gb_matrix)

        # 3.5 Emote History
        gb_history = QGroupBox("Recent Emotes (Right-click to Blacklist)")
        l_history = QVBoxLayout()

        self.emote_list = QListWidget()
        self.emote_list.setMaximumHeight(150)
        self.emote_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.emote_list.customContextMenuRequested.connect(self.show_emote_context_menu)
        l_history.addWidget(self.emote_list)

        # Blacklist Buttons
        h_bl = QHBoxLayout()
        self.btn_edit_blacklist = QPushButton("Edit Blacklist")
        self.btn_edit_blacklist.clicked.connect(self.open_blacklist_editor)
        self.cb_blacklist_enabled = QCheckBox("Blacklist Active")
        self.cb_blacklist_enabled.setChecked(BLACKLIST.get("enabled", True))
        self.cb_blacklist_enabled.toggled.connect(self.toggle_blacklist)
        h_bl.addWidget(self.cb_blacklist_enabled)
        h_bl.addWidget(self.btn_edit_blacklist)
        l_history.addLayout(h_bl)

        gb_history.setLayout(l_history)
        layout.addWidget(gb_history)

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

    def update_storage_labels(self):
        """Updates the slider labels with MB values based on total storage."""
        total_mb = self.matrix.total_storage / (1024 * 1024)
        
        th_val = self.slider_threshold.value()
        th_mb = total_mb * (th_val / 100.0)
        self.lbl_threshold.setText(f"{th_val}% ({th_mb:.1f} MB)")
        
        ta_val = self.slider_target.value()
        ta_mb = total_mb * (ta_val / 100.0)
        self.lbl_target.setText(f"{ta_val}% ({ta_mb:.1f} MB)")

    def update_storage(self, total, used):
        self.storage_bar.setMaximum(total)
        self.storage_bar.setValue(used)
        self.storage_bar.setFormat(f"Storage: {used/(1024*1024):.1f} / {total/(1024*1024):.1f} MB")
        
        # Update slider labels now that we know total storage
        self.update_storage_labels()

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
            self.btn_connect.setText("Disconnect")
        else:
            self.lbl_status_twitch.setText("Twitch: Disconnected")
            self.lbl_status_twitch.setStyleSheet("color: #ce3030;")
            self.btn_connect.setText("Connect")

    def toggle_connection(self):
        if self.bot.running:
            self.bot.stop()
            self.log_msg("[System] Disconnecting from Twitch...")
            # UI update happens via signal
        else:
            new_channel = self.txt_channel.text()
            CONFIG["twitch_channel"] = new_channel
            self.bot.update_credentials(new_channel, CONFIG["twitch_oauth_token"], CONFIG["twitch_username"])
            self.bot.start()
            # UI update happens via signal

    def update_config_values(self):
        CONFIG["show_duration"] = self.spin_duration.value()
        CONFIG["always_show_last_emote"] = self.cb_always_show.isChecked()
        # Rolling Storage
        CONFIG["storage_threshold"] = self.slider_threshold.value()
        CONFIG["storage_target"] = self.slider_target.value()
        CONFIG["rolling_storage_enabled"] = self.cb_rolling_enabled.isChecked()
        
        old_interval = CONFIG.get("storage_refresh_interval", 60.0)
        new_interval = self.spin_refresh.value()
        CONFIG["storage_refresh_interval"] = new_interval
        
        CONFIG["canvas_enabled"] = self.cb_canvas_enabled.isChecked()

        if old_interval != new_interval:
            self.start_refresh_timer()
            
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

    def add_emote_to_history(self, name, emote_type, identifier):
        """Adds emote to history list (max 20 entries)"""
        timestamp = time.strftime("%H:%M:%S")
        
        # Determine URL
        if emote_type == "twitch":
            url = f"https://static-cdn.jtvnw.net/emoticons/v2/{identifier}/default/dark/1.0"
        else:
            url = identifier

        item = QListWidgetItem(f"   [{timestamp}] {name}")
        
        # Check Cache
        if url in self.image_cache:
            item.setIcon(QIcon(self.image_cache[url]))
        else:
            # Placeholder or keep empty, start loader
            # Start Loader
            loader = ImageLoader(url)
            loader.loaded.connect(self.on_image_loaded)
            loader.start()
            self.active_loaders.append(loader)

        item.setData(Qt.ItemDataRole.UserRole, {"name": name, "type": emote_type, "id": identifier, "url": url})

        self.emote_list.insertItem(0, item)  # Newest on top

        # Max 20 entries
        while self.emote_list.count() > 20:
            self.emote_list.takeItem(self.emote_list.count() - 1)

    def on_image_loaded(self, url, pixmap):
        # Cache
        scaled_pix = pixmap.scaled(28, 28, Qt.AspectRatioMode.KeepAspectRatio)
        self.image_cache[url] = scaled_pix
        
        # Update List Items
        for i in range(self.emote_list.count()):
            item = self.emote_list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and data.get("url") == url:
                item.setIcon(QIcon(scaled_pix))
        
        # Cleanup loader
        sender = self.sender()
        if sender in self.active_loaders:
            self.active_loaders.remove(sender)
            # Wait for thread to actually finish before deleting
            sender.quit()
            sender.wait()
            sender.deleteLater()

    def show_emote_context_menu(self, pos):
        """Right-click menu for blacklist"""
        item = self.emote_list.itemAt(pos)
        if not item:
            return

        data = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)

        action_block = menu.addAction(f"Block '{data['name']}'")
        action_block.triggered.connect(lambda: self.add_to_blacklist(data))

        menu.exec(self.emote_list.mapToGlobal(pos))

    def add_to_blacklist(self, data):
        """Adds emote to blacklist"""
        if data["type"] == "twitch":
            if data["id"] not in BLACKLIST["twitch_ids"]:
                BLACKLIST["twitch_ids"].append(data["id"])
        else:
            if data["name"] not in BLACKLIST["custom_names"]:
                BLACKLIST["custom_names"].append(data["name"])

        if save_blacklist(BLACKLIST):
            self.log_msg(f"[Blacklist] Added: {data['name']}")
        else:
            self.log_msg("[Blacklist] Error saving!")

    def toggle_blacklist(self, enabled):
        """Activates/Deactivates Blacklist"""
        BLACKLIST["enabled"] = enabled
        save_blacklist(BLACKLIST)
        status = "enabled" if enabled else "disabled"
        self.log_msg(f"[Blacklist] {status}")

    def open_blacklist_editor(self):
        """Opens dialog to edit blacklist"""
        dialog = BlacklistEditorDialog(self)
        dialog.exec()

    def start_refresh_timer(self):
        interval = CONFIG.get("storage_refresh_interval", 60.0) * 1000
        self.refresh_timer.start(int(interval))
        self.log_msg(f"[System] Storage refresh interval: {CONFIG.get('storage_refresh_interval')}s")

    def refresh_storage_info(self):
        if self.matrix.connected:
            self.matrix.send_cmd("list", {})
            # self.log_msg("[System] Auto-refreshing storage info...") # Optional: Log it

    def update_canvas_preview(self):
        """Converts PIL canvas to QPixmap and displays it."""
        try:
            img = self.bot.canvas.image.convert("RGBA")
            data = img.tobytes("raw", "RGBA")
            qimg = QImage(data, img.size[0], img.size[1], QImage.Format.Format_RGBA8888)
            pix = QPixmap.fromImage(qimg)
            self.lbl_canvas_preview.setPixmap(pix)
        except Exception as e:
            print(f"Error updating canvas preview: {e}")

    def reset_canvas(self):
        self.bot.canvas.reset()
        self.update_canvas_preview()
        self.log_msg("[Canvas] Reset to black.")

    def force_upload_canvas(self):
        self.bot.canvas.is_dirty = True
        self.log_msg("[Canvas] Upload queued...")

    def closeEvent(self, event):
        """Cleanup threads on exit"""
        self.bot.stop()
        
        # Stop all active loaders
        for loader in self.active_loaders:
            if loader.isRunning():
                loader.quit()
                loader.wait()
        
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = TwitchGui()
    win.show()
    sys.exit(app.exec())