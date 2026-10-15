"""Язык-коды приложения <-> имена папок Localization/ в BG3."""

from __future__ import annotations

from typing import Optional

# Имена папок, которые BG3 использует в Localization/<Язык>/ (проверьте по вашей версии игры).
LANG_FOLDERS = {
    "en": "English", "ru": "Russian", "uk": "Ukrainian", "pl": "Polish",
    "de": "German", "fr": "French", "es": "Spanish", "es_mx": "LatinSpanish",
    "pt_br": "BrazilianPortuguese", "it": "Italian", "tr": "Turkish",
    "zh": "Chinese", "zh_tw": "ChineseTraditional", "ko": "Korean", "ja": "Japanese",
}

LANG_NAMES = {
    "en": "English", "ru": "Russian", "uk": "Ukrainian", "pl": "Polish",
    "de": "German", "fr": "French", "es": "Spanish", "es_mx": "Latin American Spanish",
    "pt_br": "Brazilian Portuguese", "it": "Italian", "tr": "Turkish",
    "zh": "Simplified Chinese", "zh_tw": "Traditional Chinese", "ko": "Korean", "ja": "Japanese",
}

_FOLDER_TO_CODE = {v.lower(): k for k, v in LANG_FOLDERS.items()}


def folder_for(code: str) -> str:
    return LANG_FOLDERS.get(code, code.replace("_", " ").title().replace(" ", ""))


def name_for(code: str) -> str:
    return LANG_NAMES.get(code, code)


def code_for_folder(folder: str) -> Optional[str]:
    return _FOLDER_TO_CODE.get(folder.lower())


def uses_cyrillic(code: str) -> bool:
    return code in ("ru", "uk")
