"""meta.lsx мода BG3: разбор и генерация (Version64, зависимости)."""

from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass, field
from typing import List
from xml.sax.saxutils import quoteattr

try:
    from defusedxml import ElementTree as ET
except ImportError:  # pragma: no cover
    from xml.etree import ElementTree as ET


def decode_version64(v: int) -> str:
    return f"{(v >> 55) & 0x1FF}.{(v >> 47) & 0xFF}.{(v >> 31) & 0xFFFF}.{v & 0x7FFFFFFF}"


def encode_version64(major: int = 1, minor: int = 0, revision: int = 0, build: int = 0) -> int:
    return (major << 55) | (minor << 47) | (revision << 31) | build


def version_string_to_64(s: str) -> int:
    parts = [int(p) for p in (s or "1.0.0.0").split(".") if p.isdigit()][:4]
    parts += [0] * (4 - len(parts))
    return encode_version64(*parts)


@dataclass
class Dependency:
    name: str = ""
    folder: str = ""
    uuid: str = ""
    version64: int = 36028797018963968


@dataclass
class ModMeta:
    name: str = ""
    author: str = ""
    description: str = ""
    folder: str = ""
    uuid: str = ""
    version64: int = 36028797018963968          # 1.0.0.0
    dependencies: List[Dependency] = field(default_factory=list)

    @property
    def version(self) -> str:
        return decode_version64(self.version64)


def _attrs(node) -> dict:
    return {a.get("id"): a.get("value", "") for a in node.findall("attribute")}


def parse_meta_lsx(text: str) -> ModMeta:
    if text.startswith("\ufeff"):
        text = text[1:]
    root = ET.fromstring(text.encode("utf-8"))
    meta = ModMeta()
    info = next((n for n in root.iter("node") if n.get("id") == "ModuleInfo"), None)
    if info is not None:
        a = _attrs(info)
        meta.name, meta.author = a.get("Name", ""), a.get("Author", "")
        meta.description, meta.folder, meta.uuid = a.get("Description", ""), a.get("Folder", ""), a.get("UUID", "")
        try:
            meta.version64 = int(a.get("Version64", meta.version64))
        except ValueError:
            pass
    for n in root.iter("node"):
        if n.get("id") == "ModuleShortDesc":
            a = _attrs(n)
            try:
                v64 = int(a.get("Version64", 36028797018963968))
            except ValueError:
                v64 = 36028797018963968
            meta.dependencies.append(Dependency(a.get("Name", ""), a.get("Folder", ""), a.get("UUID", ""), v64))
    return meta


def _attr(id_: str, type_: str, value) -> str:
    return f'          <attribute id="{id_}" type="{type_}" value={quoteattr(str(value))}/>'


def build_meta_lsx(meta: ModMeta) -> str:
    """Минимальный meta.lsx для мода-дополнения (перевода)."""
    uid = meta.uuid or str(_uuid.uuid4())
    deps = ""
    if meta.dependencies:
        items = []
        for d in meta.dependencies:
            items.append("\n".join([
                '            <node id="ModuleShortDesc">',
                _attr("Folder", "LSString", d.folder).replace("          ", "              "),
                _attr("MD5", "LSString", "").replace("          ", "              "),
                _attr("Name", "LSString", d.name).replace("          ", "              "),
                _attr("UUID", "FixedString", d.uuid).replace("          ", "              "),
                _attr("Version64", "int64", d.version64).replace("          ", "              "),
                "            </node>",
            ]))
        deps = ('        <node id="Dependencies">\n          <children>\n' + "\n".join(items)
                + "\n          </children>\n        </node>\n")
    else:
        deps = '        <node id="Dependencies"/>\n'
    attrs = "\n".join([
        _attr("Author", "LSString", meta.author),
        _attr("CharacterCreationLevelName", "FixedString", ""),
        _attr("Description", "LSString", meta.description),
        _attr("Folder", "LSString", meta.folder),
        _attr("LobbyLevelName", "FixedString", ""),
        _attr("MD5", "LSString", ""),
        _attr("MainMenuBackgroundVideo", "FixedString", ""),
        _attr("MenuLevelName", "FixedString", ""),
        _attr("Name", "FixedString", meta.name),
        _attr("NumPlayers", "uint8", 4),
        _attr("PhotoBooth", "FixedString", ""),
        _attr("StartupLevelName", "FixedString", ""),
        _attr("Tags", "LSString", ""),
        _attr("Type", "FixedString", "Add-on"),
        _attr("UUID", "FixedString", uid),
        _attr("Version64", "int64", meta.version64),
    ])
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<save>\n'
        '  <version major="4" minor="0" revision="9" build="331"/>\n'
        '  <region id="Config">\n    <node id="root">\n      <children>\n'
        + deps +
        '        <node id="ModuleInfo">\n' + attrs + '\n'
        '          <children>\n'
        '            <node id="TargetModes">\n              <children>\n'
        '                <node id="Target">\n'
        '                  <attribute id="Object" type="FixedString" value="Story"/>\n'
        '                </node>\n              </children>\n            </node>\n'
        '          </children>\n        </node>\n'
        '      </children>\n    </node>\n  </region>\n</save>\n'
    )
