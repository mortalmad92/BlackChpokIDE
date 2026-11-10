"""Планування роботи локальною моделлю: запит → нумерована черга кроків.

Головна ідея: користувач пише ОДНЕ велике завдання, а зміст кроків визначає
**локальна модель**, а не зашитий в IDE алгоритм. Цей модуль робить рівно
три речі й не більше:

1. **Питає модель** — окремим коротким запитом зі структурою відповіді
   (``PLAN_SCHEMA_HINT``) і реальним контекстом проєкту (стек і файли), щоб
   план стосувався цього проєкту, а не вигаданого.
2. **Розбирає й перевіряє** відповідь: нормалізує поля, прибирає абзаци,
   обрізає назви до 4–12 слів, прибирає дублікати й самопосилання,
   відновлює порядок залежностей (топологічне сортування).
3. **Перекладає** залежності з номерів кроку (модель мислить номерами) у
   реальні id задач — це вже робота :class:`queue_engine.TaskQueue`.

Чого тут НЕМАЄ: жодного списку «фіксованих» кроків на кшталт «створити базу
даних → реалізувати реєстрацію». Якщо модель недоступна, модуль чесно
повертає помилку, а виклик вирішує, що робити (зазвичай — поставити задачу
одним пунктом). Підміняти модель шаблоном означало б показати користувачу
фальшивий план.

Модуль не тягне tkinter: його легко перевіряти тестами.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

LOG = logging.getLogger("blackchpok.task_planner")

#: Скільки кроків просимо максимум. Більше — модель дробить роботу на
#: мікроскопічні кроки, і черга перетворюється на шум.
MAX_STEPS = 16
#: Скільки кроків достатньо для «звичайної» великої задачі.
DEFAULT_STEPS = 10
#: Межі довжини назви кроку в СЛОВАХ (вимога: 4–12 слів).
#: Довша назва не вміщається в рядок панелі й перетворюється на абзац —
#: саме те, чого просив не робити користувач.
MAX_TITLE_WORDS = 12
#: Межа довжини назви в символах (жорстка стеля для UI).
MAX_TITLE_CHARS = 110

#: Інструкція моделі. Навмисно вужча, ніж «склади план»: потрібен саме
#: короткий нумерований список із стислими описами, інакше локальні моделі
#: пишуть абзаци й переказують ТЗ.
PLAN_SYSTEM_PROMPT = (
    "Ти — планувальник роботи програмного агента всередині IDE.\n"
    "Твоє завдання: розбити запит користувача на послідовні кроки, які "
    "агент виконає сам інструментами (читання файлів, запис файлів, "
    "команди, перевірки).\n\n"
    "Правила:\n"
    "1. Кожен крок — одна конкретна дія, яку можна виконати за один підхід.\n"
    "2. Назва кроку: 4–12 слів, без абзаців і без переказу всього завдання.\n"
    "3. Порядок важливий: крок спирається на результат попереднього.\n"
    "4. Спирайся ЛИШЕ на реальний стек і файли проєкту з контексту.\n"
    "5. Останні кроки — перевірка результату й виправлення помилок.\n"
    "6. Не додавай кроків «уточнити вимоги», «скласти план», «почати».\n\n"
    "Відповідай ЛИШЕ JSON-масивом об'єктів, без markdown і без пояснень:\n"
    '[{"title": "коротка назва кроку", '
    '"detail": "що саме зробити в цьому кроці", '
    '"tools": ["write_file"], "depends_on": []}]\n\n'
    "depends_on — номери кроків (з 1), які мають завершитись раніше; "
    "порожній масив означає «можна робити одразу».\n"
    "tools — назви доречних інструментів із переліку, який дано в запиті.\n"
)

#: Доповнення, коли вже є план і треба його ПЕРЕПЛАНУВАТИ.
REPLAN_SYSTEM_PROMPT = (
    PLAN_SYSTEM_PROMPT
    + "\nЗАРАЗ ПОТРІБНЕ ПЕРЕПЛАНУВАННЯ: частину роботи вже зроблено, або "
      "виявилась проблема. Поверни ПОВНИЙ оновлений список залишкових і "
      "нових кроків (уже виконані не повторюй).\n"
)


@dataclass
class PlanStep:
    """Один крок плану в тому вигляді, у якому його дав розбір."""

    title: str
    detail: str = ""
    tools: list[str] = field(default_factory=list)
    #: Номери кроків (1-based), від яких залежить цей крок.
    depends_on: list[int] = field(default_factory=list)

    def as_row(self) -> dict[str, Any]:
        """Подати крок для :meth:`queue_engine.TaskQueue.add_steps`."""
        return {
            "text": self.title,
            "detail": self.detail,
            "tools": list(self.tools),
            "depends_on": list(self.depends_on),
        }


@dataclass
class PlanResult:
    """Результат планування: кроки або причина, чому їх немає."""

    steps: list[PlanStep] = field(default_factory=list)
    error: str = ""
    #: Сира відповідь моделі (для журналу й діагностики).
    raw: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.steps)

    def rows(self) -> list[dict[str, Any]]:
        return [step.as_row() for step in self.steps]


# ─────────────────────────────────────────────────────────────────────────────
# Запит до моделі
# ─────────────────────────────────────────────────────────────────────────────

def build_plan_messages(goal: str, *, context: str = "",
                        tool_names: Iterable[str] = (),
                        existing: str = "",
                        replan: bool = False) -> list[dict[str, str]]:
    """Зібрати повідомлення для моделі-планувальника.

    ``context`` — опис проєкту (стек і файли), ``existing`` — уже наявний
    план у текстовому вигляді (щоб модель не повторювала зроблене).
    """
    system = REPLAN_SYSTEM_PROMPT if replan else PLAN_SYSTEM_PROMPT
    parts: list[str] = []
    names = [str(name) for name in tool_names if str(name).strip()]
    if names:
        parts.append("Доступні інструменти: " + ", ".join(sorted(names)))
    if context.strip():
        parts.append("Контекст проєкту:\n" + context.strip())
    if existing.strip():
        parts.append("Поточний план і його стан:\n" + existing.strip())
    parts.append("Запит користувача:\n" + (goal or "").strip())
    parts.append(
        f"Дай від {max(3, min(6, DEFAULT_STEPS))} до {DEFAULT_STEPS} кроків. "
        "Лише JSON-масив."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def plan_with_model(goal: str, llm_settings: Any, *, context: str = "",
                    tool_names: Iterable[str] = (), existing: str = "",
                    replan: bool = False, timeout: int = 240,
                    max_steps: int = MAX_STEPS) -> PlanResult:
    """Попросити локальну модель скласти план.

    Окремий короткий запит, а не частина основного циклу агента: план
    з'являється швидко й не змішується з виконанням. Помилку повертаємо
    текстом, а не винятком — вікно має показати причину й працювати далі.
    """
    clean = (goal or "").strip()
    if not clean:
        return PlanResult(error="порожнє завдання")
    try:
        from .llm_client import LLMClient, LLMError
    except ImportError as exc:  # pragma: no cover - клієнт завжди є
        return PlanResult(error=str(exc))
    model = str(getattr(llm_settings, "model", "") or "").strip()
    if not model:
        return PlanResult(error="Модель не вибрана")
    messages = build_plan_messages(clean, context=context, tool_names=tool_names,
                                   existing=existing, replan=replan)
    try:
        client = LLMClient(
            getattr(llm_settings, "base_url", ""),
            model,
            getattr(llm_settings, "api_key", ""),
            temperature=0.2,
            # План із 10–16 кроків не вміщається у 512 токенів, а обрізана
            # відповідь — це обрізаний план.
            max_tokens=1600,
            timeout=timeout,
        )
        result = client.chat(messages)
        raw = result.content or ""
    except LLMError as exc:
        LOG.info("План не склався: %s", exc)
        return PlanResult(error=str(exc))
    except Exception as exc:  # noqa: BLE001 - план не має ламати вікно
        LOG.warning("Помилка планування: %s", exc, exc_info=True)
        return PlanResult(error=f"{type(exc).__name__}: {exc}")
    steps = parse_plan(raw, limit=max_steps)
    if not steps:
        return PlanResult(error="модель не повернула кроків", raw=raw)
    return PlanResult(steps=steps, raw=raw)


# ─────────────────────────────────────────────────────────────────────────────
# Розбір відповіді моделі
# ─────────────────────────────────────────────────────────────────────────────

def parse_plan(raw: str, *, limit: int = MAX_STEPS) -> list[PlanStep]:
    """Витягти кроки з відповіді моделі, терпимо до формату.

    Локальні моделі слухаються інструкції «лише JSON» приблизно в половині
    випадків. Приймаємо: JSON-масив об'єктів, JSON-масив рядків, JSON-об'єкт
    із ключем ``steps``/``plan``/``tasks``, нумерований список і список із
    маркерами. Усе інше — нічого не повертаємо, і виклик вирішує сам.
    """
    text = (raw or "").strip()
    if not text:
        return []

    for data in _json_candidates(text):
        steps = _steps_from_json(data, limit=limit)
        if steps:
            return steps

    steps = _steps_from_lines(text, limit=limit)
    return steps


def _json_candidates(text: str) -> Iterable[Any]:
    """Усі JSON-фрагменти в тексті, які вдалось розібрати."""
    # 1. Цілий текст як JSON.
    for candidate in (text, _strip_fences(text)):
        try:
            yield json.loads(candidate)
            return
        except (json.JSONDecodeError, TypeError):
            continue
    # 2. Масив або об'єкт усередині тексту (модель додала пояснення).
    #
    # Регулярка ``\[[\s\S]*?\]`` (нежадібна) зупинялась на ПЕРШІЙ ``]``:
    # для плану з трьох кроків у масиві об'єктів вона повертала лише
    # другий крок, і план складався з 1 кроку без залежностей (перевірено).
    # Тому шукаємо збалансовані дужки вручну.
    for chunk in _balanced_chunks(_strip_fences(text)):
        try:
            yield json.loads(chunk)
        except json.JSONDecodeError:
            continue


def _balanced_chunks(text: str) -> list[str]:
    """Вирізати збалансовані JSON-масиви й об'єкти з довільного тексту.

    Ігноруємо вміст рядків (лапки), щоб ``]`` усередині рядка не ламав
    підрахунок. Повертає фрагменти в порядку появи.
    """
    chunks: list[str] = []
    opened = ""
    depth = 0
    in_string = False
    escaped = False
    start = -1
    for index, char in enumerate(text or ""):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char in "[{":
            if depth == 0:
                start = index
                opened = char
            depth += 1
            continue
        if char in "]}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start >= 0:
                closing_ok = (opened == "[" and char == "]") or \
                             (opened == "{" and char == "}")
                if closing_ok:
                    chunks.append(text[start:index + 1])
                start = -1
    return chunks


def _strip_fences(text: str) -> str:
    clean = re.sub(r"^\s*```[a-zA-Z]*\s*", "", text or "")
    return re.sub(r"\s*```\s*$", "", clean).strip()


def _steps_from_json(data: Any, *, limit: int) -> list[PlanStep]:
    """Побудувати кроки з розібраного JSON (кілька підтримуваних форм)."""
    items: list[Any] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("steps", "plan", "tasks", "items"):
            value = data.get(key)
            if isinstance(value, list):
                items = value
                break
        else:
            # Один крок, поданий як об'єкт.
            if data.get("title") or data.get("text"):
                items = [data]
    if not items:
        return []
    steps: list[PlanStep] = []
    for item in items:
        if isinstance(item, str):
            step = _step_from_title(item)
            if step is not None:
                steps.append(step)
            continue
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("text") or item.get("step") or item.get("name")
        detail = item.get("detail") or item.get("description") or item.get("what") or ""
        step = _step_from_title(str(title or ""), detail=str(detail or ""),
                                tools=item.get("tools"),
                                depends=item.get("depends_on", item.get("deps")))
        if step is not None:
            steps.append(step)
        if len(steps) >= limit:
            break
    return _finalise(steps)


def _steps_from_lines(text: str, *, limit: int) -> list[PlanStep]:
    """Запасний шлях: нумерований список або маркери в тексті."""
    steps: list[PlanStep] = []
    for line in _strip_fences(text).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(r"^(?:\d+[.)]|[-*•·])\s+(.+)$", stripped)
        if not match:
            continue
        # «1. Назва — опис» розділяємо на назву й опис.
        body = match.group(1).strip()
        step = _step_from_title(body)
        if step is not None:
            steps.append(step)
        if len(steps) >= limit:
            break
    return _finalise(steps)


def _step_from_title(raw_title: str, *, detail: str = "",
                     tools: Any = None, depends: Any = None) -> Optional[PlanStep]:
    """Нормалізувати один крок: коротка назва + опис + залежності."""
    title, inline_detail = _split_title_detail(raw_title)
    if not title:
        return None
    return PlanStep(
        title=title,
        detail=(detail or inline_detail).strip()[:400],
        tools=_clean_tools(tools),
        depends_on=_clean_depends(depends),
    )


def _split_title_detail(text: str) -> tuple[str, str]:
    """Розділити «Назва — докладніше» і скоротити назву до 4–12 слів.

    Вимога «не записувати абзаци в чергу» виконується тут: усе, що довше
    за :data:`MAX_TITLE_WORDS` слів, відрізається в назву, решта стає
    описом, який відкривається натисканням на пункт.
    """
    clean = " ".join((text or "").split())
    clean = clean.strip("\"'` ")
    # Маркери списку, що могли лишитись.
    clean = re.sub(r"^(?:\d+[.)]|[-*•·])\s*", "", clean)
    if not clean:
        return "", ""
    detail = ""
    # Явне розділення назви й опису: тире, двокрапка або « — ».
    parts = re.split(r"\s+[—–]\s+|\s*\|\s*", clean, maxsplit=1)
    if len(parts) == 2 and parts[0].strip():
        clean, detail = parts[0].strip(), parts[1].strip()
    words = clean.split()
    if len(words) > MAX_TITLE_WORDS:
        head = " ".join(words[:MAX_TITLE_WORDS])
        rest = " ".join(words[MAX_TITLE_WORDS:])
        detail = (rest + (" " + detail if detail else "")).strip()
        clean = head
    if len(clean) > MAX_TITLE_CHARS:
        detail = (clean[MAX_TITLE_CHARS:] + " " + detail).strip()
        clean = clean[:MAX_TITLE_CHARS].rstrip()
    # Крапка в кінці назви лише заважає читати список.
    clean = clean.rstrip(" .;:")
    return clean, detail.strip()


def _clean_tools(value: Any) -> list[str]:
    if isinstance(value, str):
        items = re.split(r"[,\s]+", value)
    elif isinstance(value, (list, tuple)):
        items = [str(item) for item in value]
    else:
        return []
    return [item.strip() for item in items if item.strip()][:6]


def _clean_depends(value: Any) -> list[int]:
    """Номери залежностей: приймаємо 1, "1", [1,2], "1,2"."""
    if value is None:
        return []
    if isinstance(value, (int, float)):
        items: list[Any] = [value]
    elif isinstance(value, str):
        items = re.findall(r"\d+", value)
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        return []
    numbers: list[int] = []
    for item in items:
        try:
            number = int(str(item).strip())
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in numbers:
            numbers.append(number)
    return numbers


def _finalise(steps: list[PlanStep]) -> list[PlanStep]:
    """Прибрати дублікати й самопосилання, відновити порядок за залежностями."""
    unique: list[PlanStep] = []
    seen: set[str] = set()
    seen_meaning: dict[tuple[str, tuple[str, ...]], int] = {}
    for step in steps:
        key = _norm_key(step.title)
        if not key or key in seen:
            continue
        # ── Смисловий дубль ────────────────────────────────────────────────
        # Модель часто повторює ту саму роботу іншими словами:
        # «Створити файл greeting.py» і «Створити файл greeting.py» (різні
        # регістри/пунктуація вже злиті), але буває й
        # «Створити файл app.py» + «Створити файл app.py повторно».
        # Порівнюємо ЗМІСТ: дієслово + згадані файли. Якщо збігається —
        # лишаємо перший крок, а докладніший опис переносимо в нього.
        meaning = _meaning_key(step.title)
        if meaning in seen_meaning:
            first = unique[seen_meaning[meaning]]
            if len(step.detail) > len(first.detail):
                first.detail = step.detail
            LOG.info("Смисловий дубль кроку: %r ≈ %r", step.title, first.title)
            continue
        seen_meaning[meaning] = len(unique)
        seen.add(key)
        unique.append(step)
    if not unique:
        return []
    total = len(unique)
    for position, step in enumerate(unique, start=1):
        # Самопосилання й номери поза межами — прибираємо: інакше задача
        # чекала б сама на себе й ніколи не запускалась.
        step.depends_on = [n for n in step.depends_on if 1 <= n <= total and n != position]
    return order_by_dependencies(unique)


#: Дієслова, за якими визначаємо «що саме робить крок».
_ACTION_VERBS = (
    "створити", "створи", "записати", "запиши", "додати", "додай",
    "реалізувати", "реалізуй", "перевірити", "перевір", "запустити",
    "запусти", "виправити", "виправ", "оновити", "онови", "змінити",
    "зміни", "створити структуру", "прочитати", "прочитай", "зберегти",
)


def _meaning_key(title: str) -> tuple[str, tuple[str, ...]]:
    """Смисловий ключ кроку: дія + файли, яких вона стосується.

    «Створити файл app.py» і «Створити app.py» дають один ключ —
    ``("створити", ("app.py",))``. Кроки про РІЗНІ файли лишаються
    різними, навіть якщо дія та сама.
    """
    low = (title or "").lower()
    action = ""
    for verb in _ACTION_VERBS:
        if low.startswith(verb) or f" {verb} " in f" {low} ":
            action = verb.split()[0]
            break
    # Файли з розширенням — головна ознака «про що цей крок».
    files = tuple(sorted(set(
        match.lower()
        for match in re.findall(r"[\w./\\-]+\.\w{1,8}", low)
    )))
    words = [word for word in re.findall(r"\w+", low)][:4]
    if not files:
        # Без файлів «смисловий» ключ мусить містити СЛОВА повністю: інакше
        # два різні кроки з однаковою дією злилися б в один. Беремо й
        # короткі слова («A крок» / «B крок» — різні кроки).
        return action, tuple(words)
    # З файлами досить дії + списку файлів: «Створити файл app.py» і
    # «Створити app.py» — це один крок, а хвіст назви («повторно», «знову»)
    # змісту не змінює.
    return action, files


def _norm_key(title: str) -> str:
    """Ключ для пошуку дублікатів: без регістру й пунктуації."""
    return re.sub(r"[^\wа-яїієґ ]+", "", (title or "").lower()).strip()


def order_by_dependencies(steps: list[PlanStep]) -> list[PlanStep]:
    """Стабільне топологічне сортування кроків за їхніми залежностями.

    Після сортування номери в ``depends_on`` ПЕРЕРАХОВУЮТЬСЯ під новий
    порядок: модель дала номери для свого початкового списку, а ми його
    переставили.
    """
    total = len(steps)
    if total <= 1:
        return list(steps)
    original = list(steps)
    # Явна залежність «крок N чекає на N-1», коли модель її не вказала, уже
    # забезпечена порядком черги — тут її не додаємо, щоб не робити
    # сортування надто жорстким.
    indegree = {index: 0 for index in range(total)}
    edges: dict[int, list[int]] = {index: [] for index in range(total)}
    for index, step in enumerate(original):
        for dep in step.depends_on:
            source = dep - 1
            if source == index or source < 0 or source >= total:
                continue
            edges[source].append(index)
            indegree[index] += 1
    ready = [index for index in range(total) if indegree[index] == 0]
    ordered: list[int] = []
    while ready:
        # Стабільність: серед готових беремо найменший номер — так порядок
        # моделі зберігається, коли залежності його не змінюють.
        ready.sort()
        current = ready.pop(0)
        ordered.append(current)
        for target in edges[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    # Цикл у залежностях (A чекає на B, B — на A): модель іноді таке
    # повертає. Лишати як є НЕ можна — обидві задачі чекали б вічно й
    # черга стояла б назавжди. Розриваємо цикл: решту додаємо в
    # початковому порядку моделі, а їхні залежності перераховуємо нижче
    # (від уже впорядкованих вони залишаться, на себе — зникнуть).
    leftover = [index for index in range(total) if index not in ordered]
    if leftover:
        LOG.info("Цикл у залежностях плану (%d кроків) — розриваю", len(leftover))
        ordered.extend(leftover)

    remap = {old_index: new_index + 1 for new_index, old_index in enumerate(ordered)}
    result: list[PlanStep] = []
    for new_index, old_index in enumerate(ordered):
        step = original[old_index]
        new_position = new_index + 1
        # Залежність лишаємо, тільки якщо вона веде на крок, що стоїть
        # РАНІШЕ в новому порядку. Залежність «уперед» або «на себе»
        # зробила б задачу недосяжною для виконання.
        deps: list[int] = []
        for dep in step.depends_on:
            if not 1 <= dep <= total:
                continue
            target = remap.get(dep - 1, 0)
            if target and target < new_position and target not in deps:
                deps.append(target)
        result.append(PlanStep(
            title=step.title,
            detail=step.detail,
            tools=list(step.tools),
            depends_on=sorted(deps),
        ))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Допоміжне для інтерфейсу
# ─────────────────────────────────────────────────────────────────────────────

def plan_as_text(tasks: Iterable[Any], *, limit: int = 40) -> str:
    """Подати поточний план текстом (для перепланування моделлю).

    Модель має бачити, що вже зроблено, щоб не пропонувати це знову.
    """
    rows: list[str] = []
    for task in tasks:
        number = getattr(task, "number", 0) or 0
        label = f"{number:02d}" if number else "--"
        title = str(getattr(task, "title", "") or getattr(task, "text", "") or "")
        status = str(getattr(task, "status", "") or "")
        rows.append(f"{label}. {title} [{status}]")
        if len(rows) >= limit:
            break
    return "\n".join(rows)


def plan_markdown(goal: str, steps: list[PlanStep]) -> str:
    """Показати план у чаті як нумерований список (для повідомлення агенту)."""
    lines = ["**План роботи**", ""]
    for index, step in enumerate(steps, start=1):
        lines.append(f"{index:02d}. {step.title}")
        if step.detail:
            lines.append(f"    _{step.detail}_")
    if goal.strip():
        lines.append("")
        lines.append(f"Мета: {goal.strip()[:400]}")
    return "\n".join(lines)


def step_prompt(task: Any, *, total: int = 0, goal: str = "") -> str:
    """Текст запиту агенту для одного кроку плану.

    Модель бачить номер, назву, свій же докладний опис і загальну мету —
    цього досить, щоб виконати саме цей крок, не переписуючи весь проєкт.
    """
    title = str(getattr(task, "text", "") or "").strip()
    detail = str(getattr(task, "detail", "") or "").strip()
    number = int(getattr(task, "number", 0) or 0)
    whole = (goal or str(getattr(task, "goal", "") or "")).strip()
    head = f"Крок {number} із {total}: {title}" if number and total else title
    parts = [head]
    if detail:
        parts.append(detail)
    tools = [str(tool) for tool in (getattr(task, "tools", None) or []) if str(tool)]
    # Якщо просять ДОДАТИ — прямо кажемо про append_file, інакше модель
    # візьме write_file і затере наявний вміст файлу.
    from . import task_plan as _task_plan

    append = _task_plan.append_hint(f"{title} {detail}")
    if append:
        parts.append(append)
        if "append_file" not in tools:
            tools.append("append_file")
    if tools:
        parts.append("Доречні інструменти: " + ", ".join(tools) + ".")
    # Файл, до якого належить крок. Автономний режим ставить його в
    # ``file_hint``, і без цього рядка агент шукав файл навмання —
    # виправлення йшло не в той модуль.
    hint = str(getattr(task, "file_hint", "") or "").strip()
    if hint:
        parts.append(f"Файл цього кроку: {hint}")
    if whole:
        parts.append(f"Загальна мета (для контексту): {whole[:500]}")
    parts.append(
        "Виконай ЛИШЕ цей крок. Не роби роботу наступних кроків і не "
        "переписуй файли, яких він не стосується."
    )
    return "\n\n".join(parts)


__all__ = [
    "DEFAULT_STEPS",
    "MAX_STEPS",
    "MAX_TITLE_CHARS",
    "MAX_TITLE_WORDS",
    "PLAN_SYSTEM_PROMPT",
    "PlanResult",
    "PlanStep",
    "REPLAN_SYSTEM_PROMPT",
    "build_plan_messages",
    "order_by_dependencies",
    "parse_plan",
    "plan_as_text",
    "plan_markdown",
    "plan_with_model",
    "step_prompt",
]
