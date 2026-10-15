"""Shared application state: проект, движок, словарь, автосохранение, недавние проекты."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from ..config import PATHS, get_settings
from ..models.translation import ModMetadata, TranslationEntry, TranslationProject, TranslationStatus
from ..services import keystore
from ..services.dictionary import DictionaryStore
from ..services.engine import EngineOptions, TranslationEngine
from ..services.prefs import get_prefs
from ..services.providers import get_provider

log = logging.getLogger(__name__)
MAX_RECENT = 8


def api_key_for(settings, provider_name: str) -> str:
    cfg = settings.providers.get(provider_name)
    return keystore.get_api_key(provider_name, cfg.api_key if cfg else "")


class AppState(QObject):
    """Application-wide state, shared between pages via MainWindow."""

    project_changed = Signal()
    entry_edited = Signal(str)       # handle ("" = массовое изменение)

    def __init__(self):
        super().__init__()
        self.settings = get_settings()
        self.prefs = get_prefs()
        self.dictionary = DictionaryStore(Path(PATHS.cache_dir) / "dictionary.db")
        self.project: Optional[TranslationProject] = None
        self._engine: Optional[TranslationEngine] = None

        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.timeout.connect(self.save_project)
        self.dirty = False
        self.last_saved_path: Optional[Path] = None
        self.project_changed.connect(self.request_autosave)
        self.entry_edited.connect(lambda _h: self.request_autosave())

    # -- провайдер / движок ---------------------------------------------------
    def _build_provider(self):
        name = self.settings.default_provider
        cfg = self.settings.providers.get(name)
        try:
            prov = get_provider(name, api_key=api_key_for(self.settings, name),
                                model=cfg.model if cfg else "", base_url=cfg.base_url if cfg else "",
                                timeout=self.settings.timeout)
            prov.max_retries = max(0, min(int(self.settings.retry_attempts), 8))
            return prov
        except Exception:
            log.exception("Не удалось создать провайдера %s", name)
            return None

    def engine_options(self) -> EngineOptions:
        s = self.settings
        g = lambda name, default: getattr(s, name, default)          # noqa: E731
        return EngineOptions(
            batch_size=max(1, min(int(g("batch_size", 25)), 100)),
            workers=max(1, min(int(g("max_concurrent_requests", 3)), 8)),
            validate_placeholders=bool(g("validate_placeholders", True)),
            strict_placeholders=bool(g("strict_mode", False)),
            shield_placeholders=bool(g("shield_placeholders", True)),
            use_glossary=bool(g("use_glossary", True)),
            use_dictionary=bool(g("use_dictionary", True)),
            fuzzy_threshold=float(g("dictionary_match_threshold", 0.85)) if g("use_fuzzy", False) else 0.0,
            style=str(g("translation_style", "") or ""),
            custom_prompt=str(g("custom_prompt", "") or ""),
        )

    @property
    def engine(self) -> TranslationEngine:
        if self._engine is None:
            self._engine = TranslationEngine(self.dictionary, self._build_provider(), self.engine_options())
        return self._engine

    def reset_engine(self):
        """Обновляет провайдера и параметры, не пересоздавая движок (сигналы UI остаются подключёнными)."""
        if self._engine is None:
            _ = self.engine
            return
        self._engine.set_provider(self._build_provider())
        self._engine.options = self.engine_options()

    # -- проект ----------------------------------------------------------------
    def new_project(self, metadata: ModMetadata, entries: List[TranslationEntry],
                    source_lang: str, target_lang: str):
        self.project = TranslationProject(metadata=metadata, entries=entries,
                                          source_language=source_lang, target_language=target_lang)
        self.project_changed.emit()

    def set_project(self, project: Optional[TranslationProject]):
        self.project = project
        self.project_changed.emit()

    def close_project(self):
        self.save_project()
        self.project = None
        self.project_changed.emit()

    def stats(self) -> dict:
        if not self.project:
            return {"total": 0, "translated": 0, "percent": 0, "errors": 0, "review": 0, "warnings": 0}
        p = self.project
        es = p.entries
        return {
            "total": p.total_entries, "translated": p.translated_entries,
            "percent": int(p.get_progress() * 100),
            "errors": sum(1 for e in es if e.has_validation_errors()),
            "review": sum(1 for e in es if e.status == TranslationStatus.NEEDS_REVIEW),
            "warnings": sum(1 for e in es if e.validation_warnings and not e.validation_errors),
        }

    # -- сохранение --------------------------------------------------------------------
    @staticmethod
    def projects_dir() -> Path:
        d = Path(PATHS.cache_dir) / "projects"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def project_path(self, project: TranslationProject) -> Path:
        from ..services.exporter import safe_name
        return self.projects_dir() / f"{safe_name(project.metadata.name)}_{project.metadata.uuid[:8]}.json"

    def request_autosave(self):
        """Помечает проект изменённым и планирует сохранение (не чаще раза в auto_save_interval)."""
        if self.project is None:
            return
        self.dirty = True
        if not getattr(self.settings, "auto_save", True) or self._autosave.isActive():
            return
        self._autosave.start(max(3, int(getattr(self.settings, "auto_save_interval", 30))) * 1000)

    def save_project(self, path: Optional[Path] = None) -> Optional[Path]:
        project = self.project
        if project is None:
            return None
        self._autosave.stop()
        try:
            project.update_stats()
            target = Path(path) if path else self.project_path(project)
            tmp = target.with_suffix(".tmp")
            tmp.write_text(json.dumps(project.to_dict(), ensure_ascii=False), encoding="utf-8")
            tmp.replace(target)
            self._remember(target, project)
            self.dirty = False
            self.last_saved_path = target
            return target
        except Exception:
            log.exception("Не удалось сохранить проект")
            return None

    def load_project(self, path) -> TranslationProject:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        project = TranslationProject.from_dict(data)
        self.set_project(project)
        self._remember(Path(path), project)
        return project

    def recent_projects(self) -> List[dict]:
        items = [r for r in (self.prefs.get("recent_projects") or []) if Path(r.get("path", "")).exists()]
        return items[:MAX_RECENT]

    def remove_recent(self, path: str):
        self.prefs.set("recent_projects", [r for r in (self.prefs.get("recent_projects") or [])
                                           if r.get("path") != str(path)])

    def _remember(self, path: Path, project: TranslationProject):
        items = [r for r in (self.prefs.get("recent_projects") or []) if r.get("path") != str(path)]
        items.insert(0, {
            "path": str(path), "name": project.metadata.name,
            "total": project.total_entries, "translated": project.translated_entries,
            "source": project.source_language, "target": project.target_language,
            "updated": datetime.now().isoformat(timespec="seconds"),
        })
        self.prefs.set("recent_projects", items[:MAX_RECENT])


_app_state: Optional[AppState] = None


def get_app_state() -> AppState:
    global _app_state
    if _app_state is None:
        _app_state = AppState()
    return _app_state
