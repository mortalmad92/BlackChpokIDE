"""Автовизначення порту й самодіагностика: регресії реального збою.

Що сталося насправді (лог користувача):

```
17:09:47 Старт рушія: … --port 8081        ← 8080 тримав Steam
17:11:18 LLM недоступна: HTTP 404 від http://127.0.0.1:8080/v1/…
```

Модель працювала. Клієнт стукав у чужий порт. У інтерфейсі це виглядало
як «модель не працює», і причина не була видна ніде.

Ці тести фіксують:

* пошук робочого порту (а не довіра налаштуванням);
* відрізнення «наш рушій» від «стороння програма на тому ж порту»;
* діагностику, яка називає причину й що зробити;
* великий статус «МОДЕЛЬ ОНЛАЙН / ОФЛАЙН»;
* вивантаження попередньої моделі при перемиканні.

Запуск: python -m unittest tests.test_port_discovery -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchp-port-"))
os.environ["BLACKCHPOK_NO_SAVE"] = "1"


class _FakeServer:
    """Мінімальний HTTP-сервер на вільному порту (для перевірки портів).

    ``mode``:
    * ``healthy`` — ``/health`` → 200 (як llama-server);
    * ``auth``    — ``/health`` → 404, ``/v1/models`` → 401 (потрібен ключ);
    * ``stranger``— усе 404 (як Steam: порт зайнятий, але це не рушій).
    """

    def __init__(self, mode: str = "healthy") -> None:
        self.mode = mode
        handler = self._handler()

        class _Server(HTTPServer):
            daemon_threads = True

            def log_message(self, *_args):  # pragma: no cover
                pass

        self.httpd = _Server(("127.0.0.1", 0), handler)
        self.port = int(self.httpd.server_address[1])
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    def _handler(self):
        mode = self.mode

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def _send(self, code: int, body: bytes = b"{}") -> None:
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                path = self.path.split("?")[0]
                if mode == "healthy":
                    if path == "/health":
                        return self._send(200, b'{"status":"ok"}')
                    if path == "/v1/models":
                        return self._send(200, b'{"data":[]}')
                    return self._send(404)
                if mode == "auth":
                    if path == "/health":
                        return self._send(404)
                    if path == "/v1/models":
                        return self._send(401)
                    return self._send(404)
                return self._send(404)

            def do_POST(self) -> None:
                self._send(404)

        return Handler

    def stop(self) -> None:
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:  # noqa: BLE001
            pass


class TestServerResponds(unittest.TestCase):
    """``server_responds`` має відрізняти наш рушій від сторонньої програми."""

    def setUp(self) -> None:
        self.servers: list[_FakeServer] = []

    def tearDown(self) -> None:
        for server in self.servers:
            server.stop()

    def _make(self, mode: str) -> _FakeServer:
        server = _FakeServer(mode)
        self.servers.append(server)
        return server

    def test_healthy_engine_is_recognised(self) -> None:
        from blackchpok_ide import runtime

        server = self._make("healthy")
        self.assertTrue(
            runtime.server_responds(f"http://127.0.0.1:{server.port}/v1"))

    def test_key_protected_engine_is_recognised(self) -> None:
        """Рушій із --api-key відповідає 401 на /v1/models, але він НАШ.

        Дефект. Перевірка йшла лише в ``/v1/models`` без ключа й вважала
        робочий сервер мертвим — через це адреса 8081 не знаходилась.
        """
        from blackchpok_ide import runtime

        server = self._make("auth")
        self.assertTrue(
            runtime.server_responds(f"http://127.0.0.1:{server.port}/v1"))

    def test_stranger_on_port_is_rejected(self) -> None:
        """Steam на 8080 слухає порт, але це не рушій — має бути False."""
        from blackchpok_ide import runtime

        server = self._make("stranger")
        self.assertFalse(
            runtime.server_responds(f"http://127.0.0.1:{server.port}/v1"))

    def test_closed_port_is_rejected(self) -> None:
        from blackchpok_ide import runtime

        port = runtime.free_port(9200)
        self.assertFalse(runtime.server_responds(f"http://127.0.0.1:{port}/v1"))


class TestDiscoverServerUrl(unittest.TestCase):
    """Пошук робочої адреси замість довіри налаштуванням."""

    def setUp(self) -> None:
        self.servers: list[_FakeServer] = []

    def tearDown(self) -> None:
        for server in self.servers:
            server.stop()

    def test_finds_live_port_when_configured_is_dead(self) -> None:
        """Реальний сценарій: наш рушій на іншому порту, ніж у налаштуваннях.

        Саме це сталося в лозі користувача: 8080 тримав Steam, рушій пішов
        на 8081. Порт рушія записується у файл PID під час запуску, тому
        пошук бере його звідти — без сканування навмання.
        """
        from unittest import mock

        from blackchpok_ide import runtime

        server = _FakeServer("healthy")
        self.servers.append(server)
        stranger = _FakeServer("stranger")
        self.servers.append(stranger)

        # Наш рушій записаний із фактичним портом (так робить LocalServer).
        with mock.patch.object(runtime, "live_server_ports",
                               return_value=[{"pid": os.getpid(),
                                              "port": server.port,
                                              "model": "fake"}]):
            found = runtime.discover_server_url(
                f"http://127.0.0.1:{stranger.port}/v1")
        self.assertEqual(found, f"http://127.0.0.1:{server.port}/v1")
        self.assertTrue(runtime.server_responds(found), found)

    def test_preferred_port_is_checked_first(self) -> None:
        """Якщо налаштований порт робочий — його й повертаємо."""
        from blackchpok_ide import runtime

        server = _FakeServer("healthy")
        self.servers.append(server)
        url = f"http://127.0.0.1:{server.port}/v1"
        self.assertEqual(runtime.discover_server_url(url), url)

    def test_empty_when_nothing_listens(self) -> None:
        from blackchpok_ide import runtime

        port = runtime.free_port(9400)
        found = runtime.discover_server_url(f"http://127.0.0.1:{port}/v1")
        # Сканування діапазону 8080.. може знайти чужий рушій на машині,
        # тому перевіряємо саме те, що «мертвий» порт не повертається.
        self.assertNotEqual(found, f"http://127.0.0.1:{port}/v1")


class TestDiagnosticsReport(unittest.TestCase):
    """Самодіагностика називає причину й що зробити."""

    def _settings(self, *, base_url: str, model: str = "m", model_path: str = ""):
        from blackchpok_ide.config import Settings

        settings = Settings()
        settings.llm.base_url = base_url
        settings.llm.model = model
        settings.engine.model_path = model_path
        return settings

    def test_reports_dead_configured_port(self) -> None:
        from blackchpok_ide import diagnostics, runtime

        port = runtime.free_port(9300)
        settings = self._settings(base_url=f"http://127.0.0.1:{port}/v1")
        report = diagnostics.run(settings=settings, probe_inference=False)
        names = {item.name: item for item in report.checks}
        self.assertIn("Адреса з налаштувань", names)
        self.assertFalse(names["Адреса з налаштувань"].ok)
        self.assertTrue(report.verdict, "висновок має бути непорожнім")
        # Кожен збій мусить мати підказку, що робити.
        for item in report.failures:
            self.assertTrue(item.fix, f"немає підказки для «{item.name}»")

    def test_reports_missing_model_file(self) -> None:
        from blackchpok_ide import diagnostics

        settings = self._settings(
            base_url="http://127.0.0.1:1/v1",
            model_path=str(Path(tempfile.mkdtemp()) / "nope.gguf"))
        report = diagnostics.run(settings=settings, probe_inference=False)
        names = {item.name: item for item in report.checks}
        self.assertFalse(names["Файл моделі"].ok)
        self.assertIn("вибери модель", names["Файл моделі"].fix.lower())

    def test_verdict_is_human_readable(self) -> None:
        from blackchpok_ide import diagnostics

        settings = self._settings(base_url="http://127.0.0.1:1/v1")
        report = diagnostics.run(settings=settings, probe_inference=False)
        self.assertGreater(len(report.verdict), 20)


class TestBigModelStatus(unittest.TestCase):
    """Великий статус моделі: ВЕЛИКІ ЛІТЕРИ, зелений/червоний кружечок."""

    @classmethod
    def setUpClass(cls) -> None:
        try:
            import tkinter as tk

            from blackchpok_ide import theme

            cls.root = tk.Tk()
            cls.root.withdraw()
            cls.fonts = theme.Theme(cls.root)
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(f"tkinter недоступний: {exc}") from exc

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def _bar(self):
        from blackchpok_ide import header_bar

        bar = header_bar.HeaderBar(
            self.root, self.fonts,
            on_command=lambda _k: None, on_menu=lambda _a, _b: None,
            on_palette=lambda: None, on_project_menu=lambda _a: None,
            on_model_menu=lambda _a: None, on_agent_menu=lambda _a: None,
            on_git_menu=lambda _a: None, on_more_menu=lambda _a: None,
        )
        bar.pack()
        self.root.update()
        return bar

    def test_online_is_green_and_uppercase(self) -> None:
        from blackchpok_ide import theme

        bar = self._bar()
        try:
            bar.set_model_status(True)
            self.root.update()
            text = str(bar.model_status.cget("text"))
            self.assertIn("ОНЛАЙН", text)
            self.assertEqual(text, text.upper(), "підпис мусить бути великими")
            self.assertEqual(str(bar.model_status.cget("fg")), theme.SUCCESS)
        finally:
            bar.destroy()

    def test_offline_is_red_and_uppercase(self) -> None:
        from blackchpok_ide import theme

        bar = self._bar()
        try:
            bar.set_model_status(False)
            self.root.update()
            text = str(bar.model_status.cget("text"))
            self.assertIn("ОФЛАЙН", text)
            self.assertEqual(text, text.upper())
            self.assertEqual(str(bar.model_status.cget("fg")), theme.ERROR)
        finally:
            bar.destroy()

    def test_unknown_state_is_not_green(self) -> None:
        """Поки стан невідомий — жодного вигаданого зеленого."""
        from blackchpok_ide import theme

        bar = self._bar()
        try:
            bar.set_model_status(None)
            self.root.update()
            self.assertNotEqual(str(bar.model_status.cget("fg")), theme.SUCCESS)
        finally:
            bar.destroy()

    def test_click_opens_diagnostics(self) -> None:
        calls: list[str] = []
        from blackchpok_ide import header_bar

        bar = header_bar.HeaderBar(
            self.root, self.fonts,
            on_command=lambda _k: None, on_menu=lambda _a, _b: None,
            on_palette=lambda: None, on_project_menu=lambda _a: None,
            on_model_menu=lambda _a: None, on_agent_menu=lambda _a: None,
            on_git_menu=lambda _a: None, on_more_menu=lambda _a: None,
            on_status_click=lambda: calls.append("diagnostics"),
        )
        bar.pack()
        self.root.update()
        try:
            bar._on_model_status_click()
            self.assertEqual(calls, ["diagnostics"])
        finally:
            bar.destroy()


class TestSwitchUnloadsPreviousModel(unittest.TestCase):
    """Перемикання моделі мусить зупинити попередню (звільнити VRAM)."""

    def test_hub_ready_stops_previous(self) -> None:
        import inspect

        from blackchpok_ide import main_window

        source = inspect.getsource(
            main_window.BlackChpokIDE._on_hub_model_ready)
        self.assertIn("_stop_previous_model", source)

    def test_stop_previous_stops_server(self) -> None:
        import inspect

        from blackchpok_ide import main_window

        source = inspect.getsource(
            main_window.BlackChpokIDE._stop_previous_model)
        self.assertIn("server.stop()", source)
        self.assertIn("cleanup_stale_processes", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
