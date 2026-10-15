"""Подключает src/ и ставит заглушки lz4 / PySide6, если реальных пакетов нет.

Реальные библиотеки всегда имеют приоритет — заглушки нужны только чтобы тесты ядра
запускались в «голом» окружении (CI без Qt).
"""
import importlib.util
import sys
import types
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _have(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


if not _have("lz4"):
    lz4 = types.ModuleType("lz4")
    block = types.ModuleType("lz4.block")

    def _ext(out: bytearray, n: int):
        while n >= 255:
            out.append(255)
            n -= 255
        out.append(n)

    def compress(data, store_size=True, **_kw):
        data = bytes(data)
        n, out, anchor, i, table = len(data), bytearray(), 0, 0, {}

        def emit(lits: bytes, offset=None, mlen=0):
            lit_n = len(lits)
            token = (min(lit_n, 15) << 4) | (min(mlen - 4, 15) if offset else 0)
            out.append(token)
            if lit_n >= 15:
                _ext(out, lit_n - 15)
            out.extend(lits)
            if offset:
                out.extend(offset.to_bytes(2, "little"))
                if mlen - 4 >= 15:
                    _ext(out, mlen - 4 - 15)

        while i < n - 12:
            key = data[i:i + 4]
            cand = table.get(key)
            table[key] = i
            if cand is not None and i - cand <= 65535:
                ml, maxlen = 4, n - 5 - i
                while ml < maxlen and data[cand + ml] == data[i + ml]:
                    ml += 1
                emit(data[anchor:i], i - cand, ml)
                i += ml
                anchor = i
                continue
            i += 1
        emit(data[anchor:])
        res = bytes(out)
        return (n.to_bytes(4, "little") + res) if store_size else res

    def decompress(data, uncompressed_size=None, **_kw):
        data, out, i = bytes(data), bytearray(), 0
        while i < len(data):
            token = data[i]; i += 1
            lit = token >> 4
            if lit == 15:
                while True:
                    b = data[i]; i += 1; lit += b
                    if b != 255:
                        break
            out += data[i:i + lit]; i += lit
            if i >= len(data):
                break
            off = data[i] | (data[i + 1] << 8); i += 2
            ml = token & 15
            if ml == 15:
                while True:
                    b = data[i]; i += 1; ml += b
                    if b != 255:
                        break
            for _ in range(ml + 4):
                out.append(out[-off])
        return bytes(out)

    block.compress, block.decompress = compress, decompress
    lz4.block = block
    sys.modules["lz4"], sys.modules["lz4.block"] = lz4, block

if not _have("PySide6"):
    pyside, qtcore = types.ModuleType("PySide6"), types.ModuleType("PySide6.QtCore")

    class _Bound:
        def __init__(self):
            self.slots = []

        def connect(self, fn):
            self.slots.append(fn)

        def emit(self, *args):
            for fn in list(self.slots):
                fn(*args)

    class Signal:
        def __init__(self, *types_):
            self.name = None

        def __set_name__(self, owner, name):
            self.name = "_sig_" + name

        def __get__(self, obj, owner=None):
            if obj is None:
                return self
            return obj.__dict__.setdefault(self.name, _Bound())

    class QObject:
        def __init__(self, *a, **k):
            pass

    qtcore.Signal, qtcore.QObject = Signal, QObject
    pyside.QtCore = qtcore
    sys.modules["PySide6"], sys.modules["PySide6.QtCore"] = pyside, qtcore
