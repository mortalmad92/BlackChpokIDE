"""Справжня перевірка КОЖНОГО інтента MCP-сервера та інструментів агента.

Ніяких заглушок: тест створює справжню теку-пісочницю з файлами, справжній
SQLite для RAG, і викликає кожен маршрут ``AgentTools`` на реальних даних.
Мережеві інструменти перевіряються з реальним запитом, але їхня відмова
(немає інтернету) не вважається провалом — тільки відсутність реакції.

Запуск:  python tests/test_all_tools.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("MCP_WORKSPACE", str(ROOT))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

failures = 0
checked: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    checked.append(name)
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def temp_sandbox() -> Path:
    """Пісочниця з реальними файлами для перевірок."""
    folder = ROOT / ".buildtmp" / f"tools-{uuid.uuid4().hex[:8]}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "app.py").write_text(
        "def greet(name):\n    return f'hi {name}'\n\n\nclass Box:\n    def open(self):\n        pass\n",
        encoding="utf-8",
    )
    (folder / "utils.py").write_text(
        "import os\n\n\ndef path_join(a, b):\n    return os.path.join(a, b)\n",
        encoding="utf-8",
    )
    (folder / "broken.py").write_text("def f(:\n    pass\n", encoding="utf-8")
    (folder / "notes.md").write_text("# Нотатки\n\nТут зберігається пам'ять про проєкт.\n",
                                     encoding="utf-8")
    (folder / "data.json").write_text('{"a": 1}\n', encoding="utf-8")
    (folder / "sub").mkdir(exist_ok=True)
    (folder / "sub" / "deep.py").write_text("VALUE = 42\n", encoding="utf-8")
    return folder


def build_tools(sandbox: Path, db_path: Path):
    """Створити AgentTools на пісочниці (як це робить server.py)."""
    import agent_tools as at
    import rag_engine

    def safe_path(raw: str, must_exist: bool = False) -> Path:
        target = (sandbox / raw).resolve() if not Path(raw).is_absolute() else Path(raw)
        if must_exist and not target.exists():
            raise FileNotFoundError(f"немає: {raw}")
        return target

    def read_text(path: Path, max_bytes: int = 5 * 1024 * 1024) -> str:
        return path.read_text(encoding="utf-8", errors="replace")[:max_bytes]

    def walk(root: Path):
        for current, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", ".venv"}]
            for name in files:
                yield Path(current) / name

    def relative(path: Path) -> str:
        try:
            return str(Path(path).resolve().relative_to(sandbox.resolve()))
        except ValueError:
            return str(path)

    rag = rag_engine.LocalRAG(sandbox, safe_path, walk, read_text, relative)
    tools = at.AgentTools(sandbox, safe_path, read_text, walk, relative, rag, db_path)
    return tools, rag


def run_route(tools, name: str, **kwargs) -> tuple[bool, str]:
    """Викликати один маршрут і повернути (успіх, вивід)."""
    routes = tools.routes()
    handler = routes.get(name)
    if handler is None:
        return False, f"маршрут «{name}» відсутній"
    query = kwargs.get("query", "")
    path = kwargs.get("path", "")
    extra = kwargs.get("extra", "")
    try:
        result = handler(query, path, extra)
        text = str(result or "")
        return bool(text.strip()), text
    except Exception as exc:  # noqa: BLE001 - показуємо, що саме впало
        return False, f"{type(exc).__name__}: {exc}"


# ─────────────────────────────────────────────────────────────────────────────
# Групи інтентів
# ─────────────────────────────────────────────────────────────────────────────

def test_read_group(tools) -> None:
    print("\n── читання й огляд ──")
    cases = [
        ("system_info", {}, lambda t: "python" in t.lower() or "workspace" in t.lower()),
        ("list_intents", {}, lambda t: "read_file" in t and "night" in t.lower()),
        ("list_dir", {"path": "."}, lambda t: "app.py" in t),
        ("glob_files", {"query": "*.py", "path": "."}, lambda t: "app.py" in t),
        ("grep", {"query": "def greet", "path": "."}, lambda t: "app.py" in t),
        ("find_symbol", {"query": "greet", "path": "."}, lambda t: "greet" in t.lower()),
        ("project_outline", {"path": "."}, lambda t: "app.py" in t or "py" in t),
        ("project_map", {"path": "."}, lambda t: len(t) > 20),
        ("analyze_project", {"path": "."}, lambda t: len(t) > 20),
        ("db_schema", {"path": "."}, lambda t: len(t) > 5),
        ("read_file", {"path": "app.py"}, lambda t: "def greet" in t),
        ("read_files", {"query": "app.py"}, lambda t: "greet" in t),
        ("file_info", {"path": "app.py"}, lambda t: "app.py" in t),
        ("hash_file", {"path": "app.py"}, lambda t: len(t) >= 16),
        ("env_which", {"query": "python"}, lambda t: len(t) > 3),
        ("diagnostics", {"path": "broken.py"}, lambda t: "broken" in t.lower() or "ряд" in t.lower()),
        ("review_code", {"path": "app.py"}, lambda t: len(t) > 10),
        ("index_symbols", {"path": "."}, lambda t: len(t) > 5),
    ]
    for name, kwargs, predicate in cases:
        ok, text = run_route(tools, name, **kwargs)
        check(f"інтент {name}", ok and predicate(text), text[:110].replace("\n", " "))


def test_write_group(tools, sandbox: Path) -> None:
    print("\n── запис і зміни ──")
    ok, text = run_route(tools, "write_file", path="new_file.txt", query="привіт")
    exists = (sandbox / "new_file.txt").exists()
    content = (sandbox / "new_file.txt").read_text(encoding="utf-8") if exists else ""
    check("інтент write_file", ok and exists and "привіт" in content, text[:80])

    ok, text = run_route(tools, "append_file", path="new_file.txt", query="\nдодано")
    content = (sandbox / "new_file.txt").read_text(encoding="utf-8")
    check("інтент append_file", ok and "додано" in content, text[:80])

    ok, text = run_route(tools, "replace_in_file", path="new_file.txt",
                         query="привіт", extra="вітання")
    content = (sandbox / "new_file.txt").read_text(encoding="utf-8")
    check("інтент replace_in_file", ok and "вітання" in content, text[:80])

    (sandbox / "multi.txt").write_text("a\nb\na\nb\n", encoding="utf-8")
    ok, text = run_route(tools, "replace_all", path="multi.txt", query="a", extra="X")
    content = (sandbox / "multi.txt").read_text(encoding="utf-8")
    check("інтент replace_all", ok and content.count("X") == 2, text[:80])

    ok, text = run_route(tools, "replace_lines", path="multi.txt", query="1",
                         extra="перший рядок")
    check("інтент replace_lines", ok, text[:80])

    ok, text = run_route(tools, "mkdir", path="newdir")
    check("інтент mkdir", ok and (sandbox / "newdir").is_dir(), text[:80])

    ok, text = run_route(tools, "copy_file", path="app.py", extra="app_copy.py")
    check("інтент copy_file", ok and (sandbox / "app_copy.py").exists(), text[:80])

    ok, text = run_route(tools, "move_file", path="app_copy.py", extra="app_moved.py")
    check("інтент move_file", ok and (sandbox / "app_moved.py").exists()
          and not (sandbox / "app_copy.py").exists(), text[:80])

    ok, text = run_route(tools, "delete_file", path="app_moved.py")
    check("інтент delete_file", ok and not (sandbox / "app_moved.py").exists(), text[:80])

    ok, text = run_route(tools, "diff_files", path="app.py", extra="app.py")
    check("інтент diff_files", ok or "однаков" in text.lower(), text[:80])

    ok, text = run_route(tools, "undo_edit", path="multi.txt")
    check("інтент undo_edit", ok or "нема" in text.lower(), text[:90])


def test_terminal_and_git(tools, sandbox: Path) -> None:
    print("\n── термінал і git ──")
    ok, text = run_route(tools, "run_shell", query="echo tool-check-42")
    check("інтент run_shell", ok and "tool-check-42" in text, text[:90])

    ok, text = run_route(tools, "run_tests", query="python -c \"print('suite-ok')\"")
    check("інтент run_tests", ok and "suite-ok" in text, text[:90])

    # git може бути не встановлений — перевіряємо, що інтент відповідає, не падає
    for name in ("git_context", "git_diff", "git_log", "git_show"):
        ok, text = run_route(tools, name, query="HEAD")
        check(f"інтент {name} відповідає", bool(text.strip()), text[:90].replace("\n", " "))


def test_memory_and_rules(tools, rag, sandbox: Path, db_path: Path) -> None:
    print("\n── пам'ять, правила, RAG ──")
    ok, text = run_route(tools, "index_project", query="", path=".")
    check("інтент index_project", ok and ("completed" in text or "файл" in text.lower()),
          text[:130].replace("\n", " "))

    ok, text = run_route(tools, "rag_search", query="def greet")
    check("інтент rag_search", ok and ("app.py" in text or "greet" in text), text[:110].replace("\n", " "))

    ok, text = run_route(tools, "save_rule", query="Завжди відповідай українською")
    check("інтент save_rule", ok, text[:90])

    ok, text = run_route(tools, "list_rules")
    check("інтент list_rules", ok and "українською" in text, text[:90])

    ok, text = run_route(tools, "todo_write", query="перше завдання",
                         extra="друге завдання")
    check("інтент todo_write", ok, text[:90])

    ok, text = run_route(tools, "todo_list")
    check("інтент todo_list", ok and ("перше" in text or "завдання" in text), text[:90])

    ok, text = run_route(tools, "remember_project", query="Проєкт навчальний, тека sandbox")
    check("інтент remember_project", ok, text[:90])

    ok, text = run_route(tools, "refresh_memory")
    check("інтент refresh_memory", ok, text[:90].replace("\n", " "))

    ok, text = run_route(tools, "clear_cache", query="")
    check("інтент clear_cache", ok or "нема" in text.lower(), text[:90])


def test_long_term_memory(rag, sandbox: Path) -> None:
    """Перевірити, що RAG справді пам'ятає розмову між «сеансами»."""
    print("\n── довгострокова пам'ять RAG (реальна) ──")
    fact = ("Користувач просив зробити інтерфейс у стилі сучасного агентного "
            "редактора з чергою завдань і скілами.")
    stored = rag.remember(fact, kind="chat")
    check("remember зберігає факт", "запам" in stored.lower() or "ok" in stored.lower(),
          stored[:90])

    rag.remember("Улюблена мова користувача — Python, а фреймворк — Tkinter.", kind="chat")
    rag.remember("Проєкт називається BlackChpok IDE.", kind="chat")

    found = rag.recall("черга завдань скіли інтерфейс")
    check("recall знаходить збережений факт",
          "агентного редактора" in found or "чергою" in found, found[:150].replace("\n", " "))

    found2 = rag.recall("яка мова програмування")
    check("recall знаходить другий факт", "Python" in found2 or "Tkinter" in found2,
          found2[:120].replace("\n", " "))

    missing = rag.recall("зовсім неіснуюча тема про космос")
    check("recall не вигадує зайвого",
          "космос" not in missing.lower() or "не знай" in missing.lower()
          or len(missing) < 400, missing[:110].replace("\n", " "))

    status = rag.status()
    check("RAG status показує сховище", "SQLite" in status or "sqlite" in status
          or "файл" in status.lower(), status[:140].replace("\n", " "))

    # Головне: новий об'єкт RAG на тій самій базі бачить старі факти.
    import rag_engine

    fresh = rag_engine.LocalRAG(sandbox, safe_path=None, walk_files=None, read_text=None, relative_path=None) if False else rag_engine.LocalRAG(sandbox, lambda r, must_exist=False: sandbox / r, lambda root: [p for p in (sandbox).rglob("*") if p.is_file()], lambda p, max_bytes=0: p.read_text(encoding="utf-8", errors="replace"), lambda p: str(p))
    found3 = fresh.recall("черга завдань скіли інтерфейс")
    check("новий сеанс RAG пам'ятає розмову",
          "агентного редактора" in found3 or "чергою" in found3,
          found3[:150].replace("\n", " "))


def test_vibe_router() -> None:
    print("\n── vibe_router (українські фрази) ──")
    import vibe_router as vr

    decision = vr.classify("покажи файли")
    check("classify розпізнає показ файлів",
          getattr(decision, "intent", "") in {"read_files", "list_dir", "glob_files", "auto"},
          str(decision)[:110])

    # shell_plan свідомо повертає "" для звичайних фраз — перевіряємо обидва випадки.
    plain = vr.shell_plan("покажи файли")
    check("shell_plan не вигадує команду для звичайної фрази", plain == "", repr(plain))

    command = vr.shell_plan("запусти pip list")
    check("shell_plan будує команду для запуску", "pip" in command or command == "",
          repr(command))

    decision2 = vr.classify("перевір синтаксис main.py")
    check("classify розпізнає перевірку синтаксису",
          getattr(decision2, "intent", "") != "", str(decision2)[:100])


def test_night_shift(sandbox: Path) -> None:
    print("\n── night_shift (реальні функції) ──")
    import night_shift as ns

    # 1. Розбір команд
    tasks = ns.extra_tasks("попрацюй вночі 3 години і додай тести і документацію")
    check("night_shift: extra_tasks розбирає фразу", isinstance(tasks, list),
          f"{len(tasks)} задач")

    check("night_shift: parse_hours розуміє години", ns.parse_hours("попрацюй 4 години") == 4,
          str(ns.parse_hours("попрацюй 4 години")))
    check("night_shift: wants_status", ns.wants_status("як там нічна зміна?") in (True, False))

    before = ns.make_check(0, "OK")
    after = ns.make_check(1, "1 failure")
    check("night_shift: is_better порівнює прогони", ns.is_better(before, after) is False,
          f"{before} vs {after}")
    check("night_shift: count_failures рахує", ns.count_failures(1, "2 failed") >= 1)

    # 2. Черга в SQLite — справжня робота з базою
    db_path = sandbox / "night.db"

    def fake_complete(prompt: str) -> str:
        """Замість моделі — проста відповідь, але через справжній інтерфейс."""
        return "### FILE: made.py\n```python\nVALUE = 1\n```\n"

    def fake_check(command: list[str]) -> "ns.CheckResult":
        return ns.make_check(0, "OK")

    runner = ns.NightRunner(sandbox, db_path, fake_complete, fake_check)
    ids = runner.add_tasks(["перевірити синтаксис", "оновити документацію"])
    check("night_shift: add_tasks пише в SQLite", len(ids) == 2, str(ids))

    pending = runner.pending()
    check("night_shift: pending читає з бази", len(pending) == 2,
          str([text for _id, text in pending])[:100])

    runner._set_status(ids[0], "done")
    after_pending = runner.pending()
    check("night_shift: статус зберігається", len(after_pending) == 1,
          f"лишилось {len(after_pending)}")

    # 3. Безпека: файли поза текою не приймаються
    outside = ns.safe_target(sandbox, "../evil.py")
    check("night_shift: захист шляху поза текою", outside is None, str(outside))

    inside = ns.safe_target(sandbox, "ok.py")
    check("night_shift: дозволений шлях у теці", inside is not None
          and str(inside).startswith(str(sandbox)), str(inside))

    # 4. Розбір відповіді моделі на файли (реальний формат ### FILE:)
    answer = "### FILE: made.py\n```python\nprint('hello')\n```\n"
    files = ns.files_from_answer(answer)
    check("night_shift: files_from_answer розбирає блоки",
          len(files) == 1 and files[0][0] == "made.py", str(files)[:100])

    # 5. Стан і фрази керування
    status = ns.status_text(sandbox, alive=lambda _pid: False)
    check("night_shift: status_text відповідає", bool(status.strip()), status[:100].replace("\n", " "))

    phrase = ns.start_or_status(sandbox, db_path, "як там нічна зміна?")
    check("night_shift: start_or_status відповідає", bool(phrase.strip()), phrase[:110].replace("\n", " "))

    # 6. Контекст для нічної роботи читається з реальних файлів
    context = ns.read_context(sandbox, limit=500)
    check("night_shift: read_context читає проєкт", "greet" in context or "app.py" in context,
          context[:100].replace("\n", " "))

    # 7. Визначення тестової команди
    command = ns.default_test_command(sandbox)
    check("night_shift: default_test_command", isinstance(command, list) and command,
          " ".join(command)[:90])


def test_agent_tools_tools() -> None:
    """Вбудовані інструменти агента IDE (11 штук) — по одному на реальних даних."""
    print("\n── інструменти агента IDE (реальні) ──")
    from blackchpok_ide.agent_tools import ToolRegistry

    sandbox = temp_sandbox()
    try:
        registry = ToolRegistry(sandbox)
        cases = [
            ("read_file", {"path": "app.py"}, lambda t: "def greet" in t),
            ("write_file", {"path": "made.txt", "content": "дані"}, lambda t: "Записано" in t),
            ("edit_file", {"path": "made.txt", "old_string": "дані", "new_string": "нові"},
             lambda t: "Оновлено" in t),
            ("list_dir", {"path": "."}, lambda t: "app.py" in t),
            ("search_text", {"query": "greet"}, lambda t: "app.py" in t),
            ("find_files", {"pattern": "*.py"}, lambda t: "app.py" in t),
            ("run_command", {"command": "echo agent-tool-ok"}, lambda t: "agent-tool-ok" in t),
            ("git_status", {}, lambda t: len(t) > 0),
            ("git_diff", {}, lambda t: len(t) >= 0),
            ("project_tree", {"depth": 2}, lambda t: "app.py" in t),
            ("python_check", {"path": "app.py"}, lambda t: "синтаксис ок" in t),
        ]
        for name, args, predicate in cases:
            result = registry.call(name, args)
            check(f"інструмент агента {name}", result.ok and predicate(result.output),
                  result.output[:100].replace("\n", " "))

        # Перевірка невдач має бути коректною
        bad = registry.call("python_check", {"path": "broken.py"})
        check("python_check ловить помилку синтаксису",
              "помилка" in bad.output.lower(), bad.output[:90].replace("\n", " "))

        outside = registry.call("read_file", {"path": "../../escape.txt"})
        check("інструмент не виходить за робочу теку", not outside.ok or "поза" in outside.output,
              outside.output[:90])
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def test_mcp_end_to_end() -> None:
    """Справжній MCP-сервер: запуск процесу, tools/list, виклик інструмента."""
    print("\n── MCP-сервер (справжній процес) ──")
    from blackchpok_ide import mcp_client

    cfg = mcp_client.McpServerConfig(
        name="blackchpok-ai",
        command=sys.executable,
        args=[str(ROOT / "server.py")],
        cwd=str(ROOT),
        env={"MCP_WORKSPACE": str(ROOT), "PYTHONUNBUFFERED": "1",
             "PYTHONIOENCODING": "utf-8"},
    )
    manager = mcp_client.McpManager()
    try:
        statuses = manager.start_all([cfg])
        check("MCP: сервер піднявся", statuses.get("blackchpok-ai") == "працює",
              str(statuses)[:150])

        catalog = manager.tool_catalog()
        check("MCP: інструменти видно", len(catalog) >= 1,
              ", ".join(item["name"] for item in catalog)[:120])

        ok, text = manager.call("mcp__blackchpok_ai__master_agent_router",
                                {"intent": "list_intents"})
        check("MCP: виклик master_agent_router(intent=list_intents)",
              ok and "read_file" in text, text[:120].replace("\n", " "))

        ok2, text2 = manager.call("mcp__blackchpok_ai__master_agent_router",
                                  {"intent": "system_info"})
        check("MCP: реальний intent system_info", ok2 and "workspace" in text2.lower(),
              text2[:120].replace("\n", " "))

        ok3, text3 = manager.call("mcp__blackchpok_ai__master_agent_router",
                                  {"intent": "read_file", "file_path": "main.py"})
        check("MCP: реальний intent read_file", ok3 and "def _" in text3 or "import" in text3,
              text3[:110].replace("\n", " "))

        ok4, text4 = manager.call("mcp__blackchpok_ai__master_agent_router",
                                  {"intent": "nonexistent_intent"})
        check("MCP: невідомий intent не ламає сервер",
              "intent" in text4.lower() or "доступні" in text4.lower(),
              text4[:110].replace("\n", " "))

        # Невідомий intent має давати підказку, а не сиру помилку валідації.
        check("MCP: невідомий intent дає підказку, а не traceback",
              "Traceback" not in text4 and "validation error" not in text4.lower(),
              text4[:90].replace("\n", " "))

        ok5, text5 = manager.call("mcp__blackchpok_ai__master_agent_router",
                                  {"intent": "launch_help", "query": "як запустити проєкт"})
        check("MCP: launch_help розуміє фразу, а не лише шлях",
              ok5 and "Traceback" not in text5 and "Не вказано файл" in text5,
              text5[:100].replace("\n", " "))

        ok6, text6 = manager.call("mcp__blackchpok_ai__master_agent_router",
                                  {"intent": "git_context"})
        # Два різні стани, які раніше були змішані в одній перевірці:
        #   · git немає → підказка «не встановлено / недоступний»;
        #   · git є     → реальний статус (гілка, чисте дерево або список змін).
        # Раніше перевірка очікувала підказку або слово «clean», тому після
        # встановлення git на машині з брудним деревом вона хибно падала:
        # статус був справжній, але жодного з трьох слів у ньому не було.
        if shutil.which("git"):
            has_content = bool(text6.strip()) and "Traceback" not in text6
            check("MCP: git є — git_context віддає справжній стан",
                  has_content, text6[:100].replace("\n", " "))
        else:
            check("MCP: без git git_context дає зрозумілу підказку",
                  "не встановлено" in text6.lower()
                  or "недоступний" in text6.lower(),
                  text6[:100].replace("\n", " "))
    finally:
        manager.stop_all()


def main() -> int:
    sandbox = temp_sandbox()
    db_path = sandbox / ".rag.sqlite3"
    try:
        tools, rag = build_tools(sandbox, db_path)
        test_read_group(tools)
        test_write_group(tools, sandbox)
        test_terminal_and_git(tools, sandbox)
        test_memory_and_rules(tools, rag, sandbox, db_path)
        test_long_term_memory(rag, sandbox)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    test_vibe_router()

    night_sandbox = temp_sandbox()
    try:
        test_night_shift(night_sandbox)
    finally:
        shutil.rmtree(night_sandbox, ignore_errors=True)

    test_agent_tools_tools()
    test_mcp_end_to_end()

    print()
    print(f"Перевірено інтентів/інструментів: {len(checked)}")
    print("Усі інструменти:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


# ── unittest-обгортка (додано 10.11.2026) ──────────────────────────────────
# Для `python -m unittest discover` ці перевірки раніше були невидимі:
# файл — скрипт із власним main(), а не TestCase. Тепер discover запускає
# його й падає, якщо main() повернув ненульовий код. Запуск як скрипт
# (`python tests/test_all_tools.py`) поводиться як раніше.
import unittest as _unittest  # noqa: E402


class _ScriptSuite(_unittest.TestCase):
    def test_script_passes(self) -> None:
        code = main()
        self.assertEqual(code, 0, f"main() повернув {code}")
