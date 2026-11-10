"""Головний баг: модель відповідала, а користувач бачив «порожню відповідь».

Два дефекти, знайдені живим прогоном:

1. У ЛІНИВОМУ режимі агент передає моделі 17 схем із 50. Модель цілком
   може написати виклик інструмента, якого серед них немає::

       {"name": "search_web", "arguments": {"query": "ціна соняш"}}

   ``extract_tool_calls`` будував імена ЛИШЕ з переданих схем, не знаходив
   ``search_web`` і повертав ``[]``. Текст викидався як «службовий», і
   користувач бачив «Модель повернула порожню відповідь».

2. ``vision_enabled`` типово ``True``: знімки надсилались моделі без
   візуального проєктора, рушій відповідав ``HTTP 500: image input is not
   supported``, і це виглядало як «модель не працює».
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import agent as agent_module  # noqa: E402
from blackchpok_ide import agent_tools, llm_client  # noqa: E402

TEXTUAL_CALL = ('{"name": "search_web", '
                '"arguments": {"query": "ціна соняш"}}')

#: Схеми «ядра» лінивого режиму — search_web серед них НЕМАЄ.
LAZY_CORE = [
    {"type": "function", "function": {"name": "read_file"}},
    {"type": "function", "function": {"name": "list_dir"}},
    {"type": "function", "function": {"name": "run_tool"}},
]


class TestTextualToolCallInLazyMode(unittest.TestCase):
    """Дефект 1: виклик поза переданими схемами."""

    def test_call_outside_passed_schemas_is_lost_without_known_names(self) -> None:
        """Фіксуємо САМЕ дефект: без known_names виклик губиться."""
        result = llm_client.extract_tool_calls(TEXTUAL_CALL, LAZY_CORE)
        self.assertEqual(result, [],
                         "поведінка змінилась — перевір, чи не зламано сумісність")

    def test_call_outside_passed_schemas_is_recovered_with_known_names(self) -> None:
        """Виправлення: з повним переліком імен виклик розпізнається."""
        result = llm_client.extract_tool_calls(
            TEXTUAL_CALL, LAZY_CORE, ["search_web", "read_file"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["function"]["name"], "search_web")
        self.assertIn("ціна соняш", result[0]["function"]["arguments"])

    def test_known_names_do_not_break_unknown_tool(self) -> None:
        """Ім'я, якого немає ніде, не має ставати викликом."""
        body = '{"name": "hack_the_planet", "arguments": {}}'
        result = llm_client.extract_tool_calls(
            body, LAZY_CORE, ["search_web", "read_file"])
        self.assertEqual(result, [])

    def test_passed_schemas_still_work(self) -> None:
        body = '{"name": "read_file", "arguments": {"path": "main.py"}}'
        result = llm_client.extract_tool_calls(body, LAZY_CORE)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["function"]["name"], "read_file")


class TestKnownToolNames(unittest.TestCase):
    """Перелік імен має бути ПОВНИМ, а не зрізаним."""

    def setUp(self) -> None:
        from blackchpok_ide import config

        settings = config.Settings()
        settings.llm.model = "qwen2.5-coder-14b"
        settings.llm.base_url = "http://127.0.0.1:8080/v1"
        settings.llm.api_key = "local"
        registry = agent_tools.ToolRegistry(ROOT)
        self.runner = agent_module.AgentRunner(
            registry, settings.llm, settings.agent, ROOT)

    def test_known_names_cover_all_agent_tools(self) -> None:
        known = self.runner._known_tool_names()
        self.assertGreater(len(known), 40,
                           f"очікували повний перелік, отримали {len(known)}")
        # ключові інструменти, яких немає в лінивому ядрі
        for name in ("search_web", "write_file", "list_dir", "run_command"):
            with self.subTest(tool=name):
                self.assertIn(name, known)

    def test_known_names_superset_of_lazy_schemas(self) -> None:
        lazy = {s["function"]["name"] for s in self.runner.tool_schemas()}
        known = set(self.runner._known_tool_names())
        self.assertTrue(lazy.issubset(known),
                        f"втрачено: {lazy - known}")

    def test_known_names_have_no_duplicates(self) -> None:
        known = self.runner._known_tool_names()
        self.assertEqual(len(known), len(set(known)))


class TestVisionDefaultOff(unittest.TestCase):
    """Дефект 2: знімки моделі без проєктора."""

    def test_vision_is_off_by_default(self) -> None:
        self.assertFalse(
            agent_module.AgentRunner.vision_enabled,
            "типове значення True надсилає зображення моделі без mmproj — "
            "рушій відповідає HTTP 500 'image input is not supported'",
        )

    def test_vision_can_be_enabled_explicitly(self) -> None:
        """Вікно має мати можливість увімкнути зір, коли проєктор є."""
        from blackchpok_ide import config

        settings = config.Settings()
        registry = agent_tools.ToolRegistry(ROOT)
        runner = agent_module.AgentRunner(
            registry, settings.llm, settings.agent, ROOT)
        runner.vision_enabled = True
        self.assertTrue(runner.vision_enabled)

    def test_main_window_sets_vision_from_projector(self) -> None:
        """Перевіряємо, що вікно справді виставляє прапорець за проєктором."""
        source = (ROOT / "blackchpok_ide" / "main_window.py").read_text(
            encoding="utf-8", errors="replace")
        self.assertIn("vision_enabled = bool(projector)", source,
                      "вікно має вмикати зір лише коли проєктор справді є")


if __name__ == "__main__":
    unittest.main(verbosity=2)
