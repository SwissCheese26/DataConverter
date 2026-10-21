"""Things that tend to break on Windows: odd paths, locked files, orphaned processes, tool lookup.

Most run everywhere (so they also guard Linux); the ones that only make sense on Windows are skipped elsewhere.
"""

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

from dataconverter import audio, image, video
from dataconverter.audio.ffmpeg import find_tool, popen_flags
from dataconverter.common import Cancelled, CancelToken, ConversionError

WINDOWS = sys.platform == "win32"
only_windows = pytest.mark.skipif(not WINDOWS, reason="Windows behaviour")


def _ff(*args):
    subprocess.run([find_tool("ffmpeg"), "-v", "error", "-y", *map(str, args)], check=True)


def _make(folder: Path, stem: str = "x"):
    folder.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), "teal").save(folder / f"{stem}.png")
    _ff("-f", "lavfi", "-i", "sine=duration=1", folder / f"{stem}.wav")
    _ff("-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=1", "-pix_fmt", "yuv420p", folder / f"{stem}.mp4")
    return folder


# ----------------------------------------------------------------------------- awkward paths

NAMES = ["Männer Ärger (1)", "日本語 フォルダ", "émoji 🎵 & co", "with'quote and, comma;semi", "ends with space ok"]


@pytest.mark.parametrize("folder", NAMES)
def test_special_characters_in_folder_and_file_names(tmp_path, folder):
    d = _make(tmp_path / folder, "Büro Foto – final (2)")
    out = tmp_path / "Ausgabe ÄÖÜ"
    assert image.convert(d / "Büro Foto – final (2).png", "webp", out).exists()
    assert audio.convert(d / "Büro Foto – final (2).wav", "mp3", out).exists()
    assert video.convert(d / "Büro Foto – final (2).mp4", "mkv", out).exists()
    assert {p.name for p in out.iterdir()} == {"Büro Foto – final (2).webp", "Büro Foto – final (2).mp3",
                                              "Büro Foto – final (2).mkv"}


def test_heic_and_avif_with_umlaut_paths(tmp_path):
    d = _make(tmp_path / "Bilder Ünï", "Größe")
    for fmt in ("heic", "avif"):
        assert image.convert(d / "Größe.png", fmt, tmp_path / "o").exists()
    assert image.convert(d / "Größe.png", "avif", tmp_path / "ll", image.ImageOptions(lossless=True)).exists()


def test_error_text_with_umlauts_is_not_garbled(tmp_path):
    bad = tmp_path / "Käse Ärger.mp3"
    bad.write_bytes(b"not audio at all")
    with pytest.raises(ConversionError) as e:
        audio.convert(bad, "wav", tmp_path / "o")
    assert "Käse Ärger" in str(e.value) and "�" not in str(e.value)


@only_windows
def test_path_longer_than_260_characters(tmp_path):
    deep = tmp_path
    for i in range(7):
        deep = deep / f"verzeichnis_mit_langem_namen_{i}_{'x' * 30}"
    assert len(str(deep)) > 260
    d = _make(deep)
    assert image.convert(d / "x.png", "jpg").exists()
    assert audio.convert(d / "x.wav", "mp3").exists()
    assert video.convert(d / "x.mp4", "mkv").exists()


@only_windows
def test_upper_and_lower_case_extension_is_the_same_file(tmp_path):
    src = tmp_path / "Foto.PNG"
    Image.new("RGB", (8, 8)).save(src, format="PNG")
    with pytest.raises(ConversionError, match="overwrite the input"):
        image.convert(src, "png")


# ----------------------------------------------------------------------------- locked / unwritable targets

def _deny_replace(monkeypatch):
    real = Path.replace

    def fake(self, target):
        if ".partial" in self.name:
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", fake)


@pytest.mark.parametrize("kind", ["audio", "image", "video"])
def test_locked_target_gives_readable_error_and_no_leftovers(tmp_path, monkeypatch, kind):
    d = _make(tmp_path / "in")
    _deny_replace(monkeypatch)
    out = tmp_path / "out"
    call = {"audio": lambda: audio.convert(d / "x.wav", "mp3", out),
            "image": lambda: image.convert(d / "x.png", "webp", out),
            "video": lambda: video.convert(d / "x.mp4", "mkv", out)}[kind]
    with pytest.raises(ConversionError, match="Cannot write"):
        call()
    assert not list(out.glob("*"))


def test_batches_survive_a_locked_target(tmp_path, monkeypatch):
    d = _make(tmp_path / "in")
    _deny_replace(monkeypatch)
    for res in (audio.convert_batch([d / "x.wav"], "mp3", tmp_path / "a"),
                image.convert_batch([d / "x.png"], "webp", tmp_path / "b"),
                video.convert_batch([d / "x.mp4"], "mkv", tmp_path / "c")):
        assert [r.ok for r in res] == [False] and "Cannot write" in res[0].error


@only_windows
def test_really_open_target_file_is_reported_not_crashing(tmp_path):
    d = _make(tmp_path / "in")
    out = tmp_path / "out"
    first = image.convert(d / "x.png", "jpg", out)
    with open(first, "rb"):  # another program has the old result open
        with pytest.raises(ConversionError, match="Cannot write"):
            image.convert(d / "x.png", "jpg", out, image.ImageOptions(overwrite=True))
    assert first.exists() and not list(out.glob("*.partial*"))
    image.convert(d / "x.png", "jpg", out, image.ImageOptions(overwrite=True))  # works once closed


def test_source_file_open_elsewhere_can_still_be_converted(tmp_path):
    d = _make(tmp_path / "in")
    with open(d / "x.wav", "rb"), open(d / "x.png", "rb"), open(d / "x.mp4", "rb"):
        assert audio.convert(d / "x.wav", "mp3", tmp_path / "o").exists()
        assert image.convert(d / "x.png", "jpg", tmp_path / "o").exists()
        assert video.convert(d / "x.mp4", "mkv", tmp_path / "o").exists()


# ----------------------------------------------------------------------------- processes

def _ffmpeg_processes() -> int:
    if WINDOWS:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ffmpeg.exe", "/NH"], capture_output=True, text=True).stdout
        return out.lower().count("ffmpeg.exe")
    out = subprocess.run(["pgrep", "-xc", "ffmpeg"], capture_output=True, text=True).stdout.strip()
    return int(out or 0)


def test_cancel_leaves_no_ffmpeg_process_behind(tmp_path):
    big = tmp_path / "big.mp4"
    _ff("-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=60", "-c:v", "libx264",
        "-preset", "ultrafast", "-pix_fmt", "yuv420p", big)
    assert _ffmpeg_processes() == 0
    tok = CancelToken()
    seen = []

    def progress(f):
        seen.append(f)
        if len(seen) == 1:
            tok.cancel()

    with pytest.raises(Cancelled):
        video.convert(big, "mkv", tmp_path / "o", video.VideoOptions(preset="veryslow"), progress, tok)
    deadline = time.time() + 10
    while _ffmpeg_processes() and time.time() < deadline:
        time.sleep(0.25)
    assert _ffmpeg_processes() == 0, "ffmpeg is still running after cancel"
    assert not list((tmp_path / "o").glob("*"))


def test_converting_from_a_thread_while_cancelling_does_not_hang(tmp_path):
    d = _make(tmp_path / "in")
    tok = CancelToken()
    results = []
    t = threading.Thread(target=lambda: results.append(
        video.convert_batch([d / "x.mp4"] * 1, "mkv", tmp_path / "o", cancel=tok)))
    t.start()
    tok.cancel()
    t.join(30)
    assert not t.is_alive()


# ----------------------------------------------------------------------------- ffmpeg lookup / console

def test_ffmpeg_is_found_next_to_the_app(tmp_path, monkeypatch):
    exe = ".exe" if os.name == "nt" else ""
    for tool in ("ffmpeg", "ffprobe"):
        shutil.copy(find_tool(tool), tmp_path / (tool + exe))
    monkeypatch.setenv("DATACONVERTER_FFMPEG_DIR", str(tmp_path))
    assert Path(find_tool("ffmpeg")).parent == tmp_path
    assert Path(find_tool("ffprobe")).parent == tmp_path
    d = _make(tmp_path / "in")
    assert audio.convert(d / "x.wav", "mp3", tmp_path / "o").exists()


def test_missing_ffmpeg_gives_clear_message(tmp_path, monkeypatch):
    monkeypatch.setenv("DATACONVERTER_FFMPEG_DIR", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path))
    import dataconverter.audio.ffmpeg as ff
    monkeypatch.setattr(ff, "_candidate_dirs", lambda: [])
    with pytest.raises(ff.FFmpegNotFoundError, match="not found"):
        ff.find_tool("ffmpeg")


@only_windows
def test_no_console_window_flag_is_set():
    assert popen_flags()["creationflags"] == subprocess.CREATE_NO_WINDOW
