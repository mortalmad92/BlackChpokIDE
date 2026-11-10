"""Прибрати з chats.json послідовні дублі, що накопичились через баг.

Кожне відкриття чату раніше дописувало останні повідомлення назад, тож у
файлі лишились ланцюжки однакових записів. Скрипт:
  * робить резервну копію поруч із файлом;
  * прибирає лише ПІДРЯД повторів (роль + текст + 2 с допуску за часом);
  * нічого не вигадує й не переставляє.

Запуск: python tools/dedupe_chats.py [шлях-до-chats.json] [--apply]
Без --apply лише показує, що буде зроблено.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Два записи вважаємо тим самим «відлунням», якщо між ними не більше
#: стількох секунд і збігаються роль із текстом.
DUPLICATE_WINDOW = 2.0


def strip_consecutive_duplicates(messages: list) -> tuple[list, int]:
    """Прибрати послідовні повтори повідомлень."""
    kept: list = []
    removed = 0
    for item in messages:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        if kept:
            previous = kept[-1]
            same_text = (
                isinstance(previous, dict)
                and previous.get("role") == item.get("role")
                and (previous.get("text") or "") == (item.get("text") or "")
            )
            if same_text:
                try:
                    gap = abs(float(item.get("timestamp") or 0)
                              - float(previous.get("timestamp") or 0))
                except (TypeError, ValueError):
                    gap = 0.0
                if gap <= DUPLICATE_WINDOW:
                    removed += 1
                    continue
        kept.append(item)
    return kept, removed


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply = "--apply" in sys.argv
    path = Path(args[0]) if args else ROOT / "userdata" / "chats.json"
    if not path.exists():
        print(f"Файл не знайдено: {path}")
        return 1

    raw = json.loads(path.read_text(encoding="utf-8"))
    chats = raw.get("chats") if isinstance(raw, dict) else raw
    if not isinstance(chats, list):
        print("Неочікуваний формат файлу — нічого не роблю.")
        return 1

    total_before = total_after = 0
    for chat in chats:
        if not isinstance(chat, dict):
            continue
        messages = chat.get("messages")
        if not isinstance(messages, list):
            continue
        kept, removed = strip_consecutive_duplicates(messages)
        title = (chat.get("title") or "Без назви")[:52]
        total_before += len(messages)
        total_after += len(kept)
        if removed:
            print(f"- {title}: {len(messages)} → {len(kept)} (прибрано {removed})")
        chat["messages"] = kept

    print(f"\nУсього повідомлень: {total_before} → {total_after} "
          f"(прибрано {total_before - total_after})")
    if not apply:
        print("Це попередній перегляд. Додай --apply, щоб записати.")
        return 0
    if total_before == total_after:
        print("Змін немає — файл не перезаписую.")
        return 0

    backup = path.with_name(f"{path.name}.backup-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(path, backup)
    print(f"Резервна копія: {backup}")

    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    tmp.replace(path)
    print(f"Записано: {path}")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    raise SystemExit(main())
