"""Тести MCP-наглядача: виявлення смерті, зависання, відновлення.

Фіксують вимогу: сервер, що помер або завис, має бути ПОМІЧЕНИЙ і
відновлений. Успішний сервер чіпати не можна.

Запуск:
    python -m unittest tests.test_mcp_watch -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchp-watch-"))
os.environ["BLACKCHPOK_NO_SAVE"] = "1"

from blackchpok_ide import mcp_watch  # noqa: E402


class FakeConfig:
    def __init__(self, name: str = "fake", enabled: bool = True) -> None:
        self.name = name
        self.enabled = enabled


class FakeClient:
    """Мінімальна підміна ``McpClient`` для перевірки наглядача."""

    def __init__(self, *, running: bool = True, tools: list | None = None,
                 raise_on_list: bool = False) -> None:
        self.config = FakeConfig()
        self.running = running
        self._tools = tools if tools is not None else [
            {"name": "echo", "inputSchema": {"type": "object"}}]
        self.raise_on_list = raise_on_list
        self.list_calls = 0

    def list_tools(self):
        self.list_calls += 1
        if self.raise_on_list:
            raise TimeoutError("сервер не відповів")
        return self._tools


class FakeManager:
    def __init__(self, servers: dict) -> None:
        self.servers = dict(servers)
        self.added: list[str] = []
        self.new_client: FakeClient | None = None

    def add(self, config, start: bool = True):
        self.added.append(config.name)
        self.new_client = FakeClient()
        self.servers[config.name] = self.new_client
        return self.new_client


class TestHealthDetection(unittest.TestCase):
    """Наглядач мусить розрізняти живий, мертвий і завислий сервер."""

    def setUp(self) -> None:
        self.watcher = mcp_watch.Watcher(FakeManager({}))

    def test_healthy_server(self) -> None:
        health = self.watcher._inspect("s", FakeClient())
        self.assertTrue(health.ok)
        self.assertEqual(health.status, mcp_watch.HEALTHY)
        self.assertEqual(health.tools, 1)

    def test_dead_process_is_detected(self) -> None:
        health = self.watcher._inspect("s", FakeClient(running=False))
        self.assertFalse(health.ok)
        self.assertEqual(health.status, mcp_watch.DEAD)

    def test_hung_server_is_detected(self) -> None:
        """Сервер, що не відповідає, не має вважатись здоровим."""
        health = self.watcher._inspect("s", FakeClient(raise_on_list=True))
        self.assertFalse(health.ok)
        self.assertEqual(health.status, mcp_watch.HUNG)
        self.assertIn("не відповів", health.last_error)

    def test_server_without_tools_is_not_healthy(self) -> None:
        health = self.watcher._inspect("s", FakeClient(tools=[]))
        self.assertFalse(health.ok)
        self.assertIn("інструмент", health.last_error)

    def test_disabled_server_is_skipped(self) -> None:
        client = FakeClient()
        client.config.enabled = False
        health = self.watcher._inspect("s", client)
        self.assertTrue(health.ok)
        self.assertEqual(health.status, mcp_watch.DISABLED)


class TestRecovery(unittest.TestCase):
    """Відновлення хворого сервера."""

    def test_dead_server_is_restarted(self) -> None:
        client = FakeClient(running=False)
        manager = FakeManager({"s": client})
        watcher = mcp_watch.Watcher(manager)
        watcher.remember([FakeConfig("s")])
        report = watcher.check_once()
        self.assertEqual(report.restarted, ["s"])
        self.assertEqual(manager.added, ["s"],
                         "сервер має бути перезапущений через manager.add")
        health = watcher.report()[0]
        self.assertTrue(health.ok)
        self.assertEqual(health.status, mcp_watch.RECOVERED)
        self.assertEqual(health.restarts, 1)

    def test_healthy_server_is_never_restarted(self) -> None:
        """ГОЛОВНЕ: робочий сервер не можна чіпати."""
        manager = FakeManager({"s": FakeClient()})
        watcher = mcp_watch.Watcher(manager)
        watcher.remember([FakeConfig("s")])
        report = watcher.check_once()
        self.assertEqual(report.restarted, [])
        self.assertEqual(manager.added, [],
                         "успішний сервер перезапускати заборонено")
        self.assertEqual(report.healthy, 1)

    def test_restart_limit(self) -> None:
        """Після вичерпання спроб наглядач припиняє спроби."""
        client = FakeClient(running=False)
        manager = FakeManager({"s": client})
        # add повертає клієнт без інструментів — «відновлення» не вдається
        manager.add = lambda config, start=True: FakeClient(tools=[])
        watcher = mcp_watch.Watcher(manager)
        watcher.remember([FakeConfig("s")])
        for _ in range(mcp_watch.MAX_RESTARTS + 2):
            watcher.check_once()
        health = watcher.report()[0]
        self.assertFalse(health.ok)
        self.assertGreaterEqual(health.restarts, mcp_watch.MAX_RESTARTS)

    def test_no_config_means_no_restart(self) -> None:
        manager = FakeManager({"s": FakeClient(running=False)})
        watcher = mcp_watch.Watcher(manager)
        report = watcher.check_once()
        self.assertEqual(report.restarted, [])
        self.assertEqual(report.failed, ["s"])


class TestDiagnostics(unittest.TestCase):
    """Діагностика має бути зрозумілою."""

    def test_empty_report(self) -> None:
        watcher = mcp_watch.Watcher(FakeManager({}))
        text = watcher.diagnostics()
        self.assertTrue("не підключено" in text or "немає" in text, text)

    def test_report_lists_each_server(self) -> None:
        manager = FakeManager({"a": FakeClient(), "b": FakeClient(running=False)})
        watcher = mcp_watch.Watcher(manager)
        watcher.check_once()
        text = watcher.diagnostics()
        self.assertIn("a", text)
        self.assertIn("b", text)
        self.assertIn("✓", text)
        self.assertIn("✗", text)

    def test_report_summary_counts(self) -> None:
        manager = FakeManager({"a": FakeClient(), "b": FakeClient()})
        watcher = mcp_watch.Watcher(manager)
        report = watcher.check_once()
        self.assertEqual(report.checked, 2)
        self.assertEqual(report.healthy, 2)
        self.assertIn("2 з 2", report.text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
