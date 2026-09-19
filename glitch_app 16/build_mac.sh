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
    echo "Homebrew not found. Install it from https://brew.sh first (needed for ffmpeg, portaudio, create-dmg, and dylibbundler)."
    exit 1
fi
brew list ffmpeg &>/dev/null || { echo "Installing ffmpeg (needed for Live Monitor's Network Stream mode)..."; brew install ffmpeg; }
brew list portaudio &>/dev/null || { echo "Installing portaudio (needed for Live Monitor's Sound Card mode)..."; brew install portaudio; }
brew list create-dmg &>/dev/null || { echo "Installing create-dmg (for a nicer install window)..."; brew install create-dmg; }
brew list dylibbundler &>/dev/null || { echo "Installing dylibbundler (to bundle ffmpeg so end users don't need it installed)..."; brew install dylibbundler; }

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

echo "== Bundling ffmpeg so end users don't need it installed =="
if [ -d "dist/Glitchy.app" ]; then
    FFMPEG_BIN="$(command -v ffmpeg || true)"
    if [ -z "$FFMPEG_BIN" ]; then
        echo "WARNING: ffmpeg not found on PATH even after brew install -- skipping bundling."
        echo "Network Stream mode will require end users to install ffmpeg themselves."
    else
        BUNDLE_DIR="dist/Glitchy.app/Contents/MacOS/ffmpeg_bundle"
        mkdir -p "$BUNDLE_DIR/libs"
        cp "$FFMPEG_BIN" "$BUNDLE_DIR/ffmpeg"
        chmod +w "$BUNDLE_DIR/ffmpeg"
        # Copies every dylib ffmpeg depends on into libs/ and rewrites
        # ffmpeg's own load commands to reference them via @executable_path
        # instead of their original Homebrew paths (/opt/homebrew/... or
        # /usr/local/...) -- so the copy works on a Mac with no Homebrew
        # and no ffmpeg installed at all.
        dylibbundler -od -b \
            -x "$BUNDLE_DIR/ffmpeg" \
            -d "$BUNDLE_DIR/libs" \
            -p "@executable_path/libs/"
        echo "ffmpeg bundled into the app -- Network Stream mode will work with no separate install."
        echo "NOTE: Homebrew's ffmpeg is built with --enable-gpl (GPL-3.0), not LGPL. Bundling it"
        echo "as a separate subprocess (never linked into Glitchy's own code) is the standard"
        echo "'mere aggregation' case and doesn't change Glitchy's own MIT license, but if you"
        echo "redistribute this build, ffmpeg's source must remain available -- ffmpeg.org's"
        echo "public source satisfies that. See resources/THIRD_PARTY_NOTICES.md."
    fi
else
    echo "Skipping ffmpeg bundling -- dist/Glitchy.app wasn't built."
fi

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
