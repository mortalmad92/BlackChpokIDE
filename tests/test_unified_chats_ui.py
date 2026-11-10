"""Тести об'єднаного списку чатів і панелі автономного режиму.

Перевіряємо те, що користувач бачить і натискає: один список сесій замість
двох, іконки «архівувати» й «закрити» біля кожного рядка, панель
автономного режиму зі статусом, планом, чергою та журналом.

Запуск: python -m unittest tests.test_unified_chats_ui -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class GuiCase(unittest.TestCase):
    """Спільна основа: приховане кореневе вікно й тема."""

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
        cls.fonts.apply()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def pump(self) -> None:
        self.root.update()

    def store(self):
        from blackchpok_ide.chat_store import ChatStore

        return ChatStore(Path(tempfile.mkdtemp()) / "chats.json")


class TestMergedNavigation(unittest.TestCase):
    """Навігація: «Чати» й «Агенти» — один розділ."""

    def test_single_chat_section(self) -> None:
        from blackchpok_ide import nav_sidebar

        keys = [item[0] for item in nav_sidebar.NAV_ITEMS]
        self.assertIn("chats", keys)
        self.assertNotIn("agents", keys)

    def test_autonomous_belongs_to_chat_not_sidebar(self) -> None:
        """Автономний режим більше не пункт меню — він належить чату.

        Раніше він стояв окремим розділом і виглядав глобальним
        перемикачем. Через це задачі режиму не мали ``chat_id`` і
        лишались «сиротами» після видалення чату.
        """
        from blackchpok_ide import nav_sidebar

        keys = [item[0] for item in nav_sidebar.NAV_ITEMS]
        self.assertNotIn("autonomous", keys)
        sub = {item[0] for item in nav_sidebar.SUB_ITEMS.get("chats", ())}
        self.assertIn("autonomous", sub,
                      "автономний режим має лишитись доступним із розділу «Чати»")

    def test_section_labels_are_ukrainian(self) -> None:
        from blackchpok_ide import nav_sidebar

        for key, icon, label, tip in nav_sidebar.NAV_ITEMS:
            self.assertTrue(label.strip(), key)
            self.assertFalse(any(word in label for word in ("Agents", "Chats")), label)

    def test_main_window_maps_autonomous_panel(self) -> None:
        """Панель автономного режиму доступна, але належить розділу «Чати»."""
        from blackchpok_ide import main_window

        self.assertIn("autonomous", main_window.PANEL_TITLES)
        self.assertEqual(main_window.PANEL_SECTIONS.get("autonomous"), "chats",
                         "автономний режим стосується чату, а не окремого розділу")

    def test_cases_panel_belongs_to_chats_section(self) -> None:
        from blackchpok_ide import main_window

        self.assertEqual(main_window.PANEL_SECTIONS.get("cases"), "chats",
                         "кроки агента мають жити в розділі «Чати»")


class TestSessionRowIcons(GuiCase):
    """Іконки закриття й архівування біля кожного чату."""

    def _row(self, **kwargs):
        from blackchpok_ide import chat_list_panel

        store = self.store()
        chat = store.create(title="Тестова сесія")
        defaults = dict(active=False, fonts=self.fonts,
                        on_open=lambda: None, on_menu=lambda c, e: None)
        defaults.update(kwargs)
        row = chat_list_panel._SessionRow(self.root, chat, **defaults)
        row.pack(fill="x")
        self.pump()
        return row, chat

    def test_archive_icon_exists(self) -> None:
        row, _chat = self._row()
        self.assertTrue(row.archive_btn.winfo_exists())
        self.assertTrue(str(row.archive_btn.cget("text")))
        self.assertIn("<Button-1>", row.archive_btn.bind())

    def test_close_icon_exists(self) -> None:
        row, _chat = self._row()
        self.assertTrue(row.close_btn.winfo_exists())
        self.assertIn("×", str(row.close_btn.cget("text")))
        self.assertIn("<Button-1>", row.close_btn.bind())

    # Приховане вікно (withdraw) не доставляє синтетичні кліки, тому
    # перевіряємо сам обробник, до якого прив'язана іконка: якщо він
    # викликає колбек, натискання теж його викличе.
    def test_close_icon_calls_callback(self) -> None:
        seen: list[bool] = []
        row, _chat = self._row(on_close=lambda: seen.append(True))
        row._close()
        self.pump()
        self.assertEqual(seen, [True])

    def test_archive_icon_calls_callback(self) -> None:
        seen: list[bool] = []
        row, _chat = self._row(on_archive=lambda: seen.append(True))
        row._archive()
        self.pump()
        self.assertEqual(seen, [True])

    def test_broken_callback_does_not_crash(self) -> None:
        def boom() -> None:
            raise RuntimeError("навмисно")

        row, _chat = self._row(on_close=boom, on_archive=boom)
        row._close()
        row._archive()
        self.pump()
        self.assertTrue(row.winfo_exists())

    def test_row_shows_title(self) -> None:
        row, _chat = self._row()
        self.assertIn("Тестова", str(row.title_label.cget("text")))

    def test_compact_row_shortens_long_title(self) -> None:
        from blackchpok_ide import chat_list_panel

        store = self.store()
        chat = store.create(title="Дуже довга назва сесії " * 6)
        row = chat_list_panel._SessionRow(
            self.root, chat, active=False, fonts=self.fonts,
            on_open=lambda: None, on_menu=lambda c, e: None, compact=True)
        row.pack(fill="x")
        self.pump()
        self.assertLessEqual(len(str(row.title_label.cget("text"))),
                             chat_list_panel.COMPACT_TITLE_CHARS)


class TestChatListPanel(GuiCase):
    """Панель списку: заголовок, закриття, компактний режим."""

    def _panel(self, **kwargs):
        from blackchpok_ide import chat_list_panel

        store = kwargs.pop("store", None) or self.store()
        panel = chat_list_panel.ChatListPanel(self.root, self.fonts, store=store, **kwargs)
        panel.pack(fill="both", expand=True)
        self.pump()
        return panel, store

    def test_section_mentions_chats_and_agents(self) -> None:
        panel, _store = self._panel()
        text = str(panel.section_label.cget("text")).upper()
        self.assertIn("ЧАТИ", text)
        self.assertIn("АГЕНТИ", text)

    def test_close_chat_callback_used(self) -> None:
        seen: list[str] = []
        panel, store = self._panel(on_close_chat=lambda cid: seen.append(cid) or True)
        chat = store.create(title="Закрити мене")
        panel.refresh()
        self.pump()
        panel._close_chat(chat)
        self.assertEqual(seen, [chat.id])

    def test_close_falls_back_to_archive(self) -> None:
        """Без оболонки «закрити» не має бути мертвою кнопкою."""
        panel, store = self._panel()
        chat = store.create(title="Без оболонки")
        panel.refresh()
        self.pump()
        panel._close_chat(chat)
        self.pump()
        restored = store.get(chat.id)
        self.assertIsNotNone(restored)
        self.assertTrue(restored.archived, "чат має піти в архів")

    def test_close_callback_returning_false_archives(self) -> None:
        panel, store = self._panel(on_close_chat=lambda cid: False)
        chat = store.create(title="Відмова")
        panel.refresh()
        panel._close_chat(chat)
        self.assertTrue(store.get(chat.id).archived)

    def test_compact_refresh_does_not_crash(self) -> None:
        panel, store = self._panel()
        store.create(title="Сесія")
        panel.set_compact(True)
        self.pump()
        self.assertTrue(panel.compact)
        panel.set_compact(False)
        self.pump()
        self.assertFalse(panel.compact)

    def test_empty_state_text(self) -> None:
        panel, _store = self._panel()
        texts = [str(child.cget("text")) for child in panel.host.winfo_children()
                 if child.winfo_class() == "Label"]
        self.assertTrue(any("Чатів ще немає" in text for text in texts), texts)


class TestAutonomousPanel(GuiCase):
    """Панель автономного режиму."""

    def _panel(self, **kwargs):
        from blackchpok_ide import autonomous, autonomous_panel, queue_engine

        queue = queue_engine.TaskQueue(Path(tempfile.mkdtemp()) / "queue.json")
        engine = autonomous.AutonomousEngine(queue=queue)
        seen: dict[str, list] = {"start": [], "stop": [], "task": [], "project": []}
        panel = autonomous_panel.AutonomousPanel(
            self.root, self.fonts, engine,
            on_start=kwargs.get("on_start", lambda: seen["start"].append(True)),
            on_stop=kwargs.get("on_stop", lambda: seen["stop"].append(True)),
            on_add_task=kwargs.get("on_add_task",
                                   lambda text: seen["task"].append(text)),
            on_pick_project=kwargs.get("on_pick_project",
                                       lambda: seen["project"].append(True)),
        )
        panel.pack(fill="both", expand=True)
        self.pump()
        return panel, engine, queue, seen

    def test_panel_builds(self) -> None:
        panel, _engine, _queue, _seen = self._panel()
        self.assertTrue(panel.winfo_exists())

    def test_panel_paints_on_first_build(self) -> None:
        """Перша перемальовка має намалювати порожні стани.

        Регресія: «підпис порожнього вмісту» дорівнював початковому
        значенню, тож панель уперше малювалась порожньою і план з'являвся
        лише після якоїсь події.
        """
        panel, _engine, _queue, _seen = self._panel()
        self.assertTrue(panel._plan_widgets, "порожній план має показати підказку")
        self.assertTrue(panel._task_widgets, "порожня черга має показати підказку")
        self.assertTrue(panel._log_widgets, "порожній журнал має показати підказку")

    def test_refresh_is_idempotent(self) -> None:
        """Повторний refresh без змін не перемальовує секції."""
        panel, engine, _queue, _seen = self._panel()
        engine.set_plan(["єдиний пункт"])
        panel.refresh()
        before = list(panel._plan_widgets)
        panel.refresh()
        self.assertEqual([id(w) for w in before], [id(w) for w in panel._plan_widgets])

    def test_shows_off_state_initially(self) -> None:
        from blackchpok_ide import autonomous

        panel, _engine, _queue, _seen = self._panel()
        self.assertIn(autonomous.STATE_OFF, str(panel.state_label.cget("text")))

    # Кнопки панелі — це HoverLabel: натискання викликає ``_on_release``.
    # Приховане вікно не доставляє синтетичні події, тому кличемо той самий
    # обробник, який Tk викликає при відпусканні кнопки миші.
    def test_start_button_calls_back(self) -> None:
        panel, _engine, _queue, seen = self._panel()
        self.assertIn("<Button-1>", panel.start_btn.bind())
        panel.start_btn._on_release()
        self.pump()
        self.assertTrue(seen["start"])

    def test_stop_button_calls_back(self) -> None:
        panel, _engine, _queue, seen = self._panel()
        self.assertIn("<Button-1>", panel.stop_btn.bind())
        panel.stop_btn._on_release()
        self.pump()
        self.assertTrue(seen["stop"])

    def test_pick_project_button(self) -> None:
        panel, _engine, _queue, seen = self._panel()
        self.assertIn("<Button-1>", panel.pick_btn.bind())
        panel.pick_btn._on_release()
        self.pump()
        self.assertTrue(seen["project"])

    def test_add_task_from_entry(self) -> None:
        panel, _engine, _queue, seen = self._panel()
        panel.task_entry.insert(0, "виправ баг")
        panel._add_task()
        self.pump()
        self.assertEqual(seen["task"], ["виправ баг"])

    def test_empty_task_is_ignored(self) -> None:
        panel, _engine, _queue, seen = self._panel()
        panel.task_entry.insert(0, "   ")
        panel._add_task()
        self.pump()
        self.assertEqual(seen["task"], [])

    def test_refresh_draws_plan_and_queue(self) -> None:
        from blackchpok_ide import autonomous, queue_engine

        panel, engine, queue, _seen = self._panel()
        engine.set_plan(["Розібрати TODO у main.py", "Додати тести"])
        queue.add("задача агента", origin=queue_engine.ORIGIN_AGENT)
        engine.add_user_task("моя задача")
        panel.refresh()
        self.pump()
        self.assertTrue(panel._plan_widgets)
        self.assertTrue(panel._task_widgets)

    def test_queue_shows_origin_badges(self) -> None:
        from blackchpok_ide import queue_engine

        panel, engine, queue, _seen = self._panel()
        queue.add("агентська", origin=queue_engine.ORIGIN_AGENT)
        engine.add_user_task("людська")
        panel.refresh()
        self.pump()
        texts = self._all_texts(panel.queue_host)
        self.assertTrue(any("від агента" in text for text in texts), texts)
        self.assertTrue(any("від тебе" in text for text in texts), texts)

    def test_log_is_rendered(self) -> None:
        panel, engine, _queue, _seen = self._panel()
        engine.log("щось сталося")
        panel.refresh()
        self.pump()
        texts = self._all_texts(panel.log_host)
        self.assertTrue(any("щось сталося" in text for text in texts), texts)

    def test_clear_log(self) -> None:
        panel, engine, _queue, _seen = self._panel()
        engine.log("рядок")
        panel._clear_log()
        self.assertEqual(engine.log_entries, [])

    def test_drop_pending_task(self) -> None:
        panel, _engine, queue, _seen = self._panel()
        task = queue.add("прибрати мене", origin="агент")
        panel._drop_task(task)
        self.assertNotEqual(queue.get(task.id).status, "очікує")

    def test_state_label_updates(self) -> None:
        from blackchpok_ide import autonomous

        panel, engine, _queue, _seen = self._panel()
        project = Path(tempfile.mkdtemp())
        (project / "tests").mkdir()
        engine.start(project)
        panel.refresh()
        self.pump()
        self.assertIn(autonomous.STATE_RUNNING, str(panel.state_label.cget("text")))

    def test_stopping_state_is_visible(self) -> None:
        from blackchpok_ide import autonomous

        panel, engine, _queue, _seen = self._panel()
        project = Path(tempfile.mkdtemp())
        (project / "tests").mkdir()
        engine.start(project)
        engine.request_stop()
        panel.refresh()
        self.pump()
        self.assertIn(autonomous.STATE_STOPPING, str(panel.state_label.cget("text")))
        self.assertIn("Зупиняю", str(panel.focus_label.cget("text")))

    def _all_texts(self, widget) -> list[str]:
        found: list[str] = []
        stack = list(widget.winfo_children())
        while stack:
            item = stack.pop()
            try:
                found.append(str(item.cget("text")))
            except Exception:  # noqa: BLE001 - не в кожного віджета є text
                pass
            try:
                stack.extend(item.winfo_children())
            except Exception:  # noqa: BLE001
                continue
        return found


if __name__ == "__main__":
    unittest.main(verbosity=2)
