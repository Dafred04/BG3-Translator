"""Плейсхолдеры, защита (shield/unshield) и проверки качества перевода BG3.

Главное отличие от прежней версии: <LSTag ...>текст</LSTag> теперь разбирается на
открывающий и закрывающий теги, а текст между ними переводится. Раньше весь тег
считался одним плейсхолдером, и корректный перевод помечался ошибочным.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Optional, Tuple

from ..models.translation import Placeholder
from .languages import uses_cyrillic

LSTAG_OPEN_RE = re.compile(r"<LSTag\b[^>]*>", re.IGNORECASE)          # включая <LSTag ... />
LSTAG_CLOSE_RE = re.compile(r"</LSTag\s*>", re.IGNORECASE)
BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
TAG_RE = re.compile(r"</?(?:i|b|u|em|strong|font|p|span|color)\b[^>]*>", re.IGNORECASE)
ENTITY_RE = re.compile(r"&(?:[a-zA-Z][a-zA-Z0-9]{1,31}|#\d{1,7}|#[xX][0-9a-fA-F]{1,6});")
FMT_RE = re.compile(r"\{\d+\}")
NUM_RE = re.compile(r"\[\d+\]")

# Порядок важен: при пересечении побеждает более ранний/длинный матч.
_PATTERNS = (
    (LSTAG_OPEN_RE, "lstag_open"),
    (LSTAG_CLOSE_RE, "lstag_close"),
    (BR_RE, "br"),
    (TAG_RE, "tag"),
    (ENTITY_RE, "entity"),
    (FMT_RE, "format"),
    (NUM_RE, "numeric"),
)

DEFAULT_TOKEN = "⟦{n}⟧"


def _scan(text: str) -> List[Tuple[int, int, str, str]]:
    hits = []
    for regex, ptype in _PATTERNS:
        for m in regex.finditer(text):
            hits.append((m.start(), m.end(), ptype, m.group(0)))
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    out, last_end = [], -1
    for h in hits:
        if h[0] >= last_end:
            out.append(h)
            last_end = h[1]
    return out


def extract_placeholders(text: str) -> List[Placeholder]:
    """Все распознанные плейсхолдеры в порядке появления."""
    return [Placeholder(original=o, type=t, position=s) for s, _e, t, o in _scan(text)]


def normalize_for_compare(text: str) -> str:
    return text


def lstag_balance(text: str) -> int:
    """>0 — есть незакрытые <LSTag>, <0 — лишние </LSTag>."""
    opens = [m for m in LSTAG_OPEN_RE.findall(text) if not m.rstrip().endswith("/>")]
    return len(opens) - len(LSTAG_CLOSE_RE.findall(text))


def has_unclosed_tag(text: str) -> bool:
    return lstag_balance(text) > 0


def compare_placeholders(source: str, target: str) -> Tuple[List[str], List[str]]:
    """(errors, warnings). Ошибка — плейсхолдер потерян/лишний/испорчен."""
    errors: List[str] = []
    warnings: List[str] = []
    src = Counter((p.type, p.original) for p in extract_placeholders(source))
    tgt = Counter((p.type, p.original) for p in extract_placeholders(target))

    for (ptype, orig), count in src.items():
        have = tgt.get((ptype, orig), 0)
        if have == 0:
            errors.append(f"Пропущен плейсхолдер: {orig}")
        elif have != count:
            warnings.append(f"Число вхождений {orig}: в оригинале {count}, в переводе {have}")
    for key in tgt:
        if key not in src:
            errors.append(f"Лишний плейсхолдер: {key[1]}")

    if lstag_balance(target) != 0 and lstag_balance(source) == 0:
        errors.append("Незакрытый или лишний тег LSTag")
    return errors, warnings


def find_spans(text: str):
    """[(start, end)] всех плейсхолдеров — для подсветки в редакторе."""
    return [(s, e) for s, e, _t, _o in _scan(text)]


def strip_placeholders(text: str) -> str:
    """Текст без плейсхолдеров (для оценки длины, языка и т.п.)."""
    out, pos = [], 0
    for s, e, _t, _o in _scan(text):
        out.append(text[pos:s])
        pos = e
    out.append(text[pos:])
    return "".join(out)


# ---------------------------------------------------------------------------
# Shield / unshield: плейсхолдеры -> токены перед отправкой ИИ
# ---------------------------------------------------------------------------
def _token_regex(fmt: str, n: Optional[int] = None) -> "re.Pattern[str]":
    prefix, suffix = fmt.split("{n}")
    num = str(n) if n is not None else r"\d+"
    return re.compile(re.escape(prefix) + r"\s*(" + num + r")\s*" + re.escape(suffix))


def shield(text: str, fmt: str = DEFAULT_TOKEN) -> Tuple[str, List[str]]:
    """Заменяет плейсхолдеры токенами. Возвращает (текст_с_токенами, оригиналы)."""
    hits = _scan(text)
    if not hits:
        return text, []
    originals: List[str] = []
    out, pos = [], 0
    for s, e, _t, o in hits:
        out.append(text[pos:s])
        originals.append(o)
        out.append(fmt.format(n=len(originals)))
        pos = e
    out.append(text[pos:])
    return "".join(out), originals


def unshield(text: str, originals: List[str], fmt: str = DEFAULT_TOKEN) -> Tuple[str, List[str]]:
    """Возвращает (текст, проблемы). Проблема = токен потерян или появился лишний."""
    problems: List[str] = []
    result = text
    for n, orig in enumerate(originals, 1):
        rx = _token_regex(fmt, n)
        if not rx.search(result):
            problems.append(f"Потерян плейсхолдер: {orig}")
            continue
        result = rx.sub(lambda _m, o=orig: o, result)
    stray = _token_regex(fmt).findall(result)
    if stray:
        problems.append("Лишние токены в ответе ИИ: " + ", ".join(stray))
    return result, problems


# ---------------------------------------------------------------------------
# QA
# ---------------------------------------------------------------------------
_LATIN_RE = re.compile(r"[A-Za-z]")
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)


def qa_check(source: str, target: str, target_lang: str = "ru",
             glossary: Optional[Dict[str, str]] = None) -> List[str]:
    """Предупреждения о качестве (не блокируют перевод)."""
    warns: List[str] = []
    if not source.strip():
        return warns
    if not target.strip():
        return ["Пустой перевод"]

    plain_src, plain_tgt = strip_placeholders(source), strip_placeholders(target)
    if source.strip() == target.strip() and len(_LETTER_RE.findall(plain_src)) > 3:
        warns.append("Перевод совпадает с оригиналом")

    if len(plain_src) >= 12:
        ratio = len(plain_tgt) / max(len(plain_src), 1)
        if ratio > 2.5:
            warns.append(f"Перевод намного длиннее оригинала (×{ratio:.1f})")
        elif ratio < 0.3:
            warns.append(f"Перевод намного короче оригинала (×{ratio:.1f})")

    if uses_cyrillic(target_lang) and len(plain_tgt) >= 10:
        letters = _LETTER_RE.findall(plain_tgt)
        latin = _LATIN_RE.findall(plain_tgt)
        if letters and len(latin) / len(letters) > 0.5:
            warns.append("В переводе остался английский текст")

    if "  " in target and "  " not in source:
        warns.append("Двойные пробелы")
    if source[:1].isspace() != target[:1].isspace() or source[-1:].isspace() != target[-1:].isspace():
        warns.append("Пробелы по краям отличаются от оригинала")
    if source.count("\n") != target.count("\n"):
        warns.append("Число переводов строки отличается от оригинала")

    if glossary:
        low = target.lower()
        for term, tr in glossary.items():
            stem = tr.lower()[: max(4, len(tr) - 2)]
            if stem and stem not in low:
                warns.append(f"Термин «{term}» должен переводиться как «{tr}»")
    return warns
