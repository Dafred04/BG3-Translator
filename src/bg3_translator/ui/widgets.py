"""Reusable UI components: cards, glowing buttons, animated progress,
ring chart, toasts, fade-stack, hero card, drop zone, empty state."""

from __future__ import annotations

import math
import random
import re
from pathlib import Path

from PySide6.QtCore import (
    QAbstractAnimation, QEasingCurve, QParallelAnimationGroup, QPoint, QPointF, QPropertyAnimation,
    QRectF, Qt, QTimer, QVariantAnimation, Property, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QConicalGradient, QFont, QLinearGradient, QPainter,
    QPainterPath, QPen, QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QHBoxLayout,
    QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from . import theme


def repolish(w: QWidget) -> None:
    """Применить QSS заново после смены dynamic-property."""
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def _lerp_color(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
        int(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


# ======================================================================
# Basic containers
# ======================================================================
class Card(QFrame):
    """Rounded panel container (#Card)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")


class Chip(QLabel):
    """Small rounded pill label. tone: accent | success | warning | danger | ''."""

    def __init__(self, text: str = "", tone: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("Chip")
        self.set_tone(tone)

    def set_tone(self, tone: str):
        if self.property("tone") != tone:
            self.setProperty("tone", tone)
            repolish(self)


class StatTile(Card):
    """Одна метрика: крупное число (с анимацией «набегания») + подпись."""

    def __init__(self, label: str, value: str = "0", tone: str = "accent", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(2)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("StatValue")
        self.value_label.setProperty("tone", tone)
        self.text_label = QLabel(label)
        self.text_label.setObjectName("StatLabel")
        lay.addWidget(self.value_label)
        lay.addWidget(self.text_label)

        self._current = 0
        self._suffix = ""
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(750)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._tick)

    def _tick(self, v):
        self._current = int(v)
        self.value_label.setText(f"{self._current}{self._suffix}")

    def set_value(self, value: str, animate: bool = True):
        m = re.match(r"^(\d+)(.*)$", value.strip())
        self._anim.stop()
        if not m:
            self.value_label.setText(value)
            return
        target, self._suffix = int(m.group(1)), m.group(2)
        if not animate or target == self._current:
            self._current = target
            self.value_label.setText(value)
            return
        self._anim.setStartValue(self._current)
        self._anim.setEndValue(target)
        self._anim.start()


# ======================================================================
# Buttons (with animated glow on hover)
# ======================================================================
class PrimaryButton(QPushButton):
    """Accent-filled button, красное свечение при наведении."""

    GLOW_IDLE, GLOW_HOVER = 6, 30

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("Primary")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(38)

        self._glow = QGraphicsDropShadowEffect(self)
        self._glow.setOffset(0, 4)
        self._glow.setColor(theme.qcolor(theme.current().accent, 150))
        self._glow.setBlurRadius(self.GLOW_IDLE)
        self.setGraphicsEffect(self._glow)

        self._glow_anim = QVariantAnimation(self)
        self._glow_anim.setDuration(240)
        self._glow_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._glow_anim.valueChanged.connect(lambda v: self._glow.setBlurRadius(float(v)))

    def _glow_to(self, target: float):
        self._glow_anim.stop()
        self._glow_anim.setStartValue(self._glow.blurRadius())
        self._glow_anim.setEndValue(target)
        self._glow_anim.start()

    def enterEvent(self, e):
        if self.isEnabled():
            self._glow_to(self.GLOW_HOVER)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._glow_to(self.GLOW_IDLE)
        super().leaveEvent(e)


class GhostButton(QPushButton):
    """Прозрачная кнопка с контуром — для второстепенных действий."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("Ghost")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(38)


class DangerButton(QPushButton):
    """Красная контурная кнопка (остановить / удалить)."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("Danger")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(38)


# ======================================================================
# Progress
# ======================================================================
class GlowProgressBar(QWidget):
    """Плавный прогресс-бар с бегущим бликом.

    API совместим с QProgressBar: setMaximum / setValue / value.
    setMaximum(0) включает «бесконечный» режим (идёт работа, но объём неизвестен).
    """

    def __init__(self, parent=None, height: int = 8):
        super().__init__(parent)
        self._bar_h = height
        self.setFixedHeight(height + 6)
        self._max = 100
        self._value = 0
        self._shown = 0.0
        self._phase = 0.0

        self._anim = QPropertyAnimation(self, b"shown", self)
        self._anim.setDuration(480)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._shimmer = QVariantAnimation(self)
        self._shimmer.setStartValue(0.0)
        self._shimmer.setEndValue(1.0)
        self._shimmer.setDuration(1500)
        self._shimmer.setLoopCount(-1)
        self._shimmer.valueChanged.connect(self._on_phase)

    # --- Qt property for animation
    def _get_shown(self) -> float:
        return self._shown

    def _set_shown(self, v: float):
        self._shown = v
        self.update()

    shown = Property(float, _get_shown, _set_shown)

    def _on_phase(self, v):
        self._phase = float(v)
        self.update()

    # --- QProgressBar-like API
    def setMaximum(self, m: int):
        self._max = max(int(m), 0)
        self._retarget()

    def setRange(self, lo: int, hi: int):
        self.setMaximum(hi)

    def setValue(self, v: int):
        self._value = int(v)
        self._retarget()

    def value(self) -> int:
        return self._value

    def _retarget(self):
        if self._max <= 0:
            self.update()
            return
        target = max(0.0, min(1.0, self._value / self._max))
        self._anim.stop()
        self._anim.setStartValue(self._shown)
        self._anim.setEndValue(target)
        self._anim.start()

    def showEvent(self, e):
        self._shimmer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._shimmer.stop()
        super().hideEvent(e)

    def paintEvent(self, _e):
        pal = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self._bar_h
        y = (self.height() - h) / 2
        w = self.width()
        radius = h / 2
        track = QRectF(0, y, w, h)
        p.setBrush(QColor(pal.surface_alt))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(track, radius, radius)

        accent = QColor(pal.accent)
        if self._max <= 0:                          # indeterminate
            seg = w * 0.32
            x = -seg + (w + seg) * self._phase
            fill = QRectF(max(0.0, x), y, min(seg, w - max(0.0, x), x + seg), h)
            if fill.width() > 0:
                g = QLinearGradient(fill.left(), 0, fill.right(), 0)
                g.setColorAt(0, QColor(accent.red(), accent.green(), accent.blue(), 0))
                g.setColorAt(0.5, accent)
                g.setColorAt(1, QColor(accent.red(), accent.green(), accent.blue(), 0))
                p.setBrush(g)
                p.drawRoundedRect(fill, radius, radius)
            return

        fw = max(0.0, w * self._shown)
        if fw <= 0.5:
            return
        fill = QRectF(0, y, max(fw, h), h)
        glow = QColor(accent)
        glow.setAlpha(55)
        p.setBrush(glow)
        p.drawRoundedRect(fill.adjusted(-1, -3, 1, 3), radius + 2, radius + 2)
        g = QLinearGradient(0, 0, fill.right(), 0)
        g.setColorAt(0, QColor(pal.accent_pressed))
        g.setColorAt(1, QColor(pal.accent_hover))
        p.setBrush(g)
        p.drawRoundedRect(fill, radius, radius)

        # бегущий блик, обрезанный по заливке
        p.save()
        clip = QPainterPath()
        clip.addRoundedRect(fill, radius, radius)
        p.setClipPath(clip)
        band = fill.width() * 0.35 + 24
        bx = -band + (fill.width() + band) * self._phase
        sh = QLinearGradient(bx, 0, bx + band, 0)
        sh.setColorAt(0, QColor(255, 255, 255, 0))
        sh.setColorAt(0.5, QColor(255, 255, 255, 90))
        sh.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(sh)
        p.drawRect(QRectF(bx, y, band, h))
        p.restore()


class RingProgress(QWidget):
    """Круговой индикатор 0..100% с плавной анимацией и свечением."""

    def __init__(self, size: int = 150, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._value = 0.0
        self._anim = QPropertyAnimation(self, b"ringValue", self)
        self._anim.setDuration(900)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _get(self) -> float:
        return self._value

    def _set(self, v: float):
        self._value = v
        self.update()

    ringValue = Property(float, _get, _set)

    def set_value(self, v: float):
        self._anim.stop()
        self._anim.setStartValue(self._value)
        self._anim.setEndValue(float(max(0, min(100, v))))
        self._anim.start()

    def paintEvent(self, _e):
        pal = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        thick = 12
        rect = QRectF(self.rect()).adjusted(thick, thick, -thick, -thick)

        pen = QPen(QColor(pal.surface_alt), thick)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, 0, 360 * 16)

        span = int(-self._value * 3.6 * 16)
        if abs(span) > 0:
            glow = QColor(pal.accent)
            glow.setAlpha(45)
            gp = QPen(glow, thick + 8)
            gp.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(gp)
            p.drawArc(rect, 90 * 16, span)

            grad = QConicalGradient(rect.center(), 90)
            grad.setColorAt(0.0, QColor(pal.accent_hover))
            grad.setColorAt(1.0, QColor(pal.accent_pressed))
            ap = QPen(QBrush(grad), thick)
            ap.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(ap)
            p.drawArc(rect, 90 * 16, span)

        p.setPen(QColor(pal.text))
        f = QFont(self.font())
        f.setPixelSize(int(self.height() * 0.2))
        f.setWeight(QFont.Weight.ExtraBold)
        p.setFont(f)
        p.drawText(self.rect().adjusted(0, -8, 0, -8), Qt.AlignmentFlag.AlignCenter,
                   f"{int(round(self._value))}%")
        f2 = QFont(self.font())
        f2.setPixelSize(11)
        p.setFont(f2)
        p.setPen(QColor(pal.text_muted))
        p.drawText(self.rect().adjusted(0, int(self.height() * 0.26), 0, 0),
                   Qt.AlignmentFlag.AlignCenter, "переведено")


# ======================================================================
# Toast
# ======================================================================
class Toast(QFrame):
    """Всплывающее уведомление: выезжает справа, внизу — полоска обратного отсчёта.

    Позиционированием управляет MainWindow (см. MainWindow.toast).
    """

    CLOSED = Signal()
    WIDTH = 380
    ICONS = {"info": "i", "success": "✔", "error": "✖", "warning": "!"}

    def __init__(self, message: str, kind: str = "info", timeout_ms: int = 3500, parent=None):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.kind = kind if kind in self.ICONS else "info"
        self.setProperty("kind", self.kind)
        self._closing = False
        self._progress = 1.0

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 13, 12, 16)
        lay.setSpacing(12)
        icon = QLabel(self.ICONS[self.kind])
        icon.setObjectName("ToastIcon")
        icon.setProperty("kind", self.kind)
        icon.setFixedWidth(20)
        icon.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        msg = QLabel(message)
        msg.setWordWrap(True)
        close = QPushButton("✕")
        close.setObjectName("IconButton")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setFixedSize(24, 24)
        close.clicked.connect(self.dismiss)
        lay.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(msg, 1)
        lay.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)

        self.setFixedWidth(self.WIDTH)
        lay.activate()
        h = lay.heightForWidth(self.WIDTH)
        if h <= 0:
            h = lay.sizeHint().height()
        self.setFixedHeight(max(56, h))

        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(0.0)
        self.setGraphicsEffect(self._fx)

        self._move_anim = QPropertyAnimation(self, b"pos", self)
        self._move_anim.setDuration(320)
        self._move_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._fade = QPropertyAnimation(self._fx, b"opacity", self)

        self._life = QVariantAnimation(self)
        self._life.setStartValue(1.0)
        self._life.setEndValue(0.0)
        self._life.setDuration(max(timeout_ms, 500))
        self._life.valueChanged.connect(self._on_life)
        self._life.finished.connect(self.dismiss)

    def _on_life(self, v):
        self._progress = float(v)
        self.update()

    def slide_to(self, pos: QPoint, animate: bool = True):
        self._move_anim.stop()
        if not animate or self._closing:
            self.move(pos)
            return
        self._move_anim.setStartValue(self.pos())
        self._move_anim.setEndValue(pos)
        self._move_anim.start()

    def present(self):
        """Fade-in + запуск таймера жизни."""
        self._fade.stop()
        self._fade.setDuration(260)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._life.start()

    def dismiss(self):
        if self._closing:
            return
        self._closing = True
        self._life.stop()
        self._move_anim.stop()
        self._fade.stop()
        self._fade.setDuration(220)
        self._fade.setStartValue(self._fx.opacity())
        self._fade.setEndValue(0.0)
        self._move_anim.setDuration(240)
        self._move_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._move_anim.setStartValue(self.pos())
        self._move_anim.setEndValue(self.pos() + QPoint(40, 0))
        self._fade.finished.connect(self._finish_close)
        self._fade.start()
        self._move_anim.start()

    def _finish_close(self):
        self.CLOSED.emit()
        self.hide()
        self.deleteLater()

    def set_timeout(self, ms: int):
        self._life.stop()
        self._life.setDuration(max(ms, 500))
        self._life.start()

    def enterEvent(self, e):          # пауза при наведении
        if not self._closing and self._life.state() == QAbstractAnimation.State.Running:
            self._life.pause()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if not self._closing and self._life.state() == QAbstractAnimation.State.Paused:
            self._life.resume()
        super().leaveEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        pal = theme.current()
        color = {"success": pal.success, "error": pal.danger, "warning": pal.warning}.get(
            self.kind, pal.info)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        w = (self.width() - 32) * self._progress
        if w > 0:
            p.drawRoundedRect(QRectF(16, self.height() - 7, w, 2.5), 1.2, 1.2)


# ======================================================================
# Page transitions & collapsing
# ======================================================================
class FadeStack(QStackedWidget):
    """QStackedWidget с плавным появлением страницы (fade + лёгкий подъём)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._group: QParallelAnimationGroup | None = None

    def set_index_animated(self, idx: int):
        if idx == self.currentIndex():
            return
        if self._group is not None:
            self._group.stop()
            self._group = None
        for i in range(self.count()):
            self.widget(i).setGraphicsEffect(None)
        self.setCurrentIndex(idx)
        w = self.currentWidget()
        if w is None:
            return
        fx = QGraphicsOpacityEffect(w)
        fx.setOpacity(0.0)
        w.setGraphicsEffect(fx)

        fade = QPropertyAnimation(fx, b"opacity")
        fade.setDuration(260)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        base = w.pos()
        rise = QPropertyAnimation(w, b"pos")
        rise.setDuration(320)
        rise.setStartValue(base + QPoint(0, 18))
        rise.setEndValue(base)
        rise.setEasingCurve(QEasingCurve.Type.OutCubic)

        grp = QParallelAnimationGroup(self)
        grp.addAnimation(fade)
        grp.addAnimation(rise)

        def _done():
            w.setGraphicsEffect(None)
            w.move(base)
        grp.finished.connect(_done)
        self._group = grp
        grp.start()


class Collapsible(QWidget):
    """Контейнер, плавно разворачивающийся / сворачивающийся по высоте."""

    def __init__(self, inner: QWidget, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(inner)
        self._inner = inner
        self._open = False
        self.setMaximumHeight(0)
        self.setVisible(False)
        self._anim = QPropertyAnimation(self, b"maximumHeight", self)
        self._anim.setDuration(360)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim.finished.connect(self._on_done)

    def is_open(self) -> bool:
        return self._open

    def expand(self):
        if self._open:
            return
        self._open = True
        self.setVisible(True)
        self._anim.stop()
        self._anim.setStartValue(self.maximumHeight() if self.maximumHeight() < 10000 else 0)
        self._anim.setEndValue(max(self._inner.sizeHint().height(), 40))
        self._anim.start()

    def collapse(self):
        if not self._open:
            return
        self._open = False
        self._anim.stop()
        self._anim.setStartValue(self.height())
        self._anim.setEndValue(0)
        self._anim.start()

    def _on_done(self):
        if self._open:
            self.setMaximumHeight(16777215)
        else:
            self.setVisible(False)


# ======================================================================
# Empty state
# ======================================================================
class EmptyState(QWidget):
    """Пустой экран: парящая иконка, заголовок, пояснение и кнопки действий."""

    def __init__(self, icon: str, title: str, text: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(6)

        self.icon = QLabel(icon)
        self.icon.setObjectName("EmptyIcon")
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("Title")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text_label = QLabel(text)
        self.text_label.setObjectName("Subtitle")
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text_label.setWordWrap(True)
        self.text_label.setMaximumWidth(460)
        self.actions = QHBoxLayout()
        self.actions.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lay.addStretch(1)
        lay.addWidget(self.icon)
        lay.addWidget(self.title_label)
        lay.addWidget(self.text_label, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(10)
        lay.addLayout(self.actions)
        lay.addStretch(1)

        self._bob = QVariantAnimation(self)
        self._bob.setStartValue(0.0)
        self._bob.setEndValue(1.0)
        self._bob.setDuration(2600)
        self._bob.setLoopCount(-1)
        self._bob.valueChanged.connect(self._on_bob)

    def _on_bob(self, v):
        off = int(round(math.sin(float(v) * 2 * math.pi) * 6)) + 8
        self.icon.setContentsMargins(0, off, 0, 16 - off)

    def set_text(self, title: str, text: str):
        self.title_label.setText(title)
        self.text_label.setText(text)

    def add_action(self, button: QPushButton):
        self.actions.addWidget(button)

    def showEvent(self, e):
        self._bob.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._bob.stop()
        super().hideEvent(e)


# ======================================================================
# Hero card (animated embers) and Drop zone
# ======================================================================
class HeroCard(QFrame):
    """Главная «вау»-карточка: тёмно-красный градиент, дрейфующее свечение
    и поднимающиеся вверх искры. Рисуется вручную, ~30 fps, только пока видна."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HeroCard")
        rnd = random.Random(7)
        # x, стартовая высота, радиус, скорость, фаза
        self._embers = [
            (rnd.random(), rnd.random(), rnd.uniform(1.2, 3.4), rnd.uniform(0.035, 0.09),
             rnd.uniform(0, 6.28))
            for _ in range(30)
        ]
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        self._t += 0.033
        self.update()

    def showEvent(self, e):
        self._timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def paintEvent(self, _e):
        pal = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        t = self._t

        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 18, 18)
        p.setClipPath(path)

        base = QLinearGradient(0, 0, w, h)
        if pal.is_dark:
            base.setColorAt(0, QColor("#2b0d13"))
            base.setColorAt(0.55, QColor("#170b10"))
            base.setColorAt(1, QColor("#0e0a0d"))
        else:
            base.setColorAt(0, QColor(pal.accent_pressed))
            base.setColorAt(1, QColor(pal.accent))
        p.fillRect(self.rect(), base)

        accent = QColor(pal.accent)
        for cx, cy, rad, a in (
            (0.80 + 0.05 * math.sin(t * 0.6), 0.30 + 0.12 * math.cos(t * 0.45), 0.55, 120),
            (0.15 + 0.06 * math.cos(t * 0.5), 1.05 + 0.05 * math.sin(t * 0.7), 0.45, 70),
        ):
            g = QRadialGradient(QPointF(w * cx, h * cy), w * rad)
            g.setColorAt(0, QColor(accent.red(), accent.green(), accent.blue(), a))
            g.setColorAt(1, QColor(accent.red(), accent.green(), accent.blue(), 0))
            p.fillRect(self.rect(), g)

        p.setPen(Qt.PenStyle.NoPen)
        for x0, y0, r, speed, phase in self._embers:
            frac = (y0 + speed * t) % 1.0               # 0 = низ, 1 = верх
            x = w * x0 + math.sin(t * 0.8 + phase) * 14
            y = h * (1.0 - frac)
            alpha = int(200 * math.sin(math.pi * frac) ** 1.4)
            p.setBrush(QColor(255, 150 + int(60 * frac), 100, max(0, alpha)))
            p.drawEllipse(QPointF(x, y), r, r)

        p.setClipping(False)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 110), 1))
        p.drawPath(path)


class DropZone(QFrame):
    """Зона перетаскивания мода. Бегущий пунктир и подсветка при наведении."""

    dropped = Signal(str, bool)     # path, is_folder
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(300, 150)
        self._glow = 0.0
        self._dash = 0.0
        self._hover = False
        self._drag = False

        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(4)
        icon = QLabel("⤓")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 34px; font-weight: 800; color: #ffffff;")
        title = QLabel("Перетащите мод сюда")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #ffffff;")
        sub = QLabel(".pak · .zip · .xml или папка\nили нажмите, чтобы выбрать файл")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color: rgba(255,255,255,0.65);")
        for w in (icon, title, sub):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            lay.addWidget(w)

        self._glow_anim = QVariantAnimation(self)
        self._glow_anim.setDuration(260)
        self._glow_anim.valueChanged.connect(self._on_glow)
        self._march = QVariantAnimation(self)
        self._march.setStartValue(0.0)
        self._march.setEndValue(12.0)
        self._march.setDuration(700)
        self._march.setLoopCount(-1)
        self._march.valueChanged.connect(self._on_march)

    def _on_glow(self, v):
        self._glow = float(v)
        self.update()

    def _on_march(self, v):
        self._dash = float(v)
        self.update()

    def _set_active(self):
        active = self._hover or self._drag
        self._glow_anim.stop()
        self._glow_anim.setStartValue(self._glow)
        self._glow_anim.setEndValue(1.0 if active else 0.0)
        self._glow_anim.start()
        if active:
            self._march.start()
        else:
            self._march.stop()

    def enterEvent(self, e):
        self._hover = True
        self._set_active()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self._set_active()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag = True
            self._set_active()

    def dragLeaveEvent(self, e):
        self._drag = False
        self._set_active()

    def dropEvent(self, e):
        self._drag = False
        self._set_active()
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path:
                self.dropped.emit(path, Path(path).is_dir())
                e.acceptProposedAction()

    def paintEvent(self, _e):
        pal = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        fill = QColor(255, 255, 255, int(10 + 22 * self._glow))
        if self._glow > 0:
            fill = _lerp_color(fill, QColor(pal.accent), 0.0)
            fill.setAlpha(int(14 + 50 * self._glow))
        p.setBrush(fill)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(r, 14, 14)

        edge = _lerp_color(QColor(255, 255, 255, 80), QColor(pal.accent_hover), self._glow)
        pen = QPen(edge, 2)
        pen.setDashPattern([4.0, 4.0])
        pen.setDashOffset(-self._dash)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 14, 14)
