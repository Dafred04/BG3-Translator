"""Хранение API-ключей в системном хранилище (Windows Credential Manager и т.п.).

Если пакет `keyring` не установлен или недоступен, всё работает по-старому:
ключ лежит в настройках приложения.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)
SERVICE = "BG3ModTranslator"

try:
    import keyring as _keyring
except Exception:  # pragma: no cover
    _keyring = None


def available() -> bool:
    return _keyring is not None


def get_api_key(provider: str, fallback: str = "") -> str:
    """Ключ из хранилища; если там пусто — значение из настроек (fallback)."""
    if _keyring is not None:
        try:
            val = _keyring.get_password(SERVICE, provider)
            if val:
                return val
        except Exception as exc:
            log.warning("keyring недоступен: %s", exc)
    return fallback


def set_api_key(provider: str, key: str) -> bool:
    """True, если ключ сохранён в хранилище (тогда в файл настроек писать не нужно)."""
    if _keyring is None:
        return False
    try:
        if key:
            _keyring.set_password(SERVICE, provider, key)
        else:
            try:
                _keyring.delete_password(SERVICE, provider)
            except Exception:
                pass
        return True
    except Exception as exc:
        log.warning("Не удалось записать ключ в keyring: %s", exc)
        return False
