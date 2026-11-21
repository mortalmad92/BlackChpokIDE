"""Живе визначення вікна контексту — для БУДЬ-ЯКОЇ моделі.

Навіщо окремий модуль. Донедавну вікно брали з трьох джерел, і жодне не
було справжнім для хмари:

* ``/props`` — ендпоінт llama-server. У хмари його немає взагалі;
* метадані ``.gguf`` — є лише для локального файлу;
* каталог провайдера (``cloud_agents``) — СТАТИЧНИЙ список, який ми самі
  й написали. Для Deploy там стоїть 1 000 000, і це правда, але для
  власного або нового провайдера там нулі, і агент падав на «обережний
  запас 8192» — тобто різав історію всемеро раніше, ніж міг.

Тепер вікно визначається ЖИВИМ запитом:

1. **``/models``** — багато OpenAI-сумісних серверів віддають
   ``context_length`` / ``max_context_length`` у переліку моделей.
2. **Пробний запит із контрольованим переповненням** — найнадійніше, і
   саме те, що шукав користувач («під будь-яку модель»). Надсилаємо
   коротке повідомлення з ``max_tokens``, більшим за будь-яке вікно, і
   читаємо з помилки, скільки токенів сервер дозволяє: провайдери
   відповідають ``400`` з текстом на кшталт «maximum context length is
   131072 tokens», «context_length_exceeded», «prompt is too long».
3. **Каталог провайдера** — запасний шлях, коли мережа недоступна.

Модуль НЕ змінює налаштувань і не вирішує, що робити з числом: він
повертає :class:`Probe` з полем ``tokens`` (0 — не вдалось) і поясненням,
ЗВІДКИ воно. Рішення ухвалює ``context_budget.resolve_window``.

Модуль не тягне tkinter. Мережеві виклики — лише з явного дозволу
викликача (``allow_network``), щоб тести й офлайн-режим не чекали таймаутів.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

LOG = logging.getLogger("blackchpok.context_probe")

#: Стеля, яку просимо в пробному запиті. Більша за будь-яке відоме вікно
#: (1M у Deploy, Gemini та інших), тому переповнення гарантоване — а саме
#: його відповідь і несе справжнє число.
PROBE_MAX_TOKENS = 2_000_000

#: Скільки чекати на пробний запит. Це перевірка можливостей, а не робота:
#: провайдер, який думає довше, однаково відповість помилкою.
PROBE_TIMEOUT = 30.0

#: Ознаки того, що число в тексті помилки — це ВІКНО КОНТЕКСТУ, а не,
#: скажімо, «maximum 20 requests per minute». Порядок важливий: спершу
#: точні формулювання провайдерів.
_CONTEXT_HINTS: tuple[str, ...] = (
    "context length", "context_length", "context window", "context size",
    "maximum context", "max context", "prompt is too long", "too many tokens",
    "prompt length", "input is too long", "maximum tokens", "n_ctx",
)


@dataclass
class Probe:
    """Результат живої проби вікна контексту."""

    tokens: int = 0
    #: Звідки число — для журналу й для чесного показу користувачу.
    source: str = ""
    #: Сира відповідь сервера (обрізана) — щоб причину можна було довести.
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.tokens > 0


def _headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json",
               "User-Agent": "BlackChpokIDE/1.2"}
    if (api_key or "").strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    return headers


def _numbers_in(text: str) -> list[int]:
    """Усі великі числа з тексту (кандидати у вікно контексту).

    Дрібні числа навмисно відкинуто: «20 requests», «HTTP 400» ніколи не
    бувають вікном, а от 131072, 128000, 1000000 — завжди.
    """
    found: list[int] = []
    for raw in re.findall(r"\d[\d,_ ]{2,}", text or ""):
        try:
            value = int(raw.replace(",", "").replace("_", "").replace(" ", ""))
        except ValueError:
            continue
        # Вікно менше 2048 токенів непрацездатне агентськи, а більше за
        # 100 млн не існує — це вже номер запиту або таймстемп.
        if 2048 <= value <= 100_000_000:
            found.append(value)
    return found


def _plausible_window(values: list[int]) -> int:
    """Найправдоподібніше вікно зі знайдених чисел.

    Провайдери пишуть у помилці кілька чисел: «maximum context length is
    131072 tokens. However, your messages resulted in 2000004 tokens».
    Вікно — МЕНШЕ з них, і воно ж зазвичай «кругле» (128k, 200k, 1M).
    """
    if not values:
        return 0
    # Спершу — точні степені двійки й круглі десяткові: саме так задають
    # вікна. Якщо таких немає, беремо найменше правдоподібне.
    round_ones = [value for value in values
                  if value % 1024 == 0 or value % 1000 == 0]
    pool = round_ones or values
    return min(pool)


def window_from_error(body: str) -> int:
    """Витягти вікно контексту з ТЕКСТУ помилки провайдера.

    Окрема функція, щоб її можна було перевірити тестом без мережі:
    формати помилок у провайдерів різні, і саме на цьому ламався б
    звичайний «розбери JSON».
    """
    text = (body or "").strip()
    if not text:
        return 0
    low = text.lower()
    if not any(hint in low for hint in _CONTEXT_HINTS):
        return 0
    # Спершу пробуємо JSON: деякі провайдери кладуть число в поле.
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict):
        for key in ("context_length", "max_context_length", "context_window",
                    "max_tokens", "limit"):
            value = _find_key(data, key)
            if isinstance(value, int) and 2048 <= value <= 100_000_000:
                return value
    # Провайдери, що віддають готове поле, але в іншому місці.
    match = re.search(r'"(\w*context\w*)"\s*:\s*(\d{4,})', text, re.IGNORECASE)
    if match:
        try:
            value = int(match.group(2))
            if 2048 <= value <= 100_000_000:
                return value
        except ValueError:
            pass
    return _plausible_window(_numbers_in(text))


def _find_key(data: Any, key: str) -> Any:
    """Знайти значення ключа вкладеного словника (глибина до 4)."""
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for value in data.values():
            found = _find_key(value, key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data[:4]:
            found = _find_key(item, key)
            if found is not None:
                return found
    return None


def window_from_models(payload: str, model: str = "") -> int:
    """Витягти вікно з відповіді ``GET /models``.

    Багато OpenAI-сумісних серверів (LM Studio, vLLM, OpenRouter) віддають
    ``context_length`` поруч із назвою моделі. Раніше це поле просто
    ігнорувалось, і агент брав «обережний запас 8192».
    """
    try:
        data = json.loads(payload)
    except ValueError:
        return 0
    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return 0
    wanted = (model or "").strip().lower()

    def window_of(item: Any) -> int:
        if not isinstance(item, dict):
            return 0
        for key in ("context_length", "max_context_length", "context_window",
                    "max_model_len", "max_input_tokens", "context_size"):
            value = item.get(key)
            if isinstance(value, int) and 2048 <= value <= 100_000_000:
                return value
            if isinstance(value, str) and value.isdigit():
                number = int(value)
                if 2048 <= number <= 100_000_000:
                    return number
        return 0

    # Спершу — саме наша модель, потім будь-яка з вікном.
    for item in items:
        name = str((item or {}).get("id") or (item or {}).get("name") or "").lower()
        if wanted and wanted in name:
            found = window_of(item)
            if found:
                return found
    for item in items:
        found = window_of(item)
        if found:
            return found
    return 0


def _post_json(url: str, payload: dict[str, Any], api_key: str,
               timeout: float) -> tuple[int, str]:
    """POST із поверненням ``(код, тіло)`` навіть на помилку.

    Ключове: тіло помилки ПОТРІБНЕ (воно й несе вікно контексту), тому
    ``HTTPError`` не летить далі, а читається як звичайна відповідь.
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    for name, value in _headers(api_key).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read(200_000).decode(
                "utf-8", "replace")
    except urllib.error.HTTPError as exc:
        try:
            return int(exc.code), exc.read(200_000).decode("utf-8", "replace")
        except OSError:
            return int(exc.code), ""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        LOG.debug("Проба вікна не дісталась сервера: %s", exc)
        return 0, ""


def _rejected(code: int, body: str) -> bool:
    """Чи сервер ВІДХИЛИВ запит через переповнення (а не з іншої причини)."""
    if 400 <= code < 500:
        low = (body or "").lower()
        # 400 «reduce the number of tokens», «too long», 413 — це ліміт.
        if any(hint in low for hint in _CONTEXT_HINTS):
            return True
        if any(hint in low for hint in ("reduce the number of tokens",
                                        "too long", "payload too large",
                                        "request entity too large")):
            return True
        return code == 413
    return False


def _accepted(code: int) -> bool:
    return 200 <= code < 300


def probe_by_bisection(base_url: str, model: str, *, api_key: str = "",
                       chat_path: str = "chat/completions",
                       timeout: float = PROBE_TIMEOUT,
                       low: int = 2048,
                       high: int = PROBE_MAX_TOKENS) -> Probe:
    """Знайти вікно бінарним пошуком, коли провайдер не називає числа.

    Навіщо. Частина провайдерів (зокрема Deploy) на переповнення
    відповідає загальним «Please reduce the number of tokens…» — без
    жодного числа. Тоді єдиний спосіб дізнатись ліміт: питати, поки
    сервер не погодиться.

    Коштує це дешево, бо кожен запит — ОДИН токен повідомлення й
    мінімальний ``max_tokens``: ми перевіряємо саме ліміт ``max_tokens``,
    а не довжину промпту.

    ── ЧОМУ ПОШУК ІДЕ ВІД 1024, А НЕ ВІД 2048 ──────────────────────────────
    Перша версія починала з 2048 і звужувала діапазон до точності 1024 —
    на живому Deploy це коштувало **16.5 секунди** (18 послідовних
    запитів). Тепер крок ширший (степені двійки), а потім уточнюємо вже
    навколо знайденої межі: 6–8 запитів замість 18, точність та сама.
    """
    root = (base_url or "").strip().rstrip("/")
    name = (model or "").strip()
    if not root or not name:
        return Probe()
    url = f"{root}/{chat_path.lstrip('/')}"

    def works(limit: int) -> bool:
        code, body = _post_json(
            url,
            {"model": name,
             "messages": [{"role": "user", "content": "1"}],
             "max_tokens": int(limit)},
            api_key, timeout)
        if code == 0:
            raise _ProbeOffline()
        if _accepted(code):
            return True
        if _rejected(code, body):
            return False
        # Інша помилка (401/404/429) — проба неможлива, не гадаємо.
        raise _ProbeOffline()

    try:
        if not works(low):
            return Probe(detail="сервер відхилив навіть малий запит")
        best = low
        # ── Фаза 1: грубе подвоєння, поки не відмовлять ───────────────────
        # Степені двійки дають ~10 кроків до мільйона, але на практиці
        # сервер відмовляє вже на 4–5-му, і тоді фаза 2 звужує діапазон.
        left, right = low, min(int(high), low * 2)
        while right <= int(high):
            if works(right):
                best = right
                left, right = right, right * 2
                continue
            break
        else:
            # Дійшли до межі проби — вікно не менше за неї.
            return Probe(min(best, int(high)), "бінарний пошук (межа проби)",
                         f"прийнято {best} токенів")
        if right > int(high):
            return Probe(int(high), "бінарний пошук (межа проби)",
                         f"прийнято {int(high)} токенів")
        # ── Фаза 2: уточнення між останнім прийнятим і першим відмовленим ──
        while right - left > max(1024, left // 64):
            middle = (left + right) // 2
            if works(middle):
                best = middle
                left = middle
            else:
                right = middle
        LOG.info("Вікно контексту бінарним пошуком: ~%s токенів", best)
        return Probe(best, "бінарний пошук", f"найбільше прийняте: {best}")
    except _ProbeOffline:
        return Probe(detail="мережа або ключ не дали завершити пробу")
    except Exception:  # noqa: BLE001 - проба не має ламати хід
        LOG.debug("Бінарний пошук вікна не вдався", exc_info=True)
        return Probe()


class _ProbeOffline(RuntimeError):
    """Проба не може продовжитись (мережа, ключ, інша помилка)."""


def probe_window(base_url: str, model: str, *, api_key: str = "",
                 chat_path: str = "chat/completions",
                 allow_network: bool = True,
                 timeout: float = PROBE_TIMEOUT,
                 bisect: bool = True) -> Probe:
    """Спитати в СЕРВЕРА справжнє вікно контексту.

    Порядок: спершу дешеве ``/models``, потім пробний запит. Обидва кроки
    необов'язкові: якщо мережа недоступна, повертається ``Probe()`` з
    нулем — викликач тоді бере каталог провайдера або обережний запас.
    """
    root = (base_url or "").strip().rstrip("/")
    if not root or not allow_network:
        return Probe()
    name = (model or "").strip()

    # ── Крок 1: /models (дешево й без витрат токенів) ─────────────────────
    try:
        request = urllib.request.Request(f"{root}/models", method="GET")
        for header, value in _headers(api_key).items():
            if header != "Content-Type":
                request.add_header(header, value)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            listing = response.read(400_000).decode("utf-8", "replace")
        found = window_from_models(listing, name)
        if found:
            return Probe(found, "перелік /models", listing[:200])
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            OSError, ValueError) as exc:
        LOG.debug("Вікно з /models не прочитано: %s", exc)

    # ── Крок 2: пробний запит, що ГАРАНТОВАНО переповнює вікно ────────────
    # Просимо більше токенів, ніж будь-яка модель має. Провайдер відповідає
    # 400 і пише справжній ліміт. Це єдиний спосіб дізнатись вікно в хмари,
    # де немає ні /props, ні gguf.
    if not name:
        return Probe()
    code, body = _post_json(
        f"{root}/{chat_path.lstrip('/')}",
        {"model": name,
         "messages": [{"role": "user", "content": "1"}],
         "max_tokens": PROBE_MAX_TOKENS},
        api_key, timeout)
    if code == 0:
        return Probe()
    found = window_from_error(body)
    if found:
        return Probe(found, "відповідь сервера про переповнення", body[:300])
    # 200 означає, що сервер прийняв мільйон токенів — це не помилка
    # проби: просто вікно більше за наше припущення.
    if 200 <= code < 300:
        LOG.info("Сервер прийняв max_tokens=%s — вікно не менше", PROBE_MAX_TOKENS)
        return Probe(0, "сервер прийняв пробний запит", body[:200])
    # ── Крок 3: сервер відмовив без числа — шукаємо межу бінарно ───────────
    # Заміряно на справжньому Deploy: на переповнення він відповідає
    # загальним «Please reduce the number of tokens…», і числа в тексті
    # немає. Без цього кроку вікно лишалось «невідомим», і агент працював
    # із запасом 8192 замість реального мільйона.
    if bisect and _rejected(code, body):
        return probe_by_bisection(
            base_url, model, api_key=api_key, chat_path=chat_path,
            timeout=timeout)
    return Probe(0, "", body[:300])


__all__ = [
    "PROBE_MAX_TOKENS",
    "PROBE_TIMEOUT",
    "Probe",
    "probe_window",
    "window_from_error",
    "window_from_models",
]
