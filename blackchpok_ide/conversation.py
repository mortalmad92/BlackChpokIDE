"""Стан розмови: що ми вже зрозуміли, пообіцяли й вирішили.

Проблема, яку закриває цей модуль, описана користувачем буквально:
«Чат знову забув попереднє». Причин було дві, і обидві не в моделі:

1. кожне повідомлення трактувалось як НОВЕ завдання — зв'язки між
   репліками не зберігались;
2. обмеження («тільки щоб старі не видалялись») жили в тексті останнього
   повідомлення й зникали, щойно модель починала новий хід.

Тут зберігається саме те, що мусить пережити окремий хід:

* **ціль завдання** — одна на діалог, доки не з'явиться нова;
* **обмеження** — додаються, ніколи не зникають самі;
* **об'єкти згадки** — файли, функції, теми (для «воно», «той файл»);
* **відкрите питання** — якщо ми щось уточнили й чекаємо відповіді;
* **профіль користувача** — довготривалі вподобання, які людина назвала
  прямо («відповідай українською», «мінімальні правки»).

Профіль навмисно відділений від поточного завдання: «зроби коротко» —
це тимчасова інструкція, а «відповідай українською» — назавжди.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "ConversationState",
    "Preference",
    "UserProfile",
    "extract_preferences",
    "resolve_reference",
]


# ─── Профіль користувача ────────────────────────────────────────────────────

@dataclass
class Preference:
    """Одне довготривале вподобання, назване користувачем прямо."""

    key: str
    value: str
    said: str = ""          # як саме це сказали (для пояснення)
    when: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "value": self.value,
                "said": self.said, "when": self.when}

    @classmethod
    def from_dict(cls, data: Any) -> "Preference | None":
        if not isinstance(data, dict):
            return None
        key = str(data.get("key") or "").strip()
        value = str(data.get("value") or "").strip()
        if not key or not value:
            return None
        try:
            when = float(data.get("when") or time.time())
        except (TypeError, ValueError):
            when = time.time()
        return cls(key=key, value=value, said=str(data.get("said") or ""), when=when)


#: (ключ, ознаки у фразі, значення). Порядок — від загального до часткового.
_PREFERENCE_RULES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("language", ("відповідай українською", "говори українською",
                  "спілкуйся українською", "відповідай по-українськи"),
     "українська"),
    ("language", ("answer in english", "reply in english", "speak english"),
     "англійська"),
    ("verbosity", ("коротко", "без води", "стисло", "по суті", "не розписуй"),
     "коротко"),
    ("verbosity", ("детально", "докладно", "з поясненнями", "розпиши"),
     "детально"),
    ("code_style", ("мінімальні зміни", "мінімальні правки", "точково",
                    "не переписуй файли", "лише потрібне"),
     "мінімальні точкові зміни"),
    ("code_style", ("додавай коментарі", "з коментарями"), "з коментарями"),
    ("tooling", ("не використовуй mcp", "без mcp"), "без MCP"),
    ("tooling", ("завжди перевіряй тестами", "проганяй тести після"),
     "перевіряти тестами"),
    ("format", ("без блоків коду", "не показуй код"), "без блоків коду"),
    ("format", ("показуй код повністю", "повний код файлу"), "повний код файлу"),
    ("safety", ("ніколи не видаляй", "не видаляй файли", "не видаляй нічого"),
     "нічого не видаляти"),
)

#: Слова, які роблять інструкцію ДОВГОТРИВАЛОЮ (а не «на цей раз»).
_PERMANENT_MARKERS: tuple[str, ...] = (
    "завжди", "надалі", "відтепер", "запам'ятай", "запамятай", "правило",
    "у всіх відповідях", "постійно", "always", "from now on", "remember",
)

#: Слова, які роблять інструкцію ТИМЧАСОВОЮ.
_TEMPORARY_MARKERS: tuple[str, ...] = (
    "цього разу", "зараз", "на цей раз", "тільки сьогодні", "поки що",
    "this time", "for now",
)

#: Що НЕ можна зберігати, навіть якщо попросили (приватність за замовчуванням).
_PRIVATE_MARKERS: tuple[str, ...] = (
    "не зберігай", "не записуй", "не пам'ятай", "видали з пам'яті",
    "do not store", "don't remember",
)


def extract_preferences(text: str) -> tuple[list[Preference], bool]:
    """Витягти довготривалі вподобання з фрази.

    Повертає ``(знайдені, чи_просили_не_зберігати)``. Друге значення
    важливе: явне «не зберігай» забороняє запис навіть того, що інакше
    виглядало б як вподобання.
    """
    low = (text or "").strip().lower()
    if not low:
        return [], False
    if any(marker in low for marker in _PRIVATE_MARKERS):
        return [], True
    permanent = any(marker in low for marker in _PERMANENT_MARKERS)
    temporary = any(marker in low for marker in _TEMPORARY_MARKERS)
    found: list[Preference] = []
    for key, markers, value in _PREFERENCE_RULES:
        if not any(marker in low for marker in markers):
            continue
        # «коротко» без «завжди» — це прохання до цієї відповіді, а не
        # правило назавжди. Зберігаємо лише явні вподобання.
        if not permanent and not _looks_general_rule(low):
            continue
        if temporary and not permanent:
            continue
        found.append(Preference(key=key, value=value, said=text.strip()[:200]))
    return found, False


def _looks_general_rule(low: str) -> bool:
    """Чи фраза звучить як правило, а не як прохання на один раз."""
    markers = ("відповідай", "спілкуйся", "говори", "пиши завжди",
               "у всіх", "мені подобається коли", "хочу щоб ти")
    return any(marker in low for marker in markers)


class UserProfile:
    """Довготривалі вподобання користувача (зберігаються між сесіями).

    Не робить висновків про особистість: лише те, що людина сказала прямо.
    """

    def __init__(self, items: Iterable[Preference] | None = None) -> None:
        self._items: dict[str, Preference] = {}
        for item in items or ():
            self.remember(item)

    # ── вміст ──────────────────────────────────────────────────────────────
    def remember(self, preference: Preference) -> bool:
        """Записати вподобання. Новіше значення перекриває старе."""
        if not preference.key or not preference.value:
            return False
        old = self._items.get(preference.key)
        if old is not None and old.value == preference.value:
            return False
        self._items[preference.key] = preference
        return True

    def forget(self, key: str) -> bool:
        return self._items.pop(key, None) is not None

    def get(self, key: str, default: str = "") -> str:
        item = self._items.get(key)
        return item.value if item is not None else default

    def all(self) -> list[Preference]:
        return sorted(self._items.values(), key=lambda item: item.key)

    def is_empty(self) -> bool:
        return not self._items

    # ── вплив на поведінку ─────────────────────────────────────────────────
    def prompt_block(self, *, language: str = "uk") -> str:
        """Підказка моделі (стисла, без JSON). Порожня, якщо нічого немає."""
        if not self._items:
            return ""
        lines = ["Постійні побажання користувача (виконуй їх завжди):"]
        for item in self.all():
            lines.append(f"- {item.value}")
        return "\n".join(lines)

    def language(self, fallback: str = "uk") -> str:
        value = self.get("language")
        if value == "українська":
            return "uk"
        if value == "англійська":
            return "en"
        return fallback

    def verbosity(self) -> str:
        return self.get("verbosity", "")

    def to_list(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.all()]

    @classmethod
    def from_list(cls, data: Any) -> "UserProfile":
        items: list[Preference] = []
        if isinstance(data, list):
            for entry in data:
                parsed = Preference.from_dict(entry)
                if parsed is not None:
                    items.append(parsed)
        return cls(items)


# ─── Стан розмови ───────────────────────────────────────────────────────────

#: Скільки останніх реплік тримаємо для розв'язання згадок.
RECENT_LIMIT = 12

#: Займенники й звороти, які треба розв'язати з контексту.
_REFERENCE_MARKERS: tuple[str, ...] = (
    "воно", "він", "вона", "вони", "цей файл", "той файл", "цю штуку",
    "ту штуку", "там", "сюди", "туди", "те саме", "так само", "це все",
    "воно знову", "як минулого разу",
)

#: Звороти «зроби як того разу» — для них достатньо попередньої репліки,
#: навіть якщо мети завдання ще не сформульовано.
_REPEAT_MARKERS: tuple[str, ...] = (
    "так само", "як минулого разу", "як учора", "як раніше", "те саме",
    "поверни як було", "теж саме", "ще раз так",
)


@dataclass
class ConversationState:
    """Що ми знаємо про поточне завдання в цьому діалозі."""

    #: Головна мета поточного завдання (словами).
    goal: str = ""
    #: Обмеження, які діють до кінця завдання.
    constraints: list[str] = field(default_factory=list)
    #: Останній зрозумілий намір (тип із :mod:`intent_engine`).
    intent_type: str = ""
    #: Файли й символи, про які йшлося.
    files: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    #: Останні повідомлення користувача (для контексту й розв'язання згадок).
    recent: list[str] = field(default_factory=list)
    #: Відкрите уточнення: питання, яке ми поставили, і що саме з'ясовуємо.
    pending_question: str = ""
    pending_field: str = ""
    #: Що вже зроблено в межах завдання (для «не роби вдруге»).
    completed: list[str] = field(default_factory=list)
    #: Чи користувач просив не зберігати інформацію з цього діалогу.
    private: bool = False
    #: Лічильник ходів — для traces.
    turns: int = 0
    updated_at: float = field(default_factory=time.time)

    # ── наповнення ────────────────────────────────────────────────────────
    def observe_user_message(self, text: str, intent: Any = None) -> None:
        """Оновити стан після повідомлення користувача.

        ``intent`` — :class:`intent_engine.IntentFrame` (або ``None``).
        Свідомо приймаємо будь-який об'єкт із потрібними полями: це
        дозволяє тестувати стан без побудови кадру.
        """
        body = (text or "").strip()
        if not body:
            return
        self.turns += 1
        self.updated_at = time.time()
        self.recent.append(body)
        del self.recent[:-RECENT_LIMIT]
        if intent is None:
            return
        intent_type = str(getattr(intent, "intent_type", "") or "")
        continuation = bool(getattr(intent, "continuation", False))
        goal = str(getattr(intent, "primary_goal", "") or "")
        if goal and (not continuation or not self.goal):
            self.goal = goal
        # «Продовж» не змінює тип завдання: воно лише додає вимогу до того,
        # що вже робимо. Інакше наступний хід вважався б «розмовою».
        if intent_type and (not continuation or not self.intent_type):
            self.intent_type = intent_type
        for item in getattr(intent, "constraints", ()) or ():
            clean = str(item or "").strip()
            if clean and clean not in self.constraints:
                self.constraints.append(clean)
        for item in getattr(intent, "referenced_files", ()) or ():
            clean = str(item or "").strip()
            if clean and clean not in self.files:
                self.files.append(clean)
        for item in getattr(intent, "referenced_features", ()) or ():
            clean = str(item or "").strip()
            if clean and clean not in self.features:
                self.features.append(clean)
        # Нова задача скидає старі об'єкти, але НЕ обмеження проєкту:
        # людина сказала «не видаляй старі чати» один раз, і це діє далі.
        if not continuation and intent_type not in ("continue", "revise",
                                                    "clarify", ""):
            self.files = self.files[-8:]
            self.features = self.features[-8:]
        self.pending_question = ""
        self.pending_field = ""

    def ask(self, question: str, field_name: str = "") -> None:
        """Запам'ятати, що ми поставили уточнення й чекаємо відповіді."""
        self.pending_question = (question or "").strip()
        self.pending_field = (field_name or "").strip()

    def answered(self) -> bool:
        return bool(self.pending_question)

    def note_done(self, what: str) -> None:
        """Записати, що вже виконано (щоб не робити це вдруге)."""
        clean = (what or "").strip()
        if clean and clean not in self.completed:
            self.completed.append(clean)
            del self.completed[:-20]

    def reset_task(self) -> None:
        """Нове завдання: ціль, файли й «зроблено» — чисті; обмеження лишаються."""
        self.goal = ""
        self.intent_type = ""
        self.files = []
        self.features = []
        self.completed = []
        self.pending_question = ""
        self.pending_field = ""

    # ── використання ──────────────────────────────────────────────────────
    def previous_user_messages(self) -> list[str]:
        """Попередні репліки користувача (без останньої)."""
        return list(self.recent[:-1])

    def last_concrete_message(self, current: str = "") -> str:
        """Остання репліка, у якій справді названо ЗМІСТ (не «воно»).

        Потрібно для «зроби так само»: посилатись треба на репліку зі
        змістом, а не на саму себе й не на попередню згадку. Раніше
        `recent[-1]` міг бути поточною фразою, і модель отримувала
        підказку «„так само“ = зроби так само».
        """
        body = (current or "").strip()
        for item in reversed(self.recent):
            if body and item.strip() == body:
                continue
            if self.has_reference(item):
                continue
            if item.strip():
                return item
        return ""

    def has_reference(self, text: str) -> bool:
        """Чи містить фраза займенник або зворот, що потребує контексту."""
        low = (text or "").lower()
        return any(marker in low for marker in _REFERENCE_MARKERS)

    def resolve(self, text: str) -> str:
        """Підставити об'єкт згадки замість «воно», «той файл», «так само».

        Повертає ПОЯСНЕННЯ для моделі (не переписаний текст): краще
        показати, що саме ми маємо на увазі, ніж мовчки підміняти слова
        користувача.
        """
        return resolve_reference(text, self)

    def prompt_block(self) -> str:
        """Що додати до запиту моделі про поточне завдання."""
        lines: list[str] = []
        if self.goal:
            lines.append(f"Поточна мета: {self.goal}.")
        if self.constraints:
            lines.append("Чинні обмеження: " + "; ".join(self.constraints) + ".")
        if self.files:
            lines.append("Файли завдання: " + ", ".join(self.files[-5:]) + ".")
        if self.completed:
            lines.append("Уже зроблено: " + "; ".join(self.completed[-5:]) + ".")
        if self.pending_question:
            lines.append(f"Ти вже спитав: «{self.pending_question}» — врахуй відповідь.")
        if not lines:
            return ""
        return "\n".join(["Контекст завдання (не перепитуй це):", *lines])

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "constraints": list(self.constraints),
            "intent_type": self.intent_type,
            "files": list(self.files),
            "features": list(self.features),
            "recent": list(self.recent),
            "pending_question": self.pending_question,
            "pending_field": self.pending_field,
            "completed": list(self.completed),
            "private": self.private,
            "turns": self.turns,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "ConversationState":
        if not isinstance(data, dict):
            return cls()
        state = cls()
        state.goal = str(data.get("goal") or "")
        state.intent_type = str(data.get("intent_type") or "")
        state.pending_question = str(data.get("pending_question") or "")
        state.pending_field = str(data.get("pending_field") or "")
        state.private = bool(data.get("private"))
        for key, attr in (("constraints", "constraints"), ("files", "files"),
                          ("features", "features"), ("recent", "recent"),
                          ("completed", "completed")):
            value = data.get(key)
            if isinstance(value, list):
                setattr(state, attr, [str(item) for item in value if str(item)])
        try:
            state.turns = int(data.get("turns") or 0)
        except (TypeError, ValueError):
            state.turns = 0
        try:
            state.updated_at = float(data.get("updated_at") or time.time())
        except (TypeError, ValueError):
            state.updated_at = time.time()
        return state


def resolve_reference(text: str, state: ConversationState) -> str:
    """Пояснити, на що вказують «воно», «той файл», «так само».

    Якщо в контексті нічого немає — чесно кажемо це (порожній рядок):
    тоді краще перепитати, ніж вигадати об'єкт.
    """
    body = (text or "").strip()
    if not body or not state.has_reference(body):
        return ""
    low = body.lower()
    parts: list[str] = []
    repeat = any(marker in low for marker in _REPEAT_MARKERS)
    if repeat:
        # Беремо останню ЗМІСТОВНУ репліку: ``recent`` уже містить поточну
        # фразу, і без цієї перевірки «так само» вказувало на себе ж.
        concrete = state.last_concrete_message(body)
        if concrete:
            parts.append("«Так само» = попереднє прохання: "
                         + _clip(concrete, 200))
        elif state.goal:
            parts.append(f"«Так само» = поточна мета: {state.goal}")
    if not repeat and any(marker in low for marker in (
            "воно", "він", "вона", "вони", "цю штуку", "ту штуку", "це все")):
        concrete = state.last_concrete_message(body)
        subject = concrete or state.goal
        if subject and subject != body.strip():
            parts.append(f"«Воно / це» = {_clip(subject, 160)}")
    if any(marker in low for marker in ("цей файл", "той файл", "там", "сюди",
                                        "туди")) and state.files:
        parts.append("Файл з контексту: " + ", ".join(state.files[-3:]))
    if not parts:
        return ""
    return "Що мається на увазі:\n" + "\n".join(f"- {item}" for item in parts)


def _clip(text: str, limit: int) -> str:
    body = " ".join((text or "").split())
    return body if len(body) <= limit else body[: limit - 1] + "…"


# ─── Збереження стану ───────────────────────────────────────────────────────

def merge_preferences(profile: UserProfile, prefs: Sequence[Preference]) -> int:
    """Додати знайдені вподобання; повернути кількість нових."""
    added = 0
    for item in prefs:
        if profile.remember(item):
            added += 1
    return added


def describe_profile(profile: UserProfile) -> str:
    """Людський опис профілю (для панелі налаштувань і тестів)."""
    items = profile.all()
    if not items:
        return "Постійних побажань ще немає."
    return "Постійні побажання:\n" + "\n".join(
        f"- {item.value}" for item in items)


def profile_from_mapping(data: Mapping[str, Any]) -> UserProfile:
    """Профіль із збереженого словника налаштувань."""
    raw = data.get("preferences") if isinstance(data, Mapping) else None
    return UserProfile.from_list(raw)
