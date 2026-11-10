"""Живий прогін на СПРАВЖНЬОМУ сервері: модель, контекст, лінивий реєстр.

Це не юніт-тест: тут справжній llama-server, справжня модель і справжні
файли на диску. Перевіряються сценарії A/C/D/F з технічного завдання.

Запуск: python tools/check_live_lazy.py
Сервер має бути вже піднятий (tools/start_check_server.py).
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

BASE = "http://127.0.0.1:8080/v1"
API_KEY = "local"
MODEL = "qwen25vl3b"

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def scenario_a_state() -> None:
    """A: сервер доступний, назва моделі й контекст — реальні."""
    print("\n=== Сценарій A: запуск моделі й стан ===")
    from blackchpok_ide import server_state

    state = server_state.probe_server(BASE, api_key=API_KEY)
    check("сервер справді доступний", state.reachable)
    check("модель повідомлена сервером", bool(state.model_loaded),
          state.model_loaded)
    check("контекст узято з сервера", state.context > 0,
          f"{state.context} ({state.context_source})")
    check("джерело контексту — /props", "props" in state.context_source,
          state.context_source)
    check("порт визначено", state.port == 8080, str(state.port))

    # Реальний запит до моделі.
    from blackchpok_ide.llm_client import LLMClient

    client = LLMClient(BASE, MODEL, API_KEY, timeout=120)
    result = client.chat([{"role": "user",
                           "content": "Відповідай одним словом: працюєш?"}])
    text = (result.content or "").strip()
    check("модель відповіла на повідомлення", bool(text), repr(text[:60]))
    usage = getattr(result, "usage", None) or {}
    print(f"      usage: {json.dumps(usage, ensure_ascii=False)[:160]}")


def scenario_b_switch() -> None:
    """B: перемикання моделі скидає контекст і реєстр."""
    print("\n=== Сценарій B: інвалідація після перемикання ===")
    from blackchpok_ide.agent import AgentRunner
    from blackchpok_ide.agent_tools import ToolRegistry
    from blackchpok_ide.config import AgentSettings, LLMSettings

    llm = LLMSettings(base_url=BASE, model=MODEL, api_key=API_KEY, timeout=120)
    runner = AgentRunner(ToolRegistry(ROOT), llm, AgentSettings(), ROOT)
    runner.settings_ref = None
    runner.tools_enabled = True
    runner.adopt_context_window(props_ctx=16384)
    before = runner.session.context_limit
    check("вікно застосовано", before == 16384, str(before))
    runner.invalidate_tool_cache(reason="перемикання моделі")
    check("кеш схем скинуто",
          runner.tool_registry_state()["total"] == 0,
          str(runner.tool_registry_state()))
    runner.adopt_context_window(props_ctx=32768)
    after = runner.session.context_limit
    check("нове вікно застосовано", after == 32768, str(after))
    check("нове вікно відрізняється", after != before)


def scenario_c_lazy() -> None:
    """C: компактний реєстр, динамічне завантаження, реальний виклик."""
    print("\n=== Сценарій C: лінивий реєстр інструментів ===")
    from blackchpok_ide.agent import AgentRunner
    from blackchpok_ide.agent_tools import TOOL_SCHEMAS, ToolRegistry
    from blackchpok_ide.config import AgentSettings, LLMSettings

    llm = LLMSettings(base_url=BASE, model=MODEL, api_key=API_KEY, timeout=120)
    runner = AgentRunner(ToolRegistry(ROOT), llm, AgentSettings(), ROOT)
    runner.settings_ref = None
    runner.tools_enabled = True
    runner.adopt_context_window(props_ctx=32768)

    schemas = runner.tool_schemas()
    sent = {s["function"]["name"] for s in schemas}
    registry = runner.tool_registry_state()
    print(f"      інструментів у реєстрі: {registry['total']}")
    print(f"      схем у запиті: {len(sent)}")
    print(f"      причина: {registry['reason']}")
    check("реєстр містить усі вбудовані інструменти",
          registry["total"] >= len(TOOL_SCHEMAS), str(registry["total"]))
    check("схем у запиті менше, ніж інструментів",
          len(sent) < registry["total"], f"{len(sent)} < {registry['total']}")

    # Пошук → завантаження → реальний виклик.
    found = runner.call_tool("find_tools", {"query": "скріншот"})
    check("find_tools знаходить інструмент", found.ok, found.output[:80])

    target = "list_screenshots"
    loaded = runner.call_tool("load_tools", {"names": [target]})
    check("load_tools завантажує схему", loaded.ok, loaded.output[:80])
    after = {s["function"]["name"] for s in runner.tool_schemas()}
    check("схема додана до наступного запиту", target in after,
          f"{target} in sent={target in after}")

    # Виклик БЕЗ завантаження схеми — головна властивість.
    ran = runner.call_tool("run_tool", {"name": "list_screenshots",
                                        "arguments": {"limit": 2}})
    check("run_tool виконує без завантаженої схеми", ran.ok, ran.output[:80])

    # Реальний файловий інструмент через run_tool.
    ran2 = runner.call_tool("run_tool", {"name": "list_dir",
                                         "arguments": {"path": "blackchpok_ide"}})
    check("run_tool виконує файлову дію", ran2.ok, ran2.output[:80])


def scenario_d_budget() -> None:
    """D: бюджет розподіляється, запит не переповнює вікно."""
    print("\n=== Сценарій D: контекстний бюджет ===")
    from blackchpok_ide.agent import AgentRunner
    from blackchpok_ide.agent_tools import ToolRegistry
    from blackchpok_ide.config import AgentSettings, LLMSettings

    llm = LLMSettings(base_url=BASE, model=MODEL, api_key=API_KEY, timeout=120)
    runner = AgentRunner(ToolRegistry(ROOT), llm, AgentSettings(), ROOT)
    runner.settings_ref = None
    runner.tools_enabled = True
    budget = runner.adopt_context_window(props_ctx=32768)
    print(f"      бюджет: {budget.text()}")
    total = (budget.answer + budget.history + budget.tools + budget.system
             + budget.safety + budget.payload)
    check("частини вміщуються у вікно", total <= 32768 + 1,
          f"{total} <= 32768")
    check("місце під відповідь є", budget.answer >= 2048, str(budget.answer))

    # Історія не має роздувати запит.
    runner.session.add_user("x" * 60_000)
    runner.session.trim()
    estimate = runner.session._estimate_tokens()
    check("велике повідомлення обрізано під вікно", estimate <= 32768,
          f"{estimate} <= 32768")


def scenario_f_realfile() -> None:
    """F: реальна робота агента з файлами проєкту (модель сама обирає дію)."""
    print("\n=== Сценарій F: реальна робота агента з файлом ===")
    import queue as queue_module

    from blackchpok_ide.agent import AgentRunner
    from blackchpok_ide.agent_tools import ToolRegistry
    from blackchpok_ide.config import AgentSettings, LLMSettings

    folder = Path(tempfile.mkdtemp(prefix="bc-live-"))
    (folder / "calc.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8")
    print(f"      тека: {folder}")

    llm = LLMSettings(base_url=BASE, model=MODEL, api_key=API_KEY, timeout=180)
    settings = AgentSettings(max_steps=8, confirm_commands=False,
                             offline_fallback=False)
    runner = AgentRunner(ToolRegistry(folder), llm, settings, folder)
    runner.settings_ref = None
    runner.tools_enabled = True
    runner.set_permission_mode = getattr(runner, "set_permission_mode", None)
    from blackchpok_ide import permissions

    runner.permission_mode = permissions.WORKSPACE

    goal = ("У файлі calc.py функція add має додавати числа, а не віднімати. "
            "Виправ це: прочитай файл і заміни тіло функції через edit_file.")
    print(f"      запит: {goal[:80]}…")
    runner.start(goal)

    events = []
    done = {"ok": None}
    deadline = time.time() + 240
    while time.time() < deadline and done["ok"] is None:
        try:
            event = runner.events.get(timeout=0.5)
        except queue_module.Empty:
            continue
        events.append(event)
        if event.kind == "done":
            done["ok"] = bool(event.data.get("ok", True))
        if event.kind == "error":
            print(f"      error: {event.text[:120]}")

    used = [e.data.get("name", "") for e in events if e.kind == "tool_call"]
    print(f"      викликано: {used}")
    check("агент завершив хід", done["ok"] is not None)
    check("агент викликав інструменти", bool(used), ", ".join(used[:6]))

    body = (folder / "calc.py").read_text(encoding="utf-8", errors="replace")
    print(f"      вміст: {body.strip()!r}")
    # Перевіряємо САМЕ семантику: функція тепер додає.
    fixed = "returna+b" in body.replace(" ", "").replace("\t", "")
    check("файл СПРАВДІ виправлено на диску", fixed, body.strip()[:80])
    check("функція не загубилась", "def add" in body)


def main() -> int:
    from blackchpok_ide import server_state

    state = server_state.probe_server(BASE, api_key=API_KEY, timeout=3)
    if not state.reachable:
        print(f"[SKIP] Сервер {BASE} не відповідає: {state.error}")
        return 0
    print(f"Сервер: {state.note()}")

    scenario_a_state()
    scenario_b_switch()
    scenario_c_lazy()
    scenario_d_budget()
    scenario_f_realfile()

    print()
    print("Живий прогін: " + ("УСПІШНО" if not failures
                              else f"ЗБОЇВ: {failures}"))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
