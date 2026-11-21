"""Свобода моделі: інструменти на її розсуд, без хардкоду в промпті.

Фіксують вимогу користувача (20.11.2026):

  «Дати максимальної свободи для локальних і хмарних моделей і максимум
   самовирішування, а не жорсткої привязки до хардтексту!»

Що саме було зламано і як перевіряємо:

1. **Режим «Чат» забороняв інструменти.** У системний промпт ішов текст
   «Відповідай текстом, без викликів інструментів… попроси перемкнути
   режим на Агент», а ``use_tools=False`` не давав схем узагалі. На
   «привіт» агент ВИГАДУВАВ опис проєкту замість того, щоб подивитись
   файли.

2. **Порожня відповідь підмінялась готовим рядком** «Привіт! Готовий
   допомогти з кодом…» — користувач бачив його як відповідь моделі.

3. **Питання про власні можливості** («який контекст доступний, чи є
   пам'ять і RAG…») ішло повним циклом з інструментами: 11 кроків і два
   створені файли, хоч користувач нічого не просив робити.

Запуск: python -m unittest tests.test_model_freedom -v
"""

from __future__ import annotations

import inspect
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BLACKCHPOK_NO_SAVE", "1")

from blackchpok_ide import agent as agent_module  # noqa: E402
from blackchpok_ide import evidence, intent_engine, modes  # noqa: E402

#: Питання, яке на скріншоті користувача викликало 11 кроків і два файли.
CAPABILITY_QUESTION = (
    "Який контекст тобі доступний і чи є в тебе функція працювати цілу ніч "
    "або безкінечного чату за допомогою довгострокової памяті та RAG і "
    "самоочишення контексту і вивільнення для наступних задач?")


class TestEveryModeAllowsTools(unittest.TestCase):
    """Модель сама вирішує, чи потрібен інструмент — у будь-якому режимі."""

    def test_no_mode_disables_tools(self) -> None:
        without = [mode.key for mode in modes.MODES if not mode.use_tools]
        self.assertEqual(without, [],
                         "режими без інструментів забороняють моделі працювати: "
                         + ", ".join(without))

    def test_chat_mode_is_not_a_text_only_cage(self) -> None:
        """«Чат» не має промпту-заборони й не обрізає роботу лімітом."""
        chat = modes.get(modes.CHAT)
        self.assertTrue(chat.use_tools, "«Чат» мусить давати інструменти")
        self.assertEqual(
            chat.prompt, "",
            "промпт «Чат» більше не має забороняти інструменти")
        # ── 0 = БЕЗ ЛІМІТУ (21.11.2026) ───────────────────────────────────
        # Раніше тут вимагалось «більше одного кроку» — це була реакція на
        # ліміт 1. Тепер ліміт знято зовсім: будь-яке додатне число знову
        # обрізало б довгу роботу («прибери всі обмеження, щоб агент міг
        # працювати хоч 24/7»).
        self.assertEqual(
            chat.max_steps, 0,
            "режим не має нав'язувати ліміт кроків: 0 означає «без ліміту»")

    def test_chat_mode_has_full_access(self) -> None:
        """Усі режими дають ПОВНИЙ доступ (вимога 21.11.2026).

        Раніше тут перевірялось протилежне: «Чат» лишався лише читанням.
        Користувач попросив прямо: «лиш тільки повний доступ для агента!
        Прибери перемикач!» — бо в режимі читання модель не могла створити
        файл і просила перемкнути режим замість роботи.

        Запобіжник лишився в іншому місці: ``permissions`` усе ще вміє
        відхиляти запис, і тести цього модуля перевіряють саме правило.
        """
        from blackchpok_ide import permissions

        for mode in modes.MODES:
            with self.subTest(mode=mode.key):
                self.assertEqual(
                    mode.permission, permissions.FULL,
                    f"режим «{mode.label}» не має повного доступу")


class TestNoHardcodedGreeting(unittest.TestCase):
    """Готовий текст від нашого імені більше не підставляється."""

    def test_chat_only_has_no_canned_greeting(self) -> None:
        """Готового рядка-відповіді немає — лише честна причина."""
        source = inspect.getsource(agent_module.AgentRunner._chat_only)
        # Перевіряємо ПРИСВОЄННЯ, а не згадку в коментарі: коментар
        # пояснює, ЩО прибрано, і містить той самий рядок як історію.
        self.assertNotIn('text = "Привіт!', source,
                         "знайдено хардкод-привітання замість відповіді моделі")

    def test_empty_answer_is_reported_honestly(self) -> None:
        """Порожня відповідь називає причину, а не вигадує текст."""
        source = inspect.getsource(agent_module.AgentRunner._chat_only)
        self.assertIn("порожню відповідь", source)
        self.assertIn("finish_reason", source)


class TestCapabilityQuestionsDoNotUseTools(unittest.TestCase):
    """Питання про власні можливості не чіпають проєкт."""

    def test_reported_question_needs_no_tools(self) -> None:
        self.assertFalse(
            evidence.needs_tools_for(CAPABILITY_QUESTION),
            "питання про контекст і пам'ять не має запускати інструменти")

    def test_short_memory_question_needs_no_tools(self) -> None:
        for question in ("чи є в тебе пам'ять?",
                         "який у тебе контекст?",
                         "чи вмієш ти працювати цілу ніч?",
                         "чи є RAG?"):
            with self.subTest(question=question):
                self.assertFalse(evidence.needs_tools_for(question), question)

    def test_project_questions_still_need_tools(self) -> None:
        """Запобіжник не має вимкнути інструменти там, де потрібен факт."""
        for question in ("скільки файлів у проєкті?",
                         "чи є в проєкті тести?",
                         "які файли в теці?",
                         "покажи структуру проєкту"):
            with self.subTest(question=question):
                self.assertTrue(evidence.needs_tools_for(question), question)

    def test_orders_about_capabilities_are_not_questions_about_self(self) -> None:
        """«Додай RAG» — це робота, а не питання про власні можливості.

        ``needs_tools_for`` відповідає на інше питання («чи потрібен
        ФАКТ про проєкт»), тож перевіряємо саме новий запобіжник: наказ не
        має вважатись питанням про себе й випадати з робочого шляху.
        """
        for order in ("додай RAG у проєкт",
                      "зроби нічний режим для агента",
                      "виправ пам'ять у модулі",
                      "реалізуй самоочищення контексту"):
            with self.subTest(order=order):
                self.assertFalse(
                    evidence._asks_about_own_capabilities(order.lower()), order)
                # Навіть якщо режим вийде «Чат», це більше не клітка:
                # інструменти в ньому доступні (див. TestEveryModeAllowsTools).
                self.assertTrue(modes.get(modes.auto_mode(order)).use_tools, order)

    def test_greeting_stays_a_conversation(self) -> None:
        frame = intent_engine.frame("привіт")
        self.assertEqual(frame.intent_type, intent_engine.CONVERSE)
        self.assertFalse(evidence.needs_tools_for("привіт"))


class TestComposerHasNoModeCage(unittest.TestCase):
    """Пігулки режиму в композері більше немає."""

    @classmethod
    def setUpClass(cls) -> None:
        import tkinter as tk

        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError as exc:  # pragma: no cover
            raise unittest.SkipTest(f"tkinter недоступний: {exc}") from exc

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def test_no_mode_pill_in_composer(self) -> None:
        import tkinter as tk

        from blackchpok_ide import theme
        from blackchpok_ide.agent_tools import ToolRegistry
        from blackchpok_ide.chat_panel import ChatPanel
        from blackchpok_ide.config import Settings

        host = tk.Frame(self.root)
        host.pack(fill="both", expand=True)
        try:
            panel = ChatPanel(host, theme.Theme(self.root), Settings(),
                              ToolRegistry(ROOT), composer_parent=host)
            panel.pack(fill="both", expand=True)
            self.root.update()
            self.assertIsNone(getattr(panel, "mode_btn", "missing"),
                              "пігулка режиму має бути прибрана")
            self.assertIsNone(getattr(panel, "mode_caption", "missing"),
                              "підпис режиму має бути прибраний")
            # ── Пігулку ТЕКИ теж прибрано (21.11.2026) ────────────────────
            # Раніше тут вимагалось ``assertIsNotNone(panel.workspace_btn)``:
            # «тека — не режим, тому пігулка лишається». Користувач змінив
            # вимогу: «Заборони змінювати привязку до однієї теки. Як вже
            # вибрав одну папку — один чат, то так і працюємо тут, прибери
            # кнопку з чату!». Причина: пігулка дозволяла перемкнути теку
            # посеред розмови, і агент починав писати в інший проєкт.
            self.assertIsNone(getattr(panel, "workspace_btn", "missing"),
                              "пігулка теки має бути прибрана з чату")
            # Стан теки лишається доступним (для підпису й журналу).
            panel.set_workspace("proj", path=str(ROOT))
            self.assertEqual(panel._workspace_name, "proj")
        finally:
            host.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
