"""``edit_file`` показує РЕАЛЬНИЙ вміст, коли фрагмент не знайдено.

Причина появи. Заміряно живим прогоном ``tools/eval_agent.py --one multi``:

    [tool_call]  edit_file(path=calc.py,
                           old_string=«# Додай функцію множення тут», …)
    [tool_result] Фрагмент не знайдено у calc.py.
                  Прочитай файл ще раз і візьми точний текст.

Модель 14B ВИГАДАЛА цей фрагмент — у файлі такого рядка немає й ніколи не
було. Підказка «прочитай ще раз» не допомагала: модель повторювала ту саму
вигадку, бо не бачила, що насправді у файлі. Завдання провалювалось
(«Виконано частково»), хоч файл був простий.

Тепер помилка містить справжній вміст із номерами рядків і пряму вказівку
взяти ``old_string`` звідти. Це та сама інформація, яку модель дістала б
окремим ``read_file``, але без витраченого кроку.

Заміряно після зміни: сценарій ``multi`` проходить (10 з 10 у eval_agent).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide.agent_tools import ToolRegistry  # noqa: E402

SAMPLE = '''"""Калькулятор."""


def add(a, b):
    return a + b
'''


class TestMissingFragmentShowsContent(TestCase):
    """Помилка правки мусить показувати файл, а не лише «не знайдено»."""

    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp(prefix="edit-hint-"))
        (self.workspace / "calc.py").write_text(SAMPLE, encoding="utf-8")
        self.registry = ToolRegistry(self.workspace)

    def _fail(self, old_string: str):
        return self.registry.call("edit_file", {
            "path": "calc.py",
            "old_string": old_string,
            "new_string": "def multiply(a, b):\n    return a * b",
        })

    def test_error_mentions_file(self) -> None:
        result = self._fail("# Додай функцію множення тут")
        self.assertFalse(result.ok, "вигаданий фрагмент не має застосовуватись")
        self.assertIn("calc.py", result.output)

    def test_error_shows_real_lines(self) -> None:
        """Головна вимога: у помилці видно СПРАВЖНІЙ код."""
        result = self._fail("# Додай функцію множення тут")
        self.assertIn("def add(a, b):", result.output,
                      "модель мусить бачити реальний вміст файлу")
        self.assertIn("return a + b", result.output)

    def test_error_has_line_numbers(self) -> None:
        result = self._fail("вигаданий рядок")
        self.assertIn("1 |", result.output, "немає номерів рядків")
        self.assertIn("4 |", result.output)

    def test_error_asks_to_copy_verbatim(self) -> None:
        result = self._fail("вигаданий рядок")
        low = result.output.lower()
        self.assertIn("дослівно", low,
                      "модель має знати, що фрагмент треба копіювати точно")

    def test_valid_edit_still_works(self) -> None:
        """Покращене повідомлення не зламало успішну правку."""
        result = self.registry.call("edit_file", {
            "path": "calc.py",
            "old_string": "def add(a, b):",
            "new_string": ("def multiply(a, b):\n    return a * b\n\n\n"
                           "def add(a, b):"),
        })
        self.assertTrue(result.ok, result.output)
        body = (self.workspace / "calc.py").read_text(encoding="utf-8")
        self.assertIn("def multiply", body)

    def test_long_file_is_not_dumped_whole(self) -> None:
        """Довгий файл обрізаємо — інакше відповідь з'їдає контекст."""
        big = "\n".join(f"value_{index} = {index}" for index in range(200))
        (self.workspace / "big.py").write_text(big + "\n", encoding="utf-8")
        result = self.registry.call("edit_file", {
            "path": "big.py",
            "old_string": "немає такого рядка",
            "new_string": "x = 1",
        })
        self.assertFalse(result.ok)
        self.assertIn("ще 160 рядків", result.output,
                      "хвіст довгого файлу має бути обрізаний")


if __name__ == "__main__":
    main()
