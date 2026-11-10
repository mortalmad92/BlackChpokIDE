"""Тести планування з IntentFrame та інтеграції з NEUROMESH.

Перевіряємо те, чого раніше не було:

* план будується з кадру наміру БЕЗ моделі — з кроками, залежностями й
  перевірками;
* обмеження користувача стають окремим кроком, а не рядком у промпті;
* пам'ять підкладає факти й обмеження в контекст ДО звернення до моделі;
* у пам'ять іде лише те, що підтверджено результатом інструмента.

Запуск: python -m unittest tests.test_planning_and_memory -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import intent_engine, memory_bridge, planning  # noqa: E402


class TestPlanBuilding(unittest.TestCase):
    """План із кадру наміру: кроки, залежності, перевірки."""

    def test_simple_request_has_check_step(self) -> None:
        steps = planning.build_plan(intent_engine.frame("створи калькулятор"))
        self.assertTrue(steps)
        self.assertTrue(any(step.check for step in steps),
                        "план без перевірки — це обіцянка, а не робота")

    def test_two_files_give_two_work_steps(self) -> None:
        frame = intent_engine.frame(
            "у файлі calc.py додай множення, а в файлі notes.txt запиши що зроблено")
        steps = planning.build_plan(frame)
        titles = " | ".join(step.title for step in steps)
        self.assertIn("calc.py", titles)
        self.assertIn("notes.txt", titles)

    def test_debug_plan_starts_with_reproduction(self) -> None:
        steps = planning.build_plan(
            intent_engine.frame("не працює кнопка збереження, виправ"))
        titles = [step.title.lower() for step in steps]
        self.assertTrue(any("причин" in title or "відтвор" in title
                            for title in titles),
                        f"немає кроку пошуку причини: {titles}")

    def test_dependencies_point_to_existing_steps(self) -> None:
        steps = planning.build_plan(
            intent_engine.frame("не працює кнопка збереження, виправ"))
        total = len(steps)
        for step in steps:
            for dependency in step.depends_on:
                self.assertGreaterEqual(dependency, 1, step.title)
                self.assertLessEqual(dependency, total, step.title)

    def test_no_self_dependency(self) -> None:
        for text in ("створи калькулятор",
                     "не працює кнопка збереження, виправ",
                     "у файлі calc.py додай множення"):
            steps = planning.build_plan(intent_engine.frame(text))
            for index, step in enumerate(steps, start=1):
                self.assertNotIn(index, step.depends_on,
                                 f"крок {index} залежить від себе: {step.title}")

    def test_constraints_become_steps(self) -> None:
        frame = intent_engine.frame(
            "перероби збереження чатів, тільки щоб старі не видалялись")
        steps = planning.build_plan(frame)
        titles = " | ".join(step.title for step in steps).lower()
        self.assertTrue("старі дані" in titles or "наявна поведінка" in titles,
                        f"обмеження не стало кроком: {titles}")

    def test_conversation_gives_no_plan(self) -> None:
        self.assertEqual(planning.build_plan(intent_engine.frame("привіт")), [])

    def test_should_plan_is_false_for_one_file(self) -> None:
        frame = intent_engine.frame("створи калькулятор")
        self.assertFalse(planning.should_plan(frame),
                         "просте завдання не потребує плану з кількох кроків")

    def test_should_plan_true_for_two_files(self) -> None:
        frame = intent_engine.frame(
            "у файлі calc.py додай множення, а в файлі notes.txt запиши")
        self.assertTrue(planning.should_plan(frame))

    def test_plan_is_bounded(self) -> None:
        files = ", ".join(f"file{index}.py" for index in range(30))
        frame = intent_engine.frame(f"зміни {files}")
        steps = planning.build_plan(frame)
        self.assertLessEqual(len(steps), planning.MAX_PLAN_STEPS)

    def test_plan_text_has_no_json(self) -> None:
        steps = planning.build_plan(
            intent_engine.frame("не працює кнопка збереження, виправ"))
        text = planning.plan_as_text(steps)
        self.assertIn("План роботи:", text)
        self.assertNotIn("{", text)

    def test_prompt_block_includes_constraints(self) -> None:
        frame = intent_engine.frame(
            "перероби збереження чатів, тільки щоб старі не видалялись")
        steps = planning.build_plan(frame)
        block = planning.plan_prompt_block(frame, steps)
        self.assertIn("Обмеження", block)
        self.assertIn("не видаляти наявні дані", block)

    def test_order_keeps_all_steps(self) -> None:
        steps = planning.build_plan(
            intent_engine.frame("не працює кнопка збереження, виправ"))
        ordered = planning.order_steps(steps)
        self.assertEqual(len(ordered), len(steps))


class FakeMemory:
    """Підроблений сервіс пам'яті: такий самий інтерфейс, без бази."""

    def __init__(self, hits=None, constraints=None) -> None:
        self.hits = hits or []
        self.constraint_hits = constraints or []
        self.stored: list[dict] = []
        self.turns: list[dict] = []
        self.search_calls: list[str] = []

    def search(self, query, *, limit=12, kinds=None, task="", files=None):
        self.search_calls.append(query)
        source = self.constraint_hits if kinds and "constraint" in kinds else self.hits
        return {"query": query, "hits": list(source)[:limit], "count": len(source)}

    def remember(self, content, *, kind="fact", source="", confidence=0.5,
                 files=None, task="", tags=None):
        self.stored.append({"content": content, "kind": kind, "source": source,
                            "files": list(files or [])})
        return {"id": f"m{len(self.stored)}"}

    def record_task(self, task, action, *, status="ok", detail="",
                    files=None, tools=None):
        self.turns.append({"task": task, "action": action, "status": status})


def _hit(content: str, *, kind: str = "fact", source: str = "чат") -> dict:
    return {"memory": {"content": content, "kind": kind, "source": source}}


class TestMemoryBridge(unittest.TestCase):
    """Пам'ять бере участь у розумінні запиту."""

    def test_not_ready_without_service(self) -> None:
        bridge = memory_bridge.MemoryBridge(None)
        self.assertFalse(bridge.ready())
        self.assertTrue(bridge.snapshot("що тут").empty)

    def test_snapshot_reads_search(self) -> None:
        service = FakeMemory(hits=[_hit("Проєкт — Tkinter IDE", kind="fact"),
                                   _hit("Поріг контексту 8192", kind="decision")])
        bridge = memory_bridge.MemoryBridge(service)
        snapshot = bridge.snapshot("як влаштований проєкт")
        self.assertEqual(len(snapshot.memories), 2)
        self.assertIn("Tkinter IDE", snapshot.memories[0])
        self.assertIn("fact", snapshot.memories[0])

    def test_snapshot_limits_results(self) -> None:
        service = FakeMemory(hits=[_hit(f"факт {index}")
                                   for index in range(20)])
        bridge = memory_bridge.MemoryBridge(service)
        snapshot = bridge.snapshot("щось", limit=3)
        self.assertEqual(len(snapshot.memories), 3)

    def test_constraints_are_separate(self) -> None:
        service = FakeMemory(
            hits=[_hit("звичайний факт")],
            constraints=[_hit("ніколи не видаляти чати", kind="constraint")])
        bridge = memory_bridge.MemoryBridge(service)
        self.assertIn("ніколи не видаляти чати", " ".join(bridge.constraints()))

    def test_apply_to_state_adds_constraints(self) -> None:
        state = FakeState()
        snapshot = memory_bridge.MemorySnapshot(
            constraints=["ніколи не видаляти чати"])
        added = memory_bridge.MemoryBridge().apply_to_state(snapshot, state)
        self.assertEqual(added, 1)
        self.assertIn("ніколи не видаляти чати", " ".join(state.constraints))

    def test_apply_does_not_duplicate(self) -> None:
        state = FakeState()
        snapshot = memory_bridge.MemorySnapshot(constraints=["правило"])
        bridge = memory_bridge.MemoryBridge()
        bridge.apply_to_state(snapshot, state)
        added = bridge.apply_to_state(snapshot, state)
        self.assertEqual(added, 0)
        self.assertEqual(len(state.constraints), 1)

    def test_remember_fact_is_stored(self) -> None:
        service = FakeMemory()
        bridge = memory_bridge.MemoryBridge(service)
        self.assertTrue(bridge.remember_fact(
            "Змінено calc.py", kind="change", files=["calc.py"]))
        self.assertEqual(len(service.stored), 1)
        self.assertEqual(service.stored[0]["files"], ["calc.py"])

    def test_remember_rejects_empty(self) -> None:
        service = FakeMemory()
        bridge = memory_bridge.MemoryBridge(service)
        self.assertFalse(bridge.remember_fact("   "))
        self.assertEqual(service.stored, [])

    def test_record_turn_is_stored(self) -> None:
        service = FakeMemory()
        bridge = memory_bridge.MemoryBridge(service)
        self.assertTrue(bridge.record_turn(
            task="правка", action="готово", files=["calc.py"]))
        self.assertEqual(len(service.turns), 1)

    def test_service_failure_does_not_crash(self) -> None:
        class Broken:
            def search(self, *_args, **_kwargs):
                raise RuntimeError("база закрита")

        bridge = memory_bridge.MemoryBridge(Broken())
        snapshot = bridge.snapshot("щось")
        self.assertTrue(snapshot.empty)

    def test_prompt_block_is_readable(self) -> None:
        snapshot = memory_bridge.MemorySnapshot(
            memories=["Проєкт — Tkinter IDE"], constraints=["не видаляти чати"])
        block = snapshot.prompt_block()
        self.assertIn("Обмеження проєкту", block)
        self.assertIn("Що вже відомо", block)
        self.assertNotIn("{", block)

    def test_describe_snapshot(self) -> None:
        snapshot = memory_bridge.MemorySnapshot(memories=["a", "b"], tokens=42)
        text = memory_bridge.describe_snapshot(snapshot)
        self.assertIn("2 спогадів", text)
        self.assertIn("42", text)

    def test_project_context_is_preferred(self) -> None:
        """Коли є бюджет вікна, беремо project_context (він стежить за обсягом)."""
        used: list[int] = []

        class WithContext(FakeMemory):
            def project_context(self, *, query, window, task="", files=(),
                                kinds=None, max_share=0.15):
                used.append(window)
                bundle = FakeBundle()
                return bundle

        bridge = memory_bridge.MemoryBridge(WithContext())
        snapshot = bridge.snapshot("питання", window=8192)
        self.assertEqual(used, [8192])
        self.assertIn("критичне обмеження", " ".join(snapshot.constraints))
        self.assertIn("звичайний факт", " ".join(snapshot.memories))


class FakePiece:
    def __init__(self, text: str, *, critical: bool = False,
                 label: str = "", reason: str = "") -> None:
        self.text = text
        self.critical = critical
        self.label = label
        self.reason = reason


class FakeReport:
    def __init__(self) -> None:
        self.pieces = [FakePiece("критичне обмеження проєкту", critical=True,
                                 reason="обов'язкове обмеження проєкту"),
                       FakePiece("звичайний факт", label="fact")]
        self.dropped = [FakePiece("зайве")]
        self.used = 120
        self.budget = 1000
        self.exact = True


class FakeBundle:
    report = FakeReport()
    note = ""


class FakeState:
    """Мінімальний стан розмови (без залежності від conversation)."""

    def __init__(self) -> None:
        self.constraints: list[str] = []


if __name__ == "__main__":
    unittest.main(verbosity=2)
