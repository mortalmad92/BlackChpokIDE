"""Тести розуміння людського наміру: фрази → IntentFrame.

Перевіряємо не «чи код запускається», а те, що справді ламалось у роботі:
живі звороти без дієслів, помилки друку, багатоповідомленнєві інструкції
й межа між «спитати» та «діяти».

Запуск: python -m unittest tests.test_intent_engine -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import conversation, intent_engine  # noqa: E402


class TestMessageTypes(unittest.TestCase):
    """Тип повідомлення визначає, чи запускати інструменти взагалі."""

    def test_plain_greeting_is_conversation(self) -> None:
        self.assertEqual(intent_engine.classify_message("привіт"), intent_engine.CONVERSE)
        self.assertEqual(intent_engine.classify_message("дякую, все супер"),
                         intent_engine.CONVERSE)

    def test_complaint_is_debug(self) -> None:
        for phrase in ("чому воно знову не паше",
                       "Він знову не бачить ті файли",
                       "Чат знову забув попереднє",
                       "не працює кнопка збереження"):
            with self.subTest(phrase=phrase):
                self.assertEqual(intent_engine.classify_message(phrase),
                                 intent_engine.DEBUG)

    def test_misspelled_command_is_an_action(self) -> None:
        """«поправ роутер мсп» — це доручення, а не розмова."""
        self.assertEqual(intent_engine.classify_message("поправ роутер мсп"),
                         intent_engine.DEBUG)

    def test_behaviour_wish_is_edit_not_create(self) -> None:
        """«Зроби щоб він бачив файли» — правка наявного, а не новий файл."""
        frame = intent_engine.frame(
            "Зроби щоб він сам бачив які файли треба міняти і не ліз у все підряд")
        self.assertEqual(frame.intent_type, intent_engine.EDIT)
        self.assertIn("змінювати лише потрібні файли", frame.constraints)

    def test_create_with_subject(self) -> None:
        frame = intent_engine.frame("створи калькулятор")
        self.assertEqual(frame.intent_type, intent_engine.CREATE)
        self.assertTrue(frame.actionable)

    def test_question_about_file_is_inspection(self) -> None:
        frame = intent_engine.frame("поясни що робить цей файл")
        self.assertEqual(frame.intent_type, intent_engine.INSPECT)

    def test_live_price_is_research(self) -> None:
        """Свіжі дані не лежать у проєкті — їх треба шукати в мережі."""
        self.assertEqual(intent_engine.classify_message("скільки коштує біткоїн"),
                         intent_engine.RESEARCH)

    def test_tests_request(self) -> None:
        self.assertEqual(intent_engine.classify_message("прожени тести"),
                         intent_engine.TEST)


class TestConstraints(unittest.TestCase):
    """Обмеження мусять зберігатися, навіть якщо їх сказали один раз."""

    def test_constraint_from_informal_phrase(self) -> None:
        found = intent_engine.extract_constraints(
            "прибери цю дурню, але нічого іншого не зламай")
        self.assertIn("не ламати наявну поведінку", found)

    def test_constraints_survive_next_messages(self) -> None:
        found = intent_engine.extract_constraints(
            "і додай автоматичне відновлення",
            previous=["Тільки щоб старі не видалялись"])
        self.assertIn("не видаляти наявні дані", found)

    def test_no_invention_constraint(self) -> None:
        found = intent_engine.extract_constraints(
            "зроби щоб агент нормально бачив файли і не вигадував їх")
        self.assertIn("не вигадувати вміст файлів і результати", found)

    def test_offline_constraint(self) -> None:
        found = intent_engine.extract_constraints("Без сторонніх програм")
        self.assertIn("не додавати зовнішніх залежностей", found)


class TestMultiMessageTask(unittest.TestCase):
    """Кілька повідомлень — одне завдання, а не три різні."""

    def test_continuation_keeps_task_type(self) -> None:
        state = conversation.ConversationState()
        messages = [
            "Перероби збереження чатів",
            "Тільки щоб старі не видалялись",
            "І додай автоматичне відновлення після перезапуску",
        ]
        types: list[str] = []
        for text in messages:
            frame = intent_engine.frame(
                text, previous_messages=state.recent,
                previous_intent=state.intent_type)
            types.append(frame.intent_type)
            state.observe_user_message(text, frame)
        self.assertEqual(types[0], intent_engine.EDIT)
        # Продовження не має перетворювати правку на створення.
        self.assertEqual(set(types), {intent_engine.EDIT})
        self.assertIn("не видаляти наявні дані", state.constraints)
        self.assertTrue(state.goal)

    def test_gpu_and_offline_example(self) -> None:
        state = conversation.ConversationState()
        for text in ("Перероби механізм запуску локальної моделі",
                     "І ще зроби щоб він автоматично визначав відеокарту",
                     "Без сторонніх програм"):
            frame = intent_engine.frame(
                text, previous_messages=state.recent,
                previous_intent=state.intent_type)
            state.observe_user_message(text, frame)
        self.assertIn("працювати локально", state.constraints)
        self.assertIn("не додавати зовнішніх залежностей", state.constraints)

    def test_reference_resolution(self) -> None:
        state = conversation.ConversationState()
        state.observe_user_message(
            "Перероби запуск моделі",
            intent_engine.frame("Перероби запуск моделі"))
        explained = state.resolve("зроби так само")
        self.assertIn("попереднє прохання", explained)

    def test_no_reference_means_no_guess(self) -> None:
        state = conversation.ConversationState()
        self.assertEqual(state.resolve("зроби так само"), "")


class TestClarification(unittest.TestCase):
    """Питаємо лише тоді, коли без відповіді можна зіпсувати дані."""

    def test_vague_request_asks(self) -> None:
        frame = intent_engine.frame("зроби краще")
        self.assertTrue(intent_engine.needs_clarification(frame))
        self.assertTrue(frame.missing_information)

    def test_concrete_request_does_not_ask(self) -> None:
        self.assertFalse(intent_engine.needs_clarification(
            intent_engine.frame("створи калькулятор")))

    def test_failure_report_does_not_ask(self) -> None:
        """«Не працює» — агент має шукати сам, а не питати."""
        self.assertFalse(intent_engine.needs_clarification(
            intent_engine.frame("не працює кнопка збереження")))

    def test_destructive_request_asks(self) -> None:
        frame = intent_engine.frame("видали все зайве")
        self.assertEqual(frame.risk_level, "high")
        self.assertTrue(intent_engine.needs_clarification(frame))


class TestFrameShape(unittest.TestCase):
    """Кадр мусить містити всі поля, з якими працює планувальник."""

    def test_required_fields_present(self) -> None:
        frame = intent_engine.frame("у файлі calc.py додай множення")
        data = frame.to_dict()
        for key in ("intent_type", "primary_goal", "secondary_goals", "entities",
                    "referenced_files", "referenced_features", "constraints",
                    "expected_output", "requested_actions", "required_tools",
                    "known_context", "missing_information", "risk_level",
                    "confidence", "completion_criteria"):
            self.assertIn(key, data, key)
        self.assertIn("calc.py", frame.referenced_files)
        self.assertTrue(frame.completion_criteria)

    def test_goal_is_human_text(self) -> None:
        frame = intent_engine.frame("у файлі calc.py додай множення")
        text = frame.goal_text()
        self.assertTrue(text)
        self.assertNotIn("{", text)
        self.assertNotIn("intent_type", text)

    def test_prompt_block_has_no_json(self) -> None:
        frame = intent_engine.frame("у файлі calc.py додай множення")
        block = intent_engine.frame_prompt(frame)
        self.assertIn("calc.py", block)
        self.assertNotIn('"', block)

    def test_language_detection(self) -> None:
        self.assertEqual(intent_engine.detect_language("зроби файл"), "uk")
        self.assertEqual(intent_engine.detect_language("please make a file"), "en")
        self.assertEqual(intent_engine.detect_language("сделай файл"), "ru")


class TestAnswerParsing(unittest.TestCase):
    """Відповідь на уточнення розпізнається без нової моделі."""

    def test_selection_answers(self) -> None:
        self.assertEqual(intent_engine.parse_answer("обидва", "який файл?"),
                         {"selection": "all"})
        self.assertEqual(intent_engine.parse_answer("перший", "який файл?"),
                         {"selection": "first"})

    def test_unrelated_answer(self) -> None:
        self.assertIsNone(intent_engine.parse_answer("погода гарна", "який файл?"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
