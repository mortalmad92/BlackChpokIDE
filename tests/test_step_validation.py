"""Крок не зараховується «на слово»: файл мусить існувати на диску.

Найнебезпечніший вид дефекту в агенті — ЗЕЛЕНИЙ звіт без роботи.

Заміряно ``tools/check_full_cycle.py`` до виправлення:

    план: 01. Створення файлу greeting.py
          02. Створення файлу test_greeting.py
          …
    усі кроки завершено: {'done': 6, 'errors': 0}
    файли на диску: []          ← ПОРОЖНЬО

Причина: перевірка дивилась ЛИШЕ на відповідь моделі. Крок просить
створити файл, модель відповідає «Готово.» — у відповіді немає жодного
шляху, і перевірка робила висновок «файлів не згадано → все гаразд».

Другий дефект тієї ж ділянки: у ``main_window`` була ВЛАСНА копія regex,
яка вважала файлом будь-яке «слово.літери». Команда ``python -m
unittest -l`` давала «файл» ``unittest.l``, і крок провалювався з
«файлів немає на диску» — хоч це прапорець командного рядка.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import queue_engine  # noqa: E402
from blackchpok_ide.task_executor import TaskValidator  # noqa: E402


def _task(text: str) -> queue_engine.QueueTask:
    return queue_engine.QueueTask(text=text)


class TestStepThatPromisesFiles(TestCase):
    """Крок «створити файл X» без файлу X — ПРОВАЛ, а не «готово»."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="validator-"))
        self.validator = TaskValidator(lambda: self.root)

    def test_creation_step_without_file_fails(self) -> None:
        verdict = self.validator.validate(
            _task("Створення файлу greeting.py"), "Готово.")
        self.assertFalse(verdict.ok,
                         "крок просив файл, файлу немає — мусить бути провал")
        self.assertIn("greeting.py", verdict.reason)

    def test_other_wording_also_fails(self) -> None:
        for task_text in ("Створи файл app.py",
                          "Напиши скрипт build.py",
                          "Згенеруй module.py"):
            with self.subTest(task=task_text):
                verdict = self.validator.validate(_task(task_text), "Зроблено.")
                self.assertFalse(verdict.ok, f"«{task_text}» зарахували без файлу")

    def test_creation_step_with_file_passes(self) -> None:
        (self.root / "greeting.py").write_text("def hello(n):\n    return n\n",
                                               encoding="utf-8")
        verdict = self.validator.validate(
            _task("Створення файлу greeting.py"), "Готово.")
        self.assertTrue(verdict.ok, f"файл же існує: {verdict.reason}")

    def test_analysis_step_does_not_require_creating(self) -> None:
        """«Проаналізувати greeting.py» нічого не обіцяє створити."""
        verdict = self.validator.validate(
            _task("Проаналізувати greeting.py"), "Файл замалий.")
        self.assertTrue(verdict.ok, f"аналіз не має вимагати файлу: {verdict.reason}")

    def test_non_file_step_passes(self) -> None:
        verdict = self.validator.validate(_task("Запуск тестів"), "Тести пройшли.")
        self.assertTrue(verdict.ok)

    def test_empty_answer_still_fails(self) -> None:
        verdict = self.validator.validate(_task("Запуск тестів"), "")
        self.assertFalse(verdict.ok)


class TestPathsInTaskText(TestCase):
    """Намір кроку береться з ЙОГО тексту, а не з відповіді моделі."""

    def test_creation_detected(self) -> None:
        self.assertEqual(TaskValidator.paths_in_task_text("Створення файлу a.py"),
                         {"a.py"})

    def test_analysis_not_detected(self) -> None:
        self.assertEqual(TaskValidator.paths_in_task_text("Перевірити a.py"),
                         set())

    def test_command_flags_not_files(self) -> None:
        """``-l``/``-q`` — прапорці, а не файли."""
        for text in ("python -m unittest -l",
                     "python -m pytest -q",
                     "python -m unittest discover -s tests"):
            with self.subTest(text=text):
                self.assertEqual(TaskValidator.paths_in_task_text(text), set(),
                                 f"«{text}» дало несправжні файли")


class TestMentionedPaths(TestCase):
    """Один спільний розбір шляхів — без «unittest.l»."""

    def test_code_files_found(self) -> None:
        found = TaskValidator.mentioned_paths("Готово. tests/test_greeting.py")
        self.assertTrue(any("test_greeting.py" in name for name in found),
                        f"не знайдено справжній файл: {found}")

    def test_flags_are_not_files(self) -> None:
        for text in ("python -m unittest -l", "unittest.l", "pytest -q"):
            with self.subTest(text=text):
                self.assertEqual(TaskValidator.mentioned_paths(text), set(),
                                 f"«{text}» дало несправжній файл")

    def test_numbers_are_not_files(self) -> None:
        self.assertEqual(TaskValidator.mentioned_paths("версія 1.5 і 3.14"), set())


if __name__ == "__main__":
    main()
