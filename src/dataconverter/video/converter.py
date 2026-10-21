"""Video conversion via ffmpeg."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from ..audio.ffmpeg import find_tool
from ..audio.formats import get_format as get_audio_format
from ..common import CancelToken, ConversionError, ConversionResult, finalize, ProgressCallback
from ..ffrun import duration_seconds, probe, run_ffmpeg
from .formats import INPUT_EXTENSIONS, get_format


@dataclass
class VideoOptions:
    mode: str = "compress"  # "compress" | "lossless" | "copy" (see build_command)
    crf: int = 23  # quality for mode="compress", lower = better (x264/vp9); ignored by old codecs
    target_size_mb: float | None = None  # mode="compress": aim for (at most about) this file size
    suffix: str = ""  # appended to the file name, e.g. "_small"
    preset: str = "medium"  # x264 speed/size trade-off
    height: int | None = None  # scale to this height, keep aspect (never upscales)
    fps: float | None = None
    audio_bitrate: str = "128k"
    video_bitrate: str | None = None  # for codecs without crf (avi, wmv, flv, mpg)
    gif_width: int = 480
    gif_fps: int = 12
    copy_metadata: bool = True
    overwrite: bool = False


def _scale_filter(height: int | None) -> str | None:
    # -2 keeps the width even and trunc(../2)*2 the height (yuv420p encoders require both);
    # min() avoids upscaling
    return f"scale=-2:'trunc(min({int(height)},ih)/2)*2'" if height else None


_LOSSLESS_AUDIO = {"mkv": "flac", "mp4": "alac", "mov": "alac", "m4v": "alac"}
_LOSSLESS_FORMATS = {"mp4", "mkv", "mov", "m4v", "ts", "webm", "3gp"}
MODES = ("compress", "lossless", "copy")


def build_command(source: Path, target: Path, fmt_name: str, opts: VideoOptions,
                  duration: float | None = None) -> list[str]:
    """Modes: compress = re-encode with CRF (or to `target_size_mb`);
    lossless = re-encode without any quality loss (huge files);
    copy = no re-encoding at all, only change the container (instant, same quality)."""
    fmt = get_format(fmt_name)
    if opts.mode not in MODES:
        raise ConversionError(f"Unknown mode {opts.mode!r}. Use one of: {', '.join(MODES)}.")
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error",
           "-progress", "pipe:1", "-nostats", "-y", "-i", str(source)]
    if opts.mode == "copy":
        if fmt.name == "gif":
            raise ConversionError("GIF cannot be created without re-encoding. Use mode 'compress'.")
        if opts.height or opts.fps or opts.target_size_mb:
            raise ConversionError("Resizing, frame rate and target size need re-encoding; "
                                  "they cannot be combined with mode 'copy'.")
        cmd += ["-map", "0:v:0?", "-map", "0:a:0?", "-sn", "-c", "copy"]
        if fmt.name in ("mp4", "mov", "m4v"):
            cmd += ["-movflags", "+faststart"]
        cmd += ["-map_metadata", "0" if opts.copy_metadata else "-1", str(target)]
        return cmd
    if opts.mode == "lossless":
        if fmt.name not in _LOSSLESS_FORMATS:
            raise ConversionError(
                f"Lossless is not available for {fmt.name.upper()}. Use MKV or MP4 for lossless output.")
    if fmt.name == "gif":
        vf = f"fps={opts.gif_fps},scale='min({opts.gif_width},iw)':-1:flags=lanczos"
        vf += ",split[a][b];[a]palettegen[p];[b][p]paletteuse"
        return cmd + ["-an", "-vf", vf, "-loop", "0", str(target)]

    cmd += ["-map", "0:v:0?", "-map", "0:a:0?", "-sn"]  # first video + audio only; no subs/data
    vf = [f for f in (_scale_filter(opts.height),) if f]
    if opts.fps:
        cmd += ["-r", str(opts.fps)]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    cmd += ["-c:v", fmt.vcodec, "-pix_fmt", "yuv420p"]  # 8-bit 4:2:0 plays everywhere
    audio_codec, audio_args = fmt.acodec, ["-b:a", opts.audio_bitrate]
    if opts.mode == "lossless":
        if fmt.vcodec == "libx264":
            cmd += ["-preset", "veryfast", "-crf", "0"]
        else:  # webm
            cmd += ["-lossless", "1", "-row-mt", "1"]
        if fmt.name in _LOSSLESS_AUDIO:
            audio_codec, audio_args = _LOSSLESS_AUDIO[fmt.name], []
        else:
            audio_args = ["-b:a", "256k" if fmt.name == "webm" else "320k"]  # opus tops out at 256k
    elif opts.target_size_mb:
        if not duration:
            raise ConversionError("Cannot aim for a file size: the video length is unknown.")
        audio_bps = int(opts.audio_bitrate.rstrip("kK")) * 1000 if opts.audio_bitrate.lower().endswith("k") else 128_000
        total_bps = opts.target_size_mb * 8_000_000 * 0.95 / duration  # 5 % head-room for the container
        v_bps = int(total_bps - audio_bps)
        if v_bps < 50_000:
            raise ConversionError(
                f"{opts.target_size_mb:g} MB is too small for a {duration:.0f} s video. Choose a larger size.")
        if fmt.vcodec == "libx264":
            cmd += ["-preset", opts.preset]
        cmd += ["-b:v", str(v_bps), "-maxrate", str(int(v_bps * 1.2)), "-bufsize", str(v_bps * 2)]
    elif fmt.vcodec == "libx264":
        cmd += ["-preset", opts.preset, "-crf", str(opts.crf)]
    elif fmt.vcodec == "libvpx-vp9":
        cmd += ["-crf", str(opts.crf + 8), "-row-mt", "1", "-deadline", "good", "-cpu-used", "4"]
    else:
        cmd += ["-b:v", opts.video_bitrate or "2M"]
    cmd += ["-c:a", audio_codec, *audio_args]
    cmd += list(fmt.extra)
    cmd += ["-map_metadata", "0" if opts.copy_metadata else "-1"]
    cmd.append(str(target))
    return cmd


def _prepare_target(src: Path, ext: str, output_dir, overwrite: bool, suffix: str = "") -> tuple[Path, Path]:
    if not src.is_file():
        raise ConversionError(f"Input file not found: {src}")
    out_dir = Path(output_dir) if output_dir else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / (src.stem + suffix + ext)
    if target.resolve() == src.resolve():
        raise ConversionError("Output would overwrite the input file; choose another folder.")
    if target.exists() and not overwrite:
        raise ConversionError(f"Output already exists: {target}")
    return target, target.with_name(target.stem + ".partial" + target.suffix)


def convert(
    source: str | Path,
    target_format: str,
    output_dir: str | Path | None = None,
    options: VideoOptions | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> Path:
    """Convert one video. Returns the output path. Raises ConversionError/Cancelled."""
    opts = options or VideoOptions()
    src = Path(source)
    fmt = get_format(target_format)
    target, tmp = _prepare_target(src, fmt.extension, output_dir, opts.overwrite, opts.suffix)
    info = probe(src)
    if not any(s.get("codec_type") == "video" for s in info["streams"]):
        raise ConversionError(f"{src.name} has no video stream.")
    total = float(info["format"].get("duration") or 0) or None
    run_ffmpeg(build_command(src, tmp, target_format, opts, total), tmp, src.name, total, progress, cancel)
    finalize(tmp, target)
    if progress:
        progress(1.0)
    return target


def extract_audio(
    source: str | Path,
    audio_format: str = "mp3",
    output_dir: str | Path | None = None,
    bitrate: str | None = "192k",
    overwrite: bool = False,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> Path:
    """Pull the soundtrack out of a video (video -> mp3/wav/flac/...)."""
    from ..audio.converter import AudioOptions, build_command as build_audio

    src = Path(source)
    afmt = get_audio_format(audio_format)
    target, tmp = _prepare_target(src, afmt.extension, output_dir, overwrite)
    info = probe(src)
    if not any(s.get("codec_type") == "audio" for s in info["streams"]):
        raise ConversionError(f"{src.name} has no audio track.")
    total = float(info["format"].get("duration") or 0) or None
    cmd = build_audio(src, tmp, audio_format, AudioOptions(bitrate=bitrate, overwrite=True))
    run_ffmpeg(cmd, tmp, src.name, total, progress, cancel)
    finalize(tmp, target)
    return target


def collect_inputs(paths: Iterable[str | Path], recursive: bool = True) -> list[Path]:
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
    options: VideoOptions | None = None,
    workers: int = 1,
    on_file_done: Callable[[ConversionResult], None] | None = None,
    on_file_progress: Callable[[Path, float], None] | None = None,
    cancel: CancelToken | None = None,
) -> list[ConversionResult]:
    def work(src: Path) -> ConversionResult:
        if cancel and cancel.cancelled:
            return ConversionResult(src, None, False, "Cancelled")
        cb = (lambda f: on_file_progress(src, f)) if on_file_progress else None
        try:
            res = ConversionResult(src, convert(src, target_format, output_dir, options, cb, cancel), True)
        except ConversionError as e:
            res = ConversionResult(src, None, False, str(e))
        if on_file_done:
            on_file_done(res)
        return res

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(work, map(Path, sources)))
