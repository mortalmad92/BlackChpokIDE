"""Саморозширення агента: create_skill / create_tool / custom:* / learn_from_web.

Раніше інструменти мали схеми (модель бачила їх у промпті й викликала), але
виконавців НЕ мали: ``call_tool`` веде на ``self._extend`` /
``self._run_custom_tool``, яких у класі не було — кожен виклик падав
``AttributeError``. Тепер перевіряємо саме ПОВЕДІНКУ:

* ``create_skill`` справді створює SKILL.md і не перезаписує наявний;
* ``create_tool`` створює інструмент, а ``custom:<назва>`` ВИКОНУЄ його
  в окремому процесі й повертає результат моделі;
* зламаний код інструмента відхиляється ще на створенні;
* ``list_custom_tools`` показує створене;
* ``learn_from_web`` без аргументів просить url/query, а не падає;
* маркери «обіцянок» розділені: переказ веб-результату й репліка дії
  перевіряються РІЗНИМИ списками (раніше другий ``_PROMISE_MARKERS``
  мовчки перекривав перший).

Запуск: python -m unittest tests.test_extension_tools -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import extensions as ext            # noqa: E402
from blackchpok_ide import skills as skills_module      # noqa: E402
from blackchpok_ide.agent import (                      # noqa: E402
    AgentRunner,
    _is_bare_promise,
    _promises_action,
)
from blackchpok_ide.agent_tools import ToolRegistry     # noqa: E402
from blackchpok_ide.config import AgentSettings, LLMSettings  # noqa: E402


class ExtensionToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="bch-extensions-"))
        self.runner = AgentRunner(
            ToolRegistry(self.temp), LLMSettings(), AgentSettings(), self.temp)
        self.runner.tools_enabled = True

    # ── create_skill ──────────────────────────────────────────────────────
    def test_create_skill_writes_file(self) -> None:
        result = self.runner.call_tool("create_skill", {
            "name": "release",
            "description": "Як перевіряти реліз",
            "body": "1. Запусти тести.",
        })
        self.assertTrue(result.ok, result.output)
        path = (self.temp / ".agents/skills/release/SKILL.md")
        self.assertTrue(path.is_file())
        self.assertIn("release", path.read_text(encoding="utf-8"))

    def test_create_skill_second_call_reports_existing(self) -> None:
        self.runner.call_tool("create_skill",
                              {"name": "release", "description": "перша"})
        again = self.runner.call_tool("create_skill", {
            "name": "release", "description": "друга", "body": "ІНШИЙ ВМІСТ"})
        self.assertTrue(again.ok)
        self.assertIn("уже існував", again.output)
        # Вміст НЕ перезаписано — опис першого виклику лишився.
        body = (self.temp / ".agents/skills/release/SKILL.md").read_text(
            encoding="utf-8")
        self.assertIn("перша", body)

    # ── create_tool + custom:* ────────────────────────────────────────────
    def test_create_tool_and_run_custom(self) -> None:
        made = self.runner.call_tool("create_tool", {
            "name": "greet",
            "description": "Тестовий інструмент",
            "code": "def run(**arguments):\n"
                    "    return 'привіт ' + str(arguments.get('name', ''))",
        })
        self.assertTrue(made.ok, made.output)
        folder = self.temp / ".agents/tools/greet"
        self.assertTrue((folder / "TOOL.json").is_file())
        self.assertTrue((folder / "tool.py").is_file())

        run = self.runner.call_tool("custom:greet", {"name": "Світ"})
        self.assertTrue(run.ok, run.output)
        self.assertIn("привіт Світ", run.output)
        # Виклик записано в метадані (runs = 1, ok_runs = 1).
        meta = json.loads((folder / "TOOL.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["runs"], 1)
        self.assertEqual(meta["ok_runs"], 1)

    def test_create_tool_rejects_broken_code(self) -> None:
        made = self.runner.call_tool("create_tool", {
            "name": "broken", "description": "зламаний",
            "code": "def run(:\n  pass",
        })
        self.assertFalse(made.ok)
        self.assertIn("не компілюється", made.output)

    def test_run_custom_tool_unknown_name_gives_hint(self) -> None:
        run = self.runner.call_tool("custom:немає-такого", {})
        self.assertFalse(run.ok)
        self.assertIn("не знайдено", run.output)
        self.assertIn("create_tool", run.output)

    # ── list_custom_tools / learn_from_web ────────────────────────────────
    def test_list_custom_tools_mentions_created(self) -> None:
        self.runner.call_tool("create_tool", {
            "name": "greet", "description": "Тестовий інструмент",
            "code": "def run(**arguments):\n    return 'ok'",
        })
        listed = self.runner.call_tool("list_custom_tools", {})
        self.assertTrue(listed.ok)
        self.assertIn("custom:greet", listed.output)

    def test_learn_from_web_requires_arguments(self) -> None:
        result = self.runner.call_tool("learn_from_web", {})
        self.assertFalse(result.ok)
        self.assertIn("url", result.output)
        self.assertIn("query", result.output)

    def test_unknown_extension_tool_reports_choices(self) -> None:
        result = self.runner.call_tool("create_skill_typo", {})
        self.assertFalse(result.ok)
        self.assertIn("create_skill", result.output)


class PromiseMarkersSplitTest(unittest.TestCase):
    """Два списки «обіцянок» не перекривають один одного."""

    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="bch-promises-"))

    def test_bare_promise_uses_web_markers(self) -> None:
        # «давайте подивимось» — маркер переліку переказу веб-результату.
        self.assertTrue(_is_bare_promise("давайте подивимось на графік"))

    def test_bare_promise_ignores_action_markers(self) -> None:
        # «спробую» — маркер ДІЇ, а не переказу: переказ «спробую …» не має
        # вважатися обіцянкою показати результат (раніше списки були спільні).
        self.assertFalse(_is_bare_promise("спробую інший запит"))

    def test_promises_action_unchanged(self) -> None:
        self.assertTrue(_promises_action("Спробую інший запит."))
        self.assertFalse(_promises_action("Ціна SOL сьогодні — 150 доларів."))

    def test_skill_path_helper_matches_create_skill(self) -> None:
        name = "Реліз-1"
        created = skills_module.create_skill(self.temp, name, "d", "b")
        self.assertEqual(created, skills_module.skill_path(self.temp, name))


if __name__ == "__main__":
    unittest.main(verbosity=2)
