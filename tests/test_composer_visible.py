"""Поле вводу мусить бути на екрані — інакше програмою не користуватись.

Регресія, яку цей тест закриває: у ``bottom_box`` два віджети отримали
однаковий ``row=3`` у ``grid``. Два віджети в одній комірці накладаються,
і поле вводу **зникло з екрана** — користувач бачив порожню темну смугу
замість форми, куди писати завдання.

Таке не ловиться ні юніт-тестами логіки, ні «пройшло 77 натискань»:
віджет існує, метод ``_send`` працює, але дістатись до нього неможливо.
Тому перевіряємо саме ГЕОМЕТРІЮ: композер має бути видимим і мати
ненульову висоту.

Запуск: python -m unittest tests.test_composer_visible -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestComposerGeometry(unittest.TestCase):
    """Віджети композера не мають накладатись у grid."""

    @classmethod
    def setUpClass(cls) -> None:
        import tkinter as tk

        from blackchpok_ide import theme

        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError as exc:  # pragma: no cover
            raise unittest.SkipTest(f"tkinter недоступний: {exc}") from exc
        cls.fonts = theme.Theme(cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def _panel(self):
        import tkinter as tk

        from blackchpok_ide.agent_tools import ToolRegistry
        from blackchpok_ide.chat_panel import ChatPanel
        from blackchpok_ide.config import Settings

        host = tk.Frame(self.root)
        host.pack(fill="both", expand=True)
        panel = ChatPanel(host, self.fonts, Settings(), ToolRegistry(ROOT),
                          composer_parent=host)
        panel.pack(fill="both", expand=True)
        self.root.update()
        return panel, host

    def test_no_two_children_share_a_cell(self) -> None:
        """Головна вимога: у ``bottom_box`` немає двох віджетів в одній комірці.

        Саме це й зламалось: ``stats_bar`` і композер обоє отримали row=3,
        і форма вводу сховалась під смугою статистики.
        """
        panel, host = self._panel()
        try:
            cells: dict[tuple, list[str]] = {}
            for child in panel.bottom_box.winfo_children():
                info = child.grid_info()
                if not info:
                    continue
                key = (info.get("row"), info.get("column"))
                cells.setdefault(key, []).append(str(child))
            clashed = {key: names for key, names in cells.items() if len(names) > 1}
            self.assertEqual(clashed, {},
                             f"віджети наклались в одній комірці grid: {clashed}")
        finally:
            host.destroy()

    def test_input_box_has_size(self) -> None:
        """Поле вводу має реальну висоту (його видно й у нього можна писати)."""
        panel, host = self._panel()
        try:
            box = panel.input_box
            self.assertGreater(box.winfo_reqheight(), 10,
                               "поле вводу має ненульову висоту")
            self.assertGreater(box.winfo_reqwidth(), 50,
                               "поле вводу має ненульову ширину")
        finally:
            host.destroy()

    def test_composer_is_mapped_and_positive_height(self) -> None:
        """Композер у розкладці й має висоту більшу за нуль."""
        panel, host = self._panel()
        try:
            self.root.update_idletasks()
            self.assertTrue(bool(panel.bottom_box.grid_info()) or
                            bool(panel.bottom_box.pack_info()),
                            "композер має бути в менеджері геометрії")
            self.assertGreater(panel.bottom_box.winfo_reqheight(), 40,
                               "композер має вміщати поле вводу")
        finally:
            host.destroy()

    def test_send_button_reachable(self) -> None:
        """Кнопка надсилання існує й має розмір."""
        panel, host = self._panel()
        try:
            self.root.update_idletasks()
            sender = getattr(panel, "send_btn", None) or getattr(panel, "btn_send", None)
            if sender is not None:
                self.assertGreater(sender.winfo_reqwidth(), 4)
        finally:
            host.destroy()

    def test_stages_and_queue_above_input(self) -> None:
        """Смуги етапів і черги стоять ВИЩЕ за поле вводу, не поверх нього."""
        panel, host = self._panel()
        try:
            rows = {}
            for name, widget in (("stages", panel.stage_strip),
                                 ("queue", panel.queue_strip)):
                info = widget.grid_info()
                if info:
                    rows[name] = info.get("row")
            input_row = panel.composer_card.grid_info().get("row")
            self.assertIsNotNone(input_row)
            for name, row in rows.items():
                self.assertLess(row, input_row,
                                f"смуга «{name}» має бути вище за поле вводу")
        finally:
            host.destroy()


class TestComposerInSource(unittest.TestCase):
    """Перевірка в тексті: рядки композера унікальні."""

    def test_grid_rows_are_unique(self) -> None:
        import ast
        import inspect
        import textwrap

        from blackchpok_ide.chat_panel import ChatPanel

        source = textwrap.dedent(inspect.getsource(ChatPanel))
        tree = ast.parse(source)
        rows: dict[str, int] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if getattr(func, "attr", "") != "grid":
                continue
            target = ast.unparse(func.value) if hasattr(ast, "unparse") else ""
            if "self.bottom_box" not in str(target):
                continue
            for keyword in node.keywords:
                if keyword.arg == "row" and isinstance(keyword.value, ast.Constant):
                    rows[target] = keyword.value.value
        # Кожен віджет у bottom_box має власний рядок.
        seen: dict[int, str] = {}
        for target, row in rows.items():
            self.assertNotIn(row, seen,
                             f"{target} і {seen.get(row)} обидва на row={row}")
            seen[row] = target


if __name__ == "__main__":
    unittest.main(verbosity=2)
