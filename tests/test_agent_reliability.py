"""Тести надійності агента: правки, дописування, самоперевірка.

Кожен тест тут виріс із РЕАЛЬНОГО провалу на живій моделі, а не з
припущень. Мета — щоб ці провали не повернулись.

Запуск: python -m unittest tests.test_agent_reliability -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide.agent_tools import (  # noqa: E402
    ToolRegistry,
    _fuzzy_fragment,
    _syntax_issue,
)

SOURCE = '''"""Калькулятор."""


def add(a, b):
    return a + b


def average(numbers):
    total = 0
    for n in numbers:
        total += n
    return total / len(numbers)
'''


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="rel-"))
        self.registry = ToolRegistry(self.folder)

    def _write(self, name: str, body: str) -> None:
        (self.folder / name).write_text(body, encoding="utf-8")


class TestAppendKeepsContent(Base):
    """«Додай рядок» не має затирати файл."""

    def test_append_keeps_previous(self) -> None:
        self._write("notes.txt", "рядок 1\nрядок 2\n")
        out = self.registry.call("append_file",
                                 {"path": "notes.txt", "content": "рядок 3"})
        self.assertTrue(out.ok, out.output)
        body = (self.folder / "notes.txt").read_text(encoding="utf-8")
        self.assertIn("рядок 1", body, "попередній вміст зник")
        self.assertIn("рядок 2", body)
        self.assertIn("рядок 3", body)

    def test_append_adds_newline(self) -> None:
        """Без переводу рядка в кінці новий текст приклеївся б."""
        self._write("a.txt", "без нового рядка")
        self.registry.call("append_file", {"path": "a.txt", "content": "друге"})
        body = (self.folder / "a.txt").read_text(encoding="utf-8")
        self.assertEqual(body, "без нового рядка\nдруге\n")

    def test_append_creates_missing_file(self) -> None:
        out = self.registry.call("append_file",
                                 {"path": "new.txt", "content": "перший"})
        self.assertTrue(out.ok, out.output)
        self.assertTrue((self.folder / "new.txt").exists())

    def test_append_empty_is_rejected(self) -> None:
        out = self.registry.call("append_file",
                                 {"path": "x.txt", "content": "   "})
        self.assertFalse(out.ok)

    def test_write_warns_about_lost_content(self) -> None:
        """Перезапис довгого файлу коротким має попереджати."""
        self._write("big.txt", "дуже довгий вміст\n" * 10)
        out = self.registry.call("write_file",
                                 {"path": "big.txt", "content": "коротко\n"})
        self.assertIn("попередній вміст", out.output.lower(), out.output[:120])


class TestFuzzyEdit(Base):
    """Правка має прощати типові розбіжності локальних моделей."""

    def test_without_indent(self) -> None:
        self._write("calc.py", SOURCE)
        out = self.registry.call("edit_file", {
            "path": "calc.py", "old_string": "return total / len(numbers)",
            "new_string": "return total / max(1, len(numbers))"})
        self.assertTrue(out.ok, out.output)
        self.assertIn("max(1, len(numbers))",
                      (self.folder / "calc.py").read_text(encoding="utf-8"))

    def test_extra_spaces(self) -> None:
        self._write("calc.py", SOURCE)
        out = self.registry.call("edit_file", {
            "path": "calc.py",
            "old_string": "    total = 0   \n    for n in numbers:",
            "new_string": "    total = 0\n    for n in numbers:  # цикл"})
        self.assertTrue(out.ok, out.output)

    def test_missing_fragment_clear_error(self) -> None:
        self._write("calc.py", SOURCE)
        out = self.registry.call("edit_file", {
            "path": "calc.py", "old_string": "def nonexistent",
            "new_string": "x"})
        self.assertFalse(out.ok)
        self.assertIn("не знайдено", out.output.lower())

    def test_fuzzy_returns_real_text(self) -> None:
        """Повертається ТОЧНИЙ текст із файлу, а не запит моделі."""
        found = _fuzzy_fragment(SOURCE, "return total / len(numbers)")
        self.assertIsNotNone(found)
        actual, _wanted = found
        self.assertIn(actual, SOURCE, "фрагмент має бути з файлу")


class TestSyntaxGuard(Base):
    """Синтаксис перевіряється при записі."""

    def test_broken_python_flagged(self) -> None:
        body = "name = input('Введіть ім'я: ')\n"
        self.assertTrue(_syntax_issue(Path("x.py"), body))

    def test_good_python_passes(self) -> None:
        self.assertEqual(_syntax_issue(Path("x.py"), 'print("ок")\n'), "")

    def test_non_python_not_checked(self) -> None:
        self.assertEqual(_syntax_issue(Path("x.txt"), "ім'я"), "")

    def test_write_reports_syntax_error(self) -> None:
        out = self.registry.call("write_file", {
            "path": "bad.py", "content": "x = 'незакритий\n"})
        self.assertIn("синтаксична помилка", out.output.lower())


class TestPlannerMultiFile(unittest.TestCase):
    """Кілька файлів у фразі — кілька етапів."""

    def test_two_files_are_two_stages(self) -> None:
        from blackchpok_ide import task_plan

        phrase = ("додай у calc.py функцію множення, а в notes.txt "
                  "запиши що це зроблено")
        stages = task_plan.split_into_stages(phrase)
        self.assertGreaterEqual(len(stages), 2, [s.text for s in stages])
        joined = " ".join(stage.text for stage in stages)
        self.assertIn("calc.py", joined)
        self.assertIn("notes.txt", joined)

    def test_two_files_make_task_big(self) -> None:
        from blackchpok_ide import task_plan

        info = task_plan.understand(
            "додай у calc.py множення і в notes.txt рядок")
        self.assertTrue(info.is_big, f"вага {info.weight}, шляхів {info.paths}")

    def test_single_file_stays_single_stage(self) -> None:
        from blackchpok_ide import task_plan

        stages = task_plan.split_into_stages("у calc.py додай multiply")
        self.assertEqual(len(stages), 1)

    def test_edit_intent_for_named_file(self) -> None:
        """«у файлі X додай Y» — правка наявного, а не новий файл."""
        from blackchpok_ide import task_plan

        info = task_plan.understand("у файлі calc.py додай множення")
        self.assertIn(task_plan.EDIT, info.intents, info.intents)

    def test_new_file_phrase_stays_create(self) -> None:
        from blackchpok_ide import task_plan

        info = task_plan.understand("створи файл app.py")
        self.assertIn(task_plan.CREATE, info.intents)


class TestRouterEditCommand(unittest.TestCase):
    """Роутер має бачити наказ правки з названим файлом."""

    def test_edit_command_is_confident(self) -> None:
        from blackchpok_ide import tool_router

        hints = tool_router.confident("у файлі calc.py додай множення")
        self.assertTrue(hints, "роутер не розпізнав наказ")
        self.assertEqual(hints[0].tool, "read_file")

    def test_creation_still_routes(self) -> None:
        """Створення файлу не має вести до НЕІСНУЮЧОГО інструмента.

        Раніше тут перевірялось, що ``confident("створи файл app.py")``
        непорожній — але єдина підказка вела в ``router:build_project``,
        якого немає ні в реєстрі інструментів, ні серед дій MCP-роутера.
        Агент викликав його, діставав «Інструмента немає в реєстрі» й
        витрачав на це єдиний крок: файл не створювався (перевірено
        живим прогоном: 10 с і порожня тека).

        Тепер контракт інший і чесніший:
        * підказка ``build_project`` не з'являється взагалі;
        * намір усе одно «створити», тож розмовний шлях не спрацьовує і
          роботу виконує модель зі ``write_file``.
        """
        from blackchpok_ide import intent_engine, tool_router

        hints = tool_router.confident("створи файл app.py")
        self.assertFalse(
            [h for h in hints if "build_project" in h.tool],
            "підказка веде до неіснуючого інструмента")
        # Головне: це НЕ балачка — агент мусить працювати інструментами.
        frame = intent_engine.frame("створи файл app.py")
        self.assertEqual(frame.intent_type, intent_engine.CREATE)

    def test_all_named_files_are_routed(self) -> None:
        """Фраза з двома файлами дає підказки для ОБОХ.

        Регресія: ключем дедуплікації був лише інструмент, тож
        «прочитати calc.py» витісняло «прочитати notes.txt», і агент
        виконував половину прохання.
        """
        from blackchpok_ide import tool_router

        phrase = ("додай у calc.py функцію множення, а в notes.txt "
                  "запиши що це зроблено")
        paths = [hint.arguments.get("path")
                 for hint in tool_router.confident(phrase)]
        self.assertIn("calc.py", paths)
        self.assertIn("notes.txt", paths)


class TestRetryAfterModelFailure(unittest.TestCase):
    """Тимчасовий збій моделі не має переводити роботу в офлайн."""

    def test_agent_has_retry(self) -> None:
        import inspect

        from blackchpok_ide.agent import AgentRunner

        self.assertTrue(hasattr(AgentRunner, "_retry_once"))
        source = inspect.getsource(AgentRunner._run)
        self.assertIn("_retry_once", source,
                      "перед офлайн-роутером має бути повторна спроба")

    def test_retry_requires_model(self) -> None:
        """Без вибраної моделі повторювати нема чого."""
        from types import SimpleNamespace

        from blackchpok_ide.agent import AgentRunner

        holder = SimpleNamespace(
            llm_settings=SimpleNamespace(model=""),
            _cancel=SimpleNamespace(is_set=lambda: False),
            _emit=lambda *a, **k: None,
        )
        self.assertFalse(AgentRunner._retry_once(holder, None))


class TestReadingIsNotWork(unittest.TestCase):
    """Саме читання файлу не можна вважати виконаною правкою."""

    def test_asks_for_change_detects_edit(self) -> None:
        from types import SimpleNamespace

        from blackchpok_ide.agent import AgentRunner

        def holder(text: str):
            return SimpleNamespace(
                session=SimpleNamespace(messages=[
                    {"role": "user", "content": text}]),
            )

        for phrase in ("у файлі calc.py додай множення",
                       "виправ помилку",
                       "створи файл app.py"):
            self.assertTrue(AgentRunner._asks_for_change(holder(phrase)),
                            phrase)

    def test_pure_question_is_not_change(self) -> None:
        from types import SimpleNamespace

        from blackchpok_ide.agent import AgentRunner

        holder = SimpleNamespace(session=SimpleNamespace(messages=[
            {"role": "user", "content": "що робить ця функція"}]))

        self.assertFalse(AgentRunner._asks_for_change(holder))


if __name__ == "__main__":
    unittest.main(verbosity=2)
