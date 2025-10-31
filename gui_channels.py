import sys
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List, TYPE_CHECKING
import subprocess
import threading
import time

import autobot

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLineEdit, QTextEdit, QComboBox, QSpinBox, QCheckBox, QPushButton,
    QLabel, QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QGroupBox, QScrollArea, QProgressBar, QStatusBar, QMenuBar, QMenu,
    QDialog, QDialogButtonBox, QGridLayout, QFrame, QListWidget, QListWidgetItem,
    QSizePolicy, QToolButton, QButtonGroup, QInputDialog, QAbstractItemView
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSettings
from PySide6.QtGui import QIcon, QFont, QPixmap, QAction

from localization import translator, tr

if TYPE_CHECKING:
    from gui_main import ConfigManager
else:
    ConfigManager = Any


class ChannelPipelineWorker(QThread):
    """Background worker to run the automation pipeline for a channel."""

    progress = Signal(str, str)  # channel_id, message
    finished = Signal(str, bool, str)  # channel_id, success, summary

    def __init__(
        self,
        channel_id: str,
        config_manager: ConfigManager,
        video_url: Optional[str] = None,
    ):
        super().__init__()
        self.channel_id = channel_id
        self.config_manager = config_manager
        self.video_url = video_url.strip() if video_url else None
        self._stop_requested = threading.Event()

    def request_stop(self) -> None:
        self._stop_requested.set()

    def run(self) -> None:
        try:
            self.progress.emit(self.channel_id, tr("Preparing pipeline environment..."))
            settings = self.config_manager.load_settings()
            autobot.APP_CONFIGS = settings

            channels = self.config_manager.get_channels()
            autobot.ALL_CONFIGS = channels

            channel_data = channels.get(self.channel_id)
            if not channel_data:
                self.finished.emit(self.channel_id, False, tr("Channel configuration not found"))
                return

            channel_config = channel_data['config']
            pipeline_steps = autobot._sanitize_pipeline_steps(
                channel_config.get("pipeline_steps")
            )
            scan_interval = max(1, int(channel_config.get("scan_interval", 5)))

            manual_video = None
            if self.video_url:
                manual_video = self._create_video_from_url(self.video_url, channel_config)
                if not manual_video:
                    self.finished.emit(
                        self.channel_id,
                        False,
                        tr("Failed to resolve video details from URL"),
                    )
                    return

            if not pipeline_steps.get("scan", True):
                if not manual_video:
                    self.finished.emit(
                        self.channel_id,
                        False,
                        tr("Video URL required when scan step is disabled"),
                    )
                    return

                success = self._process_video(manual_video, pipeline_steps)
                if self._stop_requested.is_set():
                    self.finished.emit(self.channel_id, False, tr("Pipeline cancelled"))
                elif success:
                    self.finished.emit(self.channel_id, True, tr("Pipeline completed successfully"))
                else:
                    self.finished.emit(self.channel_id, False, tr("Pipeline finished with errors"))
                return

            if manual_video:
                success = self._process_video(manual_video, pipeline_steps)
                if self._stop_requested.is_set():
                    self.finished.emit(self.channel_id, True, tr("Stopped by user"))
                    return
                if not success:
                    self.finished.emit(self.channel_id, False, tr("Pipeline finished with errors"))
                    return

            self.progress.emit(
                self.channel_id,
                tr("Scanning every {seconds}s for new videos...").format(seconds=scan_interval),
            )

            while not self._stop_requested.is_set():
                try:
                    video = autobot.check_new_video(self.channel_id)
                except Exception as err:
                    self.progress.emit(
                        self.channel_id,
                        tr("Error checking videos: {error}").format(error=err),
                    )
                    if self._wait_with_stop(scan_interval):
                        break
                    continue

                if self._stop_requested.is_set():
                    break

                if video:
                    success = self._process_video(video, pipeline_steps)
                    if not success and not self._stop_requested.is_set():
                        self.progress.emit(
                            self.channel_id,
                            tr("⚠ Pipeline finished with errors; waiting for next scan"),
                        )
                else:
                    self.progress.emit(
                        self.channel_id,
                        tr("No new videos. Next scan in {seconds}s").format(seconds=scan_interval),
                    )

                if self._wait_with_stop(scan_interval):
                    break

            if self._stop_requested.is_set():
                self.finished.emit(self.channel_id, True, tr("Stopped by user"))
            else:
                self.finished.emit(self.channel_id, True, tr("Scanner stopped"))

        except Exception as exc:
            self.finished.emit(
                self.channel_id,
                False,
                tr("Error: {error}").format(error=exc),
            )

    def _wait_with_stop(self, seconds: int) -> bool:
        seconds = max(0, int(seconds))
        if seconds <= 0:
            return self._stop_requested.is_set()
        return self._stop_requested.wait(timeout=seconds)

    def _process_video(self, video: autobot.Video, pipeline_steps: Dict[str, bool]) -> bool:
        if self._stop_requested.is_set():
            return False

        video_title = getattr(video, 'title', 'Unknown title')
        self.progress.emit(
            self.channel_id,
            tr("Processing video: {title}").format(title=video_title),
        )

        try:
            success = autobot.process_video_pipeline(
                self.channel_id,
                video,
                pipeline_steps=pipeline_steps,
                stop_event=self._stop_requested,
                progress_callback=lambda message: self.progress.emit(
                    self.channel_id, message
                ),
            )
        except TypeError:
            success = autobot.process_video_pipeline(self.channel_id, video)

        if not success and not self._stop_requested.is_set():
            self.progress.emit(self.channel_id, tr("⚠ Pipeline finished with errors"))

        return bool(success)

    def _create_video_from_url(self, url: str, channel_config: Dict[str, Any]) -> Optional[autobot.Video]:
        try:
            import yt_dlp

            ydl_opts = {"quiet": True, "skip_download": True, "noplaylist": True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            video_id = info.get("id")
            title = info.get("title", video_id or "Unknown Title")
            upload_date = info.get("upload_date")
            if upload_date:
                published = datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc).isoformat()
            else:
                published = datetime.now(timezone.utc).isoformat()

            if not video_id:
                return None

            channel_id = channel_config.get("youtube_channel_id", "")
            return autobot.Video(
                id=video_id,
                title=title,
                url=url,
                channel_id=channel_id,
                published=published,
            )
        except Exception as err:
            print(f"Failed to build video from URL {url}: {err}")
            return None


class ChannelDialog(QDialog):
    """Dialog for creating/editing channels"""
    
    def __init__(self, config_manager, channel_id: str = None, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.channel_id = channel_id
        self.is_editing = channel_id is not None
        self._updating_steps = False
        self._syncing_proxy_text = False
        self.pipeline_checks = {}  # type: Dict[str, QCheckBox]
        self.setup_ui()
        
        if self.is_editing:
            self.load_channel_data()
        else:
            self.set_pipeline_steps(self.config_manager._default_pipeline_steps())
    
    def setup_ui(self):
        self.setWindowTitle("Edit Channel" if self.is_editing else "New Channel")
        self.setModal(True)
        self.resize(600, 700)
        
        layout = QVBoxLayout()
        
        # Create tab widget for channel settings
        tab_widget = QTabWidget()
        
        # Basic Settings Tab
        basic_tab = self.create_basic_settings_tab()
        tab_widget.addTab(basic_tab, tr("Basic Settings"))
        
        # YouTube Settings Tab
        youtube_tab = self.create_youtube_settings_tab()
        tab_widget.addTab(youtube_tab, tr("YouTube API"))
        
        # TikTok Settings Tab
        tiktok_tab = self.create_tiktok_settings_tab()
        tab_widget.addTab(tiktok_tab, tr("TikTok Settings"))
        
        # Pipeline Settings Tab
        pipeline_tab = self.create_pipeline_settings_tab()
        tab_widget.addTab(pipeline_tab, tr("Pipeline"))

        # Advanced Settings Tab
        advanced_tab = self.create_advanced_settings_tab()
        tab_widget.addTab(advanced_tab, tr("Advanced"))
        
        # Cookies Tab
        cookies_tab = self.create_cookies_tab()
        tab_widget.addTab(cookies_tab, tr("Cookies"))
        
        layout.addWidget(tab_widget)
        
        # Dialog buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

        translator.bind_widget_tree(self)
    
    def create_basic_settings_tab(self):
        widget = QWidget()
        layout = QFormLayout()
        layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.channel_id_edit = QLineEdit()
        self.channel_id_edit.setPlaceholderText("UC...")
        self._prepare_line_edit(self.channel_id_edit)
        if self.is_editing:
            self.channel_id_edit.setReadOnly(True)
        layout.addRow(tr("YouTube Channel ID:"), self.channel_id_edit)

        self.channel_name_edit = QLineEdit()
        self.channel_name_edit.setPlaceholderText("Channel display name")
        self._prepare_line_edit(self.channel_name_edit)
        layout.addRow(tr("Channel Name:"), self.channel_name_edit)

        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("TikTok username")
        self._prepare_line_edit(self.username_edit)
        layout.addRow(tr("TikTok Username:"), self.username_edit)

        self.telegram_chat_id_edit = QLineEdit()
        self.telegram_chat_id_edit.setPlaceholderText("6601226586 (optional)")
        self._prepare_line_edit(self.telegram_chat_id_edit)
        layout.addRow(tr("Telegram Chat ID Override:"), self.telegram_chat_id_edit)

        self.telegram_bot_token_edit = QLineEdit()
        self.telegram_bot_token_edit.setPlaceholderText("8295256760:AAF5xzq_Emngvp-g8SqhASJBLcvjJHvjr4Y (optional)")
        self._prepare_line_edit(self.telegram_bot_token_edit)
        layout.addRow(tr("Telegram Bot Token Override:"), self.telegram_bot_token_edit)

        widget.setLayout(layout)
        return widget

    def create_youtube_settings_tab(self):
        widget = QWidget()
        layout = QFormLayout()
        layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.api_key_edit = QTextEdit()
        self.api_key_edit.setMaximumHeight(100)
        self.api_key_edit.setPlaceholderText("Enter API keys separated by semicolons (;)")
        self._prepare_text_edit(self.api_key_edit)
        layout.addRow(tr("YouTube API Keys:"), self.api_key_edit)

        self.api_type_combo = QComboBox()
        for value in ["activities", "playlistItems"]:
            self.api_type_combo.addItem(value, value)
        layout.addRow(tr("API Type:"), self.api_type_combo)

        self.scan_method_combo = QComboBox()
        for value in ["sequence", "parallel"]:
            self.scan_method_combo.addItem(value, value)
        layout.addRow(tr("API Scan Method:"), self.scan_method_combo)

        self.detect_video_combo = QComboBox()
        for value in ["websub", "api", "both"]:
            self.detect_video_combo.addItem(value, value)
        self.detect_video_combo.currentTextChanged.connect(self.on_detect_video_changed)
        layout.addRow(tr("Video Detection:"), self.detect_video_combo)

        self.scan_interval_spin = QSpinBox()
        self.scan_interval_spin.setRange(1, 3600)
        self.scan_interval_spin.setValue(5)
        self.scan_interval_spin.setSuffix(f" {tr('seconds')}")
        layout.addRow(tr("Scan Interval:"), self.scan_interval_spin)

        self.is_new_second_spin = QSpinBox()
        self.is_new_second_spin.setRange(60, 86400)
        self.is_new_second_spin.setValue(36000000)
        self.is_new_second_spin.setSuffix(f" {tr('seconds')}")
        layout.addRow(tr("New Video Threshold:"), self.is_new_second_spin)

        widget.setLayout(layout)
        return widget

    def create_tiktok_settings_tab(self):
        widget = QWidget()
        layout = QFormLayout()
        layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.upload_method_combo = QComboBox()
        for value in ["api", "browser"]:
            self.upload_method_combo.addItem(value, value)
        layout.addRow(tr("Upload Method:"), self.upload_method_combo)

        self.region_combo = QComboBox()
        for value in ["ap-northeast-3", "ap-southeast-1", "us-east-1", "eu-west-1"]:
            self.region_combo.addItem(value, value)
        layout.addRow(tr("Region:"), self.region_combo)

        self.video_format_edit = QLineEdit()
        self.video_format_edit.setText("18")
        self.video_format_edit.setPlaceholderText("YouTube video format")
        self._prepare_line_edit(self.video_format_edit)
        layout.addRow(tr("Video Format:"), self.video_format_edit)

        self.render_method_combo = QComboBox()
        for value in ["repeat", "slow"]:
            self.render_method_combo.addItem(value, value)
        layout.addRow(tr("Render Method:"), self.render_method_combo)

        self.is_human_check = QCheckBox()
        layout.addRow(tr("Human-like Behavior:"), self.is_human_check)

        widget.setLayout(layout)
        return widget

    def create_advanced_settings_tab(self):
        widget = QWidget()
        layout = QFormLayout()
        layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        proxy_layout = QHBoxLayout()
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("host:port:username:password")
        self._prepare_line_edit(self.proxy_edit)
        self.proxy_edit.textChanged.connect(self._on_advanced_proxy_changed)
        proxy_layout.addWidget(self.proxy_edit)
        
        self.proxy_test_btn = QPushButton(tr("Test"))
        self.proxy_test_btn.clicked.connect(self._test_proxy)
        self.proxy_test_btn.setMaximumWidth(60)
        proxy_layout.addWidget(self.proxy_test_btn)
        
        layout.addRow(tr("Proxy:"), proxy_layout)

        self.user_agent_edit = QLineEdit()
        self.user_agent_edit.setText("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        self._prepare_line_edit(self.user_agent_edit)
        layout.addRow(tr("User Agent:"), self.user_agent_edit)

        self.viewport_edit = QLineEdit()
        self.viewport_edit.setText("1280x720")
        self.viewport_edit.setPlaceholderText("widthxheight")
        self._prepare_line_edit(self.viewport_edit)
        layout.addRow(tr("Viewport Size:"), self.viewport_edit)

        widget.setLayout(layout)
        return widget
    
    def create_cookies_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()

        # Instructions
        instructions = QLabel(
            tr("Paste TikTok cookies in JSON format. You can export cookies from browser extensions.\n"
            "The format should match the structure used by the application.")
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        # Cookies text area
        self.cookies_edit = QTextEdit()
        self.cookies_edit.setPlaceholderText('{"url": "https://www.tiktok.com", "cookies": [...]}')
        self._prepare_text_edit(self.cookies_edit)
        self.cookies_edit.textChanged.connect(self._on_cookies_text_changed)
        layout.addWidget(self.cookies_edit)

        # Buttons for cookie management
        button_layout = QHBoxLayout()

        load_btn = QPushButton(tr("Load from File"))
        load_btn.clicked.connect(self.load_cookies_from_file)
        button_layout.addWidget(load_btn)

        save_btn = QPushButton(tr("Save to File"))
        save_btn.clicked.connect(self.save_cookies_to_file)
        button_layout.addWidget(save_btn)

        validate_btn = QPushButton(tr("Validate"))
        validate_btn.clicked.connect(self.validate_cookies)
        button_layout.addWidget(validate_btn)

        button_layout.addStretch()
        layout.addLayout(button_layout)

        widget.setLayout(layout)
        return widget

    def create_pipeline_settings_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()

        description = QLabel(
            tr("Choose which stages of the automation pipeline should run for this channel.\n"
            "Steps later in the pipeline require the previous ones to remain enabled.")
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        steps_group = QGroupBox(tr("Pipeline Steps"))
        steps_layout = QVBoxLayout()

        step_labels = {
            "scan": tr("Scan for new YouTube videos"),
            "download": tr("Download detected videos"),
            "render": tr("Render downloaded videos"),
            "upload": tr("Upload rendered videos to TikTok"),
        }

        for step, label in step_labels.items():
            checkbox = QCheckBox(label)
            checkbox.setChecked(True)
            checkbox.stateChanged.connect(lambda _, s=step: self.on_pipeline_step_changed(s))
            self.pipeline_checks[step] = checkbox
            steps_layout.addWidget(checkbox)

        steps_group.setLayout(steps_layout)
        layout.addWidget(steps_group)
        layout.addStretch()

        widget.setLayout(layout)
        return widget
    
    def load_channel_data(self):
        """Load existing channel data"""
        channels = self.config_manager.get_channels()
        if self.channel_id in channels:
            config = channels[self.channel_id]['config']
            cookies = channels[self.channel_id]['cookies']
            
            # Basic settings
            self.channel_id_edit.setText(config.get('youtube_channel_id', ''))
            self.channel_name_edit.setText(config.get('channel_name', ''))
            self.username_edit.setText(config.get('username', ''))
            
            # Parse telegram setting (chat_id|bot_token)
            telegram = config.get('telegram', '')
            if telegram and '|' in telegram:
                chat_id, bot_token = telegram.split('|', 1)
                self.telegram_chat_id_edit.setText(chat_id.strip())
                self.telegram_bot_token_edit.setText(bot_token.strip())
            else:
                self.telegram_chat_id_edit.setText('')
                self.telegram_bot_token_edit.setText('')
            
            # YouTube settings
            self.api_key_edit.setPlainText(config.get('youtube_api_key', ''))
            self.api_type_combo.setCurrentText(config.get('youtube_api_type', 'activities'))
            self.scan_method_combo.setCurrentText(config.get('api_scan_method', 'sequence'))
            self.detect_video_combo.setCurrentText(config.get('detect_video', 'websub'))
            self.scan_interval_spin.setValue(config.get('scan_interval', 5))
            self.is_new_second_spin.setValue(config.get('is_new_second', 36000000))
            
            # TikTok settings
            self.upload_method_combo.setCurrentText(config.get('upload_method', 'api'))
            self.region_combo.setCurrentText(config.get('region', 'ap-northeast-3'))
            self.video_format_edit.setText(config.get('video_format', '18'))
            self.render_method_combo.setCurrentText(config.get('render_video_method', 'repeat'))
            self.is_human_check.setChecked(bool(config.get('is_human', 1)))
            
            # Advanced settings
            proxy_value = str(config.get('proxy', '') or '').strip()
            self._set_proxy_text(proxy_value)
            self.user_agent_edit.setText(config.get('user_agent', ''))
            self.viewport_edit.setText(config.get('view_port', '1280x720'))
            
            # Cookies
            if cookies:
                self.cookies_edit.setPlainText(json.dumps(cookies, indent=2))
                if isinstance(cookies, dict):
                    cookies_proxy = str(cookies.get('proxy', '') or '').strip()
                    if cookies_proxy:
                        self._set_proxy_text(cookies_proxy)

            # Pipeline steps
            self.set_pipeline_steps(config.get('pipeline_steps', {}))
    
    def get_channel_data(self):
        """Get channel data from UI"""
        proxy_value = self.proxy_edit.text().strip()
        self._set_proxy_text(proxy_value)

        # Combine chat_id and bot_token into telegram format
        chat_id = self.telegram_chat_id_edit.text().strip()
        bot_token = self.telegram_bot_token_edit.text().strip()
        telegram = f"{chat_id}|{bot_token}" if chat_id and bot_token else ""

        config = {
            'youtube_channel_id': self.channel_id_edit.text().strip(),
            'channel_name': self.channel_name_edit.text().strip(),
            'username': self.username_edit.text().strip(),
            'telegram': telegram,
            'youtube_api_key': self.api_key_edit.toPlainText().strip(),
            'youtube_api_type': self.api_type_combo.currentText(),
            'api_scan_method': self.scan_method_combo.currentText(),
            'detect_video': self.detect_video_combo.currentText(),
            'scan_interval': self.scan_interval_spin.value(),
            'is_new_second': self.is_new_second_spin.value(),
            'upload_method': self.upload_method_combo.currentText(),
            'region': self.region_combo.currentText(),
            'video_format': self.video_format_edit.text().strip(),
            'render_video_method': self.render_method_combo.currentText(),
            'is_human': 1 if self.is_human_check.isChecked() else 0,
            'proxy': proxy_value,
            'user_agent': self.user_agent_edit.text().strip(),
            'view_port': self.viewport_edit.text().strip(),
            'pipeline_steps': self.get_pipeline_steps()
        }
        
        # Parse cookies
        cookies = {}
        cookies_text = self.cookies_edit.toPlainText().strip()
        if cookies_text:
            try:
                cookies = json.loads(cookies_text)
                if isinstance(cookies, dict):
                    if proxy_value:
                        cookies['proxy'] = proxy_value
                    elif 'proxy' in cookies:
                        del cookies['proxy']
            except json.JSONDecodeError:
                pass
        
        return config, cookies

    def set_pipeline_steps(self, steps: Dict[str, Any]):
        sanitized = self.config_manager._sanitize_pipeline_steps(steps)
        previous_state = self._updating_steps
        self._updating_steps = True
        for step, checkbox in self.pipeline_checks.items():
            checkbox.setChecked(bool(sanitized.get(step, True)))
        self._updating_steps = previous_state
        self._sync_scan_checkbox()

    def get_pipeline_steps(self) -> Dict[str, bool]:
        return {step: checkbox.isChecked() for step, checkbox in self.pipeline_checks.items()}

    def on_pipeline_step_changed(self, step: str):
        if self._updating_steps:
            return
        self._updating_steps = True

        steps_state = {name: cb.isChecked() for name, cb in self.pipeline_checks.items()}

        if steps_state["upload"]:
            steps_state["render"] = True
            steps_state["download"] = True

        if steps_state["render"] and not steps_state["download"]:
            steps_state["download"] = True

        if not steps_state["render"]:
            steps_state["upload"] = False

        if not steps_state["download"]:
            steps_state["render"] = False
            steps_state["upload"] = False

        for name, checked in steps_state.items():
            checkbox = self.pipeline_checks[name]
            if checkbox.isChecked() != checked:
                checkbox.setChecked(checked)

        self._updating_steps = False
        self._sync_scan_checkbox()

    def on_detect_video_changed(self, value: str):
        self._sync_scan_checkbox()

    def _sync_scan_checkbox(self):
        detect_mode = self.detect_video_combo.currentText() if hasattr(self, 'detect_video_combo') else "api"
        requires_scan = detect_mode in {"websub", "both"}
        scan_checkbox = self.pipeline_checks.get("scan")
        if not scan_checkbox:
            return

        previous_state = self._updating_steps
        self._updating_steps = True
        try:
            if requires_scan:
                if not scan_checkbox.isChecked():
                    scan_checkbox.setChecked(True)
                scan_checkbox.setEnabled(False)
                scan_checkbox.setToolTip(tr("Scan is required when using WebSub detection modes."))
            else:
                scan_checkbox.setEnabled(True)
                scan_checkbox.setToolTip("")
        finally:
            self._updating_steps = previous_state

    def _prepare_line_edit(self, widget: QLineEdit):
        widget.setMinimumWidth(320)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def _prepare_text_edit(self, widget: QTextEdit):
        widget.setMinimumWidth(320)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def _set_proxy_text(self, text: str):
        if self._syncing_proxy_text or not hasattr(self, "proxy_edit"):
            return
        sanitized = (text or "").strip()
        self._syncing_proxy_text = True
        try:
            current_proxy = self.proxy_edit.text() if self.proxy_edit else ""
            if sanitized != current_proxy:
                self.proxy_edit.setText(sanitized)
        finally:
            self._syncing_proxy_text = False

    def _on_advanced_proxy_changed(self, text: str):
        self._set_proxy_text(text)

    def _on_cookies_text_changed(self):
        text = self.cookies_edit.toPlainText().strip()
        if not text:
            return
        try:
            data = json.loads(text)
        except Exception:
            return
        if isinstance(data, dict):
            proxy_value = str(data.get("proxy", "") or "").strip()
            if proxy_value:
                self._set_proxy_text(proxy_value)

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
    
    def _test_proxy(self):
        """Test if the proxy connection is working"""
        proxy_text = self.proxy_edit.text().strip()
        
        if not proxy_text:
            QMessageBox.warning(
                self,
                tr("No Proxy"),
                tr("Please enter a proxy address to test."),
            )
            return
        
        if not self._is_valid_proxy_format(proxy_text):
            QMessageBox.warning(
                self,
                tr("Invalid Format"),
                tr("Proxy format should be host:port or host:port:username:password."),
            )
            return
        
        # Parse proxy
        parts = proxy_text.split(":")
        host = parts[0]
        port = int(parts[1])
        
        proxy_dict = {
            "http": f"http://{proxy_text}",
            "https": f"http://{proxy_text}",
        }
        
        if len(parts) == 4:
            username, password = parts[2], parts[3]
            proxy_dict = {
                "http": f"http://{username}:{password}@{host}:{port}",
                "https": f"http://{username}:{password}@{host}:{port}",
            }
        
        # Create worker thread for testing
        class ProxyTestWorker(QThread):
            finished = Signal(bool, str)
            
            def __init__(self, proxy_dict):
                super().__init__()
                self.proxy_dict = proxy_dict
            
            def run(self):
                try:
                    import requests
                    response = requests.get(
                        "https://www.google.com",
                        proxies=self.proxy_dict,
                        timeout=10
                    )
                    self.finished.emit(True, tr("Proxy is working! Status code: {code}").format(code=response.status_code))
                except Exception as e:
                    self.finished.emit(False, tr("Proxy connection failed:\n{error}").format(error=str(e)))
        
        # Show testing dialog
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Testing Proxy"))
        dialog.setModal(True)
        dialog.resize(400, 150)
        
        layout = QVBoxLayout()
        
        status_label = QLabel(tr("Testing proxy connection...\nThis may take a few seconds."))
        status_label.setWordWrap(True)
        layout.addWidget(status_label)
        
        progress = QProgressBar()
        progress.setRange(0, 0)  # Indeterminate progress
        layout.addWidget(progress)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.button(QDialogButtonBox.Close).setEnabled(False)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        dialog.setLayout(layout)
        
        # Create and start worker
        worker = ProxyTestWorker(proxy_dict)
        
        def on_test_finished(success, message):
            status_label.setText(message)
            progress.setRange(0, 1)
            progress.setValue(1)
            button_box.button(QDialogButtonBox.Close).setEnabled(True)
            
            if success:
                status_label.setStyleSheet("color: green;")
            else:
                status_label.setStyleSheet("color: red;")
        
        worker.finished.connect(on_test_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()
        
        dialog.exec()
    
    def load_cookies_from_file(self):
        """Load cookies from JSON file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Load Cookies"),
            "",
            tr("JSON Files (*.json);;All Files (*)"),
        )
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    cookies = json.load(f)
                self.cookies_edit.setPlainText(json.dumps(cookies, indent=2))
                if isinstance(cookies, dict):
                    self._set_proxy_text(cookies.get("proxy", ""))
                QMessageBox.information(
                    self,
                    tr("Success"),
                    tr("Cookies loaded successfully!"),
                )
            except Exception as e:
                QMessageBox.critical(
                    self,
                    tr("Error"),
                    tr("Failed to load cookies: {error}").format(error=str(e)),
                )
    
    def save_cookies_to_file(self):
        """Save cookies to JSON file"""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("Save Cookies"),
            "",
            tr("JSON Files (*.json);;All Files (*)"),
        )
        if file_path:
            try:
                cookies_text = self.cookies_edit.toPlainText().strip()
                proxy_text = self.cookies_proxy_edit.text().strip() if self.cookies_proxy_edit else ""
                if proxy_text and not self._is_valid_proxy_format(proxy_text):
                    QMessageBox.warning(
                        self,
                        tr("Warning"),
                        tr("Proxy format should be host:port or host:port:username:password"),
                    )
                    return
                if cookies_text:
                    cookies = json.loads(cookies_text)
                    if isinstance(cookies, dict):
                        if proxy_text:
                            cookies["proxy"] = proxy_text
                        elif "proxy" in cookies:
                            del cookies["proxy"]
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(cookies, f, indent=2)
                    QMessageBox.information(
                        self,
                        tr("Success"),
                        tr("Cookies saved successfully!"),
                    )
                else:
                    QMessageBox.warning(
                        self,
                        tr("Warning"),
                        tr("No cookies to save!"),
                    )
            except Exception as e:
                QMessageBox.critical(
                    self,
                    tr("Error"),
                    tr("Failed to save cookies: {error}").format(error=str(e)),
                )
    
    def validate_cookies(self):
        """Validate cookies JSON format"""
        cookies_text = self.cookies_edit.toPlainText().strip()
        if not cookies_text:
            QMessageBox.warning(self, tr("Warning"), tr("No cookies to validate!"))
            return
        
        try:
            cookies = json.loads(cookies_text)
            proxy_text = ""
            if isinstance(cookies, dict):
                proxy_text = str(cookies.get("proxy", "") or "").strip()
                if proxy_text:
                    self._set_proxy_text(proxy_text)
            if proxy_text and not self._is_valid_proxy_format(proxy_text):
                QMessageBox.warning(
                    self,
                    "Warning",
                    "Proxy format should be host:port or host:port:username:password",
                )
                return
            # Basic validation
            if isinstance(cookies, dict) and 'cookies' in cookies:
                QMessageBox.information(self, tr("Success"), tr("Cookies format is valid!"))
            else:
                QMessageBox.warning(
                    self,
                    tr("Warning"),
                    tr("Cookies format may be incorrect. Expected structure with 'cookies' key."),
                )
        except json.JSONDecodeError as e:
            QMessageBox.critical(
                self,
                tr("Error"),
                tr("Invalid JSON format: {error}").format(error=str(e)),
            )
    
    def accept(self):
        """Validate and accept dialog"""
        config, cookies = self.get_channel_data()
        
        # Basic validation
        if not config['youtube_channel_id']:
            QMessageBox.warning(
                self,
                tr("Validation Error"),
                tr("YouTube Channel ID is required!"),
            )
            return
        
        if not config['youtube_api_key']:
            QMessageBox.warning(
                self,
                tr("Validation Error"),
                tr("At least one YouTube API key is required!"),
            )
            return
        
        # Save channel
        channel_id = config['youtube_channel_id']
        if self.config_manager.save_channel(channel_id, config, cookies):
            super().accept()
        else:
            QMessageBox.critical(self, tr("Error"), tr("Failed to save channel!"))


class ChannelsTab(QWidget):
    """Tab for channel management"""
    
    def __init__(self, config_manager: 'ConfigManager'):
        super().__init__()
        self.config_manager = config_manager
        self.pipeline_workers: Dict[str, ChannelPipelineWorker] = {}
        self.start_buttons: Dict[str, QPushButton] = {}
        self.stop_buttons: Dict[str, QPushButton] = {}
        self.status_items: Dict[str, QTableWidgetItem] = {}
        self.last_status_message: Dict[str, str] = {}
        self._channel_cache: Dict[str, Any] = {}
        self.setup_ui()
        self.refresh_channels()
        translator.register_callback(self._on_language_changed)
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # Toolbar
        toolbar_layout = QHBoxLayout()
        
        self.add_btn = QPushButton("Add Channel")
        self.add_btn.clicked.connect(self.add_channel)
        toolbar_layout.addWidget(self.add_btn)
        
        self.edit_btn = QPushButton("Edit Channel")
        self.edit_btn.clicked.connect(self.edit_channel)
        self.edit_btn.setEnabled(False)
        toolbar_layout.addWidget(self.edit_btn)
        
        self.delete_btn = QPushButton("Delete Channel")
        self.delete_btn.clicked.connect(self.delete_channel)
        self.delete_btn.setEnabled(False)
        toolbar_layout.addWidget(self.delete_btn)
        
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_channels)
        toolbar_layout.addWidget(self.refresh_btn)

        self.start_all_btn = QPushButton("Start All")
        self.start_all_btn.clicked.connect(self.start_all_channels)
        toolbar_layout.addWidget(self.start_all_btn)

        self.stop_all_btn = QPushButton("Stop All")
        self.stop_all_btn.clicked.connect(self.stop_all_channels)
        self.stop_all_btn.setEnabled(False)
        toolbar_layout.addWidget(self.stop_all_btn)

        self.show_columns_btn = QToolButton()
        self.show_columns_btn.setText("Show Columns")
        self.show_columns_btn.setPopupMode(QToolButton.InstantPopup)
        toolbar_layout.addWidget(self.show_columns_btn)
        
        toolbar_layout.addStretch()
        
        # Channels table
        self.channels_table = QTableWidget()
        self.column_definitions = self._build_column_definitions()
        self.channels_table.setColumnCount(len(self.column_definitions))
        self.channels_table.setHorizontalHeaderLabels([
            tr(column["label"]) for column in self.column_definitions
        ])
        for index, column in enumerate(self.column_definitions):
            if not column.get("default_visible", True):
                self.channels_table.setColumnHidden(index, True)
        
        # Configure table
        header = self.channels_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(False)
        
        self.channels_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.channels_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.channels_table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.channels_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.channels_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.channels_table.setWordWrap(False)

        self.column_actions: List[QAction] = []
        self._create_column_menu()

        self.channels_table.itemSelectionChanged.connect(self.on_selection_changed)
        self.channels_table.itemDoubleClicked.connect(self.edit_channel)
        
        layout.addLayout(toolbar_layout)
        layout.addWidget(self.channels_table)
        self.setLayout(layout)

        translator.bind_widget_tree(self)
        self._apply_localized_column_labels()
    
    def _create_column_menu(self):
        self.show_columns_menu = QMenu(self)
        self.show_all_columns_action = QAction("Show All Columns", self)
        self.show_all_columns_action.triggered.connect(self._show_all_columns)
        self.show_columns_menu.addAction(self.show_all_columns_action)

        self.restore_columns_action = QAction("Restore Default Columns", self)
        self.restore_columns_action.triggered.connect(self._restore_default_columns)
        self.show_columns_menu.addAction(self.restore_columns_action)

        self.show_columns_menu.addSeparator()
        self.column_actions.clear()
        for index, column in enumerate(self.column_definitions):
            action = QAction(column["label"], self)
            action.setCheckable(True)
            action.setChecked(not self.channels_table.isColumnHidden(index))
            action.toggled.connect(lambda checked, col=index: self.set_column_visible(col, checked))
            self.show_columns_menu.addAction(action)
            self.column_actions.append(action)
        self.show_columns_btn.setMenu(self.show_columns_menu)

    def _apply_localized_column_labels(self) -> None:
        for index, column in enumerate(self.column_definitions):
            header_item = self.channels_table.horizontalHeaderItem(index)
            if header_item is not None:
                header_item.setText(tr(column["label"]))
            if index < len(self.column_actions):
                try:
                    self.column_actions[index].setText(tr(column["label"]))
                except RuntimeError:
                    continue

        if hasattr(self, "show_all_columns_action"):
            self.show_all_columns_action.setText(tr("Show All Columns"))
        if hasattr(self, "restore_columns_action"):
            self.restore_columns_action.setText(tr("Restore Default Columns"))

    def _on_language_changed(self, _language: str) -> None:
        self._apply_localized_column_labels()
        self.scan_interval_spin.setSuffix(f" {tr('seconds')}")
        self.is_new_second_spin.setSuffix(f" {tr('seconds')}")
        self.last_status_message.clear()
        self.refresh_channels()

    def _show_all_columns(self) -> None:
        for index in range(len(self.column_definitions)):
            self.channels_table.setColumnHidden(index, False)
        self._sync_column_actions()

    def _restore_default_columns(self) -> None:
        for index, column in enumerate(self.column_definitions):
            self.channels_table.setColumnHidden(index, not column.get("default_visible", True))
        self._sync_column_actions()

    def _build_column_definitions(self) -> List[Dict[str, Any]]:
        return [
            {"id": "channel_id", "label": "Channel ID", "source": "channel_id", "default_visible": True},
            {"id": "channel_name", "label": "Channel Name", "source": "config", "key": "channel_name", "default_visible": True},
            {"id": "username", "label": "TikTok Username", "source": "config", "key": "username", "default_visible": True},
            {"id": "telegram", "label": "Telegram Override", "source": "config", "key": "telegram", "default_visible": False},
            {"id": "detect_video", "label": "Video Detection", "source": "config", "key": "detect_video", "default_visible": True},
            {"id": "youtube_api_type", "label": "YouTube API Type", "source": "config", "key": "youtube_api_type", "default_visible": False},
            {"id": "youtube_api_key", "label": "YouTube API Keys", "source": "config", "key": "youtube_api_key", "default_visible": False, "formatter": self._format_api_keys},
            {"id": "api_scan_method", "label": "API Scan Method", "source": "config", "key": "api_scan_method", "default_visible": False},
            {"id": "scan_interval", "label": "Scan Interval (s)", "source": "config", "key": "scan_interval", "default_visible": False, "alignment": Qt.AlignCenter},
            {"id": "is_new_second", "label": "New Video Threshold (s)", "source": "config", "key": "is_new_second", "default_visible": False, "alignment": Qt.AlignCenter},
            {"id": "upload_method", "label": "Upload Method", "source": "config", "key": "upload_method", "default_visible": True},
            {"id": "region", "label": "Region", "source": "config", "key": "region", "default_visible": True},
            {"id": "video_format", "label": "Video Format", "source": "config", "key": "video_format", "default_visible": False, "alignment": Qt.AlignCenter},
            {"id": "render_video_method", "label": "Render Method", "source": "config", "key": "render_video_method", "default_visible": False},
            {"id": "is_human", "label": "Human-like Behavior", "source": "config", "key": "is_human", "default_visible": False, "formatter": self._format_bool, "alignment": Qt.AlignCenter},
            {"id": "proxy", "label": "Proxy", "source": "config", "key": "proxy", "default_visible": False},
            {"id": "user_agent", "label": "User Agent", "source": "config", "key": "user_agent", "default_visible": False},
            {"id": "view_port", "label": "Viewport Size", "source": "config", "key": "view_port", "default_visible": False, "alignment": Qt.AlignCenter},
            {"id": "pipeline_scan", "label": "Pipeline: Scan", "source": "pipeline", "key": "scan", "default_visible": False, "formatter": self._format_bool, "alignment": Qt.AlignCenter},
            {"id": "pipeline_download", "label": "Pipeline: Download", "source": "pipeline", "key": "download", "default_visible": False, "formatter": self._format_bool, "alignment": Qt.AlignCenter},
            {"id": "pipeline_render", "label": "Pipeline: Render", "source": "pipeline", "key": "render", "default_visible": False, "formatter": self._format_bool, "alignment": Qt.AlignCenter},
            {"id": "pipeline_upload", "label": "Pipeline: Upload", "source": "pipeline", "key": "upload", "default_visible": False, "formatter": self._format_bool, "alignment": Qt.AlignCenter},
            {"id": "cookies", "label": "Has Cookies", "source": "cookies", "default_visible": False, "formatter": self._format_bool, "alignment": Qt.AlignCenter},
            {"id": "status", "label": "Status", "source": "status", "default_visible": True},
            {"id": "actions", "label": "Actions", "source": "actions", "default_visible": True},
        ]

    @staticmethod
    def _format_bool(value: Any) -> str:
        return tr("Yes") if bool(value) else tr("No")

    @staticmethod
    def _format_api_keys(value: Any) -> str:
        if not value:
            return ""
        if isinstance(value, str):
            cleaned = value.replace("\r", "\n")
            parts = [part.strip() for part in cleaned.split("\n") if part.strip()]
            return "; ".join(parts) if parts else ""
        return str(value)

    def _resolve_column_value(
        self,
        column: Dict[str, Any],
        channel_id: str,
        config: Dict[str, Any],
        pipeline_steps: Dict[str, bool],
        has_cookies: bool,
        status_text: str,
    ) -> str:
        source = column.get("source")
        if source == "channel_id":
            value = channel_id
        elif source == "config":
            value = config.get(column.get("key", ""), "")
            if column["id"] == "channel_name" and not value:
                value = config.get("youtube_channel_id", channel_id)
        elif source == "pipeline":
            value = pipeline_steps.get(column.get("key"), False)
        elif source == "cookies":
            value = has_cookies
        elif source == "status":
            value = status_text
        else:
            value = ""

        formatter = column.get("formatter")
        if formatter:
            value = formatter(value)

        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return str(value)

    def _create_actions_widget(self, channel_id: str, is_running: bool) -> QWidget:
        controls_widget = QWidget()
        controls_layout = QHBoxLayout(controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)

        start_btn = QPushButton(tr("Start"))
        stop_btn = QPushButton(tr("Stop"))

        start_btn.setEnabled(not is_running)
        stop_btn.setEnabled(is_running)

        start_btn.clicked.connect(lambda checked, cid=channel_id: self.start_channel_pipeline(cid))
        stop_btn.clicked.connect(lambda checked, cid=channel_id: self.stop_channel_pipeline(cid))

        controls_layout.addWidget(start_btn)
        controls_layout.addWidget(stop_btn)
        controls_layout.addStretch()

        self.start_buttons[channel_id] = start_btn
        self.stop_buttons[channel_id] = stop_btn
        return controls_widget

    def set_column_visible(self, column: int, visible: bool) -> None:
        if column < 0 or column >= len(self.column_definitions):
            return

        if not visible:
            remaining_visible = sum(
                1
                for idx in range(len(self.column_definitions))
                if idx != column and not self.channels_table.isColumnHidden(idx)
            )
            if remaining_visible == 0:
                action = self.column_actions[column]
                action.blockSignals(True)
                action.setChecked(True)
                action.blockSignals(False)
                return

        self.channels_table.setColumnHidden(column, not visible)
        self._sync_column_actions()

    def _sync_column_actions(self) -> None:
        for idx, action in enumerate(self.column_actions):
            desired = not self.channels_table.isColumnHidden(idx)
            if action.isChecked() != desired:
                action.blockSignals(True)
                action.setChecked(desired)
                action.blockSignals(False)

    def refresh_channels(self):
        """Refresh channels list"""
        channels = self.config_manager.get_channels()
        self._channel_cache = channels
        current_ids = set(channels.keys())

        # Clean up references for removed channels
        for mapping in (self.start_buttons, self.stop_buttons, self.status_items, self.last_status_message):
            for cid in list(mapping.keys()):
                if cid not in current_ids:
                    mapping.pop(cid, None)
        for cid in list(self.pipeline_workers.keys()):
            if cid not in current_ids:
                worker = self.pipeline_workers.pop(cid)
                worker.request_stop()
                worker.deleteLater()
        
        self.start_buttons.clear()
        self.stop_buttons.clear()
        self.status_items.clear()
        
        self.channels_table.setRowCount(len(channels))
        
        for row, (channel_id, data) in enumerate(channels.items()):
            config = data['config']
            pipeline_steps = autobot._sanitize_pipeline_steps(config.get("pipeline_steps"))
            has_cookies = bool(data.get('cookies'))
            is_running = channel_id in self.pipeline_workers
            base_status = tr("✓ Ready") if has_cookies else tr("⚠ No Cookies")
            default_status = tr("⏱ Running...") if is_running else base_status
            status_text = self.last_status_message.get(channel_id, default_status)
            self.last_status_message.setdefault(channel_id, status_text)

            for column_index, column in enumerate(self.column_definitions):
                source = column.get("source")
                if source == "actions":
                    controls_widget = self._create_actions_widget(channel_id, is_running)
                    self.channels_table.setCellWidget(row, column_index, controls_widget)
                    continue

                value = self._resolve_column_value(
                    column,
                    channel_id,
                    config,
                    pipeline_steps,
                    has_cookies,
                    status_text,
                )

                item = QTableWidgetItem(value)
                if value:
                    item.setToolTip(value)
                alignment = column.get("alignment")
                if alignment is not None:
                    item.setTextAlignment(alignment)
                self.channels_table.setItem(row, column_index, item)
                if column["id"] == "status":
                    self.status_items[channel_id] = item

        self.update_bulk_controls()
        self._sync_column_actions()
    
    def on_selection_changed(self):
        """Handle selection change"""
        has_selection = len(self.channels_table.selectedItems()) > 0
        self.edit_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)

    def update_bulk_controls(self):
        channels = getattr(self, "_channel_cache", {})
        any_running = bool(self.pipeline_workers)
        any_startable = False

        for channel_id, data in channels.items():
            if channel_id in self.pipeline_workers:
                continue
            config = data.get('config', {})
            steps = autobot._sanitize_pipeline_steps(config.get("pipeline_steps"))
            if steps.get("scan", True):
                any_startable = True
                break

        self.start_all_btn.setEnabled(any_startable)
        self.stop_all_btn.setEnabled(any_running)

    def start_all_channels(self):
        channels = self._channel_cache or self.config_manager.get_channels()
        if not channels:
            return

        skipped_manual = []
        for channel_id, data in channels.items():
            if channel_id in self.pipeline_workers:
                continue

            config = data.get('config', {})
            steps = autobot._sanitize_pipeline_steps(config.get("pipeline_steps"))

            if not steps.get("scan", True):
                skipped_manual.append(channel_id)
                self.update_channel_status(channel_id, tr("⚠ Requires manual video URL"))
                continue

            self.start_channel_pipeline(channel_id)

        if skipped_manual:
            QMessageBox.information(
                self,
                tr("Manual Start Required"),
                tr("Skipped channels requiring manual video URL:\n{channels}").format(
                    channels="\n".join(skipped_manual)
                ),
            )

        self.update_bulk_controls()

    def stop_all_channels(self):
        if not self.pipeline_workers:
            return

        for channel_id in list(self.pipeline_workers.keys()):
            self.stop_channel_pipeline(channel_id)
        self.update_bulk_controls()

    def start_channel_pipeline(self, channel_id: str):
        if channel_id in self.pipeline_workers:
            QMessageBox.information(
                self,
                tr("Pipeline Running"),
                tr("Channel {channel_id} is already running").format(channel_id=channel_id),
            )
            return

        channels = self.config_manager.get_channels()
        channel_data = channels.get(channel_id)
        if not channel_data:
            QMessageBox.warning(
                self,
                tr("Missing Configuration"),
                tr("Could not find configuration for {channel_id}").format(channel_id=channel_id),
            )
            return

        pipeline_steps = autobot._sanitize_pipeline_steps(
            channel_data['config'].get("pipeline_steps")
        )

        manual_video_url = None
        if not pipeline_steps.get("scan", True):
            video_url, ok = QInputDialog.getText(
                self,
                tr("Manual Video URL"),
                tr("Scan step is disabled. Provide a YouTube video URL to process:"),
            )
            if not ok or not video_url.strip():
                return
            manual_video_url = video_url.strip()

        if pipeline_steps.get("upload", True) and not channel_data['cookies']:
            reply = QMessageBox.question(
                self,
                tr("Missing Cookies"),
                tr("This channel has no cookies configured. Continue anyway?"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        worker = ChannelPipelineWorker(channel_id, self.config_manager, video_url=manual_video_url)
        worker.progress.connect(self.on_worker_progress)
        worker.finished.connect(self.on_worker_finished)

        self.pipeline_workers[channel_id] = worker

        if channel_id in self.start_buttons:
            self.start_buttons[channel_id].setEnabled(False)
        if channel_id in self.stop_buttons:
            self.stop_buttons[channel_id].setEnabled(True)

        self.update_channel_status(channel_id, tr("Starting pipeline..."))
        worker.start()
        self.update_bulk_controls()

    def stop_channel_pipeline(self, channel_id: str):
        worker = self.pipeline_workers.get(channel_id)
        if not worker:
            return
        worker.request_stop()
        if channel_id in self.stop_buttons:
            self.stop_buttons[channel_id].setEnabled(False)
        self.update_channel_status(channel_id, tr("Stopping pipeline..."))
        self.update_bulk_controls()

    def on_worker_progress(self, channel_id: str, message: str):
        self.update_channel_status(channel_id, message)

    def on_worker_finished(self, channel_id: str, success: bool, message: str):
        worker = self.pipeline_workers.pop(channel_id, None)
        if worker:
            worker.deleteLater()

        if channel_id in self.start_buttons:
            self.start_buttons[channel_id].setEnabled(True)
        if channel_id in self.stop_buttons:
            self.stop_buttons[channel_id].setEnabled(False)

        status_prefix = "✅" if success else "⚠"
        final_message = (
            f"{status_prefix} {message}"
            if message
            else (tr("✅ Done") if success else tr("⚠ Failed"))
        )
        self.update_channel_status(channel_id, final_message)
        self.update_bulk_controls()

    def update_channel_status(self, channel_id: str, message: str):
        self.last_status_message[channel_id] = message
        status_item = self.status_items.get(channel_id)
        if status_item:
            status_item.setText(message)
    
    def add_channel(self):
        """Add new channel"""
        dialog = ChannelDialog(self.config_manager, parent=self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_channels()
    
    def edit_channel(self):
        """Edit selected channel"""
        current_row = self.channels_table.currentRow()
        if current_row >= 0:
            channel_id = self.channels_table.item(current_row, 0).text()
            dialog = ChannelDialog(self.config_manager, channel_id, parent=self)
            if dialog.exec() == QDialog.Accepted:
                self.refresh_channels()
    
    def delete_channel(self):
        """Delete selected channel"""
        current_row = self.channels_table.currentRow()
        if current_row >= 0:
            channel_id = self.channels_table.item(current_row, 0).text()
            
            reply = QMessageBox.question(
                self,
                tr("Delete Channel"),
                tr("Are you sure you want to delete channel '{channel_id}'?\nThis action cannot be undone.").format(
                    channel_id=channel_id
                ),
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                if self.config_manager.delete_channel(channel_id):
                    self.refresh_channels()
                    QMessageBox.information(
                        self,
                        tr("Success"),
                        tr("Channel deleted successfully!"),
                    )
                else:
                    QMessageBox.critical(self, tr("Error"), tr("Failed to delete channel!"))

    def prepare_shutdown(self) -> None:
        for worker in list(self.pipeline_workers.values()):
            try:
                worker.request_stop()
            except Exception:
                pass

        for channel_id, worker in list(self.pipeline_workers.items()):
            try:
                if not worker.wait(5000):
                    worker.terminate()
                    worker.wait(1000)
            except Exception:
                pass
            finally:
                self.pipeline_workers.pop(channel_id, None)


# Export the additional classes for the main file
__all__ = ['ChannelDialog', 'ChannelsTab']