"""LSPK v18 package reader/writer for BG3 .pak files.

Header (40 bytes, little-endian) — порядок полей по LSLib `LSPKHeader16`:
  signature u32 "LSPK" | version u32 | file_list_off u64 | file_list_size u32
  flags u8 | priority u8 | md5 16 bytes | num_parts u16

File list (at file_list_off): num_files u32, compressed_size u32, LZ4 block (без префикса размера)
FileEntry v18 (272 bytes): name[256] | offset u32 + u16<<32 | archive_part u8 | flags u8 |
                           size_on_disk u32 | uncompressed_size u32

flags & 0x0F — метод сжатия: 0=None, 1=Zlib, 2=LZ4, 3=Zstd. Старшие биты — уровень сжатия.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional

import lz4.block

try:
    import zstandard
    _HAS_ZSTD = True
except ImportError:  # pragma: no cover
    _HAS_ZSTD = False

SIGNATURE = 0x4B50534C
HEADER_SIZE = 40
ENTRY_SIZE = 272

COMP_NONE = 0
COMP_ZLIB = 1
COMP_LZ4 = 2
COMP_ZSTD = 3


class PakError(Exception):
    pass


@dataclass
class PakEntry:
    name: str
    offset: int
    archive_part: int
    flags: int
    size_on_disk: int
    uncompressed_size: int

    @property
    def compression_method(self) -> int:
        return self.flags & 0x0F

    @property
    def is_compressed(self) -> bool:
        return self.compression_method != COMP_NONE


def _decompress(data: bytes, method: int, uncompressed_size: int) -> bytes:
    if method == COMP_NONE:
        return data
    if method == COMP_ZLIB:
        return zlib.decompress(data)
    if method == COMP_LZ4:
        return lz4.block.decompress(data, uncompressed_size=uncompressed_size)
    if method == COMP_ZSTD:
        # Значение 3 в разных описаниях формата означает то Zstd, то LZ4HC. Различаем по
        # сигнатуре кадра Zstd (28 B5 2F FD), иначе читаем как LZ4-блок.
        if data[:4] == b"\x28\xb5\x2f\xfd":
            if not _HAS_ZSTD:
                raise PakError("Пак сжат Zstd — установите пакет 'zstandard'")
            return zstandard.ZstdDecompressor().decompress(data, max_output_size=uncompressed_size)
        return lz4.block.decompress(data, uncompressed_size=uncompressed_size)
    raise PakError(f"Неизвестный метод сжатия: {method}")


def safe_join(base: Path, name: str) -> Path:
    """base/name, но только если результат остаётся внутри base (защита от ../)."""
    base_r = Path(base).resolve()
    target = (base_r / name).resolve()
    try:
        target.relative_to(base_r)
    except ValueError:
        raise PakError(f"Небезопасный путь в архиве: {name!r}") from None
    return target


class PakReader:
    """Reads BG3 LSPK v17/v18 packages."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._fh = open(self.path, "rb")
        self.entries: List[PakEntry] = []
        self.num_parts = 1
        try:
            self._read_header()
        except BaseException:
            self._fh.close()
            self._fh = None
            raise
        self._by_name: Dict[str, PakEntry] = {e.name: e for e in self.entries}

    def _read_header(self):
        self._fh.seek(0)
        header = self._fh.read(HEADER_SIZE)
        if len(header) < HEADER_SIZE:
            raise PakError("Файл слишком мал для .pak")
        sig, version, fl_off, fl_size = struct.unpack("<IIQI", header[:20])
        if sig != SIGNATURE:
            raise PakError("Это не .pak: неверная сигнатура (bad signature)")
        if version not in (17, 18):
            raise PakError(f"Неподдерживаемая версия пака: {version} (нужна 17 или 18)")
        self.version = version
        self.num_parts = struct.unpack_from("<H", header, 38)[0] or 1

        self._fh.seek(fl_off)
        list_head = self._fh.read(8)
        if len(list_head) < 8:
            raise PakError("Обрезан заголовок списка файлов")
        num_files, compressed_size = struct.unpack("<II", list_head)
        if not (0 < num_files < 1_000_000):
            raise PakError(f"Неправдоподобное число файлов: {num_files}")
        payload = self._fh.read(compressed_size)
        if len(payload) < compressed_size:
            raise PakError("Обрезан список файлов")
        expected = num_files * ENTRY_SIZE
        try:
            table = lz4.block.decompress(payload, uncompressed_size=expected)
        except Exception as exc:
            raise PakError(f"Не удалось распаковать список файлов: {exc}") from exc
        if len(table) != expected:
            raise PakError(f"Размер списка файлов не совпал: {len(table)} вместо {expected}")
        for i in range(num_files):
            raw = table[i * ENTRY_SIZE:(i + 1) * ENTRY_SIZE]
            name = raw[:256].split(b"\x00", 1)[0].decode("utf-8", errors="replace")
            offset = struct.unpack_from("<I", raw, 256)[0] | (struct.unpack_from("<H", raw, 260)[0] << 32)
            size_on_disk, uncomp_size = struct.unpack_from("<II", raw, 264)
            self.entries.append(PakEntry(
                name=name.replace("\\", "/"), offset=offset, archive_part=raw[262],
                flags=raw[263], size_on_disk=size_on_disk, uncompressed_size=uncomp_size,
            ))

    # -- доступ к файлам ---------------------------------------------------
    def names(self) -> List[str]:
        return [e.name for e in self.entries]

    def find(self, name: str) -> Optional[PakEntry]:
        return self._by_name.get(name.replace("\\", "/"))

    def read_file(self, entry: PakEntry) -> bytes:
        if entry.archive_part != 0:
            raise PakError(f"{entry.name}: многочастные паки (_1.pak, …) не поддерживаются")
        self._fh.seek(entry.offset)
        data = self._fh.read(entry.size_on_disk)
        if len(data) < entry.size_on_disk:
            raise PakError(f"Обрезаны данные файла {entry.name}")
        return _decompress(data, entry.compression_method, entry.uncompressed_size)

    def read_named(self, name: str) -> bytes:
        entry = self.find(name)
        if entry is None:
            raise PakError(f"В паке нет файла {name}")
        return self.read_file(entry)

    def iter_files(self, prefix: str = "") -> Iterator[PakEntry]:
        p = prefix.replace("\\", "/")
        return (e for e in self.entries if e.name.startswith(p))

    def extract_all(self, out_dir: Path) -> int:
        out_dir = Path(out_dir)
        count = 0
        for entry in self.entries:
            target = safe_join(out_dir, entry.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.read_file(entry))
            count += 1
        return count

    def close(self):
        if self._fh:
            self._fh.close()
            self._fh = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def extract_pak(pak_path: Path, out_dir: Path) -> int:
    with PakReader(pak_path) as pak:
        return pak.extract_all(out_dir)


def write_pak(out_path: Path, files: Dict[str, bytes], compress: bool = True) -> Path:
    """Пишет валидный LSPK v18 из {путь_в_паке: содержимое}. Порядок файлов — по имени."""
    out_path = Path(out_path)
    blobs = []   # name, offset, disk, uncomp, flags, data
    offset = HEADER_SIZE
    for name in sorted(files):
        content = files[name]
        disk, uncomp, flags, blob = len(content), 0, COMP_NONE, content
        if compress and content:
            comp = lz4.block.compress(content, store_size=False)
            if len(comp) < len(content):
                disk, uncomp, flags, blob = len(comp), len(content), COMP_LZ4, comp
        blobs.append((name.replace("\\", "/"), offset, disk, uncomp, flags, blob))
        offset += disk

    table = bytearray()
    for name, off, disk, uncomp, flags, _blob in blobs:
        entry = bytearray(ENTRY_SIZE)
        nb = name.encode("utf-8")
        if len(nb) > 255:
            raise PakError(f"Слишком длинное имя файла в паке: {name}")
        entry[:len(nb)] = nb
        struct.pack_into("<I", entry, 256, off & 0xFFFFFFFF)
        struct.pack_into("<H", entry, 260, (off >> 32) & 0xFFFF)
        entry[262] = 0
        entry[263] = flags
        struct.pack_into("<II", entry, 264, disk, uncomp)
        table.extend(entry)

    ctable = lz4.block.compress(bytes(table), store_size=False)
    fl_off = offset
    with open(out_path, "wb") as f:
        f.write(struct.pack("<IIQI BB16sH", SIGNATURE, 18, fl_off, len(ctable), 0, 0, b"\x00" * 16, 1))
        for *_rest, blob in blobs:
            f.write(blob)
        f.write(struct.pack("<II", len(blobs), len(ctable)))
        f.write(ctable)
    return out_path
