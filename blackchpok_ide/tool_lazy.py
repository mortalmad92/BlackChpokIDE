"""Лінива маршрутизація інструментів: компактний реєстр замість усіх схем.

Проблема, яку це вирішує. Коли підключено MCP-сервер, пам'ять NEUROMESH і
скіли, кількість інструментів переходить за шістдесят. Кожен — це повна
JSON-схема з описами параметрів: разом близько 20 000 токенів. Локальна
модель із вікном 16 384 не має куди подіти такий запит, і сервер обриває
з'єднання (``WinError 10054``) ще до першого токена відповіді. Користувач
бачить «модель не працює», хоч вона працює.

Що робить цей модуль. Замість «усе або нічого»:

1. **Компактний реєстр.** Моделі показують ОДИН рядок на інструмент:
   назву, коротке призначення й категорію. Параметрів там немає — вони
   займають 90% обсягу схеми.
2. **Повні схеми — на вимогу.** Модель бачить повну схему лише тоді, коли
   справді збирається викликати інструмент (``load_tools``) або коли
   схема вже завантажена в цьому діалозі.
3. **Жодних втрат.** Інструмент, схему якого не завантажено, усе одно
   можна викликати через ``run_tool`` — він приймає назву й аргументи.
   Тобто лінивість не «ховає» можливості, а лише економить місце.
4. **Кеш із правильною інвалідацією.** Схеми кешуються; коли реєстр
   змінюється (MCP перезапустився, пам'ять підключилась), кеш
   перебудовується, а «завантажені» назви, яких більше немає, зникають.

Коли лінивість НЕ вмикається. Якщо повний набір схем спокійно вміщається
в бюджет, він і передається повністю: зайва церемонія з
``load_tools`` коштувала б моделі зайвого кроку без жодної вигоди. Рішення
ухвалюється за РЕАЛЬНИМ розміром, а не за кількістю назв навмання.

Модуль не тягне tkinter, не робить мережевих викликів і не знає нічого про
конкретний виконавець: йому передають готові схеми, а виконує їх агент.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import context_budget

LOG = logging.getLogger("blackchpok.tool_lazy")

__all__ = [
    "CONTROL_FIND",
    "CONTROL_LOAD",
    "CONTROL_RUN",
    "CONTROL_TOOLS",
    "CORE_TOOLS",
    "LazyToolRouter",
    "ToolCard",
    "control_schemas",
    "is_control_tool",
]

# ── Рівні пріоритету ────────────────────────────────────────────────────────
#
# Пріоритет визначає, чия ПОВНА схема лишається в запиті, коли місця
# бракує. Він НЕ визначає доступність: інструмент нижчого рівня однаково
# можна знайти в реєстрі та викликати.

TIER_CORE = 0        # без цього агент не працює зовсім
TIER_PROJECT = 1     # пошук і аналіз проєкту
TIER_SPECIAL = 2     # спеціалізовані можливості (сторінка, зір, застосунок)
TIER_RARE = 3        # рідко вживані
TIER_EXTERNAL = 4    # зовнішні джерела: MCP, пам'ять, скіли, соцмережі

TIER_TITLES: dict[int, str] = {
    TIER_CORE: "ядро",
    TIER_PROJECT: "проєкт",
    TIER_SPECIAL: "спеціальні",
    TIER_RARE: "рідкі",
    TIER_EXTERNAL: "зовнішні",
}

#: Інструменти, без яких агент не виконує основну роботу. Їхні повні схеми
#: передаються завжди — навіть коли лінивість увімкнена. Причина проста:
#: економити один крок на читанні файлу означало б платити зайвим кроком
#: моделі в КОЖНОМУ завданні.
CORE_TOOLS: tuple[str, ...] = (
    "read_file", "write_file", "edit_file", "append_file",
    "list_dir", "search_text", "find_files", "run_command",
    "project_tree", "python_check", "git_status", "git_diff",
)

#: Інструменти керування реєстром. Вони завжди доступні — саме вони й
#: роблять лінивість безпечною, бо дають шлях до БУДЬ-ЯКОГО інструмента.
CONTROL_FIND = "find_tools"
CONTROL_LOAD = "load_tools"
CONTROL_RUN = "run_tool"
CONTROL_TOOLS: tuple[str, ...] = (CONTROL_FIND, CONTROL_LOAD, CONTROL_RUN)

#: Назви цих інструментів не можна передавати в ``run_tool``: інакше модель
#: зробила б нескінченну рекурсію замість роботи.
_RECURSION_GUARD: frozenset[str] = frozenset(CONTROL_TOOLS)


def is_control_tool(name: str) -> bool:
    """Чи це інструмент керування реєстром (``find_tools`` тощо)."""
    return str(name or "").strip() in _RECURSION_GUARD

#: Поріг, після якого повний набір схем вважається завеликим для передачі
#: цілком. Виміряно: одна повна схема — у середньому 350 токенів, тож
#: 60 інструментів дають ≈21 000 токенів, що саме й ламало вікно 16 384.
MAX_EAGER_TOOLS = 48

#: Скільки символів опису інструмента лишаємо в компактному реєстрі.
CARD_DESCRIPTION_LIMIT = 90


@dataclass(frozen=True)
class ToolCard:
    """Один рядок компактного реєстру.

    ``schema_key`` — ідентифікатор, за яким можна отримати ПОВНУ схему. Для
    вбудованих це власне назва, для зовнішніх — повне ім'я з префіксом, яке
    модель передає у ``load_tools``.
    """

    name: str
    purpose: str
    category: str = "files"
    tier: int = TIER_RARE
    schema_key: str = ""

    @property
    def tier_title(self) -> str:
        return TIER_TITLES.get(self.tier, "інші")

    def line(self) -> str:
        """Один рядок для моделі: назва, призначення, категорія."""
        purpose = self.purpose or "дія"
        return f"- {self.name} [{self.category}] — {purpose}"

    def searchable(self) -> str:
        return f"{self.name} {self.purpose} {self.category}".lower()


# ── Схеми інструментів керування реєстром ───────────────────────────────────
#
# Вони навмисно КОРОТКІ: це єдине, що додається до запиту постійно. Кожне
# зайве слово тут коштує токенів у кожному кроці кожного діалогу.

def control_schemas() -> list[dict[str, Any]]:
    """Три маленькі схеми, які роблять реєстр доступним для моделі."""
    return [
        {
            "type": "function",
            "function": {
                "name": CONTROL_FIND,
                "description": (
                    "Знайти інструмент у повному реєстрі IDE за словами. "
                    "Повертає назви й призначення. Виклич це, якщо потрібної "
                    "дії немає серед уже показаних інструментів."),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": ("слова для пошуку: дія, об'єкт або "
                                            "частина назви (напр. «скріншот»)",
                                            ),
                        },
                        "limit": {
                            "type": "integer",
                            "description": "скільки результатів показати (типово 8)",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": CONTROL_LOAD,
                "description": (
                    "Завантажити ПОВНІ схеми інструментів, щоб бачити їхні "
                    "параметри. Після цього інструмент можна викликати "
                    "звичайним способом у наступному кроці."),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": ("точні назви інструментів із "
                                            "компактного реєстру"),
                        },
                    },
                    "required": ["names"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": CONTROL_RUN,
                "description": (
                    "Викликати БУДЬ-ЯКИЙ інструмент реєстру за назвою, навіть "
                    "якщо його повна схема не завантажена. Аргументи — об'єкт "
                    "із параметрами цього інструмента."),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "точна назва інструмента з реєстру",
                        },
                        "arguments": {
                            "type": "object",
                            "description": ("параметри виклику; якщо їх немає — "
                                            "порожній об'єкт"),
                        },
                    },
                    "required": ["name"],
                },
            },
        },
    ]


def _schema_name(schema: Mapping[str, Any]) -> str:
    function = schema.get("function") if isinstance(schema, Mapping) else None
    if isinstance(function, Mapping):
        return str(function.get("name") or "").strip()
    return ""


def _schema_purpose(schema: Mapping[str, Any]) -> str:
    function = schema.get("function") if isinstance(schema, Mapping) else None
    if not isinstance(function, Mapping):
        return ""
    text = str(function.get("description") or "").strip()
    if not text:
        return ""
    # Беремо перше речення: повний опис у реєстрі не потрібен, він є у схемі.
    for stop in (". ", ".\n", "; "):
        cut = text.find(stop)
        if 0 < cut <= CARD_DESCRIPTION_LIMIT:
            text = text[:cut]
            break
    text = " ".join(text.split())
    return text if len(text) <= CARD_DESCRIPTION_LIMIT \
        else text[: CARD_DESCRIPTION_LIMIT - 1] + "…"


def _category_of(name: str, spec_category: str = "") -> str:
    """Категорія для реєстру: зі специфікації, інакше — за префіксом."""
    if spec_category:
        return spec_category
    if name.startswith("mcp__"):
        parts = name.split("__")
        return parts[1] if len(parts) > 2 else "mcp"
    if name.startswith("router:"):
        return "mcp"
    if name.startswith("memory_"):
        return "memory"
    if name in ("list_skills", "read_skill"):
        return "skill"
    return "files"


class LazyToolRouter:
    """Реєстр інструментів, який віддає моделі повні схеми на вимогу.

    Один екземпляр живе в :class:`blackchpok_ide.agent.AgentRunner` і
    переживає кроки циклу. Виклик :meth:`update` перебудовує реєстр із
    АКТУАЛЬНОГО набору схем — саме там відбувається інвалідація кешу.
    """

    def __init__(
        self,
        *,
        priority: Sequence[str] = (),
        max_eager: int = MAX_EAGER_TOOLS,
        emit: Callable[..., None] | None = None,
    ) -> None:
        self._priority: dict[str, int] = {
            str(name): index for index, name in enumerate(priority or ())
        }
        self._max_eager = max(len(CORE_TOOLS) + len(CONTROL_TOOLS),
                              int(max_eager or MAX_EAGER_TOOLS))
        self._emit_callback = emit
        #: Усі схеми, які зараз існують (джерело істини для реєстру).
        self._all: dict[str, dict[str, Any]] = {}
        #: Компактний реєстр у порядку показу.
        self._cards: list[ToolCard] = []
        #: Назви, чиї повні схеми вже показані моделі.
        self._loaded: set[str] = set()
        #: Чи ввімкнено лінивість для ПОТОЧНОГО набору.
        self._lazy = False
        #: Причина рішення — для журналу й для індикатора в інтерфейсі.
        self._reason = ""
        #: Бюджет схем у токенах (0 = не заданий).
        self._budget = 0
        #: Відбиток набору схем: за ним визначаємо, що реєстр змінився.
        self._signature = ""
        #: Лічильники для інтерфейсу (скільки схем реально пішло моделі).
        self.eager_count = 0
        self.total_count = 0
        self.loaded_count = 0

    # ── реєстр ──────────────────────────────────────────────────────────────
    def update(
        self,
        schemas: Iterable[Mapping[str, Any]],
        *,
        budget_tokens: int = 0,
        token_counter: Callable[[Any], int] | None = None,
        specs: Mapping[str, Any] | None = None,
    ) -> bool:
        """Перебудувати реєстр. Повертає ``True``, якщо ввімкнено лінивість.

        ``budget_tokens`` — скільки токенів відведено під схеми. Якщо 0,
        рішення ухвалюється лише за кількістю (:data:`MAX_EAGER_TOOLS`).
        """
        fresh: dict[str, dict[str, Any]] = {}
        for schema in schemas or ():
            if not isinstance(schema, Mapping):
                continue
            name = _schema_name(schema)
            if not name or name in _RECURSION_GUARD:
                continue
            fresh[name] = dict(schema)
        if not fresh:
            self._all = {}
            self._cards = []
            self._loaded.clear()
            self._lazy = False
            self._reason = "інструментів немає"
            self._signature = ""
            self.eager_count = self.total_count = self.loaded_count = 0
            return False

        signature = "\u0000".join(sorted(fresh))
        if signature != self._signature:
            # Реєстр змінився: старі схеми більше не дійсні, а «завантажені»
            # назви, яких уже немає, прибираємо — інакше модель бачила б
            # кнопку, якої не існує.
            gone = self._loaded - set(fresh)
            if gone:
                LOG.info("Інструменти зникли з реєстру: %s",
                         ", ".join(sorted(gone)))
            self._loaded &= set(fresh)
            self._signature = signature
        self._all = fresh
        self._rebuild_cards(specs or {})

        total_tokens = self._cost(list(fresh.values()), token_counter)
        over_count = len(fresh) > self._max_eager
        over_budget = bool(budget_tokens) and total_tokens > int(budget_tokens)
        self._lazy = bool(over_count or over_budget)
        self._budget = int(budget_tokens or 0)
        if self._lazy:
            why = []
            if over_budget:
                why.append(f"схеми {total_tokens} токенів > бюджету "
                           f"{int(budget_tokens)}")
            if over_count:
                why.append(f"інструментів {len(fresh)} > {self._max_eager}")
            self._reason = "лінивість: " + "; ".join(why)
        else:
            self._reason = (f"усе вміщається ({len(fresh)} інструментів, "
                            f"{total_tokens} токенів)")
        self._recount()
        LOG.info("Реєстр інструментів: %s — %s", self._reason,
                 "лінивий" if self._lazy else "повний")
        return self._lazy

    def _rebuild_cards(self, specs: Mapping[str, Any]) -> None:
        """Побудувати компактні картки з поточних схем."""
        cards: list[ToolCard] = []
        for name, schema in self._all.items():
            spec_category = ""
            spec = specs.get(name) if specs else None
            if spec is not None:
                spec_category = str(getattr(spec, "category", "") or "")
            cards.append(ToolCard(
                name=name,
                purpose=_schema_purpose(schema),
                category=_category_of(name, spec_category),
                tier=self._tier_of(name),
                schema_key=name,
            ))
        cards.sort(key=lambda card: (card.tier, card.name))
        self._cards = cards

    def _tier_of(self, name: str) -> int:
        """Рівень пріоритету інструмента (менший — важливіший)."""
        if name in CORE_TOOLS:
            return TIER_CORE
        if name.startswith(("mcp__", "router:")) or name.startswith("memory_"):
            return TIER_EXTERNAL
        # Скіли й соцмережі — ЗОВНІШНІ, і перевірка мусить стояти ДО
        # ``_priority``. Інакше назви, які є і в SCHEMA_PRIORITY, і тут,
        # діставали рівень «проєкт», а ``eager_schemas`` додає лише
        # TIER_EXTERNAL — тобто скіли тихо зникали зі схем при лінивості
        # (``test_features``: «агент бачить інструменти скілів»).
        if name in ("list_skills", "read_skill", "publish_social"):
            return TIER_EXTERNAL
        if name in self._priority:
            # Порядок із SCHEMA_PRIORITY: перші 40% — «проєкт».
            position = self._priority[name]
            scale = max(1, len(self._priority))
            if position < scale * 0.45:
                return TIER_PROJECT
            if position < scale * 0.8:
                return TIER_SPECIAL
            return TIER_RARE
        return TIER_RARE

    # ── вибір схем ──────────────────────────────────────────────────────────
    @property
    def lazy(self) -> bool:
        """Чи ввімкнено лінивість для поточного набору."""
        return self._lazy

    @property
    def reason(self) -> str:
        return self._reason

    def eager_schemas(self) -> list[dict[str, Any]]:
        """Схеми, які треба передати моделі ЦЬОГО разу.

        Повний режим — усе. Лінивий — у такому порядку:

        1. **ядро** (:data:`CORE_TOOLS`) — без нього агент не працює;
        2. **зовнішні** інструменти (MCP, пам'ять, скіли) — у них назви на
           кшталт ``mcp__demo__echo``, які модель фізично не може вгадати;
           ховати їх означало б «MCP підключено, але недосяжне»;
        3. **завантажені на вимогу** — те, що модель попросила сама;
        4. **інструменти керування реєстром** — вони й дають шлях до решти.

        Спеціалізовані й рідкі вбудовані інструменти лишаються в
        компактному реєстрі: їхні назви зрозумілі з опису, і модель дістане
        повну схему через ``load_tools``, коли вони справді знадобляться.
        """
        if not self._all:
            return []
        if not self._lazy:
            return [self._all[card.name] for card in self._cards]

        mandatory = [name for name in self._all
                     if name in CORE_TOOLS or name in self._loaded]
        external = [card.name for card in self._cards
                    if card.tier == TIER_EXTERNAL and card.name not in mandatory]
        # Зовнішні додаємо, доки вистачає бюджету. Обмеження навмисно м'яке:
        # недоступний MCP-інструмент дорожчий за кілька сотень токенів.
        selected = list(mandatory)
        remaining = self._budget
        if remaining > 0:
            for name in mandatory:
                remaining -= self._cost([self._all[name]], None)
            for name in external:
                cost = self._cost([self._all[name]], None)
                if remaining - cost < 0:
                    break
                selected.append(name)
                remaining -= cost
        else:
            selected.extend(external)

        ordered = sorted(
            set(selected),
            key=lambda name: (
                0 if name in CORE_TOOLS else
                1 if name in self._loaded else
                2 if self._tier_of(name) == TIER_EXTERNAL else 3,
                self._tier_of(name), name))
        schemas = [self._all[name] for name in ordered if name in self._all]
        schemas.extend(control_schemas())
        return schemas

    def all_schemas(self) -> list[dict[str, Any]]:
        """Повний набір схем — для реєстру специфікацій і для перевірки."""
        return [self._all[card.name] for card in self._cards]

    def schema_for(self, name: str) -> dict[str, Any] | None:
        """Повна схема за назвою (``None``, якщо такого інструмента немає)."""
        schema = self._all.get(str(name or ""))
        return dict(schema) if schema else None

    def knows(self, name: str) -> bool:
        return str(name or "") in self._all

    # ── дії моделі ──────────────────────────────────────────────────────────
    def find(self, query: str, *, limit: int = 8) -> list[ToolCard]:
        """Знайти інструменти за словами запиту (найрелевантніші першими).

        Спершу — збіг у назві (це найточніше), потім у призначенні, далі в
        категорії. Порожній запит повертає найважливіші інструменти.
        """
        words = [part for part in re.split(r"[^\w\u0400-\u04FF]+",
                                           str(query or "").lower()) if part]
        scored: list[tuple[int, int, str, ToolCard]] = []
        for card in self._cards:
            haystack = card.searchable()
            if not words:
                scored.append((card.tier, 0, card.name, card))
                continue
            low_name = card.name.lower()
            hits = sum(1 for word in words if word in haystack)
            if not hits:
                continue
            # Точний збіг у назві — найсильніший сигнал.
            bonus = 0
            if any(word in low_name for word in words):
                bonus = 2
            if str(query or "").strip().lower() in low_name:
                bonus = 4
            scored.append((card.tier - bonus, -hits, card.name, card))
        scored.sort()
        return [item[3] for item in scored[: max(1, int(limit or 8))]]

    def activate(self, names: Iterable[str]) -> tuple[list[str], list[str]]:
        """Позначити схеми як завантажені.

        Повертає ``(завантажено, невідомі)``. Невідомі назви не мовчать:
        модель має дізнатися, що вона вигадала ім'я, а не «все гаразд».
        """
        loaded: list[str] = []
        unknown: list[str] = []
        for raw in names or ():
            name = str(raw or "").strip()
            if not name:
                continue
            if name in _RECURSION_GUARD:
                unknown.append(name)
                continue
            if name not in self._all:
                unknown.append(name)
                continue
            if name not in self._loaded:
                self._loaded.add(name)
                loaded.append(name)
        if loaded:
            self._recount()
            LOG.info("Схеми інструментів завантажено на вимогу: %s",
                     ", ".join(loaded))
        return loaded, unknown

    def is_control(self, name: str) -> bool:
        return str(name or "") in _RECURSION_GUARD

    # ── компактний реєстр для промпту ───────────────────────────────────────
    def catalog_text(self, *, include_external: bool = True) -> str:
        """Текст компактного реєстру — його бачить модель у кожному запиті.

        Групуємо за рівнем пріоритету: моделі важливо спершу побачити те, що
        знадобиться найчастіше, а не алфавітний список із вісімдесяти назв.
        """
        if not self._cards:
            return ""
        lines = ["Реєстр інструментів (повні схеми — на вимогу):"]
        grouped: dict[int, list[ToolCard]] = {}
        for card in self._cards:
            if not include_external and card.tier >= TIER_EXTERNAL:
                continue
            grouped.setdefault(card.tier, []).append(card)
        for tier in sorted(grouped):
            title = TIER_TITLES.get(tier, "інші")
            lines.append(f"{title}:")
            lines.extend(f"  {card.line()}" for card in grouped[tier])
        lines.append(
            f"Усього інструментів: {len(self._cards)}. Щоб побачити параметри — "
            f"виклич {CONTROL_LOAD} із назвами; щоб виконати без завантаження — "
            f"{CONTROL_RUN}; щоб знайти потрібний — {CONTROL_FIND}.")
        return "\n".join(lines)

    def compact_text(self) -> str:
        """Найкоротший реєстр: назви того, чого НЕМАЄ серед показаних схем.

        Повний ``catalog_text`` (з описами) — це ≈2000 токенів у КОЖНОМУ
        кроці. Для інструментів, чиї схеми модель уже бачить, ці описи
        дублюють саму схему; для решти достатньо назви, бо призначення
        знаходиться через ``find_tools`` (він шукає і за описом).

        Замір на локальній моделі: повний реєстр 1993 ток. → цей 194 ток.
        Економія йде в історію розмови, а не «в нікуди».
        """
        if not self._cards:
            return ""
        visible = {_schema_name(schema) for schema in self.eager_schemas()}
        hidden = [card for card in self._cards if card.name not in visible]
        if not hidden:
            return ""
        lines = ["Інші інструменти (повна схема — через "
                 f"{CONTROL_LOAD}, виконати за назвою — {CONTROL_RUN}):"]
        for tier in sorted({card.tier for card in hidden}):
            names = [card.name for card in hidden if card.tier == tier]
            lines.append(f"{TIER_TITLES.get(tier, 'інші')}: " + ", ".join(names))
        lines.append(f"Усього інструментів: {len(self._cards)}; пошук за словами — "
                     f"{CONTROL_FIND}.")
        return "\n".join(lines)

    # ── стан для інтерфейсу ─────────────────────────────────────────────────
    def stats(self) -> dict[str, Any]:
        """Реальні показники реєстру (без декоративних чисел)."""
        return {
            "total": self.total_count,
            "eager": self.eager_count,
            "loaded": self.loaded_count,
            "lazy": bool(self._lazy),
            "reason": self._reason,
        }

    def indicator_text(self) -> str:
        """Один рядок для індикатора контексту в інтерфейсі."""
        if not self.total_count:
            return "інструментів немає"
        if not self._lazy:
            return f"інструментів {self.total_count} (усі схеми)"
        return (f"інструментів {self.total_count} · схем у запиті "
                f"{self.eager_count} · завантажено на вимогу "
                f"{self.loaded_count}")

    # ── внутрішнє ───────────────────────────────────────────────────────────
    def _recount(self) -> None:
        self.total_count = len(self._all)
        self.loaded_count = len(self._loaded)
        self.eager_count = len(self.eager_schemas())

    @staticmethod
    def _cost(schemas: Iterable[Mapping[str, Any]],
              counter: Callable[[Any], int] | None) -> int:
        """Оцінити вартість схем у токенах."""
        schemas = list(schemas)
        if counter is not None:
            try:
                total = 0
                for schema in schemas:
                    total += int(counter(json.dumps(schema, ensure_ascii=False)))
                if total > 0:
                    return total
            except Exception:  # noqa: BLE001 - оцінка не має ламати реєстр
                LOG.debug("Точний підрахунок схем не вдався", exc_info=True)
        # Єдина евристика проєкту (``context_budget``) замість власної
        # «len/3.5»: інакше та сама схема рахувалась по-різному в реєстрі,
        # в агенті й у смузі статистики.
        total = 0
        for schema in schemas:
            try:
                total += context_budget.estimate_tokens(
                    json.dumps(schema, ensure_ascii=False))
            except (TypeError, ValueError):
                total += 350
        return total

    def invalidate(self, *, reason: str = "") -> None:
        """Скинути кеш схем: наступний :meth:`update` перебудує все.

        Викликається після зміни моделі, перезапуску MCP або зміни
        конфігурації агента — тобто коли старі схеми можуть бути хибними.
        """
        if reason:
            LOG.info("Кеш реєстру інструментів скинуто: %s", reason)
        self._signature = ""
        self._all = {}
        self._cards = []
        self._loaded.clear()
        self._lazy = False
        self._reason = ""
        self.eager_count = self.total_count = self.loaded_count = 0
