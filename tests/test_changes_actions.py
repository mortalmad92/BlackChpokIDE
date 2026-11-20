"""Відкат і прийняття змін у панелі «Зміни».

Перевіряємо дві дії, яких раніше не було: ``restore_from_backup`` (відкат
до ``.bak``) і ``accept_backup`` (прибрати копію, лишити поточний вміст), а
також те, що панель показує кнопки лише тоді, коли дію справді можна
виконати.

Запуск:  python -m unittest tests.test_changes_actions -v
"""

from __future__ import annotations

import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import changes_panel, theme, workspace  # noqa: E402


class TestBackupActions(unittest.TestCase):
    """Файлові операції відкату й прийняття — без tkinter."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="changes-"))
        self.file = self.tmp / "sample.py"
        self.file.write_text("old\n", encoding="utf-8")
        # Пишемо через API робочої області: саме він створює .bak.
        workspace.write_text_file(self.file, "new\n")

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_write_creates_backup(self) -> None:
        self.assertTrue(workspace.has_backup(self.file))
        backup = workspace.backup_path(self.file)
        self.assertEqual(backup.read_text(encoding="utf-8"), "old\n")
        self.assertEqual(self.file.read_text(encoding="utf-8"), "new\n")

    def test_restore_returns_previous_content(self) -> None:
        self.assertTrue(workspace.restore_from_backup(self.file))
        self.assertEqual(self.file.read_text(encoding="utf-8"), "old\n")
        # Копію лишаємо: користувач може відкотити ще раз або порівняти.
        self.assertTrue(workspace.has_backup(self.file))

    def test_accept_removes_backup_only(self) -> None:
        self.assertTrue(workspace.accept_backup(self.file))
        self.assertFalse(workspace.has_backup(self.file))
        self.assertEqual(self.file.read_text(encoding="utf-8"), "new\n")

    def test_missing_backup_is_reported(self) -> None:
        workspace.accept_backup(self.file)
        self.assertFalse(workspace.has_backup(self.file))
        # Немає копії — немає й «тихого успіху».
        self.assertFalse(workspace.restore_from_backup(self.file))
        self.assertFalse(workspace.accept_backup(self.file))
        self.assertEqual(self.file.read_text(encoding="utf-8"), "new\n")


class TestChangesPanelActions(unittest.TestCase):
    """Кнопки панелі прив'язані до реальних файлів."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="changes-ui-"))
        self.file = self.tmp / "code.py"
        self.file.write_text("before\n", encoding="utf-8")
        workspace.write_text_file(self.file, "after\n")
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self) -> None:
        import shutil

        try:
            self.root.destroy()
        except tk.TclError:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _panel(self) -> changes_panel.ChangesPanel:
        statuses: list[str] = []
        panel = changes_panel.ChangesPanel(
            self.root, theme.Theme(self.root), lambda: self.tmp,
            on_status=statuses.append, synchronous=True,
        )
        panel.statuses = statuses  # type: ignore[attr-defined]
        return panel

    def test_panel_lists_change(self) -> None:
        panel = self._panel()
        self.assertFalse(panel.changeset.is_empty)
        self.assertIn("code.py", [item.path for item in panel.changeset.files])

    def test_revert_restores_file(self) -> None:
        panel = self._panel()
        change = panel.changeset.files[0]
        panel._revert(self.file, change)
        self.assertEqual(self.file.read_text(encoding="utf-8"), "before\n")
        self.assertTrue(any("Відкотив" in text for text in panel.statuses))

    def test_accept_clears_change_from_list(self) -> None:
        panel = self._panel()
        change = panel.changeset.files[0]
        panel._accept(self.file, change)
        self.assertEqual(self.file.read_text(encoding="utf-8"), "after\n")
        # Після прийняття порівнювати немає з чим — файл зникає зі списку.
        panel.refresh()
        self.assertTrue(panel.changeset.is_empty)

    def test_accept_all_reports_when_nothing_to_accept(self) -> None:
        panel = self._panel()
        panel.accept_all()
        panel.accept_all()
        self.assertTrue(any("Приймати нічого" in text for text in panel.statuses))


if __name__ == "__main__":
    unittest.main()
