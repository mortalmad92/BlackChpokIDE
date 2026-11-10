"""Перевірка сховища історії чатів BlackChpok IDE.

Запуск::

    python tests\\test_chat_store.py

Скрипт не потребує tkinter і третіх пакетів: усі тимчасові сховища лежать
у ``<репозиторій>\\.buildtmp\\<унікальна тека>`` і прибираються у ``finally``.
Повертає 0, якщо всі перевірки успішні.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blackchpok_ide.chat_store import (  # noqa: E402
    Chat,
    ChatMessage,
    ChatStore,
)

BUILD_TMP = ROOT / ".buildtmp"

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    """Надрукувати результат однієї перевірки."""
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def utf8_stdout() -> None:
    """Увімкнути UTF-8 у консолі, щоб українські рядки не ламали вивід."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def short(text: object, limit: int = 90) -> str:
    """Скоротити значення для рядка деталей."""
    flat = str(text).replace("\r", "").replace("\n", " ⏎ ")
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def new_path(folder: Path, name: str = "chats.json") -> Path:
    """Шлях до файлу сховища в теці конкретного тесту."""
    folder.mkdir(parents=True, exist_ok=True)
    return folder / name


# ─────────────────────────────────────────────────────────────────────────────
# 1. створення, пошук, активна розмова
# ─────────────────────────────────────────────────────────────────────────────

def test_create_get_active(folder: Path) -> None:
    """create/get/active/set_active працюють узгоджено."""
    store = ChatStore(new_path(folder))
    check("порожнє сховище: 0 чатів, active_id ''", store.chats == [] and store.active_id == "",
          f"chats={len(store.chats)}, active={store.active_id!r}")

    first = store.create(title="Перша", workspace=r"C:\proj", model="local")
    check("create() додає чат і робить його активним",
          len(store.chats) == 1 and store.active_id == first.id and store.active() is first,
          f"active_id={first.id}")
    check("create() заповнює поля", first.title == "Перша" and first.workspace == r"C:\proj"
          and first.model == "local", f"{first.title!r} / {first.workspace!r} / {first.model!r}")
    check("id має 12 hex-символів", len(first.id) == 12 and all(c in "0123456789abcdef" for c in first.id),
          first.id)
    check("get() знаходить створений чат", store.get(first.id) is first)
    check("get() на невідомому id → None", store.get("deadbeefcafe") is None and store.get("") is None)

    second = store.create(title="Друга")
    check("другий create() стає першим у списку",
          store.chats[0] is second and store.chats[1] is first, f"порядок={[c.title for c in store.chats]}")
    check("новий чат — активний", store.active() is second)

    check("set_active() на наявний чат → True", store.set_active(first.id) and store.active() is first)
    check("set_active() на невідомий id → False і вибір не змінюється",
          store.set_active("000000000000") is False and store.active() is first)
    check("set_active('') очищає вибір", store.set_active("") and store.active_id == ""
          and store.active() is None)


# ─────────────────────────────────────────────────────────────────────────────
# 2. автоматична назва
# ─────────────────────────────────────────────────────────────────────────────

def test_auto_title(folder: Path) -> None:
    """Назва генерується лише з першого повідомлення користувача."""
    store = ChatStore(new_path(folder))
    chat = store.create()
    store.append("user", "  **Привіт** `світ` — як справи?")
    check("перше повідомлення користувача задає назву",
          chat.title == "Привіт світ — як справи?", short(chat.title))

    store.append("user", "друге повідомлення не має перейменувати")
    check("наступні повідомлення не перейменовують", chat.title == "Привіт світ — як справи?",
          short(chat.title))

    explicit = store.create(title="Моя тема")
    store.append("user", "зовсім інший текст запиту")
    check("явна назва не перезаписується", explicit.title == "Моя тема", short(explicit.title))

    quiet = store.create()
    store.append("assistant", "відповідь без запиту")
    check("відповідь агента не задає назву", quiet.title == "", short(quiet.title))


# ─────────────────────────────────────────────────────────────────────────────
# 3. append: updated_at, message_count, preview
# ─────────────────────────────────────────────────────────────────────────────

def test_append_effects(folder: Path) -> None:
    """append() оновлює час, лічильник і прев'ю."""
    store = ChatStore(new_path(folder))
    chat = store.create(title="Тема")
    old = chat.updated_at = time.time() - 60.0

    message = store.append("user", "Запитай мене")
    check("append() повертає ChatMessage",
          isinstance(message, ChatMessage) and message.role == "user" and message.text == "Запитай мене")
    check("append() оновлює updated_at", chat.updated_at > old,
          f"{old:.2f} → {chat.updated_at:.2f}")
    check("message_count = 1 після одного append", chat.message_count == 1, str(chat.message_count))

    store.append("assistant", "Готово!\n\nОсь   результат.")
    check("preview() — останнє повідомлення в один рядок",
          chat.preview() == "Готово! Ось результат.", short(chat.preview()))
    check("message_count = 2", chat.message_count == 2, str(chat.message_count))
    check("preview(limit) скорочує", len(chat.preview(10)) <= 11, short(chat.preview(10)))

    check("append(meta=...) заповнює meta", store.append(
        "tool", "read_file", meta={"tool": "read_file"}).meta == {"tool": "read_file"})

    empty = ChatStore(new_path(folder, "empty.json"))
    check("append() без жодного чату → None", empty.append("user", "привіт") is None)

    other = store.create(title="Інша")
    store.append("user", "у неї", chat_id=other.id)
    check("append(chat_id=...) пише у вказаний чат",
          other.message_count == 1 and chat.message_count == 3,
          f"{other.message_count}/{chat.message_count}")

    added = store.append_many(chat.id, [("user", "раз"), ("assistant", "два"), "сміття"])
    check("append_many() додає пари й пропускає сміття",
          added == 2 and chat.message_count == 5, f"додано={added}, всього={chat.message_count}")
    check("append_many() приймає генератор",
          store.append_many(chat.id, (item for item in [("user", "генератор")])) == 1,
          str(chat.message_count))

    check("clear_messages() очищає історію, лишаючи назву",
          store.clear_messages(chat.id) and chat.message_count == 0 and chat.title == "Тема")
    check("clear_messages() на невідомому id → False", store.clear_messages("nope") is False)


# ─────────────────────────────────────────────────────────────────────────────
# 4. видалення
# ─────────────────────────────────────────────────────────────────────────────

def test_delete(folder: Path) -> None:
    """Видалення прибирає чат і переносить active_id."""
    store = ChatStore(new_path(folder))
    a = store.create(title="A")
    b = store.create(title="B")
    store.set_active(a.id)

    check("delete() видаляє чат", store.delete(a.id) and store.get(a.id) is None
          and len(store.chats) == 1, str(len(store.chats)))
    check("активність перейшла до наступного видимого", store.active_id == b.id, store.active_id)
    check("delete() на невідомому id → False", store.delete(a.id) is False)

    check("видалення останнього чату лишає active_id ''",
          store.delete(b.id) and store.chats == [] and store.active_id == "",
          f"active={store.active_id!r}")

    store.create(title="C")
    archived = store.create(title="D")
    store.archive(archived.id, True)
    store.set_active(store.chats[-1].id)
    store.delete(store.chats[-1].id)
    check("активність не переходить в архівний чат",
          store.active_id == "", f"active={store.active_id!r}, архівний={archived.id}")


# ─────────────────────────────────────────────────────────────────────────────
# 5. архів
# ─────────────────────────────────────────────────────────────────────────────

def test_archive(folder: Path) -> None:
    """Архів ховає чат зі списку, але не видаляє його."""
    store = ChatStore(new_path(folder))
    chat = store.create(title="Стара")
    store.append("user", "текст")

    check("archive() → True", store.archive(chat.id) is True)
    check("архівний чат зникає з visible()",
          store.visible() == [] and store.get(chat.id) is chat,
          f"visible={len(store.visible())}")
    check("архівний чат є у visible(archived=True)", store.visible(archived=True) == [chat])
    check("дані архівного чату не втрачені", chat.message_count == 1 and chat.title == "Стара")

    store.archive(chat.id, False)
    check("unarchive повертає чат у visible()", store.visible() == [chat])
    check("archive() на невідомому id → False", store.archive("nope") is False)
    check("counts()['архів'] рахує архівні", store.archive(chat.id) and store.counts()["архів"] == 1,
          str(store.counts()))


# ─────────────────────────────────────────────────────────────────────────────
# 6. закріплення
# ─────────────────────────────────────────────────────────────────────────────

def test_pin(folder: Path) -> None:
    """Закріплені чати стоять перед новішими незакріпленими."""
    store = ChatStore(new_path(folder))
    old = store.create(title="Старий")
    old.updated_at = 1_000.0
    newer = store.create(title="Новий")
    newer.updated_at = 9_000.0

    check("без закріплення перший — новіший",
          [chat.title for chat in store.visible()] == ["Новий", "Старий"],
          str([chat.title for chat in store.visible()]))

    check("pin() → True", store.pin(old.id) is True)
    check("закріплений старий стоїть першим",
          [chat.title for chat in store.visible()] == ["Старий", "Новий"],
          str([chat.title for chat in store.visible()]))
    check("counts()['закріплено'] враховує закріплені", store.counts()["закріплено"] == 1,
          str(store.counts()))

    store.pin(old.id, False)
    check("pin(False) знімає закріплення",
          [chat.title for chat in store.visible()] == ["Новий", "Старий"])
    check("pin() на невідомому id → False", store.pin("nope") is False)


# ─────────────────────────────────────────────────────────────────────────────
# 7. пошук
# ─────────────────────────────────────────────────────────────────────────────

def test_search(folder: Path) -> None:
    """Пошук іде за назвою й текстами, без урахування регістру."""
    store = ChatStore(new_path(folder))
    by_title = store.create(title="Рефакторинг парсера")
    by_text = store.create(title="Без назви")
    store.append("assistant", "Треба оновити ПАРСЕР у модулі", chat_id=by_text.id)
    store.append("user", "зовсім інше", chat_id=by_title.id)
    store.create(title="Третій чат")

    found = store.search("парсер")
    ids = {chat.id for chat in found}
    check("search() знаходить за назвою", by_title.id in ids, str(len(found)))
    check("search() знаходить за текстом повідомлення", by_text.id in ids, str(len(found)))
    check("search() не чіпляє зайвих", len(found) == 2, short([c.title for c in found]))
    check("search() регістронезалежний (верхній регістр)",
          {chat.id for chat in store.search("ПАРСЕР")} == ids)
    check("порожній запит → []", store.search("   ") == [])
    check("нічого не знайдено → []", store.search("абракадабра") == [])


# ─────────────────────────────────────────────────────────────────────────────
# 8. збереження на диск
# ─────────────────────────────────────────────────────────────────────────────

def test_persistence(folder: Path) -> None:
    """Новий ChatStore на тому самому шляху бачить усе збережене."""
    path = new_path(folder)
    store = ChatStore(path)
    kept = store.create(title="Основна", workspace=r"C:\work", model="qwen")
    store.append("user", "початок розмови")
    store.append("assistant", "відповідь агента", meta={"ms": 5})
    hidden = store.create(title="Архівна")
    store.append("user", "прихована")
    store.archive(hidden.id, True)
    store.pin(kept.id, True)
    store.set_active(kept.id)
    store.save()
    store.save()                       # другий виклик поспіль не має ламати файл

    check("файл сховища створено", path.exists(), str(path))
    check("тимчасовий .tmp не лишився", not path.with_suffix(".tmp").exists(),
          str(path.with_suffix(".tmp")))
    raw = json.loads(path.read_text(encoding="utf-8"))
    check("JSON має поля active і chats",
          isinstance(raw, dict) and raw.get("active") == kept.id and isinstance(raw.get("chats"), list),
          short(list(raw) if isinstance(raw, dict) else raw))

    reopened = ChatStore(path)
    check("після перезапуску чати на місці", len(reopened.chats) == 2,
          f"чатів={len(reopened.chats)}")
    check("active_id пережив перезапуск", reopened.active_id == kept.id, reopened.active_id)
    again = reopened.get(kept.id)
    check("чат знайдено за id після перезапуску", again is not None)
    if again is not None:
        check("назва, тека й модель збереглися",
              again.title == "Основна" and again.workspace == r"C:\work" and again.model == "qwen",
              f"{again.title!r} / {again.workspace!r} / {again.model!r}")
        check("повідомлення й meta збереглися",
              again.message_count == 2 and again.messages[1].text == "відповідь агента"
              and again.messages[1].meta == {"ms": 5},
              str(again.message_count))
        check("архівне й закріплене збереглися",
              reopened.get(hidden.id) is not None and bool(reopened.get(hidden.id).archived)
              and again.pinned, f"archived={bool(reopened.get(hidden.id).archived)}, pinned={again.pinned}")
        check("порядок вставлення збережено (новіші спереду)",
              reopened.chats[0].title == "Архівна", reopened.chats[0].title)


# ─────────────────────────────────────────────────────────────────────────────
# 9. пошкоджений файл
# ─────────────────────────────────────────────────────────────────────────────

def test_corrupt_file(folder: Path) -> None:
    """Сміття у файлі не валить конструктор."""
    broken = new_path(folder, "broken.json")
    broken.write_text('{"chats": [{"id": "aaa"', encoding="utf-8")     # обірваний JSON
    try:
        store = ChatStore(broken)
        check("пошкоджений JSON → порожнє сховище", store.chats == [] and store.active_id == "",
              f"chats={len(store.chats)}")
    except Exception as exc:  # noqa: BLE001
        check("пошкоджений JSON → порожнє сховище", False, f"кинув: {exc!r}")

    weird = new_path(folder, "weird.json")
    weird.write_text('["не словник", 42, null, {"title": 5, "messages": "не список"}]',
                     encoding="utf-8")
    try:
        store = ChatStore(weird)
        check("список зі сміттям → лише валідні чати",
              len(store.chats) == 1 and store.chats[0].messages == [],
              f"chats={len(store.chats)}")
    except Exception as exc:  # noqa: BLE001
        check("список зі сміттям → лише валідні чати", False, f"кинув: {exc!r}")

    missing = new_path(folder, "does-not-exist.json")
    try:
        store = ChatStore(missing)
        check("відсутній файл → порожнє сховище", store.chats == [] and store.active_id == "")
    except Exception as exc:  # noqa: BLE001
        check("відсутній файл → порожнє сховище", False, f"кинув: {exc!r}")

    store.create(title="Після збою")
    check("сховище далі працює після пошкодженого файлу",
          missing.exists() and len(store.chats) == 1)


# ─────────────────────────────────────────────────────────────────────────────
# 10. терпимі from_dict
# ─────────────────────────────────────────────────────────────────────────────

def test_tolerant_from_dict() -> None:
    """from_dict не кидає на None, кривих типах і зайвих ключах."""
    junk_chats = [None, "рядок", 42, [], {}, {"messages": None}, {"id": None, "title": 5},
                  {"id": "x" * 500, "created_at": "не число", "archived": "true",
                   "messages": [{"role": 5, "text": None}, "сміття", 7,
                                {"meta": "не словник", "extra": 1}]}]
    problems: list[str] = []
    for item in junk_chats:
        try:
            chat = Chat.from_dict(item)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{short(item, 30)} → {exc!r}")
            continue
        if not isinstance(chat.id, str) or not chat.id or not isinstance(chat.title, str):
            problems.append(f"{short(item, 30)} → поганий id/title")
        if not isinstance(chat.messages, list) or not isinstance(chat.archived, bool):
            problems.append(f"{short(item, 30)} → поганий messages/archived")
    check("Chat.from_dict() не кидає на смітті", not problems, "; ".join(problems[:3]))

    blank = Chat.from_dict(None)
    check("Chat.from_dict(None) → свіжий чат із id на 12 символів",
          len(blank.id) == 12 and blank.title == "" and blank.messages == [] and not blank.archived,
          f"id={blank.id!r}")
    mixed = Chat.from_dict({"id": "x" * 500, "created_at": "не число", "archived": "true",
                            "messages": [{"role": 5, "text": None}, "сміття", 7,
                                         {"meta": "не словник", "extra": 1}]})
    check("кривий id замінено нормальним", len(mixed.id) == 12, mixed.id)
    check("нечисловий час замінено числом",
          isinstance(mixed.created_at, float) and isinstance(mixed.updated_at, float),
          f"{mixed.created_at!r}/{mixed.updated_at!r}")
    check("рядок 'true' читається як True", mixed.archived is True)
    check("не-словники серед messages пропущено", mixed.message_count == 2,
          str(mixed.message_count))
    check("не-словник у meta відкинуто", mixed.messages[1].meta == {}, str(mixed.messages[1].meta))

    junk_messages = [None, "рядок", 3, [], {}, {"role": None, "text": 12},
                     {"timestamp": "не число", "meta": [1, 2]}]
    problems = []
    for item in junk_messages:
        try:
            message = ChatMessage.from_dict(item)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{item!r} → {exc!r}")
            continue
        if not isinstance(message.role, str) or not isinstance(message.text, str):
            problems.append(f"{item!r} → поганий role/text")
        if not isinstance(message.timestamp, float) or not isinstance(message.meta, dict):
            problems.append(f"{item!r} → поганий timestamp/meta")
    check("ChatMessage.from_dict() не кидає на смітті", not problems, "; ".join(problems[:3]))
    empty = ChatMessage.from_dict(None)
    check("ChatMessage.from_dict(None) → role 'user', text ''",
          empty.role == "user" and empty.text == "" and empty.meta == {},
          f"{empty.role!r}/{empty.text!r}")
    numeric = ChatMessage.from_dict({"role": None, "text": 12})
    check("число в text стає рядком", numeric.text == "12" and numeric.role == "user",
          f"{numeric.role!r}/{numeric.text!r}")

    extra = Chat.from_dict({"id": "abcdef123456", "title": "Т", "зайвий": 1, "messages": []})
    check("зайві ключі ігноруються", extra.id == "abcdef123456" and extra.title == "Т")


# ─────────────────────────────────────────────────────────────────────────────
# 11-12. auto_title і age_text
# ─────────────────────────────────────────────────────────────────────────────

def test_auto_title_rules() -> None:
    """auto_title прибирає markdown і ріже по межі слова."""
    chat = Chat(title="x")
    text = "## Заголовок **тема** `код` " + "слово " * 20
    title = chat.auto_title(text, 40)
    check("auto_title() обрізає довгий текст", title.endswith("…") and len(title) <= 41,
          short(title, 60))
    check("auto_title() не лишає markdown",
          not any(mark in title for mark in ("*", "`", "#", "~~")), short(title, 60))
    plain = chat.auto_title(text, 200)
    head = title[:-1]
    check("auto_title() обрізає по межі слова (без обрубка)",
          title.endswith("…") and f"{head} " in f"{plain} ",
          f"обрізано={head!r}")

    check("auto_title() розкриває markdown у чистому вигляді",
          plain.startswith("Заголовок тема код слово"), short(plain, 60))
    check("auto_title(limit) коротший за повний текст", len(title) < len(plain))

    check("auto_title() на порожньому тексті → ''", chat.auto_title("") == "")
    spaced = "Привіт,\n\n   світе   мій"
    check("auto_title() стискає пробіли", chat.auto_title(spaced) == "Привіт, світе мій",
          short(chat.auto_title(spaced)))

    filled = Chat()
    filled.add("assistant", "перша відповідь")
    filled.add("user", "власне запит користувача")
    check("auto_title() без аргументу бере перший user-текст",
          filled.auto_title() == "власне запит користувача", short(filled.auto_title()))


def test_age_text() -> None:
    """age_text дає український відносний час."""
    now = time.time()
    cases = [
        (Chat(updated_at=now), "щойно"),
        (Chat(updated_at=now - 5 * 60), "5 хв тому"),
        (Chat(updated_at=now - 3 * 3600), "3 год тому"),
        (Chat(updated_at=now - 2 * 86_400 - 60), "2 дн тому"),
    ]
    for chat, expected in cases:
        check(f"age_text() для {expected}", chat.age_text == expected, chat.age_text)
    old = Chat(updated_at=now - 40 * 86_400)
    check("age_text() для давніх показує дату", len(old.age_text) == 5 and "." in old.age_text,
          old.age_text)
    check("age_text() без часу → ''", Chat(updated_at=0.0).age_text == "")


# ─────────────────────────────────────────────────────────────────────────────
# 13. експорт
# ─────────────────────────────────────────────────────────────────────────────

def test_export_markdown(folder: Path) -> None:
    """export_markdown дає читабельний конспект із ролями й текстами."""
    store = ChatStore(new_path(folder))
    chat = store.create(title="Експорт")
    store.append("user", "Питання користувача")
    store.append("assistant", "Відповідь агента")
    markdown = store.export_markdown(chat.id)
    check("export_markdown() містить назву", "# Експорт" in markdown)
    check("export_markdown() містить текст користувача", "Питання користувача" in markdown)
    check("export_markdown() містить текст агента", "Відповідь агента" in markdown)
    check("export_markdown() підписує ролі", "**ВИ**" in markdown and "**АГЕНТ**" in markdown,
          short(markdown, 120))
    check("export_markdown() має мітки часу", markdown.count(" · ") >= 2,
          f"міток={markdown.count(' · ')}")
    check("export_markdown() на невідомому id → ''", store.export_markdown("nope") == "")


# ─────────────────────────────────────────────────────────────────────────────
# 14. прибирання
# ─────────────────────────────────────────────────────────────────────────────

def test_prune(folder: Path) -> None:
    """prune() лишає N незакріплених чатів і ніколи не чіпає активний."""
    store = ChatStore(new_path(folder))
    chats = []
    for index in range(6):
        chat = store.create(title=f"Чат {index}")
        chat.updated_at = 1_000.0 + index          # детермінований порядок
        chats.append(chat)
    keep = chats[1]
    store.pin(keep.id, True)                       # закріплений — недоторканний
    active = store.create(title="Активний")
    active.updated_at = 500.0                      # найстаріший, але активний
    store.set_active(active.id)

    removed = store.prune(keep=2)
    titles = [chat.title for chat in store.chats]
    non_pinned = [chat for chat in store.chats if not chat.pinned and chat.id != store.active_id]
    check("prune() повертає кількість видалених", removed == 3, f"видалено={removed}")
    check("prune() лишає не більше keep незакріплених", len(non_pinned) <= 2,
          f"незакріплених={len(non_pinned)}: {[c.title for c in non_pinned]}")
    check("prune() не видаляє закріплений", store.get(keep.id) is not None)
    check("prune() не видаляє активний", store.get(active.id) is not None
          and store.active_id == active.id)
    check("prune() прибирає найстаріші",
          store.get(chats[0].id) is None and store.get(chats[5].id) is not None,
          str(titles))
    check("prune(keep=999) нічого не робить", store.prune(keep=999) == 0)
    check("prune() зберігся на диск",
          len(ChatStore(new_path(folder)).chats) == len(store.chats),
          f"на диску={len(ChatStore(new_path(folder)).chats)}")


# ─────────────────────────────────────────────────────────────────────────────
# 15. копія, ensure_active, counts
# ─────────────────────────────────────────────────────────────────────────────

def test_duplicate(folder: Path) -> None:
    """duplicate() дає новий id і ті самі повідомлення."""
    store = ChatStore(new_path(folder))
    source = store.create(title="Оригінал", workspace=r"C:\w", model="m")
    store.append("user", "перше")
    store.append("assistant", "друге")
    copy = store.duplicate(source.id)
    check("duplicate() повертає чат", copy is not None)
    if copy is None:
        return
    check("duplicate() має інший id", copy.id != source.id and bool(copy.id), copy.id)
    check("duplicate() копіює повідомлення",
          [m.text for m in copy.messages] == ["перше", "друге"]
          and copy.message_count == source.message_count,
          str(copy.message_count))
    check("duplicate() копіює теку й модель", copy.workspace == r"C:\w" and copy.model == "m")
    check("duplicate() додає копію у список", store.get(copy.id) is copy and len(store.chats) == 2)
    check("duplicate() не змінює активний чат", store.active_id == source.id, store.active_id)
    check("duplicate() на невідомому id → None", store.duplicate("nope") is None)

    store.append("user", "третє", chat_id=source.id)
    check("копія не залежить від оригіналу", copy.message_count == 2 and source.message_count == 3,
          f"{copy.message_count}/{source.message_count}")


def test_ensure_active_and_counts(folder: Path) -> None:
    """ensure_active() завжди повертає розмову; counts() рахує стан."""
    store = ChatStore(new_path(folder))
    created = store.ensure_active(workspace=r"C:\p", model="x")
    check("ensure_active() на порожньому сховищі створює чат",
          created is not None and len(store.chats) == 1 and created.workspace == r"C:\p",
          f"чатів={len(store.chats)}")
    store.set_active("")
    reused = store.ensure_active()
    check("ensure_active() підхоплює наявний видимий чат",
          reused.id == created.id and len(store.chats) == 1, reused.id)

    hidden = store.create(title="Прихований")
    store.archive(hidden.id, True)
    store.archive(created.id, True)
    store.set_active("")
    fresh = store.ensure_active(workspace=r"C:\q")
    check("ensure_active() ігнорує архівні й створює новий",
          fresh.id not in {created.id, hidden.id} and len(store.chats) == 3,
          f"чатів={len(store.chats)}")

    stats = store.counts()
    check("counts() має ключі усього/архів/закріплено",
          set(stats) == {"усього", "архів", "закріплено"}, str(sorted(stats)))
    check("counts() рахує правильно",
          stats["усього"] == 3 and stats["архів"] == 2 and stats["закріплено"] == 0, str(stats))


# ─────────────────────────────────────────────────────────────────────────────
# запуск
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    """Прогнати всі перевірки та повернути код виходу процесу."""
    utf8_stdout()
    BUILD_TMP.mkdir(parents=True, exist_ok=True)
    root = BUILD_TMP / f"chat-store-{uuid.uuid4().hex[:10]}"
    root.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        test_create_get_active(root / "create")
        test_auto_title(root / "auto-title")
        test_append_effects(root / "append")
        test_delete(root / "delete")
        test_archive(root / "archive")
        test_pin(root / "pin")
        test_search(root / "search")
        test_persistence(root / "persistence")
        test_corrupt_file(root / "corrupt")
        test_tolerant_from_dict()
        test_auto_title_rules()
        test_age_text()
        test_export_markdown(root / "export")
        test_prune(root / "prune")
        test_duplicate(root / "duplicate")
        test_ensure_active_and_counts(root / "ensure-active")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    check("тимчасову теку прибрано", not root.exists(), str(root))
    elapsed = time.monotonic() - started
    print(f"\nЧас виконання: {elapsed:.2f} с")
    if failures:
        print(f"Провалено перевірок: {failures}")
        return 1
    print("Усі перевірки пройдено.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ── unittest-обгортка (додано 10.11.2026) ──────────────────────────────────
# Для `python -m unittest discover` ці перевірки раніше були невидимі:
# файл — скрипт із власним main(), а не TestCase. Тепер discover запускає
# його й падає, якщо main() повернув ненульовий код. Запуск як скрипт
# (`python tests/test_chat_store.py`) поводиться як раніше.
import unittest as _unittest  # noqa: E402


class _ScriptSuite(_unittest.TestCase):
    def test_script_passes(self) -> None:
        code = main()
        self.assertEqual(code, 0, f"main() повернув {code}")
