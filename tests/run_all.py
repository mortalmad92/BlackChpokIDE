"""Запустити всі перевірки проєкту послідовно.

    python tests/run_all.py            # юніт + e2e + smoke GUI
    python tests/run_all.py --fast     # без GUI
    python tests/run_all.py --list     # що саме буде запущено

ГОЛОВНЕ ПРО ПОВНОТУ. Раніше цей файл містив РУЧНИЙ список тестів, і він
розійшовся з реальністю: зі 113 модулів ``test_*.py`` запускались 67, а
46 (серед них ``test_v2_audit`` на 89 КБ, ``test_mcp_integration``,
``test_native_runtime``, ``test_bench``) не запускались НІКОЛИ. Саме через
це «141 успішний набір» і «7 помилок» описували різні набори тестів: один
прогін ішов через ``unittest discover``, другий — через цей список.

Тепер список модулів БУДУЄТЬСЯ з диска: будь-який новий ``tests/test_*.py``
потрапляє в прогін автоматично, і розбіжність більше не виникає.

ВИПРАВЛЕНО 10.11.2026. Файл містив ДВІ функції ``main()`` (рядки 149 і 191):
друга перекривала першу, зверталась до неоголошеної ``_SCRIPTS`` і падала
``NameError`` одразу після першої групи. Через це «повний набір» складався з
одного ``main.py --selftest`` (0.77 с замість 357 с), а 39 модулів не
запускались жодного разу. Другу ``main()`` видалено, ``_SCRIPTS`` замінено на
наявну :func:`script_modules`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
TESTS = ROOT / "tests"


def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


_utf8_stdout()

#: Модулі, які не можна запускати через ``unittest`` (власний ``main()``
#: або живий прогін, що сам керує процесом). Їх запускаємо як скрипти.
SCRIPT_MODULES: frozenset[str] = frozenset({
    "test_agent_e2e", "test_edge_cases", "test_features", "test_chat_store",
    "test_context_stats", "test_diff_stats", "test_auto_setup",
    "test_all_tools", "test_tool_router", "test_commands",
    "test_cloud_social", "test_deploy", "test_ast_editor",
    "test_web_preview", "test_model_menu", "test_layout_persist",
    "test_shell", "test_voice_hub", "test_mcp_client",
    "test_markdown_view", "test_cases_panel", "test_work_log",
    "test_streaming", "test_rag_ui", "test_tools_panel",
    "test_shell_session", "test_editor_files", "test_layout",
    "test_focus_mode", "test_task_center_live", "test_cases_live",
    "test_autonomous_live", "test_idle_unload_live",
    "test_browser_wizard_live", "test_deep_mode_live",
    "test_deep_mode_live_model", "e2e_real_agent", "smoke_gui",
    "test_model_switch_live", "test_idle_reload_live",
    "test_work_log_live", "test_new_layers_live", "test_agent_live_ux",
    "test_autonomous_stability_live", "test_autonomous",
    "test_adaptive_power", "test_unified_chats_ui", "test_browser_url",
    "test_env_setup", "test_deep_mode", "test_deep_view", "test_chat_ux",
    "test_chat_fixes", "test_composer_pills", "test_project_gate",
    "test_chat_ownership", "test_task_plan", "test_sidebar_chats_only",
    "test_task_queue_engine", "test_model_identity",
    "test_plain_language", "test_agent_reliability",
})

#: Живі прогони (GUI або справжня модель): у ``--fast`` їх пропускаємо.
LIVE_MODULES: frozenset[str] = frozenset({
    "smoke_gui", "e2e_real_agent", "e2e_stabilization_demo",
    "test_model_switch_live", "test_idle_reload_live", "test_idle_unload_live",
    "test_cases_live", "test_autonomous_live", "test_browser_wizard_live",
    "test_deep_mode_live", "test_deep_mode_live_model", "test_task_center_live",
    "test_work_log_live", "test_new_layers_live", "test_agent_live_ux",
    "test_shell_session", "test_editor_files", "test_layout",
    "test_focus_mode", "test_bench", "test_native_runtime",
})

#: Додаткові скрипти поза текою tests.
EXTRA_SCRIPTS: tuple[tuple[str, str], ...] = (
    ("Самоперевірка ядра", "main.py --selftest"),
)


def _module_has_main(path: Path) -> bool:
    """Чи це скрипт із власним ``main()`` (а не ``unittest``-модуль)."""
    import ast

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return False
    return any(isinstance(node, ast.FunctionDef) and node.name == "main"
               for node in tree.body)


def script_modules() -> frozenset[str]:
    """Модулі, які треба запускати як скрипти.

    Визначається з КОДУ, а не з ручного списку. Раніше список був руками
    написаний і містив 19 модулів, які насправді є звичайними
    ``unittest``-модулями: їх запускали як скрипти, і вони «проходили»,
    не виконавши жодного тесту (у них немає ``main()``). Це та сама
    хвороба, що й ручний перелік тестів.
    """
    found: set[str] = set()
    for path in TESTS.glob("*.py"):
        if not path.stem.startswith(("test_", "e2e_", "smoke_")):
            continue
        if _module_has_main(path):
            found.add(path.stem)
    return frozenset(found)


def discover_modules() -> list[str]:
    """Усі модулі тестів на диску — БЕЗ ручного списку.

    Порядок: спершу швидкі юніт-модулі, далі живі прогони. Це не впливає на
    повноту, але дає ранній сигнал: якщо зламано базову логіку, довгі живі
    прогони вже не витрачають час.
    """
    found = sorted(path.stem for path in TESTS.glob("*.py")
                   if path.stem.startswith(("test_", "e2e_", "smoke_")))
    fast = [name for name in found if name not in LIVE_MODULES]
    slow = [name for name in found if name in LIVE_MODULES]
    return fast + slow


def run(title: str, args: list[str]) -> bool:
    print("=" * 70)
    print(title)
    print("=" * 70)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    # Тести не мають чіпати справжні налаштування користувача: інакше прогін
    # перезаписує вибрану модель і робочу теку. Усі шляхи йдуть у .buildtmp.
    env["BLACKCHPOK_HOME"] = str(ROOT / ".buildtmp" / "apphome")
    # Додатковий запобіжник: навіть якщо тест звернеться до справжнього
    # шляху, запис не відбудеться. Раніше прогін записав у СПРАВЖНІЙ конфіг
    # engine.auto_start = False, і локальна модель перестала стартувати.
    env["BLACKCHPOK_NO_SAVE"] = "1"
    proc = subprocess.run(args, cwd=str(ROOT), env=env)
    ok = proc.returncode == 0
    print(("[OK] " if ok else "[FAIL] ") + title + f" (код {proc.returncode})")
    print()
    return ok


def main() -> int:
    fast = "--fast" in sys.argv
    modules = discover_modules()
    scripts = script_modules()
    if "--list" in sys.argv:
        for name in modules:
            kind = "script" if name in scripts else "unittest"
            print(f"{name:44s} {kind}")
        print(f"\nУсього модулів: {len(modules)}")
        return 0

    results: list[tuple[str, bool]] = []
    for title, command in EXTRA_SCRIPTS:
        results.append((title, run(title, [PY, *command.split()])))
    for name in modules:
        if fast and name in LIVE_MODULES:
            continue
        path = TESTS / f"{name}.py"
        if not path.exists():
            continue                      # модуль зник під час прогону
        if name in scripts:
            results.append((name, run(name, [PY, f"tests/{name}.py"])))
        else:
            results.append((name, run(
                f"unittest tests.{name}",
                [PY, "-m", "unittest", f"tests.{name}"])))

    print("=" * 70)
    for title, ok in results:
        print(("[OK] " if ok else "[FAIL] ") + title)
    failed = [title for title, ok in results if not ok]
    print("=" * 70)
    print(f"Модулів у прогоні: {len(results)}")
    print("Усе пройдено." if not failed else f"Провалено: {', '.join(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())

