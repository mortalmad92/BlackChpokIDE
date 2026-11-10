"""Перевірка діалогу налаштувань: підказки, списки, збереження.

Окремий скрипт, бо діалог налаштувань — найбільше місце, де користувач
шукає «налаштування зберігаються і редагуються». Тут перевіряється:

* кожен інтерактивний елемент має підказку;
* жоден Combobox не порожній (порожній список виглядає як зламаний);
* зміни справді записуються в ``Settings`` і переживають повторне читання.

Запуск::

    python tools/check_settings_dialog.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import ttk

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchp-ui-check-"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def walk(widget: tk.Misc):
    yield widget
    for child in widget.winfo_children():
        try:
            yield from walk(child)
        except tk.TclError:
            continue


def _label(widget: tk.Misc) -> str:
    try:
        return str(widget.cget("text") or "").strip()
    except (tk.TclError, AttributeError):
        return ""


def _has_tip(widget: tk.Misc) -> bool:
    try:
        return bool(widget.bind("<Enter>"))
    except tk.TclError:
        return False


def main() -> int:
    from blackchpok_ide import config, main_window, settings_dialog

    settings = config.Settings()
    settings.workspace = str(ROOT)
    settings.project_chosen = True
    settings.engine.auto_start = False
    app = main_window.BlackChpokIDE(settings=settings)
    app.update_idletasks()
    app.update()

    dialog = settings_dialog.SettingsDialog(app, app.theme, app.settings)
    for _ in range(10):
        dialog.update_idletasks()
        dialog.update()

    problems = 0
    no_tip = [
        _label(w) for w in walk(dialog)
        if isinstance(w, (ttk.Button, tk.Button, ttk.Checkbutton,
                          tk.Checkbutton, tk.Radiobutton)) and not _has_tip(w)
    ]
    empty = [
        w.winfo_name() for w in walk(dialog)
        if isinstance(w, ttk.Combobox) and not list(w["values"] or ())
    ]
    print(f"Без підказки: {len(no_tip)}")
    for item in no_tip[:15]:
        print("  ·", item)
    print(f"Порожні списки: {len(empty)} {empty}")
    problems += len(no_tip) + len(empty)

    # ── збереження: зміна в діалозі має дійти до Settings ────────────────
    dialog.temp_var.set(1.35)
    dialog.native_enabled_var.set(True)
    try:
        dialog._save()
    except Exception as exc:              # noqa: BLE001 - показуємо причину
        print("Збереження впало:", type(exc).__name__, exc)
        problems += 1
    else:
        saved = config.Settings.load()
        if abs(float(saved.llm.temperature) - 1.35) > 0.001:
            print("НЕ збережено: temperature =", saved.llm.temperature)
            problems += 1
        else:
            print("Збереження працює: temperature =", saved.llm.temperature)
        if not saved.engine.native:
            print("НЕ збережено: engine.native =", saved.engine.native)
            problems += 1
        else:
            print("Збереження працює: engine.native =", saved.engine.native)

    try:
        dialog.destroy()
    except tk.TclError:
        pass
    app.destroy()
    print("Усього проблем:", problems)
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
