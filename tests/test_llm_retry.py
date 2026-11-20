"""Повторні спроби запиту до моделі видно в чаті.

Перевіряємо весь ланцюг: ``LLMClient.on_retry`` → подія ``llm_retry`` в
агенті → рядок у журналі роботи. Мережі не потрібно: клієнт кличемо
напряму, а сервер імітуємо через ``urllib`` із 429.

Запуск:  python -m unittest tests.test_llm_retry -v
"""

from __future__ import annotations

import sys
import tkinter as tk
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import llm_client, theme, work_log  # noqa: E402


class TestRetryCallback(unittest.TestCase):
    """Клієнт повідомляє про кожну повторну спробу."""

    def _client(self, events: list) -> llm_client.LLMClient:
        return llm_client.LLMClient(
            "http://127.0.0.1:9/v1", "m",
            on_retry=lambda *args: events.append(args),
        )

    def test_http_429_reports_each_attempt(self) -> None:
        events: list = []
        client = self._client(events)
        error = urllib.error.HTTPError(
            "http://127.0.0.1:9/v1/chat/completions", 429, "Too Many", {},
            mock.MagicMock(read=lambda: b'{"error":"rate"}'))

        # Прискорюємо: без реальних пауз між спробами.
        with mock.patch.object(llm_client.time, "sleep", lambda _s: None), \
                mock.patch.object(client, "_open", side_effect=error):
            with self.assertRaises(llm_client.LLMError):
                client._request_text("http://127.0.0.1:9/v1/chat/completions", {})

        self.assertTrue(events, "жодного повідомлення про повтор")
        # Остання спроба не повідомляється (повторювати вже нічого).
        self.assertEqual(len(events), llm_client.RETRY_ATTEMPTS - 1)
        attempt, total, wait, reason = events[0]
        self.assertEqual(attempt, 1)
        self.assertEqual(total, llm_client.RETRY_ATTEMPTS)
        self.assertGreaterEqual(wait, 0.0)
        self.assertIn("429", reason)

    def test_success_does_not_report(self) -> None:
        events: list = []
        client = self._client(events)
        response = mock.MagicMock()
        response.read.return_value = b'{"ok": true}'
        response.__enter__ = lambda self: self
        response.__exit__ = lambda *args: False
        with mock.patch.object(client, "_open", return_value=response):
            body = client._request_text("http://x/v1/chat", {})
        self.assertIn("ok", body)
        self.assertEqual(events, [])

    def test_callback_error_does_not_break_request(self) -> None:
        """Зламаний зворотний виклик не має зривати сам запит."""
        def boom(*_args) -> None:
            raise RuntimeError("інтерфейс зник")

        client = llm_client.LLMClient("http://127.0.0.1:9/v1", "m", on_retry=boom)
        error = urllib.error.HTTPError(
            "http://x", 503, "Unavailable", {}, mock.MagicMock(read=lambda: b"{}"))
        response = mock.MagicMock()
        response.read.return_value = b'{"ok": true}'
        response.__enter__ = lambda self: self
        response.__exit__ = lambda *args: False
        calls = {"n": 0}

        def open_side_effect(*_a, **_k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise error
            return response

        with mock.patch.object(llm_client.time, "sleep", lambda _s: None), \
                mock.patch.object(client, "_open", side_effect=open_side_effect):
            body = client._request_text("http://x", {})
        self.assertIn("ok", body, "запит мав пройти попри зламаний callback")


class TestAgentEmitsRetry(unittest.TestCase):
    """Агент перетворює виклик клієнта на подію ``llm_retry``."""

    def test_emit_llm_retry(self) -> None:
        from blackchpok_ide.agent import AgentRunner
        from blackchpok_ide.agent_tools import ToolRegistry
        from blackchpok_ide.config import AgentSettings, LLMSettings

        runner = AgentRunner(ToolRegistry(ROOT),
                             LLMSettings(model="m", base_url="http://127.0.0.1:9/v1"),
                             AgentSettings(), ROOT)
        runner._on_llm_retry(2, 4, 3.0, "HTTP 429")
        events = []
        while True:
            try:
                events.append(runner.events.get_nowait())
            except Exception:  # noqa: BLE001 - черга порожня
                break
        retries = [e for e in events if e.kind == "llm_retry"]
        self.assertEqual(len(retries), 1, [e.kind for e in events])
        event = retries[0]
        self.assertIn("2/4", event.text)
        self.assertIn("3 с", event.text)
        self.assertEqual(event.data.get("attempt"), 2)
        self.assertEqual(event.data.get("total"), 4)


class TestWorkLogRetryRow(unittest.TestCase):
    """Рядок повтору у журналі роботи."""

    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self) -> None:
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def test_retry_row_is_warning_coloured(self) -> None:
        log = work_log.WorkLog(self.root, theme.Theme(self.root), wrap_width=600)
        log.pack(fill="x")
        row = log.add_retry(1, 4, 2.0, "HTTP 429")
        self.root.update()
        self.assertIsNotNone(row)
        self.assertEqual(row.kind, work_log.KIND_RETRY)
        self.assertEqual(row.icon.cget("text"), "↻")
        self.assertEqual(row.label.cget("fg"), theme.WARN)
        text = row.label.cget("text")
        self.assertIn("1/4", text)
        self.assertIn("2 с", text)
        self.assertIn("HTTP 429", text)

    def test_same_attempt_updates_in_place(self) -> None:
        """Той самий номер спроби не плодить другий рядок."""
        log = work_log.WorkLog(self.root, theme.Theme(self.root), wrap_width=600)
        log.pack(fill="x")
        log.add_retry(1, 4, 2.0, "HTTP 429")
        log.add_retry(1, 4, 2.0, "HTTP 429")
        self.root.update()
        retries = [r for r in log._rows if r.kind == work_log.KIND_RETRY]
        self.assertEqual(len(retries), 1)

    def test_different_attempt_adds_row(self) -> None:
        log = work_log.WorkLog(self.root, theme.Theme(self.root), wrap_width=600)
        log.pack(fill="x")
        log.add_retry(1, 4, 2.0, "HTTP 429")
        log.add_retry(2, 4, 4.0, "HTTP 429")
        self.root.update()
        retries = [r for r in log._rows if r.kind == work_log.KIND_RETRY]
        self.assertEqual(len(retries), 2)
        self.assertIn("2/4", retries[1].label.cget("text"))


if __name__ == "__main__":
    unittest.main()
