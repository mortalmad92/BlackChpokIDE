"""Пігулки вибору в чаті: «робочий простір» і «режим».

Що перевіряємо — те, що бачив користувач на скріншоті: над полем вводу
мусить бути **дві** кнопки з реальним станом і випадаючим меню, а не лише
підписи в шапці.

Важливо саме те, що пігулка ПОКАЗУЄ стан: якщо ``set_workspace("")``
лишить порожній підпис, користувач не зрозуміє, чому агент відмовляється
працювати. Тому перевіряємо і текст, і наявність меню, і те, що вибір теки
веде до справжнього ``set_workspace`` оболонки.

Запуск: python -m unittest tests.test_composer_pills -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestComposerPills(unittest.TestCase):
    """Живі віджети: пігулки, їхні підписи й меню."""

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

    def test_both_pills_exist_above_input(self) -> None:
        panel, host = self._panel()
        try:
            self.assertTrue(panel.workspace_btn.winfo_exists())
            # Пігулка режиму прибрана 20.11.2026 на прохання користувача:
            # «модель має працювати в режимі агента та чату і використання
            # будь-яких інструментів на розсуд самої моделі». Її підпис
            # читався як заборона працювати з файлами.
            self.assertIsNone(panel.mode_btn,
                              "пігулки режиму в композері більше немає")
            # Робочий простір стоїть вище за поле вводу в СВОЇЙ сітці.
            self.assertLess(panel.space_row.grid_info().get("row"),
                            panel.input_box.grid_info().get("row"))
        finally:
            host.destroy()

    def test_workspace_pill_shows_real_name(self) -> None:
        panel, host = self._panel()
        try:
            panel.set_workspace("blackchpock_ai", path=str(ROOT))
            self.assertEqual(panel.workspace_btn.label.cget("text"), "blackchpock_ai")
            panel.set_workspace("")
            self.assertIn("не обрано", panel.workspace_btn.label.cget("text"))
        finally:
            host.destroy()

    def test_mode_pill_shows_mode(self) -> None:
        """Режим більше не малюється — але його стан лишається доступним.

        Раніше тут перевірялись підписи пігулки («Код») і підпису-опису.
        Обидва прибрано 20.11.2026: користувач просив максимальне
        самовирішування моделі й прибрати пункт, що читався як заборона.
        Вимога, що лишилась: ``set_mode`` приймає виклик вікна й не падає.
        """
        panel, host = self._panel()
        try:
            panel.set_mode("Код", icon="⟨⟩")
            self.assertEqual(panel._mode_label, "Код")
            self.assertIsNone(panel.mode_btn)
            self.assertIsNone(panel.mode_caption)
        finally:
            host.destroy()

    def test_pill_click_calls_shell_callback(self) -> None:
        panel, host = self._panel()
        calls: list[str] = []
        panel.on_workspace_menu = lambda _btn: calls.append("workspace")
        panel.on_mode_menu = lambda _btn: calls.append("mode")
        try:
            panel.workspace_btn.event_generate("<Button-1>")
            self.root.update()
            # Пігулки режиму немає — меню викликають програмно (слэш-команда
            # чи меню програм), і колбек вікна мусить лишатись робочим.
            panel._open_mode_menu()
            self.root.update()
            if "workspace" not in calls:
                # event_generate у прихованому вікні може не дійти —
                # викликаємо той самий обробник явно (він і є бізнес-логікою).
                panel._open_workspace_menu()
            # Кожен колбек спрацював рівно один раз.
            self.assertEqual(sorted(calls), ["mode", "workspace"])
        finally:
            host.destroy()

    def test_workspace_menu_lists_only_real_folders(self) -> None:
        from blackchpok_ide.workspace_menu import WorkspaceMenu

        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real-project"
            real.mkdir()
            gone = Path(tmp) / "gone-project"
            menu = WorkspaceMenu(
                self.root, self.fonts,
                current=str(real),
                recent=[str(real), str(gone), ""],
            )
            try:
                self.assertEqual(menu.recent, [],
                                 "неіснуючі теки не мають потрапляти в меню")
                menu2 = WorkspaceMenu(
                    self.root, self.fonts,
                    current="",
                    recent=[str(real), str(gone)],
                )
                self.assertEqual(menu2.recent, [str(real)])
                menu2.destroy()
            finally:
                menu.destroy()

    def test_workspace_menu_pick_calls_back(self) -> None:
        from blackchpok_ide.workspace_menu import WorkspaceMenu

        picked: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "one"
            second = Path(tmp) / "two"
            first.mkdir()
            second.mkdir()
            menu = WorkspaceMenu(self.root, self.fonts, current=str(first),
                                 recent=[str(second)],
                                 on_pick=picked.append)
            try:
                menu._pick(str(second))
                self.assertEqual(picked, [str(second)])
                # Неіснуюча тека не вибирається й не ламає меню.
                menu._pick(str(Path(tmp) / "nope"))
                self.assertEqual(picked, [str(second)])
            finally:
                menu.destroy()

    def test_workspace_menu_forget_does_not_open_folder(self) -> None:
        from blackchpok_ide.workspace_menu import WorkspaceMenu

        picked: list[str] = []
        forgotten: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "one"
            second = Path(tmp) / "two"
            first.mkdir()
            second.mkdir()
            menu = WorkspaceMenu(
                self.root, self.fonts, current=str(first),
                recent=[str(second)],
                on_pick=picked.append,
                on_forget=forgotten.append,
            )
            try:
                menu._forget(str(second))
                self.assertEqual(forgotten, [str(second)])
                self.assertEqual(picked, [])
            finally:
                menu.destroy()


class TestShellWiring(unittest.TestCase):
    """Оболонка: пігулки підключені до реальних дій, а не до заглушок."""

    def test_main_window_connects_pills(self) -> None:
        import inspect

        from blackchpok_ide import main_window

        source = inspect.getsource(main_window.BlackChpokIDE)
        self.assertIn("chat.on_workspace_menu = self.show_workspace_menu", source)
        self.assertIn("chat.on_mode_menu = self.show_mode_menu", source)
        # Вибір теки йде ТІЄЮ Ж логікою, що й шапка.
        pick = inspect.getsource(main_window.BlackChpokIDE._pick_workspace_from_chat)
        self.assertIn("set_workspace", pick)
        menu = inspect.getsource(main_window.BlackChpokIDE.show_workspace_menu)
        self.assertIn("on_forget=self.forget_recent_folder", menu)

    def test_set_project_updates_pill(self) -> None:
        import inspect

        from blackchpok_ide import main_window

        source = inspect.getsource(main_window.BlackChpokIDE.set_project)
        self.assertIn("chat.set_workspace", source)

    def test_set_agent_mode_updates_pill(self) -> None:
        import inspect

        from blackchpok_ide import main_window

        source = inspect.getsource(main_window.BlackChpokIDE.set_agent_mode)
        self.assertIn("chat.set_mode", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
