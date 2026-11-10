"""Сценарій E: поведінка при збоях з'єднання й після відновлення.

Перевіряє те, що користувач бачив як «модель не працює»:

1. недоступний сервер → зрозуміла помилка, БЕЗ зависання;
2. відповідь на мертвому порту не вважається успіхом;
3. стан сервера після підйому знову показує реальну модель і контекст;
4. ``WinError 10054`` (обрив стріму) перетворюється на зрозумілий текст і
   відкат на звичайний запит, а не на «здався».

Запуск: python tools/check_live_errors.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

LIVE = "http://127.0.0.1:8080/v1"
DEAD = "http://127.0.0.1:9/v1"        # порт, якого точно ніхто не слухає
API_KEY = "local"
MODEL = "qwen25vl3b"

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def dead_server_fails_fast() -> None:
    """Мертвий сервер: швидка помилка, жодного зависання."""
    print("\n=== Недоступний сервер ===")
    from blackchpok_ide.llm_client import LLMClient, LLMError

    client = LLMClient(DEAD, MODEL, API_KEY, timeout=5)
    started = time.perf_counter()
    raised = ""
    answer = ""
    try:
        result = client.chat([{"role": "user", "content": "привіт"}])
        answer = (getattr(result, "content", "") or "").strip()
    except LLMError as exc:
        raised = str(exc)
    except Exception as exc:  # noqa: BLE001
        raised = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started
    check("помилка сталася (немає вигаданої відповіді)",
          bool(raised) and not answer, f"{elapsed:.1f} с · {raised[:70]}")
    check("помилка швидка (без зависання)", elapsed < 30, f"{elapsed:.1f} с")
    check("текст помилки зрозумілий",
          any(word in raised.lower() for word in
              ("недоступ", "з'єднан", "connection", "відмов", "refused",
               "модель")), raised[:90])


def state_reports_dead() -> None:
    """Стан сервера на мертвому порті: чесно «недоступний»."""
    print("\n=== Стан мертвого сервера ===")
    from blackchpok_ide import server_state

    state = server_state.probe_server(DEAD, api_key=API_KEY, timeout=2)
    check("reachable = False", not state.reachable)
    check("online = False", not state.online)
    check("причина вказана", bool(state.error), state.error)
    check("текст для людини пояснює стан",
          "недоступний" in state.note() or "не відповідає" in state.note(),
          state.note())


def live_server_recovers() -> None:
    """Живий сервер: стан, модель, контекст і реальна відповідь."""
    print("\n=== Живий сервер після «збою» ===")
    from blackchpok_ide import server_state
    from blackchpok_ide.llm_client import LLMClient

    state = server_state.probe_server(LIVE, api_key=API_KEY, timeout=5)
    if not state.reachable:
        print(f"[SKIP] {LIVE} не піднятий: {state.error}")
        return
    check("сервер знову доступний", state.reachable)
    check("модель визначена", bool(state.model_loaded), state.model_loaded)
    check("контекст визначений", state.context > 0,
          f"{state.context} ({state.context_source})")

    client = LLMClient(LIVE, MODEL, API_KEY, timeout=120)
    result = client.chat([{"role": "user", "content": "Скажи одне слово."}])
    text = (result.content or "").strip()
    check("модель відповіла після відновлення", bool(text), repr(text[:50]))


def stream_fallback_is_real() -> None:
    """Обрив стріму не завершує хід: є звичайний запит."""
    print("\n=== Відкат стрімінгу ===")
    import inspect

    from blackchpok_ide import llm_client

    source = inspect.getsource(llm_client.LLMClient.chat_stream)
    check("обрив з'єднання розпізнається", "ConnectionResetError" in source)
    check("є пояснення українською", "обірвав" in source)

    from blackchpok_ide import agent

    ask = inspect.getsource(agent.AgentRunner._ask)
    check("після збою стріму йде звичайний запит",
          "client.chat(messages" in ask)
    check("фатальні помилки не повторюються", "fatal" in ask)

    # Жива перевірка: стрім справді працює на цьому сервері.
    client = llm_client.LLMClient(LIVE, MODEL, API_KEY, timeout=120)
    pieces: list[str] = []
    try:
        result = client.chat_stream(
            [{"role": "user", "content": "Порахуй від 1 до 3."}],
            on_text=lambda piece: pieces.append(piece))
    except Exception as exc:  # noqa: BLE001
        check("стрімінг працює на живому сервері", False,
              f"{type(exc).__name__}: {exc}")
        return
    text = (result.content or "").strip()
    check("стрімінг працює на живому сервері", bool(text), repr(text[:60]))
    check("стрімінг віддає частини", bool(pieces), f"{len(pieces)} частин")


def main() -> int:
    from blackchpok_ide import server_state

    state = server_state.probe_server(LIVE, api_key=API_KEY, timeout=3)
    print(f"Живий сервер: {state.note()}")
    dead_server_fails_fast()
    state_reports_dead()
    live_server_recovers()
    if state.reachable:
        stream_fallback_is_real()
    print()
    print("Помилки й відновлення: " + ("УСПІШНО" if not failures
                                       else f"ЗБОЇВ: {failures}"))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
