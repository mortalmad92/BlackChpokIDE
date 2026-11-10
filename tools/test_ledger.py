"""Постійний реєстр тестів: що вже пройдено й коли це треба перезапускати.

НАВІЩО. Тести коштують ~210 с на повний прогін. Проганяти їх щоразу, коли
нічого не змінилось, — марна трата часу, і саме на це була скарга
користувача. Реєстр запам'ятовує результат разом із ВІДБИТКОМ коду, тому:

* код не змінювався → тест не запускається взагалі;
* змінився файл, який тест справді використовує → тест запускається;
* тест упав → він запускається завжди, доки не стане зеленим.

Відбиток НЕ «вся тека пакета»: він складається з самого файлу тесту й тих
модулів пакета, назви яких згадані в його коді. Тому правка `chat_panel.py`
не змушує перезапускати `test_neuromesh`.

Формат навмисно простий (JSON + Markdown), щоб його читав будь-який
інструмент — не лише цей. Див. ``.teststate/README.md``.

Використання::

    python tools/test_ledger.py status            # що пройдено, що застаріло
    python tools/test_ledger.py run               # запустити ЛИШЕ застарілі
    python tools/test_ledger.py run --all         # примусово все
    python tools/test_ledger.py run tests/test_x.py
    python tools/test_ledger.py mark tests/test_x.py pass --note "…"
    python tools/test_ledger.py seed --evidence "…"   # зафіксувати базовий стан
    python tools/test_ledger.py forget            # очистити реєстр
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
PACKAGE = ROOT / "blackchpok_ide"
STATE_DIR = ROOT / ".teststate"
LEDGER = STATE_DIR / "ledger.json"
REPORT = STATE_DIR / "STATUS.md"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

#: Модулі, які запускаються як скрипти (мають власний ``main()``).
LIBRARY = "unittest"
SCRIPT = "script"


# ─────────────────────────────────────────────────────────────────────────────
# Відбитки
# ─────────────────────────────────────────────────────────────────────────────

def _package_files() -> dict[str, list[Path]]:
    """Назва модуля → файли з такою назвою (у пакеті й у корені)."""
    found: dict[str, list[Path]] = {}
    candidates = list(PACKAGE.rglob("*.py")) + [
        ROOT / "main.py", ROOT / "server.py", ROOT / "agent_tools.py",
        ROOT / "rag_engine.py", ROOT / "vibe_router.py", ROOT / "night_shift.py",
    ]
    for path in candidates:
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        stem = path.stem
        if stem == "__init__":
            stem = path.parent.name
        found.setdefault(stem, []).append(path)
    return found


def _module_stems() -> set[str]:
    return set(_package_files())


def _deps_of(text: str, stems: set[str]) -> list[str]:
    """Модулі пакета, назви яких згадані в коді тесту."""
    found: list[str] = []
    for stem in stems:
        if len(stem) < 3:
            continue
        if re.search(r"\b" + re.escape(stem) + r"\b", text):
            found.append(stem)
    return sorted(found)


def fingerprint(test_path: Path) -> tuple[str, list[str]]:
    """Відбиток тесту: його вміст + вміст згаданих модулів пакета."""
    digest = hashlib.sha256()
    try:
        raw = test_path.read_bytes()
    except OSError:
        return "missing", []
    digest.update(raw)
    text = raw.decode("utf-8", "replace")
    stems = _module_stems()
    deps = _deps_of(text, stems)
    files = _package_files()
    for stem in deps:
        for path in sorted(files.get(stem, [])):
            try:
                digest.update(path.read_bytes())
            except OSError:
                continue
    return digest.hexdigest()[:16], deps


def kind_of(test_path: Path) -> str:
    """Скрипт чи unittest-модуль — визначаємо з коду, не зі списку."""
    try:
        text = test_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return LIBRARY
    has_main = re.search(r"^def main\(", text, re.MULTILINE) is not None
    if has_main and "__name__" in text:
        return SCRIPT
    return LIBRARY


def discover_tests(patterns: list[str] | None = None) -> list[Path]:
    """Усі тестові модулі на диску (або лише вказані)."""
    if patterns:
        resolved: list[Path] = []
        for pattern in patterns:
            candidate = Path(pattern)
            if not candidate.is_absolute():
                candidate = ROOT / candidate
            if candidate.is_dir():
                resolved.extend(sorted(candidate.glob("*.py")))
            elif candidate.exists():
                resolved.append(candidate)
            else:
                resolved.extend(sorted(TESTS.glob(pattern)))
        return [path for path in resolved if path.suffix == ".py"]

    found = [path for path in sorted(TESTS.glob("*.py"))
             if path.stem.startswith(("test_", "e2e_", "smoke_"))]
    return found


# ─────────────────────────────────────────────────────────────────────────────
# Реєстр
# ─────────────────────────────────────────────────────────────────────────────

def _empty() -> dict[str, Any]:
    return {"version": 1, "updated": "", "entries": {}}


def load_ledger() -> dict[str, Any]:
    if not LEDGER.exists():
        return _empty()
    try:
        data = json.loads(LEDGER.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty()
    if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
        return _empty()
    return data


def save_ledger(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    data["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    LEDGER.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    REPORT.write_text(render_markdown(data), encoding="utf-8")


def _key(test_path: Path) -> str:
    """Ключ у реєстрі — шлях від кореня з прямими слешами."""
    try:
        return test_path.relative_to(ROOT).as_posix()
    except ValueError:
        return test_path.as_posix()


def _state_of(entry: dict[str, Any] | None, print_now: str) -> str:
    if not entry:
        return "never"
    if entry.get("status") == "fail":
        return "fail"
    if entry.get("fingerprint") != print_now:
        return "stale"
    return "fresh"


_STATE_ORDER = {"fail": 0, "never": 1, "stale": 2, "fresh": 3}
_STATE_TEXT = {
    "fail": "ПАДАЄ",
    "never": "не запускався",
    "stale": "застарів (код змінився)",
    "fresh": "пройдено, код не змінювався",
}


def survey(patterns: list[str] | None = None) -> list[dict[str, Any]]:
    """Порахувати стан кожного тесту без запуску."""
    ledger = load_ledger()
    rows: list[dict[str, Any]] = []
    for path in discover_tests(patterns):
        key = _key(path)
        print_now, deps = fingerprint(path)
        entry = ledger["entries"].get(key)
        rows.append({
            "key": key,
            "path": path,
            "state": _state_of(entry, print_now),
            "fingerprint": print_now,
            "stored": (entry or {}).get("fingerprint", ""),
            "deps": deps,
            "entry": entry,
            "kind": (entry or {}).get("kind") or kind_of(path),
        })
    rows.sort(key=lambda row: (_STATE_ORDER[row["state"]], row["key"]))
    return rows


def render_markdown(data: dict[str, Any]) -> str:
    """Людино-читний звіт: його розуміє й інший інструмент."""
    entries = data.get("entries", {})
    lines = [
        "# Стан тестів (автоматично, не правити руками)",
        "",
        "Створено: `tools/test_ledger.py`. Оновлено: "
        f"{data.get('updated') or '—'}",
        "",
        "**Якщо ти ШІ-агент:** перш ніж запускати тести, виконай "
        "`python tools/test_ledger.py status`. Запускай лише ті, що "
        "позначені «не запускався», «застарів» або «ПАДАЄ».",
        "",
        "| Тест | Стан | Тип | Оновлено | Нотатка |",
        "|---|---|---|---|---|",
    ]
    order = {"fail": 0, "passed": 1}
    for key, entry in sorted(entries.items(),
                             key=lambda item: (order.get(item[1].get("status"), 2),
                                               item[0])):
        status = entry.get("status", "")
        mark = "ПАДАЄ" if status == "fail" else "пройдено"
        lines.append(
            f"| `{key}` | {mark} | {entry.get('kind', '')} | "
            f"{entry.get('when', '')} | {(entry.get('note') or '')[:60]} |")
    failures = [key for key, entry in entries.items() if entry.get("status") == "fail"]
    lines.extend(["", "## Підсумок", ""])
    lines.append(f"- Усього записів: **{len(entries)}**")
    lines.append(f"- Падає: **{len(failures)}**"
                 + (f" — {', '.join(failures)}" if failures else ""))
    lines.append("")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Запуск
# ─────────────────────────────────────────────────────────────────────────────

def run_one(test_path: Path, kind: str) -> tuple[bool, str, float]:
    """Запустити один модуль. Повертає (успіх, вивід, секунди)."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env.setdefault("BLACKCHPOK_HOME", str(ROOT / ".buildtmp" / "ledger-home"))
    env.setdefault("BLACKCHPOK_NO_SAVE", "1")
    if kind == SCRIPT:
        command = [sys.executable, str(test_path)]
    else:
        # ``-m unittest`` з модулем без пакета tests: додаємо корінь у PYTHONPATH.
        command = [sys.executable, "-m", "unittest",
                   f"tests.{test_path.stem}"]
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    started = time.perf_counter()
    try:
        done = subprocess.run(command, cwd=str(ROOT), env=env,
                              capture_output=True, text=True, timeout=900)
        output = (done.stdout or "") + (done.stderr or "")
        ok = done.returncode == 0
    except subprocess.TimeoutExpired:
        output = "Тайм-аут 900 с"
        ok = False
    except OSError as exc:
        output = f"Не запустилось: {exc}"
        ok = False
    return ok, output, time.perf_counter() - started


def _tail(output: str, lines: int = 12) -> str:
    return "\n".join(output.strip().splitlines()[-lines:])


def command_status(show_all: bool) -> int:
    rows = survey()
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    width = max((len(row["key"]) for row in rows), default=10)
    print(f"{'ТЕСТ':<{width}} {'СТАН':<26} ТИП")
    print("-" * (width + 34))
    for row in rows:
        if not show_all and row["state"] == "fresh":
            continue
        note = ""
        if row["state"] == "fail" and row["entry"]:
            note = "  ← " + (row["entry"].get("note") or "").splitlines()[0][:50]
        print(f"{row['key']:<{width}} {_STATE_TEXT[row['state']]:<26} "
              f"{row['kind']}{note}")
    print()
    for state in ("fail", "never", "stale", "fresh"):
        print(f"  {_STATE_TEXT[state]:<26} {counts.get(state, 0)}")
    to_run = counts.get("fail", 0) + counts.get("never", 0) + counts.get("stale", 0)
    print()
    if to_run:
        print(f"Треба запустити: {to_run} з {len(rows)}. "
              "Команда: python tools/test_ledger.py run")
    else:
        print(f"Усі {len(rows)} тестів актуальні — запускати нічого не треба.")
    print(f"Звіт для людей: {REPORT.relative_to(ROOT)}")
    return 0


def command_run(args) -> int:
    rows = survey(args.patterns or None)
    if args.all:
        chosen = rows
    elif args.patterns:
        chosen = rows
    else:
        chosen = [row for row in rows if row["state"] != "fresh"]
    if not chosen:
        print(f"Усі {len(rows)} тестів актуальні — нічого не запускаю.")
        return 0

    ledger = load_ledger()
    print(f"Запускаю {len(chosen)} тест(ів) із {len(rows)}.\n")
    failed: list[str] = []
    for index, row in enumerate(chosen, 1):
        path = row["path"]
        print(f"[{index}/{len(chosen)}] {row['key']} …", end=" ", flush=True)
        ok, output, seconds = run_one(path, row["kind"])
        status = "passed" if ok else "fail"
        ledger["entries"][row["key"]] = {
            "fingerprint": row["fingerprint"],
            "status": status,
            "kind": row["kind"],
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_s": round(seconds, 1),
            "deps": row["deps"],
            "note": "" if ok else _tail(output, 14),
            "machine": platform.node(),
            "python": platform.python_version(),
        }
        save_ledger(ledger)
        if ok:
            print(f"OK ({seconds:.1f} с)")
        else:
            failed.append(row["key"])
            print(f"ПАДІННЯ ({seconds:.1f} с)")
            print("  " + _tail(output, 8).replace("\n", "\n  "))

    print()
    if failed:
        print("Провалено:", ", ".join(failed))
        return 1
    print("Усе пройдено.")
    return 0


def command_mark(args) -> int:
    ledger = load_ledger()
    changed = 0
    for path in discover_tests(args.patterns):
        key = _key(path)
        print_now, deps = fingerprint(path)
        ledger["entries"][key] = {
            "fingerprint": print_now,
            "status": args.status,
            "kind": kind_of(path),
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_s": 0.0,
            "deps": deps,
            "note": args.note or "",
            "machine": platform.node(),
            "python": platform.python_version(),
        }
        changed += 1
        print(f"{key}: {args.status}")
    save_ledger(ledger)
    print(f"Оновлено записів: {changed}")
    return 0


def command_seed(args) -> int:
    """Зафіксувати базовий стан: усе пройдено, крім названих винятків."""
    exceptions = {item.strip() for item in (args.except_for or "").split(",")
                  if item.strip()}
    ledger = load_ledger()
    seeded = 0
    for path in discover_tests():
        key = _key(path)
        print_now, deps = fingerprint(path)
        failing = any(token in key for token in exceptions)
        ledger["entries"][key] = {
            "fingerprint": print_now,
            "status": "fail" if failing else "passed",
            "kind": kind_of(path),
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_s": 0.0,
            "deps": deps,
            "note": (args.note or "") if failing else "",
            "machine": platform.node(),
            "python": platform.python_version(),
            "evidence": args.evidence or "",
        }
        seeded += 1
    save_ledger(ledger)
    print(f"Базовий стан зафіксовано для {seeded} тестів.")
    if exceptions:
        print("Позначено як проблемні:", ", ".join(sorted(exceptions)))
    print(f"Звіт: {REPORT.relative_to(ROOT)}")
    return 0


def command_forget(_args) -> int:
    if LEDGER.exists():
        LEDGER.unlink()
    if REPORT.exists():
        REPORT.unlink()
    print("Реєстр очищено. Наступний прогін запустить усе.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Постійний реєстр результатів тестів")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="показати стан без запуску")
    status.add_argument("--all", action="store_true",
                        help="показати й ті, що вже пройдені")

    run = sub.add_parser("run", help="запустити лише застарілі тести")
    run.add_argument("patterns", nargs="*", help="конкретні файли або шаблони")
    run.add_argument("--all", action="store_true", help="примусово все")

    mark = sub.add_parser("mark", help="вручну поставити стан")
    mark.add_argument("patterns", nargs="+")
    mark.add_argument("status", choices=["pass", "passed", "fail"])
    mark.add_argument("--note", default="")

    seed = sub.add_parser("seed", help="зафіксувати базовий стан")
    seed.add_argument("--evidence", default="", help="чим підтверджено")
    seed.add_argument("--except", dest="except_for", default="",
                      help="підрядки шляхів, які позначити як проблемні")
    seed.add_argument("--note", default="", help="нотатка для проблемних")

    sub.add_parser("forget", help="очистити реєстр")

    args = parser.parse_args()
    if args.command == "status":
        return command_status(args.all)
    if args.command == "run":
        return command_run(args)
    if args.command == "mark":
        if args.status == "pass":
            args.status = "passed"
        return command_mark(args)
    if args.command == "seed":
        return command_seed(args)
    return command_forget(args)


if __name__ == "__main__":
    raise SystemExit(main())
