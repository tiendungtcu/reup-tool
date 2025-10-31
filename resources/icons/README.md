# Application Icon

## Overview
The application icon is a custom-designed combination of YouTube and TikTok icons, representing the core functionality of the AutoBot GUI - automating content flow from YouTube to TikTok.

## Icon Design
- **Left side**: YouTube play button (red rounded rectangle with white play triangle)
- **Right side**: TikTok musical note (with signature cyan and pink offset effect)
- **Center arrow**: Indicates the flow direction from YouTube to TikTok
- **Background**: Dark rounded rectangle for modern appearance

## Generated Files

### Icon Formats
- `icon.icns` - macOS application icon (111 KB)
- `icon.ico` - Windows application icon (593 B)
- `icon_1024.png` - High-resolution PNG (10 KB)
- `icon_512.png` - Standard resolution (18 KB)
- `icon_256.png` - Window icon (9.5 KB)
- `icon_128.png` - Small icon (4.5 KB)
- `icon_64.png` - Tiny icon (2.2 KB)
- `icon_32.png` - Mini icon (1.1 KB)
- `icon_16.png` - Micro icon (571 B)

### IconSet (macOS)
The `icon.iconset` folder contains all required sizes for macOS:
- icon_16x16.png, icon_16x16@2x.png
- icon_32x32.png, icon_32x32@2x.png
- icon_128x128.png, icon_128x128@2x.png
- icon_256x256.png, icon_256x256@2x.png
- icon_512x512.png, icon_512x512@2x.png

## Regenerating the Icon

To regenerate the icon (if you need to modify the design):

```bash
python3 generate_icon.py
cd resources/icons
iconutil -c icns icon.iconset
```

## Usage in Application

### GUI Window Icon
The icon is automatically loaded in `gui_main.py`:
```python
icon_path = resource_path("resources", "icons", "icon_256.png")
if Path(icon_path).exists():
    self.setWindowIcon(QIcon(icon_path))
```

### Application Bundle Icon
The icon is specified in `packaging/autobot_gui.spec`:
```python
app = BUNDLE(
    coll,
    name='AutoBot GUI.app',
    icon=str(PROJECT_ROOT / 'resources' / 'icons' / 'icon.icns'),
    bundle_identifier='com.autobot.gui',
)
```

## Platform Support
- ✅ **macOS**: Uses `.icns` format with multiple resolutions
- ✅ **Windows**: Uses `.ico` format with embedded sizes
- ✅ **Linux**: Uses `.png` format (typically 256x256)

## Color Palette
- YouTube Red: `#FF0000` (RGB: 255, 0, 0)
- TikTok Cyan: `#00F2EA` (RGB: 0, 242, 234)
- TikTok Pink: `#FE2C55` (RGB: 254, 44, 85)
- Background: `#282832` (RGB: 40, 40, 50)
- White: `#FFFFFF` (RGB: 255, 255, 255)

## Design Files
The icon is generated programmatically using PIL (Pillow). The generation script is `generate_icon.py` in the project root.

## License
The icon design is custom-made for this project. YouTube and TikTok are trademarks of their respective owners. This icon is for identification purposes only and does not imply endorsement.
