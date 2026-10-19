"""Image tests use real files generated on disk (and the converter writes real files back)."""

import shutil
import subprocess

import pytest
from PIL import Image, ImageDraw

from dataconverter.audio.ffmpeg import find_tool
from dataconverter.common import ConversionError
from dataconverter.image import ImageOptions, collect_inputs, convert, convert_batch


@pytest.fixture
def photo(tmp_path):
    im = Image.new("RGB", (640, 480), (30, 120, 200))
    ImageDraw.Draw(im).ellipse((100, 100, 500, 400), fill=(250, 200, 20))
    p = tmp_path / "photo.png"
    im.save(p)
    return p


@pytest.fixture
def transparent(tmp_path):
    im = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
    ImageDraw.Draw(im).rectangle((20, 20, 100, 80), fill=(255, 0, 0, 255))
    p = tmp_path / "logo.png"
    im.save(p)
    return p


@pytest.mark.parametrize("fmt", ["jpg", "png", "webp", "gif", "bmp", "tiff", "ico", "avif",
                                 "heic", "pdf", "tga", "ppm", "jp2"])
def test_all_output_formats(photo, tmp_path, fmt):
    out = convert(photo, fmt, tmp_path / "o")
    assert out.suffix == "." + ("tiff" if fmt == "tiff" else fmt) and out.stat().st_size > 0
    if fmt != "pdf":
        with Image.open(out) as im:
            assert im.size[0] > 0


@pytest.mark.parametrize("fmt", ["jpg", "bmp", "ppm", "pdf"])
def test_transparency_is_flattened_onto_white(transparent, tmp_path, fmt):
    out = convert(transparent, fmt, tmp_path / "o")
    if fmt == "pdf":
        return
    with Image.open(out) as im:
        assert im.convert("RGB").getpixel((0, 0))[0] > 240  # was transparent -> white, not black


def test_transparency_kept_for_png_webp(transparent, tmp_path):
    for fmt in ("png", "webp", "tiff"):
        out = convert(transparent, fmt, tmp_path / "o")
        with Image.open(out) as im:
            assert im.convert("RGBA").getpixel((0, 0))[3] == 0


def test_resize_keeps_aspect(photo, tmp_path):
    out = convert(photo, "jpg", tmp_path, ImageOptions(max_width=320, max_height=320))
    with Image.open(out) as im:
        assert im.size == (320, 240)


def test_never_upscales(photo, tmp_path):
    out = convert(photo, "jpg", tmp_path, ImageOptions(max_width=5000))
    with Image.open(out) as im:
        assert im.size == (640, 480)


def test_quality_changes_size(photo, tmp_path):
    lo = convert(photo, "jpg", tmp_path / "lo", ImageOptions(quality=10))
    hi = convert(photo, "jpg", tmp_path / "hi", ImageOptions(quality=95))
    assert lo.stat().st_size < hi.stat().st_size


def test_exif_orientation_applied(tmp_path):
    im = Image.new("RGB", (200, 100), "red")
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 CW when displayed
    src = tmp_path / "rot.jpg"
    im.save(src, exif=exif.tobytes())
    out = convert(src, "png", tmp_path / "o")
    with Image.open(out) as r:
        assert r.size == (100, 200)


def test_animated_gif_to_webp_and_back(tmp_path):
    frames = [Image.new("RGB", (64, 64), c) for c in ("red", "green", "blue")]
    gif = tmp_path / "anim.gif"
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=100, loop=0)
    webp = convert(gif, "webp", tmp_path / "o")
    with Image.open(webp) as im:
        assert im.n_frames == 3
    back = convert(webp, "gif", tmp_path / "o2")
    with Image.open(back) as im:
        assert im.n_frames == 3


def test_multipage_to_pdf(tmp_path):
    frames = [Image.new("RGB", (64, 64), c) for c in ("red", "blue")]
    gif = tmp_path / "two.gif"
    frames[0].save(gif, save_all=True, append_images=frames[1:])
    out = convert(gif, "pdf", tmp_path / "o")
    assert out.read_bytes().count(b"/Type /Page\n") + out.read_bytes().count(b"/Type /Page ") >= 2


def test_svg_input(tmp_path):
    svg = tmp_path / "icon.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
                   '<circle cx="32" cy="32" r="30" fill="green"/></svg>')
    out = convert(svg, "png", tmp_path / "o")
    with Image.open(out) as im:
        assert im.size == (64, 64)


def test_heic_roundtrip(photo, tmp_path):
    heic = convert(photo, "heic", tmp_path / "h")
    back = convert(heic, "jpg", tmp_path / "j")
    with Image.open(back) as im:
        assert im.size == (640, 480)


def test_ico_sizes(photo, tmp_path):
    out = convert(photo, "ico", tmp_path)
    with Image.open(out) as im:
        assert 256 in {s[0] for s in im.info["sizes"]}


def test_ffmpeg_made_jpeg_and_16bit_png(tmp_path):
    src = tmp_path / "gray16.png"
    subprocess.run([find_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "gradients=s=64x64:d=1",
                    "-frames:v", "1", "-pix_fmt", "gray16be", str(src)], check=True)
    out = convert(src, "jpg", tmp_path / "o")
    with Image.open(out) as im:
        assert im.size == (64, 64)


def test_cmyk_jpeg_to_png(tmp_path):
    src = tmp_path / "cmyk.jpg"
    Image.new("CMYK", (32, 32), (0, 255, 255, 0)).save(src)
    out = convert(src, "png", tmp_path / "o")
    with Image.open(out) as im:
        assert im.mode in ("RGB", "RGBA")


def test_palette_png_to_jpg(tmp_path):
    src = tmp_path / "pal.png"
    Image.new("P", (32, 32), 3).save(src)
    assert convert(src, "jpg", tmp_path / "o").exists()


def test_corrupt_and_missing(tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"\xff\xd8garbage")
    with pytest.raises(ConversionError):
        convert(bad, "png", tmp_path / "o")
    with pytest.raises(ConversionError):
        convert(tmp_path / "nope.png", "jpg")
    assert not list((tmp_path / "o").iterdir())


def test_no_overwrite(photo, tmp_path):
    convert(photo, "jpg", tmp_path)
    with pytest.raises(ConversionError):
        convert(photo, "jpg", tmp_path)
    convert(photo, "jpg", tmp_path, ImageOptions(overwrite=True))


def test_unicode_and_spaces_in_path(photo, tmp_path):
    d = tmp_path / "Bilder äöü 日本"
    d.mkdir()
    src = d / "Urlaubsfoto (1).png"
    src.write_bytes(photo.read_bytes())
    assert convert(src, "jpg").name == "Urlaubsfoto (1).jpg"


def test_batch(photo, tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"x")
    res = convert_batch(collect_inputs([tmp_path]), "webp", tmp_path / "o")
    assert sorted(r.ok for r in res) == [False, True]


# --- regressions found by hand-testing with awkward files -------------------------------

def test_apng_to_avif_float_durations(tmp_path):
    frames = [Image.new("RGBA", (64, 64), (i * 40, 0, 0, 255)) for i in range(4)]
    src = tmp_path / "anim.png"
    frames[0].save(src, save_all=True, append_images=frames[1:], duration=80, loop=0)
    out = convert(src, "avif", tmp_path / "o")
    with Image.open(out) as im:
        assert im.n_frames == 4


def test_svg_without_size(tmp_path):
    svg = tmp_path / "nosize.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><circle cx="50" cy="50" r="40"/></svg>')
    with Image.open(convert(svg, "png", tmp_path / "o")) as im:
        assert im.width > 0


def test_psd_16bit(tmp_path):
    pytest.importorskip("psd_tools")
    if not shutil.which("convert"):
        pytest.skip("ImageMagick needed to create a 16-bit PSD")
    src = tmp_path / "deep.psd"
    subprocess.run(["convert", "-size", "40x20", "gradient:red-blue", "-depth", "16", str(src)], check=True)
    with Image.open(convert(src, "png", tmp_path / "o")) as im:
        assert im.size == (40, 20)


def test_ico_is_square_even_for_wide_images(tmp_path):
    wide = tmp_path / "wide.png"
    Image.new("RGB", (300, 100), "red").save(wide)
    with Image.open(convert(wide, "ico", tmp_path / "o")) as ico:
        assert all(w == h for w, h in ico.info["sizes"])


def test_ico_from_tiny_image_is_readable(tmp_path):
    tiny = tmp_path / "tiny.png"
    Image.new("RGB", (10, 10), "red").save(tiny)
    with Image.open(convert(tiny, "ico", tmp_path / "o")) as ico:
        assert ico.info["sizes"]


def test_huge_image_error_is_understandable(tmp_path, monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
    big = tmp_path / "big.png"
    Image.new("RGB", (200, 200)).save(big)
    with pytest.raises(ConversionError, match="extremely large"):
        convert(big, "jpg", tmp_path / "o")
