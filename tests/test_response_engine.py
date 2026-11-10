"""Тести людської відповіді: жодного протоколу в чаті, жодного хибного успіху.

Приводи — реальні скарги користувача: «не перетворюй відповідь на набір
JSON і логів», «код має бути окремим блоком», «не кажи „готово“, якщо
нічого не змінилось».

Запуск: python -m unittest tests.test_response_engine -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import intent_engine, response_engine  # noqa: E402
from blackchpok_ide.tool_orchestrator import Observation  # noqa: E402


def _ok(name: str, output: str) -> Observation:
    return Observation(name=name, ok=True, output=output)


def _fail(name: str, error: str) -> Observation:
    return Observation(name=name, ok=False, error=error)


class TestProtocolStripping(unittest.TestCase):
    """Сирий протокол не має потрапляти в чат."""

    def test_plain_tool_json_is_removed(self) -> None:
        text = ('Зараз прочитаю файл.\n'
                '{"name": "read_file", "arguments": {"path": "a.py"}}\n'
                'Готово.')
        cleaned = response_engine.strip_protocol(text)
        self.assertNotIn("read_file", cleaned)
        self.assertIn("Зараз прочитаю файл", cleaned)
        self.assertIn("Готово", cleaned)

    def test_tool_call_tags_are_removed(self) -> None:
        text = ('<tool_call>{"name": "list_dir", "arguments": {}}</tool_call>\n'
                'У теці три файли.')
        self.assertEqual(response_engine.strip_protocol(text).strip(),
                         "У теці три файли.")

    def test_agent_frames_are_removed(self) -> None:
        text = ("Контекст завдання (не перепитуй це):\nПоточна мета: правка\n\n"
                "Файл виправлено.")
        cleaned = response_engine.strip_protocol(text)
        self.assertNotIn("Контекст завдання", cleaned)
        self.assertIn("Файл виправлено", cleaned)

    def test_detects_raw_protocol(self) -> None:
        self.assertTrue(response_engine.looks_like_raw_protocol(
            '{"tool_calls": [{"id": "1", "function": {}}]}'))
        self.assertFalse(response_engine.looks_like_raw_protocol(
            "Готово. Я додав функцію множення у calc.py."))

    def test_normal_answer_survives_untouched(self) -> None:
        text = "Змінив `calc.py`: додав множення.\n\n```python\ndef mul(a, b):\n    return a * b\n```"
        self.assertEqual(response_engine.strip_protocol(text), text)


class TestAnswerFromObservations(unittest.TestCase):
    """Коли модель мовчить, відповідь збирається зі справжніх результатів."""

    def test_file_list_becomes_bullets(self) -> None:
        draft = response_engine.answer_from_observations([
            _ok("list_dir", "main.py\nserver.py\nREADME_UK.md")])
        self.assertIn("- main.py", draft.text)
        self.assertIn("- server.py", draft.text)
        self.assertNotIn("```", draft.text)

    def test_short_output_is_inline(self) -> None:
        draft = response_engine.answer_from_observations([
            _ok("search_text", "main.py:12:def run():")])
        self.assertIn("search_text", draft.text)
        self.assertNotIn("```", draft.text)

    def test_failure_is_marked(self) -> None:
        draft = response_engine.answer_from_observations([
            _fail("read_file", "Файл не знайдено: nope.py")])
        self.assertIn("не вдалось", draft.text)
        self.assertIn("> Файл не знайдено", draft.text)

    def test_long_output_is_trimmed(self) -> None:
        body = "\n".join(f"рядок {index}" for index in range(60))
        draft = response_engine.answer_from_observations([_ok("run_command", body)])
        self.assertIn("усього 60 рядків", draft.text)
        self.assertLess(len(draft.text), 1200)

    def test_changed_files_are_listed(self) -> None:
        draft = response_engine.answer_from_observations([
            _ok("read_file", "вміст"),
            _ok("edit_file", "Оновлено calc.py: замінено 1 фрагмент.")])
        self.assertIn("calc.py", draft.changed_files)
        self.assertIn("**Змінено файли:**", draft.text)

    def test_no_observations_gives_empty(self) -> None:
        self.assertEqual(
            response_engine.answer_from_observations([]).text, "")


class TestFinalAnswer(unittest.TestCase):
    """Вибір між відповіддю моделі, результатами й чесним поясненням."""

    def test_model_text_is_kept(self) -> None:
        answer = response_engine.final_answer(
            "Готово: у теці три файли.", [_ok("list_dir", "a.py\nb.py\nc.py")])
        self.assertEqual(answer, "Готово: у теці три файли.")

    def test_empty_model_text_uses_results(self) -> None:
        answer = response_engine.final_answer(
            "", [_ok("list_dir", "a.py\nb.py\nc.py")])
        self.assertIn("- a.py", answer)

    def test_promise_is_replaced_with_evidence(self) -> None:
        """«Спробую інший запит» — не відповідь; показуємо справжнє."""
        answer = response_engine.final_answer(
            "Спробую інший запит.", [_ok("list_dir", "a.py\nb.py")])
        self.assertNotEqual(answer.strip(), "Спробую інший запит.")
        self.assertIn("a.py", answer)

    def test_promise_without_work_is_honest(self) -> None:
        answer = response_engine.final_answer("Спробую пізніше.", [])
        self.assertIn("нічого не", answer)
        self.assertIn("Що можна зробити", answer)

    def test_raw_protocol_is_replaced(self) -> None:
        answer = response_engine.final_answer(
            '{"name": "read_file", "arguments": {"path": "a.py"}}',
            [_ok("read_file", "вміст файлу")])
        self.assertIn("read_file", answer)
        self.assertNotIn('"arguments"', answer)

    def test_promises_action_detection(self) -> None:
        self.assertTrue(response_engine.promises_action("Перевірю файл."))
        self.assertFalse(response_engine.promises_action("Готово: файл змінено."))
        self.assertFalse(response_engine.promises_action(
            "Перевірю:\n```python\nx = 1\n```"))


class TestClarifyingQuestion(unittest.TestCase):
    """Одне конкретне питання замість «розкажіть детальніше»."""

    def test_vague_frame_gets_question(self) -> None:
        frame = intent_engine.frame("зроби краще")
        question = response_engine.clarifying_question(frame)
        self.assertIn("Уточніть", question)
        self.assertIn("файл", question.lower())

    def test_destructive_frame_gets_question(self) -> None:
        frame = intent_engine.frame("видали все зайве")
        question = response_engine.clarifying_question(frame)
        self.assertIn("видалити", question)

    def test_clear_frame_gets_nothing(self) -> None:
        frame = intent_engine.frame("у файлі calc.py додай множення")
        self.assertEqual(response_engine.clarifying_question(frame), "")


class TestHelpers(unittest.TestCase):
    """Допоміжні перетворення не мають ламати текст."""

    def test_preview_is_one_line(self) -> None:
        text = "**Заголовок**\n\n- пункт один\n- пункт два"
        preview = response_engine.preview_of(text)
        self.assertNotIn("\n", preview)
        self.assertNotIn("**", preview)

    def test_clean_for_chat_trims_on_sentence(self) -> None:
        text = "Перше речення. Друге речення. Третє речення."
        cleaned = response_engine.clean_for_chat(text, limit=30)
        self.assertTrue(cleaned.endswith("…"))
        self.assertIn("Перше речення.", cleaned)

    def test_evidence_lines_show_status(self) -> None:
        lines = response_engine.evidence_lines([
            _ok("list_dir", "a.py"), _fail("read_file", "немає файлу")])
        self.assertTrue(lines[0].startswith("✓"))
        self.assertTrue(lines[1].startswith("✗"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
