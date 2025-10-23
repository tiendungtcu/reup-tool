#!/bin/bash
set -euo pipefail

# Build a standalone AutoBot GUI .app bundle for macOS (Apple Silicon)

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${BUILD_VENV:-$ROOT_DIR/.build-venv}"

if [ -z "${PYTHON_BIN:-}" ]; then
  for candidate in python3.12 python3.13 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi

if [ -z "${PYTHON_BIN:-}" ]; then
  echo "Error: Python 3.11+ is required to build the macOS bundle." >&2
  exit 1
fi

PYTHON_BIN="$(command -v "$PYTHON_BIN")"
SPEC_FILE="$ROOT_DIR/packaging/autobot_gui.spec"
DIST_DIR="$ROOT_DIR/dist"

if [ -d "$VENV_DIR" ] && [ -x "$VENV_DIR/bin/python" ]; then
  if ! "$VENV_DIR/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo "Recreating build virtual environment with $PYTHON_BIN"
    rm -rf "$VENV_DIR"
  fi
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating build virtual environment at $VENV_DIR using $PYTHON_BIN"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip
python -m pip install -r "$ROOT_DIR/requirements.txt"
python -m pip install -r "$ROOT_DIR/requirements_gui.txt"
python -m pip install pyinstaller

pyinstaller "$SPEC_FILE" --clean --noconfirm

# Ensure TikTok signature assets are bundled alongside the frozen app.
SIGNATURE_SRC="$ROOT_DIR/tiktok_uploader/tiktok-signature"
if [ -d "$SIGNATURE_SRC" ]; then
  copy_signature() {
    local destination="$1"
    if [ ! -d "$destination" ]; then
      mkdir -p "$destination"
    fi
    if command -v rsync >/dev/null 2>&1; then
      rsync -a --delete "$SIGNATURE_SRC/" "$destination/tiktok-signature/"
    else
      rm -rf "$destination/tiktok-signature"
      cp -R "$SIGNATURE_SRC" "$destination/tiktok-signature"
    fi
  }

  if [ -d "$DIST_DIR/AutoBot-GUI/_internal" ]; then
    copy_signature "$DIST_DIR/AutoBot-GUI/_internal/tiktok_uploader"
  fi

  if [ -d "$DIST_DIR/AutoBot GUI.app/Contents/Resources" ]; then
    copy_signature "$DIST_DIR/AutoBot GUI.app/Contents/Resources/tiktok_uploader"
  fi
fi

# Display resulting bundle location
if [ -d "$DIST_DIR" ]; then
  echo "Build artifacts are available in: $DIST_DIR"
fi
