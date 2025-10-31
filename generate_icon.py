#!/usr/bin/env python3
"""Generate application icon combining YouTube and TikTok icons"""

from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

def create_youtube_tiktok_icon(size=1024):
    """Create a combined YouTube + TikTok icon"""
    
    # Create a new image with transparent background
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Colors
    youtube_red = (255, 0, 0, 255)
    tiktok_cyan = (0, 242, 234, 255)
    tiktok_pink = (254, 44, 85, 255)
    white = (255, 255, 255, 255)
    black = (0, 0, 0, 255)
    
    # Background - rounded rectangle with gradient effect
    background_color = (40, 40, 50, 255)
    draw.rounded_rectangle([(0, 0), (size, size)], radius=size//8, fill=background_color)
    
    # Left half - YouTube style
    # YouTube play button (red rounded rectangle with white play triangle)
    yt_left = size // 8
    yt_top = size // 3
    yt_width = size // 2.5
    yt_height = size // 3
    
    # Red rounded rectangle for YouTube
    draw.rounded_rectangle(
        [(yt_left, yt_top), (yt_left + yt_width, yt_top + yt_height)],
        radius=size//20,
        fill=youtube_red
    )
    
    # White play triangle
    play_size = size // 8
    play_center_x = yt_left + yt_width // 2
    play_center_y = yt_top + yt_height // 2
    play_triangle = [
        (play_center_x - play_size//3, play_center_y - play_size//2),
        (play_center_x - play_size//3, play_center_y + play_size//2),
        (play_center_x + play_size//2, play_center_y)
    ]
    draw.polygon(play_triangle, fill=white)
    
    # Right half - TikTok style
    # TikTok musical note with offset colors
    tk_right = size * 5 // 8
    tk_top = size // 3
    tk_size = size // 3
    
    # Function to draw a musical note
    def draw_musical_note(x_offset, y_offset, color, alpha=255):
        # Note stem
        stem_x = tk_right + x_offset
        stem_y = tk_top + y_offset
        stem_height = tk_size * 0.7
        stem_width = tk_size // 12
        
        color_with_alpha = (*color[:3], alpha)
        
        # Vertical stem
        draw.rectangle(
            [(stem_x, stem_y), (stem_x + stem_width, stem_y + stem_height)],
            fill=color_with_alpha
        )
        
        # Note head (circle at bottom)
        head_radius = tk_size // 8
        draw.ellipse(
            [(stem_x - head_radius, stem_y + stem_height - head_radius),
             (stem_x + head_radius + stem_width, stem_y + stem_height + head_radius)],
            fill=color_with_alpha
        )
        
        # Note flag (curved line at top)
        flag_width = tk_size // 4
        draw.arc(
            [(stem_x + stem_width - 2, stem_y - 5),
             (stem_x + stem_width + flag_width, stem_y + tk_size // 4)],
            start=180, end=360, fill=color_with_alpha, width=stem_width
        )
    
    # Draw TikTok note with offset colors (TikTok style)
    offset = size // 40
    draw_musical_note(-offset, -offset, tiktok_cyan, 220)  # Cyan shadow
    draw_musical_note(offset, offset, tiktok_pink, 220)    # Pink shadow
    draw_musical_note(0, 0, white, 255)                     # White main
    
    # Add arrow indicating flow (YouTube to TikTok)
    arrow_y = size * 2 // 3
    arrow_start_x = size // 3
    arrow_end_x = size * 2 // 3
    arrow_color = (255, 255, 255, 180)
    arrow_width = size // 50
    
    # Arrow line
    draw.line(
        [(arrow_start_x, arrow_y), (arrow_end_x, arrow_y)],
        fill=arrow_color,
        width=arrow_width
    )
    
    # Arrow head
    arrow_head_size = size // 25
    arrow_head = [
        (arrow_end_x, arrow_y),
        (arrow_end_x - arrow_head_size, arrow_y - arrow_head_size),
        (arrow_end_x - arrow_head_size, arrow_y + arrow_head_size)
    ]
    draw.polygon(arrow_head, fill=arrow_color)
    
    return img

def save_icon_formats(base_img, output_dir):
    """Save icon in multiple formats and sizes"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save high-res PNG
    base_img.save(output_dir / "icon_1024.png", "PNG")
    print(f"Created: {output_dir / 'icon_1024.png'}")
    
    # Common sizes
    sizes = [16, 32, 64, 128, 256, 512, 1024]
    
    # Create .ico file (Windows icon with multiple sizes)
    ico_images = []
    for size in [16, 32, 48, 64, 128, 256]:
        resized = base_img.resize((size, size), Image.Resampling.LANCZOS)
        ico_images.append(resized)
    
    ico_images[0].save(
        output_dir / "icon.ico",
        format='ICO',
        sizes=[(img.size[0], img.size[1]) for img in ico_images]
    )
    print(f"Created: {output_dir / 'icon.ico'}")
    
    # Create .icns file (macOS icon)
    # For proper .icns, we need to create iconutil compatible structure
    iconset_dir = output_dir / "icon.iconset"
    iconset_dir.mkdir(exist_ok=True)
    
    icns_sizes = {
        16: "icon_16x16.png",
        32: ["icon_16x16@2x.png", "icon_32x32.png"],
        64: "icon_32x32@2x.png",
        128: ["icon_128x128.png"],
        256: ["icon_128x128@2x.png", "icon_256x256.png"],
        512: ["icon_256x256@2x.png", "icon_512x512.png"],
        1024: "icon_512x512@2x.png"
    }
    
    for size, filenames in icns_sizes.items():
        resized = base_img.resize((size, size), Image.Resampling.LANCZOS)
        if isinstance(filenames, list):
            for filename in filenames:
                resized.save(iconset_dir / filename, "PNG")
        else:
            resized.save(iconset_dir / filenames, "PNG")
    
    print(f"Created iconset: {iconset_dir}")
    print("To create .icns file, run: iconutil -c icns icon.iconset")
    
    # Save individual PNG sizes
    for size in sizes:
        resized = base_img.resize((size, size), Image.Resampling.LANCZOS)
        resized.save(output_dir / f"icon_{size}.png", "PNG")
    
    print(f"\nGenerated icons in multiple sizes: {', '.join(map(str, sizes))}")

def main():
    print("Generating YouTube + TikTok combined icon...")
    
    # Create the icon
    icon = create_youtube_tiktok_icon(1024)
    
    # Save in various formats
    resources_dir = Path(__file__).parent / "resources" / "icons"
    save_icon_formats(icon, resources_dir)
    
    print("\n✅ Icon generation complete!")
    print(f"Icons saved to: {resources_dir}")
    print("\nNext steps:")
    print("1. Run: iconutil -c icns resources/icons/icon.iconset")
    print("2. Update gui_main.py to use the new icon")
    print("3. Update .spec files to reference the new icon")

if __name__ == "__main__":
    main()
