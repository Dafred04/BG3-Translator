"""M6 smoke test: pak write -> read -> extract round-trip + ImportWorker integration."""
import sys, os, pathlib, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from bg3_translator.core.pak import PakReader, write_pak, extract_pak, PakError

XML_CONTENT = ('<?xml version="1.0" encoding="utf-8"?>'
               '<content root="ResourceList">'
               '<version major="1" minor="0" revision="0" build="0"/>'
               '<contentList>'
               '<translated_string handle="h1"><content str="Hello"/></translated_string>'
               '<translated_string handle="h2"><content str="World &amp; Co"/></translated_string>'
               '</contentList></content>')

def test_roundtrip(tmp: pathlib.Path):
    pak_path = tmp / "test.pak"
    xml = XML_CONTENT.encode("utf-8")
    small = b"x"
    big = (b"repeat " * 5000)

    files = {
        "Public/Localization/Test/Localization.loc": xml,
        "small.bin": small,
        "big.bin": big,
    }
    write_pak(pak_path, files, compress=True)

    with PakReader(pak_path) as pak:
        names = sorted(e.name for e in pak.entries)
        assert names == sorted(files.keys()), names
        by_name = {e.name: e for e in pak.entries}
        assert by_name["big.bin"].is_compressed
        assert pak.read_file(by_name["big.bin"]) == big
        assert not by_name["small.bin"].is_compressed
        assert pak.read_file(by_name["small.bin"]) == small
        got = pak.read_file(by_name["Public/Localization/Test/Localization.loc"])
        from bg3_translator.core.locaxml import parse_loca_xml
        parsed = parse_loca_xml(got.decode("utf-8"))
        assert parsed.entries == [("h1", "Hello"), ("h2", "World & Co")]

    out = tmp / "extracted"
    n = extract_pak(pak_path, out)
    assert n == 3
    assert (out / "small.bin").read_bytes() == small
    print("pak round-trip: OK")

def test_bad_signature(tmp: pathlib.Path):
    bad = tmp / "bad.pak"
    bad.write_bytes(b"NOTA" + b"\x00" * 60)
    try:
        PakReader(bad)
        raise AssertionError("should have raised")
    except PakError as exc:
        assert "signature" in str(exc).lower()
    print("pak bad signature: OK")

def test_import_worker_pak(tmp: pathlib.Path):
    """End-to-end: write pak -> ImportWorker loads project from it."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    pak_path = tmp / "mod.pak"
    write_pak(pak_path, {
        "Public/MyMod/Localization/MyMod.loc": XML_CONTENT.encode("utf-8"),
    })

    from bg3_translator.ui.pages.editor import ImportWorker
    worker = ImportWorker(str(pak_path), False, "en", "zh")
    project = worker._import()
    assert project.total_entries == 2, project.total_entries
    handles = [e.handle for e in project.entries]
    assert handles == ["h1", "h2"]
    assert project.entries[0].source_text == "Hello"
    assert project.entries[1].source_text == "World & Co"

    # zip import
    import zipfile
    zip_path = tmp / "mod.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("Data/loc.xml", XML_CONTENT)
    worker2 = ImportWorker(str(zip_path), False, "en", "ru")
    project2 = worker2._import()
    assert project2.total_entries == 2
    assert project2.target_language == "ru"
    print("ImportWorker pak+zip: OK")

if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        test_roundtrip(tmp)
        test_bad_signature(tmp)
        test_import_worker_pak(tmp)
    print("M6 pak tests passed")