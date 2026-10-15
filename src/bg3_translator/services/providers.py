"""Провайдеры перевода: Gemini, OpenAI-совместимые (в т.ч. Ollama/LM Studio), Google Free.

Особенности этой версии:
  * ключ Gemini передаётся заголовком, а не в URL, и вычищается из текстов ошибок;
  * пачки строк идут как JSON-массив -> JSON-массив (многострочные тексты не ломают разбор);
  * повторы с нарастающей паузой на 429/5xx/таймауты;
  * в промпт попадают контекст, глоссарий и пожелания по стилю.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import requests

from ..core.languages import name_for

log = logging.getLogger(__name__)


class TranslationError(Exception):
    """Ошибка провайдера."""


class FatalTranslationError(TranslationError):
    """Бессмысленно повторять: неверный ключ, нет модели и т.п. Прогон нужно остановить."""


class BatchMismatchError(TranslationError):
    """Провайдер вернул не столько строк, сколько отправили — пачку нужно поделить."""


@dataclass
class TranslateRequest:
    texts: List[str]
    source_lang: str
    target_lang: str
    context: str = ""
    glossary: Dict[str, str] = field(default_factory=dict)
    style: str = ""
    custom_prompt: str = ""
    token_example: str = ""         # напр. "⟦1⟧" — если задан, в тексте есть защитные токены


@dataclass
class TranslateResult:
    texts: List[str]
    provider: str
    characters: int = 0


GOOGLE_LANG = {
    "en": "en", "zh": "zh-CN", "zh_tw": "zh-TW", "ko": "ko", "ja": "ja",
    "ru": "ru", "uk": "uk", "pl": "pl", "de": "de", "fr": "fr", "es": "es",
    "es_mx": "es", "pt_br": "pt", "it": "it", "tr": "tr",
}

_KEY_IN_URL = re.compile(r"([?&](?:key|api_key|apikey)=)[^&\s'\"]+", re.IGNORECASE)


def scrub(text: str, *secrets: str) -> str:
    """Убирает ключи из текста ошибки (URL ?key=..., Bearer, сам ключ)."""
    out = _KEY_IN_URL.sub(r"\1***", str(text))
    out = re.sub(r"(Bearer\s+)\S+", r"\1***", out)
    for s in secrets:
        if s and len(s) >= 6:
            out = out.replace(s, "***")
    return out


def build_system_prompt(req: TranslateRequest) -> str:
    src, tgt = name_for(req.source_lang), name_for(req.target_lang)
    parts = [
        f"You are a professional game localizer for Baldur's Gate 3. Translate from {src} to {tgt}.",
        "Keep Dungeons & Dragons / BG3 terminology consistent and natural for players.",
        "Preserve HTML-like markup, {0}-style and [1]-style placeholders and &entities; exactly as they are.",
    ]
    if req.token_example:
        parts.append(f"Tokens such as {req.token_example} stand for markup: copy every token unchanged, "
                     "keep it in the sentence where it logically belongs, never translate or drop it.")
    parts.append("You receive a JSON array of strings and must return a JSON array of the same length "
                 "with the translations in the same order. Return ONLY the JSON array.")
    if req.context:
        parts.append(f"Context: {req.context}")
    if req.glossary:
        lines = "\n".join(f"- {k} => {v}" for k, v in list(req.glossary.items())[:40])
        parts.append("Mandatory glossary (use exactly these translations, adapting grammar as needed):\n" + lines)
    if req.style:
        parts.append(f"Style notes: {req.style}")
    if req.custom_prompt:
        parts.append(req.custom_prompt)
    return "\n".join(parts)


def parse_json_array(content: str, expected: int) -> List[str]:
    """Достаёт массив строк из ответа модели (терпит ```json-ограждения и обёртки-объекты)."""
    s = content.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.IGNORECASE)
    data = None
    try:
        data = json.loads(s)
    except ValueError:
        a, b = s.find("["), s.rfind("]")
        if a != -1 and b > a:
            try:
                data = json.loads(s[a:b + 1])
            except ValueError:
                data = None
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), None)
    if not isinstance(data, list):
        raise BatchMismatchError("Ответ модели не является JSON-массивом")
    items = [x if isinstance(x, str) else str(x) for x in data]
    if len(items) != expected:
        raise BatchMismatchError(f"Вернулось {len(items)} строк вместо {expected}")
    return items


class BaseProvider(ABC):
    name: str = "base"
    display_name: str = "Base"
    requires_key: bool = True
    token_fmt: str = "⟦{n}⟧"
    max_retries: int = 3

    def __init__(self, api_key: str = "", model: str = "", base_url: str = "", timeout: int = 60):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout = timeout
        self.characters_used: int = 0
        self._session = requests.Session()
        self._sleep = time.sleep          # подменяется в тестах

    @abstractmethod
    def translate(self, request: TranslateRequest) -> TranslateResult: ...

    def is_configured(self) -> bool:
        return bool(self.api_key) or not self.requires_key

    def list_models(self) -> List[str]:
        return []

    def test_connection(self) -> Tuple[float, str]:
        """Переводит «Hello» и возвращает (секунды, ответ). Бросает TranslationError."""
        t0 = time.monotonic()
        res = self.translate(TranslateRequest(["Hello, adventurer!"], "en", "ru"))
        return time.monotonic() - t0, res.texts[0]

    # -- HTTP с повторами -------------------------------------------------
    def _request(self, method: str, url: str, **kw) -> requests.Response:
        last = "неизвестная ошибка"
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.request(method, url, timeout=self.timeout, **kw)
            except (requests.Timeout, requests.ConnectionError) as exc:
                last = f"сеть/таймаут: {scrub(exc, self.api_key)}"
            else:
                if resp.status_code in (401, 403):
                    raise FatalTranslationError(f"Неверный ключ API ({resp.status_code})")
                if resp.status_code == 404:
                    raise FatalTranslationError("Не найдено (404): проверьте модель и базовый URL")
                if resp.status_code == 429 or resp.status_code >= 500:
                    last = "лимит запросов (429)" if resp.status_code == 429 else f"ошибка сервера ({resp.status_code})"
                    ra = resp.headers.get("Retry-After", "")
                    if ra.isdigit() and attempt < self.max_retries:
                        self._sleep(min(int(ra), 60))
                        continue
                else:
                    if resp.status_code >= 400:
                        body = scrub(resp.text[:300], self.api_key)
                        raise TranslationError(f"HTTP {resp.status_code}: {body}")
                    return resp
            if attempt < self.max_retries:
                self._sleep(min(2 ** attempt + random.random(), 30))
        raise TranslationError(f"Запрос не удался после {self.max_retries + 1} попыток: {last}")


class GoogleFreeProvider(BaseProvider):
    """Google Translate (бесплатный неофициальный endpoint)."""

    name = "google_free"
    display_name = "Google Translate (free)"
    requires_key = False
    token_fmt = "QX{n}XQ"           # Google чаще всего не трогает буквенно-цифровые токены

    URL = "https://translate.googleapis.com/translate_a/single"

    def translate(self, request: TranslateRequest) -> TranslateResult:
        src = GOOGLE_LANG.get(request.source_lang, request.source_lang)
        tgt = GOOGLE_LANG.get(request.target_lang, request.target_lang)
        out: List[str] = []
        for text in request.texts:
            resp = self._request("GET", self.URL,
                                 params={"client": "gtx", "sl": src, "tl": tgt, "dt": "t", "q": text})
            try:
                data = resp.json()
                chunk = "".join(seg[0] for seg in data[0] if seg and seg[0])
            except Exception as exc:
                raise TranslationError(f"Google вернул неожиданный ответ: {exc}") from exc
            out.append(chunk or text)
            self.characters_used += len(text)
        return TranslateResult(texts=out, provider=self.name, characters=self.characters_used)


class OpenAICompatibleProvider(BaseProvider):
    """OpenAI / DeepSeek / OpenRouter / Ollama / LM Studio (для локальных ключ не нужен)."""

    name = "openai_compatible"
    display_name = "OpenAI-compatible"
    requires_key = True
    DEFAULT_BASE_URL = "https://api.openai.com/v1"

    def is_configured(self) -> bool:
        return bool(self.api_key) or bool(self.base_url)

    def _base(self) -> str:
        return (self.base_url or self.DEFAULT_BASE_URL).rstrip("/")

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def list_models(self) -> List[str]:
        resp = self._request("GET", f"{self._base()}/models", headers=self._headers())
        try:
            return sorted(m["id"] for m in resp.json().get("data", []))
        except Exception:
            return []

    def translate(self, request: TranslateRequest) -> TranslateResult:
        if not self.is_configured():
            raise FatalTranslationError("Не задан ключ API или базовый URL")
        payload = {
            "model": self.model or "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": build_system_prompt(request)},
                {"role": "user", "content": json.dumps(request.texts, ensure_ascii=False)},
            ],
            "temperature": 0.2,
        }
        url = f"{self._base()}/chat/completions"
        try:
            resp = self._request("POST", url, json=payload, headers=self._headers())
        except TranslationError as exc:
            if "temperature" in str(exc).lower():          # модели без настраиваемой температуры
                payload.pop("temperature", None)
                resp = self._request("POST", url, json=payload, headers=self._headers())
            else:
                raise
        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            raise TranslationError(f"Неожиданный ответ провайдера: {scrub(exc, self.api_key)}") from exc
        items = _parse_or_single(content, request.texts)
        self.characters_used += sum(len(t) for t in request.texts)
        return TranslateResult(texts=items, provider=self.name, characters=self.characters_used)


def _parse_or_single(content: str, texts: List[str]) -> List[str]:
    try:
        return parse_json_array(content, len(texts))
    except BatchMismatchError:
        if len(texts) == 1 and content.strip():
            return [content.strip().strip('"')]
        raise


class GeminiProvider(BaseProvider):
    """Google Gemini (Generative Language API)."""

    name = "gemini"
    display_name = "Google Gemini"
    requires_key = True
    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    DEFAULT_MODEL = "gemini-2.5-flash"

    _SAFETY = [{"category": c, "threshold": "BLOCK_NONE"} for c in (
        "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")]

    def _base(self) -> str:
        return (self.base_url or self.DEFAULT_BASE_URL).rstrip("/")

    def _headers(self) -> dict:
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

    def list_models(self) -> List[str]:
        try:
            resp = self._request("GET", f"{self._base()}/models", headers=self._headers())
            names = []
            for m in resp.json().get("models", []):
                nm = m.get("name", "")
                if "generateContent" not in (m.get("supportedGenerationMethods") or []):
                    continue
                nm = nm.removeprefix("models/")
                if "embedding" in nm or "aqa" in nm:
                    continue
                names.append(nm)
            return names or self.fallback_models()
        except FatalTranslationError:
            raise
        except Exception as exc:
            log.warning("list_models: %s", scrub(exc, self.api_key))
            return self.fallback_models()

    @staticmethod
    def fallback_models() -> List[str]:
        return ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash", "gemini-2.0-flash-lite",
                "gemini-1.5-flash", "gemini-1.5-pro"]

    def translate(self, request: TranslateRequest) -> TranslateResult:
        if not self.is_configured():
            raise FatalTranslationError("Ключ API Gemini не задан")
        model = self.model or self.DEFAULT_MODEL
        gen_cfg = {"temperature": 0.2, "responseMimeType": "application/json",
                   "responseSchema": {"type": "ARRAY", "items": {"type": "STRING"}}}
        if "2.5" in model and "pro" not in model:
            gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}       # быстрее и дешевле
        payload = {
            "systemInstruction": {"parts": [{"text": build_system_prompt(request)}]},
            "contents": [{"role": "user", "parts": [{"text": json.dumps(request.texts, ensure_ascii=False)}]}],
            "generationConfig": gen_cfg,
            "safetySettings": self._SAFETY,
        }
        resp = self._request("POST", f"{self._base()}/models/{model}:generateContent",
                             json=payload, headers=self._headers())
        try:
            data = resp.json()
        except ValueError as exc:
            raise TranslationError("Gemini вернула не JSON") from exc
        block = (data.get("promptFeedback") or {}).get("blockReason")
        if block:
            raise TranslationError(f"Gemini заблокировала запрос: {block}")
        cands = data.get("candidates") or []
        if not cands:
            raise TranslationError("Gemini не вернула ни одного варианта ответа")
        parts = (cands[0].get("content") or {}).get("parts") or []
        content = "".join(p.get("text", "") for p in parts)
        if not content.strip():
            raise TranslationError(f"Пустой ответ Gemini (finishReason={cands[0].get('finishReason')})")
        items = _parse_or_single(content, request.texts)
        self.characters_used += sum(len(t) for t in request.texts)
        return TranslateResult(texts=items, provider=self.name, characters=self.characters_used)


def get_provider(name: str, api_key: str = "", model: str = "", base_url: str = "",
                 timeout: int = 60) -> BaseProvider:
    providers = {"gemini": GeminiProvider, "google_free": GoogleFreeProvider,
                 "openai_compatible": OpenAICompatibleProvider}
    cls = providers.get(name)
    if cls is None:
        raise TranslationError(f"Неизвестный провайдер: {name}")
    return cls(api_key=api_key, model=model, base_url=base_url, timeout=timeout)
