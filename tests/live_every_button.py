"""Живий прогін кожного інтерактивного елемента у справжньому вікні IDE.

На відміну від юніт-тестів, тут вікно реально відкривається, і кожен
елемент з обробником кліку натискається подіями <Button-1>/
<ButtonRelease-1>. Перевіряється, що жоден клік не кидає винятку.

Запуск: python tests/live_every_button.py
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
home = ROOT / ".buildtmp" / "buttons-home"
home.mkdir(parents=True, exist_ok=True)
os.environ["BLACKCHPOK_HOME"] = str(home)


def _utf8_console() -> None:
    """Друк у консоль Windows не має падати на «×», «→», «✗».

    Заміряно: без цього прогін завершувався ``UnicodeEncodeError`` на
    ``cp1251`` — і «0 помилок» губилось за збоєм самого друку.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    os.environ["PYTHONIOENCODING"] = "utf-8"


_utf8_console()

from blackchpok_ide.config import Settings, setup_logging  # noqa: E402

setup_logging()

from blackchpok_ide import widgets  # noqa: E402

import tkinter.filedialog as fd  # noqa: E402
import tkinter.messagebox as mb  # noqa: E402
import tkinter.simpledialog as sd  # noqa: E402

mb.askyesno = lambda *a, **k: True
mb.askyesnocancel = lambda *a, **k: True
mb.showinfo = lambda *a, **k: None
mb.showwarning = lambda *a, **k: None
mb.showerror = lambda *a, **k: None
sd.askstring = lambda *a, **k: "тест"
sd.askinteger = lambda *a, **k: 1
fd.asksaveasfilename = lambda *a, **k: ""
fd.askopenfilename = lambda *a, **k: ""
fd.askdirectory = lambda *a, **k: str(ROOT)

settings = Settings.load()
settings.workspace = str(ROOT)
settings.engine.auto_start = False
settings.agent.queue_auto_run = False
settings.agent.confirm_commands = False
settings.first_run_done = True
settings.ui.theme = "dark"

from blackchpok_ide.main_window import BlackChpokIDE  # noqa: E402

app = BlackChpokIDE(settings)
app.geometry("1500x920+30+30")
SHOTS = ROOT / ".buildtmp" / "button-shots"
SHOTS.mkdir(parents=True, exist_ok=True)

#: Друкувати кожен клік (для діагностики зависань).
VERBOSE = "--verbose" in sys.argv or os.environ.get("BCHPOK_VERBOSE") == "1"

results: list[tuple[str, str, str]] = []

#: Дії, які змінюють дані користувача — їх не натискаємо.
DESTRUCTIVE = (
    "видалити", "delete", "вихід", "quit", "exit", "закрити всі", "close all",
    "очистити", "clear", "зупинити", "stop", "перезапустити", "скинути",
    "встановити", "завантажити", "install", "download", "архівувати",
    # Запуск сайту піднімає реальний процес і чекає порт — прогін зависає.
    "запустити сайт", "запустити застосунок",
)

#: Кнопки, що відкривають МОДАЛЬНИЙ діалог із ``grab_set``.
#: Такий діалог перехоплює введення, і автоматичний прогін далі не йде
#: (це властивість Tk, а не вада програми). Їх перевіряє окремий сценарій
#: ``tests/live_modals.py``: там діалоги відкриваються по одному, з
#: перевіркою позиції на екрані й закриттям після кожного.
MODAL_OPENERS = (
    "налаштування", "майстер", "хаб моделей", "палітра", "швидке відкриття",
    "скіли", "квантування", "про програму", "гарячі клавіші",
)

#: Кнопки, що ЗАПУСКАЮТЬ РОБОТУ (агента, сервер, модель). Їх перевіряє
#: окремий живий сценарій із справжньою моделлю — тут вони лише
#: заважали б: агент зайнятий, і наступні кліки нічого не дають.
WORK_STARTERS = (
    "поясни файл", "знайди помилки", "додай тести", "рефакторинг",
    "надіслати", "покажи файли", "перевірити модель", "оновити список",
)

#: Кнопки, що відкривають СПЛИВНЕ МЕНЮ з ``-topmost`` і власним
#: перехопленням кліків (вибір моделі, режим роботи, контекст, меню «⋯»).
#: Після такого кліку меню стає модальним для подій і блокує прогін;
#: окремо їх перевіряє ``tests/test_modal_windows.py``.
POPUP_OPENERS = (
    "⋯", "◈ агент", "⊟", "контекст", "режим", "зусилля", "◔",
)

#: Віджети-контейнери, які не є кнопками: у них є обробник кліку (для
#: перетягування або фокуса), але «натискати» їх безглуздо — до того ж
#: ``TPanedwindow`` захоплює мишу на весь жест і блокує прогін.
NON_BUTTON_CLASSES = (
    "TPanedwindow", "Panedwindow", "Canvas", "Text", "Listbox",
    "TScrollbar", "Scrollbar", "Treeview",
)


def pump(seconds: float = 0.1) -> None:
    end = time.time() + seconds
    while time.time() < end:
        try:
            app.update()
        except Exception:
            return
        time.sleep(0.004)


def label_of(widget) -> str:
    try:
        for option in ("text", "label"):
            try:
                value = str(widget.cget(option) or "").strip()
                if value:
                    return value.replace("\n", " ")[:44]
            except Exception:
                continue
        return f"<{widget.winfo_class()}>"
    except Exception:
        return "<знищено>"


def alive(widget) -> bool:
    try:
        return bool(widget.winfo_exists())
    except Exception:
        return False


def visible(widget) -> bool:
    try:
        return bool(widget.winfo_ismapped())
    except Exception:
        return False


def click(widget) -> None:
    widget.update_idletasks()
    x = max(1, widget.winfo_width() // 2)
    y = max(1, widget.winfo_height() // 2)
    widget.event_generate("<Button-1>", x=x, y=y)
    widget.event_generate("<ButtonRelease-1>", x=x, y=y)


def interactive(root_widget, limit: int = 16) -> list:
    found, stack, seen = [], [(root_widget, 0)], set()
    while stack:
        widget, depth = stack.pop()
        if depth > limit or id(widget) in seen:
            continue
        seen.add(id(widget))
        try:
            children = widget.winfo_children()
        except Exception:
            continue
        for child in children:
            stack.append((child, depth + 1))
            try:
                binds = str(child.bind() or "")
            except Exception:
                continue
            if "<Button-1>" in binds or "<ButtonRelease-1>" in binds:
                found.append(child)
    return found


def state() -> dict:
    return {
        "side": getattr(app, "_active_side", ""),
        "bottom": getattr(app, "_bottom_shown", False),
        "sidebar": visible(app.sidebar),
        "theme": app.settings.ui.theme,
        "chat": app.chat_store.active_id,
        "view": getattr(app, "_view", ""),
    }


def restore(saved: dict) -> None:
    """Повернути вигляд і прибрати модальні вікна.

    Клік по «Налаштуваннях» відкриває діалог із ``grab_set``: без його
    закриття решта кліків блокується, і прогін зависає назавжди.
    """
    try:
        modal = widgets.active_modal()
        if modal is not None:
            widgets.release_modal(modal)
            try:
                modal.destroy()
            except Exception:
                pass
        widgets.close_popovers()
    except Exception:
        pass
    try:
        if saved["side"]:
            app.show_side(saved["side"])
        if visible(app.sidebar) != saved["sidebar"]:
            app.toggle_sidebar(saved["sidebar"])
        if getattr(app, "_bottom_shown", False) != saved["bottom"]:
            app.show_bottom("terminal" if saved["bottom"] else "")
        if app.settings.ui.theme != saved["theme"]:
            app.apply_theme_mode(saved["theme"])
        if saved["view"] and getattr(app, "_view", "") != saved["view"]:
            app.set_view(saved["view"])
    except Exception:
        pass
    pump(0.04)


def press_all(group: str, widgets_list: list) -> None:
    for widget in widgets_list:
        if not alive(widget):
            continue
        name = label_of(widget)
        lower = name.lower()
        try:
            widget_class = widget.winfo_class()
        except Exception:
            widget_class = ""
        if widget_class in NON_BUTTON_CLASSES:
            results.append((f"{group} · <{widget_class}>", "skip", "контейнер, не кнопка"))
            continue
        if any(bad in lower for bad in DESTRUCTIVE):
            results.append((f"{group} · {name}", "skip", "змінює дані"))
            continue
        if any(opener in lower for opener in MODAL_OPENERS):
            results.append((f"{group} · {name}", "skip", "модальний діалог (окремий тест)"))
            continue
        if any(starter in lower for starter in WORK_STARTERS):
            results.append((f"{group} · {name}", "skip", "запускає роботу агента"))
            continue
        if any(opener in lower for opener in POPUP_OPENERS):
            results.append((f"{group} · {name}", "skip", "спливне меню (окремий тест)"))
            continue
        if not visible(widget):
            results.append((f"{group} · {name}", "skip", "не видно"))
            continue
        saved = state()
        try:
            if VERBOSE:
                print(f"  → клік {len(results)+1}: {widget_class} {name!r}", flush=True)
            click(widget)
            pump(0.1)
            results.append((f"{group} · {name}", "OK", ""))
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            if "bad window path name" in message:
                results.append((f"{group} · {name}", "skip", "зник при перемальовуванні"))
            else:
                results.append((f"{group} · {name}", "ERR",
                                f"{type(exc).__name__}: {message}"))
        finally:
            try:
                restore(saved)
            except Exception:  # noqa: BLE001 - відновлення не має валити прогін
                pass
            # Спливні картки й меню після кліку можуть лишитись поверх
            # усього й перехопити наступні події — прибираємо одразу.
            try:
                widgets.close_popovers()
            except Exception:  # noqa: BLE001
                pass


def shot(name: str) -> None:
    try:
        from PIL import ImageGrab

        x, y = app.winfo_rootx(), app.winfo_rooty()
        img = ImageGrab.grab(bbox=(x, y, x + app.winfo_width(), y + app.winfo_height()))
        img.save(SHOTS / f"{name}.png")
    except Exception:
        pass


def main() -> int:
    app.lift()
    app.focus_force()
    try:
        app.attributes("-topmost", True)
    except Exception:
        pass
    pump(0.9)
    app.show_side("chats")
    pump(0.3)

    window_widgets = interactive(app)
    print(f"Інтерактивних елементів у вікні: {len(window_widgets)}", flush=True)
    shot("00-window")
    press_all("вікно", window_widgets)
    print(f"вікно: оброблено {len(results)}", flush=True)

    for key in ("chats", "cases", "queue", "skills", "mcp", "tools",
                "explorer", "changes", "outline", "rag", "autonomous",
                "runtime", "neuromesh"):
        try:
            app.show_side(key)
            pump(0.25)
        except Exception as exc:  # noqa: BLE001
            results.append((f"панель {key}", "ERR", str(exc)))
            continue
        # ``interactive`` обходить ``app`` (усе вікно), а не саму панель:
        # раніше обхід ``app.side_stack`` пропускав частину елементів, і вони
        # лишались неперевіреними.
        panel_widgets = interactive(app)
        shot(f"panel-{key}")
        press_all(f"панель {key}", panel_widgets)
        # Модальні діалоги й попапи могли лишитись — прибираємо одразу.
        try:
            widgets.close_popovers()
            modal = widgets.active_modal()
            if modal is not None:
                widgets.release_modal(modal)
                modal.destroy()
        except Exception:
            pass
        print(f"панель {key}: усього {len(results)}", flush=True)

    for tab in ("terminal", "search", "hub", "site"):
        try:
            app.show_bottom(tab)
            pump(0.3)
            shot(f"bottom-{tab}")
            press_all(f"низ {tab}", interactive(app.bottom_tabs))
            results.append((f"низ · {tab}", "OK", ""))
        except Exception as exc:  # noqa: BLE001
            results.append((f"низ · {tab}", "ERR", f"{type(exc).__name__}: {exc}"))
    try:
        app.show_bottom("")
    except Exception:
        pass

    for mode in ("light", "dark"):
        try:
            app.apply_theme_mode(mode)
            pump(0.3)
            shot(f"theme-{mode}")
            results.append((f"тема · {mode}", "OK", ""))
        except Exception as exc:  # noqa: BLE001
            results.append((f"тема · {mode}", "ERR", str(exc)))

    pump(0.3)
    shot("99-final")
    app.destroy()

    ok = sum(1 for r in results if r[1] == "OK")
    err = [r for r in results if r[1] == "ERR"]
    skip = [r for r in results if r[1] == "skip"]
    print()
    print(f"Натиснуто успішно: {ok}")
    print(f"Помилок: {len(err)}")
    print(f"Пропущено: {len(skip)}")
    reasons = Counter(detail for _, _, detail in skip)
    for reason, count in reasons.most_common():
        print(f"  {count:4d} × {reason}")
    if err:
        print()
        print("ПОМИЛКИ:")
        for name, _, detail in err:
            print(f"  ✗ {name}: {detail}")
    print(f"\nСкріншоти: {SHOTS}")
    return 0 if not err else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
