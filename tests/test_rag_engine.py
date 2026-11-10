import json
import os
import tempfile
import unittest
from pathlib import Path

from rag_engine import LocalRAG


class LocalRAGTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root / "src").mkdir()
        (self.root / "README.md").write_text(
            "# Payment service\n\nFailed HTTP requests are retried using exponential backoff.\n",
            encoding="utf-8",
        )
        (self.root / "src" / "payment.py").write_text(
            'def retry_request():\n    """Retry failed HTTP requests with exponential backoff."""\n    return 3\n',
            encoding="utf-8",
        )
        (self.root / ".env").write_text("PRIVATE_TOKEN=not-for-indexing\n", encoding="utf-8")

        ignored = {".git", ".hg", ".svn", ".venv", "venv", "env", ".mcp_rag", "node_modules", "__pycache__"}

        def safe_path(raw_path, *, must_exist=False):
            path = Path(raw_path).expanduser()
            if not path.is_absolute():
                path = self.root / path
            path = path.resolve(strict=must_exist)
            path.relative_to(self.root)
            if ".git" in path.parts:
                raise PermissionError(".git access blocked")
            return path

        def walk_files(base=None):
            start = base or self.root
            for current, dirs, files in os.walk(start, followlinks=False):
                dirs[:] = [d for d in dirs if d not in ignored and not (Path(current) / d).is_symlink()]
                for filename in files:
                    path = Path(current) / filename
                    if not path.is_symlink() and filename not in {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock", "uv.lock"}:
                        yield path

        def read_text(path):
            raw = path.read_bytes()
            if b"\x00" in raw[:8192]:
                raise ValueError("binary file")
            if len(raw) > 2_000_000:
                raise ValueError("file too large")
            return raw.decode("utf-8-sig", errors="replace")

        def relative(path):
            return path.relative_to(self.root).as_posix() or "."

        self.rag = LocalRAG(self.root, safe_path, walk_files, read_text, relative)
        os.environ.pop("MCP_RAG_EMBEDDINGS_URL", None)
        os.environ.pop("MCP_RAG_EMBEDDINGS_MODEL", None)

    def tearDown(self):
        self.temp.cleanup()

    def test_index_search_and_cited_context(self):
        indexed = json.loads(self.rag.index_workspace())
        self.assertEqual(indexed["files_indexed_or_updated"], 2)
        self.assertGreaterEqual(indexed["files_skipped_or_excluded"], 1)

        results = json.loads(self.rag.search("exponential backoff failed HTTP request"))
        self.assertTrue(results["results"])
        self.assertTrue(any(item["source"] == "src/payment.py" for item in results["results"]))

        context = self.rag.get_context("where are failed HTTP requests retried")
        self.assertIn("[ДЖЕРЕЛО", context)
        self.assertIn("src/payment.py", context)

    def test_reindex_skips_unchanged_and_prunes_deleted_files(self):
        self.rag.index_workspace()
        second = json.loads(self.rag.index_workspace())
        self.assertEqual(second["files_unchanged"], 2)

        (self.root / "README.md").unlink()
        third = json.loads(self.rag.index_workspace())
        self.assertEqual(third["stale_documents_removed"], 1)

    def test_index_clear_does_not_delete_source_files(self):
        self.rag.index_workspace()
        result = json.loads(self.rag.clear_index(confirm=True))
        self.assertFalse(result["source_files_deleted"])
        self.assertTrue((self.root / "README.md").exists())
        self.assertEqual(json.loads(self.rag.status())["documents"], 0)

    def test_memory_recall_finds_saved_fact(self):
        self.rag.index_workspace()
        note = self.rag.remember("Секретний маяк проекту називається Синій Кіт", "rule")
        self.assertIn("Запам'ятав", note)
        again = self.rag.remember("Секретний маяк проекту називається Синій Кіт", "rule")
        self.assertIn("Вже в пам'яті", again)
        text = self.rag.recall("де маяк Синій Кіт")
        self.assertIn("Синій Кіт", text)
        with self.rag._db() as conn:
            stored = conn.execute("SELECT path FROM rag_documents").fetchone()["path"]
        self.assertNotIn("\\", stored)
        self.assertFalse(stored[1:2] == ":")

    def test_repairs_utf8_read_as_cp1251(self):
        original = "локальний сервер пам'яті агента працює українською мовою щодня"
        broken = original.encode("utf-8").decode("cp1251")
        self.assertEqual(LocalRAG._repair_text(broken), original)
        self.assertEqual(LocalRAG._repair_text(original), original)

    def test_outside_path_prefix_is_rejected(self):
        result = json.loads(self.rag.search("retry", path_prefix=str(self.root.parent)))
        self.assertIn("error", result)

    def test_newer_similar_fact_replaces_older_one(self):
        first = self.rag.remember("Курс долара на сьогодні становить 41 гривню", "rule")
        second = self.rag.remember("Курс долара на сьогодні становить 43 гривню", "rule")
        self.assertIn("Запам'ятав", first)
        self.assertIn("Оновив", second)
        with self.rag._db() as conn:
            rows = conn.execute("SELECT content FROM rag_memory WHERE kind='rule'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertIn("43", rows[0]["content"])
        self.assertNotIn("41", rows[0]["content"])

    def test_different_facts_and_short_note_stay_separate(self):
        self.rag.remember("Курс долара на сьогодні становить 41 гривню", "rule")
        self.rag.remember("Робоча папка агента лежить на локальному диску", "rule")
        long_rule = (
            "Єдиний виклик роутера приймає звичайні слова користувача і сам обирає дію. "
            "Читання файлу обмежене ста п'ятдесятьма рядками. Запис робить копію перед зміною. "
            "Пошук у коді йде окремо від фінансових новин і чернетки поста."
        )
        self.rag.remember(long_rule, "rule")
        self.rag.remember("Відповідь користувачу завжди українською мовою", "rule")
        with self.rag._db() as conn:
            rows = conn.execute("SELECT content FROM rag_memory WHERE kind='rule'").fetchall()
        self.assertEqual(len(rows), 4)
        self.assertTrue(any(long_rule[:40] in row["content"] for row in rows))

    def test_chat_turns_are_not_collapsed(self):
        self.rag.remember("Користувач: який курс долара\nАгент: курс долара 41", "chat")
        self.rag.remember("Користувач: який курс долара\nАгент: курс долара 43", "chat")
        with self.rag._db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM rag_memory WHERE kind='chat'").fetchone()[0]
        self.assertEqual(count, 2)

    def test_refresh_keeps_newest_duplicate(self):
        with self.rag._db() as conn:
            conn.execute(
                "INSERT INTO rag_memory(kind, content, content_hash, created_at) VALUES(?,?,?,?)",
                ("rule", "Курс долара на сьогодні становить 41 гривню", "old-rate", "2020-01-01T00:00:00+00:00"),
            )
            conn.execute(
                "INSERT INTO rag_memory(kind, content, content_hash, created_at) VALUES(?,?,?,?)",
                ("rule", "Курс долара на сьогодні становить 43 гривню", "new-rate", "2026-01-01T00:00:00+00:00"),
            )
        note = self.rag.refresh_memory(force=True)
        self.assertIn("1", note)
        with self.rag._db() as conn:
            rows = conn.execute("SELECT content FROM rag_memory WHERE kind='rule'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertIn("43", rows[0]["content"])


if __name__ == "__main__":
    unittest.main()
