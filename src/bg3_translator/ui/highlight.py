"""Подсветка плейсхолдеров (теги, {0}, [1], &entity;) в полях ввода."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

from ..core.validation import find_spans
from . import theme


class PlaceholderHighlighter(QSyntaxHighlighter):
    """Выделяет служебную разметку цветом акцента, чтобы её не трогали при правке."""

    def __init__(self, document):
        super().__init__(document)
        self._fmt = QTextCharFormat()
        self.refresh_colors()

    def refresh_colors(self):
        pal = theme.current()
        self._fmt = QTextCharFormat()
        self._fmt.setForeground(QColor(pal.accent_hover))
        self._fmt.setBackground(theme.qcolor(pal.accent, 38))
        self._fmt.setFontWeight(QFont.Weight.DemiBold)
        self.rehighlight()

    def highlightBlock(self, text: str):
        for start, end in find_spans(text):
            self.setFormat(start, end - start, self._fmt)
