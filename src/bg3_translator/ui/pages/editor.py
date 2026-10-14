"""Translation editor page + mod import worker."""

from __future__ import annotations

import zipfile
from pathlib import Path

from PySide6.QtCore import Qt, QObject, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import theme
from ..progress_panel import ProgressPanel
from ..state import get_app_state
from ..widgets import (
    Card, Chip, Collapsible, DangerButton, EmptyState, GhostButton,
    GlowProgressBar, PrimaryButton,
)
from ...core.locaxml import parse_loca_xml, loca_to_entries
from ...models.translation import ModMetadata, TranslationProject, TranslationStatus

AI_COLOR = "#b98cff"


class ImportWorker(QObject):
    """Background import: reads .xml/.pak/.zip/folder, returns a project.

    Note: full .pak (LSPK v18) decompression is handled by core.pak (M6).
    This worker supports .xml and .zip (containing .xml) and folders now;
    .pak falls back to scanning for nested XMLs after extraction attempt.
    """

    finished = Signal(object)   # TranslationProject
    failed = Signal(str)

    def __init__(self, path: str, is_folder: bool, source_lang: str, target_lang: str):
        super().__init__()
        self.path = path
        self.is_folder = is_folder
        self.source_lang = source_lang
        self.target_lang = target_lang

    def run(self):
        try:
            project = self._import()
            self.finished.emit(project)
        except Exception as exc:
            self.failed.emit(str(exc))

    def _import(self) -> TranslationProject:
        import tempfile
        p = Path(self.path)
        xml_files: list[Path] = []
        temp_dir = None

        if self.is_folder or p.is_dir():
            xml_files = self._find_xmls(p)
        elif p.suffix.lower() == ".xml":
            xml_files = [p]
        elif p.suffix.lower() == ".zip":
            temp_dir = Path(tempfile.mkdtemp(prefix="bg3mt_"))
            with zipfile.ZipFile(p, "r") as zf:
                zf.extractall(temp_dir)
            xml_files = self._find_xmls(temp_dir)
        elif p.suffix.lower() == ".pak":
            from ...core.pak import extract_pak, PakError
            temp_dir = Path(tempfile.mkdtemp(prefix="bg3mt_pak_"))
            try:
                extract_pak(p, temp_dir)
            except PakError as exc:
                raise RuntimeError(f"Не удалось прочитать пакет: {exc}") from exc
            xml_files = self._find_xmls(temp_dir)
        else:
            raise RuntimeError(f"Неподдерживаемый тип файла: {p.suffix}")

        if not xml_files:
            raise RuntimeError("В источнике не найдено файлов локализации (XML)")

        entries = []
        for xf in xml_files:
            text = xf.read_text(encoding="utf-8", errors="replace")
            parsed = parse_loca_xml(text)
            entries.extend(loca_to_entries(parsed, self.source_lang, self.target_lang))

        if not entries:
            raise RuntimeError("Файлы локализации не содержат строк")

        metadata = ModMetadata(
            name=p.stem,
            source_path=p,
            supported_languages=[self.target_lang],
        )
        return TranslationProject(
            metadata=metadata,
            entries=entries,
            source_language=self.source_lang,
            target_language=self.target_lang,
        )

    @staticmethod
    def _find_xmls(root: Path) -> list[Path]:
        result = []
        for pattern in ("**/*.xml", "**/*.loc"):
            result.extend(root.glob(pattern))
        # Prefer files under Localization folders first
        result.sort(key=lambda x: (0 if "localization" in str(x).lower() else 1, str(x)))
        return result



class EditorPage(QWidget):
    """Таблица перевода: поиск, фильтр, пакетный перевод с живым прогрессом."""

    COL_STATUS, COL_SRC, COL_TGT = 0, 1, 2

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.state = get_app_state()
        self._running = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(14)

        # ---------- заголовок + счётчики ----------
        head = QHBoxLayout()
        head.setSpacing(8)
        header = QLabel("Перевод")
        header.setObjectName("PageTitle")
        head.addWidget(header)
        head.addStretch(1)
        self.chip_total = Chip("Всего: 0")
        self.chip_done = Chip("Переведено: 0", "success")
        self.chip_err = Chip("Ошибок: 0")
        for c in (self.chip_total, self.chip_done, self.chip_err):
            head.addWidget(c)
        lay.addLayout(head)

        # ---------- панель инструментов ----------
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по тексту или переводу…  (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(220)
        self._debounce.timeout.connect(self._apply_filter)
        self.search.textChanged.connect(lambda _t: self._debounce.start())
        bar.addWidget(self.search, 1)

        self.filter_box = QComboBox()
        self.filter_box.addItem("Все строки", "all")
        self.filter_box.addItem("Не переведено", "untranslated")
        self.filter_box.addItem("Переведено", "translated")
        self.filter_box.addItem("С ошибками", "errors")
        self.filter_box.currentIndexChanged.connect(self._apply_filter)
        bar.addWidget(self.filter_box)

        self.translate_btn = PrimaryButton("Перевести всё")
        self.translate_btn.clicked.connect(self._translate_all)
        bar.addWidget(self.translate_btn)

        self.cancel_btn = DangerButton("Остановить")
        self.cancel_btn.clicked.connect(self._cancel_translate)
        self.cancel_btn.setVisible(False)
        bar.addWidget(self.cancel_btn)

        self.export_btn = GhostButton("Экспорт…")
        self.export_btn.clicked.connect(self._export)
        bar.addWidget(self.export_btn)
        lay.addLayout(bar)

        # ---------- общий прогресс проекта ----------
        self.overall = GlowProgressBar(height=6)
        lay.addWidget(self.overall)

        # ---------- живая панель прогресса (разворачивается при запуске) ----------
        panel_card = Card()
        pcl = QVBoxLayout(panel_card)
        pcl.setContentsMargins(22, 18, 22, 18)
        self.panel = ProgressPanel()
        pcl.addWidget(self.panel)
        self.reveal = Collapsible(panel_card)
        lay.addWidget(self.reveal)

        # ---------- таблица ----------
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Статус", "Исходный текст", "Перевод"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.SelectedClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(self.COL_SRC, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(self.COL_TGT, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(self.COL_STATUS, 130)
        self.table.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.table, 1)

        self.empty = EmptyState(
            "📂", "Здесь появится перевод",
            "Откройте мод на главном экране — строки появятся в таблице, "
            "и их можно будет перевести одной кнопкой.",
        )
        go = PrimaryButton("Открыть мод")
        go.clicked.connect(lambda: self.main.navigate("dashboard"))
        self.empty.add_action(go)
        lay.addWidget(self.empty, 1)

        QShortcut(QKeySequence("Ctrl+F"), self, activated=self._focus_search)

        self.state.project_changed.connect(self.reload)
        self._connect_engine()
        self.reload()

    def _focus_search(self):
        self.search.setFocus()
        self.search.selectAll()

    def _connect_engine(self):
        """Connect engine signals once. The engine object is stable (its provider
        is swapped in-place on settings change), so these connections stay valid
        for the whole session and never need disconnecting."""
        engine = self.state.engine
        engine.progress.connect(self._on_translate_progress)
        engine.stage.connect(self._on_translate_stage)
        engine.finished.connect(self._on_translate_finished)
        engine.error.connect(self._on_translate_error)
        engine.cancelled.connect(self._on_translate_cancelled)

    # ---------- data loading ----------
    def reload(self):
        project = self.state.project
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        has = project is not None and bool(project.entries)
        self.table.setVisible(has)
        self.empty.setVisible(not has)
        self.translate_btn.setEnabled(has and not self._running)
        self.export_btn.setEnabled(has)
        if not has:
            self.table.blockSignals(False)
            self._refresh_stats()
            return
        entries = project.entries
        self.table.setRowCount(len(entries))
        for row, e in enumerate(entries):
            status_item = QTableWidgetItem()
            status_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            src_item = QTableWidgetItem(e.source_text)
            src_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            src_item.setToolTip(e.source_text)
            tgt_item = QTableWidgetItem(e.target_text)
            tgt_item.setData(Qt.ItemDataRole.UserRole, e.handle)
            tgt_item.setToolTip(e.target_text)
            self.table.setItem(row, self.COL_STATUS, status_item)
            self.table.setItem(row, self.COL_SRC, src_item)
            self.table.setItem(row, self.COL_TGT, tgt_item)
            self._style_row(row, e)
        self.table.blockSignals(False)
        self._refresh_stats()
        self._apply_filter()

    def _refresh_stats(self):
        s = self.state.stats()
        self.chip_total.setText(f"Всего: {s['total']}")
        self.chip_done.setText(f"Переведено: {s['translated']}")
        self.chip_err.setText(f"Ошибок: {s['errors']}")
        self.chip_err.set_tone("danger" if s["errors"] else "")
        self.overall.setMaximum(100)
        self.overall.setValue(s["percent"])
        left = max(s["total"] - s["translated"], 0)
        self.translate_btn.setText(f"Перевести всё · {left}" if left else "Перевести всё")

    # ---------- row styling ----------
    @staticmethod
    def _status_label(status: TranslationStatus) -> str:
        return {
            TranslationStatus.NEW: "○ Новый",
            TranslationStatus.TRANSLATED: "● Переведено",
            TranslationStatus.DICTIONARY_MATCH: "◆ Словарь",
            TranslationStatus.AUTO_TRANSLATED: "▲ AI",
            TranslationStatus.NEEDS_REVIEW: "⚑ Проверка",
            TranslationStatus.APPROVED: "✔ Готово",
            TranslationStatus.LOCKED: "Закрыто",
        }.get(status, status.value)

    @staticmethod
    def _status_color(status: TranslationStatus) -> str:
        pal = theme.current()
        return {
            TranslationStatus.NEW: pal.text_muted,
            TranslationStatus.TRANSLATED: pal.success,
            TranslationStatus.DICTIONARY_MATCH: pal.info,
            TranslationStatus.AUTO_TRANSLATED: AI_COLOR,
            TranslationStatus.NEEDS_REVIEW: pal.warning,
            TranslationStatus.APPROVED: pal.success,
            TranslationStatus.LOCKED: pal.text_muted,
        }.get(status, pal.text_muted)

    def _style_row(self, row: int, e):
        """Цвет и текст статуса; красная подсветка строки при ошибках плейсхолдеров."""
        pal = theme.current()
        st = self.table.item(row, self.COL_STATUS)
        src = self.table.item(row, self.COL_SRC)
        tgt = self.table.item(row, self.COL_TGT)
        if st is None or src is None or tgt is None:
            return
        has_err = e.has_validation_errors()
        if has_err:
            st.setText("✖ Ошибка")
            st.setForeground(QBrush(QColor(pal.danger)))
            tint = QBrush(theme.qcolor(pal.danger, 34))
            for it in (st, src, tgt):
                it.setBackground(tint)
            errs = list(getattr(e, "validation_errors", []) or [])
            st.setToolTip("\n".join(str(x) for x in errs) or "Ошибка плейсхолдеров")
        else:
            st.setText(self._status_label(e.status))
            st.setForeground(QBrush(QColor(self._status_color(e.status))))
            for it in (st, src, tgt):
                it.setData(Qt.ItemDataRole.BackgroundRole, None)
            st.setToolTip("")

    # ---------- editing ----------
    def _on_item_changed(self, item: QTableWidgetItem):
        if item.column() != self.COL_TGT:
            return
        handle = item.data(Qt.ItemDataRole.UserRole)
        project = self.state.project
        if not project or not handle:
            return
        for e in project.entries:
            if e.handle == handle:
                new_text = item.text()
                if new_text != e.target_text:
                    e.target_text = new_text
                    e.status = (TranslationStatus.TRANSLATED if new_text.strip()
                                else TranslationStatus.NEW)
                    e.update_timestamps()
                    from ...core.validation import compare_placeholders
                    errs, warns = compare_placeholders(e.source_text, new_text)
                    e.validation_errors = errs
                    e.validation_warnings = warns
                    project.update_stats()
                    self.table.blockSignals(True)
                    item.setToolTip(new_text)
                    self._style_row(item.row(), e)
                    self.table.blockSignals(False)
                    self._refresh_stats()
                    self.state.entry_edited.emit(handle)
                break

    # ---------- filtering ----------
    def _apply_filter(self):
        project = self.state.project
        if not project:
            return
        needle = self.search.text().lower()
        mode = self.filter_box.currentData()
        by_handle = {e.handle: e for e in project.entries}
        self.table.setUpdatesEnabled(False)
        for row in range(self.table.rowCount()):
            src_it = self.table.item(row, self.COL_SRC)
            tgt_it = self.table.item(row, self.COL_TGT)
            if src_it is None or tgt_it is None:
                continue
            handle = tgt_it.data(Qt.ItemDataRole.UserRole)
            entry = by_handle.get(handle)
            match_text = (not needle) or (needle in src_it.text().lower()) or (needle in tgt_it.text().lower())
            match_mode = True
            if mode == "untranslated":
                match_mode = bool(entry) and not entry.is_translated()
            elif mode == "translated":
                match_mode = bool(entry) and entry.is_translated()
            elif mode == "errors":
                match_mode = bool(entry and entry.has_validation_errors())
            self.table.setRowHidden(row, not (match_text and match_mode))
        self.table.setUpdatesEnabled(True)

    # ---------- batch translate (async, UI never freezes) ----------
    def _translate_all(self):
        project = self.state.project
        if not project:
            return
        targets = project.get_untranslated()
        if not targets:
            self.main.toast("Нечего переводить — все строки уже готовы.", "info")
            return
        if self.state.engine.provider is None:
            self.main.toast(
                "Провайдер перевода не настроен. Будут использованы только совпадения "
                "из словаря. Настройте провайдера в разделе «Настройки».", "warning", 5000
            )

        # The engine runs its loop in a worker thread; only queued Qt signals touch the UI,
        # so the window never freezes. Signals are connected once in __init__.
        engine = self.state.engine

        self._running = True
        self.panel.reset()
        self.panel.mod_label.setText(f"Мод: {project.metadata.name}")
        self.reveal.expand()
        self.translate_btn.setEnabled(False)
        self.cancel_btn.setVisible(True)
        self.cancel_btn.setEnabled(True)

        # Wrap only the untranslated entries; the engine mutates them in place,
        # so the live project objects are updated directly.
        sub = TranslationProject(
            metadata=project.metadata,
            entries=list(targets),
            source_language=project.source_language,
            target_language=project.target_language,
        )
        engine.run_async(sub)

    def _cancel_translate(self):
        if self.state.engine.is_running():
            self.cancel_btn.setEnabled(False)
            self.state.engine.cancel()

    def _on_translate_stage(self, _stage_id, stage_text):
        self.main.set_status(stage_text)

    def _on_translate_progress(self, pg):
        self.panel.update_progress(pg)
        err = getattr(pg, "failed", 0)
        skip = getattr(pg, "skipped", 0)
        done = getattr(pg, "succeeded", 0)
        self.main.set_status(
            f"{getattr(pg, 'stage_text', '')} · {done}/{getattr(pg, 'lines_total', 0)} строк"
            + (f" · ошибок: {err}" if err else "")
            + (f" · пропущено: {skip}" if skip else "")
        )

    def _finish_translate(self):
        self._running = False
        self.cancel_btn.setVisible(False)
        if self.state.project:
            self.state.project.update_stats()
        self.reload()                               # включает кнопку «Перевести»
        QTimer.singleShot(2200, self._maybe_collapse)

    def _maybe_collapse(self):
        if not self._running:
            self.reveal.collapse()

    def _on_translate_finished(self, _project):
        self._finish_translate()
        s = self.state.stats()
        if s["translated"] == 0 and s["total"] > 0:
            reason = getattr(self.state.engine, "first_error", None) or (
                "Не удалось перевести строки. Проверьте провайдера в «Настройках»."
            )
            self.main.toast(f"Ни одна строка не переведена. {reason}", "error", 9000)
            return
        self.main.toast(
            f"Перевод завершён: {s['translated']}/{s['total']} строк ({s['percent']}%)",
            "success", 5000,
        )
        self.state.entry_edited.emit("")      # обновить главную и сайдбар

    def _on_translate_error(self, message):
        self._finish_translate()
        self.main.toast(message, "error", 6000)

    def _on_translate_cancelled(self):
        self._finish_translate()
        self.main.toast("Перевод остановлен.", "warning")


    # ---------- export ----------
    def _export(self):
        from PySide6.QtWidgets import QFileDialog, QMenu
        from PySide6.QtCore import QPoint

        project = self.state.project
        if not project:
            return
        menu = QMenu(self)
        act_xml = menu.addAction("Файл локализации XML (.xml)")
        act_pak = menu.addAction("Пакет BG3 (.pak)")
        chosen = menu.exec(self.export_btn.mapToGlobal(QPoint(0, self.export_btn.height())))
        if chosen is act_xml:
            self._export_xml()
        elif chosen is act_pak:
            self._export_pak()

    def _export_xml(self):
        from PySide6.QtWidgets import QFileDialog
        from ...core.locaxml import build_loca_xml

        project = self.state.project
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт файла локализации XML", f"{project.metadata.name}.xml",
            "Файл локализации XML (*.xml)"
        )
        if not path:
            return
        pairs = [
            (e.handle, e.target_text if e.is_translated() else e.source_text)
            for e in project.entries
        ]
        Path(path).write_text(build_loca_xml(pairs), encoding="utf-8")
        self.main.toast(f"Экспортировано строк: {len(pairs)} → {Path(path).name}", "success")

    def _export_pak(self):
        from PySide6.QtWidgets import QFileDialog
        from ...core.locaxml import build_loca_xml, LocaVersion
        from ...core.pak import write_pak, PakError

        project = self.state.project
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт пакета BG3", f"{project.metadata.name}_Local.pak",
            "Пакет BG3 (*.pak)"
        )
        if not path:
            return
        pairs = [
            (e.handle, e.target_text if e.is_translated() else e.source_text)
            for e in project.entries
        ]
        xml_text = build_loca_xml(pairs, source_version=LocaVersion(1, 0, 0, 0))
        mod_name = project.metadata.name or "Mod"
        internal = f"Public/{mod_name}/Localization/{mod_name}.loc"
        try:
            write_pak(Path(path), {internal: xml_text.encode("utf-8")})
        except PakError as exc:
            self.main.toast(f"Не удалось создать пакет: {exc}", "error", 6000)
            return
        self.main.toast(
            f"Пакет создан, строк: {len(pairs)} → {Path(path).name}", "success"
        )
