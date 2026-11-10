"""Скриншоти майстра першого запуску (усі кроки).

Запуск: python tests/screenshot_wizard.py [тека]
За замовчуванням знімки йдуть у assets/:
    wizard_hardware.png, wizard_libs.png, wizard_tools.png, wizard_model.png
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def pump(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def shoot(widget, target: Path) -> bool:
    """Знімок вікна через Pillow (піднявши його поверх усього)."""
    try:
        from PIL import ImageGrab
    except ImportError:
        print("Pillow недоступний — знімок пропущено.")
        return False
    try:
        widget.attributes("-topmost", True)
    except Exception:  # noqa: BLE001
        pass
    for _ in range(4):
        widget.update_idletasks()
        widget.update()
        time.sleep(0.1)
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    w, h = widget.winfo_width(), widget.winfo_height()
    if w < 2 or h < 2:
        print(f"вікно без розміру ({w}x{h})")
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    image = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    image.save(target)
    print(f"Знімок: {target} ({w}x{h})")
    return True


def main() -> int:
    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()
    settings = Settings.load()
    settings.workspace = str(ROOT)

    import tkinter as tk

    from blackchpok_ide import theme
    from blackchpok_ide.first_run import FirstRunWizard

    root = tk.Tk()
    root.geometry("900x760+20+10")
    root.deiconify()
    fonts = theme.Theme(root, "", 13)
    fonts.apply()

    wizard = FirstRunWizard(root, fonts, settings)
    wizard.geometry("680x640+80+40")
    wizard.deiconify()
    wizard.lift()
    # Дати визначенню заліза й перевірці середовища завершитись.
    pump(root, 3.2)

    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "assets"
    for step, name in (("hardware", "wizard_hardware.png"),
                       ("libs", "wizard_libs.png"),
                       ("tools", "wizard_tools.png"),
                       ("model", "wizard_model.png")):
        wizard.show_step(step)
        pump(root, 0.7)
        shoot(wizard, out_dir / name)

    try:
        wizard.on_close_cleanup()
        wizard.destroy()
        root.destroy()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
