"""Dictionary page: поиск и просмотр памяти переводов."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..state import get_app_state
from ..widgets import Chip, EmptyState, GhostButton


class DictionaryPage(QWidget):
    """Browse, search and manage the translation memory."""

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.state = get_app_state()

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

        hint = QLabel(
            "Память переводов: каждое сохранённое значение переиспользуется в других "
            "модах — повторяющиеся строки переводятся мгновенно и бесплатно."
        )
        hint.setObjectName("Subtitle")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по исходному тексту…")
        self.search.setClearButtonEnabled(True)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self._reload)
        self.search.textChanged.connect(lambda _t: self._debounce.start())
        bar.addWidget(self.search, 1)
        self.refresh_btn = GhostButton("Обновить")
        self.refresh_btn.clicked.connect(self._reload)
        bar.addWidget(self.refresh_btn)
        lay.addLayout(bar)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Источник", "Перевод", "Использований"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 130)
        lay.addWidget(self.table, 1)

        self.empty = EmptyState("📚", "Словарь пока пуст",
                                "Переведённые строки автоматически попадают сюда и "
                                "переиспользуются в следующих модах.")
        lay.addWidget(self.empty, 1)

        self._reload()

    def showEvent(self, event):
        super().showEvent(event)
        self._reload()

    def _reload(self):
        needle = self.search.text().strip()
        entries = self.state.dictionary.search(needle, "", limit=500)
        total = self.state.dictionary.count()
        self.count_chip.setText(
            f"показано {len(entries)} из {total}" if needle else f"{total} записей"
        )
        has = bool(entries)
        self.table.setVisible(has)
        self.empty.setVisible(not has)
        if not has:
            if needle:
                self.empty.set_text("Ничего не найдено", f"По запросу «{needle}» записей нет.")
            else:
                self.empty.set_text("Словарь пока пуст",
                                    "Переведённые строки автоматически попадают сюда и "
                                    "переиспользуются в следующих модах.")
            return
        self.table.setRowCount(len(entries))
        for row, e in enumerate(entries):
            src = QTableWidgetItem(e.source_text)
            src.setToolTip(e.source_text)
            tgt = QTableWidgetItem(e.target_text)
            tgt.setToolTip(e.target_text)
            uses = QTableWidgetItem(str(e.usage_count))
            uses.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, src)
            self.table.setItem(row, 1, tgt)
            self.table.setItem(row, 2, uses)
