"""Translation editor page + mod import worker."""

import zipfile
from pathlib import Path

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QProgressBar, QHeaderView,
    QAbstractItemView,
)

from ..state import get_app_state
from ..widgets import Card, PrimaryButton
from ...core.locaxml import parse_loca_xml, loca_to_entries
from ...models.translation import ModMetadata, TranslationProject, TranslationStatus


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
    """Side-by-side translation table with search, filter, batch translate."""

    COL_STATUS, COL_SRC, COL_TGT = 0, 1, 2

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.state = get_app_state()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(14)

        header = QLabel("Перевод")
        header.setObjectName("Title")
        lay.addWidget(header)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по исходному тексту или переводу…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        bar.addWidget(self.search, 1)

        self.filter_box = QComboBox()
        self.filter_box.addItem("Все", "all")
        self.filter_box.addItem("Не переведено", "untranslated")
        self.filter_box.addItem("Переведено", "translated")
        self.filter_box.addItem("С ошибками", "errors")
        self.filter_box.currentIndexChanged.connect(self._apply_filter)
        bar.addWidget(self.filter_box)

        self.translate_btn = PrimaryButton("Перевести всё")
        self.translate_btn.clicked.connect(self._translate_all)
        bar.addWidget(self.translate_btn)

        self.cancel_btn = PrimaryButton("Остановить")
        self.cancel_btn.clicked.connect(self._cancel_translate)
        self.cancel_btn.setVisible(False)
        bar.addWidget(self.cancel_btn)

        self.export_btn = PrimaryButton("Экспорт…")
        self.export_btn.clicked.connect(self._export)
        bar.addWidget(self.export_btn)
        lay.addLayout(bar)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        lay.addWidget(self.progress)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Статус", "Исходный текст", "Перевод"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.SelectedClicked)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(self.COL_SRC, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(self.COL_TGT, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(self.COL_STATUS, 110)
        self.table.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.table, 1)

        self.empty_label = QLabel("Проект не загружен.\nОткройте мод на главном экране, чтобы начать.")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setObjectName("Subtitle")
        lay.addWidget(self.empty_label, 1)

        self.state.project_changed.connect(self.reload)
        self.reload()

    # ---------- data loading ----------
    def reload(self):
        project = self.state.project
        self.table.setRowCount(0)
        has = project is not None and bool(project.entries)
        self.table.setVisible(has)
        self.empty_label.setVisible(not has)
        self.translate_btn.setEnabled(has)
        self.export_btn.setEnabled(has)
        if not has:
            return
        entries = project.entries
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(entries))
        for row, e in enumerate(entries):
            status_item = QTableWidgetItem(self._status_label(e.status))
            status_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            src_item = QTableWidgetItem(e.source_text)
            src_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            tgt_item = QTableWidgetItem(e.target_text)
            tgt_item.setData(Qt.ItemDataRole.UserRole, e.handle)
            self.table.setItem(row, self.COL_STATUS, status_item)
            self.table.setItem(row, self.COL_SRC, src_item)
            self.table.setItem(row, self.COL_TGT, tgt_item)
        self.table.setSortingEnabled(True)

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
        for row in range(self.table.rowCount()):
            src = self.table.item(row, self.COL_SRC).text().lower()
            tgt = self.table.item(row, self.COL_TGT).text().lower()
            handle = self.table.item(row, self.COL_TGT).data(Qt.ItemDataRole.UserRole)
            entry = by_handle.get(handle)
            match_text = (not needle) or (needle in src) or (needle in tgt)
            match_mode = True
            if mode == "untranslated":
                match_mode = bool(entry) and not entry.is_translated()
            elif mode == "translated":
                match_mode = bool(entry) and entry.is_translated()
            elif mode == "errors":
                match_mode = bool(entry and entry.has_validation_errors())
            self.table.setRowHidden(row, not (match_text and match_mode))

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

        # Run the whole loop in the engine's worker thread. Only Qt signals
        # (queued to the main thread) update the UI, so the window never freezes
        # even if a single Gemini call takes many seconds.
        engine = self.state.engine
        self._disconnect_engine()
        engine.progress.connect(self._on_translate_progress)
        engine.stage.connect(self._on_translate_stage)
        engine.finished.connect(self._on_translate_finished)
        engine.error.connect(self._on_translate_error)
        engine.cancelled.connect(self._on_translate_cancelled)

        self.progress.setVisible(True)
        self.progress.setMaximum(len(targets))
        self.progress.setValue(0)
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
        self.progress.setMaximum(max(getattr(pg, "total_files", 0), 1))
        self.progress.setValue(getattr(pg, "processed_files", 0))
        err = getattr(pg, "failed", 0)
        skip = getattr(pg, "skipped", 0)
        done = getattr(pg, "succeeded", 0)
        self.main.set_status(
            f"{pg.stage_text} · {done}/{getattr(pg, 'lines_total', 0)} строк"
            + (f" · ошибок: {err}" if err else "")
            + (f" · пропущено: {skip}" if skip else "")
        )

    def _finish_translate(self):
        self.progress.setVisible(False)
        self.translate_btn.setEnabled(True)
        self.cancel_btn.setVisible(False)
        self._disconnect_engine()
        if self.state.project:
            self.state.project.update_stats()
        self.reload()

    def _on_translate_finished(self, _project):
        self._finish_translate()
        s = self.state.stats()
        self.main.toast(
            f"Перевод завершён: {s['translated']}/{s['total']} строк ({s['percent']}%)",
            "success", 5000,
        )

    def _on_translate_error(self, message):
        self._finish_translate()
        self.main.toast(message, "error", 6000)

    def _on_translate_cancelled(self):
        self._finish_translate()
        self.main.toast("Перевод остановлен пользователем.", "warning")
        if self.state.project:
            self.state.project.update_stats()
        self.reload()

    def _disconnect_engine(self):
        engine = self.state.engine
        for sig, slot in (
            (engine.progress, self._on_translate_progress),
            (engine.stage, self._on_translate_stage),
            (engine.finished, self._on_translate_finished),
            (engine.error, self._on_translate_error),
            (engine.cancelled, self._on_translate_cancelled),
        ):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass


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