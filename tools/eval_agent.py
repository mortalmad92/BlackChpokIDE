"""Стенд: різні АРХЕТИПИ задач на реальній моделі.

Кожен сценарій готує проєкт-пісочницю й перевіряє ФАКТ на диску. Мета —
знайти реальні провали, а не підтвердити, що просте працює.

Запуск:
    .venv\\Scripts\\python.exe tools\\eval_agent.py            # усі
    .venv\\Scripts\\python.exe tools\\eval_agent.py edit fix   # окремі
"""

from __future__ import annotations

import py_compile
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Підготовка пісочниць ───────────────────────────────────────────────────

CALC_BROKEN = '''"""Калькулятор."""


def add(a, b):
    return a + b


def divide(a, b):
    return a / b


def average(numbers):
    total = 0
    for n in numbers:
        total += n
    return total / len(numbers)
'''

CALC_BROKEN_WITH_BUG = CALC_BROKEN.replace(
    "    return total / len(numbers)",
    "    return total / (len(numbers) - 1)")   # ділення на нуль для [x]

TEXT_SAMPLE = """Проєкт: замітки

Цей файл описує маленький проєкт.
Тут три рядки.
"""


def _setup_simple(workspace: Path) -> None:
    """Порожня тека."""


def _setup_existing(workspace: Path) -> None:
    (workspace / "calc.py").write_text(CALC_BROKEN, encoding="utf-8")


def _setup_bug(workspace: Path) -> None:
    (workspace / "calc.py").write_text(CALC_BROKEN_WITH_BUG, encoding="utf-8")
    (workspace / "run.py").write_text(
        "from calc import average\nprint(average([2, 4, 6]))\n", encoding="utf-8")


def _setup_text(workspace: Path) -> None:
    (workspace / "notes.txt").write_text(TEXT_SAMPLE, encoding="utf-8")


def _setup_tests(workspace: Path) -> None:
    (workspace / "calc.py").write_text(CALC_BROKEN, encoding="utf-8")
    (workspace / "test_calc.py").write_text(
        "import unittest\nfrom calc import add\n\n\n"
        "class T(unittest.TestCase):\n"
        "    def test_add(self):\n"
        "        self.assertEqual(add(2, 3), 5)\n", encoding="utf-8")


def _setup_two(workspace: Path) -> None:
    (workspace / "calc.py").write_text(CALC_BROKEN, encoding="utf-8")
    (workspace / "notes.txt").write_text(TEXT_SAMPLE, encoding="utf-8")


# ── Перевірки результату ──────────────────────────────────────────────────

def _python_ok(workspace: Path) -> tuple[bool, str]:
    """Усі .py-файли в теці компілюються."""
    broken: list[str] = []
    for path in workspace.rglob("*.py"):
        try:
            py_compile.compile(str(path), doraise=True)
        except Exception as exc:  # noqa: BLE001
            broken.append(f"{path.name}: {str(exc)[:80]}")
    return (not broken), "; ".join(broken)


def _has_text(workspace: Path, name: str, needle: str) -> tuple[bool, str]:
    path = workspace / name
    if not path.exists():
        return False, f"немає файлу {name}"
    body = path.read_text(encoding="utf-8", errors="replace")
    return (needle.lower() in body.lower()), f"{name}: {body[:80]!r}"


def _file_exists(workspace: Path, name: str) -> tuple[bool, str]:
    return (workspace / name).exists(), str(sorted(p.name for p in workspace.iterdir()))


def _all_python_ok_plus(workspace: Path, needle: str) -> tuple[bool, str]:
    ok, detail = _python_ok(workspace)
    if not ok:
        return False, detail
    blob = " ".join(
        p.read_text(encoding="utf-8", errors="replace").lower()
        for p in workspace.rglob("*.py"))
    return (needle.lower() in blob), f"шукали {needle!r}"


# ── Сценарії ──────────────────────────────────────────────────────────────

Scenario = tuple[str, str, Callable[[Path], None], str, Callable[[Path], tuple[bool, str]]]

SCENARIOS: dict[str, Scenario] = {
    "create": (
        "Створення з нуля",
        "зроби мені калькулятор на пітоні з додаванням і діленням",
        _setup_simple,
        "усі .py компілюються",
        _python_ok,
    ),
    "edit": (
        "Правка наявного файлу",
        "у файлі calc.py додай функцію множення multiply",
        _setup_existing,
        "у calc.py є multiply",
        lambda ws: _all_python_ok_plus(ws, "def multiply"),
    ),
    "fix": (
        "Виправлення помилки за скаргою",
        "програма падає з помилкою коли запускаю run.py, виправ",
        _setup_bug,
        "усі .py компілюються й average не ділить на нуль",
        lambda ws: _all_python_ok_plus(ws, "len(numbers)"),
    ),
    "upgrade": (
        "Доповнення наявного тексту",
        "додай у notes.txt четвертий рядок про тести",
        _setup_text,
        "у notes.txt є згадка тестів",
        lambda ws: _has_text(ws, "notes.txt", "тест"),
    ),
    "test": (
        "Запуск тестів і звіт",
        "запусти тести й скажи чи проходять",
        _setup_tests,
        "усі .py компілюються",
        _python_ok,
    ),
    "read": (
        "Пояснення без змін",
        "що робить функція average у calc.py",
        _setup_existing,
        "файл не зламано",
        _python_ok,
    ),
    "refactor": (
        "Перейменування по всьому проєкту",
        "перейменуй функцію average на mean у всьому проєкті",
        _setup_existing,
        "немає старого імені, є нове",
        lambda ws: _rename_ok(ws, "average", "mean"),
    ),
    "multi": (
        "Кілька робіт в одному реченні",
        "додай у calc.py функцію множення, а в notes.txt запиши що це "
        "зроблено",
        _setup_two,
        "у calc.py є multiply, у notes.txt дописано (не затерто)",
        # Перевіряємо САМЕ факт дописування: попередній вміст notes.txt
        # мусить лишитись, а новий рядок — з'явитись. Пошук конкретного
        # слова («зробл») хибно падав, коли модель писала «Додана функція».
        lambda ws: _appended_keeps_old(ws, "notes.txt", "замітки"),
    ),
    "docs": (
        "Документація до коду",
        "напиши в README.md як користуватись калькулятором",
        _setup_existing,
        "з'явився README з описом",
        lambda ws: _file_mentions_any(ws, "README.md",
                                      ("calc", "калькул", "функц")),
    ),
    "guard": (
        "Питання не має ламати файли",
        "як працює калькулятор взагалі?",
        _setup_existing,
        "файл без змін",
        lambda ws: _unchanged_calc(ws),
    ),
}


def _rename_ok(workspace: Path, old: str, new: str) -> tuple[bool, str]:
    blob = " ".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in workspace.rglob("*.py"))
    has_old = f"def {old}" in blob
    has_new = f"def {new}" in blob
    ok, detail = _python_ok(workspace)
    return (has_new and not has_old and ok,
            f"стара={has_old} нова={has_new} {detail}")


def _both(workspace: Path, file_a: str, needle_a: str,
          file_b: str, needle_b: str) -> tuple[bool, str]:
    ok_a, _ = _has_text(workspace, file_a, needle_a)
    ok_b, _ = _has_text(workspace, file_b, needle_b)
    ok_py, detail = _python_ok(workspace)
    return (ok_a and ok_b and ok_py,
            f"{file_a}:{ok_a} {file_b}:{ok_b} {detail}")


def _appended_keeps_old(workspace: Path, name: str,
                        must_keep: str) -> tuple[bool, str]:
    """Файл доповнено, а не затерто: старий текст лишився, новий додався."""
    path = workspace / name
    if not path.exists():
        return False, f"немає {name}"
    body = path.read_text(encoding="utf-8", errors="replace")
    kept = must_keep.lower() in body.lower()
    grew = len(body.strip()) > len(TEXT_SAMPLE.strip())
    calc = workspace / "calc.py"
    calc_ok = calc.exists() and "def multiply" in calc.read_text(
        encoding="utf-8", errors="replace")
    ok_py, detail = _python_ok(workspace)
    return (kept and grew and calc_ok and ok_py,
            f"старий текст={kept} дописано={grew} multiply={calc_ok} {detail}")


def _file_mentions(workspace: Path, name: str, needle: str) -> tuple[bool, str]:
    return _file_mentions_any(workspace, name, (needle,))


def _file_mentions_any(workspace: Path, name: str,
                       needles: tuple[str, ...]) -> tuple[bool, str]:
    """Файл існує й згадує хоч одне з ключових слів.

    Кілька варіантів потрібні, бо модель пише природною мовою: на прохання
    про «калькулятор» вона цілком слушно напише «калькулятор», а не
    «calc» — і перевірка не має цього вважати провалом.
    """
    path = workspace / name
    if not path.exists():
        found = [p for p in workspace.rglob("*.md")]
        if not found:
            files = sorted(p.name for p in workspace.iterdir() if p.is_file())
            return False, f"немає {name}; файли: {files}"
        path = found[0]
    body = path.read_text(encoding="utf-8", errors="replace")
    low = body.lower()
    hit = next((word for word in needles if word in low), "")
    return (bool(hit) and len(body.strip()) > 20,
            f"{path.name}: {len(body)} символів, збіг={hit or '—'}")


def _unchanged_calc(workspace: Path) -> tuple[bool, str]:
    path = workspace / "calc.py"
    if not path.exists():
        return False, "файл зник"
    body = path.read_text(encoding="utf-8", errors="replace")
    return (body.strip() == CALC_BROKEN.strip(), "файл змінено без прохання")


def pump(app, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        try:
            app.update()
        except Exception:  # noqa: BLE001
            return
        time.sleep(0.01)


def run_scenario(key: str) -> tuple[bool, str]:
    title, phrase, setup, expect, verify = SCENARIOS[key]
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb

    mb.askyesno = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    fd.askdirectory = lambda *a, **k: ""

    from blackchpok_ide.config import Settings

    workspace = Path(tempfile.mkdtemp(prefix=f"eval-{key}-"))
    setup(workspace)

    settings = Settings.load()
    settings.workspace = str(workspace)
    settings.first_run_done = True
    settings.project_chosen = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False
    settings.agent.max_steps = 14
    settings.ui.view = "workspace"

    from blackchpok_ide.main_window import BlackChpokIDE

    print()
    print("=" * 76)
    print(f"[{key}] {title}")
    print(f"фраза: «{phrase}»")
    print(f"очікуємо: {expect}")
    print("=" * 76)

    app = BlackChpokIDE(settings)
    app.geometry("1400x860")
    events: list[tuple[str, str]] = []
    original = app.chat._handle_event

    def spy(event):
        events.append((event.kind, " ".join(str(event.text or "").split())[:100]))
        return original(event)

    app.chat._handle_event = spy
    try:
        pump(app, 1.8)
        app.hide_welcome()
        pump(app, 0.4)
        idle = 0.0
        while app.agent.busy and idle < 90:
            pump(app, 0.5)
            idle += 0.5

        started = time.time()
        app.chat._send(phrase)
        waited = 0.0
        while app.agent.busy and waited < 600:
            pump(app, 0.5)
            waited += 0.5
        pump(app, 0.5)

        # Якщо склали план — дочікуємось виконання
        if app._planning:
            while app._planning and time.time() - started < 700:
                pump(app, 0.5)
        if app.task_queue.tasks:
            print(f"   план: {len(app.task_queue.tasks)} кроків")
            run_start = time.time()
            while time.time() - run_start < 600:
                pump(app, 0.5)
                if app.task_queue.paused:
                    app.resume_queue()
                if not app.task_queue.running_id and not app.agent.busy:
                    if app.executor.next_task() is None:
                        break
                    app.executor.start_next()

        elapsed = time.time() - started
        ok, detail = verify(workspace)
        print(f"   витрачено: {elapsed:.0f} с")
        print(f"   файли: {sorted(p.name for p in workspace.iterdir() if p.is_file())}")
        if not ok:
            # Показуємо ФАКТИЧНИЙ вміст файлів, а не лише «не зійшлось»:
            # без цього незрозуміло, що саме агент зробив не так.
            for path in sorted(workspace.iterdir()):
                if path.is_file() and not path.name.endswith(".bak"):
                    body = path.read_text(encoding="utf-8", errors="replace")
                    print(f"   вміст {path.name} ({len(body)} симв): "
                          f"{body[:160]!r}")
        if app.task_queue.tasks:
            print(f"   черга: {app.task_queue.progress()}")
        print(f"[{'OK  ' if ok else 'FAIL'}] {expect}" + (f" — {detail}" if detail else ""))
        if not ok:
            print("   останні події:")
            for kind, text in events[-10:]:
                if kind in ("status", "tool_call", "error", "assistant"):
                    print(f"     [{kind}] {text}")
        return ok, f"{key}: {phrase}"
    finally:
        try:
            app.agent.cancel()
            app.task_queue.clear()
            app.destroy()
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(workspace, ignore_errors=True)


def main() -> int:
    wanted = [a for a in sys.argv[1:] if a in SCENARIOS] or list(SCENARIOS)
    unknown = [a for a in sys.argv[1:] if a not in SCENARIOS and not a.startswith("-")]
    if unknown:
        print("Невідомі сценарії:", ", ".join(unknown))
        print("Доступні:", ", ".join(SCENARIOS))
        return 2

    results: list[tuple[bool, str]] = []
    for key in wanted:
        try:
            results.append(run_scenario(key))
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {key}: виняток {type(exc).__name__}: {exc}")
            results.append((False, f"{key}: виняток"))

    print()
    print("=" * 76)
    for ok, label in results:
        print(("[OK  ] " if ok else "[FAIL] ") + label)
    passed = sum(1 for ok, _ in results if ok)
    print("=" * 76)
    print(f"Пройдено {passed} з {len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
