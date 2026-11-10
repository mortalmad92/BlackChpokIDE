"""Тести запуску сайтів і вбудованого браузера.

Запуск:  python tests/test_web_preview.py
"""

from __future__ import annotations

import shutil
import sys
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import browser_panel, web_server  # noqa: E402

failures = 0
checked = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures, checked
    checked += 1
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def temp_dir() -> Path:
    folder = ROOT / ".buildtmp" / f"web-{uuid.uuid4().hex[:8]}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# ─────────────────────────────────────────────────────────────────────────────
# Визначення стеку
# ─────────────────────────────────────────────────────────────────────────────

def test_detect() -> None:
    folder = temp_dir()
    try:
        # ── статика
        site = folder / "static"
        site.mkdir()
        (site / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
        recipe = web_server.detect(site)
        check("статика розпізнана", recipe.kind == web_server.STATIC, recipe.kind)
        check("рецепт статики готовий", recipe.ok)
        check("позначка статики", recipe.icon == "🌐", recipe.icon)

        # ── Flask
        flask = folder / "flask"
        flask.mkdir()
        (flask / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n",
                                      encoding="utf-8")
        recipe = web_server.detect(flask)
        check("Flask розпізнано", recipe.kind == web_server.PYTHON, recipe.kind)
        check("команда запускає app.py",
              any("app.py" in part for part in recipe.command), str(recipe.command))
        check("причина вказана", "Flask" in recipe.reason, recipe.reason)

        # ── FastAPI
        fast = folder / "fast"
        fast.mkdir()
        (fast / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n",
                                      encoding="utf-8")
        recipe = web_server.detect(fast)
        check("FastAPI розпізнано", "uvicorn" in " ".join(recipe.command),
              str(recipe.command))
        check("FastAPI з --reload", "--reload" in recipe.command, str(recipe.command))

        # ── Django
        dj = folder / "django"
        dj.mkdir()
        (dj / "manage.py").write_text("import django\n", encoding="utf-8")
        recipe = web_server.detect(dj)
        check("Django розпізнано", "manage.py" in " ".join(recipe.command),
              str(recipe.command))

        # ── Node
        node = folder / "node"
        node.mkdir()
        (node / "package.json").write_text('{"scripts": {"dev": "vite"}}',
                                          encoding="utf-8")
        recipe = web_server.detect(node)
        check("Node.js розпізнано", recipe.kind == web_server.NODE, recipe.kind)
        check("Vite визначено", "Vite" in recipe.reason, recipe.reason)

        # ── порожня тека
        empty = folder / "empty"
        empty.mkdir()
        recipe = web_server.detect(empty)
        check("порожня тека — невідомо", recipe.kind == web_server.UNKNOWN, recipe.kind)
        check("порожня тека без команди", not recipe.command)

        # ── неіснуюча тека
        missing = web_server.detect(folder / "nope")
        check("неіснуюча тека не ламає", missing.kind == web_server.UNKNOWN)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_ports() -> None:
    port = web_server.free_port(8700)
    check("вільний порт знайдено", port >= 8700, str(port))
    check("порт справді вільний", not web_server.port_busy(port), str(port))


# ─────────────────────────────────────────────────────────────────────────────
# Реальний сервер
# ─────────────────────────────────────────────────────────────────────────────

def test_static_server() -> None:
    folder = temp_dir()
    server = None
    try:
        (folder / "index.html").write_text(
            "<html><body><h1>Мій сайт</h1></body></html>", encoding="utf-8")
        (folder / "style.css").write_text("h1 { color: red; }", encoding="utf-8")
        (folder / "app.js").write_text("console.log('ok')", encoding="utf-8")

        recipe = web_server.detect(folder)
        recipe.port = web_server.free_port(8800)
        server = web_server.DevServer(recipe)
        ok, detail = server.start()
        check("сервер запустився", ok, detail)
        check("адреса правильна", server.url.startswith("http://127.0.0.1:"), server.url)

        ready, note = web_server.wait_for_port(server.port, timeout=15)
        check("порт відповідає", ready, note)

        with urllib.request.urlopen(server.url, timeout=5) as response:
            body = response.read().decode("utf-8", "replace")
            headers = str(response.headers).lower()
        check("HTML віддається", "Мій сайт" in body, body[:40])
        check("кеш вимкнено (для живих змін)", "no-store" in headers,
              headers[:80])
        # Кодування обов'язкове: без нього браузер вгадує й показує
        # український текст кракозябрами (перевірено наживо).
        check("HTML віддається з кодуванням UTF-8", "charset=utf-8" in headers,
              headers[:120])

        with urllib.request.urlopen(server.url + "style.css", timeout=5) as response:
            css = response.read().decode("utf-8", "replace")
            css_headers = str(response.headers).lower()
        check("CSS віддається", "color: red" in css, css[:40])
        check("CSS теж з кодуванням", "charset=utf-8" in css_headers,
              css_headers[:80])

        with urllib.request.urlopen(server.url + "app.js", timeout=5) as response:
            js = response.read().decode("utf-8", "replace")
        check("JS віддається", "console.log" in js, js[:40])

        # Зміна файлу — має бути видно одразу
        (folder / "index.html").write_text("<h1>ОНОВЛЕНО</h1>", encoding="utf-8")
        with urllib.request.urlopen(server.url, timeout=5) as response:
            updated = response.read().decode("utf-8", "replace")
        check("зміну видно без перезапуску", "ОНОВЛЕНО" in updated, updated[:40])
    finally:
        if server is not None:
            server.stop()
        check("сервер зупинено", server is None or not server.running)
        shutil.rmtree(folder, ignore_errors=True)


def test_missing_entry() -> None:
    folder = temp_dir()
    try:
        recipe = web_server.Recipe(kind=web_server.NODE,
                                   command=["definitely-not-a-real-command-xyz"])
        missing = web_server.missing_tools(recipe)
        check("відсутній інструмент знайдено", bool(missing), str(missing))
        server = web_server.DevServer(recipe)
        ok, detail = server.start()
        check("запуск неіснуючої команди оброблено", not ok, detail[:60])
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_missing_tools_static() -> None:
    recipe = web_server.Recipe(kind=web_server.STATIC)
    check("статиці нічого не бракує", web_server.missing_tools(recipe) == [])


# ─────────────────────────────────────────────────────────────────────────────
# Браузер
# ─────────────────────────────────────────────────────────────────────────────

def test_browser_detection() -> None:
    found = browser_panel.browsers()
    check("браузери знайдено", len(found) >= 1, f"{len(found)} шт.")
    name, path = browser_panel.find_browser()
    check("назва браузера", bool(name), name)
    check("шлях існує", bool(path) and Path(path).exists(), path)


def test_browser_widget() -> None:
    import tkinter as tk

    from blackchpok_ide import theme

    root = tk.Tk()
    root.geometry("700x500")
    fonts = theme.Theme(root)
    fonts.apply()

    view = browser_panel.BrowserView(root, fonts)
    view.pack(fill="both", expand=True)

    def pump(seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            root.update()
            time.sleep(0.02)

    pump(0.5)
    check("віджет створено", view.winfo_exists() == 1)
    check("живе оновлення типово ввімкнено", view.live)
    view.toggle_live()
    check("вимикач живого оновлення працює", not view.live)
    view.toggle_live()
    check("вмикається назад", view.live)

    # Розкладка без сервера не має падати
    view.schedule_reload()
    pump(0.2)
    check("перезавантаження без адреси не падає", True)

    view.stop()
    pump(0.2)
    check("зупинка без запуску безпечна", not view.running)
    root.destroy()


def test_embed_api() -> None:
    """Windows API для вбудовування доступне."""
    check("система Windows", browser_panel.IS_WINDOWS,
          "лише Windows" if not browser_panel.IS_WINDOWS else "")
    if not browser_panel.IS_WINDOWS:
        return
    windows = browser_panel._enum_windows()
    check("перелік вікон доступний", isinstance(windows, list) and len(windows) > 0,
          f"{len(windows)} вікон")


def main() -> int:
    test_detect()
    test_ports()
    test_static_server()
    test_missing_entry()
    test_missing_tools_static()
    test_browser_detection()
    test_browser_widget()
    test_embed_api()
    print()
    print(f"Перевірено тверджень: {checked}")
    print("Сайт у браузері:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


# ── unittest-обгортка (додано 10.11.2026) ──────────────────────────────────
# Для `python -m unittest discover` ці перевірки раніше були невидимі:
# файл — скрипт із власним main(), а не TestCase. Тепер discover запускає
# його й падає, якщо main() повернув ненульовий код. Запуск як скрипт
# (`python tests/test_web_preview.py`) поводиться як раніше.
import unittest as _unittest  # noqa: E402


class _ScriptSuite(_unittest.TestCase):
    def test_script_passes(self) -> None:
        code = main()
        self.assertEqual(code, 0, f"main() повернув {code}")
