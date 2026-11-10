"""Регресії на три скарги користувача після мого попереднього кола.

1. «Навіщо це дублювання?» — я додав у шапку ДРУГИЙ рядок меню, хоча у
   вікна вже є нативне ``tk.Menu``. Рядок прибрано.
2. «З архіву не видаляються чати!» — перевіряємо весь ланцюг у
   справжньому сховищі: архів → «×» → видалення → перечитування з диска.
3. «На звичайне ПРИВІТ він вивів багато всього не потрібного» — вітання
   не має запускати інструменти, план і службові блоки.

Запуск: python -m unittest tests.test_no_duplication_and_greetings -v
"""

from __future__ import annotations

import inspect
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import chat_store, intent_engine, planning  # noqa: E402


class TestNoDuplicateMenu(unittest.TestCase):
    """Другого рядка меню в шапці немає: воно вже є в вікні."""

    def test_header_has_no_menu_row(self) -> None:
        source = (ROOT / "blackchpok_ide" / "header_bar.py").read_text(
            encoding="utf-8")
        self.assertNotIn("menu_row", source,
                         "рядок меню в шапці дублював нативне меню вікна")

    def test_header_is_single_row(self) -> None:
        from blackchpok_ide import header_bar

        self.assertLessEqual(header_bar.HEADER_HEIGHT, 52,
                             "шапка не має бути на два рядки")

    def test_native_menu_still_exists(self) -> None:
        """Прибираючи дубль, не можна прибрати справжнє меню."""
        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE._build_menu)
        for label in ("Файл", "Правка", "Вигляд", "Агент", "Git", "Довідка"):
            self.assertIn(f'label="{label}"', source,
                          f"меню «{label}» зникло разом з дублем")

    def test_header_still_has_icon_groups(self) -> None:
        """Іконки лишились: прибрано лише текстовий дубль."""
        from blackchpok_ide import header_bar

        source = (ROOT / "blackchpok_ide" / "header_bar.py").read_text(
            encoding="utf-8")
        self.assertIn('"run.browser"', source)
        self.assertIn('"file.save"', source)
        self.assertGreaterEqual(header_bar.ICON_SIZE, 14)


class TestArchiveDeletion(unittest.TestCase):
    """Чат з архіву справді видаляється — і не повертається."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.path = self.folder / "chats.json"
        self.store = chat_store.ChatStore(self.path)

    def test_delete_from_archive(self) -> None:
        chat = self.store.create(title="Архівний")
        self.store.append("user", "текст", chat_id=chat.id)
        self.store.archive(chat.id, True)
        self.assertEqual(len(self.store.visible(archived=True)), 1)

        self.assertTrue(self.store.delete(chat.id))
        self.assertEqual(self.store.visible(archived=True), [])
        self.assertIsNone(self.store.get(chat.id))

    def test_deletion_survives_reload(self) -> None:
        """Після перезапуску видалений чат не має повертатись."""
        chat = self.store.create(title="Архівний")
        self.store.archive(chat.id, True)
        self.store.delete(chat.id)
        self.store.save()

        reread = chat_store.ChatStore(self.path)
        self.assertEqual(reread.visible(archived=True), [],
                         "видалений чат повернувся після перечитування")

    def test_active_chat_untouched(self) -> None:
        active = self.store.create(title="Робочий")
        arch = self.store.create(title="Архівний")
        self.store.archive(arch.id, True)
        self.store.delete(arch.id)
        self.assertIsNotNone(self.store.get(active.id))

    def test_delete_all_archived_only(self) -> None:
        active = self.store.create(title="Робочий")
        arch = self.store.create(title="Архівний")
        self.store.archive(arch.id, True)
        removed = self.store.delete_all(archived=True)
        self.assertEqual(removed, 1)
        self.assertEqual(len(self.store.chats), 1)
        self.assertEqual(self.store.chats[0].id, active.id)

    def test_close_in_archive_tab_deletes(self) -> None:
        """«×» у вкладці архіву викликає саме видалення."""
        source = (ROOT / "blackchpok_ide" / "chat_list_panel.py").read_text(
            encoding="utf-8")
        block = source[source.index("def _close_chat"):]
        block = block[:block.index("def update_row_status")]
        self.assertIn("archived", block)
        self.assertIn("self._delete(chat)", block,
                      "для архівного рядка «×» мусить видаляти, а не архівувати")


class TestGreetingIsShort(unittest.TestCase):
    """Вітання не запускає інструментів і не будує план."""

    def test_greetings_are_conversation(self) -> None:
        for phrase in ("Привіт", "привіт", "Привіт!", "Добрий день",
                       "Дякую", "Як справи?"):
            with self.subTest(phrase=phrase):
                frame = intent_engine.frame(phrase)
                self.assertEqual(frame.intent_type, intent_engine.CONVERSE)
                self.assertFalse(frame.actionable)
                self.assertFalse(frame.needs_tools)

    def test_greeting_gets_no_plan(self) -> None:
        for phrase in ("Привіт", "Дякую"):
            with self.subTest(phrase=phrase):
                self.assertEqual(planning.build_plan(intent_engine.frame(phrase)), [])
                self.assertFalse(planning.should_plan(intent_engine.frame(phrase)))

    def test_greeting_needs_no_clarification(self) -> None:
        self.assertFalse(
            intent_engine.needs_clarification(intent_engine.frame("Привіт")))

    def test_agent_has_chat_only_path(self) -> None:
        from blackchpok_ide.agent import AgentRunner

        self.assertTrue(hasattr(AgentRunner, "_is_small_talk"))
        self.assertTrue(hasattr(AgentRunner, "_chat_only"))
        source = inspect.getsource(AgentRunner._chat_only)
        self.assertIn("tools=None", source,
                      "у розмові схеми інструментів не передаються")

    def test_small_talk_detection(self) -> None:
        from blackchpok_ide.agent import AgentRunner
        from blackchpok_ide.config import AgentSettings

        runner = AgentRunner.__new__(AgentRunner)
        runner.intent = intent_engine.frame("Привіт")
        runner.state = None
        settings = AgentSettings()
        runner.agent_settings = settings
        self.assertTrue(runner._is_small_talk())

        # Доручення — не розмова.
        runner.intent = intent_engine.frame("не працює кнопка, виправ")
        self.assertFalse(runner._is_small_talk())

    def test_promise_check_skipped_for_chat(self) -> None:
        """«Я можу допомогти» на вітання не вважається обіцянкою дії."""
        from blackchpok_ide.agent import AgentRunner

        runner = AgentRunner.__new__(AgentRunner)
        runner.intent = intent_engine.frame("Привіт")
        self.assertFalse(runner._expects_action())

        runner.intent = intent_engine.frame("створи калькулятор")
        self.assertTrue(runner._expects_action())


if __name__ == "__main__":
    unittest.main(verbosity=2)
