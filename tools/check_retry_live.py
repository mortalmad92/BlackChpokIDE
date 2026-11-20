"""Вигляд рядка повторної спроби в журналі роботи.

Запуск:  .venv\\Scripts\\python.exe tools/check_retry_live.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def pump(app, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.02)


def main() -> int:
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb
    import tkinter.simpledialog as sd

    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    sd.askstring = lambda *a, **k: None
    fd.askdirectory = lambda *a, **k: ""

    from blackchpok_ide.agent import AgentEvent
    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()
    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.first_run_done = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False

    from blackchpok_ide.main_window import BlackChpokIDE

    app = BlackChpokIDE(settings)
    app.geometry("1560x940+20+20")
    pump(app, 1.4)
    app.hide_welcome()
    chat = app.chat
    chat.new_chat()
    pump(app, 0.3)

    # Реалістична послідовність: запит → дві невдалі спроби → інструмент.
    chat._handle_event(AgentEvent("status", "Запит до моделі…"))
    chat._handle_event(AgentEvent("llm_retry",
                                  "Повторний запит моделі (1/4) · 2 с",
                                  {"attempt": 1, "total": 4, "wait": 2.0,
                                   "reason": "HTTP 429"}))
    chat._handle_event(AgentEvent("llm_retry",
                                  "Повторний запит моделі (2/4) · 4 с",
                                  {"attempt": 2, "total": 4, "wait": 4.0,
                                   "reason": "HTTP 429"}))
    chat._handle_event(AgentEvent("tool_call", "read_file(file_path=a.py)",
                                  {"call_id": "s1", "name": "read_file",
                                   "arguments": "file_path=a.py"}))
    chat._handle_event(AgentEvent("tool_result", "ок",
                                  {"call_id": "s1", "name": "read_file", "ok": True}))
    pump(app, 1.0)

    log = chat._log
    if log is not None:
        rows = [(r.kind, r.label.cget("text")) for r in log._rows]
        print("рядки журналу:")
        for kind, text in rows:
            print(f"  {kind:10} {text}")
        retries = [r for r in log._rows if r.kind == "retry"]
        print("рядків повтору:", len(retries))
        if retries:
            print("колір першого:", retries[0].label.cget("fg"))
    else:
        print("журнал не створено")

    chat._handle_event(AgentEvent("assistant", "Готово.", {"final": True}))
    chat._handle_event(AgentEvent("done", "", {"ok": True}))
    pump(app, 0.8)
    app.agent.cancel()
    app.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
