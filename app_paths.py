from __future__ import annotations

import os
import sys
from pathlib import Path


def _meipass_root() -> Path | None:
    """Return the temporary PyInstaller extraction directory if present."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base)
    return None


def _bundle_root() -> Path | None:
    """Return the macOS .app bundle root if running inside one."""
    candidates = [Path(__file__).resolve(), Path(sys.executable).resolve()]
    for path in candidates:
        for parent in path.parents:
            if parent.suffix == ".app" and parent.name.endswith(".app"):
                return parent
    return None


def project_root() -> Path:
    """Location of bundled source files.

    When running from source this is the repository root. When running from a
    PyInstaller bundle it resolves to the temporary extraction directory.
    """
    meipass = _meipass_root()
    if meipass is not None:
        return meipass
    bundle_root = _bundle_root()
    if bundle_root is not None:
        # Source files are stored inside Contents/Resources for onedir bundles.
        resources_dir = bundle_root / "Contents" / "Resources"
        if resources_dir.exists():
            return resources_dir

    return Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    """Build an absolute path to a bundled resource."""
    base = project_root().joinpath(*parts)
    if base.exists():
        return base

    bundle_root = _bundle_root()
    if bundle_root is not None:
        resources_dir = bundle_root / "Contents" / "Resources"
        return resources_dir.joinpath(*parts)

    return base


def default_runtime_root() -> Path:
    """Default writable directory for user configurations and artifacts."""
    explicit = os.environ.get("AUTOBOT_HOME")
    if explicit:
        return Path(explicit).expanduser()

    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
        return base / "AutoBot"

    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
        return base / "AutoBot"

    # Linux and other Unix platforms
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "autobot"


def ensure_runtime_structure() -> Path:
    """Ensure the runtime directory structure exists and return its path."""
    root = default_runtime_root()
    root.mkdir(parents=True, exist_ok=True)

    for name in ("configs", "downloads", "processed", "log"):
        (root / name).mkdir(parents=True, exist_ok=True)

    return root


def change_working_directory(target: Path) -> None:
    """Change the current working directory."""
    os.chdir(str(target))


__all__ = [
    "project_root",
    "resource_path",
    "default_runtime_root",
    "ensure_runtime_structure",
    "change_working_directory",
]
