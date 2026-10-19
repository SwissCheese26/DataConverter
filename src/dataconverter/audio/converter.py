"""Audio conversion via ffmpeg."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from ..common import Cancelled, CancelToken, ConversionError, ConversionResult, ProgressCallback
from ..ffrun import duration_seconds, probe, run_ffmpeg
from .ffmpeg import find_tool
from .formats import INPUT_EXTENSIONS, get_format


@dataclass
class AudioOptions:
    bitrate: str | None = None  # e.g. "192k" (lossy formats only)
    sample_rate: int | None = None  # Hz
    channels: int | None = None  # 1 = mono, 2 = stereo
    quality: int | None = None  # codec VBR quality (-q:a), lossy only
    copy_metadata: bool = True
    overwrite: bool = False
    suffix: str = ""  # appended to the file name, e.g. "_small"


def build_command(source: Path, target: Path, fmt_name: str, opts: AudioOptions) -> list[str]:
    fmt = get_format(fmt_name)
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error",
           "-progress", "pipe:1", "-nostats", "-y" if opts.overwrite else "-n",
           "-i", str(source), "-vn"]  # drop cover-art/video streams
    if fmt.codec:
        cmd += ["-c:a", fmt.codec]
    if fmt.lossy:
        if opts.quality is not None:
            cmd += ["-q:a", str(opts.quality)]
        elif opts.bitrate:
            cmd += ["-b:a", opts.bitrate]
    if opts.sample_rate:
        cmd += ["-ar", str(opts.sample_rate)]
    if opts.channels:
        cmd += ["-ac", str(opts.channels)]
    cmd += ["-map_metadata", "0" if opts.copy_metadata else "-1"]
    cmd += list(fmt.container_args)
    cmd.append(str(target))
    return cmd


def convert(
    source: str | Path,
    target_format: str,
    output_dir: str | Path | None = None,
    options: AudioOptions | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> Path:
    """Convert one file. Returns the output path. Raises ConversionError/Cancelled."""
    opts = options or AudioOptions()
    src = Path(source)
    if not src.is_file():
        raise ConversionError(f"Input file not found: {src}")
    fmt = get_format(target_format)
    out_dir = Path(output_dir) if output_dir else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / (src.stem + opts.suffix + fmt.extension)
    if target.resolve() == src.resolve():
        raise ConversionError("Output would overwrite the input file; choose another folder.")
    if target.exists() and not opts.overwrite:
        raise ConversionError(f"Output already exists: {target}")

    total = duration_seconds(src) if progress else None
    # Write to a temp name so a failed/cancelled run never leaves a half file at `target`.
    tmp = target.with_name(target.stem + ".partial" + target.suffix)
    cmd = build_command(src, tmp, target_format, AudioOptions(**{**opts.__dict__, "overwrite": True}))
    run_ffmpeg(cmd, tmp, src.name, total, progress, cancel)
    tmp.replace(target)
    if progress:
        progress(1.0)
    return target


def collect_inputs(paths: Iterable[str | Path], recursive: bool = True) -> list[Path]:
    """Expand files/folders into a list of supported audio files."""
    found: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            it = p.rglob("*") if recursive else p.glob("*")
            found += sorted(f for f in it if f.is_file() and f.suffix.lower() in INPUT_EXTENSIONS)
        elif p.is_file():
            found.append(p)
    return found


def convert_batch(
    sources: Iterable[str | Path],
    target_format: str,
    output_dir: str | Path | None = None,
    options: AudioOptions | None = None,
    workers: int = 2,
    on_file_done: Callable[[ConversionResult], None] | None = None,
    on_file_progress: Callable[[Path, float], None] | None = None,
    cancel: CancelToken | None = None,
) -> list[ConversionResult]:
    """Convert many files in parallel. Never raises per-file; errors go into the results."""
    files = list(map(Path, sources))

    def work(src: Path) -> ConversionResult:
        if cancel and cancel.cancelled:
            return ConversionResult(src, None, False, "Cancelled")
        cb = (lambda f: on_file_progress(src, f)) if on_file_progress else None
        try:
            out = convert(src, target_format, output_dir, options, cb, cancel)
            res = ConversionResult(src, out, True)
        except ConversionError as e:
            res = ConversionResult(src, None, False, str(e))
        if on_file_done:
            on_file_done(res)
        return res

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(work, files))
