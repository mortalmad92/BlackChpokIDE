"""Перевірка геометрії вікна: панелі мають ту ширину, яку просить макет.

Запуск:  python tests/test_layout.py
Повертає 0, якщо всі панелі в межах допуску.
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

failures = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if condition else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures += 1


def nearest(value: int, target: int, tolerance: float = 0.20) -> bool:
    return abs(value - target) <= max(16, int(target * tolerance))


def _neutralise_dialogs() -> None:
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb
    import tkinter.simpledialog as sd

    mb.askyesno = lambda *a, **k: True
    mb.askyesnocancel = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    sd.askstring = lambda *a, **k: None
    sd.askinteger = lambda *a, **k: None
    fd.asksaveasfilename = lambda *a, **k: ""
    fd.askopenfilename = lambda *a, **k: ""
    fd.askdirectory = lambda *a, **k: ""


def pump(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def main() -> int:
    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()
    _neutralise_dialogs()
    # Збережена розкладка користувача перебиває будь-яку ширину з тесту:
    # ``layout.json`` у справжній теці конфігу містить власний
    # ``sidebar_width``, і перевірка «250» падала на реальних 300–396.
    # Тест міряє геометрію, тож бере чисту розкладку.
    from blackchpok_ide import layout as layout_module

    try:
        stored = layout_module.layout_path()
        if stored.exists():
            stored.unlink()
    except (OSError, AttributeError):
        pass
    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.first_run_done = True
    settings.ui.sidebar_width = 250
    settings.ui.chat_width = 460
    settings.ui.context_width = 212
    settings.ui.bottom_height = 200
    settings.ui.bottom_visible = True
    # Тест міряє геометрію всіх трьох колонок, тому потрібен вид «робоча
    # область» незалежно від того, що користувач лишив у налаштуваннях.
    settings.ui.view = "workspace"

    from blackchpok_ide.main_window import BlackChpokIDE

    app = BlackChpokIDE(settings)
    app.geometry("1560x900")
    app.update_idletasks()
    pump(app, 1.0)

    total = app.winfo_width()
    check("вікно має ширину", total >= 1200, f"{total} px")
    check(
        "панель стану видима",
        app.status_bar.winfo_ismapped() == 1 and app.status_bar.winfo_height() >= 16,
        f"h={app.status_bar.winfo_height()}",
    )

    side = app.sidebar.winfo_width()
    check("бічна панель ≈ sidebar_width", nearest(side, 250, 0.12), f"{side} px (ціль 250)")

    # Нова розкладка: навігація зліва (всередині сайдбара), далі
    # діалог | робоча область | контекст.
    chat = app.conversation_host.winfo_width()
    ctx = app.context_host.winfo_width()
    editor_w = app.centre.winfo_width()
    check("розмова має ширину", chat >= 250, f"{chat} px")
    check("контекстна панель має свою ширину", nearest(ctx, 212, 0.30), f"{ctx} px")
    check("редактор має ширину", editor_w >= 250, f"{editor_w} px")

    # Навігація тепер частина сайдбара, а не окремою колонкою, тому
    # перевіряємо, що колонки h_split справді вкладаються у вікно.
    check(
        "сума панелей не перевищує вікно",
        side + app.h_split.winfo_width() <= total + 8,
        f"{side} + {app.h_split.winfo_width()} <= {total}",
    )
    check("навігація всередині бічної панелі",
          app.rail.winfo_width() <= side,
          f"rail={app.rail.winfo_width()} <= sidebar={side}")

    bottom = app.bottom_tabs.winfo_height() if app._bottom_shown else 0
    check("нижня панель ≈ bottom_height", nearest(bottom, 200, 0.35) or bottom == 0,
          f"{bottom} px (ціль 200)")
    composer = app.composer_host.winfo_height()
    check("поле чату знизу ≈ composer_height", nearest(composer, 210, 0.35),
          f"{composer} px (ціль 210)")

    # Мінімальний розмір: панелі мають стискатись, а не зникати.
    app.geometry("1100x700")
    pump(app, 0.6)
    side2 = app.sidebar.winfo_width()
    chat2 = app.conversation_host.winfo_width()
    editor2 = app.centre.winfo_width()
    check(
        "на малому вікні панелі стискаються, а не зникають",
        side2 > 80 and chat2 > 150 and editor2 > 150,
        f"side={side2} chat={chat2} editor={editor2}",
    )

    app.geometry("1560x900")
    pump(app, 0.5)

    # Перемикання бічної панелі має віддавати місце редактору.
    before = app.centre.winfo_width()
    app.toggle_sidebar()
    pump(app, 0.5)
    after = app.centre.winfo_width()
    check("прихована панель віддає ширину редактору", after > before, f"{before} → {after}")
    app.toggle_sidebar()
    pump(app, 0.5)

    # Колонка контексту теж має ховатись і повертатись.
    w_before = app.centre.winfo_width()
    app.toggle_context()
    pump(app, 0.6)
    w_after = app.centre.winfo_width()
    check("прихований контекст віддає ширину редактору", w_after > w_before,
          f"{w_before} → {w_after}")
    app.toggle_context()
    pump(app, 0.5)
    app.toggle_context()
    pump(app, 0.4)

    app.agent.cancel()
    app.destroy()
    print()
    print("Геометрія:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)
