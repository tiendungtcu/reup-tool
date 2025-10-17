import sys
import json
import os
import platform
import uuid
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, List
import subprocess
import threading
import time
from functools import lru_cache

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLineEdit, QTextEdit, QComboBox, QSpinBox, QCheckBox, QPushButton,
    QLabel, QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QGroupBox, QScrollArea, QProgressBar, QStatusBar, QMenuBar, QMenu,
    QDialog, QDialogButtonBox, QGridLayout, QFrame, QListWidget, QListWidgetItem,
    QSizePolicy, QToolButton, QButtonGroup
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSettings
from PySide6.QtGui import QIcon, QFont, QPixmap, QAction

# Import additional GUI components
try:
    from gui_channels import ChannelsTab, ChannelDialog
except ImportError:
    # Fallback if imports fail
    ChannelsTab = None
    ChannelDialog = None
@lru_cache(maxsize=1)
def get_machine_key(length: int = 16) -> str:
    """Generate a deterministic hardware-based key for the current machine."""

    identifiers: List[str] = []

    def add_identifier(value: Any) -> None:
        if value is None:
            return
        text = str(value).strip()
        if text and text not in identifiers:
            identifiers.append(text)

    try:
        add_identifier(platform.node())
        add_identifier(platform.system())
        add_identifier(platform.machine())
        add_identifier(platform.processor())
        add_identifier(platform.version())
    except Exception:
        pass

    try:
        mac_int = uuid.getnode()
        if isinstance(mac_int, int) and mac_int:
            add_identifier(f"MAC{mac_int:012X}")
    except Exception:
        pass

    if not identifiers:
        fallback = os.getenv("COMPUTERNAME") or os.getenv("HOSTNAME") or "AUTOBOT"
        identifiers.append(fallback)

    raw_fingerprint = "|".join(identifiers)
    digest = hashlib.sha256(raw_fingerprint.encode("utf-8")).hexdigest().upper()

    if length <= 0:
        return ""

    if length > len(digest):
        repetitions = (length // len(digest)) + 1
        digest = (digest * repetitions)[:length]
        return digest

    return digest[:length]


class ConfigManager:
    """Manages configuration file operations"""

    def __init__(self, config_dir: str = "configs", settings_file: str = "settings.json"):
        self.config_dir = Path(config_dir)
        self.settings_file = Path(settings_file)
        self.config_dir.mkdir(exist_ok=True)
        Path("log").mkdir(exist_ok=True)

    def load_settings(self) -> Dict[str, Any]:
        """Load global settings"""
        if self.settings_file.exists():
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading settings: {e}")
        return self._default_settings()

    def save_settings(self, settings: Dict[str, Any]) -> bool:
        """Save global settings"""
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving settings: {e}")
            return False

    def get_channels(self) -> Dict[str, Dict[str, Any]]:
        """Get all channels configuration"""
        channels: Dict[str, Dict[str, Any]] = {}
        if not self.config_dir.exists():
            return channels

        for channel_dir in self.config_dir.iterdir():
            if not channel_dir.is_dir():
                continue

            channel_id = channel_dir.name
            config_file = channel_dir / "config.json"
            cookies_file = channel_dir / "cookies.json"

            if not config_file.exists():
                continue

            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                cookies: Dict[str, Any] = {}
                if cookies_file.exists():
                    with open(cookies_file, 'r', encoding='utf-8') as f:
                        cookies = json.load(f)

                config = self._merge_channel_defaults(config)

                channels[channel_id] = {
                    'config': config,
                    'cookies': cookies
                }
            except Exception as e:
                print(f"Error loading channel {channel_id}: {e}")

        return channels

    def save_channel(self, channel_id: str, config: Dict[str, Any], cookies: Dict[str, Any]) -> bool:
        """Save channel configuration and cookies"""
        try:
            channel_dir = self.config_dir / channel_id
            channel_dir.mkdir(exist_ok=True)

            sanitized_config = self._merge_channel_defaults(config)

            config_file = channel_dir / "config.json"
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(sanitized_config, f, indent=2, ensure_ascii=False)

            cookies_file = channel_dir / "cookies.json"
            with open(cookies_file, 'w', encoding='utf-8') as f:
                json.dump(cookies, f, indent=2, ensure_ascii=False)

            return True
        except Exception as e:
            print(f"Error saving channel {channel_id}: {e}")
            return False

    def delete_channel(self, channel_id: str) -> bool:
        """Delete channel configuration"""
        try:
            channel_dir = self.config_dir / channel_id
            if channel_dir.exists():
                import shutil
                shutil.rmtree(channel_dir)
            return True
        except Exception as e:
            print(f"Error deleting channel {channel_id}: {e}")
            return False

    def _default_settings(self) -> Dict[str, Any]:
        """Default settings structure"""
        return {
            "websub_url": "",
            "ngrok_auth_token": "",
            "domain_type": "ngrok",
            "websub_port": 8080,
            "telegram": "",
            "is_human": 1
        }

    def _default_channel_config(self) -> Dict[str, Any]:
        """Default channel configuration structure"""
        return {
            "youtube_channel_id": "",
            "channel_name": "",
            "youtube_api_key": "",
            "api_scan_method": "sequence",
            "youtube_api_type": "activities",
            "telegram": "",
            "proxy": "",
            "username": "",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.82 Safari/537.36",
            "view_port": "1280x720",
            "video_format": "18",
            "render_video_method": "repeat",
            "detect_video": "websub",
            "is_new_second": 36000000,
            "scan_interval": 5,
            "is_human": 1,
            "upload_method": "api",
            "region": "ap-northeast-3",
            "pipeline_steps": self._default_pipeline_steps()
        }

    def validate_settings(self, settings: Dict[str, Any]) -> List[str]:
        """Validate settings and return list of errors"""
        errors: List[str] = []

        if settings.get("domain_type") == "ngrok" and not settings.get("ngrok_auth_token"):
            errors.append("Ngrok auth token is required when using ngrok domain type")

        if settings.get("telegram"):
            telegram = settings["telegram"]
            if "|" not in telegram:
                errors.append("Telegram format should be: chat_id|bot_token")

        websub_port = settings.get("websub_port", 8080)
        if not isinstance(websub_port, int) or websub_port < 1000 or websub_port > 65535:
            errors.append("WebSub port should be between 1000 and 65535")

        return errors

    def validate_channel_config(self, config: Dict[str, Any]) -> List[str]:
        """Validate channel configuration and return list of errors"""
        errors: List[str] = []

        if not config.get("youtube_channel_id"):
            errors.append("YouTube Channel ID is required")
        elif not config["youtube_channel_id"].startswith("UC"):
            errors.append("YouTube Channel ID should start with 'UC'")

        if not config.get("youtube_api_key"):
            errors.append("At least one YouTube API key is required")

        if config.get("proxy"):
            proxy = config["proxy"]
            parts = proxy.split(":")
            if len(parts) not in [2, 4]:
                errors.append("Proxy format should be host:port or host:port:username:password")

        if config.get("view_port"):
            viewport = config["view_port"]
            if "x" not in viewport:
                errors.append("Viewport format should be widthxheight (e.g., 1280x720)")

        sanitized_steps = self._sanitize_pipeline_steps(config.get("pipeline_steps"))
        config["pipeline_steps"] = sanitized_steps

        if not sanitized_steps["scan"] and config.get("detect_video") in {"websub", "both"}:
            errors.append("Scan step is required when using websub or both detection modes")

        if sanitized_steps["upload"] and not sanitized_steps["render"]:
            errors.append("Upload step requires render step to be enabled")

        if sanitized_steps["render"] and not sanitized_steps["download"]:
            errors.append("Render step requires download step to be enabled")

        return errors

    def _default_pipeline_steps(self) -> Dict[str, bool]:
        return {
            "scan": True,
            "download": True,
            "render": True,
            "upload": True,
        }

    def _sanitize_pipeline_steps(self, pipeline_steps: Optional[Dict[str, Any]]) -> Dict[str, bool]:
        defaults = self._default_pipeline_steps()
        if isinstance(pipeline_steps, dict):
            for key in defaults:
                if key in pipeline_steps:
                    defaults[key] = bool(pipeline_steps[key])

        if defaults["upload"]:
            defaults["render"] = True
            defaults["download"] = True

        if defaults["render"] and not defaults["download"]:
            defaults["download"] = True

        if not defaults["render"]:
            defaults["upload"] = False

        if not defaults["download"]:
            defaults["render"] = False
            defaults["upload"] = False

        return defaults

    def _merge_channel_defaults(self, config: Dict[str, Any]) -> Dict[str, Any]:
        merged = self._default_channel_config()
        user_config = dict(config or {})

        pipeline_steps = user_config.pop("pipeline_steps", None)
        merged.update(user_config)
        merged["pipeline_steps"] = self._sanitize_pipeline_steps(pipeline_steps)
        return merged


class SettingsTab(QWidget):
    """Tab for global settings configuration"""
    
    def __init__(self, config_manager: ConfigManager):
        super().__init__()
        self.config_manager = config_manager
        self.setup_ui()
        self.load_settings()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # Create scroll area for settings
        scroll = QScrollArea()
        scroll_widget = QWidget()
        scroll_layout = QFormLayout(scroll_widget)
        
        # WebSub Configuration
        websub_group = QGroupBox("WebSub Configuration")
        websub_layout = QFormLayout()
        websub_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        
        self.websub_url_edit = QLineEdit()
        self.websub_url_edit.setPlaceholderText("https://your-domain.com/websub")
        self._prepare_line_edit(self.websub_url_edit)
        websub_layout.addRow("WebSub URL:", self.websub_url_edit)
        
        self.ngrok_token_edit = QLineEdit()
        self.ngrok_token_edit.setPlaceholderText("Your ngrok auth token")
        self.ngrok_token_edit.setEchoMode(QLineEdit.Password)
        self._prepare_line_edit(self.ngrok_token_edit)
        websub_layout.addRow("Ngrok Auth Token:", self.ngrok_token_edit)
        
        self.domain_type_combo = QComboBox()
        self.domain_type_combo.addItems(["ngrok", "custom"])
        websub_layout.addRow("Domain Type:", self.domain_type_combo)
        
        self.websub_port_spin = QSpinBox()
        self.websub_port_spin.setRange(1000, 65535)
        self.websub_port_spin.setValue(8080)
        websub_layout.addRow("WebSub Port:", self.websub_port_spin)
        
        websub_group.setLayout(websub_layout)
        
        # Telegram Configuration
        telegram_group = QGroupBox("Telegram Configuration")
        telegram_layout = QFormLayout()
        telegram_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        
        self.telegram_edit = QLineEdit()
        self.telegram_edit.setPlaceholderText("chat_id|bot_token")
        self._prepare_line_edit(self.telegram_edit)
        telegram_layout.addRow("Telegram Bot:", self.telegram_edit)
        
        telegram_group.setLayout(telegram_layout)
        
        # Global Behavior
        behavior_group = QGroupBox("Global Behavior")
        behavior_layout = QFormLayout()
        behavior_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        
        self.is_human_check = QCheckBox()
        behavior_layout.addRow("Human-like Behavior:", self.is_human_check)
        
        behavior_group.setLayout(behavior_layout)
        
        # Add groups to main layout
        scroll_layout.addWidget(websub_group)
        scroll_layout.addWidget(telegram_group)
        scroll_layout.addWidget(behavior_group)
        
        scroll.setWidget(scroll_widget)
        scroll.setWidgetResizable(True)
        
        # Buttons
        button_layout = QHBoxLayout()
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.clicked.connect(self.save_settings)
        self.reset_btn = QPushButton("Reset to Default")
        self.reset_btn.clicked.connect(self.reset_settings)
        
        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.reset_btn)
        button_layout.addStretch()
        
        layout.addWidget(scroll)
        layout.addLayout(button_layout)
        self.setLayout(layout)

    def _prepare_line_edit(self, widget: QLineEdit):
        widget.setMinimumWidth(320)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    
    def load_settings(self):
        """Load settings into UI"""
        settings = self.config_manager.load_settings()
        
        self.websub_url_edit.setText(settings.get("websub_url", ""))
        self.ngrok_token_edit.setText(settings.get("ngrok_auth_token", ""))
        self.domain_type_combo.setCurrentText(settings.get("domain_type", "ngrok"))
        self.websub_port_spin.setValue(settings.get("websub_port", 8080))
        self.telegram_edit.setText(settings.get("telegram", ""))
        self.is_human_check.setChecked(bool(settings.get("is_human", 1)))
    
    def save_settings(self):
        """Save settings from UI"""
        settings = {
            "websub_url": self.websub_url_edit.text().strip(),
            "ngrok_auth_token": self.ngrok_token_edit.text().strip(),
            "domain_type": self.domain_type_combo.currentText(),
            "websub_port": self.websub_port_spin.value(),
            "telegram": self.telegram_edit.text().strip(),
            "is_human": 1 if self.is_human_check.isChecked() else 0
        }
        
        # Validate settings
        errors = self.config_manager.validate_settings(settings)
        if errors:
            QMessageBox.warning(self, "Validation Error", "\n".join(errors))
            return
        
        if self.config_manager.save_settings(settings):
            QMessageBox.information(self, "Success", "Settings saved successfully!")
        else:
            QMessageBox.critical(self, "Error", "Failed to save settings!")
    
    def reset_settings(self):
        """Reset settings to default"""
        reply = QMessageBox.question(
            self, "Reset Settings", 
            "Are you sure you want to reset all settings to default?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            default_settings = self.config_manager._default_settings()
            if self.config_manager.save_settings(default_settings):
                self.load_settings()
                QMessageBox.information(self, "Success", "Settings reset to default!")


class YTDLPWorker(QThread):
    formats_ready = Signal(list, dict)
    progress = Signal(float, str)
    completed = Signal(bool, str)
    error = Signal(str)

    def __init__(
        self,
        url: str,
        mode: str,
        format_id: Optional[str] = None,
        output_dir: Optional[str] = None,
    ):
        super().__init__()
        self.url = url
        self.mode = mode
        self.format_id = format_id
        self.output_dir = output_dir

    def run(self) -> None:
        try:
            import yt_dlp
        except ImportError as exc:
            self.error.emit(f"yt-dlp not installed: {exc}")
            self.completed.emit(False, "yt-dlp not available")
            return

        try:
            if self.mode == "fetch":
                ydl_opts = {
                    "quiet": True,
                    "skip_download": True,
                    "noplaylist": True,
                    "no_warnings": True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(self.url, download=False)
                formats = info.get("formats", [])
                self.formats_ready.emit(formats, info)
                self.completed.emit(True, info.get("title", ""))
            elif self.mode == "download":
                if not self.format_id or not self.output_dir:
                    raise ValueError("Missing format selection or output directory")

                progress_hook = lambda status: self._progress_hook(status)
                ydl_opts = {
                    "quiet": True,
                    "format": self.format_id,
                    "noplaylist": True,
                    "no_warnings": True,
                    "outtmpl": os.path.join(self.output_dir, "%(title).80s.%(ext)s"),
                    "merge_output_format": "mp4",
                    "source_address": "0.0.0.0",
                    "http_chunk_size": 2 * 1024 * 1024,
                    "socket_timeout": 30,
                    "progress_hooks": [progress_hook],
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([self.url])
                self.completed.emit(True, "Download completed")
            else:
                raise ValueError(f"Unknown worker mode: {self.mode}")
        except Exception as exc:
            self.error.emit(str(exc))
            self.completed.emit(False, str(exc))

    def _progress_hook(self, status: Dict[str, Any]) -> None:
        state = status.get("status")
        if state == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate")
            downloaded = status.get("downloaded_bytes", 0)
            percent = downloaded / total if total else 0.0
            speed = status.get("speed")
            eta = status.get("eta")
            message_parts = []
            if speed:
                message_parts.append(f"{speed/1024:.1f} KiB/s")
            if eta:
                message_parts.append(f"ETA {eta:.0f}s")
            message = " | ".join(message_parts) if message_parts else "Downloading..."
            self.progress.emit(percent, message)
        elif state == "finished":
            self.progress.emit(1.0, "Processing...")


class UtilitiesTab(QWidget):
    def __init__(self):
        super().__init__()
        self.current_url: Optional[str] = None
        self.current_formats: List[Dict[str, Any]] = []
        self.format_map: Dict[str, str] = {}
        self.active_worker: Optional[YTDLPWorker] = None
        self.active_mode: Optional[str] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setSpacing(12)

        form_layout = QFormLayout()
        form_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://www.youtube.com/watch?v=...")
        self.url_edit.setMinimumWidth(360)
        form_layout.addRow("Video URL or ID:", self.url_edit)

        fetch_layout = QHBoxLayout()
        self.fetch_btn = QPushButton("Fetch Formats")
        self.fetch_btn.clicked.connect(self.fetch_formats)
        fetch_layout.addWidget(self.fetch_btn)
        fetch_layout.addStretch()
        form_layout.addRow("", fetch_layout)

        self.video_title_label = QLabel("")
        self.video_title_label.setWordWrap(True)
        self.video_title_label.setMinimumWidth(500)
        form_layout.addRow("Video Title:", self.video_title_label)

        self.formats_combo = QComboBox()
        self.formats_combo.setEnabled(False)
        form_layout.addRow("Available Formats:", self.formats_combo)

        folder_layout = QHBoxLayout()
        self.folder_edit = QLineEdit(str(Path("downloads").resolve()))
        self.folder_edit.setMinimumWidth(320)
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self.choose_folder)
        folder_layout.addWidget(self.folder_edit)
        folder_layout.addWidget(browse_btn)
        form_layout.addRow("Save Folder:", folder_layout)

        layout.addLayout(form_layout)

        controls_layout = QHBoxLayout()
        self.download_btn = QPushButton("Download Video")
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self.download_video)
        controls_layout.addWidget(self.download_btn)
        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        layout.addStretch()
        self.setLayout(layout)

    def fetch_formats(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "Missing URL", "Please enter a YouTube video URL or ID.")
            return

        if "//" not in url:
            url = f"https://www.youtube.com/watch?v={url}"

        self._reset_state()
        self._set_working_state(True, mode="fetch")
        self.status_label.setText("Fetching available formats...")

        worker = YTDLPWorker(url=url, mode="fetch")
        worker.formats_ready.connect(self.on_formats_ready)
        worker.progress.connect(self.on_worker_progress)
        worker.completed.connect(lambda success, message: self.on_worker_completed("fetch", success, message))
        worker.error.connect(self.on_worker_error)
        worker.finished.connect(lambda: self._clear_worker_reference(worker))
        self.active_worker = worker
        self.active_mode = "fetch"
        worker.start()
        self.current_url = url

    def download_video(self) -> None:
        if not self.current_url:
            QMessageBox.warning(self, "No Video", "Please fetch video formats first.")
            return

        if not self.formats_combo.isEnabled() or self.formats_combo.currentIndex() < 0:
            QMessageBox.warning(self, "No Format", "Please select a video format to download.")
            return

        format_label = self.formats_combo.currentText()
        format_id = self.format_map.get(format_label)
        if not format_id:
            QMessageBox.warning(self, "Invalid Format", "Could not determine the selected format.")
            return

        output_dir = Path(self.folder_edit.text().strip() or ".").expanduser()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            QMessageBox.critical(self, "Folder Error", f"Failed to create output folder: {exc}")
            return

        self._set_working_state(True, mode="download")
        self.status_label.setText("Starting download...")
        self.progress_bar.setValue(0)

        worker = YTDLPWorker(
            url=self.current_url,
            mode="download",
            format_id=format_id,
            output_dir=str(output_dir),
        )
        worker.progress.connect(self.on_worker_progress)
        worker.completed.connect(lambda success, message: self.on_worker_completed("download", success, message))
        worker.error.connect(self.on_worker_error)
        worker.finished.connect(lambda: self._clear_worker_reference(worker))
        self.active_worker = worker
        self.active_mode = "download"
        worker.start()

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Download Folder", self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)

    def on_formats_ready(self, formats: List[Dict[str, Any]], info: Dict[str, Any]) -> None:
        self.current_formats = formats
        self.format_map.clear()
        self.formats_combo.clear()

        video_formats: List[Dict[str, Any]] = []
        for fmt in formats:
            vcodec = fmt.get("vcodec")
            if vcodec and vcodec != "none":
                video_formats.append(fmt)

        if not video_formats:
            self.formats_combo.setEnabled(False)
            self.download_btn.setEnabled(False)
            self.status_label.setText("No downloadable formats found.")
            return

        def sort_key(fmt: Dict[str, Any]) -> tuple:
            height = fmt.get("height") or 0
            bitrate = fmt.get("tbr") or 0
            size = fmt.get("filesize") or fmt.get("filesize_approx") or 0
            return height, bitrate, size

        sorted_formats = sorted(video_formats, key=sort_key, reverse=True)

        for fmt in sorted_formats:
            label = self._format_description(fmt)
            self.formats_combo.addItem(label)
            fmt_id = fmt.get("format_id")
            if fmt_id:
                acodec = fmt.get("acodec")
                if acodec == "none":
                    fmt_id_with_audio = f"{fmt_id}+bestaudio/best"
                else:
                    fmt_id_with_audio = fmt_id
                self.format_map[label] = fmt_id_with_audio

        self.formats_combo.setEnabled(True)
        self.download_btn.setEnabled(True)
        title = info.get("title", "")
        uploader = info.get("uploader")
        extra = f" by {uploader}" if uploader else ""
        self.video_title_label.setText(f"{title}{extra}")
        self.status_label.setText(f"Loaded {len(sorted_formats)} formats. Select one to download.")

    def on_worker_progress(self, progress: float, message: str) -> None:
        percent = max(0, min(100, int(progress * 100)))
        self.progress_bar.setValue(percent)
        if message:
            self.status_label.setText(message)

    def on_worker_completed(self, mode: str, success: bool, message: str) -> None:
        self._set_working_state(False, mode=mode)
        if success:
            if mode == "download":
                self.status_label.setText("Download completed successfully.")
                self.progress_bar.setValue(100)
        else:
            error_text = message or "Operation failed."
            self.status_label.setText(error_text)
            if mode == "download":
                QMessageBox.critical(self, "Download Failed", error_text)

    def on_worker_error(self, message: str) -> None:
        if message:
            self.status_label.setText(message)
        if self.active_mode == "fetch" and message:
            QMessageBox.critical(self, "Fetch Failed", message)

    def _set_working_state(self, working: bool, mode: str) -> None:
        if working:
            self.fetch_btn.setEnabled(False)
            self.download_btn.setEnabled(False)
            self.formats_combo.setEnabled(False)
        else:
            has_formats = bool(self.format_map)
            self.fetch_btn.setEnabled(True)
            self.formats_combo.setEnabled(has_formats)
            self.download_btn.setEnabled(has_formats)

    def _reset_state(self) -> None:
        self.current_formats = []
        self.format_map.clear()
        self.formats_combo.clear()
        self.formats_combo.setEnabled(False)
        self.download_btn.setEnabled(False)
        self.video_title_label.setText("")
        self.progress_bar.setValue(0)
        self.status_label.setText("Ready")

    def _format_description(self, fmt: Dict[str, Any]) -> str:
        fmt_id = fmt.get("format_id", "?")
        ext = fmt.get("ext", "")
        resolution = ""
        height = fmt.get("height")
        width = fmt.get("width")
        if height and width:
            resolution = f"{width}x{height}"
        elif fmt.get("resolution"):
            resolution = fmt["resolution"]

        fps = fmt.get("fps")
        if fps:
            resolution = f"{resolution} @{fps}fps" if resolution else f"{fps}fps"

        filesize = fmt.get("filesize") or fmt.get("filesize_approx")
        if filesize:
            size_mb = filesize / (1024 * 1024)
            size_text = f"{size_mb:.1f} MB"
        else:
            size_text = "Unknown size"

        vcodec = fmt.get("vcodec", "")
        acodec = fmt.get("acodec", "")
        codecs = ", ".join(filter(None, [vcodec if vcodec != "none" else "video", acodec if acodec != "none" else "audio"]))

        parts = [fmt_id]
        if ext:
            parts.append(ext)
        if resolution:
            parts.append(resolution)
        if codecs:
            parts.append(codecs)
        parts.append(size_text)
        return " | ".join(parts)

    def _clear_worker_reference(self, worker: YTDLPWorker) -> None:
        if self.active_worker is worker:
            self.active_worker = None
            self.active_mode = None

class AutoBotGUI(QMainWindow):
    """Main GUI application window"""
    
    def __init__(self):
        super().__init__()
        self.config_manager = ConfigManager()
        self.machine_key = get_machine_key()
        self.setup_ui()
        self.setup_menu()
        self.setup_status_bar()
        
    def setup_ui(self):
        """Setup the main UI"""
        self.setWindowTitle("AutoBot GUI - YouTube to TikTok Bot")
        self.setGeometry(100, 100, 1400, 900)
        
        # Central widget with tab widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)

        # Machine key banner
        key_layout = QHBoxLayout()
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.setSpacing(8)

        key_label = QLabel("Machine Key:")
        key_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self.machine_key_field = QLineEdit(self.machine_key)
        self.machine_key_field.setReadOnly(True)
        self.machine_key_field.setCursorPosition(0)
        self.machine_key_field.setFocusPolicy(Qt.NoFocus)
        self.machine_key_field.setMinimumWidth(260)

        copy_btn = QPushButton("Copy Key")
        copy_btn.clicked.connect(self.copy_machine_key)
        copy_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        key_layout.addWidget(key_label)
        key_layout.addWidget(self.machine_key_field, 1)
        key_layout.addWidget(copy_btn)

        layout.addLayout(key_layout)
        
        # Tab widget
        self.tab_widget = QTabWidget()
        
        # Add tabs
        self.settings_tab = SettingsTab(self.config_manager)
        self.tab_widget.addTab(self.settings_tab, "🔧 Settings")
        
        # Add channels tab if available
        if ChannelsTab:
            self.channels_tab = ChannelsTab(self.config_manager)
            self.tab_widget.addTab(self.channels_tab, "📺 Channels")

        self.utilities_tab = UtilitiesTab()
        self.tab_widget.addTab(self.utilities_tab, "🛠 Utilities")
        
        layout.addWidget(self.tab_widget)
    
    def setup_menu(self):
        """Setup menu bar"""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu('File')
        
        new_channel_action = QAction('New Channel', self)
        new_channel_action.triggered.connect(self.new_channel)
        file_menu.addAction(new_channel_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction('Exit', self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Tools menu
        tools_menu = menubar.addMenu('Tools')
        
        import_config_action = QAction('Import Configuration', self)
        import_config_action.triggered.connect(self.import_configuration)
        tools_menu.addAction(import_config_action)
        
        export_config_action = QAction('Export Configuration', self)
        export_config_action.triggered.connect(self.export_configuration)
        tools_menu.addAction(export_config_action)
        
        # Help menu
        help_menu = menubar.addMenu('Help')
        
        about_action = QAction('About', self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def setup_status_bar(self):
        """Setup status bar"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def copy_machine_key(self):
        """Copy the machine key to the clipboard."""
        clipboard = QApplication.clipboard()
        clipboard.setText(self.machine_key)
        if hasattr(self, "status_bar"):
            self.status_bar.showMessage("Machine key copied to clipboard", 3000)
    
    def new_channel(self):
        """Create new channel"""
        if ChannelDialog:
            dialog = ChannelDialog(self.config_manager, parent=self)
            if dialog.exec() == QDialog.Accepted:
                if hasattr(self, 'channels_tab'):
                    self.channels_tab.refresh_channels()
                self.status_bar.showMessage("New channel created successfully", 3000)
        else:
            QMessageBox.information(self, "Info", "Channel management components not available!")
    
    def import_configuration(self):
        """Import configuration from file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Configuration", "", "JSON Files (*.json);;All Files (*)"
        )
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                
                # Determine if it's settings or channel config
                if "websub_url" in config_data or "ngrok_auth_token" in config_data:
                    # It's settings
                    errors = self.config_manager.validate_settings(config_data)
                    if errors:
                        QMessageBox.warning(self, "Validation Error", 
                                          f"Configuration has errors:\n" + "\n".join(errors))
                        return
                    
                    if self.config_manager.save_settings(config_data):
                        self.settings_tab.load_settings()
                        QMessageBox.information(self, "Success", "Settings imported successfully!")
                    else:
                        QMessageBox.critical(self, "Error", "Failed to import settings!")
                
                elif "youtube_channel_id" in config_data:
                    # It's a channel config
                    errors = self.config_manager.validate_channel_config(config_data)
                    if errors:
                        QMessageBox.warning(self, "Validation Error", 
                                          f"Configuration has errors:\n" + "\n".join(errors))
                        return
                    
                    channel_id = config_data["youtube_channel_id"]
                    if self.config_manager.save_channel(channel_id, config_data, {}):
                        if hasattr(self, 'channels_tab'):
                            self.channels_tab.refresh_channels()
                        QMessageBox.information(self, "Success", f"Channel {channel_id} imported successfully!")
                    else:
                        QMessageBox.critical(self, "Error", "Failed to import channel!")
                
                else:
                    QMessageBox.warning(self, "Invalid Format", 
                                      "File doesn't appear to be a valid settings or channel configuration!")
                    
            except json.JSONDecodeError:
                QMessageBox.critical(self, "Error", "Invalid JSON file!")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to import configuration: {str(e)}")
    
    def export_configuration(self):
        """Export configuration to file"""
        # Show dialog to choose what to export
        export_dialog = QDialog(self)
        export_dialog.setWindowTitle("Export Configuration")
        export_dialog.setModal(True)
        
        layout = QVBoxLayout()
        
        # Export options
        settings_check = QCheckBox("Export Global Settings")
        settings_check.setChecked(True)
        layout.addWidget(settings_check)
        
        channels_check = QCheckBox("Export All Channels")
        channels_check.setChecked(True)
        layout.addWidget(channels_check)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(export_dialog.accept)
        buttons.rejected.connect(export_dialog.reject)
        layout.addWidget(buttons)
        
        export_dialog.setLayout(layout)
        
        if export_dialog.exec() == QDialog.Accepted:
            file_path, _ = QFileDialog.getSaveFileName(
                self, "Export Configuration", 
                f"autobot_config_{time.strftime('%Y%m%d_%H%M%S')}.json",
                "JSON Files (*.json)"
            )
            
            if file_path:
                try:
                    export_data = {}
                    
                    if settings_check.isChecked():
                        export_data["settings"] = self.config_manager.load_settings()
                    
                    if channels_check.isChecked():
                        export_data["channels"] = self.config_manager.get_channels()
                    
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(export_data, f, indent=2, ensure_ascii=False)
                    
                    QMessageBox.information(self, "Success", f"Configuration exported to {file_path}")
                    
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to export configuration: {str(e)}")
    
    def show_about(self):
        """Show about dialog"""
        QMessageBox.about(
            self, "About AutoBot GUI",
            "AutoBot GUI v1.0\n\n"
            "A graphical interface for managing YouTube to TikTok automation.\n\n"
            "Features:\n"
            "• Configure global settings\n"
            "• Manage multiple channels\n"
            "• Monitor channel automation\n\n"
            "Built with PySide6"
        )


def main():
    """Main entry point"""
    app = QApplication(sys.argv)
    
    # Set application properties
    app.setApplicationName("AutoBot GUI")
    app.setApplicationVersion("1.0")
    app.setOrganizationName("AutoBot")
    
    # Create and show main window
    window = AutoBotGUI()
    window.show()
    
    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()