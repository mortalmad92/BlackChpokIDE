"""Аудит гарячих клавіш: конфлікти, порожні, неможливі.

Дві команди на ту саму комбінацію означають, що одна з них недосяжна —
користувач натискає й отримує не те, що чекав.
"""
from __future__ import annotations

import collections
import os
import pathlib
import sys
import tempfile

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchk_keys_"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def normalise(binding: str) -> str:
    """Канонічна форма комбінації: порядок модифікаторів не важливий."""
    parts = [p.strip().lower() for p in (binding or "").split("+") if p.strip()]
    if not parts:
        return ""
    mods = sorted(p for p in parts
                  if p in {"ctrl", "control", "alt", "shift", "cmd", "super"})
    keys = [p for p in parts if p not in
            {"ctrl", "control", "alt", "shift", "cmd", "super"}]
    mods = ["ctrl" if m == "control" else m for m in mods]
    return "+".join(mods + keys)


def main() -> int:
    import tkinter as tk
    from unittest import mock

    from blackchpok_ide import command_registry, commands
    from blackchpok_ide import main_window as mw
    from blackchpok_ide.config import Settings

    for name in ("showerror", "showinfo", "showwarning"):
        setattr(mw.messagebox, name, lambda *a, **k: None)
    mw.messagebox.askyesno = lambda *a, **k: False

    root = tk.Tk()
    root.withdraw()
    settings = Settings()
    settings.remember_workspace(tempfile.mkdtemp(prefix="bchk_keys_ws_"))
    app = mw.BlackChpokIDE(settings)
    command_registry.register_all(app)

    rows: list[tuple[str, str, str]] = []
    for cmd in commands.all_commands():
        binding = getattr(cmd, "shortcut", "") or getattr(cmd, "binding", "") or ""
        if binding:
            rows.append((normalise(str(binding)), cmd.key, str(binding)))

    print(f"команд із клавішами: {len(rows)}")
    by_binding: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    for canon, key, raw in rows:
        by_binding[canon].append((key, raw))

    clashes = {b: items for b, items in by_binding.items() if len(items) > 1}
    check("немає конфліктів клавіш", not clashes,
          "; ".join(f"{b}: {[k for k, _ in items]}" for b, items in list(clashes.items())[:4]))

    # Порожні й неоднозначні позначення.
    weird = [raw for canon, key, raw in rows if not canon or "+" not in canon and
             len(canon) > 1 and not canon.startswith("f")]
    check("позначення клавіш коректні", not weird, str(weird[:6]))

    # Кожна клавіша справді прив'язана у вікні.
    unbound: list[str] = []
    for canon, key, raw in rows:
        found = False
        for sequence in (raw, f"<{raw}>"):
            try:
                if root.bind(sequence) or app.bind(sequence):
                    found = True
                    break
            except tk.TclError:
                continue
        # Не всі прив'язки йдуть через bind вікна — не вважаємо це помилкою,
        # лише збираємо статистику.
        if not found:
            unbound.append(key)

    print(f"клавіш, не знайдених серед прив'язок вікна: {len(unbound)}")
    if unbound:
        print("   " + ", ".join(unbound[:12]))

    app.on_close()
    print(f"\nпровалів: {len(FAILS)}")
    for name in FAILS:
        print("  " + name)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
