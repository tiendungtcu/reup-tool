#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${BUILD_VENV:-$ROOT_DIR/.build-venv}"

if [ -z "${PYTHON_BIN:-}" ]; then
  for candidate in python3.13 python3.12 python3.11 python3; do
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
CHROME_METADATA_URL="${CHROME_METADATA_URL:-https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json}"
CHROME_FALLBACK_VERSION="${CHROME_FALLBACK_VERSION:-128.0.6613.137}"

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
if [ -f "$ROOT_DIR/requirements_gui.txt" ]; then
  python -m pip install -r "$ROOT_DIR/requirements_gui.txt"
fi
python -m pip install pyinstaller

pyinstaller "$SPEC_FILE" --clean --noconfirm

SIGNATURE_SRC="$ROOT_DIR/tiktok_uploader/tiktok-signature"

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

if [ -d "$SIGNATURE_SRC" ]; then
  if [ -d "$DIST_DIR/AutoBot-GUI" ]; then
    copy_signature "$DIST_DIR/AutoBot-GUI/tiktok_uploader"
  fi
  if [ -d "$DIST_DIR/AutoBot-GUI/_internal" ]; then
    copy_signature "$DIST_DIR/AutoBot-GUI/_internal/tiktok_uploader"
  fi
  if [ -d "$DIST_DIR/AutoBot GUI.app/Contents/Resources" ]; then
    copy_signature "$DIST_DIR/AutoBot GUI.app/Contents/Resources/tiktok_uploader"
  fi
fi

detect_chrome_platform() {
  if [ -n "${CHROME_PLATFORM:-}" ]; then
    echo "$CHROME_PLATFORM"
    return 0
  fi

  local arch
  arch="$(uname -m 2>/dev/null || echo arm64)"
  case "$arch" in
    arm64|aarch64)
      echo "mac-arm64"
      ;;
    x86_64|amd64)
      echo "mac-x64"
      ;;
    *)
      echo "mac-arm64"
      ;;
  esac
}

fetch_latest_chrome_download() {
  local platform="$1"
  local python_bin="$VENV_DIR/bin/python"
  if [ ! -x "$python_bin" ]; then
    python_bin="${PYTHON_BIN:-python3}"
  fi

  "$python_bin" - "$platform" "$CHROME_METADATA_URL" <<'PY'
import json
import sys
import urllib.request

platform = sys.argv[1]
metadata_url = sys.argv[2]

try:
    with urllib.request.urlopen(metadata_url, timeout=30) as response:
        data = json.load(response)
except Exception as exc:  # pragma: no cover - best effort logging
    print(f"error: failed to fetch metadata: {exc}", file=sys.stderr)
    sys.exit(1)

channel = data.get("channels", {}).get("Stable")
if not channel:
    print("error: stable channel missing in metadata", file=sys.stderr)
    sys.exit(1)

downloads = channel.get("downloads", {}).get("chrome") or []
for item in downloads:
    if item.get("platform") == platform and item.get("url"):
        version = channel.get("version")
        if not version:
            print("error: version missing in metadata", file=sys.stderr)
            sys.exit(1)
        print(f"{version}|{item['url']}")
        sys.exit(0)

print(f"error: no download found for platform {platform}", file=sys.stderr)
sys.exit(1)
PY
}

install_aria2_cli() {
  local destination="$1"
  local version="${ARIA2_VERSION:-1.37.0}"
  local archive_url="${ARIA2_URL:-https://github.com/aria2/aria2/releases/download/release-${version}/aria2-${version}.tar.bz2}"
  local binary_path="$destination/aria2c"

  if [ -x "$binary_path" ]; then
    echo "aria2 already present at $binary_path"
    return
  fi

  if ! command -v curl >/dev/null 2>&1; then
    echo "Warning: curl not available; skipping aria2 bundling." >&2
    return
  fi

  local tmpdir
  tmpdir="$(mktemp -d)"
  if [ ! -d "$tmpdir" ]; then
    echo "Warning: Unable to create temporary directory for aria2 download." >&2
    return
  fi

  if ! curl -fsSL "$archive_url" -o "$tmpdir/aria2.tar.bz2"; then
    echo "Warning: Failed to download aria2 archive." >&2
    rm -rf "$tmpdir"
    return
  fi

  if ! tar -xjf "$tmpdir/aria2.tar.bz2" -C "$tmpdir"; then
    echo "Warning: Failed to extract aria2 archive." >&2
    rm -rf "$tmpdir"
    return
  fi

  local extracted
  extracted="$(find "$tmpdir" -maxdepth 1 -type d -name 'aria2-*' -print -quit)"
  if [ -z "$extracted" ]; then
    echo "Warning: Extracted aria2 directory not found." >&2
    rm -rf "$tmpdir"
    return
  fi

  mkdir -p "$destination"
  local binary_source
  binary_source="$(find "$extracted" -type f -name 'aria2c' -print -quit)"
  if [ -n "$binary_source" ]; then
    cp "$binary_source" "$binary_path"
    chmod +x "$binary_path"
  else
    echo "Warning: aria2 binary not found in archive." >&2
  fi

  while IFS= read -r doc_path; do
    cp "$doc_path" "$destination/$(basename "$doc_path")"
  done < <(find "$extracted" -maxdepth 1 -type f \( -name 'COPYING*' -o -name 'LICENSE*' -o -name 'README*' -o -name 'ChangeLog*' \))

  rm -rf "$tmpdir"
  echo "aria2 bundled at $binary_path"
}

install_node_runtime() {
  local destination="$1"
  local version="${NODE_VERSION:-20.17.0}"
  local archive_url="${NODE_URL:-https://nodejs.org/dist/v${version}/node-v${version}-darwin-arm64.tar.gz}"
  local binary_path="$destination/bin/node"

  if [ -x "$binary_path" ]; then
    echo "Node.js already present at $binary_path"
    return
  fi

  if ! command -v curl >/dev/null 2>&1; then
    echo "Warning: curl not available; skipping Node.js bundling." >&2
    return
  fi

  local tmpdir
  tmpdir="$(mktemp -d)"
  if [ ! -d "$tmpdir" ]; then
    echo "Warning: Unable to create temporary directory for Node.js download." >&2
    return
  fi

  if ! curl -fsSL "$archive_url" -o "$tmpdir/node.tar.gz"; then
    echo "Warning: Failed to download Node.js archive." >&2
    rm -rf "$tmpdir"
    return
  fi

  if ! tar -xzf "$tmpdir/node.tar.gz" -C "$tmpdir"; then
    echo "Warning: Failed to extract Node.js archive." >&2
    rm -rf "$tmpdir"
    return
  fi

  local extracted
  extracted="$(find "$tmpdir" -maxdepth 1 -type d -name 'node-v*' -print -quit)"
  if [ -z "$extracted" ]; then
    echo "Warning: Extracted Node.js directory not found." >&2
    rm -rf "$tmpdir"
    return
  fi

  mkdir -p "$destination"
  cp -R "$extracted"/* "$destination/"
  if [ -x "$destination/bin/node" ]; then
    chmod +x "$destination/bin/node"
  fi

  rm -rf "$tmpdir"
  echo "Node.js bundled at $destination"
}

install_ffmpeg_cli() {
  local destination="$1"
  local archive_url="${FFMPEG_URL:-https://evermeet.cx/ffmpeg/ffmpeg-6.1.1.zip}"
  local binary_path="$destination/ffmpeg"

  if [ -x "$binary_path" ]; then
    echo "ffmpeg already present at $binary_path"
    return
  fi

  if ! command -v curl >/dev/null 2>&1; then
    echo "Warning: curl not available; skipping ffmpeg bundling." >&2
    return
  fi

  local tmpdir
  tmpdir="$(mktemp -d)"
  if [ ! -d "$tmpdir" ]; then
    echo "Warning: Unable to create temporary directory for ffmpeg download." >&2
    return
  fi

  if ! curl -fsSL "$archive_url" -o "$tmpdir/ffmpeg.zip"; then
    echo "Warning: Failed to download ffmpeg archive." >&2
    rm -rf "$tmpdir"
    return
  fi

  local extract_dir="$tmpdir/extracted"
  mkdir -p "$extract_dir"
  if command -v ditto >/dev/null 2>&1; then
    if ! ditto -x -k "$tmpdir/ffmpeg.zip" "$extract_dir"; then
      echo "Warning: Failed to extract ffmpeg archive." >&2
      rm -rf "$tmpdir"
      return
    fi
  else
    if ! unzip -q "$tmpdir/ffmpeg.zip" -d "$extract_dir"; then
      echo "Warning: Failed to extract ffmpeg archive." >&2
      rm -rf "$tmpdir"
      return
    fi
  fi

  mkdir -p "$destination"
  local ffmpeg_src
  ffmpeg_src="$(find "$extract_dir" -type f -name 'ffmpeg' -print -quit)"
  if [ -n "$ffmpeg_src" ]; then
    cp "$ffmpeg_src" "$binary_path"
    chmod +x "$binary_path"
  else
    echo "Warning: ffmpeg binary not found in archive." >&2
  fi

  local ffprobe_src
  ffprobe_src="$(find "$extract_dir" -type f -name 'ffprobe' -print -quit)"
  if [ -n "$ffprobe_src" ]; then
    cp "$ffprobe_src" "$destination/ffprobe"
    chmod +x "$destination/ffprobe"
  fi

  rm -rf "$tmpdir"
  echo "ffmpeg bundled at $destination"
}

install_chrome_runtime() {
  local destination="$1"
  local requested_version="${CHROME_VERSION:-}"
  local requested_url="${CHROME_URL:-}"
  local requested_version_lower=""
  if [ -n "$requested_version" ]; then
    requested_version_lower="$(printf '%s' "$requested_version" | tr '[:upper:]' '[:lower:]')"
  fi

  local platform
  platform="$(detect_chrome_platform)"
  local resolved_version=""
  local archive_url=""
  local version_marker="$destination/.chrome-version"
  local binary_path="$destination/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"

  if [ -n "$requested_url" ]; then
    archive_url="$requested_url"
    if [ -n "$requested_version" ] && [ "$requested_version_lower" != "latest" ]; then
      resolved_version="$requested_version"
    else
      resolved_version="custom"
    fi
  else
    if [ -z "$requested_version_lower" ] || [ "$requested_version_lower" = "latest" ]; then
      local fetch_output
      if fetch_output="$(fetch_latest_chrome_download "$platform")"; then
        resolved_version="$(printf '%s' "${fetch_output%%|*}")"
        archive_url="$(printf '%s' "${fetch_output#*|}")"
      else
        echo "Warning: Failed to retrieve latest Chrome for Testing metadata; falling back to pinned version." >&2
        resolved_version="$CHROME_FALLBACK_VERSION"
      fi
    else
      resolved_version="$requested_version"
    fi

    if [ -z "$archive_url" ]; then
      local suffix
      suffix="${platform#mac-}"
      archive_url="https://edgedl.me.gvt1.com/edgedl/chrome/chrome-for-testing/${resolved_version}/${platform}/chrome-mac-${suffix}.zip"
    fi
  fi

  if [ -z "$archive_url" ]; then
    echo "Warning: Unable to determine Chrome download URL; skipping bundling." >&2
    return
  fi

  if [ -z "$resolved_version" ]; then
    resolved_version="custom"
  fi

  if [ "$resolved_version" != "custom" ] && [ -x "$binary_path" ] && [ -f "$version_marker" ]; then
    local current_version
    current_version="$(cat "$version_marker" 2>/dev/null || true)"
    if [ "$current_version" = "$resolved_version" ]; then
      echo "Chrome runtime $resolved_version already present at $binary_path"
      return
    fi
  fi

  if ! command -v curl >/dev/null 2>&1; then
    echo "Warning: curl not available; skipping Chrome bundling." >&2
    return
  fi

  local tmpdir
  tmpdir="$(mktemp -d)"
  if [ ! -d "$tmpdir" ]; then
    echo "Warning: Unable to create temporary directory for Chrome download." >&2
    return
  fi

  local archive_file="$tmpdir/chrome.zip"
  if ! curl -fsSL "$archive_url" -o "$archive_file"; then
    echo "Warning: Failed to download Chrome archive." >&2
    rm -rf "$tmpdir"
    return
  fi

  local extract_dir="$tmpdir/extracted"
  mkdir -p "$extract_dir"
  if command -v ditto >/dev/null 2>&1; then
    if ! ditto -x -k "$archive_file" "$extract_dir"; then
      echo "Warning: Failed to extract Chrome archive." >&2
      rm -rf "$tmpdir"
      return
    fi
  else
    if ! unzip -q "$archive_file" -d "$extract_dir"; then
      echo "Warning: Failed to extract Chrome archive." >&2
      rm -rf "$tmpdir"
      return
    fi
  fi

  local extracted
  extracted="$(find "$extract_dir" -maxdepth 1 -type d -name 'chrome-mac*' -print -quit)"
  if [ -z "$extracted" ]; then
    echo "Warning: Extracted Chrome directory not found." >&2
    rm -rf "$tmpdir"
    return
  fi

  local staging_dir="$tmpdir/staging"
  mkdir -p "$staging_dir"
  if ! cp -R "$extracted"/* "$staging_dir/"; then
    echo "Warning: Failed to stage Chrome runtime files." >&2
    rm -rf "$tmpdir"
    return
  fi

  mkdir -p "$(dirname "$destination")"
  rm -rf "$destination"
  mkdir -p "$destination"
  if ! cp -R "$staging_dir"/. "$destination"/; then
    echo "Warning: Failed to copy staged Chrome runtime into place." >&2
    rm -rf "$tmpdir"
    return
  fi

  if [ "$resolved_version" != "custom" ]; then
    printf '%s\n' "$resolved_version" > "$version_marker"
  else
    rm -f "$version_marker"
  fi

  rm -rf "$tmpdir"
  if [ "$resolved_version" != "custom" ]; then
    echo "Chrome runtime $resolved_version bundled at $destination"
  else
    echo "Chrome runtime bundled at $destination"
  fi
}

replicate_dir() {
  local source="$1"
  local target="$2"

  if [ ! -d "$source" ]; then
    return
  fi

  rm -rf "$target"
  mkdir -p "$target"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a "$source"/ "$target"/
  else
    cp -R "$source"/. "$target"/
  fi
}

MAIN_ONEDIR="$DIST_DIR/AutoBot-GUI"
APP_BUNDLE="$DIST_DIR/AutoBot GUI.app"
APP_RESOURCES="$APP_BUNDLE/Contents/Resources"
MAIN_INTERNAL="$MAIN_ONEDIR/_internal"

if [ -d "$MAIN_ONEDIR" ]; then
  install_aria2_cli "$MAIN_ONEDIR/aria2"
  install_node_runtime "$MAIN_ONEDIR/node"
  install_ffmpeg_cli "$MAIN_ONEDIR/ffmpeg"
  install_chrome_runtime "$MAIN_ONEDIR/chrome"

  if [ -d "$MAIN_INTERNAL" ]; then
    replicate_dir "$MAIN_ONEDIR/aria2" "$MAIN_INTERNAL/aria2"
    replicate_dir "$MAIN_ONEDIR/node" "$MAIN_INTERNAL/node"
    replicate_dir "$MAIN_ONEDIR/ffmpeg" "$MAIN_INTERNAL/ffmpeg"
    replicate_dir "$MAIN_ONEDIR/chrome" "$MAIN_INTERNAL/chrome"
  fi
else
  echo "Warning: Primary distribution directory not found at $MAIN_ONEDIR" >&2
fi

if [ -d "$APP_RESOURCES" ]; then
  replicate_dir "$MAIN_ONEDIR/aria2" "$APP_RESOURCES/aria2"
  replicate_dir "$MAIN_ONEDIR/node" "$APP_RESOURCES/node"
  replicate_dir "$MAIN_ONEDIR/ffmpeg" "$APP_RESOURCES/ffmpeg"
  replicate_dir "$MAIN_ONEDIR/chrome" "$APP_RESOURCES/chrome"
fi

if [ -d "$APP_BUNDLE" ]; then
  if ! command -v hdiutil >/dev/null 2>&1; then
    echo "Warning: hdiutil not found; skipping DMG creation." >&2
  else
    DMG_NAME="${DMG_NAME:-AutoBot-GUI.dmg}"
    DMG_PATH="$DIST_DIR/$DMG_NAME"
    DMG_STAGING="$DIST_DIR/.dmg-staging"

    echo "Creating DMG at $DMG_PATH"
    rm -rf "$DMG_STAGING"
    mkdir -p "$DMG_STAGING"
    cp -R "$APP_BUNDLE" "$DMG_STAGING/"
    ln -sf /Applications "$DMG_STAGING/Applications"

    rm -f "$DMG_PATH"
    hdiutil create -volname "AutoBot GUI" -srcfolder "$DMG_STAGING" -ov -format UDZO "$DMG_PATH"
    rm -rf "$DMG_STAGING"
    echo "DMG created at: $DMG_PATH"
  fi
else
  echo "Warning: Application bundle not found at $APP_BUNDLE; skipping DMG creation." >&2
fi

if [ -d "$DIST_DIR" ]; then
  echo "Build artifacts are available in: $DIST_DIR"
fi
