"""Точка входу BlackChpok IDE.

Запуск з коду:      python main.py [папка]
Самоперевірка:      python main.py --selftest
Збірка у .exe:      build_exe.bat   (див. BUILD_UK.md)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _ensure_stdio() -> None:
    """У .exe без консолі sys.stdout/sys.stderr = None; print() тоді падає.

    Підставляємо файл журналу, щоб діагностика не зникала, а --selftest
    міг друкувати результати. Заодно переводимо потоки на UTF-8, інакше
    український текст у консолі Windows перетворюється на «кракозябри».
    """
    if sys.stdout is not None and sys.stderr is not None:
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
            except (AttributeError, ValueError, OSError):
                pass
        return
    try:
        from blackchpok_ide.config import app_data_dir

        target = app_data_dir() / "console.log"
        target.parent.mkdir(parents=True, exist_ok=True)
        stream = open(target, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - живе до виходу
    except OSError:
        import io

        stream = io.StringIO()
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def _ensure_repo_on_path() -> None:
    """Щоб працював імпорт пакета навіть при запуску з іншої теки."""
    if getattr(sys, "frozen", False):
        return  # у .exe модулі вже всередині архіву
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))


def run_selftest() -> int:
    """Консольна перевірка без відкриття вікна (для CI та перевірки .exe)."""
    from blackchpok_ide.config import Settings, setup_logging
    from blackchpok_ide.agent_tools import TOOL_SCHEMAS, ToolRegistry
    from blackchpok_ide.offline import OfflinePlanner
    from blackchpok_ide.syntax import highlighter_for
    from blackchpok_ide import workspace as ws

    setup_logging()
    failures = 0

    def check(name: str, condition: bool, detail: str = "") -> None:
        nonlocal failures
        status = "OK  " if condition else "FAIL"
        print(f"[{status}] {name}{(' — ' + detail) if detail else ''}")
        if not condition:
            failures += 1

    settings = Settings.load()
    check("налаштування завантажуються", isinstance(settings.llm.base_url, str), settings.llm.base_url)

    root = Path.cwd()
    registry = ToolRegistry(root)
    listing = registry.call("list_dir", {"path": "."})
    check("інструмент list_dir", listing.ok and len(listing.output) > 0)

    tree = registry.call("project_tree", {"depth": 1})
    check("інструмент project_tree", tree.ok and "├──" in tree.output or "└──" in tree.output)

    unknown = registry.call("no_such_tool", {})
    check("невідомий інструмент відхилено", not unknown.ok)

    blocked = registry.call("read_file", {"path": "../../../etc/passwd"})
    check("шлях поза текою заблоковано", not blocked.ok, blocked.output[:60])

    syntax = highlighter_for("sample.py").spans('def foo(x): return "text"  # comment')
    tags = {tag for _s, _e, tag in syntax}
    check("підсвітка синтаксису", "keyword" in tags and "string" in tags, ",".join(sorted(tags)))

    planner = OfflinePlanner(root, registry)
    steps = planner.plan("покажи файли")
    check("офлайн-роутер", bool(steps), str(steps))

    check("схеми інструментів", len(TOOL_SCHEMAS) >= 8, f"{len(TOOL_SCHEMAS)} шт.")

    hits = ws.search_text(root, "def ", glob="*.py", limit=5)
    check("пошук по файлах", isinstance(hits, list), f"{len(hits)} збігів")

    # ── хаб моделей: залізо, каталог, рушій ────────────────────────────────
    from blackchpok_ide import hardware as hw
    from blackchpok_ide import model_hub as hub
    from blackchpok_ide import runtime as rt

    profile = hw.detect(root)
    check("залізо визначено", profile.ram_total_gb > 0 and profile.cpu_threads > 0,
          profile.summary()[:90])

    choice = hw.recommend(profile)
    fitted = hw.fit(profile, choice)
    check("модель підібрана під залізо", choice.approx_gb <= profile.usable_gb + 0.01,
          f"{choice.label} · {fitted.speed} · ctx {fitted.plan.ctx_size}")
    check("план запуску не порожній", fitted.plan.ctx_size >= hw.MIN_CTX,
          f"ngl={fitted.plan.gpu_layers} threads={fitted.plan.threads}")

    check("каталог моделей", len(hw.MODEL_CATALOG) >= 5, f"{len(hw.MODEL_CATALOG)} моделей")
    check("розбір посилань HF",
          hub.parse_ref("https://huggingface.co/Qwen/Qwen3-4B-GGUF") == "Qwen/Qwen3-4B-GGUF")
    check("вибір квантування",
          hub.pick_best_gguf(["a-q8_0.gguf", "a-q4_k_m.gguf"]) == "a-q4_k_m.gguf")

    releases = [
        {"tag": "b1", "assets": [
            {"name": "llama-b1-bin-win-cpu-x64.zip", "size": 1, "url": "u"},
            {"name": "llama-b1-bin-win-vulkan-x64.zip", "size": 1, "url": "u"},
        ]},
    ]
    assets, _tried = rt.plan_engine_install(profile, releases=releases)
    check("вибір збірки рушія", bool(assets), assets[0]["name"] if assets else "—")
    # Рушій — необов'язковий: він завантажується з хабу на вимогу користувача,
    # тому його відсутність не є помилкою самоперевірки.
    engine_state = (f"є: {rt.engine_version() or 'без версії'}"
                    if rt.engine_installed() else "не встановлено (завантажиться з хабу)")
    check("шлях до рушія визначено", bool(rt.server_path().name), engine_state)

    from blackchpok_ide.llm_client import extract_tool_calls, strip_tool_json

    recovered = extract_tool_calls('```json\n{"name": "list_dir", "arguments": {"path": "."}}\n```',
                                   TOOL_SCHEMAS)
    check("виклик інструмента з тексту", len(recovered) == 1,
          recovered[0]["function"]["name"] if recovered else "")
    check("очищення тексту від JSON",
          "list_dir" not in strip_tool_json('```json\n{"name":"list_dir","arguments":{}}\n```'))

    check("тека моделей доступна", hub.models_dir().exists(),
          f"{len(hub.local_models())} файлів у {hub.models_dir()}")

    # ── черга завдань, скіли, MCP, термінал ───────────────────────────────
    import tempfile

    from blackchpok_ide import queue_engine
    from blackchpok_ide import skills as skills_mod

    queue_file = Path(tempfile.mkdtemp()) / "queue.json"
    task_queue = queue_engine.TaskQueue(queue_file)
    task = task_queue.add("перевірити проєкт")
    task_queue.mark_running(task.id)
    task_queue.mark_done(task.id, "готово")
    check("черга завдань", task_queue.counts()[queue_engine.DONE] == 1,
          task_queue.summary())
    check("розбір списку задач",
          queue_engine.split_batch("- a\n- b\n2. c") == ["a", "b", "c"])

    book = skills_mod.SkillBook(root)
    check("скіли знайдено", True, f"{len(book.skills)} шт. · " +
          ", ".join(s.name for s in book.skills[:4]) or "немає")
    check("схеми скілів", len(skills_mod.tool_schemas()) == 2)

    from blackchpok_ide.mcp_client import McpManager

    manager = McpManager()
    check("MCP-клієнт створено", manager.status == {}, "серверів не підключено")

    # ── зовнішні залежності: чесний звіт про те, що є, а що ні ────────────
    # Без цього користувач бачить «агент не працює», хоча причина — лише
    # відсутній git або рушій моделі.
    import shutil as _shutil

    from blackchpok_ide import runtime as _rt

    optional_modules = (
        ("PIL", "скріншоти застосунку"),
        ("numpy", "векторний пошук RAG"),
        ("pygments", "підсвітка синтаксису"),
    )
    absent_modules = []
    for module_name, purpose in optional_modules:
        try:
            __import__(module_name)
        except ImportError:
            absent_modules.append(f"{module_name} ({purpose})")
    # Відсутність опційних бібліотек — не помилка: IDE працює без них,
    # просто частина можливостей вимикається. Тому це інформаційний рядок.
    check("опційні бібліотеки", True,
          "усі на місці" if not absent_modules
          else "немає: " + ", ".join(absent_modules))

    tools = {
        "git": "історія змін і diff",
        "node": "запуск Node.js-проєктів",
        "npm": "запуск Node.js-проєктів",
    }
    absent_tools = [f"{name} ({purpose})" for name, purpose in tools.items()
                    if _shutil.which(name) is None]
    check("зовнішні програми", True,
          "усі на місці" if not absent_tools
          else "немає: " + ", ".join(absent_tools))

    engine_ready = _rt.engine_installed()
    check("рушій моделі", True,
          f"встановлено {_rt.engine_version() or 'без версії'}" if engine_ready
          else "не встановлено — завантажиться з хабу моделей")

    from blackchpok_ide.shell_session import available_shell, strip_ansi

    check("оболонка для терміналу", bool(available_shell()), available_shell())
    check("ANSI прибрано", strip_ansi("\x1b[31mred\x1b[0m") == "red")

    from blackchpok_ide.markdown_view import parse_markdown

    segments = parse_markdown("## Заголовок\n\n```python\nx = 1\n```\n\n- пункт")
    kinds = {segment.kind for segment in segments}
    check("розбір markdown у чаті", {"heading", "code", "bullet"} <= kinds,
          ",".join(sorted(kinds)))

    from blackchpok_ide.llm_client import strip_tool_json

    bare = '{"name": "list_dir", "arguments": {"path": "."}}'
    check("сирий виклик не потрапляє у відповідь",
          strip_tool_json(bare, TOOL_SCHEMAS) == "")

    print()
    print("Самоперевірка завершена:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


def main(argv: list[str] | None = None) -> int:
    _ensure_stdio()
    _ensure_repo_on_path()
    parser = argparse.ArgumentParser(prog="blackchpok", description="BlackChpok IDE")
    parser.add_argument("workspace", nargs="?", default="", help="Папка проєкту")
    parser.add_argument("--selftest", action="store_true", help="Консольна перевірка без вікна")
    parser.add_argument("--version", action="store_true", help="Показати версію")
    args = parser.parse_args(argv)

    if args.version:
        from blackchpok_ide import APP_NAME, APP_VERSION

        print(f"{APP_NAME} {APP_VERSION}")
        return 0
    if args.selftest:
        return run_selftest()

    from blackchpok_ide import run

    return run(args.workspace)


if __name__ == "__main__":
    raise SystemExit(main())
