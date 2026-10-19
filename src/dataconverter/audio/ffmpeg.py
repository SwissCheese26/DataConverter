"""Locating ffmpeg/ffprobe (bundled next to the app, env override, or PATH)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


class FFmpegNotFoundError(RuntimeError):
    pass


def _candidate_dirs() -> list[Path]:
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):  # PyInstaller build
        dirs.append(Path(sys.executable).parent)
        dirs.append(Path(getattr(sys, "_MEIPASS", sys.executable)))
    dirs.append(Path(__file__).resolve().parents[3] / "bin")
    return dirs


def find_tool(name: str) -> str:
    """Resolve `ffmpeg` or `ffprobe`. Order: $DATACONVERTER_FFMPEG_DIR, bundled dirs, PATH."""
    exe = name + (".exe" if os.name == "nt" else "")
    env_dir = os.environ.get("DATACONVERTER_FFMPEG_DIR")
    dirs = ([Path(env_dir)] if env_dir else []) + _candidate_dirs()
    for d in dirs:
        p = d / exe
        if p.is_file():
            return str(p)
    found = shutil.which(name)
    if found:
        return found
    raise FFmpegNotFoundError(
        f"{name} not found. Put {exe} next to the app, set DATACONVERTER_FFMPEG_DIR, or add it to PATH."
    )


def popen_flags() -> dict:
    """Hide the console window when spawning ffmpeg from a Windows GUI app."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}
