"""
Application configuration and constants.
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import json


@dataclass
class AppPaths:
    """Application paths."""
    base_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent.parent)
    data_dir: Path = field(default_factory=lambda: Path.home() / "AppData" / "Local" / "BG3ModTranslator")
    cache_dir: Path = field(default_factory=lambda: Path.home() / "AppData" / "Local" / "BG3ModTranslator" / "cache")
    logs_dir: Path = field(default_factory=lambda: Path.home() / "AppData" / "Local" / "BG3ModTranslator" / "logs")
    exports_dir: Path = field(default_factory=lambda: Path.home() / "Documents" / "BG3ModTranslator" / "exports")
    glossary_dir: Path = field(default_factory=lambda: Path.home() / "AppData" / "Local" / "BG3ModTranslator" / "glossary")

    def __post_init__(self):
        for path in [self.data_dir, self.cache_dir, self.logs_dir, self.exports_dir, self.glossary_dir]:
            path.mkdir(parents=True, exist_ok=True)


@dataclass
class TranslationProviderConfig:
    """Configuration for a translation provider."""
    name: str
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    enabled: bool = True
    priority: int = 0
    settings: Dict = field(default_factory=dict)


@dataclass
class Language:
    """Language definition."""
    code: str
    name: str
    native_name: str
    bg3_folder_name: str
    flag_emoji: str = ""


# Supported BG3 languages (matching Larian's folder names)
SUPPORTED_LANGUAGES: List[Language] = [
    Language("en", "English", "English", "English", "🇺🇸"),
    Language("zh", "Chinese (Simplified)", "简体中文", "Chinese", "🇨🇳"),
    Language("zh_tw", "Chinese (Traditional)", "繁體中文", "ChineseTraditional", "🇹🇼"),
    Language("ko", "Korean", "한국어", "Korean", "🇰🇷"),
    Language("ja", "Japanese", "日本語", "Japanese", "🇯🇵"),
    Language("ru", "Russian", "Русский", "Russian", "🇷🇺"),
    Language("pl", "Polish", "Polski", "Polish", "🇵🇱"),
    Language("de", "German", "Deutsch", "German", "🇩🇪"),
    Language("fr", "French", "Français", "French", "🇫🇷"),
    Language("es", "Spanish (Spain)", "Español (España)", "Spanish", "🇪🇸"),
    Language("es_mx", "Spanish (Latin America)", "Español (Latinoamérica)", "LatinSpanish", "🇲🇽"),
    Language("pt_br", "Portuguese (Brazil)", "Português (Brasil)", "BrazilianPortuguese", "🇧🇷"),
    Language("it", "Italian", "Italiano", "Italian", "🇮🇹"),
    Language("tr", "Turkish", "Türkçe", "Turkish", "🇹🇷"),
]

# Official BG3 languages (marked for priority sorting)
OFFICIAL_BG3_LANGUAGES = {"en", "zh", "ko", "ja", "ru", "pl", "de", "fr", "es", "es_mx", "pt_br", "it", "tr", "zh_tw"}


@dataclass
class AppSettings:
    """Application settings."""
    # General
    language: str = "en"
    theme: str = "system"  # light, dark, system
    auto_save: bool = True
    auto_save_interval: int = 30  # seconds

    # Translation
    default_provider: str = "gemini"
    providers: Dict[str, TranslationProviderConfig] = field(default_factory=dict)
    batch_size: int = 50
    max_concurrent_requests: int = 3
    retry_attempts: int = 3
    timeout: int = 60

    # Dictionary/Cache
    use_dictionary: bool = True
    dictionary_match_threshold: float = 0.85
    cache_translations: bool = True

    # Validation
    validate_placeholders: bool = True
    validate_terminology: bool = True
    strict_mode: bool = False

    # Export
    export_format: str = "pak"  # pak, xml, zip
    include_original: bool = False
    create_backup: bool = True

    # Advanced
    log_level: str = "INFO"
    debug_mode: bool = False

    @classmethod
    def load(cls, path: Path) -> "AppSettings":
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                settings = cls()
                for key, value in data.items():
                    if hasattr(settings, key):
                        if key == "providers":
                            settings.providers = {
                                k: TranslationProviderConfig(**v) for k, v in value.items()
                            }
                        else:
                            setattr(settings, key, value)
                return settings
            except Exception:
                pass
        return cls()

    def save(self, path: Path):
        data = {}
        for key in self.__dataclass_fields__:
            value = getattr(self, key)
            if key == "providers":
                data[key] = {k: v.__dict__ for k, v in value.items()}
            else:
                data[key] = value
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


# Global instances
PATHS = AppPaths()
SETTINGS_FILE = PATHS.data_dir / "settings.json"


def get_settings() -> AppSettings:
    """Get application settings singleton."""
    return AppSettings.load(SETTINGS_FILE)


def save_settings(settings: AppSettings):
    """Save application settings."""
    settings.save(SETTINGS_FILE)