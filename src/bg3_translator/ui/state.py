"""Shared application state (current project, services)."""

from typing import Optional

from PySide6.QtCore import QObject, Signal

from ..config import PATHS, get_settings
from ..models.translation import TranslationEntry, TranslationProject, ModMetadata
from ..services.dictionary import DictionaryStore
from ..services.engine import TranslationEngine
from ..services.providers import get_provider


class AppState(QObject):
    """Application-wide state, shared between pages via MainWindow."""

    project_changed = Signal()
    entry_edited = Signal(str)  # handle

    def __init__(self):
        super().__init__()
        self.settings = get_settings()
        self.dictionary = DictionaryStore(PATHS.cache_dir / "dictionary.db")
        self.project: Optional[TranslationProject] = None
        self._engine: Optional[TranslationEngine] = None

    @property
    def engine(self) -> TranslationEngine:
        if self._engine is None:
            provider = None
            prov_cfg = self.settings.providers.get(self.settings.default_provider)
            try:
                provider = get_provider(
                    self.settings.default_provider,
                    api_key=prov_cfg.api_key if prov_cfg else "",
                    model=prov_cfg.model if prov_cfg else "",
                    base_url=prov_cfg.base_url if prov_cfg else "",
                    timeout=self.settings.timeout,
                )
            except Exception:
                provider = None
            self._engine = TranslationEngine(self.dictionary, provider=provider)
        return self._engine

    def reset_engine(self):
        self._engine = None

    def new_project(self, metadata: ModMetadata, entries: list[TranslationEntry],
                    source_lang: str, target_lang: str):
        self.project = TranslationProject(
            metadata=metadata,
            entries=entries,
            source_language=source_lang,
            target_language=target_lang,
        )
        self.project_changed.emit()

    def close_project(self):
        self.project = None
        self.project_changed.emit()

    def stats(self) -> dict:
        if not self.project:
            return {"total": 0, "translated": 0, "percent": 0, "errors": 0}
        p = self.project
        return {
            "total": p.total_entries,
            "translated": p.translated_entries,
            "percent": int(p.get_progress() * 100),
            "errors": sum(1 for e in p.entries if e.has_validation_errors()),
        }


_app_state: Optional[AppState] = None


def get_app_state() -> AppState:
    global _app_state
    if _app_state is None:
        _app_state = AppState()
    return _app_state