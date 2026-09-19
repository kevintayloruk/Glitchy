@echo off
REM Build Glitchy.exe for Windows. Run this ON WINDOWS -- .exe bundles
REM can't be cross-compiled from macOS/Linux.
REM
REM Usage: build_windows.bat
REM Output: dist\Glitchy\Glitchy.exe

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python not found. Install it from python.org first ^(check "Add to PATH" during install^).
    exit /b 1
)

echo == Setting up a clean virtual environment ==
if exist build_venv rmdir /s /q build_venv
python -m venv build_venv
call build_venv\Scripts\activate.bat
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
pip install pyinstaller --quiet

echo == Building Glitchy.exe ==
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist Glitchy.spec del Glitchy.spec

pyinstaller --name Glitchy --windowed --noconfirm ^
    --icon resources\Glitchy.ico ^
    --add-data "resources;resources" ^
    glitchy_gui.py

call build_venv\Scripts\deactivate.bat

echo.
echo Done. dist\Glitchy\Glitchy.exe is ready.
echo Network Stream (SDP) mode also needs ffmpeg on your PATH -- download it
echo from https://ffmpeg.org/download.html if you don't already have it.
