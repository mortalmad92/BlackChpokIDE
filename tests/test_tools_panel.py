"""Тести панелі «Інструменти»: каталог із реальних схем і справжній виклик.

Запуск:  python tests/test_tools_panel.py
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

failures = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if condition else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures += 1


def pump(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def test_catalog() -> None:
    """Каталог збігається з реальними схемами агента."""
    from blackchpok_ide.agent_tools import TOOL_SCHEMAS
    from blackchpok_ide.tools_panel import builtin_tools

    items = builtin_tools()
    schema_names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    item_names = {item["name"] for item in items}

    check("усі схеми потрапили в каталог", schema_names == item_names,
          f"схем {len(schema_names)}, у каталозі {len(item_names)}")
    # Перевірка «не порожній» мусить бути НЕЗАЛЕЖНОЮ від кількості: раніше
    # тут стояло жорстке ``== 20``, яке не виконувалось навіть у базовій
    # версії (там схем було 11). Тепер каталог мусить покривати всі схеми й
    # містити щонайменше базовий набір.
    # Деталі: research/KNOWN_BASELINE_FAILURES.md.
    check("каталог не порожній", len(items) >= 8, f"{len(items)} інструментів")
    check("каталог повний", schema_names == item_names,
          f"схем {len(schema_names)}, у каталозі {len(item_names)}")

    read = next((i for i in items if i["name"] == "read_file"), None)
    check("read_file має опис", read is not None and bool(read["description"]))
    check("read_file має параметри", read is not None and len(read["params"]) >= 1,
          str(len(read["params"])) if read else "0")
    check("обов'язковий параметр позначено",
          read is not None and any(required for _k, _h, required in read["params"]))
    check("категорія файлів правильна",
          read is not None and read["category"] == "Файли")


def test_panel_and_call() -> None:
    """Панель малює каталог і реально виконує інструмент."""
    import tkinter as tk

    from blackchpok_ide import theme, tools_panel
    from blackchpok_ide.agent_tools import TOOL_SCHEMAS, ToolRegistry

    root = tk.Tk()
    root.geometry("320x800")
    fonts = theme.Theme(root)
    fonts.apply()

    registry = ToolRegistry(ROOT)
    results: list[tuple[str, bool]] = []
    panel = tools_panel.ToolsPanel(
        root, fonts, registry,
        on_result=lambda out, ok: results.append((out, ok)),
    )
    panel.pack(fill="both", expand=True)
    root.update()

    check("панель має каталог", len(panel._items) == len(TOOL_SCHEMAS),
          f"{len(panel._items)} із {len(TOOL_SCHEMAS)} схем")

    # Розгортаємо read_file і заповнюємо параметри.
    panel._toggle("read_file")
    root.update()
    check("форма відкрилась", "path" in panel._forms, str(list(panel._forms)))
    check("є поле path", panel._forms.get("path") is not None)

    panel._fill_example("read_file")
    root.update()
    check("приклад заповнив path",
          panel._forms["path"].get() == "main.py", panel._forms["path"].get())

    # Справжній виклик інструмента.
    panel.run_tool("read_file")
    pump(root, 2.5)
    check("виклик виконався", len(results) == 1, f"{len(results)} результатів")
    if results:
        output, ok = results[0]
        check("інструмент повернув успіх", ok is True)
        check("результат містить вміст файлу",
              "main.py" in output or "def main" in output, output[:80])
    check("результат показано в панелі",
          "✓" in panel.result_label.cget("text"),
          panel.result_label.cget("text")[:60])

    # Помилковий шлях — інструмент має чесно повідомити про помилку.
    panel._toggle("read_file")
    panel._toggle("read_file")
    root.update()
    panel._forms["path"].delete(0, "end")
    panel._forms["path"].insert(0, "неіснуючий_файл_12345.txt")
    panel.run_tool("read_file")
    pump(root, 2.5)
    check("помилка теж доходить", len(results) == 2, f"{len(results)}")
    if len(results) == 2:
        check("помилка позначена як невдача", results[1][1] is False)

    # Пошук по каталогу: лишаються тільки ті інструменти, що містять запит.
    panel.entry.insert(0, "git")
    panel._on_query()
    root.update()
    expected_git = [s["function"]["name"] for s in TOOL_SCHEMAS
                    if "git" in s["function"]["name"]]
    check("фільтр працює", len(panel._shown) == len(expected_git),
          f"{len(panel._shown)} із {len(expected_git)}")
    names_shown = [i["name"] for i in panel._shown]
    check("знайдено git-інструменти", len(names_shown) == len(expected_git), str(names_shown))

    panel.cancel()
    root.destroy()


def test_run_command_real() -> None:
    """Реальний запуск команди через панель (не мок)."""
    import tkinter as tk

    from blackchpok_ide import theme, tools_panel
    from blackchpok_ide.agent_tools import ToolRegistry

    root = tk.Tk()
    root.withdraw()
    fonts = theme.Theme(root)
    fonts.apply()

    registry = ToolRegistry(ROOT)
    registry.confirm_commands = False
    results: list[tuple[str, bool]] = []
    panel = tools_panel.ToolsPanel(
        root, fonts, registry,
        on_result=lambda out, ok: results.append((out, ok)),
    )
    root.update()

    panel._toggle("run_command")
    root.update()
    panel._forms["command"].insert(0, "echo panel-test-ok")
    panel.run_tool("run_command")
    pump(root, 4.0)

    check("команда виконалась", len(results) == 1, f"{len(results)}")
    if results:
        check("вивід команди справжній", "panel-test-ok" in results[0][0],
              results[0][0][:80])

    panel.cancel()
    root.destroy()


def test_in_window() -> None:
    """Панель у справжньому вікні IDE."""
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb

    mb.askyesno = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    fd.asksaveasfilename = lambda *a, **k: ""
    fd.askopenfilename = lambda *a, **k: ""
    fd.askdirectory = lambda *a, **k: ""

    from blackchpok_ide.config import Settings, setup_logging
    from blackchpok_ide.main_window import BlackChpokIDE

    setup_logging()
    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.first_run_done = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False

    app = BlackChpokIDE(settings)
    app.geometry("1400x860")
    pump(app, 1.0)

    app.show_side("tools")
    pump(app, 0.6)
    check("панель інструментів видима", app.tools_panel.winfo_ismapped() == 1)
    check("панель знає всі інструменти", len(app.tools_panel._items) >= 11,
          f"{len(app.tools_panel._items)}")

    app._rail_action("tools")
    pump(app, 0.4)
    check("рейка веде на панель інструментів", app._active_side == "tools")

    app.tools_panel.cancel()
    app.rag_panel.cancel()
    app.agent.cancel()
    app.destroy()


def main() -> int:
    test_catalog()
    test_panel_and_call()
    test_run_command_real()
    test_in_window()
    print()
    print("Панель інструментів:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)


# ── unittest-обгортка (додано 10.11.2026) ──────────────────────────────────
# Для `python -m unittest discover` ці перевірки раніше були невидимі:
# файл — скрипт із власним main(), а не TestCase. Тепер discover запускає
# його й падає, якщо main() повернув ненульовий код. Запуск як скрипт
# (`python tests/test_tools_panel.py`) поводиться як раніше.
import unittest as _unittest  # noqa: E402


class _ScriptSuite(_unittest.TestCase):
    def test_script_passes(self) -> None:
        code = main()
        self.assertEqual(code, 0, f"main() повернув {code}")
