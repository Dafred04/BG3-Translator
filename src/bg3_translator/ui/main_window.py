"""Main application window: animated sidebar navigation + pages + toasts."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, QSize, Qt, QThread, QTimer
from PySide6.QtGui import QFontMetrics, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QVBoxLayout, QWidget,
)

from . import theme
from .theme import DARK, LIGHT, build_qpalette, build_stylesheet
from .state import api_key_for, get_app_state
from .widgets import Chip, FadeStack, GlowProgressBar, Toast, repolish
from ..config import get_settings

_PROVIDER_NAMES = {
    "gemini": "Gemini",
    "openai_compatible": "OpenAI-совместимый",
    "google_free": "Google Переводчик",
}


class MainWindow(QMainWindow):
    """Shell window: left sidebar nav + animated stacked pages + toast host."""

    MAX_TOASTS = 4

    def __init__(self):
        super().__init__()
        self.setWindowTitle("BG3 Mod Translator")
        self.setMinimumSize(QSize(1100, 720))
        self.resize(1280, 800)

        self.settings = get_settings()
        self.state = get_app_state()
        self._toasts: list[Toast] = []
        self._apply_theme(self.settings.theme)

        root = QWidget()
        root.setObjectName("Root")
        root_lay = QHBoxLayout(root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)
        self.setCentralWidget(root)

        # ---------------- Sidebar ----------------
        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(232)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(14, 22, 14, 16)
        side.setSpacing(4)

        brand = QHBoxLayout()
        brand.setSpacing(12)
        badge = QLabel("B")
        badge.setObjectName("LogoBadge")
        badge.setFixedSize(40, 40)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.addWidget(badge)
        names = QVBoxLayout()
        names.setSpacing(0)
        logo = QLabel("BG3 Translator")
        logo.setObjectName("CardTitle")
        subtitle = QLabel("v2.0 · Локализация модов")
        subtitle.setObjectName("Subtitle")
        names.addWidget(logo)
        names.addWidget(subtitle)
        brand.addLayout(names, 1)
        side.addLayout(brand)
        side.addSpacing(26)

        # Подвижная подсветка активного пункта (создаётся ДО кнопок -> лежит под ними)
        self._indicator = QFrame(self.sidebar)
        self._indicator.setObjectName("NavIndicator")
        self._bar = QFrame(self.sidebar)
        self._bar.setObjectName("NavBar")
        self._ind_anim = QPropertyAnimation(self._indicator, b"geometry", self)
        self._ind_anim.setDuration(340)
        self._ind_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._bar_anim = QPropertyAnimation(self._bar, b"geometry", self)
        self._bar_anim.setDuration(460)
        self._bar_anim.setEasingCurve(QEasingCurve.Type.OutBack)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self._nav_buttons: list[QPushButton] = []

        from .pages.dashboard import DashboardPage
        from .pages.editor import EditorPage
        from .pages.dictionary_page import DictionaryPage
        from .pages.settings_page import SettingsPage

        self.stack = FadeStack()
        self.pages: dict[str, QWidget] = {}

        page_defs = [
            ("dashboard", "🏠   Главная", DashboardPage(self)),
            ("editor", "📝   Перевод", EditorPage(self)),
            ("dictionary", "📚   Словарь", DictionaryPage(self)),
            ("settings", "⚙   Настройки", SettingsPage(self)),
        ]
        for i, (key, label, widget) in enumerate(page_defs):
            btn = QPushButton(label)
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(42)
            btn.setToolTip(f"Ctrl+{i + 1}")
            self.nav_group.addButton(btn, i)
            self._nav_buttons.append(btn)
            side.addWidget(btn)
            self.pages[key] = widget
            self.stack.addWidget(widget)
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda i=i: self._go(i))

        self.nav_group.idClicked.connect(self._go)
        side.addStretch(1)

        # Карточка текущего проекта (внизу сайдбара)
        self._proj_card = QFrame()
        self._proj_card.setObjectName("SideCard")
        pc = QVBoxLayout(self._proj_card)
        pc.setContentsMargins(12, 10, 12, 12)
        pc.setSpacing(6)
        cap = QLabel("Текущий мод")
        cap.setObjectName("Subtitle")
        self._proj_name = QLabel("Не открыт")
        self._proj_name.setObjectName("CardTitle")
        self._proj_bar = GlowProgressBar(height=6)
        self._proj_pct = QLabel("Откройте мод на главной")
        self._proj_pct.setObjectName("Subtitle")
        pc.addWidget(cap)
        pc.addWidget(self._proj_name)
        pc.addWidget(self._proj_bar)
        pc.addWidget(self._proj_pct)
        side.addWidget(self._proj_card)

        root_lay.addWidget(self.sidebar)
        root_lay.addWidget(self.stack, 1)

        # ---------------- Status bar ----------------
        self.statusBar().setObjectName("StatusBar")
        self.statusBar().setSizeGripEnabled(False)
        self._status_label = QLabel("Готово")
        self._status_label.setObjectName("Subtitle")
        self.statusBar().addWidget(self._status_label)
        self._provider_chip = Chip("")
        self.statusBar().addPermanentWidget(self._provider_chip)
        self._refresh_provider_chip()

        self._nav_buttons[0].setChecked(True)
        self._cur_idx = 0
        self.state.project_changed.connect(self._refresh_project_card)
        self.state.project_changed.connect(self._update_title)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save_now)
        self.state.entry_edited.connect(lambda _h: self._refresh_project_card())
        self._refresh_project_card(animate=False)
        QTimer.singleShot(0, lambda: self._move_indicator(False))

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def _go(self, idx: int):
        self._nav_buttons[idx].setChecked(True)
        self._cur_idx = idx
        self.stack.set_index_animated(idx)
        self._move_indicator(True)
        self._refresh_project_card()

    def navigate(self, page_key: str):
        self._go(list(self.pages.keys()).index(page_key))

    def _move_indicator(self, animate: bool = True):
        btn = self._nav_buttons[self._cur_idx] if self._nav_buttons else None
        if btn is None or btn.width() <= 0:
            return
        g = btn.geometry()
        bar = QRect(g.x() - 6, g.y() + 11, 3, g.height() - 22)
        if animate and self._indicator.isVisible():
            for anim, rect, widget in ((self._ind_anim, g, self._indicator),
                                       (self._bar_anim, bar, self._bar)):
                anim.stop()
                anim.setStartValue(widget.geometry())
                anim.setEndValue(rect)
                anim.start()
        else:
            self._indicator.setGeometry(g)
            self._bar.setGeometry(bar)
        self._indicator.show()
        self._bar.show()
        self._indicator.lower()
        self._bar.raise_()

    # ------------------------------------------------------------------
    # Status / project card
    # ------------------------------------------------------------------
    def set_status(self, text: str):
        """Update the bottom status bar text."""
        self._status_label.setText(text)

    def _refresh_project_card(self, *_args, animate: bool = True):
        s = self.state.stats()
        project = self.state.project
        if not project:
            self._proj_name.setText("Не открыт")
            self._proj_pct.setText("Откройте мод на главной")
            self._proj_bar.setMaximum(100)
            self._proj_bar.setValue(0)
            return
        fm = QFontMetrics(self._proj_name.font())
        name = project.metadata.name or "Без названия"
        self._proj_name.setText(fm.elidedText(name, Qt.TextElideMode.ElideMiddle, 180))
        self._proj_name.setToolTip(name)
        self._proj_bar.setMaximum(100)
        self._proj_bar.setValue(s["percent"])
        self._proj_pct.setText(f"{s['percent']}% · {s['translated']} из {s['total']} строк")

    def _update_title(self):
        p = self.state.project
        self.setWindowTitle(f"{p.metadata.name} — BG3 Mod Translator" if p else "BG3 Mod Translator")

    def save_now(self):
        """Ctrl+S: сохранить проект сразу."""
        if self.state.project is None:
            self.toast("Нет открытого проекта.", "info")
            return
        path = self.state.save_project()
        if path:
            self.toast(f"Проект сохранён: {path.name}", "success", 2500)
        else:
            self.toast("Не удалось сохранить проект. Подробности — в журнале.", "error", 5000)

    def closeEvent(self, event):
        """Остановить перевод и сохранить проект, чтобы ничего не потерять."""
        try:
            engine = self.state.engine
            if engine.is_running():
                engine.cancel()
                for _ in range(50):                      # дождаться воркера до 2.5 с
                    if not engine.is_running():
                        break
                    QApplication.processEvents()
                    QThread.msleep(50)
            self.state.save_project()
        except Exception:
            pass
        super().closeEvent(event)

    def _refresh_provider_chip(self):
        try:
            s = get_settings()
            name = _PROVIDER_NAMES.get(s.default_provider, s.default_provider)
            cfg = s.providers.get(s.default_provider)
            local = bool(cfg and cfg.base_url) and s.default_provider == "openai_compatible"
            ready = (s.default_provider == "google_free" or local
                     or bool(api_key_for(s, s.default_provider)))
            self._provider_chip.setText(f"●  {name}" if ready else f"●  {name}: нужен ключ API")
            self._provider_chip.set_tone("success" if ready else "warning")
        except Exception:
            self._provider_chip.setText("●  Провайдер не настроен")
            self._provider_chip.set_tone("warning")

    # ------------------------------------------------------------------
    # Toasts (стек в правом нижнем углу)
    # ------------------------------------------------------------------
    def toast(self, message: str, kind: str = "info", timeout_ms: int = 3500):
        """Show a floating toast notification."""
        while len(self._toasts) >= self.MAX_TOASTS:
            self._toasts.pop(0).dismiss()
        t = Toast(message, kind, timeout_ms, parent=self)
        t.CLOSED.connect(lambda t=t: self._toast_closed(t))
        self._toasts.append(t)
        self._layout_toasts(new=t)
        t.show()
        t.raise_()
        t.present()

    def _toast_closed(self, t: Toast):
        if t in self._toasts:
            self._toasts.remove(t)
        self._layout_toasts()

    def _layout_toasts(self, new: Toast | None = None, animate: bool = True):
        x = self.width() - Toast.WIDTH - 24
        y = self.height() - self.statusBar().height() - 20
        for t in reversed(self._toasts):
            y -= t.height()
            if t is new:
                t.move(self.width() + 10, y)
            t.slide_to(QPoint(x, y), animate)
            y -= 10

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_toasts(animate=False)
        QTimer.singleShot(0, lambda: self._move_indicator(False))

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, lambda: self._move_indicator(False))

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------
    def _apply_theme(self, theme_name: str):
        pal = DARK
        if theme_name == "light":
            pal = LIGHT
        elif theme_name == "system":
            try:
                scheme = QApplication.instance().styleHints().colorScheme()
                pal = LIGHT if scheme == Qt.ColorScheme.Light else DARK
            except Exception:
                pal = DARK
        app = QApplication.instance()
        if app:
            app.setPalette(build_qpalette(pal))
            app.setStyleSheet(build_stylesheet(pal))
        if hasattr(self, "_provider_chip"):
            self._refresh_provider_chip()
            self.update()
