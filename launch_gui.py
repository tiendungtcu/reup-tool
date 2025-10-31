#!/usr/bin/env python3
"""
AutoBot GUI Launcher
A simple launcher script for the AutoBot GUI application.
"""

import sys
import os
import shutil
import importlib.util
import functools
from pathlib import Path
from typing import Optional, Iterable

from app_paths import (
    change_working_directory,
    ensure_runtime_structure,
    project_root,
    resource_path,
)


def _first_existing_path(candidates: Iterable[object]) -> Optional[Path]:
    """Return the first existing filesystem path from the provided candidates."""

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.exists():
            return path
    return None


def _resolve_if_possible(path: Path) -> Path:
    """Resolve a path if it exists, otherwise return it unchanged."""

    try:
        return path.resolve()
    except OSError:
        return path


def _prepend_to_path(directory: Path) -> None:
    """Prepend a directory to PATH if it is not already present."""

    directory_str = str(directory)
    if not directory_str:
        return

    current = os.environ.get("PATH", "")
    parts = [part for part in current.split(os.pathsep) if part]
    if directory_str in parts:
        return

    os.environ["PATH"] = os.pathsep.join([directory_str] + parts)


def _configure_media_binaries() -> None:
    """Ensure bundled FFmpeg binaries are discoverable at runtime."""

    ffmpeg_names = {"win32": "ffmpeg.exe"}
    ffprobe_names = {"win32": "ffprobe.exe"}

    ffmpeg_name = ffmpeg_names.get(sys.platform, "ffmpeg")
    ffprobe_name = ffprobe_names.get(sys.platform, "ffprobe")

    ffmpeg_candidates = [
        resource_path("ffmpeg", ffmpeg_name),
        resource_path("ffmpeg", "bin", ffmpeg_name),
        resource_path("_internal", "ffmpeg", ffmpeg_name),
        resource_path("_internal", "ffmpeg", "bin", ffmpeg_name),
        project_root() / "ffmpeg" / ffmpeg_name,
        project_root() / "ffmpeg" / "bin" / ffmpeg_name,
        Path(sys.executable).resolve().parent / "ffmpeg" / ffmpeg_name,
        Path(sys.executable).resolve().parent / "ffmpeg" / "bin" / ffmpeg_name,
        Path(sys.executable).resolve().parent / "_internal" / "ffmpeg" / ffmpeg_name,
        Path(sys.executable).resolve().parent / "_internal" / "ffmpeg" / "bin" / ffmpeg_name,
    ]

    ffprobe_candidates = [
        resource_path("ffmpeg", ffprobe_name),
        resource_path("ffmpeg", "bin", ffprobe_name),
        resource_path("_internal", "ffmpeg", ffprobe_name),
        resource_path("_internal", "ffmpeg", "bin", ffprobe_name),
        project_root() / "ffmpeg" / ffprobe_name,
        project_root() / "ffmpeg" / "bin" / ffprobe_name,
        Path(sys.executable).resolve().parent / "ffmpeg" / ffprobe_name,
        Path(sys.executable).resolve().parent / "ffmpeg" / "bin" / ffprobe_name,
        Path(sys.executable).resolve().parent / "_internal" / "ffmpeg" / ffprobe_name,
        Path(sys.executable).resolve().parent / "_internal" / "ffmpeg" / "bin" / ffprobe_name,
    ]

    ffmpeg_path = _first_existing_path(ffmpeg_candidates)
    if ffmpeg_path is not None:
        ffmpeg_path = _resolve_if_possible(ffmpeg_path)
        os.environ.setdefault("FFMPEG_BINARY", str(ffmpeg_path))
        os.environ.setdefault("IMAGEIO_FFMPEG_EXE", str(ffmpeg_path))
        _prepend_to_path(ffmpeg_path.parent)

        os.environ["FFMPEG_BINARY"] = str(ffmpeg_path)

        try:
            import moviepy.config as moviepy_config

            moviepy_config.FFMPEG_BINARY = str(ffmpeg_path)
        except Exception:
            pass

    ffprobe_path = _first_existing_path(ffprobe_candidates)
    if ffprobe_path is not None:
        ffprobe_path = _resolve_if_possible(ffprobe_path)
        os.environ.setdefault("MOVIEPY_FFPROBE_BINARY", str(ffprobe_path))
        _prepend_to_path(ffprobe_path.parent)


def _configure_node_runtime() -> None:
    """Ensure the bundled Node.js runtime is available on PATH."""
    binary_name = "node.exe" if sys.platform == "win32" else "node"
    candidate_paths = [
        os.environ.get("NODE_BINARY"),
        resource_path("node", binary_name),
        resource_path("node", "bin", binary_name),
        resource_path("_internal", "node", binary_name),
        resource_path("_internal", "node", "bin", binary_name),
        project_root() / "node" / binary_name,
        project_root() / "node" / "bin" / binary_name,
        Path(sys.executable).resolve().parent / "node" / binary_name,
        Path(sys.executable).resolve().parent / "node" / "bin" / binary_name,
        Path(sys.executable).resolve().parent / "_internal" / "node" / binary_name,
        Path(sys.executable).resolve().parent / "_internal" / "node" / "bin" / binary_name,
        Path(__file__).resolve().parent / "node" / binary_name,
        Path(__file__).resolve().parent / "node" / "bin" / binary_name,
        shutil.which(binary_name),
        shutil.which("node"),
    ]

    node_path = _first_existing_path(candidate_paths)
    if node_path is not None:
        node_path = _resolve_if_possible(node_path)
        _prepend_to_path(node_path.parent)
        os.environ["NODE_BINARY"] = str(node_path)
        return


def _configure_aria2_cli() -> None:
    """Ensure the aria2 command-line client is discoverable."""
    binary_name = "aria2c.exe" if sys.platform == "win32" else "aria2c"
    candidate_paths = [
        os.environ.get("ARIA2C_BINARY"),
        resource_path("aria2", binary_name),
        resource_path("aria2", "bin", binary_name),
        resource_path("_internal", "aria2", binary_name),
        resource_path("_internal", "aria2", "bin", binary_name),
        project_root() / "aria2" / binary_name,
        project_root() / "aria2" / "bin" / binary_name,
        Path(sys.executable).resolve().parent / "aria2" / binary_name,
        Path(sys.executable).resolve().parent / "aria2" / "bin" / binary_name,
        Path(sys.executable).resolve().parent / "_internal" / "aria2" / binary_name,
        Path(sys.executable).resolve().parent / "_internal" / "aria2" / "bin" / binary_name,
        Path(__file__).resolve().parent / "aria2" / binary_name,
        Path(__file__).resolve().parent / "aria2" / "bin" / binary_name,
        shutil.which(binary_name),
        shutil.which("aria2c"),
    ]

    aria2_path = _first_existing_path(candidate_paths)
    if aria2_path is not None:
        aria2_path = _resolve_if_possible(aria2_path)
        _prepend_to_path(aria2_path.parent)
        os.environ["ARIA2C_BINARY"] = str(aria2_path)
        return


@functools.lru_cache(maxsize=1)
def _locate_chrome_binary() -> Optional[Path]:
    """Locate a Chrome browser binary, preferring bundled copies."""

    env_candidates = [
        os.environ.get("GOOGLE_CHROME_BIN"),
        os.environ.get("CHROME_BINARY"),
        os.environ.get("CHROME_EXECUTABLE"),
        os.environ.get("UC_CHROME_PATH"),
    ]

    candidates: list[object] = [
        resource_path("chrome", "chrome.exe"),
        resource_path("chrome", "chrome-win64", "chrome.exe"),
        resource_path("_internal", "chrome", "chrome.exe"),
        resource_path("_internal", "chrome", "chrome-win64", "chrome.exe"),
        resource_path("chrome", "Google Chrome for Testing.app", "Contents", "MacOS", "Google Chrome for Testing"),
        resource_path("_internal", "chrome", "Google Chrome for Testing.app", "Contents", "MacOS", "Google Chrome for Testing"),
        resource_path("chrome", "chrome-linux64", "chrome"),
        resource_path("_internal", "chrome", "chrome-linux64", "chrome"),
        project_root() / "chrome" / "chrome.exe",
        project_root() / "chrome-win64" / "chrome.exe",
        project_root() / "chrome" / "Google Chrome for Testing.app" / "Contents" / "MacOS" / "Google Chrome for Testing",
        project_root() / "chrome-linux64" / "chrome",
        *env_candidates,
        shutil.which("chrome"),
        shutil.which("chrome.exe"),
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        Path(sys.executable).resolve().parent / "chrome" / "chrome.exe",
        Path(sys.executable).resolve().parent / "chrome-win64" / "chrome.exe",
        Path(sys.executable).resolve().parent / "_internal" / "chrome" / "chrome.exe",
        Path(sys.executable).resolve().parent / "_internal" / "chrome" / "chrome-win64" / "chrome.exe",
        Path(sys.executable).resolve().parent / "chrome" / "Google Chrome for Testing.app" / "Contents" / "MacOS" / "Google Chrome for Testing",
        Path(sys.executable).resolve().parent / "_internal" / "chrome" / "Google Chrome for Testing.app" / "Contents" / "MacOS" / "Google Chrome for Testing",
        Path(__file__).resolve().parent / "chrome" / "chrome.exe",
        Path(__file__).resolve().parent / "chrome" / "Google Chrome for Testing.app" / "Contents" / "MacOS" / "Google Chrome for Testing",
    ]

    if sys.platform == "win32":
        for env_var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env_var)
            if base:
                candidates.append(Path(base) / "Google/Chrome/Application/chrome.exe")
                candidates.append(Path(base) / "Google/Chrome for Testing/Application/chrome.exe")
    elif sys.platform == "darwin":
        candidates.extend(
            [
                Path("/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"),
                Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            ]
        )
    else:
        candidates.extend(
            [
                Path("/usr/bin/google-chrome"),
                Path("/usr/bin/chromium"),
                Path("/usr/bin/chromium-browser"),
            ]
        )

    chrome_path = _first_existing_path(candidates)
    if chrome_path is not None:
        return _resolve_if_possible(chrome_path)

    return None


def _configure_chrome_runtime() -> None:
    """Ensure a Chrome executable is discoverable for browser automation."""

    chrome_path = _locate_chrome_binary()
    if chrome_path is None:
        return

    _prepend_to_path(chrome_path.parent)
    path_str = str(chrome_path)
    os.environ.setdefault("GOOGLE_CHROME_BIN", path_str)
    os.environ.setdefault("CHROME_BINARY", path_str)
    os.environ.setdefault("CHROME_EXECUTABLE", path_str)
    os.environ.setdefault("UC_CHROME_PATH", path_str)


def _ensure_signature_assets(runtime_root: Path) -> None:
    """Copy bundled TikTok signature helpers into the writable runtime area."""

    source_dir = resource_path("tiktok_uploader", "tiktok-signature")
    if not source_dir.exists():
        return

    target_dir = runtime_root / "tiktok_uploader" / "tiktok-signature"
    if target_dir.exists():
        return

    target_dir.parent.mkdir(parents=True, exist_ok=True)

    try:
        shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)  # type: ignore[arg-type]
    except TypeError:
        # Python versions without dirs_exist_ok
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.copytree(source_dir, target_dir)


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

    if not shutil.which("aria2c"):
        print("⚠️  aria2c not found in PATH. Downloads may fall back to slower built-in methods.")
        print("    Install aria2 manually or ensure the bundled binary is present.")

    if _locate_chrome_binary() is None:
        print("⚠️  Chrome runtime not found. TikTok browser automation will be unavailable.")
        print("    Install Google Chrome or ensure the packaged Chrome for Testing runtime is bundled.")
    
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
        if hasattr(lock, "lockInfo"):
            pid, hostname, _app_name = lock.lockInfo()
        else:
            pid, hostname, _app_name = lock.getLockInfo()
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

    # Configure bundled runtimes before validating dependencies.
    _configure_media_binaries()
    _configure_node_runtime()
    _configure_aria2_cli()
    _configure_chrome_runtime()
    
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
    
    _ensure_signature_assets(runtime_root)
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