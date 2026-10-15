import tempfile
import time
import unittest
import zipfile
from pathlib import Path

import _stubs  # noqa: F401
from bg3_translator.core.locaxml import build_loca_binary, build_loca_xml, parse_loca_binary
from bg3_translator.core.meta import ModMeta, build_meta_lsx, parse_meta_lsx
from bg3_translator.core.pak import PakReader, write_pak
from bg3_translator.models.translation import (
    DictionaryEntry, TranslationEntry, TranslationStatus,
)
from bg3_translator.services import exporter
from bg3_translator.services.dictionary import DictionaryStore
from bg3_translator.services.importer import (
    ImportFailure, apply_translation_file, import_mod,
)

EN = [("hA", "Hello <br>world", 2),
      ("hB", 'Cast <LSTag Type="Spell" Tooltip="Fire">Fireball</LSTag> now', 2),
      ("hC", "Third line", 1)]
RU = [("hA", "Привет <br>мир", 2), ("hB", 'Брось <LSTag Type="Spell" Tooltip="Fire">Огненный шар</LSTag>', 1)]
ORIG_META = ModMeta(name="Cool Mod", author="Me", folder="CoolMod", uuid="aaaaaaaa-0000-0000-0000-000000000001",
                    version64=36028797018963968 + 5)


def make_pak(path: Path, *, with_ru=True, with_dup_xml=True, bad_xml=False) -> Path:
    files = {
        "Mods/CoolMod/meta.lsx": build_meta_lsx(ORIG_META).encode(),
        "Localization/English/CoolMod.loca": build_loca_binary(EN),
    }
    if with_dup_xml:
        files["Localization/English/CoolMod.xml"] = build_loca_xml(EN).encode()
    if with_ru:
        files["Localization/Russian/CoolMod.loca"] = build_loca_binary(RU)
    if bad_xml:
        files["Localization/English/Broken.xml"] = b"<contentList><content"
    return write_pak(path, files)


class ImporterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_pak_import_dedupes_picks_language_and_prefills(self):
        res = import_mod(make_pak(self.tmp / "m.pak"), "en", "ru")
        self.assertEqual([e.handle for e in res.entries], ["hA", "hB", "hC"])      # без дублей loca+xml
        self.assertEqual((res.source_folder, res.target_folder), ("English", "Russian"))
        self.assertEqual(res.prefilled, 2)
        by = {e.handle: e for e in res.entries}
        self.assertEqual(by["hA"].status, TranslationStatus.TRANSLATED)
        self.assertEqual(by["hB"].status, TranslationStatus.NEEDS_REVIEW)           # версия перевода старее
        self.assertEqual(by["hC"].status, TranslationStatus.NEW)
        self.assertEqual(by["hA"].version, 2)
        self.assertEqual(res.metadata.name, "Cool Mod")
        self.assertEqual(res.metadata.original_mod_folder, "CoolMod")
        self.assertEqual(res.metadata.version, "1.0.0.5")

    def test_other_languages_are_not_mixed_in(self):
        p = write_pak(self.tmp / "m.pak", {
            "Localization/English/a.loca": build_loca_binary([("h1", "One", 1)]),
            "Localization/French/a.loca": build_loca_binary([("h9", "Un", 1)])})
        res = import_mod(p, "en", "ru")
        self.assertEqual([e.handle for e in res.entries], ["h1"])
        self.assertEqual(res.languages, ["English", "French"])

    def test_zip_and_folder_and_single_file(self):
        pak = make_pak(self.tmp / "m.pak", with_ru=False)
        with PakReader(pak) as r:
            files = {n: r.read_named(n) for n in r.names()}
        zp = self.tmp / "m.zip"
        with zipfile.ZipFile(zp, "w") as z:
            for n, d in files.items():
                z.writestr(n, d)
        folder = self.tmp / "extracted"
        for n, d in files.items():
            (folder / n).parent.mkdir(parents=True, exist_ok=True)
            (folder / n).write_bytes(d)
        for src in (zp, folder):
            self.assertEqual(len(import_mod(src).entries), 3, src)
        single = self.tmp / "only.loca"
        single.write_bytes(build_loca_binary(EN))
        self.assertEqual(len(import_mod(single).entries), 3)

    def test_broken_file_is_reported_not_fatal(self):
        res = import_mod(make_pak(self.tmp / "m.pak", bad_xml=True))
        self.assertEqual(len(res.entries), 3)
        self.assertTrue(any("Broken.xml" in d for d in res.diagnostics))

    def test_no_loca_raises_friendly_error(self):
        p = write_pak(self.tmp / "e.pak", {"Mods/X/meta.lsx": build_meta_lsx(ORIG_META).encode()})
        with self.assertRaises(ImportFailure):
            import_mod(p)
        with self.assertRaises(ImportFailure):
            import_mod(self.tmp / "missing.pak")

    def test_apply_translation_file_update_mode(self):
        res = import_mod(make_pak(self.tmp / "m.pak", with_ru=False))
        project = res.to_project("en", "ru")
        tr = self.tmp / "ru.loca"
        tr.write_bytes(build_loca_binary(RU))
        filled, review = apply_translation_file(project, tr)
        self.assertEqual((filled, review), (2, 1))
        self.assertEqual(project.translated_entries, 2)


class ExporterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.project = import_mod(make_pak(self.tmp / "m.pak", with_ru=False)).to_project("en", "ru")

    def test_pak_contains_loca_and_meta_with_dependency(self):
        for e in self.project.entries[:2]:
            e.target_text, e.status = "РУ " + e.source_text, TranslationStatus.TRANSLATED
        self.project.update_stats()
        out = exporter.export_pak(self.project, self.tmp / "out.pak")
        self.assertEqual(out.name, "out.pak")
        with PakReader(out) as r:
            self.assertEqual(sorted(r.names()),
                             ["Localization/Russian/CoolMod_Russian.loca", "Mods/CoolMod_Russian/meta.lsx"])
            parsed = parse_loca_binary(r.read_named("Localization/Russian/CoolMod_Russian.loca"))
            meta = parse_meta_lsx(r.read_named("Mods/CoolMod_Russian/meta.lsx").decode())
        d = dict(parsed.entries)
        self.assertTrue(d["hA"].startswith("РУ "))
        self.assertEqual(d["hC"], "Third line")                         # fallback на оригинал
        self.assertEqual(parsed.versions["hA"], 2)                      # версия сохранена
        self.assertEqual(meta.folder, "CoolMod_Russian")
        self.assertEqual(meta.dependencies[0].uuid, ORIG_META.uuid)
        self.assertNotEqual(meta.uuid, ORIG_META.uuid)

    def test_only_translated_and_report(self):
        self.project.entries[0].target_text = "x"
        self.project.entries[0].status = TranslationStatus.TRANSLATED
        self.assertEqual(len(exporter.collect_entries(self.project, fallback_to_source=False)), 1)
        rep = exporter.report(self.project)
        self.assertEqual((rep.total, rep.translated, rep.untranslated), (3, 1, 2))


class DictionaryTests(unittest.TestCase):
    def setUp(self):
        self.d = DictionaryStore(Path(tempfile.mkdtemp()) / "d.db")

    def entry(self, s, t, verified=False):
        return DictionaryEntry(source_text=s, source_language="en", target_text=t,
                               target_language="ru", verified=verified)

    def test_verified_is_not_overwritten_by_auto_translation(self):
        self.d.add(self.entry("Hello", "Привет", verified=True))
        self.d.add(self.entry("Hello", "Здрасьте", verified=False))
        self.assertEqual(self.d.lookup("Hello", "en", "ru").target_text, "Привет")
        self.d.add(self.entry("Hello", "Приветствую", verified=True))       # человек может перезаписать
        self.assertEqual(self.d.lookup("Hello", "en", "ru").target_text, "Приветствую")

    def test_lookup_many_case_insensitive_and_usage(self):
        self.d.add_many([self.entry("Fire", "Огонь"), self.entry("Ice", "Лёд")])
        got = self.d.lookup_many(["Fire", "Ice", "Wind"], "en", "ru")
        self.assertEqual(set(got), {"Fire", "Ice"})
        self.assertEqual(self.d.lookup("  fire ", "en", "ru").target_text, "Огонь")
        self.assertEqual(self.d.lookup("Fire", "en", "ru").usage_count, 2)

    def test_search_escapes_wildcards_and_target(self):
        self.d.add_many([self.entry("100% sure", "уверен"), self.entry("abc", "xyz")])
        self.assertEqual([e.source_text for e in self.d.search("%")], ["100% sure"])
        self.assertEqual(len(self.d.search("xyz", in_target=True)), 1)
        self.assertEqual(len(self.d.search("xyz")), 0)

    def test_fuzzy(self):
        self.d.add(self.entry("You have found a hidden treasure chest", "Вы нашли сундук"))
        hit = self.d.lookup_fuzzy("You have found a hidden treasure chests", "en", "ru", 0.9)
        self.assertIsNotNone(hit)
        self.assertGreater(hit[1], 0.9)
        self.assertIsNone(self.d.lookup_fuzzy("Completely different sentence here", "en", "ru", 0.9))

    def test_csv_roundtrip_and_delete_update(self):
        self.d.add(self.entry("A word", "Слово", verified=True))
        path = Path(tempfile.mkdtemp()) / "x.csv"
        self.assertEqual(self.d.export_csv(path), 1)
        d2 = DictionaryStore(Path(tempfile.mkdtemp()) / "d2.db")
        self.assertEqual(d2.import_csv(path), 1)
        self.assertTrue(d2.lookup("A word", "en", "ru").verified)
        self.assertTrue(d2.update_target("A word", "en", "ru", "Слово!"))
        self.assertTrue(d2.delete_by_source("A word", "en", "ru"))
        self.assertEqual(d2.count(), 0)

    def test_glossary_matching(self):
        self.d.glossary_add("Wild Magic", "Дикая магия", "en", "ru")
        self.d.glossary_add("Fire", "Огонь", "en", "ru")
        got = self.d.glossary_for("The wild magic surge, Firebolt and FIRE", "en", "ru")
        self.assertEqual(sorted(got.values()), ["Дикая магия", "Огонь"])        # Firebolt не считается
        self.d.glossary_delete("Fire", "en", "ru")
        self.assertEqual(len(self.d.glossary_for("fire", "en", "ru")), 0)


if __name__ == "__main__":
    unittest.main()
