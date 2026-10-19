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

## Bilder & Video
```
dataconverter image C:\Fotos -f webp -q 85 --max-width 1920 -o C:\Out
dataconverter video film.mkv -f mp4 --height 720 --crf 23
dataconverter video film.mp4 -f mp4 --extract-audio mp3
```
Bilder: jpg, png, webp, gif, bmp, tiff, ico, avif, heic, pdf, tga, ppm, jp2 (Eingabe zusätzlich SVG, PSD, RAW).
Video: mp4, mkv, mov, m4v, ts, webm, avi, wmv, flv, mpg, 3gp, gif. Es wird immer die erste Video- und Tonspur übernommen.
Offene Punkte stehen als GitHub-Issues.

## Oberfläche (Windows)
```
pip install -e .
dataconverter-gui          # oder: python -m dataconverter.gui
```
Drei Reiter (Audio, Bilder, Video): Dateien oder ganze Ordner hineinziehen, Zielformat und Art wählen
(komprimiert, verlustfrei, Zielgröße, bei Video auch „ohne Neukodierung“), umwandeln. Abbrechen jederzeit möglich;
Doppelklick auf eine fertige Zeile öffnet den Ordner.

Fertige `.exe` bauen: `./build_windows.ps1` (oder in GitHub: Actions → tests → *Run workflow*, das Ergebnis
liegt als Artefakt `DataConverter-windows` bereit; ffmpeg ist darin enthalten).
