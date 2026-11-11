"""Аудит гарячих клавіш: конфлікти, порожні, неможливі.

Дві команди на ту саму комбінацію означають, що одна з них недосяжна —
користувач натискає й отримує не те, що чекав.
"""
from __future__ import annotations

import collections
import os
import pathlib
import re
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


def to_tk(binding: str) -> str:
    """Перетворити «Ctrl+Alt+J» у Tk-послідовність ``<Control-Alt-j>``.

    ``command_registry`` зберігає людський запис, а вікно прив'язує
    Tk-запис. Без цього перетворення аудитор шукав рядок «Ctrl+Alt+J»
    серед прив'язок і не знаходив нічого.
    """
    raw = (binding or "").strip()
    if not raw:
        return ""
    parts = [p for p in re.split(r"[+\-]", raw) if p.strip()]
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
    # Односимвольні клавіші Tk приймає в нижньому регістрі (інакше
    # ``<Control-Shift-P>`` і ``<Control-Shift-p>`` — різні прив'язки).
    if len(key) == 1 and key.isalpha():
        key = key.lower() if not any(m == "Shift" for m in mods) else key.upper()
    return "<" + "-".join([*mods, key]) + ">"


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
    #
    # ВАЖЛИВО: вікно прив'язує клавіші через ``bind_all`` (щоб вони діяли
    # незалежно від того, який віджет у фокусі), а не через ``bind``.
    # Раніше аудитор питав лише ``bind`` і тому оголошував «не знайденими»
    # УСІ 43 клавіші — сигнал, який нічого не означав.
    unbound: list[str] = []
    for canon, key, raw in rows:
        sequence = to_tk(raw)
        found = False
        for probe in (sequence, f"<{sequence}>"):
            for binder in (root.bind_all, root.bind, app.bind):
                try:
                    if binder(probe):
                        found = True
                        break
                except (tk.TclError, AttributeError):
                    continue
            if found:
                break
        if not found:
            unbound.append(key)

    print(f"клавіш, не знайдених серед прив'язок вікна: {len(unbound)}")
    if unbound:
        # Це НЕ провал: частину клавіш вішає редактор або сама система
        # (Alt+F4), частину Tk обслуговує віртуальними подіями. Точну
        # перевірку робить ``tools/audit_keys_consistency.py``.
        print("   " + ", ".join(unbound[:12]))

    app.on_close()
    print(f"\nпровалів: {len(FAILS)}")
    for name in FAILS:
        print("  " + name)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
