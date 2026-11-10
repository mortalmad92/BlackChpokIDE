"""Пошкоджений queue.json не має заважати відкрити IDE.

``TaskQueue()`` створюється в конструкторі головного вікна
(``main_window.py:290``) без захисту. Раніше файл із вмістом не того типу
(список чисел, рядок, ``{"tasks": [1]}``) валив створення черги з
``AttributeError: 'int' object has no attribute 'items'`` — і **IDE не
відкривалась узагалі**, без жодної підказки користувачу.

Перевірено: 7 з 10 пошкоджених варіантів ламали старт.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import queue_engine  # noqa: E402

BROKEN_PAYLOADS = {
    "список чисел": "[1, 2, 3]",
    "список рядків": '["a", "b"]',
    "список null": "[null]",
    "вкладений список": "[[1, 2]]",
    "рядок": '"просто рядок"',
    "число": "42",
    "null": "null",
    "tasks з числами": '{"tasks": [1, 2]}',
    "tasks з рядком": '{"tasks": ["x"]}',
    "tasks не список": '{"tasks": "рядок"}',
    "порожній список": "[]",
    "порожній обʼєкт": "{}",
}


class BrokenQueueTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp(prefix="queue-broken-"))
        self._old = os.environ.get("BLACKCHPOK_HOME")
        os.environ["BLACKCHPOK_HOME"] = str(self.home)

    def tearDown(self) -> None:
        import shutil

        if self._old is None:
            os.environ.pop("BLACKCHPOK_HOME", None)
        else:
            os.environ["BLACKCHPOK_HOME"] = self._old
        shutil.rmtree(self.home, ignore_errors=True)

    def _queue_with(self, payload: str) -> queue_engine.TaskQueue:
        path = self.home / "queue.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        return queue_engine.TaskQueue(path)

    # ── пошкоджені файли ─────────────────────────────────────────────────
    def test_all_broken_payloads_are_safe(self) -> None:
        for label, payload in BROKEN_PAYLOADS.items():
            with self.subTest(payload=label):
                queue = self._queue_with(payload)
                self.assertEqual(queue.tasks, [],
                                 f"{label}: мали лишитись без завдань")

    def test_truncated_json_is_safe(self) -> None:
        queue = self._queue_with('{"tasks": [{"id": 1,')
        self.assertEqual(queue.tasks, [])

    def test_not_utf8_is_safe(self) -> None:
        path = self.home / "queue.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xfe\x00\x00\xff\xff")
        queue = queue_engine.TaskQueue(path)
        self.assertEqual(queue.tasks, [])

    def test_partial_valid_keeps_good_tasks(self) -> None:
        """Одне погане завдання не має знищувати решту."""
        payload = json.dumps({"tasks": [
            {"text": "добре завдання", "number": 1},
            42,
            {"text": "ще одне", "number": 2},
            None,
        ]}, ensure_ascii=False)
        queue = self._queue_with(payload)
        self.assertEqual(len(queue.tasks), 2,
                         f"втрачено хороші завдання: {len(queue.tasks)}")
        self.assertEqual(queue.tasks[0].text, "добре завдання")

    # ── нормальна робота не зламана ──────────────────────────────────────
    def test_normal_queue_roundtrip(self) -> None:
        path = self.home / "queue.json"
        queue = queue_engine.TaskQueue(path)
        queue.tasks.append(queue_engine.QueueTask(text="Перевірити збірку",
                                                  number=1))
        queue.tasks.append(queue_engine.QueueTask(text="Запустити тести",
                                                  number=2))
        queue.save()

        again = queue_engine.TaskQueue(path)
        self.assertEqual(len(again.tasks), 2)
        self.assertEqual([t.text for t in again.tasks],
                         ["Перевірити збірку", "Запустити тести"])

    def test_paused_flag_survives(self) -> None:
        path = self.home / "queue.json"
        queue = queue_engine.TaskQueue(path)
        queue.paused = True
        queue.save()
        again = queue_engine.TaskQueue(path)
        self.assertTrue(again.paused, "прапорець паузи втрачено")

    def test_plain_list_format_still_supported(self) -> None:
        """Файл міг бути записаний просто списком завдань."""
        payload = json.dumps([{"text": "з списку", "number": 1}],
                             ensure_ascii=False)
        queue = self._queue_with(payload)
        self.assertEqual(len(queue.tasks), 1)
        self.assertEqual(queue.tasks[0].text, "з списку")


class TestWindowStartsWithBrokenQueue(unittest.TestCase):
    """Наскрізно: конструктор головного вікна не падає."""

    def test_window_constructs(self) -> None:
        home = Path(tempfile.mkdtemp(prefix="queue-win-"))
        try:
            (home / "queue.json").write_text("[1, 2, 3]", encoding="utf-8")
            env = dict(os.environ)
            env["BLACKCHPOK_HOME"] = str(home)
            env["BLACKCHPOK_NO_SAVE"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            code = (
                f"import sys; sys.path.insert(0, r'{ROOT}');"
                "from blackchpok_ide import config, main_window;"
                "app = main_window.BlackChpokIDE(settings=config.Settings.load());"
                "app.update_idletasks();"
                "print('ЗАВДАНЬ:', len(app.task_queue.tasks));"
                "app.destroy()"
            )
            result = subprocess.run(
                [sys.executable, "-c", code], cwd=str(ROOT), env=env,
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=240)
            self.assertEqual(
                result.returncode, 0,
                f"вікно не створилось: {(result.stderr or '')[-500:]}")
            self.assertIn("ЗАВДАНЬ: 0", result.stdout or "")
        finally:
            import shutil

            shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
