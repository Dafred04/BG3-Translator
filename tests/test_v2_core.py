import json
import struct
import tempfile
import unittest
from pathlib import Path

import _stubs  # noqa: F401
from bg3_translator.core import pak as pakmod
from bg3_translator.core.loca import LocaResource, LocaText, read_loca, write_loca
from bg3_translator.core.locaxml import (
    build_loca_binary, build_loca_xml, parse_loca_binary, parse_loca_xml,
)
from bg3_translator.core.meta import (
    Dependency, ModMeta, build_meta_lsx, decode_version64, encode_version64, parse_meta_lsx,
)
from bg3_translator.core.validation import (
    compare_placeholders, extract_placeholders, has_unclosed_tag, qa_check, shield, unshield,
)

SRC = 'Deals <LSTag Type="Status" Tooltip="BURNING">Burning</LSTag> damage.<br>Save: [1]'


class ValidationTests(unittest.TestCase):
    def test_correct_translation_with_lstag_has_no_errors(self):
        """Регресс: раньше этот корректный перевод давал две ошибки."""
        tr = 'Наносит урон <LSTag Type="Status" Tooltip="BURNING">Горение</LSTag>.<br>Спасбросок: [1]'
        self.assertEqual(compare_placeholders(SRC, tr)[0], [])

    def test_missing_br_and_tag_attrs_are_errors(self):
        errs, _ = compare_placeholders(SRC, 'Урон <LSTag Type="Status" Tooltip="BURNING">Горение</LSTag> [1]')
        self.assertTrue(any("<br>" in e for e in errs))
        errs, _ = compare_placeholders(SRC, 'Урон <LSTag Type="Status" Tooltip="WRONG">Горение</LSTag><br>[1]')
        self.assertTrue(errs)

    def test_unclosed_tag_detected(self):
        self.assertTrue(has_unclosed_tag("<LSTag Type='x'>abc"))
        self.assertFalse(has_unclosed_tag("<LSTag Type='x'/>abc"))
        errs, _ = compare_placeholders("a <LSTag Type='x'>b</LSTag>", "а <LSTag Type='x'>б")
        self.assertTrue(any("LSTag" in e for e in errs))

    def test_extract_types(self):
        types_ = [p.type for p in extract_placeholders(SRC)]
        self.assertEqual(types_, ["lstag_open", "lstag_close", "br", "numeric"])

    def test_shield_roundtrip_and_tolerance(self):
        shielded, orig = shield(SRC)
        self.assertNotIn("<", shielded)
        self.assertEqual(len(orig), 4)
        back, problems = unshield(shielded.replace("⟦2⟧", "⟦ 2 ⟧"), orig)
        self.assertEqual((back, problems), (SRC, []))

    def test_unshield_reports_lost_and_stray_tokens(self):
        shielded, orig = shield("a<br>b")
        _, problems = unshield("а б", orig)
        self.assertTrue(problems)
        _, problems = unshield("а ⟦1⟧ ⟦7⟧", orig)
        self.assertTrue(any("Лишние" in p for p in problems))

    def test_alt_token_format(self):
        s, o = shield("x {0} y", "QX{n}XQ")
        self.assertEqual(s, "x QX1XQ y")
        self.assertEqual(unshield("икс QX1XQ игрек", o, "QX{n}XQ")[0], "икс {0} игрек")

    def test_qa(self):
        self.assertIn("Перевод совпадает с оригиналом", qa_check("Fireball spell", "Fireball spell"))
        self.assertTrue(any("английский" in w for w in qa_check("Hello there my friend", "Hello there my friend!")))
        self.assertTrue(any("длиннее" in w for w in qa_check("Short sentence here", "А" * 100)))
        self.assertEqual(qa_check("Hello", "Привет"), [])
        self.assertTrue(qa_check("Cast Fireball", "Бросить шар", glossary={"Fireball": "Огненный шар"}))


class PakTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_roundtrip_with_compression(self):
        big = (b"The quick brown fox jumps over the lazy dog. " * 200)
        files = {"Mods/X/meta.lsx": b"<save/>", "Localization/English/x.loca": big, "empty.txt": b""}
        p = pakmod.write_pak(self.tmp / "a.pak", files)
        with pakmod.PakReader(p) as r:
            self.assertEqual(sorted(r.names()), sorted(files))
            for name, data in files.items():
                self.assertEqual(r.read_named(name), data)
            self.assertTrue(r.find("Localization/English/x.loca").is_compressed)
            self.assertEqual(r.num_parts, 1)

    def test_header_layout_matches_lslib_order(self):
        p = pakmod.write_pak(self.tmp / "h.pak", {"a": b"1"})
        head = p.read_bytes()[:40]
        sig, ver, off, size = struct.unpack("<IIQI", head[:20])
        self.assertEqual((sig, ver), (pakmod.SIGNATURE, 18))
        self.assertEqual(head[20:22], b"\x00\x00")            # flags, priority
        self.assertEqual(struct.unpack_from("<H", head, 38)[0], 1)  # NumParts в конце

    def test_compression_method_uses_low_nibble(self):
        for flags, method in ((0x22, 2), (0x02, 2), (0x03, 3), (0x01, 1), (0x00, 0)):
            e = pakmod.PakEntry("x", 0, 0, flags, 0, 0)
            self.assertEqual(e.compression_method, method)

    def test_path_traversal_blocked(self):
        p = pakmod.write_pak(self.tmp / "evil.pak", {"../evil.txt": b"x"})
        out = self.tmp / "out"
        out.mkdir()
        with pakmod.PakReader(p) as r, self.assertRaises(pakmod.PakError):
            r.extract_all(out)
        self.assertFalse((self.tmp / "evil.txt").exists())

    def test_bad_file_raises_and_closes_handle(self):
        bad = self.tmp / "bad.pak"
        bad.write_bytes(b"NOPE" * 20)
        with self.assertRaises(pakmod.PakError):
            pakmod.PakReader(bad)


class LocaTests(unittest.TestCase):
    def test_binary_roundtrip_unicode_and_versions(self):
        res = LocaResource([LocaText("h1", 3, "Привет, мир"), LocaText("h2", 1, ""), LocaText("h3", 2, "a\nb")])
        back = read_loca(write_loca(res))
        self.assertEqual([(e.key, e.version, e.text) for e in back.entries],
                         [("h1", 3, "Привет, мир"), ("h2", 1, ""), ("h3", 2, "a\nb")])

    def test_xml_default_format_roundtrip(self):
        entries = [("h1", "Line1\nLine2 & <b>", 4), ("h2", 'He said "hi"', 1), ("h3", "<LSTag Type='A'>x</LSTag>", 2)]
        xml = build_loca_xml(entries)
        self.assertIn('<content contentuid="h1" version="4">', xml)
        self.assertNotIn("translated_string", xml)
        parsed = parse_loca_xml(xml)
        self.assertEqual(parsed.entries, [(h, t) for h, t, _v in entries])     # \n сохраняется
        self.assertEqual(parsed.versions, {"h1": 4, "h2": 1, "h3": 2})

    def test_legacy_format_still_readable_and_writable(self):
        xml = build_loca_xml([("h1", "a\nb")], legacy=True)
        self.assertIn("translated_string", xml)
        self.assertEqual(parse_loca_xml(xml).entries, [("h1", "a\nb")])

    def test_binary_xml_equivalence(self):
        entries = [("hA", "One", 1), ("hB", "Two", 2)]
        self.assertEqual(parse_loca_binary(build_loca_binary(entries)).entries,
                         parse_loca_xml(build_loca_xml(entries)).entries)


class MetaTests(unittest.TestCase):
    def test_version64(self):
        v = encode_version64(1, 2, 3, 4)
        self.assertEqual(decode_version64(v), "1.2.3.4")
        self.assertEqual(decode_version64(36028797018963968), "1.0.0.0")

    def test_roundtrip_with_dependency_and_escaping(self):
        m = ModMeta(name='Мод "Тест" & Co', author="A<B", description="d", folder="F_Ru",
                    uuid="11111111-2222-3333-4444-555555555555",
                    dependencies=[Dependency("Orig", "OrigFolder", "99999999-0000-0000-0000-000000000000")])
        back = parse_meta_lsx(build_meta_lsx(m))
        self.assertEqual((back.name, back.author, back.folder, back.uuid), (m.name, m.author, "F_Ru", m.uuid))
        self.assertEqual(back.dependencies[0].folder, "OrigFolder")
        self.assertEqual(back.version, "1.0.0.0")


if __name__ == "__main__":
    unittest.main()
