"""Async translation orchestration (UI never blocks).

Runs in a worker thread and reports detailed progress through PySide6
signals: stage, current mod, current file, line counters, speed, ETA and
per-entry errors. The UI thread stays responsive at all times.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QObject, Signal

from ..core.mods import ModScan, find_mods
from ..core.validation import compare_placeholders
from ..models.translation import (
    DictionaryEntry,
    TranslationEntry,
    TranslationProject,
    TranslationStatus,
)
from ..services.dictionary import DictionaryStore
from ..services.providers import BaseProvider, TranslateRequest, TranslationError


class StageId(str, Enum):
    """High-level stages of a translation run (shown to the user)."""

    SEARCHING_MODS = "searching_mods"
    ANALYZING = "analyzing"
    FINDING_STRINGS = "finding_strings"
    EXTRACTING_TEXT = "extracting_text"
    TRANSLATING = "translating"
    SAVING = "saving"
    DONE = "done"


STAGE_TEXT = {
    StageId.SEARCHING_MODS: "Поиск модов",
    StageId.ANALYZING: "Анализ структуры мода",
    StageId.FINDING_STRINGS: "Поиск переводимых строк",
    StageId.EXTRACTING_TEXT: "Извлечение текста",
    StageId.TRANSLATING: "Перевод через Gemini",
    StageId.SAVING: "Сохранение результата",
    StageId.DONE: "Завершено",
}


@dataclass
class JobProgress:
    """Detailed, UI-friendly progress payload emitted on every step."""

    stage: str = StageId.SEARCHING_MODS.value
    stage_text: str = STAGE_TEXT[StageId.SEARCHING_MODS]
    current_mod: str = ""
    current_file: str = ""
    current_line: int = 0
    lines_total: int = 0
    processed_files: int = 0
    total_files: int = 0
    done: int = 0
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    errors: int = 0
    warnings: int = 0
    skipped: int = 0
    percent: int = 0
    elapsed_seconds: float = 0.0
    eta_seconds: float = 0.0
    speed_lines_per_sec: float = 0.0

    found_files: int = 0
    supported_files: int = 0
    unsupported: List[str] = field(default_factory=list)
    error_details: Dict[str, str] = field(default_factory=dict)

    message: str = ""


class TranslationEngine(QObject):
    """Long-running translation runs in a worker thread and reports progress
    through PySide6 signals. Never blocks the UI thread."""

    progress = Signal(object)      # JobProgress
    stage = Signal(str, str)       # stage_id, human text
    finished = Signal(object)      # TranslationProject
    error = Signal(str)            # human-readable message
    cancelled = Signal()

    def __init__(self, dictionary: Optional[DictionaryStore], provider: Optional[BaseProvider] = None):
        super().__init__()
        self.dictionary = dictionary
        self.provider = provider
        self.strict_placeholders = True

        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._callback: Optional[Callable[[JobProgress], None]] = None

    # -- public control ---------------------------------------------------
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def run_async(self, project: TranslationProject, callback: Optional[Callable[[JobProgress], None]] = None):
        if self.is_running():
            return
        self._stop.clear()
        self._callback = callback
        self._worker = threading.Thread(target=self._run_core, args=(project,), daemon=True)
        self._worker.start()

    def cancel(self):
        """Request a graceful stop; the worker finishes the current entry."""
        self._stop.set()
        self.cancelled.emit()

    # -- synchronous API (on-demand / tests) ------------------------------
    def translate_entry(self, entry: TranslationEntry) -> bool:
        """Translate a single entry synchronously. Returns True on success."""
        return self._translate_one(entry) == "ok"

    def translate_batch(self, entries: List[TranslationEntry], on_progress: Optional[Callable[[JobProgress], None]] = None) -> JobProgress:
        """Translate a list of entries synchronously, reporting progress."""
        total = len(entries)
        pg = JobProgress(total_files=total, lines_total=total, total=total)
        for i, e in enumerate(entries, 1):
            status = self._translate_one(e)
            if status == "ok":
                pg.succeeded += 1
            elif status == "skip":
                pg.skipped += 1
            else:
                pg.failed += 1
                reason = "; ".join(e.validation_errors) if e.validation_errors else "Перевод не удался"
                pg.error_details[e.handle] = reason
            pg.done = i
            pg.processed_files = i
            pg.percent = int(i * 100 / total) if total else 100
            if on_progress is not None:
                on_progress(pg)
        return pg


    # -- worker body ------------------------------------------------------
    def _run_core(self, project: TranslationProject):
        start = time.monotonic()
        try:
            entries: List[TranslationEntry] = list(project.entries)
            if not entries and project.metadata.source_path:
                entries = self._scan_project(project)

            if not entries:
                self.error.emit(
                    "Моды не найдены. Проверьте путь к папке модов или добавьте мод вручную."
                )
                return

            project.entries = entries

            total = len(entries)
            self._emit_stage(StageId.ANALYZING)
            self._emit(JobProgress(
                stage=StageId.ANALYZING.value,
                stage_text=STAGE_TEXT[StageId.ANALYZING],
                current_mod=project.metadata.name,
                found_files=total,
                total_files=total,
            ))

            self._emit_stage(StageId.TRANSLATING)
            succeeded = failed = skipped = 0
            for i, e in enumerate(entries, 1):
                if self._stop.is_set():
                    self.cancelled.emit()
                    return

                status = self._translate_one(e)
                if status == "ok":
                    succeeded += 1
                elif status == "skip":
                    skipped += 1
                else:
                    failed += 1

                elapsed = time.monotonic() - start
                speed = (succeeded + failed) / elapsed if elapsed > 0 else 0.0
                remaining = total - i
                eta = remaining / speed if speed > 0 else 0.0

                pg = JobProgress(
                    stage=StageId.TRANSLATING.value,
                    stage_text=STAGE_TEXT[StageId.TRANSLATING],
                    current_mod=project.metadata.name,
                    current_file=e.context or e.handle,
                    current_line=i,
                    lines_total=total,
                    processed_files=i,
                    total_files=total,
                    succeeded=succeeded,
                    failed=failed,
                    skipped=skipped,
                    percent=int(i * 100 / total),
                    elapsed_seconds=round(elapsed, 1),
                    eta_seconds=round(eta, 1),
                    speed_lines_per_sec=round(speed, 2),
                )
                if status == "fail":
                    reason = "; ".join(e.validation_errors) if e.validation_errors else "Перевод не удался"
                    pg.error_details[e.handle] = reason
                self._emit(pg)

            self._emit_stage(StageId.SAVING)
            project.update_stats()
            self._emit_stage(StageId.DONE)
            self.finished.emit(project)
        except Exception as exc:  # safety net
            self.error.emit(f"Не удалось обработать мод: {exc}")

    def _scan_project(self, project: TranslationProject) -> List[TranslationEntry]:
        """Scan source_path into translation entries (folder with mods)."""
        self._emit_stage(StageId.SEARCHING_MODS)
        scans: List[ModScan] = find_mods(Path(project.metadata.source_path))
        entries: List[TranslationEntry] = []
        for scan in scans:
            entries.extend(scan.entries)
        return entries

    def _translate_one(self, entry: TranslationEntry) -> str:
        """Translate a single entry. Returns 'ok' | 'skip' | 'fail'."""
        if not entry.source_text.strip():
            return "skip"
        if entry.is_translated():
            return "ok"

        if self.dictionary is not None:
            hit = self.dictionary.lookup(entry.source_text, entry.source_language, entry.target_language)
            if hit is not None:
                entry.target_text = hit.target_text
                entry.status = TranslationStatus.DICTIONARY_MATCH
                entry.update_timestamps()
                return "ok"

        if self.provider is None or not self.provider.is_configured():
            return "fail"

        try:
            result = self.provider.translate(
                TranslateRequest(
                    texts=[entry.source_text],
                    source_lang=entry.source_language,
                    target_lang=entry.target_language,
                    context=entry.context,
                )
            )
        except TranslationError:
            return "fail"

        candidate = result.texts[0] if result.texts else entry.source_text
        errs, warns = compare_placeholders(entry.source_text, candidate)
        if errs and self.strict_placeholders:
            entry.validation_errors = errs
            return "fail"

        entry.target_text = candidate
        entry.status = TranslationStatus.AUTO_TRANSLATED
        entry.translated_by = f"ai:{getattr(result, 'provider', 'provider')}"
        entry.validation_errors = errs
        entry.validation_warnings = warns
        entry.update_timestamps()

        if self.dictionary is not None:
            self.dictionary.add(DictionaryEntry(
                source_text=entry.source_text,
                source_language=entry.source_language,
                target_text=candidate,
                target_language=entry.target_language,
                handle=entry.handle,
                context=entry.context,
            ))
        return "ok"

    # -- emit helpers -----------------------------------------------------
    def _emit(self, pg: JobProgress):
        self.progress.emit(pg)
        if self._callback is not None:
            try:
                self._callback(pg)
            except Exception:
                pass

    def _emit_stage(self, stage_id: StageId):
        self.stage.emit(stage_id.value, STAGE_TEXT[stage_id])
