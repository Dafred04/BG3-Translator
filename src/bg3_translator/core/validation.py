"""Placeholder extraction and validation for BG3 localization text."""

import re
from typing import List, Tuple
from ..models.translation import Placeholder

# BG3 LSTag: <LSTag ...>...</LSTag> or <LSTag ... />
LSTAG_RE = re.compile(r"<LSTag\b[^>]*/>|<LSTag\b[^>]*>.*?</LSTag>", re.DOTALL)
# Entity: &name; (e.g. &amp; &lt; &#8217;)
ENTITY_RE = re.compile(r"&(?:[a-zA-Z][a-zA-Z0-9]{1,31}|#\d{1,7}|#[xX][0-9a-fA-F]{1,6});")
# Format placeholder: {0}, {1}, ... {N}
FMT_RE = re.compile(r"\{\d+\}")
# Legacy numeric: [1], [2], ...
NUM_RE = re.compile(r"\[\d+\]")


def extract_placeholders(text: str) -> List[Placeholder]:
    """Extract all recognized placeholders from text, preserving order."""
    found: List[Placeholder] = []
    patterns = [
        (LSTAG_RE, "lstag"),
        (ENTITY_RE, "entity"),
        (FMT_RE, "format"),
        (NUM_RE, "numeric"),
    ]
    for regex, ptype in patterns:
        for m in regex.finditer(text):
            found.append(Placeholder(original=m.group(0), type=ptype, position=m.start()))
    found.sort(key=lambda p: p.position)
    return found


def normalize_for_compare(text: str) -> str:
    """Normalize text for placeholder-count comparison (order-independent)."""
    return text


def compare_placeholders(source: str, target: str) -> Tuple[List[str], List[str]]:
    """Compare placeholders between source and target.

    Returns (errors, warnings):
      errors   - missing/malformed placeholders in target
      warnings - placeholder count mismatches (non-strict)
    """
    errors: List[str] = []
    warnings: List[str] = []

    src_ph = extract_placeholders(source)
    tgt_ph = extract_placeholders(target)

    # Group counts by (type, original) — order-independent, count-based
    from collections import Counter
    src_counts = Counter((p.type, p.original) for p in src_ph)
    tgt_counts = Counter((p.type, p.original) for p in tgt_ph)

    for (ptype, orig), count in src_counts.items():
        tgt_count = tgt_counts.get((ptype, orig), 0)
        if tgt_count == 0:
            errors.append(f"Missing placeholder in target: {orig}")
        elif tgt_count != count:
            warnings.append(
                f"Placeholder count mismatch for {orig}: source has {count}, target has {tgt_count}"
            )

    for (ptype, orig), count in tgt_counts.items():
        if (ptype, orig) not in src_counts:
            errors.append(f"Unexpected placeholder in target: {orig}")

    return errors, warnings


def has_unclosed_tag(text: str) -> bool:
    """Check for obviously broken LSTag markup (open tag without close)."""
    opens = len(re.findall(r"<LSTag\b[^>]*>", text))
    closes = text.count("</LSTag>")
    self_closing = len(re.findall(r"<LSTag\b[^>]*/>", text))
    return opens - self_closing > closes


def strip_placeholders(text: str) -> str:
    """Return text with placeholders removed (for plain-text operations)."""
    result = text
    for regex, _ in [(LSTAG_RE, "lstag"), (ENTITY_RE, "entity")]:
        result = regex.sub("", result)
    return result