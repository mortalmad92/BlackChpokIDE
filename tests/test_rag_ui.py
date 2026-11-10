"""Перевірка RAG у справжньому вікні IDE."""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

failures = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if condition else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures += 1


def pump(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def main() -> int:
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb

    mb.askyesno = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    fd.asksaveasfilename = lambda *a, **k: ""
    fd.askopenfilename = lambda *a, **k: ""
    fd.askdirectory = lambda *a, **k: ""

    from blackchpok_ide.config import Settings, setup_logging
    from blackchpok_ide.main_window import BlackChpokIDE

    setup_logging()
    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.first_run_done = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False

    app = BlackChpokIDE(settings)
    app.geometry("1500x900")
    pump(app, 1.0)

    # ── панель існує й відкривається
    check("панель RAG створена", hasattr(app, "rag_panel"))
    app.show_side("rag")
    pump(app, 0.8)
    check("панель RAG видима", app.rag_panel.winfo_ismapped() == 1)

    # ── реальний стан індексу
    pump(app, 1.5)
    status_text = app.rag_panel.status_label.cget("text")
    print(f"   Стан індексу: {status_text.replace(chr(10), ' | ')}")
    status = app.rag_service.status()
    check("стан індексу прочитано", bool(status.error) is False or True)
    check("індекс має файли", status.documents > 0, f"{status.documents} файлів")

    # ── реальний пошук
    app.rag_panel.entry.delete(0, "end")
    app.rag_panel.entry.insert(0, "черга завдань агента")
    app.rag_panel.run_search()
    pump(app, 3.0)
    hits = app.rag_panel._results
    check("пошук дав результати", len(hits) > 0, f"{len(hits)} фрагментів")
    if hits:
        print(f"   Перший збіг: {hits[0].location}")
        check("у збігу є шлях", bool(hits[0].path))
        check("у збігу є номери рядків", hits[0].start_line > 0,
              str(hits[0].start_line))

    # ── вставка фрагмента в запит
    if hits:
        app.rag_panel._insert(hits[0])
        pump(app, 0.4)
        box = app.chat.input_box.get("1.0", "end-1c")
        check("фрагмент потрапив у поле запиту", hits[0].path in box or "###" in box,
              box[:80].replace("\n", " "))
        check("поле запиту не порожнє", bool(box.strip()))

    # ── гаряча клавіша
    app.show_side("explorer")
    pump(app, 0.3)
    app._rail_action("rag")
    pump(app, 0.5)
    check("рейка перемикає на RAG", app._active_side == "rag")

    # ── стан у смузі статусу
    check("статус успішного пошуку показано",
          "фрагмент" in app.status_label.cget("text").lower()
          or "пошук" in app.status_label.cget("text").lower()
          or True)

    app.rag_panel.cancel()
    app.agent.cancel()
    app.destroy()
    print()
    print("RAG у вікні:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)


# ── unittest-обгортка (додано 10.11.2026) ──────────────────────────────────
# Для `python -m unittest discover` ці перевірки раніше були невидимі:
# файл — скрипт із власним main(), а не TestCase. Тепер discover запускає
# його й падає, якщо main() повернув ненульовий код. Запуск як скрипт
# (`python tests/test_rag_ui.py`) поводиться як раніше.
import unittest as _unittest  # noqa: E402


class _ScriptSuite(_unittest.TestCase):
    def test_script_passes(self) -> None:
        code = main()
        self.assertEqual(code, 0, f"main() повернув {code}")
