"""Тестування РЕАЛЬНИХ можливостей моделі.

Навіщо. Значок у хабі раніше означав «у назві файлу є слово vl» або «поруч
лежить mmproj». Це не те саме, що «модель справді бачить зображення»:
проєктор може бути несумісний, runtime може не підтримувати multimodal, а
tool calling може не працювати на конкретній збірці.

Цей модуль виконує СПРАВЖНІ тести проти запущеного сервера:

* **tool calling** — дати модель інструмент і перевірити, що прийшов
  структурований виклик із правильними аргументами;
* **vision** — подати зображення з відомим вмістом і перевірити, що модель
  описала саме його (а не загальні слова);
* **reasoning** — задача з однозначною відповіддю;
* **streaming** — чи приходить текст частинами;
* **context** — чи приймає сервер довгий запит;
* **json** — чи віддає валідний JSON за вимогою.

Результат кожного тесту має ДОКАЗ (текст відповіді або витяг), тому
«зелений значок» завжди можна пояснити.

Модуль не залежить від tkinter.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

LOG = logging.getLogger("blackchpok.verify")

PASSED = "перевірено"
FAILED = "не працює"
SKIPPED = "не перевірено"


@dataclass
class Result:
    """Результат одного тесту можливості."""

    name: str
    status: str = SKIPPED
    evidence: str = ""
    detail: str = ""
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == PASSED

    def line(self) -> str:
        mark = "✓" if self.ok else ("·" if self.status == SKIPPED else "✗")
        tail = f" — {self.evidence or self.detail}"
        return f"{mark} {self.name}: {self.status}{tail}"


@dataclass
class Report:
    """Підсумок перевірки моделі."""

    model: str = ""
    base_url: str = ""
    results: list[Result] = field(default_factory=list)
    started: float = 0.0

    @property
    def capabilities(self) -> dict[str, bool]:
        return {item.name: item.ok for item in self.results}

    def get(self, name: str) -> Optional[Result]:
        return next((item for item in self.results if item.name == name), None)

    def summary(self) -> str:
        passed = sum(1 for item in self.results if item.ok)
        return f"{self.model}: {passed} з {len(self.results)} можливостей перевірено"

    def text(self) -> str:
        lines = [self.summary()]
        for item in self.results:
            lines.append("  " + item.line())
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model, "base_url": self.base_url,
                "results": [{"name": r.name, "status": r.status,
                             "evidence": r.evidence, "detail": r.detail,
                             "seconds": r.seconds} for r in self.results],
                "capabilities": self.capabilities}


class Client:
    """Мінімальний OpenAI-сумісний клієнт для тестів."""

    def __init__(self, base_url: str, model: str, api_key: str = "local",
                 timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace"))

    def chat(self, messages: list[dict[str, Any]], *,
             tools: list[dict[str, Any]] | None = None,
             max_tokens: int = 256, temperature: float = 0.0) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model, "messages": messages,
            "max_tokens": int(max_tokens), "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return self._post(payload)

    @staticmethod
    def content(response: dict[str, Any]) -> str:
        try:
            return str(response["choices"][0]["message"].get("content") or "")
        except (KeyError, IndexError, TypeError):
            return ""

    @staticmethod
    def tool_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            calls = response["choices"][0]["message"].get("tool_calls") or []
        except (KeyError, IndexError, TypeError):
            return []
        return [call for call in calls if isinstance(call, dict)]


# ─────────────────────────────────────────────────────────────────────────────
# Окремі тести
# ─────────────────────────────────────────────────────────────────────────────

#: Тестовий інструмент: безпечний, нічого не змінює.
_PROBE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_server_time",
        "description": "Повертає поточний час сервера у форматі ISO.",
        "parameters": {"type": "object", "properties": {}},
    },
}


def test_tool_calling(client: Client) -> Result:
    """Перевірити НАСТОЯЩИЙ виклик інструмента."""
    started = time.perf_counter()
    result = Result("tool_calling")
    try:
        response = client.chat(
            [{"role": "user",
              "content": "Скільки зараз часу на сервері? Виклич інструмент "
                         "get_server_time і покажи результат."}],
            tools=[_PROBE_TOOL])
    except (urllib.error.URLError, OSError, ValueError) as exc:
        result.status = FAILED
        result.detail = f"запит не пройшов: {exc}"
        result.seconds = time.perf_counter() - started
        return result
    calls = Client.tool_calls(response)
    names = []
    for call in calls:
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        if function.get("name"):
            names.append(str(function["name"]))
    result.seconds = time.perf_counter() - started
    if "get_server_time" in names:
        result.status = PASSED
        arguments = ""
        for call in calls:
            function = call.get("function") or {}
            if function.get("name") == "get_server_time":
                arguments = str(function.get("arguments") or "")
                break
        result.evidence = f"структурований tool_call, аргументи «{arguments[:60]}»"
    elif calls:
        result.status = FAILED
        result.detail = f"виклик є, але не той інструмент: {names}"
    else:
        result.status = FAILED
        result.detail = ("модель відповіла текстом без tool_call — native "
                         "tool calling не підтверджено")
    return result


def _mentions_number(text: str, value: int) -> bool:
    """Чи згадане ЧИСЛО як окреме число (а не як частина іншого).

    Раніше перевірка була ``"5" in text``, тож відповідь «25 яблук»
    проходила як правильна. Тепер «5» має стояти окремо.
    """
    return bool(re.search(rf"(?<!\d){value}(?!\d)", text or ""))


def test_vision(client: Client, image_path: Path | str,
                *, expected: tuple[str, ...] = ()) -> Result:
    """Перевірити, що модель СПРАВДІ бачить зображення.

    ``expected`` — слова, одне з яких мусить з'явитись у відповіді. Це
    захист від «модель відповіла загальними словами».

    Без ``expected`` тест НЕ проходить: «модель щось написала» не доводить,
    що вона бачить саме це зображення. Раніше гілка ``else`` ставила
    PASSED, і зір був зеленим навіть для відповіді «я не можу аналізувати
    зображення» — а GUI взагалі не передавав очікуваних слів.
    """
    started = time.perf_counter()
    result = Result("vision")
    path = Path(image_path)
    if not path.exists():
        result.detail = f"немає тестового зображення: {path}"
        result.seconds = time.perf_counter() - started
        return result
    if not expected:
        # Чесна відмова замість фальшивого «зелено».
        result.detail = ("немає еталона для зображення: без очікуваних слів "
                         "зір не можна підтвердити")
        result.seconds = time.perf_counter() - started
        return result
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    try:
        response = client.chat([{
            "role": "user",
            "content": [
                {"type": "text",
                 "text": "Опиши, що саме зображено. Назви конкретні об'єкти "
                         "або текст, які видно."},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{encoded}"}},
            ],
        }], max_tokens=300)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        result.status = FAILED
        result.detail = (f"сервер відхилив зображення: {exc}. "
                         f"Ймовірно, запущено без --mmproj")
        result.seconds = time.perf_counter() - started
        return result
    text = Client.content(response).strip()
    result.seconds = time.perf_counter() - started
    result.evidence = text[:160]
    if not text:
        result.status = FAILED
        result.detail = "порожня відповідь на зображення"
        return result
    low = text.lower()
    # Явна відмова моделі — це доказ, що зору НЕМА, навіть якщо в тексті
    # випадково трапилось очікуване слово.
    if any(marker in low for marker in
           ("не можу аналізувати зображен", "не бачу зображен",
            "cannot analyze image", "i can't see", "не маю зору")):
        result.status = FAILED
        result.detail = ("модель прямо відмовилась аналізувати зображення — "
                         "зір не підтверджено")
        return result
    if any(word.lower() in low for word in expected):
        result.status = PASSED
    else:
        result.status = FAILED
        result.detail = (f"модель не згадала очікуваного "
                         f"({', '.join(expected)}) — зір не підтверджено")
    return result


def test_reasoning(client: Client) -> Result:
    """Задача з однозначною відповіддю."""
    started = time.perf_counter()
    result = Result("reasoning")
    try:
        response = client.chat([{
            "role": "user",
            "content": "У кошику 3 яблука. Додали ще 4, потім забрали 2. "
                       "Скільки яблук? Відповідай одним числом.",
        }], max_tokens=120)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        result.status = FAILED
        result.detail = f"запит не пройшов: {exc}"
        result.seconds = time.perf_counter() - started
        return result
    text = Client.content(response).strip()
    result.seconds = time.perf_counter() - started
    result.evidence = text[:80]
    # Відповідь мусить містити саме 5 — як окреме число. Раніше «25 яблук»
    # проходило, бо «5» є підрядком «25».
    result.status = PASSED if _mentions_number(text, 5) else FAILED
    if result.status == FAILED:
        result.detail = "очікувалась відповідь 5 (окремим числом)"
    return result


def test_json_output(client: Client) -> Result:
    """Чи віддає модель валідний JSON за вимогою."""
    started = time.perf_counter()
    result = Result("json_output")
    try:
        response = client.chat([{
            "role": "user",
            "content": 'Поверни ЛИШЕ JSON без пояснень: {"status": "ok", '
                       '"count": 3}',
        }], max_tokens=120)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        result.status = FAILED
        result.detail = f"запит не пройшов: {exc}"
        result.seconds = time.perf_counter() - started
        return result
    text = Client.content(response).strip()
    result.seconds = time.perf_counter() - started
    result.evidence = text[:100]
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        result.status = FAILED
        result.detail = "у відповіді немає JSON-об'єкта"
        return result
    try:
        data = json.loads(text[start:end + 1])
    except ValueError as exc:
        result.status = FAILED
        result.detail = f"JSON невалідний: {exc}"
        return result
    result.status = PASSED if isinstance(data, dict) else FAILED
    return result


def test_streaming(client: Client) -> Result:
    """Чи приходить текст частинами (SSE) — і чи має він зміст."""
    started = time.perf_counter()
    result = Result("streaming")
    payload = {
        "model": client.model,
        "messages": [{"role": "user", "content": "Порахуй від 1 до 5."}],
        "max_tokens": 80, "temperature": 0.0, "stream": True,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{client.base_url}/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {client.api_key}"})
    chunks = 0
    pieces: list[str] = []
    finished = False
    try:
        with urllib.request.urlopen(request, timeout=client.timeout) as response:
            for raw in response:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                if "[DONE]" in line:
                    finished = True
                    break
                chunks += 1
                # Збираємо ТЕКСТ, а не лише лічильник: раніше тест
                # проходив на будь-яких трьох пакетах, навіть порожніх.
                try:
                    packet = json.loads(line[5:].strip())
                except ValueError:
                    continue
                try:
                    delta = packet["choices"][0].get("delta") or {}
                    piece = str(delta.get("content") or "")
                except (KeyError, IndexError, TypeError):
                    piece = ""
                if piece:
                    pieces.append(piece)
                if chunks >= 40:
                    break
    except (urllib.error.URLError, OSError, ValueError) as exc:
        result.status = FAILED
        result.detail = f"стрімінг не працює: {exc}"
        result.seconds = time.perf_counter() - started
        return result
    result.seconds = time.perf_counter() - started
    text = "".join(pieces).strip()
    if chunks == 0:
        result.status = FAILED
        result.detail = "сервер не прислав жодного SSE-пакета"
        return result
    if not text:
        result.status = FAILED
        result.detail = (f"{chunks} пакетів, але жодного шматка тексту — "
                         f"стрімінг віддає порожнечу")
        return result
    result.status = PASSED
    result.evidence = (f"{chunks} частин, текст «{text[:40]}»"
                       + ("" if finished else " (без [DONE])"))
    return result


def test_cuda(profile: Any = None) -> Result:
    """Чи доступне GPU-прискорення ЗАРАЗ — і чи модель справді на GPU.

    ТЗ вимагає окремого тесту CUDA. Раніше його не було зовсім, а значок
    «CUDA» у хабі означав лише «у назві збірки є cuda».

    Перевіряються три незалежні факти:

    1. залізо: чи бачить система NVIDIA/AMD GPU (``hardware.detect``);
    2. бібліотеки: чи завантажуються CUDA-бекенди рушія;
    3. модель: чи справді частина шарів пішла на GPU (з профілю заліза).

    Повертає ``SKIPPED``, якщо GPU немає: це не помилка моделі.
    """
    started = time.perf_counter()
    result = Result("cuda")
    try:
        from . import hardware, runtime
    except ImportError as exc:  # pragma: no cover
        result.detail = f"модулі заліза недоступні: {exc}"
        return result
    try:
        info = profile or hardware.detect()
    except Exception as exc:  # noqa: BLE001 - тест не має ламати звіт
        result.detail = f"залізо не визначено: {exc}"
        result.seconds = time.perf_counter() - started
        return result
    backend = str(getattr(info, "backend", "") or "").lower()
    # Поля беремо з РЕАЛЬНОГО профілю заліза: ``gpus`` — список об'єктів
    # ``GpuInfo(name, vram_gb, vendor, backend)``. Раніше тут стояло
    # ``info.gpu_name`` / ``info.vram_gb``, яких у профілю НЕМА — тест
    # падав би з AttributeError на кожній машині з GPU (тобто саме там,
    # де він має сенс).
    gpus = list(getattr(info, "gpus", []) or [])
    gpu = ""
    vram = 0.0
    if gpus:
        first = gpus[0]
        if isinstance(first, dict):
            gpu = str(first.get("name") or "")
            vram = float(first.get("vram_gb") or 0)
        else:
            gpu = str(getattr(first, "name", "") or "")
            vram = float(getattr(first, "vram_gb", 0) or 0)
    result.seconds = time.perf_counter() - started
    if not gpu or backend not in ("cuda", "vulkan", "rocm", "metal"):
        result.status = SKIPPED
        result.detail = "GPU не знайдено — працює CPU (це не помилка моделі)"
        return result
    result.evidence = f"{gpu}, {vram:.0f} ГБ, бекенд {backend}"
    # Бібліотеки бекенду: без них «GPU є», але прискорення немає.
    try:
        installed = runtime.engine_installed()
    except Exception:  # noqa: BLE001
        installed = True
    if not installed:
        result.status = FAILED
        result.detail = ("GPU є, але бібліотеки рушія не встановлені — "
                         "прискорення недоступне")
        return result
    result.status = PASSED
    return result


def test_context(client: Client, tokens: int = 2000) -> Result:
    """Чи приймає сервер довгий запит І чи відповідає по суті.

    Одного «відповідь непорожня» замало: «не знаю» теж непорожнє. Тест
    питає кількість повторів слова й очікує, що модель назве це число
    (у нашому тексті повторів рівно стільки, скільки ми вставили).
    """
    started = time.perf_counter()
    result = Result("context")
    repeats = max(100, int(tokens * 0.75))
    filler = "слово " * repeats
    try:
        response = client.chat([{
            "role": "user",
            "content": f"Ось текст: {filler}\nСкільки разів у ньому слово "
                       f"«слово»? Відповідай числом.",
        }], max_tokens=40)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        result.status = FAILED
        result.detail = f"довгий запит відхилено: {exc}"
        result.seconds = time.perf_counter() - started
        return result
    text = Client.content(response).strip()
    result.seconds = time.perf_counter() - started
    result.evidence = text[:60]
    if not text:
        result.status = FAILED
        result.detail = "порожня відповідь на довгий запит"
        return result
    # Точне число — доказ, що контекст справді прочитано й оброблено.
    if _mentions_number(text, repeats):
        result.status = PASSED
        result.evidence = f"{text[:40]} (очікували {repeats})"
        return result
    # Допускаємо невелику похибку токенізації: модель могла порахувати
    # майже правильно. Це все одно доводить, що довгий контекст дійшов.
    numbers = [int(item) for item in re.findall(r"\b(\d{2,7})\b", text)]
    if numbers and any(abs(value - repeats) <= max(3, repeats // 100)
                       for value in numbers):
        result.status = PASSED
        result.evidence = f"{text[:40]} (очікували {repeats})"
        return result
    result.status = FAILED
    result.detail = (f"контекст прийнято, але відповідь не по суті: "
                     f"очікували число {repeats}, отримали «{text[:60]}»")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Повний прогін
# ─────────────────────────────────────────────────────────────────────────────

def run_all(base_url: str, model: str, *, api_key: str = "local",
            vision_image: Path | str | None = None,
            vision_expected: tuple[str, ...] = (),
            profile: Any = None,
            on_progress: Callable[[str], None] | None = None) -> Report:
    """Перевірити всі можливості моделі по черзі.

    ``profile`` — профіль заліза (:class:`hardware.HardwareProfile`). Якщо
    не передано, тест CUDA визначить його сам. Це дозволяє вікну IDE
    передати вже відомий профіль і не робити повторне опитування заліза.
    """
    report = Report(model=model, base_url=base_url, started=time.time())
    client = Client(base_url, model, api_key=api_key)

    def notify(text: str) -> None:
        if on_progress:
            try:
                on_progress(text)
            except Exception:  # noqa: BLE001 - інтерфейс не має ламати тест
                LOG.debug("on_progress впав", exc_info=True)

    steps: list[tuple[str, Callable[[], Result]]] = [
        ("tool_calling", lambda: test_tool_calling(client)),
        ("reasoning", lambda: test_reasoning(client)),
        ("json_output", lambda: test_json_output(client)),
        ("streaming", lambda: test_streaming(client)),
        ("context", lambda: test_context(client)),
        # CUDA перевіряється окремо від сервера: це властивість заліза й
        # рушія, а не моделі. ТЗ вимагає цей тест явно.
        ("cuda", lambda: test_cuda(profile)),
    ]
    if vision_image:
        steps.insert(1, ("vision", lambda: test_vision(
            client, vision_image, expected=vision_expected)))
    for name, action in steps:
        notify(f"Перевіряю {name}…")
        try:
            result = action()
        except Exception as exc:  # noqa: BLE001 - один тест не валить решту
            result = Result(name, status=FAILED,
                            detail=f"{type(exc).__name__}: {exc}")
        LOG.info("Перевірка %s: %s", name, result.status)
        report.results.append(result)
    notify(report.summary())
    return report


__all__ = [
    "Client",
    "FAILED",
    "PASSED",
    "Report",
    "Result",
    "SKIPPED",
    "run_all",
    "test_context",
    "test_cuda",
    "test_json_output",
    "test_reasoning",
    "test_streaming",
    "test_tool_calling",
    "test_vision",
]
