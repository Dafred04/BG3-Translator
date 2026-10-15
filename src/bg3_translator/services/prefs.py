"""Небольшие пользовательские настройки, которых нет в config (JSON в папке кэша)."""

from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional

DEFAULTS = {
    "recent_projects": [],
    "last_dir": "",
}


def _default_path() -> Path:
    try:
        from ..config import PATHS
        return Path(PATHS.cache_dir) / "prefs.json"
    except Exception:
        return Path(tempfile.gettempdir()) / "bg3mt_prefs.json"


class Prefs:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else _default_path()
        self._lock = threading.Lock()
        self._data: dict = {}
        try:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self._data = {}

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._data:
            return self._data[key]
        return DEFAULTS.get(key, default) if default is None else default

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._flush()

    def _flush(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass


_prefs: Optional[Prefs] = None


def get_prefs() -> Prefs:
    global _prefs
    if _prefs is None:
        _prefs = Prefs()
    return _prefs
