"""Наскрізна перевірка майстра й вбудованого браузера у СПРАВЖНЬОМУ вікні.

Головне, що перевіряємо:

1. жодна дія в інтерфейсі не відкриває системний браузер ПК — усе йде у
   вбудоване вікно (раніше «Встановити git» викидав у Chrome);
2. вбудований браузер приймає і локальні адреси, і адреси з інтернету;
3. майстер показує всі чотири кроки й реальні стани бібліотек і програм.

Запуск: python tests/test_browser_wizard_live.py
"""

from __future__ import annotations

import sys
import tempfile
import time
import traceback
from pathlib import Path
from unittest import mock

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
    global failures
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb

    mb.askyesno = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    fd.asksaveasfilename = lambda *a, **k: ""
    fd.askopenfilename = lambda *a, **k: ""
    fd.askdirectory = lambda *a, **k: ""
    fd.asksaveasfilename = lambda *a, **k: ""

    from blackchpok_ide import browser_panel, env_setup
    from blackchpok_ide.config import Settings, setup_logging
    from blackchpok_ide.first_run import STEPS, FirstRunWizard
    from blackchpok_ide.main_window import BlackChpokIDE

    setup_logging()
    settings = Settings.load()
    settings.workspace = tempfile.mkdtemp()
    settings.first_run_done = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False
    settings.ui.view = "workspace"
    # Нижня панель має бути закритою: інакше попередній прогін міг зберегти
    # bottom_visible=True, і перевірка «не відкрито другу панель браузера»
    # падала б не через код, а через стан на диску.
    settings.ui.bottom_visible = False

    app = BlackChpokIDE(settings)
    app.withdraw()
    # Системний браузер під забороною на весь тест: якщо хтось його
    # викличе — це провал, а не «просто відкрилась вкладка».
    opened_external: list[str] = []

    def spy(url: str) -> bool:
        opened_external.append(url)
        return True

    try:
        with mock.patch("webbrowser.open", side_effect=spy):
            pump(app, 0.6)

            # ── 1. Спільний відкривач зареєстрований вікном
            check("вікно зареєструвало вбудований відкривач",
                  browser_panel.current_url_opener() is not None)

            # ── 2. Перехід на адресу з інтернету йде у вбудоване вікно
            app.open_url_in_browser("git-scm.com/download/win")
            pump(app, 0.4)
            check("сторінка git адресована вбудованому браузеру",
                  browser_panel.current_url_opener() is not None)
            check("системний браузер НЕ відкривався",
                  opened_external == [], str(opened_external))
            check("колонка прев'ю показана", app._preview_shown)

            view = app.live_preview.inner.view
            check("адреса нормалізована у вбудованому вікні",
                  view.url.startswith("https://"), view.url)

            # ── 3. Локальна адреса теж приймається
            check("локальна адреса приймається",
                  app.open_url_in_browser("127.0.0.1:8000/app"))
            pump(app, 0.2)
            check("локальна адреса стала http://",
                  view.url.startswith("http://127.0.0.1"), view.url)
            check("системний браузер досі не відкривався",
                  opened_external == [], str(opened_external))

            # ── 4. Локальний файл проєкту показується у вбудованому вікні
            page = ROOT / "README_UK.md"
            check("локальний файл відкрито як file://",
                  app.open_local_page(page))
            check("адреса файлу у вбудованому вікні",
                  view.url.startswith("file:///"), view.url)
            check("системний браузер не чіпали", opened_external == [])

            # ── 5. Сміттєва адреса не ламає нічого
            before = view.url
            app.open_url_in_browser("   ")
            pump(app, 0.1)
            check("порожня адреса ігнорується", view.url == before)
            app.open_url_in_browser("mailto:a@b.c")
            pump(app, 0.1)
            check("непридатна схема не відкривається", view.url == before)
            check("і не йде в системний браузер", opened_external == [])

            # ── 6. Панель змін теж не кличе системний браузер
            app.changes_panel._install_git()
            pump(app, 0.2)
            check("«Встановити git» не відкриває Chrome", opened_external == [],
                  str(opened_external))

            # ── 7. Майстер: усі чотири кроки живі
            wizard = FirstRunWizard(app, app.theme, settings)
            pump(app, 3.0)
            check("майстер створився", wizard.winfo_exists())
            check("кроків рівно чотири", len(STEPS) == 4)
            for key, label in STEPS:
                wizard.show_step(key)
                pump(app, 0.15)
                check(f"крок «{label}» показується", wizard.step == key)
            check("майстер не відкривав системний браузер", opened_external == [])

            # ── 8. Майстер справді бачить середовище
            check("бібліотеки перевірені", len(wizard.lib_rows) == len(env_setup.REQUIREMENTS),
                  f"{len(wizard.lib_rows)}")
            check("програми перевірені", len(wizard.tool_rows) == len(env_setup.TOOLS),
                  f"{len(wizard.tool_rows)}")
            titles = [str(wizard.libs_title.cget("text")),
                      str(wizard.tools_title.cget("text"))]
            check("заголовки показують кількість", all("—" in t for t in titles),
                  str(titles))

            # ── 9. Кнопки установки присутні лише для відсутнього
            missing = [row for row in wizard.tool_rows if not row.ok]
            check("для відсутньої програми є кнопка", all(row.actionable for row in missing)
                  if missing else True, f"{len(missing)} відсутніх")

            # ── 10. Закриття майстра не лишає сміття
            wizard.on_close_cleanup()
            wizard.destroy()
            pump(app, 0.2)
            check("майстер закрився", not wizard.winfo_exists())
            check("системний браузер так і не відкривався", opened_external == [],
                  str(opened_external))

            # ── 11. Локальний сайт проєкту відкривається у вбудованому вікні
            # Це частина 2 вимоги: «вбудований браузер відкриває локальні
            # сайти, зібрані в IDE». Регресія: start_site піднімав сервер,
            # але не показував сторінку — вікно лишалось порожнім.
            site = Path(tempfile.mkdtemp())
            (site / "index.html").write_text(
                "<html><head><meta charset='utf-8'></head><body>"
                "<h1>Локальний сайт</h1></body></html>", encoding="utf-8")
            app.set_workspace(site)
            pump(app, 0.5)
            app.open_site()
            pump(app, 6.0)
            check("сервер сайту піднявся", app.app.running)
            site_view = app.live_preview.inner.view
            check("сторінку показано у вбудованому браузері",
                  site_view.url.startswith("http://127.0.0.1"), site_view.url)
            check("вікно браузера справді вбудоване", site_view._embedded)
            check("системний браузер не чіпали й тут", opened_external == [],
                  str(opened_external))
            check("не відкрито другу панель браузера", not app._bottom_shown,
                  "нижня вкладка «Сайт» має лишатись закритою")
            app.stop_site()
            pump(app, 0.5)
            check("сайт зупиняється разом із браузером", not app.app.running)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        failures += 1
    finally:
        try:
            app.on_close()
        except Exception:  # noqa: BLE001
            pass

    print()
    print("Браузер і майстер: успішно" if failures == 0
          else f"Браузер і майстер: помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
