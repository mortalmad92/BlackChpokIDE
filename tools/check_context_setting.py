"""Перевірка поля «Розмір контексту» в діалозі налаштувань.

Відкриваємо справжній діалог, міняємо значення, зберігаємо й перевіряємо,
що воно дійшло до налаштувань і до плану запуску моделі.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Цей скрипт змінює й зберігає налаштування. Без ізоляції він писав у
# СПРАВЖНІЙ конфіг користувача (%APPDATA%\BlackChpokIDE\settings.json) —
# саме так у ньому опинялись тестові значення, зокрема вимкнений автозапуск
# локальної моделі. Ізолюємо ДО імпорту пакета.
os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchp-ctx-"))
os.environ["BLACKCHPOK_NO_SAVE"] = "1"

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def pump(root, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        try:
            root.update()
        except Exception:  # noqa: BLE001
            return
        time.sleep(0.01)


def main() -> int:
    import tkinter as tk
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb

    mb.askyesno = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    fd.askdirectory = lambda *a, **k: ""

    from blackchpok_ide import hardware as hw, theme
    from blackchpok_ide.config import Settings
    from blackchpok_ide.settings_dialog import SettingsDialog

    root = tk.Tk()
    root.withdraw()
    fonts = theme.Theme(root)
    fonts.apply()

    settings = Settings.load()
    original = int(getattr(settings.engine, "ctx_size", 0) or 0)
    try:
        dialog = SettingsDialog(root, fonts, settings)
        pump(root, 0.4)
        check("діалог відкрився", dialog.winfo_exists() == 1)
        check("поле контексту існує", hasattr(dialog, "ctx_var"),
              "ctx_var")
        check("поле показує поточне значення",
              int(dialog.ctx_var.get()) == original, f"{dialog.ctx_var.get()}")

        # Міняємо на 32768 і зберігаємо
        dialog.ctx_var.set(32768)
        pump(root, 0.2)
        dialog._save()
        pump(root, 0.3)
        saved = Settings.load()
        check("значення збережено", int(saved.engine.ctx_size) == 32768,
              str(saved.engine.ctx_size))

        # І воно справді впливає на план запуску
        profile = hw.detect(ROOT)
        choice = next((c for c in hw.MODEL_CATALOG
                       if "14b" in c.filename.lower()), hw.MODEL_CATALOG[0])
        plan = hw.fit(profile, choice,
                      target_ctx=int(saved.engine.ctx_size)).plan
        check("план враховує збережений контекст", plan.ctx_size == 32768,
              f"{plan.ctx_size} · {plan.summary()}")
        check("великий контекст використовує RAM",
              plan.kv_in_ram and "--no-kv-offload" in plan.args(),
              plan.summary())

        # Нуль означає «авто»
        dialog2 = SettingsDialog(root, fonts, settings)
        pump(root, 0.3)
        dialog2.ctx_var.set(0)
        dialog2._save()
        pump(root, 0.3)
        check("нуль зберігається як авто",
              int(Settings.load().engine.ctx_size) == 0,
              str(Settings.load().engine.ctx_size))
        auto_plan = hw.fit(profile, choice, target_ctx=0).plan
        check("авто не йде в повільний режим RAM", not auto_plan.kv_in_ram,
              auto_plan.summary())
    finally:
        # Повертаємо як було
        try:
            settings.engine.ctx_size = original
            settings.save()
        except Exception:  # noqa: BLE001
            pass
        try:
            root.destroy()
        except Exception:  # noqa: BLE001
            pass

    print()
    print("Налаштування контексту:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
