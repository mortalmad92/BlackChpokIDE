"""Тести панелі «Сайт»: визначення стеку й вбудований браузер.

Приводи з життя:

1. панель показувала «Стек не визначено» й не працювала, бо **цей**
   репозиторій визначався як FastAPI-застосунок (у ``server.py`` є слово
   ``uvicorn`` у рядку підказки), і прев'ю падало з
   ``FATAL: MCP_WORKSPACE не встановлено``;
2. у браузері не було пошуку: введені слова ставали безглуздою адресою
   ``https://погода київ``.

Запуск: python -m unittest tests.test_web_preview_stack -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import browser_panel, web_server  # noqa: E402

#: Справжній вебзастосунок (Flask).
FLASK_APP = (
    "from flask import Flask\n"
    "app = Flask(__name__)\n"
    "\n"
    "@app.route('/')\n"
    "def index():\n"
    "    return 'ok'\n"
)

#: Справжній FastAPI.
FASTAPI_APP = (
    "from fastapi import FastAPI\n"
    "app = FastAPI()\n"
)

#: MCP-сервер: НЕ вебзастосунок, хоч і згадує Flask/FastAPI у тексті.
MCP_SERVER = (
    '"""MCP-сервер.\n'
    "\n"
    "Якщо це сервер (Flask/FastAPI/Streamlit) — host 0.0.0.0.\n"
    '"""\n'
    "from mcp.server.mcpserver import MCPServer\n"
    "mcp = MCPServer('blackchpok')\n"
    "mcp.run()\n"
)


class TestLooksLikeWebApp(unittest.TestCase):
    """Ознаки вебзастосунку — це ІМПОРТИ, а не згадки слів."""

    def test_flask_is_web(self) -> None:
        is_web, why = web_server.looks_like_web_app(FLASK_APP)
        self.assertTrue(is_web, why)
        self.assertIn("flask", why)

    def test_fastapi_is_web(self) -> None:
        self.assertTrue(web_server.looks_like_web_app(FASTAPI_APP)[0])

    def test_mcp_server_is_not_web(self) -> None:
        """Головна регресія: MCP-сервер не має запускатись як сайт."""
        is_web, why = web_server.looks_like_web_app(MCP_SERVER)
        self.assertFalse(is_web, f"MCP-сервер визнано сайтом: {why}")
        self.assertIn("не сайт", why)

    def test_mention_without_import_is_not_web(self) -> None:
        code = 'text = "тут був Flask і FastAPI"\nprint(text)\n'
        self.assertFalse(web_server.looks_like_web_app(code)[0])

    def test_http_server_counts(self) -> None:
        code = "import http.server\nhttp.server.HTTPServer(('', 8000), None)\n"
        self.assertTrue(web_server.looks_like_web_app(code)[0])

    def test_plain_script_is_not_web(self) -> None:
        self.assertFalse(web_server.looks_like_web_app("print('hi')\n")[0])

    def test_tkinter_script_is_not_web(self) -> None:
        code = "import tkinter as tk\nroot = tk.Tk()\nroot.mainloop()\n"
        self.assertFalse(web_server.looks_like_web_app(code)[0])


class TestDetectProject(unittest.TestCase):
    """detect() на реальних теках."""

    def _folder(self, files: dict[str, str]) -> Path:
        folder = Path(tempfile.mkdtemp())
        for name, body in files.items():
            (folder / name).write_text(body, encoding="utf-8")
        return folder

    def test_flask_project(self) -> None:
        folder = self._folder({"app.py": FLASK_APP})
        recipe = web_server.detect(folder)
        self.assertEqual(recipe.kind, web_server.PYTHON)
        self.assertTrue(recipe.ok)
        self.assertIn("app.py", " ".join(recipe.command))

    def test_fastapi_project_uses_uvicorn(self) -> None:
        folder = self._folder({"main.py": FASTAPI_APP})
        recipe = web_server.detect(folder)
        self.assertIn("uvicorn", " ".join(recipe.command))

    def test_mcp_project_is_not_started_as_site(self) -> None:
        folder = self._folder({"server.py": MCP_SERVER})
        recipe = web_server.detect(folder)
        self.assertNotEqual(recipe.kind, web_server.PYTHON,
                            "MCP-сервер не можна запускати як сайт")

    def test_static_index_html(self) -> None:
        folder = self._folder({"index.html": "<h1>Привіт</h1>"})
        recipe = web_server.detect(folder)
        self.assertEqual(recipe.kind, web_server.STATIC)
        self.assertTrue(recipe.ok)

    def test_this_repo_is_not_fastapi(self) -> None:
        """Цей репозиторій — IDE, а не FastAPI-застосунок."""
        recipe = web_server.detect(ROOT)
        command = " ".join(recipe.command)
        self.assertNotIn("uvicorn", command,
                         f"репозиторій визнано FastAPI-застосунком: {recipe.reason}")


class TestBrowserAddress(unittest.TestCase):
    """Рядок адреси розуміє і адреси, і пошукові запити."""

    def test_full_url_kept(self) -> None:
        self.assertEqual(browser_panel.normalise_url("https://x.com/a"),
                         "https://x.com/a")

    def test_domain_gets_https(self) -> None:
        self.assertEqual(browser_panel.normalise_url("github.com"),
                         "https://github.com")

    def test_localhost_gets_http(self) -> None:
        self.assertEqual(browser_panel.normalise_url("localhost:8000"),
                         "http://localhost:8000")
        self.assertEqual(browser_panel.normalise_url("127.0.0.1:8080/app"),
                         "http://127.0.0.1:8080/app")

    def test_words_become_google_search(self) -> None:
        url = browser_panel.normalise_url("погода київ")
        self.assertIn("google.com.ua/search", url)
        self.assertIn("%D0", url, "кирилиця має бути закодована")

    def test_latin_words_become_search(self) -> None:
        url = browser_panel.normalise_url("fastapi tutorial")
        self.assertIn("google.com.ua/search", url)
        self.assertIn("fastapi+tutorial", url)

    def test_single_word_without_dot_searches(self) -> None:
        self.assertTrue(browser_panel.looks_like_query("fastapi"))
        self.assertIn("google", browser_panel.normalise_url("fastapi"))

    def test_domain_is_not_a_query(self) -> None:
        self.assertFalse(browser_panel.looks_like_query("github.com"))

    def test_other_scheme_kept(self) -> None:
        self.assertEqual(browser_panel.normalise_url("mailto:a@b.c"),
                         "mailto:a@b.c")

    def test_empty_stays_empty(self) -> None:
        self.assertEqual(browser_panel.normalise_url(""), "")
        self.assertEqual(browser_panel.search_url(""), "")

    def test_search_url_encodes(self) -> None:
        url = browser_panel.search_url("a b&c")
        self.assertIn("a+b%26c", url)


if __name__ == "__main__":
    unittest.main(verbosity=2)
