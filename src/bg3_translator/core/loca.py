"""Binary .loca reader/writer (LSLib LocaResource layout).

Header: signature u32 'LOCA' + numEntries u32 + textsOffset u32.
Entry (70 bytes each): key 64B null-terminated UTF-8 + version u16 + length u32.
Texts: UTF-8 bytes of (length-1) + 1 null byte each.
"""

import struct
from dataclasses import dataclass, field
from typing import List

LOCA_SIGNATURE = 0x41434F4C  # 'LOCA'
LOCA_HEADER_SIZE = 12
LOCA_ENTRY_SIZE = 70
LOCA_KEY_SIZE = 64


class LocaError(Exception):
    pass


@dataclass
class LocaText:
    key: str
    version: int
    text: str


@dataclass
class LocaResource:
    entries: List[LocaText] = field(default_factory=list)


def read_loca(data: bytes) -> LocaResource:
    if len(data) < LOCA_HEADER_SIZE:
        raise LocaError("File too small to be a .loca")
    sig, num, texts_off = struct.unpack("<III", data[:LOCA_HEADER_SIZE])
    if sig != LOCA_SIGNATURE:
        raise LocaError("Not a .loca file (bad signature)")
    entries_end = LOCA_HEADER_SIZE + num * LOCA_ENTRY_SIZE
    if entries_end > len(data):
        raise LocaError("Truncated .loca entries")
    if texts_off > len(data):
        raise LocaError("Truncated .loca (texts offset out of range)")

    res = LocaResource()
    pos = texts_off
    for i in range(num):
        raw = data[LOCA_HEADER_SIZE + i * LOCA_ENTRY_SIZE:
                   LOCA_HEADER_SIZE + (i + 1) * LOCA_ENTRY_SIZE]
        key = raw[:LOCA_KEY_SIZE].split(b"\x00", 1)[0].decode("utf-8", "replace")
        version, length = struct.unpack_from("<HI", raw, LOCA_KEY_SIZE)
        if pos + length > len(data):
            raise LocaError(f"Truncated text for handle {key!r}")
        text = data[pos:pos + max(length - 1, 0)].decode("utf-8", "replace")
        pos += length
        res.entries.append(LocaText(key=key, version=version, text=text))
    return res


def write_loca(res: LocaResource) -> bytes:
    out = bytearray()
    texts_off = LOCA_HEADER_SIZE + LOCA_ENTRY_SIZE * len(res.entries)
    out += struct.pack("<III", LOCA_SIGNATURE, len(res.entries), texts_off)
    for e in res.entries:
        key = e.key.encode("utf-8")[:LOCA_KEY_SIZE - 1]
        out += key + b"\x00" * (LOCA_KEY_SIZE - len(key))
        body = e.text.encode("utf-8")
        out += struct.pack("<HI", e.version, len(body) + 1)
    for e in res.entries:
        out += e.text.encode("utf-8") + b"\x00"
    return bytes(out)
