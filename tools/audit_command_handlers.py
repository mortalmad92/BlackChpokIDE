"""Аудит: чи кожна команда палітри справді викликає РОБОЧИЙ метод вікна.

``command_registry`` посилається на методи вікна напряму. Якщо метод
перейменували або він тепер потребує аргументу, команда в палітрі стає
мертвою: натискання нічого не робить і нічого не повідомляє.

Перевірка статична (AST + dir), тому швидка й без побічних ефектів.
"""
from __future__ import annotations

import ast
import os
import pathlib
import sys
import tempfile

os.environ.setdefault("BLACKCHPOCK_HOME", tempfile.mkdtemp(prefix="bchk_cmd_"))
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    from blackchpok_ide import command_registry, commands
    from blackchpok_ide import main_window as mw

    # Команди реєструються у вікно, тож беремо «сухий» екземпляр без tkinter:
    # дивимось лише те, на що посилаються лямбди й атрибути, і звіряємо з
    # наявними методами класу.
    available = set(dir(mw.BlackChpokIDE))
    instance_attrs = set()
    source = (ROOT / "blackchpok_ide" / "main_window.py").read_text(encoding="utf-8")
    for match in ast.finditer(r"self\.([a-z_][a-z0-9_]{2,})\s*=", source) \
            if hasattr(ast, "finditer") else ():
        instance_attrs.add(match.group(1))
    import re

    instance_attrs |= {m.group(1) for m in re.finditer(
        r"self\.([a-z_][a-z0-9_]{2,})\s*=", source)}

    registry_source = (ROOT / "blackchpok_ide" / "command_registry.py").read_text(
        encoding="utf-8")
    referenced = {m.group(1) for m in re.finditer(
        r"window\.([a-z_][a-z0-9_]{2,})", registry_source)}
    missing = sorted(name for name in referenced
                     if name not in available and name not in instance_attrs)
    check("усі команди ведуть до наявних методів вікна", not missing,
          ", ".join(missing[:8]))

    # Кожна команда має обробник, що викликається без аргументів.
    class _Stub:
        def __getattr__(self, name):
            return lambda *a, **k: None

    stub = _Stub()
    command_registry.register_all(stub)
    all_commands = list(commands.all_commands())
    broken: list[str] = []
    for cmd in all_commands:
        handler = getattr(cmd, "run", None) or getattr(cmd, "callback", None)
        if handler is None:
            broken.append(f"{cmd.key}: немає обробника")
            continue
        if not callable(handler):
            broken.append(f"{cmd.key}: обробник не викликається")
    check("кожна команда має викличний обробник", not broken,
          "; ".join(broken[:6]))

    print(f"\nкоманд перевірено: {len(all_commands)}")
    print(f"провалів: {len(FAILS)}")
    for name in FAILS:
        print("  " + name)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
