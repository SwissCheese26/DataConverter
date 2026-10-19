# DataConverter

Windows-Datenkonverter. Aktueller Stand: **Audio-Backend** (Python + ffmpeg).

## Features
- Formate: mp3, wav, flac, ogg, opus, aac, m4a, wma, aiff
- Optionen: Bitrate, Samplerate, Kanäle, Metadaten kopieren, Überschreiben
- Fortschritt pro Datei, Abbruch (`CancelToken`), paralleler Batch, Ordner-Scan
- Schreibt zuerst in `*.partial.*` – keine halbfertigen Dateien bei Fehler/Abbruch

## Nutzung
```
pip install -e .[dev]
dataconverter audio C:\Musik -f mp3 -b 192k -o C:\Out
pytest
```
```python
from dataconverter.audio import convert, AudioOptions
convert("song.flac", "mp3", "out", AudioOptions(bitrate="192k"), progress=print)
```

## ffmpeg
Gesucht wird `ffmpeg.exe`/`ffprobe.exe` in: `$DATACONVERTER_FFMPEG_DIR`, neben der App
(bzw. `bin/` im Repo), dann `PATH`. Für Auslieferung ffmpeg-Binaries mitbündeln (Lizenz beachten, LGPL-Build).
