"""Режими роботи агента: Chat, Agent, Code, Plan, Tools.

Кожен режим — це не лише підпис у смузі: він змінює **реальні** параметри
виконання, які вже є в системі.

============================  ==========  ===========  =========  ==============
режим                         дозволи     кроки         tools      підказка
============================  ==========  ===========  =========  ==============
``chat``                      read_only   1            ні         відповідати текстом
``agent``                     workspace   з налаштувань так        як є
``code``                      workspace   12           так        правити файли
``plan``                      read_only   4            так (чит.) спершу план
``tools``                     workspace   12           так        кликати інструменти
============================  ==========  ===========  =========  ==============

Дозволи перевіряє :mod:`permissions` у ``AgentRunner.call_tool``, ліміт кроків —
цикл ``AgentRunner._loop``, а підказкаMode додається до системного промпту через
``AgentRunner.start(..., extra_prompt=...)``. Тобто перемикання режиму справді
міняє те, що агент робить, а не тільки те, як він виглядає.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import permissions

CHAT = "chat"
AGENT = "agent"
CODE = "code"
PLAN = "plan"
TOOLS = "tools"


@dataclass(frozen=True)
class AgentMode:
    """Один режим роботи з реальними параметрами виконання."""

    key: str
    label: str
    icon: str
    hint: str
    permission: str
    max_steps: int
    use_tools: bool
    prompt: str


MODES: tuple[AgentMode, ...] = (
    AgentMode(
        key=CHAT,
        label="Чат",
        icon="◌",
        hint="Звичайний діалог: агент відповідає текстом і не чіпає файли.",
        permission=permissions.READ_ONLY,
        max_steps=1,
        use_tools=False,
        prompt=("Режим «Чат». Відповідай текстом, без викликів інструментів і без "
                "змін файлів. Якщо для відповіді потрібен код проєкту — попроси "
                "перемкнути режим на «Агент» або «Код»."),
    ),
    AgentMode(
        key=AGENT,
        label="Агент",
        icon="◈",
        hint="Автономне виконання: читає файли, вносить зміни, перевіряє результат.",
        permission=permissions.WORKSPACE,
        max_steps=0,          # 0 = взяти з налаштувань (agent.max_steps)
        use_tools=True,
        prompt="",
    ),
    AgentMode(
        key=CODE,
        label="Код",
        icon="⟨⟩",
        hint="Правки коду: спершу прочитати, потім змінити файл і перевірити.",
        permission=permissions.WORKSPACE,
        max_steps=12,
        use_tools=True,
        prompt=("Режим «Код». Працюй із кодом: спершу прочитай файл інструментом "
                "read_file, зміни його через edit_file або write_file, потім "
                "перевір синтаксис (python_check) або запусти тести. У фінальній "
                "відповіді переліч змінені файли."),
    ),
    AgentMode(
        key=PLAN,
        label="План",
        icon="☰",
        hint="Планування й аналіз: файли не змінюються, спершу узгоджуємо план.",
        permission=permissions.READ_ONLY,
        max_steps=4,
        use_tools=True,
        prompt=("Режим «План». Спершу досліди проєкт (read_file, list_dir, "
                "search_text, project_tree) і склади детальний план кроками. "
                "Файли НЕ змінюй — дочекайся підтвердження."),
    ),
    AgentMode(
        key=TOOLS,
        label="Інструменти",
        icon="⌘",
        hint="Робота з інструментами: MCP-сервери, пошук, команди, RAG.",
        permission=permissions.WORKSPACE,
        max_steps=12,
        use_tools=True,
        prompt=("Режим «Інструменти». Активно використовуй доступні інструменти "
                "(файли, пошук, команди, MCP, RAG) і показуй результат дії, а не "
                "опис того, що можна зробити."),
    ),
)

_BY_KEY = {mode.key: mode for mode in MODES}
DEFAULT_MODE = AGENT


def get(key: str) -> AgentMode:
    """Режим за ключем (невідомий ключ → типовий режим)."""
    return _BY_KEY.get((key or "").strip().lower(), _BY_KEY[DEFAULT_MODE])


def normalise(key: str) -> str:
    return get(key).key


def keys() -> list[str]:
    return [mode.key for mode in MODES]


def label_for(key: str) -> str:
    return get(key).label


def hint_for(key: str) -> str:
    return get(key).hint


#: Скільки кроків брати, коли режим не задає власного ліміту.
DEFAULT_MAX_STEPS = 8

#: Ліміт кроків, який користувач задав у налаштуваннях (до застосування
#: режиму). Режим не має права переписувати це значення назавжди.
_BASE_STEPS = {"value": 0}


def base_max_steps(settings: Any) -> int:
    """Ліміт кроків із налаштувань (без урахування поточного режиму)."""
    if not _BASE_STEPS["value"]:
        try:
            _BASE_STEPS["value"] = max(1, int(settings.agent.max_steps))
        except (AttributeError, TypeError, ValueError):
            _BASE_STEPS["value"] = DEFAULT_MAX_STEPS
    return int(_BASE_STEPS["value"])


def remember_base_steps(value: int) -> None:
    """Запам'ятати нове «базове» значення, коли його змінив користувач."""
    try:
        _BASE_STEPS["value"] = max(1, int(value))
    except (TypeError, ValueError):
        return


def apply(settings: Any, agent: Any, key: str) -> AgentMode:
    """Застосувати режим до живого агента.

    Ліміт кроків режиму діє **лише доки режим активний**: базове значення з
    налаштувань не переписується, інакше перехід у «Код» назавжди змінював
    би глобальне налаштування. Дозволи ж — це частина режиму, тож вони
    пишуться в налаштування і зберігаються між запусками.
    """
    mode = get(key)
    base = base_max_steps(settings)
    try:
        settings.agent.permission_mode = mode.permission
        settings.agent.mode = mode.key
    except AttributeError:
        pass
    if agent is not None:
        try:
            agent.permission_mode = mode.permission
            agent.tools_enabled = mode.use_tools
            # Режим задає СВІЙ ліміт кроків, не чіпаючи налаштувань.
            agent.max_steps_override = max(0, int(mode.max_steps))
            agent.mode_prompt = mode.prompt
        except (AttributeError, TypeError, ValueError):
            pass
    return mode


def mode_prompt(settings: Any, key: str) -> str:
    """Підказка режиму — те, що додається до системного промпту запиту."""
    return get(key).prompt


__all__ = [
    "AGENT", "AgentMode", "CHAT", "CODE", "DEFAULT_MAX_STEPS", "DEFAULT_MODE", "MODES",
    "PLAN", "TOOLS", "apply", "base_max_steps", "get", "hint_for", "keys",
    "label_for", "mode_prompt", "normalise", "remember_base_steps",
]
