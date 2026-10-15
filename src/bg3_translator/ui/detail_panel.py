"""Панель редактирования одной строки: оригинал, перевод, проверки, подсказка из словаря."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QStackedLayout, QVBoxLayout, QWidget,
)

from ..core.validation import compare_placeholders, qa_check
from ..models.translation import TranslationEntry
from .highlight import PlaceholderHighlighter
from .widgets import GhostButton, PrimaryButton


def _clean(text: str) -> str:
    return text.replace(" ", "\n").replace("\r\n", "\n")


class DetailPanel(QFrame):
    """Правая панель редактора. Сама ничего не сохраняет — только шлёт сигналы странице."""

    apply_requested = Signal(str, str)        # handle, текст
    approve_requested = Signal(str, str)      # handle, текст (применить и отметить «Готово»)
    translate_requested = Signal(str)         # handle
    comment_edited = Signal(str, str)         # handle, комментарий

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumWidth(340)
        self._entry: Optional[TranslationEntry] = None
        self._suggestion: Optional[str] = None
        self._target_lang = "ru"
        self._baseline = ""          # текст, с которым поле синхронизировано в последний раз

        stack = QStackedLayout(self)
        stack.setContentsMargins(0, 0, 0, 0)
        self._stack = stack

        # --- страница «ничего не выбрано» ---
        empty = QWidget()
        el = QVBoxLayout(empty)
        el.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("Выберите строку в таблице,\nчтобы отредактировать её здесь")
        hint.setObjectName("Subtitle")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.addWidget(hint)
        stack.addWidget(empty)

        # --- страница редактора ---
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(8)

        self.title = QLabel("Строка")
        self.title.setObjectName("CardTitle")
        self.where = QLabel("")
        self.where.setObjectName("Hint")
        self.where.setWordWrap(True)
        lay.addWidget(self.title)
        lay.addWidget(self.where)

        cap_src = QLabel("Оригинал")
        cap_src.setObjectName("Subtitle")
        self.src_edit = QPlainTextEdit()
        self.src_edit.setReadOnly(True)
        self.src_edit.setMinimumHeight(80)
        self._src_hl = PlaceholderHighlighter(self.src_edit.document())
        lay.addWidget(cap_src)
        lay.addWidget(self.src_edit, 2)

        head = QHBoxLayout()
        cap_tgt = QLabel("Перевод")
        cap_tgt.setObjectName("Subtitle")
        self.counter = QLabel("")
        self.counter.setObjectName("Hint")
        head.addWidget(cap_tgt)
        head.addStretch(1)
        head.addWidget(self.counter)
        lay.addLayout(head)
        self.tgt_edit = QPlainTextEdit()
        self.tgt_edit.setMinimumHeight(100)
        self.tgt_edit.setPlaceholderText("Введите перевод…  Ctrl+Enter — применить")
        self._tgt_hl = PlaceholderHighlighter(self.tgt_edit.document())
        lay.addWidget(self.tgt_edit, 3)

        self.err_label = QLabel("")
        self.err_label.setObjectName("IssueError")
        self.err_label.setWordWrap(True)
        self.warn_label = QLabel("")
        self.warn_label.setObjectName("IssueWarn")
        self.warn_label.setWordWrap(True)
        lay.addWidget(self.err_label)
        lay.addWidget(self.warn_label)

        self.banner = QFrame()
        self.banner.setObjectName("Banner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(12, 8, 8, 8)
        self.banner_text = QLabel("")
        self.banner_text.setWordWrap(True)
        self.use_suggestion = GhostButton("Подставить")
        self.use_suggestion.clicked.connect(self._use_suggestion)
        bl.addWidget(self.banner_text, 1)
        bl.addWidget(self.use_suggestion)
        self.banner.setVisible(False)
        lay.addWidget(self.banner)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.apply_btn = PrimaryButton("Применить")
        self.apply_btn.clicked.connect(self._apply)
        self.approve_btn = GhostButton("Утвердить ✔")
        self.approve_btn.setToolTip("Применить и отметить строку как проверенную")
        self.approve_btn.clicked.connect(self._approve)
        self.translate_btn = GhostButton("Перевести")
        self.translate_btn.setToolTip("Перевести только эту строку")
        self.translate_btn.clicked.connect(self._translate)
        row.addWidget(self.apply_btn)
        row.addWidget(self.approve_btn)
        row.addWidget(self.translate_btn)
        lay.addLayout(row)

        self.comment = QLineEdit()
        self.comment.setPlaceholderText("Комментарий к строке…")
        self.comment.editingFinished.connect(self._comment_done)
        lay.addWidget(self.comment)
        stack.addWidget(page)

        self._live = QTimer(self)
        self._live.setSingleShot(True)
        self._live.setInterval(180)
        self._live.timeout.connect(self._update_live)
        self.tgt_edit.textChanged.connect(self._on_text_changed)

        for seq in ("Ctrl+Return", "Ctrl+Enter"):
            sc = QShortcut(QKeySequence(seq), self.tgt_edit)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._apply)

        stack.setCurrentIndex(0)

    # ------------------------------------------------------------------
    def set_target_language(self, code: str):
        self._target_lang = code

    def entry(self) -> Optional[TranslationEntry]:
        return self._entry

    def has_unsaved_text(self) -> bool:
        """Пользователь что-то изменил в поле после последней синхронизации."""
        return self._entry is not None and _clean(self.tgt_edit.toPlainText()) != self._baseline

    def current_text(self) -> str:
        return _clean(self.tgt_edit.toPlainText())

    def mark_saved(self):
        self._baseline = _clean(self.tgt_edit.toPlainText())

    def set_entry(self, entry: Optional[TranslationEntry]):
        self._entry = entry
        self._suggestion = None
        self.banner.setVisible(False)
        if entry is None:
            self._stack.setCurrentIndex(0)
            return
        self._stack.setCurrentIndex(1)
        self.title.setText(f"Строка {entry.handle[:14]}…" if len(entry.handle) > 15 else f"Строка {entry.handle}")
        self.title.setToolTip(entry.handle)
        self.where.setText(entry.context or "")
        self.where.setVisible(bool(entry.context))
        self.src_edit.setPlainText(entry.source_text)
        self._set_text_quiet(entry.target_text)
        self._baseline = entry.target_text
        self.comment.blockSignals(True)
        self.comment.setText(entry.comment)
        self.comment.blockSignals(False)
        self._update_live()

    def refresh_from_entry(self):
        """Обновить поля после изменения записи снаружи (перевод ИИ, замена…)."""
        e = self._entry
        if e is None or self.has_unsaved_text():
            return                      # не затираем то, что пользователь печатает
        if _clean(self.tgt_edit.toPlainText()) != e.target_text:
            self._set_text_quiet(e.target_text)
        self._baseline = e.target_text
        self._update_live()

    def _set_text_quiet(self, text: str):
        self.tgt_edit.blockSignals(True)
        self.tgt_edit.setPlainText(text)
        self.tgt_edit.blockSignals(False)

    def set_suggestion(self, text: Optional[str], ratio: float = 1.0):
        self._suggestion = text
        if not text or self._entry is None or self._entry.is_translated():
            self.banner.setVisible(False)
            return
        shown = text if len(text) <= 120 else text[:117] + "…"
        self.banner_text.setText(f"В словаре есть похожая строка ({ratio:.0%}): «{shown}»")
        self.banner.setVisible(True)

    # ------------------------------------------------------------------
    def _on_text_changed(self):
        self._update_counter()
        self._live.start()

    def _update_counter(self):
        e = self._entry
        if e is None:
            return
        n = len(_clean(self.tgt_edit.toPlainText()))
        self.counter.setText(f"{n} зн. · оригинал {len(e.source_text)}")

    def _update_live(self):
        """Проверка введённого текста без изменения записи."""
        e = self._entry
        if e is None:
            return
        self._update_counter()
        text = _clean(self.tgt_edit.toPlainText())
        if not text.strip():
            errs, warns = [], []
        else:
            errs, warns = compare_placeholders(e.source_text, text)
            warns = warns + qa_check(e.source_text, text, self._target_lang)
        self.err_label.setText("\n".join("✖ " + x for x in errs[:5]))
        self.err_label.setVisible(bool(errs))
        self.warn_label.setText("\n".join("⚠ " + x for x in warns[:5]))
        self.warn_label.setVisible(bool(warns))

    def _current(self):
        return self._entry.handle if self._entry else "", _clean(self.tgt_edit.toPlainText())

    def _apply(self):
        handle, text = self._current()
        if handle:
            self.apply_requested.emit(handle, text)

    def _approve(self):
        handle, text = self._current()
        if handle:
            self.approve_requested.emit(handle, text)

    def _translate(self):
        if self._entry:
            self.translate_requested.emit(self._entry.handle)

    def _use_suggestion(self):
        if self._suggestion:
            self.tgt_edit.setPlainText(self._suggestion)
            self.banner.setVisible(False)
            self.tgt_edit.setFocus()

    def _comment_done(self):
        if self._entry and self.comment.text() != self._entry.comment:
            self.comment_edited.emit(self._entry.handle, self.comment.text())

    def set_busy(self, busy: bool):
        """Во время пакетного перевода нельзя запускать перевод строки отдельно."""
        self.translate_btn.setEnabled(not busy)
