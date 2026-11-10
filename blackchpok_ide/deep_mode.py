"""Режим глибокого аналізу й планування — логіка без tkinter.

Ідея: на складну задачу агент не кидається одразу писати код. Спершу він
аналізує проєкт і **пише свої проміжні думки просто в чат**, потім складає
список конкретних задач, і лише після цього починає виконувати першу.

Модуль описує цей процес як дані:

* :class:`Task` — один пункт плану зі станом;
* :class:`DeepSession` — ціль, задачі, фаза, час початку;
* :func:`wants_deep_plan` — чи задача достатньо складна для цього режиму;
* :func:`group_title` — людська назва групи викликів («Читання файлів,
  пошук коду»);
* :func:`plan_tasks` — попросити модель скласти план (використовується
  чатом у фоновому потоці).

Візуальна частина живе окремо — у :mod:`deep_view`.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from . import planner

LOG = logging.getLogger("blackchpok.deep")

# ── Стани задачі ──────────────────────────────────────────────────────────
STATE_PENDING = "очікує"
STATE_RUNNING = "у процесі"
STATE_DONE = "готово"
STATE_FAILED = "помилка"

#: Іконка-кружечок для кожного стану (як у панелі задач на скріншоті).
STATE_MARKS = {
    STATE_PENDING: "○",
    STATE_RUNNING: "◐",
    STATE_DONE: "●",
    STATE_FAILED: "✗",
}

# ── Фази режиму ───────────────────────────────────────────────────────────
PHASE_IDLE = ""
PHASE_ANALYSIS = "аналіз"
PHASE_PLAN = "план"
PHASE_EXECUTE = "виконання"
PHASE_DONE = "готово"

#: Скільки задач тримаємо в плані (більше — модель надто дробить).
MAX_TASKS = 24

# ── Категорії інструментів для групування ─────────────────────────────────
CAT_READ = "read"
CAT_SEARCH = "search"
CAT_RUN = "run"
CAT_EDIT = "edit"
CAT_APP = "app"
CAT_OTHER = "other"

#: Назви категорій людською мовою (для заголовка згортаного блоку).
CAT_LABELS = {
    CAT_READ: "Читання файлів",
    CAT_SEARCH: "Пошук коду",
    CAT_RUN: "Виконання команд",
    CAT_EDIT: "Зміна файлів",
    CAT_APP: "Керування застосунком",
    CAT_OTHER: "Інструменти",
}

#: До якої категорії належить кожен інструмент агента.
TOOL_CATEGORIES: dict[str, str] = {
    "read_file": CAT_READ,
    "list_dir": CAT_READ,
    "find_files": CAT_READ,
    "project_tree": CAT_READ,
    "search_text": CAT_SEARCH,
    "git_status": CAT_SEARCH,
    "git_diff": CAT_SEARCH,
    "run_command": CAT_RUN,
    "python_check": CAT_RUN,
    "write_file": CAT_EDIT,
    "edit_file": CAT_EDIT,
    "app_start": CAT_APP,
    "app_stop": CAT_APP,
    "app_restart": CAT_APP,
    "app_status": CAT_APP,
    "app_screenshot": CAT_APP,
    "project_screenshot": CAT_APP,
    "app_windows": CAT_APP,
    "window_screenshot": CAT_APP,
    "app_logs": CAT_APP,
    "app_click": CAT_APP,
    "app_type": CAT_APP,
    "app_key": CAT_APP,
}

#: Порядок категорій у заголовку групи (як їх читає людина).
CAT_ORDER = (CAT_READ, CAT_SEARCH, CAT_RUN, CAT_EDIT, CAT_APP, CAT_OTHER)


def category_of(tool: str) -> str:
    """Категорія інструмента (невідомий → ``other``)."""
    clean = (tool or "").strip()
    if clean.startswith(("router:", "mcp:")):
        clean = clean.split(":", 1)[1]
    return TOOL_CATEGORIES.get(clean, CAT_OTHER)


def group_title(tools: Iterable[str]) -> str:
    """Заголовок групи викликів людською мовою.

    Порядок сталий (читання → пошук → команди → зміни), щоб заголовок не
    «стрибав» під час роботи: людина бачить, що саме агент робив у цій групі.
    """
    seen = {category_of(tool) for tool in tools}
    parts = [CAT_LABELS[cat] for cat in CAT_ORDER if cat in seen]
    return ", ".join(parts) if parts else CAT_LABELS[CAT_OTHER]


# ── Задача ────────────────────────────────────────────────────────────────

@dataclass
class Task:
    """Один пункт плану."""

    text: str
    state: str = STATE_PENDING
    #: Порядковий номер у плані (з 0) — за ним шукаємо задачу.
    index: int = 0

    @property
    def mark(self) -> str:
        return STATE_MARKS.get(self.state, "○")

    @property
    def running(self) -> bool:
        return self.state == STATE_RUNNING

    @property
    def settled(self) -> bool:
        return self.state in (STATE_DONE, STATE_FAILED)


def _clean_task(text: str, *, limit: int = 200) -> str:
    """Прибрати з пункту плану маркери й зайву пунктуацію."""
    clean = " ".join((text or "").split())
    clean = re.sub(r"^[*\-•·]\s*", "", clean)
    clean = re.sub(r"^\d+[.)]\s*", "", clean)
    clean = clean.strip("\"'` ")
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


def build_tasks(steps: Iterable[str], *, limit: int = MAX_TASKS) -> list[Task]:
    """Перетворити рядки плану на задачі зі станами."""
    tasks: list[Task] = []
    for step in steps or ():
        clean = _clean_task(step)
        if not clean:
            continue
        tasks.append(Task(text=clean, index=len(tasks)))
        if len(tasks) >= limit:
            break
    return tasks


# ── Сесія ─────────────────────────────────────────────────────────────────

@dataclass
class DeepSession:
    """Стан одного сеансу глибокого аналізу.

    Живе від моменту, коли користувач дав складну задачу, до завершення
    виконання. Чат малює його через :class:`deep_view.DeepCard`.
    """

    goal: str = ""
    phase: str = PHASE_ANALYSIS
    tasks: list[Task] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    #: Скільки наративів (проміжних думок) уже показано.
    narrations: int = 0
    #: Чи план уже показано користувачу.
    plan_shown: bool = False
    error: str = ""

    # ── час ───────────────────────────────────────────────────────────────
    @property
    def elapsed(self) -> float:
        end = self.finished_at or time.time()
        return max(0.0, end - self.started_at)

    @property
    def elapsed_text(self) -> str:
        return thinking_time(self.elapsed)

    # ── задачі ────────────────────────────────────────────────────────────
    def counts(self) -> dict[str, int]:
        result = {STATE_PENDING: 0, STATE_RUNNING: 0, STATE_DONE: 0,
                  STATE_FAILED: 0}
        for task in self.tasks:
            if task.state in result:
                result[task.state] += 1
        return result

    def summary(self) -> str:
        """«1 у процесі · 7 в очікуванні» — як заголовок панелі задач."""
        counts = self.counts()
        parts: list[str] = []
        if counts[STATE_RUNNING]:
            parts.append(f"{counts[STATE_RUNNING]} у процесі")
        if counts[STATE_DONE]:
            parts.append(f"{counts[STATE_DONE]} готово")
        if counts[STATE_FAILED]:
            parts.append(f"{counts[STATE_FAILED]} з помилкою")
        if counts[STATE_PENDING]:
            parts.append(f"{counts[STATE_PENDING]} в очікуванні")
        return " · ".join(parts) if parts else "задач немає"

    def set_tasks(self, steps: Iterable[str]) -> list[Task]:
        """Задати план і перевести сесію у фазу «план»."""
        self.tasks = build_tasks(steps)
        self.plan_shown = bool(self.tasks)
        self.phase = PHASE_PLAN if self.tasks else PHASE_ANALYSIS
        return self.tasks

    def start_work(self) -> Optional[Task]:
        """Почати першу невиконану задачу (переводить у фазу «виконання»)."""
        task = self.next_pending()
        if task is None:
            return None
        self.phase = PHASE_EXECUTE
        task.state = STATE_RUNNING
        return task

    def next_pending(self) -> Optional[Task]:
        for task in self.tasks:
            if task.state == STATE_PENDING:
                return task
        return None

    def current(self) -> Optional[Task]:
        for task in self.tasks:
            if task.state == STATE_RUNNING:
                return task
        return None

    def task_at(self, index: int) -> Optional[Task]:
        for task in self.tasks:
            if task.index == index:
                return task
        return None

    def mark(self, index: int, state: str) -> Optional[Task]:
        task = self.task_at(index)
        if task is None:
            return None
        task.state = state
        if state == STATE_RUNNING:
            self.phase = PHASE_EXECUTE
        return task

    def finish(self, *, ok: bool = True) -> None:
        """Завершити сесію: закрити поточну задачу, виставити фазу."""
        self.finished_at = time.time()
        current = self.current()
        pending = self.next_pending()
        if ok:
            # Агент отримав увесь план і завершив успішно — решта задач
            # виконана в межах того самого ходу.
            for task in self.tasks:
                if task.state in (STATE_PENDING, STATE_RUNNING):
                    task.state = STATE_DONE
            self.phase = PHASE_DONE
        else:
            if current is not None:
                current.state = STATE_FAILED
            self.phase = PHASE_DONE if pending is None else PHASE_EXECUTE
        self.error = "" if ok else "виконання зупинено"

    @property
    def done(self) -> bool:
        return self.phase == PHASE_DONE


def human_time(seconds: float) -> str:
    """Час по-людськи: 7 хв 0 с · 12 с · 1 год 5 хв."""
    total = int(max(0.0, seconds))
    if total < 60:
        return f"{total} с"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes} хв {secs} с"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} год {minutes} хв"


def thinking_time(seconds: float) -> str:
    """Час для індикатора «Глибоке розмислення в течение …».

    Формат навмисно інший, ніж у :func:`human_time`: там важлива компактність
    («7 хв 0 с»), а тут — точність до хвилини й секунди, як у прикладі
    інтерфейсу: «7м 0с». Поки минає менше хвилини, показуємо секунди.
    """
    total = int(max(0.0, seconds))
    if total < 60:
        return f"{total}с"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}м {secs}с"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}г {minutes}м {secs}с"


# ── Коли вмикати режим ────────────────────────────────────────────────────

#: Явні прохання про план/аналіз — режим вмикається завжди.
DEEP_MARKERS = (
    "/план", "/plan", "/аналіз", "/analyze",
    "склади план", "скласти план", "спершу план", "план і почни",
    "детально проаналізуй", "глибокий аналіз", "подумай крок за кроком",
    "розбий на задачі", "розбий на кроки",
)

#: Слова-вимоги, що роблять задачу «складною».
#:
#: Раніше тут був жорсткий поріг «4+ речення й 3+ різні дієслова», і
#: реальне завдання («об'єднати вкладки… зроби іконки… зроби адаптивний
#: розмір» — 3 речення, 2 дієслова) його НЕ проходило: режим не вмикався
#: на задачі, для якої його й робили. Перевірено на живій моделі.
MANY_TASKS_HINTS = (
    "потрібно", "треба", "зроби", "зробити", "створи", "створити", "додай",
    "додати", "виправ", "виправити", "перевір", "перевірити", "реалізуй",
    "реалізувати", "онови", "оновити", "прибери", "прибрати", "заміни",
    "замінити", "об'єднай", "обєднай", "збери", "налаштуй", "впровадь",
    "дозволь", "дай змогу", "має бути", "має вміти", "хочу",
)

#: Скільки різних вимог достатньо, якщо задача не коротка.
DEMAND_THRESHOLD = 2
#: Мінімальна довжина тексту, після якої взагалі варто дивитись на вимоги.
SUBSTANTIAL_CHARS = 60


def wants_deep_plan(text: str) -> bool:
    """Чи варто вмикати режим глибокого планування для цієї задачі.

    Режим вмикається, коли користувач попросив план явно або коли задача
    справді багатогранна. Пороги відкалібровані на живих запитах
    (перевірено на локальній Qwen2.5-Coder 14B):

    * «запусти тести» (14 символів) — НЕ вмикає: одне доручення;
    * «об'єднай вкладки… зроби іконки… зроби адаптивний розмір»
      (161 символ, 2 вимоги) — вмикає: це вже кілька робіт.
    """
    clean = (text or "").strip()
    if not clean:
        return False
    low = clean.lower()
    if any(marker in low for marker in DEEP_MARKERS):
        return True
    # Велике завдання з попереднього евристичного аналізу.
    if planner.is_big_task(clean):
        return True
    if len(clean) < SUBSTANTIAL_CHARS:
        return False
    # Кілька різних вимог у змістовному тексті — привід спланувати.
    demands = sum(1 for hint in MANY_TASKS_HINTS if hint in low)
    return demands >= DEMAND_THRESHOLD


def goal_from(text: str, *, limit: int = 240) -> str:
    """Коротка ціль для блоку «Поточна ціль»."""
    clean = " ".join((text or "").split())
    # Прибираємо службові префікси, щоб ціль читалась як твердження.
    clean = re.sub(r"^(будь ласка|прошу|треба|потрібно)[,:\s]+", "", clean, flags=re.I)
    if not clean:
        return ""
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


# ── План від моделі ───────────────────────────────────────────────────────

#: Скільки файлів проєкту показуємо моделі як контекст.
PROJECT_CONTEXT_FILES = 40


def project_context(root: Any, *, limit: int = PROJECT_CONTEXT_FILES) -> str:
    """Короткий опис проєкту для запиту плану.

    Навіщо це: без контексту локальна модель вигадує стек. Перевірено на
    живій Qwen2.5-Coder 14B: на запит про Tkinter-проєкт вона склала план
    «додати HTML-структуру, CSS-стилі, JavaScript-код» — тобто планувала
    вебсайт замість десктопного застосунку. З описом стеку й списком
    файлів план стає по тому самому проєкту.

    Повертає порожній рядок, якщо теку не передано або вона недоступна —
    тоді план складається як раніше, без контексту.
    """
    if root is None:
        return ""
    try:
        folder = Path(root)
        if not folder.is_dir():
            # Неіснуюча тека не має давати «Мова/стек: код» — це вигадка,
            # а не контекст. Краще порожньо: план тоді складеться без
            # обмежень, ніж з хибним описом стеку.
            return ""
        from . import auto_setup

        profile = auto_setup.profile_project(folder)
    except Exception:  # noqa: BLE001 - контекст не має ламати планування
        LOG.debug("Профіль проєкту недоступний", exc_info=True)
        return ""
    parts: list[str] = []
    try:
        parts.append(f"Мова/стек: {profile.language_label}")
        if profile.frameworks:
            parts.append("Фреймворки: " + ", ".join(sorted(profile.frameworks)[:6]))
        if profile.entry_points:
            names = ", ".join(Path(str(p)).name for p in profile.entry_points[:4])
            parts.append(f"Точки входу: {names}")
    except Exception:  # noqa: BLE001
        pass
    # Список файлів — найважливіше: модель бачить реальні назви модулів.
    try:
        files = sorted(
            p.relative_to(folder).as_posix()
            for p in folder.rglob("*")
            if p.is_file()
            and p.suffix in {".py", ".js", ".ts", ".html", ".css", ".md", ".json"}
            and not any(part in {".venv", "node_modules", "__pycache__", ".git",
                                 ".buildtmp", "userdata", "dist", "build"}
                        for part in p.parts)
        )[:limit]
        if files:
            parts.append("Файли проєкту: " + ", ".join(files))
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(parts)


#: Доповнення до запиту плану: тримає модель у межах конкретного проєкту.
PLAN_CONTEXT_HEAD = (
    "Ти плануєш роботу над конкретним проєктом. Спирайся ЛИШЕ на його стек і "
    "файли нижче: не вигадуй інших мов, фреймворків чи технологій. Якщо це "
    "Python-проєкт — кроки мають бути про Python-модулі, а не про HTML/CSS/JS.\n\n"
)


def plan_tasks(goal: str, llm_settings: Any, *, timeout: int = 180,
               temperature: float = 0.2, root: Any = None) -> tuple[list[str], str]:
    """Попросити модель скласти план. Повертає (кроки, помилка).

    Окремий короткий запит, а не частина основного циклу агента: так план
    з'являється швидко й не змішується з виконанням. Помилку повертаємо
    текстом, а не винятком — чат має показати причину й працювати далі
    без плану.

    ``root`` — тека проєкту. Якщо передана, до запиту додається стек і
    список файлів: без цього модель планує «взагалі», часто не той стек.
    """
    clean = (goal or "").strip()
    if not clean:
        return [], "порожня задача"
    try:
        from .llm_client import LLMClient, LLMError
    except ImportError as exc:  # pragma: no cover - клієнт завжди є
        return [], str(exc)
    context = project_context(root)
    prompt = planner.PLAN_PROMPT
    if context.strip():
        prompt = PLAN_CONTEXT_HEAD + context + "\n\n" + planner.PLAN_PROMPT
    try:
        client = LLMClient(
            getattr(llm_settings, "base_url", ""),
            getattr(llm_settings, "model", ""),
            getattr(llm_settings, "api_key", ""),
            temperature=temperature,
            max_tokens=1200,
            timeout=timeout,
        )
        result = client.chat([{"role": "user", "content": prompt + clean}])
        steps = planner.steps_from_answer(result.content)
    except LLMError as exc:
        LOG.info("План не склався: %s", exc)
        return [], str(exc)
    except Exception as exc:  # noqa: BLE001 - план не має ламати чат
        LOG.warning("Помилка планування: %s", exc, exc_info=True)
        return [], f"{type(exc).__name__}: {exc}"
    if not steps:
        return [], "модель не повернула кроків"
    return steps, ""


def goals_text(goal: str, *, limit: int = 96) -> str:
    """Однорядковий варіант цілі для заголовка."""
    clean = " ".join((goal or "").split())
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


__all__ = [
    "CAT_APP",
    "CAT_EDIT",
    "CAT_LABELS",
    "CAT_OTHER",
    "CAT_ORDER",
    "CAT_READ",
    "CAT_RUN",
    "CAT_SEARCH",
    "DEEP_MARKERS",
    "DeepSession",
    "MAX_TASKS",
    "PHASE_ANALYSIS",
    "PHASE_DONE",
    "PHASE_EXECUTE",
    "PHASE_IDLE",
    "PHASE_PLAN",
    "STATE_DONE",
    "STATE_FAILED",
    "STATE_MARKS",
    "STATE_PENDING",
    "STATE_RUNNING",
    "TOOL_CATEGORIES",
    "Task",
    "build_tasks",
    "category_of",
    "goal_from",
    "goals_text",
    "group_title",
    "human_time",
    "plan_tasks",
    "thinking_time",
    "wants_deep_plan",
]
