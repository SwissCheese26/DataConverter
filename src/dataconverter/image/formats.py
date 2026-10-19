"""Supported image formats (Pillow)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImageFormat:
    name: str
    extension: str
    pil_format: str
    lossy: bool = False
    alpha: bool = True  # can store transparency
    animated: bool = False  # can store multiple frames


FORMATS: dict[str, ImageFormat] = {
    f.name: f
    for f in (
        ImageFormat("jpg", ".jpg", "JPEG", lossy=True, alpha=False),
        ImageFormat("png", ".png", "PNG"),
        ImageFormat("webp", ".webp", "WEBP", lossy=True, animated=True),
        ImageFormat("gif", ".gif", "GIF", animated=True),
        ImageFormat("bmp", ".bmp", "BMP", alpha=False),
        ImageFormat("tiff", ".tiff", "TIFF"),
        ImageFormat("ico", ".ico", "ICO"),
        ImageFormat("avif", ".avif", "AVIF", lossy=True, animated=True),
        ImageFormat("heic", ".heic", "HEIF", lossy=True),
        ImageFormat("pdf", ".pdf", "PDF", alpha=False, animated=True),
        ImageFormat("tga", ".tga", "TGA"),
        ImageFormat("ppm", ".ppm", "PPM", alpha=False),
        ImageFormat("jp2", ".jp2", "JPEG2000", lossy=True),
    )
}

# Formats where lossless=True gives a bit-exact copy of the pixels.
# (jpg and pdf only get the highest quality; their codec cannot be exact.)
TRULY_LOSSLESS = frozenset({"png", "webp", "avif", "heic", "jp2", "tiff", "bmp", "tga", "ppm"})

_ALIASES = {"jpeg": "jpg", "tif": "tiff", "heif": "heic", "jpeg2000": "jp2"}

# Input filter for folder scans; Pillow (+ plugins) decides what it can really open.
INPUT_EXTENSIONS = frozenset(
    {f.extension for f in FORMATS.values()}
    | {".jpeg", ".tif", ".heif", ".svg", ".psd", ".cr2", ".nef", ".arw", ".dng", ".jfif"}
)


def get_format(name: str) -> ImageFormat:
    key = name.lower().lstrip(".")
    key = _ALIASES.get(key, key)
    try:
        return FORMATS[key]
    except KeyError:
        raise ValueError(
            f"Unsupported output format {name!r}. Supported: {', '.join(sorted(FORMATS))}"
        ) from None
