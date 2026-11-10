"""Наскрізний прогін агента проти фейкового OpenAI-сервера.

Це єдина перевірка, яка показує, що ланцюг «питання → виклик інструмента →
результат → фінальна відповідь» справді живий: справжній ``AgentRunner``,
справжній ``ToolRegistry`` на справжній теці й справжній HTTP-сервер
(``tests/fake_llm.py``). Модель не потрібна.

Запуск: ``python tools/probe_agent_cycle.py`` — код виходу 1, якщо цикл
не дійшов до фінальної відповіді.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import fake_llm                                            # noqa: E402

from blackchpok_ide.agent import AgentRunner               # noqa: E402
from blackchpok_ide.agent_tools import ToolRegistry        # noqa: E402
from blackchpok_ide.config import AgentSettings, LLMSettings  # noqa: E402


def collect(runner: AgentRunner, timeout: float = 25.0) -> tuple[bool, str, list[str]]:
    """Дочекатись завершення ходу й зібрати події."""
    done = False
    text: list[str] = []
    errors: list[str] = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            event = runner.events.get(timeout=0.2)
        except Exception:                                   # noqa: BLE001 - порожня черга
            if not runner.busy:
                break
            continue
        kind = getattr(event, "kind", "")
        if kind in ("done", "finished", "final"):
            done = True
        payload = getattr(event, "text", "")
        if payload:
            text.append(str(payload))
        if kind in ("error", "failed"):
            errors.append(str(payload))
        if getattr(event, "final", False):
            break
    return done, "\n".join(text), errors


def main() -> int:
    workspace = Path(tempfile.mkdtemp(prefix="probe-agent-"))
    (workspace / "app.py").write_text("def greet(n):\n    return n\n", encoding="utf-8")
    server, port = fake_llm.start(0)
    try:
        runner = AgentRunner(
            ToolRegistry(workspace),
            LLMSettings(base_url=f"http://127.0.0.1:{port}/v1", api_key="local",
                        model="fake-coder", auto_detect=False),
            AgentSettings(max_steps=6, stream=False, confirm_commands=False),
            workspace,
        )
        print("busy перед стартом:", runner.busy)
        runner.start("покажи файли в проєкті")
        done, text, errors = collect(runner)
        print("завершено:", done, "| busy:", runner.busy)
        print("подій тексту:", len(text))
        preview = text.strip().replace("\n", " ")[:200]
        print("відповідь:", preview or "—")
        if errors:
            print("помилки:", errors[:3])
        calls = fake_llm.STATE["calls"]
        print("запитів до сервера:", calls)
        ok = done and calls >= 2 and bool(text.strip()) and not errors
        print("ЦИКЛ:", "OK" if ok else "ПРОБЛЕМА")
        return 0 if ok else 1
    finally:
        server.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
