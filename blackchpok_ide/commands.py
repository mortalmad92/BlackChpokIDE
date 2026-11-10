"""Єдиний реєстр команд IDE: меню, шапка й палітра беруть їх ЗВІДСИ.

Навіщо це окремий модуль. Раніше кожна можливість жила у двох-трьох місцях
одночасно: пункт у меню, рядок у ``_command_items`` палітри і (в новій
шапці) ще одна кнопка. Додати команду означало згадати про всі три місця, і
забуте місце давало або «мертву» кнопку, або команду, недоступну з пошуку.
Тепер джерело одне:

* :class:`Command` — назва, категорія, гарячі клавіші, дія й перевірка
  доступності;
* :func:`register` — додати команду (ідемпотентно, за ключем);
* :func:`all_commands` — усі команди для палітри й для меню;
* :func:`available` — команди, доступні ЗАРАЗ (з урахуванням стану).

Модуль не тягне tkinter: усе, що потрібно від вікна, приходить через
колбеки-дії. Це дозволяє тестувати реєстр без дисплея.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

LOG = logging.getLogger("blackchpok.commands")

#: Категорії в порядку показу. Підпис видно в палітрі перед назвою команди.
CATEGORIES: tuple[str, ...] = (
    "Файл",
    "Правка",
    "Вигляд",
    "Агент",
    "Чат",
    "Завдання",
    "Код",
    "Git",
    "Сайт",
    "Модель",
    "Довідка",
)

#: Рівні «важливості» команди — визначають, де вона показується.
#: ``primary`` — видима кнопка в шапці; ``menu`` — у випадаючому меню шапки;
#: ``palette`` — лише через палітру (рідкісні дії).
PRIMARY = "primary"
MENU = "menu"
PALETTE = "palette"

#: Групи шапки — порядок колонок зліва направо.
HEADER_GROUPS: tuple[str, ...] = (
    "brand",     # логотип + проєкт
    "file",      # відкрити / створити / зберегти / скасувати
    "agent",     # агент, модель, стан сервера
    "run",       # запуск, термінал, live browser
    "git",       # гілка, зміни, commit
    "view",      # панелі, пошук, налаштування
)


@dataclass(frozen=True)
class Command:
    """Одна команда IDE.

    ``enabled`` — предикат: команда, яка зараз недоступна, у палітрі
    показана тьмяно (а не зникає), а в шапці стає неактивною. Так
    користувач бачить, що можливість існує, але потребує, наприклад,
    відкритого файлу.
    """

    key: str
    label: str
    category: str
    action: Callable[[], Any]
    shortcut: str = ""
    level: str = PALETTE
    group: str = ""
    icon: str = ""
    tip: str = ""
    enabled: Optional[Callable[[], bool]] = None
    aliases: tuple[str, ...] = ()

    # ── сервіс ─────────────────────────────────────────────────────────────
    def is_enabled(self) -> bool:
        """Чи можна виконати команду зараз (безпечно, без винятків)."""
        if self.enabled is None:
            return True
        try:
            return bool(self.enabled())
        except Exception:  # noqa: BLE001 - перевірка не має ламати палітру
            LOG.debug("Перевірка доступності «%s» впала", self.key, exc_info=True)
            return False

    def run(self) -> bool:
        """Виконати команду; ``False`` — якщо вона недоступна або впала."""
        if not self.is_enabled():
            return False
        try:
            self.action()
            return True
        except Exception:  # noqa: BLE001 - одна команда не має валити IDE
            LOG.warning("Команда «%s» впала", self.key, exc_info=True)
            return False

    @property
    def qualified(self) -> str:
        """Підпис для палітри: «Категорія: Назва»."""
        return f"{self.category}: {self.label}"

    def matches(self, query: str) -> bool:
        """Чи відповідає команда пошуковому запиту (усі слова мають бути)."""
        needle = (query or "").strip().casefold()
        if not needle:
            return True
        haystack = " ".join(
            (self.label, self.category, self.shortcut, self.tip,
             self.key, *self.aliases)
        ).casefold()
        return all(token in haystack for token in needle.split())


#: Ключ → команда. Порядок вставлення збережено для стабільного вигляду.
_REGISTRY: dict[str, Command] = {}


def register(command: Command) -> Command:
    """Додати або замінити команду за ключем (ідемпотентно)."""
    _REGISTRY[command.key] = command
    return command


def register_many(commands: Iterable[Command]) -> None:
    for command in commands:
        register(command)


def get(key: str) -> Optional[Command]:
    return _REGISTRY.get(key)


def all_commands() -> list[Command]:
    """Усі команди в стабільному порядку."""
    return list(_REGISTRY.values())


def available(query: str = "", *, only_enabled: bool = False) -> list[Command]:
    """Команди за запитом (недоступні лишаються, якщо ``only_enabled=False``)."""
    found = [command for command in _REGISTRY.values() if command.matches(query)]
    if only_enabled:
        found = [command for command in found if command.is_enabled()]
    return found


def by_level(level: str) -> list[Command]:
    return [command for command in _REGISTRY.values() if command.level == level]


def by_group(group: str) -> list[Command]:
    return [command for command in _REGISTRY.values() if command.group == group]


def categories_present() -> list[str]:
    """Категорії, у яких справді є команди (для підписів палітри)."""
    used = {command.category for command in _REGISTRY.values()}
    ordered = [name for name in CATEGORIES if name in used]
    ordered.extend(sorted(used - set(CATEGORIES)))
    return ordered


def reset() -> None:
    """Очистити реєстр (для тестів)."""
    _REGISTRY.clear()


def palette_items(query: str = "") -> list[tuple[str, str, Callable[[], None]]]:
    """Готові рядки для :class:`palette.Palette`.

    Недоступні команди лишаємо у списку з поміткою «недоступно»: так
    користувач бачить можливість і розуміє, чого бракує (файлу, проєкту),
    замість того щоб шукати команду, якої «немає».
    """
    rows: list[tuple[str, str, Callable[[], None]]] = []

    def make(command: Command) -> Callable[[], None]:
        return command.run

    for command in available(query):
        ok = command.is_enabled()
        hint_parts: list[str] = []
        if command.shortcut:
            hint_parts.append(command.shortcut)
        if not ok:
            hint_parts.append("недоступно")
        label = command.qualified if not command.icon else f"{command.icon} {command.qualified}"
        rows.append((label, "   ".join(hint_parts), make(command)))
    return rows


def header_layout() -> list[tuple[str, list[Command]]]:
    """Групи команд для нової шапки: [(група, команди-primary)]."""
    groups: list[tuple[str, list[Command]]] = []
    for group in HEADER_GROUPS:
        items = [command for command in _REGISTRY.values()
                 if command.group == group and command.level == PRIMARY]
        groups.append((group, items))
    return groups


def menu_layout() -> list[tuple[str, list[Command]]]:
    """Випадаючі меню шапки: [(підпис групи, команди menu-рівня)]."""
    labels = {
        "file": "Файл",
        "agent": "Агент",
        "run": "Запуск",
        "git": "Git",
        "view": "Вигляд",
    }
    groups: list[tuple[str, list[Command]]] = []
    for group, label in labels.items():
        items = [command for command in _REGISTRY.values()
                 if command.group == group and command.level == MENU]
        if items:
            groups.append((label, items))
    return groups


__all__ = [
    "CATEGORIES",
    "Command",
    "HEADER_GROUPS",
    "MENU",
    "PALETTE",
    "PRIMARY",
    "all_commands",
    "available",
    "by_group",
    "by_level",
    "categories_present",
    "get",
    "header_layout",
    "menu_layout",
    "palette_items",
    "register",
    "register_many",
    "reset",
]
