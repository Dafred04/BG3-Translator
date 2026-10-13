"""Dashboard: quick start actions + project stats."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QComboBox, QVBoxLayout, QWidget, QGridLayout,
)

from ..state import get_app_state
from ..widgets import Card, PrimaryButton, StatTile
from ...config import SUPPORTED_LANGUAGES


class DashboardPage(QWidget):
    """Landing page: open mod, see progress, quick actions."""

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.state = get_app_state()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(20)

        header = QLabel("Dashboard")
        header.setObjectName("Title")
        lay.addWidget(header)

        # --- Quick start card ---
        start_card = Card()
        sc_lay = QVBoxLayout(start_card)
        sc_lay.setContentsMargins(24, 20, 24, 20)
        sc_lay.setSpacing(12)

        sc_title = QLabel("Start a new translation")
        sc_title.setObjectName("Title")
        sc_lay.addWidget(sc_title)
        sc_hint = QLabel("Open a mod file (.pak, .zip, .xml) or an extracted folder to begin.")
        sc_hint.setObjectName("Subtitle")
        sc_lay.addWidget(sc_hint)

        row = QHBoxLayout()
        row.setSpacing(12)

        self.source_lang = QComboBox()
        self.target_lang = QComboBox()
        for lang in SUPPORTED_LANGUAGES:
            label = f"{lang.flag_emoji}  {lang.name}"
            self.source_lang.addItem(label, lang.code)
            self.target_lang.addItem(label, lang.code)
        # defaults en -> zh
        self.source_lang.setCurrentIndex(0)
        self.target_lang.setCurrentIndex(1)

        src_lbl = QLabel("From")
        src_lbl.setObjectName("Subtitle")
        tgt_lbl = QLabel("To")
        tgt_lbl.setObjectName("Subtitle")
        row.addWidget(src_lbl)
        row.addWidget(self.source_lang)
        row.addSpacing(12)
        row.addWidget(tgt_lbl)
        row.addWidget(self.target_lang)
        row.addStretch(1)

        self.open_btn = PrimaryButton("Open mod file…")
        self.open_btn.clicked.connect(self._open_mod)
        row.addWidget(self.open_btn)
        self.open_folder_btn = PrimaryButton("Open folder…")
        self.open_folder_btn.clicked.connect(self._open_folder)
        row.addWidget(self.open_folder_btn)

        sc_lay.addLayout(row)
        lay.addWidget(start_card)

        # --- Stats grid ---
        stats_card = Card()
        stats_lay = QGridLayout(stats_card)
        stats_lay.setContentsMargins(24, 20, 24, 20)
        stats_lay.setHorizontalSpacing(16)
        stats_lay.setVerticalSpacing(16)

        self.stat_total = StatTile("Total strings")
        self.stat_translated = StatTile("Translated")
        self.stat_progress = StatTile("Progress")
        self.stat_errors = StatTile("Validation errors")
        stats_lay.addWidget(self.stat_total, 0, 0)
        stats_lay.addWidget(self.stat_translated, 0, 1)
        stats_lay.addWidget(self.stat_progress, 0, 2)
        stats_lay.addWidget(self.stat_errors, 0, 3)
        lay.addWidget(stats_card)

        # --- Project info ---
        self.project_info = QLabel("No project loaded. Open a mod to get started.")
        self.project_info.setObjectName("Subtitle")
        self.project_info.setWordWrap(True)
        lay.addWidget(self.project_info)

        lay.addStretch(1)

        self.state.project_changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        s = self.state.stats()
        self.stat_total.set_value(str(s["total"]))
        self.stat_translated.set_value(str(s["translated"]))
        self.stat_progress.set_value(f"{s['percent']}%")
        self.stat_errors.set_value(str(s["errors"]))
        if self.state.project:
            m = self.state.project.metadata
            self.project_info.setText(
                f"Project: {m.name}  ·  {m.author or 'Unknown author'}  ·  v{m.version}\n"
                f"{m.source_path}"
            )
        else:
            self.project_info.setText("No project loaded. Open a mod to get started.")

    def _open_mod(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open mod file", "",
            "BG3 mod files (*.pak *.zip *.xml);;All files (*)"
        )
        if path:
            self._start_import(path, is_folder=False)

    def _open_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Open extracted mod folder")
        if path:
            self._start_import(path, is_folder=True)

    def _start_import(self, path: str, is_folder: bool):
        from .editor import ImportWorker
        from PySide6.QtCore import QThread

        self.main.toast("Reading mod…", "info")
        self.open_btn.setEnabled(False)
        self.open_folder_btn.setEnabled(False)

        self._thread = QThread()
        self._worker = ImportWorker(path, is_folder,
                                    self.source_lang.currentData(),
                                    self.target_lang.currentData())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_import_done)
        self._worker.failed.connect(self._on_import_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_import_done(self, project):
        self.state.project = project
        self.state.project_changed.emit()
        self.main.toast(f"Loaded {project.total_entries} strings", "success")
        self.main.navigate("editor")
        self.open_btn.setEnabled(True)
        self.open_folder_btn.setEnabled(True)

    def _on_import_failed(self, error: str):
        self.main.toast(f"Import failed: {error}", "error", 6000)
        self.open_btn.setEnabled(True)
        self.open_folder_btn.setEnabled(True)