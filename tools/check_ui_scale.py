"""Перевірка поля «Масштаб інтерфейсу» в діалозі налаштувань.

Запуск:  .venv\\Scripts\\python.exe tools/check_ui_scale.py
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import theme  # noqa: E402
from blackchpok_ide.config import Settings  # noqa: E402
from blackchpok_ide.settings_dialog import SettingsDialog  # noqa: E402

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def main() -> int:
    root = tk.Tk()
    root.withdraw()
    fonts = theme.Theme(root, "", 13)
    settings = Settings.load()
    settings.ui.ui_scale = 1.0
    settings.ui.font_size = 13

    dialog = SettingsDialog(root, fonts, settings)
    root.update_idletasks()

    check("поле масштабу існує", hasattr(dialog, "scale_var"))
    check("типове значення 1.0", abs(float(dialog.scale_var.get()) - 1.0) < 0.001,
          str(dialog.scale_var.get()))

    # Ставимо 1.25 і зберігаємо через той самий шлях, що й кнопка «Зберегти».
    dialog.scale_var.set("1.25")
    dialog.size_var.set("14")
    dialog._apply_fields()
    check("масштаб записано в налаштування",
          abs(float(settings.ui.ui_scale) - 1.25) < 0.001, str(settings.ui.ui_scale))
    check("розмір шрифту записано", int(settings.ui.font_size) == 14,
          str(settings.ui.font_size))

    # Той самий масштаб має дійти до шрифтів.
    before = fonts.ui.actual("size")
    fonts.set_family("", 14, scale=settings.ui.ui_scale)
    after = fonts.ui.actual("size")
    check("шрифт інтерфейсу виріс", after > before, f"{before} → {after}")

    # Перевірка меж: безглузде значення не має ламати вікно.
    settings.ui.ui_scale = 99.0
    settings.ui.normalise()
    check("завеликий масштаб підрізано", settings.ui.ui_scale <= 1.75,
          str(settings.ui.ui_scale))
    settings.ui.ui_scale = 0.1
    settings.ui.normalise()
    check("замалий масштаб піднято", settings.ui.ui_scale >= 0.85,
          str(settings.ui.ui_scale))

    try:
        dialog.destroy()
    except tk.TclError:
        pass
    root.destroy()
    print()
    print("Масштаб інтерфейсу:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
