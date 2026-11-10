"""Слэш-команди композера: «/файл», «/ціль», «/план», «/дозвіл» тощо.

Команди — це швидкий спосіб зробити дію просто з поля введення, не
перемикаючись мишею. Кожна команда знає: назву, псевдоніми, підказку, чи
потребує аргументу, і функцію-виконавець (її надає вікно).

Модуль не тягне tkinter: реєстр можна перевіряти тестами.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

#: Групи в меню — порядок показу.
GROUP_ADD = "Додати"
GROUP_COMMANDS = "Команди"

#: Виконавець: приймає (argument: str) і повертає текст результату (або "").
Executor = Callable[[str], str]


@dataclass(frozen=True)
class SlashCommand:
    """Одна команда композера."""

    name: str                       # без слеша, напр. "файл"
    hint: str                       # що робить (показується праворуч)
    group: str = GROUP_COMMANDS
    aliases: tuple[str, ...] = ()
    takes_argument: bool = False
    icon: str = "›"
    order: int = 100

    def matches(self, text: str) -> bool:
        """Чи введений текст є цією командою (з аргументом або без)."""
        clean = (text or "").strip().lstrip("/").lower()
        if not clean:
            return False
        head = clean.split()[0] if clean.split() else ""
        names = (self.name.lower(), *self.aliases)
        return head in names

    def argument_of(self, text: str) -> str:
        """Аргумент після назви команди."""
        clean = (text or "").strip().lstrip("/")
        parts = clean.split(maxsplit=1)
        return parts[1].strip() if len(parts) > 1 else ""

    def menu_text(self) -> str:
        return f"/{self.name}"


#: Повний перелік команд.
#: Користувач говорить людською мовою — цього достатньо.
COMMANDS: tuple[SlashCommand, ...] = (
    # ── Додати ────────────────────────────────────────────────────────────
    SlashCommand("файл", "Прикріпити файл до запиту", GROUP_ADD,
                 aliases=("file", "attach"), icon="📄", order=10),
    SlashCommand("ціль", "Поставити ціль для довгострокової задачі", GROUP_ADD,
                 aliases=("goal",), takes_argument=True, icon="◎", order=20),
    SlashCommand("план", "Спершу скласти план, файли не змінювати", GROUP_ADD,
                 aliases=("plan",), icon="☰", order=30),
    SlashCommand("відгук", "Залишити відгук про цю сесію", GROUP_ADD,
                 aliases=("feedback",), takes_argument=True, icon="✎", order=40),

    # ── Команди ───────────────────────────────────────────────────────────
    SlashCommand("стиснути", "Стиснути історію розмови", GROUP_COMMANDS,
                 aliases=("compact", "стисни"), icon="◌", order=50),
    SlashCommand("дозвіл", "Змінити режим дозволів (читання / робоча / повний)",
                 GROUP_COMMANDS, aliases=("permission", "perms", "права"),
                 icon="🛡", order=60),
    SlashCommand("модель", "Вибрати модель для цієї розмови", GROUP_COMMANDS,
                 aliases=("model",), icon="⊟", order=70),
    SlashCommand("експорт", "Завантажити журнал сесії", GROUP_COMMANDS,
                 aliases=("export",), icon="↧", order=80),
    SlashCommand("скіли", "Перелік скілів агента", GROUP_COMMANDS,
                 aliases=("skills", "скіл"), icon="✦", order=90),
    SlashCommand("скіл", "Надіслати скіл агенту", GROUP_COMMANDS,
                 aliases=(), takes_argument=True, icon="✧", order=110),
    SlashCommand("стоп", "Зупинити агента", GROUP_COMMANDS,
                 aliases=("stop",), icon="■", order=120),
    SlashCommand("очистити", "Очистити цей чат", GROUP_COMMANDS,
                 aliases=("clear", "новий"), icon="✕", order=130),
    SlashCommand("допомога", "Показати всі команди", GROUP_COMMANDS,
                 aliases=("help", "?"), icon="?", order=140),
)

_BY_NAME: dict[str, SlashCommand] = {}
for _command in COMMANDS:
    for _alias in (_command.name, *_command.aliases):
        _BY_NAME[_alias.lower()] = _command


def is_slash(text: str) -> bool:
    """Чи починається введене зі слеша."""
    return (text or "").lstrip().startswith("/")


def find(text: str) -> Optional[SlashCommand]:
    """Знайти команду, яку ввів користувач."""
    clean = (text or "").strip()
    if not clean.startswith("/"):
        return None
    head = clean.lstrip("/").split()[0].lower() if clean.lstrip("/").split() else ""
    return _BY_NAME.get(head)


def filter_commands(prefix: str) -> list[SlashCommand]:
    """Команди, що підходять під уже введений текст (для меню)."""
    clean = (prefix or "").strip().lstrip("/").lower()
    if not clean:
        return sorted(COMMANDS, key=lambda c: c.order)
    found = [
        command for command in COMMANDS
        if command.name.lower().startswith(clean)
        or any(alias.startswith(clean) for alias in command.aliases)
        or clean in command.hint.lower()
    ]
    return sorted(found, key=lambda c: c.order)


def grouped(commands: Iterable[SlashCommand] | None = None) -> list[tuple[str, list[SlashCommand]]]:
    """Команди, згруповані для меню: [("Додати", [...]), ("Команди", [...])]."""
    items = sorted(commands if commands is not None else COMMANDS,
                   key=lambda c: c.order)
    groups: list[tuple[str, list[SlashCommand]]] = []
    for group in (GROUP_ADD, GROUP_COMMANDS):
        members = [command for command in items if command.group == group]
        if members:
            groups.append((group, members))
    return groups


def parse(text: str) -> tuple[Optional[SlashCommand], str]:
    """Розібрати «/модель qwen» → (команда, "qwen")."""
    command = find(text)
    if command is None:
        return None, ""
    return command, command.argument_of(text)


def help_text() -> str:
    """Текстова довідка для «/допомога»."""
    lines = ["Команди композера:"]
    for group, items in grouped():
        lines.append("")
        lines.append(f"{group}:")
        for command in items:
            names = ", ".join(f"/{alias}" for alias in (command.name, *command.aliases))
            lines.append(f"  {names} — {command.hint}")
    return "\n".join(lines)


def permission_modes() -> list[tuple[str, str, str, str]]:
    """Варіанти режиму дозволів для меню: (ключ, підпис, підказка, іконка)."""
    from . import permissions

    return [
        (mode, *permissions.MODE_LABELS[mode]) for mode in permissions.MODES
    ]


__all__ = [
    "COMMANDS",
    "GROUP_ADD",
    "GROUP_COMMANDS",
    "Executor",
    "SlashCommand",
    "filter_commands",
    "find",
    "grouped",
    "help_text",
    "is_slash",
    "parse",
    "permission_modes",
]
