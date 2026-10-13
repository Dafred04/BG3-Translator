"""BG3 localization XML (.loc / .xml) parse & generate.

BG3 localization files use this structure:
  <content root="ResourceList">
    <version major="1" minor="0" revision="0" build="0"/>
    <contentList>
      <translated_string handle="hXXXXXXXX"><content str="..."/></translated_string>
    </contentList>
  </content>
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from xml.etree import ElementTree as ET

from ..models.translation import TranslationEntry


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
    entries: List[Tuple[str, str]] = field(default_factory=list)  # (handle, content)
    version: LocaVersion = field(default_factory=LocaVersion)


def parse_loca_xml(xml_text: str) -> ParsedLoca:
    """Parse BG3 localization XML text into handles/contents + version."""
    # strip BOM if present
    if xml_text.startswith("\ufeff"):
        xml_text = xml_text[1:]
    root = ET.fromstring(xml_text)
    result = ParsedLoca()

    ver_el = root.find("version")
    if ver_el is not None:
        result.version = LocaVersion(
            major=int(ver_el.get("major", 1)),
            minor=int(ver_el.get("minor", 0)),
            revision=int(ver_el.get("revision", 0)),
            build=int(ver_el.get("build", 0)),
        )

    for ts in root.iter("translated_string"):
        handle = ts.get("handle", "")
        content_el = ts.find("content")
        content = content_el.get("str", "") if content_el is not None else ""
        if handle:
            result.entries.append((handle, content))
    return result


def build_loca_xml(
    entries: List[Tuple[str, str]],
    version: LocaVersion | None = None,
    source_version: LocaVersion | None = None,
) -> str:
    """Generate BG3 localization XML from (handle, content) pairs.

    Ensures output version >= source_version (version downgrade protection).
    """
    out_version = version or LocaVersion()
    if source_version is not None and out_version < source_version:
        out_version = LocaVersion(
            major=source_version.major,
            minor=source_version.minor,
            revision=source_version.revision,
            build=source_version.build + 1,  # bump revision to stay strictly newer
        )

    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<content root="ResourceList">',
        (
            f'  <version major="{out_version.major}" minor="{out_version.minor}" '
            f'revision="{out_version.revision}" build="{out_version.build}"/>'
        ),
        "  <contentList>",
    ]
    for handle, content in entries:
        esc = (
            content.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )
        lines.append(f'    <translated_string handle="{handle}">')
        lines.append(f'      <content str="{esc}"/>')
        lines.append("    </translated_string>")
    lines.append("  </contentList>")
    lines.append("</content>")
    return "\n".join(lines)


def loca_to_entries(
    loca: ParsedLoca,
    source_language: str = "en",
    target_language: str = "zh",
) -> List[TranslationEntry]:
    """Convert parsed LOCA into TranslationEntry list (source only)."""
    return [
        TranslationEntry(
            handle=handle,
            source_text=content,
            source_language=source_language,
            target_language=target_language,
        )
        for handle, content in loca.entries
    ]


def merge_translations(
    original: ParsedLoca,
    translations: Dict[str, str],
) -> List[Tuple[str, str]]:
    """Merge: original handles in order, using translated text when available."""
    return [(handle, translations.get(handle, content)) for handle, content in original.entries]