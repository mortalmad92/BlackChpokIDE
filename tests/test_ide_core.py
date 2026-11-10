"""Юніт-тести ядра BlackChpok IDE (без графіки).

Запуск:
    .venv\\Scripts\\python.exe -m unittest tests.test_ide_core -v
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blackchpok_ide import workspace as ws  # noqa: E402
from blackchpok_ide.agent_tools import TOOL_SCHEMAS, ToolRegistry, ToolResult  # noqa: E402
from blackchpok_ide.agent import AgentSession, _pretty_arguments  # noqa: E402
from blackchpok_ide.config import AgentSettings, LLMSettings, Settings  # noqa: E402
from blackchpok_ide.llm_client import ChatResult, LLMClient, LLMError  # noqa: E402
from blackchpok_ide.offline import OfflinePlanner  # noqa: E402
from blackchpok_ide.syntax import highlighter_for, language_for  # noqa: E402

TEMP_ROOT = ROOT / ".buildtmp"


def make_temp_dir() -> Path:
    """Тимчасова тека без режиму 0700 (у пісочниці такий режим забороняє запис)."""
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    target = TEMP_ROOT / f"test-{uuid.uuid4().hex[:12]}"
    os.makedirs(target, exist_ok=True)
    return target


def drop_temp_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


class TempWorkspace(unittest.TestCase):
    """Спільна тимчасова тека для тестів інструментів."""

    def setUp(self) -> None:
        self.root = make_temp_dir()
        (self.root / "module.py").write_text(
            "def hello(name):\n    return f'hi {name}'\n\n\nclass Box:\n    pass\n",
            encoding="utf-8",
        )
        (self.root / "sub").mkdir()
        (self.root / "sub" / "data.json").write_text('{"a": 1}\n', encoding="utf-8")
        self.registry = ToolRegistry(self.root)

    def tearDown(self) -> None:
        drop_temp_dir(self.root)


class TestWorkspace(TempWorkspace):
    def test_safe_join_rejects_escape(self) -> None:
        with self.assertRaises(ws.WorkspaceError):
            ws.safe_join(self.root, "../outside.txt")
        self.assertEqual(ws.safe_join(self.root, "module.py"), (self.root / "module.py").resolve())

    def test_read_write_roundtrip(self) -> None:
        target = self.root / "new.txt"
        ws.write_text_file(target, "один\nдва\n")
        self.assertFalse(Path(str(target) + ".bak").exists(), "для нового файлу копія не потрібна")
        ws.write_text_file(target, "три\n")
        content, encoding = ws.read_text_file(target)
        self.assertEqual(content, "три\n")
        self.assertTrue(encoding.startswith("utf-8"))
        backup = Path(str(target) + ".bak")
        self.assertTrue(backup.exists(), "перезапис існуючого файлу має лишити .bak")
        self.assertEqual(backup.read_text(encoding="utf-8"), "один\nдва\n")

    def test_search_text(self) -> None:
        hits = ws.search_text(self.root, "hello")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].line, 1)

    def test_search_regex_and_glob(self) -> None:
        hits = ws.search_text(self.root, r"def\s+\w+", regex=True, glob="*.py")
        self.assertEqual(len(hits), 1)
        empty = ws.search_text(self.root, "def", glob="*.json")
        self.assertEqual(empty, [])

    def test_search_bad_regex(self) -> None:
        with self.assertRaises(ws.WorkspaceError):
            ws.search_text(self.root, "([", regex=True)

    def test_relative_to_root(self) -> None:
        self.assertEqual(ws.relative_to_root(self.root, self.root / "sub" / "data.json"), "sub/data.json")

    def test_binary_detected(self) -> None:
        binary = self.root / "blob.bin"
        binary.write_bytes(b"\x00\x01\x02")
        with self.assertRaises(ws.WorkspaceError):
            ws.read_text_file(binary)


class TestTools(TempWorkspace):
    def test_read_file_with_range(self) -> None:
        result = self.registry.call("read_file", {"path": "module.py", "start_line": 1, "end_line": 2})
        self.assertTrue(result.ok)
        self.assertIn("def hello", result.output)
        self.assertNotIn("class Box", result.output)

    def test_write_and_edit(self) -> None:
        created = self.registry.call("write_file", {"path": "made.py", "content": "x = 1\n"})
        self.assertTrue(created.ok)
        edited = self.registry.call("edit_file", {"path": "made.py", "old_string": "x = 1", "new_string": "x = 2"})
        self.assertTrue(edited.ok)
        content, _ = ws.read_text_file(self.root / "made.py")
        self.assertEqual(content.strip(), "x = 2")

    def test_edit_requires_unique_match(self) -> None:
        self.registry.call("write_file", {"path": "dup.py", "content": "a\na\n"})
        ambiguous = self.registry.call("edit_file", {"path": "dup.py", "old_string": "a", "new_string": "b"})
        self.assertFalse(ambiguous.ok)
        self.assertIn("2 разів", ambiguous.output)
        forced = self.registry.call(
            "edit_file", {"path": "dup.py", "old_string": "a", "new_string": "b", "replace_all": True}
        )
        self.assertTrue(forced.ok)

    def test_edit_missing_fragment(self) -> None:
        result = self.registry.call("edit_file", {"path": "module.py", "old_string": "absent", "new_string": "x"})
        self.assertFalse(result.ok)

    def test_list_dir(self) -> None:
        result = self.registry.call("list_dir", {"path": "."})
        self.assertTrue(result.ok)
        self.assertIn("module.py", result.output)
        self.assertIn("sub/", result.output)

    def test_path_escape_blocked(self) -> None:
        result = self.registry.call("read_file", {"path": "../../secret.txt"})
        self.assertFalse(result.ok)

    def test_unknown_tool(self) -> None:
        self.assertFalse(self.registry.call("nope", {}).ok)

    def test_bad_arguments(self) -> None:
        self.assertFalse(self.registry.call("read_file", {"wrong": 1}).ok)
        self.assertFalse(self.registry.call("read_file", "not json").ok)

    def test_search_and_find(self) -> None:
        searched = self.registry.call("search_text", {"query": "hello"})
        self.assertTrue(searched.ok and "module.py:1" in searched.output)
        found = self.registry.call("find_files", {"pattern": "*.py"})
        self.assertTrue(found.ok and "module.py" in found.output)

    def test_run_command(self) -> None:
        result = self.registry.call("run_command", {"command": "echo hello-tools"})
        self.assertTrue(result.ok)
        self.assertIn("hello-tools", result.output)
        self.assertIn("exit=0", result.output)

    def test_run_command_guard(self) -> None:
        registry = ToolRegistry(self.root, confirm_commands=True)
        registry.command_guard = lambda _cmd: False
        denied = registry.call("run_command", {"command": "echo no"})
        self.assertFalse(denied.ok)
        self.assertIn("відхилив", denied.output)

    def test_python_check(self) -> None:
        ok = self.registry.call("python_check", {"path": "module.py"})
        self.assertTrue(ok.ok)
        self.assertIn("синтаксис ок", ok.output)
        (self.root / "broken.py").write_text("def (\n", encoding="utf-8")
        broken = self.registry.call("python_check", {"path": "broken.py"})
        self.assertIn("помилка синтаксису", broken.output)

    def test_project_tree(self) -> None:
        tree = self.registry.call("project_tree", {"depth": 2})
        self.assertTrue(tree.ok)
        self.assertIn("module.py", tree.output)

    def test_schemas_present(self) -> None:
        names = {schema["function"]["name"] for schema in TOOL_SCHEMAS}
        for required in ("read_file", "write_file", "edit_file", "run_command", "search_text"):
            self.assertIn(required, names)
        for schema in TOOL_SCHEMAS:
            self.assertEqual(schema["type"], "function")
            self.assertIn("parameters", schema["function"])


class TestSyntax(unittest.TestCase):
    def test_language_detection(self) -> None:
        self.assertEqual(language_for("a.py").name, "python")
        self.assertEqual(language_for("a.tsx").name, "typescript")
        self.assertEqual(language_for("a.unknown").name, "plain")

    def test_python_spans(self) -> None:
        spans = highlighter_for("x.py").spans('def f(x): return "s"  # c')
        tags = {tag for _s, _e, tag in spans}
        self.assertIn("keyword", tags)
        self.assertIn("string", tags)
        self.assertIn("comment", tags)
        self.assertIn("function", tags)

    def test_spans_do_not_overlap(self) -> None:
        spans = highlighter_for("x.py").spans('value = "def not keyword"')
        ordered = sorted(spans)
        for first, second in zip(ordered, ordered[1:]):
            self.assertLessEqual(first[1], second[0], f"перекриття: {first} і {second}")

    def test_plain_has_no_spans(self) -> None:
        self.assertEqual(highlighter_for("notes.xyz").spans("def hello"), [])

    def test_markdown_heading(self) -> None:
        spans = highlighter_for("readme.md").spans("# Заголовок")
        self.assertIn("keyword", {tag for _s, _e, tag in spans})


class TestOfflinePlanner(TempWorkspace):
    def setUp(self) -> None:
        super().setUp()
        self.planner = OfflinePlanner(self.root, self.registry)

    def test_list_files(self) -> None:
        self.assertEqual(self.planner.plan("покажи файли"), [("list_dir", {"path": "."})])

    def test_read_named_file(self) -> None:
        self.assertEqual(self.planner.plan("прочитай module.py"), [("read_file", {"path": "module.py"})])

    def test_tree(self) -> None:
        self.assertEqual(self.planner.plan("дерево проєкту"), [("project_tree", {"depth": 3})])

    def test_search_quoted(self) -> None:
        steps = self.planner.plan('знайди текст "hello"')
        self.assertEqual(steps[0][0], "search_text")
        self.assertEqual(steps[0][1]["query"], "hello")

    def test_unknown_phrase(self) -> None:
        self.assertEqual(self.planner.plan("розкажи вірш про море"), [])

    def test_empty(self) -> None:
        self.assertEqual(self.planner.plan(""), [])


class TestAgentSession(TempWorkspace):
    def test_system_message_contains_workspace(self) -> None:
        session = AgentSession(AgentSettings(), self.root)
        message = session.system_message()
        self.assertEqual(message["role"], "system")
        self.assertIn(str(self.root), message["content"])

    def test_tool_result_truncated(self) -> None:
        session = AgentSession(AgentSettings(context_char_limit=1000), self.root)
        session.add_tool_result("1", "read_file", ToolResult(True, "x" * 50_000))
        self.assertLessEqual(len(session.messages[-1]["content"]), 3000)
        self.assertIn("обрізано", session.messages[-1]["content"])

    def test_tool_error_marked(self) -> None:
        session = AgentSession(AgentSettings(), self.root)
        session.add_tool_result("1", "read_file", ToolResult(False, "немає файлу"))
        self.assertTrue(session.messages[-1]["content"].startswith("ПОМИЛКА:"))

    def test_trim_keeps_system_and_recent(self) -> None:
        settings = AgentSettings(context_char_limit=4000)
        session = AgentSession(settings, self.root)
        for index in range(30):
            session.add_user("x" * 500 + str(index))
        trimmed = session.build()
        self.assertEqual(trimmed[0]["role"], "system")
        self.assertLess(len(trimmed), 31)

    def test_reset(self) -> None:
        session = AgentSession(AgentSettings(), self.root)
        session.add_user("привіт")
        session.reset()
        self.assertEqual(session.messages, [])

    def test_pretty_arguments(self) -> None:
        self.assertEqual(_pretty_arguments(json.dumps({"path": "a.py"})), "path=a.py")
        self.assertIn("path", _pretty_arguments('{"path": "a" * 500}'))


class TestLLMClient(unittest.TestCase):
    def test_normalises_base_url(self) -> None:
        client = LLMClient("http://127.0.0.1:1234", "m", timeout=5)
        self.assertEqual(client.base_url, "http://127.0.0.1:1234")

    def test_pick_model_prefers_coder(self) -> None:
        self.assertEqual(LLMClient.pick_model(["llama3:8b", "qwen2.5-coder:14b"]), "qwen2.5-coder:14b")
        self.assertEqual(LLMClient.pick_model([]), "")

    def test_chat_without_model_raises(self) -> None:
        client = LLMClient("http://127.0.0.1:9/v1", "", timeout=1)
        with self.assertRaises(LLMError):
            client.chat([{"role": "user", "content": "привіт"}])

    def test_chat_result_message(self) -> None:
        result = ChatResult(content="текст", tool_calls=[])
        self.assertEqual(result.message(), {"role": "assistant", "content": "текст"})
        result.tool_calls = [{"id": "1", "type": "function", "function": {"name": "f", "arguments": "{}"}}]
        self.assertIn("tool_calls", result.message())

    def test_error_when_no_server(self) -> None:
        client = LLMClient("http://127.0.0.1:9/v1", "m", timeout=1)
        with self.assertRaises(LLMError):
            client.chat([{"role": "user", "content": "привіт"}])


class TestSettings(unittest.TestCase):
    def test_roundtrip(self) -> None:
        folder = make_temp_dir()
        try:
            path = folder / "settings.json"
            settings = Settings(workspace=str(folder))
            settings.llm.model = "test-model"
            settings.llm.base_url = "http://127.0.0.1:1234"
            settings.ui.font_size = 15
            settings.save(path)
            loaded = Settings.load(path)
            self.assertEqual(loaded.llm.model, "test-model")
            self.assertEqual(loaded.llm.base_url, "http://127.0.0.1:1234/v1")
            self.assertEqual(loaded.ui.font_size, 15)
        finally:
            drop_temp_dir(folder)

    def test_normalise_clamps(self) -> None:
        settings = LLMSettings(temperature=9.0, max_tokens=1, timeout=1).normalise()
        self.assertEqual(settings.temperature, 2.0)
        self.assertEqual(settings.max_tokens, 256)
        self.assertEqual(settings.timeout, 10)

    def test_corrupted_file_falls_back(self) -> None:
        """Зіпсований файл налаштувань не валить запуск: беруться типові.

        Перевіряємо саме ПОВЕРНЕННЯ ДО ТИПОВИХ, а не конкретну адресу:
        раніше тут стояло ``startswith("http")``, бо типовим провайдером був
        зовнішній LM Studio. Тепер типовий рушій — вбудований
        (``native://blackchpok``), і модель працює в процесі IDE.
        """
        folder = make_temp_dir()
        try:
            path = folder / "settings.json"
            path.write_text("{ not json", encoding="utf-8")
            loaded = Settings.load(path)
            default = Settings()
            self.assertEqual(loaded.llm.base_url, default.llm.base_url)
            self.assertTrue(loaded.llm.base_url.strip(),
                            "типова адреса не може бути порожньою")
        finally:
            drop_temp_dir(folder)

    def test_recent_workspaces(self) -> None:
        settings = Settings()
        for index in range(15):
            settings.remember_workspace(f"C:/p{index}")
        self.assertEqual(len(settings.recent), 12)
        self.assertEqual(settings.recent[0], "C:/p14")


if __name__ == "__main__":
    unittest.main(verbosity=2)
