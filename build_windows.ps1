# Builds dist\DataConverter\DataConverter.exe (a folder you can zip and hand out).
# Needs: Python 3.10+, and ffmpeg.exe + ffprobe.exe (path via -FfmpegDir, or already on PATH).
param([string]$FfmpegDir = "")

$ErrorActionPreference = "Stop"
python -m pip install -e . pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --name DataConverter `
    --collect-all pillow_heif --collect-all psd_tools --collect-data cairosvg `
    --paths src src\dataconverter\gui\__main__.py

if (-not $FfmpegDir) { $FfmpegDir = Split-Path (Get-Command ffmpeg).Source }
Copy-Item "$FfmpegDir\ffmpeg.exe", "$FfmpegDir\ffprobe.exe" dist\DataConverter\
Write-Host "Done: dist\DataConverter\DataConverter.exe"
