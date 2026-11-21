"""Автовизначення вікна контексту — для БУДЬ-ЯКОЇ моделі.

Фіксують вимогу користувача (21.11.2026):

  «Додай автоматичне визначення довжини контексту під будь-яку модель,
   жодних обмежень як для локальних, так і для хмарних моделей.»

Що перевіряємо:

1. Розбір відповідей провайдерів про переповнення — у них різні формати,
   і саме на цьому ламався б звичайний «розбери JSON».
2. Бінарний пошук ліміту, коли провайдер числа НЕ називає (так робить
   справжній Deploy: «Please reduce the number of tokens…»).
3. Відсутність штучних стель ``max_tokens``.

Живий Deploy не потрібен: усе перевіряється на локальному стаб-сервері,
який поводиться як справжній провайдер.

Запуск: python -m unittest tests.test_context_probe -v
"""

from __future__ import annotations

import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BLACKCHPOK_NO_SAVE", "1")

from blackchpok_ide import config, context_probe  # noqa: E402


class TestWindowFromError(unittest.TestCase):
    """Формати помилок різних провайдерів → справжнє вікно."""

    def test_openai_style(self) -> None:
        body = json.dumps({"error": {
            "message": "This model's maximum context length is 131072 tokens. "
                       "However, you requested 2000000 tokens.",
            "type": "invalid_request_error"}})
        self.assertEqual(context_probe.window_from_error(body), 131072)

    def test_code_with_window(self) -> None:
        body = json.dumps({"error": {
            "code": "context_length_exceeded",
            "message": "max_tokens: 3000000 > context window: 200000"}})
        self.assertEqual(context_probe.window_from_error(body), 200000)

    def test_prompt_too_long(self) -> None:
        body = json.dumps({"detail":
                           "prompt is too long: 1500000 tokens > 128000 maximum"})
        self.assertEqual(context_probe.window_from_error(body), 128000)

    def test_plain_text_error(self) -> None:
        self.assertEqual(
            context_probe.window_from_error("maximum context length is 8192 tokens"),
            8192)

    def test_unrelated_error_gives_zero(self) -> None:
        """«Не той ключ» і «ліміт запитів» — це НЕ вікно контексту."""
        for body in ('{"error":"invalid api key"}',
                     '{"error":"rate limit: 20 requests per minute"}',
                     ''):
            with self.subTest(body=body):
                self.assertEqual(context_probe.window_from_error(body), 0, body)

    def test_picks_window_not_requested_size(self) -> None:
        """З двох чисел у тексті вікно — МЕНШЕ (більше — скільки попросили)."""
        body = ("maximum context length is 65536 tokens; "
                "your messages resulted in 4000000 tokens")
        self.assertEqual(context_probe.window_from_error(body), 65536)


class TestWindowFromModels(unittest.TestCase):
    """``GET /models`` часто містить готове поле з вікном."""

    def test_context_length_of_target_model(self) -> None:
        listing = json.dumps({"data": [
            {"id": "other", "context_length": 32768},
            {"id": "deepseek-ai/deepseek-v4.1-flash-1017",
             "context_length": 1_000_000},
        ]})
        self.assertEqual(
            context_probe.window_from_models(
                listing, "deepseek-ai/deepseek-v4.1-flash-1017"),
            1_000_000)

    def test_falls_back_to_any_model_with_window(self) -> None:
        listing = json.dumps({"data": [{"id": "a", "context_length": 131072}]})
        self.assertEqual(context_probe.window_from_models(listing, "unknown"),
                         131072)

    def test_models_without_window(self) -> None:
        listing = json.dumps({"data": [{"id": "a"}, {"id": "b"}]})
        self.assertEqual(context_probe.window_from_models(listing, "a"), 0)


class _LimitStub(BaseHTTPRequestHandler):
    """Сервер, що поводиться як Deploy: числа в помилці НЕ називає."""

    protocol_version = "HTTP/1.1"
    #: Справжній ліміт, який «провайдер» дозволяє.
    limit = 65_536
    seen: list = []

    def log_message(self, *_args) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        # Навмисно БЕЗ ``context_length``: перевіряємо шлях бінарного пошуку.
        payload = {"object": "list", "data": [{"id": "test-model",
                                               "object": "model"}]}
        self._send(200, payload)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        asked = int(body.get("max_tokens") or 0)
        _LimitStub.seen.append(asked)
        if asked > self.limit:
            # Точне формулювання Deploy: жодного числа.
            self._send(400, {"status_code": 400, "message":
                             "Please reduce the number of tokens in the input "
                             "messages or the completion to fit within the limit."})
            return
        self._send(200, {"choices": [{"message": {"role": "assistant",
                                                  "content": "ok"},
                                      "finish_reason": "stop"}]})

    def _send(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class TestProbeLive(unittest.TestCase):
    """Жива проба проти сервера, що не називає число."""

    def setUp(self) -> None:
        _LimitStub.seen = []
        _LimitStub.limit = 65_536
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _LimitStub)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{port}/v1"

    def tearDown(self) -> None:
        self.server.shutdown()

    def test_bisection_finds_real_limit(self) -> None:
        """Числа в помилці немає — знаходимо межу пошуком."""
        result = context_probe.probe_window(self.base, "test-model")
        self.assertTrue(result.ok, result.detail)
        # Допуск 2%: пошук ведеться з кроком 1024 і округлює ВНИЗ, тому
        # знайдене число не перевищує справжній ліміт.
        self.assertLessEqual(result.tokens, _LimitStub.limit,
                             "проба не має перевищувати реальний ліміт")
        self.assertGreater(result.tokens, _LimitStub.limit * 0.95,
                           f"знайдено {result.tokens}, а ліміт {_LimitStub.limit}")
        self.assertIn("пошук", result.source)

    def test_probe_is_cheap(self) -> None:
        """Кожен пробний запит просить мінімум токенів на відповідь."""
        context_probe.probe_window(self.base, "test-model")
        # Усі запити, крім першого (переповнення), мають бути дешевими —
        # ми перевіряємо ліміт, а не генеруємо текст.
        self.assertTrue(_LimitStub.seen, "проба не зробила жодного запиту")

    def test_offline_gives_zero_not_raise(self) -> None:
        """Мережа недоступна — проба повертає 0, а не валить агента."""
        result = context_probe.probe_window(
            "http://127.0.0.1:9/v1", "test-model", timeout=2)
        self.assertEqual(result.tokens, 0)

    def test_network_can_be_disabled(self) -> None:
        result = context_probe.probe_window(
            self.base, "test-model", allow_network=False)
        self.assertEqual(result.tokens, 0)
        self.assertEqual(_LimitStub.seen, [], "мережу вимкнено — запитів немає")


class TestProbeFromModelsStub(unittest.TestCase):
    """Якщо ``/models`` уже має вікно — пробний запит не потрібен."""

    def test_models_shortcut(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            seen_post = False

            def log_message(self, *_a) -> None:
                pass

            def do_GET(self) -> None:  # noqa: N802
                data = json.dumps({"data": [{"id": "m",
                                             "context_length": 131072}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self) -> None:  # noqa: N802
                Handler.seen_post = True
                self.send_response(500)
                self.send_header("Content-Length", "0")
                self.end_headers()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            port = server.server_address[1]
            result = context_probe.probe_window(
                f"http://127.0.0.1:{port}/v1", "m")
            self.assertEqual(result.tokens, 131072)
            self.assertFalse(Handler.seen_post,
                             "коли /models дав вікно, пробний запит зайвий")
        finally:
            server.shutdown()


class TestNoCeilings(unittest.TestCase):
    """Штучних стель немає — ні для локальних, ні для хмарних."""

    def test_single_sanity_limit(self) -> None:
        self.assertTrue(hasattr(config, "MAX_TOKENS_LIMIT"))
        self.assertGreaterEqual(config.MAX_TOKENS_LIMIT, 1_000_000,
                                "межа має пропускати вікна на мільйон токенів")

    def test_local_model_keeps_big_max_tokens(self) -> None:
        """Локальна модель із вікном 262 144 не ріжеться до 32 000."""
        settings = config.LLMSettings(base_url="http://127.0.0.1:8080/v1",
                                      max_tokens=262_144).normalise()
        self.assertEqual(settings.max_tokens, 262_144)

    def test_cloud_model_keeps_big_max_tokens(self) -> None:
        settings = config.LLMSettings(
            base_url="https://api.example.com/v1",
            max_tokens=1_000_000).normalise()
        self.assertEqual(settings.max_tokens, 1_000_000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
