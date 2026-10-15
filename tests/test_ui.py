"""UI smoke test (offscreen): instantiate MainWindow + all pages."""
import sys, os, pathlib
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from bg3_translator.ui.main_window import MainWindow
win = MainWindow()
win.show()
app.processEvents()

# all pages present
assert win.stack.count() == 4, win.stack.count()
keys = list(win.pages.keys())
assert keys == ["dashboard", "editor", "dictionary", "settings"], keys

# navigation works
win.navigate("editor")
app.processEvents()
win.navigate("settings")
app.processEvents()
win.navigate("dashboard")
app.processEvents()

# toast renders
win.toast("Test toast", "success")
app.processEvents()

# dashboard imports worker exists
from bg3_translator.ui.pages.editor import ImportWorker, EditorPage
from bg3_translator.ui.pages.dashboard import DashboardPage
from bg3_translator.ui.pages.dictionary_page import DictionaryPage
from bg3_translator.ui.pages.settings_page import SettingsPage

# project load -> editor fills table
from bg3_translator.models.translation import TranslationEntry, ModMetadata, TranslationProject
state = win.pages["dashboard"].state
state.save_project = lambda path=None: None      # тест не должен писать в реальные проекты пользователя
state.project = TranslationProject(
    metadata=ModMetadata(name="TestMod"),
    entries=[TranslationEntry(handle=f"h{i}", source_text=f"String {i}") for i in range(5)],
)
state.project_changed.emit()
app.processEvents()
editor = win.pages["editor"]
assert editor.table.rowCount() == 5, editor.table.rowCount()

# editing a cell updates model + validation
editor.table.item(0, 2).setText("Перевод {0}")
app.processEvents()
e0 = state.project.entries[0]
assert e0.target_text == "Перевод {0}"
assert e0.has_validation_errors()  # source "String 0" has no {0} -> unexpected placeholder

# filter untranslated
editor.filter_box.setCurrentIndex(1)
app.processEvents()

win.close()
print("M5 UI smoke test passed")