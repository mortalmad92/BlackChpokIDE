"""Черга задач: додавання, порядок, пауза, скасування, статистика."""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchk_queue_"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from blackchpok_ide import queue_engine  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    queue = queue_engine.TaskQueue()

    check("порожня черга без задач", not queue.tasks, str(queue.tasks))
    check("progress на порожній черзі", isinstance(queue.progress(), dict),
          str(queue.progress()))
    check("немає активної задачі", not queue.running_id, queue.running_id)
    check("черга не на паузі", not queue.paused, str(queue.paused))

    # Додавання зберігає порядок.
    first_task = queue.add("перша задача")
    second_task = queue.add("друга задача")
    third_task = queue.add("третя задача")
    check("три задачі додано", len(queue.tasks) == 3, str(len(queue.tasks)))
    titles = [task.title for task in queue.tasks]
    check("порядок збережено",
          titles == ["перша задача", "друга задача", "третя задача"], str(titles))
    ids = {task.id for task in queue.tasks}
    check("ідентифікатори різні", len(ids) == 3, str(ids))

    # next_pending віддає першу невиконану.
    nxt = queue.next_pending()
    check("next_pending віддає першу",
          nxt is not None and nxt.id == first_task.id, str(nxt))

    # Позначення виконаної.
    queue.mark_done(first_task.id)
    left = [task.goal for task in queue.tasks if not task.settled]
    check("виконана задача позначена", "перша задача" not in left, str(left))

    nxt2 = queue.next_pending()
    check("наступна після виконаної — друга",
          nxt2 is not None and nxt2.id == second_task.id, str(nxt2))

    # Пауза й відновлення.
    queue.set_paused(True)
    check("пауза встановлена", queue.paused is True, str(queue.paused))
    queue.set_paused(False)
    check("пауза знята", queue.paused is False, str(queue.paused))
    queue.toggle_paused()
    check("toggle_paused працює", queue.paused is True, str(queue.paused))
    queue.toggle_paused()

    # Скасування задачі.
    queue.cancel(second_task.id)
    cancelled = queue.get(second_task.id)
    check("скасована задача позначена",
          cancelled is not None and cancelled.settled,
          str(getattr(cancelled, "status", cancelled)))

    # Прогрес.
    progress = queue.progress()
    check("прогрес має лічильники",
          all(key in progress for key in ("total", "done")), str(progress))
    check("прогрес: усього 3", progress.get("total") == 3, str(progress))

    # Статистика.
    counts = queue.counts()
    check("counts працює", isinstance(counts, dict), str(counts))
    check("percent_done рахується",
          0 <= queue.percent_done() <= 100, str(queue.percent_done()))

    # Очищення завершених.
    queue.clear_finished()
    remaining = [task.goal for task in queue.tasks if task.settled]
    check("очищення завершених працює", not remaining, str(remaining))

    # Збереження.
    queue.add("четверта задача")
    try:
        queue.save()
        check("черга зберігається", True)
    except Exception as exc:  # noqa: BLE001
        check("черга зберігається", False, f"{type(exc).__name__}: {exc}")

    # Заміна плану цілком.
    try:
        queue.replace_plan(["крок 1", "крок 2"])
        goals = [task.title for task in queue.tasks]
        check("replace_plan замінює чергу", goals == ["крок 1", "крок 2"], str(goals))
    except Exception as exc:  # noqa: BLE001
        check("replace_plan замінює чергу", False, f"{type(exc).__name__}: {exc}")

    print(f"\nпровалів: {len(FAILS)}")
    for name in FAILS:
        print("  " + name)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
