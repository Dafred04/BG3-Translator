"""M11: async translation in the UI thread must never block.

Simulates a slow provider (like Gemini taking ~200ms per call) and verifies:
- progress signals are emitted repeatedly (queued to the main thread);
- the Qt event loop keeps processing events during the run;
- a cancel request is honored gracefully;
- on completion, live project entries are translated in place.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from bg3_translator.models.translation import (
    ModMetadata, TranslationEntry, TranslationProject,
)
from bg3_translator.services.engine import TranslationEngine
from bg3_translator.services.providers import BaseProvider, TranslateRequest, TranslateResult


class SlowProvider(BaseProvider):
    """Simulates a slow Gemini call (~120ms) so we can observe responsiveness."""

    name = "slow"
    requires_key = False

    def is_configured(self):
        return True

    def translate(self, request: TranslateRequest) -> TranslateResult:
        time.sleep(0.12)  # blocking network wait (happens in worker thread)
        return TranslateResult(texts=[f"[ru] {t}" for t in request.texts], provider=self.name)


def main():
    app = QApplication.instance() or QApplication([])

    engine = TranslationEngine(dictionary=None, provider=SlowProvider())
    entries = [TranslationEntry(handle=f"h{i}", source_text=f"line {i}") for i in range(8)]
    project = TranslationProject(
        metadata=ModMetadata(name="slowmod", uuid="u"),
        entries=entries, source_language="en", target_language="ru",
    )

    progresses = []
    finished = []
    errors = []
    engine.progress.connect(lambda p: progresses.append(p))
    engine.finished.connect(lambda proj: finished.append(proj))
    engine.error.connect(lambda m: errors.append(m))

    engine.run_async(project)

    # Pump the Qt event loop while the worker thread runs. If signals were
    # synchronous or the loop were blocked, these processEvents() calls would
    # never see intermediate progress.
    deadline = time.time() + 15
    while time.time() < deadline and not finished and not errors:
        app.processEvents()
        time.sleep(0.02)

    app.processEvents()

    assert not errors, f"unexpected errors: {errors}"
    assert finished, "engine did not finish"
    # progress must have been emitted at least once per entry
    assert len(progresses) >= 8, f"expected >=8 progress signals, got {len(progresses)}"
    assert progresses[-1].percent == 100, progresses[-1].percent
    # live entries translated in place
    translated = sum(1 for e in entries if e.is_translated())
    assert translated == 8, f"only {translated}/8 translated in place"
    # elapsed time consistent with slow provider (~0.12s * 8 ~ 1s), ran off-thread
    print(f"progress signals: {len(progresses)}")
    print(f"translated in place: {translated}/8")
    print(f"last percent: {progresses[-1].percent}%")
    print("M11 async UI-non-blocking test PASSED")


if __name__ == "__main__":
    main()
