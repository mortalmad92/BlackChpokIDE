"""Регресії розуміння української мови: відмінки й симетричність команд.

Знайдено живим прогоном ``tools/probe_phrases.py``, не в теорії.

1. **Відмінки.** Правило дерева проєкту шукало підрядок «структура проєкту»,
   а запитують «покажи СТРУКТУРУ проєкту». Українська відмінює
   «структура → структуру → структурі», тож точна словоформа не збігалась і
   роутер мовчав. Симптом для користувача: сказав «покажи структуру
   проєкту» — агент нічого не зробив.

2. **Порожній наказ.** «Перевір синтаксис» без назви файлу не давало
   підказки взагалі: правило вимагало ``path``. Але це очевидна дія.

3. **Асиметрія запуск/зупинка.** «запусти сервер» → ``run``, а «зупини
   сервер» → ``converse`` (розмова). Через це ``needs_tools`` ставало
   ``False``, і агент міг «поговорити» замість того, щоб зупинити
   застосунок.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import intent_engine, task_plan, tool_router  # noqa: E402


def _tools(phrase: str) -> list[str]:
    return [hint.tool for hint in tool_router.confident(phrase)]


class TestProjectTreeCases(TestCase):
    """«Структура/дерево проєкту» в усіх відмінках → ``project_tree``."""

    def test_accusative(self) -> None:
        self.assertIn("project_tree", _tools("покажи структуру проєкту"),
                      "знахідний відмінок «структуру» не розпізнано")

    def test_nominative(self) -> None:
        self.assertIn("project_tree", _tools("структура проєкту"))

    def test_locative(self) -> None:
        self.assertIn("project_tree", _tools("що в структурі проєкту"))

    def test_tree_word(self) -> None:
        self.assertIn("project_tree", _tools("дерево проєкту"))

    def test_english(self) -> None:
        self.assertIn("project_tree", _tools("project tree"))

    def test_about_single_file_is_not_tree(self) -> None:
        """«Структура ФАЙЛУ» — не дерево проєкту."""
        self.assertNotIn("project_tree", _tools("покажи структуру файлу"),
                         "дерево проєкту не потрібне для одного файлу")
        self.assertNotIn("project_tree", _tools("структура файлу main.py"))

    def test_all_files_still_tree(self) -> None:
        """«Структура ВСІХ файлів проєкту» — це все ж дерево."""
        self.assertIn("project_tree", _tools("структура всіх файлів проєкту"))


class TestSyntaxCheckWithoutPath(TestCase):
    """«Перевір синтаксис» без назви файлу — теж дія."""

    def test_without_path(self) -> None:
        self.assertIn("python_check", _tools("перевір синтаксис"),
                      "наказ без назви файлу ігнорувався")

    def test_with_path_passes_file(self) -> None:
        hints = [hint for hint in tool_router.confident("перевір синтаксис main.py")
                 if hint.tool == "python_check"]
        self.assertTrue(hints, "не розпізнано перевірку названого файлу")
        self.assertEqual(hints[0].arguments.get("path"), "main.py")

    def test_noun_form(self) -> None:
        self.assertIn("python_check", _tools("перевірка синтаксису"))

    def test_compiles_question(self) -> None:
        self.assertIn("python_check", _tools("чи компілюється"))


class TestStopIsRunNotTalk(TestCase):
    """Зупинка застосунку — це ДІЯ, а не розмова."""

    STOP_PHRASES = (
        "зупини сервер",
        "зупини програму",
        "зупини застосунок",
        "перезапусти застосунок",
        "припини роботу сервера",
    )

    def test_intent_is_run(self) -> None:
        for phrase in self.STOP_PHRASES:
            with self.subTest(phrase=phrase):
                frame = intent_engine.frame(phrase)
                self.assertEqual(
                    frame.intent_type, intent_engine.RUN,
                    f"«{phrase}» класифіковано як {frame.intent_type!r}")

    def test_needs_tools(self) -> None:
        for phrase in self.STOP_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertTrue(intent_engine.frame(phrase).needs_tools,
                                f"«{phrase}» не вимагає інструментів")

    def test_router_knows_the_action(self) -> None:
        """Роутер і намір мусять збігатися, а не суперечити одне одному."""
        for phrase in ("зупини сервер", "зупини програму"):
            with self.subTest(phrase=phrase):
                self.assertTrue(_tools(phrase),
                                f"роутер не знає дії для «{phrase}»")
                self.assertTrue(intent_engine.frame(phrase).needs_tools,
                                f"намір «{phrase}» каже «розмова»")

    def test_run_stems_cover_stopping(self) -> None:
        """Маркери ``RUN`` у планувальнику містять дієслова зупинки."""
        nodes = dict(task_plan.INTENT_STEMS) if hasattr(task_plan, "INTENT_STEMS") \
            else None
        if nodes is None:
            self.skipTest("INTENT_STEMS недоступні — перевірено через frame()")
        stems = nodes.get(task_plan.RUN, ())
        self.assertTrue(any("зупин" in stem for stem in stems),
                        "у маркерах RUN немає дієслів зупинки")


class TestFolderListingCases(TestCase):
    """«Що в теці/папці/каталозі» — усі три слова й усі відмінки."""

    PHRASES = (
        "що в теці",
        "що в папці",
        "що в каталозі",
        "покажи вміст теки",
        "покажи вміст папки",
        "покажи файли",
        "покажи список файлів",
    )

    def test_listing_recognised(self) -> None:
        for phrase in self.PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn("list_dir", _tools(phrase),
                              f"«{phrase}» не розпізнано як перелік теки")

    def test_named_folder_is_passed(self) -> None:
        """«що в теці src» мусить перелічити САМЕ src, а не корінь."""
        hints = [hint for hint in tool_router.confident("що в теці src")
                 if hint.tool == "list_dir"]
        self.assertTrue(hints, "перелік теки не розпізнано")
        self.assertEqual(hints[0].arguments.get("path"), "src",
                         "теку названо, але шлях не передано")


class TestScreenshotCases(TestCase):
    """«Зніми екран» та інші формулювання — це наказ зняти знімок."""

    def test_capture_phrases(self) -> None:
        for phrase in ("зніми екран", "зроби скріншот", "зроби знімок екрана"):
            with self.subTest(phrase=phrase):
                self.assertIn("project_screenshot", _tools(phrase),
                              f"«{phrase}» не розпізнано як знімок")

    def test_question_about_attached_image_is_not_a_command(self) -> None:
        """«Що на цьому скріншоті?» — питання про картинку, не наказ знімати."""
        self.assertNotIn("project_screenshot", _tools("що на цьому скріншоті"),
                         "питання про прикріплене зображення зіпсувалось")


class TestSmallTalkUnaffected(TestCase):
    """Розмова мусить ЛИШИТИСЬ розмовою — фікс не має її зламати."""

    def test_greeting(self) -> None:
        for phrase in ("привіт", "дякую", "як справи", "доброго ранку"):
            with self.subTest(phrase=phrase):
                frame = intent_engine.frame(phrase)
                self.assertEqual(frame.intent_type, intent_engine.CONVERSE,
                                 f"«{phrase}» перестало бути розмовою")
                self.assertFalse(frame.needs_tools,
                                 f"«{phrase}» почало вимагати інструментів")


if __name__ == "__main__":
    main()
