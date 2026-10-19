"""Image conversion via Pillow (optional: pillow-heif, cairosvg, rawpy)."""

from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from PIL import Image, ImageOps, UnidentifiedImageError

from ..common import CancelToken, ConversionError, ConversionResult, ProgressCallback
from .formats import INPUT_EXTENSIONS, ImageFormat, get_format

try:  # HEIC/HEIF read + write
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover
    pillow_heif = None

_SVG_EXT = {".svg", ".svgz"}
_RAW_EXT = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2", ".raf"}


@dataclass
class ImageOptions:
    quality: int = 90  # 1..100 for lossy formats
    max_width: int | None = None  # downscale to fit, keep aspect ratio
    max_height: int | None = None
    background: tuple[int, int, int] = (255, 255, 255)  # used where alpha can't be stored
    keep_metadata: bool = True  # EXIF / ICC
    auto_rotate: bool = True  # apply EXIF orientation
    ico_sizes: tuple[int, ...] = (16, 32, 48, 64, 128, 256)
    svg_dpi: int = 96
    overwrite: bool = False


def _open(src: Path, opts: ImageOptions) -> Image.Image:
    ext = src.suffix.lower()
    if ext in _SVG_EXT:
        try:
            import cairosvg
        except ImportError:
            raise ConversionError("SVG input needs the 'cairosvg' package.") from None
        try:
            png = cairosvg.svg2png(url=str(src), dpi=opts.svg_dpi)
        except ValueError:  # no width/height/viewBox: render on a default canvas
            png = cairosvg.svg2png(url=str(src), dpi=opts.svg_dpi,
                                   parent_width=512, parent_height=512)
        return Image.open(io.BytesIO(png))
    if ext == ".psd":
        try:
            return Image.open(src)  # 8-bit files
        except UnidentifiedImageError:
            pass
        try:
            from psd_tools import PSDImage
        except ImportError:
            raise ConversionError(f"{src.name}: this PSD needs the 'psd-tools' package.") from None
        return PSDImage.open(src).composite()
    if ext in _RAW_EXT:
        try:
            import rawpy
        except ImportError:
            raise ConversionError("RAW input needs the 'rawpy' package.") from None
        with rawpy.imread(str(src)) as raw:
            return Image.fromarray(raw.postprocess())
    try:
        return Image.open(src)
    except UnidentifiedImageError:
        raise ConversionError(f"{src.name}: not a supported image (or the file is damaged).") from None
    except OSError as e:
        raise ConversionError(f"{src.name}: cannot be read ({e}).") from None


def _flatten(im: Image.Image, bg: tuple[int, int, int]) -> Image.Image:
    rgba = im.convert("RGBA")
    base = Image.new("RGBA", rgba.size, (*bg, 255))
    return Image.alpha_composite(base, rgba).convert("RGB")


def _prepare(im: Image.Image, fmt: ImageFormat, opts: ImageOptions) -> Image.Image:
    has_alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
    if opts.auto_rotate:
        im = ImageOps.exif_transpose(im)
    if opts.max_width or opts.max_height:
        box = (opts.max_width or im.width, opts.max_height or im.height)
        if im.width > box[0] or im.height > box[1]:
            im = im.copy()
            im.thumbnail(box, Image.LANCZOS)
    if has_alpha and not fmt.alpha:
        return _flatten(im, opts.background)
    if fmt.name in ("jpg", "bmp", "ppm", "pdf") and im.mode not in ("RGB", "L"):
        return im.convert("RGB")
    if im.mode in ("P", "PA") and fmt.name not in ("gif", "png"):
        return im.convert("RGBA" if has_alpha else "RGB")
    if im.mode in ("CMYK",) and fmt.name not in ("jpg", "tiff", "pdf"):
        return im.convert("RGB")
    if im.mode in ("I;16", "I", "F") and fmt.name not in ("png", "tiff"):
        return im.point(lambda v: v / 256).convert("L") if im.mode == "I;16" else im.convert("RGB")
    return im


def _square(im: Image.Image, minimum: int) -> Image.Image:
    """Icons must be square: pad with transparency, and enlarge tiny images to `minimum`."""
    im = im.convert("RGBA")
    side = max(im.size)
    if side < minimum:
        scale = minimum / side
        im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
        side = minimum
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
    return canvas


def _frames(src_im: Image.Image, fmt: ImageFormat, opts: ImageOptions) -> list[Image.Image]:
    n = getattr(src_im, "n_frames", 1)
    count = n if (fmt.animated and n > 1) else 1
    out = []
    for i in range(count):
        src_im.seek(i)
        out.append(_prepare(src_im.copy(), fmt, opts))
    return out


def convert(
    source: str | Path,
    target_format: str,
    output_dir: str | Path | None = None,
    options: ImageOptions | None = None,
    progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
) -> Path:
    """Convert one image. Returns the output path. Raises ConversionError."""
    opts = options or ImageOptions()
    src = Path(source)
    if not src.is_file():
        raise ConversionError(f"Input file not found: {src}")
    fmt = get_format(target_format)
    if fmt.name == "heic" and pillow_heif is None:
        raise ConversionError("HEIC output needs the 'pillow-heif' package.")
    out_dir = Path(output_dir) if output_dir else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / (src.stem + fmt.extension)
    if target.resolve() == src.resolve():
        raise ConversionError("Output would overwrite the input file; choose another folder.")
    if target.exists() and not opts.overwrite:
        raise ConversionError(f"Output already exists: {target}")
    if cancel and cancel.cancelled:
        from ..common import Cancelled
        raise Cancelled(f"Cancelled: {src.name}")

    tmp = target.with_name(target.stem + ".partial" + target.suffix)
    try:
        with _open(src, opts) as im:
            frames = _frames(im, fmt, opts)
            save_kw: dict = {}
            if fmt.lossy:
                save_kw["quality"] = max(1, min(100, opts.quality))
            if opts.keep_metadata:
                if im.info.get("icc_profile") and fmt.name in ("jpg", "png", "webp", "tiff"):
                    save_kw["icc_profile"] = im.info["icc_profile"]
                exif = im.getexif()
                if exif and fmt.name in ("jpg", "png", "webp", "tiff", "avif"):
                    exif.pop(0x0112, None)  # orientation already applied
                    save_kw["exif"] = exif.tobytes()
            if fmt.name == "ico":
                frames[0] = _square(frames[0], min(opts.ico_sizes))
                biggest = frames[0].width
                save_kw["sizes"] = [(s, s) for s in opts.ico_sizes if s <= biggest]
            if len(frames) > 1:
                save_kw.update(save_all=True, append_images=frames[1:])
                if "duration" in im.info:
                    save_kw["duration"] = int(im.info["duration"])
                if fmt.name in ("gif", "webp"):
                    save_kw["loop"] = im.info.get("loop", 0)
            if fmt.name == "gif" and frames[0].mode == "RGBA":
                frames = [f.convert("P", palette=Image.ADAPTIVE) for f in frames]
            frames[0].save(tmp, format=fmt.pil_format, **save_kw)
    except ConversionError:
        tmp.unlink(missing_ok=True)
        raise
    except Image.DecompressionBombError:
        tmp.unlink(missing_ok=True)
        raise ConversionError(
            f"{src.name} is extremely large (over {Image.MAX_IMAGE_PIXELS * 2 // 1_000_000} megapixels). "
            "It was skipped to protect your computer from running out of memory."
        ) from None
    except Exception as e:  # Pillow raises many types (OSError, ValueError, KeyError, ...)
        tmp.unlink(missing_ok=True)
        raise ConversionError(f"{src.name}: conversion to {fmt.name} failed ({type(e).__name__}: {e})") from e
    tmp.replace(target)
    if progress:
        progress(1.0)
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
    options: ImageOptions | None = None,
    workers: int = 4,
    on_file_done: Callable[[ConversionResult], None] | None = None,
    cancel: CancelToken | None = None,
) -> list[ConversionResult]:
    def work(src: Path) -> ConversionResult:
        if cancel and cancel.cancelled:
            return ConversionResult(src, None, False, "Cancelled")
        try:
            res = ConversionResult(src, convert(src, target_format, output_dir, options, cancel=cancel), True)
        except ConversionError as e:
            res = ConversionResult(src, None, False, str(e))
        if on_file_done:
            on_file_done(res)
        return res

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(work, map(Path, sources)))
