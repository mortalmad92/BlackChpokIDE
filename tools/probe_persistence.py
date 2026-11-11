"""Переживання перезапуску: чат, налаштування, черга, правки.

Кожен блок пише стан, «перезапускає» застосунок (новий об'єкт у тому
самому BLACKCHPOK_HOME) і перевіряє, що стан справді повернувся.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

HOME = tempfile.mkdtemp(prefix="bchk_persist_")
os.environ["BLACKCHPOK_HOME"] = HOME
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from blackchpok_ide import chat_store  # noqa: E402
from blackchpok_ide.config import Settings  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    print(f"BLACKCHPOK_HOME: {HOME}\n")

    # ── Налаштування
    settings = Settings()
    settings.llm.model = "тестова-модель"
    settings.ui.font_size = 17
    settings.agent.confirm_commands = True
    settings.remember_workspace(HOME)
    settings.save()
    again = Settings.load()
    check("модель пережила перезапуск", again.llm.model == "тестова-модель",
          again.llm.model)
    check("розмір шрифту пережив", again.ui.font_size == 17, str(again.ui.font_size))
    check("підтвердження команд пережило",
          again.agent.confirm_commands is True, str(again.agent.confirm_commands))
    check("робоча тека пережила", again.workspace == str(pathlib.Path(HOME)),
          again.workspace)

    # ── Чат
    store = chat_store.ChatStore()
    chat = store.create("Розмова про тести")
    chat_id = chat.id
    store.append("user", "Привіт, це перевірка", chat_id=chat_id)
    store.append("assistant", "Відповідь збережена", chat_id=chat_id)
    store.save()

    store2 = chat_store.ChatStore()
    sessions = store2.visible()
    found = [s for s in sessions if getattr(s, "id", None) == chat_id]
    check("чат знайдено після перезапуску", bool(found), f"ід {chat_id}")
    if found:
        messages = found[0].messages
        texts = [getattr(m, "text", "") for m in messages]
        check("повідомлення пережили перезапуск",
              any("Привіт" in t for t in texts), str(texts)[:120])
        check("відповідь пережила перезапуск",
              any("Відповідь" in t for t in texts), str(texts)[:120])

    # ── Видалення чату не повертається
    store2.delete(chat_id)
    store2.save()
    store3 = chat_store.ChatStore()
    left = [s for s in store3.visible() if getattr(s, "id", None) == chat_id]
    check("видалений чат не повертається", not left, str(len(left)))

    print(f"\nпровалів: {len(FAILS)}")
    for name in FAILS:
        print("  " + name)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
