# AutoBot GUI - YouTube to TikTok Automation Interface

A comprehensive graphical user interface for managing YouTube to TikTok automation using PySide6.

## Features

### 🔧 Settings Management
- Configure global application settings
- WebSub/Ngrok configuration
- Telegram bot integration
- Global behavior settings

### 📺 Channel Management
- Add, edit, and delete YouTube channels
- Configure YouTube API settings per channel
- Set TikTok upload preferences
- Manage proxy and browser settings
- Advanced configuration options

### 🍪 Cookie Management
- Import/export TikTok cookies
- JSON format validation
- Per-channel cookie storage
- Cookie validation testing

### ⚡ Pipeline Control
- Run individual pipeline steps:
  - Download videos from YouTube
  - Render/process videos
  - Upload to TikTok
- Full pipeline automation
- Real-time progress monitoring
- Operation logging
- Manual URL processing

## Installation

### Prerequisites
- Python 3.8 or higher
- FFmpeg (for video processing)
- Chrome/Chromium browser (for browser automation)

### Install Dependencies
```bash
# Install GUI dependencies
pip install -r requirements_gui.txt

# Install original project dependencies
pip install -r requirements.txt
```

### Setup
1. Ensure the original autobot.py and related files are in the same directory
2. Create necessary directories (will be created automatically):
   - `configs/` - Channel configurations
   - `log/` - Application logs
   - `downloads/` - Temporary video downloads
   - `processed/` - Processed videos

## Usage

### Starting the GUI
```bash
python gui_main.py
```

### Configuration Workflow

1. **Global Settings** (Settings Tab)
   - Configure Ngrok auth token for WebSub
   - Set up Telegram notifications
   - Configure global behavior

2. **Add Channels** (Channels Tab)
   - Click "Add Channel"
   - Enter YouTube Channel ID (UC...)
   - Configure YouTube API keys
   - Set TikTok upload preferences
   - Add TikTok cookies in the Cookies tab

3. **Run Operations** (Pipeline Control Tab)
   - Select channels to run
   - Choose individual operations or full pipeline
   - Monitor progress in real-time
   - View logs for debugging

### Configuration Files

#### settings.json
Global application settings:
```json
{
  "websub_url": "https://your-domain.com/websub",
  "ngrok_auth_token": "your_ngrok_token",
  "domain_type": "ngrok",
  "websub_port": 8080,
  "telegram": "chat_id|bot_token",
  "is_human": 1
}
```

#### Channel config.json
Per-channel configuration:
```json
{
  "youtube_channel_id": "UC...",
  "channel_name": "Display Name",
  "youtube_api_key": "key1;key2;key3",
  "api_scan_method": "sequence",
  "youtube_api_type": "activities",
  "detect_video": "websub",
  "upload_method": "api",
  "region": "ap-northeast-3",
  "proxy": "host:port:user:pass",
  "is_human": 1
}
```

#### cookies.json
TikTok authentication cookies:
```json
{
  "url": "https://www.tiktok.com",
  "cookies": [
    {
      "name": "sessionid",
      "value": "your_session_id",
      "domain": ".tiktok.com"
    }
  ]
}
```

## Features Details

### Video Detection Methods
- **WebSub**: Real-time notifications via PubSubHubbub
- **API**: Periodic polling using YouTube API
- **Both**: Combined approach for maximum reliability

### Upload Methods
- **API**: Direct API upload (faster, more reliable)
- **Browser**: Browser automation (more human-like)

### Video Processing
- Automatic duration adjustment
- Quality optimization
- Format conversion for TikTok compatibility

### Monitoring & Logging
- Real-time operation progress
- Detailed logging system
- Error reporting
- Telegram notifications

## Troubleshooting

### Common Issues

1. **PySide6 Import Errors**
   ```bash
   pip install --upgrade PySide6
   ```

2. **FFmpeg Not Found**
   - Install FFmpeg system-wide
   - Ensure it's in your PATH

3. **Cookie Issues**
   - Export fresh cookies from browser
   - Ensure cookies include sessionid
   - Check cookie expiration dates

4. **API Rate Limits**
   - Use multiple API keys
   - Adjust scan intervals
   - Switch to WebSub for real-time detection

### Getting Help
- Check the logs in the Pipeline Control tab
- Verify configurations in each tab
- Test individual components before running full pipeline

## File Structure
```
bot-GUI/
├── gui_main.py          # Main GUI application
├── gui_channels.py      # Channel management interface
├── autobot.py          # Original automation script
├── settings.json       # Global settings
├── requirements_gui.txt # GUI dependencies
├── configs/            # Channel configurations
│   ├── UC.../
│   │   ├── config.json
│   │   └── cookies.json
├── log/               # Application logs
├── downloads/         # Temporary downloads
└── processed/         # Processed videos
```

## Advanced Usage

### Custom Video Processing
The GUI integrates with the existing video processing pipeline in autobot.py. You can customize:
- Video quality settings
- Duration handling
- Render methods (repeat vs slow)

### Proxy Configuration
Support for HTTP/HTTPS proxies:
- Format: `host:port` or `host:port:username:password`
- Per-channel proxy settings
- Automatic proxy rotation (if multiple provided)

### Bulk Operations
- Process multiple channels simultaneously
- Batch cookie management
- Configuration import/export

## Security Notes
- Store sensitive data (API keys, tokens) securely
- Regularly update cookies
- Use VPN/proxy for IP protection
- Monitor rate limits to avoid bans

## Contributing
This GUI extends the original autobot.py functionality. When contributing:
1. Maintain compatibility with existing configurations
2. Follow PySide6 best practices
3. Add proper error handling
4. Update documentation