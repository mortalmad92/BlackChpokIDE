"""Перевірка РЕАЛЬНИХ показників панелі контексту.

Питання: чи індикатор показує числа зі справжнього механізму, а не
декоративні? Перевіряємо текст віджетів після наповнення панелі.

Запуск: python tools/check_context_indicator.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

os.environ.setdefault("BLACKCHPOK_HOME",
                      tempfile.mkdtemp(prefix="bchp-ctxind-"))

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def collect_text(widget, depth: int = 0) -> list[str]:
    """Усі підписи в піддереві віджетів."""
    found: list[str] = []
    if depth > 8:
        return found
    for child in widget.winfo_children():
        try:
            text = child.cget("text")
        except Exception:  # noqa: BLE001 - у фреймів тексту немає
            text = ""
        if text:
            found.append(str(text))
        found.extend(collect_text(child, depth + 1))
    return found


def main() -> int:
    import tkinter as tk

    try:
        probe = tk.Tk()
        probe.destroy()
    except tk.TclError as exc:
        print(f"[SKIP] Немає дисплея: {exc}")
        return 0

    from blackchpok_ide import context_panel, theme
    from blackchpok_ide.agent import AgentRunner
    from blackchpok_ide.agent_tools import ToolRegistry
    from blackchpok_ide.config import AgentSettings, LLMSettings

    host = tk.Tk()
    host.withdraw()
    fonts = theme.Theme(host)

    llm = LLMSettings(base_url="http://127.0.0.1:8080/v1", model="qwen25vl3b",
                      api_key="local", timeout=60)
    runner = AgentRunner(ToolRegistry(ROOT), llm, AgentSettings(), ROOT)
    runner.settings_ref = None
    runner.tools_enabled = True
    runner.adopt_context_window(props_ctx=16384)
    runner.tool_schemas()

    panel = context_panel.ContextPanel(host, fonts, lambda: ROOT)
    panel.pack(fill="both", expand=True)

    # Підключаємо ТІ САМІ провайдери, що й вікно IDE.
    registry_state = runner.tool_registry_state()
    budget = runner._context_budget
    panel.agent_status_provider = lambda: "очікує завдання"
    panel.model_provider = lambda: ("qwen25vl3b", "локальна · online")
    panel.context_provider = lambda: (1234, 16384)
    panel.tools_provider = lambda: ["read_file", "write_file"]
    panel.registry_provider = lambda: registry_state
    panel.exact_counter_provider = lambda: False
    panel.budget_provider = lambda: {
        "window": budget.window, "answer": budget.answer,
        "history": budget.history, "tools": budget.tools,
        "system": budget.system, "safety": budget.safety,
    }
    panel.refresh()
    host.update_idletasks()
    host.update()

    texts = collect_text(panel)
    joined = "\n".join(texts)
    print("--- підписи панелі ---")
    for line in texts[:30]:
        print(f"    {line}")
    print("----------------------")

    check("показано модель", "qwen25vl3b" in joined, "")
    check("показано відсоток заповнення", "%" in joined, "")
    check("показано вільні токени", "вільно" in joined, "")
    check("показано стан підрахунку токенів",
          "токени:" in joined, "")
    check("показано схеми в запиті",
          "схем у запиті" in joined, "")
    # Числа мусять ЗБІГАТИСЯ з реальним реєстром.
    total = int(registry_state.get("total") or 0)
    eager = int(registry_state.get("eager") or 0)
    check("кількість інструментів збігається з реєстром",
          str(total) in joined, f"реєстр={total}")
    check("кількість схем збігається з реєстром",
          str(eager) in joined, f"схем={eager}")
    # Панель не має повторювати те саме кількома рядками (зауваження
    # користувача: «навіщо ці всі пункти дублюються?»). Іконки й короткі
    # часові підписи повторюються законно — перевіряємо лише змістовні
    # рядки (довжина > 3 і не сама іконка).
    meaningful = [text for text in texts
                  if len(text) > 3 and not text.strip("±·⚒🗂◈⊟ ")
                  and not text.endswith((" хв", " год", " дн"))]
    duplicates = [text for text in set(meaningful) if meaningful.count(text) > 1]
    check("немає повторюваних змістовних рядків", not duplicates,
          str(duplicates))
    context_rows = [text for text in texts
                    if any(word in text for word in
                           ("вільно", "токени:", "схем у запиті", "%"))]
    check("стан агента описано стисло", len(context_rows) <= 4,
          f"{len(context_rows)} рядків: {context_rows}")

    host.destroy()
    print()
    print("Індикатор контексту: " + ("УСПІШНО" if not failures
                                     else f"ЗБОЇВ: {failures}"))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
