"""
Data models for translation entries, dictionaries, and mod metadata.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Set
from pathlib import Path
import uuid


class TranslationStatus(Enum):
    """Status of a translation entry."""
    NEW = "new"
    TRANSLATED = "translated"
    DICTIONARY_MATCH = "dict_match"
    AUTO_TRANSLATED = "auto"
    NEEDS_REVIEW = "review"
    APPROVED = "approved"
    LOCKED = "locked"


class EntryType(Enum):
    """Type of localization entry."""
    TEXT = "text"
    DIALOGUE = "dialogue"
    ITEM = "item"
    SPELL = "spell"
    UI = "ui"
    OTHER = "other"


@dataclass
class Placeholder:
    """Represents a placeholder in translation text."""
    original: str
    type: str  # lstag, entity, format, newline, custom
    position: int
    validated: bool = True


@dataclass
class TranslationEntry:
    """A single translation entry (source -> target)."""
    # Identifiers
    handle: str
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Source text
    source_text: str = ""
    source_language: str = "en"

    # Target text
    target_text: str = ""
    target_language: str = "zh"

    # Metadata
    status: TranslationStatus = TranslationStatus.NEW
    entry_type: EntryType = EntryType.TEXT
    context: str = ""
    comment: str = ""
    version: int = 1            # версия строки в .loca (для режима обновления мода)

    # Placeholders
    source_placeholders: List[Placeholder] = field(default_factory=list)
    target_placeholders: List[Placeholder] = field(default_factory=list)

    # Validation
    validation_errors: List[str] = field(default_factory=list)
    validation_warnings: List[str] = field(default_factory=list)

    # History
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    translated_by: str = ""
    translation_confidence: float = 0.0

    # Alternative translations
    alternatives: List[str] = field(default_factory=list)

    def __post_init__(self):
        self.update_timestamps()

    def update_timestamps(self):
        self.updated_at = datetime.now()

    def is_translated(self) -> bool:
        return bool(self.target_text.strip()) and self.status != TranslationStatus.NEW

    def has_validation_errors(self) -> bool:
        return len(self.validation_errors) > 0

    def to_dict(self) -> dict:
        return {
            "handle": self.handle,
            "uuid": self.uuid,
            "source_text": self.source_text,
            "source_language": self.source_language,
            "target_text": self.target_text,
            "target_language": self.target_language,
            "status": self.status.value,
            "entry_type": self.entry_type.value,
            "context": self.context,
            "comment": self.comment,
            "version": self.version,
            "source_placeholders": [p.__dict__ for p in self.source_placeholders],
            "target_placeholders": [p.__dict__ for p in self.target_placeholders],
            "validation_errors": self.validation_errors,
            "validation_warnings": self.validation_warnings,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "translated_by": self.translated_by,
            "translation_confidence": self.translation_confidence,
            "alternatives": self.alternatives,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TranslationEntry":
        entry = cls(
            handle=data["handle"],
            uuid=data.get("uuid", str(uuid.uuid4())),
            source_text=data.get("source_text", ""),
            source_language=data.get("source_language", "en"),
            target_text=data.get("target_text", ""),
            target_language=data.get("target_language", "zh"),
            status=TranslationStatus(data.get("status", "new")),
            entry_type=EntryType(data.get("entry_type", "text")),
            context=data.get("context", ""),
            comment=data.get("comment", ""),
            version=int(data.get("version", 1)),
            validation_errors=data.get("validation_errors", []),
            validation_warnings=data.get("validation_warnings", []),
            translated_by=data.get("translated_by", ""),
            translation_confidence=data.get("translation_confidence", 0.0),
            alternatives=data.get("alternatives", []),
        )
        entry.created_at = datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now()
        entry.updated_at = datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.now()
        entry.source_placeholders = [Placeholder(**p) for p in data.get("source_placeholders", [])]
        entry.target_placeholders = [Placeholder(**p) for p in data.get("target_placeholders", [])]
        return entry



@dataclass
class DictionaryEntry:
    source_text: str
    source_language: str
    target_text: str
    target_language: str
    handle: str = ""
    context: str = ""
    usage_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    source_mod: str = ""
    verified: bool = False
    tags: Set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        return {
            "source_text": self.source_text,
            "source_language": self.source_language,
            "target_text": self.target_text,
            "target_language": self.target_language,
            "handle": self.handle,
            "context": self.context,
            "usage_count": self.usage_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "source_mod": self.source_mod,
            "verified": self.verified,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DictionaryEntry":
        return cls(
            source_text=data["source_text"],
            source_language=data["source_language"],
            target_text=data["target_text"],
            target_language=data["target_language"],
            handle=data.get("handle", ""),
            context=data.get("context", ""),
            usage_count=data.get("usage_count", 0),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.now(),
            source_mod=data.get("source_mod", ""),
            verified=data.get("verified", False),
            tags=set(data.get("tags", [])),
        )


@dataclass
class ModMetadata:
    name: str
    author: str = ""
    version: str = "1.0.0.0"
    description: str = ""
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))
    folder: str = ""
    supported_languages: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    source_path: Path = field(default_factory=Path)
    is_chinese_mod: bool = False
    original_mod_uuid: str = ""
    original_mod_folder: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "author": self.author,
            "version": self.version,
            "description": self.description,
            "uuid": self.uuid,
            "folder": self.folder,
            "supported_languages": self.supported_languages,
            "dependencies": self.dependencies,
            "source_path": str(self.source_path),
            "is_chinese_mod": self.is_chinese_mod,
            "original_mod_uuid": self.original_mod_uuid,
            "original_mod_folder": self.original_mod_folder,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ModMetadata":
        return cls(
            name=data["name"],
            author=data.get("author", ""),
            version=data.get("version", "1.0.0.0"),
            description=data.get("description", ""),
            uuid=data.get("uuid", str(uuid.uuid4())),
            folder=data.get("folder", ""),
            supported_languages=data.get("supported_languages", []),
            dependencies=data.get("dependencies", []),
            source_path=Path(data.get("source_path", "")),
            is_chinese_mod=data.get("is_chinese_mod", False),
            original_mod_uuid=data.get("original_mod_uuid", ""),
            original_mod_folder=data.get("original_mod_folder", ""),
        )


@dataclass
class TranslationProject:
    metadata: ModMetadata
    entries: List[TranslationEntry] = field(default_factory=list)
    source_language: str = "en"
    target_language: str = "zh"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    settings_snapshot: dict = field(default_factory=dict)
    total_entries: int = 0
    translated_entries: int = 0
    reviewed_entries: int = 0

    def __post_init__(self):
        self.update_stats()

    def update_stats(self):
        self.total_entries = len(self.entries)
        self.translated_entries = sum(1 for e in self.entries if e.is_translated())
        self.reviewed_entries = sum(
            1 for e in self.entries if e.status in (TranslationStatus.APPROVED, TranslationStatus.NEEDS_REVIEW)
        )
        self.updated_at = datetime.now()

    def get_progress(self) -> float:
        if self.total_entries == 0:
            return 0.0
        return self.translated_entries / self.total_entries

    def get_entries_by_status(self, status: TranslationStatus) -> List[TranslationEntry]:
        return [e for e in self.entries if e.status == status]

    def get_untranslated(self) -> List[TranslationEntry]:
        return [e for e in self.entries if not e.is_translated()]

    def to_dict(self) -> dict:
        return {
            "metadata": self.metadata.to_dict(),
            "entries": [e.to_dict() for e in self.entries],
            "source_language": self.source_language,
            "target_language": self.target_language,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "settings_snapshot": self.settings_snapshot,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TranslationProject":
        project = cls(
            metadata=ModMetadata.from_dict(data["metadata"]),
            entries=[TranslationEntry.from_dict(e) for e in data.get("entries", [])],
            source_language=data.get("source_language", "en"),
            target_language=data.get("target_language", "zh"),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.now(),
            settings_snapshot=data.get("settings_snapshot", {}),
        )
        project.update_stats()
        return project