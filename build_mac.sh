#!/bin/bash
# Build Glitchy.app for macOS. Run this ON A MAC -- .app bundles can't be
# cross-compiled from Linux/Windows.
#
# Usage:
#   chmod +x build_mac.sh
#   ./build_mac.sh
#
# Output: dist/Glitchy.app and Glitchy.dmg in this folder.

set -e
cd "$(dirname "$0")"

echo "== Checking for Python 3 =="
if ! command -v python3 &>/dev/null; then
    echo "python3 not found. Install it from python.org or via 'brew install python'."
    exit 1
fi

echo "== Checking for Homebrew system dependencies =="
if ! command -v brew &>/dev/null; then
    echo "Homebrew not found. Install it from https://brew.sh first (needed for ffmpeg/portaudio)."
    exit 1
fi
brew list ffmpeg &>/dev/null || { echo "Installing ffmpeg (needed for Live Monitor's Network Stream mode)..."; brew install ffmpeg; }
brew list portaudio &>/dev/null || { echo "Installing portaudio (needed for Live Monitor's Sound Card mode)..."; brew install portaudio; }
brew list create-dmg &>/dev/null || { echo "Installing create-dmg (for a nicer install window)..."; brew install create-dmg; }

echo "== Setting up a clean virtual environment =="
rm -rf build_venv
python3 -m venv build_venv
source build_venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
pip install pyinstaller --quiet

echo "== Building Glitchy.app =="
rm -rf build dist Glitchy.spec
pyinstaller --name Glitchy --windowed --noconfirm \
    --icon resources/Glitchy.icns \
    --add-data "resources:resources" \
    glitchy_gui.py

deactivate

echo "== Packaging into a DMG for distribution =="
if [ -d "dist/Glitchy.app" ]; then
    rm -f Glitchy.dmg
    # create-dmg is known to sometimes exit non-zero on Finder/AppleScript
    # timing quirks even when it succeeds -- so check for the actual file
    # afterward rather than trusting the exit code alone.
    create-dmg \
        --volname "Glitchy" \
        --volicon "resources/Glitchy.icns" \
        --background "resources/dmg_background.png" \
        --window-pos 200 120 \
        --window-size 660 400 \
        --icon-size 128 \
        --icon "Glitchy.app" 165 190 \
        --hide-extension "Glitchy.app" \
        --app-drop-link 495 190 \
        --no-internet-enable \
        "Glitchy.dmg" \
        "dist/Glitchy.app" || true

    if [ -f "Glitchy.dmg" ]; then
        echo ""
        echo "Done. Glitchy.dmg is ready in $(pwd)."
        echo "Double-click it, then drag Glitchy into Applications."
    else
        echo "create-dmg didn't produce a DMG -- falling back to a plain one (no custom background)."
        hdiutil create -volname Glitchy -srcfolder dist/Glitchy.app -ov -format UDZO Glitchy.dmg
        echo "Done. Glitchy.dmg is ready in $(pwd) (plain style)."
    fi
else
    echo "Build did not produce dist/Glitchy.app -- check the PyInstaller output above."
    exit 1
fi
