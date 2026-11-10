import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import vibe_router
from night_shift import (
    NightRunner,
    extra_tasks,
    is_better,
    make_check,
    parse_check,
    safe_target,
    default_test_command,
    suite_check,
)


class NightShiftTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "mem.sqlite3"
        self.clock = {"now": datetime(2026, 11, 5, 22, 0, tzinfo=timezone.utc)}

    def tearDown(self):
        self.temp.cleanup()

    def _runner(self, complete, checks):
        state = {"i": 0}

        def run_check(_command):
            item = checks[min(state["i"], len(checks) - 1)]
            state["i"] += 1
            return item

        return NightRunner(
            self.root,
            self.db,
            complete=complete,
            run_check=run_check,
            now=lambda: self.clock["now"],
            max_attempts=3,
        )

    def test_router_hears_the_night_phrase(self):
        decision = vibe_router.classify("нічна зміна до ранку: калькулятор з тестами")
        self.assertEqual(decision.intent, "night_shift")

    def test_patch_stays_only_when_the_check_improves(self):
        self.assertTrue(is_better(make_check(1, "2 failed"), make_check(1, "1 failed")))
        self.assertFalse(is_better(make_check(1, "FAILED test_add"), make_check(1, "FAILED test_add")))
        calls = {"n": 0}

        def complete(_prompt):
            calls["n"] += 1
            return "### FILE: app.py\n```python\nprint(1)\n```\n"

        runner = self._runner(
            complete,
            [make_check(1, "2 failed\nFAILED test_add"), make_check(0, "1 passed")],
        )
        runner.add_tasks(["Додати калькулятор і закрити тести"])
        text = runner.run(hours=1)
        self.assertIn("Задачу закрито", text)
        self.assertEqual((self.root / "app.py").read_text(encoding="utf-8").strip(), "print(1)")
        self.assertIn("done", runner.todo_list_status())

    def test_same_failure_reverts_the_patch_and_stops(self):
        def complete(_prompt):
            return "### FILE: app.py\n```python\nprint('bad')\n```\n"

        runner = self._runner(complete, [make_check(1, "FAILED test_add"), make_check(1, "FAILED test_add")])
        runner.add_tasks(["Полагодити додавання"])
        text = runner.run(hours=1)
        self.assertIn("відкочено", text)
        self.assertIn("зупинено", text)
        self.assertFalse((self.root / "app.py").exists())

    def test_forbidden_check_and_paths(self):
        with self.assertRaises(ValueError):
            parse_check("зроби сайт перевірка: pytest && del /q", self.root)
        self.assertIsNone(safe_target(self.root, "../secret.py"))
        self.assertIsNone(safe_target(self.root, ".env"))

    def test_deadline_leaves_the_next_task_pending(self):
        def complete(_prompt):
            self.clock["now"] = self.clock["now"] + timedelta(hours=3)
            return ""

        runner = self._runner(complete, [make_check(1, "FAILED test_add")])
        runner.add_tasks(["Перша довга задача на ніч", "Друга задача ще в черзі"])
        text = runner.run(hours=1)
        self.assertIn("дедлайн", text.lower())
        pending = [row for row in runner.pending()]
        self.assertTrue(any("Друга" in task for _task_id, task in pending))

    def test_next_step_reads_new_files_and_drops_the_model_note(self):
        prompts: list[str] = []
        answers = [
            "НОТАТКА_МОДЕЛІ не для наступного кроку\n### FILE: app.py\n```python\nprint(1)\n```\n",
            "### FILE: app.py\n```python\nprint(2)\n```\n",
        ]

        def complete(prompt):
            prompts.append(prompt)
            return answers[len(prompts) - 1]

        cache = self.root / "__pycache__"
        cache.mkdir()
        (cache / "old.pyc").write_bytes(b"x")
        runner = self._runner(
            complete,
            [
                make_check(1, "2 failed\nFAILED test_add"),
                make_check(1, "1 failed\nFAILED test_sub"),
                make_check(1, "1 failed\nFAILED test_sub"),
                make_check(0, "1 passed"),
            ],
        )
        runner.add_tasks(["Дописати програму і прибрати падіння"])
        text = runner.run(hours=1)
        self.assertIn("контекст зібрано заново", text)
        self.assertIn("кеш скинуто", text)
        self.assertGreaterEqual(len(prompts), 2)
        self.assertIn("print(1)", prompts[1])
        self.assertNotIn("НОТАТКА_МОДЕЛІ", prompts[1])
        self.assertFalse(cache.exists())

    def test_suite_runs_compile_and_pytest(self):
        (self.root / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        tests = self.root / "tests"
        tests.mkdir()
        (tests / "test_app.py").write_text(
            "import unittest\nfrom app import add\n\nclass AddTests(unittest.TestCase):\n"
            "    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n",
            encoding="utf-8",
        )
        result = suite_check(self.root, default_test_command(self.root))
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("py_compile", result.output)
        self.assertIn("ok", result.output.lower())

    def test_phrase_splits_tasks(self):
        tasks = extra_tasks("нічна зміна до ранку: зробити калькулятор; додати сторінку About")
        self.assertEqual(len(tasks), 2)


class _StatusMixin:
    pass


def _todo_status(self):
    conn = self._db()
    try:
        rows = conn.execute("SELECT status FROM agent_todos").fetchall()
    finally:
        conn.close()
    return " ".join(row[0] for row in rows)


NightRunner.todo_list_status = _todo_status


if __name__ == "__main__":
    unittest.main()
