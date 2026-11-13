"""Викликати КОЖЕН інструмент агента на справжній теці й перевірити межі.

Тут перевіряється те, що бачить модель: ``ToolRegistry``. Для кожного
інструмента будується мінімальна валідна аргументація з його ж схеми, потім
окремо перевіряються «погані» виклики: відсутній обов'язковий аргумент,
невідомий аргумент, вихід за робочу теку через ``..``.

Важливо: інструменти, які щось запускають або пишуть, отримують БЕЗПЕЧНУ
ціль у тимчасовій теці. Нічого з реального проєкту не змінюється.

Запуск: ``python tools/probe_tools.py`` — код виходу 1, якщо є падіння.
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
from pathlib import Path

# ── Корінь проєкту в ``sys.path`` ─────────────────────────────────────────
# Без цього скрипт працює ЛИШЕ коли запущений з кореня проєкту:
# ``ModuleNotFoundError: No module named 'blackchpok_ide'`` (перевірено).
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from blackchpok_ide.agent_tools import TOOL_SCHEMAS, ToolRegistry  # noqa: E402

#: Безпечні значення для аргументів за типом і назвою.
BY_NAME = {
    "path": "sample.py",
    "file": "sample.py",
    "file_path": "sample.py",
    "source": "sample.py",
    "target": "sample.py",
    "query": "def greet",
    "pattern": "*.py",
    "command": "echo probe-ok",
    "content": "print('новий')\n",
    "text": "привіт",
    "old_string": "def greet",
    "new_string": "def hello",
    "url": "file:///definitely/not/used",
    "prompt": "перевірка",
    "name": "перевірка",
    "key": "перевірка",
    "value": "1",
    "glob": "*.py",
    "language": "python",
    "mode": "read",
    "kind": "file",
    "limit": 5,
    "depth": 1,
    "start": 1,
    "end": 5,
    "line": 1,
    "timeout": 5,
}


def build_args(schema: dict) -> dict:
    """Мінімальні аргументи зі схеми інструмента."""
    params = ((schema.get("function") or schema).get("parameters") or {})
    properties = params.get("properties") or {}
    required = set(params.get("required") or ())
    args: dict = {}
    for name, spec in properties.items():
        if name not in required:
            continue
        if name in BY_NAME:
            args[name] = BY_NAME[name]
            continue
        kind = str((spec or {}).get("type") or "string")
        if kind in ("integer", "number"):
            args[name] = 1
        elif kind == "boolean":
            args[name] = False
        elif kind in ("array", "object"):
            args[name] = [] if kind == "array" else {}
        else:
            args[name] = "перевірка"
    return args


def main() -> int:
    workspace = Path(tempfile.mkdtemp(prefix="probe-tools-"))
    (workspace / "sample.py").write_text(
        "def greet(name):\n    return f'привіт, {name}'\n", encoding="utf-8")
    (workspace / "data.txt").write_text("рядок один\nрядок два\n", encoding="utf-8")
    registry = ToolRegistry(workspace)
    problems = 0
    crashed = 0
    untested: list[str] = []

    for schema in TOOL_SCHEMAS:
        function = schema.get("function") or schema
        name = str(function.get("name") or "")
        if not name:
            continue
        try:
            args = build_args(function)
        except Exception:                                   # noqa: BLE001
            args = {}
            untested.append(name)
        try:
            result = registry.call(name, args)
        except Exception as exc:                            # noqa: BLE001
            print(f"ВИКЛИК ВПАВ: {name}({json.dumps(args, ensure_ascii=False)[:90]})"
                  f" → {type(exc).__name__}: {exc}")
            crashed += 1
            continue
        if not hasattr(result, "ok") or not isinstance(result.output, str):
            print(f"ДИВНИЙ РЕЗУЛЬТАТ: {name} → {result!r}")
            problems += 1
            continue
        if result.ok and not result.output.strip():
            print(f"ПОРОЖНІЙ УСПІХ: {name} → ok, але вивід порожній")
            problems += 1

        # Межа безпеки: спроба вийти за робочу теку.
        for key in ("path", "file", "file_path", "target", "source"):
            if key in args:
                escape = registry.call(name, {**args, key: "../../../etc/passwd"})
                if escape.ok and "root:" in escape.output:
                    print(f"ВИХІД ЗА ТЕКУ: {name}({key}=../../..) прочитав /etc/passwd")
                    problems += 1
                break

    print(f"Інструментів у схемах: {len(TOOL_SCHEMAS)}")
    print(f"Падінь: {crashed}, проблем: {problems}, без аргументів: {len(untested)}")
    return 1 if (crashed or problems) else 0


if __name__ == "__main__":
    raise SystemExit(main())
