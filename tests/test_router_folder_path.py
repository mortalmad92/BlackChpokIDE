"""Названа тека мусить потрапляти в аргументи інструмента.

ЗАМІРЯНО ЖИВИМ ПРОГОНОМ через вікно IDE:

    запит: «Скажи одним реченням, скільки файлів .py у теці blackchpok_ide»
    [tool_call] list_dir()          <- БЕЗ path
    [tool_result] . — 38 записів    <- перелічено КОРІНЬ проєкту
    відповідь: «Готово. Результат: **list_dir** · . — 38 записів»

Реально в теці `blackchpok_ide` — **127 записів, з них 124 .py**, а в корені
38. Користувач спитав про одну теку, отримав цифри про іншу — і не мав як
це помітити.

Причина подвійна:

1. ``_PATH_RE`` шукає лише імена з розширенням файлу (``*.py``, ``*.json``…),
   тому голе ім'я теки не розпізнавалось узагалі;
2. у правилі підрахунку ``target`` лишався порожнім, і ``list_dir``
   викликався без ``path`` — тобто на корені.

Плюс окрема пастка української мови, яку зловлено тут же: у місцевому
відмінку «к» переходить у «ц» — «тека» → «у теці», «папка» → «у папці».
Перша версія регулярного виразу покривала лише одну з форм, і
«у папці tests» не розпізнавалось.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import tool_router  # noqa: E402


class TestFolderExtraction(unittest.TestCase):
    def test_known_folders_are_extracted(self) -> None:
        cases = {
            "скільки файлів .py у теці blackchpok_ide": "blackchpok_ide",
            "скільки файлів .py у теці blackchpok_ide.": "blackchpok_ide",
            "покажи файли в теці native": "native",
            "що в папці tests": "tests",
            "скільки файлів .py у папці tests?": "tests",
            "вміст каталогу docs": "docs",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(tool_router._folder_in(text), expected)

    def test_trailing_punctuation_does_not_leak(self) -> None:
        """«…у теці blackchpok_ide.» дало ``blackchpok_ide.`` → «Не папка»."""
        for text in ("у теці blackchpok_ide.", "у теці blackchpok_ide!",
                     "у теці blackchpok_ide,"):
            with self.subTest(text=text):
                self.assertEqual(tool_router._folder_in(text), "blackchpok_ide")

    def test_no_folder_mentioned(self) -> None:
        for text in ("покажи файли", "скільки файлів", "привіт",
                     "у теці проєкту", ""):
            with self.subTest(text=text):
                self.assertEqual(tool_router._folder_in(text), "")

    def test_ukrainian_consonant_alternation(self) -> None:
        """«тека»→«теці», «папка»→«папці» — обидві форми мусять працювати."""
        self.assertEqual(tool_router._folder_in("у теці src"), "src")
        self.assertEqual(tool_router._folder_in("у теці src"), "src")
        self.assertEqual(tool_router._folder_in("у папці src"), "src")
        self.assertEqual(tool_router._folder_in("у папці src"), "src")
        self.assertEqual(tool_router._folder_in("в каталозі lib"), "lib")


class TestHintsCarryFolder(unittest.TestCase):
    """Підказка мусить нести теку в ``arguments``, а не порожній словник."""

    def _hint(self, text: str):
        hints = tool_router.confident(text)
        self.assertTrue(hints, f"немає жодної підказки для {text!r}")
        return hints[0]

    def test_counting_question_names_the_folder(self) -> None:
        hint = self._hint("скільки файлів .py у теці blackchpok_ide")
        self.assertEqual(hint.tool, "list_dir")
        self.assertEqual(hint.arguments.get("path"), "blackchpok_ide",
                         "агент знову перелічить корінь замість названої теки")

    def test_listing_question_names_the_folder(self) -> None:
        hints = tool_router.confident("покажи файли в теці native")
        listing = [h for h in hints if h.tool == "list_dir"]
        self.assertTrue(listing)
        self.assertEqual(listing[0].arguments.get("path"), "native")

    def test_no_folder_still_uses_root(self) -> None:
        """Без названої теки — корінь, як і було. Регресії тут бути не має."""
        hints = tool_router.confident("покажи файли")
        listing = [h for h in hints if h.tool == "list_dir"]
        self.assertTrue(listing)
        self.assertEqual(listing[0].arguments.get("path"), ".")

    def test_bare_file_path_still_wins_when_no_folder(self) -> None:
        """«скільки рядків у agent.py» — це файл, і його не треба губити."""
        hint = self._hint("перевір синтаксис agent.py")
        self.assertEqual(hint.tool, "python_check")
        self.assertEqual(hint.arguments.get("path"), "agent.py")


class TestListDirRejectsBadPath(unittest.TestCase):
    """Хибна тека мусить давати честну помилку, а не тихий корінь."""

    def test_nonexistent_folder_fails_loudly(self) -> None:
        from blackchpok_ide import agent_tools

        registry = agent_tools.ToolRegistry(ROOT)
        outcome = registry.call("list_dir", {"path": "неіснуюча_тека_xyz"})
        self.assertFalse(outcome.ok, "хибна тека не має вважатись успіхом")


class TestRealFolderHasExpectedCount(unittest.TestCase):
    """Наскрізна перевірка на СПРАВЖНІЙ теці цієї машини."""

    def test_blackchpok_ide_folder_differs_from_root(self) -> None:
        from blackchpok_ide import agent_tools

        folder = ROOT / "blackchpok_ide"
        if not folder.is_dir():
            self.skipTest("теки blackchpok_ide немає")
        registry = agent_tools.ToolRegistry(ROOT)
        inside = registry.call("list_dir", {"path": "blackchpok_ide"})
        root = registry.call("list_dir", {})
        self.assertTrue(inside.ok, inside.output)
        self.assertTrue(root.ok, root.output)
        self.assertNotEqual(
            str(inside.output), str(root.output),
            "list_dir(path=blackchpok_ide) знову показав корінь — тека губиться")
        self.assertIn("blackchpok_ide", str(inside.output)[:80])


if __name__ == "__main__":
    unittest.main()
