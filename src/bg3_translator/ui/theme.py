"""Design system: тёмный графит + глубокий красный акцент, QSS-стили.

Экспортирует Palette, DARK, LIGHT, DEFAULT, FONT_FAMILY, FONT_SIZE,
build_stylesheet(palette), а также current() / rgba() для кастомно
рисуемых виджетов (кольцо прогресса, hero-карточка и т.д.).
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from string import Template


@dataclass(frozen=True)
class Palette:
    bg: str
    bg_elevated: str
    surface: str
    surface_alt: str
    border: str
    border_strong: str
    text: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_text: str
    accent_soft: str
    danger: str
    danger_hover: str
    success: str
    warning: str
    info: str
    is_dark: bool = True


DARK = Palette(
    bg="#0b0c0f",
    bg_elevated="#111318",
    surface="#16181f",
    surface_alt="#1e212b",
    border="#262a35",
    border_strong="#363b4b",
    text="#eef1f6",
    text_muted="#8b93a4",
    accent="#e5323d",
    accent_hover="#f2454f",
    accent_pressed="#c11e28",
    accent_text="#ffffff",
    accent_soft="rgba(229,50,61,0.14)",
    danger="#e5323d",
    danger_hover="#f2454f",
    success="#2fbf71",
    warning="#e8a33d",
    info="#4f8cff",
    is_dark=True,
)

LIGHT = Palette(
    bg="#f4f5f7",
    bg_elevated="#ffffff",
    surface="#ffffff",
    surface_alt="#eef0f4",
    border="#dfe3e8",
    border_strong="#c9cfd8",
    text="#16181f",
    text_muted="#5c6472",
    accent="#c81e2b",
    accent_hover="#e5323d",
    accent_pressed="#a11621",
    accent_text="#ffffff",
    accent_soft="rgba(200,30,43,0.12)",
    danger="#c81e2b",
    danger_hover="#e5323d",
    success="#1f9d55",
    warning="#c67c12",
    info="#2563eb",
    is_dark=False,
)

DEFAULT = DARK

FONT_FAMILY = '"Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif'
FONT_SIZE = 13  # px

_current: Palette = DEFAULT


def current() -> Palette:
    """Палитра, применённая последним вызовом build_stylesheet()."""
    return _current


def rgba(color: str, alpha: float) -> str:
    """'#rrggbb' + alpha -> 'rgba(r,g,b,a)' (для QSS)."""
    h = color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def qcolor(color: str, alpha: int = 255):
    """'#rrggbb' -> QColor с заданной прозрачностью (0..255)."""
    from PySide6.QtGui import QColor
    c = QColor(color)
    c.setAlpha(alpha)
    return c


def _icon(kind: str, color: str) -> str:
    """Рисует маленькую иконку (галочка / стрелки) в PNG и возвращает путь.

    QSS не умеет рисовать галочки и стрелки сам, а data-URI в нём не
    поддерживаются, поэтому иконки генерируются один раз во временную папку.
    """
    try:
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QPolygonF

        path = Path(tempfile.gettempdir()) / f"bg3mt_{kind}_{color.lstrip('#')}.png"
        if not path.exists():
            size = 14 if kind == "check" else 10
            pm = QPixmap(size, size)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(color), 2.0 if kind == "check" else 1.8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            pts = {
                "check": [(2.5, 7.5), (5.8, 10.5), (11.5, 3.8)],
                "down": [(1.5, 3.5), (5, 7), (8.5, 3.5)],
                "up": [(1.5, 6.5), (5, 3), (8.5, 6.5)],
            }[kind]
            p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in pts]))
            p.end()
            pm.save(str(path))
        return path.as_posix()
    except Exception:
        return ""


def _img(path: str) -> str:
    return f'image: url("{path}");' if path else ""


_QSS = Template(r"""
/* ---------- Base ---------- */
QWidget { color: $text; font-family: $ff; font-size: ${fs}px; }
QMainWindow, #Root { background-color: $bg; }
QLabel { background: transparent; }
QToolTip { background-color: $surface_alt; color: $text; border: 1px solid $border_strong;
           border-radius: 6px; padding: 6px 8px; }

/* ---------- Scrollbars ---------- */
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $border_strong; border-radius: 3px; min-height: 36px; }
QScrollBar::handle:vertical:hover { background: $accent; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: $border_strong; border-radius: 3px; min-width: 36px; }
QScrollBar::handle:horizontal:hover { background: $accent; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }

/* ---------- Typography ---------- */
#PageTitle { font-size: ${fs_xl}px; font-weight: 800; }
#Title { font-size: ${fs_l}px; font-weight: 700; }
#CardTitle { font-size: ${fs_m}px; font-weight: 700; }
#Subtitle { color: $text_muted; }
#HeroTitle { font-size: ${fs_xxl}px; font-weight: 800; color: #ffffff; }
#HeroText { color: rgba(255,255,255,0.72); font-size: ${fs_m}px; }
#PercentBig { font-size: ${fs_xl}px; font-weight: 800; color: $accent; }
#MetricValue { font-size: ${fs_m}px; font-weight: 700; }
#MetricValue[tone="danger"] { color: $danger; }
#MetricValue[tone="success"] { color: $success; }
#EmptyIcon { font-size: 54px; }

/* ---------- Cards ---------- */
#Card { background-color: $surface; border: 1px solid $border; border-radius: 14px; }
#Card:hover { border-color: $border_strong; }
#SideCard { background-color: $surface; border: 1px solid $border; border-radius: 12px; }

/* ---------- Buttons ---------- */
QPushButton { background-color: $surface_alt; border: 1px solid $border_strong; border-radius: 9px;
              padding: 8px 16px; font-weight: 600; }
QPushButton:hover { border-color: $accent; color: $accent_hover; }
QPushButton:pressed { background-color: $accent_soft; }
QPushButton:disabled { color: $text_muted; border-color: $border; background-color: $bg_elevated; }
#Primary { background-color: $accent; color: $accent_text; border: none; border-radius: 9px;
           padding: 8px 20px; font-weight: 700; }
#Primary:hover { background-color: $accent_hover; color: $accent_text; }
#Primary:pressed { background-color: $accent_pressed; }
#Primary:disabled { background-color: $border_strong; color: $text_muted; }
#Ghost { background-color: transparent; border: 1px solid $border_strong; color: $text; }
#Ghost:hover { border-color: $accent; color: $accent_hover; background-color: $accent_soft; }
#Danger { background-color: transparent; color: $danger; border: 1px solid $danger; border-radius: 9px;
          padding: 8px 18px; font-weight: 700; }
#Danger:hover { background-color: $danger; color: $accent_text; }
#Danger:disabled { color: $text_muted; border-color: $border; background-color: transparent; }
#IconButton { background: transparent; border: none; padding: 4px; border-radius: 6px; color: $text_muted; }
#IconButton:hover { background-color: $surface_alt; color: $accent_hover; }

/* ---------- Sidebar / Navigation ---------- */
#Sidebar { background-color: $bg_elevated; border-right: 1px solid $border; }
#LogoBadge { background-color: $accent; color: #ffffff; border-radius: 11px;
             font-size: ${fs_l}px; font-weight: 900; }
#NavButton { background: transparent; border: none; border-radius: 9px; padding: 8px 14px;
             text-align: left; color: $text_muted; font-size: ${fs}px; font-weight: 600; }
#NavButton:hover { color: $text; }
#NavButton:checked { color: $accent_hover; font-weight: 700; background: transparent; }
#NavIndicator { background-color: $accent_soft; border-radius: 9px; }
#NavBar { background-color: $accent; border-radius: 2px; }

/* ---------- Inputs ---------- */
QLineEdit, QComboBox, QSpinBox { background-color: $surface; border: 1px solid $border; border-radius: 9px;
    padding: 7px 11px; selection-background-color: $accent; selection-color: #ffffff; }
QLineEdit:hover, QComboBox:hover, QSpinBox:hover { border-color: $border_strong; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: $accent; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { background-color: $bg_elevated;
    color: $text_muted; border-color: $border; }
QComboBox::drop-down { border: none; width: 26px; subcontrol-origin: padding; subcontrol-position: center right; }
QComboBox::down-arrow { $arrow_down width: 10px; height: 10px; }
QComboBox QAbstractItemView { background-color: $surface; border: 1px solid $border_strong; border-radius: 8px;
    padding: 4px; selection-background-color: $accent_soft; selection-color: $accent_hover; outline: none; }
QSpinBox::up-button, QSpinBox::down-button { width: 20px; border: none; background: transparent; }
QSpinBox::up-arrow { $arrow_up width: 10px; height: 10px; }
QSpinBox::down-arrow { $arrow_down width: 10px; height: 10px; }

/* ---------- Checkbox ---------- */
QCheckBox { spacing: 10px; }
QCheckBox::indicator { width: 18px; height: 18px; border: 2px solid $border_strong; border-radius: 5px;
    background: $surface; }
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked { background-color: $accent; border-color: $accent; $check }

/* ---------- Table ---------- */
QTableWidget { background-color: $surface; border: 1px solid $border; border-radius: 12px;
    gridline-color: transparent; outline: none; alternate-background-color: $bg_elevated; }
QTableWidget::item { padding: 6px 10px; border-bottom: 1px solid $border; }
QTableWidget::item:hover { background-color: $surface_alt; }
QTableWidget::item:selected { background-color: $accent_soft; color: $text; }
QHeaderView { background: transparent; }
QHeaderView::section { background-color: $surface_alt; border: none; border-bottom: 1px solid $border_strong;
    padding: 9px 10px; color: $text_muted; font-weight: 700; }
QTableCornerButton::section { background-color: $surface_alt; border: none; }

/* ---------- Text areas ---------- */
QPlainTextEdit, QTextEdit { background-color: $surface; border: 1px solid $border; border-radius: 9px;
    padding: 8px 10px; selection-background-color: $accent; selection-color: #ffffff; }
QPlainTextEdit:hover, QTextEdit:hover { border-color: $border_strong; }
QPlainTextEdit:focus, QTextEdit:focus { border-color: $accent; }
QPlainTextEdit[readOnly="true"] { background-color: $bg_elevated; }

/* ---------- Dialogs ---------- */
QDialog, QMessageBox { background-color: $bg_elevated; }
QMessageBox QLabel { background: transparent; }

/* ---------- Splitter ---------- */
QSplitter::handle { background: transparent; }
QSplitter::handle:horizontal { width: 10px; }
QSplitter::handle:hover { background-color: $accent_soft; }

/* ---------- Segmented control ---------- */
#Seg { background-color: transparent; border: 1px solid $border_strong; border-radius: 9px;
       padding: 7px 18px; color: $text_muted; font-weight: 600; }
#Seg:hover { color: $text; border-color: $accent; }
#Seg:checked { background-color: $accent_soft; color: $accent_hover; border-color: $accent; font-weight: 700; }

/* ---------- Notices ---------- */
#Banner { background-color: $accent_soft; border: 1px solid $accent; border-radius: 10px; }
#IssueError { color: $danger; }
#IssueWarn { color: $warning; }
#Hint { color: $text_muted; font-size: ${fs_s}px; }
#RecentRow { background-color: $surface_alt; border: 1px solid $border; border-radius: 10px; }
#RecentRow:hover { border-color: $accent; }

/* ---------- Menu ---------- */
QMenu { background-color: $surface; border: 1px solid $border_strong; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 8px 24px 8px 14px; border-radius: 6px; }
QMenu::item:selected { background-color: $accent_soft; color: $accent_hover; }

/* ---------- Chips ---------- */
#Chip { background-color: $surface_alt; border: 1px solid $border; border-radius: 11px;
        padding: 3px 11px; color: $text_muted; font-weight: 600; }
#Chip[tone="accent"] { color: $accent_hover; border-color: $accent; background-color: $accent_soft; }
#Chip[tone="success"] { color: $success; border-color: $success; }
#Chip[tone="warning"] { color: $warning; border-color: $warning; }
#Chip[tone="danger"] { color: $danger; border-color: $danger; }

#StageChip { background-color: transparent; border: 1px solid $border; border-radius: 10px;
             padding: 4px 10px; color: $text_muted; }
#StageChip[state="active"] { background-color: $accent_soft; border-color: $accent; color: $accent_hover;
                             font-weight: 700; }
#StageChip[state="done"] { border-color: $success; color: $success; }

#StepDot { background-color: $surface_alt; border: 2px solid $border_strong; border-radius: 18px;
           color: $text_muted; font-weight: 800; }
#StepDot[state="current"] { border-color: $accent; color: $accent_hover; background-color: $accent_soft; }
#StepDot[state="done"] { background-color: $accent; border-color: $accent; color: #ffffff; }

/* ---------- Toast ---------- */
#Toast { background-color: $bg_elevated; border: 1px solid $border_strong; border-radius: 12px; }
#Toast[kind="success"] { border-color: $success; }
#Toast[kind="error"] { border-color: $danger; }
#Toast[kind="warning"] { border-color: $warning; }
#ToastIcon { font-size: ${fs_m}px; font-weight: 800; color: $info; }
#ToastIcon[kind="success"] { color: $success; }
#ToastIcon[kind="error"] { color: $danger; }
#ToastIcon[kind="warning"] { color: $warning; }

/* ---------- Stat tiles ---------- */
#StatValue { font-size: ${fs_xxl}px; font-weight: 800; }
#StatValue[tone="accent"] { color: $accent; }
#StatValue[tone="success"] { color: $success; }
#StatValue[tone="danger"] { color: $danger; }
#StatLabel { color: $text_muted; font-size: ${fs_s}px; }

/* ---------- Status bar ---------- */
#StatusBar { background-color: $bg_elevated; border-top: 1px solid $border; }
QStatusBar::item { border: none; }

QWidget:focus { outline: none; }
""")


def build_qpalette(pal: Palette):
    """QPalette под тему: нужна для того, что QSS не покрывает (системные диалоги, подсказки)."""
    from PySide6.QtGui import QColor, QPalette

    p = QPalette()
    R, G = QPalette.ColorRole, QPalette.ColorGroup
    for role, color in (
        (R.Window, pal.bg), (R.WindowText, pal.text), (R.Base, pal.surface),
        (R.AlternateBase, pal.bg_elevated), (R.Text, pal.text), (R.Button, pal.surface_alt),
        (R.ButtonText, pal.text), (R.ToolTipBase, pal.surface_alt), (R.ToolTipText, pal.text),
        (R.Highlight, pal.accent), (R.HighlightedText, "#ffffff"), (R.Link, pal.accent_hover),
        (R.PlaceholderText, pal.text_muted), (R.BrightText, "#ffffff"),
    ):
        p.setColor(role, QColor(color))
    for role in (R.Text, R.ButtonText, R.WindowText):
        p.setColor(G.Disabled, role, QColor(pal.text_muted))
    return p


def build_stylesheet(pal: Palette) -> str:
    """Собирает полный QSS для палитры и запоминает её как текущую."""
    global _current
    _current = pal
    return _QSS.substitute(
        ff=FONT_FAMILY,
        fs=FONT_SIZE, fs_s=FONT_SIZE - 1, fs_m=FONT_SIZE + 2, fs_l=FONT_SIZE + 5,
        fs_xl=FONT_SIZE + 13, fs_xxl=FONT_SIZE + 17,
        arrow_down=_img(_icon("down", pal.text_muted)),
        arrow_up=_img(_icon("up", pal.text_muted)),
        check=_img(_icon("check", "#ffffff")),
        **{k: v for k, v in pal.__dict__.items() if isinstance(v, str)},
    )
