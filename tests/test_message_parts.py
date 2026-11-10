"""Тести структурованих частин повідомлення.

Перевіряємо те, чого не видно «на око»: код справді стає окремою
частиною, порядок збережено, зворотне складання не губить вміст.

Запуск: python -m unittest tests.test_message_parts -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import message_parts  # noqa: E402

FENCE = "`" * 3

SAMPLE = "\n".join([
    "Готово: змінив `calc.py`.",
    "",
    "# Підсумок",
    "",
    "- додав множення",
    "- перевірив синтаксис",
    "",
    FENCE + "python",
    "def mul(a, b):",
    "    return a * b",
    FENCE,
])


class TestBuildParts(unittest.TestCase):
    """Текст і код розділяються, порядок зберігається."""

    def test_code_is_separate_part(self) -> None:
        parts = message_parts.build_parts(SAMPLE)
        codes = message_parts.code_parts(parts)
        self.assertEqual(len(codes), 1)
        self.assertEqual(codes[0].language, "python")
        self.assertIn("return a * b", codes[0].content)

    def test_text_parts_keep_structure(self) -> None:
        parts = message_parts.build_parts(SAMPLE)
        text = "".join(item.content for item in parts if item.kind == "text")
        self.assertIn("# Підсумок", text)
        self.assertIn("- додав множення", text)

    def test_file_reference_detected(self) -> None:
        parts = message_parts.build_parts(SAMPLE)
        refs = [item for item in parts if item.kind == "file_reference"]
        self.assertTrue(refs)
        self.assertEqual(refs[0].path, "calc.py")

    def test_order_preserved(self) -> None:
        parts = message_parts.build_parts(SAMPLE)
        kinds = [item.kind for item in parts]
        text_at = kinds.index("text")
        code_at = kinds.index("code")
        self.assertLess(text_at, code_at, "код має йти після вступного тексту")

    def test_two_code_blocks(self) -> None:
        text = (FENCE + "python\na = 1\n" + FENCE + "\n\nміж ними\n\n"
                + FENCE + "bash\nls\n" + FENCE)
        parts = message_parts.build_parts(text)
        codes = message_parts.code_parts(parts)
        self.assertEqual([item.language for item in codes], ["python", "bash"])

    def test_has_code(self) -> None:
        self.assertTrue(message_parts.has_code(message_parts.build_parts(SAMPLE)))
        self.assertFalse(message_parts.has_code(
            message_parts.build_parts("просто текст без коду")))

    def test_plain_text_gives_one_part(self) -> None:
        parts = message_parts.build_parts("Тільки текст.")
        self.assertEqual([item.kind for item in parts], ["text"])

    def test_empty_text_gives_no_parts(self) -> None:
        self.assertEqual(message_parts.build_parts(""), [])

    def test_unclosed_fence_is_code(self) -> None:
        """Під час стріму блок ще не закритий — це вже код."""
        parts = message_parts.build_parts(
            "Ось функція:\n\n" + FENCE + "python\ndef add(a, b):")
        codes = message_parts.code_parts(parts)
        self.assertEqual(len(codes), 1)
        self.assertIn("def add", codes[0].content)


class TestRoundTrip(unittest.TestCase):
    """Складання назад не має губити вміст."""

    def test_text_of_keeps_code(self) -> None:
        parts = message_parts.build_parts(SAMPLE)
        restored = message_parts.text_of(parts)
        self.assertIn("return a * b", restored)
        self.assertIn("Підсумок", restored)

    def test_text_of_is_valid_markdown(self) -> None:
        parts = message_parts.build_parts(SAMPLE)
        restored = message_parts.text_of(parts)
        # Складання вдруге має дати ті самі частини.
        again = message_parts.build_parts(restored)
        self.assertEqual([item.kind for item in again],
                         [item.kind for item in parts])

    def test_serialisation_round_trip(self) -> None:
        parts = message_parts.build_parts(SAMPLE)
        data = [item.to_dict() for item in parts]
        restored = [message_parts.MessagePart.from_dict(item) for item in data]
        self.assertTrue(all(item is not None for item in restored))
        self.assertEqual([item.kind for item in restored],
                         [item.kind for item in parts])

    def test_garbage_part_is_rejected(self) -> None:
        self.assertIsNone(message_parts.MessagePart.from_dict("рядок"))
        self.assertIsNone(message_parts.MessagePart.from_dict({"type": "вигадане"}))

    def test_tool_status_part(self) -> None:
        part = message_parts.MessagePart(
            kind="tool_status", tool_name="read_file", status="success",
            summary="прочитав calc.py")
        data = part.to_dict()
        self.assertEqual(data["toolName"], "read_file")
        restored = message_parts.MessagePart.from_dict(data)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.status, "success")


class TestDiff(unittest.TestCase):
    """Diff — дані, а не віджети: можна зберегти й перевірити."""

    def test_changed_line(self) -> None:
        rows = message_parts.parse_diff("a\nb\nc", "a\nB\nc")
        kinds = [row.kind for row in rows]
        self.assertIn("del", kinds)
        self.assertIn("add", kinds)
        self.assertIn("b", [row.text for row in rows if row.kind == "del"])

    def test_identical_text_has_no_changes(self) -> None:
        rows = message_parts.parse_diff("a\nb", "a\nb")
        self.assertEqual(message_parts.diff_summary(rows), "без змін")

    def test_summary_counts(self) -> None:
        rows = message_parts.parse_diff("a\nb\nc\nd", "a\nc\nd\ne")
        summary = message_parts.diff_summary(rows)
        self.assertIn("+", summary)
        self.assertIn("−", summary)

    def test_empty_old_file(self) -> None:
        rows = message_parts.parse_diff("", "new\nfile")
        self.assertEqual(sum(1 for row in rows if row.kind == "add"), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
