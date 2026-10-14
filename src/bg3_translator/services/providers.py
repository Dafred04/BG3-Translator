"""Translation providers: Google Free + OpenAI-compatible (DeepSeek/OpenAI/etc.)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import requests


class TranslationError(Exception):
    """Raised when a translation provider fails."""


@dataclass
class TranslateRequest:
    texts: List[str]
    source_lang: str
    target_lang: str
    context: str = ""


@dataclass
class TranslateResult:
    texts: List[str]
    provider: str
    characters: int = 0


# ISO codes for Google Translate
GOOGLE_LANG = {
    "en": "en", "zh": "zh-CN", "zh_tw": "zh-TW", "ko": "ko", "ja": "ja",
    "ru": "ru", "pl": "pl", "de": "de", "fr": "fr", "es": "es",
    "es_mx": "es", "pt_br": "pt", "it": "it", "tr": "tr",
}


class BaseProvider(ABC):
    name: str = "base"
    display_name: str = "Base"
    requires_key: bool = True

    def __init__(self, api_key: str = "", model: str = "", base_url: str = "", timeout: int = 60):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout = timeout
        self.characters_used: int = 0

    @abstractmethod
    def translate(self, request: TranslateRequest) -> TranslateResult:
        ...

    def is_configured(self) -> bool:
        return bool(self.api_key) or not self.requires_key


class GoogleFreeProvider(BaseProvider):
    """Google Translate free endpoint (unofficial)."""

    name = "google_free"
    display_name = "Google Translate (free)"
    requires_key = False

    URL = "https://translate.googleapis.com/translate_a/single"

    def translate(self, request: TranslateRequest) -> TranslateResult:
        src = GOOGLE_LANG.get(request.source_lang, request.source_lang)
        tgt = GOOGLE_LANG.get(request.target_lang, request.target_lang)
        translated: List[str] = []
        for text in request.texts:
            try:
                resp = requests.get(
                    self.URL,
                    params={"client": "gtx", "sl": src, "tl": tgt, "dt": "t", "q": text},
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                chunk = "".join(seg[0] for seg in data[0] if seg and seg[0])
                translated.append(chunk or text)
                self.characters_used += len(text)
            except Exception as exc:
                raise TranslationError(f"Google translate failed: {exc}") from exc
        return TranslateResult(texts=translated, provider=self.name, characters=self.characters_used)


class OpenAICompatibleProvider(BaseProvider):
    """OpenAI-compatible chat completions (OpenAI, DeepSeek, OpenRouter, etc.)."""

    name = "openai_compatible"
    display_name = "OpenAI-compatible (DeepSeek / OpenAI / ...)"
    requires_key = True

    DEFAULT_BASE_URL = "https://api.openai.com/v1"

    SYSTEM_PROMPT = (
        "You are a professional game localizer for Baldur's Gate 3. "
        "Translate from {src} to {tgt}. "
        "Preserve ALL placeholders exactly: <LSTag>...</LSTag>, &entity;, {{0}}, [1], \\n. "
        "Keep D&D/BG3 terminology consistent. "
        "Return ONLY the translated text, one line per input line, no numbering."
    )

    def translate(self, request: TranslateRequest) -> TranslateResult:
        if not self.is_configured():
            raise TranslationError("API key is not configured for OpenAI-compatible provider")

        base = (self.base_url or self.DEFAULT_BASE_URL).rstrip("/")
        url = f"{base}/chat/completions"
        system = self.SYSTEM_PROMPT.format(src=request.source_lang, tgt=request.target_lang)
        user_content = "\n".join(request.texts)

        payload = {
            "model": self.model or "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
            if resp.status_code == 401:
                raise TranslationError("Invalid API key (401)")
            if resp.status_code == 429:
                raise TranslationError("Rate limit exceeded (429), try again later")
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except TranslationError:
            raise
        except Exception as exc:
            raise TranslationError(f"OpenAI-compatible request failed: {exc}") from exc

        lines = [line.strip() for line in content.split("\n")]
        # Fallback: if line count mismatch, return whole content per text heuristically
        if len(lines) != len(request.texts):
            if len(request.texts) == 1:
                lines = [content.strip()]
            else:
                raise TranslationError(
                    f"Provider returned {len(lines)} lines for {len(request.texts)} inputs"
                )
        self.characters_used += len(user_content)
        return TranslateResult(texts=lines, provider=self.name, characters=self.characters_used)


class GeminiProvider(BaseProvider):
    """Google Gemini via the official Generative Language API (generativelanguage).

    Uses an API key. Supports model selection and live model listing.
    """

    name = "gemini"
    display_name = "Google Gemini"
    requires_key = True

    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    DEFAULT_MODEL = "gemini-2.5-flash"

    SYSTEM_PROMPT = (
        "You are a professional game localizer for Baldur's Gate 3. "
        "Translate from {src} to {tgt}. "
        "Preserve ALL placeholders exactly: <LSTag>...</LSTag>, &entity;, {{0}}, [1], \\n. "
        "Keep D&D/BG3 terminology consistent and natural. "
        "Return ONLY the translated text, one line per input line, no numbering, no comments."
    )

    def _lang_name(self, code: str) -> str:
        return {
            "en": "English", "ru": "Russian", "zh": "Simplified Chinese",
            "zh_tw": "Traditional Chinese", "ko": "Korean", "ja": "Japanese",
            "pl": "Polish", "de": "German", "fr": "French", "es": "Spanish",
            "es_mx": "Latin American Spanish", "pt_br": "Brazilian Portuguese",
            "it": "Italian", "tr": "Turkish",
        }.get(code, code)

    def list_models(self) -> List[str]:
        """Fetch available model names from the Gemini API (falls back to a
        curated list on error)."""
        base = (self.base_url or self.DEFAULT_BASE_URL).rstrip("/")
        url = f"{base}/models"
        try:
            resp = requests.get(url, params={"key": self.api_key}, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            names = []
            for m in data.get("models", []):
                nm = m.get("name", "")
                if "generateContent" not in (m.get("supportedGenerationMethods") or []):
                    continue
                if nm.startswith("models/"):
                    nm = nm[len("models/"):]
                if "embedding" in nm or "aqa" in nm:
                    continue
                names.append(nm)
            return names or self.fallback_models()
        except Exception:
            return self.fallback_models()

    @staticmethod
    def fallback_models() -> List[str]:
        return [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
        ]

    def translate(self, request: TranslateRequest) -> TranslateResult:
        if not self.is_configured():
            raise TranslationError("Ключ API Gemini не задан")
        model = self.model or self.DEFAULT_MODEL
        base = (self.base_url or self.DEFAULT_BASE_URL).rstrip("/")
        url = f"{base}/models/{model}:generateContent"
        system = self.SYSTEM_PROMPT.format(
            src=self._lang_name(request.source_lang),
            tgt=self._lang_name(request.target_lang),
        )
        user_content = "\n".join(request.texts)
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": user_content}]}],
            "generationConfig": {"temperature": 0.2},
        }
        try:
            resp = requests.post(
                url, params={"key": self.api_key}, json=payload, timeout=self.timeout
            )
            if resp.status_code in (401, 403):
                raise TranslationError("Неверный ключ API Gemini (401/403)")
            if resp.status_code == 404:
                raise TranslationError(f"Модель Gemini не найдена: {model}")
            if resp.status_code == 429:
                raise TranslationError("Лимит запросов Gemini исчерпан (429)")
            resp.raise_for_status()
            data = resp.json()
            parts = data["candidates"][0]["content"]["parts"]
            content = "".join(p.get("text", "") for p in parts)
        except TranslationError:
            raise
        except Exception as exc:
            raise TranslationError(f"Запрос к Gemini не удался: {exc}") from exc

        lines = [line.strip() for line in content.split("\n") if line.strip()]
        if len(lines) != len(request.texts):
            if len(request.texts) == 1:
                lines = [content.strip()]
            else:
                raise TranslationError(
                    f"Gemini вернула {len(lines)} строк для {len(request.texts)} входов"
                )
        self.characters_used += len(user_content)
        return TranslateResult(texts=lines, provider=self.name, characters=self.characters_used)


def get_provider(name: str, api_key: str = "", model: str = "", base_url: str = "", timeout: int = 60) -> BaseProvider:
    """Factory for providers by name."""
    providers = {
        "gemini": GeminiProvider,
        "google_free": GoogleFreeProvider,
        "openai_compatible": OpenAICompatibleProvider,
    }
    cls = providers.get(name)
    if cls is None:
        raise TranslationError(f"Unknown provider: {name}")
    return cls(api_key=api_key, model=model, base_url=base_url, timeout=timeout)