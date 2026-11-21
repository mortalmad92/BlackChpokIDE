"""Точка входу: назва застосунку й версія доступні з ``main``.

Історія цього файлу. Він з'явився як «тест» у живому прогоні автономного
агента й перевіряв ``from main import app`` — атрибута ``app`` у ``main.py``
ніколи не існувало. Через це модуль падав з ``ImportError`` на КОЖНОМУ
прогоні повного набору, і справжні збої губились серед відомого шуму.

Тепер тут перевіряється те, що справді є контрактом точки входу:
``main()`` існує, ``--version`` віддає назву й версію, а ``__main__``
викликає саме її (а не якусь третю функцію).

Запуск: python -m unittest tests.test_main -v
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as entry  # noqa: E402


class TestEntryPoint(unittest.TestCase):
    """``main.py`` як точка входу."""

    def test_main_callable_exists(self) -> None:
        self.assertTrue(callable(getattr(entry, "main", None)),
                        "у main.py немає функції main()")

    def test_version_flag_prints_name_and_version(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "main.py"), "--version"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60, cwd=str(ROOT))
        self.assertEqual(result.returncode, 0,
                         f"stdout={result.stdout!r} stderr={result.stderr!r}")
        from blackchpok_ide import APP_NAME, APP_VERSION

        self.assertIn(APP_NAME, result.stdout)
        self.assertIn(APP_VERSION, result.stdout)

    def test_app_name_is_not_empty(self) -> None:
        from blackchpok_ide import APP_NAME

        self.assertTrue(APP_NAME.strip())
        self.assertIn("BlackChpok", APP_NAME)


if __name__ == "__main__":
    unittest.main(verbosity=2)
