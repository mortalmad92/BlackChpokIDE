"""Перевірка змін цього раунду: авторежим, підписи ролей, кнопки вигляду.

Запуск:  .venv\\Scripts\\python.exe tools/check_ui_round.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def main() -> int:
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb
    import tkinter.simpledialog as sd

    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    sd.askstring = lambda *a, **k: None
    fd.askdirectory = lambda *a, **k: ""

    from blackchpok_ide import modes, theme
    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()

    # ── 1. Автоматичний вибір режиму ──────────────────────────────────────
    print("— режим обирається автоматично —")
    check("балачка → чат", modes.auto_mode("привіт, як справи") == modes.CHAT)
    check("правка коду → код",
          modes.auto_mode("виправ помилку в server.py") == modes.CODE)
    check("нове завдання → агент",
          modes.auto_mode("створи сайт-візитку") == modes.AGENT)
    check("порожнє → чат", modes.auto_mode("") == modes.CHAT)
    check("невідоме не падає", modes.auto_mode("абракадабра ззз") in modes.keys())

    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.first_run_done = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False
    # Навчання режиму пише правило у файл — перевірка не має чіпати
    # СПРАВЖНІ правила користувача, тож ведемо їх у тимчасову теку.
    import tempfile

    os.environ.setdefault("BLACKCHPOK_HOME",
                          tempfile.mkdtemp(prefix="check-ui-home-"))
    os.environ["BLACKCHPOK_NO_SAVE"] = "1"

    from blackchpok_ide.main_window import BlackChpokIDE

    app = BlackChpokIDE(settings)
    app.geometry("1400x900+20+20")
    end = time.time() + 1.5
    while time.time() < end:
        app.update()
        time.sleep(0.02)
    app.hide_welcome()

    # ── 2. Режим перемикається з тексту, без віджета ──────────────────────
    print("— режим у живому вікні —")
    app._auto_mode_for("виправ помилку в server.py")
    check("після тексту про код режим став code", app.agent_mode == modes.CODE,
          app.agent_mode)
    app._auto_mode_for("привіт")
    check("після балачки режим став chat", app.agent_mode == modes.CHAT,
          app.agent_mode)

    # ── 3. Підписи ролей повернуто ────────────────────────────────────────
    print("— підписи ролей у чаті —")
    from blackchpok_ide.agent import AgentEvent

    app.set_agent_mode(modes.AGENT, notify=False)
    app.chat.new_chat()
    app.update()
    app.chat._handle_event(AgentEvent("assistant", "Готово.", {"final": True}))
    app.update()
    cards = [c for c in app.chat._cards if hasattr(c, "role_label")]
    user_cards = [c for c in cards if c.role == app.chat.__class__.__name__ or c.is_user]
    check("картки мають підпис ролі", bool(cards), str(len(cards)))
    shown = []
    for card in cards:
        try:
            if card.role_label.winfo_manager():
                shown.append(card.role_label.cget("text"))
        except Exception:  # noqa: BLE001
            pass
    check("підпис «АГЕНТ» видно", any("АГЕНТ" in str(text) for text in shown),
          str(shown))

    # ── 4. Кнопки швидкого регулювання вигляду ────────────────────────────
    print("— кнопки вигляду в бічній панелі —")
    for name in ("theme_btn", "font_small_btn", "font_big_btn", "scale_btn"):
        check(f"є кнопка {name}", hasattr(app, name))
    before_theme = theme.current_mode()
    app.toggle_theme()
    app.update()
    check("тема перемикається", theme.current_mode() != before_theme,
          f"{before_theme} → {theme.current_mode()}")
    app.toggle_theme()

    before_font = app.settings.ui.font_size
    app.font_bigger()
    app.update()
    check("шрифт більшається", app.settings.ui.font_size > before_font,
          f"{before_font} → {app.settings.ui.font_size}")
    app.font_smaller()

    before_scale = float(getattr(app.settings.ui, "ui_scale", 1.0))
    app.cycle_ui_scale()
    app.update()
    after_scale = float(getattr(app.settings.ui, "ui_scale", 1.0))
    check("масштаб змінюється", abs(after_scale - before_scale) > 0.001,
          f"{before_scale} → {after_scale}")

    # ── 5. Кнопка розгортання згорнутої панелі ────────────────────────────
    print("— розгортання панелі —")
    app.toggle_sidebar(False)
    app.update()
    check("панель згорнута", not app._sidebar_visible())
    check("кнопка «☰» показана", app.header_bar._reveal_shown)
    app.toggle_sidebar(True)
    app.update()
    check("панель повернулась", app._sidebar_visible())
    check("кнопка «☰» схована", not app.header_bar._reveal_shown)

    # ── 6. Дублювання назви прибрано ──────────────────────────────────────
    print("— дублювання назви —")
    check("у бічній панелі назви немає",
          not hasattr(app, "brand_label") or app.brand_label is None)
    check("у шапці бренд лишився", app.header_bar.logo.winfo_exists())
    import inspect

    nav_source = inspect.getsource(__import__(
        "blackchpok_ide.nav_sidebar", fromlist=["x"]))
    # Згадка в комментарі — не дубль: шукаємо саме створення віджета з написом.
    check("nav_sidebar не малює назву",
          'text="BlackChpok"' not in nav_source)

    # ── 7. Кнопки швидких підказок прибрані ───────────────────────────────
    print("— швидкі підказки —")
    chat_source = inspect.getsource(app.chat.__class__)
    # Перевіряємо, що кнопок НЕ СТВОРЮЮТЬ: згадка в комментарі — це не кнопка.
    check("кнопки швидких дій сховані",
          not getattr(app.chat, "quick_row", None).winfo_manager())
    check("меню режимів не відкривається вручну",
          "ModeMenu(" not in inspect.getsource(app.__class__)
          or "_on_mode_selected" not in inspect.getsource(app.show_mode_menu))

    # ── 8. Іконка зображення ──────────────────────────────────────────────
    print("— іконка зображення —")
    check("є кнопка зображення", hasattr(app.chat, "image_btn"))
    check("є смуга прикріплень", hasattr(app.chat, "attachments_row"))
    check("є метод вибору зображення",
          hasattr(app.chat, "_attach_image_dialog"))

    # ── 9. Режим видно СЛОВАМИ, не лише пігулкою ──────────────────────────
    print("— режим підписано словами —")
    app.set_agent_mode(modes.CODE, notify=False)
    app.update()
    caption = getattr(app.chat, "mode_caption", None)
    check("є підпис режиму в композері", caption is not None)
    if caption is not None:
        text = str(caption.cget("text") or "")
        check("підпис не порожній", bool(text.strip()), text)
        check("підпис збігається з режимом",
              text == modes.get(modes.CODE).hint, text[:60])
    app.set_agent_mode(modes.CHAT, notify=False)
    app.update()
    if caption is not None:
        check("підпис змінюється разом із режимом",
              str(caption.cget("text") or "") == modes.get(modes.CHAT).hint)

    # ── 10. Стрічка чату не стискає картки ────────────────────────────────
    print("— стрічка чату —")
    app.set_agent_mode(modes.AGENT, notify=False)
    app.chat.new_chat()
    app.update()
    from blackchpok_ide import chat_panel as chat_module

    card = app.chat._new_card(chat_module.ROLE_USER, accent=theme.CHAT_USER)
    app.chat._body_text(card, "Перевірка висоти картки у стрічці")
    app.update()
    end = time.time() + 0.6
    while time.time() < end:
        app.update()
        time.sleep(0.02)
    heights = [c.winfo_height() for c in app.chat._cards
               if c.winfo_manager()]
    check("жодна картка не стиснута до 1 px",
          all(h > 4 for h in heights), str(heights))
    scroll = app.chat.scroll
    region = str(scroll.canvas.cget("scrollregion") or "")
    parts = region.split()
    check("область прокрутки відповідає вмісту",
          len(parts) == 4 and int(parts[3]) >= scroll.inner.winfo_reqheight() - 2,
          region)

    # ── 11. Самонавчання режиму підключене й працює ───────────────────────
    print("— самонавчання на виборі режиму —")
    learner = getattr(app, "mode_learning", None)
    check("навчач режиму підключено", learner is not None)
    if learner is not None:
        rule = learner.record("покажи мені що там у файлі конфігурації сервера",
                              chosen=modes.CHAT, wanted=modes.AGENT,
                              reason="need_tools")
        check("помилка стала правилом", rule is not None)
        check("правило змінює вибір режиму",
              modes.auto_mode("покажи мені що там у файлі конфігурації сервера",
                              learner=learner) == modes.AGENT)
        learner.forget_all()

    app.agent.cancel()
    app.destroy()
    print()
    print("Перевірка інтерфейсу:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
