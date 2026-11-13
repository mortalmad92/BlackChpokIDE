"""Розуміння людського наміру: фраза → IntentFrame.

Компонент стоїть **між** повідомленням користувача й планувальником.
Його робота — перетворити живу мову (з помилками, скороченнями, без
термінів) на структуру, з якою може працювати код:

``IntentFrame``
    тип наміру, головна й другорядна мети, згадані файли й функції,
    обмеження, очікуваний результат, потрібні інструменти, відоме й
    відсутнє, рівень ризику, впевненість і критерії завершення.

Три принципи цього модуля:

1. **Детерміноване — кодом, невідоме — моделлю.** Намір, мова, згадані
   шляхи й обмеження визначаються правилами: це швидко, повторювано й не
   залежить від того, чи завантажена модель. Модель лише уточнює те, що
   правилами не видно.
2. **Контекст обов'язковий.** «Зроби так само», «воно», «той файл»
   розв'язуються з попередніх повідомлень (:mod:`conversation`), а не з
   порожнього місця.
3. **Уточнюємо лише тоді, коли без відповіді можна зіпсувати дані.**
   Зайве питання дратує більше, ніж розумне припущення.

Модуль не тягне ні tkinter, ні мережі.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from . import language
from . import task_plan

__all__ = [
    "ACTION_TYPES",
    "CLARIFY",
    "CONVERSE",
    "INSPECT",
    "IntentFrame",
    "classify_message",
    "detect_language",
    "extract_constraints",
    "frame",
    "merge_frames",
    "needs_clarification",
]


# ─── Типи повідомлень ───────────────────────────────────────────────────────
#
# Це не те саме, що наміри в task_plan: там «що зробити з кодом», тут —
# «що це за повідомлення взагалі». Від цього залежить, чи взагалі треба
# запускати інструменти.

CONVERSE = "converse"      # звичайна розмова, жарт, подяка
EXPLAIN = "explain"        # пояснити, не змінюючи нічого
RESEARCH = "research"      # знайти інформацію (проєкт або інтернет)
INSPECT = "inspect"        # подивитись реальний стан (файли, логи, тести)
CREATE = "create"          # створити новий функціонал
EDIT = "edit"              # виправити або змінити наявний код
DEBUG = "debug"            # «не працює» → знайти причину й виправити
RUN = "run"                # виконати команду, запустити проєкт
TEST = "test"              # прогнати перевірки
CONTINUE = "continue"      # продовження попереднього завдання
REVISE = "revise"          # зміна вимог до вже озвученого завдання
CLARIFY = "clarify"        # користувач відповідає на наше питання

ACTION_TYPES: tuple[str, ...] = (
    CREATE, EDIT, DEBUG, RUN, TEST, INSPECT, RESEARCH,
)

#: Скільки часу людина витрачає на пояснення, якщо агент перепитує дарма:
#: тому поріг упевненості навмисно низький, а питання — лише за ризику.
CLARIFY_THRESHOLD = 0.55

#: Ризик, за якого краще спитати один раз, ніж зробити навмання.
RISKY_REQUESTS: tuple[str, ...] = ("видали", "видалити", "стерти", "очисти",
                                   "drop", "delete", "rm ", "звільни місце",
                                   "перезапиши весь", "задеплой", "опубліку",
                                   "опублікуй", "онови всі")

# ─── Мова ───────────────────────────────────────────────────────────────────

_UK_MARKERS = ("ї", "є", "і", "ґ", "зроби", "треба", "будь ласка", "цей", "ця")
_RU_MARKERS = ("ы", "э", "ъ", "ё", "сделай", "надо", "это", "файл нужно")
_EN_MARKERS = re.compile(r"\b(the|please|make|fix|add|create|please|should|need)\b", re.I)

#: Помилки й скорочення, які агент мусить розуміти однаково добре.
_TYPO_FIXES: tuple[tuple[str, str], ...] = (
    ("роутер мсп", "MCP router"),
    ("мсп", "MCP"),
    ("уі", "UI"),
    ("ui", "UI"),
    ("фронт", "frontend"),
    ("бек", "backend"),
    ("бекенд", "backend"),
    ("фронтенд", "frontend"),
    ("апі", "API"),
    ("api", "API"),
    ("бд", "база даних"),
    ("бд ", "база даних "),
    ("докер", "Docker"),
    ("реп", "репозиторій"),
    ("конфіг", "конфігурація"),
    ("конфиг", "конфігурація"),
)


def detect_language(text: str) -> str:
    """Мова повідомлення: ``uk``, ``ru``, ``en`` або ``mixed``.

    Свідомо груба евристика: кирилиця з «ї/є/і» — українська, з «ы/э/ъ» —
    російська. Модель усе одно читає будь-яку з них; це поле потрібне
    лише для того, щоб ВІДПОВІДАТИ тією ж мовою.

    Ідентифікатори коду (``master_agent_router``, ``calc.py``) не
    рахуються: інакше українська фраза з назвою функції вважалась би
    «змішаною мовою», і агент відповідав би не тією мовою.
    """
    body = _without_code_tokens(text or "")
    low = body.lower()
    latin = len(re.findall(r"[a-z]", low))
    cyrillic = len(re.findall(r"[а-яёіїєґ]", low))
    total = latin + cyrillic
    if total == 0:
        # Самі лише ідентифікатори — мову визначити нема з чого.
        return "uk" if not (text or "").strip() or cyrillic else "en"
    if latin > cyrillic * 2:
        return "en"
    if cyrillic == 0:
        return "en"
    uk_hits = sum(1 for marker in _UK_MARKERS if marker in low)
    ru_hits = sum(1 for marker in _RU_MARKERS if marker in low)
    if latin > cyrillic * 0.4:
        return "mixed"
    if ru_hits > uk_hits:
        return "ru"
    return "uk"


#: Слова-ідентифікатори, які не свідчать про мову повідомлення.
_IDENTIFIER_RE = re.compile(
    r"\b[\w.\-]*[_./\\][\w./\\\-]*\b"      # master_agent_router, calc.py, a/b
    r"|\b[A-Za-z]{2,}\d[\w]*\b"            # utf8, llama3, v1
    r"|\b\w+\.(?:py|js|ts|json|md|txt|html|css|yml|yaml|toml|ini)\b",
    re.IGNORECASE,
)


def _without_code_tokens(text: str) -> str:
    """Прибрати ідентифікатори коду — вони не вказують на мову спілкування."""
    return _IDENTIFIER_RE.sub(" ", text)


def normalise_phrase(text: str) -> str:
    """Привести живу фразу до вигляду, зручного для правил.

    Не «виправлення помилок» у повному сенсі, а розшифровка того, що
    людина справді має на увазі: «мсп» → «MCP», «фронт» → «frontend».

    ── РОСІЙСЬКІ СЛОВА Й СУРЖИК ─────────────────────────────────────────
    Користувач цілком може написати «сделай файл», «проверь папку
    проекта» — і правила, які шукають українські маркери, цього не
    побачать. ``language.normalise`` приводить такі слова до української
    форми, і намір розпізнається.

    Це НЕ переклад: російське речення лишається російським, просто окремі
    слова стають українськими — рівно настільно, щоб збігся пошук.
    Оригінал зберігається окремо (``IntentFrame.text``) — він потрібен
    моделі, і показувати користувачу перероблений текст не можна.
    """
    body = (text or "").strip()
    if not body:
        return ""
    # Спершу російські форми — вони трапляються цілими словами («сделай»),
    # і без них правила українських маркерів не спрацьовують зовсім.
    body = language.normalise(body)
    low = body.lower()
    replaced = low
    for wrong, right in _TYPO_FIXES:
        if wrong in replaced:
            replaced = replaced.replace(wrong, right.lower())
    # Кілька пробілів і повторів розділювачів — до одного.
    replaced = re.sub(r"[ \t]{2,}", " ", replaced)
    return replaced


# ─── IntentFrame ────────────────────────────────────────────────────────────

@dataclass
class IntentFrame:
    """Структуроване розуміння одного повідомлення (ВНУТРІШНЄ).

    Ніколи не показується користувачу як JSON: назовні йде або коротка
    мета словами, або питання, або результат роботи.
    """

    #: Оригінальний текст (модель має бачити саме його).
    text: str = ""
    intent_type: str = CONVERSE
    primary_goal: str = ""
    secondary_goals: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    referenced_files: list[str] = field(default_factory=list)
    referenced_features: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    expected_output: str = ""
    requested_actions: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    known_context: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    risk_level: str = "low"
    confidence: float = 0.5
    completion_criteria: list[str] = field(default_factory=list)
    #: Мова, якою відповідати.
    language: str = "uk"
    #: Чи це продовження попереднього завдання (а не нова задача).
    continuation: bool = False
    #: Чи зрозуміло, ЩО робити (не «про що мова», а «яка дія»).
    actionable: bool = False

    # ── похідні ──────────────────────────────────────────────────────────
    @property
    def needs_tools(self) -> bool:
        """Чи треба взагалі запускати інструменти.

        Звичайна розмова й прохання пояснити — ні. Усе, що вимагає
        подивитись на реальний стан проєкту, — так.
        """
        return self.intent_type in ACTION_TYPES or self.intent_type == INSPECT

    @property
    def is_risky(self) -> bool:
        return self.risk_level in ("high", "critical")

    def goal_text(self) -> str:
        """Мета звичайною мовою — те, що можна показати людині."""
        if self.primary_goal:
            return self.primary_goal
        label = task_plan.INTENT_LABELS.get(self.intent_type, "")
        return label or "виконати прохання"

    def summary_lines(self) -> list[str]:
        """Короткий план словами (не JSON) — для журналу й для чату."""
        lines: list[str] = []
        if self.primary_goal:
            lines.append(self.primary_goal)
        for goal in self.secondary_goals[:3]:
            lines.append(goal)
        for limit in self.constraints[:3]:
            lines.append(f"Обмеження: {limit}")
        return lines

    def to_dict(self) -> dict[str, Any]:
        """Для traces і для тестів (не для показу користувачу)."""
        return {
            "intent_type": self.intent_type,
            "primary_goal": self.primary_goal,
            "secondary_goals": list(self.secondary_goals),
            "entities": list(self.entities),
            "referenced_files": list(self.referenced_files),
            "referenced_features": list(self.referenced_features),
            "constraints": list(self.constraints),
            "expected_output": self.expected_output,
            "requested_actions": list(self.requested_actions),
            "required_tools": list(self.required_tools),
            "known_context": list(self.known_context),
            "missing_information": list(self.missing_information),
            "risk_level": self.risk_level,
            "confidence": round(float(self.confidence), 3),
            "completion_criteria": list(self.completion_criteria),
            "language": self.language,
            "continuation": self.continuation,
            "actionable": self.actionable,
        }


# ─── Розпізнавання типу повідомлення ────────────────────────────────────────

_CONTINUE_MARKERS: tuple[str, ...] = (
    "так само", "як минулого разу", "як учора", "як раніше", "дороби",
    "продовж", "продовжуй", "далі", "і ще", "і також", "те саме",
    "поверни як було", "додай сюди", "теж саме", "зроби також",
)

#: Слабкі ознаки продовження — діють ЛИШЕ коли в чаті вже щось було.
#:
#: «І додай…», «тільки щоб…» доповнюють попереднє завдання. Без історії
#: вони означають звичайне прохання: «тільки щоб старі не видалялись» —
#: це самостійна вимога до правки, а не продовження розмови. Раніше такі
#: фрази ставали «continue», і агент не будував для них жодного плану.
_WEAK_CONTINUE_MARKERS: tuple[str, ...] = (
    "і додай", "і додати", "та додай", "а ще", "і зроби", "і треба",
    "тільки щоб", "лише щоб", "і не ", "і взагалі",
)

_REVISE_MARKERS: tuple[str, ...] = (
    "не так", "замість", "навпаки", "зміни вимогу", "перероби інакше",
    "краще", "не треба", "скасуй", "відміни", "без цього",
)

_TALK_MARKERS: tuple[str, ...] = (
    "привіт", "дякую", "спасибі", "дяки", "ок", "окей", "ага", "зрозуміло",
    "молодець", "клас", "супер", "хай", "добрий день", "доброго вечора",
    "hello", "thanks", "thank you", "ok", "nice",
    # Побутові питання підтримки розмови: на них відповідають словами, і
    # жоден інструмент не потрібен. Без них «Як справи?» ставало «поясни»
    # й агент готував аналіз проєкту на просте вітання.
    "як справи", "як ти", "як воно", "що нового", "як життя", "як настрій",
    "добрий вечір", "доброго дня", "на добраніч", "бувай", "до побачення",
    "how are you", "good morning", "bye",
)

_EXPLAIN_MARKERS: tuple[str, ...] = (
    "поясни", "поясніть", "розкажи", "що таке", "як працює", "чому",
    "навіщо", "у чому різниця", "explain", "why", "how does",
)

_TEST_MARKERS: tuple[str, ...] = (
    "тести", "тест", "pytest", "unittest", "прожени", "прогнати",
    "перевір що працює", "запусти перевірки",
)


#: Живі звороти, яких немає у словниках :mod:`task_plan`.
#:
#: Навіщо окремий список: ``task_plan.understand`` знає літературні
#: дієслова («виправ», «зміни»), а людина пише «поправ», «не паше»,
#: «забув», «юзає». Без цього шару такі фрази ставали «розмовою», і агент
#: відповідав словами замість того, щоб подивитись у код.
_INFORMAL_STEMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (DEBUG, ("не паше", "не пашить", "не фуричить", "не робе", "не робить як",
             "забув", "забуває", "забула", "не бачить", "не бачив", "не видно",
             "поправ", "пофіксь", "фіксани", "полагодь", "лагає", "висить",
             "не тягне", "не запускаєть", "висипаєть", "крашиться")),
    (EDIT, ("перероби", "переробив", "поміняй", "підправ", "докрути",
            "причеши", "почисти", "оптимізуй", "розжени", "прискори")),
    (CREATE, ("накидай", "намути", "зваргань", "напиляй", "згенер", "додай")),
    (INSPECT, ("глянь", "подивись", "поглянь", "чекні", "зазирни",
               "що там", "шо там", "як там", "розберись")),
    (RESEARCH, ("погугли", "пошукай", "загугли", "глянь в інтернеті")),
    (TEST, ("прожени", "прогонив", "тестани", "потестуй")),
)

#: Дії видалення й очищення — окремо, бо вони незворотні.
#:
#: ``task_plan`` знає «прибери», але не «видали все зайве»: фраза без
#: об'єкта в списку файлів ставала «розмовою», і агент відповідав словами
#: на прохання, яке може змінити диск.
_DESTRUCTIVE_STEMS: tuple[str, ...] = (
    "видали", "видалит", "видали все", "стерти", "зітри", "прибери все",
    "очисти", "очистит", "звільни місце", "почисти все",
)

#: Заперечення перед словом-ознакою змінює його сенс на протилежний.
#:
#: «нічого іншого не зламай» — це ОБМЕЖЕННЯ, а не скарга на поломку.
#: Без цієї перевірки фраза ставала «знайди й виправ помилку», і агент
#: шукав неіснуючий баг замість того, щоб зробити прохану правку.
_NEGATIONS: tuple[str, ...] = ("не ", "ні ", "без ", "нехай не", "щоб не")

#: Ознаки «зроби, щоб працювало» — це про виправлення, а не про правку.
_WORK_MARKERS: tuple[str, ...] = (
    "працювало нормально", "працювало як треба", "працювало правильно",
    "щоб працювало", "запрацювало", "завелося",
)

#: Слова-ознаки того, що людина просить НЕ робити (обмеження).
_NO_GO_MARKERS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("не вигадув", "не придумуй", "не фантазуй", "не вигадай"),
     "не вигадувати вміст файлів і результати"),
    (("не ліз у все", "не лізь у все", "не ліз у усі", "не лізь у усі",
      "не чіпай усе підряд", "не чіпай все підряд",
      "не змінюй усе підряд", "не змінюй все підряд",
      "тільки потрібні файли", "лише потрібні файли"),
     "змінювати лише потрібні файли"),
    # Заборона КОНКРЕТНОЇ дії. Це найнебезпечніше заперечення: без нього
    # «не запускай тести» читалось як TEST (тобто саме «запусти тести»), і
    # агент робив рівно те, що людина заборонила.
    (("не запускай", "не запускати", "не проганяй", "не прожени",
      "не ганяй", "без запуску"), "не запускати команди й перевірки"),
    (("не змінюй", "не правити", "не чіпай", "не торкайся", "без змін у коді",
      "нічого не міняй"), "не змінювати наявні файли"),
    (("не читай", "не відкривай", "не дивись у файли"),
     "не читати файли проєкту"),
    (("без тестів", "не треба тестів", "тести не потрібні"),
     "не запускати тести"),
)


def _has_any(low: str, markers: Iterable[str]) -> bool:
    return any(marker in low for marker in markers)


def _negated_at(low: str, position: int) -> bool:
    """Чи перед цією позицією стоїть заперечення («не зламай», «щоб не»)."""
    if position <= 0:
        return False
    before = low[max(0, position - 14):position]
    return any(negation in before for negation in _NEGATIONS)


def _has_effective(low: str, markers: Iterable[str]) -> bool:
    """Чи є ознака БЕЗ заперечення перед нею.

    «зламай» і «не зламай» — протилежні прохання: перше просить
    виправити, друге — обмеження. Тому «погані» ознаки перевіряємо цією
    функцією, а не простим підрядком: інакше «нічого іншого не зламай»
    читалось би як скарга на поломку.
    """
    for marker in markers:
        position = low.find(marker)
        while position != -1:
            if not _negated_at(low, position):
                return True
            position = low.find(marker, position + 1)
    return False


#: Дієслова в наказовому способі, які під «не» стають ЗАБОРОНОЮ.
#:
#: «не запускай», «не читай», «не видаляй» — це вимога НЕ РОБИТИ. Слова
#: про об'єкт («тести», «файли») при цьому лишаються в реченні, і саме тому
#: без окремої перевірки фраза виглядала як завдання зробити протилежне.
_PROHIBITION_VERBS: tuple[str, ...] = (
    "запускай", "запускати", "запусти", "проганяй", "проганяти", "прожени",
    "прогонив", "ганяй", "читай", "читати", "відкрий", "відкривати",
    "видаляй", "видаляти", "стирай", "стирати", "змінюй", "змінювати",
    "чіпай", "чіпати", "торкайся", "переписуй", "переписувати", "правити",
    "встановлюй", "встановлювати", "став", "додавай", "додавати",
    "використовуй", "використовувати", "звертайся", "викликай", "викликати",
    "питай", "турбуй", "витрачай", "витрачати", "коміть", "комітити",
    "публікуй", "деплой", "деплоїти", "перезапускай", "перезапускати",
    "забудь", "забувати", "ігноруй", "ігнорувати", "лізь", "втручайся",
)

#: Заперечення, після яких наказовий спосіб стає забороною.
_PROHIBITION_MARKERS: tuple[str, ...] = (
    "не ", "нехай не", "щоб не", "більше не", "ні ", "не треба ",
    "не потрібно ", "без ",
)

#: Іменникові звороти заборони: «без запуску тестів», «без змін у коді».
#:
#: Дієслова тут немає, тож :data:`_PROHIBITION_VERBS` їх не ловить — а
#: фраза означає рівно те саме, що «не запускай тести».
_PROHIBITION_NOUNS: tuple[str, ...] = (
    "без запуску", "без тестів", "без змін", "без правок", "без видалення",
    "без читання", "без інтернету", "без мережі", "без команд",
    "без комітів", "без деплою", "без встановлення", "без нових файлів",
    "без нових залежностей", "без сторонніх",
)


def _is_prohibition(low: str) -> bool:
    """Чи фраза ЗАБОРОНЯЄ дію, а не просить її виконати.

    Перевіряємо ЛИШЕ наказові дієслова зі списку (інфінітиви на зразок
    «перевірити» не беремо — там заперечення зазвичай означає інше), і лише
    коли заперечення стоїть БЕЗПОСЕРЕДНЬО перед ними («не запускай»,
    «не треба запускати»). Це відсікає хибні спрацювання на «нічого не
    зламай» (там «не зламай» — уже обмеження, а не нова дія).

    Виняток: якщо в реченні є ЯВНЕ прохання («зроби», «виправ», «додай»)
    без заперечення — це звичайне завдання з обмеженням, і класифікувати
    його як заборону не можна.
    """
    if _has_any(low, _PROHIBITION_NOUNS):
        # «без запуску тестів» — те саме, що «не запускай тести».
        if not _has_any(low, _REQUEST_STEMS):
            return True
    for verb in _PROHIBITION_VERBS:
        position = low.find(verb)
        while position != -1:
            before = low[max(0, position - 16):position]
            if any(marker in before for marker in _PROHIBITION_MARKERS):
                # «зроби так, щоб не запускати» — це вимога, а не заборона.
                if not _has_any(low, _REQUEST_STEMS):
                    return True
            position = low.find(verb, position + 1)
    return False


#: Явні прохання: якщо вони є, речення — завдання, а «не …» — умова.
_REQUEST_STEMS: tuple[str, ...] = (
    "зроби", "зробіть", "виправ", "виправте", "додай", "додайте",
    "створи", "створіть", "напиши", "напишіть", "перероби", "поправ",
    "полагодь", "пофіксь", "хочу", "треба щоб", "потрібно щоб",
)


def _forbids_running(constraints: Sequence[str]) -> bool:
    """Чи серед обмежень є заборона запускати команди/тести.

    Потрібно, щоб не ставити взаємовиключних вимог у план: «синтаксис
    перевірено» вимагає запустити ``python_check``, а «не запускати
    команди й перевірки» це забороняє.
    """
    for item in constraints or ():
        text = str(item or "").lower()
        if "не запускати" in text or "не запускати тести" in text:
            return True
        if "не запускати команди" in text:
            return True
    return False


#: Слова, після яких відповідь живе в мережі, а не в проєкті.
#:
#: Дублюємо тут (а не беремо приватні константи :mod:`task_plan`), бо це
#: правило належить саме розумінню наміру: «скільки коштує» — питання,
#: але відповісти на нього файлами проєкту неможливо.
_LIVE_DATA_MARKERS: tuple[str, ...] = (
    "ціна", "ціни", "ціну", "коштує", "коштують", "курс", "курси", "погода",
    "погоду", "новини", "новину", "біткоїн", "bitcoin", "ethereum", "solana",
    "криптовалюта", "капіталізація", "price", "weather", "news",
    "в інтернеті", "в мережі", "погугли", "загугли", "актуальн",
    "остання версія", "скільки кошту",
)

#: Слова, які означають, що питання — про КОД, а не про свіжі дані.
_CODE_WORDS: tuple[str, ...] = (
    "файл", "код", "функці", "клас", "модул", "проєкт", "репозитор",
    "папк", "тест", "помилк", "змінн", ".py", ".js", ".html", ".css",
)


def _needs_live_data(low: str) -> bool:
    """Чи потрібні свіжі дані з мережі (а не вміст проєкту)."""
    if not _has_any(low, _LIVE_DATA_MARKERS):
        return False
    return not _has_any(low, _CODE_WORDS)


#: Питальні слова, після яких людина чекає ФАКТ, а не думку.
#:
#: «Скільки файлів», «яка версія», «чи є тести» — на це не можна відповісти
#: словами: відповідь лежить у проєкті, і її треба прочитати інструментом.
_QUESTION_WORDS: tuple[str, ...] = (
    "скільки", "скількома", "яка", "яке", "які", "який", "котра", "котрий",
    "чи є", "чи є в", "де знаход", "де леж", "де налаштов", "коли",
    "how many", "which", "where is", "is there",
)

#: Слова-предмети проєкту: роблять питання питанням про КОД.
_PROJECT_SUBJECTS: tuple[str, ...] = _CODE_WORDS + (
    "рядк", "функці", "залежност", "версі", "конфіг", "налашт", "теку",
    "директор", "структур", "розмір", "ваг", "скрипт", "сервер", "модул",
    "клас", "метод", "змінн", "імпорт", "бібліотек", "пакет",
)


def _is_project_question(low: str, understanding: Any) -> bool:
    """Чи це питання про факти проєкту (а не розмова).

    Такі питання НЕ можна віддавати моделі без інструментів: вона відповість
    вигадкою. Агент мусить спершу подивитись у файли.

    Захист від хибних спрацювань: питання про свіжі дані з мережі
    («скільки коштує біткоїн») сюди не потрапляє — його обробляє RESEARCH
    раніше, а ``_needs_live_data`` відсіює збіги з ``_CODE_WORDS``.
    """
    if not _has_any(low, _QUESTION_WORDS):
        return False
    if _has_any(low, _PROJECT_SUBJECTS):
        return True
    # Питання з явним шляхом («що в main.py?») — теж про проєкт.
    return bool(getattr(understanding, "paths", None))


def _debug_is_real(low: str, understanding: Any) -> bool:
    """Чи скарга на поломку справжня (а не «не зламай» / «щоб не падало»).

    ``task_plan`` шукає стеми підрядком, тож «нічого іншого не зламай»
    для нього — те саме, що «зламалося». Розрізняємо за запереченням
    перед стемом: якщо ВСІ збіги заперечені, це обмеження, а не скарга.
    """
    if task_plan.DEBUG not in understanding.intents:
        return False
    stems: list[str] = []
    for intent, words in task_plan.VERB_STEMS:
        if intent == task_plan.DEBUG:
            stems = list(words)
            break
    positive = [stem for stem in stems if stem.startswith("не ")]
    if _has_any(low, positive):
        return True
    rest = [stem for stem in stems if not stem.startswith("не ")]
    return _has_effective(low, rest)


def _informal_intent(low: str) -> str:
    """Намір із живих зворотів; ``""`` — якщо не впізнали.

    Перевіряємо ДОВШІ звороти першими: «не бачить» має перекривати
    випадкове «бач», а «не паше» — не ставати «розмовою».

    Ознаки скарги враховуємо ЛИШЕ без заперечення перед ними: «не зламай»
    це обмеження, а не повідомлення про поломку.
    """
    if _has_any(low, _DESTRUCTIVE_STEMS):
        # Незворотна дія. Тип — правка (агент щось робить із проєктом),
        # а ризик виставляє :func:`_risk_for` за тими самими словами.
        return EDIT
    for intent, stems in sorted(_INFORMAL_STEMS,
                                key=lambda item: -max(len(s) for s in item[1])):
        if intent == DEBUG:
            # «не паше», «не бачить» — самі по собі заперечення, тому для
            # DEBUG беремо звичайний підрядок; а от «зламав»/«лагає»
            # перевіряємо на заперечення перед словом.
            positive = [stem for stem in stems if stem.startswith("не ")]
            if _has_any(low, positive):
                return DEBUG
            rest = [stem for stem in stems if not stem.startswith("не ")]
            if _has_effective(low, rest):
                return DEBUG
            continue
        if _has_any(low, stems):
            return intent
    return ""


def classify_message(text: str, *, previous: Sequence[str] | None = None) -> str:
    """Визначити тип повідомлення.

    Порядок перевірок — це порядок пріоритету: «не працює» важливіше за
    «поясни», «продовж» важливіше за нове завдання, а порожня балачка
    ніколи не має запускати інструменти.
    """
    body = (text or "").strip()
    if not body:
        return CONVERSE
    low = normalise_phrase(body)
    # Те саме, що й у ``frame``: розуміння працює з нормалізованим текстом,
    # інакше російське «сделай» не дає наміру ``create``.
    understanding = task_plan.understand(low or body)
    informal = _informal_intent(low)

    # Питання-відповідь на наше уточнення.
    if previous and _answers_question(low):
        return CLARIFY
    # ── ЗАБОРОНА ДІЇ ───────────────────────────────────────────────────────
    # «Не запускай тести» — це НЕ завдання запустити тести. Донедавна ця
    # фраза класифікувалась як TEST (слово «тести» є, заперечення ніхто не
    # читав), і агент робив рівно те, що людина заборонила. Тепер заборона
    # перевіряється ПЕРШОЮ: якщо дія лише в інфінітиві під «не», це
    # обмеження на майбутню роботу, а не нова дія.
    if _is_prohibition(low):
        return REVISE if previous else CONVERSE
    # Звичайна розмова: коротка репліка без дії й без об'єкта.
    if len(low) <= 30 and _has_any(low, _TALK_MARKERS) and not understanding.is_action:
        return CONVERSE
    # Незворотні дії перевіряємо РАНІШЕ за «продовж»: «видали все зайве» —
    # не доповнення до попереднього, а окрема небезпечна дія.
    if _has_any(low, _DESTRUCTIVE_STEMS) and not _has_any(low, _CONTINUE_MARKERS):
        return EDIT
    # «Зроби так, щоб він бачив…» — це доповнення до наявної роботи, а не
    # нова вимога, навіть якщо фраза починається з «зроби».
    if _looks_like_behaviour_change(low) and not _has_any(
            low, ("створи", "новий файл", "з нуля", "напиши файл")):
        # «Зроби щоб воно ПРАЦЮВАЛО» — це вимога виправити, а не переписати.
        if _has_any(low, _WORK_MARKERS):
            return DEBUG
        return EDIT
    # Продовження попереднього завдання.
    if _has_any(low, _CONTINUE_MARKERS):
        return CONTINUE
    # Слабкі ознаки продовження діють лише в розмові, що вже почалась.
    if previous and _has_any(low, _WEAK_CONTINUE_MARKERS) and not _has_any(
            low, ("створи", "новий файл", "з нуля")):
        return CONTINUE
    # Зміна вимог до вже сказаного.
    if previous and _has_any(low, _REVISE_MARKERS):
        return REVISE
    # Живі звороти перекривають словникові: «не паше» — це помилка, навіть
    # якщо формально нічого не знайдено. Скаргу беремо лише тоді, коли
    # вона НЕ заперечена («не зламай» — це обмеження, а не поломка).
    if informal == DEBUG or _debug_is_real(low, understanding):
        return DEBUG
    # Тести.
    if _has_any(low, _TEST_MARKERS) and (
            task_plan.TEST in understanding.intents
            or informal == TEST
            or _has_any(low, ("прожени", "pytest", "unittest"))):
        return TEST
    if task_plan.CREATE in understanding.intents or informal == CREATE:
        return CREATE
    if (task_plan.EDIT in understanding.intents
            or task_plan.UI in understanding.intents
            or task_plan.REFACTOR in understanding.intents
            or informal == EDIT):
        return EDIT
    if task_plan.RUN in understanding.intents:
        return RUN
    if task_plan.DEPLOY in understanding.intents:
        return RUN
    if informal == INSPECT:
        return INSPECT
    # ── Загальне питання про програмування — відповідь словами ─────────────
    # «Поясни, як працює цикл» не стосується файлів проєкту, тож інструменти
    # тут нічого не додадуть. Раніше слово «поясни» вважалось ознакою
    # читання коду (``task_plan.READ``), і агент ішов оглядати проєкт,
    # витрачаючи кроки на порожню роботу. Питання Ж про проєкт («що робить
    # цей файл») містить слова «файл»/«код»/«тест», тому його не чіпаємо.
    if (_has_any(low, _EXPLAIN_MARKERS) and not understanding.paths
            and not _has_any(low, _CODE_WORDS)):
        return EXPLAIN
    # Питання про код — це огляд реального стану, а не балачка.
    if task_plan.READ in understanding.intents or task_plan.SEARCH in understanding.intents:
        return INSPECT
    if task_plan.ANALYZE in understanding.intents:
        return INSPECT
    if informal == RESEARCH or task_plan.WEB in understanding.intents:
        return RESEARCH
    # Свіжі дані з мережі: «скільки коштує біткоїн» — не розмова, навіть
    # якщо task_plan визнав фразу питальною й бездіяльною.
    if _needs_live_data(low):
        return RESEARCH
    # «Поясни, як працює X» без згадки проєкту — відповідь словами.
    if _has_any(low, _EXPLAIN_MARKERS) and not understanding.paths:
        return EXPLAIN
    if understanding.is_action:
        return EDIT
    # ── Питання про ФАКТИ ПРОЄКТУ — це не балачка ─────────────────────────
    #
    # Тут була помилка, через яку агент ВИГАДУВАВ відповіді. Умова нижче
    # робила ``low.rstrip("?!. ")`` і потім питала, чи рядок закінчується
    # на ``?``. Порівняння не могло бути істинним НІКОЛИ: rstrip уже зрізав
    # знак. Через це «Скільки .py файлів у теці?» доходило до
    # ``return CONVERSE``, агент ішов шляхом ``_chat_only`` (без інструментів),
    # і модель вигадувала результат — «Знайдено 1 файл: main.py», хоча
    # насправді їх сотні.
    #
    # Тепер питання, у якому є предмет проєкту (файл, тека, код, проєкт),
    # трактується як INSPECT: відповідь треба ВЗЯТИ інструментом.
    if _is_project_question(low, understanding):
        return INSPECT
    # Звичайне питання («як справи?», «що нового?») — розмова, а не пошук.
    # Це має бути ПЕРЕД загальним EXPLAIN: інакше привітання отримує статус
    # «поясни», і агент починає готувати аналіз на просте «як справи?».
    if _has_any(low, _TALK_MARKERS):
        return CONVERSE
    if body.rstrip().endswith(("?", "!")) and len(low) < 200:
        return EXPLAIN
    # Фраза-обмеження без дієслова («Без сторонніх програм») продовжує те,
    # що вже почали: сама собою вона не завдання, але й не балачка.
    if previous and (extract_constraints(body) or _has_any(low, _REVISE_MARKERS)):
        return CONTINUE
    return CONVERSE


#: Ознаки того, що просять змінити ПОВЕДІНКУ наявного, а не створити нове.
_BEHAVIOUR_MARKERS: tuple[str, ...] = (
    "щоб він", "щоб вона", "щоб воно", "щоб агент", "щоб чат", "щоб модель",
    "не вигадув", "бачив", "бачила", "не забував", "пам'ятав", "розумів",
    "працював", "працювало нормально", "сам визначав", "сам обирав",
    "сам бачив", "сама бачила", "само юзало", "сам викликав",
)

#: Короткі назви, які не можна шукати підрядком (легко зловити зайве).
_BEHAVIOUR_WORDS: tuple[str, ...] = ("ші", "ai", "агент")


def _looks_like_behaviour_change(low: str) -> bool:
    """Чи просять змінити поведінку наявного компонента.

    «Зроби щоб агент бачив файли» — правка агента, а не новий файл.
    Розрізнення важливе: від нього залежить, чи агент шукатиме наявний
    код, чи створюватиме новий модуль поруч.
    """
    if _has_any(low, _BEHAVIOUR_MARKERS):
        return True
    words = re.findall(r"[a-zа-яіїєґ0-9']+", low)
    return any(word in _BEHAVIOUR_WORDS for word in words)


def _answers_question(low: str) -> bool:
    """Чи схоже на відповідь на уточнення («перший», «у папці src», «так»).

    Короткі відповіді («так», «ні», «усі») перевіряємо ЯК ОКРЕМЕ СЛОВО:
    підрядок «ні» є всередині «сторонніх» і «технологій», і без цього
    звичайне обмеження вважалось би відповіддю на питання.
    """
    if len(low) > 120:
        return False
    words = set(re.findall(r"[a-zа-яіїєґ0-9']+", low))
    if words & {"перший", "перша", "другий", "друга", "третій", "усі",
                "всі", "обидва", "обидві", "так", "ні", "ага"}:
        return True
    phrases = ("у папці", "в теці", "у файлі", "у src", "в корені")
    return any(phrase in low for phrase in phrases)


# ─── Обмеження й очікуваний результат ───────────────────────────────────────

#: Обмеження, які люди формулюють побутово. Кожне — пара «ознака → як
#: записати для планувальника».
_CONSTRAINT_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("не зламай", "нічого не зламай", "не ламай", "не чіпай інше",
      "не чіпай інші", "без поломок"), "не ламати наявну поведінку"),
    (("не видаляй", "не стирай", "старі не видаляй", "не видалялись",
      "збережи старі"), "не видаляти наявні дані"),
    (("без сторонніх", "без зовнішніх програм", "без зайвих програм",
      "без нових залежностей", "без бібліотек"), "не додавати зовнішніх залежностей"),
    (("локально", "без інтернету", "офлайн", "offline"), "працювати локально"),
    (("не переписуй весь", "тільки точково", "точково", "мінімальн",
      "лише те що треба"), "мінімальні точкові зміни"),
    (("швидше", "швидко", "без затримок", "щоб не гальмувало"),
     "не сповільнювати роботу"),
    (("українською", "по-українськи", "українська мова"),
     "відповіді українською"),
    (("без коментарів", "не додавай коментарів"), "не додавати коментарів у код"),
    (("збережи стиль", "у тому ж стилі", "як у проєкті"),
     "тримати наявний стиль коду"),
)


def extract_constraints(text: str, *, previous: Sequence[str] | None = None) -> list[str]:
    """Зібрати обмеження з фрази й з попередніх вимог (не губити їх).

    Обмеження — найцінніше, що буває в діалозі: людина сказала «тільки
    щоб старі не видалялись» один раз, і це має діяти до кінця завдання.
    """
    low = normalise_phrase(text)
    found: list[str] = []
    for markers, label in _CONSTRAINT_RULES:
        if _has_any(low, markers) and label not in found:
            found.append(label)
    for markers, label in _NO_GO_MARKERS:
        if _has_any(low, markers) and label not in found:
            found.append(label)
    for earlier in previous or ():
        earlier_low = normalise_phrase(earlier)
        for markers, label in _CONSTRAINT_RULES:
            if _has_any(earlier_low, markers) and label not in found:
                found.append(label)
        for markers, label in _NO_GO_MARKERS:
            if _has_any(earlier_low, markers) and label not in found:
                found.append(label)
    return found


_EXPECT_HINT: tuple[tuple[tuple[str, ...], str], ...] = (
    (("покажи", "подивись", "як виглядає"), "показати результат"),
    (("поясни", "розкажи"), "пояснення словами"),
    (("зроби", "створи", "напиши", "додай"), "готовий робочий код"),
    (("виправ", "полагодь", "щоб працювало"), "виправлена й перевірена робота"),
    (("перевір", "протестуй", "запусти тести"), "звіт про перевірку"),
)


def expected_output(text: str) -> str:
    """Що людина очікує отримати — одним словосполученням."""
    low = normalise_phrase(text)
    for markers, label in _EXPECT_HINT:
        if _has_any(low, markers):
            return label
    return "виконане завдання з коротким поясненням"


# ─── Побудова кадру ─────────────────────────────────────────────────────────

#: Які інструменти доречні для типу наміру (підказка, не обмеження).
_TOOLS_FOR_TYPE: dict[str, tuple[str, ...]] = {
    CREATE: ("list_dir", "read_file", "write_file", "edit_file", "python_check"),
    EDIT: ("read_file", "search_text", "edit_file", "python_check"),
    DEBUG: ("run_command", "read_file", "search_text", "edit_file", "python_check"),
    RUN: ("run_command",),
    TEST: ("run_command", "python_check"),
    INSPECT: ("list_dir", "read_file", "search_text", "project_tree"),
    RESEARCH: ("search_web", "fetch_url", "read_file"),
    EXPLAIN: (),
    CONVERSE: (),
}


def _risk_for(text: str, intent_type: str) -> str:
    low = normalise_phrase(text)
    if _has_any(low, RISKY_REQUESTS) or _is_destructive(low):
        return "high"
    if intent_type in (EDIT, CREATE, RUN, DEBUG):
        return "medium"
    return "low"


def _is_destructive(low: str) -> bool:
    """Чи просить фраза незворотну дію (видалення, очищення)."""
    return _has_any(low, _DESTRUCTIVE_STEMS)


#: Слова, які НЕ є предметом роботи (службові для прохання).
_NOT_A_SUBJECT: frozenset[str] = frozenset({
    "зроби", "зробити", "зробіть", "краще", "добре", "нормально", "швидше",
    "будь", "ласка", "треба", "потрібно", "давай", "мені", "нам", "це",
    "цей", "ця", "щось", "якось", "як", "так", "що", "чи", "то",
})


def _has_subject(low: str) -> bool:
    """Чи названо ПРЕДМЕТ роботи (окрім службових слів)."""
    words = [word for word in re.findall(r"[a-zа-яіїєґ0-9'_-]+", low)
             if len(word) >= 4]
    return any(word not in _NOT_A_SUBJECT for word in words)


def _goal_from(text: str, intent_type: str, understanding: task_plan.Understanding) -> str:
    """Сформулювати мету звичайною мовою (без технічних назв)."""
    label = task_plan.INTENT_LABELS.get(intent_type)
    if not label and intent_type == INSPECT:
        label = "Огляд проєкту"
    if not label and intent_type == RESEARCH:
        label = "Пошук інформації"
    subject = ""
    if understanding.paths:
        subject = ", ".join(understanding.paths[:3])
    elif understanding.quoted:
        subject = understanding.quoted[0][:60]
    if label and subject:
        return f"{label}: {subject}"
    return label or ""


def frame(
    text: str,
    *,
    previous_messages: Sequence[str] | None = None,
    known_files: Sequence[str] | None = None,
    active_path: str = "",
    previous_intent: str = "",
) -> IntentFrame:
    """Побудувати :class:`IntentFrame` для одного повідомлення.

    ``previous_messages`` — попередні репліки користувача в цьому чаті:
    з них беруться обмеження й об'єкт згадки. ``active_path`` — файл,
    відкритий у редакторі: він і є «цей файл» для фраз без шляху.
    ``previous_intent`` — тип попереднього наміру: потрібен, коли репліка
    лише доповнює завдання («і додай…») і сама по собі виглядає як «створи».
    """
    body = (text or "").strip()
    # ── РОЗУМІННЯ ПРАЦЮЄ З НОРМАЛІЗОВАНИМ ТЕКСТОМ ────────────────────────
    # ``task_plan.understand`` і ``classify_message`` шукають УКРАЇНСЬКІ
    # маркери. На «сделай файл app.py» ОРИГІНАЛ давав ``['talk']``, а
    # нормалізований «зроби файл app.py» — ``['create', 'edit']``.
    # Заміряно: через це вся російська фраза вважалась розмовою,
    # ``needs_tools`` ставало False, і агент відповідав словами замість
    # роботи.
    #
    # ``body`` лишається ОРИГІНАЛОМ: він іде в ``IntentFrame.text`` і його
    # бачить модель. Нормалізацію беремо ЛИШЕ для розпізнавання.
    recognised = normalise_phrase(body) or body
    understanding = task_plan.understand(recognised)
    intent_type = classify_message(recognised, previous=previous_messages)
    low = recognised

    files = [path for path in understanding.paths]
    continuation = intent_type in (CONTINUE, REVISE, CLARIFY)
    # Доповнення до завдання («і додай відновлення після перезапуску») не
    # має перетворювати правку на створення нового файлу: працюємо з тим
    # самим завданням, доки людина явно не почне нове.
    if continuation and previous_intent and previous_intent in ACTION_TYPES:
        intent_type = previous_intent
    if active_path and not files and intent_type in (INSPECT, EDIT, DEBUG):
        files.append(str(active_path).replace("\\", "/"))
    features = [item for item in understanding.quoted
                if not item.lower().endswith((".py", ".js", ".ts", ".md", ".txt"))]
    constraints = extract_constraints(body, previous=previous_messages)

    missing: list[str] = []
    actionable = intent_type in ACTION_TYPES
    # «Зроби краще» без об'єкта — це справді незрозуміло. Але для збою
    # («не працює») і для огляду перепитувати НЕ можна: агент має спершу
    # подивитись сам, інакше він просить людину зробити його роботу.
    # «Створи калькулятор» об'єкт називає — питати нема про що, навіть
    # якщо слів мало.
    askable = intent_type in (CREATE, EDIT)
    if askable and not files and not features and not _has_subject(low):
        missing.append("що саме змінити (файл, екран або функцію)")
    # Незворотна дія без названого об'єкта — питаємо ЗАВЖДИ: «видали все
    # зайве» не має виконуватись навмання навіть якщо слів багато.
    if _is_destructive(low) and not files:
        missing.append("що саме видалити або очистити")

    confidence = 0.5
    if actionable:
        confidence += 0.2
    if files or features:
        confidence += 0.15
    if intent_type in (CONVERSE, EXPLAIN):
        confidence = min(1.0, confidence)
    if missing:
        confidence -= 0.25

    secondary: list[str] = []
    for intent in understanding.intents[1:4]:
        label = task_plan.INTENT_LABELS.get(intent)
        if label and label not in secondary:
            secondary.append(label)

    criteria: list[str] = []
    if intent_type in (CREATE, EDIT, DEBUG, TEST, RUN):
        criteria.append("зміни внесено у справжні файли проєкту")
        # «Не запускай команди» й «синтаксис перевірено» — взаємовиключні
        # вимоги. Раніше обидві потрапляли в план, і модель або порушувала
        # заборону, або вічно «не досягала» критерію. Тепер критерій, який
        # заборонено виконувати, замінюється на чесний: перевірити очима.
        if _forbids_running(constraints):
            criteria.append("результат перевірено без запуску команд (на прохання)")
        else:
            criteria.append("синтаксис перевірено")
        if understanding.paths:
            criteria.append("перевірено саме: " + ", ".join(understanding.paths[:3]))
    elif intent_type == INSPECT:
        criteria.append("відповідь спирається на реальний вміст проєкту")
    elif intent_type == RESEARCH:
        criteria.append("дані взяті з мережі, а не з пам'яті моделі")

    known: list[str] = []
    for name in (known_files or ())[:8]:
        if name in body:
            known.append(f"файл згадано в проєкті: {name}")
    if active_path:
        known.append(f"відкритий файл: {active_path}")

    return IntentFrame(
        text=body,
        intent_type=intent_type,
        primary_goal=_goal_from(body, intent_type, understanding),
        secondary_goals=secondary,
        entities=list(understanding.quoted[:6]),
        referenced_files=files,
        referenced_features=features[:6],
        constraints=constraints,
        expected_output=expected_output(body),
        requested_actions=[understanding.primary] if understanding.intents else [],
        required_tools=[name for name in _TOOLS_FOR_TYPE.get(intent_type, ())
                        if name],
        known_context=known,
        missing_information=missing,
        risk_level=_risk_for(body, intent_type),
        confidence=max(0.1, min(1.0, confidence)),
        completion_criteria=criteria,
        language=detect_language(body),
        continuation=continuation,
        actionable=actionable,
    )


def needs_clarification(intent: IntentFrame) -> bool:
    """Чи варто поставити ОДНЕ уточнююче питання перед роботою.

    Правило: питаємо лише коли (а) справді незрозуміло, що робити, або
    (б) дія ризикована й об'єкт не названий. В усіх інших випадках —
    діяти розумно й сказати, що припустили.
    """
    if not intent.actionable:
        return False
    if intent.missing_information and intent.confidence < CLARIFY_THRESHOLD:
        return True
    if intent.is_risky and not intent.referenced_files:
        return True
    return False


def merge_frames(base: IntentFrame, update: IntentFrame) -> IntentFrame:
    """Злити нове повідомлення з попереднім завданням.

    Наступна репліка часто лише ДОДАЄ вимогу («і ще щоб автоматично
    визначав відеокарту»). Тоді мета лишається попередня, а нові
    обмеження, файли й критерії додаються.
    """
    merged = IntentFrame(
        text=(update.text or base.text),
        intent_type=(base.intent_type if update.continuation
                     else (update.intent_type or base.intent_type)),
        primary_goal=(base.primary_goal or update.primary_goal
                      if update.continuation else
                      (update.primary_goal or base.primary_goal)),
        language=update.language or base.language,
        risk_level=max((base.risk_level, update.risk_level),
                       key=lambda item: ("low", "medium", "high", "critical").index(item)),
        confidence=max(base.confidence, update.confidence),
        continuation=update.continuation,
        actionable=base.actionable or update.actionable,
        expected_output=update.expected_output or base.expected_output,
    )
    merged.secondary_goals = _unique([*base.secondary_goals, *update.secondary_goals])
    merged.entities = _unique([*base.entities, *update.entities])
    merged.referenced_files = _unique([*base.referenced_files, *update.referenced_files])
    merged.referenced_features = _unique(
        [*base.referenced_features, *update.referenced_features])
    merged.constraints = _unique([*base.constraints, *update.constraints])
    merged.requested_actions = _unique(
        [*base.requested_actions, *update.requested_actions])
    merged.required_tools = _unique([*base.required_tools, *update.required_tools])
    merged.known_context = _unique([*base.known_context, *update.known_context])
    merged.missing_information = [
        item for item in update.missing_information
        if item not in base.missing_information
    ] if update.continuation else list(update.missing_information)
    merged.completion_criteria = _unique(
        [*base.completion_criteria, *update.completion_criteria])
    return merged


def _unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        clean = str(item or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def frame_prompt(intent: IntentFrame) -> str:
    """Коротка підказка моделі про те, що ми вже зрозуміли.

    Навмисно СТИСЛА й без JSON: локальні моделі плутаються, коли їм
    показують структури замість речень.
    """
    lines: list[str] = []
    if intent.primary_goal:
        lines.append(f"Мета: {intent.primary_goal}.")
    if intent.constraints:
        lines.append("Обмеження: " + "; ".join(intent.constraints) + ".")
    if intent.referenced_files:
        lines.append("Файли: " + ", ".join(intent.referenced_files[:4]) + ".")
    if intent.required_tools:
        lines.append("Доречні інструменти: " + ", ".join(intent.required_tools) + ".")
    if intent.completion_criteria:
        lines.append("Готово, коли: " + "; ".join(intent.completion_criteria) + ".")
    if not lines:
        return ""
    return "\n".join(["Що вже зрозуміло з прохання (не перепитуй це):", *lines])


def parse_answer(text: str, question: str) -> Mapping[str, Any] | None:
    """Найпростіше розв'язання відповіді на уточнення.

    Повертає підказку, яку можна додати до наступного кадру: «обидва»,
    «перший» тощо. ``None`` — якщо відповідь не стосується питання.

    Слова перевіряємо ЯК ОКРЕМЕ СЛОВО: підрядок «да» є в «погода», «так» —
    у «такий», «ні» — у «сторонній». Саме через це відповідь «погода
    гарна» раніше означала «так».
    """
    low = normalise_phrase(text)
    if not low or not question:
        return None
    words = set(re.findall(r"[a-zа-яіїєґ0-9']+", low))
    hints: dict[str, Any] = {}
    if words & {"обидва", "обидві", "усі", "всі", "разом"}:
        hints["selection"] = "all"
    elif words & {"перший", "перша", "перше"}:
        hints["selection"] = "first"
    elif words & {"другий", "друга", "друге"}:
        hints["selection"] = "second"
    elif words & {"так", "ага"}:
        hints["agree"] = True
    elif words & {"ні", "нет"}:
        hints["agree"] = False
    return hints or None
