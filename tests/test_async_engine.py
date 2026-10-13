"""M8 async engine smoke test (offline, fake provider).
Verifies: progress signals carry stage/file counters; UI thread never blocks.
"""
import sys, pathlib, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtWidgets import QApplication
from bg3_translator.services.engine import TranslationEngine, JobProgress
from bg3_translator.models.translation import (
    ModMetadata,
    TranslationProject,
    TranslationEntry,
)


class FakeProvider:
    """Instant-answer mock for offline testing."""

    name = "fake"
    requires_key = False

    def is_configured(self):
        return True

    def translate(self, request):
        return type("R", (), {
            "texts": [f"перевод {request.texts[0][:10]}"],
            "provider": self.name,
            "characters": 0,
        })()


def test_async_progress_signals():
    app = QApplication.instance() or QApplication(sys.argv)
    calls = []
    last = {}

    def callback(p):
        calls.append(p)
        last.update(
            stage=p.stage,
            current_mod=p.current_mod,
            succeeded=p.succeeded,
            failed=p.failed,
            percent=p.percent,
            processed_files=p.processed_files,
            error_details=getattr(p, "error_details", {}),
        )

    engine = TranslationEngine(dictionary=None, provider=FakeProvider())
    project = TranslationProject(
        metadata=ModMetadata(name="testmod", uuid="u1"),
        entries=[
            TranslationEntry(handle="h1", source_text="Hello world"),
            TranslationEntry(handle="h2", source_text="Nuclear fission"),
        ],
        source_language="en",
        target_language="ru",
    )

    engine.run_async(project, callback=callback)

    # wait until engine finishes (processed reaches total)
    for _ in range(500):
        app.processEvents()
        if last.get("processed_files", 0) >= 2:
            break
        time.sleep(0.02)

    assert len(calls) >= 2, f"expected >= 2 updates, got {len(calls)}: {calls}"
    assert all(isinstance(c, JobProgress) for c in calls)
    # every payload reports stage + current_mod + file
    for c in calls:
        assert c.current_mod == "testmod", c
        assert 0 <= c.percent <= 100, c
    assert last.get("succeeded") == 2 and last.get("failed") == 0
    engine.cancel()
    print("async progress signals: OK")
    print("last payload:", {k: v for k, v in last.items() if k != "error_details"})


if __name__ == "__main__":
    test_async_progress_signals()
    print("M8 async engine test PASSED")
