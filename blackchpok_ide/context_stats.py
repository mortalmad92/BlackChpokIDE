"""Статистика контексту: кроки, токени, швидкість і заповнення вікна.

Дані беруться з відповідей сервера моделі, а не вигадуються:

* ``usage`` — ``prompt_tokens``, ``completion_tokens``, ``total_tokens`` і
  ``prompt_tokens_details.cached_tokens`` (llama.cpp і OpenAI-сумісні сервери);
* ``timings`` — ``prompt_per_second`` / ``predicted_per_second`` (llama.cpp).

Якщо сервер цих полів не віддає, модуль чесно показує нулі, а не вигадані
числа. Модуль не залежить від tkinter — його можна тестувати окремо.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from . import context_budget


def _as_int(value: Any, default: int = 0) -> int:
    """Обережно перетворити значення у ціле (сервери іноді віддають рядки)."""
    try:
        if value is None:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def format_tokens(count: int) -> str:
    """Токени у людському вигляді: 950 · 12 400 → «12,4 тис.» · 1 240 000 → «1,2 млн»."""
    count = max(0, int(count))
    if count < 1000:
        return str(count)
    if count < 1_000_000:
        return f"{_decimal(count / 1000)} тис."
    return f"{_decimal(count / 1_000_000)} млн"


def _decimal(value: float) -> str:
    """Один знак після коми, як це прийнято в українській мові."""
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    if not text:
        return "0"
    return text.replace(".", ",")


def format_duration(seconds: float) -> str:
    """Тривалість українською: «45 с», «2 хв 5 с», «1 год 3 хв»."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} с"
    if seconds < 3600:
        minutes, rest = divmod(seconds, 60)
        return f"{minutes} хв {rest} с" if rest else f"{minutes} хв"
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    return f"{hours} год {minutes} хв" if minutes else f"{hours} год"


def percent(part: float, total: float) -> float:
    """Відсоток із захистом від ділення на нуль."""
    if total <= 0:
        return 0.0
    return max(0.0, min(100.0, 100.0 * part / total))


@dataclass
class StepStats:
    """Один крок агента (один запит до моделі)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    prompt_per_second: float = 0.0
    predicted_per_second: float = 0.0
    tool_calls: int = 0
    duration: float = 0.0
    model: str = ""
    at: float = field(default_factory=time.time)

    @classmethod
    def from_result(cls, result: Any, *, tool_calls: int = 0,
                    duration: float = 0.0) -> "StepStats":
        """Побудувати крок із ``ChatResult`` (або словника)."""
        usage = getattr(result, "usage", None)
        if usage is None and isinstance(result, dict):
            usage = result.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        timings = usage.get("timings") if isinstance(usage.get("timings"), dict) else {}
        if not timings and isinstance(result, dict):
            raw = result.get("timings")
            timings = raw if isinstance(raw, dict) else {}
        # ── ВЛАСНИЙ РУШІЙ: швидкості лежать в ``usage["native"]`` ─────────
        # Вбудований рушій віддає не ``timings`` llama-server, а власний
        # блок із реальними числами ``llama_perf_context``:
        #
        #   usage["native"] = {"tokens_per_second": 31.1,
        #                      "prompt_tokens_per_second": 581,
        #                      "prefill_ms": 96, "decode_ms": 1067, …}
        #
        # Без цього швидкість у смузі статистики лишалась би нулем, хоч
        # рушій її знає точно.
        native = usage.get("native") if isinstance(usage.get("native"), dict) else {}
        if native:
            merged = dict(timings)
            merged.setdefault("predicted_per_second",
                              native.get("tokens_per_second"))
            merged.setdefault("prompt_per_second",
                              native.get("prompt_tokens_per_second"))
            merged.setdefault("predicted_n", native.get("generated_tokens"))
            merged.setdefault("prompt_n", native.get("prompt_tokens"))
            timings = merged

        details = usage.get("prompt_tokens_details")
        details = details if isinstance(details, dict) else {}
        cached = _as_int(details.get("cached_tokens"))
        if not cached:
            cached = _as_int(usage.get("cache_read_input_tokens"))
        if not cached:
            cached = _as_int(timings.get("cache_n"))

        # llama.cpp кладе лічильники двома способами: або в usage
        # (prompt_n/predicted_n), або в timings — читаємо обидва.
        prompt = (_as_int(usage.get("prompt_tokens"))
                  or _as_int(usage.get("prompt_n"))
                  or _as_int(timings.get("prompt_n")))
        completion = (_as_int(usage.get("completion_tokens"))
                      or _as_int(usage.get("predicted_n"))
                      or _as_int(timings.get("predicted_n")))
        total = _as_int(usage.get("total_tokens")) or (prompt + completion)

        return cls(
            prompt_tokens=prompt,
            completion_tokens=completion,
            cached_tokens=cached,
            total_tokens=total,
            prompt_per_second=_as_float(timings.get("prompt_per_second")),
            predicted_per_second=_as_float(timings.get("predicted_per_second")),
            tool_calls=int(tool_calls),
            duration=max(0.0, float(duration)),
            model=str(getattr(result, "model", "") or usage.get("model") or ""),
        )


@dataclass
class ContextBreakdown:
    """З чого складається контекст: підказка, інструменти, повідомлення.

    Це оцінка в токенах, бо сервер віддає лише загальний ``prompt_tokens``.
    Сума частин масштабується до реального числа, тож відсотки чесні.
    """

    system_tokens: int = 0        # системна підказка (промпт + скіли)
    tools_tokens: int = 0         # описи інструментів, які бачить модель
    messages_tokens: int = 0      # історія діалогу (повідомлення + результати)
    total_tokens: int = 0         # реальний prompt_tokens від сервера

    @property
    def estimated_total(self) -> int:
        return self.system_tokens + self.tools_tokens + self.messages_tokens

    def scaled(self, total: int | None = None) -> "ContextBreakdown":
        """Підігнати частини під реальний ``total_tokens``.

        Сервер рахує токени своїм токенізатором, тому наша оцінка завжди
        трохи інша. Масштабування зберігає пропорції й робить числа
        узгодженими із загальним лічильником.
        """
        target = int(total if total is not None else self.total_tokens)
        estimate = self.estimated_total
        if target <= 0 or estimate <= 0:
            return self
        if abs(estimate - target) <= max(4, target * 0.02):
            return ContextBreakdown(self.system_tokens, self.tools_tokens,
                                    self.messages_tokens, target)
        factor = target / estimate
        system = int(round(self.system_tokens * factor))
        tools = int(round(self.tools_tokens * factor))
        messages = max(0, target - system - tools)
        return ContextBreakdown(system, tools, messages, target)

    @property
    def parts(self) -> list[tuple[str, int]]:
        """Складові в порядку показу: (підпис, токени)."""
        return [
            ("Системна підказка", self.system_tokens),
            ("Опис інструментів", self.tools_tokens),
            ("Повідомлення", self.messages_tokens),
        ]

    def percent_of(self, value: int) -> float:
        return percent(value, self.total_tokens or self.estimated_total)


def split_context(
    *,
    system_prompt: str = "",
    tools: Iterable[Any] = (),
    messages: Iterable[dict[str, Any]] = (),
    total_tokens: int = 0,
) -> ContextBreakdown:
    """Розкласти контекст на підказку, опис інструментів і повідомлення."""
    system = estimate_tokens(system_prompt)
    tools_tokens = estimate_tools(tools)
    messages_tokens = estimate_messages(messages)
    breakdown = ContextBreakdown(system, tools_tokens, messages_tokens, int(total_tokens))
    return breakdown.scaled()


def estimate_tools(tools: Iterable[Any]) -> int:
    """Оцінити розмір описів інструментів у токенах.

    Модель бачить JSON-схеми цілком, тому беремо назви, описи й параметри.
    """
    total = 0
    for tool in tools or ():
        if isinstance(tool, dict):
            function = tool.get("function") if isinstance(tool.get("function"), dict) else tool
            name = str(function.get("name") or "")
            description = str(function.get("description") or "")
            params = function.get("parameters")
            blob = f"{name} {description}"
            if isinstance(params, dict):
                blob += " " + _flatten_schema(params)
            total += estimate_tokens(blob) + 8
        else:
            total += estimate_tokens(str(tool)) + 4
    return total


def _flatten_schema(value: Any, depth: int = 0) -> str:
    """Плоский текст із JSON-схеми (для оцінки розміру)."""
    if depth > 6:
        return ""
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            parts.append(str(key))
            parts.append(_flatten_schema(item, depth + 1))
        return " ".join(part for part in parts if part)
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten_schema(item, depth + 1) for item in value)
    return str(value)


@dataclass
class ContextStats:
    """Накопичена статистика одного діалогу."""

    steps: list[StepStats] = field(default_factory=list)
    context_limit: int = 0          # розмір вікна моделі в токенах
    last_prompt_tokens: int = 0     # скільки займає поточний контекст
    started_at: float = field(default_factory=time.time)
    tool_calls: int = 0
    breakdown: ContextBreakdown = field(default_factory=ContextBreakdown)

    # ── накопичення ────────────────────────────────────────────────────────
    def add(self, step: StepStats) -> None:
        self.steps.append(step)
        self.tool_calls += max(0, int(step.tool_calls))
        if step.prompt_tokens:
            # Останній запит — найкраща оцінка поточного розміру контексту,
            # бо історія лише додається.
            self.last_prompt_tokens = step.prompt_tokens
            # Частини теж мають відповідати останньому запиту.
            if self.breakdown.estimated_total:
                self.breakdown = self.breakdown.scaled(step.prompt_tokens)

    def update_breakdown(self, *, system_prompt: str = "", tools: Iterable[Any] = (),
                         messages: Iterable[dict[str, Any]] = ()) -> ContextBreakdown:
        """Перерахувати складові контексту за поточним станом діалогу."""
        self.breakdown = split_context(
            system_prompt=system_prompt,
            tools=tools,
            messages=messages,
            total_tokens=self.last_prompt_tokens,
        )
        return self.breakdown

    def add_result(self, result: Any, *, tool_calls: int = 0, duration: float = 0.0) -> StepStats:
        step = StepStats.from_result(result, tool_calls=tool_calls, duration=duration)
        self.add(step)
        return step

    def reset(self) -> None:
        self.steps.clear()
        self.tool_calls = 0
        self.last_prompt_tokens = 0
        self.breakdown = ContextBreakdown()
        self.started_at = time.time()

    def set_limit(self, limit: int) -> None:
        self.context_limit = max(0, int(limit))

    # ── підсумки ───────────────────────────────────────────────────────────
    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def prompt_tokens(self) -> int:
        return sum(step.prompt_tokens for step in self.steps)

    @property
    def completion_tokens(self) -> int:
        return sum(step.completion_tokens for step in self.steps)

    @property
    def cached_tokens(self) -> int:
        return sum(step.cached_tokens for step in self.steps)

    @property
    def total_tokens(self) -> int:
        if not self.steps:
            return 0
        return sum(step.total_tokens or (step.prompt_tokens + step.completion_tokens)
                   for step in self.steps)

    @property
    def cache_hit_percent(self) -> float:
        """Частка вхідних токенів, які сервер узяв із кешу."""
        prompt = self.prompt_tokens
        if prompt <= 0:
            return 0.0
        return percent(self.cached_tokens, prompt)

    @property
    def fill_percent(self) -> float:
        """Наскільки заповнене вікно контексту."""
        if self.context_limit <= 0:
            return 0.0
        return percent(self.last_prompt_tokens, self.context_limit)

    @property
    def speed(self) -> float:
        """Швидкість генерації, ток/с (останній крок, інакше середня)."""
        for step in reversed(self.steps):
            if step.predicted_per_second > 0:
                return step.predicted_per_second
        generated = self.completion_tokens
        elapsed = sum(step.duration for step in self.steps)
        if elapsed <= 0 or generated <= 0:
            return 0.0
        return generated / elapsed

    @property
    def elapsed(self) -> float:
        if not self.steps:
            return 0.0
        return sum(step.duration for step in self.steps)

    @property
    def elapsed_text(self) -> str:
        return format_duration(self.elapsed)

    # ── рядки для інтерфейсу ───────────────────────────────────────────────
    def speed_text(self) -> str:
        speed = self.speed
        if speed >= 1:
            return f"{speed:.0f} ток/с"
        if speed > 0:
            return f"{speed:.1f} ток/с"
        return "— ток/с"

    def tokens_text(self) -> str:
        """«127 ток» — загальна кількість оброблених токенів цього діалогу."""
        return f"{format_tokens(self.total_tokens)} ток"

    def cache_text(self) -> str:
        if self.prompt_tokens <= 0:
            return "кеш: —"
        return f"кеш: {self.cache_hit_percent:.0f}%"

    def steps_text(self) -> str:
        return f"кроків: {self.step_count}"

    def tools_text(self) -> str:
        return f"інструментів: {self.tool_calls}"

    def fill_text(self, percent_value: float | None = None) -> str:
        value = self.fill_percent if percent_value is None else percent_value
        return f"{value:.0f}%"

    def summary_line(self) -> str:
        """Один рядок як у смузі статистики: кроки · швидкість · токени · кеш."""
        parts = [self.steps_text()]
        if self.tool_calls:
            parts.append(self.tools_text())
        parts.append(self.speed_text())
        if self.total_tokens:
            parts.append(self.tokens_text())
        if self.prompt_tokens:
            parts.append(self.cache_text())
        return " · ".join(parts)

    def detail_tooltip(self) -> str:
        """Докладніше — для підказки при наведенні."""
        lines = [
            f"Кроків (запитів до моделі): {self.step_count}",
            f"Викликів інструментів: {self.tool_calls}",
            f"Вхідні токени (усі кроки): {self.prompt_tokens:,}".replace(",", " "),
            f"Згенеровано токенів: {self.completion_tokens:,}".replace(",", " "),
            f"Взято з кешу: {self.cached_tokens:,}".replace(",", " "),
        ]
        if self.prompt_tokens:
            lines.append(f"Влучання в кеш: {self.cache_hit_percent:.1f}%")
        if self.context_limit:
            lines.append(f"Контекст: {self.last_prompt_tokens:,} з {self.context_limit:,} токенів "
                         f"({self.fill_percent:.0f}%)".replace(",", " "))
        if self.steps:
            lines.append(f"Швидкість генерації: {self.speed:.1f} ток/с")
            lines.append(f"Час роботи: {self.elapsed_text}")
        return "\n".join(lines)


#: Точний підрахунок токенів (задає рушій після завантаження моделі).
#:
#: ЧОМУ НЕ ``contextvars``. Раніше тут був ``ContextVar``, і це ламало саму
#: мету: ``contextvars`` **не успадковуються новим потоком**, а агент і
#: фонові оновлення панелі працюють саме в нових потоках — вони бачили
#: ``None`` і рахували «len/3.5». Заміряно: одне українське речення давало
#: 23 токени замість 89. Тепер звичайна модульна змінна під замком: її
#: видно звідусіль у процесі.
_TOKEN_COUNTER: "Callable[[str], int] | None" = None
_TOKEN_COUNTER_LOCK = threading.Lock()


def set_token_counter(counter: "Callable[[str], int] | None") -> None:
    """Підключити точний tokenizer (``Tokenizer.count``) до статистики."""
    global _TOKEN_COUNTER
    with _TOKEN_COUNTER_LOCK:
        _TOKEN_COUNTER = counter


def estimate_tokens(text: str) -> int:
    """Токени в тексті: точний tokenizer, якщо є, інакше — обережна оцінка.

    Коли модель завантажена у власний рушій, число ТОЧНЕ (``llama_tokenize``).
    Коли ні (хмарний провайдер або стара схема) — та сама евристика, що й
    в ``context_budget``, і про це чесно каже ``estimate_is_exact()``.
    """
    if not text:
        return 0
    counter = _TOKEN_COUNTER
    if counter is not None:
        try:
            exact = int(counter(text))
            if exact > 0:
                return exact
        except Exception:                            # noqa: BLE001
            pass
    # Єдина евристика проєкту замість власної «len/3.5»: інакше та сама
    # фраза рахувалась як 50 токенів в агенті й 23 тут.
    return max(1, context_budget.estimate_tokens(text))


def estimate_is_exact() -> bool:
    """Чи ``estimate_tokens`` зараз повертає точні числа."""
    return _TOKEN_COUNTER is not None


def estimate_messages(messages: Iterable[dict[str, Any]]) -> int:
    """Оцінити розмір списку повідомлень у токенах (для планування)."""
    total = 0
    for message in messages or []:
        total += estimate_tokens(str(message.get("content") or ""))
        total += 4  # службові токени ролі й роздільників
    return total


def parse_usage(result: Any) -> StepStats:
    """Зручний короткий доступ: статистика кроку з результату."""
    return StepStats.from_result(result)


def merge(stats_list: Iterable[ContextStats]) -> ContextStats:
    """Об'єднати статистику кількох діалогів (для загального підсумку)."""
    merged = ContextStats()
    for stats in stats_list:
        for step in stats.steps:
            merged.add(step)
        if stats.context_limit:
            merged.set_limit(stats.context_limit)
    return merged
