"""Контракт інструментів: що інструмент робить, чим ризикує й що приймає.

Навіщо окремий модуль, а не «схема в списку»:

* **модель бачить лише частину** — ``TOOL_SCHEMAS`` у :mod:`agent_tools`
  містить JSON-schema, але не містить категорії, рівня ризику, типових
  помилок і політики повторів. Оркестратору потрібні саме вони;
* **валідація аргументів** мусить бути однакова для всіх викликів — і для
  тих, що прийшли з нативною функцією, і для тих, що модель написала
  текстом у ``content``;
* **описи параметрів** мають відповідати на питання «що передавати, звідки
  брати значення, у якому форматі» — від цього напряму залежить, чи
  модель правильно заповнить аргументи.

Модуль чистий: без tkinter, без мережі, без диска. Усе тестується
окремо від моделі й від вікна.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "CATEGORIES",
    "RISK_EXTERNAL",
    "RISK_LOCAL",
    "RISK_READ_ONLY",
    "RISK_UNDOING",
    "ArgIssue",
    "ToolSpec",
    "arg_issues",
    "catalog_lines",
    "describe_tool",
    "format_issues",
    "risk_of",
    "spec_for",
    "specs_for_schemas",
    "unknown_arguments",
]

# ── Рівні ризику ────────────────────────────────────────────────────────────
#
# Порядок важливий: чим більший індекс, тим небезпечніша дія. Оркестратор
# бере ризик із цього поля, а права — з :mod:`permissions`. Розділяємо
# навмисно: permissions відповідає «кому можна», ризик — «що буде, якщо
# помилитись».

RISK_READ_ONLY = "read_only"     # нічого не змінює ніде
RISK_LOCAL = "local"             # змінює файли робочої теки
RISK_EXTERNAL = "external"       # виходить у мережу або в іншу систему
RISK_UNDOING = "undoing"         # незворотна дія (видалення, деплой)

RISK_ORDER: tuple[str, ...] = (
    RISK_READ_ONLY, RISK_LOCAL, RISK_EXTERNAL, RISK_UNDOING,
)

#: Категорії — для групування в каталозі й у підсказках моделі.
CATEGORIES: tuple[str, ...] = (
    "files",      # читання й запис файлів
    "search",     # пошук по проєкту
    "exec",       # команди й перевірки
    "web",        # інтернет і сторінка
    "app",        # запуск застосунку проєкту
    "memory",     # довготривала пам'ять NEUROMESH
    "skill",      # скіли агента
    "mcp",        # зовнішні MCP-сервери
    "social",     # публікація в соцмережі
)

#: Скільки разів повторювати невдалий виклик за замовчуванням.
#:
#: Один повтор — бо перша помилка часто тимчасова (файл ще пишеться,
#: мережа блимнула). Більше не робимо: локальна модель застрягає, якщо
#: отримує той самий результат багато разів.
DEFAULT_RETRIES = 1

#: Скільки секунд чекати на інструмент, якщо він сам не сказав.
DEFAULT_TIMEOUT = 120.0


@dataclass(frozen=True)
class ToolSpec:
    """Опис одного інструмента так, як його бачить оркестратор.

    ``name`` і ``parameters`` мусять збігатися зі схемою, яку отримує
    модель: інакше валідатор перевірятиме не те, що надіслано.
    """

    name: str
    purpose: str
    category: str = "files"
    risk: str = RISK_READ_ONLY
    parameters: Mapping[str, Any] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    side_effects: str = ""
    failure_modes: tuple[str, ...] = ()
    timeout: float = DEFAULT_TIMEOUT
    retries: int = DEFAULT_RETRIES
    #: Чи можна виконувати паралельно з іншими незалежними викликами.
    parallel_safe: bool = True
    #: Приклад аргументів — його бачить модель у підсказці каталогу.
    example: Mapping[str, Any] = field(default_factory=dict)
    #: Що інструмент повертає: тип і коротке пояснення.
    #:
    #: Потрібно оркестратору, щоб знати, чи можна вважати результат
    #: порожнім («файл прочитано, але він пустий» ≠ «інструмент зламався»),
    #: і щоб traces описували спостереження, а не лише виклик.
    output: str = "text"
    output_hint: str = ""

    @property
    def summary(self) -> str:
        """Один рядок для каталогу: назва, намір, ризик."""
        return f"{self.name} — {self.purpose}"

    def output_schema(self) -> dict[str, Any]:
        """Схема результату (для документації й для майбутніх строгих клієнтів).

        Навмисно проста: інструменти повертають текст, а структурованість
        досягається форматуванням (списки, шляхи, коди виходу). Вигадувати
        JSON-схеми там, де реалізація віддає рядок, означало б обіцяти
        те, чого немає.
        """
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean", "description": "чи виконано без помилки"},
                "output": {"type": "string",
                           "description": self.output_hint or "текстовий результат"},
            },
            "required": ["ok", "output"],
        }
        return schema


# ─── Описи параметрів ───────────────────────────────────────────────────────
#
# Ключ — ім'я інструмента, значення — категорія, намір, ризик, побічні дії
# й типові помилки. Параметри беремо зі СПРАВЖНІХ схем у agent_tools,
# щоб не тримати дві копії правди: тут лише те, чого в схемах немає.

_NOTES: dict[str, dict[str, Any]] = {
    "read_file": {
        "purpose": "прочитати файл із номерами рядків",
        "category": "files", "risk": RISK_READ_ONLY,
        "side_effects": "немає",
        "failure_modes": (
            "файл не знайдено → перевір шлях через list_dir або find_files",
            "шлях поза робочою текою → візьми шлях відносно проєкту",
        ),
        "example": {"path": "blackchpok_ide/agent.py"},
    },
    "write_file": {
        "purpose": "створити файл або повністю його перезаписати",
        "category": "files", "risk": RISK_LOCAL, "parallel_safe": False,
        "side_effects": "попередня версія зберігається як .bak",
        "failure_modes": (
            "забув content → пиши повний вміст файлу, а не фрагмент",
            "перезапис наявного файлу без потреби → для правки є edit_file",
        ),
        "example": {"path": "calc.py", "content": "def add(a, b):\n    return a + b\n"},
    },
    "edit_file": {
        "purpose": "замінити точний фрагмент у наявному файлі",
        "category": "files", "risk": RISK_LOCAL, "parallel_safe": False,
        "side_effects": "файл змінюється, стара версія лишається в .bak",
        "failure_modes": (
            "old_string не унікальний → додай контексту навколо",
            "old_string не знайдено → спершу прочитай файл і скопіюй точно",
        ),
        "example": {"path": "calc.py", "old_string": "return a - b",
                    "new_string": "return a + b"},
    },
    "append_file": {
        "purpose": "дописати текст у кінець файлу, не затираючи наявне",
        "category": "files", "risk": RISK_LOCAL, "parallel_safe": False,
        "side_effects": "файл стає довшим; наявний вміст лишається",
        "failure_modes": ("використовувати замість write_file для нового файлу",),
        "example": {"path": "notes.txt", "content": "третій рядок\n"},
    },
    "list_dir": {
        "purpose": "показати вміст папки робочої теки",
        "category": "files", "risk": RISK_READ_ONLY,
        "side_effects": "немає",
        "failure_modes": ("папки немає → перевір шлях у проекті",),
        "example": {"path": "."},
    },
    "search_text": {
        "purpose": "знайти текст у коді проєкту",
        "category": "search", "risk": RISK_READ_ONLY,
        "side_effects": "немає",
        "failure_modes": ("занадто загальний запит → уточни рядок або glob",),
        "example": {"query": "def call_tool", "glob": "*.py"},
    },
    "find_files": {
        "purpose": "знайти файли за glob-шаблоном",
        "category": "search", "risk": RISK_READ_ONLY,
        "side_effects": "немає",
        "failure_modes": ("шаблон без ** → пошук лише в корені",),
        "example": {"pattern": "**/*.py"},
    },
    "run_command": {
        "purpose": "виконати команду в терміналі",
        "category": "exec", "risk": RISK_EXTERNAL, "parallel_safe": False,
        "side_effects": "команда може змінити файли, процеси й стан системи",
        "failure_modes": (
            "інтерактивна команда зависає → додай прапорці без питань",
            "код повернення не 0 → покажи користувачу справжню причину",
        ),
        "timeout": 300.0, "retries": 0,
        "example": {"command": "python -m pytest -q"},
    },
    "git_status": {
        "purpose": "стан репозиторію",
        "category": "exec", "risk": RISK_READ_ONLY,
        "side_effects": "немає",
        "failure_modes": ("не git-репозиторій → скажи це прямо",),
        "example": {},
    },
    "git_diff": {
        "purpose": "різниця незакомічених змін",
        "category": "exec", "risk": RISK_READ_ONLY,
        "side_effects": "немає",
        "failure_modes": ("змін немає → порожній diff, це нормально",),
        "example": {},
    },
    "project_tree": {
        "purpose": "дерево проєкту",
        "category": "files", "risk": RISK_READ_ONLY,
        "side_effects": "немає",
        "failure_modes": ("великий проєкт → звузь шлях",),
        "example": {},
    },
    "python_check": {
        "purpose": "перевірити синтаксис Python-файлу",
        "category": "exec", "risk": RISK_READ_ONLY,
        "side_effects": "немає",
        "failure_modes": ("файл не .py → перевірка не має сенсу",),
        "example": {"path": "calc.py"},
    },
    "search_web": {
        "purpose": "пошук в інтернеті: ціни, новини, версії, документація",
        "category": "web", "risk": RISK_EXTERNAL,
        "side_effects": "мережевий запит",
        "failure_modes": (
            "немає мережі → скажи прямо, не вигадуй цифри",
            "занадто широкий запит → додай уточнення",
        ),
        "timeout": 60.0,
        "example": {"query": "python 3.14 what's new"},
    },
    "fetch_url": {
        "purpose": "завантажити й прочитати сторінку за адресою",
        "category": "web", "risk": RISK_EXTERNAL,
        "side_effects": "мережевий запит",
        "failure_modes": ("404 або таймаут → спробуй інше джерело",),
        "timeout": 60.0,
        "example": {"url": "https://docs.python.org/3/"},
    },
    "web_open": {
        "purpose": "показати сторінку КОРИСТУВАЧУ у вбудованому браузері",
        "category": "web", "risk": RISK_READ_ONLY, "parallel_safe": False,
        "side_effects": "відкриває панель «Сайт» і завантажує сторінку",
        "failure_modes": (
            "вікно IDE не підключене → користуйся fetch_url",
            "адреса недоступна → перевір її через fetch_url",
        ),
        "timeout": 30.0, "retries": 0,
        "example": {"url": "https://www.google.com.ua/search?q=fastapi"},
    },
    "web_api": {
        "purpose": "HTTP-запит до API (перевірити ендпоінт)",
        "category": "web", "risk": RISK_EXTERNAL, "parallel_safe": False,
        "side_effects": "запит може змінити стан на сервері (POST/PUT/DELETE)",
        "failure_modes": ("сервер не запущений → перевір адресу й порт",),
        "timeout": 60.0, "retries": 0,
        "example": {"url": "http://127.0.0.1:8000/api/health"},
    },
    "internet_status": {
        "purpose": "перевірити, чи є доступ до інтернету",
        "category": "web", "risk": RISK_EXTERNAL,
        "side_effects": "мережевий запит",
        "failure_modes": ("мережа за проксі → згадай це користувачу",),
        "timeout": 30.0,
        "example": {},
    },
    "list_skills": {
        "purpose": "перелік скілів агента",
        "category": "skill", "risk": RISK_READ_ONLY,
        "side_effects": "немає", "failure_modes": (),
        "example": {},
    },
    "read_skill": {
        "purpose": "прочитати інструкцію скіла",
        "category": "skill", "risk": RISK_READ_ONLY,
        "side_effects": "немає",
        "failure_modes": ("скіла немає → спершу list_skills",),
        "example": {"name": "tests"},
    },
}

#: Групи інструментів, які поводяться однаково — щоб не писати по запису
#: на кожен із тридцяти.
_GROUPS: tuple[tuple[tuple[str, ...], dict[str, Any]], ...] = (
    (("app_start", "app_stop", "app_restart", "app_click", "app_type", "app_key"),
     {"category": "app", "risk": RISK_EXTERNAL, "parallel_safe": False,
      "side_effects": "змінює стан запущеного застосунку",
      "failure_modes": ("застосунок не запущено → спершу app_start",)}),
    (("app_status", "app_screenshot", "project_screenshot", "window_screenshot",
      "app_windows", "app_logs"),
     {"category": "app", "risk": RISK_READ_ONLY,
      "side_effects": "запущений застосунок має існувати",
      "failure_modes": ("вікно не знайдено → app_windows покаже список",)}),
    (("web_url", "web_console", "web_inspect", "web_screenshot", "web_audit",
      "web_responsive"),
     {"category": "web", "risk": RISK_READ_ONLY,
      "side_effects": "сторінка має бути відкрита у вбудованому браузері",
      "failure_modes": ("сторінка не завантажена → скажи про це",)}),
    (("web_click", "web_type"),
     {"category": "web", "risk": RISK_EXTERNAL, "parallel_safe": False,
      "side_effects": "взаємодія зі сторінкою може змінити її стан",
      "failure_modes": ("елемент не знайдено → web_inspect покаже DOM",)}),
)


def _purpose_from_schema(schema: Mapping[str, Any]) -> str:
    """Взяти намір із опису схеми, якщо специфічного опису немає."""
    function = schema.get("function") if isinstance(schema, Mapping) else None
    if isinstance(function, Mapping):
        return str(function.get("description") or "").strip()
    return ""


def _group_note(name: str) -> dict[str, Any]:
    for names, note in _GROUPS:
        if name in names:
            return note
    return {}


def spec_for(schema: Mapping[str, Any]) -> ToolSpec:
    """Побудувати :class:`ToolSpec` зі СПРАВЖНЬОЇ схеми інструмента.

    Схема — джерело істини про параметри. ``_NOTES`` лише доповнює її тим,
    чого в JSON-schema немає: категорією, ризиком і типовими помилками.
    """
    function = schema.get("function") if isinstance(schema, Mapping) else None
    if not isinstance(function, Mapping):
        return ToolSpec(name="", purpose="")
    name = str(function.get("name") or "")
    parameters = function.get("parameters")
    if not isinstance(parameters, Mapping):
        parameters = {}
    properties = parameters.get("properties")
    if not isinstance(properties, Mapping):
        properties = {}
    required = parameters.get("required")
    required_tuple = tuple(str(item) for item in required) if isinstance(
        required, (list, tuple)) else ()

    note = dict(_group_note(name))
    note.update(_NOTES.get(name, {}))
    purpose = str(note.get("purpose") or "").strip() or _purpose_from_schema(schema)
    if not purpose:
        # Резервний варіант — «MCP-інструмент»: краще описати чесно, ніж
        # показати порожній рядок у каталозі.
        purpose = "зовнішній інструмент" if name.startswith(("mcp__", "router:")) \
            else "дія"

    risk = str(note.get("risk") or RISK_READ_ONLY)
    if risk not in RISK_ORDER:
        risk = RISK_READ_ONLY
    category = str(note.get("category") or ("mcp" if name.startswith(("mcp__", "router:"))
                                            else "files"))
    failures = note.get("failure_modes") or ()
    return ToolSpec(
        name=name,
        purpose=purpose,
        category=category,
        risk=risk,
        parameters=properties,
        required=required_tuple,
        side_effects=str(note.get("side_effects") or ""),
        failure_modes=tuple(str(item) for item in failures),
        timeout=float(note.get("timeout") or DEFAULT_TIMEOUT),
        retries=int(note.get("retries", DEFAULT_RETRIES)),
        parallel_safe=bool(note.get("parallel_safe", True)),
        example=dict(note.get("example") or {}),
        output=str(note.get("output") or _default_output(name, risk)),
        output_hint=str(note.get("output_hint") or _default_output_hint(name)),
    )


#: Інструменти, які повертають список шляхів (а не довільний текст).
_LIST_TOOLS: frozenset[str] = frozenset({
    "list_dir", "find_files", "project_tree",
})

#: Інструменти, які повертають знімок (файл PNG + опис).
#:
#: Нові візуальні інструменти теж дають PNG: без них каталог вважав їх
#: текстовими, і оркестратор не знав, що результат — зображення (а модель
#: мала б отримати його через ``image_url``).
_IMAGE_TOOLS: frozenset[str] = frozenset({
    "app_screenshot", "project_screenshot", "window_screenshot", "web_screenshot",
    "capture_screen", "capture_region", "capture_window", "capture_display",
    "capture_live_preview", "capture_browser_page",
    "crop_screenshot", "inspect_screenshot_regions",
    "analyze_visual_difference", "compare_screenshots",
})


def _default_output(name: str, risk: str) -> str:
    """Тип результату за назвою інструмента (text | list | image | code)."""
    if name in _LIST_TOOLS:
        return "list"
    if name in _IMAGE_TOOLS:
        return "image"
    if name == "python_check":
        return "text"
    del risk
    return "text"


def _default_output_hint(name: str) -> str:
    """Що саме повертає інструмент — одним реченням (для документації)."""
    hints = {
        "read_file": "вміст файлу з номерами рядків або повідомлення про помилку",
        "list_dir": "перелік записів теки з розмірами (по рядку на запис)",
        "search_text": "рядки «файл:рядок:текст», по одному збігу на рядок",
        "find_files": "шляхи знайдених файлів, по одному на рядок",
        "run_command": "вивід команди й код завершення",
        "python_check": "«OK» або текст синтаксичної помилки з номером рядка",
        "git_status": "короткий статус репозиторію",
        "git_diff": "unified diff незакомічених змін",
        "search_web": "результати пошуку з посиланнями",
        "fetch_url": "текст сторінки без розмітки",
        "write_file": "підтвердження запису й шлях файлу",
        "edit_file": "підтвердження заміни й кількість замінених фрагментів",
        "append_file": "підтвердження допису й новий розмір файлу",
        "app_screenshot": "шлях до PNG і короткий опис вікна",
        "project_screenshot": "шлях до PNG живого вікна проєкту",
        "window_screenshot": "шлях до PNG вибраного вікна",
        "web_screenshot": "шлях до PNG сторінки у вбудованому браузері",
        "list_skills": "перелік скілів: назва й опис",
        "read_skill": "повна інструкція скіла",
    }
    return hints.get(name, "текстовий результат виконання")


def specs_for_schemas(schemas: Iterable[Mapping[str, Any]]) -> dict[str, ToolSpec]:
    """Усі специфікації для набору схем — саме тих, які бачить модель."""
    result: dict[str, ToolSpec] = {}
    for schema in schemas or ():
        spec = spec_for(schema)
        if spec.name:
            result[spec.name] = spec
    return result


def risk_of(name: str, specs: Mapping[str, ToolSpec] | None = None) -> str:
    """Рівень ризику інструмента; невідомий вважаємо локальним.

    Невідомий інструмент — це MCP-дія, про яку ми нічого не знаємо. Безпечніше
    вважати її такою, що змінює стан, ніж дозволити «прочитати» і змінити.
    """
    if specs and name in specs:
        return specs[name].risk
    return RISK_LOCAL


# ─── Валідація аргументів ───────────────────────────────────────────────────

#: Відповідність «тип у схемі → python-тип».
_TYPES: dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


@dataclass(frozen=True)
class ArgIssue:
    """Одна проблема в аргументах виклику."""

    field_name: str
    problem: str

    def __str__(self) -> str:
        return f"{self.field_name}: {self.problem}"


def _matches_type(value: Any, expected: str) -> bool:
    """Чи відповідає значення типу зі схеми (``bool`` не є ``integer``)."""
    python_type = _TYPES.get(expected)
    if python_type is None:
        return True
    if expected in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, python_type)


def arg_issues(spec: ToolSpec, arguments: Mapping[str, Any] | None) -> list[ArgIssue]:
    """Перевірити аргументи за схемою інструмента.

    Перевіряємо рівно те, що заважає ВИКОНАТИ виклик: типи, обов'язкові
    поля, ``enum``, межі чисел і елементи масивів. Зайві поля тут не
    вважаються помилкою — їх прибирає оркестратор і каже про це моделі:
    інакше один зайвий ключ (``file_path`` замість ``path``) відкидав би
    цілком робочий виклик.
    """
    data = dict(arguments or {})
    issues: list[ArgIssue] = []
    for name in spec.required:
        if name not in data or data[name] in (None, "", [], {}):
            issues.append(ArgIssue(name, "обов'язковий аргумент відсутній"))
    for name, value in data.items():
        spec_field = spec.parameters.get(name) if isinstance(spec.parameters, Mapping) else None
        if not isinstance(spec_field, Mapping):
            continue
        expected = spec_field.get("type")
        if isinstance(expected, str) and not _matches_type(value, expected):
            issues.append(ArgIssue(
                name, f"очікувався тип {expected}, отримано {type(value).__name__}"))
            continue
        choices = spec_field.get("enum")
        if isinstance(choices, (list, tuple)) and value not in choices:
            issues.append(ArgIssue(
                name, "допустимі значення: " + ", ".join(str(item) for item in choices)))
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            minimum = spec_field.get("minimum")
            maximum = spec_field.get("maximum")
            if isinstance(minimum, (int, float)) and value < minimum:
                issues.append(ArgIssue(name, f"мінімум {minimum}"))
            if isinstance(maximum, (int, float)) and value > maximum:
                issues.append(ArgIssue(name, f"максимум {maximum}"))
        if isinstance(value, list) and isinstance(spec_field.get("items"), Mapping):
            item_type = spec_field["items"].get("type")
            if isinstance(item_type, str):
                for index, item in enumerate(value):
                    if not _matches_type(item, item_type):
                        issues.append(ArgIssue(
                            f"{name}[{index}]", f"очікувався тип {item_type}"))
                        break
    return issues


def unknown_arguments(spec: ToolSpec, arguments: Mapping[str, Any] | None) -> list[str]:
    """Зайві поля, яких немає у схемі (для підказки моделі)."""
    known = set(spec.parameters or ())
    return [name for name in (arguments or {}) if known and name not in known]


def format_issues(issues: Sequence[ArgIssue], spec: ToolSpec | None = None) -> str:
    """Текст для МОДЕЛІ (не для користувача): що саме не так з аргументами."""
    lines = ["Аргументи не прийнято:"]
    lines.extend(f"• {issue}" for issue in issues)
    if spec is not None:
        expected = ", ".join(sorted(spec.required)) or "—"
        lines.append(f"Обов'язкові параметри «{spec.name}»: {expected}.")
        example = dict(spec.example)
        if example:
            shown = ", ".join(f"{key}={value!r}" for key, value in example.items())
            lines.append(f"Приклад правильного виклику: {shown}")
        lines.append(
            "Виправ аргументи й виклич інструмент ще раз. Не вигадуй інших "
            "назв параметрів — бери лише ті, що у схемі."
        )
    return "\n".join(lines)


def describe_tool(spec: ToolSpec) -> str:
    """Багаторядковий опис для людини й для журналу (без сирого JSON)."""
    lines = [f"**{spec.name}** — {spec.purpose}"]
    if spec.category:
        lines.append(f"• категорія: {spec.category}")
    if spec.risk:
        lines.append(f"• ризик: {spec.risk}")
    if spec.required:
        lines.append("• обов'язкові параметри: " + ", ".join(sorted(spec.required)))
    if spec.side_effects:
        lines.append(f"• побічні дії: {spec.side_effects}")
    if spec.output_hint:
        lines.append(f"• повертає: {spec.output_hint}")
    if spec.failure_modes:
        lines.append("• типові збої:")
        lines.extend(f"  – {item}" for item in spec.failure_modes)
    return "\n".join(lines)


def catalog_lines(specs: Mapping[str, ToolSpec], *, limit: int = 0) -> list[str]:
    """Рядки каталогу за категоріями: «назва — намір (ризик)».

    ``limit`` обмежує кількість — для вузьких вікон контексту, де кожен
    рядок коштує токенів.
    """
    grouped: dict[str, list[ToolSpec]] = {}
    for spec in specs.values():
        grouped.setdefault(spec.category, []).append(spec)
    lines: list[str] = []
    for category in CATEGORIES:
        items = grouped.get(category)
        if not items:
            continue
        lines.append(f"{category}:")
        for spec in sorted(items, key=lambda item: item.name):
            lines.append(f"- {spec.name} — {spec.purpose} [{spec.risk}]")
            if limit and len(lines) >= limit:
                return lines
    # Категорії, яких немає в CATEGORIES (нові MCP-сервери) — у кінець.
    for category, items in sorted(grouped.items()):
        if category in CATEGORIES:
            continue
        lines.append(f"{category}:")
        for spec in sorted(items, key=lambda item: item.name):
            lines.append(f"- {spec.name} — {spec.purpose} [{spec.risk}]")
    return lines[:limit] if limit else lines
