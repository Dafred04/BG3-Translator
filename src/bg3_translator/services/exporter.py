"""Экспорт перевода: .loca (бинарный), XML, готовый .pak с meta.lsx."""

from __future__ import annotations

import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..core.languages import folder_for, name_for
from ..core.locaxml import build_loca_binary, build_loca_xml
from ..core.meta import Dependency, ModMeta, build_meta_lsx, version_string_to_64
from ..core.pak import write_pak
from ..models.translation import TranslationProject


@dataclass
class ExportReport:
    total: int
    translated: int
    untranslated: int
    with_errors: int
    with_warnings: int


def report(project: TranslationProject) -> ExportReport:
    es = project.entries
    tr = sum(1 for e in es if e.is_translated())
    return ExportReport(len(es), tr, len(es) - tr,
                        sum(1 for e in es if e.validation_errors),
                        sum(1 for e in es if e.validation_warnings))


def collect_entries(project: TranslationProject, fallback_to_source: bool = True
                    ) -> List[Tuple[str, str, int]]:
    """(handle, text, version). Непереведённое — оригинал, если fallback_to_source."""
    out = []
    for e in project.entries:
        if e.is_translated():
            out.append((e.handle, e.target_text, e.version))
        elif fallback_to_source:
            out.append((e.handle, e.source_text, e.version))
    return out


def safe_name(s: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", s, flags=re.UNICODE).strip("_") or "mod"


def translation_folder(project: TranslationProject) -> str:
    base = project.metadata.folder or safe_name(project.metadata.name)
    return f"{base}_{folder_for(project.target_language)}"


def default_pak_name(project: TranslationProject) -> str:
    return f"{translation_folder(project)}.pak"


def export_loca_bytes(project: TranslationProject, fallback_to_source: bool = True) -> bytes:
    return build_loca_binary(collect_entries(project, fallback_to_source))


def export_xml_text(project: TranslationProject, fallback_to_source: bool = True) -> str:
    return build_loca_xml(collect_entries(project, fallback_to_source))


def build_translation_meta(project: TranslationProject) -> ModMeta:
    m = project.metadata
    lang = name_for(project.target_language)
    meta = ModMeta(
        name=f"{m.name} [{lang}]",
        author=m.author or "",
        description=f"Перевод мода «{m.name}» на {lang}. Создано BG3 Mod Translator.",
        folder=translation_folder(project),
        uuid=m.uuid or str(uuid.uuid4()),
        version64=version_string_to_64(m.version),
    )
    if m.original_mod_uuid and m.original_mod_folder:
        meta.dependencies.append(Dependency(
            name=m.name, folder=m.original_mod_folder, uuid=m.original_mod_uuid,
            version64=version_string_to_64(m.version)))
    return meta


def build_pak_files(project: TranslationProject, fallback_to_source: bool = True) -> Dict[str, bytes]:
    folder = translation_folder(project)
    lang = folder_for(project.target_language)
    meta = build_translation_meta(project)
    return {
        f"Mods/{folder}/meta.lsx": build_meta_lsx(meta).encode("utf-8"),
        f"Localization/{lang}/{folder}.loca": export_loca_bytes(project, fallback_to_source),
    }


def export_pak(project: TranslationProject, out_path, fallback_to_source: bool = True) -> Path:
    return write_pak(Path(out_path), build_pak_files(project, fallback_to_source))


def mods_folder() -> Optional[Path]:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return None
    return Path(base) / "Larian Studios" / "Baldur's Gate 3" / "Mods"


def install_pak(pak_path) -> Path:
    """Копирует пак в папку модов BG3. Включить мод нужно в менеджере модов."""
    dest_dir = mods_folder()
    if dest_dir is None:
        raise RuntimeError("Папка модов BG3 не найдена (поддерживается только Windows)")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(pak_path).name
    shutil.copyfile(pak_path, dest)
    return dest
