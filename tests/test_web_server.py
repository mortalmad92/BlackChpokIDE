"""Тести запуску застосунку проєкту (живий прев'ю).

``web_server`` — 473 рядки без тестів: він визначає, ЯК запустити проєкт
користувача (Node, Flask, FastAPI, Django, статика) і керує процесом.
Помилка тут означає «кнопка ▶ Запустити сайт не працює».

Перевіряємо справжні файли й справжній процес, без мережі.

Запуск: python -m unittest tests.test_web_server -v
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import web_server  # noqa: E402


class TestDetectNode(unittest.TestCase):
    """Визначення Node.js-проєктів."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())

    def write(self, name: str, text: str) -> None:
        (self.folder / name).write_text(text, encoding="utf-8")

    def test_vite_project(self) -> None:
        self.write("package.json", '{"scripts": {"dev": "vite"}}')
        recipe = web_server.detect(self.folder)
        self.assertTrue(recipe.ok)
        self.assertIn("npm", " ".join(recipe.command))
        self.assertIn("vite", (recipe.reason or "").lower())

    def test_next_project(self) -> None:
        self.write("package.json", '{"scripts": {"dev": "next dev"}}')
        recipe = web_server.detect(self.folder)
        self.assertTrue(recipe.ok)
        self.assertEqual(recipe.port, 3000, "Next.js працює на 3000")

    def test_npm_start(self) -> None:
        self.write("package.json", '{"scripts": {"start": "node index.js"}}')
        recipe = web_server.detect(self.folder)
        self.assertTrue(recipe.ok)
        self.assertIn("start", " ".join(recipe.command))

    def test_package_without_scripts_is_not_node(self) -> None:
        self.write("package.json", '{"name": "x"}')
        recipe = web_server.detect(self.folder)
        self.assertNotEqual(recipe.kind, web_server.NODE)


class TestDetectPython(unittest.TestCase):
    """Визначення Python-проєктів."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())

    def write(self, name: str, text: str) -> None:
        (self.folder / name).write_text(text, encoding="utf-8")

    def test_flask_app(self) -> None:
        self.write("app.py", "from flask import Flask\napp = Flask(__name__)\n")
        recipe = web_server.detect(self.folder)
        self.assertTrue(recipe.ok)
        self.assertIn("Flask", recipe.reason)

    def test_fastapi_app(self) -> None:
        self.write("main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
        recipe = web_server.detect(self.folder)
        self.assertTrue(recipe.ok)
        self.assertIn("uvicorn", " ".join(recipe.command))

    def test_django_manage(self) -> None:
        self.write("manage.py", "import django\n")
        recipe = web_server.detect(self.folder)
        self.assertTrue(recipe.ok)
        self.assertIn("runserver", " ".join(recipe.command))


class TestDetectStatic(unittest.TestCase):
    """Статичний сайт (index.html)."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())

    def test_index_html_gives_static_recipe(self) -> None:
        (self.folder / "index.html").write_text("<h1>тест</h1>", encoding="utf-8")
        recipe = web_server.detect(self.folder)
        self.assertTrue(recipe.ok, recipe.reason)

    def test_empty_folder_is_not_ok(self) -> None:
        recipe = web_server.detect(self.folder)
        self.assertFalse(recipe.ok)
        self.assertTrue(recipe.reason, "має бути причина відмови")

    def test_missing_folder_is_not_ok(self) -> None:
        recipe = web_server.detect(self.folder / "немає")
        self.assertFalse(recipe.ok)


class TestPorts(unittest.TestCase):
    """Робота з портами."""

    def test_free_port_returns_positive(self) -> None:
        self.assertGreater(web_server.free_port(18000), 0)

    def test_port_busy_is_bool(self) -> None:
        self.assertIsInstance(web_server.port_busy(18099), bool)

    def test_wait_for_port_times_out_on_free_port(self) -> None:
        ok, note = web_server.wait_for_port(18098, timeout=0.4)
        self.assertFalse(ok)
        self.assertTrue(note)


class TestRecipeAndHelpers(unittest.TestCase):
    """Структура рецепта й допоміжні функції."""

    def test_recipe_command_is_list(self) -> None:
        recipe = web_server.Recipe(kind="python", command=["python", "app.py"])
        self.assertIsInstance(recipe.command, list)

    def test_missing_tools_empty_for_python(self) -> None:
        recipe = web_server.Recipe(
            kind=web_server.PYTHON,
            command=[sys.executable, "app.py"],
            cwd=str(ROOT))
        self.assertEqual(web_server.missing_tools(recipe), [])

    def test_missing_tools_reports_absent_program(self) -> None:
        recipe = web_server.Recipe(
            kind=web_server.NODE,
            command=["вигадана-програма-якої-немає-12345"],
            cwd=str(ROOT))
        missing = web_server.missing_tools(recipe)
        self.assertEqual(len(missing), 1)

    def test_describe_returns_text(self) -> None:
        recipe = web_server.Recipe(kind=web_server.PYTHON, command=[sys.executable],
                                   reason="тест")
        self.assertTrue(web_server.describe(recipe))

    def test_find_entry_looks_for_names(self) -> None:
        folder = Path(tempfile.mkdtemp())
        (folder / "index.html").write_text("x", encoding="utf-8")
        found = web_server.find_entry(folder, ["index.html", "app.py"])
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "index.html")

    def test_read_handles_missing_file(self) -> None:
        folder = Path(tempfile.mkdtemp())
        self.assertEqual(web_server._read(folder / "немає.txt"), "")


class TestDevServerLifecycle(unittest.TestCase):
    """Справжній запуск і зупинка процесу."""

    def test_start_and_stop_python_site(self) -> None:
        folder = Path(tempfile.mkdtemp())
        # Найпростіший сервер: вбудований http.server на вільному порту.
        script = folder / "site.py"
        script.write_text(
            "import http.server, socketserver, sys\n"
            "port = int(sys.argv[1])\n"
            "with socketserver.TCPServer(('127.0.0.1', port),\n"
            "        http.server.SimpleHTTPRequestHandler) as srv:\n"
            "    srv.serve_forever()\n",
            encoding="utf-8")
        port = web_server.free_port(18100)
        recipe = web_server.Recipe(
            kind=web_server.PYTHON,
            command=[sys.executable, "site.py", str(port)],
            cwd=str(folder), port=port, reason="тестовий сервер")
        server = web_server.DevServer(recipe)
        try:
            ok, detail = server.start()
            self.assertTrue(ok, detail)
            ready, note = web_server.wait_for_port(port, timeout=25)
            self.assertTrue(ready, note)
        finally:
            server.stop()
        # Після зупинки порт має звільнитись.
        deadline = time.time() + 6
        while time.time() < deadline and web_server.port_busy(port):
            time.sleep(0.2)
        self.assertFalse(web_server.port_busy(port), "порт лишився зайнятим")

    def test_server_tail_returns_text(self) -> None:
        folder = Path(tempfile.mkdtemp())
        recipe = web_server.Recipe(kind=web_server.PYTHON,
                                   command=[sys.executable, "-c", "print(1)"],
                                   cwd=str(folder), port=web_server.free_port(18200))
        server = web_server.DevServer(recipe)
        try:
            self.assertIsInstance(server.tail(5), str)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)
