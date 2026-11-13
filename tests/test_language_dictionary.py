"""Словник русизмів і суржику: виправлення відповідей і розуміння входу.

Навіщо. Локальні моделі навчені переважно на російському тексті, тож в
українській відповіді регулярно з'являються «сейчас», «нужно»,
«получается», «приймати участь». Користувач бачить це як мовну помилку.

Дві функції з різною роллю:

* :func:`blackchpok_ide.language.polish` — для ВІДПОВІДІ агента;
* :func:`blackchpok_ide.language.normalise` — для ВХІДНОЇ фрази, щоб
  російське «сделай» розпізнавалось як наказ створити.

Найважливіше, що перевіряють ці тести: словник НЕ ПСУЄ КОД. Заміряно, що
без захисту `polish('if что == 1:')` давав `'if що == 1:'` — тобто
«допомога» ламала програму.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import intent_engine, language  # noqa: E402


class TestPolishAnswers(TestCase):
    """Відповідь агента мусить стати українською."""

    def test_russian_adverb(self) -> None:
        self.assertEqual(language.polish("Сейчас перевірю"), "Зараз перевірю")

    def test_case_is_preserved(self) -> None:
        """Велика перша літера зберігається."""
        self.assertTrue(language.polish("Сейчас").startswith("З"))

    def test_conjunction_phrase(self) -> None:
        result = language.polish("Не працює, потому что была ошибка")
        self.assertIn("тому що", result)
        self.assertIn("помилка", result)

    def test_surzhyk_participle(self) -> None:
        result = language.polish("Це являється проблемою")
        self.assertIn("є", result)
        self.assertNotIn("являється", result)

    def test_calque_participation(self) -> None:
        result = language.polish("Бери приймати участь у тестуванні")
        self.assertIn("брати участь", result)

    def test_ukrainian_text_untouched(self) -> None:
        """Правильна українська не має змінюватись."""
        clean = "Готово. Функцію додано, синтаксис перевірено."
        self.assertEqual(language.polish(clean), clean)

    def test_empty_is_safe(self) -> None:
        self.assertEqual(language.polish(""), "")
        self.assertEqual(language.polish(None), None)  # type: ignore[arg-type]


class TestReportPhrases(TestCase):
    """Фрази, які модель справді видає у ЗВІТАХ про роботу.

    Заміряно на реальних відповідях: без цих форм лишалось «файл
    является», «функцию добавлено», «синтаксис проверен», «ошибок нет».
    """

    CASES = (
        ("Сейчас проверю файл, потому что была ошибка в коде",
         ("Зараз", "помилка", "у коді")),
        ("Нужно сначала прочитать папку проекта",
         ("Потрібно", "спочатку", "папку", "проєкту")),
        ("Файлы созданы, ошибок нет",
         ("Файли", "створені", "немає")),
        ("Готово: функцию добавлено, синтаксис проверен",
         ("функцію", "додано", "перевірено")),
    )

    def test_report_phrases_are_ukrainian(self) -> None:
        for source, expected in self.CASES:
            with self.subTest(source=source):
                result = language.polish(source)
                for fragment in expected:
                    self.assertIn(fragment, result,
                                  f"немає «{fragment}» у «{result}»")

    def test_no_issues_left_after_polish(self) -> None:
        """Після виправлення не має лишатись відомих русизмів."""
        for source, _expected in self.CASES:
            with self.subTest(source=source):
                left = language.find_issues(language.polish(source))
                self.assertEqual(left, [], f"лишилось: {left}")


class TestApostropheProtection(TestCase):
    """Апостроф перед словом означає ІНШЕ слово — його чіпати не можна.

    Заміряно: «Картинка з'являється в чаті» перетворювалась на
    «Картинка з'є в чаті», бо «являється» (русизм) і «з'являється»
    (цілком українське слово, множина від «являтися») мають спільну
    частину. Межа слова цього не ловила: апостроф не є літерою.

    Це було ПОРУШЕННЯ ТЕКСТУ, а не косметика: словник псував правильне
    українське слово.
    """

    def test_z_yavlyayetsya_is_preserved(self) -> None:
        text = "Картинка з'являється в чаті"
        self.assertEqual(language.polish(text), text,
                         "словник зіпсував «з'являється»")

    def test_typographic_apostrophe(self) -> None:
        text = "Вкладка з\u2019являється раніше"
        self.assertEqual(language.polish(text), text)

    def test_real_russism_still_fixed(self) -> None:
        """Справжнє «являється» без апострофа — виправляємо."""
        self.assertIn("є", language.polish("Це являється проблемою"))
        self.assertNotIn("являється", language.polish("Це являється проблемою"))

    def test_hyphenated_word_preserved(self) -> None:
        text = "будь-який текст"
        self.assertEqual(language.polish(text), text)


class TestNoFalseIssues(TestCase):
    """``find_issues`` не має лякати на українських словах.

    Пари-тотожності (source == target) і літературні слова не є русизмами.
    Заміряно: скан текстів інтерфейсу показував 44 файли з «русизмами»,
    хоч там були «запусти», «команду», «задачу», «папку» — усі українські.
    """

    def test_identity_pairs_not_reported(self) -> None:
        for text in ("запусти тести", "виконай команду", "виріши задачу",
                     "відкрий папку", "покажи папку проєкту"):
            with self.subTest(text=text):
                self.assertEqual(language.find_issues(text), [])

    def test_real_russism_reported(self) -> None:
        self.assertTrue(language.find_issues("сейчас перевірю"))

    def test_ui_texts_have_no_identity_noise(self) -> None:
        """Типовий текст інтерфейсу не має давати жодного сигналу."""
        text = ("Готовий до роботи. Опиши задачу — я прочитаю файли, "
                "внесу зміни й перевірю результат.")
        self.assertEqual(language.find_issues(text), [])


class TestCodeIsProtected(TestCase):
    """НАЙГОЛОВНІШЕ: словник не має чіпати код."""

    def test_python_condition(self) -> None:
        code = "if что == 1:"
        self.assertEqual(language.polish(code), code,
                         "словник змінив умову в коді")

    def test_print_call(self) -> None:
        code = 'print("что")'
        self.assertEqual(language.polish(code), code,
                         "словник змінив рядок усередині коду")

    def test_assignment(self) -> None:
        code = "x = что + 1"
        self.assertEqual(language.polish(code), code)

    def test_function_definition(self) -> None:
        code = "def что():"
        self.assertEqual(language.polish(code), code)

    def test_js_declaration(self) -> None:
        code = "var что = 5;"
        self.assertEqual(language.polish(code), code)

    def test_sql_statement(self) -> None:
        code = "SELECT что FROM t;"
        self.assertEqual(language.polish(code), code)

    def test_fenced_code_block(self) -> None:
        text = "Ось код:\n```python\nif что == 1:\n    pass\n```"
        result = language.polish(text)
        self.assertIn("if что == 1:", result,
                      "блок коду всередині ``` було змінено")

    def test_inline_code(self) -> None:
        text = "Перевір `get_state()` — там ошибка"
        result = language.polish(text)
        self.assertIn("`get_state()`", result)
        self.assertIn("помилка", result, "текст ПОЗА кодом усе ж виправлено")

    def test_file_paths_untouched(self) -> None:
        text = r"Файл C:\AI\site\server.py містить ошибку"
        result = language.polish(text)
        self.assertIn(r"C:\AI\site\server.py", result)
        self.assertIn("помилку", result)

    def test_url_untouched(self) -> None:
        text = "Дивись https://example.com/что?x=1 — там відповідь"
        self.assertIn("https://example.com/что?x=1", language.polish(text))


class TestNormaliseInput(TestCase):
    """Російська фраза користувача мусить розпізнаватись як дія."""

    def test_imperative(self) -> None:
        self.assertEqual(language.normalise("сделай").strip(), "зроби")

    def test_folder_word(self) -> None:
        result = language.normalise("проверь папку проекта")
        self.assertIn("папку", result)
        self.assertIn("проєкту", result)

    def test_yields_intent_create(self) -> None:
        """Головна вимога: «сделай файл app.py» — це СТВОРЕННЯ."""
        frame = intent_engine.frame("сделай файл app.py")
        self.assertEqual(frame.intent_type, intent_engine.CREATE,
                         f"отримали {frame.intent_type!r} замість create")
        self.assertTrue(frame.needs_tools, "російська команда не вимагає дій")

    def test_yields_intent_debug(self) -> None:
        frame = intent_engine.frame("исправь ошибку в calc.py")
        self.assertEqual(frame.intent_type, intent_engine.DEBUG)

    def test_yields_intent_inspect(self) -> None:
        frame = intent_engine.frame("покажи файлы в папке")
        self.assertEqual(frame.intent_type, intent_engine.INSPECT)

    def test_russian_original_kept_for_model(self) -> None:
        """Оригінал фрази лишається — модель має бачити слова користувача."""
        frame = intent_engine.frame("сделай файл app.py")
        self.assertIn("сделай", frame.text,
                      "оригінал втрачено: модель має бачити справжню фразу")


class TestUkrainianUnaffected(TestCase):
    """Українська мова не м��є постраждати від словника."""

    def test_creation_still_works(self) -> None:
        frame = intent_engine.frame("зроби файл app.py")
        self.assertEqual(frame.intent_type, intent_engine.CREATE)

    def test_small_talk_still_converse(self) -> None:
        for phrase in ("привіт", "дякую", "як справи"):
            with self.subTest(phrase=phrase):
                frame = intent_engine.frame(phrase)
                self.assertEqual(frame.intent_type, intent_engine.CONVERSE)
                self.assertFalse(frame.needs_tools)


class TestFindIssues(TestCase):
    """Діагностика: перелік знайдених русизмів."""

    def test_finds_russian_words(self) -> None:
        found = language.find_issues("Сейчас нужно проверить ошибку")
        self.assertIn("Сейчас", found)
        self.assertIn("нужно", found)
        self.assertIn("ошибку", found)

    def test_clean_text_has_no_issues(self) -> None:
        self.assertEqual(language.find_issues("Готово. Функцію додано."), [])

    def test_code_is_not_an_issue(self) -> None:
        self.assertEqual(language.find_issues("if что == 1:"), [])


if __name__ == "__main__":
    main()
