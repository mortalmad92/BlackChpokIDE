"""Тести інфраструктури якості: стиль коду, коміт-хук, CI.

Розділ 10 плану. Перевіряємо не сам код, а «запобіжники» навколо нього:
чи ловить перевірка стилю реальні огріхи, чи правильно налаштований
pre-commit і CI.

Запуск: python -m unittest tests.test_quality_gate -v
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CHECK_STYLE = ROOT / "tests" / "check_style.py"


class TestStyleChecker(unittest.TestCase):
    """Перевірка стилю справді ловить огріхи."""

    def test_project_is_clean(self) -> None:
        """Поточний код проходить перевірку — інакше винен або код, або правило."""
        result = subprocess.run(
            [sys.executable, str(CHECK_STYLE)],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180,
            env={"PYTHONIOENCODING": "utf-8", "PATH": ""})
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output[-600:])

    def _check_snippet(self, source: str, name: str = "sample.py") -> tuple[int, str]:
        """Прогнати перевірку на одному файлі у тимчасовій теці."""
        import ast
        import importlib.util

        spec = importlib.util.spec_from_file_location("check_style_probe", CHECK_STYLE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        folder = Path(tempfile.mkdtemp())
        path = folder / name
        path.write_text(source, encoding="utf-8")
        module.failures.clear()
        module.check_file(path, strict=False)
        return len(module.failures), " ".join(module.failures)

    def test_detects_trailing_spaces(self) -> None:
        count, detail = self._check_snippet('"""Модуль."""\nx = 1   \n')
        self.assertGreaterEqual(count, 1, detail)
        self.assertIn("пробіли", detail)

    def test_detects_tabs(self) -> None:
        count, detail = self._check_snippet('"""Модуль."""\nx = 1\n\t\n')
        self.assertGreaterEqual(count, 1, detail)
        self.assertIn("табуляція", detail)

    def test_detects_bare_except(self) -> None:
        count, detail = self._check_snippet(
            '"""Модуль."""\ntry:\n    pass\nexcept:\n    pass\n')
        self.assertGreaterEqual(count, 1, detail)
        self.assertIn("голий", detail)

    def test_detects_import_star(self) -> None:
        count, detail = self._check_snippet(
            '"""Модуль."""\nfrom os.path import *\n')
        self.assertGreaterEqual(count, 1, detail)
        self.assertIn("import *", detail)

    def test_detects_syntax_error(self) -> None:
        count, detail = self._check_snippet('"""Модуль."""\ndef broken(:\n')
        self.assertGreaterEqual(count, 1, detail)
        self.assertIn("синтаксична", detail)

    def test_detects_missing_module_docstring(self) -> None:
        folder = Path(tempfile.mkdtemp())
        path = folder / "sample.py"
        path.write_text("x = 1\n", encoding="utf-8")
        import importlib.util

        spec = importlib.util.spec_from_file_location("check_style_probe2", CHECK_STYLE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.failures.clear()
        # Докстрінг перевіряється лише для пакета: підміняємо PKG на теку.
        original = module.PKG
        module.PKG = folder
        try:
            module.check_file(path, strict=False)
        finally:
            module.PKG = original
        self.assertTrue(any("докстрінга" in item for item in module.failures),
                        module.failures)

    def test_clean_snippet_passes(self) -> None:
        count, detail = self._check_snippet(
            '"""Модуль."""\n\n\ndef add(a: int, b: int) -> int:\n    return a + b\n')
        self.assertEqual(count, 0, detail)


class TestPreCommitHook(unittest.TestCase):
    """Коміт-хук існує й запускає швидкі перевірки."""

    def setUp(self) -> None:
        self.script = ROOT / "tests" / "pre_commit.bat"

    def test_script_exists(self) -> None:
        self.assertTrue(self.script.exists())

    def test_runs_four_steps(self) -> None:
        source = self.script.read_text(encoding="utf-8")
        for step in ("[1/4]", "[2/4]", "[3/4]", "[4/4]"):
            self.assertIn(step, source, f"немає кроку {step}")

    def test_calls_style_checker(self) -> None:
        source = self.script.read_text(encoding="utf-8")
        self.assertIn("check_style.py", source)

    def test_calls_selftest_and_tests(self) -> None:
        source = self.script.read_text(encoding="utf-8")
        self.assertIn("--selftest", source)
        self.assertIn("unittest", source)

    def test_comments_are_ascii(self) -> None:
        """Кирилиця в .bat ламає cmd.exe — коментарі мусять бути ASCII."""
        source = self.script.read_text(encoding="utf-8")
        header = source.split("setlocal", 1)[0]
        non_ascii = [ch for ch in header if ord(ch) > 127]
        self.assertEqual(non_ascii, [],
                         f"у заголовку хука є не-ASCII: {set(non_ascii)}")

    @unittest.skipUnless(sys.platform == "win32", "хук — Windows-скрипт")
    def test_hook_passes_on_clean_project(self) -> None:
        """Хук проходить на чистому проєкті.

        Обережно з рекурсією: хук запускає ``unittest discover``, який
        запускає цей тест, який знову запускає хук — і так без кінця.
        Тому тест вимкнений, якщо вже виконується всередині хука
        (ознака — змінна ``BCHPOK_PRE_COMMIT``).
        """
        import os

        if os.environ.get("BCHPOK_PRE_COMMIT") == "1":
            self.skipTest("уже всередині хука — уникаємо рекурсії")

        env = dict(os.environ)
        env.update({
            "PYTHONIOENCODING": "utf-8",
            "BCHPOK_PRE_COMMIT": "1",
            # Крок «тести» пропускаємо: інакше цей тест запускає весь набір,
            # у якому є він сам — прогін роздувається вдвічі.
            "BCHPOK_SKIP_TESTS": "1",
        })
        result = subprocess.run(
            ["cmd", "/c", str(self.script)],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=900, env=env)
        output = (result.stdout or "") + (result.stderr or "")
        self.assertEqual(result.returncode, 0, output[-800:])


class TestCiWorkflow(unittest.TestCase):
    """CI налаштований і покриває ключові перевірки."""

    def setUp(self) -> None:
        self.config = ROOT / ".github" / "workflows" / "tests.yml"

    def test_workflow_exists(self) -> None:
        self.assertTrue(self.config.exists(), "немає .github/workflows/tests.yml")

    def test_has_core_and_gui_jobs(self) -> None:
        source = self.config.read_text(encoding="utf-8")
        self.assertIn("core:", source)
        self.assertIn("gui:", source)

    def test_core_runs_tests_and_style(self) -> None:
        source = self.config.read_text(encoding="utf-8")
        self.assertIn("unittest discover", source)
        self.assertIn("check_style.py", source)
        self.assertIn("--selftest", source)

    def test_gui_runs_live_click(self) -> None:
        source = self.config.read_text(encoding="utf-8")
        self.assertIn("live_every_button.py", source)

    def test_runs_on_push_and_pull_request(self) -> None:
        source = self.config.read_text(encoding="utf-8")
        self.assertIn("push:", source)
        self.assertIn("pull_request:", source)

    def test_yaml_is_valid(self) -> None:
        try:
            import yaml
        except ImportError:
            self.skipTest("pyyaml не встановлено")
        data = yaml.safe_load(self.config.read_text(encoding="utf-8"))
        self.assertIn("jobs", data)
        self.assertIn("core", data["jobs"])


class TestProjectConfig(unittest.TestCase):
    """pyproject.toml описує проєкт і правила стилю."""

    def setUp(self) -> None:
        self.config = ROOT / "pyproject.toml"

    def test_exists(self) -> None:
        self.assertTrue(self.config.exists(), "немає pyproject.toml")

    def test_declares_optional_dependencies(self) -> None:
        source = self.config.read_text(encoding="utf-8")
        self.assertIn("[project.optional-dependencies]", source)
        # Опційні бібліотеки мають бути описані, як у requirements.txt.
        for module in ("numpy", "pillow", "pygments"):
            self.assertIn(module, source.lower(), f"немає {module}")

    def test_ruff_line_length_matches_checker(self) -> None:
        import importlib.util

        source = self.config.read_text(encoding="utf-8")
        self.assertIn("line-length = 100", source)
        spec = importlib.util.spec_from_file_location("cs", CHECK_STYLE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.MAX_LINE, 100,
                         "довжина рядка в лінтері й перевірці має збігатись")

    def test_parses_as_toml(self) -> None:
        try:
            import tomllib
        except ImportError:  # pragma: no cover - Python < 3.11
            self.skipTest("tomllib недоступний")
        with open(self.config, "rb") as handle:
            data = tomllib.load(handle)
        self.assertEqual(data["project"]["name"], "blackchpok-ide")


if __name__ == "__main__":
    unittest.main(verbosity=2)
