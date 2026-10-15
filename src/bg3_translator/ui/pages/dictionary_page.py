"""Словарь: память переводов и глоссарий терминов."""

from __future__ import annotations

import logging
from typing import List

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..state import get_app_state
from ..widgets import Chip, EmptyState, GhostButton, PrimaryButton

log = logging.getLogger(__name__)
LIMIT = 500


def _ro(text: str, tip: str = "") -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    if tip:
        it.setToolTip(tip)
    return it


class DictionaryPage(QWidget):
    """Память переводов (правка, удаление, CSV) и глоссарий терминов."""

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.state = get_app_state()
        self._mem: list = []          # DictionaryEntry построчно
        self._gl_rows: List = []
        self._loading = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(14)

        head = QHBoxLayout()
        header = QLabel("Словарь")
        header.setObjectName("PageTitle")
        head.addWidget(header)
        head.addStretch(1)
        self.count_chip = Chip("0 записей", "accent")
        head.addWidget(self.count_chip)
        lay.addLayout(head)

        # ---------- переключатель ----------
        seg = QHBoxLayout()
        seg.setSpacing(8)
        self.btn_mem = QPushButton("Память переводов")
        self.btn_gl = QPushButton("Глоссарий")
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for i, b in enumerate((self.btn_mem, self.btn_gl)):
            b.setObjectName("Seg")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self._group.addButton(b, i)
            seg.addWidget(b)
        seg.addStretch(1)
        self.btn_mem.setChecked(True)
        self._group.idClicked.connect(self._switch)
        lay.addLayout(seg)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_memory())
        self.stack.addWidget(self._build_glossary())
        lay.addWidget(self.stack, 1)

        self._reload()

    # ==================================================================
    # Память
    # ==================================================================
    def _build_memory(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        hint = QLabel("Каждый переведённый и проверенный вами текст запоминается и подставляется "
                      "в других модах мгновенно и бесплатно. Двойной щелчок по переводу — исправить.")
        hint.setObjectName("Subtitle")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск…")
        self.search.setClearButtonEnabled(True)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self._reload_memory)
        self.search.textChanged.connect(lambda _t: self._debounce.start())
        bar.addWidget(self.search, 1)
        self.in_target = QCheckBox("и в переводе")
        self.only_verified = QCheckBox("только проверенные")
        for c in (self.in_target, self.only_verified):
            c.toggled.connect(self._reload_memory)
            bar.addWidget(c)
        imp = GhostButton("Импорт CSV…")
        imp.clicked.connect(self._import_csv)
        exp = GhostButton("Экспорт CSV…")
        exp.clicked.connect(self._export_csv)
        self.del_btn = GhostButton("Удалить выбранные")
        self.del_btn.clicked.connect(self._delete_selected)
        for b in (imp, exp, self.del_btn):
            bar.addWidget(b)
        lay.addLayout(bar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Источник", "Перевод", "Языки", "Проверен", "Исп."])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col, width in ((2, 90), (3, 100), (4, 70)):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(col, width)
        self.table.itemChanged.connect(self._on_mem_edited)
        lay.addWidget(self.table, 1)

        self.empty = EmptyState("📚", "Словарь пока пуст",
                                "Переведённые строки автоматически попадают сюда и "
                                "переиспользуются в следующих модах.")
        lay.addWidget(self.empty, 1)
        return w

    def _reload_memory(self, *_):
        needle = self.search.text().strip()
        d = self.state.dictionary
        self._mem = d.search(needle, "", limit=LIMIT, in_target=self.in_target.isChecked(),
                             only_verified=self.only_verified.isChecked())
        total = d.count()
        filtered = bool(needle) or self.only_verified.isChecked()
        self.count_chip.setText(f"показано {len(self._mem)} из {total}" if filtered else f"{total} записей")
        has = bool(self._mem)
        self.table.setVisible(has)
        self.empty.setVisible(not has)
        self.del_btn.setEnabled(has)
        if not has:
            if filtered:
                self.empty.set_text("Ничего не найдено", "Измените запрос или снимите фильтры.")
            else:
                self.empty.set_text("Словарь пока пуст",
                                    "Переведённые строки автоматически попадают сюда и "
                                    "переиспользуются в следующих модах.")
        self._loading = True
        self.table.setRowCount(len(self._mem))
        for row, e in enumerate(self._mem):
            src = _ro(e.source_text, e.source_text[:600])
            tgt = QTableWidgetItem(e.target_text)
            tgt.setToolTip(e.target_text[:600])
            langs = _ro(f"{e.source_language}→{e.target_language}")
            ver = _ro("✔" if e.verified else "—")
            ver.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            uses = _ro(str(e.usage_count))
            uses.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            for col, it in enumerate((src, tgt, langs, ver, uses)):
                self.table.setItem(row, col, it)
        self._loading = False

    def _on_mem_edited(self, item: QTableWidgetItem):
        if self._loading or item.column() != 1:
            return
        row = item.row()
        if not 0 <= row < len(self._mem):
            return
        e = self._mem[row]
        new = item.text().strip()
        if not new or new == e.target_text:
            self._loading = True
            item.setText(e.target_text)
            self._loading = False
            return
        self.state.dictionary.update_target(e.source_text, e.source_language, e.target_language, new, True)
        e.target_text, e.verified = new, True
        self._loading = True
        self.table.item(row, 3).setText("✔")
        self._loading = False
        self.main.toast("Запись обновлена", "success", 1800)

    def _delete_selected(self):
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        if not rows:
            self.main.toast("Выделите записи в таблице.", "info")
            return
        if QMessageBox.question(self, "Удалить записи",
                                f"Удалить из словаря записей: {len(rows)}?") != QMessageBox.StandardButton.Yes:
            return
        for r in rows:
            e = self._mem[r]
            self.state.dictionary.delete_by_source(e.source_text, e.source_language, e.target_language)
        self.main.toast(f"Удалено записей: {len(rows)}", "success")
        self._reload_memory()

    def _import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Импорт словаря", self.state.prefs.get("last_dir") or "",
                                              "CSV (*.csv)")
        if not path:
            return
        project = self.state.project
        try:
            n = self.state.dictionary.import_csv(
                path, project.source_language if project else "en",
                project.target_language if project else "ru")
        except Exception as exc:
            log.exception("Импорт CSV")
            self.main.toast(f"Не удалось импортировать: {exc}", "error", 6000)
            return
        self.main.toast(f"Импортировано записей: {n}", "success")
        self._reload_memory()

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт словаря", "dictionary.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            n = self.state.dictionary.export_csv(path)
        except Exception as exc:
            self.main.toast(f"Не удалось экспортировать: {exc}", "error", 6000)
            return
        self.main.toast(f"Сохранено записей: {n}", "success")

    # ==================================================================
    # Глоссарий
    # ==================================================================
    def _langs(self):
        p = self.state.project
        return (p.source_language, p.target_language) if p else ("en", "ru")

    def _build_glossary(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        hint = QLabel("Термины, которые ИИ обязан переводить одинаково: имена, заклинания, названия мест. "
                      "Если термин встретился в строке, он уходит в запрос вместе с обязательным переводом.")
        hint.setObjectName("Subtitle")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.g_term = QLineEdit()
        self.g_term.setPlaceholderText("Термин (как в оригинале)")
        self.g_tr = QLineEdit()
        self.g_tr.setPlaceholderText("Как переводить")
        self.g_note = QLineEdit()
        self.g_note.setPlaceholderText("Заметка (необязательно)")
        add = PrimaryButton("Добавить")
        add.clicked.connect(self._glossary_add)
        self.g_tr.returnPressed.connect(self._glossary_add)
        for w_ in (self.g_term, self.g_tr, self.g_note):
            row.addWidget(w_, 1)
        row.addWidget(add)
        lay.addLayout(row)
        self.g_lang = QLabel("")
        self.g_lang.setObjectName("Hint")
        lay.addWidget(self.g_lang)

        self.gtable = QTableWidget(0, 3)
        self.gtable.setHorizontalHeaderLabels(["Термин", "Перевод", "Заметка"])
        self.gtable.verticalHeader().setVisible(False)
        self.gtable.setShowGrid(False)
        self.gtable.setAlternatingRowColors(True)
        self.gtable.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.gtable.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.gtable.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        for c in range(3):
            self.gtable.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
        self.gtable.itemChanged.connect(self._on_gl_edited)
        lay.addWidget(self.gtable, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        dele = GhostButton("Удалить выбранные")
        dele.clicked.connect(self._glossary_delete)
        bottom.addWidget(dele)
        lay.addLayout(bottom)
        return w

    def _reload_glossary(self):
        src, tgt = self._langs()
        self.g_lang.setText(f"Языковая пара: {src} → {tgt} (по открытому проекту)")
        self._gl_rows = list(self.state.dictionary.glossary_list(src, tgt))
        self.count_chip.setText(f"терминов: {len(self._gl_rows)}")
        self._loading = True
        self.gtable.setRowCount(len(self._gl_rows))
        for i, r in enumerate(self._gl_rows):
            items = (_ro(r["term"]), QTableWidgetItem(r["translation"]), QTableWidgetItem(r["note"] or ""))
            for c, it in enumerate(items):
                self.gtable.setItem(i, c, it)
        self._loading = False

    def _glossary_add(self):
        term, tr = self.g_term.text().strip(), self.g_tr.text().strip()
        if not term or not tr:
            self.main.toast("Заполните термин и его перевод.", "warning")
            return
        src, tgt = self._langs()
        self.state.dictionary.glossary_add(term, tr, src, tgt, self.g_note.text().strip())
        for w in (self.g_term, self.g_tr, self.g_note):
            w.clear()
        self.g_term.setFocus()
        self._reload_glossary()

    def _on_gl_edited(self, item: QTableWidgetItem):
        if self._loading or item.column() == 0:
            return
        row = item.row()
        if not 0 <= row < len(self._gl_rows):
            return
        src, tgt = self._langs()
        term = self._gl_rows[row]["term"]
        tr = self.gtable.item(row, 1).text().strip()
        note = self.gtable.item(row, 2).text().strip()
        if not tr:
            self.main.toast("Перевод термина не может быть пустым.", "warning")
            self._reload_glossary()
            return
        self.state.dictionary.glossary_add(term, tr, src, tgt, note)

    def _glossary_delete(self):
        rows = sorted({i.row() for i in self.gtable.selectionModel().selectedRows()})
        if not rows:
            self.main.toast("Выделите термины в таблице.", "info")
            return
        src, tgt = self._langs()
        for r in rows:
            self.state.dictionary.glossary_delete(self._gl_rows[r]["term"], src, tgt)
        self._reload_glossary()

    # ==================================================================
    def _switch(self, idx: int):
        self.stack.setCurrentIndex(idx)
        self._reload()

    def _reload(self):
        if self.stack.currentIndex() == 0:
            self._reload_memory()
        else:
            self._reload_glossary()

    def showEvent(self, event):
        super().showEvent(event)
        self._reload()
