"""Скасування роботи агента: «Стоп» справді зупиняє й не лишає сміття.

Перевіряє: після cancel() агент не `busy`, файли не напівзаписані,
повторний запуск працює.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import threading
import time

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchk_cancel_"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from blackchpok_ide import agent as agent_mod  # noqa: E402
from blackchpok_ide import agent_tools  # noqa: E402
from blackchpok_ide.config import Settings  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    work = pathlib.Path(tempfile.mkdtemp(prefix="bchk_cancel_ws_"))
    settings = Settings()
    settings.llm.base_url = "http://127.0.0.1:59999/v1"   # нікого немає
    settings.llm.timeout = 30
    settings.agent.max_steps = 5
    registry = agent_tools.ToolRegistry(work)
    runner = agent_mod.AgentRunner(registry, settings.llm, settings.agent, work)

    check("спочатку агент вільний", not runner.busy)

    # Запускаємо в фоні й одразу скасовуємо.
    done = threading.Event()

    def job() -> None:
        try:
            runner.run_blocking("зроби щось дуже довге")
        except Exception:  # noqa: BLE001 - очікувано
            pass
        finally:
            done.set()

    thread = threading.Thread(target=job, daemon=True)
    thread.start()
    time.sleep(0.6)
    started = time.monotonic()
    runner.cancel()
    finished = done.wait(timeout=20)
    took = time.monotonic() - started

    check("скасування зупиняє роботу", finished, f"чекали 20 с, минуло {took:.1f}")
    check("скасування швидке (<15 с)", took < 15, f"{took:.1f} с")
    time.sleep(0.5)
    check("після скасування агент вільний", not runner.busy)

    # Повторний запуск не має падати через залишковий стан.
    try:
        runner.run_blocking("привіт")
        check("повторний запуск не падає", True)
    except Exception as exc:  # noqa: BLE001
        # Мережі немає, тож помилка очікувана — важливо, що не TypeError.
        check("повторний запуск не падає",
              not isinstance(exc, (TypeError, AttributeError, KeyError)),
              f"{type(exc).__name__}: {str(exc)[:100]}")

    files = sorted(p.name for p in work.iterdir())
    check("скасування не лишило файлів", not files, str(files))

    print(f"\nпровалів: {len(FAILS)}")
    for name in FAILS:
        print("  " + name)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
