"""Conversion self-test, run inside the packaged app: `DataConverter.exe --selftest-convert report.txt`.

Checks that the bundled ffmpeg and the image libraries really work after PyInstaller packaging,
which the startup self-test alone cannot show.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from ..audio.ffmpeg import find_tool, popen_flags
from . import jobs


def _ffmpeg(*args) -> None:
    subprocess.run([find_tool("ffmpeg"), "-v", "error", "-y", *map(str, args)], check=True,
                   capture_output=True, **popen_flags())


def run(report: Path) -> int:
    from PIL import Image

    lines: list[str] = []
    failed = 0

    def check(label: str, fn, required: bool = True) -> None:
        nonlocal failed
        try:
            out = fn()
            size = Path(out).stat().st_size
            if size == 0:
                raise RuntimeError("empty output file")
            lines.append(f"OK    {label} ({size} bytes)")
        except Exception as e:  # report everything, never stop at the first problem
            lines.append(f"{'FAIL' if required else 'INFO'}  {label}: {type(e).__name__}: {e}")
            if required:
                failed += 1

    with tempfile.TemporaryDirectory(prefix="Daten Ärger ") as td:
        d = Path(td)
        try:
            Image.new("RGB", (320, 200), (30, 120, 200)).save(d / "bild.png")
            (d / "icon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32">'
                                        '<circle cx="16" cy="16" r="14"/></svg>')
            _ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=1", d / "ton.wav")
            _ffmpeg("-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=1", "-f", "lavfi", "-i",
                    "sine=duration=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", d / "film.mp4")
        except Exception as e:
            report.write_text(f"FAIL  could not create test files with the bundled ffmpeg: {e}\n", encoding="utf-8")
            return 1

        def conv(kind, fmt, name, out="out", **options):
            return lambda: jobs.convert_one(jobs.Settings(kind, fmt, d / out, options=options), d / name)

        for fmt in ("jpg", "webp", "avif", "heic", "tiff", "pdf"):
            check(f"image png -> {fmt}", conv("image", fmt, "bild.png"))
        check("image png -> heic (lossless)", conv("image", "heic", "bild.png", out="lossless", lossless=True))
        check("image png -> avif (lossless, via ffmpeg)", conv("image", "avif", "bild.png", out="lossless", lossless=True))
        for fmt in ("mp3", "flac", "ogg"):
            check(f"audio wav -> {fmt}", conv("audio", fmt, "ton.wav"))
        for fmt in ("mkv", "webm", "mov"):
            check(f"video mp4 -> {fmt}", conv("video", fmt, "film.mp4"))
        check("video mp4 -> mp3 (audio only)", conv("video", "Nur Ton (MP3)", "film.mp4"))
        check("image svg -> png (needs Cairo, see issue #5)", conv("image", "png", "icon.svg"), required=False)

    report.write_text("\n".join(lines) + f"\n{len(lines) - failed} checks ok, {failed} failed\n", encoding="utf-8")
    return 1 if failed else 0
