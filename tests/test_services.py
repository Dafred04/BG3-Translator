"""Smoke tests for services layer (M4): dictionary + engine (offline, no network)."""
import sys, pathlib, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from bg3_translator.services import DictionaryStore, TranslationEngine, TranslationError
from bg3_translator.services.providers import BaseProvider, TranslateRequest, TranslateResult
from bg3_translator.models.translation import (
    TranslationEntry, DictionaryEntry, TranslationStatus,
)


class FakeProvider(BaseProvider):
    """Offline fake provider mapping known texts."""
    name = "fake"
    display_name = "Fake"
    requires_key = False

    MAPPING = {
        "Hello": "你好",
        "Fire Bolt": "火焰箭",
    }

    def translate(self, request: TranslateRequest) -> TranslateResult:
        out = [self.MAPPING.get(t, f"[tr]{t}") for t in request.texts]
        return TranslateResult(texts=out, provider=self.name)


def test_dictionary(tmp_path):
    store = DictionaryStore(tmp_path / "dict.db")
    e = DictionaryEntry(source_text="Hello", source_language="en",
                        target_text="你好", target_language="zh", handle="h1")
    store.add(e)
    hit = store.lookup("Hello", "en", "zh")
    assert hit and hit.target_text == "你好", hit
    assert store.count() == 1
    assert store.lookup("Missing", "en", "zh") is None
    # upsert
    e2 = DictionaryEntry(source_text="Hello", source_language="en",
                         target_text="您好", target_language="zh")
    store.add(e2)
    hit2 = store.lookup("Hello", "en", "zh")
    assert hit2.target_text == "您好"
    print("dictionary: OK")


def test_engine_dictionary_first(tmp_path):
    store = DictionaryStore(tmp_path / "dict.db")
    store.add(DictionaryEntry(source_text="Fire Bolt", source_language="en",
                              target_text="火焰箭", target_language="zh"))
    engine = TranslationEngine(store, provider=None)
    entry = TranslationEntry(handle="h1", source_text="Fire Bolt")
    ok = engine.translate_entry(entry)
    assert ok and entry.target_text == "火焰箭"
    assert entry.status == TranslationStatus.DICTIONARY_MATCH
    print("engine dictionary-first: OK")


def test_engine_provider_and_cache(tmp_path):
    store = DictionaryStore(tmp_path / "dict.db")
    engine = TranslationEngine(store, provider=FakeProvider())
    entry = TranslationEntry(handle="h2", source_text="Hello")
    ok = engine.translate_entry(entry)
    assert ok and entry.target_text == "你好", (ok, entry.target_text)
    assert entry.status == TranslationStatus.AUTO_TRANSLATED
    # cached in dictionary
    hit = store.lookup("Hello", "en", "zh")
    assert hit and hit.target_text == "你好"
    # second translation comes from dictionary without provider
    engine2 = TranslationEngine(store, provider=None)
    e2 = TranslationEntry(handle="h3", source_text="Hello")
    assert engine2.translate_entry(e2) and e2.target_text == "你好"
    print("engine provider + cache: OK")


def test_engine_placeholder_guard(tmp_path):
    """Provider output missing placeholders must be rejected."""
    store = DictionaryStore(tmp_path / "dict.db")

    class BadProvider(BaseProvider):
        name = "bad"
        requires_key = False

        def translate(self, request: TranslateRequest) -> TranslateResult:
            return TranslateResult(texts=["broken no placeholders"], provider=self.name)

    engine = TranslationEngine(store, provider=BadProvider())
    entry = TranslationEntry(handle="h4", source_text="You get {0} gold &amp;")
    ok = engine.translate_entry(entry)
    assert not ok
    assert not entry.target_text
    assert entry.validation_errors
    print("engine placeholder guard: OK")


def test_engine_batch_progress(tmp_path):
    store = DictionaryStore(tmp_path / "dict.db")
    engine = TranslationEngine(store, provider=FakeProvider())
    entries = [TranslationEntry(handle=f"h{i}", source_text=t)
               for i, t in enumerate(["Hello", "Fire Bolt", "Unknown"])]
    seen = []
    progress = engine.translate_batch(entries, on_progress=lambda p: seen.append(p.done))
    assert progress.total == 3 and progress.done == 3
    assert progress.percent == 100
    assert seen == [1, 2, 3]
    assert entries[2].target_text == "[tr]Unknown"
    print("engine batch progress: OK")


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        test_dictionary(tmp)
        test_engine_dictionary_first(tmp / "a")
        test_engine_provider_and_cache(tmp / "b")
        test_engine_placeholder_guard(tmp / "c")
        test_engine_batch_progress(tmp / "d")
    print("M4 smoke tests passed")