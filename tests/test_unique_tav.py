"""Regression: real unique_tav.pak -> extract .xml + .loca -> parse texts."""
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from bg3_translator.core.pak import PakReader
from bg3_translator.core.loca import read_loca, write_loca
from bg3_translator.core.locaxml import parse_loca_xml

PAK = "C:/Users/user/Desktop/unique_tav.pak"

pak = PakReader(PAK)
print("entries:", len(pak.entries))
xml_e = next(e for e in pak.entries if e.name.endswith("KAZSTRA_UniqueTav.xml"))
loca_e = next(e for e in pak.entries if e.name.endswith("KAZSTRA_UniqueTav.loca"))

xml_data = pak.read_file(xml_e).decode("utf-8")
parsed = parse_loca_xml(xml_data)
print("xml strings:", len(parsed.entries))

res = read_loca(pak.read_file(loca_e))
print("loca strings:", len(res.entries))
print("loca sample:", [(t.key, t.text[:60]) for t in res.entries[:3]])
pak.close()

# xml and loca must carry the same handles
xml_keys = {h for h, _ in parsed.entries}
loca_keys = {t.key for t in res.entries}
print("key overlap:", len(xml_keys & loca_keys), "/", len(xml_keys | loca_keys))
assert xml_keys == loca_keys, "xml/loca handle mismatch"

# binary round-trip
assert read_loca(write_loca(res)).entries == res.entries
print("loca round-trip: OK")
print("unique_tav regression: PASSED")
