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

echo == Bundling ffmpeg so end users don't need it installed ==
if exist "dist\Glitchy\ffmpeg_bundle" rmdir /s /q "dist\Glitchy\ffmpeg_bundle"
mkdir "dist\Glitchy\ffmpeg_bundle"
if exist ffmpeg_temp.zip del ffmpeg_temp.zip
powershell -NoProfile -Command "$ProgressPreference = 'SilentlyContinue'; Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile 'ffmpeg_temp.zip'"
if not exist ffmpeg_temp.zip (
    echo WARNING: could not download ffmpeg automatically -- skipping bundling.
    echo Network Stream mode will require end users to install ffmpeg themselves.
    goto :skip_ffmpeg_bundle
)
powershell -NoProfile -Command "Expand-Archive -Path 'ffmpeg_temp.zip' -DestinationPath 'ffmpeg_temp_extracted' -Force"
for /d %%D in (ffmpeg_temp_extracted\ffmpeg-*) do copy "%%D\bin\ffmpeg.exe" "dist\Glitchy\ffmpeg_bundle\ffmpeg.exe" >nul
del ffmpeg_temp.zip
rmdir /s /q ffmpeg_temp_extracted
if exist "dist\Glitchy\ffmpeg_bundle\ffmpeg.exe" (
    echo ffmpeg bundled into the app -- Network Stream mode will work with no separate install.
    echo NOTE: this build of ffmpeg is GPL-3.0 licensed ^(not LGPL^) -- see
    echo resources\THIRD_PARTY_NOTICES.md for what that means for redistribution.
) else (
    echo WARNING: ffmpeg download/extraction didn't produce ffmpeg.exe -- skipping bundling.
)
:skip_ffmpeg_bundle

echo.
echo Done. dist\Glitchy\Glitchy.exe is ready.
if not exist "dist\Glitchy\ffmpeg_bundle\ffmpeg.exe" (
    echo Network Stream ^(SDP^) mode also needs ffmpeg on your PATH -- download it
    echo from https://ffmpeg.org/download.html if you don't already have it.
)
