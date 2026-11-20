"""Вигляд журналу після завершення: кроки мають згорнутись самі.

Запуск:  .venv\\Scripts\\python.exe tools/check_log_collapse.py
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import theme, work_log  # noqa: E402

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def rows_shown(log) -> bool:
    """Чи рядки журналу справді в компонуванні (не залежить від видимості вікна)."""
    try:
        return bool(log.rows_host.winfo_manager())
    except tk.TclError:
        return False


def main() -> int:
    root = tk.Tk()
    root.geometry("800x600+20+20")
    fonts = theme.Theme(root, "", 13)
    log = work_log.WorkLog(root, fonts, wrap_width=600)
    log.pack(fill="x")
    log.begin("Аналіз запиту")
    row = log.add_tool("read_file", 'file_path=tests/run_all.py', call_id="c1")
    log.finish_tool("c1", ok=True)
    log.add_tool("run_command", 'command=python tests/run_all.py', call_id="c2")
    log.finish_tool("c2", ok=False)
    log.add_tool("find_text", 'query=термін', call_id="c3")
    log.finish_tool("c3", ok=True)
    root.update()

    check("під час роботи розгорнуто", log._expanded is True)
    check("рядки в компонуванні", rows_shown(log) is True)
    log.finish(ok=True)
    root.update()

    check("після завершення згорнуто", log._expanded is False)
    check("стрілка показує згорнуто", log.arrow.cget("text") == "▸",
          log.arrow.cget("text"))
    check("рядки прибрано з компонування", rows_shown(log) is False)
    summary = [r for r in log._rows if r.kind == work_log.KIND_SUMMARY]
    check("підсумок додано", len(summary) == 1)
    text = summary[0].label.cget("text") if summary else ""
    check("у підсумку є кількість кроків", "3 кроки" in text, text)
    check("підсумок українською", "Аналіз завершено" in text, text)

    # Користувач може розгорнути назад.
    log.toggle()
    root.update()
    check("шеврон розгортає", log._expanded is True)
    check("рядки знову в компонуванні", rows_shown(log) is True)

    # Якщо користувач сам згорнув ДО завершення — не чіпаємо його вибір.
    log2 = work_log.WorkLog(root, fonts, wrap_width=600)
    log2.pack(fill="x")
    log2.begin("Другий")
    log2.add_tool("read_file", "file_path=a.py", call_id="x")
    log2.finish_tool("x", ok=True)
    log2.toggle()                     # користувач згорнув сам
    root.update()
    log2.finish(ok=True)
    root.update()
    check("вибір користувача не скасовано", log2._expanded is False)

    root.destroy()
    print()
    print("Згортання журналу:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
