"""Адаптер під конкретну модель: що вона вміє й як з нею говорити.

Моделі в IDE різні: вбудований GGUF на 4k контексту, локальний сервер із
нативним function calling, хмарний Anthropic, Gemini. Один і той самий
промпт і один і той самий формат виклику для всіх — це гарантоване
«десь працює, а десь ні».

Цей модуль будує **профіль** моделі й каже решті коду, що робити:

* ``native_tools`` — використовувати нативний ``tools`` у запиті;
* ``text_protocol`` — дописати в промпт інструкцію викликати інструменти
  текстом (і розібрати його), бо native не підтримується;
* ``compact_prompt`` — вікно мале, повний промпт не влізе;
* ``max_tools`` — скільки схем показувати (малі моделі плутаються);
* ``strict_arguments`` — чи можна вимагати точних аргументів.

Профіль будується з того, що реально відомо: назви моделі, стилю
провайдера й розміру вікна. Нічого не «вгадуємо» про невідоме — беремо
безпечний варіант і кажемо про це.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import model_caps
from . import provider_adapters

__all__ = [
    "ModelProfile",
    "profile_for",
    "text_tool_protocol",
]


#: Моделі, які надійно викликають інструменти нативно.
_NATIVE_TOOL_FAMILIES: tuple[str, ...] = (
    "qwen2.5", "qwen3", "qwen2", "hermes", "mixtral", "mistral-small",
    "mistral-nemo", "llama-3.1", "llama-3.2", "llama-3.3", "llama3.1",
    "llama3.2", "llama3.3", "deepseek", "granite", "command-r", "firefunction",
    "functionary", "phi-4", "gemma-3", "gemma3", "glm-4", "glm-5", "gpt-4",
    "gpt-5", "claude", "gemini", "o1", "o3", "o4", "vikhr", "t-lite",
    "ministral", "solar", "yi-", "internlm",
)

#: Моделі, які майже завжди плутаються зі схемами (малі й «розмовні»).
_WEAK_TOOL_MARKERS: tuple[str, ...] = (
    "tinyllama", "1.5b", "0.5b", "smollm", "phi-2", "gemma-2b", "qwen2-0.5b",
    "qwen2.5-0.5b", "qwen2.5-1.5b", "-1b", "-0.6b", "stories", "chat-3.5",
)

#: Скільки схем показувати моделі за замовчуванням.
DEFAULT_MAX_TOOLS = 40
WEAK_MAX_TOOLS = 14

#: Поріг вікна, під яким вмикається стислий промпт.
#:
#: Збігається з ``agent.COMPACT_PROMPT_LIMIT``: там промпт замінюється на
#: короткий, і профіль має казати те саме, інакше рішення розійдуться.
COMPACT_WINDOW = 12_000


@dataclass(frozen=True)
class ModelProfile:
    """Що дозволено й доречно для конкретної моделі."""

    model: str = ""
    style: str = "openai"
    #: Чи є нативне function calling (тоді схеми йдуть у ``tools``).
    native_tools: bool = True
    #: Чи треба пояснювати текстом, як викликати інструмент.
    text_protocol: bool = False
    #: Чи можна вимагати точних аргументів (strict).
    strict_arguments: bool = True
    #: Стислий системний промпт (мале вікно).
    compact_prompt: bool = False
    #: Скільки схем показувати моделі.
    max_tools: int = DEFAULT_MAX_TOOLS
    #: Вікно контексту (0 = невідоме).
    context_window: int = 0
    #: Чи підтримує модель міркування (reasoning).
    reasoning: bool = False
    #: Чи розуміє зображення.
    vision: bool = False
    #: Причина такого рішення — для журналу й для чесного пояснення.
    note: str = ""

    def describe(self) -> str:
        """Один рядок для журналу (без технічного шуму)."""
        parts = [f"модель «{self.model or 'невідома'}»"]
        parts.append("нативні інструменти" if self.native_tools
                     else "інструменти текстом")
        if self.compact_prompt:
            parts.append("стислий промпт")
        if self.max_tools < DEFAULT_MAX_TOOLS:
            parts.append(f"до {self.max_tools} інструментів")
        if self.reasoning:
            parts.append("міркування")
        if self.vision:
            parts.append("зображення")
        return " · ".join(parts)


def _matches(blob: str, markers: tuple[str, ...]) -> str:
    for marker in markers:
        if marker in blob:
            return marker
    return ""


def profile_for(
    model: str,
    base_url: str = "",
    *,
    context_window: int = 0,
) -> ModelProfile:
    """Побудувати профіль моделі з назви, адреси й розміру вікна.

    Невідома модель не отримує «поганих» налаштувань навмання: вважаємо,
    що нативні інструменти є (так працює більшість сучасних серверів), але
    додаємо текстову підказку формату — вона нешкідлива й підвищує шанс
    правильного виклику.
    """
    name = (model or "").strip()
    low = name.lower()
    try:
        style = provider_adapters.detect_style(base_url or "")
    except Exception:                                   # noqa: BLE001
        style = "openai"

    caps = model_caps.detect(name=name)
    weak = _matches(low, _WEAK_TOOL_MARKERS)
    native_marker = _matches(low, _NATIVE_TOOL_FAMILIES)
    embedded = style == provider_adapters.EMBEDDED

    # Малі моделі: native може бути, але схем багато — плутаються.
    max_tools = WEAK_MAX_TOOLS if weak else DEFAULT_MAX_TOOLS
    native_tools = True
    text_protocol = False
    note = ""

    if weak:
        native_tools = False
        text_protocol = True
        note = f"мала модель («{weak}») — інструменти текстом, менше схем"
    elif native_marker:
        note = f"родина «{native_marker}» — нативний виклик"
    elif not caps.has(model_caps.TOOLS):
        # Профіль нічого не знає про інструменти — підстрахуєм��сь текстом.
        text_protocol = True
        note = "можливості невідомі — додано текстову підказку формату"
    else:
        note = "нативний виклик за родиною моделі"

    compact = bool(context_window and context_window <= COMPACT_WINDOW)
    strict = not weak and native_tools

    return ModelProfile(
        model=name,
        style=style,
        native_tools=native_tools,
        text_protocol=text_protocol,
        strict_arguments=strict,
        compact_prompt=compact,
        max_tools=max_tools,
        context_window=int(context_window or 0),
        reasoning=caps.has(model_caps.REASONING),
        vision=caps.has(model_caps.VISION),
        note=note,
    )


def text_tool_protocol(tool_names: list[str] | tuple[str, ...] = ()) -> str:
    """Текстова інструкція формату виклику для моделей без native.

    Показуємо РІВНО один формат, а не три альтернативи: коли модель
    бачить вибір, вона змішує варіанти й виклик не розбирається.
    """
    names = ", ".join(sorted(tool_names)[:12]) or "read_file, list_dir"
    return (
        "Як викликати інструмент (у тебе немає нативного виклику функцій):\n"
        "Напиши рівно один JSON-об'єкт у такому вигляді й нічого більше:\n"
        '{"name": "<інструмент>", "arguments": { ... }}\n'
        f"Доступні інструменти: {names}.\n"
        "Не додавай пояснень навколо JSON. Після результату інструмента "
        "продовжуй роботу або дай відповідь звичайним текстом."
    )
