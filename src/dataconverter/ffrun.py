"""Run an ffmpeg command with progress reporting and cancellation (shared by audio + video)."""

from __future__ import annotations

import json
import re
import subprocess
import threading
from pathlib import Path

from .audio.ffmpeg import find_tool, popen_flags
from .common import Cancelled, CancelToken, ConversionError, ProgressCallback

_TIME_RE = re.compile(r"out_time_us=(\d+)")


def probe(path: str | Path) -> dict:
    """Return ffprobe info (format + streams) as a dict."""
    cmd = [find_tool("ffprobe"), "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **popen_flags())
    if proc.returncode != 0:
        raise ConversionError(f"Cannot read {path}: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def duration_seconds(path: str | Path) -> float | None:
    try:
        return float(probe(path)["format"]["duration"])
    except (KeyError, ValueError, ConversionError):
        return None


def run_ffmpeg(
    cmd: list[str],
    tmp: Path,
    name: str,
    total: float | None,
    progress: ProgressCallback | None,
    cancel: CancelToken | None,
) -> None:
    """Run `cmd` (which writes to `tmp`). Deletes `tmp` and raises on failure/cancel."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", **popen_flags())
    stderr_buf: list[str] = []
    t = threading.Thread(target=lambda: stderr_buf.append(proc.stderr.read()), daemon=True)
    t.start()
    try:
        for line in proc.stdout:
            if cancel and cancel.cancelled:
                proc.kill()
                break
            m = _TIME_RE.match(line.strip())
            if m and progress and total:
                progress(min(int(m.group(1)) / 1e6 / total, 1.0))
        proc.wait()
        t.join()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    if cancel and cancel.cancelled:
        tmp.unlink(missing_ok=True)
        raise Cancelled(f"Cancelled: {name}")
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise ConversionError(f"ffmpeg failed for {name}: {''.join(stderr_buf).strip()}")
