"""Хто саме малює «◈ Агент ▾» і «⊟ модель» — з координатами й станом."""

from __future__ import annotations
# ── ІЗОЛЯЦІЯ ДАНИХ ───────────────────────────────────────────────────────
# Інструмент будує СПРАВЖНЄ вікно IDE. Без власного ``BLACKCHPOK_HOME``
# вікно читає ``<app_data>/chats.json`` і відновлює активний чат
# КОРИСТУВАЧА — з ЙОГО текою. Наслідок заміряно: тестовий агент писав
# файли в проєкт користувача, а перевірка дивилась у пісочницю.
# Ставимо ДО звернення до пакета: ``config`` рахує шляхи під час імпорту.
import os as _os
import tempfile as _tempfile

_os.environ.setdefault("BLACKCHPOK_HOME",
                       _tempfile.mkdtemp(prefix="tool-home-"))
_os.environ["BLACKCHPOK_NO_SAVE"] = "1"


import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
os.environ.setdefault("BLACKCHPOK_NO_SAVE", "1")

from blackchpok_ide.config import Settings, setup_logging  # noqa: E402

setup_logging()
settings = Settings.load()
settings.workspace = str(ROOT)
settings.project_chosen = True
settings.first_run_done = True
settings.engine.auto_start = False

from blackchpok_ide.main_window import BlackChpokIDE  # noqa: E402

app = BlackChpokIDE(settings)
app.geometry("1600x900+20+20")
deadline = time.time() + 3.0
while time.time() < deadline:
    app.update()
    time.sleep(0.05)

print("=== усі підписи з ◈ або ⊟ (стан + геометрія) ===")


def walk(widget, depth=0):
    if depth > 12:
        return
    for child in widget.winfo_children():
        try:
            text = str(child.cget("text"))
        except Exception:
            text = ""
        if text and ("◈" in text or "⊟" in text):
            try:
                mapped = child.winfo_ismapped()
                root_x = child.winfo_rootx()
                root_y = child.winfo_rooty()
                width = child.winfo_width()
            except Exception:
                mapped, root_x, root_y, width = "?", 0, 0, 0
            owner = type(child.master).__name__
            print(f"  mapped={str(mapped):5s} x={root_x:5d} y={root_y:4d} "
                  f"w={width:4d} owner={owner:16s} {text[:46]!r}")
        walk(child, depth + 1)


walk(app)

# Чи існують ручки й чи вони показані?
header = getattr(app, "header", None)
for attr in ("mode_label", "model_label", "chat_mode_label"):
    widget = getattr(header, attr, None) if header is not None else None
    if widget is None:
        print(f"  SessionHeader.{attr}: НЕМАЄ")
        continue
    try:
        print(f"  SessionHeader.{attr}: mapped={widget.winfo_ismapped()} "
              f"manager={widget.winfo_manager()!r} text={widget.cget('text')!r}")
    except Exception as exc:  # noqa: BLE001
        print(f"  SessionHeader.{attr}: {exc}")

app.destroy()
