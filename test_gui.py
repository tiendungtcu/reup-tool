#!/usr/bin/env python3
"""
Simple test for GUI components
"""

import sys
import os

def test_imports():
    """Test importing GUI components"""
    try:
        print("Testing basic imports...")
        import json
        import pathlib
        print("✓ Standard library imports OK")
        
        print("Testing PySide6...")
        from PySide6.QtWidgets import QApplication, QMainWindow, QWidget
        from PySide6.QtCore import Qt, QThread, Signal
        print("✓ PySide6 imports OK")
        
        print("Testing GUI modules...")
        from gui_main import ConfigManager
        print("✓ ConfigManager import OK")
        
        from gui_channels import ChannelsTab
        print("✓ ChannelsTab import OK")
        
        print("\n🎉 All imports successful!")
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def test_config_manager():
    """Test ConfigManager functionality"""
    try:
        print("\nTesting ConfigManager...")
        from gui_main import ConfigManager
        
        config_manager = ConfigManager()
        print("✓ ConfigManager created")
        
        # Test default settings
        settings = config_manager._default_settings()
        print(f"✓ Default settings: {len(settings)} keys")
        
        # Test validation
        errors = config_manager.validate_settings(settings)
        print(f"✓ Settings validation: {len(errors)} errors")
        
        return True
        
    except Exception as e:
        print(f"❌ ConfigManager test failed: {e}")
        return False

def main():
    """Main test function"""
    print("🧪 AutoBot GUI Component Tests")
    print("=" * 40)
    
    if not test_imports():
        print("Import tests failed. Please install dependencies:")
        print("pip install PySide6")
        return False
    
    if not test_config_manager():
        print("ConfigManager tests failed.")
        return False
    
    print("\n✅ All tests passed! GUI should work correctly.")
    
    # Try creating a minimal QApplication
    try:
        print("\nTesting QApplication creation...")
        from PySide6.QtWidgets import QApplication
        app = QApplication(sys.argv)
        print("✓ QApplication created successfully")
        print("✓ GUI system ready")
        return True
    except Exception as e:
        print(f"❌ QApplication test failed: {e}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)