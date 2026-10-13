"""Smoke tests for core layer (M3)."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from bg3_translator.core.validation import extract_placeholders, compare_placeholders
from bg3_translator.core.locaxml import parse_loca_xml, build_loca_xml, LocaVersion

def test_validation():
    src = 'Hello <LSTag>name</LSTag>, you have {0} gold &amp; more [1]'
    tgt_ok = 'Привет <LSTag>name</LSTag>, у тебя {0} золота &amp; ещё [1]'
    e, w = compare_placeholders(src, tgt_ok)
    assert not e and not w, (e, w)

    tgt_bad = 'Привет name'
    e2, _ = compare_placeholders(src, tgt_bad)
    assert len(e2) == 4, e2  # lstag, entity, format, numeric missing

    ph = extract_placeholders(src)
    assert [p.type for p in ph] == ["lstag", "format", "entity", "numeric"], [p.type for p in ph]
    print("validation: OK")

def test_locaxml():
    src = ('<?xml version="1.0" encoding="utf-8"?>'
           '<content root="ResourceList">'
           '<version major="1" minor="2" revision="3" build="4"/>'
           '<contentList>'
           '<translated_string handle="h1"><content str="Hi &amp; bye &lt;tag&gt;"/></translated_string>'
           '<translated_string handle="h2"><content str="Second"/></translated_string>'
           '</contentList></content>')
    p = parse_loca_xml(src)
    assert p.entries == [("h1", "Hi & bye <tag>"), ("h2", "Second")], p.entries
    assert p.version.as_tuple() == (1, 2, 3, 4)

    out = build_loca_xml(p.entries, version=LocaVersion(), source_version=p.version)
    p2 = parse_loca_xml(out)
    assert p2.entries == p.entries, p2.entries
    assert p2.version >= p.version, (p2.version.as_tuple(), p.version.as_tuple())
    print("locaxml: OK")

if __name__ == "__main__":
    test_validation()
    test_locaxml()
    print("M3 smoke tests passed")