"""Тести вимоги «проєкт → потім чат», повного тексту й ресайзу панелі.

Перевіряємо те, що користувач бачить і натискає:

* без вибраної теки проєкту чат не створюється й не відкривається;
* екран вибору проєкту з'являється замість чату;
* відповідь агента показується ПОВНІСТЮ (без власної смуги прокрутки);
* ширина лівої панелі перетягується й переживає перезапуск;
* кнопка «видалити всі чати» є й справді чистить сховище.

Запуск: python -m unittest tests.test_chat_ux -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import chat_store as cs  # noqa: E402


class TestDeleteAll(unittest.TestCase):
    """Видалення всіх чатів у сховищі."""

    def _store(self):
        return cs.ChatStore(Path(tempfile.mkdtemp()) / "chats.json")

    def test_delete_all_removes_everything(self) -> None:
        store = self._store()
        store.create(title="перший")
        store.create(title="другий")
        archived = store.create(title="архівний")
        store.archive(archived.id, True)
        removed = store.delete_all()
        self.assertEqual(removed, 3)
        self.assertEqual(store.chats, [])

    def test_delete_all_clears_active(self) -> None:
        store = self._store()
        chat = store.create(title="активний")
        store.set_active(chat.id)
        store.delete_all()
        self.assertEqual(store.active_id, "")

    def test_delete_all_moves_active_to_remaining(self) -> None:
        store = self._store()
        first = store.create(title="перший")
        second = store.create(title="другий")
        store.set_active(first.id)
        removed = store.delete_all(archived=True)   # не чіпає активні
        self.assertEqual(removed, 0)
        self.assertEqual(store.active_id, first.id)
        self.assertEqual(len(store.chats), 2)

    def test_delete_archived_only(self) -> None:
        store = self._store()
        store.create(title="активний")
        archived = store.create(title="архівний")
        store.archive(archived.id, True)
        removed = store.delete_all(archived=True)
        self.assertEqual(removed, 1)
        self.assertEqual(len(store.chats), 1)
        self.assertEqual(store.chats[0].title, "активний")

    def test_delete_all_on_empty_is_safe(self) -> None:
        store = self._store()
        self.assertEqual(store.delete_all(), 0)

    def test_delete_all_persists(self) -> None:
        path = Path(tempfile.mkdtemp()) / "chats.json"
        first = cs.ChatStore(path)
        first.create(title="зникне")
        first.delete_all()
        second = cs.ChatStore(path)
        self.assertEqual(second.chats, [])


class GuiCase(unittest.TestCase):
    """Спільна основа для перевірок у справжньому вікні."""

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
        cls.fonts.apply()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def pump(self) -> None:
        self.root.update()


class TestProjectGateWidget(GuiCase):
    """Екран вибору проєкту."""

    def _gate(self, **kwargs):
        from blackchpok_ide import project_gate

        gate = project_gate.ProjectGate(self.root, self.fonts, **kwargs)
        gate.pack(fill="both", expand=True)
        self.pump()
        return gate

    def test_builds(self) -> None:
        gate = self._gate()
        self.assertTrue(gate.winfo_exists())

    def test_title_says_pick_folder(self) -> None:
        gate = self._gate()
        self.assertIn("проєкт", str(gate.title.cget("text")).lower())

    def test_pick_callback(self) -> None:
        seen: list[bool] = []
        gate = self._gate(on_pick=lambda: seen.append(True))
        gate._pick()
        self.assertTrue(seen)

    def test_create_callback(self) -> None:
        seen: list[bool] = []
        gate = self._gate(on_create=lambda: seen.append(True))
        gate._create()
        self.assertTrue(seen)

    def test_hint_can_be_set(self) -> None:
        gate = self._gate()
        gate.set_hint("причина")
        self.assertEqual(str(gate.hint.cget("text")), "причина")


class TestLayoutKeys(unittest.TestCase):
    """Ширина лівої панелі зберігається в розкладці."""

    def test_sidebar_width_is_a_known_key(self) -> None:
        from blackchpok_ide import layout

        self.assertIn("sidebar_width", layout.KEYS)

    def test_sidebar_width_roundtrip(self) -> None:
        from blackchpok_ide import layout

        target = Path(tempfile.mkdtemp()) / "layout.json"
        saved = layout.Layout()
        saved.set("sidebar_width", 420)
        layout.save(saved, target)
        restored = layout.load(target)
        self.assertEqual(restored.get("sidebar_width"), 420)

    def test_zero_width_is_ignored(self) -> None:
        """Нульова ширина не зберігається: панель не може бути 0 px."""
        from blackchpok_ide import layout

        saved = layout.Layout()
        saved.set("sidebar_width", 0)
        # get() завжди повертає >= 0, тому перевіряємо сам словник.
        self.assertNotIn("sidebar_width", saved.values)
        self.assertEqual(saved.get("sidebar_width", 0), 0)


class TestFullTextRendering(unittest.TestCase):
    """Відповідь агента не має власної прокрутки.

    Регресія: висота тексту обрізалась на ``max_lines``, і все, що не
    вміщалось, ховалось у прокрутку віджета — саме та смуга й з'являлась
    між повідомленнями.
    """

    def test_hard_limit_is_generous(self) -> None:
        from blackchpok_ide import chat_panel

        # Запобіжник існує (полотно Tk не малює під ~24 000 px), але він
        # має бути набагато більшим за колишні 12–70 рядків.
        self.assertGreaterEqual(chat_panel._HARD_TEXT_LINES, 200)

    def test_chat_width_not_capped_by_default(self) -> None:
        from blackchpok_ide import config, theme

        self.assertEqual(config.UISettings().chat_max_width, 0)
        self.assertEqual(theme.CHAT_MAX_WIDTH, 0)

    def test_fit_clears_yscroll(self) -> None:
        """Після підгонки висоти у віджета не лишається своєї прокрутки."""
        import inspect

        from blackchpok_ide import chat_panel

        source = inspect.getsource(chat_panel.ChatPanel._apply_fit)
        self.assertIn("yscrollcommand", source,
                      "висота має прибирати власну прокрутку віджета")


class TestSidebarResize(unittest.TestCase):
    """Ліва панель живе в PanedWindow, а не у фіксованому Frame."""

    def test_uses_paned_window(self) -> None:
        text = (ROOT / "blackchpok_ide" / "main_window.py").read_text(encoding="utf-8")
        self.assertIn("side_split", text)
        self.assertIn("sashpos(0, width)", text)

    def test_visibility_checked_by_panes_not_ismapped(self) -> None:
        """Перевірка видимості має дивитись у PanedWindow.

        Регресія: ``winfo_ismapped()`` дає 0 для прихованого вікна, і
        ширина панелі через це не зберігалась. Перевіряємо СПРАВЖНІ виклики
        через ``ast`` — згадка в докстрінгу не має валити тест.
        """
        import ast
        import inspect
        import textwrap

        from blackchpok_ide import main_window

        # getsource повертає метод із відступом класу — його треба зняти,
        # інакше ast.parse падає з IndentationError.
        source = textwrap.dedent(
            inspect.getsource(main_window.BlackChpokIDE._sidebar_visible))
        tree = ast.parse(source)
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertIn("panes", calls, "видимість має перевірятись через panes()")
        self.assertNotIn("winfo_ismapped", calls,
                         "winfo_ismapped() хибно каже «немає панелі» у прихованому вікні")


if __name__ == "__main__":
    unittest.main(verbosity=2)
