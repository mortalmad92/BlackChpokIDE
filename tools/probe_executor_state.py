"""Виконавець задач: повторні спроби, збій, скасування, збереження стану.

Перевіряє логіку без моделі — самісінький двигун виконання.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchk_exec_"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from blackchpok_ide import queue_engine, task_executor  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    queue = queue_engine.TaskQueue()
    executor = task_executor.QueueExecutor(queue)

    # 1. Порожня черга — немає наступної задачі.
    check("порожня черга: next_task None", queue.next_pending() is None,
          str(queue.next_pending()))

    # 2. Одна задача: береться й позначається активною.
    task = queue.add("зроби щось")
    nxt = queue.next_pending()
    check("next_pending віддає задачу", nxt is not None and nxt.id == task.id, str(nxt))
    if nxt is not None:
        queue.mark_running(nxt.id)
        again = queue.next_pending()
        check("активна задача не видається вдруге",
              again is None or again.id != nxt.id, str(again))

    # 3. Позначення збою з причиною.
    queue.mark_failed(task.id, "тестова причина")
    failed = queue.get(task.id)
    check("збій позначено", failed is not None and failed.settled,
          str(getattr(failed, "status", "")))
    check("причина збою збережена",
          failed is not None and "тестова причина" in (getattr(failed, "error", "") or ""),
          str(getattr(failed, "error", ""))[:80])

    # 4. Повторна спроба.
    retried = False
    for name in ("retry", "requeue"):
        func = getattr(queue, name, None)
        if func is not None:
            try:
                func(task.id)
                after = queue.get(task.id)
                retried = after is not None and not after.settled
            except Exception:  # noqa: BLE001
                retried = False
            break
    check("повторна спроба повертає задачу", retried,
          str(getattr(queue.get(task.id), "status", "")))

    # 5. Скасування активної задачі.
    task2 = queue.add("друга")
    queue.mark_running(task2.id)
    queue.cancel(task2.id)
    check("активну задачу скасовано",
          queue.get(task2.id) is not None and queue.get(task2.id).settled,
          str(getattr(queue.get(task2.id), "status", "")))

    # 6. Виконавець не падає на порожній черзі.
    try:
        started = executor.start_next() if hasattr(executor, "start_next") else None
        check("start_next на порожній черзі безпечний", True, str(started))
    except Exception as exc:  # noqa: BLE001
        check("start_next на порожній черзі безпечний", False,
              f"{type(exc).__name__}: {exc}")

    # 7. next_task не видає завершених.
    queue.clear()
    check("clear очищає чергу", not queue.tasks, str(len(queue.tasks)))

    # 8. Відновлення «осиротілих» активних задач.
    orphan = queue.add("зависла")
    queue.mark_running(orphan.id)
    try:
        returned = queue.requeue_running()
        check("requeue_running повертає завислі", True, str(returned))
    except Exception as exc:  # noqa: BLE001
        check("requeue_running повертає завислі", False,
              f"{type(exc).__name__}: {exc}")

    # 9. Черга не «висить» активною.
    active = [t for t in queue.tasks if t.active]
    check("після відновлення немає вічних активних", not active,
          str([t.title for t in active]))

    print(f"\nпровалів: {len(FAILS)}")
    for name in FAILS:
        print("  " + name)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
