"""Логика интерфейса без Qt: фильтры, оценка перевода, поиск-замена, состояния строк.

Всё, что можно проверить обычными тестами, лежит здесь; виджеты только вызывают эти функции.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from ..core.validation import compare_placeholders, qa_check
from ..models.translation import TranslationEntry, TranslationProject, TranslationStatus

FILTER_MODES = (
    ("all", "Все строки"),
    ("untranslated", "Не переведено"),
    ("translated", "Переведено"),
    ("review", "На проверке"),
    ("errors", "С ошибками"),
    ("warnings", "С предупреждениями"),
)

STATUS_LABELS = {
    TranslationStatus.NEW: "○ Новый",
    TranslationStatus.TRANSLATED: "● Переведено",
    TranslationStatus.DICTIONARY_MATCH: "◆ Словарь",
    TranslationStatus.AUTO_TRANSLATED: "▲ AI",
    TranslationStatus.NEEDS_REVIEW: "⚑ Проверка",
    TranslationStatus.APPROVED: "✔ Готово",
    TranslationStatus.LOCKED: "Закрыто",
}


def status_label(entry: TranslationEntry) -> str:
    """Текст статуса в таблице. Ошибка важнее статуса; предупреждения видны по цвету и подсказке."""
    if entry.validation_errors:
        return "✖ Ошибка"
    return STATUS_LABELS.get(entry.status, entry.status.value)


def row_tone(entry: TranslationEntry) -> str:
    """'error' | 'warning' | 'review' | 'ok' | 'new' — для цвета строки."""
    if entry.validation_errors:
        return "error"
    if entry.status == TranslationStatus.NEEDS_REVIEW:
        return "review"
    if entry.validation_warnings and entry.is_translated():
        return "warning"
    if not entry.is_translated():
        return "new"
    return "ok"


def entry_matches(entry: TranslationEntry, needle: str, mode: str) -> bool:
    if needle:
        n = needle.lower()
        if n not in entry.source_text.lower() and n not in entry.target_text.lower() \
                and n not in entry.handle.lower():
            return False
    if mode == "untranslated":
        return not entry.is_translated()
    if mode == "translated":
        return entry.is_translated()
    if mode == "review":
        return entry.status == TranslationStatus.NEEDS_REVIEW
    if mode == "errors":
        return entry.has_validation_errors()
    if mode == "warnings":
        return bool(entry.validation_warnings) and not entry.validation_errors
    return True


def revalidate(entry: TranslationEntry, target_lang: Optional[str] = None,
               glossary: Optional[Dict[str, str]] = None, check_qa: bool = True) -> None:
    """Пересчитывает ошибки и предупреждения записи после ручной правки."""
    if not entry.target_text.strip():
        entry.validation_errors, entry.validation_warnings = [], []
        return
    errs, warns = compare_placeholders(entry.source_text, entry.target_text)
    if check_qa:
        warns = warns + qa_check(entry.source_text, entry.target_text,
                                 target_lang or entry.target_language, glossary)
    entry.validation_errors, entry.validation_warnings = errs, warns


def set_target(entry: TranslationEntry, text: str, status: Optional[TranslationStatus] = None,
               **kw) -> bool:
    """Меняет перевод и статус, пересчитывает проверки. True, если что-то изменилось."""
    if text == entry.target_text and (status is None or status == entry.status):
        return False
    entry.target_text = text
    if status is not None:
        entry.status = status
    else:
        entry.status = TranslationStatus.TRANSLATED if text.strip() else TranslationStatus.NEW
    entry.translated_by = "manual" if text.strip() else ""
    revalidate(entry, **kw)
    entry.update_timestamps()
    return True


# ---------------------------------------------------------------------------
# Оценка перед запуском
# ---------------------------------------------------------------------------
@dataclass
class Estimate:
    total: int = 0
    untranslated: int = 0
    unique: int = 0
    from_dictionary: int = 0
    to_translate: int = 0           # уникальных строк, уходящих в ИИ
    chars: int = 0
    requests: int = 0
    seconds: float = 0.0

    @property
    def needs_provider(self) -> bool:
        return self.to_translate > 0


def estimate_job(entries: Iterable[TranslationEntry], dictionary=None, *, batch_size: int = 25,
                 max_batch_chars: int = 6000, workers: int = 3, use_dictionary: bool = True,
                 seconds_per_request: float = 6.0) -> Estimate:
    entries = list(entries)
    est = Estimate(total=len(entries))
    groups: Dict[str, int] = {}
    for e in entries:
        if e.source_text.strip() and not e.is_translated():
            groups[e.source_text] = groups.get(e.source_text, 0) + 1
    est.untranslated = sum(groups.values())
    est.unique = len(groups)
    pending = list(groups)
    if dictionary is not None and use_dictionary and pending:
        src = entries[0].source_language
        tgt = entries[0].target_language
        hits = dictionary.lookup_many(pending, src, tgt, bump=False)
        est.from_dictionary = sum(groups[t] for t in hits)
        pending = [t for t in pending if t not in hits]
    est.to_translate = len(pending)
    est.chars = sum(len(t) for t in pending)
    chunks, cur_n, cur_c = 0, 0, 0
    for t in pending:
        if cur_n and (cur_n >= batch_size or cur_c + len(t) > max_batch_chars):
            chunks += 1
            cur_n, cur_c = 0, 0
        cur_n += 1
        cur_c += len(t)
    chunks += 1 if cur_n else 0
    est.requests = chunks
    est.seconds = chunks * seconds_per_request / max(workers, 1)
    return est


def format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds <= 0:
        return "—"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} ч {m:02d} мин"
    if m:
        return f"{m} мин {s:02d} с"
    return f"{s} с"


# ---------------------------------------------------------------------------
# Найти и заменить
# ---------------------------------------------------------------------------
def compile_find(find: str, case: bool = False, whole: bool = False, regex: bool = False):
    if not find:
        raise ValueError("Пустой запрос")
    pattern = find if regex else re.escape(find)
    if whole:
        pattern = rf"(?<!\w)(?:{pattern})(?!\w)"
    return re.compile(pattern, 0 if case else re.IGNORECASE)


def find_in_entries(entries: Iterable[TranslationEntry], rx: "re.Pattern[str]",
                    in_source: bool = False) -> List[TranslationEntry]:
    out = []
    for e in entries:
        text = e.source_text if in_source else e.target_text
        if text and rx.search(text):
            out.append(e)
    return out


def replace_in_entries(entries: Iterable[TranslationEntry], rx: "re.Pattern[str]", repl: str,
                       *, regex: bool = False, target_lang: Optional[str] = None
                       ) -> List[Tuple[str, str, TranslationStatus]]:
    """Заменяет в переводах. Возвращает историю [(handle, прежний_текст, прежний_статус)]."""
    history: List[Tuple[str, str, TranslationStatus]] = []
    template: Callable = (lambda m: m.expand(repl)) if regex else (lambda m: repl)
    for e in entries:
        if not e.target_text:
            continue
        new = rx.sub(template, e.target_text)
        if new != e.target_text:
            history.append((e.handle, e.target_text, e.status))
            keep = e.status if e.status in (TranslationStatus.APPROVED, TranslationStatus.LOCKED) \
                else TranslationStatus.TRANSLATED
            set_target(e, new, keep, target_lang=target_lang)
    return history


def undo_history(project: TranslationProject, history: List[Tuple[str, str, TranslationStatus]]) -> int:
    by = {e.handle: e for e in project.entries}
    n = 0
    for handle, old_text, old_status in reversed(history):
        e = by.get(handle)
        if e is None:
            continue
        e.target_text = old_text
        e.status = old_status
        revalidate(e)
        e.update_timestamps()
        n += 1
    return n


# ---------------------------------------------------------------------------
# Отчёт перед экспортом
# ---------------------------------------------------------------------------
def export_summary(project: TranslationProject) -> Dict[str, int]:
    es = project.entries
    translated = sum(1 for e in es if e.is_translated())
    return {
        "total": len(es), "translated": translated, "untranslated": len(es) - translated,
        "errors": sum(1 for e in es if e.validation_errors),
        "review": sum(1 for e in es if e.status == TranslationStatus.NEEDS_REVIEW),
        "warnings": sum(1 for e in es if e.validation_warnings and not e.validation_errors),
    }
