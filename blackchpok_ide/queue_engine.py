"""Черга завдань агента: послідовне виконання запитів без ручного запуску.

Ідея: користувач складає список задач («прогнати тести», «оновити README»),
а IDE виконує їх одну за одною тим самим агентом. Черга переживає перезапуск
(зберігається у ``app_data_dir()/queue.json``), уміє паузу, скасування,
перезапуск задачі й автоматичне продовження після завершення попередньої.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .config import app_data_dir

LOG = logging.getLogger("blackchpok.queue")

PENDING = "очікує"
ANALYZING = "аналіз"
RUNNING = "виконується"
VERIFYING = "перевірка"
DONE = "готово"
FAILED = "помилка"
PAUSED = "призупинено"
CANCELLED = "скасовано"

STATUS_MARKS = {
    PENDING: "○",
    ANALYZING: "◔",
    RUNNING: "◐",
    VERIFYING: "◑",
    DONE: "✓",
    FAILED: "✗",
    PAUSED: "❚❚",
    CANCELLED: "—",
}

#: Статуси, у яких задача тримає агента (виконання вже почалося).
ACTIVE_STATUSES = (ANALYZING, RUNNING, VERIFYING)

#: Статуси, які означають, що задачу вже не треба виконувати.
SETTLED_STATUSES = (DONE, FAILED, PAUSED, CANCELLED)

#: Порядок статусів у зведенні (для стабільного виводу лічильників).
STATUS_ORDER = (PENDING, ANALYZING, RUNNING, VERIFYING, DONE, FAILED,
                PAUSED, CANCELLED)

#: Людські підписи статусів (для панелі керування чергою).
STATUS_LABELS = {
    PENDING: "Очікує",
    ANALYZING: "Аналіз",
    RUNNING: "Виконується",
    VERIFYING: "Перевірка",
    DONE: "Завершено",
    FAILED: "Помилка",
    PAUSED: "Призупинено",
    CANCELLED: "Скасовано",
}

#: Скільки спроб виконання дозволено задачі, поки її не позначено як невдалу.
#: Захист від нескінченних циклів «повторити → знову помилка → повторити».
MAX_ATTEMPTS = 3

# ── Походження задачі ──────────────────────────────────────────────────────
#: Задачу придумав сам агент (автономний режим).
ORIGIN_AGENT = "агент"
#: Задачу додав користувач — вона має вищий пріоритет.
ORIGIN_USER = "користувач"

ORIGINS = (ORIGIN_AGENT, ORIGIN_USER)

#: Підписи для панелей («від агента» / «від користувача»).
ORIGIN_LABELS = {
    ORIGIN_AGENT: "від агента",
    ORIGIN_USER: "від користувача",
}


def normalise_origin(value: Any) -> str:
    """Привести походження задачі до відомого значення.

    Невідоме (або порожнє) вважаємо авторством агента: так задачі, збережені
    до появи поля, не отримують хибного «від користувача» й не лізуть наперед.
    """
    clean = str(value or "").strip().lower()
    if clean in ("user", "користувач", "людина"):
        return ORIGIN_USER
    return ORIGIN_AGENT


def queue_path() -> Path:
    return app_data_dir() / "queue.json"


@dataclass
class QueueTask:
    """Одне завдання черги."""

    text: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = PENDING
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    finished_at: float = 0.0
    result: str = ""
    error: str = ""
    skill: str = ""            # назва скіла, якщо задачу додано зі скіла
    use_skills: bool = True    # додавати зміст активних скілів у запит
    #: Хто придумав задачу: :data:`ORIGIN_AGENT` або :data:`ORIGIN_USER`.
    origin: str = ORIGIN_AGENT
    #: Файл, який задача має змінити (для «дописати до кінця» при зупинці).
    file_hint: str = ""
    #: Чат, до якого належить задача. Порожній — «спільна» задача без чату
    #: (напр. поставлена зі скіла до створення розмови). За цим полем
    #: задачі прибираються разом із чатом.
    chat_id: str = ""
    # ── дані плану, який склала локальна модель ────────────────────────────
    #: Порядковий номер у плані (1..N). 0 — задача поза планом.
    #:
    #: Номер зберігаємо окремо від позиції в списку: користувач може
    #: переставляти задачі, а «01», «02» у панелі мають лишатися тими
    #: номерами, які дав сам план.
    number: int = 0
    #: Стислий опис того, що саме робитиметься (1–2 речення від моделі).
    detail: str = ""
    #: Загальна мета, з якої народився цей крок (для контексту агенту).
    goal: str = ""
    #: Ідентифікатори задач, які мають завершитись раніше (залежності).
    depends_on: list[str] = field(default_factory=list)
    #: Інструменти, які модель назвала доречними для цього кроку.
    tools: list[str] = field(default_factory=list)
    #: Файли, які задача створила або змінила (заповнює виконавець).
    files_changed: list[str] = field(default_factory=list)
    #: Скільки разів задача вже запускалась (захист від вічних повторів).
    attempts: int = 0
    #: Журнал фактичних кроків виконання: (час, вид, текст).
    #:
    #: Заповнюється з реальних подій агента (виклик інструмента, його
    #: результат, помилка), а не з припущень — саме це показує картка
    #: «Що зробила модель».
    history: list[dict[str, Any]] = field(default_factory=list)
    #: Поточна операція (короткий підпис для активної задачі).
    current_step: str = ""

    @property
    def elapsed(self) -> float:
        if not self.started_at:
            return 0.0
        end = self.finished_at or time.time()
        return max(0.0, end - self.started_at)

    @property
    def from_user(self) -> bool:
        """True, якщо задачу поставив користувач (вищий пріоритет)."""
        return self.origin == ORIGIN_USER

    @property
    def origin_label(self) -> str:
        return ORIGIN_LABELS.get(self.origin, ORIGIN_LABELS[ORIGIN_AGENT])

    @property
    def elapsed_text(self) -> str:
        seconds = int(self.elapsed)
        if seconds <= 0:
            return ""
        if seconds < 60:
            return f"{seconds} с"
        return f"{seconds // 60} хв {seconds % 60} с"

    @property
    def title(self) -> str:
        """Коротка назва кроку для списку (перший рядок тексту)."""
        first = (self.text or "").strip().splitlines()
        head = first[0].strip() if first else ""
        return head

    @property
    def mark(self) -> str:
        return STATUS_MARKS.get(self.status, "•")

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def active(self) -> bool:
        """Задача зараз у роботі (модель щось з нею робить)."""
        return self.status in ACTIVE_STATUSES

    @property
    def settled(self) -> bool:
        """Задачу вже закрито (успішно, з помилкою, паузою чи скасуванням)."""
        return self.status in SETTLED_STATUSES

    def add_history(self, kind: str, text: str) -> None:
        """Дописати рядок у журнал виконання (з реальної події)."""
        clean = " ".join(str(text or "").split())
        if not clean:
            return
        self.history.append({"at": time.time(), "kind": kind, "text": clean[:600]})
        # Журнал не має рости безмежно: довгі задачі з десятками викликів
        # інструментів зберігали тисячі рядків у queue.json.
        del self.history[: max(0, len(self.history) - 120)]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QueueTask":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {key: value for key, value in (data or {}).items() if key in known}
        if not str(clean.get("text") or "").strip():
            raise ValueError("порожнє завдання")
        # Дані зі старого queue.json можуть мати інші типи для нових полів.
        for name in ("depends_on", "tools", "files_changed"):
            value = clean.get(name)
            if not isinstance(value, list):
                clean[name] = []
        if not isinstance(clean.get("history"), list):
            clean["history"] = []
        try:
            clean["number"] = int(clean.get("number") or 0)
        except (TypeError, ValueError):
            clean["number"] = 0
        task = cls(**clean)
        if task.status in ACTIVE_STATUSES:   # після падіння/перезапуску задача не «висить»
            task.status = PENDING
            task.current_step = ""
        task.origin = normalise_origin(getattr(task, "origin", ""))
        return task


class TaskQueue:
    """Черга задач із ручним керуванням і хуком автозапуску."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else queue_path()
        self.tasks: list[QueueTask] = []
        self.running_id: str = ""
        self.paused: bool = False
        self.on_change: Optional[Callable[[], None]] = None
        self._load()

    # ── збереження ─────────────────────────────────────────────────────────
    def _load(self) -> None:
        """Завантажити чергу. Будь-яке пошкодження файлу — не привід падати.

        Навіщо така суворість. ``TaskQueue()`` створюється в конструкторі
        головного вікна (``main_window.py:290``) БЕЗ захисту. Якщо файл
        містить не те, що очікується (список чисел, рядок, ``{"tasks": [1]}``),
        ``QueueTask.from_dict`` кидав ``AttributeError: 'int' object has no
        attribute 'items'`` — виняток летів нагору й **IDE не відкривалась
        узагалі**. Користувач бачив лише зникнення вікна, без підказки, і міг
        полагодити хіба що видаленням файлу навмання.

        Перевірено: 7 з 10 пошкоджених варіантів ламали створення черги.
        Тепер кожен елемент перевіряється на тип, а будь-який виняток під час
        відновлення одного завдання відкидає ЛИШЕ його.
        """
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return
        # ``{"tasks": [...]}`` — типовий формат; інакше файл міг бути записаний
        # просто списком. Усе, що не словник і не список, ігноруємо.
        if isinstance(data, dict):
            raw = data.get("tasks")
            if not isinstance(raw, list):
                raw = []
        elif isinstance(data, list):
            raw = data
        else:
            LOG.warning("queue.json має неочікуваний тип (%s) — черга порожня",
                        type(data).__name__)
            return
        restored: list[QueueTask] = []
        for item in raw:
            if not isinstance(item, dict):
                # Не словник — не завдання. Раніше тут летів AttributeError.
                LOG.warning("Пропущено запис черги неочікуваного типу: %s",
                            type(item).__name__)
                continue
            try:
                restored.append(QueueTask.from_dict(item))
            except (TypeError, ValueError, AttributeError, KeyError):
                continue
        self.tasks = restored
        if isinstance(data, dict):
            self.paused = bool(data.get("paused"))

    def save(self) -> None:
        payload = {
            "tasks": [task.to_dict() for task in self.tasks],
            "paused": self.paused,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            LOG.warning("Не вдалось зберегти чергу: %s", exc)

    def _changed(self) -> None:
        self.save()
        if self.on_change:
            try:
                self.on_change()
            except Exception:  # noqa: BLE001 - інтерфейс не має ламати чергу
                LOG.debug("on_change впав", exc_info=True)

    # ── додавання ──────────────────────────────────────────────────────────
    def add(self, text: str, *, skill: str = "", use_skills: bool = True,
            origin: str = ORIGIN_AGENT, file_hint: str = "",
            front: bool = False, chat_id: str = "",
            number: int = 0, detail: str = "", goal: str = "",
            depends_on: Iterable[str] = (), tools: Iterable[str] = ()) -> Optional[QueueTask]:
        """Додати задачу в чергу.

        ``origin`` визначає автора: задачі користувача мають вищий
        пріоритет, тому за замовчуванням ``front=True`` для них не
        потрібен — їх обирає :meth:`next_pending`, навіть якщо попереду
        стоять задачі агента.

        ``front=True`` ставить задачу на самий початок (ручне підняття).
        ``chat_id`` прив'язує задачу до чату — тоді вона зникає разом із ним.

        ``number``, ``detail``, ``goal``, ``depends_on`` і ``tools``
        заповнює планувальник: це дані плану, який склала локальна модель.
        """
        text = (text or "").strip()
        if not text:
            return None
        task = QueueTask(
            text=text, skill=skill, use_skills=use_skills,
            origin=normalise_origin(origin), file_hint=file_hint,
            chat_id=str(chat_id or ""),
            number=int(number or 0),
            detail=(detail or "").strip(),
            goal=(goal or "").strip(),
            depends_on=[str(dep) for dep in depends_on or () if str(dep).strip()],
            tools=[str(tool) for tool in tools or () if str(tool).strip()],
        )
        if front:
            self.tasks.insert(0, task)
        else:
            self.tasks.append(task)
        self._changed()
        return task

    def replace_plan(self, steps: Iterable[Any], *, chat_id: str = "",
                     goal: str = "") -> list[QueueTask]:
        """Замінити план цього чату новим (перепланування).

        Кожен крок — словник із ключами ``text``, ``detail``, ``tools``,
        ``depends_on`` (індекси 1..N у межах нового плану) і, за бажанням,
        ``depends_on_previous``. Задачі, які вже почали виконуватись,
        лишаються: їх не можна «переписати» під руками агента.

        Повертає додані задачі.
        """
        clean_chat = str(chat_id or "").strip()
        # Прибираємо лише ті задачі плану, що ще не починалися.
        keep: list[QueueTask] = []
        for task in self.tasks:
            same = (task.chat_id == clean_chat) if clean_chat else not task.chat_id
            if same and task.status == PENDING:
                continue
            keep.append(task)
        self.tasks = keep
        added = self.add_steps(steps, chat_id=clean_chat, goal=goal)
        if added:
            # Новий план починається з 01. Без цього номери продовжувались
            # із попереднього плану (перевірено: замість 1,2 — 2,3), і
            # панель показувала «04, 05» як перші кроки нової роботи.
            for index, task in enumerate(added, start=1):
                task.number = index
            self.renumber(chat_id=clean_chat)
        return added

    def add_steps(self, steps: Iterable[Any], *, chat_id: str = "",
                  goal: str = "", origin: str = ORIGIN_AGENT) -> list[QueueTask]:
        """Додати послідовність кроків плану з коректними залежностями.

        Кроки подаються або рядками, або словниками. Початкові індекси в
        ``depends_on`` — це НОМЕРИ ВСЕРЕДИНІ цього набору (1-based), їх
        перекладаємо в реальні ``id`` задач: модель не знає наших id, вона
        природно мислить номерами кроків.

        Послідовна залежність ставиться за замовчуванням: крок N чекає на
        крок N-1. Модель може скасувати це полем ``depends_on_previous:
        false``, якщо крок справді незалежний.
        """
        rows = list(steps or ())
        if not rows:
            return []
        created: list[QueueTask] = []
        # Нумерація продовжує НАЯВНИЙ план цього чату (дозапис кроків після
        # перепланування), а новий план починається з 01. Раніше номер
        # рахували від довжини всієї черги, і перший крок плану отримував
        # «04», якщо в черзі вже були сторонні задачі.
        existing = [int(getattr(t, "number", 0) or 0)
                    for t in self.tasks if str(t.chat_id or "") == str(chat_id or "")]
        start_number = max(existing, default=0) + 1
        for position, row in enumerate(rows, start=1):
            if isinstance(row, str):
                data: dict[str, Any] = {"text": row}
            elif isinstance(row, dict):
                data = dict(row)
            else:
                continue
            text = str(data.get("text") or "").strip()
            if not text:
                continue
            task = QueueTask(
                text=text,
                origin=normalise_origin(origin),
                chat_id=str(chat_id or ""),
                number=int(data.get("number") or (start_number + position - 1)),
                detail=str(data.get("detail") or "").strip(),
                goal=str(goal or data.get("goal") or "").strip(),
                tools=[str(t) for t in (data.get("tools") or []) if str(t).strip()],
            )
            created.append(task)
            self.tasks.append(task)
        # Тепер, коли всі id відомі, прив'язуємо залежності за номерами.
        for offset, task in enumerate(created):
            source = rows[offset] if offset < len(rows) else None
            data = source if isinstance(source, dict) else {}
            explicit = data.get("depends_on")
            deps: list[str] = []
            if isinstance(explicit, (list, tuple)):
                for item in explicit:
                    index = 0
                    try:
                        index = int(item)
                    except (TypeError, ValueError):
                        continue
                    if 1 <= index <= len(created):
                        deps.append(created[index - 1].id)
            else:
                keep_chain = bool(data.get("depends_on_previous", True))
                if keep_chain and offset > 0:
                    deps.append(created[offset - 1].id)
            task.depends_on = deps
        if created:
            self._changed()
        return created

    def renumber(self, *, chat_id: str = "") -> None:
        """Перенумерувати задачі плану від 1 (після змін черги).

        Номер має відповідати місцю в черзі, інакше панель показує «03»
        перед «01». Нумеруємо лише ті задачі, що мають номер (тобто
        належать плану), а «поодинокі» задачі користувача лишаються без
        номера — вони не частина плану.
        """
        clean_chat = str(chat_id or "").strip()
        number = 0
        for task in self.tasks:
            if clean_chat and task.chat_id and task.chat_id != clean_chat:
                continue
            # Номер мають лише кроки плану. Раніше умова «без номера, але
            # PENDING» теж нумерувала задачу — і поодинока задача
            # користувача («запусти тести») перетворювалась на крок «01»,
            # після чого ``plan_tasks`` показував її як частину плану.
            if not task.number:
                continue
            number += 1
            task.number = number

    def plan_tasks(self, *, chat_id: str = "") -> list[QueueTask]:
        """Задачі, які належать плану (мають номер), у порядку черги."""
        clean_chat = str(chat_id or "").strip()
        return [t for t in self.tasks
                if t.number
                and (not clean_chat or not t.chat_id or t.chat_id == clean_chat)]

    def drop_plan(self, *, chat_id: str = "", keep_active: bool = True) -> int:
        """Прибрати попередній план, щоб новий не змішувався зі старим.

        Прибираємо ВСІ кроки плану цього чату, не лише незавершені:
        інакше завершені кроки старого плану лишались у списку, і новий
        план виглядав як «12 задач замість 6» із дублями (перевірено на
        живому прогоні: 11 старих + 6 нових). Історія виконаного вже
        збережена у звіті й у ``files_changed``, тож втрати немає.

        Активний крок лишаємо (його не можна «переписати» під руками
        агента), якщо ``keep_active`` істинне.
        """
        clean_chat = str(chat_id or "").strip()
        removed = 0
        keep: list[QueueTask] = []
        for task in self.tasks:
            same = (task.chat_id == clean_chat) if clean_chat else not task.chat_id
            if not same:
                keep.append(task)
                continue
            if task.active and keep_active:
                keep.append(task)
                continue
            removed += 1
        if removed:
            self.tasks = keep
            if self.running_id and self.get(self.running_id) is None:
                self.running_id = ""
            self._changed()
        return removed

    def extend(self, texts: Iterable[str], *, skill: str = "",
               origin: str = ORIGIN_AGENT, chat_id: str = "") -> int:
        added = 0
        for text in texts:
            if self.add(text, skill=skill, origin=origin, chat_id=chat_id) is not None:
                added += 1
        return added

    def remove(self, task_id: str) -> bool:
        for index, task in enumerate(self.tasks):
            if task.id == task_id:
                if task.active:
                    return False
                del self.tasks[index]
                self._changed()
                return True
        return False

    def clear_finished(self) -> int:
        keep = {PENDING, ANALYZING, RUNNING, VERIFYING}
        before = len(self.tasks)
        self.tasks = [t for t in self.tasks if t.status in keep]
        removed = before - len(self.tasks)
        if removed:
            self._changed()
        return removed

    def clear(self) -> None:
        if not self.tasks:
            return
        self.tasks = []
        self.running_id = ""
        self._changed()

    def remove_for_chat(self, chat_id: str) -> int:
        """Прибрати всі задачі, прив'язані до чату. Повертає кількість.

        Викликається, коли чат видаляють або чистять: без цього черга
        лишалась із задачами «сиротами», і агент продовжував їх виконувати
        вже після того, як розмова зникла.
        """
        clean = str(chat_id or "").strip()
        if not clean:
            return 0
        before = len(self.tasks)
        self.tasks = [task for task in self.tasks if task.chat_id != clean]
        removed = before - len(self.tasks)
        if removed:
            # Активна задача могла належати цьому чату.
            if self.running_id and self.get(self.running_id) is None:
                self.running_id = ""
            self._changed()
        return removed

    def adopt_orphans(self, chat_id: str) -> int:
        """Прив'язати задачі без власника до вказаного чату. Повертає кількість.

        Навіщо: до виправлення кроки плану додавались без ``chat_id``, тож
        після видалення чату задачі лишались у черзі «сиротами» — саме
        такі три задачі й висіли в панелі «Автоматизації» на скріншоті
        користувача. Тепер на старті вони дістають власника, і видалення
        чату прибирає їх разом із ним.

        Порожній ``chat_id`` — нічого не робимо: без власника прив'язувати
        нема до чого.
        """
        clean = str(chat_id or "").strip()
        if not clean:
            return 0
        adopted = 0
        for task in self.tasks:
            if str(getattr(task, "chat_id", "") or "").strip():
                continue
            task.chat_id = clean
            adopted += 1
        if adopted:
            self._changed()
        return adopted

    # ── рух черги ──────────────────────────────────────────────────────────
    def blocked_by(self, task: QueueTask) -> list[QueueTask]:
        """Задачі з черги, які ще не закриті й потрібні цій задачі.

        Залежності — вимога послідовного плану: крок «інтеграція frontend із
        backend» не має стартувати, поки не готові кроки «backend» і
        «frontend». Повертаємо саме ті задачі, які тримають цю.
        """
        blockers: list[QueueTask] = []
        for dep_id in getattr(task, "depends_on", []) or []:
            other = self.get(str(dep_id))
            if other is None or other.id == task.id:
                continue
            if other.status != DONE:
                blockers.append(other)
        return blockers

    def is_ready(self, task: QueueTask) -> bool:
        """Чи можна брати задачу: усі її залежності вже завершені."""
        return not self.blocked_by(task)

    def dependents_of(self, task_id: str) -> list[QueueTask]:
        """Задачі, які чекають на цю (для каскадного скасування)."""
        return [t for t in self.tasks
                if task_id in (getattr(t, "depends_on", []) or [])]

    def cascade_failure(self, task_id: str) -> list[QueueTask]:
        """Зняти з черги кроки, які вже ніколи не стануть готовими.

        Навіщо: якщо крок 06 упав, кроки 07–10 із залежністю на нього не
        запустяться НІКОЛИ. Без цього черга «зависала» — користувач бачив
        список зі статусом «очікує», який не рухався, і не розумів, що
        програма чекає на неможливе.

        Скасовуємо транзитивно (07 → 08 → …), бо кожен наступний теж
        залежить від попереднього. Повертає зачеплені кроки.
        """
        broken: list[QueueTask] = []
        frontier = [str(task_id)]
        seen: set[str] = {str(task_id)}
        while frontier:
            current = frontier.pop()
            for dependent in self.dependents_of(current):
                if dependent.id in seen:
                    continue
                seen.add(dependent.id)
                if dependent.status != PENDING:
                    continue
                blocker = self.get(current)
                label = f"{blocker.number:02d}" if blocker and blocker.number else current[:6]
                dependent.status = CANCELLED
                dependent.finished_at = time.time()
                dependent.current_step = ""
                dependent.error = f"не запускався: крок {label} завершився з помилкою"
                dependent.add_history("cancelled", dependent.error)
                broken.append(dependent)
                frontier.append(dependent.id)
        if broken:
            self._changed()
        return broken

    def unresolved(self, *, chat_id: str = "") -> list[QueueTask]:
        """Кроки, які лишились «очікує», але вже не мають шансу стартувати."""
        mine = str(chat_id or "").strip()
        result: list[QueueTask] = []
        for task in self.tasks:
            if task.status != PENDING:
                continue
            if mine and task.chat_id and task.chat_id != mine:
                continue
            if any(blocker.status in (FAILED, CANCELLED)
                   for blocker in self.blocked_by(task)):
                result.append(task)
        return result

    def next_pending(self, *, chat_id: str = "") -> Optional[QueueTask]:
        """Наступна задача: спершу задачі користувача, далі задачі агента.

        Пріоритет користувача — вимога автономного режиму: агент сам
        наповнює чергу, але щойно людина додала свою задачу, вона має
        виконатись раніше за будь-яку агентську. Серед задач одного автора
        порядок лишається той, у якому їх додали.

        Задача з невиконаними залежностями не видається: інакше крок
        «перевірити весь сайт» стартував би раніше, ніж створено сторінки.

        ``chat_id`` обмежує пошук задачами цього чату: інакше після зміни
        проєкту агент брав би задачу попереднього чату й виконував її вже
        в іншій теці. Порожній ``chat_id`` — без обмеження (усі задачі),
        як було раніше.
        """
        if self.paused or self.running_id:
            return None
        mine = str(chat_id or "").strip()

        def fits(task: QueueTask) -> bool:
            # Задача без власника («сирота») належить лише режиму «без
            # обмежень» (порожній ``chat_id``). Раніше ``not task.chat_id``
            # означало «належить УСІМ», і чат Б виконував задачу чату А.
            if not mine:
                return True
            return str(getattr(task, "chat_id", "") or "") == mine

        for task in self.tasks:
            if task.status == PENDING and task.from_user and fits(task) and self.is_ready(task):
                return task
        for task in self.tasks:
            if task.status == PENDING and fits(task) and self.is_ready(task):
                return task
        return None

    def waiting_on_dependencies(self, *, chat_id: str = "") -> list[QueueTask]:
        """Задачі, які готові до запуску, але чекають на інші.

        Потрібно панелі: користувач бачить, що черга не «зависла», а
        справді чекає на попередній крок.
        """
        mine = str(chat_id or "").strip()
        return [t for t in self.tasks
                if t.status == PENDING
                and (not mine or not t.chat_id or t.chat_id == mine)
                and self.blocked_by(t)]

    def pending_of(self, origin: str) -> list[QueueTask]:
        """Усі задачі в черзі від заданого автора (у порядку виконання)."""
        want = normalise_origin(origin)
        return [t for t in self.tasks if t.status == PENDING and t.origin == want]

    def counts_by_origin(self) -> dict[str, int]:
        """Скільки задач у черзі від кожного автора (лише ``PENDING``)."""
        result = {ORIGIN_AGENT: 0, ORIGIN_USER: 0}
        for task in self.tasks:
            if task.status == PENDING and task.origin in result:
                result[task.origin] += 1
        return result

    def mark_running(self, task_id: str) -> Optional[QueueTask]:
        """Почати виконання задачі (лічильник спроб зростає)."""
        task = self.get(task_id)
        if task is None:
            return None
        task.status = RUNNING
        task.started_at = time.time()
        task.finished_at = 0.0
        task.error = ""
        task.result = ""
        task.attempts = int(getattr(task, "attempts", 0) or 0) + 1
        task.add_history("start", f"спроба {task.attempts}")
        self.running_id = task_id
        self._changed()
        return task

    def set_stage(self, task_id: str, status: str, *, step: str = "") -> bool:
        """Перевести активну задачу в проміжний стан (аналіз / перевірка).

        Статуси ``аналіз`` і ``перевірка`` показують, ЩО робить модель
        просто зараз. Задачу вони не закривають: ``running_id`` лишається,
        тож насос черги не візьме наступну задачу паралельно.
        """
        task = self.get(task_id)
        if task is None:
            return False
        if status not in (ANALYZING, RUNNING, VERIFYING):
            return False
        task.status = status
        if step:
            task.current_step = " ".join(step.split())[:200]
            task.add_history(status, step)
        self._changed()
        return True

    def mark_done(self, task_id: str, result: str = "") -> None:
        task = self.get(task_id)
        if task is None:
            return
        task.status = DONE
        task.finished_at = time.time()
        task.result = (result or "")[:4000]
        task.current_step = ""
        task.add_history("done", "завершено")
        if self.running_id == task_id:
            self.running_id = ""
        self._changed()

    def mark_failed(self, task_id: str, error: str) -> None:
        task = self.get(task_id)
        if task is None:
            return
        task.status = FAILED
        task.finished_at = time.time()
        task.error = (error or "")[:2000]
        task.current_step = ""
        task.add_history("failed", error or "невідома помилка")
        if self.running_id == task_id:
            self.running_id = ""
        self._changed()

    def mark_paused(self, task_id: str, reason: str = "") -> bool:
        """Призупинити задачу (зупинка користувачем, не помилка)."""
        task = self.get(task_id)
        if task is None:
            return False
        task.status = PAUSED
        task.finished_at = time.time()
        task.current_step = ""
        if reason:
            task.error = reason[:2000]
        task.add_history("paused", reason or "зупинено користувачем")
        if self.running_id == task_id:
            self.running_id = ""
        self._changed()
        return True

    def cancel(self, task_id: str) -> bool:
        task = self.get(task_id)
        if task is None:
            return False
        if task.active:
            return False
        task.status = CANCELLED
        task.finished_at = time.time()
        task.current_step = ""
        task.add_history("cancelled", "скасовано")
        self._changed()
        return True

    def retry(self, task_id: str) -> bool:
        """Повернути задачу в чергу (невдалу, скасовану або призупинену)."""
        task = self.get(task_id)
        if task is None or task.active:
            return False
        task.status = PENDING
        task.started_at = 0.0
        task.finished_at = 0.0
        task.result = ""
        task.error = ""
        task.current_step = ""
        # Лічильник спроб скидаємо: інакше після трьох падінь кнопка
        # «Повторити» нічого не давала — виконавець одразу відмовляв
        # («перевищено ліміт спроб»), і задача лишалась мертвою назавжди.
        # Повтор тут — це СВІДОМИЙ намір користувача, а не автоматика.
        task.attempts = 0
        task.add_history("retry", "повернуто в чергу")
        self._changed()
        return True

    def requeue_running(self) -> Optional[QueueTask]:
        """Прибрати «завислу» активну задачу: вона знову очікує.

        Викликається, коли агент завершив роботу без звіту про статус
        (напр. виняток у чужому колбеку). Без цього ``running_id`` лишався
        зайнятим, і черга назавжди зупинялась.
        """
        task = self.get(self.running_id) if self.running_id else None
        self.running_id = ""
        if task is None:
            return None
        if task.active:
            task.status = PENDING
            task.current_step = ""
            task.finished_at = 0.0
            task.add_history("requeue", "повернено в чергу після збою")
            self._changed()
        return task

    def move(self, task_id: str, delta: int) -> bool:
        task = self.get(task_id)
        if task is None:
            return False
        index = self.tasks.index(task)
        target = max(0, min(len(self.tasks) - 1, index + delta))
        if target == index:
            return False
        self.tasks.insert(target, self.tasks.pop(index))
        self._changed()
        return True

    def reorder(self, task_id: str, position: int) -> bool:
        """Поставити задачу на конкретну позицію (1 = початок черги)."""
        task = self.get(task_id)
        if task is None:
            return False
        index = self.tasks.index(task)
        target = max(0, min(len(self.tasks) - 1, int(position) - 1))
        if target == index:
            return False
        self.tasks.insert(target, self.tasks.pop(index))
        self._changed()
        return True

    def set_paused(self, paused: bool) -> None:
        self.paused = bool(paused)
        self._changed()

    def toggle_paused(self) -> bool:
        self.set_paused(not self.paused)
        return self.paused

    # ── запити ─────────────────────────────────────────────────────────────
    def get(self, task_id: str) -> Optional[QueueTask]:
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def counts(self) -> dict[str, int]:
        result = {status: 0 for status in STATUS_ORDER}
        for task in self.tasks:
            if task.status in result:
                result[task.status] += 1
        return result

    def progress(self) -> dict[str, int]:
        """Зведення для шапки центру завдань: усього / готово / у черзі / збої."""
        counts = self.counts()
        return {
            "total": len(self.tasks),
            "done": counts[DONE],
            "pending": counts[PENDING],
            "errors": counts[FAILED],
            "active": sum(counts[s] for s in ACTIVE_STATUSES),
            "paused": counts[PAUSED],
        }

    def percent_done(self) -> float:
        """Частка закритих успішно задач (0..100) для смуги прогресу."""
        total = len(self.tasks)
        if not total:
            return 0.0
        return 100.0 * self.counts()[DONE] / total

    def summary(self) -> str:
        counts = self.counts()
        parts = [f"{len(self.tasks)} задач"]
        if counts[PENDING]:
            parts.append(f"очікує {counts[PENDING]}")
        if counts[RUNNING]:
            parts.append("виконується")
        return " · ".join(parts)

    def suspend_pending(self, *, origin: str = "") -> int:
        """Прибрати задачі з черги на паузу (не скасовуючи їх).

        Використовується, коли автономний режим вимикають: задачі агента,
        які він сам собі напланував, не мають виконуватись після зупинки.
        Задачі користувача лишаються, якщо ``origin`` не задано.
        """
        removed = 0
        keep: list[QueueTask] = []
        want = normalise_origin(origin) if origin else ""
        for task in self.tasks:
            if task.status == PENDING and (not want or task.origin == want):
                task.status = CANCELLED
                task.finished_at = time.time()
                task.error = "автономний режим вимкнено"
                removed += 1
            keep.append(task)
        if removed:
            self.tasks = keep
            self._changed()
        return removed


def split_batch(text: str) -> list[str]:
    """Розбити багаторядковий текст на задачі.

    Кожен рядок, що починається з ``-``, ``*``, ``•`` або числа з крапкою,
    стає окремою задачею; решта рядків — одна задача, якщо список відсутній.
    """
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    bulleted: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        for marker in ("- ", "* ", "• "):
            if stripped.startswith(marker):
                bulleted.append(stripped[len(marker):].strip())
                break
        else:
            head, _, tail = stripped.partition(". ")
            if head.isdigit() and tail.strip():
                bulleted.append(tail.strip())
            else:
                bulleted.append(stripped)
    items = [item for item in bulleted if item]
    if len(items) <= 1:
        return [" ".join(lines).strip()] if lines else []
    return items
