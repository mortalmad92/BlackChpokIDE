"""Живий прогін: справжній агент (офлайн-роутер) малює журнал у чаті."""

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
    settings.agent.offline_fallback = True

    app = BlackChpokIDE(settings)
    app.geometry("1400x880")
    pump(app, 1.0)

    app.agent.llm_settings.model = ""
    app.chat._send("покажи файли")
    pump(app, 4.0)

    log = app.chat._log
    # Журнал міг завершитись і відчепитись — тоді шукаємо картку журналу.
    found = log
    if found is None:
        for card in app.chat._cards:
            candidate = getattr(card, "log", None)
            if candidate is not None:
                found = candidate
                break

    check("журнал створено під час роботи", found is not None)
    if found is not None:
        kinds = [row.kind for row in found._rows]
        texts = [row.label.cget("text") for row in found._rows]
        print("\n   Рядки журналу:")
        for row in found._rows:
            target = row.target.cget("text")
            print(f"   · [{row.kind}] {row.label.cget('text')} {target}")
        check("у журналі є крок інструмента", "tool" in kinds, str(kinds))
        check("журнал завершено", found.running is False)
        check("у заголовку є таймер", bool(found.timer_label.cget("text")),
              found.timer_label.cget("text"))
        check("рядки мають людські підписи",
              any(t in ("Дивиться теку", "Читає", "Шукає") for t in texts),
              str(texts))

    app.agent.cancel()
    app.destroy()
    print()
    print("Живий журнал:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)
