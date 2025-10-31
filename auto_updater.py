"""Auto-update checker for AutoBot GUI"""

import json
import requests
import threading
import zipfile
import tarfile
import shutil
import platform
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, Callable
from packaging import version

from PySide6.QtCore import QObject, Signal, QTimer, QThread, Qt
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from app_paths import resource_path
from localization import tr


class AutoUpdater(QObject):
    """Check for application updates periodically"""
    
    update_available = Signal(dict)  # Emits update info: {version, url, notes}
    download_progress = Signal(int, int)  # current, total bytes
    download_complete = Signal(str)  # file_path
    download_error = Signal(str)  # error_message
    
    # Update check configuration
    CURRENT_VERSION = "1.0.0"
    UPDATE_CHECK_URL = "https://api.github.com/repos/tiendungtcu/reup-tool/releases/latest"
    CHECK_INTERVAL_HOURS = 1
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.last_check_file = Path.home() / ".autobot_gui" / "last_update_check.json"
        self.last_check_file.parent.mkdir(parents=True, exist_ok=True)
        self.download_dir = Path.home() / ".autobot_gui" / "updates"
        self.download_dir.mkdir(parents=True, exist_ok=True)
        
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
        """Extract the appropriate download URL from release assets based on current platform"""
        assets = release_data.get('assets', [])
        current_platform = platform.system()
        
        # Define platform-specific asset patterns
        platform_patterns = {
            'Darwin': ['.dmg', '.pkg', 'macos', 'darwin', 'osx'],  # macOS
            'Windows': ['.exe', '.msi', 'windows', 'win64', 'win32'],  # Windows
            'Linux': ['.tar.gz', '.tgz', '.deb', '.rpm', '.appimage', 'linux']  # Linux
        }
        
        # Get patterns for current platform
        preferred_patterns = platform_patterns.get(current_platform, [])
        
        # First pass: Look for exact platform matches
        for asset in assets:
            name = asset.get('name', '').lower()
            
            # Check if asset matches current platform
            for pattern in preferred_patterns:
                if pattern in name:
                    download_url = asset.get('browser_download_url')
                    if download_url:
                        print(f"Found platform-specific asset for {current_platform}: {asset.get('name')}")
                        return download_url
        
        # Second pass: Look for generic archives if no platform-specific found
        generic_patterns = ['.zip', '.tar.gz']
        for asset in assets:
            name = asset.get('name', '').lower()
            for pattern in generic_patterns:
                if pattern in name:
                    download_url = asset.get('browser_download_url')
                    if download_url:
                        print(f"Found generic asset for {current_platform}: {asset.get('name')}")
                        return download_url
        
        # Fallback to source code archives
        fallback_url = None
        if current_platform == 'Linux':
            fallback_url = release_data.get('tarball_url')
        else:
            fallback_url = release_data.get('zipball_url') or release_data.get('tarball_url')
        
        if fallback_url:
            print(f"Using fallback source archive for {current_platform}")
        
        return fallback_url
        
    def check_now(self):
        """Force an immediate update check"""
        self._check_for_updates_async()
    
    def download_update(self, download_url: str, version: str) -> None:
        """Download and extract the update in a background thread"""
        thread = threading.Thread(
            target=self._download_and_extract,
            args=(download_url, version),
            daemon=True
        )
        thread.start()
    
    def _download_and_extract(self, download_url: str, version: str) -> None:
        """Download and extract the update file"""
        try:
            # Determine file extension from URL
            file_ext = self._get_file_extension(download_url)
            download_file = self.download_dir / f"autobot_gui_{version}{file_ext}"
            
            # Download the file with progress tracking
            response = requests.get(download_url, stream=True, timeout=30)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0
            
            with open(download_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        self.download_progress.emit(downloaded_size, total_size)
            
            # Handle based on file type
            if file_ext in ['.dmg', '.pkg', '.exe', '.msi', '.deb', '.rpm', '.appimage']:
                # For installers, just keep the file and let user run it
                self.download_complete.emit(str(download_file))
            else:
                # Extract archives and prepare for auto-update
                extract_dir = self.download_dir / f"autobot_gui_{version}"
                extract_dir.mkdir(exist_ok=True)
                
                if file_ext == '.zip':
                    with zipfile.ZipFile(download_file, 'r') as zip_ref:
                        zip_ref.extractall(extract_dir)
                elif file_ext in ['.tar.gz', '.tgz']:
                    with tarfile.open(download_file, 'r:gz') as tar_ref:
                        tar_ref.extractall(extract_dir)
                elif file_ext == '.tar':
                    with tarfile.open(download_file, 'r') as tar_ref:
                        tar_ref.extractall(extract_dir)
                
                # Emit success signal with the extracted directory path
                self.download_complete.emit(str(extract_dir))
            
        except Exception as e:
            self.download_error.emit(str(e))
    
    def _get_application_path(self) -> Path:
        """Get the path to the current application directory"""
        if getattr(sys, 'frozen', False):
            # Running as compiled executable
            if platform.system() == "Darwin":
                # macOS app bundle
                app_path = Path(sys.executable)
                # Navigate up to .app bundle
                while app_path.suffix != '.app' and app_path.parent != app_path:
                    app_path = app_path.parent
                if app_path.suffix == '.app':
                    return app_path
                return Path(sys.executable).parent
            else:
                # Windows/Linux executable
                return Path(sys.executable).parent
        else:
            # Running as script
            return Path(__file__).parent
    
    def prepare_auto_update(self, extract_dir: str) -> Optional[str]:
        """Prepare update script and return script path if successful"""
        try:
            extract_path = Path(extract_dir)
            app_path = self._get_application_path()
            system = platform.system()
            
            # Create update script
            script_path = self.download_dir / f"update_{platform.system().lower()}.sh"
            
            if system == "Darwin":
                # macOS update script
                script_content = f'''#!/bin/bash
# AutoBot GUI Update Script

echo "Waiting for application to close..."
sleep 2

# Backup current installation
BACKUP_DIR="{app_path}.backup.$(date +%Y%m%d_%H%M%S)"
echo "Creating backup at $BACKUP_DIR"
cp -R "{app_path}" "$BACKUP_DIR"

# Find the new app bundle in extracted directory
NEW_APP=$(find "{extract_path}" -name "*.app" -type d -maxdepth 2 | head -n 1)

if [ -z "$NEW_APP" ]; then
    echo "Error: No .app bundle found in extracted files"
    echo "Attempting to copy all files..."
    # Try copying all Python files
    rsync -av --exclude='*.pyc' --exclude='__pycache__' "{extract_path}/" "{app_path}/"
else
    echo "Found new app: $NEW_APP"
    echo "Removing old application..."
    rm -rf "{app_path}"
    
    echo "Installing new version..."
    cp -R "$NEW_APP" "{app_path}"
fi

echo "Update complete!"
echo "Starting application..."
open "{app_path}"

# Clean up
sleep 2
rm -f "$0"
'''
            elif system == "Windows":
                # Windows update script
                script_path = self.download_dir / "update_windows.bat"
                script_content = f'''@echo off
echo Waiting for application to close...
timeout /t 2 /nobreak >nul

echo Creating backup...
set BACKUP_DIR={app_path}.backup.%date:~-4,4%%date:~-10,2%%date:~-7,2%_%time:~0,2%%time:~3,2%%time:~6,2%
xcopy /E /I /H /Y "{app_path}" "%BACKUP_DIR%"

echo Installing new version...
xcopy /E /I /H /Y "{extract_path}\\*" "{app_path}\\"

echo Update complete!
echo Starting application...
start "" "{app_path}\\autobot_gui.exe"

timeout /t 2 /nobreak >nul
del "%~f0"
'''
            else:
                # Linux update script
                script_content = f'''#!/bin/bash
# AutoBot GUI Update Script

echo "Waiting for application to close..."
sleep 2

# Backup current installation
BACKUP_DIR="{app_path}.backup.$(date +%Y%m%d_%H%M%S)"
echo "Creating backup at $BACKUP_DIR"
cp -R "{app_path}" "$BACKUP_DIR"

echo "Installing new version..."
rsync -av --exclude='*.pyc' --exclude='__pycache__' "{extract_path}/" "{app_path}/"

echo "Update complete!"
echo "Starting application..."
cd "{app_path}"
./autobot_gui &

# Clean up
sleep 2
rm -f "$0"
'''
            
            # Write script file
            with open(script_path, 'w') as f:
                f.write(script_content)
            
            # Make script executable on Unix systems
            if system in ["Darwin", "Linux"]:
                os.chmod(script_path, 0o755)
            
            return str(script_path)
            
        except Exception as e:
            print(f"Failed to prepare update script: {e}")
            return None
    
    def _get_file_extension(self, url: str) -> str:
        """Extract file extension from URL based on platform preferences"""
        url_lower = url.lower()
        current_platform = platform.system()
        
        # Platform-specific extension priorities
        if current_platform == 'Darwin':  # macOS
            if '.dmg' in url_lower:
                return '.dmg'
            elif '.pkg' in url_lower:
                return '.pkg'
        elif current_platform == 'Windows':
            if '.exe' in url_lower:
                return '.exe'
            elif '.msi' in url_lower:
                return '.msi'
        elif current_platform == 'Linux':
            if '.deb' in url_lower:
                return '.deb'
            elif '.rpm' in url_lower:
                return '.rpm'
            elif '.appimage' in url_lower:
                return '.appimage'
        
        # Generic archive formats (cross-platform)
        if '.tar.gz' in url_lower or '.tgz' in url_lower:
            return '.tar.gz'
        elif '.zip' in url_lower:
            return '.zip'
        elif '.tar' in url_lower:
            return '.tar'
        
        # Default fallback based on platform
        if current_platform == 'Darwin':
            return '.dmg'
        elif current_platform == 'Windows':
            return '.exe'
        else:  # Linux and others
            return '.tar.gz'


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
        download_url = self.update_info.get('download_url', '')
        
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
        
        # Change button text and info based on whether we have a download URL
        if download_url:
            self.setInformativeText(tr("Would you like to download and install the update now?"))
        else:
            self.setInformativeText(tr("Would you like to visit the download page?"))
        
        self.setStandardButtons(QMessageBox.Yes | QMessageBox.No | QMessageBox.Ignore)
        self.setDefaultButton(QMessageBox.Yes)
        
        # Store URLs for later use
        self._download_url = download_url
        self._release_url = url
        
    def get_download_url(self) -> str:
        return self._download_url
    
    def get_release_url(self) -> str:
        return self._release_url


class UpdateDownloadDialog(QProgressDialog):
    """Progress dialog for downloading updates"""
    
    def __init__(self, version: str, parent=None):
        super().__init__(parent)
        self.version = version
        self.setWindowTitle(tr("Downloading Update"))
        self.setLabelText(tr("Downloading version {version}...").format(version=version))
        self.setMinimum(0)
        self.setMaximum(100)
        self.setValue(0)
        self.setAutoClose(False)
        self.setAutoReset(False)
        self.setCancelButton(None)  # Can't cancel download
        self.setWindowModality(Qt.ApplicationModal)  # Application modal
    
    def update_progress(self, current: int, total: int):
        """Update the progress bar"""
        if total > 0:
            percentage = int((current / total) * 100)
            self.setValue(percentage)
            
            # Update label with MB downloaded
            current_mb = current / (1024 * 1024)
            total_mb = total / (1024 * 1024)
            self.setLabelText(
                tr("Downloading version {version}...\n{current:.1f} MB / {total:.1f} MB")
                .format(version=self.version, current=current_mb, total=total_mb)
            )
