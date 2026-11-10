"""Знімки нових панелей: RAG, інструменти, стрімінг."""

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


def pump(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def grab(widget, target: Path) -> bool:
    try:
        from PIL import ImageGrab
    except ImportError:
        return False
    widget.update_idletasks()
    widget.update()
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    w, h = widget.winfo_width(), widget.winfo_height()
    if w < 2 or h < 2:
        print(f"{widget} без розміру {w}x{h}")
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    image = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    if image.getbbox() is None:
        return False
    image.save(target)
    print(f"Знімок: {target} ({w}x{h})")
    return True


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
    app.geometry("1560x940")
    pump(app, 1.2)

    app.deiconify()
    app.lift()
    app.attributes("-topmost", True)
    app.focus_force()
    pump(app, 0.8)

    # ── RAG-панель із реальним пошуком
    app.show_side("rag")
    pump(app, 1.6)
    app.rag_panel.entry.delete(0, "end")
    app.rag_panel.entry.insert(0, "як запускається агент")
    app.rag_panel.run_search()
    pump(app, 3.0)
    app.sidebar.update_idletasks()
    grab(app.sidebar, ROOT / "assets" / "rag_panel.png")

    # ── Панель інструментів
    app.show_side("tools")
    pump(app, 0.8)
    app.tools_panel._toggle("read_file")
    pump(app, 0.4)
    app.tools_panel._fill_example("read_file")
    app.tools_panel.run_tool("read_file")
    pump(app, 2.0)
    grab(app.sidebar, ROOT / "assets" / "tools_panel.png")

    # ── Стрімінг у чаті
    from blackchpok_ide.agent import AgentEvent

    app.show_chat(True)
    app.chat._handle_event(AgentEvent("reasoning_token",
                                      "Треба подивитись, як влаштований "))
    app.chat._handle_event(AgentEvent("reasoning_token",
                                      "журнал роботи й додати стрімінг."))
    for piece in ("Готово. Я додав справжній стрімінг через SSE, ",
                  "живий журнал роботи й панель RAG. ",
                  "Тепер відповідь друкується в міру генерації."):
        app.chat._handle_event(AgentEvent("token", piece))
    app.chat._flush_stream()
    pump(app, 1.5)
    grab(app.conversation_host, ROOT / "assets" / "streaming.png")

    app.attributes("-topmost", False)
    app.tools_panel.cancel()
    app.rag_panel.cancel()
    app.agent.cancel()
    app.destroy()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)
