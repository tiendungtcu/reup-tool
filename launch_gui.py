#!/usr/bin/env python3
"""
AutoBot GUI Launcher
A simple launcher script for the AutoBot GUI application.
"""

import sys
import os
import shutil
import importlib.util
from pathlib import Path
from typing import Optional

from app_paths import (
    change_working_directory,
    ensure_runtime_structure,
    project_root,
    resource_path,
)

def check_dependencies():
    """Check if required dependencies are installed"""
    try:
        import PySide6
        print("✓ PySide6 found")
    except ImportError:
        print("❌ PySide6 not found. Install with: pip install PySide6")
        return False
    
    # Check for key modules instead of raw files so bytecode-only bundles pass
    required_modules = [
        "gui_main",
        "gui_channels",
        "autobot",
    ]

    for module_name in required_modules:
        if importlib.util.find_spec(module_name) is None:
            print(f"❌ Required module not found: {module_name}")
            return False
        print(f"✓ {module_name} module available")

    if not shutil.which("node"):
        print("⚠️  Node.js runtime not found in PATH. TikTok signature generation may fail.")
        print("    Install from https://nodejs.org or ensure 'node' is available for full functionality.")
    
    return True

_INSTANCE_LOCK: Optional[object] = None


def setup_environment() -> Path:
    """Setup required directories"""
    runtime_root = ensure_runtime_structure()
    change_working_directory(runtime_root)

    print(f"✓ Runtime directory: {runtime_root}")
    for name in ("configs", "log", "downloads", "processed"):
        print(f"  └─ {name}")

    return runtime_root


def ensure_single_instance(runtime_root: Path) -> bool:
    """Ensure only one GUI instance runs at a time."""

    global _INSTANCE_LOCK

    try:
        from PySide6.QtCore import QLockFile
    except ImportError:
        # If PySide6 isn't available we can't enforce the lock, but we'll
        # fail later during dependency checks anyway.
        return True

    lock_path = Path(runtime_root) / "autobot_gui.lock"

    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(0)

    if not lock.tryLock(0):
        pid, hostname, _app_name = lock.lockInfo()
        details = []
        if pid:
            details.append(f"PID {pid}")
        if hostname:
            details.append(hostname)
        info = f" ({', '.join(details)})" if details else ""
        print(f"❌ AutoBot GUI is already running{info}.")
        return False

    _INSTANCE_LOCK = lock
    return True


def release_single_instance_lock() -> None:
    """Release the singleton lock when shutting down."""

    global _INSTANCE_LOCK

    if _INSTANCE_LOCK is None:
        return

    try:
        _INSTANCE_LOCK.unlock()
    except Exception:
        pass
    finally:
        _INSTANCE_LOCK = None


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
    runtime_root = setup_environment()

    if not ensure_single_instance(runtime_root):
        sys.exit(0)
    
    # Launch GUI
    print("\n🎯 Launching AutoBot GUI...")
    try:
        sys.path.insert(0, str(project_root()))
        from gui_main import main as gui_main
        try:
            gui_main()
        except SystemExit:
            raise
        finally:
            release_single_instance_lock()
    except ImportError as e:
        print(f"❌ Failed to import GUI modules: {e}")
        release_single_instance_lock()
        sys.exit(1)
    except Exception as e:
        print(f"❌ Failed to start GUI: {e}")
        release_single_instance_lock()
        sys.exit(1)

if __name__ == "__main__":
    try:
        import multiprocessing

        multiprocessing.freeze_support()
    except Exception:
        pass
    main()