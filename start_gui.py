#!/usr/bin/env python3
"""
Simple AutoBot GUI Launcher
"""

import sys
import os

def main():
    """Launch the AutoBot GUI"""
    try:
        print("🚀 Starting AutoBot GUI...")
        
        # Import and run the main application
        from gui_main import main as gui_main
        gui_main()
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Please install PySide6: pip install PySide6")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error starting GUI: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()