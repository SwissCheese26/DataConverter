"""Video tests build real clips with ffmpeg, convert them, and probe the real output."""

import subprocess
import threading
import time

import pytest

from dataconverter.audio.ffmpeg import find_tool
from dataconverter.common import Cancelled, CancelToken, ConversionError
from dataconverter.ffrun import probe
from dataconverter.video import VideoOptions, collect_inputs, convert, convert_batch, extract_audio


def _make(path, args):
    subprocess.run([find_tool("ffmpeg"), "-v", "error", "-y", *args, str(path)], check=True)
    return path


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    """3 s test clip, 320x240, 25 fps, with a 440 Hz tone."""
    return _make(tmp_path_factory.mktemp("src") / "clip.mp4", [
        "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"])


def _streams(path):
    s = probe(path)["streams"]
    return ({x["codec_type"]: x for x in s}), float(probe(path)["format"]["duration"])


@pytest.mark.parametrize("fmt", ["mkv", "mov", "m4v", "ts", "webm", "avi", "wmv", "flv", "mpg", "3gp"])
def test_all_containers(clip, tmp_path, fmt):
    out = convert(clip, fmt, tmp_path)
    st, dur = _streams(out)
    assert "video" in st and "audio" in st
    assert 2.5 < dur < 3.6


def test_mp4_from_other_container(clip, tmp_path):
    mkv = convert(clip, "mkv", tmp_path / "a")
    out = convert(mkv, "mp4", tmp_path / "b")
    st, _ = _streams(out)
    assert st["video"]["codec_name"] == "h264" and st["audio"]["codec_name"] == "aac"


def test_scale_keeps_aspect_and_never_upscales(clip, tmp_path):
    out = convert(clip, "mp4", tmp_path / "s", VideoOptions(height=120))
    v = _streams(out)[0]["video"]
    assert (v["width"], v["height"]) == (160, 120)
    out = convert(clip, "mp4", tmp_path / "u", VideoOptions(height=1080))
    v = _streams(out)[0]["video"]
    assert (v["width"], v["height"]) == (320, 240)


def test_odd_aspect_scales_to_even_width(tmp_path):
    odd = _make(tmp_path / "odd.mp4", ["-f", "lavfi", "-i", "testsrc=size=322x242:rate=25:duration=1",
                                       "-c:v", "libx264", "-pix_fmt", "yuv420p"])
    out = convert(odd, "mp4", tmp_path / "o", VideoOptions(height=101))
    v = _streams(out)[0]["video"]
    assert v["width"] % 2 == 0 and v["height"] % 2 == 0


def test_fps_and_crf(clip, tmp_path):
    lo = convert(clip, "mp4", tmp_path / "lo", VideoOptions(crf=40, fps=10))
    hi = convert(clip, "mp4", tmp_path / "hi", VideoOptions(crf=15))
    assert lo.stat().st_size < hi.stat().st_size
    assert _streams(lo)[0]["video"]["r_frame_rate"] == "10/1"


def test_gif(clip, tmp_path):
    out = convert(clip, "gif", tmp_path, VideoOptions(gif_width=160, gif_fps=8))
    v = _streams(out)[0]["video"]
    assert v["codec_name"] == "gif" and v["width"] == 160


def test_video_without_audio(tmp_path):
    silent = _make(tmp_path / "silent.mp4", ["-f", "lavfi", "-i", "testsrc=size=160x120:duration=1",
                                             "-c:v", "libx264", "-pix_fmt", "yuv420p"])
    for fmt in ("mkv", "avi", "webm", "wmv", "flv", "mpg"):
        st, _ = _streams(convert(silent, fmt, tmp_path / fmt))
        assert "video" in st


def test_extract_audio(clip, tmp_path):
    out = extract_audio(clip, "mp3", tmp_path)
    st, dur = _streams(out)
    assert out.suffix == ".mp3" and "video" not in st and 2.5 < dur < 3.6


def test_extract_audio_from_silent_video_has_clear_error(tmp_path):
    silent = _make(tmp_path / "silent.mp4", ["-f", "lavfi", "-i", "testsrc=size=160x120:duration=1",
                                             "-c:v", "libx264", "-pix_fmt", "yuv420p"])
    with pytest.raises(ConversionError, match="no audio"):
        extract_audio(silent, "mp3", tmp_path)


def test_audio_file_is_not_a_video(tmp_path):
    wav = _make(tmp_path / "a.wav", ["-f", "lavfi", "-i", "sine=duration=1"])
    with pytest.raises(ConversionError, match="no video"):
        convert(wav, "mp4", tmp_path / "o")


def test_progress_reaches_one(clip, tmp_path):
    seen = []
    convert(clip, "mkv", tmp_path, progress=seen.append)
    assert seen[-1] == 1.0 and seen == sorted(seen)


def test_cancel_midway_leaves_no_files(tmp_path):
    long = _make(tmp_path / "long.mp4", ["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=60",
                                         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"])
    tok = CancelToken()
    threading.Timer(0.5, tok.cancel).start()
    t0 = time.time()
    with pytest.raises(Cancelled):
        convert(long, "mkv", tmp_path / "o", VideoOptions(preset="veryslow"), cancel=tok,
                progress=lambda f: None)
    assert time.time() - t0 < 15
    assert not list((tmp_path / "o").iterdir())


def test_corrupt_input(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"junk" * 100)
    with pytest.raises(ConversionError):
        convert(bad, "mkv", tmp_path / "o")
    assert not (tmp_path / "o").exists() or not list((tmp_path / "o").iterdir())


def test_unicode_and_spaces(clip, tmp_path):
    d = tmp_path / "Videos äöü 日本 & co"
    d.mkdir()
    src = d / "Urlaub 2024 (final).mp4"
    src.write_bytes(clip.read_bytes())
    assert convert(src, "mkv").name == "Urlaub 2024 (final).mkv"


def test_no_overwrite(clip, tmp_path):
    convert(clip, "mkv", tmp_path)
    with pytest.raises(ConversionError):
        convert(clip, "mkv", tmp_path)
    convert(clip, "mkv", tmp_path, VideoOptions(overwrite=True))


def test_batch(clip, tmp_path):
    (tmp_path / "bad.mp4").write_bytes(b"x")
    d = tmp_path / "in"
    d.mkdir()
    (d / "a.mp4").write_bytes(clip.read_bytes())
    (d / "bad.mp4").write_bytes(b"x")
    res = convert_batch(collect_inputs([d]), "mkv", tmp_path / "o", workers=2)
    assert sorted(r.ok for r in res) == [False, True]


# --- regressions found by hand-testing with awkward files -------------------------------

def test_rgb_source_becomes_browser_playable_yuv420p(tmp_path):
    rgb = _make(tmp_path / "rgb.webm", ["-f", "lavfi", "-i", "testsrc=size=160x120:duration=1",
                                        "-c:v", "libvpx-vp9", "-pix_fmt", "gbrp"])
    for fmt in ("webm", "mkv", "mp4"):
        v = _streams(convert(rgb, fmt, tmp_path / fmt))[0]["video"]
        assert v["pix_fmt"] == "yuv420p"


def test_ten_bit_source_is_converted_to_8_bit(tmp_path):
    ten = _make(tmp_path / "ten.mp4", ["-f", "lavfi", "-i", "testsrc=size=160x120:duration=1",
                                       "-c:v", "libx264", "-pix_fmt", "yuv420p10le"])
    assert _streams(convert(ten, "mp4", tmp_path / "o"))[0]["video"]["pix_fmt"] == "yuv420p"


def test_phone_rotation_is_applied(tmp_path):
    plain = _make(tmp_path / "plain.mp4", ["-f", "lavfi", "-i", "testsrc=size=640x360:duration=1",
                                           "-c:v", "libx264", "-pix_fmt", "yuv420p"])
    rot = tmp_path / "rot.mp4"
    subprocess.run([find_tool("ffmpeg"), "-v", "error", "-display_rotation", "90", "-i", str(plain),
                    "-c", "copy", str(rot)], check=True)
    v = _streams(convert(rot, "mkv", tmp_path / "o"))[0]["video"]
    assert (v["width"], v["height"]) == (360, 640)


def test_odd_target_height(tmp_path):
    src = _make(tmp_path / "s.mp4", ["-f", "lavfi", "-i", "testsrc=size=640x360:duration=1",
                                     "-c:v", "libx264", "-pix_fmt", "yuv420p"])
    v = _streams(convert(src, "mp4", tmp_path / "o", VideoOptions(height=101)))[0]["video"]
    assert v["height"] % 2 == 0 and v["width"] % 2 == 0
