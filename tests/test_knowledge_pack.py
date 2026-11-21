"""Тести пакета знань проєкту: перевірені факти для довгострокової пам'яті.

Головна вимога, яку ці тести охороняють: у пам'ять НЕ потрапляє факт, який
не підтверджується справжнім файлом проєкту. Пам'ять із вигаданими фактами
гірша за порожню — модель спирається на них упевнено.

Запуск: python -m unittest tests.test_knowledge_pack -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import knowledge_pack  # noqa: E402


class FakeMemory:
    """Підроблена пам'ять із тим самим контрактом, що й Neuromesh."""

    def __init__(self, *, ready: bool = True, duplicate: bool = False) -> None:
        self.items: list[dict[str, Any]] = []
        self._ready = ready
        self._duplicate = duplicate

    def ready(self) -> bool:
        return self._ready

    def remember(self, content: str, **kwargs: Any) -> dict[str, Any]:
        duplicate = any(item["content"] == content for item in self.items)
        self.items.append({"content": content, **kwargs})
        return {"created": not duplicate, "duplicate": duplicate or self._duplicate,
                "memory": {"id": f"m{len(self.items)}"}}


def make_project(files: dict[str, str] | None = None) -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "tests").mkdir()
    for name, body in (files or {}).items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return root


class TestChecks(unittest.TestCase):
    """Перевірки фактів: проходять лише на справжніх файлах."""

    def test_fact_without_check_always_survives(self) -> None:
        fact = knowledge_pack.Fact(key="x", content="щось")
        self.assertEqual(
            [item.key for item in knowledge_pack.knowledge_facts(make_project(), facts=[fact])],
            ["x"])

    def test_missing_file_marks_fact_stale(self) -> None:
        fact = knowledge_pack.Fact(
            key="need-file", content="текст",
            check=knowledge_pack._exists("немає.py"))
        root = make_project()
        self.assertEqual(knowledge_pack.knowledge_facts(root, facts=[fact]), [])
        self.assertEqual([item.key for item in
                          knowledge_pack.stale_facts(root, facts=[fact])],
                         ["need-file"])

    def test_has_check_requires_all_needles(self) -> None:
        root = make_project({"mod.py": "class A:\n    pass\n"})
        full = knowledge_pack.Fact(key="full", content="x",
                                   check=knowledge_pack._has("mod.py", "class A"))
        partial = knowledge_pack.Fact(key="partial", content="x",
                                      check=knowledge_pack._has("mod.py", "class A",
                                                                "def b"))
        self.assertEqual([f.key for f in
                          knowledge_pack.knowledge_facts(root, facts=[full])], ["full"])
        self.assertEqual(knowledge_pack.knowledge_facts(root, facts=[partial]), [])

    def test_missing_root_gives_nothing(self) -> None:
        self.assertEqual(knowledge_pack.knowledge_facts(Path(tempfile.mkdtemp()) / "немає"),
                         [])

    def test_none_root_skips_checks(self) -> None:
        self.assertTrue(knowledge_pack.knowledge_facts(None))


class TestRealProject(unittest.TestCase):
    """Справжній проєкт: факти мусять бути правдивими САМЕ для нього."""

    def test_all_shipped_facts_are_true_for_this_repo(self) -> None:
        facts = knowledge_pack.knowledge_facts(ROOT)
        stale = [fact.key for fact in knowledge_pack.stale_facts(ROOT)]
        self.assertEqual(stale, [], f"факти не підтверджуються файлами: {stale}")
        self.assertGreaterEqual(len(facts), 10)

    def test_facts_point_at_existing_files(self) -> None:
        for fact in knowledge_pack.KNOWLEDGE:
            for name in fact.files:
                self.assertTrue((ROOT / name).exists(),
                                f"{fact.key}: файлу {name} немає")

    def test_tests_command_fact_mentions_unit_test_dir(self) -> None:
        fact = next(item for item in knowledge_pack.KNOWLEDGE
                    if item.key == "tests.no_init")
        self.assertIn("-s tests", fact.content)
        self.assertIn("Ran 0 tests", fact.content)

    def test_keys_are_unique(self) -> None:
        keys = [fact.key for fact in knowledge_pack.KNOWLEDGE]
        self.assertEqual(len(keys), len(set(keys)), keys)


class TestSeed(unittest.TestCase):
    """Запис у пам'ять: ідемпотентний і не пише неправдиве."""

    def test_seed_writes_only_verified_facts(self) -> None:
        root = make_project({"mod.py": "class A:\n    pass\n"})
        good = knowledge_pack.Fact(key="good", content="правда",
                                   check=knowledge_pack._exists("mod.py"))
        bad = knowledge_pack.Fact(key="bad", content="вигадка",
                                  check=knowledge_pack._exists("немає.py"))
        memory = FakeMemory()
        report = knowledge_pack.seed(memory, root, facts=[good, bad])
        self.assertEqual(report.added, 1)
        self.assertEqual(report.stale, ["bad"])
        self.assertEqual([item["content"] for item in memory.items], ["правда"])

    def test_seed_is_idempotent(self) -> None:
        root = make_project({"mod.py": "x = 1\n"})
        fact = knowledge_pack.Fact(key="k", content="факт",
                                   check=knowledge_pack._exists("mod.py"))
        memory = FakeMemory()
        first = knowledge_pack.seed(memory, root, facts=[fact])
        second = knowledge_pack.seed(memory, root, facts=[fact])
        self.assertEqual(first.added, 1)
        self.assertEqual(second.added, 0)
        self.assertEqual(second.confirmed, 1)

    def test_seed_marks_provenance(self) -> None:
        memory = FakeMemory()
        fact = knowledge_pack.Fact(key="arch.agent", content="факт")
        knowledge_pack.seed(memory, None, facts=[fact])
        self.assertEqual(memory.items[0]["provenance"], "knowledge:arch.agent")
        self.assertEqual(memory.items[0]["source"], knowledge_pack.SOURCE)

    def test_seed_without_memory_does_not_crash(self) -> None:
        report = knowledge_pack.seed(None, None, facts=[
            knowledge_pack.Fact(key="k", content="x")])
        self.assertGreaterEqual(report.failed, 1)

    def test_seed_reports_unavailable_memory(self) -> None:
        memory = FakeMemory(ready=False)
        report = knowledge_pack.seed(memory, None, facts=[
            knowledge_pack.Fact(key="k", content="x")])
        self.assertEqual(report.added, 0)
        self.assertEqual(report.failed, 1)

    def test_broken_remember_does_not_break_the_rest(self) -> None:
        class Partly:
            def __init__(self) -> None:
                self.saved: list[str] = []

            def ready(self) -> bool:
                return True

            def remember(self, content: str, **_kwargs: Any) -> dict[str, Any]:
                if "погано" in content:
                    raise RuntimeError("навмисно")
                self.saved.append(content)
                return {"created": True}

        memory = Partly()
        report = knowledge_pack.seed(memory, None, facts=[
            knowledge_pack.Fact(key="a", content="погано"),
            knowledge_pack.Fact(key="b", content="добре")])
        self.assertEqual(report.added, 1)
        self.assertEqual(report.failed, 1)
        self.assertEqual(memory.saved, ["добре"])

    def test_dry_run_writes_nothing(self) -> None:
        root = make_project({"mod.py": "x = 1\n"})
        memory = FakeMemory()
        fact = knowledge_pack.Fact(key="k", content="факт",
                                   check=knowledge_pack._exists("mod.py"))
        report = knowledge_pack.seed(memory, root, facts=[fact], dry_run=True)
        self.assertEqual(report.added, 1)
        self.assertEqual(memory.items, [])

    def test_describe_is_human(self) -> None:
        report = knowledge_pack.SeedReport(added=3, confirmed=2, stale=["x"])
        text = report.describe()
        self.assertIn("3 нових", text)
        self.assertIn("застарілих", text)


class TestFactsForFiles(unittest.TestCase):
    """Факти за файлами — для підказки перед дією."""

    def test_finds_fact_by_file(self) -> None:
        fact = knowledge_pack.Fact(key="k", content="x", files=("pkg/mod.py",))
        found = knowledge_pack.facts_for_files(["pkg/mod.py"], facts=[fact])
        self.assertEqual([item.key for item in found], ["k"])

    def test_windows_separators_match(self) -> None:
        fact = knowledge_pack.Fact(key="k", content="x", files=("pkg/mod.py",))
        found = knowledge_pack.facts_for_files([r"pkg\mod.py"], facts=[fact])
        self.assertEqual([item.key for item in found], ["k"])

    def test_empty_paths_give_nothing(self) -> None:
        self.assertEqual(knowledge_pack.facts_for_files([]), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
