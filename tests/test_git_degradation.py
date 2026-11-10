"""Тести чесної деградації: панель «Зміни» без git і звіт про залежності.

Розділ 8 плану. Раніше без git користувач бачив порожню панель і не
розумів, чому немає історії комітів. Тепер панель показує причину й
кнопку встановлення, а ``--selftest`` звітує про опційні залежності.

Запуск: python -m unittest tests.test_git_degradation -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestGitAvailableHelper(unittest.TestCase):
    """Функція перевірки наявності git."""

    def test_returns_bool(self) -> None:
        from blackchpok_ide import diff_stats

        self.assertIsInstance(diff_stats.git_available(), bool)

    def test_detect_changes_works_without_git(self) -> None:
        """Без git панель усе одно віддає ChangeSet, а не падає."""
        from blackchpok_ide import diff_stats

        folder = Path(ROOT)
        changeset = diff_stats.detect_changes(folder)
        self.assertIsNotNone(changeset)
        self.assertTrue(hasattr(changeset, "files"))
        self.assertIn(changeset.source, ("git", "backup"))


class TestChangesPanelDegradation(unittest.TestCase):
    """Панель змін показує підказку, коли git немає."""

    @classmethod
    def setUpClass(cls) -> None:
        import tkinter as tk
        import tkinter.messagebox as messagebox

        from blackchpok_ide import theme

        messagebox.askyesno = lambda *a, **k: True
        messagebox.showinfo = lambda *a, **k: None
        messagebox.showerror = lambda *a, **k: None

        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError as exc:  # pragma: no cover - без дисплея
            raise unittest.SkipTest(f"tkinter недоступний: {exc}") from exc
        cls.fonts = theme.Theme(cls.root)
        cls.fonts.apply()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def _panel(self, status_sink=None):
        from blackchpok_ide import changes_panel

        panel = changes_panel.ChangesPanel(
            self.root, self.fonts, lambda: Path(ROOT),
            on_status=status_sink)
        panel.pack(fill="both", expand=True)
        self.root.update()
        return panel

    def _labels(self, widget) -> list[str]:
        found: list[str] = []
        stack = [widget]
        while stack:
            node = stack.pop()
            try:
                for child in node.winfo_children():
                    stack.append(child)
                    try:
                        if child.winfo_class() == "Label":
                            found.append(str(child.cget("text")))
                    except Exception:
                        pass
            except Exception:
                continue
        return found

    def test_shows_git_hint_when_missing(self) -> None:
        from blackchpok_ide import diff_stats

        if diff_stats.git_available():
            self.skipTest("git встановлено — підказка не потрібна")
        panel = self._panel()
        texts = " ".join(self._labels(panel))
        self.assertIn("git", texts.lower(),
                      "панель має сказати, що git немає")

    def test_hint_has_install_button(self) -> None:
        from blackchpok_ide import diff_stats

        if diff_stats.git_available():
            self.skipTest("git встановлено")
        panel = self._panel()
        texts = self._labels(panel)
        self.assertTrue(any("Встановити git" in text for text in texts), texts[:5])

    def test_hint_explains_alternative(self) -> None:
        from blackchpok_ide import diff_stats

        if diff_stats.git_available():
            self.skipTest("git встановлено")
        panel = self._panel()
        texts = " ".join(self._labels(panel)).lower()
        # Користувач має знати, що зміни все одно видно.
        self.assertTrue("резервн" in texts or "копі" in texts, texts[:120])

    def test_install_reports_status(self) -> None:
        from blackchpok_ide import diff_stats

        if diff_stats.git_available():
            self.skipTest("git встановлено")
        statuses: list[str] = []
        panel = self._panel(status_sink=statuses.append)
        panel._install_git()
        self.root.update()
        self.assertTrue(statuses, "кнопка має повідомити користувача")
        self.assertIn("git", statuses[0].lower())

    def test_panel_survives_refresh_without_git(self) -> None:
        panel = self._panel()
        panel.refresh()
        self.root.update()
        panel.refresh()
        self.root.update()
        self.assertTrue(panel.winfo_exists())

    def test_empty_folder_shows_message(self) -> None:
        from blackchpok_ide import changes_panel

        panel = changes_panel.ChangesPanel(self.root, self.fonts, lambda: None)
        panel.pack(fill="both", expand=True)
        self.root.update()
        texts = " ".join(self._labels(panel))
        self.assertIn("теку проєкту", texts.lower(), texts[:120])


class TestSelftestReportsDependencies(unittest.TestCase):
    """``--selftest`` звітує про опційні залежності."""

    def test_selftest_source_checks_optional_libraries(self) -> None:
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("опційні бібліотеки", source)
        for module in ("PIL", "numpy", "pygments"):
            self.assertIn(module, source, f"немає перевірки {module}")

    def test_selftest_source_checks_external_programs(self) -> None:
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("зовнішні програми", source)
        self.assertIn("shutil", source.replace("_shutil", "shutil"))

    def test_selftest_source_checks_engine(self) -> None:
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("рушій моделі", source)
        self.assertIn("engine_installed", source)

    def test_selftest_runs_and_passes(self) -> None:
        import subprocess

        result = subprocess.run(
            [sys.executable, "main.py", "--selftest"],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180,
            env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output[-400:])
        self.assertIn("опційні бібліотеки", output)
        self.assertIn("зовнішні програми", output)
        self.assertIn("Самоперевірка завершена", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
