"""Профіль панелі контексту: яка секція дорога."""

from __future__ import annotations

import cProfile
import io
import pstats
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

    panel = ContextPanel(root, fonts, lambda: ROOT)
    panel.pack(fill="both", expand=True)
    root.update()

    sections = [
        ("_refresh_agent", panel._refresh_agent),
        ("_refresh_project", panel._refresh_project),
        ("_refresh_tools", panel._refresh_tools),
        ("_refresh_tabs", panel._refresh_tabs),
        ("_refresh_changes", panel._refresh_changes),
        ("_refresh_files", panel._refresh_files),
    ]
    print("кожна секція окремо (мс, середнє з 2, ПРОГРІТИЙ кеш):")
    totals: list[tuple[float, str]] = []
    for label, action in sections:
        action()                      # прогрів кешу
        root.update()
        started = time.perf_counter()
        for _ in range(2):
            action()
            root.update()
        spent = (time.perf_counter() - started) / 2 * 1000
        totals.append((spent, label))
        print(f"  {spent:8.2f}  {label}")

    started = time.perf_counter()
    for _ in range(5):
        panel.refresh()
        root.update()
    full = (time.perf_counter() - started) / 5 * 1000
    print(f"\n  {full:8.2f}  refresh() повністю (середнє з 5, прогрітий)")

    # Холодний старт — окремо: скільки коштує ПЕРШЕ наповнення
    panel.invalidate()
    started = time.perf_counter()
    panel.refresh()
    root.update()
    cold = (time.perf_counter() - started) * 1000
    print(f"  {cold:8.2f}  refresh() холодний (перший раз після старту)")

    print("\nпрофіль refresh():")
    pr = cProfile.Profile()
    pr.enable()
    for _ in range(2):
        panel.refresh()
    pr.disable()
    buf = io.StringIO()
    pstats.Stats(pr, stream=buf).sort_stats("tottime").print_stats(12)
    for line in buf.getvalue().splitlines():
        if any(word in line for word in ("blackchpok", "ncalls", "tottime")):
            print("  " + line)

    root.destroy()

    totals.sort(reverse=True)
    print(f"\nнайдорожча секція: {totals[0][1]} ({totals[0][0]:.1f} мс)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
