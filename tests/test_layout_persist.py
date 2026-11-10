"""Тести рухомої розкладки: збереження, межі, структура вікна.

Запуск:  python tests/test_layout_persist.py
"""

from __future__ import annotations

import json
import shutil
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import layout as L  # noqa: E402

failures = 0
checked = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures, checked
    checked += 1
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def temp_dir() -> Path:
    folder = ROOT / ".buildtmp" / f"layout-{uuid.uuid4().hex[:8]}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# ─────────────────────────────────────────────────────────────────────────────
# Чистий модуль розкладки
# ─────────────────────────────────────────────────────────────────────────────

def test_layout_basics() -> None:
    folder = temp_dir()
    try:
        path = folder / "layout.json"
        check("файла ще немає", not path.exists())
        empty = L.load(path)
        check("порожня розкладка завантажується", empty.values == {})
        check("типове значення повертається", empty.get("composer_height", 210) == 210)

        empty.set("composer_height", 340)
        empty.set("chat_split", 620)
        check("значення записується", empty.get("composer_height") == 340)
        check("нуль не записується", (empty.set("bad", 0), empty.get("bad", 5))[1] == 5)
        check("сміття не ламає", (empty.set("bad2", "abc"), empty.get("bad2", 7))[1] == 7)

        L.save(empty, path)
        check("файл створено", path.exists())
        restored = L.load(path)
        check("значення переживає запис",
              restored.get("composer_height") == 340 and restored.get("chat_split") == 620)

        # Пошкоджений файл
        path.write_text("{ не json", encoding="utf-8")
        broken = L.load(path)
        check("пошкоджений файл не ламає", broken.values == {})

        # Часткові дані
        path.write_text(json.dumps({"values": {"a": "x", "b": 12, "c": -5}}),
                        encoding="utf-8")
        partial = L.load(path)
        check("некоректні значення відкинуто",
              partial.get("b", 0) == 12 and partial.get("a", 9) == 9
              and partial.get("c", 9) == 9)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_math() -> None:
    check("clamp знизу", L.clamp(10, 60, 500) == 60)
    check("clamp зверху", L.clamp(900, 60, 500) == 500)
    check("clamp усередині", L.clamp(300, 60, 500) == 300)
    check("clamp з перевернутими межами", L.clamp(50, 100, 20) == 100)
    check("sash_pos половина", L.sash_pos(0.5, 1000) == 500)
    check("sash_pos нуль не виходить за межу", L.sash_pos(0.0, 1000) >= 60)
    check("sash_pos при нулі довжини", L.sash_pos(0.5, 0) == 0)
    check("fraction_of", abs(L.fraction_of(250, 1000) - 0.25) < 0.001)
    check("fraction_of при нулі", L.fraction_of(100, 0) == 0.0)


def test_visibility() -> None:
    state = L.Layout()
    check("типово видимий", state.is_visible("bottom"))
    state.set_visible("bottom", False)
    check("видимість зберігається", not state.is_visible("bottom"))
    restored = L.Layout.from_dict(state.to_dict())
    check("видимість переживає серіалізацію", not restored.is_visible("bottom"))


# ─────────────────────────────────────────────────────────────────────────────
# Живе вікно
# ─────────────────────────────────────────────────────────────────────────────

def test_live_window() -> None:
    import tkinter.messagebox as mb
    import tkinter.simpledialog as sd
    import tkinter.filedialog as fd

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

    from blackchpok_ide.config import Settings, setup_logging
    from blackchpok_ide.main_window import BlackChpokIDE

    setup_logging()
    layout_file = L.layout_path()
    backup = None
    if layout_file.exists():
        backup = layout_file.read_text(encoding="utf-8")
        layout_file.unlink()

    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.first_run_done = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False
    # Тест перевіряє саші трьох колонок, тому потрібен вид «робоча область»
    # незалежно від того, що лишилось у спільних налаштуваннях.
    settings.ui.view = "workspace"

    def pump(app, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            app.update()
            time.sleep(0.02)

    app = BlackChpokIDE(settings)
    app.geometry("1560x940")
    try:
        pump(app, 1.8)
        app.hide_welcome()
        pump(app, 0.6)

        # ── структура
        check("три колонки в h_split", len(app.h_split.panes()) == 3,
              str(len(app.h_split.panes())))
        check("два рядки у v_split", len(app.v_split.panes()) == 2,
              str(len(app.v_split.panes())))

        check("чати зліва за замовчуванням", app._active_side == "chats", app._active_side)
        check("сайдбар видимий", app.sidebar.winfo_ismapped() == 1)
        check("панель чатів у сайдбарі",
              app.chat_list.winfo_ismapped() == 1)

        chat_w = app.conversation_host.winfo_width()
        centre_w = app.centre.winfo_width()
        check("розмова ліворуч від редактора", chat_w > 200, f"{chat_w} px")
        check("редактор має місце", centre_w > 200, f"{centre_w} px")
        check("розмова передує редактору за порядком",
              app.h_split.panes()[0].endswith(str(app.conversation_host)),
              str(app.h_split.panes()[0]))

        composer_h = app.composer_host.winfo_height()
        check("поле чату знизу", composer_h > 100 and app.composer_host.winfo_ismapped() == 1,
              f"{composer_h} px")
        check("композер під робочою областю",
              app.v_split.panes()[1].endswith(str(app.composer_host)),
              str(app.v_split.panes()[1]))

        # ── рух сашів і збереження
        before = (app.h_split.sashpos(0), app.v_split.sashpos(0))
        app.h_split.sashpos(0, 620)
        app.v_split.sashpos(0, 480)
        pump(app, 0.4)
        moved = (app.h_split.sashpos(0), app.v_split.sashpos(0))
        check("саш рухається", moved != before, f"{before} → {moved}")

        app._remember_layout()
        pump(app, 0.3)
        check("розкладку записано", layout_file.exists())
    finally:
        app.agent.cancel()
        app.destroy()
        pump(app, 0.2)

    # ── нова сесія: відновлення
    app2 = BlackChpokIDE(settings)
    app2.geometry("1560x940")
    try:
        pump(app2, 1.8)
        app2.hide_welcome()
        pump(app2, 0.6)
        restored = (app2.h_split.sashpos(0), app2.v_split.sashpos(0))
        check("розкладка відновилась після перезапуску",
              abs(restored[0] - moved[0]) <= 15 and abs(restored[1] - moved[1]) <= 15,
              f"було {moved}, стало {restored}")

        # ── скидання
        app2.reset_layout()
        pump(app2, 0.5)
        default_pos = app2.h_split.sashpos(0)
        check("скидання змінює позицію", abs(default_pos - moved[0]) > 5,
              f"{moved[0]} → {default_pos}")
        saved = json.loads(layout_file.read_text(encoding="utf-8"))
        check("після скидання файл порожній", saved.get("values") == {},
              str(saved.get("values")))
    finally:
        app2.agent.cancel()
        app2.destroy()
        pump(app2, 0.2)

    # прибрати сліди
    if layout_file.exists():
        layout_file.unlink()
    if backup is not None:
        layout_file.write_text(backup, encoding="utf-8")


def test_chat_split_draggable() -> None:
    """Розмова й композер — окремі частини з власним сашем."""
    import tkinter as tk
    import tkinter.messagebox as mb
    import tkinter.simpledialog as sd

    mb.askyesno = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    sd.askstring = lambda *a, **k: None
    sd.askinteger = lambda *a, **k: None

    from blackchpok_ide import theme
    from blackchpok_ide.agent_tools import ToolRegistry
    from blackchpok_ide.chat_panel import ChatPanel
    from blackchpok_ide.config import Settings

    root = tk.Tk()
    root.geometry("700x700")
    fonts = theme.Theme(root)
    fonts.apply()

    # Композер зовні — як у головному вікні
    composer_host = tk.Frame(root, bg=theme.BG_ALT)
    composer_host.pack(side="bottom", fill="x")
    panel = ChatPanel(root, fonts, Settings(), ToolRegistry(ROOT),
                      composer_parent=composer_host)
    panel.pack(fill="both", expand=True)

    def pump(seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            root.update()
            time.sleep(0.02)

    pump(0.5)
    check("композер у зовнішньому контейнері",
          panel.composer_host.winfo_parent() == str(composer_host),
          panel.composer_host.winfo_parent())
    check("композер має місце", panel.composer_host.winfo_height() > 40,
          f"{panel.composer_host.winfo_height()} px")

    panel._add_assistant("Перевірка стрічки розмови")
    pump(0.5)
    check("повідомлення додано", len(panel._cards) >= 1, str(len(panel._cards)))
    check("стрічка має висоту", panel.feed.winfo_height() > 20,
          f"{panel.feed.winfo_height()} px")
    check("стрічка видима", panel.feed.winfo_ismapped() == 1)
    check("canvas має область прокрутки",
          bool(panel.scroll.canvas.cget("scrollregion")))

    root.destroy()


def main() -> int:
    test_layout_basics()
    test_math()
    test_visibility()
    test_live_window()
    test_chat_split_draggable()
    print()
    print(f"Перевірено тверджень: {checked}")
    print("Розкладка:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


# ── unittest-обгортка (додано 10.11.2026) ──────────────────────────────────
# Для `python -m unittest discover` ці перевірки раніше були невидимі:
# файл — скрипт із власним main(), а не TestCase. Тепер discover запускає
# його й падає, якщо main() повернув ненульовий код. Запуск як скрипт
# (`python tests/test_layout_persist.py`) поводиться як раніше.
import unittest as _unittest  # noqa: E402


class _ScriptSuite(_unittest.TestCase):
    def test_script_passes(self) -> None:
        code = main()
        self.assertEqual(code, 0, f"main() повернув {code}")
