"""Автоматичне регулювання контексту для БУДЬ-ЯКОЇ моделі.

Навіщо окремий модуль. Реальний збій, який користувач бачив як «модель не
працює»:

```
--ctx-size 32768            ← стільки попросили в IDE
n_ctx_slot = 16384          ← стільки РЕАЛЬНО дав сервер (ділить на слоти)
промпт = 8549 токенів
+ система, схеми інструментів, історія, відповідь…
→ сервер обриває з'єднання (WinError 10054)
```

Тобто число в налаштуваннях могло бути більшим за реальне вікно моделі.
Досі ніхто не звіряв ці числа, і агент надсилав промпт навмання.

Модуль робить три речі:

1. **Визначає справжнє вікно** — з ``/props`` (``n_ctx``), з метаданих GGUF,
   з налаштувань, зрешті — з безпечного запасу. Це джерело правди, а не
   «скільки попросили в налаштуваннях».
2. **Планує бюджет** — скільки лишити на систему, схеми інструментів,
   історію й відповідь, із запасом під похибку токенізації.
3. **Стискає запит до бюджету** — не «коли вже обірвалось», а ЗАЗДАЛЕГІДЬ.

Модуль не залежить від tkinter і не робить мережевих викликів: усе, що
потрібно з мережі, передає викликач (``measure``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

LOG = logging.getLogger("blackchpok.context_budget")

#: Найменше вікно, з яким ще можна працювати агентськи. Менше — це вже
#: не «малий контекст», а непрацездатна конфігурація: системний промпт і
#: схеми інструментів самі займають тисячі токенів.
MIN_USABLE_WINDOW = 2048

#: Частка вікна під ВІДПОВІДЬ моделі. 25% — компроміс: локальні моделі
#: люблять довгі відповіді з кодом, і замалий резерв обрізав би їх посередині.
ANSWER_SHARE = 0.25

#: Частка вікна під ІСТОРІЮ діалогу (решта — система, схеми, відповідь).
HISTORY_SHARE = 0.55

#: Запас на похибку підрахунку токенів. Точний tokenizer є не завжди, а
#: українська кирилиця дає до 2× похибки в евристиці.
SAFETY_SHARE = 0.10

#: Скільки токенів додавати на службову обгортку кожного повідомлення
#: (роль, роздільники) — приблизно, але краще переоцінити.
PER_MESSAGE_OVERHEAD = 6


@dataclass
class Window:
    """Справжнє вікно контексту моделі та його походження.

    ``source`` — ЗВІДКИ число. Це принципово: користувач має бачити, чи це
    реальний ліміт сервера, чи обережна оцінка.
    """

    tokens: int = 0
    source: str = ""
    #: Модель сама повідомила ліміт (``/props``) — найнадійніше джерело.
    measured: bool = False
    note: str = ""

    @property
    def usable(self) -> int:
        return max(0, int(self.tokens))

    def text(self) -> str:
        if not self.tokens:
            return "вікно невідоме — працюю з обережним запасом"
        return f"{self.tokens:,} токенів ({self.source})".replace(",", " ")


@dataclass
class Budget:
    """Розподіл вікна під час одного запиту."""

    window: int = 0
    answer: int = 0
    history: int = 0
    tools: int = 0
    system: int = 0
    safety: int = 0
    #: Скільки токенів лишилось на власне повідомлення й результати.
    payload: int = 0
    notes: list[str] = field(default_factory=list)

    def text(self) -> str:
        return (f"вікно {self.window:,} · відповідь {self.answer:,} · "
                f"історія {self.history:,} · інструменти {self.tools:,} · "
                f"система {self.system:,} · запас {self.safety:,}"
                ).replace(",", " ")


def resolve_window(*, settings: Any = None, props_ctx: int = 0,
                   gguf_ctx: int = 0, model_params_b: float = 0.0,
                   source: str = "") -> Window:
    """Визначити справжнє вікно контексту з усіх доступних джерел.

    Пріоритет навмисний — від найнадійнішого до найобережнішого:

    1. ``props_ctx`` — що сервер САМ сказав (``/props`` → ``n_ctx``).
       Це єдине джерело, яке знає про поділ на слоти: ``--ctx-size 32768``
       при двох слотах дає ``n_ctx = 16384``, і саме це реальний ліміт.
    2. ``gguf_ctx`` — тренувальне вікно з метаданих моделі
       (``*.context_length``): навіть якщо сервер запущено з більшим
       числом, модель не вміє далі.
    3. налаштування IDE (``engine.ctx_size``) — те, що попросив користувач.
    4. обережний запас за розміром моделі.

    ``source`` — людська назва джерела для пункту 1. У вбудованого рушія
    немає ``/props``: там вікно читається з контексту в пам'яті, і писати
    «сервер /props» означало б збрехати користувачу про походження числа.
    """
    floor = MIN_USABLE_WINDOW
    if props_ctx and props_ctx > 0:
        tokens = int(props_ctx)
        # Модель не вміє більше за своє тренувальне вікно — не обманюємось.
        if gguf_ctx and gguf_ctx > 0:
            tokens = min(tokens, int(gguf_ctx))
        return Window(tokens=max(floor, tokens),
                      source=(source or "сервер /props"), measured=True)
    if gguf_ctx and gguf_ctx > 0:
        return Window(tokens=max(floor, int(gguf_ctx)),
                      source="метадані моделі", measured=True)
    requested = 0
    if settings is not None:
        try:
            requested = int(getattr(settings.engine, "ctx_size", 0) or 0)
        except (AttributeError, TypeError, ValueError):
            requested = 0
    if requested > 0:
        return Window(tokens=max(floor, requested), source="налаштування IDE")
    # Нічого не відомо — беремо запас за розміром моделі. Велика модель
    # зазвичай має більше вікно, але обіцяти багато небезпечно.
    guess = 8192 if (model_params_b or 0) >= 7 else 16384
    LOG.info("Вікно контексту невідоме — беру обережний запас %s", guess)
    return Window(tokens=guess, source="обережний запас",
                  note="точне вікно невідоме: сервер не повідомив n_ctx")


def plan(window: Window | int, *, system_tokens: int = 0,
         tools_tokens: int = 0) -> Budget:
    """Розподілити вікно: відповідь, історія, система, схеми, запас.

    ``payload`` — скільки токенів лишається на повідомлення й результати
    інструментів. Саме це число агент використовує для стискання, і саме
    його бракувало: раніше історія різалась за фіксованою формулою, яка не
    знала ні реального вікна, ні розміру схем.
    """
    total = int(window.tokens if isinstance(window, Window) else window) or 0
    if total <= 0:
        return Budget()
    answer = max(256, int(total * ANSWER_SHARE))
    safety = max(128, int(total * SAFETY_SHARE))
    system = max(0, int(system_tokens))
    tools = max(0, int(tools_tokens))
    fixed = answer + safety + system + tools
    room = total - fixed
    if room < 256:
        # Схеми й система самі з'їли вікно: це чесна діагностика, а не
        # мовчазний збій. Викликач має зменшити набір інструментів.
        LOG.warning("Контекст переповнений службовими даними: вікно %s, "
                    "система %s, схеми %s", total, system, tools)
    history = max(0, min(int(total * HISTORY_SHARE), max(0, room)))
    payload = max(0, room - history)
    budget = Budget(window=total, answer=answer, history=history,
                    tools=tools, system=system, safety=safety, payload=payload)
    if room < 256:
        budget.notes.append(
            f"службові дані ({system + tools} токенів) майже з'їли вікно "
            f"{total}")
    if total < MIN_USABLE_WINDOW:
        budget.notes.append(
            f"вікно {total} замале для агентської роботи (мінімум "
            f"{MIN_USABLE_WINDOW})")
    return budget


def estimate_tokens(text: str, *, counter=None) -> int:
    """Оцінити токени рядка (точний лічильник, якщо є)."""
    body = str(text or "")
    if not body:
        return 0
    if counter is not None:
        try:
            exact = int(counter(body))
            if exact > 0:
                return exact + PER_MESSAGE_OVERHEAD
        except Exception:  # noqa: BLE001 - лічильник не має ламати оцінку
            LOG.debug("Точний підрахунок не вдався", exc_info=True)
    cyrillic = sum(1 for ch in body if "\u0400" <= ch <= "\u04FF")
    latin = len(body) - cyrillic
    return int(cyrillic / 1.6 + latin / 3.6) + PER_MESSAGE_OVERHEAD + 2


def fit_messages(messages: Iterable[dict[str, Any]], budget_tokens: int, *,
                 counter=None, keep_first: int = 1) -> list[dict[str, Any]]:
    """Обрізати історію так, щоб вона влізла в ``budget_tokens``.

    Зберігаємо:

    * перші ``keep_first`` повідомлень (системний контекст);
    * ОСТАННІ повідомлення — найсвіжіше завжди важливіше за давнє.

    Обрізаємо СЕРЕДИНУ, а не кінець: саме так розмова лишається зв'язною.
    """
    items = list(messages)
    if not items or budget_tokens <= 0:
        return items
    counts = [estimate_tokens(str(item.get("content") or ""), counter=counter)
              for item in items]
    total = sum(counts)
    if total <= budget_tokens:
        return items
    head = items[:keep_first]
    head_tokens = sum(counts[:keep_first])
    tail: list[dict[str, Any]] = []
    used = head_tokens
    for index in range(len(items) - 1, keep_first - 1, -1):
        if used + counts[index] > budget_tokens:
            break
        tail.insert(0, items[index])
        used += counts[index]
    if not tail and len(items) > keep_first:
        # Навіть одне повідомлення не влізає — лишаємо найсвіжіше, але
        # помічаємо це для викликача (він покаже користувачу).
        tail = [items[-1]]
    result = head + tail
    dropped = len(items) - len(result)
    if dropped:
        LOG.info("Історію стиснуто: -%s повідомлень (%s токенів бюджету)",
                 dropped, budget_tokens)
    return result


__all__ = [
    "ANSWER_SHARE",
    "Budget",
    "HISTORY_SHARE",
    "MIN_USABLE_WINDOW",
    "SAFETY_SHARE",
    "Window",
    "estimate_tokens",
    "fit_messages",
    "plan",
    "resolve_window",
]
