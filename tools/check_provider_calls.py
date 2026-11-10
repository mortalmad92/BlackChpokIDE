"""Чи викликаються провайдери панелі на кожне оновлення (і скільки це коштує)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    import tkinter as tk

    from blackchpok_ide import theme
    from blackchpok_ide.context_panel import ContextPanel

    root = tk.Tk()
    root.geometry("400x900")
    fonts = theme.Theme(root)
    fonts.apply()

    calls = {"model": 0, "status": 0, "tools": 0, "ctx": 0}

    def slow_model():
        calls["model"] += 1
        time.sleep(0.2)              # імітуємо мережевий запит
        return ("qwen2.5-coder", "локальна · online")

    def status():
        calls["status"] += 1
        return "працює"

    def tools():
        calls["tools"] += 1
        return ["read_file", "write_file"]

    def ctx():
        calls["ctx"] += 1
        time.sleep(0.05)             # імітуємо читання статистики
        return (100, 16384)

    panel = ContextPanel(root, fonts, lambda: ROOT)
    panel.model_provider = slow_model
    panel.agent_status_provider = status
    panel.tools_provider = tools
    panel.context_provider = ctx
    panel.pack(fill="both", expand=True)
    root.update()
    panel.refresh()
    root.update()
    calls.update({key: 0 for key in calls})

    rounds = 5
    started = time.perf_counter()
    for _ in range(rounds):
        panel.refresh()
    spent = (time.perf_counter() - started) / rounds * 1000
    print(f"refresh() сер.: {spent:.1f} мс")
    print(f"викликів провайдерів за {rounds} оновлень: {calls}")
    print()
    if calls["model"] > 1:
        print("ПРОБЛЕМА: провайдер моделі викликається на КОЖНЕ оновлення —")
        print("а він робить мережевий запит до сервера. Це і є гальмо.")
    else:
        print("Гаразд: провайдери не смикаються, коли стан не змінився.")

    root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
