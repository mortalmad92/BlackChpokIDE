"""Стійкість до збоїв: сервер зник, хибна адреса, величезний текст.

Перевіряє, що користувач бачить зрозуміле повідомлення, а не стектрейс,
і що застосунок не зависає.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import time

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchk_fault_"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from blackchpok_ide import llm_client  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    # 1. Мертвий порт: швидка й зрозуміла помилка, без зависання.
    client = llm_client.LLMClient("http://127.0.0.1:59999/v1", "тест", timeout=3)
    started = time.monotonic()
    try:
        client.chat([{"role": "user", "content": "привіт"}])
        check("мертвий сервер дає помилку", False, "виклик «успішний»")
    except Exception as exc:  # noqa: BLE001
        took = time.monotonic() - started
        message = str(exc)
        check("мертвий сервер дає помилку", True)
        check("помилка зрозуміла людині",
              any(word in message.lower() for word in
                  ("з'єдна", "сервер", "недоступ", "відмов", "мереж", "connect",
                   "refused", "timeout", "час")), message[:150])
        check("помилка швидка (<15 с)", took < 15, f"{took:.1f} с")

    # 2. Хибна адреса: помилка без падіння.
    client2 = llm_client.LLMClient("не-адреса", "тест", timeout=2)
    try:
        client2.chat([{"role": "user", "content": "привіт"}])
        check("хибна адреса дає помилку", False, "виклик «успішний»")
    except Exception:  # noqa: BLE001
        check("хибна адреса дає помилку", True)

    # 3. Порожній список повідомлень.
    client3 = llm_client.LLMClient("http://127.0.0.1:59999/v1", "тест", timeout=2)
    try:
        client3.chat([])
        check("порожній запит не валить", True)
    except Exception as exc:  # noqa: BLE001
        check("порожній запит не валить",
              not isinstance(exc, (TypeError, AttributeError, KeyError)),
              f"{type(exc).__name__}: {exc}")

    # 4. Величезний текст не рве клієнт.
    try:
        client3.chat([{"role": "user", "content": "а" * 200_000}])
        check("дуже довгий текст оброблено", True)
    except Exception as exc:  # noqa: BLE001
        check("дуже довгий текст оброблено",
              not isinstance(exc, (TypeError, AttributeError, RecursionError)),
              f"{type(exc).__name__}: {str(exc)[:80]}")

    print(f"\nпровалів: {len(FAILS)}")
    for name in FAILS:
        print("  " + name)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
