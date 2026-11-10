"""Наскрізний тест агента проти фейкового OpenAI-сервера.

Перевіряє: запит → tool_call → виконання інструмента → фінальна відповідь,
а також офлайн-фолбек, коли сервер віддає помилку.
"""

from __future__ import annotations

import os
import queue
import shutil
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from blackchpok_ide.agent import AgentRunner, AgentEvent  # noqa: E402
from blackchpok_ide.agent_tools import ToolRegistry  # noqa: E402
from blackchpok_ide.config import AgentSettings, LLMSettings  # noqa: E402
from blackchpok_ide.llm_client import LLMClient  # noqa: E402
import fake_llm  # noqa: E402

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def drain(runner: AgentRunner, timeout: float = 30) -> list[AgentEvent]:
    events: list[AgentEvent] = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            event = runner.events.get(timeout=0.2)
        except queue.Empty:
            if not runner.busy:
                break
            continue
        events.append(event)
        if event.kind == "done":
            break
    return events


def main() -> int:
    folder = ROOT / ".buildtmp" / f"e2e-{uuid.uuid4().hex[:8]}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "hello.py").write_text("def hello():\n    return 1\n", encoding="utf-8")

    server, port = fake_llm.start(0)
    base_url = f"http://127.0.0.1:{port}/v1"
    print(f"фейкова модель: {base_url}")

    # 1. клієнт бачить моделі
    client = LLMClient(base_url, "fake-coder", timeout=10)
    ok, detail = client.ping()
    check("ping сервера моделі", ok, detail)

    # 2. ручний tool-call цикл
    result = client.chat([{"role": "user", "content": "покажи файли"}], tools=[{"type": "function"}])
    check("модель повернула tool_call", bool(result.tool_calls), str(result.tool_calls)[:80])

    # 3. повний цикл агента
    fake_llm.STATE["calls"] = 0
    registry = ToolRegistry(folder)
    settings = AgentSettings(max_steps=4, offline_fallback=False)
    runner = AgentRunner(
        registry,
        LLMSettings(base_url=base_url, model="fake-coder", timeout=20),
        settings,
        folder,
    )
    runner.start("покажи файли")
    events = drain(runner)
    kinds = [event.kind for event in events]
    check("агент викликав інструмент", "tool_call" in kinds, ",".join(kinds))
    check("агент отримав результат", "tool_result" in kinds)
    assistant = [e for e in events if e.kind == "assistant"]
    check("агент дав відповідь", bool(assistant), assistant[-1].text[:60] if assistant else "")
    tool_events = [e for e in events if e.kind == "tool_call"]
    check("викликано list_dir", tool_events and tool_events[0].data.get("name") == "list_dir",
          str(tool_events[0].data) if tool_events else "")
    check("сервер викликано двічі", fake_llm.STATE["calls"] == 2, str(fake_llm.STATE["calls"]))
    check("подія done надіслана", kinds[-1] == "done")

    # 4. помилка сервера + офлайн-фолбек
    fake_llm.STATE["fail"] = True
    runner2 = AgentRunner(
        registry,
        LLMSettings(base_url=base_url, model="fake-coder", timeout=10),
        AgentSettings(offline_fallback=True),
        folder,
    )
    runner2.start("покажи файли")
    events2 = drain(runner2)
    offline = [e for e in events2 if e.kind == "assistant" and e.data.get("offline")]
    check("офлайн-фолбек спрацював", bool(offline), str([e.kind for e in events2]))

    # 5. без моделі — одразу офлайн
    runner3 = AgentRunner(registry, LLMSettings(model=""), AgentSettings(offline_fallback=True), folder)
    runner3.start("дерево проєкту")
    events3 = drain(runner3)
    check("працює без моделі", any(e.kind == "assistant" for e in events3))

    # 6. ліміт кроків
    fake_llm.STATE["fail"] = False
    fake_llm.STATE["mode"] = "loop"
    runner4 = AgentRunner(
        registry,
        LLMSettings(base_url=base_url, model="fake-coder", timeout=10),
        AgentSettings(max_steps=2, offline_fallback=False),
        folder,
    )
    runner4.start("покажи файли")
    events4 = drain(runner4)
    check("цикл обмежено кроками", any("ліміт" in e.text for e in events4 if e.kind == "status"),
          str([e.text for e in events4 if e.kind == "status"])[:100])

    server.shutdown()
    shutil.rmtree(folder, ignore_errors=True)
    print()
    print("E2E-тест:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


# ── unittest-обгортка (додано 10.11.2026) ──────────────────────────────────
# Для `python -m unittest discover` ці перевірки раніше були невидимі:
# файл — скрипт із власним main(), а не TestCase. Тепер discover запускає
# його й падає, якщо main() повернув ненульовий код. Запуск як скрипт
# (`python tests/test_agent_e2e.py`) поводиться як раніше.
import unittest as _unittest  # noqa: E402


class _ScriptSuite(_unittest.TestCase):
    def test_script_passes(self) -> None:
        code = main()
        self.assertEqual(code, 0, f"main() повернув {code}")
