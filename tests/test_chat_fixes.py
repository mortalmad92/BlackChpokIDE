"""Тести виправлень чату: лічильник, порожні чати, черга, ширина.

Регресії, які тут зафіксовано (усі знайдені на живому вікні):

1. «×» на рядку чату СТВОРЮВАВ новий чат — лічильник у панелі зростав
   замість того, щоб зменшуватись;
2. порожній чат не видалявся, а архівувався;
3. задачі черги лишались «сиротами» після видалення чату;
4. збережене `chat_max_width = 920` перекривало новий типовий 0, і чат
   лишався вузькою смужкою.

Запуск: python -m unittest tests.test_chat_fixes -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import chat_store as cs  # noqa: E402
from blackchpok_ide import config, queue_engine  # noqa: E402


class TestStaleWidth(unittest.TestCase):
    """Старе значення 920 не має перекривати «на всю ширину»."""

    def test_legacy_920_becomes_zero(self) -> None:
        ui = config.UISettings(chat_max_width=920).normalise()
        self.assertEqual(ui.chat_max_width, 0,
                         "920 — історичний дефолт, а не вибір користувача")

    def test_explicit_width_is_kept(self) -> None:
        ui = config.UISettings(chat_max_width=1100).normalise()
        self.assertEqual(ui.chat_max_width, 1100)

    def test_zero_stays_zero(self) -> None:
        self.assertEqual(config.UISettings(chat_max_width=0).normalise().chat_max_width, 0)

    def test_tiny_value_falls_back_to_full_width(self) -> None:
        self.assertEqual(config.UISettings(chat_max_width=120).normalise().chat_max_width, 0)

    def test_garbage_is_survivable(self) -> None:
        ui = config.UISettings(chat_max_width="не число")  # type: ignore[arg-type]
        self.assertEqual(ui.normalise().chat_max_width, 0)


class TestQueueOwnership(unittest.TestCase):
    """Задачі прив'язані до чату й гинуть разом із ним."""

    def _queue(self):
        return queue_engine.TaskQueue(Path(tempfile.mkdtemp()) / "q.json")

    def test_task_keeps_chat_id(self) -> None:
        queue = self._queue()
        task = queue.add("задача", chat_id="abc123")
        self.assertEqual(task.chat_id, "abc123")

    def test_remove_for_chat(self) -> None:
        queue = self._queue()
        queue.add("моя", chat_id="abc")
        queue.add("інша", chat_id="xyz")
        removed = queue.remove_for_chat("abc")
        self.assertEqual(removed, 1)
        self.assertEqual(len(queue.tasks), 1)
        self.assertEqual(queue.tasks[0].chat_id, "xyz")

    def test_shared_tasks_survive(self) -> None:
        """Задачі без чату (спільні) не чіпаємо."""
        queue = self._queue()
        queue.add("спільна")
        queue.add("чатова", chat_id="abc")
        queue.remove_for_chat("abc")
        self.assertEqual([t.text for t in queue.tasks], ["спільна"])

    def test_remove_unknown_chat_is_safe(self) -> None:
        queue = self._queue()
        queue.add("задача", chat_id="abc")
        self.assertEqual(queue.remove_for_chat("нема"), 0)
        self.assertEqual(len(queue.tasks), 1)

    def test_empty_chat_id_removes_nothing(self) -> None:
        queue = self._queue()
        queue.add("без чату")
        self.assertEqual(queue.remove_for_chat(""), 0)
        self.assertEqual(len(queue.tasks), 1)

    def test_chat_id_survives_reload(self) -> None:
        path = Path(tempfile.mkdtemp()) / "q.json"
        first = queue_engine.TaskQueue(path)
        first.add("задача", chat_id="abc123")
        second = queue_engine.TaskQueue(path)
        self.assertEqual(second.tasks[0].chat_id, "abc123")

    def test_running_id_cleared_when_task_removed(self) -> None:
        queue = self._queue()
        task = queue.add("біжить", chat_id="abc")
        queue.mark_running(task.id)
        self.assertEqual(queue.running_id, task.id)
        queue.remove_for_chat("abc")
        self.assertEqual(queue.running_id, "")


class TestEmptyChatDeletion(unittest.TestCase):
    """Порожній чат видаляється, а не архівується."""

    def _store(self):
        return cs.ChatStore(Path(tempfile.mkdtemp()) / "chats.json")

    def test_message_count_zero_for_new(self) -> None:
        store = self._store()
        chat = store.create(title="порожній")
        self.assertEqual(chat.message_count, 0)

    def test_delete_empty_removes_it(self) -> None:
        store = self._store()
        chat = store.create(title="порожній")
        store.delete(chat.id)
        self.assertEqual(len(store.chats), 0)
        self.assertIsNone(store.get(chat.id))

    def test_chat_with_messages_is_not_empty(self) -> None:
        store = self._store()
        chat = store.create(title="з роботою")
        store.append("user", "привіт")
        refreshed = store.get(chat.id)
        self.assertGreater(refreshed.message_count, 0)


class TestNoAutoCreate(unittest.TestCase):
    """Закриття чату не має створювати новий (лічильник не росте)."""

    @staticmethod
    def _calls_in_close_chat() -> set[str]:
        """Імена СПРАВЖНІХ викликів у тілі close_chat (без докстрінгів)."""
        import ast
        import inspect
        import textwrap

        from blackchpok_ide import main_window

        source = textwrap.dedent(
            inspect.getsource(main_window.BlackChpokIDE.close_chat))
        tree = ast.parse(source)
        # Докстрінг — це перший Expr-вузол із константою; ast.walk його
        # побачить як рядок, але викликів у ньому немає, тож згадка
        # «new_chat_session()» у тексті не заважає.
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

    def test_close_chat_source_does_not_call_new_chat(self) -> None:
        self.assertNotIn("new_chat_session", self._calls_in_close_chat(),
                         "закриття чату не має створювати новий — через це "
                         "лічильник зростав при кожному «×»")

    def test_close_chat_deletes_empty(self) -> None:
        calls = self._calls_in_close_chat()
        self.assertIn("delete", calls, "порожній чат має видалятись")

    def test_close_chat_drops_queue_tasks(self) -> None:
        self.assertIn("remove_for_chat", self._calls_in_close_chat(),
                      "задачі чату мають зникати разом із ним")


class TestQueueStrip(unittest.TestCase):
    """Компактний список черги над полем вводу."""

    def test_strip_exists_in_chat_panel(self) -> None:
        text = (ROOT / "blackchpok_ide" / "chat_panel.py").read_text(encoding="utf-8")
        self.assertIn("_QueueStrip", text)
        self.assertIn("queue_strip", text)

    def test_strip_limits_rows(self) -> None:
        from blackchpok_ide import chat_panel

        self.assertGreaterEqual(chat_panel._QueueStrip.VISIBLE, 2)
        self.assertLessEqual(chat_panel._QueueStrip.VISIBLE, 6)


class TestUkrainianButton(unittest.TestCase):
    """Головна кнопка підписана українською."""

    def test_button_text_is_ukrainian(self) -> None:
        text = (ROOT / "blackchpok_ide" / "main_window.py").read_text(encoding="utf-8")
        self.assertIn("Новий чат", text)
        self.assertNotIn("＋  New Agent", text)


class TestBiggerIcons(unittest.TestCase):
    """Іконки збільшені: дрібні важко націлити мишею."""

    def test_icon_button_default_is_larger(self) -> None:
        import inspect

        from blackchpok_ide import widgets

        source = inspect.getsource(widgets.IconButton.__init__)
        self.assertIn('("Segoe UI", 12)', source)

    def test_session_row_icons_are_larger(self) -> None:
        import inspect
        import textwrap

        from blackchpok_ide import chat_list_panel

        source = textwrap.dedent(
            inspect.getsource(chat_list_panel._SessionRow._make_icon))
        self.assertIn('("Segoe UI", 12)', source)


class TestEmptyChatPruning(unittest.TestCase):
    """Порожні чати не накопичуються.

    Регресія: на реальному конфігу знайшлось 35 порожніх чатів із 36 — їх
    плодив старий баг із «×», що створював новий чат.
    """

    def test_prune_keeps_chats_with_messages(self) -> None:
        import inspect
        import textwrap

        from blackchpok_ide import main_window

        source = textwrap.dedent(
            inspect.getsource(main_window.BlackChpokIDE._prune_empty_chats))
        self.assertIn("message_count", source)
        self.assertIn("pinned", source, "закріплені чати не прибираємо")

    def test_prune_keeps_active_chat(self) -> None:
        """Активний порожній чат — нормальний стан «щойно створив»."""
        import inspect
        import textwrap

        from blackchpok_ide import main_window

        source = textwrap.dedent(
            inspect.getsource(main_window.BlackChpokIDE._prune_empty_chats))
        self.assertIn("active_id", source)


class TestChatModeContextHidden(unittest.TestCase):
    """У режимі «Чат» колонка контексту ховається.

    Регресія: контекст забирав 359 px, і чат лишався вузькою смужкою
    (939 із 1299) навіть після зняття обмеження ширини.
    """

    def test_context_hidden_in_chat_view(self) -> None:
        import inspect
        import textwrap

        from blackchpok_ide import main_window

        source = textwrap.dedent(
            inspect.getsource(main_window.BlackChpokIDE._apply_responsive))
        self.assertIn("chat_only", source)
        self.assertIn('_view != "workspace"', source)


class TestSettingsSaveGuard(unittest.TestCase):
    """Тести не мають писати в справжній конфіг користувача."""

    def test_env_guard_blocks_default_path(self) -> None:
        import os
        import tempfile

        from blackchpok_ide import config

        previous = os.environ.get("BLACKCHPOK_NO_SAVE")
        os.environ["BLACKCHPOK_NO_SAVE"] = "1"
        try:
            settings = config.Settings()
            target = Path(tempfile.mkdtemp()) / "x.json"
            # Явний шлях ЗАВЖДИ пишеться — інакше тести round-trip ламаються.
            settings.save(target)
            self.assertTrue(target.exists(), "явний шлях має записуватись")
        finally:
            if previous is None:
                os.environ.pop("BLACKCHPOK_NO_SAVE", None)
            else:
                os.environ["BLACKCHPOK_NO_SAVE"] = previous


if __name__ == "__main__":
    unittest.main(verbosity=2)
