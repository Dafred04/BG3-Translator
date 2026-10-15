"""Страница «Перевод»: таблица, панель строки, пакетный перевод, найти/заменить, экспорт."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Set

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMenu, QMessageBox, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .. import logic, theme
from ..detail_panel import DetailPanel
from ..dialogs import FindParams, FindReplaceDialog
from ..progress_panel import ProgressPanel
from ..state import get_app_state
from ..widgets import (
    Card, Chip, Collapsible, DangerButton, EmptyState, GhostButton, GlowProgressBar, PrimaryButton,
)
from ...models.translation import (
    DictionaryEntry, TranslationEntry, TranslationProject, TranslationStatus,
)
from ...services import exporter
from ...services.importer import ImportResult, apply_translation_file, import_mod

log = logging.getLogger(__name__)

AI_COLOR = "#b98cff"
FLUSH_MS = 200            # как часто обновлять строки во время перевода
UNDO_LIMIT = 100


# ======================================================================
# Импорт в фоне
# ======================================================================
class ImportWorker(QObject):
    """Читает мод в фоновом потоке. Вся работа — в services.importer.import_mod."""

    finished = Signal(object)    # TranslationProject
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, path: str, is_folder: bool = False, source_lang: str = "en",
                 target_lang: str = "ru"):
        super().__init__()
        self.path = path
        self.is_folder = is_folder
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.result: Optional[ImportResult] = None

    def run(self):
        try:
            project = self._import()
        except Exception as exc:                                  # ImportFailure и всё остальное
            log.exception("Импорт не удался")
            self.failed.emit(str(exc) or exc.__class__.__name__)
            return
        self.finished.emit(project)

    def _import(self) -> TranslationProject:
        self.result = import_mod(self.path, self.source_lang, self.target_lang,
                                 progress=self.progress.emit)
        return self.result.to_project(self.source_lang, self.target_lang)


# ======================================================================
# Страница
# ======================================================================
class EditorPage(QWidget):
    COL_STATUS, COL_SRC, COL_TGT = 0, 1, 2

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.state = get_app_state()
        self._running = False
        self._rows: List[TranslationEntry] = []
        self._row_of: Dict[str, int] = {}
        self._dirty: Set[str] = set()
        self._undo: List[list] = []
        self._loading = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 24)
        lay.setSpacing(12)

        # ---------- заголовок ----------
        head = QHBoxLayout()
        head.setSpacing(8)
        header = QLabel("Перевод")
        header.setObjectName("PageTitle")
        head.addWidget(header)
        head.addStretch(1)
        self.chip_total = Chip("Всего: 0")
        self.chip_done = Chip("Переведено: 0", "success")
        self.chip_review = Chip("На проверке: 0", "warning")
        self.chip_err = Chip("Ошибок: 0")
        for c in (self.chip_total, self.chip_done, self.chip_review, self.chip_err):
            head.addWidget(c)
        lay.addLayout(head)

        # ---------- панель инструментов ----------
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по тексту, переводу или ключу…  (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(220)
        self._debounce.timeout.connect(self._apply_filter)
        self.search.textChanged.connect(lambda _t: self._debounce.start())
        bar.addWidget(self.search, 1)

        self.filter_box = QComboBox()
        for key, label in logic.FILTER_MODES:
            self.filter_box.addItem(label, key)
        self.filter_box.currentIndexChanged.connect(self._apply_filter)
        bar.addWidget(self.filter_box)

        self.translate_btn = PrimaryButton("Перевести всё")
        self.translate_btn.clicked.connect(self._translate_all)
        bar.addWidget(self.translate_btn)

        self.cancel_btn = DangerButton("Остановить")
        self.cancel_btn.clicked.connect(self._cancel_translate)
        self.cancel_btn.setVisible(False)
        bar.addWidget(self.cancel_btn)

        self.more_btn = GhostButton("Ещё ▾")
        self.more_btn.setMenu(self._build_more_menu())
        bar.addWidget(self.more_btn)

        self.export_btn = GhostButton("Экспорт ▾")
        self.export_btn.setMenu(self._build_export_menu())
        bar.addWidget(self.export_btn)
        lay.addLayout(bar)

        self.overall = GlowProgressBar(height=6)
        lay.addWidget(self.overall)

        # ---------- живой прогресс ----------
        panel_card = Card()
        pcl = QVBoxLayout(panel_card)
        pcl.setContentsMargins(22, 18, 22, 18)
        self.panel = ProgressPanel()
        pcl.addWidget(self.panel)
        self.reveal = Collapsible(panel_card)
        lay.addWidget(self.reveal)

        # ---------- таблица + панель строки ----------
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Статус", "Исходный текст", "Перевод"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(self.COL_SRC, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(self.COL_TGT, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(self.COL_STATUS, 130)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._on_selection)

        self.detail = DetailPanel()
        self.detail.apply_requested.connect(self._on_apply)
        self.detail.approve_requested.connect(self._on_approve)
        self.detail.translate_requested.connect(self._on_translate_one)
        self.detail.comment_edited.connect(self._on_comment)

        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.addWidget(self.table)
        self.split.addWidget(self.detail)
        self.split.setChildrenCollapsible(False)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 2)
        self.split.setSizes([700, 420])
        lay.addWidget(self.split, 1)

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
        QShortcut(QKeySequence("Ctrl+H"), self, activated=self._find_replace)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, activated=self._undo_last)

        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(FLUSH_MS)
        self._flush_timer.timeout.connect(self._flush_dirty)

        self.state.project_changed.connect(self.reload)
        self._connect_engine()
        self.reload()

    # ------------------------------------------------------------------
    # Меню
    # ------------------------------------------------------------------
    def _build_more_menu(self) -> QMenu:
        m = QMenu(self)
        m.addAction("Перевести выбранные строки", self._translate_selected)
        m.addAction("Повторить строки с ошибками", self._retry_errors)
        m.addSeparator()
        m.addAction("Найти и заменить…   Ctrl+H", self._find_replace)
        self.act_undo = m.addAction("Отменить последнюю правку   Ctrl+Shift+Z", self._undo_last)
        m.addSeparator()
        m.addAction("Подгрузить готовый перевод из файла…", self._load_existing)
        return m

    def _build_export_menu(self) -> QMenu:
        m = QMenu(self)
        m.addAction("Собрать пакет .pak…", lambda: self._export("pak"))
        m.addAction("Установить в папку модов BG3", lambda: self._export("install"))
        m.addSeparator()
        m.addAction("Файл локализации .loca…", lambda: self._export("loca"))
        m.addAction("Текстовый файл .xml…", lambda: self._export("xml"))
        return m

    # ------------------------------------------------------------------
    # Движок
    # ------------------------------------------------------------------
    def _connect_engine(self):
        """Сигналы подключаются один раз: объект движка живёт всю сессию."""
        e = self.state.engine
        e.progress.connect(self._on_translate_progress)
        e.stage.connect(self._on_translate_stage)
        e.finished.connect(self._on_translate_finished)
        e.error.connect(self._on_translate_error)
        e.cancelled.connect(self._on_translate_cancelled)
        e.entries_updated.connect(self._on_entries_updated)

    def _on_entries_updated(self, handles):
        self._dirty.update(handles or [])

    def _flush_dirty(self):
        if not self._dirty:
            return
        handles, self._dirty = self._dirty, set()
        self._refresh_rows(handles)
        self._refresh_stats()
        cur = self.detail.entry()
        if cur is not None and cur.handle in handles:
            self.detail.refresh_from_entry()

    # ------------------------------------------------------------------
    # Загрузка данных
    # ------------------------------------------------------------------
    def _focus_search(self):
        self.search.setFocus()
        self.search.selectAll()

    def reload(self):
        project = self.state.project
        self._loading = True
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setRowCount(0)
        self._undo.clear()
        self._dirty.clear()
        self.detail.set_entry(None)
        has = project is not None and bool(project.entries)
        self._rows = list(project.entries) if has else []
        self._row_of = {e.handle: i for i, e in enumerate(self._rows)}
        self.split.setVisible(has)
        self.empty.setVisible(not has)
        self.translate_btn.setEnabled(has and not self._running)
        self.more_btn.setEnabled(has and not self._running)
        self.export_btn.setEnabled(has and not self._running)
        if has:
            self.detail.set_target_language(project.target_language)
            self.table.setRowCount(len(self._rows))
            for row, e in enumerate(self._rows):
                for col in (self.COL_STATUS, self.COL_SRC, self.COL_TGT):
                    self.table.setItem(row, col, QTableWidgetItem())
                self.table.item(row, self.COL_TGT).setData(Qt.ItemDataRole.UserRole, e.handle)
                self._fill_row(row, e)
        self.table.blockSignals(False)
        self.table.setUpdatesEnabled(True)
        self._loading = False
        self._refresh_stats()
        self._apply_filter()

    def _refresh_stats(self):
        s = self.state.stats()
        self.chip_total.setText(f"Всего: {s['total']}")
        self.chip_done.setText(f"Переведено: {s['translated']}")
        self.chip_review.setText(f"На проверке: {s['review']}")
        self.chip_review.setVisible(s["review"] > 0)
        self.chip_err.setText(f"Ошибок: {s['errors']}")
        self.chip_err.set_tone("danger" if s["errors"] else "")
        self.overall.setMaximum(100)
        self.overall.setValue(s["percent"])
        left = max(s["total"] - s["translated"], 0)
        self.translate_btn.setText(f"Перевести всё · {left}" if left else "Перевести всё")
        self.act_undo.setEnabled(bool(self._undo))

    # ------------------------------------------------------------------
    # Строки таблицы
    # ------------------------------------------------------------------
    @staticmethod
    def _tone_color(tone: str, e: TranslationEntry) -> str:
        pal = theme.current()
        if e.status == TranslationStatus.AUTO_TRANSLATED and tone == "ok":
            return AI_COLOR
        return {"error": pal.danger, "warning": pal.warning, "review": pal.warning,
                "ok": pal.success, "new": pal.text_muted}.get(tone, pal.text_muted)

    def _fill_row(self, row: int, e: TranslationEntry):
        """Тексты, цвет и подсказки одной строки (сигналы таблицы должны быть заблокированы)."""
        st = self.table.item(row, self.COL_STATUS)
        src = self.table.item(row, self.COL_SRC)
        tgt = self.table.item(row, self.COL_TGT)
        if st is None or src is None or tgt is None:
            return
        tone = logic.row_tone(e)
        ro = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        st.setFlags(ro)
        src.setFlags(ro)
        tgt.setFlags(ro if "\n" in e.target_text else ro | Qt.ItemFlag.ItemIsEditable)

        st.setText(logic.status_label(e))
        st.setForeground(QBrush(QColor(self._tone_color(tone, e))))
        if src.text() != e.source_text:
            src.setText(e.source_text)
            src.setToolTip(e.source_text[:600])
        if tgt.text() != e.target_text:
            tgt.setText(e.target_text)

        notes = [f"✖ {x}" for x in e.validation_errors[:4]] + [f"⚠ {x}" for x in e.validation_warnings[:4]]
        st.setToolTip("\n".join(notes))
        tgt.setToolTip("\n".join(notes) if notes else e.target_text[:600])

        pal = theme.current()
        if tone == "error":
            tint = QBrush(theme.qcolor(pal.danger, 34))
        elif tone == "warning":
            tint = QBrush(theme.qcolor(pal.warning, 22))
        else:
            tint = None
        for it in (st, src, tgt):
            if tint is None:
                it.setData(Qt.ItemDataRole.BackgroundRole, None)
            else:
                it.setBackground(tint)

    def _refresh_rows(self, handles):
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        mode, needle = self._filter_state()
        current = self.table.currentRow()
        for h in handles:
            row = self._row_of.get(h)
            if row is None:
                continue
            e = self._rows[row]
            self._fill_row(row, e)
            if mode != "all" or needle:
                # выбранная строка не исчезает из-под рук, даже если перестала подходить под фильтр
                self.table.setRowHidden(row, row != current and not logic.entry_matches(e, needle, mode))
        self.table.setUpdatesEnabled(True)
        self.table.blockSignals(False)

    def _filter_state(self):
        return self.filter_box.currentData() or "all", self.search.text().strip().lower()

    def _apply_filter(self, *_):
        if not self._rows:
            return
        mode, needle = self._filter_state()
        self.table.setUpdatesEnabled(False)
        shown = 0
        for row, e in enumerate(self._rows):
            hide = not logic.entry_matches(e, needle, mode)
            self.table.setRowHidden(row, hide)
            shown += 0 if hide else 1
        self.table.setUpdatesEnabled(True)
        if mode != "all" or needle:
            self.main.set_status(f"Показано строк: {shown} из {len(self._rows)}")

    # ------------------------------------------------------------------
    # Выбор и правка
    # ------------------------------------------------------------------
    def _selected_entries(self) -> List[TranslationEntry]:
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        return [self._rows[r] for r in rows if 0 <= r < len(self._rows)]

    def _on_selection(self):
        if self._loading:
            return
        prev = self.detail.entry()
        if prev is not None and self.detail.has_unsaved_text():
            self._commit(prev.handle, self.detail.current_text())     # введённое не теряется
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows) or not self.table.selectionModel().hasSelection():
            self.detail.set_entry(None)
            return
        e = self._rows[row]
        self.detail.set_entry(e)
        self.detail.set_suggestion(None)
        if not e.is_translated() and e.source_text.strip():
            self._suggest(e)

    def _suggest(self, e: TranslationEntry):
        try:
            d = self.state.dictionary
            exact = d.lookup(e.source_text, e.source_language, e.target_language)
            if exact is not None:
                self.detail.set_suggestion(exact.target_text, 1.0)
                return
            found = d.lookup_fuzzy(e.source_text, e.source_language, e.target_language, 0.8)
            if found is not None:
                self.detail.set_suggestion(found[0].target_text, found[1])
        except Exception:
            log.exception("Подсказка из словаря не получена")

    def _on_item_changed(self, item: QTableWidgetItem):
        if self._loading or item.column() != self.COL_TGT:
            return
        handle = item.data(Qt.ItemDataRole.UserRole)
        if handle:
            self._commit(handle, item.text())

    def _on_apply(self, handle: str, text: str):
        self._commit(handle, text)
        self.detail.mark_saved()

    def _on_approve(self, handle: str, text: str):
        row = self._row_of.get(handle)
        if row is None:
            return
        e = self._rows[row]
        self._commit(handle, text, TranslationStatus.APPROVED)
        self.detail.mark_saved()
        if e.validation_errors:
            self.main.toast("В переводе есть ошибки плейсхолдеров — исправьте их перед утверждением.",
                            "warning", 4500)
            return
        if e.status == TranslationStatus.APPROVED:
            self._select_next(row)

    def _on_comment(self, handle: str, text: str):
        row = self._row_of.get(handle)
        if row is not None:
            self._rows[row].comment = text
            self.state.entry_edited.emit(handle)

    def _select_next(self, row: int):
        for r in range(row + 1, len(self._rows)):
            if not self.table.isRowHidden(r):
                self.table.selectRow(r)
                self.table.scrollToItem(self.table.item(r, self.COL_TGT))
                return

    def _commit(self, handle: str, text: str, status: Optional[TranslationStatus] = None) -> bool:
        """Единая точка ручной правки: история, проверки, словарь, обновление строки."""
        row = self._row_of.get(handle)
        if row is None or self.state.project is None:
            return False
        e = self._rows[row]
        old = (e.handle, e.target_text, e.status)
        if not logic.set_target(e, text, status, target_lang=e.target_language):
            self._refresh_rows([handle])        # вернуть исходный вид ячейки
            return False
        self._push_undo([old])
        self._remember_in_dictionary(e)
        self.state.project.update_stats()
        self._refresh_rows([handle])
        self._refresh_stats()
        self.state.entry_edited.emit(handle)
        cur = self.detail.entry()
        if cur is not None and cur.handle == handle:
            self.detail.refresh_from_entry()
        return True

    def _remember_in_dictionary(self, e: TranslationEntry):
        """Ручной перевод без ошибок — в память, как проверенный."""
        if not e.target_text.strip() or e.validation_errors:
            return
        try:
            self.state.dictionary.add(DictionaryEntry(
                source_text=e.source_text.strip(), source_language=e.source_language,
                target_text=e.target_text, target_language=e.target_language,
                handle=e.handle, context=e.context,
                source_mod=self.state.project.metadata.name if self.state.project else "",
                verified=True))
        except Exception:
            log.exception("Не удалось записать в словарь")

    # ------------------------------------------------------------------
    # Отмена
    # ------------------------------------------------------------------
    def _push_undo(self, group: list):
        if not group:
            return
        self._undo.append(group)
        del self._undo[:-UNDO_LIMIT]
        self.act_undo.setEnabled(True)

    def _undo_last(self):
        if self._running or not self._undo or self.state.project is None:
            return
        group = self._undo.pop()
        n = logic.undo_history(self.state.project, group)
        self.state.project.update_stats()
        self._refresh_rows({h for h, _t, _s in group})
        self._refresh_stats()
        self.detail.refresh_from_entry()
        self.state.entry_edited.emit("")
        self.main.toast(f"Отменено правок: {n}", "info")

    # ------------------------------------------------------------------
    # Найти и заменить
    # ------------------------------------------------------------------
    def _scope_entries(self, scope: str) -> List[TranslationEntry]:
        if scope == "selected":
            return self._selected_entries()
        if scope == "visible":
            return [e for r, e in enumerate(self._rows) if not self.table.isRowHidden(r)]
        return list(self._rows)

    def _count_matches(self, p: FindParams) -> int:
        rx = logic.compile_find(p.find, p.case, p.whole, p.regex)
        return len(logic.find_in_entries(self._scope_entries(p.scope), rx))

    def _find_replace(self):
        if not self._rows or self._running:
            return
        dlg = FindReplaceDialog(self, counter=self._count_matches,
                                has_selection=bool(self._selected_entries()))
        sel = self.detail.tgt_edit.textCursor().selectedText()
        if sel and " " not in sel:
            dlg.find_edit.setText(sel)
        if not dlg.exec():
            return
        p = dlg.params()
        try:
            rx = logic.compile_find(p.find, p.case, p.whole, p.regex)
            history = logic.replace_in_entries(self._scope_entries(p.scope), rx, p.replace,
                                               regex=p.regex, target_lang=self.state.project.target_language)
        except Exception as exc:
            self.main.toast(f"Замена не выполнена: {exc}", "error", 5000)
            return
        if not history:
            self.main.toast("Ничего не изменено.", "info")
            return
        self._push_undo(history)
        self.state.project.update_stats()
        self._refresh_rows({h for h, _t, _s in history})
        self._refresh_stats()
        self.detail.refresh_from_entry()
        self.state.entry_edited.emit("")
        self.main.toast(f"Заменено в строках: {len(history)}. Отменить: Ctrl+Shift+Z", "success", 5000)

    # ------------------------------------------------------------------
    # Готовый перевод из файла
    # ------------------------------------------------------------------
    def _load_existing(self):
        project = self.state.project
        if project is None or self._running:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Файл с готовым переводом", self.state.prefs.get("last_dir") or "",
            "Моды и локализация (*.pak *.zip *.loca *.xml);;Все файлы (*)")
        if not path:
            return
        self.state.prefs.set("last_dir", str(Path(path).parent))
        before = {e.handle: (e.target_text, e.status) for e in project.entries}
        try:
            filled, review = apply_translation_file(project, path)
        except Exception as exc:
            self.main.toast(f"Не удалось прочитать файл: {exc}", "error", 6000)
            return
        group = []
        for e in project.entries:
            t, s = before[e.handle]
            if e.target_text != t or e.status != s:
                group.append((e.handle, t, s))
        self._push_undo(group)
        self._refresh_rows({h for h, _t, _s in group})
        self._refresh_stats()
        self.state.entry_edited.emit("")
        if not filled:
            self.main.toast("В файле нет подходящих переводов (ключи не совпали).", "warning", 5000)
        else:
            extra = f", из них на проверке: {review}" if review else ""
            self.main.toast(f"Подгружено переводов: {filled}{extra}", "success", 5000)

    # ------------------------------------------------------------------
    # Перевод
    # ------------------------------------------------------------------
    def _ask(self, title: str, text: str, yes: str = "Продолжить", no: str = "Отмена") -> bool:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(text)
        ok = box.addButton(yes, QMessageBox.ButtonRole.AcceptRole)
        box.addButton(no, QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(ok)
        box.exec()
        return box.clickedButton() is ok

    def _translate_all(self):
        project = self.state.project
        if project is None:
            return
        todo = [e for e in project.entries if e.source_text.strip() and not e.is_translated()]
        if not todo:
            self.main.toast("Нечего переводить — все строки уже готовы.", "info")
            return
        self._start_translate(todo)

    def _translate_selected(self):
        sel = self._selected_entries()
        if not sel:
            self.main.toast("Выделите строки в таблице.", "info")
            return
        todo = [e for e in sel if e.source_text.strip() and not e.is_translated()]
        if todo:
            self._start_translate(todo)
            return
        if self._ask("Перевести заново?", f"Выбранные строки ({len(sel)}) уже переведены.\n"
                     "Стереть их перевод и перевести ещё раз?", "Перевести заново"):
            self._start_translate(sel, reset=True)

    def _retry_errors(self):
        bad = [e for e in self._rows if e.validation_errors]
        if not bad:
            self.main.toast("Строк с ошибками нет.", "info")
            return
        if self._ask("Повторить с ошибками", f"Строк с ошибками: {len(bad)}.\n"
                     "Их текущий перевод будет стёрт и получен заново (отменить можно).",
                     "Повторить"):
            self._start_translate(bad, reset=True)

    def _on_translate_one(self, handle: str):
        row = self._row_of.get(handle)
        if row is None:
            return
        self._start_translate([self._rows[row]], reset=True, confirm=False)

    def _start_translate(self, entries: List[TranslationEntry], reset: bool = False,
                         confirm: bool = True):
        project = self.state.project
        engine = self.state.engine
        if project is None or not entries:
            return
        if engine.is_running():
            self.main.toast("Перевод уже идёт.", "warning")
            return

        # Сначала оценка и подтверждение, и только потом стираем старый перевод.
        probe = entries
        if reset:
            probe = [TranslationEntry(handle=e.handle, source_text=e.source_text,
                                      source_language=e.source_language,
                                      target_language=e.target_language) for e in entries]
        opt = engine.options
        est = logic.estimate_job(probe, self.state.dictionary, batch_size=opt.batch_size,
                                 max_batch_chars=opt.max_batch_chars, workers=opt.workers,
                                 use_dictionary=opt.use_dictionary)
        if est.needs_provider and engine.provider is None:
            if not self._ask("Провайдер не настроен",
                             f"Для {est.to_translate} строк нужен ИИ-перевод, но провайдер не настроен.\n"
                             "Перевести только то, что есть в словаре?", "Только словарь"):
                return
        elif confirm and est.requests >= 5:
            text = (f"Строк: {est.untranslated} (уникальных {est.unique})\n"
                    f"Из словаря: {est.from_dictionary}\n"
                    f"Уйдёт в ИИ: {est.to_translate} строк, ≈{est.chars:,} символов\n"
                    f"Запросов: ≈{est.requests}, примерно {logic.format_duration(est.seconds)}"
                    ).replace(",", " ")
            if not self._ask("Начать перевод?", text, "Начать"):
                return

        if reset:
            group = [(e.handle, e.target_text, e.status) for e in entries
                     if e.target_text or e.status != TranslationStatus.NEW]
            for e in entries:
                e.target_text, e.status = "", TranslationStatus.NEW
                e.validation_errors, e.validation_warnings = [], []
            self._push_undo(group)
            self._refresh_rows({e.handle for e in entries})

        sub = TranslationProject(metadata=project.metadata, entries=list(entries),
                                 source_language=project.source_language,
                                 target_language=project.target_language)
        self._set_running(True)
        self.panel.reset()
        self.panel.mod_label.setText(f"Мод: {project.metadata.name}")
        self.reveal.expand()
        if not engine.run_async(sub):
            self._set_running(False)
            self.main.toast("Не удалось запустить перевод.", "error")
            return
        self._flush_timer.start()

    def _set_running(self, running: bool):
        self._running = running
        has = bool(self._rows)
        self.translate_btn.setEnabled(has and not running)
        self.more_btn.setEnabled(has and not running)
        self.export_btn.setEnabled(has and not running)
        self.cancel_btn.setVisible(running)
        self.cancel_btn.setEnabled(running)
        self.detail.set_busy(running)
        if not running:
            self._flush_timer.stop()

    def _cancel_translate(self):
        if self.state.engine.is_running():
            self.cancel_btn.setEnabled(False)
            self.cancel_btn.setText("Останавливаю…")
            self.state.engine.cancel()

    def _on_translate_stage(self, _stage_id, stage_text):
        self.main.set_status(stage_text)

    def _on_translate_progress(self, pg):
        self.panel.update_progress(pg)
        parts = [getattr(pg, "stage_text", ""),
                 f"{getattr(pg, 'done', 0)}/{getattr(pg, 'total', 0)} строк"]
        if getattr(pg, "failed", 0):
            parts.append(f"ошибок: {pg.failed}")
        if getattr(pg, "from_dictionary", 0):
            parts.append(f"из словаря: {pg.from_dictionary}")
        self.main.set_status(" · ".join(p for p in parts if p))

    def _finish_translate(self):
        """Общая концовка прогона: успех, ошибка или отмена."""
        self.cancel_btn.setText("Остановить")
        self._set_running(False)
        self._dirty.clear()
        if self.state.project:
            self.state.project.update_stats()
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        for row, e in enumerate(self._rows):                 # один полный проход после прогона
            self._fill_row(row, e)
        self.table.setUpdatesEnabled(True)
        self.table.blockSignals(False)
        self._apply_filter()
        self._refresh_stats()
        self.detail.refresh_from_entry()
        self.state.entry_edited.emit("")
        QTimer.singleShot(2500, self._maybe_collapse)

    def _maybe_collapse(self):
        if not self._running:
            self.reveal.collapse()

    def _on_translate_finished(self, _project):
        self._finish_translate()
        engine = self.state.engine
        s = self.state.stats()
        failed = len(getattr(engine, "last_failures", {}) or {})
        if s["translated"] == 0 and s["total"] > 0:
            reason = getattr(engine, "first_error", None) or "Проверьте провайдера в «Настройках»."
            self.main.toast(f"Ни одна строка не переведена. {reason}", "error", 9000)
            return
        msg = f"Перевод завершён: {s['translated']}/{s['total']} строк ({s['percent']}%)"
        if s["review"]:
            msg += f" · на проверке: {s['review']}"
        if failed:
            msg += f" · не удалось: {failed}"
        self.main.toast(msg, "warning" if (failed or s["errors"]) else "success", 6000)

    def _on_translate_error(self, message):
        self._finish_translate()
        self.main.toast(message, "error", 8000)

    def _on_translate_cancelled(self):
        self._finish_translate()
        self.main.toast("Перевод остановлен. Готовое сохранено.", "warning")

    # ------------------------------------------------------------------
    # Экспорт
    # ------------------------------------------------------------------
    def _export_dialog(self, title: str, ok_text: str) -> Optional[bool]:
        """Отчёт перед экспортом. Возвращает fallback_to_source либо None при отмене."""
        r = exporter.report(self.state.project)
        lines = [f"Всего строк: {r.total}", f"Переведено: {r.translated}"]
        if r.untranslated:
            lines.append(f"Не переведено: {r.untranslated}")
        if r.with_errors:
            lines.append(f"⚠ С ошибками плейсхолдеров: {r.with_errors} — в игре возможны сбои текста")
        if r.with_warnings:
            lines.append(f"С предупреждениями: {r.with_warnings}")
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Icon.Warning if r.with_errors else QMessageBox.Icon.Information)
        box.setText("\n".join(lines))
        cb = QCheckBox("Вставить оригинал вместо непереведённых строк")
        cb.setChecked(True)
        cb.setVisible(r.untranslated > 0)
        box.setCheckBox(cb)
        ok = box.addButton(ok_text, QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(ok)
        box.exec()
        if box.clickedButton() is not ok:
            return None
        return cb.isChecked() or r.untranslated == 0

    def _save_path(self, title: str, name: str, filt: str) -> Optional[str]:
        start = str(Path(self.state.prefs.get("last_dir") or "") / name)
        path, _ = QFileDialog.getSaveFileName(self, title, start, filt)
        if path:
            self.state.prefs.set("last_dir", str(Path(path).parent))
        return path or None

    def _export(self, kind: str):
        project = self.state.project
        if project is None or self._running:
            return
        cur = self.detail.entry()
        if cur is not None and self.detail.has_unsaved_text():
            self._commit(cur.handle, self.detail.current_text())
        fallback = self._export_dialog("Экспорт перевода", "Установить" if kind == "install" else "Экспортировать")
        if fallback is None:
            return
        base = exporter.translation_folder(project)
        try:
            if kind == "pak":
                path = self._save_path("Сохранить пакет", exporter.default_pak_name(project),
                                       "Пакет BG3 (*.pak)")
                if not path:
                    return
                out = exporter.export_pak(project, path, fallback)
                self.main.toast(f"Пакет готов: {out.name}. Положите его в папку Mods и включите в менеджере модов.",
                                "success", 7000)
            elif kind == "install":
                if exporter.mods_folder() is None:
                    self.main.toast("Папка модов BG3 есть только в Windows. Используйте «Собрать пакет».",
                                    "warning", 6000)
                    return
                with tempfile.TemporaryDirectory(prefix="bg3tr_") as tmp:
                    built = exporter.export_pak(project, Path(tmp) / exporter.default_pak_name(project), fallback)
                    dest = exporter.install_pak(built)
                self.main.toast(f"Установлено: {dest}. Включите мод в менеджере модов BG3.", "success", 8000)
            elif kind == "loca":
                path = self._save_path("Сохранить .loca", f"{base}.loca", "Файл локализации (*.loca)")
                if not path:
                    return
                Path(path).write_bytes(exporter.export_loca_bytes(project, fallback))
                self.main.toast(f"Сохранено: {Path(path).name}", "success")
            elif kind == "xml":
                path = self._save_path("Сохранить .xml", f"{base}.xml", "Текстовый файл (*.xml)")
                if not path:
                    return
                Path(path).write_text(exporter.export_xml_text(project, fallback), encoding="utf-8")
                self.main.toast(f"Сохранено: {Path(path).name}", "success")
        except Exception as exc:
            log.exception("Экспорт не удался")
            self.main.toast(f"Экспорт не удался: {exc}", "error", 7000)
