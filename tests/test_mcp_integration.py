"""Тести інтеграції MCP з агентом: два світи інструментів в одному.

Розділ 9 плану. В IDE живуть дві паралельні системи інструментів:

* **вбудовані** 19 (``agent_tools.ToolRegistry``) — працюють завжди;
* **MCP-сервери** (``mcp_client.McpManager``) — підключаються ззовні.

Треба переконатись, що агент бачить ОБИДВІ групи в одному списку схем,
викликає MCP-інструмент і повертає його результат у чат.

Використовуємо справжній stdio-сервер ``tests/fake_mcp_server.py`` —
жодних моків транспорту, лише підміна процесу на локальний скрипт.

Запуск: python -m unittest tests.test_mcp_integration -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAKE_SERVER = ROOT / "tests" / "fake_mcp_server.py"


class TestMcpServerStarts(unittest.TestCase):
    """Справжній MCP-сервер піднімається й віддає інструменти."""

    @classmethod
    def setUpClass(cls) -> None:
        from blackchpok_ide import mcp_client

        cls.mod = mcp_client
        config = mcp_client.McpServerConfig(
            name="fake",
            command=sys.executable,
            args=[str(FAKE_SERVER)],
            env={},
        )
        cls.manager = mcp_client.McpManager()
        try:
            cls.manager.add(config)
            cls.manager.start_all([config])
            cls.started = True
        except Exception as exc:  # noqa: BLE001 - сервер не піднявся
            cls.started = False
            cls.error = f"{type(exc).__name__}: {exc}"

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.manager.stop_all()
        except Exception:  # noqa: BLE001
            pass

    def setUp(self) -> None:
        if not self.started:
            raise unittest.SkipTest(f"MCP-сервер не піднявся: {self.error}")

    def test_server_running(self) -> None:
        self.assertTrue(self.manager.running_servers())

    def test_catalog_has_tools(self) -> None:
        catalog = self.manager.tool_catalog()
        names = {item["name"] for item in catalog}
        self.assertIn("echo", names)
        self.assertIn("fail", names)

    def test_schemas_are_openai_format(self) -> None:
        schemas = self.manager.tool_schemas()
        self.assertTrue(schemas, "сервер не віддав схем")
        for schema in schemas:
            self.assertEqual(schema.get("type"), "function", schema)
            func = schema.get("function") or {}
            self.assertTrue(func.get("name"), schema)
            self.assertIsInstance(func.get("parameters"), dict, schema)

    def test_schema_names_are_namespaced(self) -> None:
        schemas = self.manager.tool_schemas()
        for schema in schemas:
            name = schema["function"]["name"]
            self.assertTrue(name.startswith("mcp__"),
                            f"ім'я без простору імен: {name}")

    def test_call_echo_returns_text(self) -> None:
        schemas = self.manager.tool_schemas()
        target = next(s["function"]["name"] for s in schemas
                      if s["function"]["name"].endswith("echo"))
        ok, text = self.manager.call(target, {"text": "привіт-mcp"})
        self.assertTrue(ok, text)
        self.assertIn("привіт-mcp", text)

    def test_call_fail_reports_error(self) -> None:
        schemas = self.manager.tool_schemas()
        target = next(s["function"]["name"] for s in schemas
                      if s["function"]["name"].endswith("fail"))
        ok, text = self.manager.call(target, {})
        self.assertFalse(ok, "інструмент fail має повертати помилку")
        self.assertTrue(text)


class TestAgentSeesBothToolSets(unittest.TestCase):
    """Агент бачить вбудовані Й MCP-інструменти в одному списку."""

    @classmethod
    def setUpClass(cls) -> None:
        from blackchpok_ide import mcp_client

        cls.mod = mcp_client
        config = mcp_client.McpServerConfig(
            name="fake",
            command=sys.executable,
            args=[str(FAKE_SERVER)],
            env={},
        )
        cls.manager = mcp_client.McpManager()
        try:
            cls.manager.add(config)
            cls.manager.start_all([config])
            cls.started = True
        except Exception as exc:  # noqa: BLE001
            cls.started = False
            cls.error = f"{type(exc).__name__}: {exc}"

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.manager.stop_all()
        except Exception:  # noqa: BLE001
            pass

    def setUp(self) -> None:
        if not self.started:
            raise unittest.SkipTest(f"MCP-сервер не піднявся: {self.error}")
        from blackchpok_ide.agent import AgentRunner
        from blackchpok_ide.agent_tools import ToolRegistry
        from blackchpok_ide.config import AgentSettings, LLMSettings

        self.runner = AgentRunner(ToolRegistry(ROOT), LLMSettings(),
                                  AgentSettings(), ROOT)
        self.runner.mcp_manager = self.manager
        self.runner.settings_ref = None
        self.runner.tools_enabled = True

    def test_schemas_include_builtin_and_mcp(self) -> None:
        schemas = self.runner.tool_schemas()
        names = {schema["function"]["name"] for schema in schemas}
        # Вбудовані
        for builtin in ("read_file", "write_file", "list_dir", "run_command"):
            self.assertIn(builtin, names, f"немає вбудованого {builtin}")
        # MCP
        mcp_names = {name for name in names if name.startswith("mcp__")}
        self.assertTrue(mcp_names, f"немає MCP-інструментів у списку: {sorted(names)[:10]}")

    def test_no_duplicate_schema_names(self) -> None:
        schemas = self.runner.tool_schemas()
        names = [schema["function"]["name"] for schema in schemas]
        duplicates = {name for name in names if names.count(name) > 1}
        self.assertEqual(duplicates, set(), f"дублікати схем: {duplicates}")

    def test_agent_calls_mcp_tool(self) -> None:
        """call_tool агента виконує MCP-інструмент за його іменем."""
        schemas = self.runner.tool_schemas()
        target = next(s["function"]["name"] for s in schemas
                      if s["function"]["name"].endswith("echo"))
        outcome = self.runner.call_tool(target, '{"text": "агент-через-mcp"}')
        self.assertTrue(outcome.ok, outcome.output)
        self.assertIn("агент-через-mcp", outcome.output)

    def test_agent_calls_builtin_tool(self) -> None:
        """Вбудований інструмент працює поряд із MCP."""
        outcome = self.runner.call_tool("list_dir", '{"path": "."}')
        self.assertTrue(outcome.ok, outcome.output)

    def test_unknown_tool_reports_clearly(self) -> None:
        outcome = self.runner.call_tool("вигаданий_інструмент_123", "{}")
        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.output)

    def test_mcp_schemas_have_descriptions(self) -> None:
        schemas = [s for s in self.runner.tool_schemas()
                   if s["function"]["name"].startswith("mcp__")]
        for schema in schemas:
            self.assertTrue(schema["function"].get("description"),
                            f"{schema['function']['name']}: без опису")


class TestMcpWithoutServer(unittest.TestCase):
    """Без підключеного сервера все працює як раніше."""

    def setUp(self) -> None:
        from blackchpok_ide.agent import AgentRunner
        from blackchpok_ide.agent_tools import ToolRegistry
        from blackchpok_ide.config import AgentSettings, LLMSettings

        self.runner = AgentRunner(ToolRegistry(ROOT), LLMSettings(),
                                  AgentSettings(), ROOT)
        self.runner.settings_ref = None
        self.runner.tools_enabled = True

    def test_builtin_schemas_still_present(self) -> None:
        names = {schema["function"]["name"] for schema in self.runner.tool_schemas()}
        self.assertIn("read_file", names)
        self.assertIn("run_command", names)

    def test_no_mcp_names_without_manager(self) -> None:
        names = {schema["function"]["name"] for schema in self.runner.tool_schemas()}
        mcp_names = {name for name in names if name.startswith("mcp__")}
        self.assertEqual(mcp_names, set(),
                         "без менеджера MCP-схем бути не має")

    def test_broken_manager_does_not_break_agent(self) -> None:
        """Менеджер, що падає, не має ламати список інструментів."""

        class BrokenManager:
            def tool_catalog(self):
                raise RuntimeError("сервер зламався")

            def tool_schemas(self):
                raise RuntimeError("сервер зламався")

        self.runner.mcp_manager = BrokenManager()
        names = {schema["function"]["name"] for schema in self.runner.tool_schemas()}
        self.assertIn("read_file", names, "вбудовані інструменти мають лишитись")


class TestMcpResultInChat(unittest.TestCase):
    """Результат MCP-інструмента доходить до картки чату."""

    @classmethod
    def setUpClass(cls) -> None:
        import tkinter as tk
        import tkinter.messagebox as messagebox

        from blackchpok_ide import theme

        messagebox.askyesno = lambda *a, **k: True
        messagebox.showinfo = lambda *a, **k: None
        messagebox.showerror = lambda *a, **k: None

        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError as exc:  # pragma: no cover - без дисплея
            raise unittest.SkipTest(f"tkinter недоступний: {exc}") from exc
        cls.fonts = theme.Theme(cls.root)
        cls.fonts.apply()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def test_tool_result_event_reaches_transcript(self) -> None:
        from blackchpok_ide import theme
        from blackchpok_ide.agent import AgentEvent
        from blackchpok_ide.agent_tools import ToolRegistry
        from blackchpok_ide.chat_panel import ChatPanel
        from blackchpok_ide.config import Settings

        settings = Settings()
        settings.workspace = str(ROOT)
        panel = ChatPanel(self.root, self.fonts, settings, ToolRegistry(ROOT))
        panel.pack(fill="both", expand=True)
        self.root.update()

        # Такі події надсилає двигун агента після виклику MCP-інструмента.
        panel._handle_event(AgentEvent("tool_call", "mcp__fake__echo(text=…)",
                                       {"name": "mcp__fake__echo", "arguments": "text=…",
                                        "call_id": "c1"}))
        panel._handle_event(AgentEvent("tool_result", "привіт з MCP-сервера",
                                       {"name": "mcp__fake__echo", "ok": True,
                                        "call_id": "c1"}))
        panel._handle_event(AgentEvent("assistant", "Готово: привіт з MCP-сервера",
                                       {"final": True}))
        self.root.update()

        body = panel.transcript.get()
        self.assertIn("mcp__fake__echo", body)
        self.assertIn("привіт з MCP-сервера", body)
        self.assertGreaterEqual(len(panel._cards), 1)

    def test_mcp_error_shown_in_transcript(self) -> None:
        from blackchpok_ide.agent import AgentEvent
        from blackchpok_ide.agent_tools import ToolRegistry
        from blackchpok_ide.chat_panel import ChatPanel
        from blackchpok_ide.config import Settings

        settings = Settings()
        settings.workspace = str(ROOT)
        panel = ChatPanel(self.root, self.fonts, settings, ToolRegistry(ROOT))
        panel.pack(fill="both", expand=True)
        self.root.update()

        panel._handle_event(AgentEvent("tool_call", "mcp__fake__fail()",
                                       {"name": "mcp__fake__fail", "arguments": "",
                                        "call_id": "c2"}))
        panel._handle_event(AgentEvent("tool_result", "ПОМИЛКА: сервер відмовив",
                                       {"name": "mcp__fake__fail", "ok": False,
                                        "call_id": "c2"}))
        self.root.update()

        body = panel.transcript.get()
        self.assertIn("сервер відмовив", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
