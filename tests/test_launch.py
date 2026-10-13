"""M7 final validation: launch via main.main() offscreen, auto-quit after init."""
import sys, os, pathlib
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))  # for main.py

from PySide6.QtCore import QTimer
import PySide6.QtWidgets as W

import bg3_translator
print(f"app version: {bg3_translator.__version__}")

# Patch exec (static method in PySide6) to quit shortly after event loop starts
_original_exec = W.QApplication.exec
def _exec_short():
    from PySide6.QtCore import QTimer
    app = W.QApplication.instance()
    QTimer.singleShot(1500, app.quit)
    return _original_exec()
W.QApplication.exec = staticmethod(_exec_short)

sys.argv = [sys.argv[0]]
rc = __import__("importlib").import_module("main").main()
assert rc == 0, rc
print("M7: application launched and exited cleanly")