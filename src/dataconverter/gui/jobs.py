"""GUI-independent glue between the window and the converters (so it can be tested without Qt)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .. import audio, image, video
from ..common import Cancelled, CancelToken, ConversionError

KINDS = ("audio", "image", "video")
AUDIO_ONLY = {"Nur Ton (MP3)": "mp3", "Nur Ton (WAV)": "wav", "Nur Ton (FLAC)": "flac"}
WORKERS = {"audio": 2, "image": 4, "video": 1}


@dataclass
class Settings:
    kind: str
    fmt: str  # format name, or a key of AUDIO_ONLY (video tab)
    output_dir: Path | None = None  # None = next to the original
    suffix: str = ""
    overwrite: bool = False
    options: dict = field(default_factory=dict)


def kind_of(path: str | Path) -> str | None:
    """Which tab a dropped file belongs to (None = not supported)."""
    ext = Path(path).suffix.lower()
    if ext in image.INPUT_EXTENSIONS:
        return "image"
    if ext in video.INPUT_EXTENSIONS:
        return "video"
    if ext in audio.INPUT_EXTENSIONS:
        return "audio"
    return None


def collect(kind: str, paths) -> list[Path]:
    mod = {"audio": audio, "image": image, "video": video}[kind]
    return mod.collect_inputs(paths)


def input_extensions(kind: str) -> list[str]:
    mod = {"audio": audio, "image": image, "video": video}[kind]
    return sorted(mod.INPUT_EXTENSIONS) if hasattr(mod, "INPUT_EXTENSIONS") else []


def target_extension(s: Settings) -> str:
    if s.kind == "video" and s.fmt in AUDIO_ONLY:
        return audio.get_format(AUDIO_ONLY[s.fmt]).extension
    return {"audio": audio, "image": image, "video": video}[s.kind].get_format(s.fmt).extension


def _suffix_for(s: Settings, src: Path) -> str:
    """Same format in the same folder would overwrite the original: add a suffix automatically."""
    if s.suffix:
        return s.suffix
    out = s.output_dir or src.parent
    same_ext = src.suffix.lower() == target_extension(s) or (
        {src.suffix.lower(), target_extension(s)} == {".jpg", ".jpeg"})
    if same_ext and out.resolve() == src.parent.resolve():
        return "_konvertiert"
    return ""


def convert_one(s: Settings, src: Path, progress: Callable[[float], None] | None = None,
                cancel: CancelToken | None = None) -> Path:
    suffix = _suffix_for(s, src)
    o = dict(s.options)
    if s.kind == "audio":
        opts = audio.AudioOptions(overwrite=s.overwrite, suffix=suffix, **o)
        return audio.convert(src, s.fmt, s.output_dir, opts, progress, cancel)
    if s.kind == "image":
        opts = image.ImageOptions(overwrite=s.overwrite, suffix=suffix, **o)
        return image.convert(src, s.fmt, s.output_dir, opts, progress, cancel)
    if s.fmt in AUDIO_ONLY:
        return video.extract_audio(src, AUDIO_ONLY[s.fmt], s.output_dir, overwrite=s.overwrite,
                                   progress=progress, cancel=cancel)
    opts = video.VideoOptions(overwrite=s.overwrite, suffix=suffix, **o)
    return video.convert(src, s.fmt, s.output_dir, opts, progress, cancel)


_TRANSLATIONS = (
    ("Output already exists", "Die Zieldatei existiert schon. „Vorhandene Dateien überschreiben“ aktivieren?"),
    ("Input file not found", "Die Datei wurde nicht gefunden."),
    ("Output would overwrite the input file", "Das Ergebnis würde das Original überschreiben. Anderen Ordner wählen."),
    ("has no video stream", "Diese Datei enthält kein Video."),
    ("has no audio track", "Dieses Video hat keine Tonspur."),
    ("Lossless is not available", "Verlustfrei ist für dieses Format nicht möglich. MKV oder MP4 wählen."),
    ("cannot be made smaller than", "Die gewünschte Größe ist nicht erreichbar. Zusätzlich die Bildgröße verringern."),
    ("is too small for a", "Die Zielgröße ist für diese Videolänge zu klein."),
    ("extremely large", "Das Bild ist extrem groß und wurde zum Schutz des Speichers übersprungen."),
    ("not a supported image", "Keine unterstützte Bilddatei oder Datei beschädigt."),
    ("needs the Cairo", "SVG braucht die Cairo-Bibliothek, die hier fehlt."),
    ("Lossless AVIF with transparency", "Verlustfreies AVIF kann keine Transparenz. PNG oder WebP wählen."),
    ("ffmpeg failed", "ffmpeg konnte die Datei nicht verarbeiten (beschädigt oder Format nicht unterstützt)."),
    ("not found. Put", "ffmpeg wurde nicht gefunden. ffmpeg.exe neben das Programm legen."),
)


def friendly(error: Exception | str) -> str:
    text = str(error)
    for needle, german in _TRANSLATIONS:
        if needle in text:
            return german
    return text


def run_all(
    s: Settings,
    files: list[Path],
    on_progress: Callable[[int, float], None],
    on_done: Callable[[int, str, str, str], None],  # row, state ("ok"|"error"|"cancelled"), message, target
    cancel: CancelToken,
) -> None:
    """Convert `files`; calls back per row. Blocks until finished."""

    def work(i: int) -> None:
        if cancel.cancelled:
            on_done(i, "cancelled", "Abgebrochen", "")
            return
        try:
            out = convert_one(s, files[i], lambda f: on_progress(i, f), cancel)
            on_done(i, "ok", "Fertig", str(out))
        except Cancelled:
            on_done(i, "cancelled", "Abgebrochen", "")
        except ConversionError as e:
            on_done(i, "error", friendly(e), "")
        except Exception as e:  # never let one file kill the batch
            on_done(i, "error", f"Unerwarteter Fehler: {type(e).__name__}: {e}", "")

    with ThreadPoolExecutor(max_workers=WORKERS[s.kind]) as pool:
        list(pool.map(work, range(len(files))))
