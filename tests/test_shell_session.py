"""Перевірка постійної сесії оболонки (двигун вбудованого терміналу IDE).

Запуск:
    python tests\\test_shell_session.py

Скрипт працює зі справжнім cmd.exe, тому перевіряє саме те, що побачить
користувач у вбудованому терміналі. Повертає 0, якщо всі перевірки успішні.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blackchpok_ide.shell_session import (  # noqa: E402
    ShellSession,
    available_shell,
    run_once,
    strip_ansi,
)

failures = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    """Надрукувати результат однієї перевірки."""
    global failures
    print(f"[{'OK  ' if condition else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures += 1


def _short(text: str, limit: int = 160) -> str:
    """Обрізати довгий вивід для рядка деталей."""
    flat = text.replace("\r", "").replace("\n", " ⏎ ")
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _same_path(left: Path, right: Path) -> bool:
    """Порівняти теки без урахування регістру та хвостового розділювача."""
    try:
        return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(
            os.path.normpath(str(right))
        )
    except (OSError, ValueError):
        return False


def _which(name: str) -> str:
    """Знайти виконуваний файл у PATH (порожній рядок, якщо немає)."""
    import shutil

    return shutil.which(name) or ""


def main() -> int:
    """Прогнати всі перевірки та повернути код виходу процесу."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

    started = time.monotonic()
    temp = Path(os.environ.get("TEMP", str(ROOT)))
    shell = available_shell()
    check("available_shell() повертає наявний файл", bool(shell) and Path(shell).exists(), shell)

    session = ShellSession(temp, timeout=30.0)
    outputs: list[str] = []
    session._on_output = outputs.append  # перевіряємо, що колбек справді кличеться
    try:
        # 1. старт
        alive = session.start()
        check("start() повертає True, сесія жива", alive and session.running, f"pid={session.pid}")

        # 2. проста команда
        code, out = session.run("echo hello-bchp")
        check(
            'run("echo hello-bchp") → код 0 і вивід',
            code == 0 and "hello-bchp" in out,
            f"код={code}, вивід={_short(out)}",
        )
        check(
            "маркери не протікають у вивід",
            "__BCHPOK" not in out,
            _short(out) if "__BCHPOK" in out else "",
        )

        # 3. стан сесії зберігається між командами
        code_cd, _ = session.run("cd /d %TEMP%")
        code_pwd, pwd_out = session.run("cd")
        expected = Path(os.environ.get("TEMP", str(temp)))
        check(
            "cd зберігається, session.cwd оновився",
            code_cd == 0
            and code_pwd == 0
            and _same_path(session.cwd, expected)
            and os.path.normcase(os.path.normpath(pwd_out.strip())) == os.path.normpath(
                os.path.normcase(str(expected))
            ),
            f"cwd={session.cwd}, вивід cd={_short(pwd_out)}",
        )

        # 4. ненульовий код виходу не вбиває сесію
        code, out = session.run("cmd /c exit 7")
        still = session.running
        after = session.run("echo after-fail")
        check(
            'run("cmd /c exit 7") → код 7, сесія жива',
            code == 7 and still and after[0] == 0 and "after-fail" in after[1],
            f"код={code}, жива={still}, далі={_short(after[1])}",
        )
        check("last_exit_code відображає останню команду", session.last_exit_code == 0,
              f"last_exit_code={session.last_exit_code}")

        # 5. Unicode
        code, out = session.run("echo привіт-світ")
        check(
            "Unicode-вивід echo привіт-світ",
            code == 0 and "привіт-світ" in out,
            f"код={code}, вивід={_short(out)}",
        )

        # 6. переривання довгої команди
        box: dict[str, tuple[int, str]] = {}

        def worker() -> None:
            box["value"] = session.run("ping -n 30 127.0.0.1", timeout=60.0)

        moment = time.monotonic()
        thread = threading.Thread(target=worker, daemon=True, name="bchpok-ping")
        thread.start()
        time.sleep(1.5)
        session.interrupt()
        thread.join(15.0)
        elapsed = time.monotonic() - moment
        recovered = session.run("echo ok")
        check(
            "interrupt() повертає керування швидко",
            not thread.is_alive() and elapsed < 5.0 and "value" in box,
            f"{elapsed:.2f} с",
        )
        check(
            "після interrupt() сесія відповідає",
            session.running and recovered[0] == 0 and "ok" in recovered[1],
            f"код={recovered[0]}, вивід={_short(recovered[1])}",
        )

        # порожня команда
        check("порожня команда → (0, '')", session.run("   ") == (0, ""))

        # історія
        check(
            "history зберігає команди (нові — в кінці)",
            "echo hello-bchp" in session.history
            and session.history[-1] == "echo ok"
            and session.history.index("echo hello-bchp")
            < session.history.index("echo ok"),
            f"останні: {session.history[-3:]}",
        )
    finally:
        # 7. подвійний stop()
        try:
            session.stop()
            second_ok = True
        except Exception as exc:  # noqa: BLE001
            second_ok = False
            print("   stop() кинув:", exc)
        try:
            session.stop()
            double_ok = True
        except Exception as exc:  # noqa: BLE001
            double_ok = False
            print("   повторний stop() кинув:", exc)
        check("stop() двічі не кидає, running=False",
              second_ok and double_ok and not session.running)

    # 8. strip_ansi
    coloured = "\x1b[31mred\x1b[0m"
    check("strip_ansi прибирає кольори", strip_ansi(coloured) == "red", repr(strip_ansi(coloured)))
    check(
        "strip_ansi прибирає обірваний CSI",
        strip_ansi("abc\x1b[") == "abc",
        repr(strip_ansi("abc\x1b[")),
    )

    # резервний шлях
    code, out = run_once("echo once-bchp", temp, timeout=30.0)
    check("run_once() виконує команду", code == 0 and "once-bchp" in out,
          f"код={code}, вивід={_short(out)}")

    # перевірка «схожого на маркер» виводу
    probe = ShellSession(temp, timeout=20.0)
    try:
        probe.start()
        code, out = probe.run("echo __BCHPOK_DONE_deadbeef__0")
        check(
            "вивід, схожий на маркер, не ковтається",
            code == 0 and "__BCHPOK_DONE_deadbeef__0" in out,
            f"код={code}, вивід={_short(out)}",
        )
        code, out = probe.run("nonexistent-command-xyz")
        check(
            "невідома команда → ненульовий код",
            code != 0 and "не є внутрішньою" not in out,
            f"код={code}, вивід={_short(out)}",
        )
        probe.set_cwd(ROOT)
        check(
            "set_cwd() переводить сесію в іншу теку",
            _same_path(probe.cwd, ROOT) and _same_path(
                Path(probe.run("cd")[1].strip()), ROOT
            ),
            f"cwd={probe.cwd}",
        )
        probe.set_cwd(Path(r"C:\nope\blackchpok-missing"))
        check(
            "set_cwd() з неіснуючим шляхом не кидає",
            _same_path(probe.cwd, ROOT),
            f"cwd={probe.cwd}",
        )
    finally:
        probe.stop()

    check("колбек on_output отримував рядки", bool(outputs), f"рядків: {len(outputs)}")
    check("transcript наповнився", len(session.transcript) > 0, f"рядків: {len(session.transcript)}")

    # необовʼязково: PowerShell як альтернативна оболонка
    pwsh = next(
        (name for name in ("pwsh.exe", "powershell.exe") if _which(name)), ""
    )
    if pwsh:
        alt = ShellSession(ROOT, shell=pwsh, timeout=20.0)
        try:
            opened = alt.start()
            code, out = alt.run("cmd /c exit 7")
            reply = alt.run("echo ps-alive")
            check(
                f"PowerShell ({pwsh}) тримає сесію та код виходу",
                opened and code == 7 and reply[0] == 0 and "ps-alive" in reply[1],
                f"код={code}, далі={_short(reply[1])}",
            )
        finally:
            alt.stop()

    total = time.monotonic() - started
    print(f"\nЧас виконання: {total:.2f} с")
    if failures:
        print(f"Провалено перевірок: {failures}")
        return 1
    print("Усі перевірки пройдено.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
