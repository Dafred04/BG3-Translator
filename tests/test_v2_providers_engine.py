import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

import requests

import _stubs  # noqa: F401
from bg3_translator.models.translation import TranslationEntry, TranslationProject, ModMetadata, TranslationStatus
from bg3_translator.services.dictionary import DictionaryStore
from bg3_translator.services.engine import EngineOptions, TranslationEngine, make_chunks
from bg3_translator.services.providers import (
    BaseProvider, BatchMismatchError, FatalTranslationError, GeminiProvider, OpenAICompatibleProvider,
    TranslateRequest, TranslateResult, TranslationError, parse_json_array, scrub,
)

KEY = "AIzaSyFAKEKEY1234567890"


class FakeResp:
    def __init__(self, status=200, body=None, text="", headers=None):
        self.status_code, self._body, self.text, self.headers = status, body, text or json.dumps(body or {}), headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def gemini_ok(arr):
    return FakeResp(200, {"candidates": [{"content": {"parts": [{"text": json.dumps(arr, ensure_ascii=False)}]}}]})


def make_gemini(responses):
    p = GeminiProvider(api_key=KEY, model="gemini-2.5-flash")
    p._session, p._sleep = FakeSession(responses), lambda s: None
    return p


class ProviderTests(unittest.TestCase):
    def test_key_goes_in_header_not_url(self):
        p = make_gemini([gemini_ok(["Привет"])])
        res = p.translate(TranslateRequest(["Hello"], "en", "ru", glossary={"Hello": "Привет"}))
        self.assertEqual(res.texts, ["Привет"])
        method, url, kw = p._session.calls[0]
        self.assertNotIn(KEY, url)
        self.assertNotIn("params", kw)
        self.assertEqual(kw["headers"]["x-goog-api-key"], KEY)
        body = kw["json"]
        self.assertEqual(body["generationConfig"]["thinkingConfig"], {"thinkingBudget": 0})
        self.assertEqual(body["safetySettings"][0]["threshold"], "BLOCK_NONE")
        self.assertIn("Hello => Привет", body["systemInstruction"]["parts"][0]["text"])   # глоссарий в промпте

    def test_errors_never_contain_key(self):
        leaky = f"400 Bad Request for url: https://x/y?key={KEY} and {KEY}"
        p = make_gemini([FakeResp(400, text=leaky)])
        with self.assertRaises(TranslationError) as cm:
            p.translate(TranslateRequest(["Hi"], "en", "ru"))
        self.assertNotIn(KEY, str(cm.exception))
        self.assertNotIn(KEY, scrub(f"https://a?key={KEY}", KEY))

    def test_retries_on_429_then_succeeds_and_sleeps(self):
        sleeps = []
        p = make_gemini([FakeResp(429), requests.Timeout("t"), gemini_ok(["ок"])])
        p._sleep = sleeps.append
        self.assertEqual(p.translate(TranslateRequest(["ok"], "en", "ru")).texts, ["ок"])
        self.assertEqual(len(p._session.calls), 3)
        self.assertEqual(len(sleeps), 2)

    def test_gives_up_after_retries(self):
        p = make_gemini([FakeResp(503)] * 4)
        with self.assertRaises(TranslationError):
            p.translate(TranslateRequest(["x"], "en", "ru"))
        self.assertEqual(len(p._session.calls), 4)

    def test_auth_and_404_are_fatal_without_retry(self):
        for status in (401, 403, 404):
            p = make_gemini([FakeResp(status)])
            with self.assertRaises(FatalTranslationError):
                p.translate(TranslateRequest(["x"], "en", "ru"))
            self.assertEqual(len(p._session.calls), 1)

    def test_safety_block_and_empty_candidates_have_clear_messages(self):
        p = make_gemini([FakeResp(200, {"promptFeedback": {"blockReason": "SAFETY"}})])
        with self.assertRaisesRegex(TranslationError, "SAFETY"):
            p.translate(TranslateRequest(["x"], "en", "ru"))
        p = make_gemini([FakeResp(200, {"candidates": []})])
        with self.assertRaisesRegex(TranslationError, "вариант"):
            p.translate(TranslateRequest(["x"], "en", "ru"))

    def test_parse_json_array(self):
        self.assertEqual(parse_json_array('```json\n["a","b"]\n```', 2), ["a", "b"])
        self.assertEqual(parse_json_array('Вот: ["a\\nb"]', 1), ["a\nb"])            # многострочные строки
        self.assertEqual(parse_json_array('{"translations": ["a"]}', 1), ["a"])
        with self.assertRaises(BatchMismatchError):
            parse_json_array('["a"]', 2)
        with self.assertRaises(BatchMismatchError):
            parse_json_array("not json", 1)

    def test_openai_local_without_key_and_single_plain_text_fallback(self):
        p = OpenAICompatibleProvider(base_url="http://localhost:11434/v1", model="llama3")
        self.assertTrue(p.is_configured())
        self.assertFalse(OpenAICompatibleProvider().is_configured())
        p._session = FakeSession([FakeResp(200, {"choices": [{"message": {"content": "Просто текст"}}]})])
        self.assertEqual(p.translate(TranslateRequest(["Plain"], "en", "ru")).texts, ["Просто текст"])
        self.assertNotIn("Authorization", p._session.calls[0][2]["headers"])


# ---------------------------------------------------------------------------
class FakeProvider(BaseProvider):
    """Переводит «hello»->«привет», сохраняя токены; считает запросы."""
    name, display_name, requires_key = "fake", "Fake", False

    def __init__(self, mode="ok", delay=0.0):
        super().__init__()
        self.mode, self.delay = mode, delay
        self.requests: list = []
        self.lock = threading.Lock()

    def translate(self, request):
        with self.lock:
            self.requests.append(request)
        if self.delay:
            time.sleep(self.delay)
        if self.mode == "fatal":
            raise FatalTranslationError("Неверный ключ API (401)")
        if self.mode == "fail":
            raise TranslationError("сервер недоступен")
        texts = [f"РУ:{t}" for t in request.texts]
        if self.mode == "drop_token":
            texts = [t.replace("⟦1⟧", "") for t in texts]
        if self.mode == "wrong_count" and len(texts) > 1:
            texts = texts[:-1]
        return TranslateResult(texts, self.name)


def project(texts, ctx="f.loca"):
    entries = [TranslationEntry(handle=f"h{i}", source_text=t, context=ctx, source_language="en", target_language="ru")
               for i, t in enumerate(texts)]
    return TranslationProject(ModMetadata(name="M"), entries, "en", "ru")


def engine(provider, **opts):
    d = DictionaryStore(Path(tempfile.mkdtemp()) / "d.db")
    o = EngineOptions(workers=2, **opts)
    return TranslationEngine(d, provider, o), d


class EngineTests(unittest.TestCase):
    def test_batches_dedupes_and_adds_to_dictionary(self):
        prov = FakeProvider()
        eng, d = engine(prov, batch_size=3)
        pr = project([f"Line {i}" for i in range(7)] + ["Line 0", "Line 0"])     # 9 строк, 7 уникальных
        pg = eng.translate_batch(pr.entries)
        self.assertEqual(pg.message, "")
        self.assertEqual(sum(len(r.texts) for r in prov.requests), 7)           # дубли не уходят в API
        self.assertEqual(len(prov.requests), 3)                                 # 7 уник. / пачки по 3
        self.assertTrue(all(e.status == TranslationStatus.AUTO_TRANSLATED for e in pr.entries))
        self.assertEqual(pr.entries[7].target_text, pr.entries[0].target_text)
        self.assertEqual((pg.succeeded, pg.failed, pg.percent, pg.unique_total), (9, 0, 100, 7))
        self.assertEqual(pg.processed_files, pg.total_files)
        self.assertEqual(d.count(), 7)

        # второй проект: всё из словаря, API не вызывается
        prov.requests.clear()
        pr2 = project(["Line 1", "Line 2"])
        pg2 = eng.translate_batch(pr2.entries)
        self.assertEqual(len(prov.requests), 0)
        self.assertEqual((pg2.from_dictionary, pr2.entries[0].status), (2, TranslationStatus.DICTIONARY_MATCH))

    def test_placeholders_are_shielded_and_restored(self):
        prov = FakeProvider()
        eng, _ = engine(prov)
        src = 'Hit <LSTag Type="Status" Tooltip="X">Burning</LSTag><br>[1] times'
        pr = project([src])
        eng.translate_batch(pr.entries)
        sent = prov.requests[0].texts[0]
        self.assertNotIn("<", sent)                                              # ИИ видит только токены
        self.assertIn("⟦1⟧", prov.requests[0].token_example or "⟦1⟧")
        e = pr.entries[0]
        self.assertEqual(e.status, TranslationStatus.AUTO_TRANSLATED)
        self.assertEqual(e.target_text, "РУ:" + src)
        self.assertEqual(e.validation_errors, [])

    def test_lost_token_fails_entry_but_not_run(self):
        eng, _ = engine(FakeProvider("drop_token"))
        pr = project(["A<br>B", "Plain text only"])
        pg = eng.translate_batch(pr.entries)
        self.assertEqual((pg.failed, pg.succeeded), (1, 1))
        self.assertIn("Потерян плейсхолдер", eng.last_failures["h0"])
        self.assertEqual(pr.entries[0].status, TranslationStatus.NEW)

    def test_strict_flags_for_review_instead_of_discarding(self):
        # без shield провайдер сам портит плейсхолдер -> ошибка валидации
        class Mangler(FakeProvider):
            def translate(self, request):
                res = super().translate(request)
                res.texts = [t.replace("<br>", "") for t in res.texts]
                return res
        eng, d = engine(Mangler(), shield_placeholders=False)
        pr = project(["A<br>B"])
        eng.translate_batch(pr.entries)
        e = pr.entries[0]
        self.assertEqual(e.status, TranslationStatus.NEEDS_REVIEW)
        self.assertTrue(e.has_validation_errors())
        self.assertEqual(e.target_text, "РУ:AB")                                  # результат не потерян
        self.assertEqual(d.count(), 0)                                           # ошибочное в словарь не пишем
        eng2, _ = engine(Mangler(), shield_placeholders=False, strict_placeholders=False)
        pr2 = project(["A<br>B"])
        eng2.translate_batch(pr2.entries)
        self.assertEqual(pr2.entries[0].status, TranslationStatus.AUTO_TRANSLATED)

    def test_validation_can_be_disabled(self):
        class Mangler(FakeProvider):
            def translate(self, request):
                res = super().translate(request)
                res.texts = [t.replace("<br>", "") for t in res.texts]
                return res
        eng, _ = engine(Mangler(), shield_placeholders=False, validate_placeholders=False)
        pr = project(["A<br>B"])
        eng.translate_batch(pr.entries)
        self.assertEqual(pr.entries[0].validation_errors, [])

    def test_wrong_line_count_is_split_until_it_works(self):
        prov = FakeProvider("wrong_count")
        eng, _ = engine(prov, batch_size=8)
        pr = project([f"T{i}" for i in range(8)])
        pg = eng.translate_batch(pr.entries)
        # пачки из >1 строки всегда «ломаются»; делим пополам до одиночных
        self.assertEqual((pg.succeeded, pg.failed), (8, 0))
        self.assertTrue(all(e.target_text.startswith("РУ:") for e in pr.entries))

    def test_fatal_error_aborts_with_message(self):
        eng, _ = engine(FakeProvider("fatal"), batch_size=2)
        pr = project([f"T{i}" for i in range(10)])
        pg = eng.translate_batch(pr.entries)
        self.assertTrue(pg.message.startswith("aborted:"))
        self.assertIn("ключ", pg.message)
        self.assertIn("ключ", eng.first_error)

    def test_circuit_breaker_stops_hammering_api(self):
        prov = FakeProvider("fail")
        eng, _ = engine(prov, batch_size=1, max_consecutive_failures=3)
        eng.options.workers = 1
        pr = project([f"T{i}" for i in range(50)])
        pg = eng.translate_batch(pr.entries)
        self.assertTrue(pg.message.startswith("aborted:"))
        self.assertLessEqual(len(prov.requests), 4)                              # не 50 запросов

    def test_no_provider_reports_clear_reason(self):
        eng, d = engine(None)
        pr = project(["Known", "Unknown"])
        d.add(__import__("bg3_translator.models.translation", fromlist=["x"]).DictionaryEntry(
            "Known", "en", "Известное", "ru"))
        pg = eng.translate_batch(pr.entries)
        self.assertEqual((pg.succeeded, pg.failed), (1, 1))
        self.assertIn("не настроен", eng.first_error)

    def test_glossary_reaches_prompt_and_qa_warns(self):
        prov = FakeProvider()
        eng, d = engine(prov)
        d.glossary_add("Fireball", "Огненный шар", "en", "ru")
        pr = project(["Cast Fireball at the enemy"])
        eng.translate_batch(pr.entries)
        self.assertEqual(prov.requests[0].glossary, {"Fireball": "Огненный шар"})
        self.assertTrue(any("Огненный шар" in w for w in pr.entries[0].validation_warnings))   # ответ термин не использовал

    def test_chunking(self):
        self.assertEqual(make_chunks(list("abcde"), 2, 100), [["a", "b"], ["c", "d"], ["e"]])
        self.assertEqual(make_chunks(["aaaa", "bbbb", "cc"], 10, 6), [["aaaa"], ["bbbb", "cc"]])

    def test_async_run_cancel_emits_once_and_blocks_restart(self):
        prov = FakeProvider(delay=0.15)
        eng, _ = engine(prov, batch_size=1)
        eng.options.workers = 1
        events = []
        eng.cancelled.connect(lambda: events.append("cancelled"))
        eng.finished.connect(lambda p: events.append("finished"))
        eng.error.connect(lambda m: events.append("error"))
        pr = project([f"T{i}" for i in range(30)])
        self.assertTrue(eng.run_async(pr))
        time.sleep(0.2)
        eng.cancel()
        self.assertFalse(eng.run_async(pr))                                      # ещё не остановился
        self.assertTrue(eng.is_cancelling())
        for _ in range(100):
            if not eng.is_running():
                break
            time.sleep(0.05)
        self.assertFalse(eng.is_running())
        self.assertEqual(events, ["cancelled"])                                  # ровно один сигнал
        done = sum(1 for e in pr.entries if e.is_translated())
        self.assertTrue(0 < done < 30)
        self.assertTrue(eng.run_async(pr))                                       # теперь можно снова
        eng.cancel()
        for _ in range(100):
            if not eng.is_running():
                break
            time.sleep(0.05)

    def test_async_finished_and_progress_fields(self):
        eng, _ = engine(FakeProvider(), batch_size=2)
        seen, updates = [], []
        eng.progress.connect(seen.append)
        eng.entries_updated.connect(updates.extend)
        eng.finished.connect(lambda p: seen.append("fin"))
        pr = project([f"T{i}" for i in range(6)])
        eng.run_async(pr)
        for _ in range(100):
            if not eng.is_running():
                break
            time.sleep(0.05)
        self.assertEqual(seen[-1], "fin")
        pgs = [s for s in seen if s != "fin"]
        self.assertEqual(pgs[-1].stage, "done")
        self.assertEqual(pgs[-1].percent, 100)
        self.assertGreater(pgs[-1].chars_sent, 0)
        self.assertEqual(sorted(set(updates)), [f"h{i}" for i in range(6)])
        self.assertEqual(pr.translated_entries, 6)


if __name__ == "__main__":
    unittest.main()
