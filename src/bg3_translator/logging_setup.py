"""Логирование в файл (с ротацией) + консоль."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Optional

_configured: Optional[Path] = None


def default_log_dir() -> Path:
    try:
        from .config import PATHS
        return Path(PATHS.cache_dir) / "logs"
    except Exception:
        import tempfile
        return Path(tempfile.gettempdir()) / "bg3mt_logs"


def setup_logging(log_dir: Optional[Path] = None, level: int = logging.INFO) -> Path:
    """Идемпотентно настраивает логирование. Возвращает путь к файлу журнала."""
    global _configured
    if _configured is not None:
        return _configured
    d = Path(log_dir) if log_dir else default_log_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / "bg3_translator.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    fh = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    _configured = path
    return path
