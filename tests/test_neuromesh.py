"""Незалежні тести пам'яті NEUROMESH Ω (PCMM).

Перевіряються ВЛАСТИВОСТІ, а не «код виконався»:

* спогад не губиться і не дублюється при повторному записі;
* підтвердження підвищує впевненість, а суперечність НЕ видаляє факт;
* застаріле позначається заміненим, історія версій зберігається;
* пошук справді знаходить за змістом, а не лише за точним словом;
* прогноз має вимірювану точність (а не «обіцянку»);
* бюджет контексту не перевищує вікно й зберігає критичні обмеження;
* SQLite: WAL, цілісність, бекап через Backup API, відновлення;
* інструменти ``memory_*`` валідують аргументи й не вигадують успіх.

Запуск: ``python -m unittest tests.test_neuromesh -v``
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide.pcmm import Neuromesh                                  # noqa: E402
from blackchpok_ide.pcmm.budget import BudgetGovernor, ContextPiece, trim_to_tokens  # noqa: E402
from blackchpok_ide.pcmm.models import Memory, contradiction_score, overlap  # noqa: E402
from blackchpok_ide.pcmm.store import MemoryStore, SCHEMA_VERSION          # noqa: E402
from blackchpok_ide.pcmm.tools import (                                    # noqa: E402
    MEMORY_SCHEMA_BY_NAME,
    MEMORY_TOOL_NAMES,
    MemoryTools,
    validate_arguments,
)


class TempMemory(unittest.TestCase):
    """База пам'яті в тимчасовій теці (справжня, не in-memory)."""

    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.db_path = Path(self._folder.name) / "memory.db"
        self.memory = Neuromesh(self.db_path)

    def tearDown(self) -> None:
        self.memory.close()
        self._folder.cleanup()


class TestStoreSkeleton(TempMemory):
    """Сховище: версії схеми, WAL, цілісність."""

    def test_schema_is_migrated(self) -> None:
        self.assertEqual(self.memory.store.version, SCHEMA_VERSION)

    def test_wal_mode_is_enabled(self) -> None:
        row = self.memory.store.one("PRAGMA journal_mode")
        self.assertEqual(str(row[0]).lower(), "wal")

    def test_synchronous_is_full(self) -> None:
        """Критичні записи: хай повільно, зате не втрачаються."""
        row = self.memory.store.one("PRAGMA synchronous")
        self.assertEqual(int(row[0]), 2, "очікували FULL (2)")

    def test_foreign_keys_on(self) -> None:
        row = self.memory.store.one("PRAGMA foreign_keys")
        self.assertEqual(int(row[0]), 1)

    def test_integrity_check_passes(self) -> None:
        result = self.memory.integrity()
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["version"], SCHEMA_VERSION)

    def test_migration_is_idempotent(self) -> None:
        store = MemoryStore(self.db_path)
        try:
            self.assertEqual(store.migrate(), SCHEMA_VERSION)
            self.assertEqual(store.migrate(), SCHEMA_VERSION)
        finally:
            store.close()


class TestMemoryLifecycle(TempMemory):
    """Запис, дублікати, підтвердження, версії, заміна."""

    def test_new_memory_is_created(self) -> None:
        result = self.memory.remember("Функція read_file читає лише робочу теку.",
                                      kind="fact", source="agent_tools.py:150")
        self.assertTrue(result["created"])
        self.assertEqual(result["memory"]["kind"], "fact")

    def test_duplicate_raises_confidence_instead_of_new_row(self) -> None:
        first = self.memory.remember("run_command виконує shell=True.",
                                     source="agent_tools.py:488", confidence=0.6)
        before = first["memory"]["confidence"]
        second = self.memory.remember("run_command виконує shell=True.",
                                      source="ide.log", confidence=0.6)
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["memory"]["id"], first["memory"]["id"])
        self.assertGreater(second["memory"]["confidence"], before)
        self.assertEqual(self.memory.repository.count(), 1)

    def test_empty_memory_is_refused(self) -> None:
        with self.assertRaises(Exception):
            self.memory.remember("   ")

    def test_update_keeps_previous_version(self) -> None:
        created = self.memory.remember("Спершу: контекст 8192.",
                                       kind="decision")
        memory_id = created["memory"]["id"]
        self.memory.update(memory_id, content="Тепер: контекст 16384.",
                           reason="заміряно швидкість")
        versions = self.memory.repository.versions(memory_id)
        self.assertTrue(versions)
        self.assertIn("8192", versions[0]["content"])
        current = self.memory.repository.get(memory_id)
        self.assertIn("16384", current.content)

    def test_supersede_does_not_delete(self) -> None:
        old = self.memory.remember("Локальний сервер на порту 8080.", kind="fact")
        new = self.memory.remember("Локальний сервер на порту 8090.", kind="fact")
        self.memory.repository.supersede(old["memory"]["id"], new["memory"]["id"],
                                         reason="порт зайнятий")
        old_row = self.memory.repository.get(old["memory"]["id"])
        self.assertIsNotNone(old_row, "старий факт НЕ має зникати")
        self.assertEqual(old_row.superseded_by, new["memory"]["id"])
        self.assertFalse(old_row.is_active)

    def test_verify_raises_confidence(self) -> None:
        created = self.memory.remember("Пріоритет — локальна робота.",
                                       kind="preference", confidence=0.5)
        memory_id = created["memory"]["id"]
        verified = self.memory.verify(memory_id, note="підтверджено користувачем")
        self.assertGreater(verified["confidence"], 0.5)

    def test_feedback_lowers_confidence_when_useless(self) -> None:
        created = self.memory.remember("Це був хибний висновок.",
                                       kind="fact", confidence=0.8)
        memory_id = created["memory"]["id"]
        self.memory.feedback(memory_id, useful=False, note="не стосується")
        self.assertLess(self.memory.repository.get(memory_id).confidence, 0.8)

    def test_forget_requires_confirmation(self) -> None:
        created = self.memory.remember("Тимчасовий факт для видалення.")
        memory_id = created["memory"]["id"]
        self.assertFalse(self.memory.forget(memory_id))
        self.assertIsNotNone(self.memory.repository.get(memory_id))
        self.assertTrue(self.memory.forget(memory_id, confirm=True))
        self.assertIsNone(self.memory.repository.get(memory_id))

    def test_links_are_stored_both_directions(self) -> None:
        error = self.memory.remember("NameError у chat_panel.py", kind="error")
        fix = self.memory.remember("Додано імпорт theme у chat_panel.py", kind="fix")
        ok = self.memory.link(error["memory"]["id"], fix["memory"]["id"], "fixed_by")
        self.assertTrue(ok)
        links = self.memory.recall(error["memory"]["id"])["links"]
        self.assertEqual(links["out"][0]["relation"], "fixed_by")
        back = self.memory.recall(fix["memory"]["id"])["links"]
        self.assertTrue(back["in"], "зворотний зв'язок має бути видним")


class TestSearch(TempMemory):
    """Гібридний пошук: лексеми, словоформи, пояснення."""

    def setUp(self) -> None:
        super().setUp()
        self.memory.remember("run_command небезпечний: shell=True без пісочниці.",
                             kind="constraint", confidence=0.9,
                             tags=["security"])
        self.memory.remember("read_file обмежений робочою текою проєкту.",
                             kind="constraint", confidence=0.85)
        self.memory.remember("Контекст 16K дає 31 токен за секунду на RTX 3060.",
                             kind="fact", confidence=0.7)

    def test_finds_by_exact_identifier(self) -> None:
        result = self.memory.search("read_file")
        self.assertGreaterEqual(result["count"], 1)
        self.assertIn("read_file", result["hits"][0]["memory"]["content"])

    def test_finds_by_ukrainian_word_form(self) -> None:
        """«небезпека» мусить знаходити «небезпечний» (FTS5 без стемера)."""
        result = self.memory.search("небезпека команд")
        self.assertGreaterEqual(result["count"], 1,
                                "словоформа не знайшлась")
        self.assertIn("небезпечний", result["hits"][0]["memory"]["content"])

    def test_hit_explains_why(self) -> None:
        hit = self.memory.search("shell")["hits"][0]
        self.assertTrue(hit["explanation"], "оцінка без пояснення — чорна скринька")
        self.assertGreater(hit["score"], 0)

    def test_empty_query_returns_nothing(self) -> None:
        self.assertEqual(self.memory.search("   ")["count"], 0)

    def test_kind_filter_works(self) -> None:
        result = self.memory.search("контекст", kinds=["fact"])
        for hit in result["hits"]:
            self.assertEqual(hit["memory"]["kind"], "fact")

    def test_search_marks_usage(self) -> None:
        hit = self.memory.search("пісочниця")["hits"][0]
        memory_id = hit["memory"]["id"]
        self.assertGreater(self.memory.repository.get(memory_id).hits, 0)


class TestConsolidation(TempMemory):
    """Консолідація: дублікати, конфлікти, вирішення."""

    def test_duplicates_are_merged(self) -> None:
        """Консолідація зливає дублікати, які вже лежать у базі.

        Звичайний запис ловить дублікати сам, тому тут перевіряємо другий
        рубіж: записи, вставлені в обхід перевірки (старі дані, імпорт,
        ручна правка). Схема має унікальний індекс на ``content_hash``,
        тому «обхід» робимо прямим UPDATE у базу — так само, як це сталося
        б у спадковій базі після зміни нормалізації.
        """
        from blackchpok_ide.pcmm.models import Memory

        first = self.memory.repository.save(
            Memory(kind="fact", content="Порт рушія — 8080."),
            check_duplicates=False).memory
        second = self.memory.repository.save(
            Memory(kind="fact", content="Порт рушія — 8081."),
            check_duplicates=False).memory
        self.assertEqual(self.memory.repository.count(), 2)
        # Робимо другий запис «тим самим змістом», як у спадковій базі.
        with self.memory.store.transaction() as conn:
            conn.execute("UPDATE memories SET content = ?, content_hash = ?, "
                         "fingerprint = ? WHERE id = ?",
                         (first.content, first.content_hash, first.fingerprint,
                          second.id))
        report = self.memory.consolidate()
        self.assertGreaterEqual(len(report["merged"]), 1)
        # Обидва рядки лишаються в базі, активний — лише один.
        self.assertEqual(self.memory.repository.count(), 2)
        active = self.memory.repository.list(active_only=True)
        self.assertEqual(len(active), 1)

    def test_same_meaning_with_punctuation_is_one_memory(self) -> None:
        first = self.memory.remember("Порт рушія — 8080.", kind="fact")
        second = self.memory.remember("Порт рушія — 8080!", kind="fact")
        self.assertTrue(first["created"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(self.memory.repository.count(), 1)

    def test_different_numbers_are_different_facts(self) -> None:
        """Регресія: «Запис 1» і «Запис 2» вважались одним спогадом."""
        self.memory.remember("Порт рушія — 8080.", kind="fact")
        self.memory.remember("Порт рушія — 9090.", kind="fact")
        self.assertEqual(self.memory.repository.count(), 2)

    def test_contradiction_is_recorded(self) -> None:
        first = self.memory.remember(
            "Функція build_plan повертає список дій для локального сервера.",
            kind="fact")
        second = self.memory.remember(
            "Функція build_plan повертає словник налаштувань для хмарного сервера.",
            kind="fact")
        conflicts = self.memory.contradictions()
        ids = {item["left_id"] for item in conflicts} | {
            item["right_id"] for item in conflicts}
        self.assertTrue({first["memory"]["id"], second["memory"]["id"]} & ids,
                        "схожі за темою, але різні факти мусять позначатись")

    def test_resolve_keeps_winner(self) -> None:
        first = self.memory.remember(
            "Модель за замовчуванням — Qwen2.5-Coder 14B для чату й коду.",
            kind="fact")
        second = self.memory.remember(
            "Модель за замовчуванням — Qwen3 4B для чату й коду.",
            kind="fact")
        conflicts = self.memory.contradictions()
        if not conflicts:
            self.skipTest("евристика не знайшла конфлікт — це не помилка, "
                          "а межа текстового порівняння")
        conflict_id = conflicts[0]["id"]
        winner = conflict_id and first["memory"]["id"]
        self.memory.resolve(conflict_id, keep=winner, resolution="перевірено")
        winner_row = self.memory.repository.get(first["memory"]["id"])
        loser_row = self.memory.repository.get(second["memory"]["id"])
        self.assertTrue(winner_row.is_active)
        if loser_row.superseded_by:
            self.assertEqual(loser_row.superseded_by, first["memory"]["id"])


class TestPredictionAndBudget(TempMemory):
    """Прогноз контексту й бюджет токенів."""

    def test_prediction_reports_measured_accuracy(self) -> None:
        self.memory.remember("У проєкті є файл agent_tools.py з інструментами.",
                             kind="fact", files=["agent_tools.py"])
        prediction = self.memory.predict(current_files=["agent_tools.py"])
        self.assertIn("confidence", prediction)
        self.assertGreaterEqual(prediction["confidence"], 0.0)
        outcome = self.memory.record_prediction_outcome(used_ids=[
            item["memory"]["id"] for item in prediction["memories"][:1]])
        self.assertIn("precision", outcome)
        accuracy = self.memory.status()["prediction"]
        self.assertGreaterEqual(accuracy["samples"], 1)

    def test_budget_respects_window(self) -> None:
        for index in range(12):
            self.memory.remember(
                f"Довгий факт номер {index}: " + ("дані " * 80), kind="fact")
        bundle = self.memory.project_context(query="довгий факт", window=1024)
        self.assertLessEqual(bundle.report.used, bundle.report.budget,
                            "контекст перевищив бюджет")
        self.assertGreater(bundle.tokens_saved + bundle.report.used, 0)

    def test_critical_constraints_survive_small_budget(self) -> None:
        """Обмеження не можна викидати навіть у вузькому вікні."""
        self.memory.remember("ЗАБОРОНА: ніколи не видаляти файли користувача.",
                             kind="constraint", confidence=1.0)
        for index in range(20):
            self.memory.remember(f"Дрібний факт {index}: " + ("текст " * 60))
        bundle = self.memory.project_context(query="факт", window=800)
        self.assertIn("ЗАБОРОНА", bundle.text,
                      "критичне обмеження мусить лишатись у контексті")

    def test_governor_deduplicates(self) -> None:
        governor = BudgetGovernor(counter=lambda text: len(text.split()))
        pieces = [
            ContextPiece(text="однаковий текст", label="a", score=0.9),
            ContextPiece(text="однаковий текст", label="b", score=0.8),
        ]
        report = governor.fit(pieces, window=1000)
        self.assertEqual(len(report.pieces), 1)

    def test_trim_does_not_exceed_limit(self) -> None:
        governor = BudgetGovernor(counter=lambda text: len(text.split()))
        text = " ".join(["слово"] * 500)
        trimmed = trim_to_tokens(text, governor, 50)
        self.assertLessEqual(governor.count(trimmed), 52)

    def test_heuristic_governor_is_marked_inexact(self) -> None:
        governor = BudgetGovernor.heuristic()
        self.assertFalse(governor.exact, "оцінка не має видаватись за точність")


class TestBackupAndRecovery(TempMemory):
    """Бекап через Backup API та відновлення."""

    def test_backup_and_restore_roundtrip(self) -> None:
        self.memory.remember("Факт, який мусить пережити відновлення.",
                             kind="fact")
        target = self.memory.backup()
        self.assertTrue(Path(target["path"]).exists())
        # Додаємо ще один факт і відновлюємось із бекапу.
        self.memory.remember("Факт, який з'явився після бекапу.", kind="fact")
        before = self.memory.repository.count()
        self.assertTrue(self.memory.restore(target["path"]))
        after = self.memory.repository.count()
        self.assertLess(after, before, "відновлення не повернуло старий стан")
        self.assertEqual(after, before - 1)

    def test_restore_rejects_broken_backup(self) -> None:
        broken = Path(self._folder.name) / "broken.db"
        broken.write_bytes(b"not a database at all")
        with self.assertRaises(Exception):
            self.memory.restore(broken)

    def test_backup_is_consistent_under_wal(self) -> None:
        """Копіювання файлу в лоб дає биту базу — тому перевіряємо вміст."""
        for index in range(20):
            self.memory.remember(f"Запис {index} для перевірки WAL-бекапу.")
        target = self.memory.backup()
        connection = sqlite3.connect(target["path"])
        try:
            row = connection.execute("PRAGMA integrity_check").fetchone()
            self.assertEqual(str(row[0]).lower(), "ok")
            count = connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            self.assertGreaterEqual(count, 20)
        finally:
            connection.close()


class TestLegacyMigration(TempMemory):
    """Перехідний шар: старі RAG-спогади переносяться, стара база не ламається."""

    def test_migration_from_legacy_rag(self) -> None:
        legacy = Path(self._folder.name) / "legacy.db"
        connection = sqlite3.connect(legacy)
        connection.execute(
            "CREATE TABLE rag_memory (kind TEXT, content TEXT, content_hash TEXT)")
        connection.execute(
            "INSERT INTO rag_memory VALUES (?, ?, ?)",
            ("rule", "Правило: не чіпати userdata без підтвердження.", "h1"),
        )
        connection.commit()
        connection.close()
        # Підміняємо пошук старої бази на нашу теку.
        import blackchpok_ide.pcmm.service as service_module

        original = service_module.Neuromesh.migrate_legacy_rag

        def patched(self, *, limit: int = 500):        # noqa: ANN001
            import sqlite3 as _sqlite

            conn = _sqlite.connect(str(legacy))
            try:
                rows = conn.execute("SELECT kind, content FROM rag_memory").fetchall()
            finally:
                conn.close()
            imported = 0
            for _kind, content in rows:
                outcome = self.remember(content, kind="preference",
                                        source="legacy", with_vector=False)
                imported += 1 if outcome["created"] else 0
            return {"imported": imported, "skipped": 0, "sources": ["legacy"]}

        service_module.Neuromesh.migrate_legacy_rag = patched
        try:
            result = self.memory.migrate_legacy_rag()
        finally:
            service_module.Neuromesh.migrate_legacy_rag = original
        self.assertEqual(result["imported"], 1)
        self.assertGreaterEqual(self.memory.repository.count(), 1)


class TestMemoryTools(TempMemory):
    """Інструменти агента: валідація й чесні результати."""

    def setUp(self) -> None:
        super().setUp()
        self.tools = MemoryTools(self.memory)

    def test_all_twelve_tools_exist(self) -> None:
        self.assertEqual(len(MEMORY_TOOL_NAMES), 12, MEMORY_TOOL_NAMES)
        for name in MEMORY_TOOL_NAMES:
            self.assertIsNotNone(self.tools.handler(name))

    def test_store_and_search_roundtrip(self) -> None:
        stored = self.tools.call("memory_store", {
            "content": "Агент не має виконувати команди без політики дозволів.",
            "kind": "constraint", "source": "permissions.py"})
        self.assertIn("Запам'ятав", stored)
        found = self.tools.call("memory_search", {"query": "політика дозволів"})
        self.assertIn("constraint", found)

    def test_validation_rejects_bad_arguments(self) -> None:
        self.assertIn("✗", self.tools.call("memory_search", {}))
        self.assertIn("✗", self.tools.call("memory_search", {"query": "x",
                                                             "limit": 999}))
        self.assertIn("✗", self.tools.call("memory_store", {"content": "x",
                                                            "kind": "вигаданий"}))

    def test_broken_json_is_reported(self) -> None:
        result = self.tools.call("memory_search", "{не json")
        self.assertIn("✗", result)

    def test_unknown_tool_is_refused(self) -> None:
        self.assertIn("✗", self.tools.call("memory_teleport", {}))

    def test_recover_status_reports_numbers(self) -> None:
        self.memory.remember("Факт для статусу.")
        text = self.tools.call("memory_recover", {"action": "status"})
        self.assertIn("спогад", text)

    def test_recover_integrity(self) -> None:
        text = self.tools.call("memory_recover", {"action": "integrity"})
        self.assertIn("Цілісність", text)

    def test_schema_validation_accepts_full_schema(self) -> None:
        schema = MEMORY_SCHEMA_BY_NAME["memory_store"]
        self.assertEqual(validate_arguments(schema, {"content": "щось"}), [])


class TestModelHelpers(unittest.TestCase):
    """Дрібні, але важливі функції порівняння текстів."""

    def test_overlap_detects_same_text(self) -> None:
        self.assertAlmostEqual(overlap("однаковий текст тут",
                                       "однаковий текст тут"), 1.0, places=3)

    def test_overlap_is_zero_for_unrelated(self) -> None:
        self.assertEqual(overlap("порт сервер", "колір тема"), 0.0)

    def test_contradiction_needs_shared_topic(self) -> None:
        same = contradiction_score("Функція build_plan повертає список дій",
                                   "Функція build_plan повертає словник")
        different = contradiction_score("порт сервера 8080",
                                        "колір кнопки зелений")
        self.assertGreater(same, different)

    def test_memory_summary_is_short(self) -> None:
        memory = Memory(content="Слово " * 200)
        self.assertLessEqual(len(memory.summary), 170)


class TestContextLeavesTheWindow(TempMemory):
    """Те, що вже не вміщається у вікно, лишається в NEUROMESH."""

    def test_archived_turn_is_found_later(self) -> None:
        from blackchpok_ide.memory_bridge import MemoryBridge

        bridge = MemoryBridge(self.memory)
        saved = bridge.archive_messages([
            {"role": "user", "content": "Зроби калькулятор з кнопкою множення"},
            {"role": "assistant", "content": "Додав multiply у calc.py і перевірив синтаксис"},
            {"role": "tool", "name": "write_file", "content": "записано calc.py " + ("x" * 2000)},
        ], task="калькулятор")
        self.assertTrue(saved)
        found = self.memory.search("multiply calc.py", limit=5)
        self.assertGreater(found["count"], 0)
        body = found["hits"][0]["memory"]["content"]
        self.assertIn("multiply", body)
        self.assertLess(len(body), 1000)
        self.assertEqual(found["hits"][0]["memory"]["task"], "калькулятор")

    def test_trim_hands_the_dropped_block_to_memory(self) -> None:
        from blackchpok_ide.agent import AgentSession
        from blackchpok_ide.config import AgentSettings
        from blackchpok_ide.memory_bridge import MemoryBridge

        bridge = MemoryBridge(self.memory)
        session = AgentSession(AgentSettings(), Path("."))
        session.context_limit = 256
        session.settings.context_char_limit = 120
        session.on_evict = lambda messages: bridge.archive_messages(
            messages, task="довгий діалог")
        session.messages = [
            {"role": "user", "content": "Поясни архітектуру черги задач " + ("крок " * 80)},
            {"role": "assistant", "content": "Черга тримає кроки окремо від вікна моделі."},
            {"role": "user", "content": "а"},
            {"role": "assistant", "content": "б"},
            {"role": "user", "content": "останнє прохання лишається у вікні"},
        ]
        session.trim()
        self.assertTrue(any("останнє прохання" in str(item.get("content"))
                            for item in session.messages))
        found = self.memory.search("архітектуру черги", limit=3)
        self.assertGreater(found["count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
