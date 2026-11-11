"""Кожна гілка відповіді однаково чистить службовий текст.

Регресія, яку це ловить: агент має П'ЯТЬ шляхів, якими текст моделі
потрапляє в чат (фінальна відповідь, підсумок після ліміту кроків,
відповідь роутера, офлайн-роутер, перебудова з доказів). Правило
очищення діяло лише на частині з них — і користувач бачив ``{"tool_calls":
[]}`` або обірвану огорожу коду замість відповіді.

Перевіряємо САМЕ ФУНКЦІЮ очищення на всіх формах, які реально
зустрічаються, щоб жодна гілка не могла показати службове.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

#: Три зворотні лапки — щоб не плутати з маркдауном самого файлу.
FENCE = "`" * 3

#: (що каже модель, що МУСИТЬ бути в чаті; ``None`` — байдуже)
CASES: list[tuple[str, str | None]] = [
    ('{"tool_calls": []} Готово!', "Готово"),
    ('{"name": "read_file", "arguments": {"path": "a.py"}}', ""),
    ("<tool_call>read_file</tool_call>Готово.", "Готово"),
    ("<tools>x</tools>Зроблено.", "Зроблено"),
    (FENCE + 'json\n{"name":"list_dir","arguments":{}}\n' + FENCE, ""),
    # Закритий блок коду — це СПРАВЖНІЙ вміст, його чіпати не можна.
    (FENCE + "python\nprint(1)\n" + FENCE, "print(1)"),
    # Обірвана огорожа — сміття без змісту.
    (FENCE + "json", ""),
    ("Готово.\n" + FENCE + "json", "Готово"),
    # Рамки агента (вони для моделі, не для людини).
    ("Мета: зробити калькулятор\nГотово.", "Готово"),
    ("Правило: виклич інструмент\nГотово.", "Готово"),
    ("Обмеження: без бібліотек\nГотово.", "Готово"),
]

#: Маркери, яких у чаті бути НЕ МОЖЕ.
BANNED = ('"tool_calls"', '"arguments"', "<tool_call>", "<tools>",
          "Мета:", "Обмеження:", "Правило:")


class TestEveryAnswerBranchIsClean(unittest.TestCase):
    """Службовий текст не потрапляє в чат за жодних обставин."""

    def test_no_protocol_leaks(self) -> None:
        from blackchpok_ide import response_engine

        for raw, _expected in CASES:
            cleaned = response_engine.clean_for_chat(raw)
            leaks = [marker for marker in BANNED if marker in cleaned]
            self.assertEqual(
                leaks, [],
                f"службовий текст потрапив у чат: {raw!r} -> {cleaned!r}")

    def test_real_content_survives(self) -> None:
        from blackchpok_ide import response_engine

        for raw, expected in CASES:
            if not expected:
                continue
            cleaned = response_engine.clean_for_chat(raw)
            self.assertIn(
                expected, cleaned,
                f"вміст відповіді втрачено: {raw!r} -> {cleaned!r}")

    def test_closed_code_block_is_untouched(self) -> None:
        """Закритий блок коду — вміст, а не сміття."""
        from blackchpok_ide import response_engine

        body = "Ось код:\n" + FENCE + "python\nprint(1)\n" + FENCE
        self.assertIn("print(1)", response_engine.clean_for_chat(body))
        self.assertIn(FENCE, response_engine.clean_for_chat(body))

    def test_unpaired_fence_removed(self) -> None:
        """Обірвана огорожа зникає — інакше в чаті самотнє «```json»."""
        from blackchpok_ide import response_engine

        self.assertNotIn(FENCE, response_engine.clean_for_chat(FENCE + "json"))


if __name__ == "__main__":
    unittest.main()
