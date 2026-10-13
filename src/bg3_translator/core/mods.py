"""Mod source detection & text extraction.

Unified view of supported mod inputs:
  .pak        (BG3 LSPK v18, LZ4/Zlib/Zstd)
  .zip        (any zip)
  .xml/.loca  (single localization file)
  folder      (already extracted mod)

Every path yields a list of (handle, source_text) entries plus parse diagnostics.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from ..core.locaxml import parse_loca_xml
from ..core.loca import LocaError, read_loca
from ..core.pak import PakError, PakReader
from ..models.translation import EntryType, TranslationEntry

# (suffix, confidence, label)
KNOWN_EXT = (
    (".pak", 1.0, "BG3 package (.pak)"),
    (".zip", 0.9, "Zip archive"),
    (".xpk", 0.7, "XPACK package"),
    (".xml", 0.8, "Localization XML"),
    (".loca", 0.95, "BG3 binary localization (.loca)"),
    (".json", 0.3, "JSON"),
    (".lua", 0.1, "Lua"),
)

UNKNOWN = (".bin", 0.05, "Binary")
SUPPORTED_TEXT_EXT = (".xml", ".loca", ".json", ".txt", ".lua")


@dataclass
class FileCandidate:
    path: Path
    handle_hint: str = ""
    kind: str = "unknown"
    text: str = ""          # extracted text (if known)
    diagnostic: str = ""    # error/warning for this file


@dataclass
class ModScan:
    mod_name: str
    source_path: Path
    entries: List[TranslationEntry] = field(default_factory=list)
    diagnostics: List[str] = field(default_factory=list)
    unsupported: List[str] = field(default_factory=list)
    total_files: int = 0
    supported: int = 0


def _is_hidden(path: Path) -> bool:
    name = path.name.lower()
    return name.startswith((".", "~$")) or "desktop.ini" in name


def is_supported(path: Path, depth: int = 0) -> Tuple[bool, float]:
    """Return (supported, confidence). Depth limit prevents folder recursion blowups."""
    suffix = path.suffix.lower()
    for ext, conf, _ in KNOWN_EXT:
        if suffix == ext:
            return True, conf
    return False, 0.0


def scan_folder(root: Path, max_depth: int = 4) -> ModScan:
    """Walk a folder, classify files, extract text where supported."""
    scan = ModScan(mod_name=root.name or "unnamed", source_path=root)
    stack = [(root, 0)]
    while stack:
        cur, depth = stack.pop()
        if depth > max_depth:
            continue
        try:
            children = sorted(cur.iterdir(), key=lambda p: p.name.lower())
        except PermissionError as exc:
            scan.diagnostics.append(f"Не удалось открыть {cur}: {exc}")
            continue
        for child in children:
            if _is_hidden(child):
                continue
            if child.is_dir():
                stack.append((child, depth + 1))
                continue
            if child.is_file():
                scan.total_files += 1
                supported, _ = is_supported(child)
                if supported:
                    scan.supported += 1
                    text = extract_text(child)
                    if text is not None:
                        scan.entries.append(TranslationEntry(
                            handle=str(child.name),
                            source_text=text,
                            source_language="en",
                            target_language="ru",
                            context=str(child.relative_to(root)),
                            entry_type=EntryType.TEXT,
                        ))
                    else:
                        scan.diagnostics.append(f"Файл не содержит текста: {child.name}")
                else:
                    scan.unsupported.append(f"{child.name} ({child.suffix or 'no-extension'})")
    return scan


def extract_text(path: Path) -> Optional[str]:
    """Return readable text from a file if it looks like localization."""
    suffix = path.suffix.lower()
    if suffix == ".xml":
        return _read_xml_text(path)
    if suffix == ".loca":
        return _read_loca_text(path)
    if suffix == ".json":
        return _read_json_text(path)
    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    if suffix == ".lua":
        return _read_lua_text(path)
    return None


def _read_xml_text(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    if "<content" in text and ("handle" in text or "contentuid" in text):
        return text
    return None


def _read_loca_text(path: Path) -> Optional[str]:
    try:
        res = read_loca(path.read_bytes())
    except LocaError as exc:
        return None
    return "\n".join(f"{e.key}: {e.text}" for e in res.entries)


def _read_json_text(path: Path) -> str:
    try:
        import json
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return str(data)


def _read_lua_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return None


def find_mods(root: Path) -> List[ModScan]:
    """Top-level discovery: returns folders that look like mod sources."""
    results = []
    for item in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not item.is_dir():
            continue
        scan = scan_folder(item)
        if scan.total_files > 0:
            results.append(scan)
    return results
