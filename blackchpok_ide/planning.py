"""Планування задачі з розумінням наміру: IntentFrame → кроки з залежностями.

Навіщо окремий шар, якщо вже є :mod:`task_plan` і :mod:`task_planner`:

* :mod:`task_plan` ріже СИРИЙ ТЕКСТ на етапи — він не знає ні обмежень,
  ні критеріїв завершення, ні того, що людина вже пояснила раніше;
* :mod:`task_planner` питає план у МОДЕЛІ — це дорого й неможливо без
  моделі, а на малих моделях план буває гірший за евристику.

Тут план будується з :class:`intent_engine.IntentFrame` **детерміновано**:
файли, обмеження й критерії завершення вже відомі, тож кроки й залежності
між ними виводяться без жодного запиту до моделі. Модель лише уточнює
готовий план, а не створює його з нуля.

Головне, що це дає на практиці:

1. **перевірка не губиться** — крок «перевірити» є завжди, коли є зміна;
2. **обмеження стають кроком** — «не зламай інше» перетворюється на
   окрему перевірку, а не лишається рядком у промпті;
3. **робота по файлах не змішується** — правки різних файлів можуть іти
   незалежно, і це видно явно (``depends_on``).

Модуль чистий: без tkinter, без мережі, без моделі.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from . import intent_engine, task_plan, task_planner

__all__ = [
    "MAX_PLAN_STEPS",
    "PlannedStep",
    "build_plan",
    "is_multi_step",
    "plan_as_text",
    "plan_prompt_block",
    "should_plan",
]

#: Більше кроків не робимо: людина не читає довгий план, а модель на
#: кожному кроці втрачає контекст. 12 — межа, за якою робота вже
#: потребує окремих завдань у черзі, а не одного ходу.
MAX_PLAN_STEPS = 12

#: Типи намірів, для яких план із кількох кроків справді потрібен.
_MULTI_INTENTS: frozenset[str] = frozenset({
    intent_engine.CREATE, intent_engine.EDIT, intent_engine.DEBUG,
    intent_engine.TEST, intent_engine.INSPECT, intent_engine.RESEARCH,
})

#: Інструменти для етапів плану (підмножина, а не всі 36).
_TOOLS_EXPLORE = ["list_dir", "read_file", "search_text"]
_TOOLS_WRITE = ["write_file", "edit_file"]
_TOOLS_CHECK = ["python_check"]
_TOOLS_RUN = ["run_command"]
_TOOLS_WEB = ["search_web", "fetch_url"]


@dataclass
class PlannedStep:
    """Один крок плану з явними залежностями."""

    title: str
    detail: str = ""
    tools: list[str] = field(default_factory=list)
    #: Номери кроків (1-based), від яких залежить цей крок.
    depends_on: list[int] = field(default_factory=list)
    #: Це крок перевірки (його провал означає «не готово»).
    check: bool = False

    def as_row(self) -> dict[str, Any]:
        """Подати крок для черги задач (той самий формат, що й у планувальнику)."""
        return {
            "text": self.title,
            "detail": self.detail,
            "tools": list(self.tools),
            "depends_on": list(self.depends_on),
        }


def _clean(text: str, limit: int = 160) -> str:
    body = " ".join((text or "").split())
    return body if len(body) <= limit else body[: limit - 1] + "…"


def should_plan(intent: Any, state: Any = None) -> bool:
    """Чи варто будувати план із кількох кроків.

    Плануємо лише тоді, коли це справді допоможе: кілька файлів, кілька
    різних дій, або вже накопичені обмеження. Просте завдання на один
    файл не потребує плану — зайвий план лише сповільнює старт.
    """
    if intent is None:
        return False
    if str(getattr(intent, "intent_type", "")) not in _MULTI_INTENTS:
        return False
    if not bool(getattr(intent, "actionable", False)):
        return False
    files = list(getattr(intent, "referenced_files", ()) or ())
    constraints = list(getattr(intent, "constraints", ()) or ())
    secondary = list(getattr(intent, "secondary_goals", ()) or ())
    if len(files) >= 2:
        return True
    if secondary:
        return True
    if constraints and str(getattr(intent, "intent_type", "")) in (
            intent_engine.EDIT, intent_engine.CREATE):
        # Обмеження саме собою додає крок перевірки — це вже два кроки.
        return True
    if state is not None and list(getattr(state, "completed", ()) or ()):
        # Робота вже почалась: треба бачити, що лишилось.
        return True
    return False


def is_multi_step(intent: Any, state: Any = None) -> bool:
    """Чи план уже не вміщається в один хід (для показу смуги етапів)."""
    return len(build_plan(intent, state)) > 1


def build_plan(intent: Any, state: Any = None, *,
               limit: int = MAX_PLAN_STEPS) -> list[PlannedStep]:
    """Побудувати план із кадру наміру — без моделі й без тексту.

    Структура залежить від типу наміру:

    * ``debug``: огляд → причини → правка → перевірка;
    * ``edit``/``create``: огляд → (по кроку на файл або на вимогу) →
      перевірка;
    * ``inspect``/``research``: один-два кроки збору даних.

    Усе, що не вдалось вивести з кадру, не вигадуємо: краще короткий
    план, ніж красива структура без змісту.
    """
    if intent is None:
        return []
    intent_type = str(getattr(intent, "intent_type", "") or "")
    if intent_type not in _MULTI_INTENTS:
        return []

    files = [str(item) for item in
             (getattr(intent, "referenced_files", ()) or ()) if str(item).strip()]
    features = [str(item) for item in
                (getattr(intent, "referenced_features", ()) or ())
                if str(item).strip()]
    constraints = [str(item) for item in
                   (getattr(intent, "constraints", ()) or ())]
    criteria = [str(item) for item in
                (getattr(intent, "completion_criteria", ()) or ())]
    completed = [str(item) for item in
                 (getattr(state, "completed", ()) or ())] if state is not None else []

    steps: list[PlannedStep] = []

    def add(title: str, *, detail: str = "", tools: Iterable[str] = (),
            depends: Iterable[int] = (), check: bool = False) -> int:
        steps.append(PlannedStep(
            title=_clean(title), detail=_clean(detail, 400),
            tools=[name for name in tools if name],
            depends_on=[int(item) for item in depends],
            check=check,
        ))
        return len(steps)

    def done_before(title: str) -> bool:
        key = " ".join(title.lower().split())
        return any(key in " ".join(item.lower().split()) for item in completed)

    # ── 1. Спершу факти: що вже є в проєкті ───────────────────────────────
    explore = 0
    if intent_type in (intent_engine.EDIT, intent_engine.DEBUG,
                       intent_engine.CREATE, intent_engine.INSPECT):
        if files:
            explore = add("Прочитати наявний код: " + ", ".join(files[:4]),
                          detail="Подивитись справжній вміст перед змінами.",
                          tools=_TOOLS_EXPLORE)
        elif intent_type in (intent_engine.EDIT, intent_engine.DEBUG):
            explore = add("Знайти місце, яке треба змінити",
                          detail="Пошук по проєкту: де саме це живе.",
                          tools=_TOOLS_EXPLORE)
        elif intent_type == intent_engine.CREATE:
            explore = add("Подивитись структуру проєкту",
                          detail="Щоб новий файл ліг поруч, а не в корінь.",
                          tools=["list_dir"])

    # ── 2. Для збою: спершу відтворити, потім лагодити ────────────────────
    reproduce = 0
    if intent_type == intent_engine.DEBUG:
        reproduce = add("Відтворити помилку й побачити справжню причину",
                        detail="Запуск і читання помилки, а не здогад.",
                        tools=[*_TOOLS_RUN, "read_file"],
                        depends=[explore] if explore else [])

    # ── 3. Робота: по кроку на файл або на названу вимогу ────────────────
    work_deps = [index for index in (reproduce, explore) if index]
    work: list[int] = []
    if intent_type in (intent_engine.EDIT, intent_engine.CREATE,
                       intent_engine.DEBUG):
        if len(files) > 1:
            for name in files[:limit - 3]:
                if done_before(name):
                    continue
                work.append(add(f"Змінити {name}",
                                detail="Один файл — один крок, щоб було видно, що змінено.",
                                tools=_TOOLS_WRITE, depends=work_deps))
        elif files:
            title = (f"Змінити {files[0]}" if intent_type == intent_engine.EDIT
                     else f"Створити {files[0]}")
            work.append(add(title, tools=_TOOLS_WRITE, depends=work_deps))
        else:
            label = "виправлення" if intent_type == intent_engine.DEBUG else (
                "новий функціонал" if intent_type == intent_engine.CREATE
                else "правку")
            work.append(add(f"Внести {label}",
                            detail=_clean(str(getattr(intent, "primary_goal", "")
                                              or ""), 200),
                            tools=_TOOLS_WRITE, depends=work_deps))
        # Названі вимоги стають окремими кроками, якщо їх видно у фразі.
        for feature in features[: max(0, limit - len(steps) - 2)]:
            if done_before(feature):
                continue
            work.append(add(f"Зробити: {_clean(feature, 80)}",
                            tools=_TOOLS_WRITE,
                            depends=[work[-1]] if work else work_deps))

    # ── 4. Перевірки: синтаксис, запуск, обмеження, критерії ────────────
    check_deps = [work[-1]] if work else ([explore] if explore else [])
    needs_check = bool(work) or intent_type == intent_engine.TEST
    if needs_check:
        add("Перевірити синтаксис змінених файлів",
            detail="Компіляція без запуску — найдешевша перевірка.",
            tools=_TOOLS_CHECK, depends=check_deps, check=True)
    if bool(work) and intent_type in (intent_engine.EDIT, intent_engine.CREATE,
                                      intent_engine.DEBUG):
        add("Запустити й переконатись, що працює",
            detail="Синтаксис — лише половина: помилка виконання видна тільки тут.",
            tools=_TOOLS_RUN, depends=[len(steps)], check=True)
    if intent_type == intent_engine.TEST:
        add("Прогнати тести",
            detail="Показати справжній результат, а не «має працювати».",
            tools=_TOOLS_RUN, depends=check_deps, check=True)
    if intent_type == intent_engine.RESEARCH:
        add("Взяти дані з мережі й показати джерела",
            detail="Ціни, курси, версії не беруться з пам'яті моделі.",
            tools=_TOOLS_WEB, check=True)

    # ── 5. Обмеження: «не зламай інше» стає окремою перевіркою ──────────
    for item in constraints:
        if len(steps) >= limit:
            break
        if "не ламати" in item or "мінімальні" in item:
            add("Перевірити, що наявна поведінка не змінена",
                detail=f"Обмеження користувача: {item}",
                tools=[*_TOOLS_CHECK, "git_diff"],
                depends=[len(steps)], check=True)
        elif "не видаляти" in item:
            add("Перевірити, що старі дані на місці",
                detail=f"Обмеження користувача: {item}",
                tools=["read_file"], depends=[len(steps)], check=True)
        elif "локально" in item or "зовнішніх залежностей" in item:
            add("Перевірити, що не додано зовнішніх залежностей",
                detail=f"Обмеження користувача: {item}",
                tools=["read_file"], depends=[len(steps)], check=True)

    # ── 6. Критерії завершення з кадру ──────────────────────────────────
    if not needs_check:
        for item in criteria[:2]:
            if len(steps) >= limit:
                break
            add(f"Перевірити: {_clean(item, 90)}", depends=[len(steps)],
                check=True)

    return _tidy(steps[:limit])


def _tidy(steps: list[PlannedStep]) -> list[PlannedStep]:
    """Прибрати кроки-дублікати й полагодити номери залежностей.

    Дублікат — це крок із тим самим змістом: «Перевірити синтаксис» двічі
    поспіль лише заважає. Залежності після видалення перенумеровуємо,
    інакше план посилався б на неіснуючі кроки.
    """
    seen: dict[str, int] = {}
    kept: list[PlannedStep] = []
    mapping: dict[int, int] = {}
    for index, step in enumerate(steps, start=1):
        # Смисловий ключ — той самий, що відсіює дублікати в планувальнику:
        # «Створити app.py» і «Створити файл app.py» мають стати одним кроком.
        try:
            key = str(task_planner._meaning_key(step.title))  # noqa: SLF001
        except Exception:                        # noqa: BLE001
            key = " ".join(step.title.lower().split())
        if key in seen:
            mapping[index] = seen[key]
            continue
        new_index = len(kept) + 1
        mapping[index] = new_index
        seen[key] = new_index
        kept.append(step)
    for step in kept:
        fixed: list[int] = []
        for dependency in step.depends_on:
            target = mapping.get(dependency, dependency)
            if 1 <= target <= len(kept) and target != kept.index(step) + 1:
                if target not in fixed:
                    fixed.append(target)
        step.depends_on = fixed
    return kept


def plan_as_text(steps: Sequence[PlannedStep], *, limit: int = MAX_PLAN_STEPS) -> str:
    """Текст плану для моделі й журналу (без JSON)."""
    if not steps:
        return ""
    lines = ["План роботи:"]
    for index, step in enumerate(steps[:limit], start=1):
        deps = ""
        if step.depends_on:
            deps = " (після " + ", ".join(str(item) for item in step.depends_on) + ")"
        tools = f" — {', '.join(step.tools)}" if step.tools else ""
        lines.append(f"{index}. {step.title}{deps}{tools}")
    return "\n".join(lines)


def plan_prompt_block(intent: Any, steps: Sequence[PlannedStep]) -> str:
    """Що сказати моделі про план: мета, кроки, обмеження.

    Модель не має переписувати план — вона має виконувати поточний крок.
    Тому текст навмисно короткий і без варіантів.
    """
    if not steps:
        return ""
    parts = [plan_as_text(steps)]
    constraints = list(getattr(intent, "constraints", ()) or ())
    if constraints:
        parts.append("Обмеження, які не можна порушити: " + "; ".join(constraints))
    parts.append(
        "Виконуй кроки ПО ЧЕРЗІ. Не переходь до наступного, поки поточний "
        "не підтверджений результатом інструмента."
    )
    return "\n".join(parts)


def refine_prompt(steps: Sequence[PlannedStep]) -> str:
    """Готовий план у форматі, який приймає :func:`task_planner.parse_plan`.

    Потрібно, коли план усе ж віддають моделі на уточнення: вона бачить
    структуру, а не порожній аркуш, і не губить залежностей.
    """
    lines: list[str] = []
    for index, step in enumerate(steps, start=1):
        body = step.title
        if step.detail:
            body += f" — {step.detail}"
        lines.append(f"{index}. {body}")
    return "\n".join(lines)


def order_steps(steps: Sequence[PlannedStep], *, limit: int = MAX_PLAN_STEPS) -> list[PlannedStep]:
    """Упорядкувати кроки за залежностями (спільний алгоритм планувальника).

    Використовуємо :func:`task_planner.order_by_dependencies`, щоб не
    мати другої реалізації топологічного сортування з іншими правилами
    розриву циклів.
    """
    if not steps:
        return []
    converted = [
        task_planner.PlanStep(title=step.title, detail=step.detail,
                              tools=list(step.tools),
                              depends_on=list(step.depends_on))
        for step in steps[:limit]
    ]
    ordered = task_planner.order_by_dependencies(converted)
    by_title = {step.title: step for step in steps}
    result: list[PlannedStep] = []
    for item in ordered:
        original = by_title.get(item.title)
        if original is not None:
            result.append(original)
    return result or list(steps[:limit])
