"""Dictionary page: search & browse translation memory."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QHeaderView, QAbstractItemView, QPushButton,
)

from ..state import get_app_state
from ..widgets import Card, PrimaryButton


class DictionaryPage(QWidget):
    """Browse, search and manage the translation memory."""

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.state = get_app_state()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(14)

        header = QLabel("Словарь")
        header.setObjectName("Title")
        lay.addWidget(header)

        hint = QLabel(
            "Память переводов: каждое сохранённое значение переиспользуется в других "
            "модах. Используйте поиск, чтобы просмотреть записи."
        )
        hint.setObjectName("Subtitle")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по исходному тексту…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._reload)
        bar.addWidget(self.search, 1)

        self.count_label = QLabel("0 записей")
        self.count_label.setObjectName("Subtitle")
        bar.addWidget(self.count_label)

        self.refresh_btn = QPushButton("Обновить")
        self.refresh_btn.clicked.connect(self._reload)
        bar.addWidget(self.refresh_btn)
        lay.addLayout(bar)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Источник", "Перевод", "Использований"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 70)
        lay.addWidget(self.table, 1)

        self._reload()

    def showEvent(self, event):
        super().showEvent(event)
        self._reload()

    def _reload(self):
        needle = self.search.text().strip()
        if needle:
            entries = self.state.dictionary.search(needle, "", limit=500)
            # search() filters by target_lang; empty string returns all — see store
        else:
            entries = self.state.dictionary.search("", "", limit=500)
        total = self.state.dictionary.count()
        self.count_label.setText(f"показано {len(entries)} / всего {total}")
        self.table.setRowCount(len(entries))
        for row, e in enumerate(entries):
            self.table.setItem(row, 0, QTableWidgetItem(e.source_text))
            self.table.setItem(row, 1, QTableWidgetItem(e.target_text))
            uses = QTableWidgetItem(str(e.usage_count))
            uses.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, uses)