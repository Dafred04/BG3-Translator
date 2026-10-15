"""BG3 Mod Translator v2 — application entry point."""

import logging
import sys
import traceback
from pathlib import Path

# Ensure src/ is importable when running from repo root
_SRC = Path(__file__).resolve().parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _install_excepthook():
    """Необработанная ошибка попадает в журнал, а не молча убивает окно."""
    log = logging.getLogger("bg3_translator")

    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("Необработанная ошибка:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


def main() -> int:
    from bg3_translator.logging_setup import setup_logging
    setup_logging()
    _install_excepthook()

    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from bg3_translator.ui.main_window import MainWindow

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("BG3 Mod Translator")
    app.setOrganizationName("BG3ModTranslator")
    app.setStyle("Fusion")        # единый вид на всех системах; цвета задаёт тема

    from PySide6.QtGui import QFont
    _font = QFont("Segoe UI", 10)
    _font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(_font)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
