"""Dump LocaReader.Read body: how entry offsets/texts are located."""
import urllib.request

BASE = "https://raw.githubusercontent.com/Norbyte/lslib/master/LSLib/LS/"
text = urllib.request.urlopen(BASE + "Localization.cs", timeout=30).read().decode("utf-8", "replace")
idx = text.find("public LocaResource Read")
print(text[idx:idx + 3500].encode("ascii", "replace").decode())





