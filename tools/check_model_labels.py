"""Діагностика: які підписи моделі показує вікно і звідки вони беруться.

Питання користувача: «чому вибрані дві різні моделі?». Скрипт будує
справжнє вікно IDE і друкує КОЖЕН підпис моделі з джерелом.

Запуск: python tools/check_model_labels.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

os.environ.setdefault("BLACKCHPOK_HOME",
                      tempfile.mkdtemp(prefix="bchp-labels-"))


def collect_text(widget, depth: int = 0) -> list[str]:
    found: list[str] = []
    if depth > 9:
        return found
    for child in widget.winfo_children():
        try:
            text = str(child.cget("text"))
        except Exception:  # noqa: BLE001
            text = ""
        if text:
            found.append(text)
        found.extend(collect_text(child, depth + 1))
    return found


def main() -> int:
    import tkinter as tk

    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()
    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.project_chosen = True
    settings.first_run_done = True
    settings.engine.auto_start = False

    print("=== Джерела істини (settings.json) ===")
    print(f"llm.model          = {settings.llm.model!r}")
    print(f"engine.model_path  = {settings.engine.model_path!r}")
    print(f"llm.base_url       = {settings.llm.base_url!r}")

    from pathlib import Path as _Path

    from blackchpok_ide import providers

    entry = providers.current_entry(settings)
    print(f"providers.current_entry().name = {entry.name!r}")

    app = None
    try:
        from blackchpok_ide.main_window import BlackChpokIDE

        app = BlackChpokIDE(settings)
        app.update_idletasks()
        app.update()
    except tk.TclError as exc:
        print(f"[SKIP] Немає дисплея: {exc}")
        return 0

    print("\n=== Підписи моделі в РЕАЛЬНИХ віджетах ===")
    rows: list[tuple[str, str]] = []

    bar = getattr(app, "header_bar", None)
    if bar is not None:
        for attr in ("model_btn", "model_status", "_model"):
            widget = getattr(bar, attr, None)
            if widget is None:
                continue
            if isinstance(widget, str):
                rows.append((f"header_bar.{attr} (поле)", widget))
                continue
            try:
                rows.append((f"header_bar.{attr}", str(widget.cget("text"))))
            except Exception:  # noqa: BLE001
                pass

    header = getattr(app, "header", None)
    if header is not None:
        for attr in ("model_label", "model_btn", "model"):
            widget = getattr(header, attr, None)
            if widget is None:
                continue
            if isinstance(widget, str):
                rows.append((f"session_header.{attr} (поле)", widget))
                continue
            try:
                rows.append((f"session_header.{attr}", str(widget.cget("text"))))
            except Exception:  # noqa: BLE001
                pass

    chat = getattr(app, "chat", None)
    if chat is not None:
        rows.append(("chat.chat_model", str(getattr(chat, "chat_model", ""))))
        rows.append(("chat._model_label_text",
                     str(getattr(chat, "_model_label_text", ""))))
        button = getattr(chat, "model_button", None)
        if button is not None:
            try:
                rows.append(("chat.model_button", str(button.cget("text"))))
            except Exception:  # noqa: BLE001
                pass

    for source, text in rows:
        print(f"  {source:34s} = {text!r}")

    # Будь-який підпис, що згадує модель, у всьому дереві вікна.
    print("\n=== Усі підписи з назвою моделі у вікні ===")
    needles = ("14B", "14b", "Ministral", "qwen", "Qwen")
    seen: set[str] = set()
    for text in collect_text(app):
        if any(needle in text for needle in needles) and text not in seen:
            seen.add(text)
            print(f"  {text!r}")

    # Чи розходяться джерела?
    print("\n=== Висновок ===")
    names = {text for _src, text in rows
             if any(needle in text for needle in needles)}
    print(f"різних підписів моделі: {len(names)}")
    for text in sorted(names):
        print(f"  • {text}")

    try:
        app.destroy()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
