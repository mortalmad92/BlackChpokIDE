"""Перевірка diff-картки й вбудованого скріншота в чаті.

Запуск:  .venv\\Scripts\\python.exe tests/check_redesign.py
Файли:   .buildtmp/shots/redesign-*.png
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── ЗАХИСТ СПРАВЖНІХ НАЛАШТУВАНЬ ────────────────────────────────────────────
# Цей скрипт робить Settings.load() → settings.save(). Без ізоляції він писав
# у СПРАВЖНІЙ конфіг користувача (%APPDATA%\BlackChpokIDE\settings.json) і
# вимикав автозапуск локальної моделі. Саме через такі прогони IDE переставала
# піднімати модель сама. Обидва прапорці ставимо ДО імпорту пакета.
os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchp-redesign-"))
os.environ["BLACKCHPOK_NO_SAVE"] = "1"

OUT = ROOT / ".buildtmp" / "shots"


def pump(app, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.02)


def grab(app, name: str) -> None:
    from PIL import ImageGrab

    try:
        app.lift()
        app.focus_force()
        app.attributes("-topmost", True)
        app.update()
        time.sleep(0.35)
        app.update()
    except Exception:  # noqa: BLE001
        pass
    x = app.winfo_rootx()
    y = app.winfo_rooty()
    w = app.winfo_width()
    h = app.winfo_height()
    image = ImageGrab.grab(bbox=(x, y - 24, x + w, y + h))
    OUT.mkdir(parents=True, exist_ok=True)
    image.save(OUT / f"{name}.png")
    print("saved", name, image.size)


def main() -> int:
    import tkinter.messagebox as mb
    import tkinter.simpledialog as sd
    import tkinter.filedialog as fd

    mb.askyesno = lambda *a, **k: True
    mb.askyesnocancel = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    sd.askstring = lambda *a, **k: None
    fd.asksaveasfilename = lambda *a, **k: ""
    fd.askopenfilename = lambda *a, **k: ""
    fd.askdirectory = lambda *a, **k: ""

    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()
    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.llm.model = settings.llm.model or "test-model"
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False
    settings.ui.view = "chat"
    settings.save()

    from blackchpok_ide.main_window import BlackChpokIDE

    app = BlackChpokIDE(settings)
    app.update_idletasks()
    app.update()
    app.hide_welcome()
    app.chat.new_chat()
    app.update()

    # ── 1. diff-картка: правка файлу з .bak
    sample = ROOT / ".buildtmp" / "redesign_sample.py"
    backup = Path(str(sample) + ".bak")
    sample.write_text("def hello():\n    print('old')\n    return 1\n", encoding="utf-8")
    backup.write_text("def hello():\n    print('ancient')\n    return 0\n", encoding="utf-8")
    from blackchpok_ide.agent import AgentEvent

    app.chat._log = None  # без журналу, щоб diff був окремою карткою
    event = AgentEvent(kind="tool_result", text="Оновлено redesign_sample.py: замін 1.",
                       data={"name": "edit_file", "ok": True, "call_id": "t1"})
    app.chat._add_tool_result(event)
    app.update()
    pump(app, 0.6)
    body = app.chat.transcript.get()
    ok_diff = "redesign_sample.py" in body
    grab(app, "redesign-1-diff")

    # ── 2. скріншот-картка
    shot = ROOT / ".buildtmp" / "shots" / "shot-src.png"
    try:
        from PIL import Image

        Image.new("RGB", (640, 400), (246, 246, 242)).save(shot)
    except ImportError:
        print("PIL немає — скріншот-тест пропущено")
        return 0 if ok_diff else 1
    event2 = AgentEvent(
        kind="tool_result",
        text=f"Скріншот збережено: {shot} (640×400).",
        data={"name": "app_screenshot", "ok": True, "call_id": "t2"},
    )
    app.chat._add_tool_result(event2)
    app.update()
    pump(app, 0.6)
    grab(app, "redesign-2-screenshot")

    # ── 3. статус сесії в списку агентів
    chat = app.chat_store.active()
    app.chat_store.set_status(chat.id, "working")
    app.chat_list.refresh()
    app.update()
    pump(app, 0.4)
    grab(app, "redesign-3-status")
    row = app.chat_list._rows.get(chat.id)
    state_ok = row is not None and row.dot.state == "running"

    # ── 4. живий прев'ю: тумблер
    app.toggle_preview(True)
    app.update()
    pump(app, 0.5)
    preview_ok = app._preview_shown and app.live_preview.winfo_ismapped()
    grab(app, "redesign-4-preview")

    # ── 5. темна тема
    app.apply_theme_mode("dark")
    app.update()
    pump(app, 0.5)
    grab(app, "redesign-5-dark")
    app.apply_theme_mode("light")
    app.update()

    sample.unlink(missing_ok=True)
    backup.unlink(missing_ok=True)

    print()
    print("diff-картка в transcript:", ok_diff)
    print("статус working на крапці:", state_ok)
    print("прев'ю колонка показана:", preview_ok)
    failures = sum(1 for flag in (ok_diff, state_ok, preview_ok) if not flag)
    app.agent.cancel()
    app.destroy()
    print("Перевірка редизайну:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        raise SystemExit(2)
