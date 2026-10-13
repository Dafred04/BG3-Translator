"""Reusable UI components: cards, buttons, toast notifications, stat tiles."""

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget, QGraphicsDropShadowEffect,
)


class Card(QFrame):
    """Rounded panel container (#Card)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")


class StatTile(Card):
    """Single statistic: big value + label."""

    def __init__(self, label: str, value: str = "0", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("StatValue")
        self.text_label = QLabel(label)
        self.text_label.setObjectName("StatLabel")
        lay.addWidget(self.value_label)
        lay.addWidget(self.text_label)

    def set_value(self, value: str):
        self.value_label.setText(value)


class PrimaryButton(QPushButton):
    """Accent-filled primary action button."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("Primary")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(38)


class DangerButton(QPushButton):
    """Red destructive-action button."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("Danger")
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class Toast(QFrame):
    """Floating notification, auto-dismisses."""

    CLOSED = Signal()

    def __init__(self, message: str, kind: str = "info", timeout_ms: int = 3500, parent=None):
        super().__init__(parent)
        self.setObjectName("Toast")
        if kind == "success":
            self.setProperty("class", "ToastSuccess")
            self.setObjectName("ToastSuccess")
        elif kind == "error":
            self.setObjectName("ToastError")
        elif kind == "warning":
            self.setObjectName("ToastWarning")

        icons = {"info": "ℹ", "success": "✔", "error": "✖", "warning": "⚠"}
        lay = QHBoxLayout(self)
        icon = QLabel(icons.get(kind, "ℹ"))
        icon.setFont(QFont("Segoe UI Emoji", 14))
        msg = QLabel(message)
        msg.setWordWrap(True)
        lay.addWidget(icon)
        lay.addWidget(msg, 1)

        self.setFixedWidth(380)
        self.setMinimumHeight(48)

        shadow = QGraphicsDropShadowEffect(blurRadius=24, xOffset=0, yOffset=6)
        shadow.setColor(self.palette().color(self.palette().ColorRole.Shadow))
        self.setGraphicsEffect(shadow)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._close)
        self.timer.start(timeout_ms)

    def _close(self):
        self.CLOSED.emit()
        self.deleteLater()

    def set_timeout(self, ms: int):
        self.timer.start(ms)