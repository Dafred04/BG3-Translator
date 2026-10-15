"""Диалоги: найти и заменить."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout,
)

from .widgets import GhostButton, PrimaryButton


@dataclass
class FindParams:
    find: str
    replace: str
    case: bool
    whole: bool
    regex: bool
    scope: str            # "all" | "visible" | "selected"


class FindReplaceDialog(QDialog):
    """Найти и заменить в переводах. Счётчик совпадений обновляется по ходу ввода."""

    def __init__(self, parent=None, counter: Optional[Callable[[FindParams], int]] = None,
                 has_selection: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Найти и заменить")
        self.setMinimumWidth(460)
        self._counter = counter

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        title = QLabel("Найти и заменить в переводах")
        title.setObjectName("Title")
        lay.addWidget(title)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Что найти")
        self.repl_edit = QLineEdit()
        self.repl_edit.setPlaceholderText("На что заменить (можно пусто)")
        self.scope = QComboBox()
        self.scope.addItem("Во всём проекте", "all")
        self.scope.addItem("Только в видимых строках", "visible")
        if has_selection:
            self.scope.addItem("Только в выделенных строках", "selected")
        form.addRow("Найти", self.find_edit)
        form.addRow("Заменить на", self.repl_edit)
        form.addRow("Где", self.scope)
        lay.addLayout(form)

        self.case = QCheckBox("Учитывать регистр")
        self.whole = QCheckBox("Слово целиком")
        self.regex = QCheckBox("Регулярное выражение")
        opts = QHBoxLayout()
        for w in (self.case, self.whole, self.regex):
            opts.addWidget(w)
        opts.addStretch(1)
        lay.addLayout(opts)

        self.info = QLabel("")
        self.info.setObjectName("Subtitle")
        lay.addWidget(self.info)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = GhostButton("Отмена")
        cancel.clicked.connect(self.reject)
        self.go = PrimaryButton("Заменить всё")
        self.go.setEnabled(False)
        self.go.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(self.go)
        lay.addLayout(row)

        for w in (self.find_edit, self.repl_edit):
            w.textChanged.connect(self._update)
        for w in (self.case, self.whole, self.regex):
            w.toggled.connect(self._update)
        self.scope.currentIndexChanged.connect(self._update)
        self.find_edit.setFocus()

    def params(self) -> FindParams:
        return FindParams(self.find_edit.text(), self.repl_edit.text(), self.case.isChecked(),
                          self.whole.isChecked(), self.regex.isChecked(), self.scope.currentData())

    def _update(self):
        p = self.params()
        if not p.find:
            self.info.setText("")
            self.go.setEnabled(False)
            return
        try:
            n = self._counter(p) if self._counter else 0
        except Exception as exc:        # неверное регулярное выражение
            self.info.setText(f"Ошибка в выражении: {exc}")
            self.go.setEnabled(False)
            return
        self.info.setText(f"Найдено строк: {n}")
        self.go.setEnabled(n > 0)
