"""Чат як власник: сесія, її задачі й режими належать одній розмові.

Три скарги користувача, які ці тести фіксують:

1. **«Новий чат» одразу питає одну теку.** Запис з'являється вже з цією
   текою. Чернетка без теки лишається лише для першого запуску без чатів.
2. **Задачі лишались «сиротами».** Три задачі висіли в панелі
   «Автоматизації» після видалення чату, бо додавались без ``chat_id``.
3. **Автономний режим і автоматизації стояли в лівому меню** й виглядали
   глобальними перемикачами, хоч стосуються конкретної сесії й теки.

Запуск: python -m unittest tests.test_chat_ownership -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _store(tmp: Path):
    from blackchpok_ide import chat_store

    return chat_store.ChatStore(path=tmp / "chats.json")


class TestEmptyChatNotCreated(unittest.TestCase):
    """«Новий чат» одразу питає теку і створює запис уже з нею."""

    @staticmethod
    def _source(name: str) -> str:
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        return inspect.getsource(getattr(BlackChpokIDE, name))

    @staticmethod
    def _calls_in(source: str) -> set[str]:
        import ast
        import textwrap

        tree = ast.parse(textwrap.dedent(source))
        names: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute):
                names.add(func.attr)
            elif isinstance(func, ast.Name):
                names.add(func.id)
        return names

    def test_new_chat_session_asks_folder_then_creates(self) -> None:
        """Новий чат не з'являється, доки людина не вкаже одну теку."""
        calls = self._calls_in(self._source("new_chat_session"))
        self.assertIn("askdirectory", calls,
                      "новий чат має одразу питати робочу теку")
        self.assertIn("_start_chat_in", calls)
        started = self._calls_in(self._source("_start_chat_in"))
        self.assertIn("create", started,
                      "запис чату створюється разом із вибраною текою")
        self.assertIn("_apply_workspace", started)

    def test_new_chat_keeps_previous_context(self) -> None:
        source = self._source("_start_chat_in")
        self.assertIn("_save_chat_context", source)

    def test_remember_message_creates_on_first_message(self) -> None:
        calls = self._calls_in(self._source("_remember_message"))
        self.assertIn("_ensure_pending_chat", calls,
                      "запис має народжуватись на перше повідомлення")

    def test_ensure_pending_chat_creates_once(self) -> None:
        calls = self._calls_in(self._source("_ensure_pending_chat"))
        self.assertIn("create", calls)
        self.assertIn("active", calls, "наявний чат не має дублюватись")

    def test_pending_flag_resets_on_open_chat(self) -> None:
        source = self._source("open_chat")
        self.assertIn("_pending_chat", source,
                      "відкриття збереженого чату має знімати «чернетку»")

    def test_real_store_behaviour(self) -> None:
        """Сховище не отримує запису, поки його не створять явно."""
        import tempfile

        tmp = Path(tempfile.mkdtemp())
        try:
            store = _store(tmp)
            self.assertEqual(len(store.chats), 0)
            store.set_active("")
            self.assertIsNone(store.active())
            created = store.create(workspace=str(tmp))
            self.assertEqual(len(store.chats), 1)
            self.assertIs(store.active(), created)
        finally:
            for item in tmp.iterdir():
                item.unlink()
            tmp.rmdir()


class TestTasksBelongToChat(unittest.TestCase):
    """Задачі черги мають власника — і гинуть разом із ним."""

    def setUp(self) -> None:
        import tempfile

        from blackchpok_ide import queue_engine

        self.engine = queue_engine
        # Черга без шляху підхоплює задачі з диска, тож тести бачили б
        # роботу інших прогонів. Кожен тест має власне тимчасове сховище.
        self._tmp = Path(tempfile.mkdtemp())
        self.queue = queue_engine.TaskQueue(path=self._tmp / "queue.json")

    def tearDown(self) -> None:
        for item in self._tmp.iterdir():
            try:
                item.unlink()
            except OSError:
                pass
        try:
            self._tmp.rmdir()
        except OSError:
            pass

    def test_add_stores_chat_id(self) -> None:
        task = self.queue.add("зроби щось", chat_id="chat-1")
        self.assertEqual(task.chat_id, "chat-1")

    def test_add_without_chat_id_is_allowed(self) -> None:
        """Сумісність: старі виклики без власника не ламаються."""
        task = self.queue.add("зроби щось")
        self.assertEqual(task.chat_id, "")

    def test_adopt_orphans_assigns_owner(self) -> None:
        self.queue.add("сирота 1")
        self.queue.add("сирота 2")
        adopted = self.queue.adopt_orphans("chat-9")
        self.assertEqual(adopted, 2)
        self.assertTrue(all(t.chat_id == "chat-9" for t in self.queue.tasks))

    def test_adopt_orphans_keeps_existing_owner(self) -> None:
        self.queue.add("моя", chat_id="chat-A")
        self.queue.add("сирота")
        self.assertEqual(self.queue.adopt_orphans("chat-B"), 1)
        owners = {t.text: t.chat_id for t in self.queue.tasks}
        self.assertEqual(owners["моя"], "chat-A", "чужий чат не перепризначається")
        self.assertEqual(owners["сирота"], "chat-B")

    def test_adopt_orphans_empty_chat_is_noop(self) -> None:
        self.queue.add("сирота")
        self.assertEqual(self.queue.adopt_orphans(""), 0)
        self.assertEqual(self.queue.tasks[0].chat_id, "")

    def test_remove_for_chat_removes_only_its_tasks(self) -> None:
        self.queue.add("A", chat_id="chat-A")
        self.queue.add("B", chat_id="chat-B")
        self.assertEqual(self.queue.remove_for_chat("chat-A"), 1)
        self.assertEqual([t.text for t in self.queue.tasks], ["B"])

    def test_next_pending_respects_chat(self) -> None:
        """Черга не віддає задачу чужого чату — інакше вона виконалась би
        в іншому проєкті після зміни теки."""
        self.queue.add("A", chat_id="chat-A")
        self.queue.add("B", chat_id="chat-B")
        self.assertEqual(self.queue.next_pending(chat_id="chat-B").text, "B")
        self.assertEqual(self.queue.next_pending(chat_id="chat-A").text, "A")

    def test_next_pending_without_chat_sees_all(self) -> None:
        """Порожній chat_id — стара поведінка, без обмежень."""
        self.queue.add("A", chat_id="chat-A")
        self.assertIsNotNone(self.queue.next_pending())

    def test_next_pending_skips_orphans_for_a_specific_chat(self) -> None:
        """Задачу без власника НЕ віддаємо чату, який її не створював.

        Раніше тут перевірялось протилежне («сирота доступна будь-якому
        чату»), і саме це було дефектом: ``fits()`` повертала True для
        ``not task.chat_id``, тож чат Б брав задачу чату А (перевірено
        наживо). Сироти існують лише як спадок старих версій — їх
        прибирає :meth:`adopt_orphans`, а не «виконує перший-ліпший чат».
        """
        self.queue.add("сирота")
        self.assertIsNone(self.queue.next_pending(chat_id="chat-B"),
                          "сирота не має діставатись чужому чату")
        # Без обмеження (порожній chat_id) — як і раніше, бачимо все.
        self.assertEqual(self.queue.next_pending().text, "сирота")

    def test_adopted_orphan_then_belongs_to_chat(self) -> None:
        """Після ``adopt_orphans`` задача стає своєю й доступна цьому чату."""
        self.queue.add("сирота")
        self.assertEqual(self.queue.adopt_orphans("chat-B"), 1)
        task = self.queue.next_pending(chat_id="chat-B")
        self.assertIsNotNone(task)
        self.assertEqual(task.text, "сирота")

    def test_extend_passes_chat_id(self) -> None:
        self.queue.extend(["крок 1", "крок 2"], chat_id="chat-C")
        self.assertTrue(all(t.chat_id == "chat-C" for t in self.queue.tasks))


class TestAutonomousBelongsToChat(unittest.TestCase):
    """Автономний режим ставить задачі з власником."""

    def test_engine_has_chat_id(self) -> None:
        from blackchpok_ide import autonomous

        engine = autonomous.AutonomousEngine()
        self.assertEqual(engine.chat_id, "")

    def test_seed_and_user_tasks_carry_chat_id(self) -> None:
        import inspect

        from blackchpok_ide import autonomous

        for name in ("add_user_task", "seed"):
            source = inspect.getsource(getattr(autonomous.AutonomousEngine, name))
            self.assertIn("chat_id=self.chat_id", source,
                          f"{name} має передавати власника задачі")

    def test_start_assigns_owner_in_window(self) -> None:
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE.start_autonomous)
        self.assertIn("chat_id", source,
                      "старт режиму має прив'язати його до поточного чату")

    def test_project_switch_asks_confirmation(self) -> None:
        """Зміна теки під автономним режимом має питати підтвердження."""
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE.set_workspace)
        self.assertIn("_confirm_autonomous_project_switch", source,
                      "агент не має мовчки перейти на чужий проєкт")

    def test_other_project_detection(self) -> None:
        from types import SimpleNamespace

        from blackchpok_ide.main_window import BlackChpokIDE

        engine = SimpleNamespace(active=True, project=Path(ROOT))
        host = SimpleNamespace(autonomous_engine=engine)
        check = BlackChpokIDE._autonomous_other_project.__get__(host)
        self.assertFalse(check(ROOT), "той самий проєкт — не «інший»")
        self.assertTrue(check(Path.home()), "інша тека — привід спитати")

    def test_inactive_engine_never_blocks(self) -> None:
        from types import SimpleNamespace

        from blackchpok_ide.main_window import BlackChpokIDE

        engine = SimpleNamespace(active=False, project=Path(ROOT))
        host = SimpleNamespace(autonomous_engine=engine)
        check = BlackChpokIDE._autonomous_other_project.__get__(host)
        self.assertFalse(check(Path.home()))


class TestSidebarNoLongerHasChatModes(unittest.TestCase):
    """Режими чату прибрано з лівого меню."""

    def test_nav_items_exclude_chat_modes(self) -> None:
        from blackchpok_ide import nav_sidebar

        keys = {item[0] for item in nav_sidebar.NAV_ITEMS}
        self.assertNotIn("autonomous", keys)
        self.assertNotIn("automations", keys)

    def test_chat_modes_still_reachable(self) -> None:
        from blackchpok_ide import nav_sidebar

        sub = {item[0] for item in nav_sidebar.SUB_ITEMS.get("chats", ())}
        self.assertIn("autonomous", sub)
        self.assertIn("queue", sub)
        self.assertIn("skills", sub)

    def test_panels_map_to_chats_section(self) -> None:
        from blackchpok_ide import main_window

        for panel in ("autonomous", "queue", "skills", "cases"):
            self.assertEqual(main_window.PANEL_SECTIONS.get(panel), "chats",
                             f"панель «{panel}» стосується чату")

    def test_header_has_chat_mode_button(self) -> None:
        import inspect

        from blackchpok_ide import session_header

        source = inspect.getsource(session_header.SessionHeader._build)
        self.assertIn("chat_mode_label", source)
        self.assertIn("on_chat_mode", inspect.getsource(session_header.SessionHeader))


class TestChatModeMenu(unittest.TestCase):
    """Спливне меню режимів чату показує свій контекст."""

    @classmethod
    def setUpClass(cls) -> None:
        import tkinter as tk

        from blackchpok_ide import theme

        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError as exc:  # pragma: no cover - без дисплея
            raise unittest.SkipTest(f"tkinter недоступний: {exc}") from exc
        cls.fonts = theme.Theme(cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def _menu(self, **kwargs):
        from blackchpok_ide import chat_mode_menu

        seen: dict[str, int] = {"auto": 0, "autom": 0, "project": 0}
        menu = chat_mode_menu.ChatModeMenu(
            self.root, self.fonts,
            chat_title=kwargs.pop("chat_title", "Рефакторинг чату"),
            project=kwargs.pop("project", "blackchpock_ai"),
            on_autonomous=lambda: seen.__setitem__("auto", seen["auto"] + 1),
            on_automations=lambda: seen.__setitem__("autom", seen["autom"] + 1),
            on_pick_project=lambda: seen.__setitem__("project", seen["project"] + 1),
            **kwargs)
        self.root.update()
        return menu, seen

    def test_builds_with_context(self) -> None:
        menu, _ = self._menu()
        try:
            self.assertTrue(menu.winfo_exists())
            self.assertEqual(menu.chat_title, "Рефакторинг чату")
            self.assertEqual(menu.project, "blackchpock_ai")
        finally:
            menu.destroy()

    def test_rows_call_callbacks(self) -> None:
        menu, seen = self._menu()
        try:
            menu._autonomous()
            menu._automations()
            menu._pick_project()
            self.assertEqual(seen, {"auto": 1, "autom": 1, "project": 1})
        finally:
            menu.destroy()

    def test_autonomous_note_reflects_state(self) -> None:
        menu, _ = self._menu(autonomous_on=False)
        try:
            self.assertIn("вимкнено", menu._autonomous_note())
        finally:
            menu.destroy()
        menu, _ = self._menu(autonomous_on=True, autonomous_state="працює")
        try:
            self.assertNotIn("вимкнено", menu._autonomous_note())
        finally:
            menu.destroy()

    def test_queue_note_counts_tasks(self) -> None:
        menu, _ = self._menu(queue_count=0)
        try:
            self.assertIn("порожня", menu._automations_note())
        finally:
            menu.destroy()
        menu, _ = self._menu(queue_count=3)
        try:
            self.assertIn("3", menu._automations_note())
        finally:
            menu.destroy()

    def test_project_note_when_missing(self) -> None:
        menu, _ = self._menu(project="")
        try:
            self.assertIn("не обрано", menu._project_text())
        finally:
            menu.destroy()

    def test_show_and_hide(self) -> None:
        menu, _ = self._menu()
        try:
            menu.show_at(self.root)
            menu.hide()
            menu.hide()  # повторно — без винятку
        finally:
            menu.destroy()


class TestHeaderShowsChatState(unittest.TestCase):
    """Кнопка режиму чату показує автономний режим і кількість задач."""

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

    def _header(self):
        from blackchpok_ide import session_header

        header = session_header.SessionHeader(self.root, self.fonts)
        header.pack()
        self.root.update()
        return header

    def test_idle_text(self) -> None:
        header = self._header()
        try:
            header.set_chat_mode(autonomous=False, queue_count=0)
            self.assertIn("Чат", str(header.chat_mode_label.cget("text")))
        finally:
            header.destroy()

    def test_autonomous_is_visible(self) -> None:
        header = self._header()
        try:
            header.set_chat_mode(autonomous=True, queue_count=0)
            self.assertIn("автономно", str(header.chat_mode_label.cget("text")))
        finally:
            header.destroy()

    def test_queue_count_is_visible(self) -> None:
        header = self._header()
        try:
            header.set_chat_mode(autonomous=False, queue_count=4)
            self.assertIn("4", str(header.chat_mode_label.cget("text")))
        finally:
            header.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
