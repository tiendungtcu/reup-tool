"""Auto-update checker for AutoBot GUI"""

import json
import requests
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
from packaging import version

from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtWidgets import QMessageBox

from app_paths import resource_path
from localization import tr


class AutoUpdater(QObject):
    """Check for application updates periodically"""
    
    update_available = Signal(dict)  # Emits update info: {version, url, notes}
    
    # Update check configuration
    CURRENT_VERSION = "1.0.0"
    UPDATE_CHECK_URL = "https://api.github.com/repos/tiendungtcu/reup-tool/releases/latest"
    CHECK_INTERVAL_HOURS = 1
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.last_check_file = Path.home() / ".autobot_gui" / "last_update_check.json"
        self.last_check_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Timer for periodic checks
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._check_for_updates_async)
        self.timer.setInterval(self.CHECK_INTERVAL_HOURS * 3600 * 1000)  # Convert hours to milliseconds
        
    def start(self):
        """Start the auto-update checker"""
        # Check immediately on start if needed
        if self._should_check_now():
            self._check_for_updates_async()
        
        # Start periodic timer
        self.timer.start()
        
    def stop(self):
        """Stop the auto-update checker"""
        self.timer.stop()
        
    def _should_check_now(self) -> bool:
        """Determine if we should check for updates now"""
        if not self.last_check_file.exists():
            return True
            
        try:
            with open(self.last_check_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                last_check = datetime.fromisoformat(data.get('last_check', ''))
                # Check if more than CHECK_INTERVAL_HOURS has passed
                return datetime.now() - last_check > timedelta(hours=self.CHECK_INTERVAL_HOURS)
        except (json.JSONDecodeError, ValueError, KeyError):
            return True
            
    def _save_last_check(self):
        """Save the timestamp of the last update check"""
        try:
            with open(self.last_check_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'last_check': datetime.now().isoformat(),
                    'version': self.CURRENT_VERSION
                }, f)
        except Exception:
            pass  # Silent fail if we can't save
            
    def _check_for_updates_async(self):
        """Check for updates in a background thread"""
        thread = threading.Thread(target=self._check_for_updates, daemon=True)
        thread.start()
        
    def _check_for_updates(self):
        """Check for updates from GitHub releases"""
        try:
            response = requests.get(
                self.UPDATE_CHECK_URL,
                timeout=10,
                headers={'Accept': 'application/vnd.github.v3+json'}
            )
            response.raise_for_status()
            
            release_data = response.json()
            latest_version = release_data.get('tag_name', '').lstrip('v')
            
            # Save check timestamp
            self._save_last_check()
            
            # Compare versions
            if latest_version and self._is_newer_version(latest_version):
                update_info = {
                    'version': latest_version,
                    'url': release_data.get('html_url', ''),
                    'notes': release_data.get('body', 'No release notes available.'),
                    'download_url': self._get_download_url(release_data),
                    'published_at': release_data.get('published_at', '')
                }
                self.update_available.emit(update_info)
                
        except Exception as e:
            # Silent fail - don't interrupt user experience
            print(f"Update check failed: {e}")
            
    def _is_newer_version(self, latest: str) -> bool:
        """Compare version strings to determine if update is available"""
        try:
            return version.parse(latest) > version.parse(self.CURRENT_VERSION)
        except Exception:
            return False
            
    def _get_download_url(self, release_data: Dict[str, Any]) -> Optional[str]:
        """Extract the appropriate download URL from release assets"""
        assets = release_data.get('assets', [])
        
        # Try to find a suitable asset (installer, zip, etc.)
        for asset in assets:
            name = asset.get('name', '').lower()
            if any(ext in name for ext in ['.zip', '.tar.gz', '.dmg', '.exe', '.pkg']):
                return asset.get('browser_download_url')
                
        # Fallback to tarball or zipball
        return release_data.get('zipball_url') or release_data.get('tarball_url')
        
    def check_now(self):
        """Force an immediate update check"""
        self._check_for_updates_async()


class UpdateNotificationDialog(QMessageBox):
    """Dialog to notify user about available updates"""
    
    def __init__(self, update_info: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.update_info = update_info
        self.setup_ui()
        
    def setup_ui(self):
        self.setWindowTitle(tr("Update Available"))
        self.setIcon(QMessageBox.Information)
        
        version_str = self.update_info.get('version', 'Unknown')
        url = self.update_info.get('url', '')
        notes = self.update_info.get('notes', '')
        
        # Truncate notes if too long
        if len(notes) > 500:
            notes = notes[:500] + "..."
            
        whats_new_label = tr("What's New:")
        message = (
            f"<h3>{tr('A new version of AutoBot GUI is available!')}</h3>"
            f"<p><b>{tr('New Version:')}</b> {version_str}<br>"
            f"<b>{tr('Current Version:')}</b> {AutoUpdater.CURRENT_VERSION}</p>"
            f"<p><b>{whats_new_label}</b></p>"
            f"<pre>{notes}</pre>"
        )
        
        self.setText(message)
        self.setInformativeText(tr("Would you like to visit the download page?"))
        
        self.setStandardButtons(QMessageBox.Yes | QMessageBox.No | QMessageBox.Ignore)
        self.setDefaultButton(QMessageBox.Yes)
        
        # Store URL for later use
        self._download_url = url
        
    def get_download_url(self) -> str:
        return self._download_url
