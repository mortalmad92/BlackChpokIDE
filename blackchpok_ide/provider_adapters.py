"""Адаптери провайдерів: справжні HTTP-протоколи, а не «всі схожі на OpenAI».

Навіщо цей шар. Раніше програма надсилала ОДИН формат запиту (OpenAI
``/chat/completions`` з ``Authorization: Bearer``) до будь-якої адреси.
Для OpenAI, DeepSeek, OpenRouter, Groq, Mistral, Gemini-OpenAI і локальних
серверів це правильно. Але:

* **Anthropic** має ``POST /v1/messages``, заголовки ``x-api-key`` +
  ``anthropic-version``, ``system`` окремим полем і інший SSE
  (``content_block_delta`` / ``input_json_delta`` / ``tool_use``). Запит
  у форматі OpenAI отримував 404 — «підтримка» була фіктивною;
* **Gemini** (нативний API) має ``?key=`` і ``:generateContent``.

Тому кожен провайдер описується функцією, яка знає чотири речі: як
авторизуватись, на яку адресу йти, як перетворити наші повідомлення на
його формат і як прочитати його відповідь. Усе інше (мережа, стрімінг,
таймаути) лишається в :class:`llm_client.LLMClient`.

Модуль не тягне tkinter і не робить запитів під час імпорту.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

#: Ключ адаптера OpenAI-сумісного протоколу (більшість провайдерів).
OPENAI = "openai"
ANTHROPIC = "anthropic"
GEMINI = "gemini"
#: Вбудований рушій BLACKCHPOK: не HTTP, а виклик llama.dll у власному процесі.
#: Стиль існує, щоб решта коду не робила спроб мережевого запиту до
#: псевдо-адреси ``native://blackchpok`` і отримувала зрозумілу помилку.
EMBEDDED = "embedded"


def is_embedded(base_url: str) -> bool:
    """Чи адреса означає вбудований рушій (``native://``, ``inproc://``)."""
    low = (base_url or "").strip().lower()
    return low.startswith(("native://", "inproc://", "blackchpok://"))


#: Хости, що вказують на СВІЙ комп'ютер. Порядок не важливий — це набір.
#:
#: Одне місце на весь проєкт. Раніше «локальний чи хмарний» визначалось
#: **сімома** незалежними способами (``llm_client._is_local_url``,
#: ``auto_setup._is_local_url`` з власним списком із 7 хостів,
#: ``providers.LocalProvider.is_local``, ``providers.ModelEntry.is_local``,
#: ``main_window._model_summary`` з інлайн-списком, ``browser_panel.is_local_url``,
#: ``config.LLMSettings.normalise``). Через це та сама адреса в різних
#: місцях інтерфейсу вважалась локальною або хмарною по-різному.
LOCAL_HOSTS: frozenset[str] = frozenset({
    "127.0.0.1", "localhost", "0.0.0.0", "::1", "[::1]",
    "host.docker.internal",
})

#: Префікси приватних мереж: теж «свій» сервер, хоч і не loopback.
LOCAL_PREFIXES: tuple[str, ...] = ("192.168.", "10.", "172.16.", "172.17.",
                                   "172.18.", "172.19.", "172.2", "172.30.",
                                   "172.31.")


def is_local_url(base_url: str) -> bool:
    """Чи адреса веде на локальний (або приватний) сервер.

    ЄДИНА реалізація для всього проєкту. Враховує: ``native://`` (вбудований
    рушій — теж локальний), loopback, ``localhost``, ``::1`` і приватні
    діапазони. Свідомо НЕ робить DNS-резолву: адреса може бути недоступною,
    а питання тут — «куди ми йдемо», а не «чи відповідає воно».
    """
    text = (base_url or "").strip().lower()
    if not text:
        return False
    if is_embedded(text):
        return True
    host = text
    for prefix in ("http://", "https://", "ws://", "wss://", "file://"):
        if host.startswith(prefix):
            host = host[len(prefix):]
            break
    host = host.split("/")[0].split("?")[0].split("#")[0]
    if "@" in host:                      # user:pass@host
        host = host.rsplit("@", 1)[-1]
    if host.startswith("["):             # [::1]:8080
        host = host.split("]")[0] + "]"
    elif ":" in host:                    # 127.0.0.1:8080
        host = host.split(":")[0]
    if host in LOCAL_HOSTS:
        return True
    return any(host.startswith(prefix) for prefix in LOCAL_PREFIXES)


def is_cloud_url(base_url: str) -> bool:
    """Протилежність :func:`is_local_url` для непорожньої адреси."""
    return bool((base_url or "").strip()) and not is_local_url(base_url)


def detect_style(base_url: str) -> str:
    """Який протокол у адреси.

    ``native://…`` → ``embedded`` (власний рушій, без мережі),
    ``https://api.anthropic.com/...`` → ``anthropic``,
    ``generativelanguage.googleapis.com`` без ``/openai`` → ``gemini``,
    усе інше (зокрема Gemini-OpenAI шлях) → ``openai``.
    """
    if is_embedded(base_url):
        return EMBEDDED
    low = (base_url or "").strip().lower()
    if "anthropic.com" in low:
        return ANTHROPIC
    if "generativelanguage.googleapis.com" in low:
        return OPENAI if "/openai" in low else GEMINI
    return OPENAI


@dataclass(frozen=True)
class Adapter:
    """Опис протоколу провайдера."""

    style: str
    #: Префікс шляху відносно базової адреси (без скісної риски).
    chat_path: str
    models_path: str
    #: Версія Anthropic API (для інших — порожньо).
    version: str = ""
    extra_headers: tuple[tuple[str, str], ...] = ()

    def headers(self, api_key: str) -> dict[str, str]:
        """Заголовки авторизації для цього протоколу."""
        key = (api_key or "").strip()
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "BlackChpokIDE/2.0",
        }
        if self.style == ANTHROPIC:
            # Anthropic НЕ приймає Bearer: тільки x-api-key + версія.
            if key:
                headers["x-api-key"] = key
            headers["anthropic-version"] = self.version or "2023-06-01"
        elif self.style == GEMINI:
            # Нативний Gemini: ключ або заголовком, або в рядку запиту.
            if key:
                headers["x-goog-api-key"] = key
        else:
            headers["Authorization"] = f"Bearer {key or 'local'}"
        for name, value in self.extra_headers:
            headers[name] = value
        return headers

    def url(self, base_url: str, path: str, api_key: str = "") -> str:
        """Повна адреса запиту (у Gemini ключ іде в рядок запиту)."""
        base = (base_url or "").strip().rstrip("/")
        if self.style == ANTHROPIC and base.endswith("/v1"):
            full = f"{base}/{path}"
        elif self.style == OPENAI:
            full = f"{base}/{path}"
        else:
            full = f"{base}/{path}"
        if self.style == GEMINI and (api_key or "").strip():
            sep = "&" if "?" in full else "?"
            full = f"{full}{sep}key={api_key.strip()}"
        return full


_OPENAI_ADAPTER = Adapter(
    style=OPENAI,
    chat_path="chat/completions",
    models_path="models",
)

_ANTHROPIC_ADAPTER = Adapter(
    style=ANTHROPIC,
    chat_path="messages",
    models_path="models",
)

_GEMINI_ADAPTER = Adapter(
    style=GEMINI,
    # Нативний Gemini: модель підставляється в шлях, див. ``gemini_url``.
    chat_path="models/{model}:generateContent",
    models_path="models",
)

#: Вбудований рушій: шляхи формальні (мережі немає), потрібні лише для
#: сумісності інтерфейсу ``Adapter``.
_EMBEDDED_ADAPTER = Adapter(
    style=EMBEDDED,
    chat_path="chat/completions",
    models_path="models",
)


def for_url(base_url: str) -> Adapter:
    """Адаптер для адреси."""
    style = detect_style(base_url)
    if style == ANTHROPIC:
        return _ANTHROPIC_ADAPTER
    if style == GEMINI:
        return _GEMINI_ADAPTER
    if style == EMBEDDED:
        return _EMBEDDED_ADAPTER
    return _OPENAI_ADAPTER


# ─────────────────────────────────────────────────────────────────────────────
# Anthropic: перетворення запиту й відповіді
# ─────────────────────────────────────────────────────────────────────────────

def anthropic_payload(messages: list[dict[str, Any]], *, model: str,
                      max_tokens: int, temperature: float = 0.2,
                      tools: Optional[list[dict[str, Any]]] = None,
                      stream: bool = False) -> dict[str, Any]:
    """Наші повідомлення → формат Anthropic ``/v1/messages``.

    Головні відмінності, які треба врахувати:

    * ``system`` — не повідомлення, а окреме поле;
    * ``tool``-результати стають ``user``-повідомленням із блоком
      ``tool_result``;
    * виклики інструментів — блоки ``tool_use`` в ``assistant``;
    * ``max_tokens`` обов'язковий.
    """
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "")
        content = message.get("content")
        if role == "system":
            text = content if isinstance(content, str) else str(content or "")
            if text.strip():
                system_parts.append(text)
            continue
        if role == "tool":
            converted.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": str(message.get("tool_call_id") or ""),
                    "content": str(content or ""),
                }],
            })
            continue
        blocks: list[dict[str, Any]] = []
        text = content if isinstance(content, str) else str(content or "")
        if text.strip():
            blocks.append({"type": "text", "text": text})
        calls = message.get("tool_calls")
        if isinstance(calls, list):
            for call in calls:
                if not isinstance(call, dict):
                    continue
                function = call.get("function") or {}
                arguments = function.get("arguments")
                if isinstance(arguments, str):
                    try:
                        parsed = json.loads(arguments or "{}")
                    except json.JSONDecodeError:
                        parsed = {"raw": arguments}
                elif isinstance(arguments, dict):
                    parsed = arguments
                else:
                    parsed = {}
                blocks.append({
                    "type": "tool_use",
                    "id": str(call.get("id") or ""),
                    "name": str(function.get("name") or ""),
                    "input": parsed,
                })
        if not blocks:
            continue
        # Anthropic вимагає чергування user/assistant: зливаємо підряд.
        if converted and converted[-1]["role"] == role:
            converted[-1]["content"].extend(blocks)
        else:
            converted.append({"role": role, "content": blocks})
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max(1, int(max_tokens or 4096)),
        "messages": converted or [{"role": "user", "content": [{"type": "text", "text": ""}]}],
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)
    if temperature is not None:
        payload["temperature"] = max(0.0, min(1.0, float(temperature)))
    if tools:
        payload["tools"] = [_anthropic_tool(tool) for tool in tools if isinstance(tool, dict)]
        payload["tool_choice"] = {"type": "auto"}
    if stream:
        payload["stream"] = True
    return payload


def _anthropic_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Схема OpenAI → схема Anthropic."""
    function = tool.get("function") or {}
    parameters = function.get("parameters") or {"type": "object", "properties": {}}
    return {
        "name": str(function.get("name") or ""),
        "description": str(function.get("description") or ""),
        "input_schema": parameters,
    }


def anthropic_result(data: dict[str, Any]) -> tuple[str, list[dict[str, Any]], str]:
    """Відповідь Anthropic → (текст, tool_calls, причина завершення)."""
    text, calls, reason, _thought = anthropic_result_split(data)
    return text, calls, reason


def anthropic_result_split(
        data: dict[str, Any]) -> tuple[str, list[dict[str, Any]], str, str]:
    """Те саме, але ще й окремо РОЗДУМИ (``thinking``).

    Claude з увімкненим розширеним мисленням повертає блоки
    ``{"type": "thinking", "thinking": "…"}``. Раніше вони просто
    відкидались: користувач не бачив ходу думки, а стрімінг ці самі блоки
    показував — тобто поведінка залежала від того, чи ввімкнено потік.
    """
    texts: list[str] = []
    thoughts: list[str] = []
    calls: list[dict[str, Any]] = []
    for block in data.get("content") or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            texts.append(str(block.get("text") or ""))
        elif kind == "thinking":
            thoughts.append(str(block.get("thinking") or ""))
        elif kind == "tool_use":
            calls.append({
                "id": str(block.get("id") or f"call_{len(calls)}"),
                "type": "function",
                "function": {
                    "name": str(block.get("name") or ""),
                    "arguments": json.dumps(block.get("input") or {},
                                            ensure_ascii=False),
                },
            })
    return ("".join(texts), calls, str(data.get("stop_reason") or ""),
            "".join(thoughts))


def anthropic_stream_delta(data: dict[str, Any]) -> dict[str, Any]:
    """Подія SSE Anthropic → спрощена подія для нашого стрімінгу.

    Повертає ``{"text": …}``, ``{"reasoning": …}``,
    ``{"tool_start": {id, name}}``, ``{"tool_args": {id, delta}}``,
    ``{"tool_stop": {id}}`` або ``{}``.
    """
    kind = str(data.get("type") or "")
    if kind == "content_block_delta":
        delta = data.get("delta") or {}
        if delta.get("type") == "text_delta":
            return {"text": str(delta.get("text") or "")}
        if delta.get("type") == "input_json_delta":
            return {"tool_args": {"index": int(data.get("index") or 0),
                                  "delta": str(delta.get("partial_json") or "")}}
        if delta.get("type") == "thinking_delta":
            return {"reasoning": str(delta.get("thinking") or "")}
        return {}
    if kind == "content_block_start":
        block = data.get("content_block") or {}
        if block.get("type") == "tool_use":
            return {"tool_start": {"index": int(data.get("index") or 0),
                                   "id": str(block.get("id") or ""),
                                   "name": str(block.get("name") or "")}}
        return {}
    if kind == "content_block_stop":
        return {"tool_stop": {"index": int(data.get("index") or 0)}}
    return {}


def anthropic_usage(data: dict[str, Any]) -> dict[str, int]:
    """Використання токенів Anthropic → наш формат."""
    usage = data.get("usage") or {}
    prompt = int(usage.get("input_tokens") or 0)
    completion = int(usage.get("output_tokens") or 0)
    return {"prompt_tokens": prompt, "completion_tokens": completion,
            "total_tokens": prompt + completion}


# ─────────────────────────────────────────────────────────────────────────────
# Gemini: нативний API
# ─────────────────────────────────────────────────────────────────────────────

def gemini_payload(messages: list[dict[str, Any]], *,
                   temperature: float = 0.2,
                   max_tokens: int = 4096,
                   tools: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """Наші повідомлення → ``generateContent`` Gemini."""
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "")
        content = message.get("content")
        text = content if isinstance(content, str) else str(content or "")
        if role == "system":
            if text.strip():
                system_parts.append(text)
            continue
        if role == "tool":
            contents.append({
                "role": "user",
                "parts": [{"functionResponse": {
                    "name": str(message.get("name") or "tool"),
                    "response": {"result": text},
                }}],
            })
            continue
        parts: list[dict[str, Any]] = []
        if text.strip():
            parts.append({"text": text})
        calls = message.get("tool_calls")
        if isinstance(calls, list):
            for call in calls:
                if not isinstance(call, dict):
                    continue
                function = call.get("function") or {}
                arguments = function.get("arguments")
                if isinstance(arguments, str):
                    try:
                        parsed = json.loads(arguments or "{}")
                    except json.JSONDecodeError:
                        parsed = {}
                else:
                    parsed = arguments if isinstance(arguments, dict) else {}
                parts.append({"functionCall": {
                    "name": str(function.get("name") or ""),
                    "args": parsed,
                }})
        if not parts:
            continue
        contents.append({"role": "model" if role == "assistant" else "user",
                         "parts": parts})
    payload: dict[str, Any] = {
        "contents": contents or [{"role": "user", "parts": [{"text": ""}]}],
        "generationConfig": {
            "temperature": max(0.0, min(2.0, float(temperature))),
            "maxOutputTokens": max(1, int(max_tokens or 4096)),
        },
    }
    if system_parts:
        payload["systemInstruction"] = {
            "parts": [{"text": "\n\n".join(system_parts)}]}
    if tools:
        declarations = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            function = tool.get("function") or {}
            parameters = function.get("parameters") or {}
            declarations.append({
                "name": str(function.get("name") or ""),
                "description": str(function.get("description") or ""),
                "parameters": _gemini_schema(parameters),
            })
        if declarations:
            payload["tools"] = [{"functionDeclarations": declarations}]
    return payload


def _gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Схема параметрів OpenAI → підмножина, яку приймає Gemini.

    Gemini не приймає ``additionalProperties`` і не любить порожніх
    ``properties``; типи мусять бути у верхньому регістрі лише для
    ``OBJECT``/``STRING`` — решта приймається як є.
    """
    if not isinstance(schema, dict):
        return {"type": "OBJECT", "properties": {}}
    clean: dict[str, Any] = {}
    kind = str(schema.get("type") or "object").upper()
    clean["type"] = kind
    properties = schema.get("properties")
    if isinstance(properties, dict) and properties:
        clean["properties"] = {
            str(name): _gemini_schema(value) if isinstance(value, dict)
            else {"type": "STRING"}
            for name, value in properties.items()
        }
    items = schema.get("items")
    if isinstance(items, dict):
        clean["items"] = _gemini_schema(items)
    required = schema.get("required")
    if isinstance(required, list) and required:
        clean["required"] = [str(name) for name in required]
    description = schema.get("description")
    if description:
        clean["description"] = str(description)
    if "enum" in schema and isinstance(schema["enum"], list):
        clean["enum"] = [str(value) for value in schema["enum"]]
    return clean


def gemini_result(data: dict[str, Any]) -> tuple[str, list[dict[str, Any]], str]:
    """Відповідь Gemini → (текст, tool_calls, причина завершення)."""
    text, calls, reason, _thought = gemini_result_split(data)
    return text, calls, reason


def gemini_result_split(
        data: dict[str, Any]) -> tuple[str, list[dict[str, Any]], str, str]:
    """Те саме, але ще й окремо РОЗДУМИ (``"thought": true``).

    Gemini 2.5+ віддає міркування окремими частинами з прапорцем
    ``thought``. Раніше вони склеювались із відповіддю: користувач бачив
    «Думаю… Можливо, треба…» всередині відповіді, а модель ще й отримувала
    ці роздуми як власний текст. Тепер вони йдуть у ``reasoning`` — так
    само, як у OpenAI-сумісному каналі.
    """
    texts: list[str] = []
    thoughts: list[str] = []
    calls: list[dict[str, Any]] = []
    candidates = data.get("candidates") or []
    first = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
    for part in ((first.get("content") or {}).get("parts") or []):
        if not isinstance(part, dict):
            continue
        if part.get("text"):
            raw = str(part["text"])
            if part.get("thought"):
                thoughts.append(raw)
            else:
                texts.append(raw)
        call = part.get("functionCall")
        if isinstance(call, dict):
            calls.append({
                "id": f"call_{len(calls)}",
                "type": "function",
                "function": {
                    "name": str(call.get("name") or ""),
                    "arguments": json.dumps(call.get("args") or {},
                                            ensure_ascii=False),
                },
            })
    reason = str(first.get("finishReason") or "")
    return "".join(texts), calls, reason, "".join(thoughts)


def gemini_usage(data: dict[str, Any]) -> dict[str, int]:
    """Використання токенів Gemini → наш формат."""
    usage = data.get("usageMetadata") or {}
    prompt = int(usage.get("promptTokenCount") or 0)
    completion = int(usage.get("candidatesTokenCount") or 0)
    return {"prompt_tokens": prompt, "completion_tokens": completion,
            "total_tokens": int(usage.get("totalTokenCount") or (prompt + completion))}


def gemini_chat_path(model: str, *, stream: bool = False, base_url: str = "") -> str:
    """Шлях ``models/<model>:generateContent`` (або ``:streamGenerateContent``)."""
    name = (model or "").strip()
    # Повна назва «models/gemini-2.0-flash» — не дублюємо префікс.
    if name.startswith("models/"):
        name = name[len("models/"):]
    action = "streamGenerateContent" if stream else "generateContent"
    path = f"models/{name}:{action}"
    if stream:
        path += "?alt=sse"
    return path


__all__ = [
    "ANTHROPIC",
    "Adapter",
    "EMBEDDED",
    "GEMINI",
    "OPENAI",
    "anthropic_payload",
    "anthropic_result",
    "anthropic_stream_delta",
    "anthropic_usage",
    "detect_style",
    "for_url",
    "gemini_chat_path",
    "gemini_payload",
    "gemini_result",
    "gemini_usage",
    "is_cloud_url",
    "is_embedded",
    "is_local_url",
]
