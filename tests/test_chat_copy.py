"""Копіювання в чаті: окремо запит, окремо відповідь, окремо код.

Скарга користувача (21.11.2026): «знайшов ще одну проблему з копіюванням в
чаті — потрібне окреме копіювання для запиту користувача і окреме для повної
відповіді агента і окремо для коду».

Що було не так. Пункт «Копіювати всю відповідь» у меню коду брав
``transcript.get()`` — тобто ВЕСЬ чат разом із запитами людини. Натиснувши
«копіювати відповідь», користувач отримував усю розмову.

Тести перевіряють саме межу: кожен пункт копіює РІВНО те, що названо.

Запуск: python -m unittest tests.test_chat_copy -v
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _menu_block(source: str) -> str:
    """Тіло ``_code_menu`` БЕЗ докстрінга й коментарів.

    Чому без них: у докстрінгу навмисно описано старий дефект («копіювало
    всю відповідь»), і перевірка за текстом чіплялась за цю згадку замість
    справжнього коду.
    """
    marker = "def _code_menu"
    start = source.find(marker)
    if start < 0:
        return ""
    end = source.find("def _code_index_at", start)
    body = source[start:end if end > start else start + 4000]
    # Прибираємо докстрінг (потрійні лапки) і рядкові коментарі.
    clean = re.sub(r'"""[\s\S]*?"""', "", body, count=1)
    lines = [line for line in clean.splitlines()
             if not line.strip().startswith("#")]
    return "\n".join(lines)


class TestMenuTargets(unittest.TestCase):
    """Кожен пункт меню копіює СВОЄ джерело."""

    def setUp(self) -> None:
        import inspect

        from blackchpok_ide import chat_panel

        self.source = inspect.getsource(chat_panel.ChatPanel._code_menu)
        self.block = _menu_block(self.source)

    def test_menu_exists(self) -> None:
        self.assertTrue(self.block.strip(), "меню коду не знайдено")
        self.assertIn("items.append", self.block)

    def test_code_item_copies_the_code_block(self) -> None:
        self.assertIn("Копіювати код", self.block)
        self.assertIn("code", self.block,
                      "пункт коду має брати САМЕ блок під курсором")

    def test_this_answer_copies_card_text(self) -> None:
        """«Копіювати цю відповідь» бере текст картки, а не весь чат."""
        self.assertIn("Копіювати цю відповідь", self.block)
        self.assertIn("own", self.block,
                      "пункт відповіді має брати текст САМЕ цієї картки")
        self.assertIn("card", self.block)

    def test_whole_chat_is_a_separate_item(self) -> None:
        """Уся розмова — окремий пункт, і він єдиний чіпає ``transcript``."""
        self.assertIn("Копіювати всю розмову", self.block)
        self.assertEqual(self.block.count("transcript"), 1,
                         "``transcript`` має бути лише в пункті «вся розмова»")

    def test_old_misleading_item_is_gone(self) -> None:
        """Старого пункту «Копіювати всю відповідь» більше немає.

        Саме він копіював увесь чат під назвою «вся відповідь».
        """
        self.assertNotIn("Копіювати всю відповідь", self.block)


class TestCardKeepsText(unittest.TestCase):
    """Картка пам'ятає текст, інакше «цю відповідь» скопіювати нізвідки."""

    def test_track_text_accepts_text(self) -> None:
        import inspect

        from blackchpok_ide import chat_panel

        source = inspect.getsource(chat_panel.ChatPanel._track_text)
        self.assertIn("text", source)
        self.assertIn("card.text", source)

    def test_body_text_passes_text(self) -> None:
        import inspect

        from blackchpok_ide import chat_panel

        source = inspect.getsource(chat_panel.ChatPanel._body_text)
        self.assertIn("text=text", source,
                      "запит користувача не передає свій текст у картку")

    def test_markdown_passes_text(self) -> None:
        import inspect

        from blackchpok_ide import chat_panel

        source = inspect.getsource(chat_panel.ChatPanel._render_markdown)
        self.assertIn("text=text", source,
                      "відповідь не передає свій текст у картку")


class TestSeparateButtonsExist(unittest.TestCase):
    """Кнопки на самих картках теж окремі (запит ≠ відповідь)."""

    def test_user_card_button_copies_request(self) -> None:
        import inspect

        from blackchpok_ide import chat_panel

        # Запит людини малює ``_show_user_card`` (не ``_add_user``): картка
        # створюється там, і саме там ставиться кнопка копіювання.
        source = inspect.getsource(chat_panel.ChatPanel)
        start = source.find('card.add_action("⧉"')
        self.assertGreater(start, 0, "кнопки копіювання немає")
        window = source[max(0, start - 800):start + 300]
        self.assertIn("Копіювати запит", window,
                      "кнопка копіювання власного запиту відсутня")

    def test_agent_card_button_copies_answer(self) -> None:
        import inspect

        from blackchpok_ide import chat_panel

        source = inspect.getsource(chat_panel.ChatPanel._add_assistant)
        self.assertIn("Копіювати відповідь", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
