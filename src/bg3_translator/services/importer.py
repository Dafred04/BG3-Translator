"""Единый импорт модов: .pak, .zip, папка, одиночный .xml/.loca.

Читает всё прямо из архива в память (без распаковки на диск), выбирает язык-источник,
понимает meta.lsx и подхватывает уже существующий перевод (режим обновления мода).
"""

from __future__ import annotations

import logging
import os
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from ..core.languages import code_for_folder, folder_for
from ..core.locaxml import ParsedLoca, parse_loca_binary, parse_loca_xml
from ..core.meta import ModMeta, parse_meta_lsx
from ..core.pak import PakReader
from ..core.validation import compare_placeholders
from ..models.translation import ModMetadata, TranslationEntry, TranslationProject, TranslationStatus

log = logging.getLogger(__name__)

MAX_FILE_BYTES = 128 * 1024 * 1024
LOC_EXT = (".loca", ".xml", ".loc")
LOC_RE = re.compile(r"(?:^|/)localization/([^/]+)/([^/]+)\.(loca|xml|loc)$", re.IGNORECASE)
META_RE = re.compile(r"(?:^|/)mods/[^/]+/meta\.lsx$", re.IGNORECASE)


class ImportFailure(Exception):
    """Понятная пользователю причина, по которой мод не импортирован."""


# ---------------------------------------------------------------------------
# Источники файлов
# ---------------------------------------------------------------------------
class ModSource:
    def names(self) -> List[str]: ...
    def read(self, name: str) -> bytes: ...
    def close(self) -> None: ...

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class PakSource(ModSource):
    def __init__(self, path: Path):
        self._pak = PakReader(path)

    def names(self):
        return self._pak.names()

    def read(self, name):
        entry = self._pak.find(name)
        if entry and entry.uncompressed_size > MAX_FILE_BYTES:
            raise ImportFailure(f"Файл слишком большой: {name}")
        return self._pak.read_named(name)

    def close(self):
        self._pak.close()


class ZipSource(ModSource):
    def __init__(self, path: Path):
        self._zf = zipfile.ZipFile(path)
        self._map = {i.filename.replace("\\", "/"): i for i in self._zf.infolist() if not i.is_dir()}

    def names(self):
        return list(self._map)

    def read(self, name):
        info = self._map[name]
        if info.file_size > MAX_FILE_BYTES:
            raise ImportFailure(f"Файл слишком большой: {name}")
        return self._zf.read(info)

    def close(self):
        self._zf.close()


class DirSource(ModSource):
    def __init__(self, root: Path, max_files: int = 200_000):
        self.root = Path(root)
        self._names: List[str] = []
        for dirpath, _dirs, files in os.walk(self.root):
            for f in files:
                self._names.append(Path(dirpath, f).relative_to(self.root).as_posix())
                if len(self._names) > max_files:
                    raise ImportFailure("В папке слишком много файлов")

    def names(self):
        return self._names

    def read(self, name):
        p = self.root / name
        if p.stat().st_size > MAX_FILE_BYTES:
            raise ImportFailure(f"Файл слишком большой: {name}")
        return p.read_bytes()

    def close(self):
        pass


class FileSource(ModSource):
    def __init__(self, path: Path):
        self.path = Path(path)

    def names(self):
        return [self.path.name]

    def read(self, name):
        return self.path.read_bytes()

    def close(self):
        pass


def open_source(path: Path) -> ModSource:
    path = Path(path)
    if path.is_dir():
        return DirSource(path)
    suffix = path.suffix.lower()
    if suffix == ".pak":
        return PakSource(path)
    if suffix == ".zip":
        return ZipSource(path)
    if suffix in LOC_EXT:
        return FileSource(path)
    raise ImportFailure(f"Неподдерживаемый тип файла: {path.suffix or path.name}")


# ---------------------------------------------------------------------------
# Разбор локализаций
# ---------------------------------------------------------------------------
def _parse_loc_file(data: bytes, name: str) -> ParsedLoca:
    if name.lower().endswith(".loca"):
        return parse_loca_binary(data)
    return parse_loca_xml(data.decode("utf-8-sig", errors="replace"))


def _group_by_language(names: List[str]) -> Dict[str, List[str]]:
    groups: Dict[str, List[str]] = {}
    for n in names:
        m = LOC_RE.search(n)
        if m:
            groups.setdefault(m.group(1), []).append(n)
    for files in groups.values():             # .loca авторитетнее .xml
        files.sort(key=lambda f: (not f.lower().endswith(".loca"), f.lower()))
    return groups


def _read_group(src: ModSource, files: List[str], diagnostics: List[str]
                ) -> Dict[str, Tuple[str, int, str]]:
    """handle -> (text, version, file). При дублях берётся первое вхождение."""
    out: Dict[str, Tuple[str, int, str]] = {}
    for name in files:
        try:
            parsed = _parse_loc_file(src.read(name), name)
        except ImportFailure:
            raise
        except Exception as exc:
            diagnostics.append(f"Пропущен {name}: {exc}")
            log.warning("Не удалось разобрать %s: %s", name, exc)
            continue
        for handle, text in parsed.entries:
            out.setdefault(handle, (text, parsed.versions.get(handle, 1), name))
    return out


@dataclass
class ImportResult:
    metadata: ModMetadata
    entries: List[TranslationEntry]
    languages: List[str] = field(default_factory=list)
    source_folder: str = ""
    target_folder: Optional[str] = None
    diagnostics: List[str] = field(default_factory=list)
    prefilled: int = 0

    def to_project(self, source_lang: str, target_lang: str) -> TranslationProject:
        return TranslationProject(metadata=self.metadata, entries=self.entries,
                                  source_language=source_lang, target_language=target_lang)


def import_mod(path, source_lang: str = "en", target_lang: str = "ru",
               progress: Optional[Callable[[str], None]] = None) -> ImportResult:
    """Главная точка входа импорта."""
    path = Path(path)
    say = progress or (lambda _m: None)
    diagnostics: List[str] = []
    if not path.exists():
        raise ImportFailure(f"Путь не найден: {path}")

    say("Открываю мод…")
    try:
        src = open_source(path)
    except ImportFailure:
        raise
    except Exception as exc:
        raise ImportFailure(f"Не удалось открыть {path.name}: {exc}") from exc

    with src:
        names = src.names()
        say("Читаю описание мода…")
        meta = ModMeta()
        meta_name = next((n for n in names if META_RE.search(n)), None)
        if meta_name:
            try:
                meta = parse_meta_lsx(src.read(meta_name).decode("utf-8-sig", errors="replace"))
            except Exception as exc:
                diagnostics.append(f"meta.lsx не разобран: {exc}")

        groups = _group_by_language(names)
        single = path.is_file() and path.suffix.lower() in LOC_EXT
        if single:
            groups = {"": [path.name]}
        if not groups:                                          # свободная раскладка
            loose = sorted((n for n in names if n.lower().endswith(LOC_EXT)),
                           key=lambda f: (not f.lower().endswith(".loca"), f.lower()))
            if loose:
                groups = {"": loose}
                diagnostics.append("Папок Localization/<Язык> не найдено — читаю все .loca/.xml подряд")
        if not groups:
            raise ImportFailure("В моде не найдено файлов локализации (.loca / .xml).")

        src_folder = _pick_folder(groups, folder_for(source_lang), "English")
        if src_folder is None:
            raise ImportFailure("Не удалось определить язык-источник. Найдены: "
                                + ", ".join(sorted(groups)))
        if src_folder.lower() != folder_for(source_lang).lower() and src_folder != "":
            diagnostics.append(f"Язык {folder_for(source_lang)} не найден, взят {src_folder}")

        say(f"Читаю тексты ({src_folder or 'без языка'})…")
        source_map = _read_group(src, groups[src_folder], diagnostics)
        if not source_map:
            raise ImportFailure("Файлы локализации найдены, но строк в них нет.")

        tgt_folder = None
        target_map: Dict[str, Tuple[str, int, str]] = {}
        wanted = folder_for(target_lang)
        for g in groups:
            if g.lower() == wanted.lower() and g != src_folder:
                tgt_folder = g
        if tgt_folder is not None:
            say("Нашёл готовый перевод — подгружаю…")
            target_map = _read_group(src, groups[tgt_folder], diagnostics)

    entries: List[TranslationEntry] = []
    prefilled = 0
    for handle, (text, ver, fname) in source_map.items():
        e = TranslationEntry(handle=handle, source_text=text, source_language=source_lang,
                             target_language=target_lang, context=fname, version=ver)
        tr = target_map.get(handle)
        if tr and tr[0].strip() and tr[0].strip() != text.strip():
            e.target_text = tr[0]
            e.status = TranslationStatus.NEEDS_REVIEW if tr[1] < ver else TranslationStatus.TRANSLATED
            errs, warns = compare_placeholders(text, tr[0])
            e.validation_errors, e.validation_warnings = errs, warns
            prefilled += 1
        entries.append(e)

    name = meta.name or (path.stem if path.is_file() else path.name) or "mod"
    metadata = ModMetadata(
        name=name, author=meta.author, version=meta.version, description=meta.description,
        folder=meta.folder, source_path=path,
        original_mod_uuid=meta.uuid, original_mod_folder=meta.folder,
    )
    return ImportResult(metadata, entries, sorted(g for g in groups if g), src_folder,
                        tgt_folder, diagnostics, prefilled)


def _pick_folder(groups: Dict[str, List[str]], wanted: str, fallback: str) -> Optional[str]:
    lower = {g.lower(): g for g in groups}
    for cand in (wanted, fallback):
        if cand.lower() in lower:
            return lower[cand.lower()]
    if "" in groups:
        return ""
    return next(iter(groups), None)


def load_texts(path) -> Dict[str, Tuple[str, int]]:
    """Все пары handle -> (текст, версия) из файла/пака/папки; языки не различаются.

    Нужен для импорта терминологии из игры и для подгрузки чужого перевода.
    """
    out: Dict[str, Tuple[str, int]] = {}
    diagnostics: List[str] = []
    with open_source(Path(path)) as src:
        files = sorted((n for n in src.names() if n.lower().endswith(LOC_EXT)),
                       key=lambda f: (not f.lower().endswith(".loca"), f.lower()))
        for handle, (text, ver, _f) in _read_group(src, files, diagnostics).items():
            out[handle] = (text, ver)
    return out


def apply_translation_file(project: TranslationProject, path) -> Tuple[int, int]:
    """Подмешивает готовый перевод из файла по handle. Возвращает (заполнено, на_проверку)."""
    texts = load_texts(path)
    filled = review = 0
    for e in project.entries:
        tr = texts.get(e.handle)
        if not tr or not tr[0].strip() or tr[0].strip() == e.source_text.strip():
            continue
        e.target_text = tr[0]
        if tr[1] < e.version:
            e.status = TranslationStatus.NEEDS_REVIEW
            review += 1
        else:
            e.status = TranslationStatus.TRANSLATED
        e.validation_errors, e.validation_warnings = compare_placeholders(e.source_text, tr[0])
        e.update_timestamps()
        filled += 1
    project.update_stats()
    return filled, review
