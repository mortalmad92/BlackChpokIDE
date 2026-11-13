"""Режими дозволів: що агенту можна робити без підтвердження.

Три рівні, як у сучасних агентних редакторах:

* **read-only** — лише читання; будь-який запис відхиляється;
* **workspace** — писати можна тільки в робочу теку, системні шляхи заборонені;
* **full** — без обмежень (усе одно з підтвердженням небезпечних команд, якщо
  вмикач «питати дозвіл на команди» активний).

Модуль не тягне tkinter: правило перевіряється чистою функцією, тому його
можна тестувати й використовувати у фонових потоках.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

READ_ONLY = "read_only"
WORKSPACE = "workspace"
FULL = "full"

MODES: tuple[str, ...] = (READ_ONLY, WORKSPACE, FULL)

#: Підписи й підказки для інтерфейсу.
MODE_LABELS: dict[str, tuple[str, str, str]] = {
    READ_ONLY: (
        "Лише читання",
        "Агент може читати файли й запускати пошук, але нічого не змінює.",
        "🛡",
    ),
    WORKSPACE: (
        "Запис у робочій області",
        "Агент може створювати й правити файли, але лише в теці проєкту.",
        "🖊",
    ),
    FULL: (
        "Повний доступ",
        "Без обмежень: будь-які файли й команди (підтвердження — за налаштуванням).",
        "⚠",
    ),
}

#: Інструменти, які нічого не змінюють.
READ_TOOLS = frozenset({
    "read_file", "list_dir", "search_text", "find_files", "project_tree",
    "git_status", "git_diff", "git_remote_info", "python_check",
    "list_skills", "read_skill",
})

#: Інструменти, які змінюють стан ПОЗА цією машиною (публікація).
#:
#: ``git_publish`` відправляє коміт на GitHub — це видно іншим людям і
#: відкотити його локально неможливо. Тому він заборонений у режимі «лише
#: читання» і ЗАВЖДИ вимагає підтвердження, навіть коли загальний вмикач
#: «питати дозвіл на команди» вимкнено: ціна помилки тут інша.
PUBLISH_TOOLS = frozenset({"git_publish"})

#: Інструменти, які пишуть на диск.
#:
#: ``append_file`` тут обов'язковий: без нього режим «лише читання»
#: дозволяв дописувати у файли (перевірено: ``check_tool("append_file",
#: {"path": "../escape.txt"})`` повертав «дозволено»), а перевірка шляху
#: всередині робочої теки для нього не виконувалась зовсім.
WRITE_TOOLS = frozenset({
    "write_file", "edit_file", "append_file",
})

#: Інструменти, які виконують команди (найризикованіші).
EXEC_TOOLS = frozenset({"run_command"})

#: Мережеві й серверні дії MCP, які міняють стан, але не файли.
MCP_MUTATING = frozenset({
    "router:save_rule", "router:todo_write", "router:index_project",
    "router:night_shift", "router:run_and_repair",
})

#: Системні шляхи, куди не можна писати навіть із «робочою областю».
SYSTEM_PREFIXES = (
    "c:\\windows", "c:\\program files", "c:\\program files (x86)",
    "c:\\programdata", "/etc", "/usr", "/bin", "/sbin", "/System",
    "/Library", "/boot", "/dev", "/proc",
)


@dataclass(frozen=True)
class Decision:
    """Результат перевірки дозволу."""

    allowed: bool
    reason: str = ""
    needs_confirmation: bool = False

    def __bool__(self) -> bool:
        return self.allowed


def normalise_mode(name: str) -> str:
    """Привести назву режиму до одного з трьох значень."""
    value = (name or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "read": READ_ONLY, "readonly": READ_ONLY, "read_only": READ_ONLY,
        "лише_читання": READ_ONLY, "readonly_mode": READ_ONLY,
        "workspace": WORKSPACE, "work": WORKSPACE, "project": WORKSPACE,
        "запис": WORKSPACE, "робоча": WORKSPACE,
        "full": FULL, "all": FULL, "unrestricted": FULL, "повний": FULL,
    }
    if value in MODES:
        return value
    return aliases.get(value, WORKSPACE)


def label_for(mode: str) -> str:
    return MODE_LABELS.get(normalise_mode(mode), MODE_LABELS[WORKSPACE])[0]


#: Короткі підписи для вузьких місць (рядок композера, заголовок).
SHORT_LABELS: dict[str, str] = {
    READ_ONLY: "читання",
    WORKSPACE: "робоча",
    FULL: "повний",
}


def short_label_for(mode: str) -> str:
    return SHORT_LABELS.get(normalise_mode(mode), SHORT_LABELS[WORKSPACE])


def icon_for(mode: str) -> str:
    return MODE_LABELS.get(normalise_mode(mode), MODE_LABELS[WORKSPACE])[2]


def hint_for(mode: str) -> str:
    return MODE_LABELS.get(normalise_mode(mode), MODE_LABELS[WORKSPACE])[1]


#: Дієслова, які в назві MCP-інструмента означають зміну стану ПОЗА
#: проєктом. Потрібні тому, що список :data:`MCP_MUTATING` не може знати
#: всіх інструментів усіх серверів: «лише читання» не має ламатись від
#: того, що назви немає в списку.
_MUTATING_VERBS = (
    "write", "delete", "remove", "save", "create", "update", "edit", "append",
    "move", "rename", "publish", "deploy", "exec", "run", "kill", "stop",
    "restart", "install", "uninstall", "drop", "truncate",
)


def _mcp_looks_mutating(name: str) -> bool:
    """Чи схожа назва MCP-інструмента на дію, що змінює стан."""
    low = (name or "").lower()
    return any(verb in low for verb in _MUTATING_VERBS)


def is_system_path(path: Path | str) -> bool:
    """Чи лежить шлях у системній теці (куди писати небезпечно)."""
    try:
        text = str(Path(path).resolve()).lower().replace("/", os.sep)
    except (OSError, ValueError):
        text = str(path).lower()
    if text.startswith("\\\\"):
        return False  # мережевий шлях — не системний
    return any(text.startswith(prefix.lower()) for prefix in SYSTEM_PREFIXES)


def inside(path: Path | str, root: Path | str) -> bool:
    """Чи лежить шлях усередині робочої теки."""
    try:
        target = Path(path).resolve()
        base = Path(root).resolve()
    except (OSError, ValueError):
        return False
    try:
        target.relative_to(base)
        return True
    except ValueError:
        return False


def check_tool(
    tool: str,
    arguments: dict[str, Any] | str | None,
    *,
    mode: str = WORKSPACE,
    root: Path | str = ".",
    confirm_commands: bool = False,
) -> Decision:
    """Чи можна виконати інструмент із такими аргументами."""
    active = normalise_mode(mode)
    args = arguments if isinstance(arguments, dict) else {}
    name = (tool or "").strip()

    if name.startswith("mcp__") or name.startswith("router:"):
        intent = name.split("__")[-1] if name.startswith("mcp__") else name
        # Порівнюємо І повну назву, І «хвіст» intent'а. Раніше перевірявся
        # лише хвіст, а в MCP_MUTATING назви мають префікс ``router:`` —
        # тому ``mcp__router__save_rule`` проходив у режимі «лише читання»
        # (перевірено: allowed=True). Тепер жодна з форм не обходить правило.
        mutating = (intent in MCP_MUTATING or name in MCP_MUTATING
                    or _mcp_looks_mutating(name))
        if mutating and active == READ_ONLY:
            return Decision(False, "Режим «лише читання»: ця дія змінює стан.")
        return Decision(True)

    if name in READ_TOOLS:
        return Decision(True)

    if name in PUBLISH_TOOLS:
        # Публікація на GitHub: незворотна зовнішня дія.
        if active == READ_ONLY:
            return Decision(False, "Режим «лише читання»: відправка на GitHub "
                                   "заборонена.")
        return Decision(True, needs_confirmation=True)

    if name in EXEC_TOOLS:
        if active == READ_ONLY:
            return Decision(False, "Режим «лише читання»: команди заборонені.")
        command = str(args.get("command") or "")
        if _dangerous_command(command) and active != FULL:
            return Decision(False, "Небезпечна команда дозволена лише в режимі "
                                   "«повний доступ».")
        return Decision(True, needs_confirmation=bool(confirm_commands))

    if name in WRITE_TOOLS:
        if active == READ_ONLY:
            return Decision(False, "Режим «лише читання»: запис файлів вимкнено.")
        path = str(args.get("path") or "")
        if active == WORKSPACE:
            if not path:
                return Decision(False, "Не вказано шлях для запису.")
            try:
                target = Path(root) / path
            except (OSError, ValueError):
                return Decision(False, f"Некоректний шлях: {path}")
            if not inside(target, root):
                return Decision(False, f"Шлях «{path}» поза робочою текою.")
            if is_system_path(target):
                return Decision(False, "Системні теки заборонені в цьому режимі.")
        elif active == FULL and path and is_system_path(path):
            return Decision(True, needs_confirmation=True)
        return Decision(True)

    # Невідомий інструмент — дозволяємо, якщо це не режим лише читання.
    if active == READ_ONLY:
        return Decision(False, "Режим «лише читання»: невідома дія заборонена.")
    return Decision(True)


_DANGEROUS_MARKERS = (
    "rm -rf", "rmdir /s", "del /f", "format ", "diskpart", "reg delete",
    "shutdown", "taskkill /f", "mkfs", "dd if=", ":(){", "> /dev/sda",
    "cacls", "icacls", "takeown", "attrib -r -s -h",
)


def _dangerous_command(command: str) -> bool:
    low = (command or "").lower()
    return any(marker in low for marker in _DANGEROUS_MARKERS)


def allowed_tools(mode: str, tools: Iterable[str]) -> list[str]:
    """Підмножина інструментів, дозволених у режимі (для підказки в UI).

    У режимі робочої області заборонені лише ті MCP-дії, які змінюють
    стан ПОЗА проєктом (публікація, нічна зміна, переіндексація): файли
    в теці проєкту агент править вільно, а зовнішні системи — ні.

    Раніше тут стояла умова ``name not in MCP_MUTATING or True``, яка
    завжди істинна: список виходив повним, і підказка в інтерфейсі
    обіцяла більше, ніж режим справді дозволяв.
    """
    active = normalise_mode(mode)
    items = list(tools)
    if active == FULL:
        return items
    if active == WORKSPACE:
        return [name for name in items if name not in MCP_MUTATING]
    return [name for name in items if name in READ_TOOLS or name.startswith("mcp__")]


def describe(mode: str) -> str:
    """Один рядок для рядка стану й системного промпта."""
    active = normalise_mode(mode)
    label, hint, _icon = MODE_LABELS[active]
    return f"{label} — {hint}"


def prompt_hint(mode: str) -> str:
    """Що сказати моделі про поточний режим."""
    active = normalise_mode(mode)
    if active == READ_ONLY:
        return ("Режим роботи: ЛИШЕ ЧИТАННЯ. Не змінюй файли й не запускай команди, "
                "що щось змінюють. Пояснюй і показуй, що треба зробити.")
    if active == WORKSPACE:
        return ("Режим роботи: ЗАПИС У РОБОЧІЙ ОБЛАСТІ. Можна створювати й правити "
                "файли лише в теці проєкту.")
    return "Режим роботи: ПОВНИЙ ДОСТУП. Обмежень немає."


__all__ = [
    "Decision",
    "EXEC_TOOLS",
    "FULL",
    "MCP_MUTATING",
    "MODE_LABELS",
    "MODES",
    "READ_ONLY",
    "READ_TOOLS",
    "SYSTEM_PREFIXES",
    "WORKSPACE",
    "WRITE_TOOLS",
    "allowed_tools",
    "check_tool",
    "describe",
    "hint_for",
    "icon_for",
    "inside",
    "is_system_path",
    "label_for",
    "normalise_mode",
    "prompt_hint",
]
