"""Агент не мучить модель вимогою JSON, коли інструменти вже відпрацювали.

ЗАМІРЯНО ЖИВИМ ПРОГОНОМ (вікно IDE, власний рушій, Qwen2.5-Coder-14B):

    запит: «Скажи одним реченням, скільки файлів .py у теці blackchpok_ide»
    [tool_call] find_files(pattern=**/*.py)      -> список файлів
    [tool_call] list_dir()                       -> . — 38 записів
    [assistant] Ось структура вашого проєкту: …   <- ГОТОВА відповідь
    [status] Модель відповіла текстом — прошу виклик інструмента у форматі JSON
    [tool_call] list_dir()                       <- модель слухняно повторює
    [status] Модель повторює той самий крок «list_dir» — прошу змінити підхід
    ... і так по колу до ліміту

Користувач чекав **133 с** на відповідь, яка була готова на третьому кроці.
Причина: вимога «відповідай JSON-викликом» спрацьовувала на КОЖНУ прозову
відповідь, навіть коли інструменти вже дали результат.

Другий біль: текст показувався як фінальний із червоним застереженням
«відповідь не підтверджена даними», а потім відкликався.

Обидва виправлення — умова ``not self._observations`` і визначення
«чернетки» ДО показу.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import agent as agent_module  # noqa: E402
from blackchpok_ide import agent_tools, config  # noqa: E402


def _runner():
    """Агент без GUI й без моделі — лише для перевірки умов циклу."""
    settings = config.Settings()
    registry = agent_tools.ToolRegistry(ROOT)
    return agent_module.AgentRunner(
        registry, settings.llm, settings.agent, ROOT)


class _FakeObservation:
    """Мінімальне «спостереження» — важливий лише факт, що воно Є."""

    name = "list_dir"
    ok = True
    output = ". — 38 записів"
    error = ""
    for_user = ""


class TestNoJsonDemandAfterToolsRan(unittest.TestCase):
    """Умова циклу мусить зважати на ВЖЕ виконані інструменти."""

    def test_condition_requires_no_observations(self) -> None:
        """Джерело правди — сама умова в ``_loop``.

        Перевіряємо текст коду, бо умова живе всередині циклу, який без
        моделі не запустити. Це чесний спосіб зафіксувати правило: якщо
        хтось прибере ``not self._observations``, тест упаде.
        """
        source = (ROOT / "blackchpok_ide" / "agent.py").read_text(
            encoding="utf-8")
        start = source.index("не вміє нативного виклику")
        block = source[start:start + 3000]
        self.assertIn("not self._observations", block,
                      "вимога JSON-виклику знову спрацює після роботи інструментів")

    def test_promise_check_also_requires_no_observations(self) -> None:
        source = (ROOT / "blackchpok_ide" / "agent.py").read_text(
            encoding="utf-8")
        start = source.index("Обіцянка без дії")
        block = source[start:start + 2000]
        self.assertIn("not self._observations", block,
                      "«обіцянка» знову каратиме прозовий підсумок після роботи")

    def test_observations_are_empty_on_fresh_runner(self) -> None:
        self.assertEqual(list(_runner()._observations or []), [])

    def test_observation_is_recorded(self) -> None:
        runner = _runner()
        runner._note_observation(_FakeObservation())
        self.assertEqual(len(runner._observations), 1)


class TestFinalityDecidedBeforeShow(unittest.TestCase):
    """Чернетку не показуємо як відповідь — і не лякаємо застереженням."""

    def test_draft_guard_exists_in_loop(self) -> None:
        source = (ROOT / "blackchpok_ide" / "agent.py").read_text(
            encoding="utf-8")
        start = source.index("Чи це лише ПРОМІЖНИЙ текст")
        block = source[start:start + 2500]
        # Чернетка мусить враховувати і вимогу дії, і відсутність інструментів.
        self.assertIn("draft =", block)
        self.assertIn("_expects_action", block)
        self.assertIn("not self._observations", block)
        # І фінальність мусить її виключати.
        self.assertIn("final = not result.tool_calls and not draft", block)

    def test_evidence_runs_only_for_final(self) -> None:
        source = (ROOT / "blackchpok_ide" / "agent.py").read_text(
            encoding="utf-8")
        start = source.index("Чи це лише ПРОМІЖНИЙ текст")
        block = source[start:start + 2500]
        self.assertIn("if final:", block)
        self.assertIn("_enforce_evidence", block)


class TestUnderstoodAsDialogueVsAction(unittest.TestCase):
    """Розмова не мусить вимагати інструментів узагалі."""

    def test_greeting_is_converse(self) -> None:
        from blackchpok_ide import intent_engine

        frame = intent_engine.frame("привіт")
        self.assertFalse(bool(getattr(frame, "actionable", False)),
                         "на «привіт» агент не має вимагати інструментів")

    def test_counting_question_is_inspect(self) -> None:
        """Це питання про проєкт — дія, але й відповідь прозою допустима.

        Саме тут і був дефект: намір «inspect» робив ``_expects_action()``
        істинним, і КОЖНА прозова відповідь каралася вимогою JSON.
        """
        from blackchpok_ide import intent_engine

        frame = intent_engine.frame(
            "скільки файлів .py у теці blackchpok_ide?")
        self.assertEqual(getattr(frame, "intent_type", ""), "inspect")
        self.assertTrue(bool(getattr(frame, "actionable", False)))


if __name__ == "__main__":
    unittest.main()
