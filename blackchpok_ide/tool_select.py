"""Автоматичний роутер інструментів: моделі дають ЛИШЕ потрібні.

Навіщо окремий модуль. Донедавну модель отримувала майже весь набір схем:

* повний режим — усі 48–69 схем. Повна схема коштує ≈110–350 токенів, тож
  це 8 000–20 000 токенів на КОЖЕН запит. Для локальної моделі з вікном
  8192 це більше за все вікно, а для хмари — постійні витрати на те, чим
  вона не користується;
* «лінивий» режим (``tool_lazy``) теж брав ЯДРО з 12 інструментів плюс усі
  зовнішні — незалежно від того, що просить користувач.

Вимога користувача: «автоматичний роутер інструментів, щоб не брало всі
інструменти без необхідності, а тільки необхідні при виконанні задачі».

Як це працює тут:

1. **Розпізнаємо НАМІР задачі** з тексту запиту (сам текст, намір із
   ``intent_engine``, підказки ``tool_router``).
2. **Беремо профіль набору**: для розмови — мінімум, для правки коду —
   читання/запис/перевірка, для запуску — команда й тести, для огляду —
   лише читання.
3. **Додаємо ядро безпеки**: кілька інструментів, без яких агент не
   почне роботу (нинішній файл, список теки), і контроль реєстру
   (``find_tools``/``load_tools``/``run_tool``) — саме він гарантує, що
   решта інструментів лишається ДОСЯЖНОЮ, навіть якщо не показана.

Останній пункт принциповий: економія не має перетворюватись на «модель не
бачить потрібного інструмента й не може його знайти». Контроль реєстру
дає шлях до будь-якого інструмента в один крок.

Модуль чистий: без tkinter, без мережі, без стану між викликами.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "CORE_SAFETY",
    "CONTROL",
    "PROFILES",
    "Selection",
    "profile_for",
    "select_names",
]


#: Інструменти керування реєстром. Їх показуємо ЗАВЖДИ: вони дають доступ
#: до решти набору, тому економія тут коштувала б більше, ніж економила.
CONTROL: tuple[str, ...] = ("find_tools", "load_tools", "run_tool")

#: Мінімум, без якого агент не починає роботу: побачити теку й прочитати
#: файл. Це дешево (2 схеми) і знімає цілий клас «модель не знає, де вона».
CORE_SAFETY: tuple[str, ...] = ("list_dir", "read_file")


@dataclass(frozen=True)
class Profile:
    """Набір інструментів під конкретний тип задачі."""

    key: str
    label: str
    tools: tuple[str, ...]
    #: Чи можна доповнювати набір інструментами з тексту запиту.
    widen: bool = True


#: Профілі за наміром. Порядок у кожному — від найпотрібнішого.
PROFILES: dict[str, Profile] = {
    # Розмова, привітання, питання про можливості: інструменти майже не
    # потрібні. Але модель МАЄ могти подивитись проєкт, якщо захоче —
    # тому ядро безпеки й контроль реєстру лишаються.
    "converse": Profile("converse", "розмова", ()),
    # Огляд проєкту: тільки читання.
    "inspect": Profile("inspect", "огляд", (
        "search_text", "find_files", "project_tree", "git_status")),
    # Правка наявного коду.
    "edit": Profile("edit", "правка коду", (
        "write_file", "edit_file", "append_file", "search_text",
        "python_check", "git_diff")),
    # Створення нового.
    "create": Profile("create", "створення", (
        "write_file", "append_file", "list_dir", "project_tree",
        "python_check")),
    # Запуск команд і тестів.
    "run": Profile("run", "запуск", (
        "run_command", "python_check", "list_dir")),
    # Пошук і дослідження.
    "research": Profile("research", "дослідження", (
        "search_text", "find_files", "run_command")),
    # Виправлення помилки.
    "debug": Profile("debug", "лагодження", (
        "run_command", "edit_file", "write_file", "search_text",
        "python_check")),
    # Невідомий намір: ПОВНЕ ядро роботи з кодом. Це найдорожчий профіль,
    # і це навмисно — краще віддати більше схем, ніж позбавити модель
    # можливості виконати задачу (див. коментар до ``_FALLBACK``).
    "unknown": Profile("unknown", "невідомо (повне ядро)", (
        "write_file", "edit_file", "append_file", "list_dir", "search_text",
        "find_files", "run_command", "project_tree", "python_check",
        "git_status", "git_diff")),
}

#: Коли намір невідомий — беремо ПОВНЕ ядро роботи з кодом.
#:
#: Раніше тут стояв ``inspect`` (лише читання), і це було небезпечно:
#: запит, який евристика не розпізнала («онови конфіг»), лишався без
#: ``write_file`` — модель фізично не могла виконати завдання й просила
#: ``load_tools`` замість роботи. Невідоме має давати БІЛЬШЕ можливостей,
#: а не менше: економія не варта зламаної задачі.
_FALLBACK = "unknown"

#: Слова, за якими набір РОЗШИРЮЄТЬСЯ вище профілю. Ключ — фрагмент
#: запиту, значення — інструменти, які тоді справді потрібні.
_EXTRA_BY_WORD: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("тест", "тести", "pytest", "unittest"), ("run_command", "python_check")),
    (("git", "коміт", "commit", "push", "github"), ("git_status", "git_diff")),
    (("скріншот", "знімок", "екран", "screenshot"),
     ("app_screenshot", "capture_screen", "window_screenshot")),
    (("браузер", "сторінк", "сайт", "url", "http"),
     ("web_screenshot", "web_inspect", "browser_open")),
    (("пошук", "знайди", "search", "google"), ("search_web",)),
    (("пам'ять", "памят", "згадай", "memory"), ("memory_search", "memory_save")),
    (("rag", "знання", "документ"), ("rag_search", "rag_index")),
    (("diff", "змін", "різниц"), ("git_diff",)),
    (("файл", "теку", "папк", "структур"),
     ("list_dir", "project_tree", "find_files")),
)


@dataclass
class Selection:
    """Результат вибору: імена інструментів і ЧОМУ саме вони."""

    names: list[str] = field(default_factory=list)
    profile: str = ""
    reason: str = ""

    def __len__(self) -> int:
        return len(self.names)


def _intent_of(text: str, intent_type: str = "") -> str:
    """Намір задачі: спершу готовий, потім — власна евристика.

    ``intent_type`` передає викликач (із ``intent_engine``), бо там уже є
    повний розбір. Евристика тут — лише запасний шлях, коли наміру немає.
    """
    known = str(intent_type or "").strip().lower()
    if known in PROFILES:
        return known
    low = (text or "").lower()
    # Правка наявного — найконкретніше, тому перевіряємо першою.
    if re.search(r"\b(виправ|полагодь|лагодь|fix|debug|не працює|падає)", low):
        return "debug"
    if re.search(r"\b(зміни|змінити|онови|додай|встав|перейменуй|редагуй)", low):
        return "edit"
    if re.search(r"\b(створи|створити|напиши|зроби|згенеруй|create|generate)", low):
        return "create"
    if re.search(r"\b(запусти|запустити|виконай|прожени|run|виконати)", low):
        return "run"
    if re.search(r"\b(перевір|оглянь|проаналізуй|покажи|де знаход)", low):
        return "inspect"
    if re.search(r"\b(знайди|пошукай|search|досліди)", low):
        return "research"
    return ""


def _mentions(text: str) -> tuple[str, ...]:
    """Інструменти, які згадує САМ текст запиту (найсильніший сигнал)."""
    low = (text or "").lower()
    found: list[str] = []
    for words, tools in _EXTRA_BY_WORD:
        if any(word in low for word in words):
            found.extend(tools)
    return tuple(dict.fromkeys(found))


def _hinted(hints: Iterable[Any]) -> tuple[str, ...]:
    """Інструменти, які порадив ``tool_router`` (готові підказки)."""
    names: list[str] = []
    for hint in hints or ():
        name = str(getattr(hint, "tool", "") or "")
        if name:
            names.append(name)
    return tuple(dict.fromkeys(names))


def profile_for(*, text: str = "", intent_type: str = "",
                hints: Sequence[Any] = ()) -> Profile:
    """Профіль набору для цього запиту."""
    key = _intent_of(text, intent_type)
    if key not in PROFILES:
        key = _FALLBACK
    return PROFILES[key]


def select_names(*, available: Iterable[str], text: str = "",
                 intent_type: str = "", hints: Sequence[Any] = (),
                 loaded: Iterable[str] = (),
                 previous: Iterable[str] = (),
                 limit: int = 0) -> Selection:
    """Вибрати імена інструментів для ЦЬОГО ходу.

    ``available`` — усе, що взагалі існує в реєстрі. Функція не вигадує
    назв: вона лише звужує наявне.

    ``loaded`` — те, що модель завантажила сама (``load_tools``); воно
    лишається, інакше модель «втрачала б» щойно відкритий інструмент.

    ``previous`` — набір попереднього ходу. Кілька інструментів, які вже
    були в роботі, лишаємо: завдання складається з кількох кроків, і
    перемикання набору на кожному кроці змушувало б модель заново
    «відкривати» те саме.
    """
    known = {str(name) for name in available if str(name)}
    profile = profile_for(text=text, intent_type=intent_type, hints=hints)
    chosen: list[str] = []

    def add(names: Iterable[str]) -> None:
        for name in names:
            if name in known and name not in chosen:
                chosen.append(name)

    add(profile.tools)
    if profile.widen:
        add(_mentions(text))
        add(_hinted(hints))
    add(loaded)
    add(previous)
    # Ядро й контроль — завжди, після профільного набору (він важливіший
    # для вигляду списку, але не для доступності).
    add(CORE_SAFETY)
    add(CONTROL)
    if limit > 0 and len(chosen) > limit:
        # Обрізаємо РІДКІСНІ, а не ядро чи контроль: без них агент усе ще
        # працює, без ``run_tool`` — ні.
        keep = [name for name in chosen if name in CONTROL or name in CORE_SAFETY]
        rest = [name for name in chosen if name not in keep]
        chosen = rest[: max(0, limit - len(keep))] + keep
    reason = f"профіль «{profile.label}»: {len(chosen)} інструментів"
    return Selection(names=chosen, profile=profile.key, reason=reason)
