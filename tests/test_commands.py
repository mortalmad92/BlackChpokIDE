"""Тести слэш-команд композера й режимів дозволів.

Запуск:  python tests/test_commands.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import permissions, slash_commands  # noqa: E402

failures = 0
checked = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures, checked
    checked += 1
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


# ─────────────────────────────────────────────────────────────────────────────
# Реєстр команд
# ─────────────────────────────────────────────────────────────────────────────

def test_registry() -> None:
    names = [command.name for command in slash_commands.COMMANDS]
    check("реєстр не порожній", len(names) >= 12, f"{len(names)} команд")

    # Команди з макета мають бути на місці.
    for expected in ("файл", "ціль", "план", "відгук",
                     "стиснути", "дозвіл", "модель", "експорт"):
        check(f"є команда /{expected}", expected in names)

    groups = dict(slash_commands.grouped())
    check("група «Додати» є", "Додати" in groups and len(groups["Додати"]) >= 4,
          str(len(groups.get("Додати", []))))
    check("група «Команди» є", "Команди" in groups and len(groups["Команди"]) >= 8,
          str(len(groups.get("Команди", []))))

    check("у всіх команд є підказка",
          all(command.hint.strip() for command in slash_commands.COMMANDS))
    check("назви команд не повторюються", len(names) == len(set(names)))


def test_lookup() -> None:
    check("пошук за назвою", slash_commands.find("/модель") is not None)
    check("пошук за псевдонімом", slash_commands.find("/model") is not None)
    check("пошук англійською", slash_commands.find("/permission").name == "дозвіл")
    check("невідома команда — None", slash_commands.find("/асдфг") is None)
    check("без слеша не команда", slash_commands.find("модель") is None)
    check("is_slash розпізнає", slash_commands.is_slash("/файл")
          and not slash_commands.is_slash("файл"))

    command, argument = slash_commands.parse("/ціль переписати парсер")
    check("розбір команди з аргументом",
          command is not None and command.name == "ціль"
          and argument == "переписати парсер", argument)

    command2, argument2 = slash_commands.parse("/стиснути")
    check("команда без аргументу", command2 is not None and argument2 == "")

    check("фільтр за префіксом",
          "модель" in [c.name for c in slash_commands.filter_commands("/мо")],
          str([c.name for c in slash_commands.filter_commands("/мо")]))
    check("порожній фільтр дає всі",
          len(slash_commands.filter_commands("")) == len(slash_commands.COMMANDS))

    text = slash_commands.help_text()
    check("довідка містить команди", "/дозвіл" in text and "/модель" in text)
    check("довідка містить групи", "Додати" in text and "Команди" in text)


# ─────────────────────────────────────────────────────────────────────────────
# Режими дозволів
# ─────────────────────────────────────────────────────────────────────────────

def test_modes() -> None:
    check("три режими", len(permissions.MODES) == 3, str(permissions.MODES))
    check("типовий режим — робоча область",
          permissions.normalise_mode("") == permissions.WORKSPACE)
    check("псевдонім read-only",
          permissions.normalise_mode("read-only") == permissions.READ_ONLY)
    check("псевдонім українською",
          permissions.normalise_mode("лише читання") == permissions.READ_ONLY)
    check("псевдонім full", permissions.normalise_mode("all") == permissions.FULL)
    check("підпис для full", "Повний" in permissions.label_for("full"))
    check("опис режиму", bool(permissions.describe("workspace").strip()))


def test_permission_checks() -> None:
    root = Path(ROOT)

    decision = permissions.check_tool("read_file", {"path": "main.py"},
                                      mode=permissions.READ_ONLY, root=root)
    check("читання дозволено завжди", decision.allowed)

    decision = permissions.check_tool("write_file", {"path": "new.txt", "content": "x"},
                                      mode=permissions.READ_ONLY, root=root)
    check("запис заборонено в read-only", not decision.allowed, decision.reason)

    decision = permissions.check_tool("write_file", {"path": "new.txt", "content": "x"},
                                      mode=permissions.WORKSPACE, root=root)
    check("запис у робочій області дозволено", decision.allowed)

    decision = permissions.check_tool("write_file", {"path": "../escape.txt", "content": "x"},
                                      mode=permissions.WORKSPACE, root=root)
    check("вихід за робочу теку заборонено", not decision.allowed, decision.reason)

    decision = permissions.check_tool("write_file",
                                      {"path": "C:/Windows/system32/x.dll", "content": "x"},
                                      mode=permissions.WORKSPACE, root=root)
    check("системна тека заборонена", not decision.allowed, decision.reason)

    decision = permissions.check_tool("write_file",
                                      {"path": "C:/Windows/system32/x.dll", "content": "x"},
                                      mode=permissions.FULL, root=root)
    check("у повному доступі системна т��ка дозволена (з підтвердженням)",
          decision.allowed and decision.needs_confirmation, decision.reason)

    decision = permissions.check_tool("run_command", {"command": "echo hi"},
                                      mode=permissions.READ_ONLY, root=root)
    check("команди заборонено в read-only", not decision.allowed)

    decision = permissions.check_tool("run_command", {"command": "rm -rf /"},
                                      mode=permissions.WORKSPACE, root=root)
    check("небезпечна команда заборонена у робочій області", not decision.allowed,
          decision.reason)

    decision = permissions.check_tool("run_command", {"command": "rm -rf /"},
                                      mode=permissions.FULL, root=root)
    check("небезпечна команда дозволена в повному доступі", decision.allowed)

    decision = permissions.check_tool("router:night_shift", {},
                                      mode=permissions.READ_ONLY, root=root)
    check("MCP-дія, що змінює стан, заборонена в read-only", not decision.allowed)

    decision = permissions.check_tool("router:search_web", {"query": "x"},
                                      mode=permissions.READ_ONLY, root=root)
    check("MCP-пошук дозволено в read-only", decision.allowed)


def test_helpers() -> None:
    check("системний шлях Windows", permissions.is_system_path("C:/Windows/x"))
    check("звичайний шлях не системний",
          not permissions.is_system_path(ROOT / "main.py"))
    check("всередині теки", permissions.inside(ROOT / "main.py", ROOT))
    check("поза текою", not permissions.inside(ROOT / ".." / "x.py", ROOT))

    hint = permissions.prompt_hint(permissions.READ_ONLY)
    check("підказка моделі для read-only згадує режим", "ЧИТАННЯ" in hint)


# ─────────────────────────────────────────────────────────────────────────────
# Живий інтерфейс
# ─────────────────────────────────────────────────────────────────────────────

def test_live_panel() -> None:
    import tkinter.messagebox as mb
    import tkinter.simpledialog as sd

    mb.askyesno = lambda *a, **k: True
    mb.askyesnocancel = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    sd.askstring = lambda *a, **k: None
    sd.askinteger = lambda *a, **k: None

    from blackchpok_ide import theme
    from blackchpok_ide.chat_panel import ChatPanel
    from blackchpok_ide.agent_tools import ToolRegistry
    from blackchpok_ide.config import Settings

    import tkinter as tk

    root = tk.Tk()
    root.geometry("700x700")
    fonts = theme.Theme(root)
    fonts.apply()
    settings = Settings()
    panel = ChatPanel(root, fonts, settings, ToolRegistry(ROOT))
    panel.pack(fill="both", expand=True)

    def pump(seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            root.update()
            time.sleep(0.02)

    pump(0.4)

    check("кнопка команд є", panel.commands_btn.cget("text") == "/")
    check("перемикач дозволів показує режим",
          "робочій" in panel.permission_label.cget("text").lower(),
          panel.permission_label.cget("text"))

    panel.set_permission_mode(permissions.READ_ONLY)
    pump(0.2)
    check("режим змінюється через панель",
          panel.permission_mode == permissions.READ_ONLY
          and "читання" in panel.permission_label.cget("text").lower())

    panel.toggle_command_menu()
    pump(0.5)
    menu = panel._menu
    check("меню команд відкривається", menu is not None and menu.visible)
    check("меню має пункти", menu is not None and len(menu.items) >= 10,
          str(len(menu.items) if menu else 0))
    menu.move(1)
    check("навігація стрілками", menu.selected == 1, str(menu.selected))
    menu.close()
    pump(0.2)
    check("меню закривається", not menu.visible)

    panel.toggle_permission_menu()
    pump(0.5)
    check("меню дозволів відкривається", menu.visible and len(menu.items) == 3,
          str(len(menu.items)))
    check("у меню дозволів позначено активний",
          any("✓" in item[0] for item in menu.items), str([i[0] for i in menu.items]))
    menu.close()
    pump(0.2)

    # Команда /допомога показує довідку
    panel.set_text("/допомога")
    handled = panel._maybe_slash()
    pump(0.2)
    check("команда /допомога обробляється", handled)
    check("довідка з'явилась у чаті",
          "Команди композера" in panel.transcript.get())

    # Звичайний текст не вважається командою
    panel.set_text("звичайний запит")
    check("звичайний текст не команда", not panel._maybe_slash())

    # /дозвіл із невідомим режимом не міняє режим
    before = panel.permission_mode
    panel.set_text("/дозвіл асдфг")
    panel._maybe_slash()
    pump(0.2)
    check("невідомий режим не застосовується", panel.permission_mode == before,
          panel.permission_mode)

    root.destroy()


def main() -> int:
    test_registry()
    test_lookup()
    test_modes()
    test_permission_checks()
    test_helpers()
    test_live_panel()
    print()
    print(f"Перевірено тверджень: {checked}")
    print("Команди й дозволи:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


# ── unittest-обгортка (додано 10.11.2026) ──────────────────────────────────
# Для `python -m unittest discover` ці перевірки раніше були невидимі:
# файл — скрипт із власним main(), а не TestCase. Тепер discover запускає
# його й падає, якщо main() повернув ненульовий код. Запуск як скрипт
# (`python tests/test_commands.py`) поводиться як раніше.
import unittest as _unittest  # noqa: E402


class _ScriptSuite(_unittest.TestCase):
    def test_script_passes(self) -> None:
        code = main()
        self.assertEqual(code, 0, f"main() повернув {code}")
