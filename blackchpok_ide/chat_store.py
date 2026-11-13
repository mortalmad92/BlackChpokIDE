"""Історія чатів BlackChpok IDE: розмови, повідомлення й файлове сховище.

Модуль описує три речі:

* :class:`ChatMessage` — одне повідомлення (роль, текст, час, метадані);
* :class:`Chat` — розмова з назвою, робочою текою, архівом і закріпленням;
* :class:`ChatStore` — сховище розмов у ``app_data_dir()/chats.json``.

Стиль той самий, що й у решти IDE: лише стандартна бібліотека, жодного
імпорту tkinter, без побічних ефектів під час імпорту. Запис у файл
атомарний: спершу ``chats.tmp``, далі :func:`os.replace`, тому швидкі
подвійні виклики :meth:`ChatStore.save` не залишають обрізаного JSON.

Сховище розраховане на потік інтерфейсу. Якщо один і той самий шлях
відкривають два екземпляри :class:`ChatStore`, вони перезапишуть файл
один одного — тримайте один екземпляр на шлях.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .config import app_data_dir


def same_folder(left: str, right: str) -> bool:
    """Чи два записи вказують на одну й ту саму теку.

    Порівняння йде через ``resolve``: ``C:/a`` і ``C:\\a\\`` — одна папка.
    Якщо шлях не вдається розкрити, лишається порівняння тексту.
    """
    a = str(left or "").strip()
    b = str(right or "").strip()
    if not a or not b:
        return False
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return a.casefold() == b.casefold()

LOG = logging.getLogger("blackchpok.chats")

#: Дозволені ролі повідомлень.
ROLES = ("user", "assistant", "tool", "system")

#: Підписи ролей для експорту в markdown.
ROLE_TITLES = {
    "user": "ВИ",
    "assistant": "АГЕНТ",
    "tool": "ІНСТРУМЕНТ",
    "system": "СИСТЕМА",
}

#: Скільки чатів зберігати за замовчуванням під час прибирання.
DEFAULT_KEEP = 200

# ── Статуси сесій агентів (для списку в Cursor-стилі) ──────────────────────
STATUS_IDLE = "idle"          # сесія відкрита, агент не задіяний
STATUS_WORKING = "working"    # агент зараз працює над запитом
STATUS_DONE = "done"          # агент завершив (успіх або зупинка)
STATUS_QUEUED = "queued"      # задачі чекають у черзі

STATUS_VALUES = (STATUS_IDLE, STATUS_WORKING, STATUS_DONE, STATUS_QUEUED)


def normalise_status(value: Any) -> str:
    """Привести статус до одного з відомих значень (сміття → idle)."""
    clean = str(value or "").strip().lower()
    return clean if clean in STATUS_VALUES else STATUS_IDLE


# ─────────────────────────────────────────────────────────────────────────────
# Дрібні помічники (усі — «ніколи не кидають»)
# ─────────────────────────────────────────────────────────────────────────────

def _as_text(value: Any, default: str = "") -> str:
    """Перетворити значення на рядок, не кидаючи винятків."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return str(value)
    return default


def _as_float(value: Any, default: float) -> float:
    """Перетворити значення на додатне скінченне число."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number) or number <= 0:
        return default
    return number


def _as_bool(value: Any, default: bool = False) -> bool:
    """Перетворити значення на bool (розуміє 1/0, "true"/"false", "так"/"ні")."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        flat = value.strip().lower()
        if flat in {"1", "true", "yes", "on", "так"}:
            return True
        if flat in {"0", "false", "no", "off", "", "ні"}:
            return False
    return default


def _collapse(text: Any) -> str:
    """Згорнути всі пробіли (зокрема переноси рядків) в один."""
    return " ".join(_as_text(text).split())


#: Ролі, з якими повідомлення контексту агента справді валідні для сервера.
_CONTEXT_ROLES = ("system", "user", "assistant", "tool")

#: Скільки повідомлень контексту зберігати для одного чату.
CONTEXT_KEEP = 120


def _clean_context(raw: Any) -> list[dict[str, Any]]:
    """Привести контекст агента до безпечного списку повідомлень.

    Контекст — це той самий формат, що йде моделі (``role``/``content``, а
    для tool-викликів іще ``tool_calls``/``tool_call_id``). З диска може
    прийти будь-що, тож фільтруємо: лишаємо лише словники з відомою роллю
    й текстовим ``content``, обрізаємо надто довгий список. Ніколи не кидає.
    """
    if not isinstance(raw, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = _as_text(item.get("role")).strip().lower()
        if role not in _CONTEXT_ROLES:
            continue
        content = item.get("content")
        entry: dict[str, Any] = {
            "role": role,
            "content": content if isinstance(content, str) else _as_text(content),
        }
        # Виклики інструментів мусять пережити перезапуск: без них
        # наступний запит містить tool-результат без виклику й сервер
        # відповідає помилкою 400.
        calls = item.get("tool_calls")
        if isinstance(calls, list) and calls:
            kept_calls = [call for call in calls if isinstance(call, dict)]
            if kept_calls:
                entry["tool_calls"] = kept_calls
        for key in ("tool_call_id", "name"):
            value = item.get(key)
            if isinstance(value, str) and value:
                entry[key] = value
        cleaned.append(entry)
    return cleaned[-CONTEXT_KEEP:]


_HEAD_MARKS = re.compile(r"^[#>\s]+")
_LIST_MARK = re.compile(r"^([-+*•]|\d+[.)])\s+")
_EMPHASIS = re.compile(r"\*\*|__|~~|\*|`")


def plain_text(text: Any) -> str:
    """Прибрати markdown-маркери й зайві пробіли — для назв і прев'ю."""
    flat = _collapse(text)
    if not flat:
        return ""
    flat = _HEAD_MARKS.sub("", flat)      # "## Заголовок" → "Заголовок"
    flat = _LIST_MARK.sub("", flat)       # "- пункт", "1. крок" → "пункт", "крок"
    flat = _EMPHASIS.sub("", flat)        # **жирний**, `код`, ~~закреслений~~
    return _collapse(flat)


def shorten(text: str, limit: int) -> str:
    """Обрізати текст по межі слова, додавши «…» (жорстко, якщо слово довге)."""
    limit = max(8, int(limit))
    text = _as_text(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rstrip()
    head = cut.rsplit(" ", 1)[0].rstrip(" ,.;:—–-")
    if len(head) >= max(8, limit // 3):
        cut = head
    return cut + "…"


def _format_time(value: float) -> str:
    """Час у форматі ``05.11.2026 23:14`` (порожній рядок, якщо число дивне)."""
    try:
        return time.strftime("%d.%m.%Y %H:%M", time.localtime(float(value)))
    except (OSError, ValueError, OverflowError):
        return ""


def chats_path() -> Path:
    """Шлях до файлу історії чатів за замовчуванням."""
    return app_data_dir() / "chats.json"


# ─────────────────────────────────────────────────────────────────────────────
# Повідомлення
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ChatMessage:
    """Одне повідомлення розмови.

    ``role`` — одна з :data:`ROLES`; ``meta`` — довільні дані (назва моделі,
    тривалість, шлях файлу тощо). ``meta`` має бути словником, інакше
    :meth:`from_dict` його відкидає.
    """

    role: str
    text: str = ""
    timestamp: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Представлення для JSON."""
        meta = self.meta if isinstance(self.meta, dict) else {}
        return {
            "role": self.role,
            "text": self.text,
            "timestamp": self.timestamp,
            "meta": dict(meta),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "ChatMessage":
        """Створити повідомлення зі словника, не кидаючи на смітті.

        Відсутні ключі, зайві ключі, ``None`` замість словника чи числа
        замість тексту не спричиняють винятку — беруться безпечні значення
        за замовчуванням.
        """
        if not isinstance(data, dict):
            return cls(role="user")
        role = _as_text(data.get("role")).strip() or "user"
        text = _as_text(data.get("text"))
        timestamp = _as_float(data.get("timestamp"), time.time())
        raw_meta = data.get("meta")
        meta: dict[str, Any] = {}
        if isinstance(raw_meta, dict):
            meta = {str(key): value for key, value in raw_meta.items()}
        return cls(role=role, text=text, timestamp=timestamp, meta=meta)


# ─────────────────────────────────────────────────────────────────────────────
# Розмова
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Chat:
    """Одна розмова з агентом."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    workspace: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    messages: list[ChatMessage] = field(default_factory=list)
    archived: bool = False
    pinned: bool = False
    model: str = ""
    effort: str = ""
    #: Стан сесії агента для списку: "idle" | "working" | "done" | "queued".
    status: str = STATUS_IDLE
    #: Контекст агента ЦЬОГО чату (повідомлення у форматі OpenAI).
    #:
    #: Навіщо окреме поле: раніше ``AgentRunner`` мав одну сесію на всю
    #: програму. Після перемикання чату вона очищалась — і продовжити
    #: розмову було неможливо (агент не бачив жодного попереднього кроку),
    #: а якщо не очищалась, то контекст СУСІДНЬОГО чату просочувався в
    #: новий. Тепер контекст належить запису чату й відновлюється разом із
    #: ним — так само, як повідомлення.
    context: list[dict[str, Any]] = field(default_factory=list)
    #: Стан розуміння завдання в цьому чаті (мета, обмеження, згадки).
    #:
    #: Окремо від ``context``: ``context`` — це те, що бачить МОДЕЛЬ, а тут —
    #: те, що знає IDE: «над чим ми працюємо», «що не можна ламати»,
    #: «на що посилалось „воно“». Без цього після перезапуску агент знову
    #: питав би те, що людина вже пояснила.
    state: dict[str, Any] = field(default_factory=dict)
    #: Git-публікація, прив'язана до ЦЬОГО чату й ЦЬОГО проєкту.
    #:
    #: Навіщо в чаті, а не в налаштуваннях. Користувач працює в кількох
    #: проєктах одночасно, і «на GitHub» у кожного своя адреса. Спільне
    #: поле в налаштуваннях означало б, що чат проєкту А відправив зміни
    #: в репозиторій проєкту Б.
    #:
    #: ``git_remote`` — адреса, яку агент показав у питанні (для журналу);
    #: ``git_last_push`` — час останньої успішної відправки (epoch);
    #: ``git_auto_ask`` — чи питати «оновити файли на GitHub?» після роботи.
    git_remote: str = ""
    git_last_push: float = 0.0
    git_auto_ask: bool = True

    # ── серіалізація ───────────────────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        """Представлення для JSON (усі поля, включно з повідомленнями)."""
        return {
            "id": self.id,
            "title": self.title,
            "workspace": self.workspace,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "archived": self.archived,
            "pinned": self.pinned,
            "model": self.model,
            "effort": self.effort,
            "status": self.status,
            "context": _clean_context(self.context),
            "state": dict(self.state) if isinstance(self.state, dict) else {},
            "git_remote": _as_text(self.git_remote),
            "git_last_push": _as_float(self.git_last_push, 0.0),
            "git_auto_ask": bool(self.git_auto_ask),
            "messages": [message.to_dict() for message in self.messages],
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Chat":
        """Створити розмову зі словника, терпимо до сміття.

        Не кидає навіть на ``None``, рядку, списку, кривих типах чи зайвих
        ключах: відсутні поля отримують безпечні значення, пошкоджені
        повідомлення (не-словники) просто пропускаються.
        """
        now = time.time()
        if not isinstance(data, dict):
            return cls(created_at=now, updated_at=now)
        chat_id = _as_text(data.get("id")).strip()
        if not re.fullmatch(r"[0-9A-Za-z_-]{1,64}", chat_id):
            chat_id = uuid.uuid4().hex[:12]
        created_at = _as_float(data.get("created_at"), now)
        updated_at = _as_float(data.get("updated_at"), created_at)
        messages: list[ChatMessage] = []
        raw_messages = data.get("messages")
        if isinstance(raw_messages, list):
            for item in raw_messages:
                if not isinstance(item, dict):
                    continue          # не-словник — тихо пропускаємо
                try:
                    messages.append(ChatMessage.from_dict(item))
                except Exception:     # noqa: BLE001 - дані з диска не мають валити старт
                    LOG.debug("Пропущено пошкоджене повідомлення", exc_info=True)
        return cls(
            id=chat_id,
            title=_as_text(data.get("title")),
            workspace=_as_text(data.get("workspace")),
            created_at=created_at,
            updated_at=updated_at,
            messages=messages,
            archived=_as_bool(data.get("archived")),
            pinned=_as_bool(data.get("pinned")),
            model=_as_text(data.get("model")),
            effort=_as_text(data.get("effort")),
            status=normalise_status(data.get("status")),
            context=_clean_context(data.get("context")),
            state=data.get("state") if isinstance(data.get("state"), dict) else {},
            git_remote=_as_text(data.get("git_remote")),
            git_last_push=_as_float(data.get("git_last_push"), 0.0),
            git_auto_ask=_as_bool(data.get("git_auto_ask", True), True),
        )

    # ── вміст ──────────────────────────────────────────────────────────────
    def add(self, role_or_message: ChatMessage | str, text: str = "") -> ChatMessage:
        """Додати повідомлення й оновити ``updated_at``.

        Приймає або готовий :class:`ChatMessage`, або роль і текст::

            chat.add("user", "привіт")
            chat.add(ChatMessage(role="assistant", text="вітаю"))

        Повертає додане повідомлення.
        """
        if isinstance(role_or_message, ChatMessage):
            message = role_or_message
        else:
            role = _as_text(role_or_message).strip() or "user"
            message = ChatMessage(role=role, text=_as_text(text))
        if not isinstance(message.text, str):
            message.text = _as_text(message.text)
        self.messages.append(message)
        self.updated_at = time.time()
        return message

    def auto_title(self, text: str = "", limit: int = 48) -> str:
        """Назва розмови з першого повідомлення користувача.

        Markdown-маркери й обрамлення на кшталт ``**…**`` та ``` `…` ```
        прибираються, пробіли згортаються, довгий текст обрізається по межі
        слова з «…». Якщо ``text`` порожній, береться перше повідомлення
        користувача з розмови.
        """
        source = _as_text(text)
        if not source.strip():
            source = next(
                (message.text for message in self.messages
                 if message.role == "user" and message.text.strip()),
                "",
            )
        plain = plain_text(source)
        return shorten(plain, limit) if plain else ""

    def preview(self, limit: int = 90) -> str:
        """Останнє повідомлення, згорнуте в один рядок (для списку чатів).

        Використовує :func:`plain_text`, а не ``_collapse``: інакше в
        списку видно сиру розмітку («**Крок 1.** …»), а не текст.
        """
        if not self.messages:
            return ""
        return shorten(plain_text(self.messages[-1].text), limit)

    # ── властивості ────────────────────────────────────────────────────────
    @property
    def message_count(self) -> int:
        """Скільки повідомлень у розмові."""
        return len(self.messages)

    @property
    def age_text(self) -> str:
        """Відносний час останньої активності українською."""
        if not self.updated_at:
            return ""
        stamp = _as_float(self.updated_at, 0.0)
        if not stamp:
            return ""
        delta = time.time() - stamp
        if delta < 0:
            delta = 0.0
        if delta < 60:
            return "щойно"
        if delta < 3600:
            return f"{int(delta // 60)} хв тому"
        if delta < 86_400:
            return f"{int(delta // 3600)} год тому"
        if delta < 6 * 86_400:
            return f"{int(delta // 86_400)} дн тому"
        return time.strftime("%d.%m", time.localtime(stamp))


# ─────────────────────────────────────────────────────────────────────────────
# Сховище
# ─────────────────────────────────────────────────────────────────────────────

class ChatStore:
    """Файлове сховище розмов.

    Список :attr:`chats` зберігає порядок вставлення (нові — на початку),
    а сортування «закріплені → найновіші» роблять :meth:`visible`
    і :meth:`search`. Так індекси в списку не стрибають, поки інтерфейс
    малює рядки, а порядок на екрані задає сама панель.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path: Path = Path(path) if path else chats_path()
        self.chats: list[Chat] = []
        self.active_id: str = ""
        self._load()

    # ── файл ───────────────────────────────────────────────────────────────
    def _load(self) -> None:
        """Прочитати файл; будь-яка проблема означає «почати з порожнього»."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:      # ValueError ловить і JSONDecodeError
            if self.path.exists():
                LOG.warning("Не вдалось прочитати чати %s: %s", self.path, exc)
            return
        if isinstance(data, list):        # найпростіший формат — лише список
            raw_chats: Any = data
            raw_active: Any = ""
        elif isinstance(data, dict):
            raw_chats = data.get("chats")
            raw_active = data.get("active")
        else:
            return
        restored: list[Chat] = []
        seen: set[str] = set()
        for item in raw_chats if isinstance(raw_chats, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                chat = Chat.from_dict(item)
            except Exception:             # noqa: BLE001 - дискові дані не мають валити старт
                LOG.debug("Пропущено пошкоджений чат", exc_info=True)
                continue
            if chat.id in seen:
                chat.id = uuid.uuid4().hex[:12]
            seen.add(chat.id)
            restored.append(chat)
        self.chats = restored
        active = _as_text(raw_active)
        self.active_id = active if any(chat.id == active for chat in restored) else ""

    def save(self) -> None:
        """Записати стан атомарно (``.tmp`` + :func:`os.replace`)."""
        payload = {
            "version": 1,
            "active": self.active_id,
            "chats": [chat.to_dict() for chat in self.chats],
        }
        try:
            tmp = self.path.with_suffix(".tmp")
        except ValueError:
            tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            os.replace(tmp, self.path)
        except OSError as exc:
            LOG.warning("Не вдалось зберегти чати: %s", exc)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    # ── доступ ─────────────────────────────────────────────────────────────
    def get(self, chat_id: str) -> Chat | None:
        """Знайти розмову за ідентифікатором."""
        if not chat_id:
            return None
        for chat in self.chats:
            if chat.id == chat_id:
                return chat
        return None

    def active(self) -> Chat | None:
        """Поточна відкрита розмова (або ``None``)."""
        return self.get(self.active_id)

    def set_active(self, chat_id: str) -> bool:
        """Зробити розмову активною; ``""`` очищає вибір."""
        if not chat_id:
            self.active_id = ""
            self.save()
            return True
        if self.get(chat_id) is None:
            return False
        self.active_id = chat_id
        self.save()
        return True

    @staticmethod
    def _sort_key(chat: Chat) -> tuple[int, float]:
        """Ключ сортування: закріплені першими, далі — свіжіші вище."""
        return (0 if chat.pinned else 1, -_as_float(chat.updated_at, 0.0))

    def visible(self, *, archived: bool = False) -> list[Chat]:
        """Розмови для списку: закріплені першими, далі за ``updated_at``."""
        chats = [chat for chat in self.chats if bool(chat.archived) == bool(archived)]
        chats.sort(key=self._sort_key)
        return chats

    def search(self, query: str) -> list[Chat]:
        """Пошук без урахування регістру за назвою й текстами повідомлень.

        Архівні розмови теж потрапляють у результати (інтерфейс може
        позначити їх окремо); порожній запит дає порожній список.
        """
        needle = _as_text(query).strip().casefold()
        if not needle:
            return []
        found: list[Chat] = []
        for chat in self.chats:
            if needle in _as_text(chat.title).casefold():
                found.append(chat)
                continue
            for message in chat.messages:
                if needle in _as_text(message.text).casefold():
                    found.append(chat)
                    break
        found.sort(key=self._sort_key)
        return found

    # ── зміни ──────────────────────────────────────────────────────────────
    def create(self, title: str = "", workspace: str = "", model: str = "") -> Chat:
        """Створити розмову, поставити її першою й зробити активною."""
        now = time.time()
        chat = Chat(
            title=_as_text(title).strip(),
            workspace=_as_text(workspace),
            model=_as_text(model),
            created_at=now,
            updated_at=now,
        )
        self.chats.insert(0, chat)
        self.active_id = chat.id
        self.save()
        return chat

    def bind_workspace(self, chat_id: str, folder: str) -> str:
        """Прив'язати чат до однієї теки.

        Порожня тека чату заповнюється. Якщо тека вже записана, друга
        інша адреса не замінює її: чат не переїжджає в чужий проєкт.
        Повертає ``set``, ``same``, ``refused`` або ``missing``.
        """
        chat = self.get(chat_id)
        clean = str(folder or "").strip()
        if chat is None or not clean:
            return "missing"
        if str(chat.workspace or "").strip():
            return "same" if same_folder(chat.workspace, clean) else "refused"
        try:
            chat.workspace = str(Path(clean).resolve())
        except OSError:
            chat.workspace = clean
        self.save()
        return "set"

    def chat_for_workspace(self, folder: str) -> Chat | None:
        """Найсвіжіший чат, уже прив'язаний до цієї теки."""
        clean = str(folder or "").strip()
        if not clean:
            return None
        found = [chat for chat in self.chats
                 if same_folder(chat.workspace, clean)]
        if not found:
            return None
        found.sort(key=lambda chat: chat.updated_at, reverse=True)
        return found[0]

    # ── git-публікація (прив'язка до чату й проєкту) ────────────────────────
    def git_remote(self, chat_id: str) -> str:
        """Адреса GitHub, запам'ятована для цього чату (``""`` — невідома)."""
        chat = self.get(chat_id)
        return _as_text(getattr(chat, "git_remote", "")) if chat else ""

    def remember_git(self, chat_id: str, *, remote: str = "",
                     pushed_at: float | None = None) -> bool:
        """Запам'ятати адресу й/або час останньої відправки для чату.

        ``pushed_at=None`` — лише адреса (напр. після перевірки стану);
        ``pushed_at`` числом — позначає успішну відправку.
        """
        chat = self.get(chat_id)
        if chat is None:
            return False
        changed = False
        clean = _as_text(remote).strip()
        if clean and chat.git_remote != clean:
            chat.git_remote = clean
            changed = True
        if pushed_at is not None and float(pushed_at) != float(chat.git_last_push):
            chat.git_last_push = float(pushed_at)
            changed = True
        if changed:
            self.save()
        return changed

    def set_git_auto_ask(self, chat_id: str, value: bool) -> bool:
        """Увімкнути/вимкнути питання «оновити файли на GitHub?»."""
        chat = self.get(chat_id)
        if chat is None:
            return False
        wanted = bool(value)
        if chat.git_auto_ask != wanted:
            chat.git_auto_ask = wanted
            self.save()
        return chat.git_auto_ask

    def delete(self, chat_id: str) -> bool:
        """Остаточно видалити розмову.

        Якщо видалено активну, ``active_id`` переходить до першої видимої
        розмови, а якщо чатів не лишилось — стає ``""``.
        """
        for index, chat in enumerate(self.chats):
            if chat.id != chat_id:
                continue
            del self.chats[index]
            if self.active_id == chat_id:
                remaining = self.visible()
                self.active_id = remaining[0].id if remaining else ""
            self.save()
            return True
        return False

    def delete_all(self, *, archived: bool = False) -> int:
        """Видалити ВСІ розмови (або лише архівні) і повернути кількість.

        ``archived=False`` — прибирає все, включно з архівом: це та дія, яку
        робить кнопка «Видалити всі чати». ``archived=True`` — чистить лише
        архів, не чіпаючи активні розмови.
        """
        before = len(self.chats)
        if archived:
            self.chats = [chat for chat in self.chats if not chat.archived]
        else:
            self.chats = []
        removed = before - len(self.chats)
        # Активна розмова могла зникнути — переходимо до першої видимої.
        if self.active_id and self.get(self.active_id) is None:
            remaining = self.visible()
            self.active_id = remaining[0].id if remaining else ""
        if removed:
            self.save()
        return removed

    def archive(self, chat_id: str, archived: bool = True) -> bool:
        """Прибрати розмову в архів (або повернути звідти)."""
        chat = self.get(chat_id)
        if chat is None:
            return False
        value = bool(archived)
        if chat.archived != value:
            chat.archived = value
            self.save()
        return True

    def rename(self, chat_id: str, title: str) -> bool:
        """Перейменувати розмову (порожня назва теж дозволена — тоді її
        знову згенерує :meth:`append`)."""
        chat = self.get(chat_id)
        if chat is None:
            return False
        chat.title = _as_text(title).strip()
        self.save()
        return True

    def pin(self, chat_id: str, pinned: bool = True) -> bool:
        """Закріпити розмову — закріплені стоять першими у списку."""
        chat = self.get(chat_id)
        if chat is None:
            return False
        value = bool(pinned)
        if chat.pinned != value:
            chat.pinned = value
            self.save()
        return True

    def set_status(self, chat_id: str, status: str) -> bool:
        """Змінити стан сесії агента (working/done/queued/idle).

        Статус потрібен списку агентів зліва: працює / завершено / у черзі.
        Невідомі значення тихо стають ``idle`` — сховище не падає.
        """
        chat = self.get(chat_id)
        if chat is None:
            return False
        clean = normalise_status(status)
        if chat.status != clean:
            chat.status = clean
            self.save()
        return True

    def duplicate(self, chat_id: str) -> Chat | None:
        """Копія розмови з новим ``id`` і тими самими повідомленнями.

        Копія не закріплена й не архівна, тож одразу видима у списку;
        активною залишається поточна розмова.
        """
        source = self.get(chat_id)
        if source is None:
            return None
        now = time.time()
        title = f"{source.title} (копія)" if source.title.strip() else "Копія розмови"
        copy = Chat(
            title=title,
            workspace=source.workspace,
            model=source.model,
        effort=source.effort,
            created_at=now,
            updated_at=now,
            messages=[ChatMessage.from_dict(message.to_dict()) for message in source.messages],
            archived=False,
            pinned=False,
        )
        self.chats.insert(0, copy)
        self.save()
        return copy

    # ── повідомлення ───────────────────────────────────────────────────────
    def append(
        self,
        role: str,
        text: str,
        *,
        chat_id: str = "",
        meta: dict | None = None,
    ) -> ChatMessage | None:
        """Додати повідомлення у вказану (або активну) розмову.

        Якщо в розмові ще немає назви, а повідомлення — від користувача,
        назва генерується з тексту (:meth:`Chat.auto_title`). Повертає
        повідомлення або ``None``, коли відкритої розмови немає.
        """
        chat = self.get(chat_id) if chat_id else self.active()
        if chat is None:
            return None
        message = chat.add(_as_text(role).strip() or "user", _as_text(text))
        if isinstance(meta, dict) and meta:
            message.meta.update({str(key): value for key, value in meta.items()})
        if message.role == "user" and not chat.title.strip():
            derived = chat.auto_title(message.text)
            if derived:
                chat.title = derived
        self.save()
        return message

    def append_many(self, chat_id: str, items: Iterable[tuple[str, str]]) -> int:
        """Додати кілька пар ``(роль, текст)`` одним записом на диск.

        Записи, що не є парою, тихо пропускаються. Повертає кількість
        доданих повідомлень.
        """
        chat = self.get(chat_id) if chat_id else self.active()
        if chat is None:
            return 0
        added = 0
        for item in items or ():
            if isinstance(item, str) or not isinstance(item, (tuple, list)):
                continue                      # рядок — не пара «роль, текст»
            if len(item) != 2:
                continue
            role, text = item
            message = chat.add(_as_text(role).strip() or "user", _as_text(text))
            if message.role == "user" and not chat.title.strip():
                derived = chat.auto_title(message.text)
                if derived:
                    chat.title = derived
            added += 1
        if added:
            self.save()
        return added

    def clear_messages(self, chat_id: str) -> bool:
        """Очистити історію розмови, лишивши назву й теку."""
        chat = self.get(chat_id)
        if chat is None:
            return False
        chat.messages.clear()
        chat.context.clear()
        chat.updated_at = time.time()
        self.save()
        return True

    # ── контекст агента (належить чату) ────────────────────────────────────
    def store_context(self, chat_id: str, messages: Iterable[Any]) -> bool:
        """Зберегти контекст агента для чату.

        Викликається після кожного ходу агента: саме тут контекст
        «прикріплюється» до розмови, а не до програми. Завдяки цьому після
        перезапуску й після перемикання чатів модель бачить СВОЮ історію.

        Приймає будь-що: не-список (число, словник, ``None``) вважається
        «порожнім контекстом», а не помилкою — збереження не має падати на
        дивних даних.
        """
        chat = self.get(chat_id)
        if chat is None:
            return False
        if isinstance(messages, (str, bytes, int, float, bool)) or messages is None:
            raw: Any = []
        elif isinstance(messages, dict):
            raw = [messages]
        else:
            try:
                raw = list(messages)
            except TypeError:
                raw = []
        chat.context = _clean_context(raw)
        try:
            self.save()
        except Exception:  # noqa: BLE001 - збереження не має ламати хід агента
            LOG.debug("Не вдалось зберегти контекст чату %s", chat_id, exc_info=True)
            return False
        return True

    def load_context(self, chat_id: str) -> list[dict[str, Any]]:
        """Прочитати контекст агента цього чату (копія, не сам список)."""
        chat = self.get(chat_id)
        if chat is None:
            return []
        return [dict(item) for item in chat.context]

    def store_state(self, chat_id: str, state: dict[str, Any]) -> bool:
        """Зберегти стан розуміння завдання (мета, обмеження, згадки).

        Окремо від :meth:`store_context`: контекст — для моделі, стан — для
        IDE. Після перезапуску агент має продовжити те саме завдання з тими
        самими обмеженнями, а не починати розмову «з чистого аркуша».
        """
        chat = self.get(chat_id)
        if chat is None:
            return False
        chat.state = dict(state) if isinstance(state, dict) else {}
        try:
            self.save()
        except Exception:  # noqa: BLE001
            LOG.debug("Не вдалось зберегти стан чату %s", chat_id, exc_info=True)
            return False
        return True

    def load_state(self, chat_id: str) -> dict[str, Any]:
        """Прочитати стан розуміння завдання цього чату."""
        chat = self.get(chat_id)
        if chat is None:
            return {}
        return dict(chat.state) if isinstance(chat.state, dict) else {}

    # ── запуск ─────────────────────────────────────────────────────────────
    def ensure_active(self, *, workspace: str = "", model: str = "") -> Chat:
        """Гарантувати відкриту розмову (виклик на старті IDE).

        Порядок: активна розмова → найновіша видима → нова.
        """
        current = self.active()
        if current is not None:
            return current
        visible = self.visible()
        if visible:
            self.active_id = visible[0].id
            self.save()
            return visible[0]
        return self.create(workspace=workspace, model=model)

    # ── експорт і статистика ───────────────────────────────────────────────
    def export_markdown(self, chat_id: str) -> str:
        """Розмова у вигляді читабельного markdown-конспекту."""
        chat = self.get(chat_id)
        if chat is None:
            return ""
        lines = [f"# {chat.title.strip() or 'Без назви'}", ""]
        if chat.workspace:
            lines.append(f"- **Тека:** `{chat.workspace}`")
        if chat.model:
            lines.append(f"- **Модель:** {chat.model}")
        lines.append(f"- **Створено:** {_format_time(chat.created_at)}")
        lines.append(f"- **Повідомлень:** {chat.message_count}")
        lines.append("")
        for message in chat.messages:
            label = ROLE_TITLES.get(message.role, (message.role or "повідомлення").upper())
            lines.append(f"**{label}** · {_format_time(message.timestamp)}")
            lines.append("")
            lines.append(_as_text(message.text).strip() or "_(порожнє повідомлення)_")
            lines.append("")
            lines.append("---")
            lines.append("")
        if not chat.messages:
            lines.append("_Розмова порожня._")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def counts(self) -> dict[str, int]:
        """Лічильники для підпису панелі: усього, архів, закріплено."""
        return {
            "усього": len(self.chats),
            "архів": sum(1 for chat in self.chats if chat.archived),
            "закріплено": sum(1 for chat in self.chats if chat.pinned),
        }

    def prune(self, keep: int = DEFAULT_KEEP) -> int:
        """Прибрати найстаріші незакріплені розмови понад ``keep``.

        Активна й закріплені розмови не видаляються ніколи. Повертає
        кількість видалених.
        """
        try:
            keep = max(0, int(keep))
        except (TypeError, ValueError):
            keep = DEFAULT_KEEP
        candidates = [
            chat for chat in self.chats
            if not chat.pinned and chat.id != self.active_id
        ]
        candidates.sort(key=lambda chat: _as_float(chat.updated_at, 0.0), reverse=True)
        doomed = {chat.id for chat in candidates[keep:]}
        if not doomed:
            return 0
        self.chats = [chat for chat in self.chats if chat.id not in doomed]
        self.save()
        return len(doomed)


__all__ = [
    "Chat",
    "ChatMessage",
    "ChatStore",
    "DEFAULT_KEEP",
    "ROLE_TITLES",
    "ROLES",
    "STATUS_DONE",
    "STATUS_IDLE",
    "STATUS_QUEUED",
    "STATUS_VALUES",
    "STATUS_WORKING",
    "normalise_status",
]
