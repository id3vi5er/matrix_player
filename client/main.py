import sys
import json
import io
import time
import requests
import mss
import pygetwindow as gw
from PIL import Image, ImageSequence, ImageGrab, ImageOps
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QLineEdit, QPushButton, QListWidget, QLabel, QSlider, QFileDialog, 
                             QMessageBox, QGroupBox, QSpinBox, QComboBox, QFrame, QSplitter,
                             QDialog, QDialogButtonBox, QRadioButton, QCheckBox, QScrollArea, QFormLayout, QProgressBar, QColorDialog)
from PyQt6.QtGui import QPixmap, QImage, QIcon, QFont, QColor
from PyQt6.QtCore import Qt, QTimer, QUrl, QSize, QThread, pyqtSignal
from PyQt6.QtWebSockets import QWebSocket
from PyQt6.QtNetwork import QAbstractSocket, QNetworkAccessManager, QNetworkRequest, QNetworkReply

# --- Config ---
DEFAULT_IP = "192.168.178.155"

# --- Stylesheet (Modern Dark) ---
STYLESHEET = """
QMainWindow {
    background-color: #1e1e1e;
    color: #e0e0e0;
    font-family: 'Segoe UI', sans-serif;
}

QGroupBox {
    border: 1px solid #3a3a3a;
    border-radius: 6px;
    margin-top: 12px;
    background-color: #252526;
    font-weight: bold;
    color: #cccccc;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
}

QWidget {
    color: #e0e0e0;
}

QLineEdit, QSpinBox, QComboBox, QListWidget {
    background-color: #333333;
    border: 1px solid #444444;
    border-radius: 4px;
    padding: 5px;
    color: white;
    selection-background-color: #007acc;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #007acc;
}

QPushButton {
    background-color: #3a3a3a;
    border: 1px solid #444444;
    border-radius: 4px;
    padding: 6px 12px;
    color: white;
}
QPushButton:hover {
    background-color: #4a4a4a;
    border-color: #555555;
}
QPushButton:pressed {
    background-color: #2a2a2a;
}
QPushButton:disabled {
    background-color: #252526;
    color: #666666;
    border-color: #333333;
}

/* Specific Button Styles */
QPushButton#primary {
    background-color: #007acc;
    border: 1px solid #007acc;
}
QPushButton#primary:hover {
    background-color: #0062a3;
}

QPushButton#danger {
    background-color: #ce3030;
    border: 1px solid #ce3030;
}
QPushButton#danger:hover {
    background-color: #a02020;
}

QPushButton#success {
    background-color: #2ea043;
    border: 1px solid #2ea043;
}
QPushButton#success:hover {
    background-color: #238636;
}

QLabel#preview {
    background-color: black;
    border: 2px solid #444;
    border-radius: 4px;
}

QSlider::groove:horizontal {
    border: 1px solid #3a3a3a;
    height: 8px;
    background: #2b2b2b;
    margin: 2px 0;
    border-radius: 4px;
}
QSlider::handle:horizontal {
    background: #007acc;
    border: 1px solid #007acc;
    width: 18px;
    height: 18px;
    margin: -7px 0;
    border-radius: 9px;
}
"""

def process_image_to_bytes(img_src, settings, mode="upload"):
    """
    settings: dict with keys: res_mode, dither, bg_color, keep_trans, scale_mode, centering
    """
    frames = []
    durations = []
    is_animated = getattr(img_src, "is_animated", False)
    
    # Extract settings
    res_mode = settings.get('res_mode', Image.Resampling.LANCZOS)
    dither_mode = settings.get('dither', Image.Dither.NONE)
    bg_color = settings.get('bg_color', (0,0,0,255))
    keep_trans = settings.get('keep_trans', False)
    scale_mode = settings.get('scale_mode', 1) # 1=Fit
    centering = settings.get('centering', (0.5, 0.5))

    def proc_frame(frame):
        rgba = frame.convert("RGBA")
        
        # 1. Scaling Logic
        if scale_mode == 0: # Stretch
            if rgba.size != (64, 64):
                rgba = rgba.resize((64, 64), res_mode)
        elif scale_mode == 1: # Fit
            rgba.thumbnail((64, 64), res_mode)
            new_bg = Image.new("RGBA", (64, 64), (0,0,0,0))
            x = (64 - rgba.width) // 2
            y = (64 - rgba.height) // 2
            new_bg.paste(rgba, (x, y))
            rgba = new_bg
        elif scale_mode == 2: # Fill
            rgba = ImageOps.fit(rgba, (64, 64), method=res_mode, centering=centering)
        
        # 2. Background
        if not keep_trans:
            bg = Image.new("RGBA", (64, 64), bg_color)
            bg.paste(rgba, (0, 0), rgba)
            rgba = bg
        
        # 3. Output Format
        if mode == "upload":
            return rgba.convert("P", palette=Image.Palette.ADAPTIVE, dither=dither_mode)
        else:
            return rgba.convert("RGB")

    # Stream Mode: Return raw bytes immediately
    if mode == "stream" or mode == "settings_only":
        frame = ImageSequence.Iterator(img_src)[0] if is_animated else img_src
        return io.BytesIO(proc_frame(frame).tobytes())

    # Upload Mode: Collect frames and save as GIF
    if is_animated:
        for frame in ImageSequence.Iterator(img_src):
            frames.append(proc_frame(frame))
            durations.append(frame.info.get('duration', 100))
    else:
        frames.append(proc_frame(img_src))
        durations.append(200)

    out = io.BytesIO()
    frames[0].save(out, format='GIF', save_all=True, append_images=frames[1:], duration=durations, loop=0, disposal=2)
    out.seek(0)
    return out

class ImageFetcher(QThread):
    loaded = pyqtSignal(str, bytes)

    def __init__(self, url, filename):
        super().__init__()
        self.url = url
        self.filename = filename

    def run(self):
        try:
            r = requests.get(self.url, timeout=5)
            if r.status_code == 200:
                self.loaded.emit(self.filename, r.content)
        except:
            pass

class UploadDialog(QDialog):
    def __init__(self, parent=None, mode="upload"):
        super().__init__(parent)
        self.mode = mode
        
        if mode == "upload": title = "Upload Images - Converter Settings"
        elif mode == "stream": title = "Show Static Image (HD) - Settings"
        else: title = "Live Stream Settings"
        
        self.setWindowTitle(title)
        self.resize(1000, 700)
        self.setStyleSheet(parent.styleSheet() if parent else "")
        
        self.source_paths = []
        self.processed_data = None # This will now be for the currently selected/first preview
        self.original_image = None
        
        # Load test image for settings preview if in settings mode
        if self.mode == "settings_only":
             # Create dummy image or load a placeholder
             self.original_image = Image.new('RGB', (320, 240), color = 'gray')
             # Draw some patterns
             from PIL import ImageDraw
             d = ImageDraw.Draw(self.original_image)
             d.rectangle([(50,50),(270,190)], fill="blue", outline="white")
             d.text((60,60), "Preview Image", fill="white")
        
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 1. Top: File Selection & Playlist
        if self.mode != "settings_only":
            top_layout = QVBoxLayout()
            
            h_file = QHBoxLayout()
            self.lbl_path = QLabel("No files selected")
            btn_browse = QPushButton("Select Images...")
            btn_browse.setObjectName("primary")
            btn_browse.clicked.connect(self.browse_files)
            h_file.addWidget(self.lbl_path, 1)
            h_file.addWidget(btn_browse)
            top_layout.addLayout(h_file)

            if self.mode == "upload":
                h_playlist = QHBoxLayout()
                h_playlist.addWidget(QLabel("Playlist / Tag:"))
                self.playlist_input = QLineEdit("Default")
                h_playlist.addWidget(self.playlist_input)
                top_layout.addLayout(h_playlist)

            layout.addLayout(top_layout)

        # 2. Middle: Splitter (Original | Preview) + Settings
        h_mid = QHBoxLayout()
        
        # Left: Original
        v_orig = QVBoxLayout()
        v_orig.addWidget(QLabel("<b>Original (First Image)</b>"))
        self.lbl_orig = QLabel()
        self.lbl_orig.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_orig.setStyleSheet("background-color: #111; border: 1px solid #444;")
        self.lbl_orig.setFixedSize(320, 320)
        v_orig.addWidget(self.lbl_orig)
        v_orig.addStretch()
        h_mid.addLayout(v_orig)

        # Center: Settings
        gb_sett = QGroupBox("Conversion Settings")
        gb_sett.setFixedWidth(250)
        f_layout = QFormLayout()
        
        if self.mode == "upload":
            self.cb_direct = QCheckBox("Direct Upload (No Convert)")
            self.cb_direct.setToolTip("Uploads original files as-is (Only for 64x64 GIFs)")
            self.cb_direct.toggled.connect(self.update_preview)
            f_layout.addRow(self.cb_direct)
        
        self.combo_resize = QComboBox()
        self.combo_resize.addItems(["Lanczos (Smooth)", "Nearest (Pixel Art)", "Bicubic"])
        self.combo_resize.currentIndexChanged.connect(self.update_preview)
        f_layout.addRow("Resize Algo:", self.combo_resize)

        self.combo_scale = QComboBox()
        self.combo_scale.addItems(["Stretch (Distort)", "Fit (Contain)", "Fill (Crop/Cover)"])
        self.combo_scale.currentIndexChanged.connect(self.toggle_crop_controls)
        self.combo_scale.currentIndexChanged.connect(self.update_preview)
        f_layout.addRow("Scaling Mode:", self.combo_scale)

        # Crop Controls (Hidden by default)
        self.lbl_cx = QLabel("Center X:")
        self.slider_cx = QSlider(Qt.Orientation.Horizontal)
        self.slider_cx.setRange(0, 100)
        self.slider_cx.setValue(50)
        self.slider_cx.valueChanged.connect(self.update_preview)
        f_layout.addRow(self.lbl_cx, self.slider_cx)

        self.lbl_cy = QLabel("Center Y:")
        self.slider_cy = QSlider(Qt.Orientation.Horizontal)
        self.slider_cy.setRange(0, 100)
        self.slider_cy.setValue(50)
        self.slider_cy.valueChanged.connect(self.update_preview)
        f_layout.addRow(self.lbl_cy, self.slider_cy)

        if self.mode == "upload":
            self.cb_dither = QCheckBox("Enable Dithering")
            self.cb_dither.setToolTip("Useful for photos, bad for graphics")
            self.cb_dither.setChecked(False) 
            self.cb_dither.toggled.connect(self.update_preview)
            f_layout.addRow(self.cb_dither)

            self.combo_bg = QComboBox()
            self.combo_bg.addItems(["Black (Recommended)", "White", "Transparent"])
            self.combo_bg.currentIndexChanged.connect(self.update_preview)
            f_layout.addRow("Background:", self.combo_bg)
        
        gb_sett.setLayout(f_layout)
        h_mid.addWidget(gb_sett)

        # Right: Preview
        v_prev = QVBoxLayout()
        v_prev.addWidget(QLabel("<b>Preview (64x64)</b>"))
        self.lbl_prev = QLabel()
        self.lbl_prev.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_prev.setStyleSheet("background-color: #111; border: 1px solid #444;")
        self.lbl_prev.setFixedSize(320, 320)
        v_prev.addWidget(self.lbl_prev)
        v_prev.addStretch()
        h_mid.addLayout(v_prev)

        layout.addLayout(h_mid, 1)

        # 3. Bottom: Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.btn_ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.btn_ok.setText("Upload All" if self.mode == "upload" else ("Apply" if self.mode == "settings_only" else "Show Live"))
        self.btn_ok.setEnabled(False)
        layout.addWidget(buttons)
        
        self.toggle_crop_controls()
        
        if self.mode == "settings_only":
             self.load_image_object(self.original_image)

    def toggle_crop_controls(self):
        is_fill = (self.combo_scale.currentIndex() == 2)
        self.lbl_cx.setVisible(is_fill)
        self.slider_cx.setVisible(is_fill)
        self.lbl_cy.setVisible(is_fill)
        self.slider_cy.setVisible(is_fill)

    def load_image_object(self, img):
        self.original_image = img
        img_display = self.original_image.convert("RGBA")
        ratio = min(320 / img_display.width, 320 / img_display.height)
        new_size = (int(img_display.width * ratio), int(img_display.height * ratio))
        img_display = img_display.resize(new_size, Image.Resampling.LANCZOS)
        
        canvas = Image.new("RGBA", (320, 320), (0, 0, 0, 0))
        x = (320 - img_display.width) // 2
        y = (320 - img_display.height) // 2
        canvas.paste(img_display, (x, y))
        
        qim = QImage(canvas.tobytes(), 320, 320, 4 * 320, QImage.Format.Format_RGBA8888)
        self.lbl_orig.setPixmap(QPixmap.fromImage(qim))
        
        self.update_preview()
        self.btn_ok.setEnabled(True)

    def browse_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Select Images", "", "Images (*.png *.jpg *.jpeg *.bmp *.gif)")
        if paths:
            self.source_paths = paths
            self.load_image(paths[0])
            self.lbl_path.setText(f"{len(paths)} files selected")

    def load_image(self, path):
        # ... (Same as before, just using path parameter) ...
        self.original_image = Image.open(path)
        
        img_display = self.original_image.convert("RGBA")
        ratio = min(320 / img_display.width, 320 / img_display.height)
        new_size = (int(img_display.width * ratio), int(img_display.height * ratio))
        img_display = img_display.resize(new_size, Image.Resampling.LANCZOS)
        
        canvas = Image.new("RGBA", (320, 320), (0, 0, 0, 0))
        x = (320 - img_display.width) // 2
        y = (320 - img_display.height) // 2
        canvas.paste(img_display, (x, y))
        
        qim = QImage(canvas.tobytes(), 320, 320, 4 * 320, QImage.Format.Format_RGBA8888)
        self.lbl_orig.setPixmap(QPixmap.fromImage(qim))
        
        self.update_preview()
        self.btn_ok.setEnabled(True)

    def update_preview(self):
        if not self.source_paths and not self.original_image: return
        
        try:
            # 0. Direct Upload Mode
            if self.mode == "upload" and self.cb_direct.isChecked():
                # Show first file
                path = self.source_paths[0]
                if path.lower().endswith(".gif"):
                    with open(path, "rb") as f:
                        raw = f.read()
                    self.processed_data = io.BytesIO(raw)
                    try:
                        preview_gif = Image.open(self.processed_data)
                        frame0 = preview_gif.convert("RGBA").resize((320, 320), Image.Resampling.NEAREST)
                        qim = QImage(frame0.tobytes(), frame0.width, frame0.height, 4 * frame0.width, QImage.Format.Format_RGBA8888)
                        self.lbl_prev.setPixmap(QPixmap.fromImage(qim))
                        self.processed_data.seek(0)
                        self.btn_ok.setEnabled(True)
                    except:
                        self.lbl_prev.setText("Invalid GIF")
                        self.btn_ok.setEnabled(False)
                    return
                else:
                    self.lbl_prev.setText("Direct Upload:\nGIFs only!")
                    self.btn_ok.setEnabled(False)
                    return

            # Settings
            res_mode_idx = self.combo_resize.currentIndex()
            if res_mode_idx == 0: r_mode = Image.Resampling.LANCZOS
            elif res_mode_idx == 1: r_mode = Image.Resampling.NEAREST
            else: r_mode = Image.Resampling.BICUBIC
            
            scale_mode = self.combo_scale.currentIndex()
            cx = self.slider_cx.value() / 100.0
            cy = self.slider_cy.value() / 100.0

            if self.mode == "upload":
                dither = Image.Dither.FLOYDSTEINBERG if self.cb_dither.isChecked() else Image.Dither.NONE
                bg_idx = self.combo_bg.currentIndex()
                bg_color = (0, 0, 0, 255) if bg_idx == 0 else (255, 255, 255, 255)
                keep_trans = (bg_idx == 2)
            else:
                dither = None
                bg_color = (0, 0, 0, 255)
                keep_trans = False

            # Process First Image for Preview
            self.processed_data = self.process_to_bytes(
                self.original_image, r_mode, dither, bg_color, keep_trans, scale_mode, (cx, cy)
            )
            
            # Preview
            if self.mode == "upload":
                preview_gif = Image.open(self.processed_data)
                frame0 = preview_gif.convert("RGBA")
            else:
                self.processed_data.seek(0)
                raw = self.processed_data.read()
                frame0 = Image.frombytes("RGB", (64, 64), raw)
                self.processed_data.seek(0)

            frame0 = frame0.resize((320, 320), Image.Resampling.NEAREST)
            fmt = QImage.Format.Format_RGBA8888 if frame0.mode == "RGBA" else QImage.Format.Format_RGB888
            bytes_per_line = 4 * frame0.width if frame0.mode == "RGBA" else 3 * frame0.width
            qim = QImage(frame0.tobytes(), frame0.width, frame0.height, bytes_per_line, fmt)
            self.lbl_prev.setPixmap(QPixmap.fromImage(qim))
            
            # Success
            self.processed_data.seek(0)
            self.btn_ok.setEnabled(True)
            
        except Exception as e:
            print(f"Preview Error: {e}")

    def process_to_bytes(self, img_src, res_mode, dither_mode, bg_color, keep_trans, scale_mode, centering=(0.5, 0.5)):
        # Wrapper for global function
        settings = {
            "res_mode": res_mode,
            "dither": dither_mode,
            "bg_color": bg_color,
            "keep_trans": keep_trans,
            "scale_mode": scale_mode,
            "centering": centering
        }
        return process_image_to_bytes(img_src, settings, self.mode)

    def get_settings(self):
        """Returns the processing settings to apply to all images"""
        res_mode_idx = self.combo_resize.currentIndex()
        if res_mode_idx == 0: r_mode = Image.Resampling.LANCZOS
        elif res_mode_idx == 1: r_mode = Image.Resampling.NEAREST
        else: r_mode = Image.Resampling.BICUBIC
        
        scale_mode = self.combo_scale.currentIndex()
        cx = self.slider_cx.value() / 100.0
        cy = self.slider_cy.value() / 100.0

        dither = Image.Dither.FLOYDSTEINBERG if (hasattr(self, 'cb_dither') and self.cb_dither.isChecked()) else Image.Dither.NONE
        bg_idx = self.combo_bg.currentIndex() if hasattr(self, 'combo_bg') else 0
        bg_color = (0, 0, 0, 255) if bg_idx == 0 else (255, 255, 255, 255)
        keep_trans = (bg_idx == 2)
        
        return {
            "res_mode": r_mode,
            "scale_mode": scale_mode,
            "centering": (cx, cy),
            "dither": dither,
            "bg_color": bg_color,
            "keep_trans": keep_trans,
            "direct": self.cb_direct.isChecked() if hasattr(self, 'cb_direct') else False,
            "playlist": self.playlist_input.text() if hasattr(self, 'playlist_input') else ""
        }

    def get_result(self):
        return self.source_paths, self.get_settings()

class MatrixApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Matrix Controller Pro (64x64)")
        self.resize(1000, 750)
        self.setStyleSheet(STYLESHEET)

        # Logic Vars
        self.socket = QWebSocket()
        self.socket.textMessageReceived.connect(self.on_ws_message)
        self.socket.binaryMessageReceived.connect(self.on_ws_binary)
        self.socket.connected.connect(self.on_ws_connected)
        self.socket.disconnected.connect(self.on_ws_disconnected)
        
        self.nam = QNetworkAccessManager()
        self.nam.finished.connect(self.on_network_finished)

        self.sct = mss.mss()
        self.can_send_stream = True
        self.last_frame_time = 0
        
        self.stats_frames = 0
        self.stats_bytes = 0
        self.fps_history = []
        
        self.stream_settings = {
            "scale_mode": 1, # Fit
            "res_mode": Image.Resampling.LANCZOS,
            "bg_color": (0,0,0,255)
        }

        self.image_cache = {} # filename -> QPixmap
        self.current_remote_file = ""
        self.all_files = [] # Store raw list from server
        self.temp_file_buffer = [] # Buffer for chunked loading

        # Timers
        self.stream_timer = QTimer()
        self.stream_timer.timeout.connect(self.send_stream_frame)
        
        self.stats_timer = QTimer()
        self.stats_timer.timeout.connect(self.update_stats)
        self.stats_timer.start(1000)

        self.brightness_timer = QTimer()
        self.brightness_timer.setSingleShot(True)
        self.brightness_timer.timeout.connect(self.send_brightness)

        self.init_ui()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(15)

        # --- LEFT SIDEBAR (Connection & Files) ---
        sidebar = QWidget()
        sidebar.setFixedWidth(300)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(0, 0, 0, 0)

        # 1. Connection
        gb_conn = QGroupBox("Connection")
        l_conn = QVBoxLayout()
        self.ip_input = QLineEdit(DEFAULT_IP)
        self.ip_input.setPlaceholderText("ESP32 IP Address")
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("primary")
        self.connect_btn.clicked.connect(self.toggle_connect)
        
        l_conn.addWidget(QLabel("IP Address:"))
        l_conn.addWidget(self.ip_input)
        l_conn.addWidget(self.connect_btn)
        
        self.fw_btn = QPushButton("Update Firmware (OTA)")
        self.fw_btn.clicked.connect(self.update_firmware)
        self.fw_btn.setEnabled(False) # Enable on connect
        l_conn.addWidget(self.fw_btn)
        
        gb_conn.setLayout(l_conn)
        side_layout.addWidget(gb_conn)

        # 2. Files
        gb_files = QGroupBox("Library")
        l_files = QVBoxLayout()
        
        h_playlist_sel = QHBoxLayout()
        h_playlist_sel.addWidget(QLabel("Playlist:"))
        self.playlist_combo = QComboBox()
        self.playlist_combo.addItem("ALL")
        self.playlist_combo.currentTextChanged.connect(self.on_playlist_changed)
        h_playlist_sel.addWidget(self.playlist_combo, 1)

        self.del_playlist_btn = QPushButton("Del")
        self.del_playlist_btn.setFixedWidth(40)
        self.del_playlist_btn.setToolTip("Delete entire playlist folder")
        self.del_playlist_btn.setObjectName("danger")
        self.del_playlist_btn.clicked.connect(self.delete_current_playlist)
        h_playlist_sel.addWidget(self.del_playlist_btn)

        l_files.addLayout(h_playlist_sel)

        self.file_list = QListWidget()
        self.file_list.itemDoubleClicked.connect(self.play_selected)
        
        l_btn_files = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(lambda: self.send_cmd("list"))
        self.del_btn = QPushButton("Delete")
        self.del_btn.setObjectName("danger")
        self.del_btn.clicked.connect(self.delete_selected)
        l_btn_files.addWidget(self.refresh_btn)
        l_btn_files.addWidget(self.del_btn)

        self.upload_btn = QPushButton("Upload New Image/GIF")
        self.upload_btn.setObjectName("success")
        self.upload_btn.clicked.connect(self.upload_file)

        # Storage Usage
        self.storage_bar = QProgressBar()
        self.storage_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #444;
                border-radius: 4px;
                text-align: center;
                background-color: #333;
                color: white;
                height: 15px;
                font-size: 10px;
            }
            QProgressBar::chunk {
                background-color: #007acc;
                border-radius: 3px;
            }
        """)
        self.storage_bar.setValue(0)
        self.storage_bar.setFormat("Storage: ? / ? MB")

        l_files.addWidget(self.file_list)
        l_files.addLayout(l_btn_files)
        l_files.addWidget(self.upload_btn)
        l_files.addWidget(self.storage_bar)
        gb_files.setLayout(l_files)
        side_layout.addWidget(gb_files)

        # 3. Playback Controls
        gb_play = QGroupBox("Playback")
        l_play = QVBoxLayout()
        self.play_all_btn = QPushButton("Loop All Files")
        self.play_all_btn.clicked.connect(lambda: self.send_cmd("play", {"file": "ALL"}))
        self.stop_btn = QPushButton("Stop Playback")
        self.stop_btn.clicked.connect(lambda: self.send_cmd("stop"))
        
        l_play.addWidget(self.play_all_btn)
        l_play.addWidget(self.stop_btn)
        gb_play.setLayout(l_play)
        side_layout.addWidget(gb_play)

        side_layout.addStretch() # Push everything up
        main_layout.addWidget(sidebar)

        # --- RIGHT DASHBOARD (Previews & Settings) ---
        dashboard = QWidget()
        dash_layout = QVBoxLayout(dashboard)
        dash_layout.setContentsMargins(0, 0, 0, 0)

        # 1. Previews Area (Split for Remote / Local)
        preview_area = QHBoxLayout()
        
        # Remote Preview
        v_remote = QVBoxLayout()
        v_remote.addWidget(QLabel("<b>Now Playing (ESP32)</b>"))
        self.remote_preview_lbl = QLabel("Not Connected")
        self.remote_preview_lbl.setObjectName("preview")
        self.remote_preview_lbl.setFixedSize(256, 256) # 4x Scale
        self.remote_preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.remote_filename_lbl = QLabel("-")
        self.remote_filename_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v_remote.addWidget(self.remote_preview_lbl)
        v_remote.addWidget(self.remote_filename_lbl)
        preview_area.addLayout(v_remote)

        # Local Stream Preview
        v_local = QVBoxLayout()
        v_local.addWidget(QLabel("<b>Stream Preview (PC)</b>"))
        self.local_preview_lbl = QLabel("Stream Inactive")
        self.local_preview_lbl.setObjectName("preview")
        self.local_preview_lbl.setFixedSize(256, 256)
        self.local_preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_lbl = QLabel("- FPS | - KB/s")
        self.stats_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v_local.addWidget(self.local_preview_lbl)
        v_local.addWidget(self.stats_lbl)
        preview_area.addLayout(v_local)

        dash_layout.addLayout(preview_area)

        # 2. Settings (Grid Layout)
        gb_settings = QGroupBox("Device Settings")
        grid_sett = QGridLayout()
        grid_sett.setSpacing(10)

        # Brightness
        grid_sett.addWidget(QLabel("Brightness:"), 0, 0)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 255)
        self.slider.setValue(32)
        self.slider.valueChanged.connect(lambda: self.brightness_timer.start(50))
        grid_sett.addWidget(self.slider, 0, 1)

        # Loop Duration
        grid_sett.addWidget(QLabel("Slide Duration:"), 1, 0)
        self.dur_spin = QSpinBox()
        self.dur_spin.setRange(0, 86400) # 24 Hours
        self.dur_spin.setValue(5)
        self.dur_spin.setSuffix(" sec")
        self.dur_spin.valueChanged.connect(lambda v: self.send_cmd("duration", {"val": v * 1000}))
        grid_sett.addWidget(self.dur_spin, 1, 1)

        # Rotation
        grid_sett.addWidget(QLabel("Rotation:"), 2, 0)
        self.rot_combo = QComboBox()
        self.rot_combo.addItems(["0°", "90°", "180°", "270°"])
        self.rot_combo.currentIndexChanged.connect(lambda i: self.send_cmd("rotate", {"val": i}))
        grid_sett.addWidget(self.rot_combo, 2, 1)

        # Shuffle
        self.cb_shuffle = QCheckBox("Shuffle Playlist")
        self.cb_shuffle.toggled.connect(lambda c: self.send_cmd("shuffle", {"val": c}))
        grid_sett.addWidget(self.cb_shuffle, 3, 0, 1, 2)

        gb_settings.setLayout(grid_sett)
        dash_layout.addWidget(gb_settings)

        # 3. Stream Controls
        gb_stream = QGroupBox("Live Streaming")
        l_stream = QVBoxLayout()
        
        h_src = QHBoxLayout()
        h_src.addWidget(QLabel("Source:"))
        self.source_combo = QComboBox()
        self.source_refresh_btn = QPushButton("↻")
        self.source_refresh_btn.setFixedWidth(40)
        self.source_refresh_btn.clicked.connect(self.refresh_sources)
        h_src.addWidget(self.source_combo, 1)
        h_src.addWidget(self.source_refresh_btn)
        l_stream.addLayout(h_src)

        self.stream_btn = QPushButton("Start Live Stream")
        self.stream_btn.setCheckable(True)
        self.stream_btn.clicked.connect(self.toggle_stream)
        
        self.stream_sett_btn = QPushButton("⚙")
        self.stream_sett_btn.setFixedWidth(30)
        self.stream_sett_btn.setToolTip("Stream Settings (Crop/Scale)")
        self.stream_sett_btn.clicked.connect(self.open_stream_settings)
        
        h_stream_btn = QHBoxLayout()
        h_stream_btn.addWidget(self.stream_btn)
        h_stream_btn.addWidget(self.stream_sett_btn)
        l_stream.addLayout(h_stream_btn)

        self.static_btn = QPushButton("Show Static Image (HD)")
        self.static_btn.setToolTip("Displays an image in full color quality via streaming mode (PC must stay connected)")
        self.static_btn.clicked.connect(self.send_static_image)
        l_stream.addWidget(self.static_btn)

        gb_stream.setLayout(l_stream)
        dash_layout.addWidget(gb_stream)

        # 4. Text Message
        gb_text = QGroupBox("Text Message")
        l_text = QVBoxLayout()
        
        self.txt_input = QLineEdit()
        self.txt_input.setPlaceholderText("Enter message...")
        self.txt_input.returnPressed.connect(self.send_text)
        l_text.addWidget(self.txt_input)
        
        h_text_ctrl = QHBoxLayout()
        self.cb_scroll = QCheckBox("Scroll")
        self.cb_scroll.setChecked(True)
        
        self.btn_color = QPushButton("Color")
        self.btn_color.setFixedWidth(60)
        self.btn_color.clicked.connect(self.choose_text_color)
        self.text_color = [255, 255, 255] # Default White
        self.update_color_btn()
        
        self.btn_send_text = QPushButton("Send")
        self.btn_send_text.setObjectName("primary")
        self.btn_send_text.clicked.connect(self.send_text)
        
        h_text_ctrl.addWidget(self.cb_scroll)
        h_text_ctrl.addWidget(self.btn_color)
        h_text_ctrl.addWidget(self.btn_send_text)
        l_text.addLayout(h_text_ctrl)
        
        gb_text.setLayout(l_text)
        dash_layout.addWidget(gb_text)

        dash_layout.addStretch()
        main_layout.addWidget(dashboard)

        # Status Bar
        self.status_lbl = QLabel("Ready")
        self.status_lbl.setStyleSheet("color: #888; margin-top: 10px;")
        # We can add status bar to main window
        self.statusBar().addWidget(self.status_lbl)

        self.refresh_sources()
        self.enable_controls(False)


    # --- Logic: Networking ---

    def update_firmware(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Firmware", "", "Firmware (*.bin)")
        if not path: return
        
        reply = QMessageBox.question(self, "Update Firmware", "Flash firmware and reboot device?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes: return

        self.status_lbl.setText("Flashing Firmware... DO NOT POWER OFF")
        QApplication.processEvents()
        
        try:
            url = f"http://{self.ip_input.text()}/update"
            with open(path, "rb") as f:
                # Use a session or simple post
                r = requests.post(url, files={'file': f}, timeout=120)
            
            if r.text == "OK":
                QMessageBox.information(self, "Success", "Update complete. Device is rebooting.")
                self.on_ws_disconnected()
            else:
                QMessageBox.critical(self, "Error", f"Update failed: {r.text}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Update Error: {e}")
        
        self.status_lbl.setText("Ready")

    def toggle_connect(self):
        if self.socket.state() == QAbstractSocket.SocketState.ConnectedState:
            self.socket.close()
        else:
            url = f"ws://{self.ip_input.text()}/ws"
            self.socket.open(QUrl(url))
            self.status_lbl.setText(f"Connecting to {url}...")
            self.connect_btn.setEnabled(False)

    def on_ws_connected(self):
        self.status_lbl.setText("Connected")
        self.connect_btn.setText("Disconnect")
        self.connect_btn.setEnabled(True)
        self.connect_btn.setObjectName("danger") 
        self.connect_btn.setStyleSheet("") 
        self.fw_btn.setEnabled(True)
        self.enable_controls(True)
        self.send_cmd("list")

    def on_ws_disconnected(self):
        self.status_lbl.setText("Disconnected")
        self.connect_btn.setText("Connect")
        self.connect_btn.setEnabled(True)
        self.connect_btn.setObjectName("primary")
        self.connect_btn.setStyleSheet("")
        self.fw_btn.setEnabled(False)
        self.enable_controls(False)
        self.file_list.clear()
        self.remote_filename_lbl.setText("-")
        self.remote_preview_lbl.clear()
        self.remote_preview_lbl.setText("Disconnected")

    def on_ws_message(self, msg):
        try:
            data = json.loads(msg)
            cmd = data.get('cmd')
            
            if cmd == 'list_start':
                # Start of new list
                self.all_files = []
                self.file_list.clear()
                
                # Update Playlists
                playlists = data.get('playlists', [])
                current_p = self.playlist_combo.currentText()
                self.playlist_combo.blockSignals(True)
                self.playlist_combo.clear()
                self.playlist_combo.addItems(playlists)
                if current_p in playlists:
                    self.playlist_combo.setCurrentText(current_p)
                self.playlist_combo.blockSignals(False)

                # Update Storage Bar
                total = data.get('total', 0)
                used = data.get('used', 0)
                if total > 0:
                    self.storage_bar.setMaximum(total)
                    self.storage_bar.setValue(used)
                    self.storage_bar.setFormat(f"{used/(1024*1024):.1f} / {total/(1024*1024):.1f} MB")

            elif cmd == 'list_chunk':
                chunk = data.get('files', [])
                self.all_files.extend(chunk)
                self.add_files_to_view(chunk)

            elif cmd == 'list_end' or cmd == 'list': # Handle legacy 'list' just in case
                if cmd == 'list':
                    self.all_files = data.get('files', [])
                    self.update_file_list_view()
                
                self.status_lbl.setText(f"Loaded {len(self.all_files)} files.")
            
            elif cmd == 'reload':
                self.send_cmd("list")

            elif cmd == 'status':
                filename = data.get('file')
                self.handle_remote_preview(filename)

        except Exception as e:
            print(f"WS Text Error: {e} | Msg: {msg}")

    def on_playlist_changed(self, name):
        # Only update the local view, do NOT start playback on device automatically
        # self.send_cmd("set_playlist", {"name": name}) 
        self.update_file_list_view()

    def add_files_to_view(self, files):
        selected_playlist = self.playlist_combo.currentText()
        for f in files:
            if not f: continue
            # Normalize path check
            if selected_playlist == "ALL":
                self.file_list.addItem(f)
            else:
                # Check if file belongs to folder (e.g. "/Urlaub/img.gif")
                # We expect paths from server to start with /
                check = f if f.startswith("/") else "/" + f
                folder_sig = f"/{selected_playlist}/"
                
                if check.startswith(folder_sig):
                    self.file_list.addItem(f)

    def update_file_list_view(self):
        selected_playlist = self.playlist_combo.currentText()
        self.file_list.clear()
        
        # Update Button Text
        if selected_playlist == "ALL":
            self.play_all_btn.setText("Loop All Files")
        else:
            self.play_all_btn.setText(f"Loop '{selected_playlist}'")

        self.add_files_to_view(self.all_files)

    def on_ws_binary(self, data):
        # 0x4B is 'K'
        if len(data) == 1 and data[0] == 0x4B:
            self.can_send_stream = True

    def send_cmd(self, cmd, extra=None):
        payload = {"cmd": cmd}
        if extra: payload.update(extra)
        
        # For 'play ALL', include current playlist if not already set
        if cmd == "play" and payload.get("file") == "ALL" and "playlist" not in payload:
            payload["playlist"] = self.playlist_combo.currentText()

        if self.socket.state() == QAbstractSocket.SocketState.ConnectedState:
            self.socket.sendTextMessage(json.dumps(payload))

    def send_brightness(self):
        self.send_cmd("brightness", {"val": self.slider.value()})

    def choose_text_color(self):
        curr = QColor(self.text_color[0], self.text_color[1], self.text_color[2])
        col = QColorDialog.getColor(curr, self, "Choose Text Color")
        if col.isValid():
            self.text_color = [col.red(), col.green(), col.blue()]
            self.update_color_btn()

    def update_color_btn(self):
        r,g,b = self.text_color
        fg = "black" if (r*0.299 + g*0.587 + b*0.114) > 128 else "white"
        self.btn_color.setStyleSheet(f"background-color: rgb({r},{g},{b}); color: {fg}; border: 1px solid #555;")

    def send_text(self):
        txt = self.txt_input.text()
        if not txt: return
        
        # Stop stream if running
        if self.stream_btn.isChecked():
            self.stream_btn.setChecked(False)
            self.toggle_stream(False)

        self.send_cmd("text", {
            "text": txt,
            "scroll": self.cb_scroll.isChecked(),
            "color": self.text_color
        })
        self.status_lbl.setText(f"Sent text: {txt}")

    # --- Logic: Remote Preview ---

    def handle_remote_preview(self, filename):
        self.remote_filename_lbl.setText(filename)
        
        # Normalize filename
        if not filename.startswith("/"): filename = "/" + filename

        # Fetch (Bypassing local cache to ensure we see updates)
        base_ip = self.ip_input.text()
        # Add timestamp to bypass browser/proxy cache
        url_str = f"http://{base_ip}{filename}?t={int(time.time())}"
        
        # print(f"Fetching: {url_str}")
        self.nam.get(QNetworkRequest(QUrl(url_str)))

    def on_network_finished(self, reply):
        if reply.error() == QNetworkReply.NetworkError.NoError:
            data = reply.readAll()
            pm = QPixmap()
            if pm.loadFromData(data):
                # Extract filename from URL path for cache key
                path = reply.url().path()
                self.image_cache[path] = pm
                
                # Check if this image is still the one supposed to be displayed
                current = self.remote_filename_lbl.text()
                if not current.startswith("/"): current = "/" + current
                
                if path == current:
                    self.set_remote_pixmap(pm)
        else:
            print(f"Preview Download Error: {reply.errorString()}")
        
        reply.deleteLater()

    def set_remote_pixmap(self, pm):
        self.remote_preview_lbl.setPixmap(
            pm.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
        )

    # --- Logic: Streaming ---

    def refresh_sources(self):
        current_idx = self.source_combo.currentIndex()
        self.source_combo.clear()
        
        # Monitors
        try:
            for i, m in enumerate(self.sct.monitors[1:], 1): 
                self.source_combo.addItem(f"Monitor {i} ({m['width']}x{m['height']})", {"type": "monitor", "idx": i})
        except: pass
            
        # Windows
        try:
            windows = [w for w in gw.getAllWindows() if w.title and w.width > 0 and w.height > 0 and not w.isMinimized]
            for w in windows:
                self.source_combo.addItem(f"Win: {w.title}", {"type": "window", "title": w.title})
        except: pass
            
        if current_idx >= 0 and current_idx < self.source_combo.count():
            self.source_combo.setCurrentIndex(current_idx)

    def grab_current_source_image(self):
        try:
            source_data = self.source_combo.currentData()
            sct_img = None

            if source_data and source_data['type'] == 'monitor':
                monitor = self.sct.monitors[source_data['idx']]
                sct_img = self.sct.grab(monitor)
                
            elif source_data and source_data['type'] == 'window':
                wins = gw.getWindowsWithTitle(source_data['title'])
                if wins:
                    w = wins[0]
                    if not w.isMinimized and w.width > 0 and w.height > 0:
                        rect = {"top": w.top, "left": w.left, "width": w.width, "height": w.height}
                        sct_img = self.sct.grab(rect)
            
            if sct_img:
                return Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        except:
            pass
        return None

    def open_stream_settings(self):
        dlg = UploadDialog(self, mode="settings_only")
        
        # Try to get live image
        live_img = self.grab_current_source_image()
        if live_img:
            dlg.load_image_object(live_img)
            
        # Pre-set values (optional improvement: load current settings into dialog)
        # For now, dialog starts with defaults, which might be confusing if they differ from current.
        # Ideally we should pass self.stream_settings to dialog.
        
        if dlg.exec():
            _, settings = dlg.get_result()
            self.stream_settings = settings
            self.status_lbl.setText("Stream Settings Updated")

    def toggle_stream(self, checked):
        # Stop any static image keep-alive
        if hasattr(self, 'static_timer') and self.static_timer.isActive():
            self.static_timer.stop()

        if checked:
            self.can_send_stream = True 
            self.send_cmd("stream")
            self.stream_btn.setText("Stop Live Stream")
            self.stream_btn.setObjectName("danger")
            self.stream_btn.setStyleSheet("")
            self.stream_timer.start(5) 
            self.local_preview_lbl.setText("Starting...")
        else:
            self.stream_timer.stop()
            self.stream_btn.setText("Start Live Stream")
            self.stream_btn.setObjectName("")
            self.stream_btn.setStyleSheet("")
            self.send_cmd("stop")
            self.local_preview_lbl.clear()
            self.local_preview_lbl.setText("Stream Inactive")
            self.stats_lbl.setText("- FPS | - KB/s")

    def send_stream_frame(self):
        if self.socket.state() != QAbstractSocket.SocketState.ConnectedState:
            self.stream_btn.setChecked(False)
            self.toggle_stream(False)
            return

        # Flow Control with Timeout (Safety against dropped ACKs)
        if not self.can_send_stream:
            if time.time() - self.last_frame_time > 2.0: # 2s Timeout (Emergency Reset)
                self.can_send_stream = True
                print("Stream ACK Timeout - Resetting flow control")
            else:
                return 

        try:
            img = self.grab_current_source_image()

            if img:
                # Apply Settings
                output_io = process_image_to_bytes(img, self.stream_settings, mode="stream")
                output_io.seek(0)
                data = output_io.read()
                
                # Preview
                qimg = QImage(data, 64, 64, 64*3, QImage.Format.Format_RGB888)
                self.local_preview_lbl.setPixmap(QPixmap.fromImage(qimg).scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio))
    
                self.socket.sendBinaryMessage(data)
                self.can_send_stream = False 
                self.last_frame_time = time.time()
                
                self.stats_frames += 1
                self.stats_bytes += len(data)
            
        except Exception as e:
            print(f"Stream Error: {e}")

    def update_stats(self):
        if self.stream_btn.isChecked():
            # Rolling Average for FPS
            self.fps_history.append(self.stats_frames)
            if len(self.fps_history) > 5:
                self.fps_history.pop(0)
            
            avg_fps = sum(self.fps_history) / len(self.fps_history)
            
            kbps = self.stats_bytes / 1024.0
            
            self.stats_lbl.setText(f"{avg_fps:.1f} FPS | {kbps:.1f} KB/s")
            self.stats_bytes = 0
            self.stats_frames = 0
        else:
             self.fps_history = []

    def send_static_image(self):
        if self.socket.state() != QAbstractSocket.SocketState.ConnectedState:
            QMessageBox.warning(self, "Not Connected", "Please connect first.")
            return

        # Use UploadDialog for consistent processing UI
        dlg = UploadDialog(self, mode="stream")
        if dlg.exec():
            _, output_io = dlg.get_result()
            if not output_io: return
            
            output_io.seek(0)
            data = output_io.read()

            if self.stream_btn.isChecked():
                self.stream_btn.setChecked(False)
                self.toggle_stream(False)
            
            # Enter Stream Mode
            self.send_cmd("stream")
            
            try:
                self.current_static_data = data
                
                # Preview
                qimg = QImage(self.current_static_data, 64, 64, 64*3, QImage.Format.Format_RGB888)
                self.local_preview_lbl.setPixmap(QPixmap.fromImage(qimg).scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio))
                self.local_preview_lbl.setText("")

                # Start Keep-Alive (1 Hz)
                if not hasattr(self, 'static_timer'):
                    self.static_timer = QTimer()
                    self.static_timer.timeout.connect(self.resend_static)
                
                self.can_send_stream = True
                self.static_timer.start(1000)
                self.resend_static() # Send first frame immediately
                
                self.status_lbl.setText("Showing Static HD Image")

            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def resend_static(self):
        if self.socket.state() == QAbstractSocket.SocketState.ConnectedState and self.can_send_stream:
             self.socket.sendBinaryMessage(self.current_static_data)
             self.can_send_stream = False

    # --- Logic: File Management ---

    def play_selected(self, item):
        self.send_cmd("play", {"file": item.text()})

    def delete_current_playlist(self):
        playlist = self.playlist_combo.currentText()
        if playlist in ["ALL", "Default", ""]:
            QMessageBox.warning(self, "Protected", f"Cannot delete '{playlist}' playlist.")
            return

        reply = QMessageBox.question(
            self, "Confirm Delete", 
            f"Are you sure you want to DELETE the entire playlist '{playlist}'?\nAll files inside will be lost!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.send_cmd("delete_playlist", {"name": playlist})

    def delete_selected(self):
        item = self.file_list.currentItem()
        if item:
            self.send_cmd("delete", {"file": item.text()})

    def upload_file(self):
        dlg = UploadDialog(self)
        if dlg.exec():
            source_paths, settings = dlg.get_result()
            if not source_paths: return

            total = len(source_paths)
            for i, path in enumerate(source_paths):
                try:
                    self.status_lbl.setText(f"Uploading [{i+1}/{total}]: {path}")
                    QApplication.processEvents()
                    
                    if settings['direct'] and path.lower().endswith(".gif"):
                        with open(path, "rb") as f:
                            output_io = io.BytesIO(f.read())
                    else:
                        img = Image.open(path)
                        output_io = dlg.process_to_bytes(
                            img, settings['res_mode'], settings['dither'], 
                            settings['bg_color'], settings['keep_trans'], 
                            settings['scale_mode'], settings['centering']
                        )

                    filename = path.replace("\\", "/").split("/")[-1].split(".")[0] + ".gif"
                    
                    url = f"http://{self.ip_input.text()}/upload"
                    headers = {"X-Playlist": settings['playlist']}
                    files = {'file': (filename, output_io, 'image/gif')}
                    
                    r = requests.post(url, files=files, headers=headers, timeout=60)
                    if r.status_code != 200:
                        print(f"Failed to upload {filename}: {r.status_code}")
                
                except Exception as e:
                    print(f"Upload Error on {path}: {e}")

            self.status_lbl.setText("Upload Complete")
            self.send_cmd("list")

    def enable_controls(self, state):


        self.play_all_btn.setEnabled(state)
        self.stop_btn.setEnabled(state)
        self.refresh_btn.setEnabled(state)
        self.del_btn.setEnabled(state)
        self.upload_btn.setEnabled(state)
        self.slider.setEnabled(state)
        self.stream_btn.setEnabled(state)
        self.source_combo.setEnabled(state)
        self.source_refresh_btn.setEnabled(state)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MatrixApp()
    win.show()
    sys.exit(app.exec())
