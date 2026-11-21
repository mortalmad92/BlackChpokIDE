"""Тести захисту від циклу в автономному режимі.

Що тут охороняється (життєвий прогін 21.11.2026):

* сканер брав «TODO» як ПІДРЯДОК — у чергу йшли задачі на рядок
  ``"mastodon"`` (MAS-TODO-N) і на ``\\uXXXX`` у коментарі. Такі задачі
  виконати неможливо, тому вони повертались у чергу знову;
* ключ ідеї містив ТЕКСТ рядка, тому після будь-якої правки ставав новим, і
  лічильник повторів обнулявся. Наслідок: 14 перезаписів одного файлу й 21
  запуск тієї самої команди за годину;
* «готово» ставилось за фактом зміни файлу, а не за досягненням мети.

Запуск: python -m unittest tests.test_autonomous_loop_guard -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import autonomous, queue_engine, task_executor  # noqa: E402


def make_project(files: dict[str, str] | None = None) -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "tests").mkdir()
    for name, body in (files or {}).items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return root


class TestMarkerDetection(unittest.TestCase):
    """Маркер боргу — лише на початку КОМЕНТАРЯ."""

    def test_real_todo_comment_is_found(self) -> None:
        root = make_project({"pkg/mod.py": "# TODO: доробити\nx = 1\n"})
        ideas = autonomous.analyse_project(root)
        markers = [item for item in ideas if item.category == "marker"]
        self.assertTrue(markers, [idea.title for idea in ideas])
        self.assertEqual(markers[0].marker, "TODO")
        self.assertEqual(markers[0].line, 1)

    def test_js_style_comment_is_found(self) -> None:
        root = make_project({"app.js": "// FIXME: переробити\nlet x = 1;\n"})
        ideas = autonomous.analyse_project(root)
        self.assertTrue(any(item.marker == "FIXME" for item in ideas),
                        [idea.title for idea in ideas])

    def test_marker_inside_word_is_ignored(self) -> None:
        """``"mastodon"`` містить TODO — це не позначка боргу."""
        root = make_project({
            "pkg/social.py": 'KEYS = {\n    "mastodon": {"base": "URL"},\n}\n',
        })
        ideas = autonomous.analyse_project(root)
        self.assertFalse([item for item in ideas if item.category == "marker"],
                         [idea.title for idea in ideas])

    def test_marker_inside_docstring_example_is_ignored(self) -> None:
        """Приклад у докстрінгу — не борг: прибрати його неможливо."""
        body = (
            'def f():\n'
            '    """Перевірка.\n\n'
            '    Раніше «12 файлів» підтверджувалось доказом «line 120 has TODO».\n'
            '    """\n'
            '    return 1\n'
        )
        root = make_project({"pkg/mod.py": body})
        ideas = autonomous.analyse_project(root)
        self.assertFalse([item for item in ideas if item.category == "marker"],
                         [idea.title for idea in ideas])

    def test_xxx_escape_in_comment_is_ignored(self) -> None:
        """``\\uXXXX`` — не позначка XXX."""
        root = make_project({
            "pkg/mod.py": 'def f(char):\n    # ``\\uXXXX`` — 4 hex-символи.\n    return char\n',
        })
        ideas = autonomous.analyse_project(root)
        self.assertFalse([item for item in ideas if item.category == "marker"],
                         [idea.title for idea in ideas])

    def test_uppercase_todo_in_string_data_is_ignored(self) -> None:
        root = make_project({
            "pkg/mod.py": 'DATA = {"old_string": "TODO", "new_string": "done"}\n',
        })
        ideas = autonomous.analyse_project(root)
        self.assertFalse([item for item in ideas if item.category == "marker"])


class TestIdeaKey(unittest.TestCase):
    """Ключ ідеї не залежить від тексту рядка."""

    def test_key_stable_when_line_text_changes(self) -> None:
        first = autonomous.Candidate(title="a", instruction="x", path="pkg/mod.py",
                                     marker="TODO", category="marker")
        second = autonomous.Candidate(title="б", instruction="y", path="pkg/mod.py",
                                      marker="TODO", category="marker")
        self.assertEqual(first.key(), second.key())

    def test_key_differs_by_file(self) -> None:
        one = autonomous.Candidate(title="a", instruction="x", path="a.py",
                                   marker="TODO", category="marker")
        two = autonomous.Candidate(title="a", instruction="x", path="b.py",
                                   marker="TODO", category="marker")
        self.assertNotEqual(one.key(), two.key())

    def test_key_differs_by_marker(self) -> None:
        one = autonomous.Candidate(title="a", instruction="x", path="a.py",
                                   marker="TODO", category="marker")
        two = autonomous.Candidate(title="a", instruction="x", path="a.py",
                                   marker="FIXME", category="marker")
        self.assertNotEqual(one.key(), two.key())

    def test_key_falls_back_to_kind(self) -> None:
        idea = autonomous.Candidate(title="a", instruction="x", path="a.py",
                                    kind=autonomous.KIND_VERIFY)
        self.assertEqual(idea.key(), f"{autonomous.KIND_VERIFY}|a.py")


class TestSeedingDedupe(unittest.TestCase):
    """Черга не наповнюється копіями тієї самої ідеї."""

    def setUp(self) -> None:
        self.queue = queue_engine.TaskQueue(Path(tempfile.mkdtemp()) / "queue.json")
        self.engine = autonomous.AutonomousEngine(queue=self.queue)
        self.project = make_project({"pkg/mod.py": "# TODO: дописати\nx = 1\n"})

    def test_seed_sets_idea_key(self) -> None:
        self.engine.start(self.project)
        self.engine.seed(limit=1)
        tasks = [task for task in self.queue.tasks]
        self.assertTrue(tasks)
        self.assertTrue(tasks[0].idea_key, "ключ ідеї не збережено")
        self.assertNotIn("idea:", tasks[0].detail, "ключ не має текти в detail")

    def test_pending_idea_is_not_added_twice(self) -> None:
        self.engine.start(self.project)
        self.engine.seed(limit=3)
        first = [task.idea_key for task in self.queue.tasks]
        self.assertTrue(first)
        # Повторний скан при незакритих задачах не має додавати КОПІЙ:
        # інші ідеї — можна, той самий ключ — ні.
        self.engine.seed(limit=3)
        second = [task.idea_key for task in self.queue.tasks]
        duplicates = [key for key in set(second) if key and second.count(key) > 1]
        self.assertEqual(duplicates, [], second)

    def test_settled_idea_may_be_repeated(self) -> None:
        self.engine.start(self.project)
        self.engine.seed(limit=1)
        self.queue.mark_done(self.queue.tasks[0].id, "готово")
        self.engine.seed(limit=1)
        self.assertEqual(len(self.queue.tasks), 2)

    def test_pending_has_ignores_settled(self) -> None:
        key = "marker|pkg/mod.py|TODO"
        task = self.queue.add("x", idea_key=key)
        self.assertTrue(self.engine._pending_has(key))
        self.queue.mark_done(task.id, "ок")
        self.assertFalse(self.engine._pending_has(key))


class TestGoalProblem(unittest.TestCase):
    """Мета задачі: маркер мусить справді зникнути."""

    def test_marker_still_present_is_a_problem(self) -> None:
        root = make_project({"pkg/mod.py": "# TODO: лишилось\nx = 1\n"})
        problem = autonomous.goal_problem(
            root, idea_key="marker|pkg/mod.py|TODO", path="pkg/mod.py")
        self.assertIn("TODO", problem)

    def test_marker_removed_is_success(self) -> None:
        root = make_project({"pkg/mod.py": "# зроблено\nx = 1\n"})
        self.assertEqual(
            autonomous.goal_problem(root, idea_key="marker|pkg/mod.py|TODO",
                                    path="pkg/mod.py"), "")

    def test_other_tasks_have_no_formal_criterion(self) -> None:
        root = make_project({"pkg/mod.py": "x = 1\n"})
        self.assertEqual(
            autonomous.goal_problem(root, idea_key="missing_tests|pkg/mod.py",
                                    path="pkg/mod.py"), "")

    def test_missing_file_is_not_a_problem(self) -> None:
        root = make_project()
        self.assertEqual(
            autonomous.goal_problem(root, idea_key="marker|nope.py|TODO",
                                    path="nope.py"), "")

    def test_engine_delegates_to_goal_problem(self) -> None:
        root = make_project({"pkg/mod.py": "# TODO: x\n"})
        engine = autonomous.AutonomousEngine(
            queue=queue_engine.TaskQueue(Path(tempfile.mkdtemp()) / "q.json"))
        engine.start(root)
        self.assertIn("TODO", engine.task_succeeded(
            idea_key="marker|pkg/mod.py|TODO", path="pkg/mod.py"))


class TestValidatorGoalHook(unittest.TestCase):
    """Перевірка результату кроку враховує мету, а не лише зміну файлу."""

    def setUp(self) -> None:
        self.root = make_project({"pkg/mod.py": "# TODO: лишилось\n"})

    def make_task(self, *, idea_key: str = "", path: str = "pkg/mod.py"):
        queue = queue_engine.TaskQueue(Path(tempfile.mkdtemp()) / "queue.json")
        return queue.add("прибрати позначку", file_hint=path, idea_key=idea_key)

    def test_changed_file_is_not_enough_when_goal_unmet(self) -> None:
        validator = task_executor.TaskValidator(
            lambda: self.root,
            goal_checker=lambda task: autonomous.goal_problem(
                self.root, idea_key=task.idea_key, path=task.file_hint))
        task = self.make_task(idea_key="marker|pkg/mod.py|TODO")
        verdict = validator.validate(task, "Готово.", changed=["pkg/mod.py"])
        self.assertFalse(verdict.ok, "зміна файлу видала себе за досягнуту мету")
        self.assertIn("мету", verdict.reason)

    def test_goal_met_after_marker_removed(self) -> None:
        (self.root / "pkg/mod.py").write_text("# зроблено\n", encoding="utf-8")
        validator = task_executor.TaskValidator(
            lambda: self.root,
            goal_checker=lambda task: autonomous.goal_problem(
                self.root, idea_key=task.idea_key, path=task.file_hint))
        task = self.make_task(idea_key="marker|pkg/mod.py|TODO")
        verdict = validator.validate(task, "Готово.", changed=["pkg/mod.py"])
        self.assertTrue(verdict.ok, verdict.reason)

    def test_broken_goal_checker_does_not_break_validation(self) -> None:
        def boom(_task) -> str:
            raise RuntimeError("навмисно")

        validator = task_executor.TaskValidator(lambda: self.root, goal_checker=boom)
        task = self.make_task(idea_key="marker|pkg/mod.py|TODO")
        verdict = validator.validate(task, "Готово.", changed=["pkg/mod.py"])
        self.assertTrue(verdict.ok, "збій перевірки мети зламав крок")

    def test_validator_without_hook_works_as_before(self) -> None:
        validator = task_executor.TaskValidator(lambda: self.root)
        task = self.make_task()
        verdict = validator.validate(task, "Готово.", changed=["pkg/mod.py"])
        self.assertTrue(verdict.ok)


class TestQueueIdeaKeyPersistence(unittest.TestCase):
    """Ключ ідеї переживає перезапуск і пошкоджений файл."""

    def test_survives_save_and_load(self) -> None:
        path = Path(tempfile.mkdtemp()) / "queue.json"
        first = queue_engine.TaskQueue(path)
        first.add("праця", idea_key="marker|a.py|TODO")
        second = queue_engine.TaskQueue(path)
        self.assertEqual(second.tasks[0].idea_key, "marker|a.py|TODO")

    def test_wrong_type_falls_back_to_empty(self) -> None:
        task = queue_engine.QueueTask.from_dict({"text": "x", "idea_key": 42})
        self.assertEqual(task.idea_key, "")

    def test_missing_field_is_empty(self) -> None:
        task = queue_engine.QueueTask.from_dict({"text": "x"})
        self.assertEqual(task.idea_key, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
