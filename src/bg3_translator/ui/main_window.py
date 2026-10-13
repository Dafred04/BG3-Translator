"""Main application window with sidebar navigation."""

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget, QFrame,
)

from .theme import DARK, LIGHT, build_stylesheet
from .widgets import Toast
from ..config import get_settings


class MainWindow(QMainWindow):
    """Shell window: left sidebar nav + stacked pages + toast host."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("BG3 Mod Translator")
        self.setMinimumSize(QSize(1100, 720))
        self.resize(1280, 800)

        self.settings = get_settings()
        self._apply_theme(self.settings.theme)

        root = QWidget()
        root_lay = QHBoxLayout(root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)
        self.setCentralWidget(root)

        # --- Sidebar ---
        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(220)
        side_lay = QVBoxLayout(self.sidebar)
        side_lay.setContentsMargins(12, 20, 12, 20)
        side_lay.setSpacing(4)

        logo = QLabel("BG3 Mod Translator")
        logo.setObjectName("Title")
        logo.setWordWrap(True)
        side_lay.addWidget(logo)
        subtitle = QLabel("v2.0 · Mod localization")
        subtitle.setObjectName("Subtitle")
        side_lay.addWidget(subtitle)
        side_lay.addSpacing(24)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self._nav_buttons: list[QPushButton] = []

        # Pages registered here: (key, label, widget_factory)
        from .pages.dashboard import DashboardPage
        from .pages.editor import EditorPage
        from .pages.dictionary_page import DictionaryPage
        from .pages.settings_page import SettingsPage

        self.stack = QStackedWidget()
        self.pages: dict[str, QWidget] = {}

        page_defs = [
            ("dashboard", "🏠  Dashboard", DashboardPage(self)),
            ("editor", "📝  Translate", EditorPage(self)),
            ("dictionary", "📚  Dictionary", DictionaryPage(self)),
            ("settings", "⚙  Settings", SettingsPage(self)),
        ]
        for key, label, widget in page_defs:
            btn = QPushButton(label)
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(40)
            self.nav_group.addButton(btn)
            self._nav_buttons.append(btn)
            side_lay.addWidget(btn)
            self.pages[key] = widget
            self.stack.addWidget(widget)

        self.nav_group.idClicked.connect(self._on_nav)
        side_lay.addStretch(1)

        root_lay.addWidget(self.sidebar)
        root_lay.addWidget(self.stack, 1)

        # Select dashboard
        self._nav_buttons[0].setChecked(True)

        # Toast overlay
        self._toast_host = QWidget(self)
        toast_lay = QVBoxLayout(self._toast_host)
        toast_lay.setContentsMargins(0, 0, 24, 24)
        toast_lay.addStretch(1)
        self._toast_host.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._toast_host.raise_()

    def _on_nav(self, button_id: int):
        btn = self.nav_group.button(button_id)
        idx = self._nav_buttons.index(btn)
        self.stack.setCurrentIndex(idx)

    def navigate(self, page_key: str):
        keys = list(self.pages.keys())
        idx = keys.index(page_key)
        self._nav_buttons[idx].setChecked(True)
        self.stack.setCurrentIndex(idx)

    def toast(self, message: str, kind: str = "info", timeout_ms: int = 3500):
        """Show a floating toast notification."""
        t = Toast(message, kind, timeout_ms, parent=self._toast_host)
        lay: QVBoxLayout = self._toast_host.layout()
        lay.addWidget(t, alignment=Qt.AlignmentFlag.AlignRight)
        t.CLOSED.connect(lambda: lay.removeWidget(t))
        t.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._toast_host.setGeometry(self.rect())

    def _apply_theme(self, theme: str):
        import sys
        pal = DARK if theme == "dark" else LIGHT
        if theme == "system":
            pal = DARK if sys.platform == "win32" and QApplication.instance().styleHints().colorScheme() == Qt.ColorScheme.Dark else LIGHT
        app = QApplication.instance()
        if app:
            app.setStyleSheet(build_stylesheet(pal))