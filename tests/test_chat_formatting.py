"""Тести форматування відповідей агента й поля введення чату.

Приводи — реальні скарги користувача на скріншотах:

1. «цей напис у вікні заважає вводити текст» — підказка «Напиши задачу
   агенту…» вставлялась у поле як ЗВИЧАЙНИЙ ТЕКСТ, курсор стояв усередині
   неї, Backspace і редагування працювали «крізь» підказку;
2. «не гарне форматування тексту в чаті» — сирий вивід інструментів
   (фрагменти файлів із номерами рядків) ішов у чат суцільним ```-блоком;
3. «редагування тексту не працює в чаті» — наслідок пункту 1.

Запуск: ``python -m unittest tests.test_chat_formatting -v``
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide.agent import AgentRunner                          # noqa: E402


class _Session:
    """Підробка сесії: повертає наперед задані результати інструментів."""

    def __init__(self, rows: list[tuple[str, bool, str]]) -> None:
        self._rows = rows

    def last_tool_results(self, limit: int = 3):
        return self._rows[:limit]


class _Probe:
    """Мінімальний «агент» для виклику ``_answer_from_tools``."""

    def __init__(self, rows: list[tuple[str, bool, str]]) -> None:
        self.session = _Session(rows)

    def _looks_like_file_list(self, body: str) -> bool:
        return AgentRunner._looks_like_file_list(body)


class TestFileListHeuristic(unittest.TestCase):
    """Перелік шляхів мусить розпізнаватись у двох форматах."""

    def test_full_paths(self) -> None:
        body = "blackchpok_ide/agent.py\nblackchpok_ide/chat_panel.py"
        self.assertTrue(AgentRunner._looks_like_file_list(body))

    def test_plain_filenames_from_list_dir(self) -> None:
        """``list_dir`` віддає прості імена — саме цей випадок ламався."""
        body = "agent_tools.py\nAGENTS.md\nmain.py\nREADME_UK.md\nserver.py"
        self.assertTrue(AgentRunner._looks_like_file_list(body))

    def test_code_is_not_a_file_list(self) -> None:
        body = "def foo():\n    return 1\n\nclass Bar:\n    pass"
        self.assertFalse(AgentRunner._looks_like_file_list(body))

    def test_prose_is_not_a_file_list(self) -> None:
        self.assertFalse(AgentRunner._looks_like_file_list(
            "Файл прочитано успішно. Усього 120 рядків."))

    def test_single_line_is_not_a_list(self) -> None:
        self.assertFalse(AgentRunner._looks_like_file_list("main.py"))


class TestAnswerFromTools(unittest.TestCase):
    """Відповідь із результатів інструментів має бути читабельною."""

    def test_file_list_becomes_bullets(self) -> None:
        agent = _Probe([("list_dir", True, "main.py\nserver.py\nREADME_UK.md")])
        text = AgentRunner._answer_from_tools(agent)          # type: ignore[arg-type]
        self.assertIn("- main.py", text)
        self.assertIn("- server.py", text)
        # Найважливіше: жодного ```-блока навколо простого переліку.
        self.assertNotIn("```", text)

    def test_short_result_is_inline(self) -> None:
        agent = _Probe([("search_text", True, "main.py:12:def run():")])
        text = AgentRunner._answer_from_tools(agent)          # type: ignore[arg-type]
        self.assertIn("search_text", text)
        self.assertNotIn("```", text)

    def test_failed_tool_is_marked_as_quote(self) -> None:
        agent = _Probe([("read_file", False, "Файл не знайдено")])
        text = AgentRunner._answer_from_tools(agent)          # type: ignore[arg-type]
        self.assertIn("не вдалось", text)
        self.assertIn(">", text)

    def test_long_output_is_truncated_with_counter(self) -> None:
        body = "\n".join(f"рядок {index}" for index in range(40))
        agent = _Probe([("run_command", True, body)])
        text = AgentRunner._answer_from_tools(agent)          # type: ignore[arg-type]
        self.assertIn("усього 40 рядків", text)
        self.assertLess(len(text), 1200, "відповідь не має бути «стіною»")

    def test_empty_results_give_empty_text(self) -> None:
        agent = _Probe([])
        self.assertEqual(AgentRunner._answer_from_tools(agent), "")   # type: ignore[arg-type]

    def test_many_files_are_capped(self) -> None:
        body = "\n".join(f"file{index}.py" for index in range(40))
        agent = _Probe([("find_files", True, body)])
        text = AgentRunner._answer_from_tools(agent)          # type: ignore[arg-type]
        self.assertIn("ще 15", text)

    def test_underscores_survive(self) -> None:
        """``__pycache__`` не має ставати ``pycache``.

        Регресія: ``strip("+-* ")`` зрізав підкреслення, а ``__…__`` у
        Markdown — це жирний/курсив, тому рендерер «з'їдав» і решту.
        """
        body = "__pycache__/\n_private.py\nmain.py"
        agent = _Probe([("list_dir", True, body)])
        text = AgentRunner._answer_from_tools(agent)          # type: ignore[arg-type]
        self.assertIn("__pycache__", text)
        self.assertIn("_private.py", text)

    def test_list_dir_output_with_sizes(self) -> None:
        """Реальний формат ``list_dir``: «ім'я  (розмір)»."""
        body = (". — 41 записів\n.agents/\nagent_tools.py  (70,468 B)\n"
                "AGENTS.md  (2,469 B)\nREADME.md  (1,024 B)")
        agent = _Probe([("list_dir", True, body)])
        text = AgentRunner._answer_from_tools(agent)          # type: ignore[arg-type]
        self.assertIn("- agent_tools.py", text)
        self.assertNotIn("```", text)

    def test_log_is_not_a_file_list(self) -> None:
        body = ("2026-11-08 10:00:01 INFO start\n"
                "2026-11-08 10:00:02 INFO loaded")
        self.assertFalse(AgentRunner._looks_like_file_list(body))


class TestComposerPlaceholder(unittest.TestCase):
    """Підказка не має бути вмістом поля введення."""

    def test_placeholder_is_not_inserted_as_text(self) -> None:
        source = (ROOT / "blackchpok_ide" / "chat_panel.py").read_text(encoding="utf-8")
        self.assertIn("self._placeholder = \"\"", source,
                      "поле не має містити текст-підказку")
        self.assertNotIn('self.input_box.insert("1.0", self._placeholder)', source,
                         "підказку заборонено вставляти в Text")

    def test_hint_label_exists(self) -> None:
        source = (ROOT / "blackchpok_ide" / "chat_panel.py").read_text(encoding="utf-8")
        self.assertIn("self.hint_label = tk.Label(", source,
                      "підказка має жити в окремому написі")

    def test_placeholder_show_is_noop_for_input(self) -> None:
        source = (ROOT / "blackchpok_ide" / "chat_panel.py").read_text(encoding="utf-8")
        start = source.index("def _show_placeholder")
        block = source[start:start + 400]
        self.assertNotIn("insert(", block,
                         "_show_placeholder не має нічого вставляти в поле")


if __name__ == "__main__":
    unittest.main(verbosity=2)
