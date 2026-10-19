"""Supported audio formats and their ffmpeg encoder settings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AudioFormat:
    name: str
    extension: str
    codec: str | None  # ffmpeg audio encoder; None = ffmpeg default
    lossy: bool
    container_args: tuple[str, ...] = ()


FORMATS: dict[str, AudioFormat] = {
    f.name: f
    for f in (
        AudioFormat("mp3", ".mp3", "libmp3lame", True),
        AudioFormat("wav", ".wav", "pcm_s16le", False),
        AudioFormat("flac", ".flac", "flac", False),
        AudioFormat("ogg", ".ogg", "libvorbis", True),
        AudioFormat("opus", ".opus", "libopus", True),
        AudioFormat("aac", ".aac", "aac", True, ("-f", "adts")),
        AudioFormat("m4a", ".m4a", "aac", True),
        AudioFormat("wma", ".wma", "wmav2", True),
        AudioFormat("aiff", ".aiff", "pcm_s16be", False),
    )
}

# Extensions we accept as input (ffmpeg can decode far more; this is the UI/batch filter).
INPUT_EXTENSIONS = frozenset(
    {f.extension for f in FORMATS.values()} | {".aif", ".mp2", ".amr", ".ac3", ".mka", ".webm"}
)


def get_format(name: str) -> AudioFormat:
    key = name.lower().lstrip(".")
    if key == "aif":
        key = "aiff"
    try:
        return FORMATS[key]
    except KeyError:
        raise ValueError(
            f"Unsupported output format {name!r}. Supported: {', '.join(sorted(FORMATS))}"
        ) from None
