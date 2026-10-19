"""Supported video containers and the codecs we pair with them."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VideoFormat:
    name: str
    extension: str
    vcodec: str | None  # None = no video stream (gif handled specially)
    acodec: str | None
    extra: tuple[str, ...] = ()
    crf_codec: bool = True  # accepts -crf


_H264 = ("libx264", "aac")

FORMATS: dict[str, VideoFormat] = {
    f.name: f
    for f in (
        VideoFormat("mp4", ".mp4", *_H264, extra=("-movflags", "+faststart")),
        VideoFormat("mkv", ".mkv", *_H264),
        VideoFormat("mov", ".mov", *_H264, ),
        VideoFormat("m4v", ".m4v", *_H264, ),
        VideoFormat("ts", ".ts", *_H264, ),
        VideoFormat("webm", ".webm", "libvpx-vp9", "libopus", extra=("-b:v", "0")),
        VideoFormat("avi", ".avi", "mpeg4", "libmp3lame", extra=("-vtag", "XVID"), crf_codec=False),
        VideoFormat("wmv", ".wmv", "wmv2", "wmav2", crf_codec=False),
        VideoFormat("flv", ".flv", "flv", "libmp3lame", extra=("-ar", "44100"), crf_codec=False),
        VideoFormat("mpg", ".mpg", "mpeg2video", "mp2", crf_codec=False),
        VideoFormat("3gp", ".3gp", "libx264", "aac", ),
        VideoFormat("gif", ".gif", None, None, crf_codec=False),
    )
}

_ALIASES = {"mpeg": "mpg", "m2ts": "ts", "matroska": "mkv", "quicktime": "mov"}

INPUT_EXTENSIONS = frozenset(
    {f.extension for f in FORMATS.values()} | {".mpeg", ".m2ts", ".mts", ".vob", ".ogv", ".asf"}
)

AUDIO_ONLY_EXTENSIONS = {"mp3": ".mp3", "aac": ".m4a", "wav": ".wav", "flac": ".flac", "opus": ".opus"}


def get_format(name: str) -> VideoFormat:
    key = name.lower().lstrip(".")
    key = _ALIASES.get(key, key)
    try:
        return FORMATS[key]
    except KeyError:
        raise ValueError(
            f"Unsupported output format {name!r}. Supported: {', '.join(sorted(FORMATS))}"
        ) from None
