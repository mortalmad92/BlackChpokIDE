"""Свобода моделі: вона сама обирає інструменти, а не евристика.

Вимога користувача (21.11.2026): «а можна такі моменти перенести на мозок
самої моделі, бо потім кожен мій запит буде виконуватися не правильно, дай їй
свободу думок і хай сама підбирає інструменти, а не буде захардкодена!».

Що було не так. Евристика (:mod:`tool_router`) за словами вирішувала, що
людина просить, і ВИКОНУВАЛА це сама, коли модель відповіла текстом. Будь-яка
помилка евристики ставала помилкою роботи: «давай грати в просту гру» →
створення `game.py` і запуск тестів.

Що тепер:

* підказка йде в ПРОМПТ як ПОРАДА («можлива дія — це здогад»);
* модель вирішує сама;
* евристика втручається лише тоді, коли модель НЕ впоралась (не викликала
  жодного інструмента).

Запуск: python -m unittest tests.test_model_decides -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import config, context_flow, intent_engine, task_plan  # noqa: E402


def make_runner(*, model_decides: bool = True):
    from blackchpok_ide.agent import AgentRunner
    from blackchpok_ide.agent_tools import ToolRegistry

    settings = config.AgentSettings(model_decides=model_decides)
    runner = AgentRunner(ToolRegistry(ROOT), config.LLMSettings(),
                         settings, ROOT)
    runner.tools_enabled = False
    return runner


class TestGameInChat(unittest.TestCase):
    """«Давай грати в гру» — це розмова, а не створення файлу."""

    def test_game_in_chat_is_conversation(self) -> None:
        phrase = ("Привіт, давай грати в просту гру, будемо рахувати, "
                  "але по своїй черзі я буду в чаті")
        frame = intent_engine.frame(phrase)
        self.assertEqual(str(getattr(frame, "intent_type", "")), "converse",
                         "гра в чаті розпізнана як робота з файлами")

    def test_understanding_is_not_action(self) -> None:
        phrase = "давай пограємо в слова, я буду в чаті"
        understanding = task_plan.understand(phrase)
        self.assertFalse(understanding.is_action,
                         f"гра в чаті = дія: {understanding.intents}")

    def test_build_game_is_still_creation(self) -> None:
        """Справжня розробка гри мусить лишитись роботою."""
        for phrase in ("зроби мені гру на Python", "напиши гру змійку",
                       "створи просту гру", "хочу гру на pygame"):
            with self.subTest(phrase=phrase):
                frame = intent_engine.frame(phrase)
                got = str(getattr(frame, "intent_type", "") or "")
                self.assertIn(got, ("create", "edit", "inspect"),
                              f"{phrase!r} -> {got}")


class TestAdviceNotOrder(unittest.TestCase):
    """Підказка — порада в промпті, а не наказ."""

    def test_advice_text_says_it_is_a_guess(self) -> None:
        from blackchpok_ide import tool_router

        runner = make_runner()
        runner._pending_hint = tool_router.confident("покажи файли")
        advice = runner._hint_advice()
        self.assertIn("ЗДОГАД", advice)
        self.assertIn("Вирішуй САМ", advice)
        self.assertIn("list_dir", advice)

    def test_no_hints_gives_no_advice(self) -> None:
        runner = make_runner()
        runner._pending_hint = []
        self.assertEqual(runner._hint_advice(), "")

    def test_advice_is_short(self) -> None:
        """Порада не має з'їдати пів вікна: це лише здогад."""
        from blackchpok_ide import tool_router

        runner = make_runner()
        runner._pending_hint = tool_router.confident("покажи файли")
        self.assertLess(len(runner._hint_advice()), 700)


class TestMayOverride(unittest.TestCase):
    """Коли евристика МАЄ право втрутитись."""

    def test_does_not_override_when_model_acted(self) -> None:
        runner = make_runner()
        runner._observations = [object()]
        self.assertFalse(runner._may_override_model(None),
                         "евристика перекрила рішення моделі")

    def test_overrides_when_model_did_nothing(self) -> None:
        runner = make_runner()
        runner._observations = []
        self.assertTrue(runner._may_override_model(None))

    def test_legacy_mode_always_overrides(self) -> None:
        """Для слабких моделей примус лишається (сумісність)."""
        runner = make_runner(model_decides=False)
        runner._observations = [object()]
        self.assertTrue(runner._may_override_model(None))

    def test_code_in_chat_is_not_overridden(self) -> None:
        """Модель написала код у чаті — це спроба роботи, не перекриваємо.

        Беремо РЕАЛІСТИЧНИЙ вміст файлу: ``_wrote_code_in_chat`` шукає ознаки
        справжнього коду (``import``, ``<!DOCTYPE``, ``function``), а не
        будь-який блок у лапках. ``print(1)`` таких ознак не має й тому
        вважається звичайним прикладом у відповіді — і це правильно.
        """
        runner = make_runner()
        runner._observations = []

        class Result:
            content = ("```python\nimport os\n\n\ndef main():\n"
                       "    print(os.getcwd())\n```")

        self.assertFalse(runner._may_override_model(Result()))


class TestMissingAdviceIsHarmless(unittest.TestCase):
    """Відсутність методи поради не має зривати хід.

    Реальний дефект 21.11.2026: запущена IDE прочитала версію файлу, де
    виклик уже був, а методу ще не було — і КОЖЕН хід падав з
    ``AttributeError: no attribute '_hint_advice'``.
    """

    def test_getattr_guard_present(self) -> None:
        import inspect

        from blackchpok_ide import agent

        source = inspect.getsource(agent.AgentRunner._build_turn_prompt) \
            if hasattr(agent.AgentRunner, "_build_turn_prompt") else ""
        if not source:
            # Метод міг називатись інакше — шукаємо виклик по всьому модулю.
            with open(ROOT / "blackchpok_ide" / "agent.py",
                      encoding="utf-8") as handle:
                source = handle.read()
        self.assertIn("getattr(self, \"_hint_advice\"", source,
                      "виклик поради не захищений — знову впаде AttributeError")


class TestModelDecidesSetting(unittest.TestCase):
    """Налаштування свободи моделі."""

    def test_default_is_model_decides(self) -> None:
        self.assertTrue(config.AgentSettings().model_decides)


class TestAdaptiveContext(unittest.TestCase):
    """Адаптивна глибина контексту за запитом."""

    def test_continuation_keeps_more(self) -> None:
        plan = context_flow.choose("продовж роботу")
        self.assertEqual(plan.depth.level, context_flow.DEPTH_DEEP)
        self.assertGreater(plan.depth.digest_extra, 0)

    def test_fact_question_keeps_minimum(self) -> None:
        plan = context_flow.choose("яка ціна біткоїна")
        self.assertEqual(plan.depth.level, context_flow.DEPTH_MINIMAL)

    def test_edit_keeps_medium(self) -> None:
        plan = context_flow.choose("виправ баг у agent.py")
        self.assertEqual(plan.depth.level, context_flow.DEPTH_MEDIUM)

    def test_modes_change_depth(self) -> None:
        fresh = context_flow.choose("продовж роботу", mode="fresh")
        full = context_flow.choose("привіт", mode="full")
        self.assertEqual(fresh.depth.keep,
                         context_flow.DEPTH_KEEP[context_flow.DEPTH_SHALLOW])
        self.assertTrue(full.depth.is_deep())

    def test_model_request_wins(self) -> None:
        """Прохання моделі має пріоритет над евристикою."""
        depth = context_flow.parse_request(2, query="тести")
        plan = context_flow.plan_from_request(depth, query="тести")
        self.assertEqual(plan.depth.keep, 2)
        self.assertEqual(plan.depth.level, context_flow.DEPTH_MINIMAL)

    def test_model_can_ask_for_everything(self) -> None:
        depth = context_flow.parse_request(0)
        self.assertTrue(depth.is_deep())

    def test_negative_request_is_rejected(self) -> None:
        with self.assertRaises(context_flow.RequestError):
            context_flow.parse_request(-5)

    def test_broken_request_falls_back(self) -> None:
        plan = context_flow.plan_from_model({"messages": "багато"})
        self.assertTrue(plan.depth.is_deep(),
                        "некоректний запит має дати всю історію, а не порожнечу")


if __name__ == "__main__":
    unittest.main(verbosity=2)
