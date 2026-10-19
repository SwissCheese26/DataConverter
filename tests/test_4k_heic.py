"""4K and HEIC, each with compression and without (lossless / stream copy)."""

import math
import subprocess

import numpy as np
import pillow_heif
import pytest
from PIL import Image

from dataconverter.audio.ffmpeg import find_tool
from dataconverter.common import ConversionError
from dataconverter.ffrun import probe
from dataconverter.image import ImageOptions, convert as img_convert
from dataconverter.video import VideoOptions, convert as vid_convert

UHD = (3840, 2160)


# ----------------------------------------------------------------------------- images

def _photo_like(size, seed=1) -> Image.Image:
    """Smooth gradients + edges + mild noise: compresses like a real photo, not like a flat colour."""
    rng = np.random.default_rng(seed)
    w, h = size
    x = np.linspace(0, 1, w)[None, :, None]
    y = np.linspace(0, 1, h)[:, None, None]
    img = np.concatenate([x * 200 + y * 40, (1 - x) * 150 + y * 80, 100 + 80 * np.sin(8 * x + 5 * y)], axis=2)
    img[(h // 4):(h // 2), (w // 4):(w // 2)] = (230, 60, 40)  # a hard-edged block
    img += rng.normal(0, 6, img.shape)
    return Image.fromarray(np.clip(img, 0, 255).astype("uint8"), "RGB")


@pytest.fixture(scope="module")
def uhd_png(tmp_path_factory):
    p = tmp_path_factory.mktemp("uhd") / "uhd.png"
    _photo_like(UHD).save(p)
    return p


def _psnr(a: Image.Image, b: Image.Image) -> float:
    d = np.asarray(a.convert("RGB"), dtype=np.float64) - np.asarray(b.convert("RGB"), dtype=np.float64)
    mse = float((d ** 2).mean())
    return math.inf if mse == 0 else 10 * math.log10(255 ** 2 / mse)


def _same_pixels(a: Image.Image, b: Image.Image) -> bool:
    return np.array_equal(np.asarray(a.convert("RGB")), np.asarray(b.convert("RGB")))


LOSSY = ["jpg", "webp", "avif", "heic", "jp2"]
EXACT = ["png", "webp", "avif", "heic", "jp2", "tiff", "bmp"]


@pytest.mark.parametrize("fmt", LOSSY)
def test_4k_compressed_is_smaller_and_still_good(uhd_png, tmp_path, fmt):
    out = img_convert(uhd_png, fmt, tmp_path, ImageOptions(quality=75))
    ref = img_convert(uhd_png, fmt, tmp_path / "ll", ImageOptions(lossless=True))
    with Image.open(out) as a, Image.open(uhd_png) as o:
        assert a.size == UHD
        assert _psnr(o, a) > 30
    assert out.stat().st_size < ref.stat().st_size


@pytest.mark.parametrize("fmt", EXACT)
def test_4k_lossless_is_pixel_exact(uhd_png, tmp_path, fmt):
    out = img_convert(uhd_png, fmt, tmp_path, ImageOptions(lossless=True))
    with Image.open(out) as a, Image.open(uhd_png) as o:
        assert a.size == UHD and _same_pixels(o, a)


def test_4k_jpeg_lossless_is_near_lossless(uhd_png, tmp_path):
    out = img_convert(uhd_png, "jpg", tmp_path, ImageOptions(lossless=True))
    with Image.open(out) as a, Image.open(uhd_png) as o:
        assert _psnr(o, a) > 40


@pytest.mark.parametrize("fmt", ["jpg", "webp", "avif", "heic", "jp2"])
def test_lower_quality_means_smaller_file(uhd_png, tmp_path, fmt):
    hi = img_convert(uhd_png, fmt, tmp_path / "hi", ImageOptions(quality=90)).stat().st_size
    lo = img_convert(uhd_png, fmt, tmp_path / "lo", ImageOptions(quality=30)).stat().st_size
    assert lo < hi


def test_4k_downscale_to_fhd(uhd_png, tmp_path):
    out = img_convert(uhd_png, "jpg", tmp_path, ImageOptions(max_width=1920, max_height=1080))
    with Image.open(out) as im:
        assert im.size == (1920, 1080)


@pytest.mark.parametrize("fmt", ["jpg", "webp", "avif", "heic"])
def test_compress_to_target_file_size(uhd_png, tmp_path, fmt):
    limit = 400_000
    out = img_convert(uhd_png, fmt, tmp_path, ImageOptions(max_bytes=limit))
    size = out.stat().st_size
    assert size <= limit
    assert size > limit * 0.4, "should use the allowed size, not squash far below it"


def test_target_size_impossible_gives_clear_message(uhd_png, tmp_path):
    with pytest.raises(ConversionError, match="smaller than"):
        img_convert(uhd_png, "jpg", tmp_path, ImageOptions(max_bytes=500))
    assert not list(tmp_path.glob("*.partial*"))


def test_compress_in_place_with_suffix(tmp_path):
    src = tmp_path / "holiday.jpg"
    _photo_like((2000, 1500)).save(src, quality=98)
    before = src.read_bytes()
    out = img_convert(src, "jpg", options=ImageOptions(quality=50, suffix="_small"))
    assert out.name == "holiday_small.jpg" and out.stat().st_size < src.stat().st_size
    assert src.read_bytes() == before


# ----------------------------------------------------------------------------- HEIC

@pytest.fixture(scope="module")
def uhd_heic(tmp_path_factory):
    p = tmp_path_factory.mktemp("heic") / "iphone.heic"
    _photo_like(UHD, seed=2).save(p, format="HEIF", quality=85)
    return p


@pytest.mark.parametrize("fmt", ["jpg", "png", "webp", "tiff", "avif", "jp2", "bmp"])
def test_4k_heic_input(uhd_heic, tmp_path, fmt):
    out = img_convert(uhd_heic, fmt, tmp_path)
    with Image.open(out) as im:
        assert im.size == UHD


@pytest.mark.parametrize("fmt", ["png", "tiff", "webp"])
def test_4k_heic_to_lossless_keeps_decoded_pixels(uhd_heic, tmp_path, fmt):
    out = img_convert(uhd_heic, fmt, tmp_path, ImageOptions(lossless=True))
    with Image.open(uhd_heic) as o, Image.open(out) as a:
        assert _same_pixels(o, a)


def test_heic_compressed_vs_lossless_roundtrip(uhd_png, tmp_path):
    small = img_convert(uhd_png, "heic", tmp_path / "s", ImageOptions(quality=60))
    exact = img_convert(uhd_png, "heic", tmp_path / "e", ImageOptions(lossless=True))
    assert small.stat().st_size < exact.stat().st_size
    back = img_convert(exact, "png", tmp_path / "b")
    with Image.open(uhd_png) as o, Image.open(back) as b:
        assert _same_pixels(o, b)


def test_heic_orientation_is_applied(tmp_path):
    im = Image.new("RGB", (400, 200), "red")
    exif = Image.Exif()
    exif[0x0112] = 6
    src = tmp_path / "rot.heic"
    im.save(src, format="HEIF", quality=80, exif=exif.tobytes())
    with Image.open(img_convert(src, "jpg", tmp_path / "o")) as r:
        assert r.size == (200, 400)


def test_heic_burst_uses_first_image(tmp_path):
    heif = pillow_heif.HeifFile()
    for c in ("red", "green", "blue"):
        heif.add_from_pillow(Image.new("RGB", (64, 64), c))
    src = tmp_path / "burst.heic"
    heif.save(src, quality=90)
    with Image.open(img_convert(src, "png", tmp_path / "o")) as r:
        r = r.convert("RGB")
        assert r.getpixel((5, 5))[0] > 200  # first frame = red


def test_heic_keeps_exif_camera_info(tmp_path):
    exif = Image.Exif()
    exif[0x010F] = "Apple"
    exif[0x0110] = "iPhone 15 Pro"
    src = tmp_path / "meta.heic"
    Image.new("RGB", (100, 100), "gray").save(src, format="HEIF", exif=exif.tobytes())
    with Image.open(img_convert(src, "jpg", tmp_path / "o")) as r:
        assert r.getexif().get(0x0110) == "iPhone 15 Pro"


def test_heic_strip_metadata(tmp_path):
    exif = Image.Exif()
    exif[0x0110] = "iPhone 15 Pro"
    src = tmp_path / "meta.heic"
    Image.new("RGB", (100, 100), "gray").save(src, format="HEIF", exif=exif.tobytes())
    out = img_convert(src, "jpg", tmp_path / "o", ImageOptions(keep_metadata=False))
    with Image.open(out) as r:
        assert r.getexif().get(0x0110) is None


# ----------------------------------------------------------------------------- video

def _ff(*args):
    subprocess.run([find_tool("ffmpeg"), "-v", "error", "-y", *map(str, args)], check=True)


def _frame_hashes(path) -> list[str]:
    out = subprocess.run([find_tool("ffmpeg"), "-v", "error", "-i", str(path), "-map", "0:v:0",
                          "-pix_fmt", "yuv420p", "-f", "framemd5", "-"],
                         capture_output=True, text=True, check=True).stdout
    return [l.split(",")[-1].strip() for l in out.splitlines() if l and not l.startswith("#")]


def _video(path):
    return next(s for s in probe(path)["streams"] if s["codec_type"] == "video")


FAST = dict(preset="ultrafast")


@pytest.fixture(scope="module")
def uhd_clip(tmp_path_factory):
    """4K, 30 fps, 12 frames, noisy (so rate control has something to do), with a tone."""
    p = tmp_path_factory.mktemp("uhdv") / "uhd.mp4"
    _ff("-f", "lavfi", "-i", "testsrc2=size=3840x2160:rate=30:duration=0.4",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=0.4",
        "-vf", "noise=alls=12:allf=t", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", p)
    return p


@pytest.fixture(scope="module")
def uhd_long(tmp_path_factory):
    """4K, 4 s of noisy picture: long enough for bitrate targeting to be meaningful."""
    p = tmp_path_factory.mktemp("uhdl") / "uhd_long.mp4"
    _ff("-f", "lavfi", "-i", "testsrc2=size=3840x2160:rate=24:duration=4",
        "-f", "lavfi", "-i", "sine=duration=4",
        "-vf", "noise=alls=15:allf=t", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "aac", p)
    return p


@pytest.mark.parametrize("fmt", ["mp4", "mkv", "mov", "webm"])
def test_4k_compressed_keeps_resolution(uhd_clip, tmp_path, fmt):
    v = _video(vid_convert(uhd_clip, fmt, tmp_path, VideoOptions(**FAST, crf=28)))
    assert (v["width"], v["height"]) == UHD


@pytest.mark.parametrize("h,size", [(1080, (1920, 1080)), (720, (1280, 720)), (480, (854, 480))])
def test_4k_downscale(uhd_clip, tmp_path, h, size):
    v = _video(vid_convert(uhd_clip, "mp4", tmp_path, VideoOptions(**FAST, height=h)))
    assert (v["width"], v["height"]) == size


def test_higher_crf_means_smaller_4k_file(uhd_clip, tmp_path):
    lo = vid_convert(uhd_clip, "mp4", tmp_path / "lo", VideoOptions(**FAST, crf=38))
    hi = vid_convert(uhd_clip, "mp4", tmp_path / "hi", VideoOptions(**FAST, crf=16))
    assert lo.stat().st_size < hi.stat().st_size


def test_4k_lossless_has_identical_frames(uhd_clip, tmp_path):
    out = vid_convert(uhd_clip, "mkv", tmp_path, VideoOptions(mode="lossless"))
    assert _frame_hashes(out) == _frame_hashes(uhd_clip)
    assert out.stat().st_size > uhd_clip.stat().st_size


def test_lossless_mp4_has_identical_frames(uhd_clip, tmp_path):
    out = vid_convert(uhd_clip, "mp4", tmp_path, VideoOptions(mode="lossless"))
    assert _frame_hashes(out) == _frame_hashes(uhd_clip)
    assert any(s["codec_name"] == "alac" for s in probe(out)["streams"])


def test_lossless_webm(uhd_clip, tmp_path):
    out = vid_convert(uhd_clip, "webm", tmp_path, VideoOptions(mode="lossless"))
    assert _frame_hashes(out) == _frame_hashes(uhd_clip)


@pytest.mark.parametrize("fmt", ["avi", "wmv", "flv", "mpg", "gif"])
def test_lossless_not_available_says_so(uhd_clip, tmp_path, fmt):
    with pytest.raises(ConversionError, match="Lossless is not available"):
        vid_convert(uhd_clip, fmt, tmp_path, VideoOptions(mode="lossless"))


def test_copy_mode_changes_container_without_touching_the_picture(uhd_clip, tmp_path):
    out = vid_convert(uhd_clip, "mkv", tmp_path, VideoOptions(mode="copy"))
    assert _frame_hashes(out) == _frame_hashes(uhd_clip)
    assert _video(out)["codec_name"] == "h264" and (_video(out)["width"], _video(out)["height"]) == UHD


def test_copy_mode_is_much_faster_than_reencoding(uhd_clip, tmp_path):
    import time
    t = time.time(); vid_convert(uhd_clip, "mov", tmp_path / "c", VideoOptions(mode="copy")); copy_t = time.time() - t
    t = time.time(); vid_convert(uhd_clip, "mov", tmp_path / "r", VideoOptions(preset="slow")); enc_t = time.time() - t
    assert copy_t < enc_t


def test_copy_mode_rejects_resize_and_gif(uhd_clip, tmp_path):
    with pytest.raises(ConversionError, match="re-encoding"):
        vid_convert(uhd_clip, "mkv", tmp_path, VideoOptions(mode="copy", height=720))
    with pytest.raises(ConversionError, match="GIF"):
        vid_convert(uhd_clip, "gif", tmp_path, VideoOptions(mode="copy"))


def test_copy_into_incompatible_container_gives_readable_error(uhd_clip, tmp_path):
    with pytest.raises(ConversionError):
        vid_convert(uhd_clip, "webm", tmp_path, VideoOptions(mode="copy"))  # h264 cannot live in WebM
    assert not list(tmp_path.glob("*"))


def test_unknown_mode(uhd_clip, tmp_path):
    with pytest.raises(ConversionError, match="Unknown mode"):
        vid_convert(uhd_clip, "mp4", tmp_path, VideoOptions(mode="turbo"))


def test_target_size_is_respected(uhd_long, tmp_path):
    target_mb = 3.0
    out = vid_convert(uhd_long, "mp4", tmp_path, VideoOptions(**FAST, target_size_mb=target_mb))
    mb = out.stat().st_size / 1e6
    assert mb <= target_mb * 1.15, f"{mb:.2f} MB is over the {target_mb} MB target"
    assert mb >= target_mb * 0.5, f"{mb:.2f} MB wastes the allowed size"


def test_target_size_too_small_gives_clear_message(uhd_long, tmp_path):
    with pytest.raises(ConversionError, match="too small"):
        vid_convert(uhd_long, "mp4", tmp_path, VideoOptions(**FAST, target_size_mb=0.05))


def test_4k_hevc_source(tmp_path):
    src = tmp_path / "hevc.mp4"
    _ff("-f", "lavfi", "-i", "testsrc2=size=3840x2160:rate=30:duration=0.4", "-c:v", "libx265",
        "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-x265-params", "log-level=error", src)
    v = _video(vid_convert(src, "mp4", tmp_path / "o", VideoOptions(**FAST, height=1080)))
    assert v["codec_name"] == "h264" and v["height"] == 1080


def test_4k_60fps_to_30fps(tmp_path):
    src = tmp_path / "60.mp4"
    _ff("-f", "lavfi", "-i", "testsrc=size=3840x2160:rate=60:duration=0.5", "-c:v", "libx264",
        "-preset", "ultrafast", "-pix_fmt", "yuv420p", src)
    v = _video(vid_convert(src, "mp4", tmp_path / "o", VideoOptions(**FAST, fps=30)))
    assert v["r_frame_rate"] == "30/1"


def test_compress_video_in_place_with_suffix(uhd_clip, tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(uhd_clip.read_bytes())
    out = vid_convert(src, "mp4", options=VideoOptions(**FAST, crf=34, suffix="_small"))
    assert out.name == "clip_small.mp4" and out.stat().st_size < src.stat().st_size


def test_4k_progress_and_audio_survive(uhd_clip, tmp_path):
    seen = []
    out = vid_convert(uhd_clip, "mp4", tmp_path, VideoOptions(**FAST), progress=seen.append)
    assert seen[-1] == 1.0
    assert any(s["codec_type"] == "audio" for s in probe(out)["streams"])
