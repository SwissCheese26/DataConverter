"""DataConverter main window (PySide6)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QProgressBar, QPushButton, QRadioButton, QSlider, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from .. import audio, image, video
from ..audio.ffmpeg import FFmpegNotFoundError, find_tool
from ..common import CancelToken
from . import jobs

TAB_TITLES = {"audio": "Audio", "image": "Bilder", "video": "Video"}
GREEN, RED, GREY = "#1a7f37", "#cf222e", "#6e7781"

STYLE = """
QPushButton#primary { background:#0b5cad; color:white; border:0; padding:7px 22px; border-radius:4px; font-weight:600; }
QPushButton#primary:hover { background:#0a4f95; }
QPushButton#primary:disabled { background:#9db7d3; }
QLabel#banner { background:#fff4ce; color:#533f03; padding:6px 10px; border-radius:4px; }
QLabel#hint { color:#6e7781; }
QTableWidget { gridline-color:#e4e7eb; }
"""


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def reveal(path: Path) -> None:
    """Show a file in Explorer (select it), or open its folder elsewhere."""
    if sys.platform == "win32" and path.exists():
        subprocess.Popen(["explorer", f"/select,{path}"])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


class Worker(QThread):
    progress = Signal(int, float)
    done = Signal(int, str, str, str)

    def __init__(self, settings: jobs.Settings, files: list[Path]):
        super().__init__()
        self.settings, self.files, self.token = settings, files, CancelToken()

    def run(self) -> None:
        jobs.run_all(self.settings, self.files, self.progress.emit, self.done.emit, self.token)

    def cancel(self) -> None:
        self.token.cancel()


def _combo(items, current=None) -> QComboBox:
    box = QComboBox()
    for label, data in items:
        box.addItem(label, data)
    if current is not None:
        box.setCurrentIndex(max(0, box.findData(current)))
    return box


def _slider(lo, hi, value) -> tuple[QSlider, QLabel, QWidget]:
    s = QSlider(Qt.Horizontal)
    s.setRange(lo, hi)
    s.setValue(value)
    lab = QLabel(str(value))
    lab.setMinimumWidth(28)
    s.valueChanged.connect(lambda v: lab.setText(str(v)))
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(s, 1)
    lay.addWidget(lab)
    return s, lab, row


class ConverterTab(QWidget):
    """One tab = one kind of file: file list on the left, settings on the right."""

    changed = Signal()

    def __init__(self, kind: str):
        super().__init__()
        self.kind = kind
        self.files: list[Path] = []
        self.targets: dict[int, Path] = {}

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Datei", "Größe", "Fortschritt", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Fixed)
        h.setSectionResizeMode(3, QHeaderView.Interactive)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(3, 320)
        self.table.cellDoubleClicked.connect(self._open_row)

        self.add_btn = QPushButton("Dateien hinzufügen …")
        self.folder_btn = QPushButton("Ordner hinzufügen …")
        self.remove_btn = QPushButton("Entfernen")
        self.clear_btn = QPushButton("Liste leeren")
        self.add_btn.clicked.connect(self.pick_files)
        self.folder_btn.clicked.connect(self.pick_folder)
        self.remove_btn.clicked.connect(self.remove_selected)
        self.clear_btn.clicked.connect(self.clear)
        buttons = QHBoxLayout()
        for b in (self.add_btn, self.folder_btn, self.remove_btn, self.clear_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)

        self.empty_hint = QLabel("Dateien oder Ordner hierher ziehen")
        self.empty_hint.setObjectName("hint")
        self.empty_hint.setAlignment(Qt.AlignCenter)

        left = QVBoxLayout()
        left.addLayout(buttons)
        left.addWidget(self.empty_hint)
        left.addWidget(self.table, 1)

        self.options_box = QGroupBox("Einstellungen")
        self.form = QFormLayout(self.options_box)
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        {"audio": self._build_audio, "image": self._build_image, "video": self._build_video}[kind]()
        self.hint = QLabel("")
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        self.form.addRow(self.hint)

        side = QVBoxLayout()
        side.addWidget(self.options_box)
        side.addStretch(1)
        side_w = QWidget()
        side_w.setLayout(side)
        side_w.setFixedWidth(310)

        root = QHBoxLayout(self)
        root.addLayout(left, 1)
        root.addWidget(side_w)
        self._refresh_enabled()
        self._update_empty()

    # ---------------------------------------------------------------- option panels
    def _build_audio(self) -> None:
        self.fmt = _combo([(n.upper(), n) for n in audio.FORMATS], "mp3")
        self.bitrate = _combo([("Automatisch", None)] + [(b, b) for b in ("96k", "128k", "160k", "192k", "256k", "320k")], "192k")
        self.channels = _combo([("Wie Original", None), ("Mono", 1), ("Stereo", 2)])
        self.rate = _combo([("Wie Original", None), ("44,1 kHz", 44100), ("48 kHz", 48000)])
        self.meta = QCheckBox("Titel, Künstler, Cover behalten")
        self.meta.setChecked(True)
        for label, w in (("Zielformat", self.fmt), ("Bitrate", self.bitrate), ("Kanäle", self.channels),
                         ("Samplerate", self.rate), ("", self.meta)):
            self.form.addRow(label, w)
        self.fmt.currentIndexChanged.connect(self._refresh_enabled)

    def _build_image(self) -> None:
        order = ["jpg", "png", "webp", "avif", "heic", "tiff", "bmp", "gif", "ico", "pdf", "jp2", "tga", "ppm"]
        self.fmt = _combo([(n.upper(), n) for n in order if n in image.FORMATS], "jpg")
        self.mode = _combo([("Komprimiert", "quality"), ("Verlustfrei", "lossless"), ("Zielgröße", "size")])
        self.q, _, qrow = _slider(1, 100, 85)
        self.mb = QDoubleSpinBox()
        self.mb.setRange(0.05, 500)
        self.mb.setValue(1.0)
        self.mb.setSuffix(" MB")
        self.mb.setSingleStep(0.5)
        self.edge = _combo([("Originalgröße", None)] + [(f"{v} px", v) for v in (3840, 2560, 1920, 1280, 800)])
        self.meta = QCheckBox("EXIF und Farbprofil behalten")
        self.meta.setChecked(True)
        for label, w in (("Zielformat", self.fmt), ("Art", self.mode), ("Qualität", qrow),
                         ("Höchstgröße", self.mb), ("Längste Seite", self.edge), ("", self.meta)):
            self.form.addRow(label, w)
        self.fmt.currentIndexChanged.connect(self._refresh_enabled)
        self.mode.currentIndexChanged.connect(self._refresh_enabled)

    def _build_video(self) -> None:
        order = ["mp4", "mkv", "mov", "webm", "avi", "wmv", "flv", "mpg", "m4v", "ts", "3gp", "gif"]
        items = [(n.upper(), n) for n in order] + [(k, k) for k in jobs.AUDIO_ONLY]
        self.fmt = _combo(items, "mp4")
        self.mode = _combo([("Komprimiert", "compress"), ("Verlustfrei", "lossless"),
                            ("Ohne Neukodierung (sehr schnell)", "copy"), ("Zielgröße", "size")])
        self.q, _, qrow = _slider(10, 100, 70)
        self.mb = QDoubleSpinBox()
        self.mb.setRange(0.5, 20000)
        self.mb.setValue(50)
        self.mb.setSuffix(" MB")
        self.height = _combo([("Originalgröße", None), ("4K (2160)", 2160), ("1440p", 1440),
                              ("Full HD (1080)", 1080), ("HD (720)", 720), ("480p", 480)])
        for label, w in (("Zielformat", self.fmt), ("Art", self.mode), ("Qualität", qrow),
                         ("Höchstgröße", self.mb), ("Auflösung", self.height)):
            self.form.addRow(label, w)
        self.fmt.currentIndexChanged.connect(self._refresh_enabled)
        self.mode.currentIndexChanged.connect(self._refresh_enabled)

    def _refresh_enabled(self) -> None:
        fmt, hint = self.fmt.currentData(), ""
        if self.kind == "audio":
            self.bitrate.setEnabled(audio.FORMATS[fmt].lossy)
            if not audio.FORMATS[fmt].lossy:
                hint = f"{fmt.upper()} ist verlustfrei, eine Bitrate gibt es hier nicht."
        elif self.kind == "image":
            mode = self.mode.currentData()
            lossy = image.FORMATS[fmt].lossy
            self.q.setEnabled(mode == "quality" and lossy)
            self.mb.setEnabled(mode == "size" and lossy)
            self.mode.setEnabled(lossy or True)
            if mode == "lossless" and fmt in ("jpg", "pdf"):
                hint = "JPG kann nicht ganz verlustfrei sein: es wird mit höchster Qualität gespeichert."
            elif mode == "lossless" and fmt == "avif":
                hint = "Verlustfreies AVIF behält keine Aufnahmedaten und keine Transparenz."
            elif mode == "lossless" and fmt == "heic":
                hint = "Verlustfreies HEIC öffnet sich evtl. nicht in allen Programmen."
            elif not lossy and mode != "lossless":
                hint = f"{fmt.upper()} ist ohnehin ohne Qualitätsverlust."
            self.meta.setEnabled(fmt in ("jpg", "png", "webp", "tiff", "avif", "heic"))
        else:
            audio_only = fmt in jobs.AUDIO_ONLY
            mode = self.mode.currentData()
            for w in (self.mode, self.height):
                w.setEnabled(not audio_only and fmt != "gif")
            self.q.setEnabled(not audio_only and fmt != "gif" and mode == "compress")
            self.mb.setEnabled(not audio_only and fmt != "gif" and mode == "size")
            self.height.setEnabled(not audio_only and fmt != "gif" and mode != "copy")
            if audio_only:
                hint = "Speichert nur die Tonspur des Videos."
            elif mode == "lossless":
                hint = "Verlustfrei erzeugt sehr große Dateien (nur MP4, MKV, MOV, M4V, TS, WebM, 3GP)."
            elif mode == "copy":
                hint = "Bild und Ton bleiben unverändert, nur der Container wechselt. Nicht jede Kombination ist möglich."
        self.hint.setText(hint)

    # ---------------------------------------------------------------- files
    def _update_empty(self) -> None:
        self.empty_hint.setVisible(not self.files)
        self.table.setVisible(bool(self.files))
        self.changed.emit()

    def add_paths(self, paths) -> int:
        have = set(self.files)
        new = [p for p in jobs.collect(self.kind, paths) if p not in have]
        for p in new:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.files.append(p)
            name = QTableWidgetItem(p.name)
            name.setToolTip(str(p))
            try:
                size = human_size(p.stat().st_size)
            except OSError:
                size = "?"
            sz = QTableWidgetItem(size)
            sz.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, sz)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(False)
            bar.setFixedHeight(10)
            self.table.setCellWidget(row, 2, bar)
            self.table.setItem(row, 3, QTableWidgetItem("Wartet"))
            self.table.item(row, 3).setForeground(Qt.gray)
        self._update_empty()
        return len(new)

    def pick_files(self) -> None:
        exts = " ".join(f"*{e}" for e in jobs.input_extensions(self.kind))
        paths, _ = QFileDialog.getOpenFileNames(self, "Dateien auswählen", "", f"{TAB_TITLES[self.kind]} ({exts});;Alle Dateien (*)")
        if paths:
            self.add_paths(paths)

    def pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Ordner auswählen")
        if folder:
            self.add_paths([folder])

    def remove_selected(self) -> None:
        for row in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)
            del self.files[row]
        self.targets.clear()
        self._update_empty()

    def clear(self) -> None:
        self.table.setRowCount(0)
        self.files.clear()
        self.targets.clear()
        self._update_empty()

    def reset_rows(self) -> None:
        self.targets.clear()
        for r in range(self.table.rowCount()):
            self.set_status(r, "Wartet", GREY)
            self.table.cellWidget(r, 2).setValue(0)

    def set_status(self, row: int, text: str, color: str, tip: str = "") -> None:
        item = self.table.item(row, 3)
        if item is None:
            return
        item.setText(text)
        item.setToolTip(tip or text)
        item.setForeground(Qt.GlobalColor.black)
        from PySide6.QtGui import QColor
        item.setForeground(QColor(color))

    def set_progress(self, row: int, frac: float) -> None:
        bar = self.table.cellWidget(row, 2)
        if bar is not None:
            bar.setValue(int(frac * 100))
            if self.table.item(row, 3).text() in ("Wartet", ""):
                self.set_status(row, "Läuft …", "#0b5cad")

    def _open_row(self, row: int, _col: int) -> None:
        target = self.targets.get(row)
        if target:
            reveal(target)

    def set_busy(self, busy: bool) -> None:
        for w in (self.options_box, self.add_btn, self.folder_btn, self.remove_btn, self.clear_btn):
            w.setEnabled(not busy)
        if not busy:
            self._refresh_enabled()

    # ---------------------------------------------------------------- settings
    def options(self) -> dict:
        """Backend options for the current controls."""
        if self.kind == "audio":
            return dict(bitrate=self.bitrate.currentData() if self.bitrate.isEnabled() else None,
                        sample_rate=self.rate.currentData(), channels=self.channels.currentData(),
                        copy_metadata=self.meta.isChecked())
        if self.kind == "image":
            mode, edge = self.mode.currentData(), self.edge.currentData()
            return dict(quality=self.q.value(), lossless=mode == "lossless",
                        max_bytes=int(self.mb.value() * 1_000_000) if mode == "size" else None,
                        max_width=edge, max_height=edge, keep_metadata=self.meta.isChecked())
        mode = self.mode.currentData()
        o = dict(crf=round(36 - self.q.value() * 0.18), height=self.height.currentData())
        if mode in ("lossless", "copy"):
            o["mode"] = mode
        if mode == "size":
            o["target_size_mb"] = self.mb.value()
        if mode == "copy":
            o["height"] = None
        return o


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DataConverter")
        self.resize(1040, 660)
        self.setAcceptDrops(True)
        self.worker: Worker | None = None
        self.running_tab: ConverterTab | None = None
        self.finished_count = 0

        self.tabs = QTabWidget()
        self.tab_by_kind = {k: ConverterTab(k) for k in jobs.KINDS}
        for k, tab in self.tab_by_kind.items():
            self.tabs.addTab(tab, TAB_TITLES[k])
            tab.changed.connect(self._update_buttons)
        self.tabs.currentChanged.connect(lambda _: self._update_buttons())

        self.banner = QLabel("ffmpeg wurde nicht gefunden: Audio und Video sind nicht verfügbar. "
                             "Lege ffmpeg.exe und ffprobe.exe neben DataConverter.exe.")
        self.banner.setObjectName("banner")
        self.banner.setWordWrap(True)
        try:
            find_tool("ffmpeg")
            find_tool("ffprobe")
            self.banner.hide()
        except FFmpegNotFoundError:
            pass

        # output
        self.out_same = QRadioButton("Neben dem Original speichern")
        self.out_folder = QRadioButton("In diesen Ordner:")
        self.out_same.setChecked(True)
        self.out_path = QLineEdit()
        self.out_path.setPlaceholderText("Zielordner wählen …")
        self.out_browse = QPushButton("Durchsuchen …")
        self.out_browse.clicked.connect(self._browse_output)
        self.out_path.textEdited.connect(lambda _: self.out_folder.setChecked(True))
        self.suffix = QLineEdit()
        self.suffix.setPlaceholderText("Namenszusatz (z. B. _klein)")
        self.suffix.setMinimumWidth(240)
        self.suffix.setMaximumWidth(240)
        self.overwrite = QCheckBox("Vorhandene Dateien überschreiben")
        out_row = QHBoxLayout()
        for w in (self.out_same, self.out_folder):
            out_row.addWidget(w)
        out_row.addWidget(self.out_path, 1)
        out_row.addWidget(self.out_browse)
        opt_row = QHBoxLayout()
        opt_row.addWidget(self.suffix)
        opt_row.addWidget(self.overwrite)
        opt_row.addStretch(1)
        out_box = QGroupBox("Speichern")
        out_lay = QVBoxLayout(out_box)
        out_lay.addLayout(out_row)
        out_lay.addLayout(opt_row)

        self.start_btn = QPushButton("Umwandeln")
        self.start_btn.setObjectName("primary")
        self.start_btn.setMinimumWidth(200)
        self.start_btn.clicked.connect(self.start)
        self.cancel_btn = QPushButton("Abbrechen")
        self.cancel_btn.clicked.connect(self.cancel)
        self.cancel_btn.setEnabled(False)
        self.open_btn = QPushButton("Zielordner öffnen")
        self.open_btn.clicked.connect(self._open_output)
        self.open_btn.setEnabled(False)
        self.overall = QProgressBar()
        self.overall.setRange(0, 100)
        self.overall.setTextVisible(False)
        self.overall.setFixedHeight(10)
        self.status = QLabel("Bereit. Dateien hinzufügen oder hierher ziehen.")
        bottom = QHBoxLayout()
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.open_btn)
        bottom.addWidget(self.cancel_btn)
        bottom.addWidget(self.start_btn)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.addWidget(self.banner)
        lay.addWidget(self.tabs, 1)
        lay.addWidget(out_box)
        lay.addWidget(self.overall)
        lay.addLayout(bottom)
        self.setCentralWidget(central)
        self._update_buttons()

    # ---------------------------------------------------------------- helpers
    @property
    def tab(self) -> ConverterTab:
        return self.tabs.currentWidget()

    def _update_buttons(self) -> None:
        busy = self.worker is not None
        self.start_btn.setEnabled(not busy and bool(self.tab.files))
        n = len(self.tab.files)
        self.start_btn.setText(f"{n} Datei{'en' if n != 1 else ''} umwandeln" if n and not busy else "Umwandeln")

    def _browse_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Zielordner wählen", self.out_path.text())
        if folder:
            self.out_path.setText(folder)
            self.out_folder.setChecked(True)

    def output_dir(self) -> Path | None:
        if self.out_folder.isChecked() and self.out_path.text().strip():
            return Path(self.out_path.text().strip())
        return None

    def _open_output(self) -> None:
        tab = self.running_tab or self.tab
        target = next(iter(tab.targets.values()), None)
        if target:
            reveal(target)

    # ---------------------------------------------------------------- drag & drop
    def add_files(self, paths) -> dict[str, int]:
        """Route files/folders to the right tab. Returns how many were added per kind."""
        added = {k: 0 for k in jobs.KINDS}
        skipped = 0
        for raw in paths:
            p = Path(raw)
            if p.is_dir():
                for k in jobs.KINDS:
                    added[k] += self.tab_by_kind[k].add_paths([p])
            elif jobs.kind_of(p):
                added[jobs.kind_of(p)] += self.tab_by_kind[jobs.kind_of(p)].add_paths([p])
            else:
                skipped += 1
        first = next((k for k in jobs.KINDS if added[k]), None)
        if first and self.worker is None:
            self.tabs.setCurrentWidget(self.tab_by_kind[first])
        total = sum(added.values())
        msg = f"{total} Datei{'en' if total != 1 else ''} hinzugefügt." if total else "Keine passenden Dateien gefunden."
        if skipped:
            msg += f" {skipped} nicht unterstützt."
        self.status.setText(msg)
        return added

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        self.add_files([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    # ---------------------------------------------------------------- run
    def start(self) -> None:
        tab = self.tab
        if not tab.files:
            self.status.setText("Bitte zuerst Dateien hinzufügen.")
            return
        out = self.output_dir()
        if self.out_folder.isChecked() and out is None:
            self.status.setText("Bitte einen Zielordner wählen oder „Neben dem Original“ nutzen.")
            return
        settings = jobs.Settings(tab.kind, tab.fmt.currentData(), out, self.suffix.text().strip(),
                                 self.overwrite.isChecked(), tab.options())
        tab.reset_rows()
        self.finished_count = 0
        self.failed = 0
        self.overall.setValue(0)
        self.running_tab = tab
        self.worker = Worker(settings, list(tab.files))
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_done)
        self.worker.finished.connect(self._on_finished)
        tab.set_busy(True)
        self.tabs.tabBar().setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.open_btn.setEnabled(False)
        self._update_buttons()
        self.status.setText("Läuft …")
        self.worker.start()

    def cancel(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.status.setText("Wird abgebrochen …")

    def _on_progress(self, row: int, frac: float) -> None:
        self.running_tab.set_progress(row, frac)

    def _on_done(self, row: int, state: str, msg: str, target: str) -> None:
        tab = self.running_tab
        self.finished_count += 1
        if state == "ok":
            tab.targets[row] = Path(target)
            tab.table.cellWidget(row, 2).setValue(100)
            tab.set_status(row, "Fertig ✓", GREEN, target)
        elif state == "cancelled":
            tab.set_status(row, "Abgebrochen", GREY)
        else:
            self.failed += 1
            tab.set_status(row, "Fehler: " + msg, RED, msg)
        total = len(self.worker.files)
        self.overall.setValue(int(self.finished_count * 100 / total))
        self.status.setText(f"{self.finished_count} von {total} bearbeitet …")

    def _on_finished(self) -> None:
        tab, total = self.running_tab, len(self.worker.files)
        ok = len(tab.targets)
        text = f"Fertig: {ok} von {total} umgewandelt"
        if self.failed:
            text += f", {self.failed} mit Fehler (Zeile anzeigen für Details)"
        if self.worker.token.cancelled:
            text = f"Abgebrochen: {ok} von {total} umgewandelt"
            self.overall.setValue(int(ok * 100 / total))
        self.status.setText(text + ".")
        self.worker = None
        tab.set_busy(False)
        self.tabs.tabBar().setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.open_btn.setEnabled(bool(tab.targets))
        self._update_buttons()

    def closeEvent(self, e) -> None:
        if self.worker:
            self.worker.cancel()
            self.worker.wait(5000)
        e.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    win = MainWindow()
    win.show()
    if "--selftest" in sys.argv:  # used by the build to check that the packaged app starts
        app.processEvents()
        msg = "DataConverter GUI OK; ffmpeg " + ("missing" if win.banner.isVisible() else "found")
        i = sys.argv.index("--selftest")
        if len(sys.argv) > i + 1:  # a windowed .exe has no console: report through a file
            Path(sys.argv[i + 1]).write_text(msg, encoding="utf-8")
        elif sys.stdout:
            print(msg)
        return 1 if win.banner.isVisible() else 0
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
