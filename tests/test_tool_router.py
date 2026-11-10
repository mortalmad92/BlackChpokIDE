"""Тести маршрутизації інструментів: звичайна фраза → конкретна дія.

Перевіряє, що агент розуміє розмовну фразу й добирає правильний інструмент,
а також що він виконує дію навіть коли модель відповіла лише текстом.

Запуск:  python tests/test_tool_router.py
"""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import tool_router as tr  # noqa: E402

failures = 0
checked = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures, checked
    checked += 1
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


# ─────────────────────────────────────────────────────────────────────────────
# Маршрутизація фраз
# ─────────────────────────────────────────────────────────────────────────────

ACTION_CASES: tuple[tuple[str, str, dict], ...] = (
    ("покажи файли", "list_dir", {}),
    ("що в папці?", "list_dir", {}),
    ("прочитай main.py", "read_file", {"path": "main.py"}),
    ("покажи код server.py", "read_file", {"path": "server.py"}),
    ("знайди master_agent_router", "search_text", {"query": "master_agent_router"}),
    ("де використовується launch", "search_text", {}),
    ("знайди файли *.py", "find_files", {}),
    ("дерево проєкту", "project_tree", {"depth": 3}),
    ("структура проєкту", "project_tree", {}),
    ("перевір синтаксис main.py", "python_check", {"path": "main.py"}),
    ("запусти тести", "run_command", {}),
    ("запусти git status", "run_command", {"command": "git status"}),
    ("які є скіли", "list_skills", {}),
)

for phrase, expected_tool, expected_args in ACTION_CASES:
    hints = tr.route(phrase)
    tools = [hint.tool for hint in hints]
    ok = expected_tool in tools
    detail = ",".join(tools) if tools else "порожньо"
    if ok and expected_args:
        matched = next(hint for hint in hints if hint.tool == expected_tool)
        for key, value in expected_args.items():
            got = str(matched.arguments.get(key, ""))
            expected = str(value)
            ok = ok and (expected in got or got.endswith(expected))
    check(f"фраза «{phrase}» → {expected_tool}", ok, detail)


# ── ОНОВЛЕНО 2026-11-09 (див. research/KNOWN_BASELINE_FAILURES.md) ──────────
#
# Ці перевірки падали ЩЕ ДО поточного етапу: базовий знімок коду від 06.11
# віддавав ``mcp:search_web``, а сучасний — нативний ``search_web``. Зміна
# свідома: нативний інструмент працює й без MCP-сервера, тому він кращий.
# Тест лишався на старому очікуванні. Тепер він приймає ОБИДВА варіанти —
# так перевірка лишається корисною (роутер усе одно мусить вибрати пошук),
# але не вимагає конкретного транспорту.
SEARCH_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("пошук у мережі", ("search_web", "mcp:search_web")),
    ("завантаження сторінки", ("fetch_url", "mcp:fetch_url")),
)

WEB_CASES: tuple[tuple[str, str], ...] = (
    ("знайди в інтернеті погоду в Києві", "пошук у мережі"),
    ("погугли останні новини про Python", "пошук у мережі"),
    ("яка сьогодні погода", "пошук у мережі"),
    ("завантаж https://example.com", "завантаження сторінки"),
)

_families = dict(SEARCH_FAMILIES)
for phrase, family in WEB_CASES:
    tools = [hint.tool for hint in tr.route(phrase)]
    accepted = _families[family]
    check(f"фраза «{phrase}» → {family}", any(item in tools for item in accepted),
          ",".join(tools) if tools else "порожньо")


MCP_CASES: tuple[tuple[str, str], ...] = (
    ("що ти пам'ятаєш про проєкт", "mcp:memory_search"),
    ("про що ми говорили раніше", "mcp:memory_search"),
    ("проіндексуй проєкт", "mcp:index_project"),
    ("працюй вночі 4 години", "mcp:night_shift"),
    ("нічна зміна на 3 години", "mcp:night_shift"),
    ("проаналізуй проєкт", "mcp:analyze_project"),
)

for phrase, expected in MCP_CASES:
    tools = [hint.tool for hint in tr.route(phrase)]
    check(f"фраза «{phrase}» → {expected}", expected in tools,
          ",".join(tools) if tools else "порожньо")


TALK_CASES = (
    "привіт, як справи?",
    "розкажи вірш про море",
    "дякую!",
    "поясни, що таке рекурсія",
    "мені сумно сьогодні",
)

for phrase in TALK_CASES:
    check(f"розмова «{phrase}» не стає дією", not tr.confident(phrase),
          tr.describe_route(phrase))


def test_capability_question() -> None:
    """«Що ти вмієш?» — це доречний виклик переліку можливостей, не балачка."""
    tools = [hint.tool for hint in tr.route("що ти вмієш?")]
    check("питання про можливості дає перелік дій",
          any(t in tools for t in ("mcp:list_intents", "list_skills")), ",".join(tools))


def test_web_not_code_search() -> None:
    """«знайди в інтернеті» не має підмінятись пошуком по коду."""
    hints = tr.route("знайди в інтернеті новини про Python")
    tools = [hint.tool for hint in hints]
    check("веб-пошук не йде в search_text", "search_text" not in tools, ",".join(tools))
    # Приймаємо і нативний, і MCP-варіант: суть перевірки — «це саме
    # веб-пошук», а не «це саме MCP». Деталі — у KNOWN_BASELINE_FAILURES.md.
    check("веб-пошук іде в пошук у мережі",
          any(t in tools for t in ("search_web", "mcp:search_web")), ",".join(tools))
    matched = next(h for h in hints
                   if h.tool in ("search_web", "mcp:search_web"))
    query = str(matched.arguments.get("query", ""))
    check("запит очищено від «в інтернеті»", "інтернеті" not in query.lower(), query)


def test_night_hours() -> None:
    matched = next(h for h in tr.route("працюй вночі 4 години")
                   if h.tool == "mcp:night_shift")
    check("нічний режим бере години", matched.arguments.get("query") == "4",
          str(matched.arguments))


def test_no_duplicates() -> None:
    """MCP-дублі не повторюють уже знайдену IDE-дію."""
    hints = tr.route("прочитай main.py")
    tools = [hint.tool for hint in hints]
    check("немає дубля read_file з MCP",
          tools.count("read_file") == 1 and "mcp:read_file" not in tools, ",".join(tools))

    hints2 = tr.route("покажи файли")
    tools2 = [hint.tool for hint in hints2]
    check("немає дубля list_dir з MCP",
          "list_dir" in tools2 and "mcp:read_files" not in tools2, ",".join(tools2))


def test_catalog() -> None:
    text = tr.catalog_text(include_mcp=True)
    check("каталог містить read_file", "read_file" in text)
    check("каталог містить пошук у мережі", "search_web" in text)
    check("каталог містить приклади", "напр." in text)
    check("каталог без MCP коротший",
          len(tr.catalog_text(include_mcp=False)) < len(text))


def test_confidence_levels() -> None:
    hint = tr.route("прочитай main.py")[0]
    check("явна дія — high", hint.confidence == tr.HIGH, hint.confidence)
    medium = [h for h in tr.route("main.py") if h.confidence == tr.MEDIUM]
    check("згадка файлу без дієслова — medium", bool(medium),
          str([h.tool for h in medium]))


# ─────────────────────────────────────────────────────────────────────────────
# Агент сам виконує дію, коли модель лише «розмовляє»
# ─────────────────────────────────────────────────────────────────────────────

class _LazyModel(BaseHTTPRequestHandler):
    """Модель, яка ніколи не викликає інструментів — лише текст."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *_args) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        body = json.dumps({"object": "list", "data": [{"id": "lazy"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        payload = {
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant",
                                     "content": "Звісно! Зараз покажу файли."}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 8, "total_tokens": 48},
        }
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_agent_self_executes() -> None:
    from blackchpok_ide.agent import AgentRunner
    from blackchpok_ide.agent_tools import ToolRegistry
    from blackchpok_ide.config import AgentSettings, LLMSettings

    server = ThreadingHTTPServer(("127.0.0.1", 0), _LazyModel)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        runner = AgentRunner(
            ToolRegistry(ROOT),
            LLMSettings(base_url=f"http://127.0.0.1:{port}/v1", model="lazy", timeout=15),
            AgentSettings(offline_fallback=False, max_steps=3),
            ROOT,
        )
        runner.start("покажи файли")
        events, deadline = [], time.time() + 25
        while time.time() < deadline:
            try:
                event = runner.events.get(timeout=0.4)
            except Exception:  # noqa: BLE001
                if not runner.busy:
                    break
                continue
            events.append(event)
            if event.kind == "done":
                break

        calls = [e for e in events if e.kind == "tool_call"]
        check("агент викликав інструмент попри балачку моделі", bool(calls),
              ",".join(e.data.get("name", "") for e in calls))
        check("виклик позначено як автоматичний",
              any(e.data.get("auto") for e in calls), str(len(calls)))
        answers = [e.text for e in events if e.kind == "assistant"]
        check("відповідь містить реальний результат дії",
              bool(answers) and ("blackchpok_ide" in answers[-1] or "main.py" in answers[-1]),
              answers[-1][:110].replace("\n", " ") if answers else "порожньо")

        # А тепер звичайна розмова — жодних інструментів.
        runner.reset()
        runner.start("розкажи вірш про море")
        events2, deadline = [], time.time() + 20
        while time.time() < deadline:
            try:
                event = runner.events.get(timeout=0.4)
            except Exception:  # noqa: BLE001
                if not runner.busy:
                    break
                continue
            events2.append(event)
            if event.kind == "done":
                break
        calls2 = [e for e in events2 if e.kind == "tool_call"]
        check("на розмову інструменти не викликаються", not calls2,
              ",".join(e.data.get("name", "") for e in calls2))
    finally:
        server.shutdown()


def test_router_actions_defined() -> None:
    from blackchpok_ide.agent import _ROUTER_ACTIONS

    names = [name for name, *_ in _ROUTER_ACTIONS]
    check("дії роутера оголошені", len(names) >= 10, f"{len(names)} дій")
    check("є пошук у мережі", "search_web" in names)
    check("є пам'ять", "memory_search" in names)
    check("є нічний режим", "night_shift" in names)
    for name, description, params, required in _ROUTER_ACTIONS:
        if not description or not isinstance(params, dict):
            check(f"дія {name} описана коректно", False)
            break
    else:
        check("усі дії роутера мають опис і параметри", True)


def main() -> int:
    test_capability_question()
    test_web_not_code_search()
    test_night_hours()
    test_no_duplicates()
    test_catalog()
    test_confidence_levels()
    test_router_actions_defined()
    test_agent_self_executes()
    print()
    print(f"Перевірено тверджень: {checked}")
    print("Маршрутизація інструментів:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


# ── unittest-обгортка (додано 10.11.2026) ──────────────────────────────────
# Для `python -m unittest discover` ці перевірки раніше були невидимі:
# файл — скрипт із власним main(), а не TestCase. Тепер discover запускає
# його й падає, якщо main() повернув ненульовий код. Запуск як скрипт
# (`python tests/test_tool_router.py`) поводиться як раніше.
import unittest as _unittest  # noqa: E402


class _ScriptSuite(_unittest.TestCase):
    def test_script_passes(self) -> None:
        code = main()
        self.assertEqual(code, 0, f"main() повернув {code}")
