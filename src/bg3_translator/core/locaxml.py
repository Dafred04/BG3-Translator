"""Локализация BG3: чтение .loca/.xml и запись.

Формат записи по умолчанию — тот, что использует LSLib и сама игра для XML-версии .loca:

    <contentList>
      <content contentuid="h..." version="1">Текст</content>
    </contentList>

Старый формат (<content root="ResourceList"><translated_string handle=...>) читается,
а записывается только при legacy=True.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple, Union

try:                                    # защита от XML-бомб, если библиотека доступна
    from defusedxml import ElementTree as ET
except ImportError:                     # pragma: no cover
    from xml.etree import ElementTree as ET
from xml.etree import ElementTree as _StdET

from ..models.translation import TranslationEntry
from .loca import LocaResource, LocaText, read_loca, write_loca


@dataclass
class LocaVersion:
    major: int = 1
    minor: int = 0
    revision: int = 0
    build: int = 0

    def as_tuple(self) -> Tuple[int, int, int, int]:
        return (self.major, self.minor, self.revision, self.build)

    def __ge__(self, other: "LocaVersion") -> bool:
        return self.as_tuple() >= other.as_tuple()

    def __lt__(self, other: "LocaVersion") -> bool:
        return self.as_tuple() < other.as_tuple()


@dataclass
class ParsedLoca:
    entries: List[Tuple[str, str]] = field(default_factory=list)      # (handle, content)
    version: LocaVersion = field(default_factory=LocaVersion)
    versions: Dict[str, int] = field(default_factory=dict)            # handle -> версия строки


def _inner(el) -> str:
    """Текст элемента вместе с неэкранированной разметкой внутри (если она есть)."""
    return (el.text or "") + "".join(_StdET.tostring(c, encoding="unicode") for c in el)


def _int(v, default=1) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def parse_loca_xml(xml_text: str) -> ParsedLoca:
    """Разбирает оба известных вида XML-локализации."""
    if xml_text.startswith("\ufeff"):
        xml_text = xml_text[1:]
    root = ET.fromstring(xml_text.encode("utf-8") if xml_text.lstrip().startswith("<?xml") else xml_text)
    result = ParsedLoca()

    ver_el = root.find("version")
    if ver_el is not None:
        result.version = LocaVersion(
            major=_int(ver_el.get("major"), 1), minor=_int(ver_el.get("minor"), 0),
            revision=_int(ver_el.get("revision"), 0), build=_int(ver_el.get("build"), 0),
        )

    for ts in root.iter("translated_string"):                    # старый формат
        handle = ts.get("handle", "")
        content_el = ts.find("content")
        content = content_el.get("str", "") if content_el is not None else ""
        if handle:
            result.entries.append((handle, content))
            result.versions[handle] = 1
    if result.entries:
        return result

    for el in root.iter("content"):                              # формат LSLib / игры
        handle = el.get("contentuid", "")
        if not handle:
            continue
        result.entries.append((handle, _inner(el)))
        result.versions[handle] = _int(el.get("version"), 1)
    return result


def parse_loca_binary(data: bytes) -> ParsedLoca:
    res = read_loca(data)
    out = ParsedLoca()
    for e in res.entries:
        out.entries.append((e.key, e.text))
        out.versions[e.key] = e.version
    return out


Pair = Union[Tuple[str, str], Tuple[str, str, int]]


def _norm_entries(entries: Iterable[Pair], versions: Optional[Dict[str, int]]):
    for item in entries:
        handle, content = item[0], item[1]
        ver = item[2] if len(item) > 2 else (versions or {}).get(handle, 1)
        yield handle, content, ver


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\r", "&#13;"))


def build_loca_xml(
    entries: Iterable[Pair],
    version: Optional[LocaVersion] = None,
    source_version: Optional[LocaVersion] = None,
    versions: Optional[Dict[str, int]] = None,
    legacy: bool = False,
) -> str:
    """XML-локализация. entries: (handle, text) или (handle, text, version).

    Если передан version или source_version, пишется формат с элементом <version>
    (как раньше) — иначе плоский <contentList>/<content contentuid=…>.
    """
    items = list(_norm_entries(entries, versions))
    legacy = legacy or version is not None or source_version is not None
    if legacy:
        out_version = version or LocaVersion()
        if source_version is not None and out_version < source_version:
            out_version = LocaVersion(source_version.major, source_version.minor,
                                      source_version.revision, source_version.build + 1)
        lines = ['<?xml version="1.0" encoding="utf-8"?>', '<content root="ResourceList">',
                 f'  <version major="{out_version.major}" minor="{out_version.minor}" '
                 f'revision="{out_version.revision}" build="{out_version.build}"/>', "  <contentList>"]
        for handle, content, _v in items:
            esc = _esc(content).replace('"', "&quot;").replace("\n", "&#10;")
            lines += [f'    <translated_string handle="{handle}">',
                      f'      <content str="{esc}"/>', "    </translated_string>"]
        lines += ["  </contentList>", "</content>"]
        return "\n".join(lines)

    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<contentList>"]
    for handle, content, ver in items:
        lines.append(f'  <content contentuid="{handle}" version="{ver}">{_esc(content)}</content>')
    lines.append("</contentList>")
    return "\n".join(lines) + "\n"


def build_loca_binary(entries: Iterable[Pair], versions: Optional[Dict[str, int]] = None) -> bytes:
    res = LocaResource([LocaText(key=h, version=v, text=t) for h, t, v in _norm_entries(entries, versions)])
    return write_loca(res)


def loca_to_entries(loca: ParsedLoca, source_language: str = "en",
                    target_language: str = "ru") -> List[TranslationEntry]:
    """ParsedLoca -> TranslationEntry (только оригинал)."""
    return [
        TranslationEntry(handle=h, source_text=c, source_language=source_language,
                         target_language=target_language, version=loca.versions.get(h, 1))
        for h, c in loca.entries
    ]


def merge_translations(original: ParsedLoca, translations: Dict[str, str]) -> List[Tuple[str, str]]:
    return [(h, translations.get(h, c)) for h, c in original.entries]
