"""Тести залізного правила: інтернет → знання → пам'ять → інші чати.

Що охороняється:

* знання з результату пошуку/сторінки справді стає фактами в пам'яті, а не
  зникає разом із ходом;
* у пам'ять іде ЗМІСТ (речення з цифрами й фактами), а не навігація,
  «підписатися» й заголовки великими літерами;
* питання про свіжі дані БЕЗ мережі вважається порушенням правила;
* пам'ять у проєкті спільна для чатів — це перевіряється на справжньому
  сховищі NEUROMESH, а не на підробці.

Запуск: python -m unittest tests.test_web_learning -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import web_learning  # noqa: E402

SEARCH_RESULT = """Bitcoin price today is 67,432 USD. The price rose 2.3% in the
last 24 hours. Read more about it here https://example.com/btc
BTC PRICE TODAY IS UP. Subscribe to our newsletter for updates.
Price history shows a record high in March 2024.
"""


class TestNeedsWeb(unittest.TestCase):
    """Коли мережа ЗОБОВ'ЯЗАНА."""

    def test_price_question_needs_web(self) -> None:
        self.assertTrue(web_learning.needs_web("яка ціна біткоїна сьогодні"))

    def test_weather_question_needs_web(self) -> None:
        self.assertTrue(web_learning.needs_web("яка погода в Києві"))

    def test_news_question_needs_web(self) -> None:
        self.assertTrue(web_learning.needs_web("останні новини про Python"))

    def test_version_question_needs_web(self) -> None:
        self.assertTrue(web_learning.needs_web("яка зараз версія FastAPI"))

    def test_code_task_does_not_need_web(self) -> None:
        self.assertFalse(web_learning.needs_web("напиши функцію додавання"))

    def test_question_with_web_already_used_is_satisfied(self) -> None:
        self.assertFalse(web_learning.needs_web("яка ціна SOL",
                                                used=["search_web"]))

    def test_memory_answer_lifts_the_requirement(self) -> None:
        self.assertFalse(web_learning.needs_web("яка ціна SOL",
                                                memory_gave=True))

    def test_empty_text_is_harmless(self) -> None:
        self.assertFalse(web_learning.needs_web(""))


class TestWebToolsUsed(unittest.TestCase):
    """Які інтернет-інструменти справді працювали."""

    def test_detects_search_and_fetch(self) -> None:
        self.assertEqual(web_learning.web_tools_used(
            ["read_file", "search_web", "fetch_url", "search_web"]),
            ["search_web", "fetch_url"])

    def test_ignores_other_tools(self) -> None:
        self.assertEqual(web_learning.web_tools_used(["read_file"]), [])


class TestExtract(unittest.TestCase):
    """Що саме стає знанням."""

    def test_keeps_factual_sentences(self) -> None:
        facts = web_learning.extract(SEARCH_RESULT, query="ціна bitcoin")
        texts = " ".join(fact.text for fact in facts)
        self.assertIn("67,432", texts)
        self.assertIn("2.3%", texts)

    def test_drops_navigation_and_headings(self) -> None:
        facts = web_learning.extract(SEARCH_RESULT)
        joined = " ".join(fact.text for fact in facts)
        self.assertNotIn("Read more", joined)
        self.assertNotIn("Subscribe", joined)
        self.assertNotIn("BTC PRICE TODAY IS UP", joined)

    def test_records_source_url(self) -> None:
        facts = web_learning.extract(SEARCH_RESULT)
        self.assertTrue(facts)
        self.assertTrue(all(fact.source.startswith("https://") for fact in facts))
        self.assertTrue(all(fact.provenance().startswith("web:")
                            for fact in facts))

    def test_respects_limit(self) -> None:
        body = " ".join(f"Факт номер {index} має число {index} і сенс." for index in range(10))
        self.assertLessEqual(len(web_learning.extract(body, limit=2)), 2)

    def test_empty_result_gives_nothing(self) -> None:
        self.assertEqual(web_learning.extract(""), [])
        self.assertEqual(web_learning.extract("   "), [])

    def test_error_result_gives_nothing(self) -> None:
        self.assertEqual(web_learning.extract("✗ Помилка: мережа недоступна"), [])

    def test_short_fact_without_digits_is_dropped(self) -> None:
        self.assertEqual(web_learning.extract("Коротко."), [])

    def test_sentences_are_deduplicated(self) -> None:
        body = ("The price of Bitcoin today is 67432 USD in total. " * 3)
        facts = web_learning.extract(body, limit=5)
        self.assertEqual(len(facts), 1, [f.text for f in facts])


class TestLooksLikeWebResult(unittest.TestCase):
    """Відрізнити сторінку від файлу/помилки."""

    def test_url_makes_it_a_web_result(self) -> None:
        self.assertTrue(web_learning.looks_like_web_result(
            "Щось цікаве сталося сьогодні в світі https://example.com/news"))

    def test_plain_text_is_not_web(self) -> None:
        self.assertFalse(web_learning.looks_like_web_result(
            "Просто текст файлу без адрес і без нічого іншого взагалі"))

    def test_error_is_not_web(self) -> None:
        self.assertFalse(web_learning.looks_like_web_result(
            "✗ Помилка: не вдалось з'єднатись https://example.com"))


class FakeService:
    """Підроблена пам'ять із контрактом Neuromesh."""

    def __init__(self) -> None:
        self.items: list[tuple[str, dict[str, Any]]] = []
        self.broken = False

    def remember(self, content: str, **kwargs: Any) -> dict[str, Any]:
        if self.broken:
            raise RuntimeError("навмисно")
        self.items.append((content, kwargs))
        return {"created": True}


class TestRemember(unittest.TestCase):
    """Запис фактів у пам'ять."""

    def test_facts_are_stored_with_source(self) -> None:
        service = FakeService()
        facts = web_learning.extract(SEARCH_RESULT)
        saved = web_learning.remember(service, facts)
        self.assertEqual(saved, len(facts))
        content, kwargs = service.items[0]
        self.assertIn("джерело:", content)
        self.assertEqual(kwargs["kind"], web_learning.KNOWLEDGE_KIND)
        self.assertTrue(str(kwargs["provenance"]).startswith("web:"))

    def test_broken_memory_does_not_raise(self) -> None:
        service = FakeService()
        service.broken = True
        facts = web_learning.extract(SEARCH_RESULT)
        self.assertEqual(web_learning.remember(service, facts), 0)

    def test_no_service_is_harmless(self) -> None:
        self.assertEqual(web_learning.remember(None, []), 0)

    def test_empty_facts_write_nothing(self) -> None:
        service = FakeService()
        self.assertEqual(web_learning.remember(service, []), 0)
        self.assertEqual(service.items, [])


class TestSharedAcrossChats(unittest.TestCase):
    """Найголовніше: знання з одного чату доступне в іншому.

    Перевіряється на СПРАВЖНЬОМУ NEUROMESH: пам'ять у проєкті одна на всі
    чати (окремої таблиці на чат немає), тож записане «у першому чаті» мусить
    знаходитись пошуком «з другого».
    """

    def test_fact_is_found_from_another_chat(self) -> None:
        from blackchpok_ide.pcmm import Neuromesh

        database = Path(tempfile.mkdtemp()) / "memory.db"
        service = Neuromesh(database)
        try:
            facts = web_learning.extract(
                "Курс біткоїна сьогодні становить 67432 долари за монету. "
                "Це на два відсотки більше, ніж учора.",
                source="https://example.com/btc")
            saved = web_learning.remember(service, facts)
            self.assertGreater(saved, 0, "факти не записались")

            # «Інший чат» — це просто інший пошук у тій самій пам'яті.
            found = service.search("курс біткоїна", limit=5)
            texts = " ".join(hit["memory"]["content"]
                             for hit in found.get("hits") or [])
            self.assertIn("67432", texts,
                          f"знання не знайдено з іншого чату: {texts[:200]}")
            self.assertIn("example.com", texts)
        finally:
            service.close()

    def test_second_write_is_not_a_duplicate_row(self) -> None:
        from blackchpok_ide.pcmm import Neuromesh

        database = Path(tempfile.mkdtemp()) / "memory.db"
        service = Neuromesh(database)
        try:
            body = ("Курс біткоїна сьогодні становить 67432 долари за монету. "
                    "Це на два відсотки більше, ніж учора.")
            facts = web_learning.extract(body, source="https://example.com/btc")
            web_learning.remember(service, facts)
            before = service.status()["counts"]["memories"]
            web_learning.remember(service, facts)
            after = service.status()["counts"]["memories"]
            self.assertEqual(before, after,
                             "повторний запис створив дублікат")
        finally:
            service.close()


class TestPromptBlock(unittest.TestCase):
    """Текст вимоги для моделі."""

    def test_prompt_mentions_search_and_memory(self) -> None:
        text = web_learning.format_for_prompt("ціна SOL")
        self.assertIn("search_web", text)
        self.assertIn("пам'ять", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
