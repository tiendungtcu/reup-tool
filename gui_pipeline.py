import sys
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
import subprocess
import threading
import time
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLineEdit, QTextEdit, QComboBox, QSpinBox, QCheckBox, QPushButton,
    QLabel, QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QGroupBox, QScrollArea, QProgressBar, QStatusBar, QMenuBar, QMenu,
    QDialog, QDialogButtonBox, QGridLayout, QFrame, QListWidget, QListWidgetItem,
    QSizePolicy, QToolButton, QButtonGroup
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSettings, QObject
from PySide6.QtGui import QIcon, QFont, QPixmap, QAction, QTextCursor


class PipelineWorker(QThread):
    """Worker thread for running pipeline operations"""
    
    progress_updated = Signal(str, str)  # channel_id, message
    finished = Signal(str, bool, str)  # channel_id, success, final_message
    
    def __init__(self, channel_id: str, operation: str, config_manager, video_url: str = None):
        super().__init__()
        self.channel_id = channel_id
        self.operation = operation
        self.config_manager = config_manager
        self.video_url = video_url
        self._is_cancelled = False
        
    def run(self):
        """Run the pipeline operation"""
        try:
            self.progress_updated.emit(self.channel_id, f"Starting {self.operation}...")
            
            if self._is_cancelled:
                return
                
            if self.operation == "download":
                self._run_download()
            elif self.operation == "render":
                self._run_render()
            elif self.operation == "upload":
                self._run_upload()
            elif self.operation == "full":
                self._run_full_pipeline()
            elif self.operation == "test_cookies":
                self._test_cookies()
                
            if not self._is_cancelled:
                self.finished.emit(self.channel_id, True, f"{self.operation.title()} completed successfully!")
                
        except Exception as e:
            self.progress_updated.emit(self.channel_id, f"Error: {str(e)}")
            self.finished.emit(self.channel_id, False, f"Error in {self.operation}: {str(e)}")
    
    def cancel(self):
        """Cancel the operation"""
        self._is_cancelled = True
        self.progress_updated.emit(self.channel_id, "Cancelling operation...")
        self.finished.emit(self.channel_id, False, "Operation cancelled by user")
    
    def _run_download(self):
        """Simulate/run video download"""
        steps = [
            "Checking YouTube URL...",
            "Fetching video metadata...",
            "Starting download...",
            "Download progress: 25%",
            "Download progress: 50%",
            "Download progress: 75%",
            "Download progress: 100%",
            "Download completed!"
        ]
        
        for i, step in enumerate(steps):
            if self._is_cancelled:
                return
            self.progress_updated.emit(self.channel_id, step)
            time.sleep(1)  # Simulate processing time
    
    def _run_render(self):
        """Simulate/run video rendering"""
        steps = [
            "Checking video file...",
            "Analyzing video duration...",
            "Applying render settings...",
            "Rendering progress: 20%",
            "Rendering progress: 40%",
            "Rendering progress: 60%",
            "Rendering progress: 80%",
            "Rendering progress: 100%",
            "Render completed!"
        ]
        
        for step in steps:
            if self._is_cancelled:
                return
            self.progress_updated.emit(self.channel_id, step)
            time.sleep(1.5)  # Simulate processing time
    
    def _run_upload(self):
        """Simulate/run TikTok upload"""
        channels = self.config_manager.get_channels()
        if self.channel_id not in channels:
            raise Exception("Channel not found")
            
        config = channels[self.channel_id]['config']
        upload_method = config.get('upload_method', 'api')
        
        if upload_method == "api":
            steps = [
                "Initializing API upload...",
                "Validating cookies...",
                "Generating signatures...",
                "Uploading video file...",
                "Upload progress: 30%",
                "Upload progress: 60%",
                "Upload progress: 90%",
                "Publishing video...",
                "API upload completed!"
            ]
        else:
            steps = [
                "Starting browser...",
                "Loading TikTok Studio...",
                "Uploading video file...",
                "Waiting for processing...",
                "Adding description...",
                "Configuring settings...",
                "Publishing video...",
                "Browser upload completed!"
            ]
        
        for step in steps:
            if self._is_cancelled:
                return
            self.progress_updated.emit(self.channel_id, step)
            time.sleep(2)  # Simulate processing time
    
    def _run_full_pipeline(self):
        """Run the complete pipeline"""
        if self._is_cancelled:
            return
        self._run_download()
        
        if self._is_cancelled:
            return
        time.sleep(0.5)
        self._run_render()
        
        if self._is_cancelled:
            return
        time.sleep(0.5)
        self._run_upload()
    
    def _test_cookies(self):
        """Test TikTok cookies validity"""
        steps = [
            "Loading cookies...",
            "Testing authentication...",
            "Checking session validity...",
            "Verifying upload permissions...",
        ]
        
        for step in steps:
            if self._is_cancelled:
                return
            self.progress_updated.emit(self.channel_id, step)
            time.sleep(1)
        
        # Simulate cookie validation result
        import random
        if random.choice([True, False, True]):  # 2/3 chance of success
            self.progress_updated.emit(self.channel_id, "✅ Cookies are valid!")
        else:
            raise Exception("Cookies are invalid or expired")


class PipelineControlTab(QWidget):
    """Tab for controlling pipeline operations"""
    
    def __init__(self, config_manager):
        super().__init__()
        self.config_manager = config_manager
        self.workers = {}
        self.setup_ui()
        self.refresh_channels()
        
        # Timer for periodic refresh
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_channels)
        self.refresh_timer.start(30000)  # Refresh every 30 seconds
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # Control panel
        control_panel = self.create_control_panel()
        layout.addWidget(control_panel)
        
        # Channels operation panel
        operations_panel = self.create_operations_panel()
        layout.addWidget(operations_panel)
        
        # Log panel
        log_panel = self.create_log_panel()
        layout.addWidget(log_panel)
        
        self.setLayout(layout)
    
    def create_control_panel(self):
        """Create the main control panel"""
        group = QGroupBox("Global Controls")
        layout = QHBoxLayout()
        
        # Global operations
        self.start_all_btn = QPushButton("Start All Channels")
        self.start_all_btn.clicked.connect(self.start_all_channels)
        layout.addWidget(self.start_all_btn)
        
        self.stop_all_btn = QPushButton("Stop All Operations")
        self.stop_all_btn.clicked.connect(self.stop_all_operations)
        layout.addWidget(self.stop_all_btn)
        
        layout.addStretch()
        
        # Global settings
        self.auto_refresh_check = QCheckBox("Auto Refresh")
        self.auto_refresh_check.setChecked(True)
        self.auto_refresh_check.toggled.connect(self.toggle_auto_refresh)
        layout.addWidget(self.auto_refresh_check)
        
        self.refresh_btn = QPushButton("Refresh Now")
        self.refresh_btn.clicked.connect(self.refresh_channels)
        layout.addWidget(self.refresh_btn)
        
        group.setLayout(layout)
        return group
    
    def create_operations_panel(self):
        """Create the operations panel with channels"""
        group = QGroupBox("Channel Operations")
        layout = QVBoxLayout()
        
        # Channels table
        self.channels_table = QTableWidget()
        self.channels_table.setColumnCount(8)
        self.channels_table.setHorizontalHeaderLabels([
            "Channel", "Status", "Last Operation", "Progress", "Download", "Render", "Upload", "Full Pipeline"
        ])
        
        # Configure table
        header = self.channels_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        for i in range(4, 8):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        
        self.channels_table.setAlternatingRowColors(True)
        self.channels_table.setSelectionBehavior(QTableWidget.SelectRows)
        
        layout.addWidget(self.channels_table)
        
        # Manual operation controls
        manual_layout = QHBoxLayout()
        
        manual_layout.addWidget(QLabel("Manual Operations:"))
        
        self.video_url_edit = QLineEdit()
        self.video_url_edit.setPlaceholderText("Enter YouTube video URL for manual processing...")
        manual_layout.addWidget(self.video_url_edit)
        
        self.process_manual_btn = QPushButton("Process URL")
        self.process_manual_btn.clicked.connect(self.process_manual_url)
        manual_layout.addWidget(self.process_manual_btn)
        
        layout.addLayout(manual_layout)
        
        group.setLayout(layout)
        return group
    
    def create_log_panel(self):
        """Create the log panel"""
        group = QGroupBox("Operation Logs")
        layout = QVBoxLayout()
        
        # Log controls
        log_controls = QHBoxLayout()
        
        self.clear_logs_btn = QPushButton("Clear Logs")
        self.clear_logs_btn.clicked.connect(self.clear_logs)
        log_controls.addWidget(self.clear_logs_btn)
        
        self.save_logs_btn = QPushButton("Save Logs")
        self.save_logs_btn.clicked.connect(self.save_logs)
        log_controls.addWidget(self.save_logs_btn)
        
        log_controls.addStretch()
        
        self.auto_scroll_check = QCheckBox("Auto Scroll")
        self.auto_scroll_check.setChecked(True)
        log_controls.addWidget(self.auto_scroll_check)
        
        layout.addLayout(log_controls)
        
        # Log display
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setMaximumHeight(200)
        layout.addWidget(self.log_display)
        
        group.setLayout(layout)
        return group
    
    def refresh_channels(self):
        """Refresh the channels list"""
        channels = self.config_manager.get_channels()
        
        self.channels_table.setRowCount(len(channels))
        
        for row, (channel_id, data) in enumerate(channels.items()):
            config = data['config']
            channel_name = config.get('channel_name', channel_id)
            
            # Channel name
            self.channels_table.setItem(row, 0, QTableWidgetItem(channel_name))
            
            # Status
            status = "Running" if channel_id in self.workers else "Idle"
            status_color = "green" if status == "Idle" else "orange"
            status_item = QTableWidgetItem(status)
            self.channels_table.setItem(row, 1, status_item)
            
            # Last operation
            last_op = getattr(self, f'last_op_{channel_id}', 'None')
            self.channels_table.setItem(row, 2, QTableWidgetItem(last_op))
            
            # Progress
            progress = getattr(self, f'progress_{channel_id}', '')
            self.channels_table.setItem(row, 3, QTableWidgetItem(progress))
            
            # Operation buttons
            for col, operation in enumerate(['download', 'render', 'upload', 'full'], 4):
                btn = QPushButton(operation.title())
                btn.clicked.connect(lambda checked, cid=channel_id, op=operation: self.start_operation(cid, op))
                btn.setEnabled(channel_id not in self.workers)
                self.channels_table.setCellWidget(row, col, btn)
    
    def start_operation(self, channel_id: str, operation: str):
        """Start a pipeline operation for a channel"""
        if channel_id in self.workers:
            QMessageBox.warning(self, "Warning", f"Channel {channel_id} is already running an operation!")
            return
        
        channels = self.config_manager.get_channels()
        if channel_id not in channels:
            QMessageBox.critical(self, "Error", f"Channel {channel_id} not found!")
            return
        
        # Create and start worker
        video_url = self.video_url_edit.text().strip() if operation != 'test_cookies' else None
        worker = PipelineWorker(channel_id, operation, self.config_manager, video_url)
        worker.progress_updated.connect(self.on_progress_updated)
        worker.finished.connect(self.on_operation_finished)
        
        self.workers[channel_id] = worker
        worker.start()
        
        # Update UI
        setattr(self, f'last_op_{channel_id}', operation)
        self.refresh_channels()
        self.log_message(f"Started {operation} for {channel_id}")
    
    def start_all_channels(self):
        """Start full pipeline for all channels"""
        channels = self.config_manager.get_channels()
        
        if not channels:
            QMessageBox.information(self, "Info", "No channels configured!")
            return
        
        reply = QMessageBox.question(
            self, "Start All Channels",
            f"Start full pipeline for all {len(channels)} channels?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            for channel_id in channels:
                if channel_id not in self.workers:
                    self.start_operation(channel_id, 'full')
    
    def stop_all_operations(self):
        """Stop all running operations"""
        if not self.workers:
            QMessageBox.information(self, "Info", "No operations running!")
            return
        
        reply = QMessageBox.question(
            self, "Stop All Operations",
            f"Stop all {len(self.workers)} running operations?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            for worker in list(self.workers.values()):
                worker.cancel()
    
    def process_manual_url(self):
        """Process a manual YouTube URL"""
        url = self.video_url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "Warning", "Please enter a YouTube URL!")
            return
        
        # Get current selected channel or show dialog to select
        current_row = self.channels_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "Warning", "Please select a channel first!")
            return
        
        channel_name = self.channels_table.item(current_row, 0).text()
        channels = self.config_manager.get_channels()
        
        # Find channel ID by name
        channel_id = None
        for cid, data in channels.items():
            if data['config'].get('channel_name', cid) == channel_name:
                channel_id = cid
                break
        
        if channel_id:
            self.start_operation(channel_id, 'full')
        else:
            QMessageBox.critical(self, "Error", "Selected channel not found!")
    
    def on_progress_updated(self, channel_id: str, message: str):
        """Handle progress updates"""
        setattr(self, f'progress_{channel_id}', message)
        self.refresh_channels()
        self.log_message(f"[{channel_id}] {message}")
    
    def on_operation_finished(self, channel_id: str, success: bool, message: str):
        """Handle operation completion"""
        if channel_id in self.workers:
            del self.workers[channel_id]
        
        setattr(self, f'progress_{channel_id}', message)
        
        status = "✅" if success else "❌"
        self.log_message(f"{status} [{channel_id}] {message}")
        
        self.refresh_channels()
    
    def toggle_auto_refresh(self, enabled: bool):
        """Toggle auto refresh"""
        if enabled:
            self.refresh_timer.start(30000)
        else:
            self.refresh_timer.stop()
    
    def log_message(self, message: str):
        """Add message to log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"
        
        self.log_display.append(formatted_message)
        
        if self.auto_scroll_check.isChecked():
            cursor = self.log_display.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.log_display.setTextCursor(cursor)
    
    def clear_logs(self):
        """Clear the log display"""
        self.log_display.clear()
        self.log_message("Logs cleared")
    
    def save_logs(self):
        """Save logs to file"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Logs", f"autobot_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            "Text Files (*.txt)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(self.log_display.toPlainText())
                QMessageBox.information(self, "Success", f"Logs saved to {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save logs: {str(e)}")


# Export the class
__all__ = ['PipelineControlTab', 'PipelineWorker']