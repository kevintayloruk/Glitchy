#!/usr/bin/env python3
"""
Glitchy -- desktop app for detecting glitches in test-tone recordings,
in bulk (Recorded) or live (Live Monitor via sound card or SDP/network feed).
"""
import csv
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal, QSize
from PySide6.QtGui import QDesktopServices, QIcon, QPainter, QPainterPath, QPen, QColor, QFont, QCloseEvent, QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QStackedWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QListWidget, QListWidgetItem, QFileDialog,
    QLineEdit, QCheckBox, QSpinBox, QDoubleSpinBox, QComboBox, QRadioButton,
    QButtonGroup, QProgressBar, QPlainTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QTextEdit, QFrame, QSizePolicy, QAbstractItemView,
    QScrollArea, QDialog, QTextBrowser,
)

import glitchy_core as gc
import glitchy_capture as cap

APP_NAME = "Glitchy"
APP_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

COLORS = {
    "bg": "#15171a", "panel": "#1a1d21", "panel_alt": "#1c1f23", "border": "#2c3036",
    "border_soft": "#22262b", "text": "#e8eaed", "text_dim": "#c7ccd1", "text_faint": "#9aa1a9",
    "text_ghost": "#6b7280", "accent": "#e8934a", "accent_text": "#15171a",
    "success": "#5fb87a", "warning": "#e0b64f", "danger": "#e2645c", "info": "#6bb8d6",
    "purple": "#b58ce0",
}

QSS = f"""
QWidget {{ background: {COLORS['bg']}; color: {COLORS['text']}; font-size: 13px; }}
QLabel {{ background: transparent; }}
QMainWindow {{ background: {COLORS['bg']}; }}
QLabel[role="h2"] {{ font-size: 18px; font-weight: 600; }}
QLabel[role="h3"] {{ font-size: 15px; font-weight: 600; }}
QLabel[role="sub"] {{ color: {COLORS['text_faint']}; font-size: 12px; }}
QLabel[role="mono"] {{ font-family: Menlo, Consolas, monospace; }}
QFrame[role="panel"] {{ background: {COLORS['panel']}; border: 1px solid {COLORS['border']}; border-radius: 10px; }}
QFrame[role="row"] {{ background: {COLORS['panel_alt']}; border: 1px solid {COLORS['border']}; border-radius: 8px; }}
QPushButton {{ background: {COLORS['panel_alt']}; border: 1px solid {COLORS['border']}; border-radius: 6px;
               padding: 7px 14px; color: {COLORS['text_dim']}; }}
QPushButton:hover {{ border-color: {COLORS['accent']}; }}
QPushButton[role="primary"] {{ background: {COLORS['accent']}; color: {COLORS['accent_text']};
                                font-weight: 600; border: none; }}
QPushButton[role="danger"] {{ background: transparent; color: {COLORS['danger']}; border: 1px solid #4a2b28; }}
QPushButton[role="icon"] {{ padding: 0px; }}
QRadioButton {{ background: transparent; }}
QCheckBox {{ background: transparent; }}
QPushButton[role="tab_active"] {{ background: {COLORS['accent']}; color: {COLORS['accent_text']};
                                   font-weight: 600; border: none; }}
QPushButton[role="tab"] {{ background: transparent; color: {COLORS['text_faint']}; border: none; }}
QPushButton[role="source_active"] {{ background: {COLORS['accent']}; color: {COLORS['accent_text']};
                                      font-weight: 600; border: none; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: #0f1113; border: 1px solid {COLORS['border']}; border-radius: 6px;
    padding: 6px 8px; color: {COLORS['text']};
}}
QListWidget {{ background: transparent; border: none; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {COLORS['border']}; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {COLORS['text_ghost']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ height: 0; }}
QProgressBar {{ background: #0f1113; border: none; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {COLORS['accent']}; border-radius: 4px; }}
QTableWidget {{ background: {COLORS['panel']}; border: 1px solid {COLORS['border']}; border-radius: 10px;
                gridline-color: {COLORS['border_soft']}; }}
QHeaderView::section {{ background: {COLORS['panel_alt']}; color: {COLORS['text_ghost']}; border: none;
                         padding: 8px; font-size: 11px; text-transform: uppercase; }}
"""


def h2(text):
    l = QLabel(text); l.setProperty("role", "h2"); return l


def h3(text):
    l = QLabel(text); l.setProperty("role", "h3"); return l


def sub(text):
    l = QLabel(text); l.setProperty("role", "sub"); l.setWordWrap(True); return l


def panel():
    f = QFrame(); f.setProperty("role", "panel"); return f


def format_duration(seconds):
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


# ---------------------------------------------------------------------------
# About page waveform diagrams
# ---------------------------------------------------------------------------

class WaveformDiagram(QWidget):
    """Small illustrative waveform: clean sine in gray, with the anomalous
    region for `kind` drawn in its accent color on top."""

    def __init__(self, kind, color):
        super().__init__()
        self.kind = kind
        self.color = QColor(color)
        self.setMinimumHeight(70)
        self.setStyleSheet(f"background: #0f1113; border: 1px solid {COLORS['border']}; border-radius: 8px;")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        mid = h / 2
        amp = h * 0.32

        def sine_path(x0, x1, phase_start_deg=0, amplitude=amp):
            import math
            path = QPainterPath()
            n = max(2, int(x1 - x0))
            for i in range(n + 1):
                x = x0 + i
                frac = (x - x0) / max(1, (x1 - x0))
                deg = phase_start_deg + frac * 360 * ((x1 - x0) / 60.0)
                y = mid - amplitude * math.sin(math.radians(deg))
                if i == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            return path

        gray = QPen(QColor("#3a3f45"), 2)
        accent = QPen(self.color, 2.5)

        mid_x0, mid_x1 = w * 0.42, w * 0.58

        p.setPen(gray)
        p.drawPath(sine_path(0, mid_x0))
        p.drawPath(sine_path(mid_x1, w))

        p.setPen(accent)
        if self.kind == "click":
            path = QPainterPath()
            cx = (mid_x0 + mid_x1) / 2
            path.moveTo(mid_x0, mid)
            path.lineTo(cx - 6, mid)
            path.lineTo(cx, mid - amp * 1.7)
            path.lineTo(cx + 6, mid)
            path.lineTo(mid_x1, mid)
            p.drawPath(path)
        elif self.kind == "flatline":
            path = QPainterPath()
            path.moveTo(mid_x0, mid)
            path.lineTo(mid_x1, mid)
            p.drawPath(path)
        elif self.kind == "residual":
            import random
            rnd = random.Random(42)
            path = QPainterPath()
            x = mid_x0
            path.moveTo(x, mid)
            while x < mid_x1:
                x += 6
                y = mid + rnd.uniform(-amp * 0.5, amp * 0.5)
                path.lineTo(x, y)
            p.drawPath(path)
        elif self.kind == "freq_dev":
            p.drawPath(sine_path(mid_x0, mid_x1, amplitude=amp * 0.8))

        p.end()


ABOUT_ITEMS = [
    ("Click / Pop", "click", COLORS["danger"],
     "A single-sample discontinuity \u2014 an abrupt jump far larger than the "
     "signal's normal sample-to-sample movement. Sounds like a snap or tick. "
     "Usually a digital dropout, buffer underrun, or bad connection."),
    ("Flatline / Stuck", "flatline", COLORS["warning"],
     "The signal freezes at one value for longer than a real tone could ever "
     "sit still \u2014 a sine is only instantaneously flat at its peaks. Points "
     "to a sample-and-hold freeze or a dropped cycle."),
    ("Residual / Distortion", "residual", COLORS["info"],
     "Energy shows up outside the pure tone itself \u2014 extra harmonics or "
     "noise riding on top of it. Detected by filtering out the fundamental "
     "and checking what's left behind. Often clipping or interference."),
    ("Frequency Deviation", "freq_dev", COLORS["purple"],
     "The cycle-to-cycle timing drifts from the expected tone \u2014 measured "
     "directly from zero-crossing spacing. Suggests sample-rate mismatch, "
     "clock drift, or a phase glitch."),
]


class AboutPage(QWidget):
    def __init__(self, on_back):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 22, 32, 22)
        layout.setSpacing(14)

        top = QHBoxLayout()
        back = QPushButton("\u2190 Back")
        back.clicked.connect(on_back)
        top.addWidget(back)
        top.addStretch()
        layout.addLayout(top)

        layout.addWidget(h2("Understanding Glitch Types"))
        layout.addWidget(sub("Glitchy flags four distinct signal problems. Here's what each looks like on a waveform."))

        grid = QGridLayout()
        grid.setSpacing(16)
        for i, (title, kind, color, desc) in enumerate(ABOUT_ITEMS):
            card = panel()
            v = QVBoxLayout(card)
            v.setContentsMargins(18, 18, 18, 18)
            v.setSpacing(10)
            title_row = QHBoxLayout()
            dot = QLabel(); dot.setFixedSize(9, 9)
            dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
            title_row.addWidget(dot)
            t = h3(title); t.setStyleSheet(f"color: {color};")
            title_row.addWidget(t)
            title_row.addStretch()
            v.addLayout(title_row)
            v.addWidget(sub(desc))
            v.addWidget(WaveformDiagram(kind, color))
            grid.addWidget(card, i // 2, i % 2)
        layout.addLayout(grid, 1)


# ---------------------------------------------------------------------------
# Recorded (batch) setup page
# ---------------------------------------------------------------------------

class FileRow(QFrame):
    removed = Signal(object)

    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self.setProperty("role", "row")
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(4)

        top = QHBoxLayout()
        name = QLabel(self.path.name)
        name.setProperty("role", "mono")
        name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        top.addWidget(name, 1)
        remove_btn = QPushButton("\u00d7")
        remove_btn.setProperty("role", "icon")
        remove_btn.setFixedSize(24, 24)
        remove_btn.clicked.connect(lambda: self.removed.emit(self))
        top.addWidget(remove_btn, 0)
        v.addLayout(top)
        self._full_name = self.path.name
        self._name_label = name

        try:
            info = gc.sf.info(str(self.path))
            dur = format_duration(info.frames / info.samplerate)
            detail = f"{dur}   \u00b7   {info.samplerate}Hz / {info.subtype}"
        except Exception as e:
            detail = f"Could not read file: {e}"
        d = sub(detail)
        v.addWidget(d)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        metrics = self._name_label.fontMetrics()
        available = self._name_label.width()
        elided = metrics.elidedText(self._full_name, Qt.ElideMiddle, max(20, available))
        self._name_label.setText(elided)
        self._name_label.setToolTip(self._full_name)


class FileListWidget(QListWidget):
    """A QListWidget whose custom item widgets are kept exactly as wide as
    the viewport, so long filenames elide instead of forcing a horizontal
    scrollbar (and pushing the remove button out of view)."""

    def __init__(self):
        super().__init__()
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_item_widths()

    def _sync_item_widths(self):
        width = self.viewport().width()
        for i in range(self.count()):
            item = self.item(i)
            w = self.itemWidget(item)
            if w:
                item.setSizeHint(QSize(width, w.sizeHint().height()))
                w.resize(width, w.height())


class SetupPage(QWidget):
    start_requested = Signal()

    def __init__(self, on_switch_mode, on_about):
        super().__init__()
        self.files = []  # list of Path
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._mode_bar(on_switch_mode, on_about, active="recorded"))

        body = QHBoxLayout()
        body.setContentsMargins(20, 20, 20, 20)
        body.setSpacing(20)
        root.addLayout(body, 1)

        # Sidebar
        sidebar = QVBoxLayout()
        sidebar_header = QHBoxLayout()
        sidebar_header.addWidget(QLabel("FILES"))
        add_file_btn = QPushButton("+ File")
        add_folder_btn = QPushButton("+ Folder")
        add_file_btn.clicked.connect(self.add_files_dialog)
        add_folder_btn.clicked.connect(self.add_folder_dialog)
        sidebar_header.addStretch()
        sidebar_header.addWidget(add_file_btn)
        sidebar_header.addWidget(add_folder_btn)
        sidebar.addLayout(sidebar_header)

        self.file_list_widget = FileListWidget()
        self.file_list_widget.setSpacing(6)
        sidebar.addWidget(self.file_list_widget, 1)

        self.summary_label = sub("No files added yet")
        sidebar.addWidget(self.summary_label)

        sidebar_container = QWidget()
        sidebar_container.setLayout(sidebar)
        sidebar_container.setFixedWidth(320)
        body.addWidget(sidebar_container)

        # Main settings
        main_col = QVBoxLayout()
        settings_panel = panel()
        sv = QVBoxLayout(settings_panel)
        sv.setContentsMargins(24, 20, 24, 20)
        sv.setSpacing(14)
        sv.addWidget(h3("Detection Settings"))

        # Tone frequency
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(QLabel("Tone Frequency"))
        col.addWidget(sub("The pure tone frequency each recording is expected to contain"))
        row.addLayout(col, 1)
        self.tone_spin = QDoubleSpinBox(); self.tone_spin.setRange(20, 24000); self.tone_spin.setValue(1000)
        self.tone_spin.setSuffix(" Hz")
        self.auto_detect_check = QCheckBox("Auto-detect per file")
        self.auto_detect_check.setChecked(True)
        self.auto_detect_check.toggled.connect(lambda checked: self.tone_spin.setDisabled(checked))
        self.tone_spin.setDisabled(True)
        row.addWidget(self.tone_spin)
        row.addWidget(self.auto_detect_check)
        sv.addLayout(row)

        # Clips
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(QLabel("Save Clips Around Glitches"))
        col.addWidget(sub("Exports a short WAV around each detected glitch, named with its timestamp"))
        row.addLayout(col, 1)
        self.clips_check = QCheckBox("Enabled"); self.clips_check.setChecked(True)
        self.pre_roll_spin = QDoubleSpinBox(); self.pre_roll_spin.setRange(0, 120); self.pre_roll_spin.setValue(5)
        self.pre_roll_spin.setSuffix(" s pre-roll")
        self.post_issue_spin = QDoubleSpinBox(); self.post_issue_spin.setRange(0, 120); self.post_issue_spin.setValue(5)
        self.post_issue_spin.setSuffix(" s post-issue")
        row.addWidget(self.clips_check)
        row.addWidget(self.pre_roll_spin)
        row.addWidget(self.post_issue_spin)
        sv.addLayout(row)

        # Output folder
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(QLabel("Clip & Report Output Folder"))
        col.addWidget(sub("Where extracted clips and the CSV report are saved"))
        row.addLayout(col, 1)
        self.output_folder_edit = QLineEdit()
        self.output_folder_edit.setReadOnly(True)
        self.output_folder_edit.setPlaceholderText("Defaults to a 'glitch_clips' folder next to each file")
        browse_btn = QPushButton("Browse\u2026")
        browse_btn.clicked.connect(self.browse_output_folder)
        row.addWidget(self.output_folder_edit, 1)
        row.addWidget(browse_btn)
        sv.addLayout(row)

        # Threads
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(QLabel("Parallel Files"))
        col.addWidget(sub("Analyze multiple recordings at once, one process per file"))
        row.addLayout(col, 1)
        self.threads_combo = QComboBox()
        cpu_n = os.cpu_count() or 4
        self.threads_combo.addItem(f"Auto \u2014 up to {cpu_n} at once ({cpu_n} cores detected)", 0)
        for i in range(1, cpu_n + 1):
            self.threads_combo.addItem(str(i), i)
        row.addWidget(self.threads_combo)
        sv.addLayout(row)

        main_col.addWidget(settings_panel)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        start_btn = QPushButton("Start Analysis")
        start_btn.setProperty("role", "primary")
        start_btn.clicked.connect(self.start_requested.emit)
        btn_row.addWidget(start_btn)
        main_col.addLayout(btn_row)
        main_col.addStretch()

        main_col_widget = QWidget()
        main_col_widget.setLayout(main_col)
        main_scroll = QScrollArea()
        main_scroll.setWidgetResizable(True)
        main_scroll.setWidget(main_col_widget)
        body.addWidget(main_scroll, 1)

    def _mode_bar(self, on_switch_mode, on_about, active):
        bar = QFrame()
        bar.setObjectName("modeBar")
        bar.setStyleSheet(f"#modeBar {{ background: {COLORS['panel']}; border-bottom: 1px solid {COLORS['border']}; }}")
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 8, 20, 8)
        recorded_btn = QPushButton("Recorded")
        live_btn = QPushButton("Live Monitor")
        recorded_btn.setProperty("role", "tab_active" if active == "recorded" else "tab")
        live_btn.setProperty("role", "tab_active" if active == "live" else "tab")
        recorded_btn.clicked.connect(lambda: on_switch_mode("recorded"))
        live_btn.clicked.connect(lambda: on_switch_mode("live"))
        h.addWidget(recorded_btn)
        h.addWidget(live_btn)
        h.addStretch()
        about_btn = QPushButton("?")
        about_btn.setProperty("role", "icon")
        about_btn.setFixedSize(28, 28)
        about_btn.clicked.connect(on_about)
        h.addWidget(about_btn)
        return bar

    def add_files_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Add WAV files", "", "WAV files (*.wav)")
        self._add_paths(paths)

    def add_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, "Add folder of WAV files")
        if folder:
            self._add_paths(gc.find_wav_files(folder, recursive=True))

    def _add_paths(self, paths):
        existing = {str(p) for p in self.files}
        for p in paths:
            if str(p) not in existing:
                self.files.append(Path(p))
        self._refresh_file_list()

    def _refresh_file_list(self):
        self.file_list_widget.clear()
        total_seconds = 0.0
        for path in self.files:
            row = FileRow(path)
            row.removed.connect(self._remove_file)
            item = QListWidgetItem(self.file_list_widget)
            item.setSizeHint(row.sizeHint())
            self.file_list_widget.addItem(item)
            self.file_list_widget.setItemWidget(item, row)
            try:
                info = gc.sf.info(str(path))
                total_seconds += info.frames / info.samplerate
            except Exception:
                pass
        if self.files:
            self.summary_label.setText(f"{len(self.files)} files \u00b7 {format_duration(total_seconds)} total")
        else:
            self.summary_label.setText("No files added yet")
        # force an immediate width sync so rows don't overflow before the
        # first real resize event fires
        self.file_list_widget._sync_item_widths()

    def _remove_file(self, row_widget):
        self.files = [p for p in self.files if p != row_widget.path]
        self._refresh_file_list()

    def get_settings(self):
        cpu_n = os.cpu_count() or 4
        max_workers = self.threads_combo.currentData() or cpu_n
        return {
            "files": list(self.files),
            "tone_hz": None if self.auto_detect_check.isChecked() else self.tone_spin.value(),
            "extract_clips": self.clips_check.isChecked(),
            "clip_pre_roll": self.pre_roll_spin.value(),
            "clip_post_issue": self.post_issue_spin.value(),
            "clip_dir": self.output_folder_edit.text() or None,
            "max_workers": min(max_workers, max(1, len(self.files))),
        }

    def browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if folder:
            self.output_folder_edit.setText(folder)


# ---------------------------------------------------------------------------
# Analyzing page (batch)
# ---------------------------------------------------------------------------

class FileProgressRow(QFrame):
    def __init__(self, filename, slot):
        super().__init__()
        self.setProperty("role", "row")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(6)
        top = QHBoxLayout()
        self.badge = QLabel(f"THREAD {slot}")
        self.badge.setStyleSheet(f"background: {COLORS['panel_alt']}; border: 1px solid {COLORS['border']}; "
                                  f"border-radius: 6px; padding: 2px 8px; color: {COLORS['info']}; font-size: 10px;")
        self.badge.setProperty("role", "mono")
        name = QLabel(filename); name.setProperty("role", "mono")
        top.addWidget(self.badge)
        top.addWidget(name)
        top.addStretch()
        self.status_label = QLabel("Queued")
        self.status_label.setStyleSheet(f"color: {COLORS['text_faint']};")
        top.addWidget(self.status_label)
        v.addLayout(top)
        self.bar = QProgressBar(); self.bar.setRange(0, 1000); self.bar.setValue(0)
        v.addWidget(self.bar)

    def set_running(self):
        self.status_label.setText("Analyzing\u2026")
        self.status_label.setStyleSheet(f"color: {COLORS['accent']};")

    def set_progress(self, frac):
        self.bar.setValue(int(frac * 1000))

    def set_done(self, n_glitches, error=None, tone_hz=None):
        self.bar.setValue(1000)
        if error:
            # Keep this short -- the full error (which can be a long file
            # path) already goes to the Alert Log below, where a QPlainTextEdit
            # wraps/scrolls it safely. An unwrapped long string here would
            # balloon this row's width (and drag the progress bar with it).
            self.status_label.setText("Error \u2014 see log below")
            self.status_label.setStyleSheet(f"color: {COLORS['danger']};")
        else:
            freq_note = f" @ {tone_hz:.1f} Hz" if tone_hz else ""
            self.status_label.setText(f"Done \u2014 {n_glitches} flagged{freq_note}")
            self.status_label.setStyleSheet(f"color: {COLORS['success']};")


class AnalyzingPage(QWidget):
    cancel_requested = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 22, 32, 22)
        layout.setSpacing(16)

        top = QHBoxLayout()
        col = QVBoxLayout()
        self.title_label = h2("Analyzing Files")
        self.sub_label = sub("")
        col.addWidget(self.title_label)
        col.addWidget(self.sub_label)
        top.addLayout(col)
        top.addStretch()
        cancel_btn = QPushButton("Cancel"); cancel_btn.setProperty("role", "danger")
        cancel_btn.clicked.connect(self.cancel_requested.emit)
        top.addWidget(cancel_btn)
        layout.addLayout(top)

        overall_panel = panel()
        ov = QVBoxLayout(overall_panel)
        ov.setContentsMargins(20, 14, 20, 14)
        row = QHBoxLayout()
        row.addWidget(QLabel("Overall Progress"))
        row.addStretch()
        self.overall_pct_label = QLabel("0%")
        row.addWidget(self.overall_pct_label)
        ov.addLayout(row)
        self.overall_bar = QProgressBar(); self.overall_bar.setRange(0, 1000)
        ov.addWidget(self.overall_bar)
        layout.addWidget(overall_panel)

        stats_row = QHBoxLayout()
        self.elapsed_label = QLabel("0:00:00"); self.elapsed_label.setProperty("role", "mono")
        self.elapsed_label.setStyleSheet("font-size: 20px; font-weight: 700;")
        self.remaining_label = QLabel("\u2014"); self.remaining_label.setProperty("role", "mono")
        self.remaining_label.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {COLORS['accent']};")
        self.completed_label = QLabel("0 / 0"); self.completed_label.setProperty("role", "mono")
        self.completed_label.setStyleSheet("font-size: 20px; font-weight: 700;")
        self.alerts_label = QLabel("0"); self.alerts_label.setProperty("role", "mono")
        self.alerts_label.setStyleSheet("font-size: 20px; font-weight: 700;")
        for val, label in [(self.elapsed_label, "Elapsed"), (self.remaining_label, "Est. Remaining"),
                            (self.completed_label, "Files Completed"), (self.alerts_label, "Alerts This Session")]:
            card = panel()
            v = QVBoxLayout(card); v.setContentsMargins(16, 12, 16, 12)
            v.addWidget(val)
            v.addWidget(sub(label))
            stats_row.addWidget(card)
        layout.addLayout(stats_row)

        self.rows_container = QVBoxLayout()
        self.rows_container.setSpacing(10)
        rows_widget = QWidget(); rows_widget.setLayout(self.rows_container)
        rows_scroll = QScrollArea()
        rows_scroll.setWidgetResizable(True)
        rows_scroll.setWidget(rows_widget)
        layout.addWidget(rows_scroll, 2)

        layout.addWidget(sub("ALERT LOG"))
        self.log = QPlainTextEdit(); self.log.setReadOnly(True)
        self.log.setStyleSheet("background: #0f1113; font-family: Menlo, Consolas, monospace; font-size: 12px;")
        layout.addWidget(self.log, 1)

        self.row_widgets = {}
        self.total_files = 0
        self.completed_files = 0
        self.total_alerts = 0

    def reset_for(self, files):
        # takeAt() (not just widget().setParent(None)) so any leftover
        # stretch/spacer item from a previous run is removed too, not just
        # the row widgets -- otherwise stretches accumulate across repeated
        # analysis runs and the row layout drifts.
        while self.rows_container.count():
            item = self.rows_container.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self.row_widgets = {}
        self.total_files = len(files)
        self.completed_files = 0
        self.total_alerts = 0
        self.title_label.setText(f"Analyzing {len(files)} File{'s' if len(files) != 1 else ''}")
        self.sub_label.setText("")
        self.overall_bar.setValue(0)
        self.overall_pct_label.setText("0%")
        self.elapsed_label.setText("0:00:00")
        self.remaining_label.setText("\u2014")
        self.completed_label.setText(f"0 / {len(files)}")
        self.alerts_label.setText("0")
        self.log.clear()
        for f in files:
            row = FileProgressRow(f.name, slot="\u2013")
            self.row_widgets[str(f)] = row
            self.rows_container.addWidget(row)
        self.rows_container.addStretch()

    def set_slot(self, file_path, slot):
        row = self.row_widgets.get(str(file_path))
        if row:
            row.badge.setText(f"THREAD {slot}")
            row.set_running()

    def set_progress(self, file_path, frac):
        row = self.row_widgets.get(str(file_path))
        if row:
            row.set_progress(frac)

    def set_done(self, file_path, n_glitches, error=None, tone_hz=None):
        row = self.row_widgets.get(str(file_path))
        if row:
            row.set_done(n_glitches, error, tone_hz)
        self.completed_files += 1
        self.completed_label.setText(f"{self.completed_files} / {self.total_files}")
        if not error and n_glitches:
            self.total_alerts += n_glitches
            self.alerts_label.setText(str(self.total_alerts))

    def set_overall(self, frac):
        self.overall_bar.setValue(int(frac * 1000))
        self.overall_pct_label.setText(f"{int(frac * 100)}%")

    def set_time(self, elapsed_seconds, frac):
        self.elapsed_label.setText(format_duration(elapsed_seconds))
        if frac > 0.02:  # avoid a wild extrapolation from a near-zero fraction
            remaining = elapsed_seconds * (1 - frac) / frac
            self.remaining_label.setText(format_duration(remaining))
        else:
            self.remaining_label.setText("\u2014")

    def log_line(self, text):
        self.log.appendPlainText(text)


# ---------------------------------------------------------------------------
# Results page
# ---------------------------------------------------------------------------

TYPE_COLORS = {
    "click": COLORS["danger"], "flatline": COLORS["warning"],
    "residual": COLORS["info"], "freq_dev": COLORS["purple"],
}
TYPE_LABELS = {"click": "Click", "flatline": "Flatline", "residual": "Residual", "freq_dev": "Freq Dev"}


class ResultsPage(QWidget):
    new_analysis_requested = Signal()

    def __init__(self):
        super().__init__()
        self.all_rows = []  # (filename, timestamp, kinds_str)
        self.clip_dir_hint = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 22, 32, 22)
        layout.setSpacing(16)

        top = QHBoxLayout()
        col = QVBoxLayout()
        self.title_label = h2("Analysis Complete")
        self.sub_label = sub("")
        col.addWidget(self.title_label)
        col.addWidget(self.sub_label)
        top.addLayout(col)
        top.addStretch()
        open_folder_btn = QPushButton("Open Clips Folder")
        open_folder_btn.clicked.connect(self.open_clips_folder)
        export_btn = QPushButton("Export CSV")
        export_btn.clicked.connect(self.export_csv)
        new_btn = QPushButton("New Analysis"); new_btn.setProperty("role", "primary")
        new_btn.clicked.connect(self.new_analysis_requested.emit)
        top.addWidget(open_folder_btn)
        top.addWidget(export_btn)
        top.addWidget(new_btn)
        layout.addLayout(top)

        stats_row = QHBoxLayout()
        self.stat_labels = {}
        for key, label in [("files", "Files Analyzed"), ("glitches", "Glitches Found"),
                            ("audio", "Audio Processed"), ("time", "Analysis Time")]:
            card = panel()
            v = QVBoxLayout(card)
            v.setContentsMargins(16, 14, 16, 14)
            val = QLabel("\u2014"); val.setStyleSheet("font-size: 22px; font-weight: 700;")
            val.setProperty("role", "mono")
            v.addWidget(val)
            v.addWidget(sub(label))
            self.stat_labels[key] = val
            stats_row.addWidget(card)
        layout.addLayout(stats_row)

        layout.addWidget(sub("FILES"))
        self.files_table = QTableWidget(0, 3)
        self.files_table.setHorizontalHeaderLabels(["File", "Frequency", "Status"])
        self.files_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.files_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.files_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.files_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.files_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.files_table.verticalHeader().hide()
        self.files_table.setMaximumHeight(160)
        layout.addWidget(self.files_table)

        layout.addWidget(sub("GLITCHES"))
        self.filter_row = QHBoxLayout()
        self.filter_buttons = {}
        layout.addLayout(self.filter_row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["File", "Timestamp", "Type"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 110)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().hide()
        layout.addWidget(self.table, 1)

    def load_results(self, all_rows, n_files, total_audio_seconds, analysis_seconds, clip_dir_hint,
                      file_summaries=None):
        self.all_rows = all_rows
        self.clip_dir_hint = clip_dir_hint
        self.stat_labels["files"].setText(str(n_files))
        self.stat_labels["glitches"].setText(str(len(all_rows)))
        self.stat_labels["audio"].setText(format_duration(total_audio_seconds))
        self.stat_labels["time"].setText(format_duration(analysis_seconds))
        self.sub_label.setText(f"{n_files} file{'s' if n_files != 1 else ''} \u00b7 "
                                f"{format_duration(total_audio_seconds)} of audio analyzed "
                                f"in {format_duration(analysis_seconds)}")

        file_summaries = file_summaries or []
        self.files_table.setRowCount(len(file_summaries))
        for i, (fname, status, detail, tone_hz) in enumerate(file_summaries):
            self.files_table.setItem(i, 0, QTableWidgetItem(fname))
            freq_text = f"{tone_hz:.1f} Hz" if tone_hz else "\u2014"
            self.files_table.setItem(i, 1, QTableWidgetItem(freq_text))
            if status == "error":
                text, color = f"Error: {detail}", COLORS["danger"]
            elif status == "flagged":
                text, color = f"{detail} flagged", COLORS["warning"]
            else:
                text, color = "OK \u2014 no glitches found", COLORS["success"]
            status_item = QTableWidgetItem(text)
            status_item.setForeground(QColor(color))
            self.files_table.setItem(i, 2, status_item)

        # rebuild filter chips based on kinds actually present
        for i in reversed(range(self.filter_row.count())):
            w = self.filter_row.itemAt(i).widget()
            if w:
                w.setParent(None)
        self.filter_buttons = {}
        counts = {}
        for _, _, kinds in all_rows:
            for k in kinds.split(","):
                counts[k] = counts.get(k, 0) + 1
        all_btn = QPushButton(f"All ({len(all_rows)})")
        all_btn.clicked.connect(lambda: self._apply_filter(None))
        self.filter_row.addWidget(all_btn)
        self.filter_buttons[None] = all_btn
        for k in ["flatline", "click", "residual", "freq_dev"]:
            if k in counts:
                btn = QPushButton(f"{TYPE_LABELS[k]} ({counts[k]})")
                btn.clicked.connect(lambda checked=False, kind=k: self._apply_filter(kind))
                self.filter_row.addWidget(btn)
                self.filter_buttons[k] = btn
        self.filter_row.addStretch()

        self._apply_filter(None)

    def _apply_filter(self, kind):
        for btn_kind, btn in self.filter_buttons.items():
            btn.setProperty("role", "source_active" if btn_kind == kind else "")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        rows = self.all_rows if kind is None else [r for r in self.all_rows if kind in r[2].split(",")]
        self.table.setRowCount(len(rows))
        for i, (fname, t, kinds) in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(fname))
            self.table.setItem(i, 1, QTableWidgetItem(gc.format_timestamp(t)))
            kind_widget = QWidget()
            h = QHBoxLayout(kind_widget); h.setContentsMargins(4, 2, 4, 2)
            for k in kinds.split(","):
                tag = QLabel(TYPE_LABELS.get(k, k))
                color = TYPE_COLORS.get(k, COLORS["text_faint"])
                tag.setStyleSheet(f"background: rgba(0,0,0,0.001); color: {color}; "
                                  f"border: 1px solid {color}; border-radius: 8px; padding: 1px 8px; font-size: 11px;")
                h.addWidget(tag)
            h.addStretch()
            self.table.setCellWidget(i, 2, kind_widget)

    def open_clips_folder(self):
        if self.clip_dir_hint and Path(self.clip_dir_hint).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.clip_dir_hint)))
        else:
            QMessageBox.information(self, "No clips folder", "No clip output folder is available to open.")

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "glitchy_results.csv", "CSV files (*.csv)")
        if not path:
            return
        with open(path, "w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["filename", "timestamp", "timestamp_seconds", "glitch_type"])
            for fname, t, kinds in self.all_rows:
                writer.writerow([fname, gc.format_timestamp(t), t, kinds])


# ---------------------------------------------------------------------------
# Live Monitor setup page
# ---------------------------------------------------------------------------

class LiveSetupPage(QWidget):
    start_requested = Signal()

    def __init__(self, on_switch_mode, on_about):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._mode_bar(on_switch_mode, on_about))

        body = QVBoxLayout()
        body.setContentsMargins(28, 18, 28, 18)
        body.setSpacing(14)
        body_widget = QWidget()
        body_widget.setLayout(body)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body_widget)
        root.addWidget(scroll, 1)

        body.addWidget(h2("Live Monitor"))
        body.addWidget(sub("Continuously analyze a live audio feed and alert the moment a glitch happens"))

        settings_panel = panel()
        sv = QVBoxLayout(settings_panel)
        sv.setContentsMargins(20, 16, 20, 16)
        sv.setSpacing(12)
        sv.addWidget(h3("Source"))

        source_row = QHBoxLayout()
        self.soundcard_btn = QPushButton("Sound Card Input")
        self.network_btn = QPushButton("Network Stream (SDP)")
        self.soundcard_btn.setProperty("role", "source_active")
        self.network_btn.clicked.connect(lambda: self._set_source("network"))
        self.soundcard_btn.clicked.connect(lambda: self._set_source("soundcard"))
        source_row.addWidget(self.soundcard_btn)
        source_row.addWidget(self.network_btn)
        sv.addLayout(source_row)

        # Sound card sub-panel
        self.soundcard_panel = QWidget()
        scp = QHBoxLayout(self.soundcard_panel); scp.setContentsMargins(0, 0, 0, 0)
        col = QVBoxLayout()
        col.addWidget(QLabel("Input Device"))
        col.addWidget(sub("Any device your system's audio driver exposes"))
        scp.addLayout(col, 1)
        self.device_combo = QComboBox()
        self._populate_devices()
        scp.addWidget(self.device_combo)
        sv.addWidget(self.soundcard_panel)

        # Network sub-panel
        self.network_panel = QWidget()
        self.network_panel.setVisible(False)
        npnl = QVBoxLayout(self.network_panel); npnl.setContentsMargins(0, 0, 0, 0)
        nrow = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(QLabel("SDP Source"))
        col.addWidget(sub("Load a .sdp file, or paste its contents directly"))
        nrow.addLayout(col, 1)
        browse_sdp_btn = QPushButton("Browse File\u2026")
        browse_sdp_btn.clicked.connect(self.browse_sdp_file)
        nrow.addWidget(browse_sdp_btn)
        npnl.addLayout(nrow)
        self.sdp_text = QTextEdit()
        self.sdp_text.setPlaceholderText('Paste SDP text here, e.g. starting with "v=0"')
        self.sdp_text.setFixedHeight(90)
        npnl.addWidget(self.sdp_text)
        parse_row = QHBoxLayout()
        self.sdp_status_label = QLabel("")
        parse_row.addWidget(self.sdp_status_label)
        parse_row.addStretch()
        parse_btn = QPushButton("Parse")
        parse_btn.clicked.connect(self.parse_sdp)
        parse_row.addWidget(parse_btn)
        npnl.addLayout(parse_row)
        sv.addWidget(self.network_panel)

        # Tone frequency
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(QLabel("Tone Frequency"))
        col.addWidget(sub("Sampled from the feed for a few seconds once monitoring starts"))
        row.addLayout(col, 1)
        self.tone_spin = QDoubleSpinBox(); self.tone_spin.setRange(20, 24000); self.tone_spin.setValue(1000)
        self.tone_spin.setSuffix(" Hz"); self.tone_spin.setDisabled(True)
        self.auto_detect_check = QCheckBox("Auto-detect"); self.auto_detect_check.setChecked(True)
        self.auto_detect_check.toggled.connect(lambda c: self.tone_spin.setDisabled(c))
        row.addWidget(self.tone_spin)
        row.addWidget(self.auto_detect_check)
        sv.addLayout(row)

        # Duration
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(QLabel("Monitor Duration"))
        col.addWidget(sub("Automatically stop listening after a set time, or run until you stop it"))
        row.addLayout(col, 1)
        dur_col = QVBoxLayout()
        self.run_until_stopped_radio = QRadioButton("Run until stopped")
        stop_after_row = QHBoxLayout()
        self.stop_after_radio = QRadioButton("Stop after")
        self.stop_after_radio.setChecked(True)
        self.duration_spin = QSpinBox(); self.duration_spin.setRange(1, 999); self.duration_spin.setValue(2)
        self.duration_unit_combo = QComboBox(); self.duration_unit_combo.addItems(["Minutes", "Hours"])
        self.duration_unit_combo.setCurrentText("Hours")
        stop_after_row.addWidget(self.stop_after_radio)
        stop_after_row.addWidget(self.duration_spin)
        stop_after_row.addWidget(self.duration_unit_combo)
        dur_col.addWidget(self.run_until_stopped_radio)
        dur_col.addLayout(stop_after_row)
        row.addLayout(dur_col)
        sv.addLayout(row)

        # Clips
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(QLabel("Save Clips on Alert"))
        col.addWidget(sub("Keeps a rolling buffer so saved clips include audio from before the alert triggered"))
        row.addLayout(col, 1)
        self.clips_check = QCheckBox("Enabled"); self.clips_check.setChecked(True)
        self.pre_roll_spin = QDoubleSpinBox(); self.pre_roll_spin.setRange(0, 120); self.pre_roll_spin.setValue(5)
        self.pre_roll_spin.setSuffix(" s pre-roll")
        self.post_issue_spin = QDoubleSpinBox(); self.post_issue_spin.setRange(0, 120); self.post_issue_spin.setValue(5)
        self.post_issue_spin.setSuffix(" s post-issue")
        row.addWidget(self.clips_check)
        row.addWidget(self.pre_roll_spin)
        row.addWidget(self.post_issue_spin)
        sv.addLayout(row)

        # Output folder
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(QLabel("Clip & Report Output Folder"))
        col.addWidget(sub("Where alert clips and the session log are saved"))
        row.addLayout(col, 1)
        self.output_folder_edit = QLineEdit(); self.output_folder_edit.setReadOnly(True)
        self.output_folder_edit.setPlaceholderText("Defaults to 'glitch_clips' in the current folder")
        browse_btn = QPushButton("Browse\u2026")
        browse_btn.clicked.connect(self.browse_output_folder)
        row.addWidget(self.output_folder_edit, 1)
        row.addWidget(browse_btn)
        sv.addLayout(row)

        body.addWidget(settings_panel)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        start_btn = QPushButton("Start Monitoring"); start_btn.setProperty("role", "primary")
        start_btn.clicked.connect(self.start_requested.emit)
        btn_row.addWidget(start_btn)
        body.addLayout(btn_row)
        body.addStretch()

        self._source = "soundcard"
        self._parsed_sdp = None

    def _mode_bar(self, on_switch_mode, on_about):
        bar = QFrame()
        bar.setObjectName("modeBar")
        bar.setStyleSheet(f"#modeBar {{ background: {COLORS['panel']}; border-bottom: 1px solid {COLORS['border']}; }}")
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 8, 20, 8)
        recorded_btn = QPushButton("Recorded"); recorded_btn.setProperty("role", "tab")
        live_btn = QPushButton("Live Monitor"); live_btn.setProperty("role", "tab_active")
        recorded_btn.clicked.connect(lambda: on_switch_mode("recorded"))
        live_btn.clicked.connect(lambda: on_switch_mode("live"))
        h.addWidget(recorded_btn); h.addWidget(live_btn); h.addStretch()
        about_btn = QPushButton("?"); about_btn.setProperty("role", "icon"); about_btn.setFixedSize(28, 28)
        about_btn.clicked.connect(on_about)
        h.addWidget(about_btn)
        return bar

    def _populate_devices(self):
        self.device_combo.clear()
        try:
            devices = cap.SoundCardSource.list_devices()
            if not devices:
                self.device_combo.addItem("No input devices found", None)
            for d in devices:
                self.device_combo.addItem(d['name'], d.get('index'))
        except Exception as e:
            self.device_combo.addItem(f"Audio unavailable: {e}", None)

    def _set_source(self, source):
        self._source = source
        self.soundcard_btn.setProperty("role", "source_active" if source == "soundcard" else "")
        self.network_btn.setProperty("role", "source_active" if source == "network" else "")
        self.soundcard_btn.style().unpolish(self.soundcard_btn); self.soundcard_btn.style().polish(self.soundcard_btn)
        self.network_btn.style().unpolish(self.network_btn); self.network_btn.style().polish(self.network_btn)
        self.soundcard_panel.setVisible(source == "soundcard")
        self.network_panel.setVisible(source == "network")

    def browse_sdp_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose SDP file", "", "SDP files (*.sdp)")
        if path:
            with open(path) as f:
                self.sdp_text.setPlainText(f.read())
            self.parse_sdp()

    def parse_sdp(self):
        summary = cap.parse_sdp_summary(self.sdp_text.toPlainText())
        if summary:
            self._parsed_sdp = summary
            self.sdp_status_label.setText(
                f"Parsed \u2014 {summary['address']}:{summary['port']} \u00b7 {summary['rtpmap']}")
            self.sdp_status_label.setStyleSheet(f"color: {COLORS['success']};")
        else:
            self._parsed_sdp = None
            self.sdp_status_label.setText("Could not parse -- check the SDP text")
            self.sdp_status_label.setStyleSheet(f"color: {COLORS['danger']};")

    def browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if folder:
            self.output_folder_edit.setText(folder)

    def get_settings(self):
        duration_seconds = None
        if self.stop_after_radio.isChecked():
            mult = 3600 if self.duration_unit_combo.currentText() == "Hours" else 60
            duration_seconds = self.duration_spin.value() * mult
        return {
            "source": self._source,
            "device_index": self.device_combo.currentData(),
            "sdp_text": self.sdp_text.toPlainText(),
            "tone_hz": None if self.auto_detect_check.isChecked() else self.tone_spin.value(),
            "duration_seconds": duration_seconds,
            "extract_clips": self.clips_check.isChecked(),
            "clip_pre_roll": self.pre_roll_spin.value(),
            "clip_post_issue": self.post_issue_spin.value(),
            "clip_dir": self.output_folder_edit.text() or None,
        }


# ---------------------------------------------------------------------------
# Live Monitor running page
# ---------------------------------------------------------------------------

class LiveRunningPage(QWidget):
    stop_requested = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 22, 32, 22)
        layout.setSpacing(16)

        top = QHBoxLayout()
        dot = QLabel(); dot.setFixedSize(10, 10)
        dot.setStyleSheet(f"background: {COLORS['success']}; border-radius: 5px;")
        col = QVBoxLayout()
        title_row = QHBoxLayout()
        title_row.addWidget(dot)
        title_row.addWidget(h2("Monitoring Live"))
        title_row.addStretch()
        col.addLayout(title_row)
        self.source_label = sub("")
        col.addWidget(self.source_label)
        top.addLayout(col)
        top.addStretch()
        stop_btn = QPushButton("Stop"); stop_btn.setProperty("role", "danger")
        stop_btn.clicked.connect(self.stop_requested.emit)
        top.addWidget(stop_btn)
        layout.addLayout(top)

        stats_row = QHBoxLayout()
        self.elapsed_label = QLabel("0:00:00"); self.elapsed_label.setProperty("role", "mono")
        self.elapsed_label.setStyleSheet("font-size: 22px; font-weight: 700;")
        self.remaining_label = QLabel("\u2014"); self.remaining_label.setProperty("role", "mono")
        self.remaining_label.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {COLORS['accent']};")
        self.alert_count_label = QLabel("0"); self.alert_count_label.setProperty("role", "mono")
        self.alert_count_label.setStyleSheet("font-size: 22px; font-weight: 700;")
        for val, label in [(self.elapsed_label, "Elapsed"), (self.remaining_label, "Remaining"),
                            (self.alert_count_label, "Alerts This Session")]:
            card = panel()
            v = QVBoxLayout(card); v.setContentsMargins(16, 14, 16, 14)
            v.addWidget(val)
            v.addWidget(sub(label))
            stats_row.addWidget(card)
        layout.addLayout(stats_row)

        self.log = QPlainTextEdit(); self.log.setReadOnly(True)
        self.log.setStyleSheet("background: #0f1113; font-family: Menlo, Consolas, monospace; font-size: 12px;")
        layout.addWidget(self.log, 1)

        self.footer_label = sub("")
        layout.addWidget(self.footer_label)

        self.alert_count = 0

    def reset_for(self, source_desc, duration_seconds):
        self.source_label.setText(source_desc)
        self.elapsed_label.setText("0:00:00")
        self.remaining_label.setText(format_duration(duration_seconds) if duration_seconds else "\u2014 (until stopped)")
        self.alert_count = 0
        self.alert_count_label.setText("0")
        self.log.clear()
        if duration_seconds:
            self.footer_label.setText("Will stop automatically when the timer runs out, or press Stop at any time "
                                       "-- everything logged so far is kept either way.")
        else:
            self.footer_label.setText("Running until you press Stop -- everything logged so far is kept.")

    def update_time(self, elapsed_seconds, duration_seconds):
        self.elapsed_label.setText(format_duration(elapsed_seconds))
        if duration_seconds:
            remaining = max(0, duration_seconds - elapsed_seconds)
            self.remaining_label.setText(format_duration(remaining))

    def log_alert(self, wall_time_str, kinds_str, clip_note):
        self.alert_count += 1
        self.alert_count_label.setText(str(self.alert_count))
        self.log.appendPlainText(f"{wall_time_str}   {kinds_str:<12}   {clip_note}")


# ---------------------------------------------------------------------------
# Main window / orchestration
# ---------------------------------------------------------------------------

def _progress_relay(queue, file_key, n):
    """Top-level (picklable) function used as the progress callback inside
    a worker process -- puts progress updates onto the shared queue."""
    queue.put(("progress", file_key, n))


class LicensesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Open Source Licenses")
        self.resize(640, 560)
        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        notices_path = Path(__file__).parent / "resources" / "THIRD_PARTY_NOTICES.md"
        try:
            browser.setMarkdown(notices_path.read_text())
        except Exception as e:
            browser.setPlainText(f"Could not load license notices: {e}")
        layout.addWidget(browser)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close_btn)
        layout.addLayout(row)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1280, 820)
        self._setup_menu_bar()

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.setup_page = SetupPage(self.switch_mode, self.show_about)
        self.analyzing_page = AnalyzingPage()
        self.results_page = ResultsPage()
        self.about_page = AboutPage(self.back_from_about)
        self.live_setup_page = LiveSetupPage(self.switch_mode, self.show_about)
        self.live_running_page = LiveRunningPage()

        for w in [self.setup_page, self.analyzing_page, self.results_page,
                  self.about_page, self.live_setup_page, self.live_running_page]:
            self.stack.addWidget(w)

        self.setup_page.start_requested.connect(self.start_batch_analysis)
        self.analyzing_page.cancel_requested.connect(self.cancel_batch_analysis)
        self.results_page.new_analysis_requested.connect(lambda: self.stack.setCurrentWidget(self.setup_page))
        self.live_setup_page.start_requested.connect(self.start_live_monitor)
        self.live_running_page.stop_requested.connect(self.stop_live_monitor)

        self._pre_about_page = self.setup_page
        self.stack.setCurrentWidget(self.setup_page)

        # Batch analysis state
        self.pool = None
        self.manager = None
        self.progress_queue = None
        self.pending_files = []
        self.futures = {}          # future -> file_path
        self.slot_of_file = {}     # str(file_path) -> slot number
        self.free_slots = []
        self.file_total_frames = {}
        self.file_samplerate = {}
        self.file_progress = {}
        self.batch_settings = None
        self.batch_start_time = None
        self.batch_results = []
        self.batch_file_summaries = []
        self.batch_timer = QTimer(self)
        self.batch_timer.timeout.connect(self._poll_batch)

        # Live monitor state
        self.live_detector = None
        self.live_source = None
        self.live_timer = QTimer(self)
        self.live_timer.timeout.connect(self._poll_live)
        self.live_start_time = None
        self.live_duration = None

    # -- menu bar --

    def _setup_menu_bar(self):
        menu_bar = self.menuBar()

        about_action = QAction(f"About {APP_NAME}", self)
        about_action.setMenuRole(QAction.MenuRole.AboutRole)
        about_action.triggered.connect(self._show_about_dialog)

        licenses_action = QAction("Open Source Licenses", self)
        licenses_action.setMenuRole(QAction.MenuRole.ApplicationSpecificRole)
        licenses_action.triggered.connect(self._show_licenses_dialog)

        # On macOS, actions with AboutRole/etc. are moved into the
        # application menu automatically regardless of which menu they're
        # added to here -- Help is the conventional home for them elsewhere
        # (Windows/Linux), so it works correctly on both.
        help_menu = menu_bar.addMenu("Help")
        help_menu.addAction(about_action)
        help_menu.addAction(licenses_action)

    def _show_about_dialog(self):
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<h3>{APP_NAME}</h3>"
            f"<p>Version {APP_VERSION}</p>"
            f"<p>Detects glitches (clicks, flatlines, distortion, and frequency "
            f"deviation) in recorded or live test-tone audio.</p>"
            f"<p>Built with Python, Qt/PySide6, NumPy, SciPy, and other open "
            f"source components -- see Help \u2192 Open Source Licenses for details.</p>"
        )

    def _show_licenses_dialog(self):
        dlg = LicensesDialog(self)
        dlg.exec()

    # -- navigation --

    def switch_mode(self, mode):
        self.stack.setCurrentWidget(self.setup_page if mode == "recorded" else self.live_setup_page)

    def show_about(self):
        self._pre_about_page = self.stack.currentWidget()
        self.stack.setCurrentWidget(self.about_page)

    def back_from_about(self):
        self.stack.setCurrentWidget(self._pre_about_page)

    # -- batch analysis --

    def start_batch_analysis(self):
        settings = self.setup_page.get_settings()
        if not settings["files"]:
            QMessageBox.warning(self, "No files", "Add at least one WAV file first.")
            return

        self.batch_settings = settings
        self.batch_start_time = time.time()
        self._last_batch_poll_wall = self.batch_start_time
        self.batch_results = []
        self.batch_file_summaries = []
        self.file_total_frames = {}
        self.file_samplerate = {}
        self.file_progress = {}

        self.analyzing_page.reset_for(settings["files"])
        self.stack.setCurrentWidget(self.analyzing_page)

        for f in settings["files"]:
            try:
                info = gc.sf.info(str(f))
                self.file_total_frames[str(f)] = info.frames
                self.file_samplerate[str(f)] = info.samplerate
            except Exception:
                self.file_total_frames[str(f)] = 1
                self.file_samplerate[str(f)] = 48000  # unreadable; used only for the final audio-duration stat
            self.file_progress[str(f)] = 0

        self.manager = mp.Manager()
        self.progress_queue = self.manager.Queue()
        max_workers = settings["max_workers"]
        self.pool = mp.Pool(processes=max_workers)

        self.pending_files = list(settings["files"])
        self.futures = {}
        self.slot_of_file = {}
        self.free_slots = list(range(1, max_workers + 1))

        for _ in range(min(max_workers, len(self.pending_files))):
            self._submit_next()

        self.batch_timer.start(150)

    def _submit_next(self):
        if not self.pending_files or not self.free_slots:
            return
        f = self.pending_files.pop(0)
        slot = self.free_slots.pop(0)
        self.slot_of_file[str(f)] = slot
        self.analyzing_page.set_slot(f, slot)

        settings = self.batch_settings
        cb = None
        if self.progress_queue is not None:
            from functools import partial
            cb = partial(_progress_relay, self.progress_queue, str(f))

        async_result = self.pool.apply_async(
            gc.analyze_file,
            args=(str(f),),
            kwds=dict(
                tone_hz=settings["tone_hz"],
                extract_clips=settings["extract_clips"],
                clip_pre_roll=settings["clip_pre_roll"],
                clip_post_issue=settings["clip_post_issue"],
                clip_dir=settings["clip_dir"],
                progress_cb=cb,
            ),
        )
        self.futures[async_result] = f

    def _check_for_sleep_gap(self, attr_name, threshold=3.0):
        """
        Detects a suspiciously large gap between consecutive polls of a
        ~150-250ms timer -- the signature of the system having been asleep
        or the process suspended, not just scheduling jitter. Returns the
        gap in seconds (0 if none detected) so the caller can compensate
        elapsed-time bookkeeping and let the user know what happened,
        rather than the UI just looking like it hung or crashed.
        """
        now = time.time()
        last = getattr(self, attr_name, None)
        setattr(self, attr_name, now)
        if last is not None and (now - last) > threshold:
            return now - last
        return 0.0

    def _poll_batch(self):
        sleep_gap = self._check_for_sleep_gap("_last_batch_poll_wall")
        if sleep_gap:
            self.batch_start_time += sleep_gap
            self.analyzing_page.log_line(
                f"System appears to have been asleep for {format_duration(sleep_gap)} \u2014 resuming analysis")

        # drain progress messages
        try:
            while True:
                kind, file_key, n = self.progress_queue.get_nowait()
                if kind == "progress":
                    self.file_progress[file_key] = self.file_progress.get(file_key, 0) + n
                    total = self.file_total_frames.get(file_key, 1)
                    self.analyzing_page.set_progress(Path(file_key), min(1.0, self.file_progress[file_key] / total))
        except Exception:
            pass

        # check completed futures
        done_futures = [fut for fut in list(self.futures.keys()) if fut.ready()]
        for fut in done_futures:
            f = self.futures.pop(fut)
            slot = self.slot_of_file.pop(str(f), None)
            try:
                result = fut.get()
            except Exception as e:
                result = {"error": str(e), "glitches": [], "file": f.name}

            if result.get("error"):
                self.analyzing_page.set_done(f, 0, error=result["error"])
                self.analyzing_page.log_line(f"[ERROR] {f.name}: {result['error']}")
                self.batch_file_summaries.append((f.name, "error", result["error"], None))
            else:
                n = len(result["glitches"])
                tone_hz = result.get("tone_hz")
                self.analyzing_page.set_done(f, n, tone_hz=tone_hz)
                for t, kinds in result["glitches"]:
                    self.batch_results.append((f.name, t, kinds))
                    self.analyzing_page.log_line(
                        f"{gc.format_timestamp(t)}  {f.name}  {kinds} detected")
                if n == 0:
                    self.analyzing_page.log_line(f"{f.name}  analysis complete \u2014 no glitches found")
                self.batch_file_summaries.append((f.name, "ok" if n == 0 else "flagged", n, tone_hz))

            if slot is not None:
                self.free_slots.append(slot)
            self._submit_next()

        # Overall progress by frames -- but never claim 100% until every
        # file has actually reported done. A single pathological file
        # (corrupt header, degenerate audio) can throw off the frame-based
        # math for its own contribution; gating on completed-file count is
        # a simple, robust backstop against exactly that class of bug.
        total_frames = sum(self.file_total_frames.values()) or 1
        done_frames = sum(min(self.file_progress.get(k, 0), self.file_total_frames.get(k, 1))
                           for k in self.file_total_frames)
        frac = done_frames / total_frames
        if self.analyzing_page.completed_files < self.analyzing_page.total_files:
            frac = min(frac, 0.99)
        self.analyzing_page.set_overall(frac)
        self.analyzing_page.set_time(time.time() - self.batch_start_time, frac)

        if not self.futures and not self.pending_files:
            self._finish_batch()

    def _finish_batch(self):
        self.batch_timer.stop()
        elapsed = time.time() - self.batch_start_time
        total_audio = sum(self.file_total_frames[str(f)] / max(1, self.file_samplerate.get(str(f), 48000))
                           for f in self.batch_settings["files"]) if self.batch_settings["files"] else 0
        clip_dir_hint = self.batch_settings.get("clip_dir")
        if not clip_dir_hint and self.batch_settings["files"]:
            clip_dir_hint = str(self.batch_settings["files"][0].parent / "glitch_clips")

        self.results_page.load_results(
            self.batch_results, len(self.batch_settings["files"]), total_audio, elapsed, clip_dir_hint,
            self.batch_file_summaries)
        self.stack.setCurrentWidget(self.results_page)
        self._cleanup_pool()

    def cancel_batch_analysis(self):
        self.batch_timer.stop()
        self._cleanup_pool()
        self.stack.setCurrentWidget(self.setup_page)

    def _cleanup_pool(self):
        # pool.terminate() is documented, public API that immediately kills
        # every worker process -- unlike ProcessPoolExecutor, which has no
        # equivalent and previously required reaching into a private,
        # undocumented attribute to find worker PIDs. That attribute isn't
        # guaranteed to exist or be populated the same way across Python
        # versions, and when it silently didn't match what we expected,
        # Cancel looked like it worked but left every worker process running
        # in the background. Called unconditionally (finish or cancel) so
        # there's never any doubt about lingering processes either way.
        if self.pool is not None:
            try:
                self.pool.terminate()
                self.pool.join()
            except Exception:
                pass
        self.pool = None
        if self.manager is not None:
            try:
                self.manager.shutdown()
            except Exception:
                pass
        self.manager = None
        self.progress_queue = None
        self.futures = {}
        self.pending_files = []

    # -- live monitor --

    def start_live_monitor(self):
        settings = self.live_setup_page.get_settings()

        if settings["extract_clips"] and not settings["clip_dir"]:
            settings["clip_dir"] = str(Path.cwd() / "glitch_clips")

        sample_rate = 48000
        try:
            if settings["source"] == "soundcard":
                self.live_source = cap.SoundCardSource(device=settings["device_index"], sample_rate=sample_rate)
                source_desc = f"Sound card input \u00b7 {settings['tone_hz'] or 'auto-detecting'} Hz"
            else:
                summary = cap.parse_sdp_summary(settings["sdp_text"])
                if not summary:
                    QMessageBox.warning(self, "Invalid SDP", "Could not parse the SDP text -- check it and try again.")
                    return
                import tempfile
                tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".sdp", delete=False)
                tmp.write(settings["sdp_text"])
                tmp.close()
                self.live_source = cap.NetworkSource(tmp.name, sample_rate=sample_rate)
                source_desc = f"Network stream {summary['address']}:{summary['port']} \u00b7 {settings['tone_hz'] or 'auto-detecting'} Hz"
        except Exception as e:
            QMessageBox.critical(self, "Could not start source", str(e))
            return

        tone_hz = settings["tone_hz"] or 1000.0  # refined shortly after start if auto-detecting
        self.live_detector = cap.LiveDetector(
            sample_rate=sample_rate, tone_hz=tone_hz,
            on_glitch=self._on_live_glitch, on_clip_saved=self._on_live_clip_saved,
            extract_clips=settings["extract_clips"],
            clip_pre_roll=settings["clip_pre_roll"], clip_post_issue=settings["clip_post_issue"],
            clip_dir=settings["clip_dir"],
        )
        self._live_auto_detect_pending = settings["tone_hz"] is None
        self._live_samples_for_autodetect = []

        try:
            self.live_source.start(self.live_detector.push_audio)
        except Exception as e:
            QMessageBox.critical(self, "Could not start capture", str(e))
            return

        self.live_duration = settings["duration_seconds"]
        self.live_start_time = time.time()
        self._last_live_poll_wall = self.live_start_time
        self.live_running_page.reset_for(source_desc, self.live_duration)
        self.stack.setCurrentWidget(self.live_running_page)
        self.live_timer.start(250)

    def _on_live_glitch(self, t, kinds_str):
        wall = time.strftime("%I:%M:%S %p")
        self.live_running_page.log_alert(wall, kinds_str, "clip pending" if self.live_detector.extract_clips else "")

    def _on_live_clip_saved(self, path):
        self.live_running_page.log.appendPlainText(f"    \u2192 clip saved: {Path(path).name}")

    def _poll_live(self):
        if self.live_detector is None:
            return
        sleep_gap = self._check_for_sleep_gap("_last_live_poll_wall")
        if sleep_gap:
            self.live_start_time += sleep_gap
            self.live_running_page.log.appendPlainText(
                f"System appears to have been asleep for {format_duration(sleep_gap)} \u2014 resuming monitoring")
        self.live_detector.poll()
        elapsed = time.time() - self.live_start_time
        self.live_running_page.update_time(elapsed, self.live_duration)
        if self.live_duration and elapsed >= self.live_duration:
            self.stop_live_monitor()

    def stop_live_monitor(self):
        self.live_timer.stop()
        if self.live_source is not None:
            try:
                self.live_source.stop()
            except Exception:
                pass
        self.live_source = None
        self.live_detector = None
        self.stack.setCurrentWidget(self.live_setup_page)

    # -- shutdown --

    def closeEvent(self, event: QCloseEvent):
        """
        Best-effort cleanup of every background resource this app can be
        holding (batch worker processes, the multiprocessing Manager, a
        live capture source/subprocess), then a guaranteed hard exit.

        Without the hard exit: multiprocessing registers an atexit hook
        that joins any child processes it knows about, and a Manager's
        internal process/semaphores can be left in a state (especially
        after we've forcibly terminated a worker mid-task, as Cancel does)
        where that join hangs indefinitely -- which is exactly the "quit
        freezes" symptom. Everything the user cares about (results, clips)
        is already written to disk by this point, so a hard exit here loses
        nothing.
        """
        self.batch_timer.stop()
        self.live_timer.stop()

        if self.live_source is not None:
            try:
                self.live_source.stop()
            except Exception:
                pass

        self._cleanup_pool()

        event.accept()
        QTimer.singleShot(150, lambda: os._exit(0))


def main():
    mp.freeze_support()
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    icon_path = Path(__file__).parent / "resources" / "icon_1024.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
