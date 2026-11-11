"""Регресія: пошук шляхів мусить бути ЛІНІЙНИМ і точним.

Привід. У `task_plan` і `tool_router` шляхи шукались регуляркою
``((?:[\\w.\\-]+[\\\\/])*[\\w.\\-]+\\.(?:py|js|…))``. На короткій фразі
це непомітно, а на вставленому тексті без шляху час ріс квадратично:
8 000 символів — 0.9 с, 50 000 — 32 с. Інтерфейс зависав на пів хвилини
на звичайній вставці з буфера.

Тут перевіряються дві речі:

1. **Точність** — усі форми, які трапляються в живих запитах (підтеки,
   відносні шляхи, лапки, дужки, кілька файлів у фразі).
2. **Складність** — час на 50 000 символів має лишатись у межах
   мілісекунд, а не секунд.

Запуск: python -m unittest tests.test_path_scan -v
"""

from __future__ import annotations

import time
import unittest

from blackchpok_ide import path_scan, task_plan, tool_router


class TestFindPaths(unittest.TestCase):
    """Точність: те, що людина справді пише."""

    def test_simple_name(self) -> None:
        self.assertEqual(path_scan.find_paths("виправ main.py"), ["main.py"])

    def test_many_extensions(self) -> None:
        for name in ("a.py", "b.json", "c.md", "d.tsx", "e.yaml", "f.css", "g.go"):
            with self.subTest(name=name):
                self.assertEqual(path_scan.find_paths(f"глянь {name}"), [name])

    def test_nested_path_forward(self) -> None:
        self.assertEqual(path_scan.find_paths("виправ src/app/main.py"),
                         ["src/app/main.py"])

    def test_nested_path_backslash(self) -> None:
        self.assertEqual(path_scan.find_paths("виправ src\\app\\main.py"),
                         ["src/app/main.py"])

    def test_relative_dot_prefix(self) -> None:
        """``./main.py`` не має втрачати провідну крапку."""
        self.assertEqual(path_scan.find_paths("читай ./main.py"), ["./main.py"])

    def test_relative_parent_prefix(self) -> None:
        self.assertEqual(path_scan.find_paths("зламано ../lib/x.py"),
                         ["../lib/x.py"])

    def test_parent_traversal_kept(self) -> None:
        """Шлях ``../../etc/passwd.py`` має дійти до перевірки безпеки цілим."""
        self.assertEqual(path_scan.find_paths("читай ../../etc/passwd.py"),
                         ["../../etc/passwd.py"])

    def test_no_trailing_words(self) -> None:
        """Слова після імені файлу не мають прилипати до шляху."""
        self.assertEqual(path_scan.find_paths("у файлі calc.py додай множення"),
                         ["calc.py"])

    def test_two_files_in_phrase(self) -> None:
        self.assertEqual(
            path_scan.find_paths("додай у calc.py множення, а в notes.txt запиши"),
            ["calc.py", "notes.txt"])

    def test_wrapped_in_quotes_and_brackets(self) -> None:
        self.assertEqual(path_scan.find_paths('шлях "src/core/x.ts" тут'),
                         ["src/core/x.ts"])
        self.assertEqual(path_scan.find_paths("(main.py)"), ["main.py"])

    def test_no_duplicates(self) -> None:
        self.assertEqual(path_scan.find_paths("main.py і ще раз main.py"),
                         ["main.py"])

    def test_not_a_file(self) -> None:
        for text in ("без розширення", "версія 2.5", "", "   ", "нема шляху тут"):
            with self.subTest(text=text):
                self.assertEqual(path_scan.find_paths(text), [])

    def test_first_path(self) -> None:
        self.assertEqual(path_scan.first_path("у файлі main.py помилка"), "main.py")
        self.assertEqual(path_scan.first_path("нічого"), "")


class TestLinearTime(unittest.TestCase):
    """Складність: довгий ввід не має підвішувати інтерфейс."""

    #: Стеля навмисно щедра: тест не має «мигати» на повільній машині, але
    #: й не пропустить повернення квадратичної поведінки (там були секунди).
    LIMIT_MS = 400.0

    def _spend(self, size: int) -> float:
        text = "файл.py" + "a" * size
        start = time.perf_counter()
        path_scan.find_paths(text)
        return (time.perf_counter() - start) * 1000

    def test_garbage_50k_is_fast(self) -> None:
        """50 000 символів без шляху: було 32 453 мс, стало <1 мс."""
        spent = self._spend(50_000)
        self.assertLess(spent, self.LIMIT_MS,
                        f"пошук шляхів на 50 000 символів зайняв {spent:.0f} мс "
                        f"(квадратична поведінка повернулась)")

    def test_growth_is_linear(self) -> None:
        """Подвоєння входу не має давати чотирикратного часу."""
        small = max(self._spend(20_000), 0.01)
        large = max(self._spend(80_000), 0.01)
        # Лінійно було б ×4; квадратично — ×16. Беремо поріг ×10 як межу
        # між ними, з запасом на шум вимірювання.
        self.assertLess(large / small, 10.0,
                        f"час виріс у {large / small:.1f}× при рості входу в 4× — "
                        f"це не лінійна складність")


class TestUnderstandStaysFast(unittest.TestCase):
    """Повний розбір фрази теж має лишатись швидким."""

    def test_frame_on_long_input(self) -> None:
        text = "файл.py" + "a" * 12_000 + "))((}{   " * 4
        start = time.perf_counter()
        frame = task_plan.understand(text)
        spent = (time.perf_counter() - start) * 1000
        self.assertLess(spent, 1500.0,
                        f"task_plan.understand на 12 000 символів: {spent:.0f} мс")
        self.assertTrue(frame.intents)

    def test_router_on_long_input(self) -> None:
        text = "файл.py" + "a" * 12_000
        start = time.perf_counter()
        tool_router.route(text)
        spent = (time.perf_counter() - start) * 1000
        self.assertLess(spent, 1500.0,
                        f"tool_router.route на 12 000 символів: {spent:.0f} мс")


if __name__ == "__main__":
    unittest.main(verbosity=2)
