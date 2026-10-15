"""Тесты логики интерфейса без Qt: фильтры, правки, поиск-замена, оценка, подсветка."""
import re
import unittest

import _stubs  # noqa: F401
from bg3_translator.core.validation import find_spans
from bg3_translator.models.translation import TranslationEntry, TranslationProject, TranslationStatus, ModMetadata
from bg3_translator.ui import logic


def entry(h, src, tgt="", status=None):
    e = TranslationEntry(handle=h, source_text=src, source_language="en", target_language="ru")
    if tgt:
        e.target_text = tgt
        e.status = status or TranslationStatus.TRANSLATED
    return e


class FakeDict:
    def __init__(self, known):
        self.known = known

    def lookup_many(self, texts, src, tgt, bump=True):
        return {t: object() for t in texts if t in self.known}


class SpansTests(unittest.TestCase):
    def test_spans_cover_tags_and_format(self):
        text = 'A <LSTag Type="X">b</LSTag> {0}<br>'
        spans = find_spans(text)
        self.assertEqual([text[s:e] for s, e in spans], ['<LSTag Type="X">', "</LSTag>", "{0}", "<br>"])

    def test_no_placeholders(self):
        self.assertEqual(find_spans("plain text"), [])


class FilterTests(unittest.TestCase):
    def test_modes(self):
        new = entry("a", "Hello")
        done = entry("b", "Bye", "Пока")
        review = entry("c", "Hi", "Привет", TranslationStatus.NEEDS_REVIEW)
        bad = entry("d", "Gold {0}", "Золото")
        logic.revalidate(bad)
        self.assertTrue(logic.entry_matches(new, "", "untranslated"))
        self.assertFalse(logic.entry_matches(done, "", "untranslated"))
        self.assertTrue(logic.entry_matches(done, "", "translated"))
        self.assertTrue(logic.entry_matches(review, "", "review"))
        self.assertTrue(logic.entry_matches(bad, "", "errors"))
        self.assertFalse(logic.entry_matches(done, "", "errors"))

    def test_search_in_source_target_handle(self):
        e = entry("hKEY1", "Fire bolt", "Огненная стрела")
        for needle in ("fire", "огнен", "key1"):
            self.assertTrue(logic.entry_matches(e, needle, "all"), needle)
        self.assertFalse(logic.entry_matches(e, "water", "all"))

    def test_row_tone_and_label(self):
        bad = entry("d", "Gold {0}", "Золото")
        logic.revalidate(bad)
        self.assertEqual(logic.row_tone(bad), "error")
        self.assertEqual(logic.status_label(bad), "✖ Ошибка")
        self.assertEqual(logic.row_tone(entry("n", "x")), "new")


class EditTests(unittest.TestCase):
    def test_set_target_updates_status_and_validation(self):
        e = entry("a", "Gold {0}")
        self.assertTrue(logic.set_target(e, "Золото {0}"))
        self.assertEqual(e.status, TranslationStatus.TRANSLATED)
        self.assertEqual(e.validation_errors, [])
        self.assertTrue(logic.set_target(e, "Золото"))
        self.assertTrue(e.validation_errors)
        self.assertTrue(logic.set_target(e, ""))
        self.assertEqual(e.status, TranslationStatus.NEW)
        self.assertEqual(e.validation_errors, [])

    def test_same_text_is_noop(self):
        e = entry("a", "Hi", "Привет")
        self.assertFalse(logic.set_target(e, "Привет"))
        self.assertTrue(logic.set_target(e, "Привет", TranslationStatus.APPROVED))

    def test_find_replace_and_undo(self):
        es = [entry("a", "x", "Огненный шар"), entry("b", "y", "Шар молнии"), entry("c", "z", "Лёд")]
        project = TranslationProject(metadata=ModMetadata(name="m"), entries=es)
        rx = logic.compile_find("шар", case=False)
        self.assertEqual(len(logic.find_in_entries(es, rx)), 2)
        history = logic.replace_in_entries(es, rx, "сфера")
        self.assertEqual(len(history), 2)
        self.assertEqual(es[0].target_text, "Огненный сфера")
        self.assertEqual(logic.undo_history(project, history), 2)
        self.assertEqual(es[0].target_text, "Огненный шар")
        self.assertEqual(es[1].target_text, "Шар молнии")

    def test_regex_and_whole_word(self):
        es = [entry("a", "x", "кот и котёл")]
        rx = logic.compile_find("кот", whole=True)
        logic.replace_in_entries(es, rx, "пёс")
        self.assertEqual(es[0].target_text, "пёс и котёл")
        rx = logic.compile_find(r"(\w+) и (\w+)", regex=True)
        logic.replace_in_entries(es, rx, r"\2 и \1", regex=True)
        self.assertEqual(es[0].target_text, "котёл и пёс")

    def test_bad_regex_raises(self):
        with self.assertRaises(re.error):
            logic.compile_find("(", regex=True)
        with self.assertRaises(ValueError):
            logic.compile_find("")

    def test_replace_keeps_approved(self):
        e = entry("a", "x", "шар", TranslationStatus.APPROVED)
        logic.replace_in_entries([e], logic.compile_find("шар"), "сфера")
        self.assertEqual(e.status, TranslationStatus.APPROVED)


class EstimateTests(unittest.TestCase):
    def test_estimate_counts_unique_and_dictionary(self):
        es = [entry("1", "Hello"), entry("2", "Hello"), entry("3", "Bye"),
              entry("4", "Done", "Готово"), entry("5", "   ")]
        est = logic.estimate_job(es, FakeDict({"Bye"}), batch_size=2)
        self.assertEqual(est.untranslated, 3)
        self.assertEqual(est.unique, 2)
        self.assertEqual(est.from_dictionary, 1)
        self.assertEqual(est.to_translate, 1)
        self.assertEqual(est.requests, 1)
        self.assertTrue(est.needs_provider)

    def test_requests_follow_batch_size(self):
        es = [entry(str(i), f"text {i}") for i in range(10)]
        self.assertEqual(logic.estimate_job(es, None, batch_size=3).requests, 4)

    def test_format_duration(self):
        self.assertEqual(logic.format_duration(0), "—")
        self.assertEqual(logic.format_duration(59), "59 с")
        self.assertEqual(logic.format_duration(125), "2 мин 05 с")
        self.assertEqual(logic.format_duration(3700), "1 ч 01 мин")

    def test_export_summary(self):
        es = [entry("a", "x", "y"), entry("b", "z")]
        p = TranslationProject(metadata=ModMetadata(name="m"), entries=es)
        s = logic.export_summary(p)
        self.assertEqual((s["total"], s["translated"], s["untranslated"]), (2, 1, 1))


if __name__ == "__main__":
    unittest.main()
