"""Міст між наявним LLM-шаром IDE і власним рушієм.

Завдання: дати ``LLMClient`` (який уміє лише HTTP) можливість працювати з
моделлю, завантаженою В САМОМУ ПРОЦЕСІ. Для цього тут описаний той самий
контракт, що й у решти провайдерів:

* :func:`chat` — один блокуючий виклик, повертає ``dict`` у форматі
  відповіді OpenAI (``choices[0].message`` + ``usage``);
* :func:`chat_stream` — потокова віддача фрагментів через callback'и;
* :func:`list_models` — список локальних моделей для селектора;
* :func:`ping` — перевірка готовності.

Жодного HTTP: усе виконується викликами ``llama_decode`` у нашому процесі.
Це і є та сама автономність, якої вимагає продукт: IDE не потребує
запущеного LM Studio, Ollama чи llama-server.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from .api import NativeRuntime, RuntimeBusy
from .engine import EngineError
from .sampling import SamplingParams

LOG = logging.getLogger("blackchpok.native.bridge")

#: Псевдо-адреса вбудованого рушія. Саме її бачить решта IDE в налаштуваннях.
EMBEDDED_URL = "native://blackchpok"
#: Маркери, за якими адресу впізнають інші модулі.
EMBEDDED_MARKERS = ("native://", "inproc://", "blackchpok://")

_runtime: NativeRuntime | None = None
_runtime_lock = threading.Lock()
#: Модель, яку треба завантажити перед першим запитом (ставить UI).
_pending_model: str = ""


def is_embedded_url(url: str) -> bool:
    """Чи адреса означає «вбудований рушій», а не HTTP-сервер."""
    low = (url or "").strip().lower()
    return any(low.startswith(marker) for marker in EMBEDDED_MARKERS)


def runtime() -> NativeRuntime:
    """Спільний екземпляр Runtime API (один рушій на процес)."""
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = NativeRuntime()
        return _runtime


def set_runtime(instance: NativeRuntime | None) -> None:
    """Підмінити екземпляр (тести, перезапуск рушія)."""
    global _runtime
    with _runtime_lock:
        _runtime = instance


def remember_model(path_or_key: str) -> None:
    """Запам'ятати модель, яку треба завантажити за першої ж генерації."""
    global _pending_model
    _pending_model = (path_or_key or "").strip()


def pending_model() -> str:
    return _pending_model


def same_model(loaded: str, wanted: str) -> bool:
    """Чи це та сама модель: повний шлях, ім'я файлу або ключ без розширення."""
    left = str(loaded or "").strip()
    right = str(wanted or "").strip()
    if not right:
        return True
    if not left:
        return False
    a = Path(left)
    b = Path(right)
    names = {a.name.lower(), a.stem.lower()}
    if b.name.lower() in names or b.stem.lower() in names:
        return True
    try:
        if a.exists() and b.exists() and a.resolve() == b.resolve():
            return True
    except OSError:
        pass
    return (left.replace("/", "\\").rstrip("\\").lower()
            == right.replace("/", "\\").rstrip("\\").lower())


def _ensure_loaded(model: str = "") -> NativeRuntime:
    """Гарантувати, що завантажена САМЕ запитана модель.

    Якщо в пам'яті вже інша — ``load_model`` спершу її вивантажує
    (``Engine.load`` кличе ``unload``). Дві локальні моделі одночасно
    не тримаються: нова замінює попередню.
    """
    rt = runtime()
    target = (model or _pending_model or "").strip()
    if rt.engine.loaded and (not target or same_model(rt.engine.model_path, target)):
        return rt
    if not target:
        raise EngineError(
            "Вбудований рушій не має завантаженої моделі. "
            "Відкрий «Налаштування → AI Runtime» і натисни «Завантажити».")
    rt.load_model(target)
    remember_model("")
    return rt


def _params(temperature: float | None, max_tokens: int | None,
            *, seed: int = -1) -> SamplingParams:
    params = SamplingParams()
    if temperature is not None:
        params.temperature = float(temperature)
    if max_tokens is not None:
        params.max_tokens = int(max_tokens)
    params.seed = seed
    return params.normalised()


def chat(
    messages: list[dict[str, Any]],
    *,
    model: str = "",
    tools: list[dict[str, Any]] | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    should_stop: Callable[[], bool] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Блокуюча генерація у форматі відповіді OpenAI.

    Іде через :meth:`NativeRuntime.generate`, а не напряму через
    ``rt.engine``: так працюють черга (``_pending``), ``busy()``,
    тайм-аут і телеметрія ``_record``. Прямий виклик рушія обходив усе це,
    тому ``bridge.busy()`` не бачив роботи взагалі.

    ``timeout`` — СТЕЛЯ одного ходу. Раніше параметра не було взагалі, і
    завжди діяла типова 600 с із ``NativeRuntime.generate``: одна застрягла
    генерація тримала потік агента десять хвилин, і крок «висів» активним
    (заміряно ``tools/check_stability.py``: 600 і 855 с із ``active 1``).
    Тепер виклик передає власний тайм-аут із налаштувань.
    """
    rt = _ensure_loaded(model)
    started = time.perf_counter()
    payload_in = rt.generate(
        messages,
        params=_params(temperature, max_tokens),
        tools=tools,
        should_stop=should_stop,
        timeout=float(timeout) if timeout and timeout > 0 else 0.0,
    )
    text = payload_in.get("text") or ""
    tool_calls = payload_in.get("tool_calls") or []
    finish_reason = payload_in.get("finish_reason") or "stop"
    # ``NativeRuntime.generate`` віддає вже словник ``stats.to_dict()``,
    # а ``_usage`` уміє і об'єкт, і словник.
    usage = _usage(payload_in.get("stats") or {}, rt)
    if payload_in.get("timed_out"):
        finish_reason = "stop"
        usage["timed_out"] = True
    payload = {
        "id": f"native-{int(started * 1000)}",
        "object": "chat.completion",
        "created": int(started),
        "model": rt.engine.model_path,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": _strip_calls(text, tool_calls),
                    **({"tool_calls": tool_calls} if tool_calls else {}),
                },
                "finish_reason": ("tool_calls" if tool_calls else finish_reason),
            }
        ],
        "usage": usage,
    }
    return payload


def chat_stream(
    messages: list[dict[str, Any]],
    *,
    model: str = "",
    tools: list[dict[str, Any]] | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    on_text: Callable[[str], None] | None = None,
    on_reasoning: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    known_tools: Iterable[str] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Потокова генерація: ``on_text`` викликається на кожен фрагмент.

    Іде через :meth:`NativeRuntime.generate_stream`, а не напряму через
    ``rt.engine``: інакше не працюють ні черга (``_pending``), ні
    ``busy()``, ні телеметрія ``_record``. Раніше ``busy()`` **завжди**
    повертав ``False``, бо лічильник збільшувався лише в ``api.py``, а
    агент ходить саме сюди.

    ``known_tools`` — ПОВНИЙ перелік назв інструментів, які взагалі існують.
    Рушій будує його лише з переданих схем, а в лінивому режимі схем мало
    (≈15 із 50+). Через це виклик ``write_file``, написаний моделлю ТЕКСТОМ,
    не розпізнавався як виклик: імені не було в ``known``, текст вважався
    звичайною відповіддю, і файл не створювався (заміряно: «створи файл
    hello.py…» → 11 с, порожня тека, у чаті сирий JSON).
    """
    rt = _ensure_loaded(model)
    del on_reasoning                       # рушій поки не відділяє «думки»
    text_parts: list[str] = []
    stats = None
    tool_calls: list[dict[str, Any]] = []
    finish_reason = "stop"
    started = time.perf_counter()
    for chunk in rt.generate_stream(
            messages, params=_params(temperature, max_tokens), tools=tools,
            should_stop=should_stop, known_tools=known_tools,
            timeout=float(timeout) if timeout and timeout > 0 else 0.0):
        if chunk.get("done"):
            stats = chunk.get("stats")
            tool_calls = chunk.get("tool_calls") or []
            finish_reason = chunk.get("finish_reason") or "stop"
            break
        piece = chunk.get("text") or ""
        if not piece:
            continue
        text_parts.append(piece)
        if on_text is not None:
            try:
                on_text(piece)
            except Exception:                    # noqa: BLE001 - UI не має ламати стрім
                LOG.debug("on_text упав", exc_info=True)
    full = "".join(text_parts)
    content = _strip_calls(full, tool_calls)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    usage = _usage(stats, rt) if stats is not None else {
        "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    usage["total_duration_ms"] = round(elapsed_ms, 1)
    return {
        "id": f"native-stream-{int(started * 1000)}",
        "object": "chat.completion",
        "created": int(started),
        "model": rt.engine.model_path,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                    **({"tool_calls": tool_calls} if tool_calls else {}),
                },
                "finish_reason": "tool_calls" if tool_calls else finish_reason,
            }
        ],
        "usage": usage,
    }


def _strip_calls(text: str, tool_calls: Sequence[dict[str, Any]]) -> str:
    """Прибрати з тексту сирий JSON виклику, який уже став ``tool_calls``."""
    if not tool_calls or not text:
        return text or ""
    from .chatfmt import extract_tool_calls

    known = {str((call.get("function") or {}).get("name") or "") for call in tool_calls}
    known.discard("")
    if extract_tool_calls(text, known=known or None):
        return ""
    return text


def _usage(stats: Any, rt: NativeRuntime) -> dict[str, Any]:
    """Перевести телеметрію рушія у формат ``usage`` OpenAI."""
    data = stats.to_dict() if hasattr(stats, "to_dict") else dict(stats or {})
    prompt = int(data.get("prompt_tokens") or 0)
    completion = int(data.get("generated_tokens") or 0)
    details: dict[str, Any] = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "prompt_tokens_details": {"cached_tokens": int(data.get("cached_tokens") or 0)},
        "native": data,
    }
    del rt
    return details


def list_models() -> list[str]:
    """Список локальних моделей (для наявного селектора моделей)."""
    rt = runtime()
    models: list[str] = []
    for entry in rt.manager.local_models():
        models.append(entry.key)
    loaded = rt.engine.model_path
    if loaded:
        from pathlib import Path

        name = Path(loaded).stem
        if name not in models:
            models.insert(0, name)
    return models


def ping() -> tuple[bool, str]:
    """Готовність вбудованого рушія (без завантаження моделі)."""
    rt = runtime()
    if not rt.engine.available:
        return False, "Рушій llama.cpp не встановлено (розділ «AI Runtime»)."
    if rt.engine.loaded:
        info = rt.engine.describe()
        return True, (f"Вбудований рушій: {info.get('description', '')} · "
                      f"ctx {info.get('context_actual', 0)} · "
                      f"GPU-шарів {info.get('gpu_layers', 0)}")
    # Модель могла бути завантажена іншим екземпляром рушія (наприклад, до
    # того, як міст отримав спільний екземпляр). Тоді чесно кажемо про
    # наявність моделей, але не вдаємо, що модель уже в пам'яті.
    models = list_models()
    pending = _pending_model
    if pending:
        return True, (f"Рушій готовий. Обрана модель «{Path(pending).stem}» "
                      f"завантажиться перед першим запитом.")
    if not models:
        return False, "Рушій готовий, але локальних моделей немає."
    return True, (f"Рушій готовий (модель не завантажена). "
                  f"Доступно моделей: {len(models)}")


def load(path_or_key: str, **kwargs: Any) -> dict[str, Any]:
    """Завантажити модель у вбудований рушій."""
    info = runtime().load_model(path_or_key, **kwargs)
    remember_model("")
    return info


def unload() -> dict[str, Any]:
    return runtime().unload_model()


def busy() -> bool:
    """Чи виконується зараз генерація (для індикатора й черги)."""
    return getattr(runtime(), "_pending", 0) > 0


__all__ = [
    "EMBEDDED_MARKERS",
    "EMBEDDED_URL",
    "RuntimeBusy",
    "busy",
    "chat",
    "chat_stream",
    "is_embedded_url",
    "list_models",
    "load",
    "pending_model",
    "ping",
    "remember_model",
    "runtime",
    "set_runtime",
    "unload",
]
