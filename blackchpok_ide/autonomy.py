"""Свобода дій моделі: скільки кроків і коли можна діяти без перепитування.

Навіщо окремий шар, а не «більше кроків у налаштуваннях». Реальні скарги
на локального агента мають дві різні причини, і змішувати їх неправильно:

1. **Замало кроків.** Модель будує сайт із шести файлів, а ліміт — 8 кроків:
   на п'ятому вона ще пише CSS, і робота обривається на півдорозі.
2. **Забагато перепитувань.** Агент зупиняється й питає «яку саме форму
   зробити?», хоч у проєкті вже є зразок, а користувач сказав «зроби як
   той файл». Людина чекає, робота стоїть.

Ці дві речі керуються ОДНИМ рівнем свободи, але не тим самим числом:
«двигун» (дозволи на файли й команди) лишається в :mod:`permissions` і
ніколи не змінюється цим модулем. Тут — лише бюджет кроків і право
вирішувати самому.

Рівні:

===============  ==============  ===========================  =============
рівень           кроків (+N)     питати перед припущенням     коли доречний
===============  ==============  ===========================  =============
``cautious``     0               так                          чужі дані, складні правки
``balanced``     2               так                          типовий режим
``autonomous``   8               ні                           довге будівництво
``explorer``     16              ні                           дослідження, великі рефакторинги
===============  ==============  ===========================  =============

Важливо: рівень НЕ робить нічого незворотного. Запис у системні теки,
публікація на GitHub і небезпечні команди однаково перевіряються
:mod:`permissions`, а «не питати» стосується лише уточнень щодо
формулювання задачі — агент діє й каже, що припустив.

Модуль не тягне tkinter: правило — чиста функція, її легко перевірити.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "AUTONOMOUS",
    "BALANCED",
    "CAUTIOUS",
    "EXPLORER",
    "LEVELS",
    "Policy",
    "apply",
    "asks_before_assume",
    "get",
    "hint_for",
    "keys",
    "label_for",
    "labels",
    "normalise",
    "prompt_hint",
    "step_bonus",
]

CAUTIOUS = "cautious"
BALANCED = "balanced"
AUTONOMOUS = "autonomous"
EXPLORER = "explorer"

LEVELS: tuple[str, ...] = (CAUTIOUS, BALANCED, AUTONOMOUS, EXPLORER)

#: Типовий рівень. «Збалансований» додає два кроки (найчастіша нестача
#: в реальних прогонах: 8 кроків на 5–7 файлів) і лишає уточнення —
#: користувач не має раптом отримати агента, який вирішує за нього.
DEFAULT_LEVEL = BALANCED


@dataclass(frozen=True)
class Policy:
    """Що дозволяє конкретний рівень свободи."""

    key: str
    label: str
    hint: str
    icon: str
    #: Скільки кроків додається до ліміту з налаштувань/режиму.
    extra_steps: int
    #: Чи питати уточнення перед дією (False — діяти з припущенням).
    ask_first: bool
    #: Підказка моделі — її бачить LLM у системному промпті.
    prompt: str


_POLICIES: tuple[Policy, ...] = (
    Policy(
        key=CAUTIOUS,
        label="Обережно",
        hint="Діяти рівно за проханням: уточнювати незрозуміле, зайвих кроків не брати.",
        icon="🛡",
        extra_steps=0,
        ask_first=True,
        prompt=("Свобода дій: ОБЕРЕЖНО. Роби лише те, що прямо попросили. "
                "Якщо у формулюванні є неоднозначність, яка може зіпсувати "
                "дані, — постав одне коротке уточнення замість здогадки."),
    ),
    Policy(
        key=BALANCED,
        label="Збалансовано",
        hint="Два додаткові кроки; уточнення лише там, де помилка коштує дорого.",
        icon="⚖",
        extra_steps=2,
        ask_first=True,
        prompt=("Свобода дій: ЗБАЛАНСОВАНО. Доводь розпочате до кінця сам. "
                "Уточнюй лише тоді, коли без відповіді можна зіпсувати дані "
                "або видалити щось чуже. В іншому разі дій і коротко скажи, "
                "що саме припустив."),
    ),
    Policy(
        key=AUTONOMOUS,
        label="Автономно",
        hint="Вісім додаткових кроків; агент сам вирішує дрібні неоднозначності.",
        icon="⚡",
        extra_steps=8,
        ask_first=False,
        prompt=("Свобода дій: АВТОНОМНО. Виконуй завдання до кінця, не "
                "зупиняючись на дрібних уточненнях: приймай розумне рішення, "
                "виконуй і в підсумку переліч, що припустив. Питай лише про "
                "незворотні дії (видалення, публікація, платні сервіси)."),
    ),
    Policy(
        key=EXPLORER,
        label="Дослідник",
        hint="Шістнадцять додаткових кроків: агент сам шукає шлях і перевіряє себе.",
        icon="🜁",
        extra_steps=16,
        ask_first=False,
        prompt=("Свобода дій: ДОСЛІДНИК. Сам обирай шлях до мети: досліджуй "
                "проєкт, пробуй, перевіряй результат і виправляй себе. Не "
                "питай дозволу на окремі кроки — питай лише про незворотні "
                "дії. Наприкінці дай короткий звіт: що зробив, що перевірив, "
                "що лишилось."),
    ),
)

_BY_KEY: dict[str, Policy] = {}
for _policy in _POLICIES:
    _BY_KEY[_policy.key] = _policy

_ALIASES: dict[str, str] = {
    "обережно": CAUTIOUS, "обережний": CAUTIOUS, "safe": CAUTIOUS,
    "careful": CAUTIOUS, "low": CAUTIOUS, "0": CAUTIOUS,
    "збалансовано": BALANCED, "звичайно": BALANCED, "normal": BALANCED,
    "default": BALANCED, "medium": BALANCED, "1": BALANCED,
    "автономно": AUTONOMOUS, "автономний": AUTONOMOUS, "auto": AUTONOMOUS,
    "high": AUTONOMOUS, "2": AUTONOMOUS,
    "дослідник": EXPLORER, "досліджуй": EXPLORER, "explore": EXPLORER,
    "max": EXPLORER, "maximum": EXPLORER, "3": EXPLORER,
}


def normalise(key: str) -> str:
    """Привести назву рівня до відомого ключа (невідоме → типовий)."""
    value = (key or "").strip().lower().replace("-", "_").replace(" ", "_")
    if value in _BY_KEY:
        return value
    return _ALIASES.get(value, DEFAULT_LEVEL)


def get(key: str) -> Policy:
    return _BY_KEY[normalise(key)]


def keys() -> list[str]:
    return list(LEVELS)


def label_for(key: str) -> str:
    return get(key).label


def hint_for(key: str) -> str:
    return get(key).hint


def labels() -> list[tuple[str, str]]:
    """Пари ``(ключ, підпис)`` для випадаючого списку в налаштуваннях."""
    return [(policy.key, f"{policy.icon}  {policy.label}") for policy in _POLICIES]


def step_bonus(key: str) -> int:
    """Скільки кроків додає рівень (0 для «обережно»)."""
    return max(0, int(get(key).extra_steps))


def asks_before_assume(key: str) -> bool:
    """Чи мусить агент уточнювати перед дією з припущенням."""
    return bool(get(key).ask_first)


def prompt_hint(key: str) -> str:
    """Підказка моделі — додається до системного промпту."""
    return get(key).prompt


def apply(settings: Any, agent: Any, key: str) -> Policy:
    """Застосувати рівень до налаштувань і живого агента.

    Дозволи на файли й команди тут **не** змінюються: вони належать
    :mod:`permissions` і :mod:`modes`. Змінюється лише бюджет кроків і те,
    чи питати уточнення.
    """
    policy = get(key)
    try:
        settings.agent.autonomy = policy.key
    except AttributeError:
        pass
    if agent is not None:
        try:
            agent.autonomy = policy.key
            agent.extra_steps = policy.extra_steps
        except AttributeError:
            pass
    return policy


def describe(key: str) -> str:
    """Один рядок для рядка стану: «⚡ Автономно — вісім додаткових кроків»."""
    policy = get(key)
    return f"{policy.icon} {policy.label} (+{policy.extra_steps} кроків)"
