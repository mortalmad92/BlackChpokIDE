"""Регресії пам'яті й завантаження моделей (Етап 4, 10.11.2026).

Що фіксуємо:

* ``with sqlite3.connect(...)`` НЕ закриває з'єднання — лише commit/rollback.
  Кожен ``encode`` лишав відкритий дескриптор і WAL.
* ``manager.download`` не прибирав ``.part`` при скасуванні або
  пошкодженому файлі — на диску так лежало 945 МБ, невидимих для списку.
* Обрізання промпту мовчки відрізало СИСТЕМНИЙ промпт (голову).
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blackchpok_ide.native import manager  # noqa: E402


class TestSqliteConnectionsClose(unittest.TestCase):
    """``with conn`` не закриває з'єднання — це треба перевіряти явно."""

    def test_plain_with_block_does_not_close(self) -> None:
        """Документує саму пастку: звідси й був дефект."""
        path = Path(tempfile.mkdtemp()) / "t.db"
        with sqlite3.connect(str(path)) as conn:
            conn.execute("CREATE TABLE t(a int)")
        # Якщо це колись зміниться в Python — тест упаде й нагадає перевірити.
        try:
            conn.execute("SELECT 1")
            still_open = True
        except sqlite3.ProgrammingError:
            still_open = False
        conn.close()
        self.assertTrue(
            still_open,
            "поведінка sqlite3 змінилась: 'with conn' тепер закриває "
            "з'єднання — перевірте, чи не потрібні спрощення")

    def test_embeddings_connect_closes(self) -> None:
        from blackchpok_ide.native.embeddings import EmbeddingService

        class FakeEngine:
            loaded = False
            model_path = ""

        path = Path(tempfile.mkdtemp()) / "e.db"
        service = EmbeddingService(engine=FakeEngine(), db_path=path)
        captured: dict[str, sqlite3.Connection] = {}
        with service._connect() as conn:      # noqa: SLF001 - тест внутрішнього
            captured["conn"] = conn
            conn.execute("SELECT 1")
        with self.assertRaises(sqlite3.ProgrammingError):
            captured["conn"].execute("SELECT 1")

    def test_embeddings_init_creates_schema(self) -> None:
        from blackchpok_ide.native.embeddings import EmbeddingService

        class FakeEngine:
            loaded = False
            model_path = ""

        path = Path(tempfile.mkdtemp()) / "e2.db"
        service = EmbeddingService(engine=FakeEngine(), db_path=path)
        service._init_db()                    # noqa: SLF001
        with service._connect() as conn:      # noqa: SLF001
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='embed_cache'").fetchone()
        self.assertIsNotNone(row)

    def test_many_connections_do_not_fail(self) -> None:
        """20 циклів open/close не мають впиратись у ліміт дескрипторів."""
        from blackchpok_ide.native.embeddings import EmbeddingService

        class FakeEngine:
            loaded = False
            model_path = ""

        path = Path(tempfile.mkdtemp()) / "e3.db"
        service = EmbeddingService(engine=FakeEngine(), db_path=path)
        service._init_db()                    # noqa: SLF001
        for _ in range(20):
            with service._connect() as conn:  # noqa: SLF001
                conn.execute("SELECT 1")


class TestPartialDownloadCleanup(unittest.TestCase):
    """``.part`` не показується у списку моделей — його треба прибирати."""

    def test_drop_part_removes_file(self) -> None:
        target = Path(tempfile.mkdtemp()) / "x.gguf.part"
        target.write_bytes(b"x" * 512)
        self.assertTrue(manager._drop_part(target, reason="тест"))
        self.assertFalse(target.exists())

    def test_drop_part_is_safe_when_missing(self) -> None:
        target = Path(tempfile.mkdtemp()) / "нема.gguf.part"
        self.assertFalse(manager._drop_part(target))

    def test_download_source_calls_drop_part(self) -> None:
        """Скасування й пошкодження мусять прибирати ``.part``."""
        import inspect

        source = inspect.getsource(manager.ModelManager.download)
        self.assertIn("_drop_part", source,
                      "без цього недокачані файли лишаються назавжди")
        # Мережевий обрив НЕ має прибирати: .part придатний для докачки.
        self.assertIn("докачати", source)


class TestPromptTruncationIsLoud(unittest.TestCase):
    """Обрізання голови промпту прибирає системні інструкції."""

    def test_truncation_reports_head_loss(self) -> None:
        import inspect

        from blackchpok_ide.native import engine

        source = inspect.getsource(engine.NativeEngine)
        self.assertIn("truncated_head_tokens", source,
                      "викликач має бачити, скільки втрачено з голови")
        self.assertIn("З ГОЛОВИ", source,
                      "журнал має прямо називати небезпеку")


if __name__ == "__main__":
    unittest.main(verbosity=2)
