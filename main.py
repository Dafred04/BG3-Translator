"""BG3 Mod Translator v2 — application entry point."""

import sys
from pathlib import Path

# Ensure src/ is importable when running from repo root
_SRC = Path(__file__).resolve().parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from bg3_translator.ui.main_window import MainWindow

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("BG3 Mod Translator")
    app.setOrganizationName("BG3ModTranslator")

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())