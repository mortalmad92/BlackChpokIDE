"""Наскрізна перевірка НОВИХ шарів: план, пам'ять, оркестратор, відповідь.

Без моделі й без вікна: перевіряється саме те, що додано в цьому циклі
робіт — чи справді план будується, чи пам'ять підкладає факти, чи зміни
потрапляють у пам'ять лише після підтвердження інструментом.

Запуск: .venv\\Scripts\\python.exe tests\\test_new_layers_live.py
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import (  # noqa: E402
    conversation,
    intent_engine,
    memory_bridge,
    planning,
    response_engine,
    tool_orchestrator,
    tool_specs,
)
from blackchpok_ide.agent_tools import ToolRegistry  # noqa: E402

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures += 1


class FakeMemory:
    """Пам'ять без бази: той самий інтерфейс, що й у NEUROMESH."""

    def __init__(self) -> None:
        self.hits = [
            {"memory": {"content": "Проєкт BLACKCHPOK — Tkinter IDE, Python 3.14",
                        "kind": "fact", "source": "чат 12.10"}},
            {"memory": {"content": "Контекст локальної моделі 8192 токени",
                        "kind": "decision", "source": "bench"}},
        ]
        self.constraints_hits = [
            {"memory": {"content": "Ніколи не видаляти старі чати",
                        "kind": "constraint", "source": "користувач"}},
        ]
        self.stored: list[dict] = []
        self.turns: list[dict] = []

    def search(self, query, *, limit=12, kinds=None, task="", files=None):
        source = self.constraints_hits if kinds and "constraint" in kinds else self.hits
        return {"hits": source[:limit], "count": len(source)}

    def remember(self, content, *, kind="fact", source="", confidence=0.5,
                 files=None, task="", tags=None):
        self.stored.append({"content": content, "kind": kind,
                            "files": list(files or [])})
        return {"id": f"m{len(self.stored)}"}

    def record_task(self, task, action, *, status="ok", detail="",
                    files=None, tools=None):
        self.turns.append({"task": task, "status": status})


def main() -> int:
    folder = Path(tempfile.mkdtemp())
    (folder / "calc.py").write_text(
        '"""Калькулятор."""\n\n\ndef add(a, b):\n    return a + b\n',
        encoding="utf-8")

    # ── 1. План із кадру наміру ───────────────────────────────────────────
    frame = intent_engine.frame(
        "перероби збереження чатів, тільки щоб старі не видалялись")
    check("обмеження розпізнано", "не видаляти наявні дані" in frame.constraints,
          str(frame.constraints))
    steps = planning.build_plan(frame)
    check("план побудовано без моделі", len(steps) >= 3, f"{len(steps)} кроків")
    check("план має перевірку", any(step.check for step in steps))
    check("обмеження стало кроком",
          any("старі дані" in step.title.lower() for step in steps),
          " | ".join(step.title for step in steps))
    text = planning.plan_as_text(steps)
    check("план без JSON", "{" not in text, text.splitlines()[1] if text else "")

    # ── 2. Пам'ять підкладає контекст ─────────────────────────────────────
    memory = FakeMemory()
    bridge = memory_bridge.MemoryBridge(memory)
    check("пам'ять доступна", bridge.ready())

    state = conversation.ConversationState()
    state.observe_user_message("перероби збереження чатів", frame)
    snapshot = bridge.snapshot("збереження чатів", task=state.goal, window=8192)
    check("факти з пам'яті знайдено", len(snapshot.memories) == 2,
          str(snapshot.memories[:1]))
    constraints = bridge.constraints()
    check("обмеження проєкту прочитано", bool(constraints), str(constraints))
    snapshot.constraints.extend(constraints)
    added = bridge.apply_to_state(snapshot, state)
    check("обмеження додано у стан", added >= 1, str(state.constraints))
    block = snapshot.prompt_block()
    check("контекст пам'яті без JSON", "{" not in block and block.strip())
    check("опис для журналу", "спогадів" in memory_bridge.describe_snapshot(snapshot))

    # ── 3. Оркестратор виконує справжні інструменти ───────────────────────
    registry = ToolRegistry(folder)
    specs = tool_specs.specs_for_schemas(registry.tool_schemas())
    engine = tool_orchestrator.Orchestrator(registry.call, specs)
    read = engine.run("read_file", {"path": "calc.py"})
    check("read_file виконано", read.ok and "return a + b" in read.output)
    write = engine.run("write_file", {
        "path": "calc.py",
        "content": '"""Калькулятор."""\n\n\ndef add(a, b):\n    return a + b\n\n\n'
                   'def mul(a, b):\n    return a * b\n',
    })
    check("write_file змінив файл", write.ok, write.output[:40].replace("\n", " "))
    check("файл справді містить зміну",
          "def mul" in (folder / "calc.py").read_text(encoding="utf-8"))
    check_step = engine.run("python_check", {"path": "calc.py"})
    check("python_check пройшов", check_step.ok, check_step.output[:40])

    # ── 4. У пам'ять іде лише підтверджене ────────────────────────────────
    remembered = bridge.remember_fact(
        "Змінено: calc.py (завдання: правка збереження)",
        kind="change", source="агент: підтверджено інструментом",
        files=["calc.py"])
    check("підтверджена зміна збережена", remembered and memory.stored,
          str(memory.stored[:1]))
    check("запис має тип change", memory.stored[0]["kind"] == "change")
    check("запис має файл", memory.stored[0]["files"] == ["calc.py"])
    recorded = bridge.record_turn(task="правка збереження", action="готово",
                                  files=["calc.py"])
    check("хід записано в історію", recorded and memory.turns)

    # ── 5. Людська відповідь ──────────────────────────────────────────────
    answer = response_engine.final_answer("", [read, write, check_step])
    check("відповідь зібрано", bool(answer.strip()), answer.splitlines()[0])
    check("у відповіді немає протоколу",
          not response_engine.looks_like_raw_protocol(answer))
    check("відповідь згадує змінений файл", "calc.py" in answer)

    print()
    print("Нові шари:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    started = time.perf_counter()
    code = main()
    print(f"(перевірка зайняла {time.perf_counter() - started:.2f} с)")
    raise SystemExit(code)
