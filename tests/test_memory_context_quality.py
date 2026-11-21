"""Тести ЯКОСТІ контексту з пам'яті: що модель справді бачить перед дією.

Проблема, яку ці тести охороняють (заміряно на живій базі 822 спогади):

* 631 запис типу ``task`` — це архівні дампи «Вивільнено з контексту.
  read_file: # файл …». Вони збігалися з будь-яким запитом про файл і
  займали ПЕРШІ місця в контексті, витісняючи правила й уроки;
* 75 записів типу ``error`` — давні збої інструментів. Вони теж збігаються
  за словами («Файл не знайдено: social.py») і займали 4 місця з 6.

Наслідок для користувача: на запит «як запускати тести» модель отримувала
дамп чужого файлу замість правила «pytest не встановлено, запускай
unittest». Тобто пам'ять формально працювала, а користі не давала.

Запуск: python -m unittest tests.test_memory_context_quality -v
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide.pcmm import Neuromesh  # noqa: E402
from blackchpok_ide.pcmm import budget, service  # noqa: E402


def make_service() -> tuple[Neuromesh, Path]:
    path = Path(tempfile.mkdtemp()) / "memory.db"
    return Neuromesh(path), path


def texts(bundle) -> str:
    return " ".join(piece.text for piece in bundle.report.pieces)


class TestPromptKinds(unittest.TestCase):
    """У промпт ідуть ЗНАННЯ, а не журнал активності."""

    def test_journal_kinds_are_excluded(self) -> None:
        for kind in ("task", "change", "tool"):
            self.assertNotIn(kind, service.PROMPT_KINDS,
                             f"журнальний тип {kind} не має йти в промпт")

    def test_knowledge_kinds_are_included(self) -> None:
        for kind in ("constraint", "lesson", "fact", "fix", "decision"):
            self.assertIn(kind, service.PROMPT_KINDS)

    def test_archive_dump_is_recognised(self) -> None:
        class Memory:
            content = "Вивільнено з контексту. read_file: # файл"

        self.assertTrue(service._is_archive_dump(Memory()))

    def test_regular_content_is_not_archive(self) -> None:
        class Memory:
            content = "Тести запускаються через unittest discover -s tests"

        self.assertFalse(service._is_archive_dump(Memory()))


class TestArchiveDumpsStayOut(unittest.TestCase):
    """Архівний дамп не потрапляє в контекст, навіть якщо схожий на запит."""

    def test_dump_is_filtered_from_bundle(self) -> None:
        api, _path = make_service()
        try:
            # Десять схожих дампів і ОДНЕ справжнє правило.
            for index in range(10):
                api.remember(
                    f"Вивільнено з контексту. read_file: # tests/test_{index}.py "
                    f"1 | import unittest 2 | class Test{index}…",
                    kind="task", source="контекст", confidence=0.45,
                    with_vector=False)
            api.remember(
                "Тести цього проєкту запускаються через "
                "`python -m unittest discover -s tests -p \"test_*.py\" -v`.",
                kind="constraint", source="пакет знань", confidence=0.9,
                with_vector=False)

            bundle = api.project_context(query="як запускати тести", window=16384)
            body = texts(bundle)
            self.assertNotIn("Вивільнено з контексту", body,
                             f"дамп прослизнув у контекст: {body[:200]}")
            self.assertIn("unittest discover -s tests", body,
                          f"справжнє правило не дійшло: {body[:200]}")
        finally:
            api.close()


class TestStaleErrors(unittest.TestCase):
    """Давні помилки не займають місце; свіжі — лишаються."""

    def test_old_error_is_stale(self) -> None:
        class Memory:
            kind = "error"
            created_at = time.time() - 30 * 86400

        self.assertTrue(service._is_stale_error(Memory()))

    def test_fresh_error_is_not_stale(self) -> None:
        class Memory:
            kind = "error"
            created_at = time.time() - 3600

        self.assertFalse(service._is_stale_error(Memory()))

    def test_non_error_is_never_stale(self) -> None:
        class Memory:
            kind = "constraint"
            created_at = time.time() - 365 * 86400

        self.assertFalse(service._is_stale_error(Memory()))

    def test_error_cap_is_small(self) -> None:
        self.assertLessEqual(service.MAX_ERROR_PIECES, 2)
        self.assertGreaterEqual(service.MAX_ERROR_PIECES, 1)


class TestErrorShareIsCapped(unittest.TestCase):
    """Навіть свіжих помилок у контексті — не більше ніж дозволено."""

    def test_many_errors_do_not_fill_the_context(self) -> None:
        api, _path = make_service()
        try:
            for index in range(8):
                api.remember(
                    f"Збій інструмента: read_file: Файл не знайдено: "
                    f"tests/test_{index}.py в теці проєкту",
                    kind="error", source="агент", confidence=0.5,
                    with_vector=False)
            api.remember(
                "Правило проєкту: якщо тест падає — виправляй причину в коді.",
                kind="constraint", source="пакет знань", confidence=0.9,
                with_vector=False)

            bundle = api.project_context(query="тести падають що робити",
                                         window=16384)
            errors = [piece for piece in bundle.report.pieces
                      if "[error]" in piece.text]
            self.assertLessEqual(len(errors), service.MAX_ERROR_PIECES,
                                 f"помилки забили контекст: {len(errors)}")
            self.assertIn("Правило проєкту", texts(bundle),
                          "правило не дійшло до моделі")
        finally:
            api.close()


class TestBudgetErrorAge(unittest.TestCase):
    """Поріг свіжості помилки живе в бюджеті й доступний сервісу."""

    def test_threshold_is_one_week(self) -> None:
        self.assertEqual(budget.ERROR_FRESH_DAYS, 7.0)


class TestConstraintsAlwaysPresent(unittest.TestCase):
    """Критичні правила діють завжди, навіть на сторонній запит."""

    def test_constraint_survives_unrelated_query(self) -> None:
        api, _path = make_service()
        try:
            api.remember(
                "Контракт: не викидай повідомлення з історії без архівування.",
                kind="constraint", source="пакет знань", confidence=0.95,
                with_vector=False)
            bundle = api.project_context(query="який сьогодні день",
                                         window=16384)
            self.assertIn("не викидай повідомлення", texts(bundle))
        finally:
            api.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
