"""Хмарні агенти: пресети провайдерів, параметри API і запуск.

DeepSeek, OpenAI, Anthropic (через сумісний шлюз), Gemini, Mistral, Groq,
OpenRouter — усі як OpenAI-сумісні endpoint'и. Один шар, який знає:

* базову адресу й де взяти ключ;
* типові моделі й ліміт контексту;
* чи модель «думаюча» (reasoning) — тоді в запит додаються її параметри;
* як перевірити ключ і чи є в моделі tool calling.

Модуль не тягне tkinter і не робить мережевих запитів під час імпорту.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional


@dataclass(frozen=True)
class CloudProvider:
    """Один хмарний провайдер."""

    key: str                       # deepseek, openai, ...
    label: str
    base_url: str
    key_url: str                   # де взяти API-ключ
    docs_url: str = ""
    models: tuple[str, ...] = ()
    context: int = 0               # типове вікно контексту
    supports_tools: bool = True
    reasoning: bool = False        # «думаюча» модель
    note: str = ""

    @property
    def is_local(self) -> bool:
        return False


#: Пресети. Порядок — як показуємо в налаштуваннях.
PROVIDERS: tuple[CloudProvider, ...] = (
    CloudProvider(
        key="deepseek",
        label="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        key_url="https://platform.deepseek.com/api_keys",
        docs_url="https://api-docs.deepseek.com",
        models=("deepseek-chat", "deepseek-reasoner"),
        context=64_000,
        reasoning=True,
        note="deepseek-reasoner — «думаюча» модель: довгі відповіді, "
             "гаряче рекомендується для складних задач.",
    ),
    CloudProvider(
        key="openai",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        key_url="https://platform.openai.com/api-keys",
        docs_url="https://platform.openai.com/docs",
        models=("gpt-4o", "gpt-4o-mini", "gpt-4.1", "o3-mini"),
        context=128_000,
        reasoning=True,
        note="o3-mini та gpt-4o підтримують інструменти.",
    ),
    CloudProvider(
        key="anthropic",
        label="Anthropic (Claude)",
        base_url="https://api.anthropic.com/v1",
        key_url="https://console.anthropic.com/settings/keys",
        docs_url="https://docs.anthropic.com",
        models=("claude-sonnet-4-20250514", "claude-3-5-haiku-20241022",
                "claude-3-5-sonnet-20241022"),
        context=200_000,
        note="Реалізовано справжній протокол /v1/messages: x-api-key, "
             "блоки tool_use/tool_result і власний SSE-стрімінг.",
    ),
    CloudProvider(
        key="gemini",
        label="Google Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        key_url="https://aistudio.google.com/app/apikey",
        docs_url="https://ai.google.dev/gemini-api/docs",
        models=("gemini-2.0-flash", "gemini-2.5-pro", "gemini-1.5-pro"),
        context=1_000_000,
        note="Типово — OpenAI-сумісний шлях /openai. Якщо вказати адресу "
             "без /openai, IDE сама перейде на нативний :generateContent.",
    ),
    CloudProvider(
        key="mistral",
        label="Mistral",
        base_url="https://api.mistral.ai/v1",
        key_url="https://console.mistral.ai/api-keys",
        docs_url="https://docs.mistral.ai",
        models=("mistral-large-latest", "mistral-small-latest", "codestral-latest"),
        context=128_000,
    ),
    CloudProvider(
        key="groq",
        label="Groq",
        base_url="https://api.groq.com/openai/v1",
        key_url="https://console.groq.com/keys",
        docs_url="https://console.groq.com/docs",
        models=("llama-3.3-70b-versatile", "qwen-2.5-coder-32b"),
        context=128_000,
        note="Дуже швидкий інференс.",
    ),
    CloudProvider(
        key="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        key_url="https://openrouter.ai/keys",
        docs_url="https://openrouter.ai/docs",
        models=("deepseek/deepseek-chat", "anthropic/claude-sonnet-4",
                "qwen/qwen-2.5-coder-32b-instruct"),
        context=128_000,
        note="Один ключ — багато моделей різних виробників.",
    ),
    CloudProvider(
        key="deploy",
        label="Deploy (deploy.com)",
        base_url="https://api.deploy.com/api/v1",
        key_url="https://portal.deploy.com/?api_keys=1",
        docs_url="https://docs.deploy.com/quickstart",
        models=("deepseek-ai/deepseek-v4.1-flash-1017", "zai-org/glm-5.3-flash"),
        context=1_000_000,
        reasoning=True,
        note="OpenAI-сумісний API, вікно 1 млн токенів, є reasoning "
             "і tool calling. Ключ — у portal.deploy.com → Service API Keys.",
    ),
    CloudProvider(
        key="custom",
        label="Інший (свій URL)",
        base_url="",
        key_url="",
        models=(),
        context=32_000,
        note="Будь-який OpenAI-сумісний endpoint.",
    ),
)

_BY_KEY: dict[str, CloudProvider] = {provider.key: provider for provider in PROVIDERS}

#: Додаткові регіональні адреси Deploy (з документації).
#: Користувач обирає найближчу — це зменшує затримку.
DEPLOY_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("Найближчий", "https://api.deploy.com/api/v1"),
    ("CDN (з-за меж США)", "https://api-cdn.deploy.com/api/v1"),
    ("SF", "https://api-sf1.deploy.com/api/v1"),
    ("SF через CDN", "https://api-sf1-cdn.deploy.com/api/v1"),
    ("VA", "https://api-va1.deploy.com/api/v1"),
    ("VA через CDN", "https://api-va1-cdn.deploy.com/api/v1"),
)

#: Рівні reasoning_effort, які приймає Deploy (з документації).
DEPLOY_EFFORTS: tuple[str, ...] = ("none", "low", "high", "max")


def deploy_endpoints() -> list[tuple[str, str]]:
    """Регіональні адреси Deploy: [(підпис, url)]."""
    return list(DEPLOY_ENDPOINTS)


def deploy_efforts() -> list[str]:
    """Дозволені значення reasoning_effort для Deploy."""
    return list(DEPLOY_EFFORTS)


def is_deploy(base_url: str) -> bool:
    """Чи адреса належить Deploy."""
    return "deploy.com" in (base_url or "").lower()


def normalise_deploy_url(raw: str) -> str:
    """Привести адресу Deploy до вигляду …/api/v1.

    Deploy використовує шлях ``/api/v1``, а не ``/v1`` — тому звичайна
    нормалізація тут не годиться.
    """
    url = (raw or "").strip().rstrip("/")
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if "/api/v1" in url:
        return url
    # Відрізаємо зайвий /v1, якщо користувач його дописав.
    if url.endswith("/v1"):
        url = url[:-3]
    return url.rstrip("/") + "/api/v1"


def get(key: str) -> Optional[CloudProvider]:
    """Пресет за ключем (або None)."""
    return _BY_KEY.get((key or "").strip().lower())


def detect(base_url: str) -> Optional[CloudProvider]:
    """Визначити провайдера за адресою."""
    url = (base_url or "").strip().lower()
    if not url:
        return None
    # Deploy має багато регіональних адрес — усі вони містять deploy.com.
    if "deploy.com" in url:
        return get("deploy")
    for provider in PROVIDERS:
        base = provider.base_url.lower()
        if base and (url.startswith(base) or base.split("//")[-1].split("/")[0] in url):
            return provider
    return None


def provider_labels() -> list[tuple[str, str]]:
    """(ключ, підпис) для випадаючого списку."""
    return [(provider.key, provider.label) for provider in PROVIDERS]


def label_for(key: str) -> str:
    provider = get(key)
    return provider.label if provider else (key or "—")


def models_for(key: str) -> list[str]:
    provider = get(key)
    return list(provider.models) if provider else []


def reasoning_models() -> set[str]:
    """Моделі, які «думають» і повертають reasoning_content."""
    names: set[str] = set()
    for provider in PROVIDERS:
        if provider.reasoning:
            names.update(name for name in provider.models
                         if "reason" in name or name.startswith("o"))
    return names


def is_reasoning_model(model: str) -> bool:
    """Чи це reasoning-модель (за назвою)."""
    low = (model or "").lower()
    if not low:
        return False
    markers = ("reasoner", "reasoning", "-r1", "o1-", "o3-", "o4-", "thinking",
               "deepseek-v4", "glm-5", "flash-1017", "magistral")
    return any(marker in low for marker in markers)


def normalise_base_url(raw: str) -> str:
    """Привести адресу до вигляду …/v1 (Deploy має свій шлях ``/api/v1``)."""
    if is_deploy(raw):
        return normalise_deploy_url(raw)
    url = (raw or "").strip().rstrip("/")
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if "/v1" not in url and not url.endswith("/openai") and "/api/v1" not in url:
        url += "/v1"
    return url


def extra_payload(model: str, *, provider_key: str = "") -> dict[str, Any]:
    """Додаткові поля запиту для конкретної моделі.

    DeepSeek reasoner не приймає temperature — його треба прибрати, інакше
    сервер відповідає помилкою 400.
    """
    payload: dict[str, Any] = {}
    if is_reasoning_model(model) or provider_key == "deepseek" and "reasoner" in model:
        payload["_drop_temperature"] = True
    if (provider_key == "deepseek" and "reasoner" in (model or "").lower()):
        payload["_drop_temperature"] = True
    return payload


@dataclass
class ProbeResult:
    """Результат перевірки ключа й моделей."""

    ok: bool
    detail: str = ""
    models: list[str] = field(default_factory=list)
    latency: float = 0.0
    provider: str = ""


def probe(api_key: str, base_url: str, *, timeout: float = 15.0) -> ProbeResult:
    """Перевірити, що ключ живий і сервер віддає моделі.

    Робить справжній запит ``GET /models`` — саме так перевіряють ключ усі
    OpenAI-сумісні сервіси.
    """
    import time

    url = normalise_base_url(base_url)
    if not url:
        return ProbeResult(False, "Не вказано адресу API.")
    if not (api_key or "").strip():
        return ProbeResult(False, "Не вказано API-ключ.")
    request = urllib.request.Request(f"{url}/models", method="GET")
    request.add_header("Authorization", f"Bearer {api_key.strip()}")
    request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent", "BlackChpokIDE/1.2")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(400_000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read(600).decode("utf-8", errors="replace")
        hint = {
            401: "Ключ не прийнято (401). Перевір, чи скопійований повністю.",
            403: "Доступ заборонено (403). Можливо, ключ без прав або регіон заблоковано.",
            404: "Адресу не знайдено (404). Перевір базовий URL.",
            429: "Перевищено ліміт запитів (429). Спробуй пізніше.",
        }.get(exc.code, f"HTTP {exc.code}")
        return ProbeResult(False, f"{hint} {detail[:180]}".strip())
    except urllib.error.URLError as exc:
        return ProbeResult(False, f"Немає з'єднання: {exc.reason}")
    except (TimeoutError, OSError) as exc:
        return ProbeResult(False, f"Помилка мережі: {exc}")

    elapsed = time.perf_counter() - started
    try:
        data: Any = json.loads(body)
    except json.JSONDecodeError:
        return ProbeResult(False, f"Відповідь не JSON: {body[:120]}")

    items = data.get("data") if isinstance(data, dict) else data
    models: list[str] = []
    for item in items or []:
        if isinstance(item, dict):
            name = item.get("id") or item.get("name") or ""
        else:
            name = str(item)
        if name:
            models.append(str(name))
    if not models:
        return ProbeResult(False, "Сервер відповів, але не показав жодної моделі.",
                           models=[], latency=elapsed)
    detected = detect(url)
    return ProbeResult(
        True,
        f"Ключ працює · моделей: {len(models)} · {elapsed * 1000:.0f} мс",
        models=models,
        latency=elapsed,
        provider=detected.key if detected else "",
    )


def apply_endpoint(settings, provider_key: str) -> bool:
    """Підставити адресу й модель пресета в налаштування (без ключа)."""
    provider = get(provider_key)
    if provider is None or not provider.base_url:
        return False
    settings.llm.base_url = provider.base_url
    if provider.models and settings.llm.model not in provider.models:
        settings.llm.model = provider.models[0]
    return True


def describe(key: str) -> str:
    """Короткий опис провайдера для підказки в налаштуваннях."""
    provider = get(key)
    if provider is None:
        return ""
    parts = [provider.label]
    if provider.context:
        parts.append(f"контекст ~{provider.context // 1000}K")
    if provider.reasoning:
        parts.append("є reasoning-моделі")
    if not provider.supports_tools:
        parts.append("без tool calling")
    if provider.note:
        parts.append(provider.note)
    return " · ".join(parts)


def mask_key(key: str) -> str:
    """Показати ключ безпечно: перші 4 і останні 4 символи."""
    text = (key or "").strip()
    if len(text) <= 10:
        return "•" * len(text) if text else ""
    return f"{text[:4]}…{text[-4:]}"


__all__ = [
    "PROVIDERS",
    "CloudProvider",
    "ProbeResult",
    "apply_endpoint",
    "describe",
    "DEPLOY_EFFORTS",
    "DEPLOY_ENDPOINTS",
    "deploy_efforts",
    "deploy_endpoints",
    "detect",
    "is_deploy",
    "normalise_deploy_url",
    "extra_payload",
    "get",
    "is_reasoning_model",
    "label_for",
    "mask_key",
    "models_for",
    "normalise_base_url",
    "probe",
    "provider_labels",
    "reasoning_models",
]
