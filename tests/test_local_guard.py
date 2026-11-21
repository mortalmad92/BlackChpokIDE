"""Наглядач за локальними моделями: три види застрягання.

Тести навмисно повторюють реальні прогони, які раніше виглядали як «робота»:

* той самий виклик із тим самим результатом;
* той самий виклик, записаний трохи інакше (``./a.py``, ``file=``);
* довгий цикл A→B→A→B, у якому жодного повтору підряд немає.
"""

from __future__ import annotations

import unittest


class TestNormalisation(unittest.TestCase):
    def test_same_path_in_different_spelling(self) -> None:
        from blackchpok_ide import local_guard

        first = local_guard.fingerprint("read_file", {"path": "a.py"}, True, "x")
        second = local_guard.fingerprint("read_file", {"path": ".\\a.py"}, True, "x")
        third = local_guard.fingerprint("read_file", {"path": " a.py "}, True, "x")
        self.assertEqual(first, second)
        self.assertEqual(first, third)

    def test_alias_arguments_are_one_call(self) -> None:
        from blackchpok_ide import local_guard

        first = local_guard.fingerprint("read_file", {"path": "a.py"}, True, "x")
        second = local_guard.fingerprint("read_file", {"file": "a.py"}, True, "x")
        self.assertEqual(first, second,
                         "file= і path= — це той самий виклик")

    def test_different_files_stay_different(self) -> None:
        from blackchpok_ide import local_guard

        first = local_guard.fingerprint("read_file", {"path": "a.py"}, True, "x")
        second = local_guard.fingerprint("read_file", {"path": "b.py"}, True, "x")
        self.assertNotEqual(first, second)

    def test_noise_arguments_are_ignored(self) -> None:
        from blackchpok_ide import local_guard

        first = local_guard.fingerprint("read_file", {"path": "a.py"}, True, "x")
        second = local_guard.fingerprint(
            "read_file", {"path": "a.py", "timeout": 60}, True, "x")
        self.assertEqual(first, second)


class TestHints(unittest.TestCase):
    def test_hint_names_the_next_action(self) -> None:
        from blackchpok_ide import local_guard

        hint = local_guard.hint_for("read_file", {"path": "a.py"}, count=2)
        self.assertIn("edit_file", hint,
                      "модель має отримати конкретну наступну дію")

    def test_hint_for_unknown_tool_is_generic(self) -> None:
        from blackchpok_ide import local_guard

        hint = local_guard.hint_for("щось_невідоме", count=3)
        self.assertIn("Не повторюй", hint)


class TestStuckGuard(unittest.TestCase):
    def _guard(self):
        from blackchpok_ide.local_guard import StuckGuard

        return StuckGuard()

    def test_first_steps_are_fine(self) -> None:
        guard = self._guard()
        signal = guard.observe("read_file", {"path": "a.py"}, True, "текст")
        self.assertFalse(signal.stuck)

    def test_same_call_becomes_tired(self) -> None:
        guard = self._guard()
        signal = None
        for _ in range(3):
            signal = guard.observe("read_file", {"path": "a.py"}, True, "текст")
        self.assertIsNotNone(signal)
        self.assertTrue(signal.stuck)
        self.assertIn("read_file", signal.reason)

    def test_same_call_becomes_hopeless(self) -> None:
        guard = self._guard()
        signal = None
        for _ in range(5):
            signal = guard.observe("read_file", {"path": "a.py"}, True, "текст")
        self.assertIsNotNone(signal)
        self.assertTrue(signal.hopeless)
        self.assertTrue(signal.hint)

    def test_cosmetic_difference_does_not_reset_counter(self) -> None:
        guard = self._guard()
        signal = None
        for path in ("a.py", "./a.py", ".\\a.py"):
            signal = guard.observe("read_file", {"path": path}, True, "текст")
        self.assertIsNotNone(signal)
        self.assertTrue(signal.stuck,
                        "різне написання того самого шляху — це повтор")

    def test_long_cycle_is_detected(self) -> None:
        guard = self._guard()
        steps = [("list_dir", {"path": "."}), ("read_file", {"path": "a.py"})]
        signal = None
        for index in range(6):
            name, arguments = steps[index % 2]
            signal = guard.observe(name, arguments, True, f"крок {index % 2}")
        self.assertIsNotNone(signal)
        self.assertTrue(signal.stuck, "A→B→A→B — це цикл, а не робота")
        self.assertIn("колу", signal.reason)

    def test_progress_is_not_a_loop(self) -> None:
        guard = self._guard()
        stuck = False
        for index in range(6):
            signal = guard.observe("read_file", {"path": f"file{index}.py"},
                                   True, f"вміст {index}")
            stuck = stuck or signal.stuck
        self.assertFalse(stuck, "різні файли — це справжня робота")

    def test_blind_retries_are_detected(self) -> None:
        guard = self._guard()
        signal = None
        for index in range(4):
            signal = guard.observe("edit_file",
                                   {"path": "a.py", "old_string": f"варіант {index}"},
                                   False, "фрагмент не знайдено")
        self.assertIsNotNone(signal)
        self.assertTrue(signal.stuck)
        self.assertIn("навмання", signal.hint)

    def test_reset_forgets_history(self) -> None:
        guard = self._guard()
        for _ in range(5):
            guard.observe("read_file", {"path": "a.py"}, True, "текст")
        guard.reset()
        signal = guard.observe("read_file", {"path": "a.py"}, True, "текст")
        self.assertFalse(signal.stuck)


class TestAgentRepeatGuardUsesNormalisation(unittest.TestCase):
    """Той самий наглядач, але через ``agent._RepeatGuard`` (як у циклі)."""

    def test_cosmetic_path_change_is_a_repeat(self) -> None:
        from blackchpok_ide.agent import _RepeatGuard

        guard = _RepeatGuard()
        prints = []
        for path in ("a.py", "./a.py", "a.py ", "a.py"):
            prints.append(guard.observe(
                _RepeatGuard.fingerprint("read_file", {"path": path}, True, "x")))
        self.assertTrue(any(item[1] for item in prints))

    def test_long_cycle_stops_the_work(self) -> None:
        from blackchpok_ide.agent import _RepeatGuard

        guard = _RepeatGuard()
        hopeless = False
        for index in range(12):
            name = "list_dir" if index % 2 == 0 else "read_file"
            key = _RepeatGuard.fingerprint(
                name, {"path": "." if name == "list_dir" else "a.py"},
                True, name)
            _count, _tired, stop = guard.observe(key)
            hopeless = hopeless or stop
        self.assertTrue(hopeless, "довгий цикл має зупиняти роботу")
        self.assertIn("по колу", guard.summary())


if __name__ == "__main__":
    unittest.main()
