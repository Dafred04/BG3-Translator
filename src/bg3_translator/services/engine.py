"""Пакетный асинхронный перевод (UI не блокируется).

Конвейер:
  словарь (точные + необязательные нечёткие совпадения)  ->  дедупликация одинаковых строк
  ->  пачки по N строк в M потоков  ->  защита плейсхолдеров токенами  ->  проверка/QA
  ->  запись в словарь.

Отмена: cancel() только ставит флаг; сигнал `cancelled` испускает ровно один раз сам воркер,
когда реально остановился. Повторный запуск до этого момента отклоняется (run_async -> False).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Deque, Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal

from ..core.validation import DEFAULT_TOKEN, compare_placeholders, qa_check, shield, unshield
from ..models.translation import (
    DictionaryEntry, TranslationEntry, TranslationProject, TranslationStatus,
)
from .dictionary import DictionaryStore
from .providers import (
    BaseProvider, BatchMismatchError, FatalTranslationError, TranslateRequest, TranslationError,
)

log = logging.getLogger(__name__)


class StageId(str, Enum):
    SEARCHING_MODS = "searching_mods"
    ANALYZING = "analyzing"
    FINDING_STRINGS = "finding_strings"
    EXTRACTING_TEXT = "extracting_text"
    TRANSLATING = "translating"
    SAVING = "saving"
    DONE = "done"


STAGE_TEXT = {
    StageId.SEARCHING_MODS: "Поиск модов",
    StageId.ANALYZING: "Анализ мода",
    StageId.FINDING_STRINGS: "Поиск строк для перевода",
    StageId.EXTRACTING_TEXT: "Поиск в словаре",
    StageId.TRANSLATING: "Перевод ИИ",
    StageId.SAVING: "Сохранение результата",
    StageId.DONE: "Завершено",
}
STAGE_ORDER = list(STAGE_TEXT.keys())

STAGE_ICON_PENDING = "○"
STAGE_ICON_ACTIVE = "►"
STAGE_ICON_DONE = "•"


@dataclass
class EngineOptions:
    batch_size: int = 25
    max_batch_chars: int = 6000
    workers: int = 3
    validate_placeholders: bool = True
    strict_placeholders: bool = True       # ошибка плейсхолдеров -> NEEDS_REVIEW (перевод сохраняется)
    shield_placeholders: bool = True
    qa_checks: bool = True
    use_glossary: bool = True
    use_dictionary: bool = True            # искать готовые переводы в словаре
    fuzzy_threshold: float = 0.0           # 0 = выключено; иначе 0.8..0.99
    max_consecutive_failures: int = 5
    style: str = ""
    custom_prompt: str = ""


@dataclass
class JobProgress:
    """Подробный payload прогресса для UI."""

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
    review: int = 0
    from_dictionary: int = 0
    chars_sent: int = 0
    unique_total: int = 0
    percent: int = 0
    elapsed_seconds: float = 0.0
    eta_seconds: float = 0.0
    speed_lines_per_sec: float = 0.0

    found_files: int = 0
    supported_files: int = 0
    unsupported: List[str] = field(default_factory=list)
    error_details: Dict[str, str] = field(default_factory=dict)
    message: str = ""


class _Stopped(Exception):
    pass


def make_chunks(texts: List[str], batch_size: int, max_chars: int) -> List[List[str]]:
    chunks: List[List[str]] = []
    cur: List[str] = []
    chars = 0
    for t in texts:
        if cur and (len(cur) >= batch_size or chars + len(t) > max_chars):
            chunks.append(cur)
            cur, chars = [], 0
        cur.append(t)
        chars += len(t)
    if cur:
        chunks.append(cur)
    return chunks


class TranslationEngine(QObject):
    progress = Signal(object)          # JobProgress
    stage = Signal(str, str)           # stage_id, text
    finished = Signal(object)          # TranslationProject
    error = Signal(str)
    cancelled = Signal()
    entries_updated = Signal(object)   # list[str] handles, меняется по ходу прогона

    def __init__(self, dictionary: Optional[DictionaryStore], provider: Optional[BaseProvider] = None,
                 options: Optional[EngineOptions] = None):
        super().__init__()
        self.dictionary = dictionary
        self.provider = provider
        self.options = options or EngineOptions()
        self.first_error: Optional[str] = None
        self.last_failures: Dict[str, str] = {}

        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._callback: Optional[Callable[[JobProgress], None]] = None

    # совместимость со старым кодом
    @property
    def strict_placeholders(self) -> bool:
        return self.options.strict_placeholders

    @strict_placeholders.setter
    def strict_placeholders(self, v: bool):
        self.options.strict_placeholders = v

    # -- управление ---------------------------------------------------------
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def is_cancelling(self) -> bool:
        return self.is_running() and self._stop.is_set()

    def run_async(self, project: TranslationProject,
                  callback: Optional[Callable[[JobProgress], None]] = None) -> bool:
        """Запускает перевод в фоне. False — предыдущий прогон ещё не завершился."""
        if self.is_running():
            return False
        self._stop.clear()
        self._callback = callback
        self._worker = threading.Thread(target=self._run_core, args=(project,), daemon=True)
        self._worker.start()
        return True

    def cancel(self):
        """Просит остановиться. Сигнал `cancelled` придёт от воркера, когда он остановится."""
        self._stop.set()

    def set_provider(self, provider: Optional[BaseProvider]):
        self.provider = provider

    # -- синхронный API (CLI, тесты) -----------------------------------------
    def translate_batch(self, entries: List[TranslationEntry],
                        on_progress: Optional[Callable[[JobProgress], None]] = None,
                        mod_name: str = "") -> JobProgress:
        self._stop.clear()
        last = self._process(entries, mod_name, on_progress)
        return last

    def translate_entry(self, entry: TranslationEntry) -> bool:
        pg = self.translate_batch([entry])
        return entry.is_translated() and pg.failed == 0

    # -- рабочий поток --------------------------------------------------------
    def _run_core(self, project: TranslationProject):
        self.first_error = None
        try:
            entries = list(project.entries)
            if not entries and project.metadata.source_path:
                entries = self._scan_project(project)
            if not entries:
                self.error.emit("Строки для перевода не найдены.")
                return
            project.entries = entries
            pg = self._process(entries, project.metadata.name, self._emit)
            if pg.message == "cancelled":
                self.cancelled.emit()
                return
            if pg.message.startswith("aborted:"):
                self.error.emit(pg.message[len("aborted:"):].strip())
                return
            project.update_stats()
            self.finished.emit(project)
        except Exception as exc:
            log.exception("Сбой воркера перевода")
            self.error.emit(f"Не удалось обработать мод: {exc}")

    def _scan_project(self, project: TranslationProject) -> List[TranslationEntry]:
        from .importer import import_mod
        self._emit_stage(StageId.SEARCHING_MODS)
        res = import_mod(project.metadata.source_path, project.source_language, project.target_language)
        return res.entries

    # -- ядро -----------------------------------------------------------------
    def _process(self, entries: List[TranslationEntry], mod_name: str,
                 on_progress: Optional[Callable[[JobProgress], None]]) -> JobProgress:
        return _Run(self, entries, mod_name, on_progress).run()

    # -- emit helpers -----------------------------------------------------------
    def _emit(self, pg: JobProgress):
        self.progress.emit(pg)
        if self._callback is not None:
            try:
                self._callback(pg)
            except Exception:
                log.exception("Ошибка в callback прогресса")

    def _emit_stage(self, stage_id: StageId, text: Optional[str] = None):
        self.stage.emit(stage_id.value, text or STAGE_TEXT[stage_id])


Chunk = List[str]
Result = Tuple[Optional[str], Optional[str], Dict[str, str]]     # (перевод | None, ошибка | None, глоссарий)


class _Run:
    """Состояние одного прогона перевода."""

    def __init__(self, engine: TranslationEngine, entries: List[TranslationEntry], mod_name: str,
                 on_progress: Optional[Callable[[JobProgress], None]]):
        self.eng = engine
        self.opt = engine.options
        self.entries = entries
        self.mod_name = mod_name
        self.total = len(entries)
        self.t0 = time.monotonic()
        self.already = 0
        self.api_total = 0
        self.api_done = 0
        self.history: Deque[Tuple[float, int]] = deque()
        self.ctx_left: Dict[str, int] = {}
        self.groups: Dict[str, List[TranslationEntry]] = {}
        self.halt = threading.Event()
        self.on_progress = on_progress or engine._emit
        self.src = entries[0].source_language if entries else "en"
        self.tgt = entries[0].target_language if entries else "ru"
        self.pg = JobProgress(current_mod=mod_name, total=self.total, lines_total=self.total)
        for e in entries:
            if e.context:
                self.ctx_left[e.context] = self.ctx_left.get(e.context, 0) + 1
        # Нет информации о файлах (одиночные записи) — «файл» = строка, как в прежней версии.
        self.use_ctx = bool(self.ctx_left)
        self.pg.total_files = len(self.ctx_left) if self.use_ctx else self.total
        engine.last_failures = {}

    # -- прогресс -------------------------------------------------------------------
    def _snapshot(self, stage: StageId, text: Optional[str] = None):
        pg = self.pg
        pg.stage, pg.stage_text = stage.value, text or STAGE_TEXT[stage]
        now = time.monotonic()
        pg.elapsed_seconds = round(now - self.t0, 1)
        pg.done = pg.current_line = pg.succeeded + pg.failed + pg.skipped + self.already
        pg.processed_files = (sum(1 for v in self.ctx_left.values() if v <= 0)
                              if self.use_ctx else pg.done)
        pg.percent = int(pg.done * 100 / self.total) if self.total else 100
        if self.api_done:
            self.history.append((now, self.api_done))
            while len(self.history) > 1 and now - self.history[0][0] > 20:
                self.history.popleft()
            first, last = self.history[0], self.history[-1]
            speed = ((last[1] - first[1]) / (last[0] - first[0]) if len(self.history) > 1 and last[0] > first[0]
                     else self.api_done / max(now - self.t0, 0.001))
            pg.speed_lines_per_sec = round(speed, 2)
            pg.eta_seconds = round(max(self.api_total - self.api_done, 0) / speed, 1) if speed > 0 else 0.0

    def stage(self, stage: StageId, text: Optional[str] = None):
        self.eng._emit_stage(stage, text)
        self._snapshot(stage, text)
        self.on_progress(self.pg)

    def tick(self, stage: StageId, text: Optional[str] = None):
        self._snapshot(stage, text)
        self.on_progress(self.pg)

    def finish(self, e: TranslationEntry):
        if e.context in self.ctx_left:
            self.ctx_left[e.context] -= 1

    def stopped(self) -> bool:
        return self.eng._stop.is_set() or self.halt.is_set()

    # -- сценарий ----------------------------------------------------------------------
    def run(self) -> JobProgress:
        pg = self.pg
        self.stage(StageId.ANALYZING)
        self.stage(StageId.FINDING_STRINGS)
        for e in self.entries:
            if not e.source_text.strip():
                pg.skipped += 1
                self.finish(e)
            elif e.is_translated():
                self.already += 1
                self.finish(e)
            else:
                self.groups.setdefault(e.source_text, []).append(e)
        pg.unique_total = len(self.groups)
        self.tick(StageId.FINDING_STRINGS)
        if self.eng._stop.is_set():
            return self._end("cancelled")

        self.stage(StageId.EXTRACTING_TEXT)
        pending = self._dictionary_pass(list(self.groups))
        self.tick(StageId.EXTRACTING_TEXT)
        if self.eng._stop.is_set():
            return self._end("cancelled")

        prov = self.eng.provider
        if pending and (prov is None or not prov.is_configured()):
            reason = ("Провайдер перевода не настроен. Укажите ключ API в «Настройках» — "
                      "пока переведено только из словаря.")
            self.eng.first_error = self.eng.first_error or reason
            for text in pending:
                for e in self.groups[text]:
                    e.validation_errors = ["Провайдер перевода не настроен (нет ключа API)"]
                    self.eng.last_failures[e.handle] = e.validation_errors[0]
                    pg.failed += 1
                    self.finish(e)
            pending = []

        outcome = ""
        if pending:
            self.api_total = sum(len(self.groups[t]) for t in pending)
            name = getattr(prov, "display_name", "ИИ")
            self.stage(StageId.TRANSLATING, f"Перевод: {name}")
            outcome = self._translate(pending)

        pg.errors = pg.failed
        if outcome:
            return self._end(outcome)
        self.stage(StageId.SAVING)
        pg.percent = 100
        self.stage(StageId.DONE)
        return self._end("")

    def _end(self, message: str) -> JobProgress:
        self.pg.errors = self.pg.failed
        self.pg.message = message
        return self.pg

    # -- словарь ---------------------------------------------------------------------------------
    def _dictionary_pass(self, pending: List[str]) -> List[str]:
        dic, pg = self.eng.dictionary, self.pg
        if dic is None or not pending or not self.opt.use_dictionary:
            return pending
        touched: List[str] = []
        hits = dic.lookup_many(pending, self.src, self.tgt)
        for text, hit in hits.items():
            for e in self.groups[text]:
                e.target_text = hit.target_text
                e.status = TranslationStatus.DICTIONARY_MATCH
                e.validation_errors, e.validation_warnings = [], []
                e.update_timestamps()
                self.finish(e)
                touched.append(e.handle)
                pg.succeeded += 1
                pg.from_dictionary += 1
        pending = [t for t in pending if t not in hits]
        if self.opt.fuzzy_threshold > 0:
            for text in list(pending):
                fz = dic.lookup_fuzzy(text, self.src, self.tgt, self.opt.fuzzy_threshold)
                if not fz:
                    continue
                entry, ratio = fz
                for e in self.groups[text]:
                    e.target_text = entry.target_text
                    e.status = TranslationStatus.NEEDS_REVIEW
                    e.validation_errors = []
                    e.validation_warnings = [f"Нечёткое совпадение со словарём ({ratio:.0%})"]
                    e.update_timestamps()
                    self.finish(e)
                    touched.append(e.handle)
                    pg.succeeded += 1
                    pg.review += 1
                pending.remove(text)
        if touched:
            self.eng.entries_updated.emit(touched)
        return pending

    # -- перевод пачками ---------------------------------------------------------------------------
    def _translate(self, pending: List[str]) -> str:
        opt, pg = self.opt, self.pg
        chunks = iter(make_chunks(pending, max(opt.batch_size, 1), opt.max_batch_chars))
        in_flight: Dict = {}
        consecutive = 0
        abort = ""
        workers = max(opt.workers, 1)

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="translate") as pool:
            def submit_next() -> bool:
                chunk = next(chunks, None)
                if chunk is None or self.stopped():
                    return False
                in_flight[pool.submit(self._call_chunk, chunk)] = chunk
                return True

            for _ in range(workers):
                if not submit_next():
                    break
            while in_flight:
                done, _ = wait(list(in_flight), return_when=FIRST_COMPLETED)
                for fut in done:
                    chunk = in_flight.pop(fut)
                    try:
                        results = fut.result()
                    except _Stopped:
                        continue
                    except FatalTranslationError as exc:
                        abort = str(exc)
                        self.eng.first_error = self.eng.first_error or abort
                        self.halt.set()
                        continue
                    except Exception as exc:                       # непредвиденный сбой в потоке
                        log.exception("Сбой при переводе пачки")
                        results = [(None, f"Внутренняя ошибка: {exc}", {}) for _ in chunk]
                    ok = self._apply_chunk(chunk, results)
                    consecutive = 0 if ok else consecutive + 1
                    if consecutive >= opt.max_consecutive_failures and not abort:
                        last = next((r[1] for r in results if r[1]), "неизвестная ошибка")
                        abort = (f"Остановлено: {consecutive} пачек подряд завершились ошибкой. "
                                 f"Последняя причина: {last}")
                        self.halt.set()
                    if not self.halt.is_set():
                        submit_next()
        if abort:
            return f"aborted: {abort}"
        if self.eng._stop.is_set():
            return "cancelled"
        return ""

    def _call_chunk(self, chunk: Chunk) -> List[Result]:
        if self.stopped():
            raise _Stopped()
        return self._call_texts(chunk)

    def _call_texts(self, texts: Chunk) -> List[Result]:
        if self.stopped():
            raise _Stopped()
        try:
            return self._request_once(texts)
        except BatchMismatchError as exc:
            if len(texts) == 1:
                return [(None, str(exc), {})]
            mid = len(texts) // 2
            return self._call_texts(texts[:mid]) + self._call_texts(texts[mid:])
        except FatalTranslationError:
            raise
        except TranslationError as exc:
            return [(None, str(exc), {}) for _ in texts]

    def _request_once(self, texts: Chunk) -> List[Result]:
        prov, opt, dic = self.eng.provider, self.opt, self.eng.dictionary
        use_shield = opt.shield_placeholders and getattr(prov, "supports_shielding", True)
        fmt = getattr(prov, "token_fmt", DEFAULT_TOKEN)
        prepared, originals, glossaries = [], [], []
        for t in texts:
            s, o = shield(t, fmt) if use_shield else (t, [])
            prepared.append(s)
            originals.append(o)
            glossaries.append(dic.glossary_for(t, self.src, self.tgt) if (opt.use_glossary and dic) else {})
        merged: Dict[str, str] = {}
        for g in glossaries:
            merged.update(g)
        req = TranslateRequest(
            texts=prepared, source_lang=self.src, target_lang=self.tgt,
            context=f"Mod: {self.mod_name}" if self.mod_name else "",
            glossary=merged, style=opt.style, custom_prompt=opt.custom_prompt,
            token_example=fmt.format(n=1) if any(originals) else "",
        )
        res = prov.translate(req)
        if len(res.texts) != len(texts):
            raise BatchMismatchError(f"Вернулось {len(res.texts)} строк вместо {len(texts)}")
        out: List[Result] = []
        for cand, orig, gl in zip(res.texts, originals, glossaries):
            if orig:
                cand, problems = unshield(cand, orig, fmt)
                if problems:
                    out.append((None, "; ".join(problems), gl))
                    continue
            out.append((cand, None, gl))
        return out

    def _apply_chunk(self, chunk: Chunk, results: List[Result]) -> bool:
        """Записывает результаты в записи. True, если хоть одна строка пачки переведена."""
        pg, opt, dic = self.pg, self.opt, self.eng.dictionary
        handles: List[str] = []
        to_dict: List[DictionaryEntry] = []
        any_ok = False
        for text, (cand, err, gl) in zip(chunk, results):
            group = self.groups[text]
            self.api_done += len(group)
            pg.chars_sent += len(text)
            if cand is None:
                self.eng.first_error = self.eng.first_error or err
                for e in group:
                    e.validation_errors = [err or "Перевод не удался"]
                    self.eng.last_failures[e.handle] = e.validation_errors[0]
                    pg.failed += 1
                    pg.error_details[e.handle] = e.validation_errors[0]
                    self.finish(e)
                    handles.append(e.handle)
                continue
            any_ok = True
            errs: List[str] = []
            warns: List[str] = []
            if opt.validate_placeholders:
                errs, warns = compare_placeholders(text, cand)
            if opt.qa_checks:
                warns = warns + qa_check(text, cand, self.tgt, gl)
            flagged = bool(errs) and opt.strict_placeholders
            status = TranslationStatus.NEEDS_REVIEW if flagged else TranslationStatus.AUTO_TRANSLATED
            for e in group:
                e.target_text = cand
                e.status = status
                e.translated_by = f"ai:{getattr(self.eng.provider, 'name', 'provider')}"
                e.validation_errors, e.validation_warnings = list(errs), list(warns)
                e.update_timestamps()
                pg.succeeded += 1
                if flagged:
                    pg.review += 1
                if warns:
                    pg.warnings += 1
                self.finish(e)
                handles.append(e.handle)
            if not errs:
                to_dict.append(DictionaryEntry(
                    source_text=text, source_language=self.src, target_text=cand,
                    target_language=self.tgt, handle=group[0].handle, context=group[0].context,
                    source_mod=self.mod_name))
        if dic is not None and to_dict:
            dic.add_many(to_dict)
        last = self.groups[chunk[-1]][-1]
        pg.current_file = last.context or last.handle
        pg.error_details = {h: self.eng.last_failures[h] for h in handles if h in self.eng.last_failures}
        if handles:
            self.eng.entries_updated.emit(handles)
        self.tick(StageId.TRANSLATING, f"Перевод: {getattr(self.eng.provider, 'display_name', 'ИИ')}")
        return any_ok
