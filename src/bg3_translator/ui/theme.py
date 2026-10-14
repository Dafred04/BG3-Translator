"""Design system: premium dark "gaming / AI" palette + QSS stylesheet.

Dark graphite base with a deep red accent. Exposes Palette, DARK, LIGHT,
build_stylesheet(palette) and DEFAULT / FONT_FAMILY / FONT_SIZE.
"""

from dataclasses import dataclass


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


# Premium dark: near-black graphite with a deep red accent.
DARK = Palette(
    bg="#0c0d10",
    bg_elevated="#12141a",
    surface="#16181f",
    surface_alt="#1e212b",
    border="#262a35",
    border_strong="#333846",
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
)


# Light fallback (rarely used; app defaults to dark).
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
)


# App default theme.
DEFAULT = DARK


FONT_FAMILY = "Segoe UI"
FONT_SIZE = 10
def build_stylesheet(pal: Palette) -> str:
    """Build the complete QSS stylesheet for the given palette."""
    return (
        "/* Base */\\n"
        f"QWidget {{ background-color: {pal.bg}; color: {pal.text}; "
        f'font-family: "{FONT_FAMILY}"; font-size: {FONT_SIZE}px; }}\\n\\n'

        "/* Scrollbars */\\n"
        f"QScrollBar:vertical {{ background: {pal.bg}; width: 10px; margin: 0; }} "
        f"QScrollBar::handle:vertical {{ background: {pal.border_strong}; border-radius: 5px; min-height: 30px; }} "
        f"QScrollBar::handle:vertical:hover {{ background: {pal.accent_hover}; }} "
        "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; } "
        f"QScrollBar:horizontal {{ background: {pal.bg}; height: 10px; margin: 0; }} "
        f"QScrollBar::handle:horizontal {{ background: {pal.border_strong}; border-radius: 5px; min-width: 30px; }} "
        f"QScrollBar::handle:horizontal:hover {{ background: {pal.accent_hover}; }} "
        "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; } "
        "/* Cards */\\n"
        f"#Card {{ background-color: {pal.surface}; border: 1px solid {pal.border}; border-radius: 10px; }} "
        f"#Card:hover {{ border-color: {pal.border_strong}; }} "
        "/* Buttons */\\n"
        f"#Primary {{ background-color: {pal.accent}; color: {pal.accent_text}; border: none; "
        f"border-radius: 8px; padding: 8px 18px; font-weight: 600; }} "
        f"#Primary:hover {{ background-color: {pal.accent_hover}; }} "
        f"#Primary:pressed {{ background-color: {pal.accent_pressed}; }} "
        f"#Primary:disabled {{ background-color: {pal.border_strong}; color: {pal.text_muted}; }} "
        f"#Danger {{ background-color: {pal.danger}; color: {pal.accent_text}; border: none; "
        f"border-radius: 8px; padding: 8px 18px; font-weight: 600; }} "
        f"#Danger:hover {{ background-color: {pal.danger_hover}; }} "
        f"#Danger:pressed {{ background-color: {pal.danger_hover}; }} "
        f"#Danger:disabled {{ background-color: {pal.border_strong}; color: {pal.text_muted}; }} "
        "/* Nav / Sidebar */\\n"
        f"#Sidebar {{ background-color: {pal.bg_elevated}; border-right: 1px solid {pal.border}; }} "
        f"#Title {{ color: {pal.text}; font-size: {FONT_SIZE + 4}px; font-weight: 700; }} "
        f"#Subtitle {{ color: {pal.text_muted}; font-size: {FONT_SIZE}px; }} "
        f"#NavButton {{ background: transparent; border: none; border-radius: 8px; padding: 8px 12px; "
        f"text-align: left; color: {pal.text}; font-size: {FONT_SIZE}px; font-weight: 500; }} "
        f"#NavButton:hover {{ background-color: {pal.surface_alt}; }} "
        f"#NavButton:checked {{ background-color: {pal.accent_soft}; color: {pal.accent}; font-weight: 600; }} "
        f"#NavButton:disabled {{ color: {pal.text_muted}; }} "
        "/* Inputs */\\n"
        f"QLineEdit, QComboBox, QSpinBox {{ background-color: {pal.surface}; border: 1px solid {pal.border}; "
        f"border-radius: 6px; padding: 6px 10px; color: {pal.text}; "
        f"selection-background-color: {pal.accent_soft}; }} "
        f"QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {pal.accent}; }} "
        f"QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ background-color: {pal.bg_elevated}; "
        f"color: {pal.text_muted}; border-color: {pal.border}; }} "
        f"QComboBox::drop-down {{ border: none; width: 24px; subcontrol-origin: padding; "
        f"subcontrol-position: center right; }} "
        f"QComboBox::down-arrow {{ image: none; border-left: 5px solid transparent; "
        f"border-right: 5px solid transparent; border-top: 6px solid {pal.text_muted}; margin-right: 8px; }} "
        f"QComboBox QAbstractItemView {{ background-color: {pal.surface}; border: 1px solid {pal.border}; "
        f"selection-background-color: {pal.accent_soft}; selection-color: {pal.accent}; outline: none; }} "
        "/* Checkboxes */\\n"
        f"QCheckBox {{ spacing: 8px; color: {pal.text}; }} "
        f"QCheckBox::indicator {{ width: 18px; height: 18px; border: 2px solid {pal.border_strong}; "
        f"border-radius: 4px; background: {pal.surface}; }} "
        f"QCheckBox::indicator:hover {{ border-color: {pal.accent}; }} "
        f"QCheckBox::indicator:checked {{ background-color: {pal.accent}; border-color: {pal.accent}; "
        f"image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMiIgaGVpZ2h0PSI5IiB2aVZnQm94PSIwIDAgMTIgOSIgZmlsbD0ibm9uZSI+PHBhdGggZD0iTTEgNC41IDQuNSA4IDExIDEiIHN0cm9rZT0id2hpdGViIHN0cm9rZS13aWR0aD0iMiIvcj48L3N2Zz4=); }} "
        "/* Table */\\n"
        f"QTableWidget {{ background-color: {pal.surface}; border: 1px solid {pal.border}; "
        f"border-radius: 8px; gridline-color: {pal.border}; outline: none; }} "
        f"QTableWidget::item {{ padding: 8px 10px; border-bottom: 1px solid {pal.border}; }} "
        f"QTableWidget::item:selected {{ background-color: {pal.accent_soft}; color: {pal.text}; }} "
        f"QHeaderView::section {{ background-color: {pal.surface_alt}; border: none; "
        f"border-bottom: 1px solid {pal.border_strong}; padding: 8px 10px; "
        f"color: {pal.text_muted}; font-weight: 600; }} "
        f"QHeaderView::section:horizontal:first {{ border-top-left-radius: 8px; }} "
        f"QHeaderView::section:horizontal:last {{ border-top-right-radius: 8px; }} "
        "/* ProgressBar */\\n"
        f"QProgressBar {{ background-color: {pal.surface}; border: 1px solid {pal.border}; "
        f"border-radius: 4px; text-align: center; }} "
        f"QProgressBar::chunk {{ background-color: {pal.accent}; border-radius: 3px; }} "
        "/* Toast */\\n"
        f"#Toast {{ background-color: {pal.surface}; border: 1px solid {pal.border}; "
        f"border-radius: 10px; padding: 8px 14px; }} "
        f"#ToastSuccess {{ border-color: {pal.success}; }} "
        f"#ToastError {{ border-color: {pal.danger}; }} "
        f"#ToastWarning {{ border-color: {pal.warning}; }} "
        "/* Stat Tiles */\\n"
        f"#StatValue {{ color: {pal.accent}; font-size: {FONT_SIZE + 14}px; font-weight: 800; }} "
        f"#StatLabel {{ color: {pal.text_muted}; font-size: {FONT_SIZE - 1}px; }} "
        "/* StatusBar */\\n"
        f"#StatusBar {{ background-color: {pal.bg_elevated}; border-top: 1px solid {pal.border}; "
        f"padding: 4px 12px; }} "
        "/* Focus outline */\\n"
        "QWidget:focus { outline: none; } "
    )
