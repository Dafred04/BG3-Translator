"""Design system: color tokens + QSS stylesheet (light & dark)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    bg: str
    surface: str
    surface_alt: str
    border: str
    text: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_text: str
    success: str
    warning: str
    error: str
    info: str


LIGHT = Palette(
    bg="#f6f7f9",
    surface="#ffffff",
    surface_alt="#eef0f4",
    border="#dfe3e8",
    text="#1a1d21",
    text_muted="#6b7280",
    accent="#4f6ef7",
    accent_hover="#3b5bf0",
    accent_text="#ffffff",
    success="#16a34a",
    warning="#d97706",
    error="#dc2626",
    info="#0284c7",
)

DARK = Palette(
    bg="#121417",
    surface="#1b1e23",
    surface_alt="#23272e",
    border="#2e333b",
    text="#e8eaed",
    text_muted="#9aa0a6",
    accent="#6b8aff",
    accent_hover="#8aa2ff",
    accent_text="#0d0f12",
    success="#34d399",
    warning="#fbbf24",
    error="#f87171",
    info="#38bdf8",
)

FONT_FAMILY = "Segoe UI"
FONT_SIZE = 13


def build_stylesheet(p: Palette) -> str:
    return f"""
* {{ font-family: "{FONT_FAMILY}"; font-size: {FONT_SIZE}px; }}
QMainWindow, QDialog {{ background: {p.bg}; }}
QWidget {{ color: {p.text}; }}

/* ---------- Sidebar ---------- */
#Sidebar {{
    background: {p.surface};
    border-right: 1px solid {p.border};
}}
#NavButton {{
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 10px 14px;
    text-align: left;
    color: {p.text_muted};
}}
#NavButton:hover {{ background: {p.surface_alt}; color: {p.text}; }}
#NavButton:checked {{
    background: {p.accent}1a;
    color: {p.accent};
    font-weight: 600;
}}

/* ---------- Buttons ---------- */
QPushButton {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: 8px;
    padding: 8px 16px;
}}
QPushButton:hover {{ background: {p.border}; }}
QPushButton:pressed {{ background: {p.surface_alt}; }}
QPushButton:disabled {{ color: {p.text_muted}; opacity: 0.5; }}
QPushButton#Primary {{
    background: {p.accent};
    color: {p.accent_text};
    border: none;
    font-weight: 600;
    padding: 9px 20px;
}}
QPushButton#Primary:hover {{ background: {p.accent_hover}; }}
QPushButton#Primary:disabled {{ background: {p.surface_alt}; color: {p.text_muted}; }}
QPushButton#Danger {{
    background: {p.error};
    color: #ffffff;
    border: none;
    font-weight: 600;
}}

/* ---------- Cards / panels ---------- */
#Card {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 12px;
}}
#Title {{ font-size: 18px; font-weight: 700; }}
#Subtitle {{ color: {p.text_muted}; }}
#StatValue {{ font-size: 26px; font-weight: 700; }}
#StatLabel {{ color: {p.text_muted}; font-size: 12px; }}

/* ---------- Inputs ---------- */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: {p.accent};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
    border: 1px solid {p.accent};
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {p.surface};
    border: 1px solid {p.border};
    selection-background-color: {p.accent}33;
}}

/* ---------- Table ---------- */
QTableWidget {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 10px;
    gridline-color: {p.border};
}}
QTableWidget::item {{ padding: 6px; }}
QTableWidget::item:selected {{ background: {p.accent}22; color: {p.text}; }}
QHeaderView::section {{
    background: {p.surface_alt};
    border: none;
    border-bottom: 1px solid {p.border};
    padding: 8px;
    font-weight: 600;
    color: {p.text_muted};
}}

/* ---------- Progress ---------- */
QProgressBar {{
    background: {p.surface_alt};
    border: none;
    border-radius: 6px;
    height: 12px;
    text-align: center;
}}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 6px; }}

/* ---------- Scrollbars ---------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {p.border}; border-radius: 4px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.text_muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p.border}; border-radius: 4px; min-width: 30px; }}

/* ---------- Toast ---------- */
#Toast {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-left: 4px solid {p.accent};
    border-radius: 8px;
    padding: 12px 16px;
}}
#ToastSuccess {{ border-left-color: {p.success}; }}
#ToastError {{ border-left-color: {p.error}; }}
#ToastWarning {{ border-left-color: {p.warning}; }}
"""