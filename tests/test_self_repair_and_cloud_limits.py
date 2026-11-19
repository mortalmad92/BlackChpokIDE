"""Тести саморемонту IDE, віконних лімітів і захисту від застарілого кеша.

Перевіряються рівно ті збої, які видно на скріншотах користувача:

* агент не міг створити файл, бо політика блокувала ``write_file``
  («Користувач заборонив цю дію: видалення наявних даних»);
* модель читала файл, змінювала його, читала ще раз — і отримувала
  СТАРИЙ вміст із кеша дублікатів, після чого переписувала файл знову;
* ліміти кроків, контексту й пам'яті були однакові для локальної моделі
  на 8k і для хмари на 1M, тому хмара працювала врівень із локальною.

Модуль не потребує мережі, моделі чи вікна: усе перевіряється чистими
функціями на тимчасовій теці.
"""

from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path

from blackchpok_ide import cloud_agents, config, memory_bridge, permissions
from blackchpok_ide import selflearning, selfrepair, tool_orchestrator, tool_specs


class TestWriteBlockedByConstraint(unittest.TestCase):
    """«Не видаляй наявне» не має забороняти створення НОВОГО файлу."""

    def setUp(self) -> None:
        from blackchpok_ide import agent as agent_module

        self.agent_module = agent_module
        self.tmp = Path(tempfile.mkdtemp())
        self.stub = types.SimpleNamespace()
        self.stub.workspace = ""
        self.stub.intent = None
        self.stub._looks_like_test_run = agent_module.AgentRunner._looks_like_test_run
        self.stub._target_exists = agent_module.AgentRunner._target_exists.__get__(
            self.stub, type(self.stub))

    def _forbidden(self, tool: str, path: str, constraint: str) -> str:
        self.stub.intent = types.SimpleNamespace(constraints=[constraint])
        return self.agent_module.AgentRunner._forbidden_by_user_request(
            self.stub, tool, {"path": path})

    def test_new_file_allowed_despite_delete_constraint(self) -> None:
        """Створення файлу, якого ще немає, — не видалення наявних даних."""
        new_file = self.tmp / "calculator_new.py"
        self.assertEqual(
            self._forbidden("write_file", str(new_file),
                            "не видаляти наявні дані"),
            "")

    def test_existing_file_still_protected(self) -> None:
        """Перезапис НАЯВНОГО файлу лишається забороненим."""
        existing = self.tmp / "existing.py"
        existing.write_text("x = 1\n", encoding="utf-8")
        self.assertEqual(
            self._forbidden("write_file", str(existing),
                            "не видаляти наявні дані"),
            "видалення наявних даних")

    def test_append_to_new_file_allowed(self) -> None:
        new_file = self.tmp / "notes.txt"
        self.assertEqual(
            self._forbidden("append_file", str(new_file),
                            "не видаляти наявні дані"),
            "")

    def test_delete_always_blocked(self) -> None:
        """``delete_file`` знищує наявне завжди — без винятків для нових."""
        self.assertEqual(
            self._forbidden("delete_file", str(self.tmp / "whatever.py"),
                            "не видаляти наявні дані"),
            "видалення наявних даних")

    def test_no_constraint_allows_everything(self) -> None:
        existing = self.tmp / "existing.py"
        existing.write_text("x = 1\n", encoding="utf-8")
        self.stub.intent = None
        self.assertEqual(
            self.agent_module.AgentRunner._forbidden_by_user_request(
                self.stub, "write_file", {"path": str(existing)}), "")


class TestStaleToolCache(unittest.TestCase):
    """Після запису кеш результатів мусить скидатись."""

    def _specs(self):
        return tool_specs.specs_for_schemas([
            {"type": "function", "function": {
                "name": "read_file", "description": "read",
                "parameters": {"type": "object",
                               "properties": {"path": {"type": "string"}},
                               "required": ["path"]}}},
            {"type": "function", "function": {
                "name": "write_file", "description": "write",
                "parameters": {"type": "object",
                               "properties": {"path": {"type": "string"},
                                              "content": {"type": "string"}},
                               "required": ["path", "content"]}}},
        ])

    def test_read_after_write_returns_new_content(self) -> None:
        state = {"content": "OLD"}

        def executor(name, data):
            if name == "write_file":
                state["content"] = "NEW"
                return True, "written"
            return True, state["content"]

        orch = tool_orchestrator.Orchestrator(executor, specs=self._specs())
        self.assertEqual(
            orch.run("read_file", {"path": "a.py"}, call_id="1").output, "OLD")
        orch.run("write_file", {"path": "a.py", "content": "x"}, call_id="2")
        again = orch.run("read_file", {"path": "a.py"}, call_id="3")
        self.assertEqual(again.output, "NEW",
                         "модель отримала застарілий вміст із кеша")
        self.assertFalse(again.duplicate)

    def test_repeated_read_still_deduplicated(self) -> None:
        """Без змін стану повторне читання однаково береться з кеша."""
        def executor(name, data):
            return True, "SAME"

        orch = tool_orchestrator.Orchestrator(executor, specs=self._specs())
        orch.run("read_file", {"path": "a.py"}, call_id="1")
        second = orch.run("read_file", {"path": "a.py"}, call_id="2")
        self.assertTrue(second.duplicate)

    def test_rate_limit_is_transient(self) -> None:
        """429 — тимчасова помилка: її лікує повтор, а не здача."""
        self.assertTrue(tool_orchestrator._is_transient(
            "HTTP 429 Too Many Requests: rate limit"))
        self.assertTrue(tool_orchestrator._is_transient("503 Service Unavailable"))


class TestCloudLimitsScale(unittest.TestCase):
    """Стелі для хмари мають бути більшими, ніж для локального рушія."""

    def test_cloud_ceiling_above_local(self) -> None:
        cloud = config.LLMSettings(
            base_url="https://api.deploy.com/api/v1", max_tokens=150_000)
        cloud.normalise()
        local = config.LLMSettings(
            base_url="http://127.0.0.1:1234/v1", max_tokens=150_000)
        local.normalise()
        self.assertEqual(cloud.max_tokens, 150_000)
        self.assertEqual(local.max_tokens, config.LOCAL_MAX_TOKENS_CEILING)
        self.assertGreater(cloud.max_tokens, local.max_tokens)

    def test_embedded_engine_keeps_local_ceiling(self) -> None:
        native = config.LLMSettings(
            base_url="native://blackchpok", max_tokens=150_000).normalise()
        self.assertEqual(native.max_tokens, config.LOCAL_MAX_TOKENS_CEILING)

    def test_recall_limit_grows_with_window(self) -> None:
        self.assertEqual(memory_bridge.recall_limit(8_192),
                         memory_bridge.DEFAULT_LIMIT)
        self.assertEqual(memory_bridge.recall_limit(1_000_000),
                         memory_bridge.LARGE_WINDOW_LIMIT)
        self.assertGreater(memory_bridge.item_chars(1_000_000),
                           memory_bridge.item_chars(8_192))

    def test_lesson_limit_grows_with_window(self) -> None:
        self.assertEqual(selflearning.recall_limit(8_192),
                         selflearning.RECALL_LIMIT)
        self.assertEqual(selflearning.recall_limit(128_000),
                         selflearning.RECALL_LIMIT_LARGE)

    def test_cloud_catalog_windows_are_real(self) -> None:
        """Каталог провайдерів справді віддає великі вікна."""
        deploy = cloud_agents.get("deploy")
        self.assertIsNotNone(deploy)
        self.assertGreaterEqual(deploy.context, 100_000)


class TestSelfRepair(unittest.TestCase):
    """Самодіагностика й безпечний ремонт."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def test_missing_workspace_is_reported_and_created(self) -> None:
        target = self.tmp / "not_yet"
        report = selfrepair.diagnose(workspace=str(target))
        codes = {item.code for item in report.findings}
        self.assertIn("workspace.missing", codes)
        self.assertFalse(report.ok)

        selfrepair.repair_self(report)
        self.assertTrue(target.exists())
        self.assertGreaterEqual(report.fixed, 1)

    def test_broken_json_detected_and_not_rewritten(self) -> None:
        """Пошкоджений стан показуємо, але НЕ переписуємо навмання."""
        settings = self.tmp / "settings.json"
        settings.write_text('{"a": 1,,}', encoding="utf-8")
        before = settings.read_text(encoding="utf-8")
        report = selfrepair.diagnose(settings_path=str(settings))
        codes = {item.code for item in report.findings}
        self.assertIn("settings.broken", codes)

        selfrepair.repair_self(report)
        self.assertEqual(settings.read_text(encoding="utf-8"), before,
                         "саморемонт не має вгадувати втрачений вміст")

    def test_broken_source_is_repaired_only_if_compilable(self) -> None:
        pkg = self.tmp / "pkg"
        pkg.mkdir()
        broken = pkg / "bad.py"
        broken.write_text("x = input('Введіть ім'я: ')\n", encoding="utf-8")

        report = selfrepair.diagnose(package_root=str(pkg))
        self.assertIn("source.broken", {item.code for item in report.findings})

        selfrepair.repair_self(report)
        fixed = broken.read_text(encoding="utf-8")
        self.assertIn('"', fixed)
        compile(fixed, str(broken), "exec", dont_inherit=True)

    def test_healthy_package_reports_nothing(self) -> None:
        pkg = self.tmp / "ok_pkg"
        pkg.mkdir()
        (pkg / "good.py").write_text("y = 1\n", encoding="utf-8")
        report = selfrepair.diagnose(package_root=str(pkg))
        self.assertEqual(report.findings, [])
        self.assertTrue(report.ok)

    def test_empty_registry_is_reported(self) -> None:
        report = selfrepair.diagnose(registry_names=[])
        codes = {item.code for item in report.findings}
        self.assertIn("tools.empty", codes)

    def test_report_uses_ukrainian_plurals(self) -> None:
        report = selfrepair.RepairReport(checked=3)
        text = report.summary()
        self.assertIn("3 файли", text)
        self.assertIn("гаразд", text)


class TestSelfRepairPermissions(unittest.TestCase):
    """Діагностику можна завжди, ремонт — лише коли запис дозволено."""

    def test_diagnose_allowed_even_read_only(self) -> None:
        decision = permissions.check_tool(
            "self_diagnose", {}, mode=permissions.READ_ONLY, root=".")
        self.assertTrue(decision.allowed)

    def test_repair_blocked_in_read_only(self) -> None:
        decision = permissions.check_tool(
            "self_repair", {}, mode=permissions.READ_ONLY, root=".")
        self.assertFalse(decision.allowed)

    def test_repair_allowed_in_workspace(self) -> None:
        decision = permissions.check_tool(
            "self_repair", {}, mode=permissions.WORKSPACE, root=".")
        self.assertTrue(decision.allowed)


if __name__ == "__main__":
    unittest.main()
