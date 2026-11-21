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
        hint="Розмова; інструменти — на розсуд моделі.",
        # ── ПОВНИЙ ДОСТУП У ВСІХ РЕЖИМАХ (21.11.2026) ─────────────────────
        # Вимога користувача: «лиш тільки повний доступ для агента!
        # Прибери перемикач!». Раніше «Чат» був ``READ_ONLY``, і модель
        # фізично не могла створити файл: вона просила перемкнути режим
        # замість того, щоб зробити роботу.
        permission=permissions.FULL,
        max_steps=4,
        use_tools=True,
        # ── ЧОМУ ПІДКАЗКИ БІЛЬШЕ НЕМА (20.11.2026) ────────────────────────
        # Тут стояло: «Режим «Чат». Відповідай текстом, без викликів
        # інструментів і без змін файлів… попроси перемкнути режим на
        # Агент». Цей текст ішов моделі в системному промпті й ЗАБОРОНЯВ
        # їй працювати: на питання «привіт» агент відповідав вигаданим
        # описом проєкту («у проєкті досі є декоративний текст —
        # tests/test_greeting.py…»), бо мусив відповісти словами замість
        # подивитись файли. Користувач просив прямо: «дай максимально
        # свободи для локальних і хмарних моделей і максимум
        # самовирішування, а не жорсткої прив'язки до хардтексту».
        #
        # Тепер режим задає лише ДОЗВІЛ (читання) і типовий ліміт кроків;
        # чи викликати інструмент — вирішує сама модель. Читання файлів
        # безпечне й не потребує дозволу на запис.
        prompt="",
    ),
    AgentMode(
        key=AGENT,
        label="Агент",
        icon="◈",
        hint="Автономне виконання: читає файли, вносить зміни, перевіряє результат.",
        permission=permissions.FULL,
        max_steps=0,          # 0 = взяти з налаштувань (agent.max_steps)
        use_tools=True,
        prompt="",
    ),
    AgentMode(
        key=CODE,
        label="Код",
        icon="⟨⟩",
        hint="Правки коду: спершу прочитати, потім змінити файл і перевірити.",
        permission=permissions.FULL,
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
        permission=permissions.FULL,
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
        permission=permissions.FULL,
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


# ── АВТОМАТИЧНИЙ ВИБІР РЕЖИМУ ─────────────────────────────────────────────
#
# Користувач не має обирати режим вручну: він пише завдання, а не «режим
# роботи». Ручний перемикач змушував його вгадувати, чи це «Чат», «Код» чи
# «План», і найчастіше він лишався в «Чат» — тоді агент відповідав текстом
# замість того, щоб працювати з файлами.
#
# Тепер режим визначається з самого повідомлення наявним рушієм намірів
# (:func:`intent_engine.classify_message`), а не з віджета. Це стосується
# ОДНАКОВО локальних і хмарних моделей: вибір не залежить від того, хто
# виконує запит.

#: Який режим відповідає типу наміру.
_INTENT_MODES: dict[str, str] = {
    "converse": CHAT,     # балачка, подяка, питання-відповідь
    "clarify": CHAT,      # відповідь на наше уточнення
    "revise": AGENT,      # зміна вимог — далі працюємо
    "create": AGENT,      # створити функціонал
    "edit": CODE,         # правити наявний код
    "debug": CODE,        # «не працює» → знайти й виправити
    "run": AGENT,         # запустити команду
    "test": AGENT,        # прогнати перевірки
}

#: Режим, коли намір визначити не вдалося (найбезпечніший «робочий»).
_FALLBACK = AGENT


def auto_mode(text: str, *, previous: list[str] | None = None,
              learner: Any = None, veto: Any = None) -> str:
    """Режим, що відповідає змісту повідомлення.

    Порожнє або суто розмовне повідомлення → ``chat`` (агент не чіпає
    файли). Будь-яке завдання → ``agent``/``code``. Помилка визначення не
    має ламати хід: тоді беремо ``agent``.

    ── САМОНАВЧАННЯ НА ВИБОРІ РЕЖИМУ ─────────────────────────────────────
    ``learner`` — :class:`mode_learning.ModeLearner`. Сталі правила іноді
    помиляються на живій фразі, і раніше помилка ніде не осідала: агент
    робив не те, що просили, і наступного разу повторював те саме. Тепер
    вивчене правило перекриває сталу класифікацію, а ``veto`` не дає
    навчанню зробити агента небезпечнішим (напр. обрати «Чат» там, де
    запит вимагає інструментів).
    """
    body = (text or "").strip()
    if not body:
        return CHAT
    kind = _intent_of(body, previous=previous)
    chosen = _INTENT_MODES.get(str(kind or ""), _FALLBACK)
    if learner is None:
        return chosen
    try:
        corrected, rule = learner.apply(body, chosen, veto=veto)
    except Exception:  # noqa: BLE001 - навчання не має зривати запит
        return chosen
    if rule is None or corrected not in _BY_KEY:
        return chosen
    return corrected


def _intent_of(body: str, *, previous: list[str] | None = None) -> str:
    """Тип наміру з тексту; ``""`` — якщо визначити не вдалося."""
    try:
        from . import intent_engine

        return str(intent_engine.classify_message(body, previous=previous) or "")
    except Exception:  # noqa: BLE001 - визначення не має зривати запит
        return ""



def auto_apply(settings: Any, agent: Any, text: str,
               *, previous: list[str] | None = None,
               learner: Any = None, veto: Any = None) -> AgentMode:
    """Визначити режим із повідомлення й застосувати його до агента."""
    return apply(settings, agent,
                 auto_mode(text, previous=previous, learner=learner, veto=veto))


def safe_mode(mode: str, text: str) -> bool:
    """Запобіжник навчання: чи БЕЗПЕЧНО цей режим для цього тексту.

    Навчання виправляє помилки, але не має права зробити агента менш
    здатним: якщо запит вимагає фактів про проєкт (правило доказів,
    :func:`evidence.needs_tools_for`), режим БЕЗ інструментів заборонений —
    інакше вивчене правило «на цю фразу відповідай текстом» знову привело
    б до вигаданої відповіді замість фактів.

    ── ЩО ЗМІНИЛОСЬ 20.11.2026 ───────────────────────────────────────────
    Перевірка йде за :attr:`AgentMode.use_tools`, а не за назвою режиму.
    Раніше «Чат» не мав інструментів, і саме він був єдиним небезпечним
    вибором. Тепер «Чат» теж дає інструменти (модель сама вирішує, чи
    кликати), тож усі наявні режими безпечні для запитів про факти — і
    запобіжник лишається чинним для будь-якого майбутнього режиму без
    інструментів.
    """
    if get(mode).use_tools:
        return False
    try:
        from . import evidence

        return bool(evidence.needs_tools_for(text))
    except Exception:  # noqa: BLE001 - перевірка не має ламати вибір
        return False



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
    "PLAN", "TOOLS", "apply", "auto_apply", "auto_mode", "base_max_steps", "get",
    "hint_for", "keys", "label_for", "mode_prompt", "normalise",
    "remember_base_steps", "safe_mode",
]
