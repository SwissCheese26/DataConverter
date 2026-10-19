"""GUI tests: the job layer without Qt, and the real window running offscreen with real files."""

import os
import subprocess
import time
from pathlib import Path

import pytest
from PIL import Image

from dataconverter.audio.ffmpeg import find_tool
from dataconverter.common import CancelToken
from dataconverter.gui import jobs

SHOTS = os.environ.get("DATACONVERTER_SHOTS")  # directory: save window screenshots there


def _ff(*args):
    subprocess.run([find_tool("ffmpeg"), "-v", "error", "-y", *map(str, args)], check=True)


@pytest.fixture
def media(tmp_path):
    d = tmp_path / "in"
    d.mkdir()
    Image.new("RGB", (800, 600), (200, 80, 40)).save(d / "foto.png")
    Image.new("RGB", (400, 300), "navy").save(d / "bild.jpg")
    (d / "kaputt.png").write_bytes(b"not an image")
    _ff("-f", "lavfi", "-i", "sine=frequency=440:duration=2", d / "ton.wav")
    _ff("-f", "lavfi", "-i", "testsrc=size=640x360:rate=25:duration=2", "-f", "lavfi", "-i", "sine=duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", d / "film.mp4")
    (d / "notizen.txt").write_text("hi")
    return d


# ----------------------------------------------------------------------------- job layer (no Qt)

def test_kind_of():
    assert [jobs.kind_of(x) for x in ("a.HEIC", "a.mkv", "a.flac", "a.gif", "a.txt")] == \
        ["image", "video", "audio", "image", None]


def test_same_format_in_same_folder_gets_automatic_suffix(media):
    s = jobs.Settings("image", "jpg", options=dict(quality=50))
    out = jobs.convert_one(s, media / "bild.jpg")
    assert out.name == "bild_konvertiert.jpg" and (media / "bild.jpg").exists()


def test_error_messages_are_german():
    assert "überschreiben" in jobs.friendly("Output already exists: x")
    assert "Tonspur" in jobs.friendly("clip.mp4 has no audio track.")
    assert jobs.friendly("something odd") == "something odd"


def test_run_all_reports_every_file_and_survives_errors(media):
    files = [media / "foto.png", media / "kaputt.png", media / "bild.jpg"]
    done = {}
    s = jobs.Settings("image", "webp", media / "out", options=dict(quality=80))
    jobs.run_all(s, files, lambda i, f: None, lambda i, st, m, t: done.__setitem__(i, (st, m)), CancelToken())
    assert [done[i][0] for i in range(3)] == ["ok", "error", "ok"]
    assert "Bilddatei" in done[1][1]


def test_run_all_cancelled_before_start(media):
    tok = CancelToken()
    tok.cancel()
    done = {}
    jobs.run_all(jobs.Settings("audio", "mp3", media / "o"), [media / "ton.wav"], lambda *a: None,
                 lambda i, st, m, t: done.__setitem__(i, st), tok)
    assert done == {0: "cancelled"}


def test_video_audio_only_option(media):
    s = jobs.Settings("video", "Nur Ton (MP3)", media / "o")
    out = jobs.convert_one(s, media / "film.mp4")
    assert out.suffix == ".mp3"


# ----------------------------------------------------------------------------- the window

qt = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    a = QApplication.instance() or QApplication([])
    a.setStyle("Fusion")
    from dataconverter.gui.app import STYLE
    a.setStyleSheet(STYLE)
    return a


@pytest.fixture
def win(app):
    from dataconverter.gui.app import MainWindow
    w = MainWindow()
    w.show()
    yield w
    w.close()


def _wait(app, cond, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


def _shot(win, name):
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        win.grab().save(str(Path(SHOTS) / f"{name}.png"))


def test_drop_routes_files_to_the_right_tab(win, media):
    added = win.add_files([media / "foto.png", media / "ton.wav", media / "film.mp4", media / "notizen.txt"])
    assert added == {"audio": 1, "image": 1, "video": 1}
    assert "nicht unterstützt" in win.status.text()
    assert win.tabs.currentWidget() is win.tab_by_kind["audio"]


def test_dropping_a_folder_sorts_everything(win, media):
    added = win.add_files([media])
    assert added["image"] == 3 and added["audio"] == 1 and added["video"] == 1  # kaputt.png counts as image


def test_adding_same_file_twice_does_not_duplicate(win, media):
    win.add_files([media / "foto.png"])
    win.add_files([media / "foto.png"])
    assert len(win.tab_by_kind["image"].files) == 1


def test_convert_images_end_to_end(app, win, media):
    win.add_files([media / "foto.png", media / "bild.jpg", media / "kaputt.png"])
    tab = win.tab
    assert tab.kind == "image"
    _shot(win, "1_images_added")
    tab.fmt.setCurrentIndex(tab.fmt.findData("webp"))
    win.out_folder.setChecked(True)
    win.out_path.setText(str(media / "out"))
    win.start_btn.click()
    assert win.cancel_btn.isEnabled() and not win.start_btn.isEnabled()
    _wait(app, lambda: win.worker is None)
    texts = [tab.table.item(r, 3).text() for r in range(3)]
    assert texts[0] == "Fertig ✓" and texts[1] == "Fertig ✓" and texts[2].startswith("Fehler:")
    assert "Bilddatei" in texts[2]
    assert (media / "out" / "foto.webp").exists() and (media / "out" / "bild.webp").exists()
    assert win.open_btn.isEnabled() and "2 von 3" in win.status.text()
    assert win.overall.value() == 100
    _shot(win, "2_images_done")


def test_image_modes_reach_the_backend(win, media):
    win.add_files([media / "foto.png"])
    t = win.tab
    t.mode.setCurrentIndex(t.mode.findData("lossless"))
    assert t.options()["lossless"] is True
    t.mode.setCurrentIndex(t.mode.findData("size"))
    t.mb.setValue(0.25)
    assert t.options()["max_bytes"] == 250_000
    t.edge.setCurrentIndex(t.edge.findData(1280))
    assert (t.options()["max_width"], t.options()["max_height"]) == (1280, 1280)


def test_controls_follow_the_selected_format(win):
    img = win.tab_by_kind["image"]
    img.fmt.setCurrentIndex(img.fmt.findData("png"))
    assert not img.q.isEnabled()  # PNG has no quality
    img.fmt.setCurrentIndex(img.fmt.findData("jpg"))
    assert img.q.isEnabled()
    aud = win.tab_by_kind["audio"]
    aud.fmt.setCurrentIndex(aud.fmt.findData("flac"))
    assert not aud.bitrate.isEnabled() and "verlustfrei" in aud.hint.text()
    vid = win.tab_by_kind["video"]
    vid.mode.setCurrentIndex(vid.mode.findData("copy"))
    assert not vid.height.isEnabled() and vid.options()["mode"] == "copy" and vid.options()["height"] is None
    vid.fmt.setCurrentIndex(vid.fmt.findData("gif"))
    assert not vid.mode.isEnabled()


def test_convert_audio_and_video_end_to_end(app, win, media):
    win.add_files([media / "ton.wav", media / "film.mp4"])
    aud = win.tab_by_kind["audio"]
    win.tabs.setCurrentWidget(aud)
    aud.fmt.setCurrentIndex(aud.fmt.findData("mp3"))
    win.start_btn.click()
    _wait(app, lambda: win.worker is None)
    assert aud.table.item(0, 3).text() == "Fertig ✓" and (media / "ton.mp3").exists()

    vid = win.tab_by_kind["video"]
    win.tabs.setCurrentWidget(vid)
    vid.fmt.setCurrentIndex(vid.fmt.findData("mkv"))
    vid.height.setCurrentIndex(vid.height.findData(480))
    vid.height.addItem("240p", 240)
    vid.height.setCurrentIndex(vid.height.findData(240))
    win.start_btn.click()
    _wait(app, lambda: win.worker is None, timeout=90)
    assert vid.table.item(0, 3).text() == "Fertig ✓"
    out = media / "film.mkv"
    info = subprocess.run([find_tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=height", "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout
    assert info.strip() == "240"
    _shot(win, "3_video_done")


def test_same_format_same_folder_does_not_destroy_original(app, win, media):
    before = (media / "bild.jpg").read_bytes()
    win.add_files([media / "bild.jpg"])
    win.start_btn.click()
    _wait(app, lambda: win.worker is None)
    assert (media / "bild.jpg").read_bytes() == before
    assert (media / "bild_konvertiert.jpg").exists()


def test_existing_target_shows_helpful_error_then_overwrite_works(app, win, media):
    win.add_files([media / "foto.png"])
    win.tab.fmt.setCurrentIndex(win.tab.fmt.findData("jpg"))
    win.start_btn.click(); _wait(app, lambda: win.worker is None)
    win.start_btn.click(); _wait(app, lambda: win.worker is None)
    assert "überschreiben" in win.tab.table.item(0, 3).text()
    win.overwrite.setChecked(True)
    win.start_btn.click(); _wait(app, lambda: win.worker is None)
    assert win.tab.table.item(0, 3).text() == "Fertig ✓"


def test_cancel_stops_a_running_video(app, win, media):
    big = media / "gross.mp4"
    _ff("-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=40", "-c:v", "libx264",
        "-preset", "ultrafast", "-pix_fmt", "yuv420p", big)
    win.add_files([big])
    vid = win.tab
    vid.fmt.setCurrentIndex(vid.fmt.findData("mkv"))
    win.start_btn.click()
    t0 = time.time()
    _wait(app, lambda: vid.table.cellWidget(0, 2).value() > 0 or time.time() - t0 > 20)
    win.cancel_btn.click()
    _wait(app, lambda: win.worker is None, timeout=30)
    assert vid.table.item(0, 3).text() == "Abgebrochen" and not (media / "gross.mkv").exists()
    assert "Abgebrochen" in win.status.text()
    _shot(win, "4_cancelled")


def test_start_without_files_or_folder_gives_hint(win):
    win.start()
    assert "Dateien" in win.status.text()
    win.add_files([])
    win.out_folder.setChecked(True)
    win.tab_by_kind["audio"].files.append(Path("x.mp3"))
    win.start()
    assert "Zielordner" in win.status.text()


def test_remove_and_clear(win, media):
    win.add_files([media / "foto.png", media / "bild.jpg"])
    t = win.tab
    t.table.selectRow(0)
    t.remove_selected()
    assert len(t.files) == 1 and t.table.rowCount() == 1
    t.clear()
    assert not t.files and not t.table.isVisible()
