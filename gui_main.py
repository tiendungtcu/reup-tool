import sys
import json
import os
import platform
import uuid
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, List, Set, Tuple
import subprocess
import threading
import time
from functools import lru_cache
from copy import deepcopy

from autobot import ALL_CONFIGS, channel_events, event_lock, is_rendered, upload_to_tiktok

from localization import translator, tr
from auto_updater import AutoUpdater, UpdateNotificationDialog

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton,
    QLabel, QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QGroupBox, QScrollArea, QProgressBar, QStatusBar, QMenuBar, QMenu,
    QDialog, QDialogButtonBox, QGridLayout, QFrame, QListWidget, QListWidgetItem,
    QSizePolicy, QToolButton, QButtonGroup, QRadioButton
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSettings
from PySide6.QtGui import QIcon, QFont, QPixmap, QAction, QActionGroup

try:
    from PIL import Image, ImageFilter
except ImportError:
    Image = None
    ImageFilter = None

import numpy as np

from moviepy.editor import (
    VideoFileClip,
    AudioFileClip,
    ImageClip,
    ColorClip,
    CompositeVideoClip,
    concatenate_videoclips,
)
import moviepy.video.fx.all as vfx
import moviepy.audio.fx.all as afx


def _patch_pillow_resampling() -> None:
    if Image is None:
        return

    resampling = getattr(Image, "Resampling", None)
    if resampling is None:
        return

    replacements = {
        "ANTIALIAS": "LANCZOS",
        "LANCZOS": "LANCZOS",
        "BICUBIC": "BICUBIC",
        "BILINEAR": "BILINEAR",
    }

    for legacy_name, modern_name in replacements.items():
        if not hasattr(Image, legacy_name) and hasattr(resampling, modern_name):
            setattr(Image, legacy_name, getattr(resampling, modern_name))


_patch_pillow_resampling()

# Import additional GUI components
try:
    from gui_channels import ChannelsTab, ChannelDialog
except ImportError:
    # Fallback if imports fail
    ChannelsTab = None
    ChannelDialog = None


class WorkerCancelled(Exception):
    """Raised when a worker thread is asked to stop early."""
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
            errors.append(tr("Ngrok auth token is required when using ngrok domain type"))

        if settings.get("telegram"):
            telegram = settings["telegram"]
            if "|" not in telegram:
                errors.append(tr("Telegram format should be: chat_id|bot_token"))

        websub_port = settings.get("websub_port", 8080)
        if not isinstance(websub_port, int) or websub_port < 1000 or websub_port > 65535:
            errors.append(tr("WebSub port should be between 1000 and 65535"))

        return errors

    def validate_channel_config(self, config: Dict[str, Any]) -> List[str]:
        """Validate channel configuration and return list of errors"""
        errors: List[str] = []

        if not config.get("youtube_channel_id"):
            errors.append(tr("YouTube Channel ID is required"))
        elif not config["youtube_channel_id"].startswith("UC"):
            errors.append(tr("YouTube Channel ID should start with 'UC'"))

        if not config.get("youtube_api_key"):
            errors.append(tr("At least one YouTube API key is required"))

        if config.get("proxy"):
            proxy = config["proxy"]
            parts = proxy.split(":")
            if len(parts) not in [2, 4]:
                errors.append(tr("Proxy format should be host:port or host:port:username:password."))

        if config.get("view_port"):
            viewport = config["view_port"]
            if "x" not in viewport:
                errors.append(tr("Viewport format should be widthxheight (e.g., 1280x720)"))

        sanitized_steps = self._sanitize_pipeline_steps(config.get("pipeline_steps"))
        config["pipeline_steps"] = sanitized_steps

        if not sanitized_steps["scan"] and config.get("detect_video") in {"websub", "both"}:
            errors.append(tr("Scan step is required when using websub or both detection modes"))

        if sanitized_steps["upload"] and not sanitized_steps["render"]:
            errors.append(tr("Upload step requires render step to be enabled"))

        if sanitized_steps["render"] and not sanitized_steps["download"]:
            errors.append(tr("Render step requires download step to be enabled"))

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
            QMessageBox.warning(self, tr("Validation Error"), "\n".join(errors))
            return
        
        if self.config_manager.save_settings(settings):
            QMessageBox.information(self, tr("Success"), tr("Settings saved successfully!"))
        else:
            QMessageBox.critical(self, tr("Error"), tr("Failed to save settings!"))
    
    def reset_settings(self):
        """Reset settings to default"""
        reply = QMessageBox.question(
            self,
            tr("Reset Settings"),
            tr("Are you sure you want to reset all settings to default?"),
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            default_settings = self.config_manager._default_settings()
            if self.config_manager.save_settings(default_settings):
                self.load_settings()
                QMessageBox.information(self, tr("Success"), tr("Settings reset to default!"))


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
        self._last_downloaded_path = None
        self._cancel_event = threading.Event()

    def run(self) -> None:
        try:
            import yt_dlp
        except ImportError as exc:
            self.error.emit(f"yt-dlp not installed: {exc}")
            self.completed.emit(False, "yt-dlp not available")
            return

        try:
            self._check_cancelled()

            if self.mode == "fetch":
                ydl_opts = {
                    "quiet": True,
                    "skip_download": True,
                    "noplaylist": True,
                    "no_warnings": True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(self.url, download=False)
                self._check_cancelled()
                formats = info.get("formats", [])
                self.formats_ready.emit(formats, info)
                self.completed.emit(True, info.get("title", ""))
            elif self.mode == "download":
                if not self.format_id or not self.output_dir:
                    raise ValueError(tr("Missing format selection or output directory"))

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
                raise ValueError(tr("Unknown worker mode: {mode}").format(mode=self.mode))
        except WorkerCancelled:
            self.completed.emit(False, "Operation cancelled")
        except Exception as exc:
            self.error.emit(str(exc))
            self.completed.emit(False, str(exc))

    def _progress_hook(self, status: Dict[str, Any]) -> None:
        self._check_cancelled()
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
            filename = (
                status.get("filename")
                or status.get("info_dict", {}).get("filepath")
                or status.get("info_dict", {}).get("_filename")
            )
            if filename:
                self._last_downloaded_path = filename
            self.progress.emit(1.0, "Processing...")

    @property
    def last_downloaded_path(self) -> Optional[str]:
        return self._last_downloaded_path

    def cancel(self) -> None:
        self._cancel_event.set()
        self.requestInterruption()

    def _check_cancelled(self) -> None:
        if self._cancel_event.is_set() or self.isInterruptionRequested():
            raise WorkerCancelled()


class VideoEditingWorker(QThread):
    progress = Signal(str)
    finished = Signal(bool, str, str)

    def __init__(self, input_path: str, output_dir: Path, options: Dict[str, Any]):
        super().__init__()
        self.input_path = Path(input_path)
        self.output_dir = Path(output_dir)
        self.options = options or {}
        self._cancel_event = threading.Event()

    def run(self) -> None:
        output_path = ""
        other_clip = None
        audio_resources: List[Any] = []
        clips_to_close: List[Any] = []
        cleanup_ids: Set[int] = set()

        def register_clip(clip_obj: Any) -> None:
            if clip_obj is None or not hasattr(clip_obj, "close"):
                return
            obj_id = id(clip_obj)
            if obj_id not in cleanup_ids:
                cleanup_ids.add(obj_id)
                clips_to_close.append(clip_obj)

        try:
            self._ensure_running()
            if not self.input_path.exists():
                raise FileNotFoundError(f"Input video not found: {self.input_path}")

            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.progress.emit(tr("Loading video..."))
            result_clip = VideoFileClip(str(self.input_path))
            register_clip(result_clip)
            self._ensure_running()

            # Add center line
            if self.options.get("add_line"):
                thickness = max(1, int(self.options.get("line_thickness", 4)))
                color = tuple(self.options.get("line_color", (255, 255, 255)))
                self.progress.emit(tr("Adding center line..."))
                self._ensure_running()
                line_clip = ColorClip(size=(result_clip.w, thickness), color=color)
                line_clip = line_clip.set_duration(result_clip.duration)
                line_clip = line_clip.set_position(("center", "center"))
                register_clip(line_clip)
                result_clip = CompositeVideoClip(
                    [result_clip, line_clip], size=result_clip.size, use_bgclip=True
                )
                register_clip(result_clip)

            # Blur
            if self.options.get("blur") and self.options.get("blur_sigma", 0) > 0:
                sigma = max(0.1, float(self.options.get("blur_sigma", 5.0)))
                self.progress.emit(tr("Applying blur..."))
                self._ensure_running()
                result_clip = self._apply_gaussian_blur(result_clip, sigma)
                register_clip(result_clip)

            # Overlay image
            if self.options.get("overlay") and self.options.get("overlay_path"):
                overlay_path = Path(str(self.options.get("overlay_path")))
                if not overlay_path.exists():
                    raise FileNotFoundError(f"Overlay image not found: {overlay_path}")
                self.progress.emit(tr("Adding overlay image..."))
                self._ensure_running()
                overlay_clip = ImageClip(str(overlay_path)).set_duration(result_clip.duration)
                register_clip(overlay_clip)
                scale_factor = min(
                    result_clip.w / overlay_clip.w if overlay_clip.w else 1.0,
                    result_clip.h / overlay_clip.h if overlay_clip.h else 1.0,
                    1.0,
                )
                if scale_factor < 1.0:
                    overlay_clip = overlay_clip.resize(scale_factor)
                    register_clip(overlay_clip)
                overlay_clip = overlay_clip.set_position(("center", "center"))
                result_clip = CompositeVideoClip(
                    [result_clip, overlay_clip], size=result_clip.size, use_bgclip=True
                )
                register_clip(result_clip)

            # Interleave with another video
            if self.options.get("interleave") and self.options.get("interleave_path"):
                interleave_path = Path(str(self.options.get("interleave_path")))
                if not interleave_path.exists():
                    raise FileNotFoundError(f"Interleave video not found: {interleave_path}")
                self.progress.emit(tr("Interleaving videos..."))
                self._ensure_running()
                other_clip = VideoFileClip(str(interleave_path))
                register_clip(other_clip)
                other_clip = other_clip.resize(result_clip.size)
                register_clip(other_clip)

                primary_duration = result_clip.duration
                secondary_duration = other_clip.duration
                segment_length = max(0.5, float(self.options.get("interleave_segment", 1.0)))
                segments: List[Any] = []
                segments_ids: Set[int] = set()

                def add_segment(segment_clip: Any) -> None:
                    if segment_clip is None:
                        return
                    seg_id = id(segment_clip)
                    if seg_id not in segments_ids:
                        segments_ids.add(seg_id)
                        segments.append(segment_clip)
                        register_clip(segment_clip)

                t_primary = 0.0
                t_secondary = 0.0
                use_primary = True

                while t_primary < primary_duration or t_secondary < secondary_duration:
                    self._ensure_running()
                    if use_primary and t_primary < primary_duration:
                        start = t_primary
                        end = min(start + segment_length, primary_duration)
                        add_segment(result_clip.subclip(start, end))
                        t_primary = end
                        use_primary = False
                    elif not use_primary and t_secondary < secondary_duration:
                        start = t_secondary
                        end = min(start + segment_length, secondary_duration)
                        add_segment(other_clip.subclip(start, end))
                        t_secondary = end
                        use_primary = True
                    else:
                        # Switch to whichever clip still has content
                        use_primary = not use_primary

                if not segments:
                    raise RuntimeError("Interleave operation produced no segments")

                result_clip = concatenate_videoclips(segments, method="compose")
                register_clip(result_clip)

            # Mute original audio
            if self.options.get("mute"):
                self.progress.emit(tr("Muting original audio..."))
                self._ensure_running()
                result_clip = result_clip.without_audio()
                register_clip(result_clip)

            # Replace audio
            if self.options.get("add_audio") and self.options.get("audio_path"):
                audio_path = Path(str(self.options.get("audio_path")))
                if not audio_path.exists():
                    raise FileNotFoundError(f"Audio file not found: {audio_path}")
                self.progress.emit(tr("Adding custom audio..."))
                self._ensure_running()
                base_audio = AudioFileClip(str(audio_path))
                audio_resources.append(base_audio)

                if base_audio.duration < result_clip.duration:
                    final_audio = afx.audio_loop(base_audio, duration=result_clip.duration)
                    audio_resources.append(final_audio)
                else:
                    final_audio = base_audio.subclip(0, result_clip.duration)
                    audio_resources.append(final_audio)

                result_clip = result_clip.set_audio(final_audio)
                register_clip(result_clip)

            # Rotate
            if self.options.get("rotate"):
                angle = float(self.options.get("rotate_degrees", 0.0))
                if angle % 360:
                    self.progress.emit(tr("Rotating video..."))
                    self._ensure_running()
                    result_clip = result_clip.rotate(angle)
                    register_clip(result_clip)

            # Zoom in
            if self.options.get("zoom_in"):
                factor = float(self.options.get("zoom_in_factor", 1.0))
                if factor > 1.0:
                    self.progress.emit(tr("Zooming in..."))
                    self._ensure_running()
                    zoomed = result_clip.fx(vfx.resize, factor)
                    register_clip(zoomed)
                    w, h = result_clip.size
                    x1 = max(0, int(round((zoomed.w - w) / 2)))
                    y1 = max(0, int(round((zoomed.h - h) / 2)))
                    x2 = x1 + w
                    y2 = y1 + h
                    zoomed = vfx.crop(zoomed, x1=x1, y1=y1, x2=x2, y2=y2)
                    register_clip(zoomed)
                    result_clip = zoomed

            # Zoom out
            if self.options.get("zoom_out"):
                factor = float(self.options.get("zoom_out_factor", 1.0))
                if 0 < factor < 1.0:
                    self.progress.emit(tr("Zooming out..."))
                    self._ensure_running()
                    scaled = result_clip.fx(vfx.resize, factor)
                    register_clip(scaled)
                    background = ColorClip(size=result_clip.size, color=(0, 0, 0))
                    background = background.set_duration(result_clip.duration)
                    register_clip(background)
                    composite = CompositeVideoClip(
                        [background, scaled.set_position(("center", "center"))],
                        size=result_clip.size,
                        use_bgclip=True,
                    )
                    if result_clip.audio:
                        composite = composite.set_audio(result_clip.audio)
                    register_clip(composite)
                    result_clip = composite

            suffix = self.input_path.suffix or ".mp4"
            base_name = f"{self.input_path.stem}_edited{suffix}"
            output_path = self.output_dir / base_name
            counter = 1
            while output_path.exists():
                output_path = self.output_dir / f"{self.input_path.stem}_edited_{counter}{suffix}"
                counter += 1

            self.progress.emit(tr("Rendering edited video..."))
            self._ensure_running()
            temp_audio = self.output_dir / f"{self.input_path.stem}_temp_audio.m4a"
            result_clip.write_videofile(
                str(output_path),
                codec="libx264",
                audio_codec="aac",
                temp_audiofile=str(temp_audio),
                remove_temp=True,
                threads=4,
                logger=None,
                verbose=False,
            )

            self.progress.emit(tr("Finished video editing"))
            self.finished.emit(True, "Video edits applied successfully.", str(output_path))
        except Exception as exc:
            self.finished.emit(False, str(exc), "")
        finally:
            for resource in audio_resources:
                try:
                    resource.close()
                except Exception:
                    pass
            if other_clip is not None:
                try:
                    other_clip.close()
                except Exception:
                    pass
            for clip_obj in reversed(clips_to_close):
                try:
                    clip_obj.close()
                except Exception:
                    pass

    def cancel(self) -> None:
        self._cancel_event.set()
        self.requestInterruption()

    def _ensure_running(self) -> None:
        if self._cancel_event.is_set() or self.isInterruptionRequested():
            raise WorkerCancelled()

    def _apply_gaussian_blur(self, clip: VideoFileClip, sigma: float) -> VideoFileClip:
        if Image is None or ImageFilter is None:
            raise RuntimeError("Pillow is required for blur effect.")

        radius = max(0.1, float(sigma))

        def blur_frame(frame: np.ndarray) -> np.ndarray:
            pil_image = Image.fromarray(frame)
            blurred = pil_image.filter(ImageFilter.GaussianBlur(radius=radius))
            return np.array(blurred)

        return clip.fl_image(blur_frame)


class TikTokUploadWorker(QThread):
    progress = Signal(str)
    completed = Signal(bool, str)

    def __init__(
        self,
        channel_id: str,
        config: Dict[str, Any],
        cookies: Any,
        video_path: str,
        video_title: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.channel_id = channel_id
        self.config = config
        self.cookies = cookies
        self.video_path = str(video_path)
        self.video_title = video_title or Path(video_path).stem
        self._cancel_event = threading.Event()

    def run(self) -> None:
        previous_config = ALL_CONFIGS.get(self.channel_id)
        previous_render = is_rendered.get(self.channel_id)
        event_created = False
        try:
            self.progress.emit(tr("Preparing TikTok upload..."))
            with event_lock:
                upload_event = channel_events.get(self.channel_id)
                if upload_event is None:
                    upload_event = threading.Event()
                    channel_events[self.channel_id] = upload_event
                    event_created = True
                upload_event.set()

            ALL_CONFIGS[self.channel_id] = {
                "config": self.config,
                "cookies": self.cookies,
            }
            is_rendered[self.channel_id] = True

            self.progress.emit(tr("Uploading video to TikTok..."))
            success = bool(
                upload_to_tiktok(
                    self.channel_id,
                    self.video_path,
                    self.video_path,
                    video_id=self.video_title,
                    video_title=self.video_title,
                )
            )
            message = "Upload completed successfully." if success else "Upload failed. Check logs for details."
            self.completed.emit(success, message)
        except Exception as exc:
            self.completed.emit(False, str(exc))
        finally:
            if previous_config is not None:
                ALL_CONFIGS[self.channel_id] = previous_config
            else:
                ALL_CONFIGS.pop(self.channel_id, None)

            if previous_render is not None:
                is_rendered[self.channel_id] = previous_render
            else:
                is_rendered.pop(self.channel_id, None)

            if event_created:
                channel_events.pop(self.channel_id, None)


class UtilitiesTab(QWidget):
    def __init__(self, config_manager: ConfigManager):
        super().__init__()
        self.config_manager = config_manager
        self.current_url: Optional[str] = None
        self.current_formats: List[Dict[str, Any]] = []
        self.format_map: Dict[str, str] = {}
        self.active_worker: Optional[YTDLPWorker] = None
        self.active_mode: Optional[str] = None
        self.edit_worker = None
        self.last_download_path = None
        self.last_output_dir = None
        self.upload_worker: Optional[QThread] = None

        # Upload UI references (initialized during UI setup)
        self.use_channel_radio: Optional[QRadioButton] = None
        self.use_custom_radio: Optional[QRadioButton] = None
        self.upload_channel_combo: Optional[QComboBox] = None
        self.refresh_channels_btn: Optional[QPushButton] = None
        self.custom_cookie_edit: Optional[QTextEdit] = None
        self.custom_proxy_edit: Optional[QLineEdit] = None
        self.load_cookie_file_btn: Optional[QPushButton] = None
        self.clear_cookie_btn: Optional[QPushButton] = None
        self.upload_method_group: Optional[QButtonGroup] = None
        self.browser_method_radio: Optional[QRadioButton] = None
        self.api_method_radio: Optional[QRadioButton] = None
        self.use_last_video_radio: Optional[QRadioButton] = None
        self.use_other_video_radio: Optional[QRadioButton] = None
        self.last_video_path_label: Optional[QLabel] = None
        self.custom_video_path_edit: Optional[QLineEdit] = None
        self.custom_video_browse_btn: Optional[QPushButton] = None
        self.upload_button: Optional[QPushButton] = None
        self.upload_status_label: Optional[QLabel] = None
        self.cookie_source_group: Optional[QButtonGroup] = None
        self.video_source_group: Optional[QButtonGroup] = None
        self.upload_channel_entries: List[Dict[str, Any]] = []
        self._syncing_custom_proxy = False
        self._setup_ui()
        self.refresh_upload_channels(initial=True)
        self._update_last_video_label()
        self._update_cookie_widgets()
        self._update_video_widgets()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout()
        main_layout.setSpacing(12)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(12)
        content_layout.setContentsMargins(0, 0, 0, 0)

        form_layout = QFormLayout()
        form_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://www.youtube.com/watch?v=...")
        self.url_edit.setMinimumWidth(360)
        form_layout.addRow("Video URL or ID:", self.url_edit)

        self.platform_combo = QComboBox()
        self.platform_combo.addItems([
            "Auto Detect (yt-dlp)",
            "YouTube",
            "TikTok",
            "Instagram",
            "Vimeo",
            "Facebook Reel",
        ])
        self.platform_combo.currentTextChanged.connect(self.on_platform_changed)
        form_layout.addRow("Platform:", self.platform_combo)

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

        content_layout.addLayout(form_layout)

        controls_layout = QHBoxLayout()
        self.download_btn = QPushButton("Download Video")
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self.download_video)
        controls_layout.addWidget(self.download_btn)
        controls_layout.addStretch()
        content_layout.addLayout(controls_layout)

        content_layout.addWidget(self._create_editing_group())
        content_layout.addWidget(self._create_upload_group())
        content_layout.addStretch()

        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        main_layout.addWidget(self.status_label)

        self.setLayout(main_layout)
        self.on_platform_changed(self.platform_combo.currentText())

    def _create_editing_group(self) -> QGroupBox:
        group = QGroupBox("Video Editing Options")
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)

        row = 0

        # Center line overlay
        self.line_checkbox = QCheckBox("Add center guide line")
        self.line_checkbox.setToolTip("Draw a horizontal line across the vertical midpoint of the video.")
        self.line_thickness_spin = QSpinBox()
        self.line_thickness_spin.setRange(1, 20)
        self.line_thickness_spin.setValue(4)
        self.line_thickness_spin.setEnabled(False)
        self.line_checkbox.toggled.connect(self.line_thickness_spin.setEnabled)

        line_controls = QWidget()
        line_layout = QHBoxLayout(line_controls)
        line_layout.setContentsMargins(0, 0, 0, 0)
        line_layout.setSpacing(6)
        line_layout.addWidget(QLabel("Thickness (px):"))
        line_layout.addWidget(self.line_thickness_spin)
        line_layout.addStretch()

        grid.addWidget(self.line_checkbox, row, 0, alignment=Qt.AlignLeft)
        grid.addWidget(line_controls, row, 1)
        row += 1

        # Blur
        self.blur_checkbox = QCheckBox("Blur video")
        self.blur_checkbox.setToolTip("Apply a Gaussian blur to soften the footage.")
        self.blur_value_spin = QDoubleSpinBox()
        self.blur_value_spin.setRange(0.5, 50.0)
        self.blur_value_spin.setSingleStep(0.5)
        self.blur_value_spin.setValue(5.0)
        self.blur_value_spin.setEnabled(False)
        self.blur_checkbox.toggled.connect(self.blur_value_spin.setEnabled)

        blur_controls = QWidget()
        blur_layout = QHBoxLayout(blur_controls)
        blur_layout.setContentsMargins(0, 0, 0, 0)
        blur_layout.setSpacing(6)
        blur_layout.addWidget(QLabel("Sigma:"))
        blur_layout.addWidget(self.blur_value_spin)
        blur_layout.addStretch()

        grid.addWidget(self.blur_checkbox, row, 0, alignment=Qt.AlignLeft)
        grid.addWidget(blur_controls, row, 1)
        row += 1

        # Overlay image
        self.overlay_checkbox = QCheckBox("Add overlay image")
        self.overlay_checkbox.setToolTip("Place a static image on top of the entire video.")
        self.overlay_path_edit = QLineEdit()
        self.overlay_path_edit.setPlaceholderText("Select image file (PNG, JPG, BMP)")
        self.overlay_path_edit.setEnabled(False)
        self.overlay_browse_btn = QPushButton("Browse")
        self.overlay_browse_btn.setEnabled(False)
        self.overlay_browse_btn.clicked.connect(self.choose_overlay_image)
        self.overlay_checkbox.toggled.connect(lambda checked: self._set_widgets_enabled([self.overlay_path_edit, self.overlay_browse_btn], checked))

        overlay_controls = QWidget()
        overlay_layout = QHBoxLayout(overlay_controls)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.setSpacing(6)
        overlay_layout.addWidget(self.overlay_path_edit)
        overlay_layout.addWidget(self.overlay_browse_btn)

        grid.addWidget(self.overlay_checkbox, row, 0, alignment=Qt.AlignLeft)
        grid.addWidget(overlay_controls, row, 1)
        row += 1

        # Interleave video
        self.interleave_checkbox = QCheckBox("Interleave with another video")
        self.interleave_checkbox.setToolTip("Alternate segments of this video with another clip.")
        self.interleave_path_edit = QLineEdit()
        self.interleave_path_edit.setPlaceholderText("Select secondary video file")
        self.interleave_path_edit.setEnabled(False)
        self.interleave_browse_btn = QPushButton("Browse")
        self.interleave_browse_btn.setEnabled(False)
        self.interleave_browse_btn.clicked.connect(self.choose_interleave_video)
        self.interleave_segment_spin = QDoubleSpinBox()
        self.interleave_segment_spin.setRange(0.5, 10.0)
        self.interleave_segment_spin.setSingleStep(0.5)
        self.interleave_segment_spin.setValue(1.0)
        self.interleave_segment_spin.setSuffix(" s")
        self.interleave_segment_spin.setEnabled(False)
        self.interleave_checkbox.toggled.connect(lambda checked: self._set_widgets_enabled([
            self.interleave_path_edit,
            self.interleave_browse_btn,
            self.interleave_segment_spin,
        ], checked))

        interleave_controls = QWidget()
        interleave_layout = QHBoxLayout(interleave_controls)
        interleave_layout.setContentsMargins(0, 0, 0, 0)
        interleave_layout.setSpacing(6)
        interleave_layout.addWidget(self.interleave_path_edit)
        interleave_layout.addWidget(self.interleave_browse_btn)
        interleave_layout.addWidget(QLabel("Segment:"))
        interleave_layout.addWidget(self.interleave_segment_spin)

        grid.addWidget(self.interleave_checkbox, row, 0, alignment=Qt.AlignLeft)
        grid.addWidget(interleave_controls, row, 1)
        row += 1

        # Mute audio
        self.mute_checkbox = QCheckBox("Mute original audio")
        self.mute_checkbox.setToolTip("Remove the original audio track from the video.")
        grid.addWidget(self.mute_checkbox, row, 0, alignment=Qt.AlignLeft)
        row += 1

        # Replace audio
        self.audio_checkbox = QCheckBox("Add custom audio track")
        self.audio_checkbox.setToolTip("Replace the audio with a specific sound file (loops if shorter).")
        self.audio_path_edit = QLineEdit()
        self.audio_path_edit.setPlaceholderText("Select audio file (MP3, WAV, AAC)")
        self.audio_path_edit.setEnabled(False)
        self.audio_browse_btn = QPushButton("Browse")
        self.audio_browse_btn.setEnabled(False)
        self.audio_browse_btn.clicked.connect(self.choose_audio_file)
        self.audio_checkbox.toggled.connect(lambda checked: self._set_widgets_enabled([self.audio_path_edit, self.audio_browse_btn], checked))

        audio_controls = QWidget()
        audio_layout = QHBoxLayout(audio_controls)
        audio_layout.setContentsMargins(0, 0, 0, 0)
        audio_layout.setSpacing(6)
        audio_layout.addWidget(self.audio_path_edit)
        audio_layout.addWidget(self.audio_browse_btn)

        grid.addWidget(self.audio_checkbox, row, 0, alignment=Qt.AlignLeft)
        grid.addWidget(audio_controls, row, 1)
        row += 1

        # Rotate
        self.rotate_checkbox = QCheckBox("Rotate video")
        self.rotate_checkbox.setToolTip("Rotate the video clockwise (positive) or counter-clockwise (negative).")
        self.rotate_spin = QDoubleSpinBox()
        self.rotate_spin.setRange(-180.0, 180.0)
        self.rotate_spin.setSingleStep(5.0)
        self.rotate_spin.setSuffix(" °")
        self.rotate_spin.setValue(0.0)
        self.rotate_spin.setEnabled(False)
        self.rotate_checkbox.toggled.connect(self.rotate_spin.setEnabled)

        rotate_controls = QWidget()
        rotate_layout = QHBoxLayout(rotate_controls)
        rotate_layout.setContentsMargins(0, 0, 0, 0)
        rotate_layout.setSpacing(6)
        rotate_layout.addWidget(QLabel("Degrees:"))
        rotate_layout.addWidget(self.rotate_spin)
        rotate_layout.addStretch()

        grid.addWidget(self.rotate_checkbox, row, 0, alignment=Qt.AlignLeft)
        grid.addWidget(rotate_controls, row, 1)
        row += 1

        # Zoom in
        self.zoom_in_checkbox = QCheckBox("Zoom in")
        self.zoom_in_checkbox.setToolTip("Zoom into the center of the frame by the specified factor.")
        self.zoom_in_spin = QDoubleSpinBox()
        self.zoom_in_spin.setRange(1.1, 4.0)
        self.zoom_in_spin.setSingleStep(0.1)
        self.zoom_in_spin.setValue(1.2)
        self.zoom_in_spin.setEnabled(False)
        self.zoom_in_checkbox.toggled.connect(self._on_zoom_in_toggled)

        zoom_in_controls = QWidget()
        zoom_in_layout = QHBoxLayout(zoom_in_controls)
        zoom_in_layout.setContentsMargins(0, 0, 0, 0)
        zoom_in_layout.setSpacing(6)
        zoom_in_layout.addWidget(QLabel("Factor:"))
        zoom_in_layout.addWidget(self.zoom_in_spin)
        zoom_in_layout.addStretch()

        grid.addWidget(self.zoom_in_checkbox, row, 0, alignment=Qt.AlignLeft)
        grid.addWidget(zoom_in_controls, row, 1)
        row += 1

        # Zoom out
        self.zoom_out_checkbox = QCheckBox("Zoom out")
        self.zoom_out_checkbox.setToolTip("Scale the video down and letterbox it inside the frame.")
        self.zoom_out_spin = QDoubleSpinBox()
        self.zoom_out_spin.setRange(0.2, 0.99)
        self.zoom_out_spin.setSingleStep(0.05)
        self.zoom_out_spin.setValue(0.8)
        self.zoom_out_spin.setEnabled(False)
        self.zoom_out_checkbox.toggled.connect(self._on_zoom_out_toggled)

        zoom_out_controls = QWidget()
        zoom_out_layout = QHBoxLayout(zoom_out_controls)
        zoom_out_layout.setContentsMargins(0, 0, 0, 0)
        zoom_out_layout.setSpacing(6)
        zoom_out_layout.addWidget(QLabel("Factor:"))
        zoom_out_layout.addWidget(self.zoom_out_spin)
        zoom_out_layout.addStretch()

        grid.addWidget(self.zoom_out_checkbox, row, 0, alignment=Qt.AlignLeft)
        grid.addWidget(zoom_out_controls, row, 1)

        group.setLayout(grid)
        return group

    def _create_upload_group(self) -> QGroupBox:
        group = QGroupBox("Upload Options")
        layout = QVBoxLayout()
        layout.setSpacing(8)

        description = QLabel(
            "Upload the downloaded or edited video to a TikTok account using saved cookies "
            "or custom cookies."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        self.cookie_source_group = QButtonGroup(self)
        self.cookie_source_group.setExclusive(True)

        self.use_channel_radio = QRadioButton("Use cookies from configured channel")
        self.use_custom_radio = QRadioButton("Use custom cookies JSON")
        self.use_channel_radio.setChecked(True)

        self.cookie_source_group.addButton(self.use_channel_radio)
        self.cookie_source_group.addButton(self.use_custom_radio)

        self.use_channel_radio.toggled.connect(self._update_cookie_widgets)
        self.use_custom_radio.toggled.connect(self._update_cookie_widgets)

        layout.addWidget(self.use_channel_radio)

        channel_row = QHBoxLayout()
        self.upload_channel_combo = QComboBox()
        self.upload_channel_combo.setPlaceholderText("Select channel with TikTok cookies")
        self.upload_channel_combo.currentIndexChanged.connect(self._on_channel_selection_changed)
        channel_row.addWidget(self.upload_channel_combo, 1)

        self.refresh_channels_btn = QPushButton("Refresh")
        self.refresh_channels_btn.clicked.connect(self.refresh_upload_channels)
        channel_row.addWidget(self.refresh_channels_btn)
        layout.addLayout(channel_row)

        layout.addWidget(self.use_custom_radio)

        custom_cookie_buttons = QHBoxLayout()
        self.load_cookie_file_btn = QPushButton("Load cookies from file")
        self.load_cookie_file_btn.clicked.connect(self.load_custom_cookies_from_file)
        custom_cookie_buttons.addWidget(self.load_cookie_file_btn)

        self.clear_cookie_btn = QPushButton("Clear")
        self.clear_cookie_btn.clicked.connect(self.clear_custom_cookies)
        custom_cookie_buttons.addWidget(self.clear_cookie_btn)
        custom_cookie_buttons.addStretch()
        layout.addLayout(custom_cookie_buttons)

        self.custom_cookie_edit = QTextEdit()
        self.custom_cookie_edit.setPlaceholderText('Paste cookies JSON (e.g., {"cookies": [...]})')
        self.custom_cookie_edit.setMinimumHeight(100)
        self.custom_cookie_edit.textChanged.connect(self._on_custom_cookies_changed)
        layout.addWidget(self.custom_cookie_edit)

        proxy_form = QFormLayout()
        proxy_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.custom_proxy_edit = QLineEdit()
        self.custom_proxy_edit.setPlaceholderText("host:port or host:port:username:password")
        self.custom_proxy_edit.setEnabled(False)
        self.custom_proxy_edit.textChanged.connect(self._on_custom_proxy_changed)
        proxy_form.addRow("Upload Proxy:", self.custom_proxy_edit)
        layout.addLayout(proxy_form)

        method_layout = QHBoxLayout()
        method_label = QLabel("Upload method:")
        method_layout.addWidget(method_label)

        self.upload_method_group = QButtonGroup(self)
        self.upload_method_group.setExclusive(True)

        self.browser_method_radio = QRadioButton("Browser")
        self.api_method_radio = QRadioButton("API")
        self.browser_method_radio.setChecked(True)

        self.upload_method_group.addButton(self.browser_method_radio)
        self.upload_method_group.addButton(self.api_method_radio)

        method_layout.addWidget(self.browser_method_radio)
        method_layout.addWidget(self.api_method_radio)
        method_layout.addStretch()
        layout.addLayout(method_layout)

        layout.addSpacing(4)
        video_label = QLabel("Select the video to upload")
        video_label.setWordWrap(True)
        layout.addWidget(video_label)

        self.video_source_group = QButtonGroup(self)
        self.video_source_group.setExclusive(True)

        self.use_last_video_radio = QRadioButton("Use last downloaded/edited video")
        self.use_last_video_radio.setChecked(True)
        self.use_last_video_radio.toggled.connect(self._update_video_widgets)
        self.video_source_group.addButton(self.use_last_video_radio)
        layout.addWidget(self.use_last_video_radio)

        self.last_video_path_label = QLabel(tr("No video available yet."))
        self.last_video_path_label.setWordWrap(True)
        layout.addWidget(self.last_video_path_label)

        self.use_other_video_radio = QRadioButton(tr("Select another video file"))
        self.use_other_video_radio.toggled.connect(self._update_video_widgets)
        self.video_source_group.addButton(self.use_other_video_radio)
        layout.addWidget(self.use_other_video_radio)

        custom_video_row = QHBoxLayout()
        self.custom_video_path_edit = QLineEdit()
        self.custom_video_path_edit.setPlaceholderText("Choose a video file to upload")
        custom_video_row.addWidget(self.custom_video_path_edit, 1)

        self.custom_video_browse_btn = QPushButton("Browse")
        self.custom_video_browse_btn.clicked.connect(self._browse_custom_video)
        custom_video_row.addWidget(self.custom_video_browse_btn)
        layout.addLayout(custom_video_row)

        controls_layout = QHBoxLayout()
        self.upload_button = QPushButton("Upload to TikTok")
        self.upload_button.setEnabled(False)
        self.upload_button.clicked.connect(self.start_upload)
        controls_layout.addWidget(self.upload_button)
        controls_layout.addStretch()
        layout.addLayout(controls_layout)

        self.upload_status_label = QLabel("")
        self.upload_status_label.setWordWrap(True)
        layout.addWidget(self.upload_status_label)

        group.setLayout(layout)
        return group

    def _update_cookie_widgets(self) -> None:
        use_channel = bool(self.use_channel_radio and self.use_channel_radio.isChecked())
        use_custom = bool(self.use_custom_radio and self.use_custom_radio.isChecked())

        if self.upload_channel_combo:
            self.upload_channel_combo.setEnabled(use_channel)
        if self.refresh_channels_btn:
            self.refresh_channels_btn.setEnabled(use_channel)

        for widget in (self.custom_cookie_edit, self.load_cookie_file_btn, self.clear_cookie_btn, self.custom_proxy_edit):
            if widget:
                widget.setEnabled(use_custom)

        self._update_upload_button_state()

    def _update_video_widgets(self) -> None:
        use_custom = bool(self.use_other_video_radio and self.use_other_video_radio.isChecked())

        for widget in (self.custom_video_path_edit, self.custom_video_browse_btn):
            if widget:
                widget.setEnabled(use_custom)

        self._update_last_video_label()
        self._update_upload_button_state()

    def _on_channel_selection_changed(self, index: int) -> None:
        entry = self._selected_channel_entry()
        if self.upload_status_label and self.use_channel_radio and self.use_channel_radio.isChecked():
            if not entry:
                self.upload_status_label.setText("")
            elif not entry.get("has_cookies"):
                self.upload_status_label.setText("Selected channel has no cookies configured.")
            else:
                self.upload_status_label.setText("")

        if entry and self.use_channel_radio and self.use_channel_radio.isChecked():
            config = entry.get("config") or {}
            self._set_upload_method_radio(config.get("upload_method"))

        self._update_upload_button_state()

    def _selected_channel_entry(self) -> Optional[Dict[str, Any]]:
        if not self.upload_channel_combo:
            return None

        data = self.upload_channel_combo.itemData(self.upload_channel_combo.currentIndex())
        return data if isinstance(data, dict) else None

    def refresh_upload_channels(self, initial: bool = False) -> None:
        if not self.upload_channel_combo:
            return

        try:
            channels = self.config_manager.get_channels()
        except Exception as exc:
            if not initial:
                QMessageBox.critical(self, tr("Failed to load channels"), str(exc))
            return

        entries: List[Dict[str, Any]] = []
        for channel_id, data in sorted(channels.items(), key=lambda item: item[0]):
            config = data.get("config", {})
            cookies = data.get("cookies")
            has_cookies = bool(cookies)
            name = config.get("channel_name") or channel_id
            label = name if name else channel_id
            if name and name != channel_id:
                label = f"{name} ({channel_id})"
            if not has_cookies:
                label = f"{label} – missing cookies"
            entries.append({
                "id": channel_id,
                "label": label,
                "has_cookies": has_cookies,
                "config": config,
                "cookies": cookies,
            })

        self.upload_channel_entries = entries

        combo = self.upload_channel_combo
        current_entry = self._selected_channel_entry()
        current_id = current_entry.get("id") if current_entry else None

        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Select channel", None)

        restore_index = 0
        for idx, entry in enumerate(entries, start=1):
            combo.addItem(entry["label"], entry)
            if entry["id"] == current_id:
                restore_index = idx

        combo.setCurrentIndex(restore_index)
        combo.blockSignals(False)

        if not entries and not initial and self.upload_status_label:
            self.upload_status_label.setText(
                "No channels available. Configure TikTok cookies in the Channels tab or use custom cookies."
            )

        self._on_channel_selection_changed(combo.currentIndex())
        self._update_cookie_widgets()

    def load_custom_cookies_from_file(self) -> None:
        if not self.custom_cookie_edit:
            return

        start_dir = str(Path(self.folder_edit.text()).expanduser()) if hasattr(self, "folder_edit") else ""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select cookies JSON file",
            start_dir,
            "JSON Files (*.json);;All Files (*)",
        )
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                content = fh.read()
            self.custom_cookie_edit.setPlainText(content)
            if self.use_custom_radio and not self.use_custom_radio.isChecked():
                self.use_custom_radio.setChecked(True)
        except Exception as exc:
            QMessageBox.critical(
                self,
                tr("Load Cookies Failed"),
                tr("Could not load cookies:\n{error}").format(error=exc),
            )

    def clear_custom_cookies(self) -> None:
        if self.custom_cookie_edit:
            self.custom_cookie_edit.clear()
        if self.custom_proxy_edit:
            self._set_custom_proxy_text("")
        self._set_upload_method_radio("browser")
        self._update_upload_button_state()

    def _on_custom_cookies_changed(self) -> None:
        self._update_upload_button_state()
        self._sync_proxy_from_cookie_text()

    def _on_custom_proxy_changed(self, _text: str) -> None:
        if self._syncing_custom_proxy:
            return

    def _sync_proxy_from_cookie_text(self) -> None:
        if not self.custom_cookie_edit or not self.custom_proxy_edit:
            return
        if self._syncing_custom_proxy:
            return
        raw_text = self.custom_cookie_edit.toPlainText().strip()
        if not raw_text:
            self._set_custom_proxy_text("")
            return
        try:
            data = json.loads(raw_text)
        except Exception:
            return
        if isinstance(data, dict):
            proxy_value = str(data.get("proxy", "") or "").strip()
            self._set_custom_proxy_text(proxy_value)
            method_value = str(data.get("upload_method", "") or "").strip().lower()
            if method_value in {"browser", "api"}:
                self._set_upload_method_radio(method_value)

    def _set_custom_proxy_text(self, value: str) -> None:
        if not self.custom_proxy_edit:
            return
        sanitized = (value or "").strip()
        if self.custom_proxy_edit.text() == sanitized:
            return
        self._syncing_custom_proxy = True
        try:
            self.custom_proxy_edit.setText(sanitized)
        finally:
            self._syncing_custom_proxy = False

    def _current_custom_proxy(self) -> str:
        if not self.custom_proxy_edit:
            return ""
        return self.custom_proxy_edit.text().strip()

    def _set_upload_method_radio(self, method: Optional[str]) -> None:
        if not self.browser_method_radio or not self.api_method_radio:
            return
        normalized = (method or "").strip().lower()
        if normalized == "api":
            self.api_method_radio.setChecked(True)
        else:
            self.browser_method_radio.setChecked(True)

    def _selected_upload_method(self) -> str:
        if self.api_method_radio and self.api_method_radio.isChecked():
            return "api"
        return "browser"

    @staticmethod
    def _is_valid_proxy_format(proxy: str) -> bool:
        if not proxy:
            return True
        parts = [part.strip() for part in proxy.split(":")]
        if len(parts) not in (2, 4):
            return False
        host, port = parts[0], parts[1]
        if not host or not port.isdigit():
            return False
        port_value = int(port)
        if port_value < 1 or port_value > 65535:
            return False
        if len(parts) == 4:
            username, password = parts[2], parts[3]
            if not username or not password:
                return False
        return True

    def _browse_custom_video(self) -> None:
        start_dir = (
            str((self.last_output_dir or Path(self.folder_edit.text()).expanduser()))
            if hasattr(self, "folder_edit")
            else ""
        )
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select video file",
            start_dir,
            "Video Files (*.mp4 *.mov *.mkv *.webm *.m4v *.avi);;All Files (*)",
        )
        if not file_path:
            return

        if self.custom_video_path_edit:
            self.custom_video_path_edit.setText(file_path)
        if self.use_other_video_radio and not self.use_other_video_radio.isChecked():
            self.use_other_video_radio.setChecked(True)

        self._update_upload_button_state()

    def _update_last_video_label(self) -> None:
        if not self.last_video_path_label:
            return

        if self.last_download_path and Path(self.last_download_path).exists():
            display_name = Path(self.last_download_path).name
            self.last_video_path_label.setText(f"Last video ready: {display_name}")
        elif self.last_download_path:
            display_name = Path(self.last_download_path).name
            self.last_video_path_label.setText(f"Last video missing: {display_name}")
        else:
            self.last_video_path_label.setText("No video available yet.")

        self._update_upload_button_state()

    def _current_upload_video_path(self) -> Optional[str]:
        if self.use_last_video_radio and self.use_last_video_radio.isChecked():
            return self.last_download_path
        if self.use_other_video_radio and self.use_other_video_radio.isChecked():
            if self.custom_video_path_edit:
                path = self.custom_video_path_edit.text().strip()
                return path or None
        return None

    def _has_selected_video(self) -> bool:
        video_path = self._current_upload_video_path()
        return bool(video_path and Path(video_path).exists())

    def _has_cookie_source(self) -> bool:
        if self.use_channel_radio and self.use_channel_radio.isChecked():
            entry = self._selected_channel_entry()
            return bool(entry and entry.get("has_cookies"))
        if self.use_custom_radio and self.use_custom_radio.isChecked():
            return bool(self.custom_cookie_edit and self.custom_cookie_edit.toPlainText().strip())
        return False

    def _update_upload_button_state(self) -> None:
        if not self.upload_button:
            return

        ready = self._has_cookie_source() and self._has_selected_video()
        if self.upload_worker and self.upload_worker.isRunning():
            ready = False

        self.upload_button.setEnabled(ready)

    def _parse_custom_cookies(self) -> Any:
        if not self.custom_cookie_edit:
            raise ValueError(tr("Custom cookies editor unavailable."))

        raw_text = self.custom_cookie_edit.toPlainText().strip()
        if not raw_text:
            raise ValueError(tr("Paste custom cookies JSON or load from file before uploading."))

        proxy_value = self._current_custom_proxy()
        if proxy_value and not self._is_valid_proxy_format(proxy_value):
            raise ValueError(tr("Proxy format should be host:port or host:port:username:password."))

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(tr("Invalid cookies JSON: {error}").format(error=exc))

        if isinstance(data, (list, tuple)) and not data:
            raise ValueError(tr("Custom cookies JSON is empty."))
        if isinstance(data, dict) and not data:
            raise ValueError(tr("Custom cookies JSON is empty."))

        if isinstance(data, dict):
            data["upload_method"] = self._selected_upload_method()

        return data

    def _derive_video_title(self, video_path: str) -> str:
        if self.video_title_label:
            label_text = self.video_title_label.text().strip()
            if label_text:
                return label_text
        return Path(video_path).stem

    def start_upload(self) -> None:
        if self.upload_worker and self.upload_worker.isRunning():
            QMessageBox.information(
                self,
                tr("Upload In Progress"),
                tr("Please wait for the current upload to finish before starting a new one."),
            )
            return

        video_path = self._current_upload_video_path()
        if not video_path:
            QMessageBox.warning(self, tr("Video Selection"), tr("Select a video to upload."))
            return

        video_file = Path(video_path)
        if not video_file.exists():
            QMessageBox.warning(
                self,
                tr("Video Missing"),
                tr("Selected video not found:\n{path}").format(path=video_path),
            )
            return

        try:
            selected_method = self._selected_upload_method()
            if self.use_channel_radio and self.use_channel_radio.isChecked():
                entry = self._selected_channel_entry()
                if not entry:
                    raise ValueError(tr("Choose a channel with stored TikTok cookies."))
                if not entry.get("has_cookies"):
                    raise ValueError(tr("Selected channel does not have cookies configured."))
                channel_id = entry["id"]
                base_config = dict(entry.get("config") or {})
                config = self.config_manager._merge_channel_defaults(base_config)
                config["upload_method"] = selected_method
                cookies = deepcopy(entry.get("cookies") or {})
                if isinstance(cookies, dict):
                    cookies["upload_method"] = selected_method
            else:
                cookies = self._parse_custom_cookies()
                channel_id = "__gui_custom__"
                config = self.config_manager._merge_channel_defaults(
                    {
                        "channel_name": "Custom TikTok Upload",
                        "upload_method": "browser",
                        "is_human": 0,
                    }
                )
                config["upload_method"] = selected_method
                proxy_value = self._current_custom_proxy()
                config["proxy"] = proxy_value
                if isinstance(cookies, dict):
                    if proxy_value:
                        cookies["proxy"] = proxy_value
                    elif "proxy" in cookies:
                        del cookies["proxy"]
                    cookies["upload_method"] = selected_method
            proxy_value = str(config.get("proxy", "") or "").strip()
            if proxy_value and not self._is_valid_proxy_format(proxy_value):
                raise ValueError(tr("Proxy format should be host:port or host:port:username:password."))
        except ValueError as exc:
            QMessageBox.warning(self, tr("Upload Configuration"), str(exc))
            return

        video_title = self._derive_video_title(str(video_file))

        self.upload_status_label.setText(tr("Preparing upload..."))

        worker = TikTokUploadWorker(
            channel_id=channel_id,
            config=config,
            cookies=cookies,
            video_path=str(video_file),
            video_title=video_title,
        )
        worker.setParent(self)
        worker.progress.connect(self._on_upload_progress)
        worker.completed.connect(self._on_upload_completed)
        worker.finished.connect(worker.deleteLater)

        self.upload_worker = worker
        self._update_upload_button_state()
        worker.start()

    def _on_upload_progress(self, message: str) -> None:
        if message and self.upload_status_label:
            self.upload_status_label.setText(message)

    def _on_upload_completed(self, success: bool, message: str) -> None:
        self.upload_status_label.setText(message)
        if not success:
            QMessageBox.critical(self, tr("Upload Failed"), message)
        else:
            QMessageBox.information(self, tr("Upload Complete"), message)

        self.upload_worker = None
        self._update_upload_button_state()

    def _set_widgets_enabled(self, widgets: List[QWidget], enabled: bool) -> None:
        for widget in widgets:
            widget.setEnabled(enabled)

    def _on_zoom_in_toggled(self, checked: bool) -> None:
        self.zoom_in_spin.setEnabled(checked)
        if checked:
            self.zoom_out_checkbox.blockSignals(True)
            self.zoom_out_checkbox.setChecked(False)
            self.zoom_out_checkbox.blockSignals(False)
            self.zoom_out_spin.setEnabled(False)

    def _on_zoom_out_toggled(self, checked: bool) -> None:
        self.zoom_out_spin.setEnabled(checked)
        if checked:
            self.zoom_in_checkbox.blockSignals(True)
            self.zoom_in_checkbox.setChecked(False)
            self.zoom_in_checkbox.blockSignals(False)
            self.zoom_in_spin.setEnabled(False)

    def fetch_formats(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, tr("Missing URL"), tr("Please enter a video URL or ID."))
            return

        url = self._normalize_url(url)

        self._reset_state()
        self._set_working_state(True, mode="fetch")
        self.status_label.setText(tr("Fetching available formats..."))

        worker = YTDLPWorker(url=url, mode="fetch")
        worker.setParent(self)
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
        if self.edit_worker and self.edit_worker.isRunning():
            QMessageBox.warning(
                self,
                tr("Editing In Progress"),
                tr("Please wait for the current video editing to finish before starting a new download."),
            )
            return

        if not self.current_url:
            QMessageBox.warning(self, tr("No Video"), tr("Please fetch video formats first."))
            return

        manual_format_required = not self._platform_supports_format_selection()

        if not self.formats_combo.isEnabled() or self.formats_combo.currentIndex() < 0:
            if manual_format_required:
                selected_label = self.formats_combo.currentText() or next(iter(self.format_map), None)
            else:
                QMessageBox.warning(self, tr("No Format"), tr("Please select a video format to download."))
                return
        else:
            selected_label = self.formats_combo.currentText()

        if not selected_label:
            selected_label = next(iter(self.format_map), "best")

        format_label = selected_label
        format_id = self.format_map.get(format_label, "best")

        if manual_format_required:
            self.status_label.setText(tr("Using best available format for selected platform."))

        if not format_id:
            QMessageBox.warning(self, tr("No Format"), tr("Please select a video format to download."))
            return

        output_dir = Path(self.folder_edit.text().strip() or ".").expanduser()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            QMessageBox.critical(
                self,
                tr("Folder Error"),
                tr("Failed to create output folder: {error}").format(error=exc),
            )
            return

        self.last_output_dir = output_dir
        self.last_download_path = None

        self._set_working_state(True, mode="download")
        self.status_label.setText(tr("Starting download..."))
        self.progress_bar.setValue(0)

        worker = YTDLPWorker(
            url=self.current_url,
            mode="download",
            format_id=format_id,
            output_dir=str(output_dir),
        )
        worker.setParent(self)
        worker.progress.connect(self.on_worker_progress)
        worker.completed.connect(lambda success, message: self.on_worker_completed("download", success, message))
        worker.error.connect(self.on_worker_error)
        worker.finished.connect(lambda: self._clear_worker_reference(worker))
        self.active_worker = worker
        self.active_mode = "download"
        worker.start()
        self._update_last_video_label()

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            tr("Select Download Folder"),
            self.folder_edit.text(),
        )
        if folder:
            self.folder_edit.setText(folder)

    def choose_overlay_image(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Select overlay image"),
            str(Path(self.folder_edit.text()).expanduser()),
            tr("Image Files (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All Files (*)"),
        )
        if file_path:
            self.overlay_path_edit.setText(file_path)
            if not self.overlay_checkbox.isChecked():
                self.overlay_checkbox.setChecked(True)

    def choose_interleave_video(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Select secondary video"),
            str(Path(self.folder_edit.text()).expanduser()),
            tr("Video Files (*.mp4 *.mov *.mkv *.webm *.m4v *.avi);;All Files (*)"),
        )
        if file_path:
            self.interleave_path_edit.setText(file_path)
            if not self.interleave_checkbox.isChecked():
                self.interleave_checkbox.setChecked(True)

    def choose_audio_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Select audio file"),
            str(Path(self.folder_edit.text()).expanduser()),
            tr("Audio Files (*.mp3 *.wav *.aac *.m4a *.ogg *.flac);;All Files (*)"),
        )
        if file_path:
            self.audio_path_edit.setText(file_path)
            if not self.audio_checkbox.isChecked():
                self.audio_checkbox.setChecked(True)

    def _normalize_url(self, url: str) -> str:
        if not url:
            return url

        platform = self.platform_combo.currentText()
        if platform == "Auto Detect (yt-dlp)":
            return url

        if platform == "YouTube" and "//" not in url:
            return f"https://www.youtube.com/watch?v={url}"
        if platform == "TikTok" and "//" not in url:
            return f"https://www.tiktok.com/@_/{url}"
        if platform == "Instagram" and "//" not in url:
            return f"https://www.instagram.com/reel/{url}/"
        if platform == "Vimeo" and "//" not in url:
            return f"https://vimeo.com/{url}"
        if platform == "Facebook Reel" and "//" not in url:
            return f"https://www.facebook.com/reel/{url}"

        return url

    def _platform_supports_format_selection(self) -> bool:
        return self.platform_combo.currentText() in {
            "Auto Detect (yt-dlp)",
            "YouTube",
            "Vimeo",
        }

    def _update_format_controls(self, has_formats: bool) -> None:
        supports_selection = self._platform_supports_format_selection()
        if supports_selection:
            self.formats_combo.setEnabled(has_formats)
            self.download_btn.setEnabled(has_formats)
        else:
            self.formats_combo.setEnabled(False)
            self.download_btn.setEnabled(has_formats)

    def on_platform_changed(self, platform: str) -> None:
        placeholder_map = {
            "Auto Detect (yt-dlp)": "Paste a supported video URL",
            "YouTube": "https://www.youtube.com/watch?v=...",
            "TikTok": "https://www.tiktok.com/@user/video/...",
            "Instagram": "https://www.instagram.com/reel/...",
            "Vimeo": "https://vimeo.com/...",
            "Facebook Reel": "https://www.facebook.com/reel/...",
        }
        self.url_edit.setPlaceholderText(
            placeholder_map.get(platform, "Paste a supported video URL")
        )

        if self.active_worker and self.active_worker.isRunning():
            return

        self._reset_state()

    def _any_edit_selected(self) -> bool:
        return any(
            checkbox.isChecked()
            for checkbox in [
                self.line_checkbox,
                self.blur_checkbox,
                self.overlay_checkbox,
                self.interleave_checkbox,
                self.mute_checkbox,
                self.audio_checkbox,
                self.rotate_checkbox,
                self.zoom_in_checkbox,
                self.zoom_out_checkbox,
            ]
        )

    def _gather_edit_options(self) -> Dict[str, Any]:
        return {
            "add_line": self.line_checkbox.isChecked(),
            "line_thickness": self.line_thickness_spin.value(),
            "line_color": (255, 255, 255),
            "blur": self.blur_checkbox.isChecked(),
            "blur_sigma": self.blur_value_spin.value(),
            "overlay": self.overlay_checkbox.isChecked(),
            "overlay_path": self.overlay_path_edit.text().strip(),
            "interleave": self.interleave_checkbox.isChecked(),
            "interleave_path": self.interleave_path_edit.text().strip(),
            "interleave_segment": self.interleave_segment_spin.value(),
            "mute": self.mute_checkbox.isChecked(),
            "add_audio": self.audio_checkbox.isChecked(),
            "audio_path": self.audio_path_edit.text().strip(),
            "rotate": self.rotate_checkbox.isChecked(),
            "rotate_degrees": self.rotate_spin.value(),
            "zoom_in": self.zoom_in_checkbox.isChecked(),
            "zoom_in_factor": self.zoom_in_spin.value(),
            "zoom_out": self.zoom_out_checkbox.isChecked(),
            "zoom_out_factor": self.zoom_out_spin.value(),
        }

    def _validate_edit_options(self, options: Dict[str, Any]) -> Optional[str]:
        if options["add_line"] and options["line_thickness"] <= 0:
            return "Line thickness must be greater than zero."

        if options["blur"] and options["blur_sigma"] <= 0:
            return "Blur intensity must be greater than zero."

        if options["overlay"]:
            overlay_path = options.get("overlay_path")
            if not overlay_path:
                return "Select an overlay image file."
            if not Path(overlay_path).exists():
                return f"Overlay image not found: {overlay_path}"

        if options["interleave"]:
            interleave_path = options.get("interleave_path")
            if not interleave_path:
                return "Select a secondary video to interleave."
            if not Path(interleave_path).exists():
                return f"Secondary video not found: {interleave_path}"
            if options.get("interleave_segment", 0) <= 0:
                return "Interleave segment length must be greater than zero."

        if options["add_audio"]:
            audio_path = options.get("audio_path")
            if not audio_path:
                return "Select an audio file to add."
            if not Path(audio_path).exists():
                return f"Audio file not found: {audio_path}"

        if options["zoom_in"] and options["zoom_in_factor"] <= 1.0:
            return "Zoom-in factor must be greater than 1.0."

        if options["zoom_out"]:
            zoom_out_factor = options.get("zoom_out_factor", 1.0)
            if not (0.0 < zoom_out_factor < 1.0):
                return "Zoom-out factor must be between 0 and 1."

        return None

    def _find_latest_file(self, directory: Path) -> Optional[str]:
        try:
            files = [entry for entry in Path(directory).iterdir() if entry.is_file()]
        except Exception:
            return None

        if not files:
            return None

        latest = max(files, key=lambda f: f.stat().st_mtime)
        return str(latest)

    def _start_edit_worker(self, input_path: str) -> bool:
        options = self._gather_edit_options()
        validation_error = self._validate_edit_options(options)
        if validation_error:
            QMessageBox.warning(self, "Edit Options", validation_error)
            return False

        self.status_label.setText("Applying video edits...")
        self.progress_bar.setRange(0, 0)

        output_dir = self.last_output_dir or Path(input_path).parent
        worker = VideoEditingWorker(input_path=input_path, output_dir=output_dir, options=options)
        worker.setParent(self)
        worker.progress.connect(self.on_edit_progress)
        worker.finished.connect(self.on_edit_finished)
        worker.finished.connect(worker.deleteLater)
        self.edit_worker = worker
        worker.start()
        return True

    def on_edit_progress(self, message: str) -> None:
        if message:
            self.status_label.setText(message)

    def on_edit_finished(self, success: bool, message: str, output_path: str) -> None:
        self.progress_bar.setRange(0, 100)
        self.edit_worker = None

        if success:
            self.progress_bar.setValue(100)
            self.status_label.setText(f"Edits complete: {output_path}")
            self.last_download_path = output_path
            QMessageBox.information(self, "Editing Complete", f"Edited video saved to:\n{output_path}")
            self._update_last_video_label()
        else:
            self.progress_bar.setValue(0)
            error_text = message or "Video editing failed."
            self.status_label.setText(error_text)
            QMessageBox.critical(self, "Editing Failed", error_text)

        self._set_working_state(False, mode="download")

    def prepare_shutdown(self) -> None:
        self._cancel_worker(self.active_worker)
        self.active_worker = None
        self.active_mode = None
        self._cancel_worker(self.edit_worker)
        self.edit_worker = None

    def _cancel_worker(self, worker: Optional[QThread]) -> None:
        if not worker:
            return
        try:
            cancel = getattr(worker, "cancel", None)
            if callable(cancel):
                cancel()
            worker.requestInterruption()
            if not worker.wait(5000):
                worker.terminate()
                worker.wait(1000)
        except Exception:
            pass

    def on_formats_ready(self, formats: List[Dict[str, Any]], info: Dict[str, Any]) -> None:
        self.current_formats = formats
        self.format_map.clear()
        self.formats_combo.clear()

        supports_selection = self._platform_supports_format_selection()

        video_formats: List[Dict[str, Any]] = []
        for fmt in formats:
            vcodec = fmt.get("vcodec")
            if vcodec and vcodec != "none":
                video_formats.append(fmt)

        if supports_selection and not video_formats:
            self._update_format_controls(False)
            self.status_label.setText("No downloadable video formats found.")
            return

        def sort_key(fmt: Dict[str, Any]) -> tuple:
            height = fmt.get("height") or 0
            bitrate = fmt.get("tbr") or 0
            size = fmt.get("filesize") or fmt.get("filesize_approx") or 0
            return height, bitrate, size

        sorted_formats = sorted(video_formats, key=sort_key, reverse=True)

        if supports_selection:
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

            has_formats = bool(self.format_map)
            self._update_format_controls(has_formats)
        else:
            self.formats_combo.addItem("Best available")
            self.format_map["Best available"] = "best"
            self._update_format_controls(True)

        title = info.get("title", "")
        uploader = info.get("uploader")
        extra = f" by {uploader}" if uploader else ""
        self.video_title_label.setText(f"{title}{extra}")
        if supports_selection:
            self.status_label.setText(f"Loaded {len(sorted_formats)} formats. Select one to download.")
        else:
            self.status_label.setText("Ready to download best available quality for this platform.")

    def on_worker_progress(self, progress: float, message: str) -> None:
        percent = max(0, min(100, int(progress * 100)))
        self.progress_bar.setValue(percent)
        if message:
            self.status_label.setText(message)

    def on_worker_completed(self, mode: str, success: bool, message: str) -> None:
        worker = self.active_worker if self.active_mode == mode else None
        download_path = None

        if mode == "download" and worker is not None:
            download_path = getattr(worker, "last_downloaded_path", None)
            if download_path:
                self.last_download_path = download_path

        if mode == "download" and success:
            if not download_path and self.last_output_dir:
                download_path = self._find_latest_file(self.last_output_dir)
                if download_path:
                    self.last_download_path = download_path

            self.progress_bar.setValue(100)

            if self._any_edit_selected():
                if download_path and Path(download_path).exists():
                    if self._start_edit_worker(download_path):
                        return
                else:
                    QMessageBox.warning(
                        self,
                        "Video Editing",
                        "Unable to locate the downloaded file. Skipping editing steps.",
                    )

            self._set_working_state(False, mode=mode)
            self.status_label.setText("Download completed successfully.")
            self._update_last_video_label()
            return

        self._set_working_state(False, mode=mode)

        if success:
            if mode == "fetch":
                self.status_label.setText("Formats fetched successfully.")
            if mode != "download":
                self._update_last_video_label()
        else:
            error_text = message or "Operation failed."
            self.status_label.setText(error_text)
            if mode == "download":
                QMessageBox.critical(self, "Download Failed", error_text)
            self._update_last_video_label()

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
            self._update_format_controls(has_formats)
        self._update_upload_button_state()

    def _reset_state(self) -> None:
        self.current_formats = []
        self.format_map.clear()
        self.formats_combo.clear()
        self._update_format_controls(False)
        self.fetch_btn.setEnabled(True)
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
        self._initialize_localization()
        self._setup_auto_updater()
        
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

        self.utilities_tab = UtilitiesTab(self.config_manager)
        self.tab_widget.addTab(self.utilities_tab, "🛠 Utilities")

        layout.addWidget(self.tab_widget)

        language_layout = QHBoxLayout()
        language_layout.setContentsMargins(0, 0, 0, 0)
        language_layout.addStretch()

        self.language_menu = QMenu(self)
        self.language_action_group = QActionGroup(self)
        self.language_action_group.setExclusive(True)
        self.language_actions = {}

        self.language_button = QPushButton("Switch Language")
        self.language_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.language_button.setMenu(self.language_menu)

        self._populate_language_menu()

        language_layout.addWidget(self.language_button)
        layout.addLayout(language_layout)
    
    def _populate_language_menu(self) -> None:
        if not hasattr(self, "language_menu"):
            return

        for action in list(self.language_action_group.actions()):
            self.language_action_group.removeAction(action)

        self.language_menu.clear()
        self.language_actions.clear()

        base_labels = {"en": "English", "vi": "Vietnamese"}
        language_codes = [
            code for code in translator.available_languages() if isinstance(code, str)
        ]
        language_codes.sort(key=lambda code: (0 if code == translator.default_language else 1, code))

        for code in language_codes:
            base_text = base_labels.get(code, code.upper())
            action = self.language_menu.addAction(base_text)
            action.setCheckable(True)
            action.setData(code)
            action.triggered.connect(lambda _checked=False, lang=code: self.change_language(lang))
            self.language_action_group.addAction(action)
            self.language_actions[code] = action

        self._update_language_menu_checks(translator.current_language)

    def _update_language_button_text(self) -> None:
        if not hasattr(self, "language_button"):
            return
        current_label = translator.language_label(translator.current_language)
        self.language_button.setText(f"{tr('Language')}: {current_label}")

    def _update_language_menu_checks(self, language_code: str) -> None:
        for code, action in self.language_actions.items():
            try:
                action.setChecked(code == language_code)
            except RuntimeError:
                pass

    def _initialize_localization(self) -> None:
        translator.bind_widget_tree(self)
        if getattr(self, "language_menu", None) is not None:
            translator.bind_widget_tree(self.language_menu)
        self._update_language_button_text()
        self._update_language_menu_checks(translator.current_language)
        translator.register_callback(self.on_language_changed)
    
    def _setup_auto_updater(self) -> None:
        """Initialize and start the auto-updater"""
        self.auto_updater = AutoUpdater(self)
        self.auto_updater.update_available.connect(self._on_update_available)
        self.auto_updater.start()
    
    def _on_update_available(self, update_info: Dict[str, Any]) -> None:
        """Handle notification when an update is available"""
        dialog = UpdateNotificationDialog(update_info, self)
        result = dialog.exec()
        
        if result == QMessageBox.Yes:
            # Open the download page in the default browser
            import webbrowser
            url = dialog.get_download_url()
            if url:
                webbrowser.open(url)
        elif result == QMessageBox.Ignore:
            # User chose to ignore this update
            pass

    def change_language(self, language_code: str) -> None:
        translator.set_language(language_code)

    def on_language_changed(self, language_code: str) -> None:
        self._update_language_button_text()
        self._update_language_menu_checks(language_code)
        if hasattr(self, "status_bar") and self.status_bar:
            if language_code == "vi":
                message_key = "Language switched to Vietnamese"
            else:
                message_key = "Language switched to English"
            self.status_bar.showMessage(tr(message_key), 3000)

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
        
        check_updates_action = QAction('Check for Updates', self)
        check_updates_action.triggered.connect(self.check_for_updates)
        help_menu.addAction(check_updates_action)
        
        help_menu.addSeparator()
        
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

    def closeEvent(self, event):
        try:
            # Stop auto-updater
            if hasattr(self, "auto_updater"):
                self.auto_updater.stop()
            
            if hasattr(self, "utilities_tab") and self.utilities_tab:
                self.utilities_tab.prepare_shutdown()
            if hasattr(self, "channels_tab") and self.channels_tab:
                self.channels_tab.prepare_shutdown()
        except Exception:
            pass
        super().closeEvent(event)
    
    def new_channel(self):
        """Create new channel"""
        if ChannelDialog:
            dialog = ChannelDialog(self.config_manager, parent=self)
            if dialog.exec() == QDialog.Accepted:
                if hasattr(self, 'channels_tab'):
                    self.channels_tab.refresh_channels()
                self.status_bar.showMessage(tr("New channel created successfully"), 3000)
        else:
            QMessageBox.information(self, tr("Info"), tr("Channel management components not available!"))
    
    def import_configuration(self):
        """Import configuration from file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Import Configuration"),
            "",
            tr("JSON Files (*.json);;All Files (*)"),
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
                        QMessageBox.warning(
                            self,
                            tr("Validation Error"),
                            tr("Configuration has errors:") + "\n" + "\n".join(errors),
                        )
                        return
                    
                    if self.config_manager.save_settings(config_data):
                        self.settings_tab.load_settings()
                        QMessageBox.information(
                            self,
                            tr("Success"),
                            tr("Settings imported successfully!"),
                        )
                    else:
                        QMessageBox.critical(self, tr("Error"), tr("Failed to import settings!"))
                
                elif "youtube_channel_id" in config_data:
                    # It's a channel config
                    errors = self.config_manager.validate_channel_config(config_data)
                    if errors:
                        QMessageBox.warning(
                            self,
                            tr("Validation Error"),
                            tr("Configuration has errors:") + "\n" + "\n".join(errors),
                        )
                        return
                    
                    channel_id = config_data["youtube_channel_id"]
                    if self.config_manager.save_channel(channel_id, config_data, {}):
                        if hasattr(self, 'channels_tab'):
                            self.channels_tab.refresh_channels()
                        QMessageBox.information(
                            self,
                            tr("Success"),
                            tr("Channel {channel_id} imported successfully!").format(channel_id=channel_id),
                        )
                    else:
                        QMessageBox.critical(self, tr("Error"), tr("Failed to import channel!"))
                
                else:
                    QMessageBox.warning(
                        self,
                        tr("Invalid Format"),
                        tr("File doesn't appear to be a valid settings or channel configuration!"),
                    )
                    
            except json.JSONDecodeError:
                QMessageBox.critical(self, tr("Error"), tr("Invalid JSON file!"))
            except Exception as e:
                QMessageBox.critical(
                    self,
                    tr("Error"),
                    tr("Failed to import configuration: {error}").format(error=str(e)),
                )
    
    def export_configuration(self):
        """Export configuration to file"""
        # Show dialog to choose what to export
        export_dialog = QDialog(self)
        export_dialog.setWindowTitle(tr("Export Configuration"))
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
                self,
                tr("Export Configuration"),
                f"autobot_config_{time.strftime('%Y%m%d_%H%M%S')}.json",
                tr("JSON Files (*.json);;All Files (*)"),
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
                    
                    QMessageBox.information(
                        self,
                        tr("Success"),
                        tr("Configuration exported to {path}").format(path=file_path),
                    )
                    
                except Exception as e:
                    QMessageBox.critical(
                        self,
                        tr("Error"),
                        tr("Failed to export configuration: {error}").format(error=str(e)),
                    )
    
    def check_for_updates(self):
        """Manually check for updates"""
        if hasattr(self, "auto_updater"):
            self.auto_updater.check_now()
            if hasattr(self, "status_bar"):
                self.status_bar.showMessage(tr("Checking for updates..."), 3000)
    
    def show_about(self):
        """Show about dialog"""
        QMessageBox.about(
            self,
            tr("About AutoBot GUI"),
            tr(
                "AutoBot GUI v1.0\n\n"
                "A graphical interface for managing YouTube to TikTok automation.\n\n"
                "Features:\n"
                "• Configure global settings\n"
                "• Manage multiple channels\n"
                "• Monitor channel automation\n\n"
                "Built with PySide6"
            ),
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