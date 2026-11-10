"""Узгодженість тестових раннерів.

Головна суперечність попереднього аудиту: «141 успішний набір тестів» в
одному середовищі й «7 помилок» в іншому. Причина знайдена:

* ``unittest discover`` бачив УСІ модулі ``tests/test_*.py``;
* ``tests/run_all.py`` мав РУЧНИЙ список — зі 113 модулів запускав 67, а
  46 (``test_v2_audit``, ``test_mcp_integration``, ``test_native_runtime``,
  ``test_bench`` …) не запускались НІКОЛИ.

Тому зелений прогін через ``run_tests.bat`` нічого не казав про 46
модулів. Ці тести фіксують, що розбіжність не повернеться.

Запуск: python -m unittest tests.test_runner_consistency -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

TESTS_DIR = ROOT / "tests"


def _runner_module():
    import run_all  # noqa: PLC0415 - модуль tests/run_all.py

    return run_all


class TestRunnerCoverage(unittest.TestCase):
    """``run_all.py`` мусить бачити КОЖЕН тестовий модуль на диску."""

    def test_no_module_is_missing_from_runner(self) -> None:
        runner = _runner_module()
        discovered = set(runner.discover_modules())
        on_disk = {path.stem for path in TESTS_DIR.glob("test_*.py")}
        missing = sorted(on_disk - discovered)
        self.assertEqual(missing, [],
                         f"run_all.py не запускає ці модулі: {missing}")

    def test_live_scripts_are_discovered_too(self) -> None:
        """``e2e_``/``smoke_`` теж мають бути в прогоні, а не поза ним."""
        runner = _runner_module()
        discovered = set(runner.discover_modules())
        extra = {path.stem for path in TESTS_DIR.glob("e2e_*.py")}
        extra |= {path.stem for path in TESTS_DIR.glob("smoke_*.py")}
        self.assertTrue(extra, "у проєкті мають бути e2e/smoke-скрипти")
        self.assertEqual(sorted(extra - discovered), [],
                         "e2e/smoke-скрипти не потрапили в прогін")

    def test_discovery_is_dynamic(self) -> None:
        """Список будується з ДИСКА, а не з констант у коді.

        Якщо хтось знову впише ручний перелік, новий тест мовчки перестане
        запускатись — саме це й сталося раніше.
        """
        import inspect

        source = inspect.getsource(_runner_module().discover_modules)
        self.assertIn("glob(", source,
                      "перелік модулів має будуватись обходом теки")

    def test_fast_mode_skips_only_live(self) -> None:
        """``--fast`` пропускає ЛИШЕ живі прогони, не «половину тестів»."""
        runner = _runner_module()
        modules = runner.discover_modules()
        fast_set = [name for name in modules if name not in runner.LIVE_MODULES]
        self.assertGreater(len(fast_set), len(modules) // 2,
                           "у швидкому режимі лишилось замало тестів")
        self.assertTrue(runner.LIVE_MODULES, "живі прогони мають бути виділені")


class TestKnownModulesAreListed(unittest.TestCase):
    """Модулі, які РАНІШЕ не запускались, тепер у прогоні."""

    def test_previously_skipped_modules_present(self) -> None:
        runner = _runner_module()
        discovered = set(runner.discover_modules())
        previously_missing = (
            "test_v2_audit", "test_mcp_integration", "test_native_runtime",
            "test_bench", "test_context_budget", "test_tool_orchestrator",
            "test_intent_engine", "test_lazy_tools",
        )
        for name in previously_missing:
            with self.subTest(module=name):
                self.assertIn(name, discovered,
                              f"{name} знову поза прогоном")


class TestSuiteIsRunnable(unittest.TestCase):
    """Заявлена повнота підтверджується придатністю кожного модуля."""

    def test_every_test_module_imports_or_is_script(self) -> None:
        """Кожен модуль — або ``unittest``, або скрипт із ``main()``."""
        import ast

        problems: list[str] = []
        for path in sorted(TESTS_DIR.glob("*.py")):
            if not path.stem.startswith(("test_", "e2e_", "smoke_")):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError as exc:
                problems.append(f"{path.name}: SyntaxError {exc}")
                continue
            has_main = any(
                isinstance(node, ast.FunctionDef) and node.name == "main"
                for node in tree.body)
            has_classes = any(isinstance(node, ast.ClassDef)
                              for node in tree.body)
            if not (has_main or has_classes):
                problems.append(f"{path.name}: ні main(), ні класів")
        self.assertEqual(problems, [], f"проблемні модулі: {problems}")

    def test_script_classification_matches_code(self) -> None:
        """Класифікація «скрипт проти unittest» береться з КОДУ.

        Регресія: ручний список ``SCRIPT_MODULES`` містив 19 звичайних
        ``unittest``-модулів. Їх запускали як скрипти — і вони «проходили»,
        не виконавши ЖОДНОГО тесту (у них немає ``main()``).
        """
        import ast

        runner = _runner_module()
        scripts = runner.script_modules()
        wrong: list[str] = []
        for name in sorted(scripts):
            path = TESTS_DIR / f"{name}.py"
            if not path.exists():
                wrong.append(f"{name}: файлу немає")
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            has_main = any(
                isinstance(node, ast.FunctionDef) and node.name == "main"
                for node in tree.body)
            if not has_main:
                wrong.append(f"{name}: у списку скриптів, але без main()")
        self.assertEqual(wrong, [], f"хибна класифікація: {wrong}")

    def test_unittest_modules_have_test_cases(self) -> None:
        """Модуль, який запускають через ``unittest``, мусить мати тести."""
        import ast

        runner = _runner_module()
        scripts = runner.script_modules()
        empty: list[str] = []
        for name in runner.discover_modules():
            if name in scripts:
                continue
            path = TESTS_DIR / f"{name}.py"
            if not path.exists():
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            has_case = any(
                isinstance(node, ast.ClassDef) and node.bases
                for node in tree.body)
            has_test = any(
                isinstance(node, ast.FunctionDef) and node.name.startswith("test")
                for node in tree.body)
            if not (has_case or has_test):
                empty.append(name)
        self.assertEqual(empty, [],
                         f"через unittest запускаються без тестів: {empty}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
