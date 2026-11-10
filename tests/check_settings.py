"""Перевірка діалогу налаштувань: кнопка «Зберегти» видима на всіх вкладках."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    import tkinter as tk
    import tkinter.messagebox as mb
    import tkinter.simpledialog as sd
    from tkinter import ttk

    mb.askyesno = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    sd.askstring = lambda *a, **k: None

    from blackchpok_ide import theme
    from blackchpok_ide.config import Settings, setup_logging
    from blackchpok_ide.settings_dialog import SettingsDialog

    setup_logging()
    settings = Settings.load()
    root = tk.Tk()
    root.geometry("900x700")
    fonts = theme.Theme(root)
    fonts.apply()

    dlg = SettingsDialog(root, fonts, settings, on_saved=lambda: None)
    dlg.update()

    def find_buttons(widget, out: list) -> None:
        for child in widget.winfo_children():
            if isinstance(child, ttk.Button) and str(child.cget("text")) == "Зберегти":
                out.append(child)
            find_buttons(child, out)

    buttons: list = []
    find_buttons(dlg, buttons)
    ok = True
    if not buttons:
        print("FAIL: кнопку «Зберегти» не знайдено")
        return 1
    button = buttons[0]

    notebook = None

    def find_notebook(widget) -> None:
        nonlocal notebook
        for child in widget.winfo_children():
            if isinstance(child, ttk.Notebook):
                notebook = child
            find_notebook(child)

    find_notebook(dlg)
    for tab in notebook.tabs():
        notebook.select(tab)
        dlg.update()
        mapped = button.winfo_ismapped()
        y = button.winfo_rooty() - dlg.winfo_rooty()
        title = str(nb := notebook.tab(tab, "text")).strip()
        print(f"  {title:<18} mapped={mapped}  y={y}")
        if not mapped or y < 0 or y > dlg.winfo_height():
            ok = False

    dlg.destroy()
    root.update()
    root.destroy()
    print("Кнопка «Зберегти» видима на всіх вкладках:", "ТАК" if ok else "НІ")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
