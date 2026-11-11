"""Аудит: чи збігаються підписи гарячих клавіш у меню, палітрі й прив'язках.

Користувач бачить у меню «Ctrl+Shift+S», натискає його — і мусить статись
та сама дія, що й у палітрі з тим самим підписом. Розбіжність означає
або мертву клавішу, або дві різні дії на одній комбінації.
"""
from __future__ import annotations

import os
import pathlib
import re
import sys
import tempfile

os.environ.setdefault("BLACKCHPOCK_HOME", tempfile.mkdtemp(prefix="bchk_keys2_"))
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def to_tk(binding: str) -> str:
    """Людський запис → Tk-послідовність без дужок.

    Окремі клавіші мають ІНШІ імена в Tk: ``Enter`` тут означає мишу, а
    клавіша — ``Return``; ``-`` це ``minus``, ``+``/``=`` — ``equal``,
    ``/`` — ``slash``. Без цього перетворення аудитор «не знаходив»
    робочі прив'язки.
    """
    raw = (binding or "").strip()
    if not raw:
        return ""
    # Клавіша-символ може сама бути «-» або «+»: ділимо лише по «+» після
    # першого елемента, тож «Ctrl+-» дає ["Ctrl", "-"], а не ["Ctrl"].
    parts = raw.split("+")
    if parts and parts[-1] == "" and len(parts) > 1:
        parts = parts[:-1] + ["+"]
    mods: list[str] = []
    key = ""
    for part in parts:
        low = part.strip().lower()
        if low in {"ctrl", "control"}:
            mods.append("Control")
        elif low == "alt":
            mods.append("Alt")
        elif low == "shift":
            mods.append("Shift")
        elif low in {"cmd", "super", "meta", "win"}:
            mods.append("Meta")
        else:
            key = part.strip()
    if not key:
        return ""
    if len(key) == 1 and not key.isalnum():
        key = {"-": "minus", "=": "equal", "+": "plus", "/": "slash",
               "`": "grave", ",": "comma", ".": "period"}.get(key, key)
    elif len(key) == 1 and key.isalpha():
        key = key.upper() if "Shift" in mods else key.lower()
    elif key.lower() == "enter":
        key = "Return"
    return "-".join([*mods, key])


def main() -> int:
    import tkinter as tk

    from blackchpok_ide import command_registry, commands
    from blackchpok_ide import main_window as mw
    from blackchpok_ide.config import Settings

    for name in ("showerror", "showinfo", "showwarning"):
        setattr(mw.messagebox, name, lambda *a, **k: None)
    mw.messagebox.askyesno = lambda *a, **k: False

    root = tk.Tk()
    root.withdraw()
    settings = Settings()
    settings.remember_workspace(tempfile.mkdtemp(prefix="bchk_keys2_ws_"))
    app = mw.BlackChpokIDE(settings)
    command_registry.register_all(app)

    registered = {
        str(cmd.key): str(getattr(cmd, "shortcut", "") or "")
        for cmd in commands.all_commands()
    }

    # 1. Кожна комбінація з реєстру справді прив'язана — або у вікні, або
    #    класом ``Text`` (редактор сам обробляє копіювання, вставку,
    #    скасування через віртуальні події Tk), або системою (Alt+F4).
    #
    # Питаємо ``bind_all(sequence)``, а не шукаємо рядок у списку
    # ``bind_all()``: Tk нормалізує запис («<Control-n>» стає
    # «<Control-Key-n>»), і просте порівняння рядків давало хибні «не
    # прив'язано».
    textual = tk.Text(root)          # той самий клас, що в редакторі
    # Дії редактора (Ctrl+G — перехід до рядка, Ctrl+/ — коментар) вішає
    # САМ редактор на свій ``Text``, а не вікно. Тому питаємо і його.
    from blackchpok_ide import editor as editor_module
    from blackchpok_ide import theme as theme_module

    code_editor = editor_module.CodeEditor(root, theme_module.Theme(root))
    editor_widget = code_editor.text
    system_keys = {"Alt+F4"}         # закриття вікна робить сама система
    unbound: list[str] = []
    for key, shortcut in registered.items():
        if not shortcut:
            continue
        if shortcut in system_keys:
            continue
        sequence = f"<{to_tk(shortcut)}>"
        try:
            found = bool(app.bind_all(sequence) or root.bind_all(sequence))
        except Exception:  # noqa: BLE001 - перевірка не має падати
            found = False
        if not found:
            # Чи це дія редактора, яку Tk обслуговує сам?
            try:
                found = bool(textual.bind_class("Text", sequence)) or \
                    bool(textual.bind(sequence))
            except Exception:  # noqa: BLE001
                found = False
        if not found:
            # Чи її прив'язав сам редактор (``<Control-g>`` тощо)?
            try:
                found = bool(editor_widget.bind(sequence))
            except Exception:  # noqa: BLE001
                found = False
        if not found and sequence in {
                f"<{to_tk(s)}>" for s in
                ("Ctrl+Z", "Ctrl+Y", "Ctrl+C", "Ctrl+V", "Ctrl+X")}:
            # Віртуальні події Tk: <Control-Key-c> → <<Copy>> тощо.
            found = True
        if not found:
            unbound.append(f"{key} ({shortcut})")
    check("усі клавіші реєстру прив'язані", not unbound,
          "; ".join(unbound[:6]))

    # 2. Кожен акселератор у меню має відповідну команду.
    source = (ROOT / "blackchpok_ide" / "main_window.py").read_text(encoding="utf-8")
    accelerators = set(re.findall(r'accelerator="([^"]+)"', source))
    known = {str(s) for s in registered.values() if s}
    orphans = sorted(a for a in accelerators if a not in known)
    check("акселератори меню мають команду", not orphans,
          ", ".join(orphans[:8]))

    app.on_close()
    print(f"\nпровалів: {len(FAILS)}")
    for name in FAILS:
        print("  " + name)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
