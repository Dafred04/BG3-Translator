"""Совместимый слой над services.importer (старый API scan_folder/find_mods)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from ..models.translation import TranslationEntry


@dataclass
class ModScan:
    mod_name: str
    source_path: Path
    entries: List[TranslationEntry] = field(default_factory=list)
    diagnostics: List[str] = field(default_factory=list)
    unsupported: List[str] = field(default_factory=list)
    total_files: int = 0
    supported: int = 0


def scan_folder(root: Path, max_depth: int = 4, source_lang: str = "en", target_lang: str = "ru") -> ModScan:
    from ..services.importer import ImportFailure, import_mod
    root = Path(root)
    scan = ModScan(mod_name=root.name or "unnamed", source_path=root)
    try:
        res = import_mod(root, source_lang, target_lang)
    except ImportFailure as exc:
        scan.diagnostics.append(str(exc))
        return scan
    scan.entries = res.entries
    scan.diagnostics = res.diagnostics
    scan.mod_name = res.metadata.name
    scan.total_files = scan.supported = len({e.context for e in res.entries})
    return scan


def find_mods(root: Path) -> List[ModScan]:
    """Подпапки root, в которых нашлись тексты."""
    results = []
    for item in sorted(Path(root).iterdir(), key=lambda p: p.name.lower()):
        if item.is_dir():
            scan = scan_folder(item)
            if scan.entries:
                results.append(scan)
    return results
