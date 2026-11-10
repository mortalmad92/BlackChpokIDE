"""Помилки сервера мають бути читабельними, а не \\u043c\\u043e\\u0434...

Реальний випадок: OpenAI-сумісний сервер віддає 500 із тілом, записаним
через ``json.dumps(..., ensure_ascii=True)``. Раніше користувач бачив у
діалозі сирий JSON з escape-послідовностями замість людського тексту.
"""
from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import llm_client  # noqa: E402


class TestHumanErrorBody(unittest.TestCase):
    """Прямі перевірки функції перетворення."""

    def test_escaped_cyrillic_is_decoded(self) -> None:
        escaped = json.dumps({"error": {"message": "модель впала"}},
                             ensure_ascii=True)
        self.assertIn("\\u", escaped, "тест має подавати саме escape-варіант")
        result = llm_client._human_error_body(escaped)
        self.assertEqual(result, "модель впала")
        self.assertNotIn("\\u", result)

    def test_plain_text_passes_through(self) -> None:
        self.assertEqual(llm_client._human_error_body("просто текст"),
                         "просто текст")

    def test_plain_json_without_escape_is_readable(self) -> None:
        body = json.dumps({"error": {"message": "немає памʼяті"}},
                          ensure_ascii=False)
        self.assertEqual(llm_client._human_error_body(body), "немає памʼяті")

    def test_error_as_string(self) -> None:
        body = json.dumps({"error": "помилка сервера"}, ensure_ascii=True)
        self.assertEqual(llm_client._human_error_body(body), "помилка сервера")

    def test_non_json_is_returned_as_is(self) -> None:
        self.assertEqual(llm_client._human_error_body("<html>oops</html>"),
                         "<html>oops</html>")

    def test_empty_returns_empty(self) -> None:
        self.assertEqual(llm_client._human_error_body(""), "")
        self.assertEqual(llm_client._human_error_body("   "), "")

    def test_long_body_is_truncated(self) -> None:
        result = llm_client._human_error_body("x" * 5000)
        self.assertLessEqual(len(result), 800)

    def test_json_without_message_still_decoded(self) -> None:
        body = json.dumps({"деталь": "щось трапилось"}, ensure_ascii=True)
        result = llm_client._human_error_body(body)
        self.assertNotIn("\\u", result)
        self.assertIn("трапилось", result)


class _EscapedErrorHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(
            {"error": {"message": "модель впала: немає памʼяті"}},
            ensure_ascii=True).encode("utf-8"))

    def log_message(self, *args):  # noqa: ANN002
        pass


class TestRealHttpErrorIsReadable(unittest.TestCase):
    """Наскрізна перевірка: справжній HTTP-сервер віддає 500."""

    def test_http_500_message_is_human(self) -> None:
        server = HTTPServer(("127.0.0.1", 0), _EscapedErrorHandler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            client = llm_client.LLMClient(
                base_url=f"http://127.0.0.1:{port}/v1", api_key="x", model="m")
            with self.assertRaises(llm_client.LLMError) as ctx:
                client.chat([{"role": "user", "content": "hi"}])
            text = str(ctx.exception)
            self.assertIn("500", text)
            self.assertIn("модель впала", text,
                          f"текст помилки нечитабельний: {text}")
            self.assertNotIn("\\u", text,
                             f"лишились escape-послідовності: {text}")
            self.assertNotIn("\\u043c", text)
        finally:
            server.shutdown()


if __name__ == "__main__":
    unittest.main(verbosity=2)
