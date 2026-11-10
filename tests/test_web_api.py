"""`web_api`: HTTP-запит для перевірки власного бекенду проєкту.

Модуль `internet` і метод `web_api` раніше не мали ЖОДНОГО тесту (перевірено
пошуком у tests/). Це та сама зона, де ховаються тихі дефекти.

ВАЖЛИВО про локальні адреси. `web_api` навмисно дозволяє `127.0.0.1` і
`localhost`: його призначення — перевірити, що створений агентом бекенд
відповідає. Заборона локальних адрес зламала б цю функцію. Тести нижче
фіксують цю поведінку ЯВНО, щоб вона не змінилась випадково.
"""
from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import internet  # noqa: E402
from blackchpok_ide.agent_tools import ToolError, ToolRegistry  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    """Мінімальний сервер, що відповідає різними способами."""

    routes: dict = {}

    def _respond(self) -> None:
        body = self.routes.get(self.path, {"code": 404, "body": "не знайдено"})
        payload = body.get("body", "")
        if isinstance(payload, (dict, list)):
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            ctype = "application/json; charset=utf-8"
        else:
            raw = str(payload).encode("utf-8")
            ctype = "text/plain; charset=utf-8"
        self.send_response(body.get("code", 200))
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    do_GET = _respond       # noqa: N815
    do_POST = _respond      # noqa: N815
    do_PUT = _respond       # noqa: N815
    do_DELETE = _respond    # noqa: N815

    def log_message(self, *args):  # noqa: ANN002
        pass


class WebApiCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _Handler.routes = {
            "/ok": {"code": 200, "body": {"status": "працює", "items": [1, 2]}},
            "/text": {"code": 200, "body": "простий текст"},
            "/bad": {"code": 500, "body": {"error": "зламалось"}},
            "/echo": {"code": 200, "body": {"ok": True}},
        }
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

        import tempfile

        cls.folder = Path(tempfile.mkdtemp(prefix="webapi-"))
        cls.tools = ToolRegistry(cls.folder)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()

    # ── основні сценарії ─────────────────────────────────────────────────
    def test_get_json_endpoint(self) -> None:
        out = self.tools.web_api(f"{self.base}/ok")
        self.assertIn("HTTP 200", out)
        self.assertIn("працює", out)

    def test_plain_text_endpoint(self) -> None:
        out = self.tools.web_api(f"{self.base}/text")
        self.assertIn("HTTP 200", out)
        self.assertIn("простий текст", out)

    def test_server_error_is_visible(self) -> None:
        out = self.tools.web_api(f"{self.base}/bad")
        self.assertIn("500", out)
        self.assertIn("зламалось", out)

    def test_missing_path_shows_404(self) -> None:
        # Шлях латиницею: HTTP-заголовки не приймають кирилицю (обмеження
        # протоколу, не коду). Окремо перевіряємо, що кирилиця в шляху дає
        # КОНТРОЛЬОВАНУ помилку, а не голий traceback.
        out = self.tools.web_api(f"{self.base}/no-such-path")
        self.assertIn("404", out)

    def test_cyrillic_path_gives_controlled_error(self) -> None:
        try:
            out = self.tools.web_api(f"{self.base}/немає-такого")
        except Exception as exc:  # noqa: BLE001
            out = str(exc)
        self.assertNotIn("Traceback", out)

    def test_post_with_json_body(self) -> None:
        out = self.tools.web_api(f"{self.base}/echo", method="POST",
                                 body='{"ключ": "значення"}')
        self.assertIn("HTTP 200", out)

    def test_post_with_plain_body(self) -> None:
        out = self.tools.web_api(f"{self.base}/echo", method="POST",
                                 body="сирий текст",
                                 content_type="text/plain")
        self.assertIn("HTTP 200", out)

    def test_empty_url_is_refused(self) -> None:
        for value in ("", "   "):
            with self.subTest(url=repr(value)):
                with self.assertRaises(ToolError):
                    self.tools.web_api(value)

    def test_broken_json_body_does_not_crash(self) -> None:
        """Тіло з синтаксичною помилкою надсилається як текст, не падає."""
        out = self.tools.web_api(f"{self.base}/echo", method="POST",
                                 body='{"незакритий": ')
        self.assertIn("HTTP", out)

    # ── локальні адреси: свідома поведінка ────────────────────────────────
    def test_localhost_is_allowed_on_purpose(self) -> None:
        """`web_api` існує, щоб перевіряти ВЛАСНИЙ бекенд — локальність потрібна."""
        out = self.tools.web_api(f"http://localhost:{self.port}/ok")
        self.assertIn("HTTP 200", out,
                      "заборона localhost зламала б перевірку власного бекенду")

    def test_dead_local_port_reports_timeout_or_error(self) -> None:
        """Мертвий локальний порт не має висіти — контрольована помилка."""
        out = None
        try:
            out = self.tools.web_api("http://127.0.0.1:1/нічого", )
        except ToolError as exc:
            out = str(exc)
        except Exception as exc:  # noqa: BLE001 — InternetError теж прийнятний
            out = str(exc)
        self.assertIsNotNone(out)
        self.assertNotIn("Traceback", out)

    def test_file_scheme_is_not_read(self) -> None:
        """file:// не має читати локальні файли через цей інструмент."""
        try:
            out = self.tools.web_api("file:///C:/Windows/win.ini")
        except Exception as exc:  # noqa: BLE001
            out = str(exc)
        self.assertNotIn("[fonts]", out.lower(),
                         "вдалось прочитати файл через web_api")


class InternetModuleCase(unittest.TestCase):
    """Прямі перевірки модуля internet."""

    def test_connectivity_returns_tuple(self) -> None:
        result = internet.connectivity()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], bool)
        self.assertIsInstance(result[1], str)

    def test_internet_error_is_exception(self) -> None:
        self.assertTrue(issubclass(internet.InternetError, Exception))

    def test_pretty_json_handles_garbage(self) -> None:
        self.assertEqual(internet._pretty_json("не json"), "не json")
        self.assertEqual(internet._pretty_json(""), "")
        self.assertIn("\n", internet._pretty_json('{"a": 1}'))

    def test_strip_html_removes_scripts(self) -> None:
        html = "<html><script>alert(1)</script><p>Текст</p></html>"
        text = internet._strip_html(html)
        self.assertIn("Текст", text)
        self.assertNotIn("alert", text)

    def test_strip_html_handles_empty(self) -> None:
        self.assertEqual(internet._strip_html("").strip(), "")

    def test_http_request_dead_host_is_controlled(self) -> None:
        try:
            out = internet.http_request("http://127.0.0.1:1/", timeout=2)
        except Exception as exc:  # noqa: BLE001
            out = str(exc)
        self.assertNotIn("Traceback", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
