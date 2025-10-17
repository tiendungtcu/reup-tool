#!/usr/bin/env python3
"""
AutoBot GUI Launcher
A simple launcher script for the AutoBot GUI application.
"""

import sys
import os
from pathlib import Path

def check_dependencies():
    """Check if required dependencies are installed"""
    try:
        import PySide6
        print("✓ PySide6 found")
    except ImportError:
        print("❌ PySide6 not found. Install with: pip install PySide6")
        return False
    
    # Check for main application files
    required_files = [
        "gui_main.py",
        "gui_channels.py", 
        "gui_pipeline.py",
        "autobot.py"
    ]
    
    for file in required_files:
        if not Path(file).exists():
            print(f"❌ Required file not found: {file}")
            return False
        print(f"✓ {file} found")
    
    return True

def setup_environment():
    """Setup required directories"""
    directories = ["configs", "log", "downloads", "processed"]
    
    for directory in directories:
        Path(directory).mkdir(exist_ok=True)
        print(f"✓ Directory ready: {directory}")

def main():
    """Main launcher function"""
    print("🚀 AutoBot GUI Launcher")
    print("=" * 40)
    
    # Check dependencies
    print("Checking dependencies...")
    if not check_dependencies():
        print("\n❌ Dependency check failed. Please install missing components.")
        sys.exit(1)
    
    # Setup environment
    print("\nSetting up environment...")
    setup_environment()
    
    # Launch GUI
    print("\n🎯 Launching AutoBot GUI...")
    try:
        from gui_main import main as gui_main
        gui_main()
    except ImportError as e:
        print(f"❌ Failed to import GUI modules: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Failed to start GUI: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()