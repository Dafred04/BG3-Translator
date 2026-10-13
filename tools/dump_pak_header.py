"""Decode .loca binary (LSLib LOCA format): entries + text extraction."""
import struct

PATH = "C:/Users/user/Desktop/unique_tav.pak"

import sys
sys.path.insert(0, "src")
from bg3_translator.core.pak import PakReader

pak = PakReader(PATH)
for target in ("Localization/English/KAZSTRA_UniqueTav.loca",
               "Localization/English/KAZSTRA_UniqueTav.xml"):
    e = next(x for x in pak.entries if x.name == target)
    data = pak.read_file(e)
    print("=" * 30, target, len(data))
    print("head hex:", data[:64].hex(" "))
    print("head ascii:", data[:64])
pak.close()







