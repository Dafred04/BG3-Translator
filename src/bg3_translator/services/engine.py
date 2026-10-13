"""Translation orchestration: dictionary -> provider -> validation."""

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from ..models.translation import TranslationEntry, TranslationStatus
from ..core.validation import compare_placeholders
from .dictionary import DictionaryStore
from .providers import BaseProvider, TranslateRequest, TranslationError


@dataclass
class TranslationProgress:
    done: int = 0
    total: int = 0
    current_text: str = ""
    errors: List[str] = field(default_factory=list)

    @property
    def percent(self) -> int:
        return int(self.done * 100 / self.total) if self.total else 0


class TranslationEngine:
    """Translates entries using dictionary first, then provider fallback."""

    def __init__(self, dictionary: DictionaryStore, provider: Optional[BaseProvider] = None):
        self.dictionary = dictionary
        self.provider = provider
        self.strict_placeholders = True

    def translate_entry(self, entry: TranslationEntry) -> bool:
        """Translate a single entry. Returns True if translated."""
        if not entry.source_text.strip():
            return False

        # 1) Dictionary lookup
        hit = self.dictionary.lookup(entry.source_text, entry.source_language, entry.target_language)
        if hit is not None:
            errors, _ = compare_placeholders(entry.source_text, hit.target_text)
            if not errors or not self.strict_placeholders:
                entry.target_text = hit.target_text
                entry.status = TranslationStatus.DICTIONARY_MATCH
                entry.translated_by = "dictionary"
                entry.update_timestamps()
                return True

        # 2) Provider fallback
        if self.provider is None or not self.provider.is_configured():
            return False
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
            return False

        candidate = result.texts[0]
        errors, warnings = compare_placeholders(entry.source_text, candidate)
        if errors and self.strict_placeholders:
            # placeholder mismatch -> keep source (never emit broken text)
            entry.validation_errors = errors
            return False

        entry.target_text = candidate
        entry.status = TranslationStatus.AUTO_TRANSLATED
        entry.translated_by = f"ai:{self.provider.name}"
        entry.validation_errors = errors
        entry.validation_warnings = warnings
        entry.update_timestamps()

        # 3) Save to dictionary for future reuse
        from ..models.translation import DictionaryEntry
        self.dictionary.add(
            DictionaryEntry(
                source_text=entry.source_text,
                source_language=entry.source_language,
                target_text=candidate,
                target_language=entry.target_language,
                handle=entry.handle,
                context=entry.context,
                source_mod="",
            )
        )
        return True

    def translate_batch(
        self,
        entries: List[TranslationEntry],
        on_progress: Optional[Callable[[TranslationProgress], None]] = None,
    ) -> TranslationProgress:
        """Translate many entries, reporting progress."""
        progress = TranslationProgress(total=len(entries))
        for entry in entries:
            progress.current_text = entry.source_text[:80]
            try:
                ok = self.translate_entry(entry)
                if not ok and self.provider is None:
                    progress.errors.append(f"No provider and no dictionary hit: {entry.handle}")
            except Exception as exc:
                progress.errors.append(f"{entry.handle}: {exc}")
            progress.done += 1
            if on_progress:
                on_progress(progress)
        return progress