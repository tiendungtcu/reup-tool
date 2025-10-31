# Auto-Update Feature Implementation

## Overview
The AutoBot GUI application now includes a comprehensive auto-update feature that automatically checks for new versions, downloads updates, and provides easy installation options for users.

## Features

### 1. Automatic Update Checking
- **Startup Check**: Checks for updates when the application starts
- **Hourly Checks**: Automatically checks every hour in the background
- **GitHub Integration**: Fetches latest release information from GitHub repository
- **Version Comparison**: Uses semantic versioning to determine if an update is available

### 2. Smart Download Management
- **Automatic Download**: When user clicks "Yes" on update notification, the download starts automatically
- **Progress Tracking**: Shows real-time download progress with MB downloaded/total
- **Background Download**: Downloads happen in a separate thread to avoid UI blocking
- **Multiple Format Support**: Handles `.zip`, `.tar.gz`, `.dmg`, `.pkg`, `.exe` files

### 3. Platform-Specific Installation
The update system provides tailored installation experiences for each platform:

#### macOS
- **DMG/PKG Installers**: 
  - Shows "Open" button to launch installer immediately
  - Shows "Show in Finder" button to open download location
  - Automatically uses macOS `open` command
  
#### Windows
- **EXE Installers**:
  - Shows "Run Installer" button to launch immediately
  - Shows "Show in Explorer" button to open download location
  - Automatically launches installer when requested

#### Linux & Archives
- **ZIP/TAR.GZ**:
  - Automatically extracts to update folder
  - Shows "Open Folder" button to view extracted files
  - Provides instructions for manual installation

### 4. User Interface
- **Update Notification Dialog**: Shows version info, release notes, and options
- **Download Progress Dialog**: Displays download status with percentage and MB progress
- **Success Dialog**: Platform-specific instructions and action buttons
- **Error Handling**: Clear error messages if download fails

### 5. Localization
All user-facing messages are fully localized in English and Vietnamese:
- Update notification messages
- Download progress indicators
- Success/error messages
- Button labels
- Installation instructions

## Technical Implementation

### Files Modified/Created

#### `auto_updater.py`
- **AutoUpdater Class**:
  - `update_available` signal: Emits when new version is found
  - `download_progress` signal: Emits (current_bytes, total_bytes) during download
  - `download_complete` signal: Emits file path when download succeeds
  - `download_error` signal: Emits error message if download fails
  - `download_update()`: Starts background download
  - `_download_and_extract()`: Downloads file with progress tracking and extracts archives

- **UpdateNotificationDialog Class**:
  - Shows update information and release notes
  - Provides Yes/No/Ignore buttons
  - Returns download URL or release page URL

- **UpdateDownloadDialog Class**:
  - QProgressDialog showing download progress
  - Updates with percentage and MB downloaded
  - Cannot be cancelled (ensures complete download)

#### `gui_main.py`
- **Auto-Updater Integration**:
  - `_setup_auto_updater()`: Initializes AutoUpdater and connects signals
  - `_on_update_available()`: Handles update notification and starts download
  - `_on_download_progress()`: Updates progress dialog
  - `_on_download_complete()`: Shows platform-specific success dialog
  - `_on_download_error()`: Shows error dialog

#### `resources/i18n/translations.json`
Added translations for:
- "Would you like to download and install the update now?"
- "Downloading Update"
- "Downloading version {version}..."
- "Downloading version {version}...\n{current:.1f} MB / {total:.1f} MB"
- "Failed to download update:\n{error}"
- "Update Downloaded"
- "Update downloaded successfully!"
- Platform-specific installer instructions
- Button labels (Open, Run Installer, Show in Finder, etc.)

## Configuration

### Update Check Settings
Located in `auto_updater.py`:
```python
CURRENT_VERSION = "1.0.1"  # Update this with each release
UPDATE_CHECK_URL = "https://api.github.com/repos/tiendungtcu/reup-tool/releases/latest"
CHECK_INTERVAL_HOURS = 1  # How often to check for updates
```

### Download Location
Updates are downloaded to: `~/.autobot_gui/updates/`

### Last Check Timestamp
Stored in: `~/.autobot_gui/last_update_check.json`

## Usage Flow

1. **User starts application**
   - Auto-updater checks if update check is needed (based on interval)
   - If needed, checks GitHub for latest release

2. **Update detected**
   - Notification dialog appears with version info and release notes
   - User can choose: Yes (download), No (dismiss), or Ignore (skip this version)

3. **User clicks Yes**
   - Progress dialog appears immediately
   - Download starts in background thread
   - Progress updates in real-time (percentage and MB)

4. **Download completes**
   - Progress dialog closes
   - Archives are automatically extracted
   - Platform-specific success dialog appears with action buttons

5. **User installs update**
   - Click "Open" or "Run Installer" to launch installer
   - Or click "Show in Finder/Explorer" to manually open location

## Error Handling

- **Network Errors**: Shows error dialog with specific error message
- **Extraction Errors**: Caught and reported to user
- **Invalid Downloads**: Handles corrupted or incomplete downloads
- **Silent Failures**: Update checks fail silently to not interrupt user experience

## Future Enhancements

Possible improvements for future versions:
- Resume interrupted downloads
- Delta/patch updates to reduce download size
- Automatic installation without user intervention (with permission)
- Rollback capability if new version has issues
- Update changelog viewer within the application
- Notification badge on menu bar when update available

## Testing

To test the auto-update feature:
1. Modify `CURRENT_VERSION` to an older version (e.g., "1.0.0")
2. Ensure there's a newer release on GitHub
3. Start the application
4. Update notification should appear
5. Click "Yes" to test download flow
6. Verify progress dialog updates correctly
7. Verify platform-specific success dialog appears
8. Test actual installation of downloaded update

## Security Considerations

- All downloads use HTTPS from GitHub
- Version comparison uses semantic versioning library
- No arbitrary code execution during update check
- Downloads are placed in user's home directory
- User must manually confirm installation
