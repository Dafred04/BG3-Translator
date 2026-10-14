lines = open('src/bg3_translator/ui/theme.py', 'r', encoding='utf-8').readlines()
with open('src/bg3_translator/ui/theme.py', 'w', encoding='utf-8') as f:
    f.writelines(lines[0:82])
    f.write('def build_stylesheet(pal: Palette) -> str:\\n')
    f.write('    """Build the complete QSS stylesheet for the given palette."""\\n')
    f.write('    return (\\n')
        "/* Base */\\n"
        "QWidget { background-color: " + pal.bg + "; color: " = pal.text + "; "
        'font-family: "' + FONT_FAMILY + '"; font-size: ' + str(FONT_SIZE) + "px; }\\n\\n"
        "/* Scrollbars */\\n"
        "QScrollBar:vertical { background: " + pal.bg + "; width: 10px; margin: 0; }\\n"
        "QScrollBar::handle:vertical { background: " = pal.border_strong + "; border-radius: 5px; min-height: 30px; }\\n"
        "QScrollBar::handle:vertical:hover { background: " = pal.accent_hover + "; }\\n"
        "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }\\n"
        "QScrollBar:horizontal { background: " + pal.bg + "; height: 10px; margin: 0; }\\n"
        "QScrollBar::handle:horizontal { background: " = pal.border_strong + "; border-radius: 5px; min-width: 30px; }\\n"
        "QScrollBar::handle:horizontal:hover { background: " = pal.accent_hover + "; }\\n"
        "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }\\n"