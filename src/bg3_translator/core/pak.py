"""LSPK v18 package reader/writer for BG3 .pak files.

Format (from LSLib PackageFormat.cs + bin_unpak reference impl):

Header (40 bytes):
  signature       u32  "LSPK" (0x4B50534C)
  version         u32  (18)
  file_list_off   u64  offset of file list
  file_list_size  u32
  num_parts       u16
  flags           u8
  priority        u8
  md5             16 bytes

File list (at file_list_off), per LSLib ReadCompressedFileList:
  num_files       u32
  compressed_size u32
  data            compressed_size bytes LZ4 block (no store_size prefix) of num_files entries

FileEntry v18 (272 bytes each):
  name              256 bytes, null-terminated, '/' separators
  offset_in_file    u32 + (u16 << 32)
  archive_part      u8
  flags             u8   (low nibble = compression method)
  size_on_disk      u32
  uncompressed_size u32  (0 when stored uncompressed)

Compression methods: 0=None, 1=Zlib, 2=LZ4, 3=LZ4HC, 105=Zstd
"""

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import List

import lz4.block

try:
    import zstandard
    _HAS_ZSTD = True
except ImportError:
    _HAS_ZSTD = False

SIGNATURE = 0x4B50534C
HEADER_SIZE = 40
ENTRY_SIZE = 272

COMP_NONE = 0
COMP_ZLIB = 1
COMP_LZ4 = 2
COMP_LZ4HC = 3
COMP_ZSTD = 105


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
    if method in (COMP_LZ4, COMP_LZ4HC):
        return lz4.block.decompress(data, uncompressed_size=uncompressed_size)
    if method == COMP_ZSTD:
        if not _HAS_ZSTD:
            raise PakError("Zstd-compressed pak requires the 'zstandard' package")
        return zstandard.ZstdDecompressor().decompress(data, max_output_size=uncompressed_size)
    raise PakError(f"Unknown compression method: {method}")


class PakReader:
    """Reads BG3 LSPK v18 packages."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._fh = open(self.path, "rb")
        self.entries: List[PakEntry] = []
        self._read_header()

    def _read_header(self):
        self._fh.seek(0)
        header = self._fh.read(HEADER_SIZE)
        if len(header) < HEADER_SIZE:
            raise PakError("File too small to be a pak")
        (sig, version, fl_off, fl_size, num_parts,
         flags, priority) = struct.unpack("<IIQI HBB", header[:24])
        if sig != SIGNATURE:
            raise PakError("Not a valid pak (bad signature)")
        if version not in (17, 18):
            raise PakError(f"Unsupported pak version: {version} (only v17/v18 supported)")
        self.version = version

        # LSLib ReadCompressedFileList: numFiles u32 @off, compressedSize u32 @off+4,
        # LZ4 block payload @off+8 (no store_size prefix). No SOLID support in v1 of this reader.
        self._fh.seek(fl_off)
        list_head = self._fh.read(8)
        if len(list_head) < 8:
            raise PakError("Truncated file list header")
        num_files, compressed_size = struct.unpack("<II", list_head)
        if not (0 < num_files < 1_000_000):
            raise PakError(f"Implausible file count: {num_files}")
        payload = self._fh.read(compressed_size)
        if len(payload) < compressed_size:
            raise PakError("Truncated file list payload")
        expected = num_files * ENTRY_SIZE
        try:
            table = lz4.block.decompress(payload, uncompressed_size=expected)
        except Exception as exc:
            raise PakError(f"File list decompression failed: {exc}") from exc
        if len(table) != expected:
            raise PakError(f"File list size mismatch: got {len(table)}, expected {expected}")
        self.entries = []
        for i in range(num_files):
            off = i * ENTRY_SIZE
            raw = table[off:off + ENTRY_SIZE]
            if len(raw) < ENTRY_SIZE:
                raise PakError("File list truncated")
            name_bytes = raw[:256]
            name = name_bytes.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
            offset = struct.unpack_from("<I", raw, 256)[0] | (struct.unpack_from("<H", raw, 260)[0] << 32)
            archive_part = raw[262]
            eflags = raw[263]
            size_on_disk, uncomp_size = struct.unpack_from("<II", raw, 264)
            self.entries.append(PakEntry(
                name=name.replace("\\", "/"),
                offset=offset,
                archive_part=archive_part,
                flags=eflags,
                size_on_disk=size_on_disk,
                uncompressed_size=uncomp_size,
            ))

    def read_file(self, entry: PakEntry) -> bytes:
        self._fh.seek(entry.offset)
        data = self._fh.read(entry.size_on_disk)
        if len(data) < entry.size_on_disk:
            raise PakError(f"Truncated file data for {entry.name}")
        return _decompress(data, entry.compression_method, entry.uncompressed_size)

    def extract_all(self, out_dir: Path) -> int:
        out_dir = Path(out_dir)
        count = 0
        for entry in self.entries:
            target = out_dir / entry.name
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
    """Convenience: extract a pak to a directory. Returns file count."""
    with PakReader(pak_path) as pak:
        return pak.extract_all(out_dir)


def write_pak(out_path: Path, files: dict[str, bytes], compress: bool = True) -> Path:
    """Write a valid LSPK v18 pak from {path_in_pak: content}.

    Uses LZ4 block compression when beneficial; stores uncompressed otherwise.
    """
    out_path = Path(out_path)
    file_blobs: list[tuple[str, int, int, int, bytes]] = []  # name, offset, disk, uncomp, data
    offset = HEADER_SIZE  # data starts right after header

    for name, content in files.items():
        if compress:
            compressed = lz4.block.compress(content, store_size=False)
            if len(compressed) < len(content):
                disk, uncomp, flags = len(compressed), len(content), COMP_LZ4
                blob = compressed
            else:
                disk, uncomp, flags = len(content), 0, COMP_NONE
                blob = content
        else:
            disk, uncomp, flags = len(content), 0, COMP_NONE
            blob = content
        file_blobs.append((name.replace("\\", "/"), offset, disk, uncomp, blob))
        offset += disk

    # Build file list table (v18 entries, 272 bytes each)
    # Data is placed right after the 40-byte header; the file list follows the data.
    table = bytearray()
    for name, off, disk, uncomp, _blob in file_blobs:
        entry = bytearray(ENTRY_SIZE)
        name_bytes = name.encode("utf-8")[:255]
        entry[:len(name_bytes)] = name_bytes
        struct.pack_into("<I", entry, 256, off & 0xFFFFFFFF)
        struct.pack_into("<H", entry, 260, (off >> 32) & 0xFFFF)
        entry[262] = 0  # archive part
        flags = COMP_LZ4 if uncomp > 0 else COMP_NONE
        entry[263] = flags
        struct.pack_into("<II", entry, 264, disk, uncomp)
        table.extend(entry)

    table_bytes = bytes(table)
    compressed_table = lz4.block.compress(table_bytes, store_size=False)
    file_list_offset = HEADER_SIZE + sum(disk for _n, _o, disk, _u, _b in file_blobs)

    with open(out_path, "wb") as f:
        # Header (file list located after all data)
        f.write(struct.pack(
            "<IIQI HBB16s",
            SIGNATURE, 18, file_list_offset, len(compressed_table),
            1, 0, 0, b"\x00" * 16,
        ))
        # File data
        for *_rest, blob in file_blobs:
            f.write(blob)
        # File list: numFiles u32 + compressedSize u32 + LZ4 block (LSLib layout)
        f.write(struct.pack("<II", len(file_blobs), len(compressed_table)))
        f.write(compressed_table)

    return out_path