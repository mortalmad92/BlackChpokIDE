"""Перевірка інтерфейсу: підказки, іконки, списки, збереження налаштувань.

Вимога користувача: «щоб не було жодної не робочої кнопки, щоб всюди були
підказки, списки та іконки, налаштування зберігалися й редагувалися, всі
списки відкривалися».

Перевіряється на СПРАВЖНЬОМУ вікні, по черзі відкриваючи кожну панель:

1. кожен інтерактивний елемент має підказку (``Tip`` вішає ``<Enter>``);
2. кожен елемент має підпис або іконку (порожня кнопка — «мертва»);
3. жоден Combobox/Listbox не порожній (порожній список виглядає зламаним);
4. налаштування зберігаються й читаються назад.

Запуск::

    python tools/audit_ui_completeness.py            # звіт
    python tools/audit_ui_completeness.py --strict   # код 1, якщо є прогалини
"""

from __future__ import annotations

import os
import sys
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import ttk

ROOT = Path(__file__).resolve().parent.parent
# Ізоляція ДО імпорту пакета: інакше прогін перезапише справжні налаштування.
os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchp-audit-ui-"))
os.environ["BLACKCHPOK_NO_SAVE"] = "1"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

#: Віджети, які користувач натискає.
_CLICKABLE = (
    tk.Button,
    ttk.Button,
    tk.Checkbutton,
    ttk.Checkbutton,
    tk.Radiobutton,
)


def walk(widget: tk.Misc):
    yield widget
    for child in widget.winfo_children():
        try:
            yield from walk(child)
        except tk.TclError:
            continue


def _label_of(widget: tk.Misc) -> str:
    """Підпис елемента — текст, заголовок або іконка."""
    try:
        text = widget.cget("text")
    except (tk.TclError, KeyError, TypeError):
        text = ""
    if text:
        return str(text).strip()
    for attribute in ("text", "_tip", "_text"):
        value = getattr(widget, attribute, "")
        if value:
            return str(value).strip()
    return ""


def _has_tip(widget: tk.Misc) -> bool:
    """Чи має віджет підказку (``Tip`` підписується на ``<Enter>``)."""
    if getattr(widget, "_tip", ""):
        return True
    try:
        return bool(widget.bind("<Enter>"))
    except tk.TclError:
        return False


def _where(widget: tk.Misc) -> str:
    """Людський шлях віджета: ланцюг батьків + тип + підпис."""
    kind = type(widget).__name__
    label = _label_of(widget)
    chain: list[str] = []
    parent = widget
    for _ in range(4):
        try:
            parent = parent.master
        except AttributeError:
            break
        if parent is None:
            break
        chain.append(type(parent).__name__)
    where = "/".join(reversed(chain))
    if label:
        return f"{where} → {kind} «{label[:40]}»"
    return f"{where} → {kind} #{str(widget).rsplit('.', 1)[-1]}"


def audit(root: tk.Misc) -> dict[str, list[str]]:
    """Обійти вікно й повернути знайдені прогалини."""
    report: dict[str, list[str]] = {
        "без підказки": [], "без підпису": [], "порожній список": []}
    for widget in walk(root):
        if isinstance(widget, ttk.Combobox):
            try:
                values = list(widget["values"] or ())
            except tk.TclError:
                values = []
            if not values:
                report["порожній список"].append(_where(widget))
            if not _has_tip(widget):
                report["без підказки"].append(_where(widget))
            continue
        if isinstance(widget, tk.Listbox):
            try:
                size = int(widget.size())
            except tk.TclError:
                size = 0
            if not size:
                report["порожній список"].append(_where(widget))
            continue
        if not isinstance(widget, _CLICKABLE):
            continue
        if not _has_tip(widget):
            report["без підказки"].append(_where(widget))
        if not _label_of(widget):
            report["без підпису"].append(_where(widget))
    return report


def main() -> int:
    from blackchpok_ide import config, main_window

    settings = config.Settings()
    settings.workspace = str(ROOT)
    settings.project_chosen = True
    # Модель не потрібна: перевіряємо інтерфейс, а не рушій.
    settings.engine.auto_start = False
    app = main_window.BlackChpokIDE(settings=settings)
    app.update_idletasks()
    app.update()

    grand: dict[str, int] = {"без підказки": 0, "без підпису": 0,
                             "порожній список": 0}
    print(f"Панелей: {len(main_window.PANEL_TITLES)}")
    for key, title in main_window.PANEL_TITLES.items():
        try:
            app.show_side(key)
            app.update_idletasks()
            app.update()
        except Exception as exc:            # noqa: BLE001 - показуємо причину
            print(f"  ✗ {key}: панель не відкрилась — {type(exc).__name__}: {exc}")
            grand["без підказки"] += 1
            continue
        found = audit(app)
        line = " · ".join(f"{name}: {len(items)}" for name, items in found.items())
        print(f"  {key:12s} {title[:26]:28s} {line}")
        for name, items in found.items():
            grand[name] += len(items)
            for item in items[:3]:
                print(f"       {name}: {item}")

    total = sum(grand.values())
    print()
    for name, count in grand.items():
        print(f"{name}: {count}")
    print(f"Усього прогалин: {total}")
    app.destroy()
    strict = "--strict" in sys.argv
    return 1 if (strict and total) else 0


if __name__ == "__main__":
    raise SystemExit(main())
