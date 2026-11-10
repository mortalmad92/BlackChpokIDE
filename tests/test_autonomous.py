"""Тести автономного режиму: пріоритет задач, план, зупинка, один проєкт.

Модуль :mod:`blackchpok_ide.autonomous` навмисно не тягне tkinter — усі
рішення ухвалюються у звичайних методах, тому й перевіряються тут без
вікна й без ``mainloop``.

Запуск: python -m unittest tests.test_autonomous -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import autonomous  # noqa: E402
from blackchpok_ide import queue_engine  # noqa: E402


def make_project(files: dict[str, str] | None = None) -> Path:
    """Тимчасова тека проєкту з заданими файлами."""
    root = Path(tempfile.mkdtemp())
    (root / "tests").mkdir()
    for name, body in (files or {}).items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return root


class TestScanner(unittest.TestCase):
    """Сканер проєкту: що він узагалі знаходить."""

    def test_finds_todo_marker(self) -> None:
        root = make_project({"pkg/mod.py": "# TODO: доробити\nx = 1\n"})
        ideas = autonomous.analyse_project(root)
        self.assertTrue(any("TODO" in idea.title for idea in ideas), [i.title for i in ideas])

    def test_finds_swallowed_exceptions(self) -> None:
        body = ("def f():\n"
                "    try:\n"
                "        g()\n"
                "    except ValueError:\n"
                "        pass\n") * 3
        root = make_project({"pkg/mod.py": body})
        ideas = autonomous.analyse_project(root)
        self.assertTrue(any("приховані помилки" in idea.title.lower() or "винят" in idea.title.lower()
                            for idea in ideas), [i.title for i in ideas])

    def test_finds_missing_tests(self) -> None:
        root = make_project({"pkg/mod.py": "def f():\n    return 1\n"})
        ideas = autonomous.analyse_project(root)
        self.assertTrue(any("тести" in idea.title.lower() for idea in ideas),
                        [i.title for i in ideas])

    def test_skips_dependency_dirs(self) -> None:
        root = make_project({
            "node_modules/lib/index.js": "# TODO: не чіпати\n",
            "pkg/mod.py": "x = 1\n",
        })
        ideas = autonomous.analyse_project(root)
        self.assertFalse(any("node_modules" in idea.path for idea in ideas),
                         [idea.path for idea in ideas])

    def test_empty_project_gives_no_crash(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.assertEqual(autonomous.analyse_project(root), [])

    def test_missing_project_returns_empty(self) -> None:
        self.assertEqual(autonomous.analyse_project(Path(tempfile.mkdtemp()) / "nope"), [])

    def test_candidates_are_unique(self) -> None:
        body = "# TODO: a\n" + "print(1)\n" * 10
        root = make_project({"pkg/mod.py": body})
        ideas = autonomous.analyse_project(root, limit=50)
        keys = [idea.key() for idea in ideas]
        self.assertEqual(len(keys), len(set(keys)), keys)

    def test_respects_limit(self) -> None:
        files = {f"pkg/m{index}.py": "x = 1\n" for index in range(12)}
        root = make_project(files)
        self.assertLessEqual(len(autonomous.analyse_project(root, limit=4)), 4)

    def test_research_ideas_from_packages(self) -> None:
        ideas = autonomous.research_ideas(["requests", "flask"])
        self.assertEqual(len(ideas), 2)
        self.assertTrue(all("requests" in idea.title or "flask" in idea.title
                            for idea in ideas))

    def test_project_packages_reads_requirements(self) -> None:
        root = make_project({"requirements.txt": "requests==2.31.0\n# comment\nflask>=3\n"})
        self.assertEqual(autonomous.project_packages(root), ["requests", "flask"])


class TestEngineState(unittest.TestCase):
    """Старт, стан і правило одного проєкту."""

    def setUp(self) -> None:
        self.queue = queue_engine.TaskQueue(Path(tempfile.mkdtemp()) / "queue.json")
        self.engine = autonomous.AutonomousEngine(queue=self.queue)
        self.project = make_project({"pkg/mod.py": "# TODO: x\n"})

    def test_starts_off(self) -> None:
        self.assertEqual(self.engine.state, autonomous.STATE_OFF)
        self.assertFalse(self.engine.active)

    def test_start_enables_mode(self) -> None:
        ok, message = self.engine.start(self.project)
        self.assertTrue(ok, message)
        self.assertEqual(self.engine.state, autonomous.STATE_RUNNING)
        self.assertTrue(self.engine.active)

    def test_start_rejects_missing_folder(self) -> None:
        ok, _ = self.engine.start(self.project / "немає")
        self.assertFalse(ok)
        self.assertEqual(self.engine.state, autonomous.STATE_OFF)

    def test_only_one_project_at_a_time(self) -> None:
        other = make_project({"pkg/mod.py": "x = 1\n"})
        self.assertTrue(self.engine.start(self.project)[0])
        ok, reason = self.engine.start(other)
        self.assertFalse(ok, "другий проєкт не має вмикатись")
        self.assertIn(self.project.name, reason)
        self.assertEqual(self.engine.project, self.project)

    def test_same_project_twice_is_refused(self) -> None:
        self.engine.start(self.project)
        ok, reason = self.engine.can_start(self.project)
        self.assertFalse(ok)
        self.assertIn("уже працює", reason)

    def test_snapshot_shape(self) -> None:
        self.engine.start(self.project)
        snap = self.engine.snapshot()
        for key in ("state", "project", "focus", "pending_user", "pending_agent",
                    "done", "failed", "cycles"):
            self.assertIn(key, snap)
        self.assertEqual(snap["project"], self.project.name)


class TestPriority(unittest.TestCase):
    """Задачі користувача мають вищий пріоритет."""

    def setUp(self) -> None:
        self.queue = queue_engine.TaskQueue(Path(tempfile.mkdtemp()) / "queue.json")
        self.engine = autonomous.AutonomousEngine(queue=self.queue)

    def test_user_task_goes_before_agent_tasks(self) -> None:
        self.queue.add("задача агента 1", origin=queue_engine.ORIGIN_AGENT)
        self.queue.add("задача агента 2", origin=queue_engine.ORIGIN_AGENT)
        self.engine.add_user_task("моя задача")
        first = self.queue.next_pending()
        self.assertIsNotNone(first)
        self.assertEqual(first.text, "моя задача")
        self.assertTrue(first.from_user)

    def test_origin_is_labelled(self) -> None:
        task = self.queue.add("x", origin=queue_engine.ORIGIN_USER)
        self.assertEqual(task.origin_label, "від користувача")
        agent_task = self.queue.add("y", origin=queue_engine.ORIGIN_AGENT)
        self.assertEqual(agent_task.origin_label, "від агента")

    def test_empty_user_task_is_rejected(self) -> None:
        ok, _ = self.engine.add_user_task("   ")
        self.assertFalse(ok)
        self.assertEqual(self.queue.tasks, [])

    def test_counts_by_origin(self) -> None:
        self.queue.add("a", origin=queue_engine.ORIGIN_AGENT)
        self.queue.add("b", origin=queue_engine.ORIGIN_USER)
        counts = self.queue.counts_by_origin()
        self.assertEqual(counts[queue_engine.ORIGIN_AGENT], 1)
        self.assertEqual(counts[queue_engine.ORIGIN_USER], 1)

    def test_origin_survives_save_and_load(self) -> None:
        path = Path(tempfile.mkdtemp()) / "queue.json"
        first = queue_engine.TaskQueue(path)
        first.add("моя", origin=queue_engine.ORIGIN_USER)
        second = queue_engine.TaskQueue(path)
        self.assertEqual(second.tasks[0].origin, queue_engine.ORIGIN_USER)

    def test_unknown_origin_falls_back_to_agent(self) -> None:
        task = queue_engine.QueueTask.from_dict({"text": "щось", "origin": "хтозна"})
        self.assertEqual(task.origin, queue_engine.ORIGIN_AGENT)


class TestSeeding(unittest.TestCase):
    """Наповнення черги знайденими покращеннями."""

    def setUp(self) -> None:
        self.queue = queue_engine.TaskQueue(Path(tempfile.mkdtemp()) / "queue.json")
        self.engine = autonomous.AutonomousEngine(queue=self.queue)
        self.project = make_project({
            "pkg/mod.py": "# TODO: дописати\n" + "print(1)\n" * 8,
        })

    def test_seed_requires_running_mode(self) -> None:
        self.assertEqual(self.engine.seed(), 0)

    def test_seed_adds_agent_tasks(self) -> None:
        self.engine.start(self.project)
        added = self.engine.seed(limit=3)
        self.assertGreater(added, 0)
        pending = self.queue.pending_of(queue_engine.ORIGIN_AGENT)
        self.assertEqual(len(pending), added)

    def test_seed_repeats_are_capped(self) -> None:
        self.engine.start(self.project)
        for _ in range(6):
            self.engine.seed(limit=3)
            for task in self.queue.tasks:
                if task.status == queue_engine.PENDING:
                    self.queue.cancel(task.id)
        # Той самий файл не має породжувати безкінечну кількість задач.
        self.assertLessEqual(len(self.queue.tasks), 6 * 3)

    def test_seed_updates_plan(self) -> None:
        self.engine.start(self.project)
        self.engine.seed(limit=2)
        self.assertTrue(self.engine.plan_rows())

    def test_plan_marks_first_as_current(self) -> None:
        self.engine.set_plan([("перше", autonomous.KIND_CODE), ("друге", autonomous.KIND_CODE)])
        rows = self.engine.plan_rows()
        self.assertEqual(rows[0][2], "зараз")
        self.assertEqual(rows[1][2], "далі")

    def test_plan_limits_items(self) -> None:
        self.engine.set_plan([(f"пункт {index}", autonomous.KIND_CODE)
                              for index in range(40)])
        self.assertLessEqual(len(self.engine.plan), autonomous.MAX_PLAN_ITEMS)

    def test_note_action_updates_focus_and_history(self) -> None:
        self.engine.start(self.project)
        self.engine.note_action("Рефакторю auth.py", kind=autonomous.KIND_CODE,
                                file="pkg/mod.py")
        self.assertIn("auth.py", self.engine.focus.text)
        self.assertIn("pkg/mod.py", self.engine.touched_files)


class TestStop(unittest.TestCase):
    """Коректна зупинка: файл дописується, задачі агента знімаються."""

    def setUp(self) -> None:
        self.queue = queue_engine.TaskQueue(Path(tempfile.mkdtemp()) / "queue.json")
        self.engine = autonomous.AutonomousEngine(queue=self.queue)
        self.project = make_project({"pkg/mod.py": "x = 1\n"})
        self.engine.start(self.project)

    def test_request_stop_sets_stopping(self) -> None:
        self.engine.request_stop()
        self.assertEqual(self.engine.state, autonomous.STATE_STOPPING)
        self.assertTrue(self.engine.stopping)

    def test_stop_waits_while_agent_busy(self) -> None:
        self.engine.request_stop()
        self.assertEqual(self.engine.tick(busy=True, has_pending=True), "stop_wait")

    def test_stop_finishes_when_agent_free(self) -> None:
        self.engine.request_stop()
        self.assertEqual(self.engine.tick(busy=False, has_pending=True), "stop_finish")

    def test_confirm_stop_turns_mode_off(self) -> None:
        self.engine.request_stop()
        self.engine.confirm_stop()
        self.assertEqual(self.engine.state, autonomous.STATE_OFF)
        self.assertFalse(self.engine.active)

    def test_stop_keeps_user_tasks(self) -> None:
        self.queue.add("задача агента", origin=queue_engine.ORIGIN_AGENT)
        self.engine.add_user_task("моя задача")
        self.engine.request_stop()
        self.engine.confirm_stop()
        self.assertEqual(self.queue.pending_of(queue_engine.ORIGIN_USER)[0].text,
                         "моя задача")
        self.assertEqual(self.queue.pending_of(queue_engine.ORIGIN_AGENT), [])

    def test_stop_when_off_is_harmless(self) -> None:
        self.engine.confirm_stop()
        self.engine.request_stop()
        self.assertEqual(self.engine.state, autonomous.STATE_OFF)

    def test_tick_off_when_disabled(self) -> None:
        self.engine.confirm_stop()
        self.assertEqual(self.engine.tick(busy=False, has_pending=True), "off")


class TestTickDecisions(unittest.TestCase):
    """Рішення «що робити далі»."""

    def setUp(self) -> None:
        self.queue = queue_engine.TaskQueue(Path(tempfile.mkdtemp()) / "queue.json")
        self.engine = autonomous.AutonomousEngine(queue=self.queue)
        self.engine.start(make_project({"pkg/mod.py": "x = 1\n"}))

    def test_busy_waits(self) -> None:
        self.assertEqual(self.engine.tick(busy=True, has_pending=True), "wait")

    def test_pending_runs(self) -> None:
        self.assertEqual(self.engine.tick(busy=False, has_pending=True), "run")

    def test_empty_queue_seeds(self) -> None:
        self.assertEqual(self.engine.tick(busy=False, has_pending=False), "seed")


class TestLog(unittest.TestCase):
    """Журнал дій."""

    def test_log_records_entries(self) -> None:
        engine = autonomous.AutonomousEngine(
            queue=queue_engine.TaskQueue(Path(tempfile.mkdtemp()) / "q.json"))
        engine.log("щось сталося", kind="ok")
        entries = engine.recent_log()
        self.assertEqual(entries[-1].text, "щось сталося")
        self.assertEqual(entries[-1].kind, "ok")
        self.assertTrue(entries[-1].clock)

    def test_log_is_trimmed(self) -> None:
        engine = autonomous.AutonomousEngine(
            queue=queue_engine.TaskQueue(Path(tempfile.mkdtemp()) / "q.json"))
        for index in range(autonomous.MAX_LOG + 40):
            engine.log(f"рядок {index}")
        self.assertLessEqual(len(engine.log_entries), autonomous.MAX_LOG)

    def test_on_change_is_called(self) -> None:
        seen: list[int] = []
        engine = autonomous.AutonomousEngine(
            queue=queue_engine.TaskQueue(Path(tempfile.mkdtemp()) / "q.json"),
            on_change=lambda: seen.append(1))
        engine.log("подія")
        self.assertTrue(seen)

    def test_broken_callback_does_not_break_mode(self) -> None:
        def boom() -> None:
            raise RuntimeError("навмисно")

        engine = autonomous.AutonomousEngine(
            queue=queue_engine.TaskQueue(Path(tempfile.mkdtemp()) / "q.json"),
            on_change=boom, on_status=boom)
        engine.log("все одно працює")
        self.assertTrue(engine.log_entries)


if __name__ == "__main__":
    unittest.main(verbosity=2)
