"""Тести нових можливостей: черга, скіли, контекстна панель, MCP-конфіг.

Запуск:  python tests/test_features.py
Повертає 0, якщо все гаразд.
"""

from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import queue_engine, skills as skills_module  # noqa: E402
from blackchpok_ide.agent_tools import TOOL_SCHEMAS  # noqa: E402
from blackchpok_ide.llm_client import strip_tool_json  # noqa: E402

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def temp_dir() -> Path:
    path = ROOT / ".buildtmp" / f"feat-{uuid.uuid4().hex[:10]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# Черга завдань
# ─────────────────────────────────────────────────────────────────────────────

def test_queue() -> None:
    folder = temp_dir()
    try:
        path = folder / "queue.json"
        q = queue_engine.TaskQueue(path)
        check("порожня черга", q.counts()[queue_engine.PENDING] == 0)

        first = q.add("перша задача")
        second = q.add("  друга задача  ")
        check("додавання задач", len(q.tasks) == 2 and q.tasks[0] is first)
        check("текст обрізано", second is not None and second.text == "друга задача")
        check("порожнє завдання відхилено", q.add("   ") is None)

        nxt = q.next_pending()
        check("наступна задача — перша", nxt is not None and nxt.id == first.id)

        q.mark_running(first.id)
        check("задача виконується", q.get(first.id).status == queue_engine.RUNNING)
        check("поки виконується — наступної немає", q.next_pending() is None)

        q.mark_done(first.id, "результат")
        check("задача завершена", q.get(first.id).status == queue_engine.DONE)
        check("результат збережено", q.get(first.id).result == "результат")
        check("після завершення беремо наступну",
              q.next_pending() is not None and q.next_pending().id == second.id)

        q.mark_failed(second.id, "помилка")
        check("помилка задачі", q.get(second.id).status == queue_engine.FAILED)
        check("повтор помилки повертає в чергу", q.retry(second.id)
              and q.get(second.id).status == queue_engine.PENDING)

        q.set_paused(True)
        check("пауза зупиняє видачу", q.next_pending() is None)
        q.set_paused(False)
        check("після паузи знову видає", q.next_pending() is not None)

        # Одна задача виконується — її не можна видалити
        q.mark_running(second.id)
        check("зайняту задачу не видалити", q.remove(second.id) is False)
        q.mark_done(second.id, "ок")

        removed = q.clear_finished()
        check("прибирання завершених", removed == 2 and not q.tasks, f"{removed}")

        # Збереження/відновлення
        q.add("задача на перезапуск")
        restored = queue_engine.TaskQueue(path)
        check("черга переживає перезапуск",
              len(restored.tasks) == 1 and restored.tasks[0].text == "задача на перезапуск")

        # «Виконується» після падіння має стати знову очікуючою
        q.mark_running(restored.tasks[0].id)
        again = queue_engine.TaskQueue(path)
        check("зависла задача повертається в очікування",
              again.tasks[0].status == queue_engine.PENDING)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_split_batch() -> None:
    check("список з маркерами розбивається",
          queue_engine.split_batch("- одна\n- друга\n3. третя") == ["одна", "друга", "третя"])
    check("один рядок — одна задача", queue_engine.split_batch("просто задача") == ["просто задача"])
    check("порожній текст — порожній список", queue_engine.split_batch("   \n\n ") == [])


# ─────────────────────────────────────────────────────────────────────────────
# Скіли
# ─────────────────────────────────────────────────────────────────────────────

def test_skills() -> None:
    folder = temp_dir()
    try:
        name, description, body = skills_module.parse_skill(
            "---\nname: demo\ndescription: Опис демо\n---\n\nРоби щось корисне.\n",
            fallback_name="fallback",
        )
        check("заголовок скіла розібрано", name == "demo" and description == "Опис демо")
        check("тіло скіла без заголовка", body.strip() == "Роби щось корисне.")

        no_header = skills_module.parse_skill("Перший рядок опису\n\nДалі інструкція.",
                                              fallback_name="папка")
        check("без заголовка беремо назву теки й перший рядок",
              no_header[0] == "папка" and "Перший рядок" in no_header[1])

        path = skills_module.create_skill(folder, "Мій Скіл", "демонстрація", "1. крок")
        check("скіл створено", path.exists() and path.name == "SKILL.md", str(path))
        check("тека скіла з латинською назвою", path.parent.parent.name == "skills")

        skill = skills_module.load_skill(path)
        check("скіл читається", skill is not None and "крок" in skill.body, str(skill))

        book = skills_module.SkillBook(folder)
        check("скіл знайдено в теці", len(book.skills) == 1, f"{len(book.skills)}")
        check("скіл вимкнено за замовчуванням", book.skills[0].enabled is False)
        check("порожній промпт без увімкнених", book.prompt() == "")

        book.toggle("Мій Скіл")
        check("скіл увімкнено", book.skills[0].enabled is True)
        check("увімкнений скіл потрапляє в промпт",
              "Мій Скіл" in book.prompt() and "крок" in book.prompt())

        check("перелік для агента містить назву", "Мій Скіл" in book.describe())
        check("скіл знаходиться за назвою теки", book.get("мій-скіл") is not None)

        known = {schema["function"]["name"] for schema in skills_module.tool_schemas()}
        check("схеми скілів", {"list_skills", "read_skill"} <= known, ",".join(sorted(known)))

        book.set_root(ROOT)
        check("скіли робочої теки проєкту", len(book.skills) >= 1,
              ",".join(s.name for s in book.skills))
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
# Очищення тексту від виклику інструмента
# ─────────────────────────────────────────────────────────────────────────────

def test_tool_json_stripping() -> None:
    check("огорожений виклик прибрано",
          strip_tool_json('```json\n{"name": "list_dir", "arguments": {"path": "."}}\n```') == "")
    bare = '{"name": "run_command", "arguments": {"command": "python -m unittest"}}'
    check("голий виклик прибрано", strip_tool_json(bare, TOOL_SCHEMAS) == "")
    mixed = 'Гаразд. {"name": "read_file", "arguments": {"path": "a.py"}} Далі подивлюсь.'
    cleaned = strip_tool_json(mixed, TOOL_SCHEMAS)
    check("текст навколо виклику збережено",
          "Гаразд." in cleaned and "Далі" in cleaned and "read_file" not in cleaned, cleaned)
    plain = 'Звичайна відповідь {"temperature": 0.2}'
    check("звичайний JSON не чіпаємо", strip_tool_json(plain, TOOL_SCHEMAS) == plain)
    tag = '<tool_call>{"name": "list_dir", "arguments": {}}</tool_call>Готово'
    check("теги tool_call прибрано", "list_dir" not in strip_tool_json(tag, TOOL_SCHEMAS))


# ─────────────────────────────────────────────────────────────────────────────
# Контекстна панель
# ─────────────────────────────────────────────────────────────────────────────

def test_context_helpers() -> None:
    from blackchpok_ide import context_panel

    folder = temp_dir()
    try:
        (folder / "a.py").write_text("x = 1\n", encoding="utf-8")
        (folder / ".bak").mkdir()
        (folder / "a.py.bak").write_text("old\n", encoding="utf-8")
        changes = context_panel._recent_changes(folder)
        names = [path.name for path, _ in changes]
        check("зміни не містять .bak", "a.py.bak" not in names, ",".join(names))
        check("зміни містять справжній файл", "a.py" in names)
        files = context_panel._top_files(folder)
        check("файли теки зібрано", any(p.name == "a.py" for p in files))
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_mcp_config() -> None:
    from blackchpok_ide import mcp_client, mcp_panel

    folder = temp_dir()
    try:
        config = folder / ".mcp.json"
        config.write_text(
            '{"mcpServers": {"demo": {"command": "python", "args": ["srv.py"]}}}',
            encoding="utf-8",
        )
        found = mcp_panel.workspace_config_paths(folder)
        check("конфігурацію MCP знайдено", config in found)
        loaded = mcp_client.McpManager.load_configs(found)
        check("сервер із конфігурації прочитано",
              len(loaded) == 1 and loaded[0].name == "demo" and loaded[0].command == "python")

        broken = folder / "mcp.json"
        broken.write_text("{ не json", encoding="utf-8")
        still = mcp_client.McpManager.load_configs([broken, config])
        check("битий файл не ламає розбір", len(still) == 1)

        configs = mcp_client.McpManager.load_configs([ROOT / ".cursor" / "mcp.json"])
        check("конфіг проєкту читається", bool(configs),
              ",".join(c.name for c in configs))
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
# Інтеграція: агент бачить скіли й MCP-інструменти
# ─────────────────────────────────────────────────────────────────────────────

def test_agent_tool_routing() -> None:
    """Агент має віддавати моделі скіли й MCP-інструменти та виконувати їх."""
    from blackchpok_ide import mcp_client
    from blackchpok_ide.agent import AgentRunner
    from blackchpok_ide.agent_tools import ToolRegistry
    from blackchpok_ide.config import AgentSettings, LLMSettings

    folder = temp_dir()
    manager = mcp_client.McpManager()
    try:
        book = skills_module.SkillBook(ROOT)
        runner = AgentRunner(
            ToolRegistry(folder),
            LLMSettings(base_url="http://127.0.0.1:9/v1", model="check", timeout=5),
            AgentSettings(offline_fallback=False),
            folder,
        )
        runner.skill_book = book

        names = {schema["function"]["name"] for schema in runner.tool_schemas()}
        check("агент бачить інструменти скілів",
              {"list_skills", "read_skill"} <= names, f"{len(names)} інструментів")
        check("list_skills виконується", runner.call_tool("list_skills", {}).ok)
        read = runner.call_tool("read_skill", {"name": "ukrainian-reply"})
        check("read_skill віддає інструкцію", read.ok and "AGENTS.md" in read.output)
        missing = runner.call_tool("read_skill", {"name": "нема-такого"})
        check("невідомий скіл — помилка, не виняток", not missing.ok)

        # Без увімкнених скілів промпт не роздувається
        check("вимкнені скіли не потрапляють у промпт", book.prompt() == "")

        # MCP: справжній сервер через фейковий процес
        config = mcp_client.McpServerConfig(
            name="demo",
            command=sys.executable,
            args=[str(ROOT / "tests" / "fake_mcp_server.py")],
            cwd=str(ROOT),
        )
        statuses = manager.start_all([config])
        check("MCP-сервер запущено", statuses.get("demo") == "працює", str(statuses))

        runner.mcp_manager = manager
        mcp_names = {schema["function"]["name"] for schema in runner.tool_schemas()
                     if schema["function"]["name"].startswith("mcp__")}
        check("MCP-інструменти в схемах агента",
              "mcp__demo__echo" in mcp_names, ",".join(sorted(mcp_names)))

        echoed = runner.call_tool("mcp__demo__echo", {"text": "привіт"})
        check("виклик MCP-інструмента через агента", echoed.ok and "привіт" in echoed.output,
              echoed.output[:40])
        failed = runner.call_tool("mcp__demo__fail", {})
        check("помилка MCP-інструмента не ламає агента",
              failed.ok is False and "помилка" in failed.output.lower(), failed.output[:40])
        unknown = runner.call_tool("mcp__nope__x", {})
        check("невідомий MCP-інструмент оброблено", not unknown.ok)
    finally:
        manager.stop_all()
        shutil.rmtree(folder, ignore_errors=True)


def main() -> int:
    test_queue()
    test_split_batch()
    test_skills()
    test_tool_json_stripping()
    test_context_helpers()
    test_mcp_config()
    test_agent_tool_routing()
    print()
    print("Нові можливості:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
