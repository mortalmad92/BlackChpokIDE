"""Пакет знань проєкту: перевірені факти, які агент кладе собі в пам'ять.

Навіщо це потрібно. Локальна модель не знає нічого про ЦЕЙ проєкт: ні де
лежить черга, ні як запускати тести, ні які домовленості вже ухвалені. Кожне
нове завдання вона починає з нуля — читає ті самі файли, припускається тих
самих помилок і повторює роботу, яку вже зроблено. Довгострокова пам'ять
(NEUROMESH) це лікує, але лише тоді, коли в ній є ЩО шукати.

Цей модуль наповнює пам'ять базовими знаннями про проєкт. Головне правило —
**жодного вигаданого факту**: кожне твердження супроводжується перевіркою
по справжньому файлу. Якщо перевірка не проходить (файл перейменовано,
рядок зник), факт НЕ записується, а список «застарілих» повертається
викликачу. Це принципово: пам'ять, у якій лежать неправдиві факти, гірша за
порожню — модель спиратиметься на них упевнено й помилятиметься.

Що ще важливо:

* **ідемпотентність** — повторний запуск не плодить дублікати: сховище саме
  відсіює однаковий зміст (``content_hash``/``fingerprint``), а тут ще й
  ставиться стабільне ``provenance`` з ключем факту;
* **без tkinter і без мережі** — модуль перевіряється тестами на звичайному
  тимчасовому проєкті;
* **без вигадок про модель** — «навчання» тут означає рівно те, що в
  реальних агентних системах: перевірені факти лягають у пам'ять і
  підкладаються в контекст наступного разу (див. ``memory_bridge``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

__all__ = [
    "Fact",
    "KNOWLEDGE",
    "SeedReport",
    "knowledge_facts",
    "seed",
    "stale_facts",
]

LOG = logging.getLogger("blackchpok.knowledge")

#: Джерело в пам'яті — щоб у панелі було видно, звідки взявся факт.
SOURCE = "пакет знань проєкту"


@dataclass(frozen=True)
class Fact:
    """Одне твердження про проєкт разом зі способом його перевірити."""

    #: Стабільний ключ (не залежить від тексту — щоб факт не дублювався).
    key: str
    #: Текст факту: саме його побачить модель у контексті.
    content: str
    #: Тип спогаду з ``pcmm.models.KINDS``.
    kind: str = "fact"
    #: Файли, яких факт стосується (для пошуку за файлом).
    files: tuple[str, ...] = ()
    confidence: float = 0.75
    #: Перевірка: (тека проєкту) → True, якщо факт усе ще правдивий.
    check: Callable[[Path], bool] | None = field(default=None, compare=False)


def _text_of(root: Path, name: str) -> str:
    """Прочитати файл проєкту (порожній рядок, якщо його немає)."""
    try:
        return (Path(root) / name).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _has(name: str, *needles: str) -> Callable[[Path], bool]:
    """Перевірка «у файлі є ВСІ ці підрядки»."""
    def check(root: Path) -> bool:
        body = _text_of(root, name)
        return bool(body) and all(needle in body for needle in needles)
    return check


def _exists(*names: str) -> Callable[[Path], bool]:
    """Перевірка «ці файли (і теки) існують»."""
    def check(root: Path) -> bool:
        return all((Path(root) / name).exists() for name in names)
    return check


def _and(*checks: Callable[[Path], bool]) -> Callable[[Path], bool]:
    def check(root: Path) -> bool:
        return all(item(root) for item in checks)
    return check


#: Базові знання про цей проєкт.
#:
#: Кожен запис — «твердження + спосіб перевірки». Твердження сформульовані
#: так, як їх має прочитати локальна модель: коротко, дієво, з назвою файлу.
#: Список навмисно невеликий: 20 точних фактів корисніші за 200 загальних.
KNOWLEDGE: tuple[Fact, ...] = (
    # ── Як запускати тести (найчастіша точка зациклення) ────────────────
    Fact(
        key="tests.command",
        content=(
            "Тести цього проєкту запускаються так: "
            "`.venv\\Scripts\\python.exe -m unittest discover -s tests -p \"test_*.py\" -v`, "
            "а повний набір — `.venv\\Scripts\\python.exe tests\\run_all.py --fast`. "
            "Голий `python` — це Python 3.14 ззовні, без потрібних пакетів."
        ),
        kind="constraint", files=("tests/run_all.py",), confidence=0.9,
        check=_exists("tests", "tests/run_all.py"),
    ),
    Fact(
        key="tests.no_init",
        content=(
            "У теці `tests` НЕМАЄ `__init__.py`, тому `python -m unittest discover` "
            "без `-s tests` завжди дає «Ran 0 tests» (код 5). Це не помилка коду: "
            "додай `-s tests`, і тести знайдуться."
        ),
        kind="constraint", files=("tests",), confidence=0.9,
        check=_exists("tests"),
    ),
    Fact(
        key="tests.pytest_absent",
        content=(
            "`pytest` у проєкті НЕ встановлено: `import pytest` дає "
            "`ModuleNotFoundError`. Запускай тести через `unittest`, а не `pytest`."
        ),
        kind="constraint", files=("requirements.txt",), confidence=0.85,
        check=_exists("requirements.txt"),
    ),
    # ── Архітектура: де що лежить ───────────────────────────────────────
    Fact(
        key="arch.agent",
        content=(
            "`blackchpok_ide/agent.py` — серце агента: клас `AgentRunner`, цикл "
            "`_loop`, захист від зациклення `_RepeatGuard`, автозвільнення "
            "контексту `auto_free_context`."
        ),
        kind="fact", files=("blackchpok_ide/agent.py",), confidence=0.9,
        check=_has("blackchpok_ide/agent.py", "class AgentRunner", "_RepeatGuard",
                   "def auto_free_context"),
    ),
    Fact(
        key="arch.queue",
        content=(
            "Черга завдань — `blackchpok_ide/queue_engine.py` (клас `TaskQueue`, "
            "файл `queue.json` у теці даних застосунку). Статуси: очікує, аналіз, "
            "виконується, перевірка, готово, помилка."
        ),
        kind="fact", files=("blackchpok_ide/queue_engine.py",), confidence=0.9,
        check=_has("blackchpok_ide/queue_engine.py", "class TaskQueue", "PENDING"),
    ),
    Fact(
        key="arch.executor",
        content=(
            "`blackchpok_ide/task_executor.py` веде кроки черги: не вірить «готово» "
            "на слово, перевіряє результат на диску (`TaskValidator.validate`), "
            "обмежує кількість спроб."
        ),
        kind="fact", files=("blackchpok_ide/task_executor.py",), confidence=0.9,
        check=_has("blackchpok_ide/task_executor.py", "class QueueExecutor",
                   "class TaskValidator"),
    ),
    Fact(
        key="arch.autonomous",
        content=(
            "Автономний режим — `blackchpok_ide/autonomous.py`: сканер "
            "`analyse_project` шукає ідеї (позначки TODO/FIXME лише в коментарях, "
            "проковтнуті винятки, print(), завеликі файли, модулі без тестів) і "
            "ставить їх у ту саму чергу через `AutonomousEngine.seed`."
        ),
        kind="fact", files=("blackchpok_ide/autonomous.py",), confidence=0.9,
        check=_has("blackchpok_ide/autonomous.py", "def analyse_project",
                   "class AutonomousEngine", "def seed"),
    ),
    Fact(
        key="arch.memory",
        content=(
            "Довгострокова пам'ять — NEUROMESH: `blackchpok_ide/pcmm/service.py` "
            "(клас `Neuromesh`, методи `remember`, `search`, `project_context`) і "
            "міст `blackchpok_ide/memory_bridge.py`, який підкладає спогади в "
            "контекст до початку дії."
        ),
        kind="fact", files=("blackchpok_ide/pcmm/service.py",
                            "blackchpok_ide/memory_bridge.py"), confidence=0.9,
        check=_and(_has("blackchpok_ide/pcmm/service.py", "class Neuromesh", "def search"),
                   _has("blackchpok_ide/memory_bridge.py", "class MemoryBridge")),
    ),
    Fact(
        key="arch.selflearning",
        content=(
            "Самонавчання — `blackchpok_ide/selflearning.py`: з фактів ходу "
            "робляться короткі уроки (тип `lesson` у пам'яті) і підкладаються "
            "в контекст наступного разу через `SelfLearning.hints`."
        ),
        kind="fact", files=("blackchpok_ide/selflearning.py",), confidence=0.9,
        check=_has("blackchpok_ide/selflearning.py", "def extract_lessons",
                   "class SelfLearning"),
    ),
    Fact(
        key="arch.tools",
        content=(
            "Інструменти агента — `blackchpok_ide/agent_tools.py` (реєстр "
            "`read_file/write_file/edit_file/list_dir/search_text/run_command/"
            "python_check/memory_*`). Схеми для моделі — `tool_specs.py`, "
            "звуження набору за наміром — `tool_select.py`."
        ),
        kind="fact", files=("blackchpok_ide/agent_tools.py",
                            "blackchpok_ide/tool_select.py"), confidence=0.85,
        check=_and(_has("blackchpok_ide/agent_tools.py", "class ToolRegistry"),
                   _has("blackchpok_ide/tool_select.py", "def select_names")),
    ),
    # ── Домовленості, які не можна ламати ───────────────────────────────
    Fact(
        key="rule.endless_chat",
        content=(
            "Контракт нескінченного чату (docs/ENDLESS_CHAT.md) забороняє "
            "викидати повідомлення з історії без архівування в хроніку, "
            "NEUROMESH і RAG, забороняє відхиляти запит під час роботи агента "
            "(він стає в гарячу чергу) і забороняє дві стелі `max_tokens` для "
            "локальних і хмарних моделей."
        ),
        kind="constraint", files=("docs/ENDLESS_CHAT.md",), confidence=0.95,
        check=_has("docs/ENDLESS_CHAT.md", "Нескінченний чат", "гаряча черга"),
    ),
    Fact(
        key="rule.tests_not_weakened",
        content=(
            "Правило проєкту: якщо тест падає — виправляй ПРИЧИНУ в коді, а не "
            "тест; вимикати й видаляти тести, щоб «позеленіло», заборонено."
        ),
        kind="constraint", files=("docs/AGENTS.md",), confidence=0.95,
        check=_has("docs/AGENTS.md", "виправ причину"),
    ),
    Fact(
        key="rule.no_false_success",
        content=(
            "Крок черги стає «готово» лише тоді, коли результат підтверджено на "
            "диску. Відповідь «Готово.» без змінених файлів — це невдача, а не "
            "успіх."
        ),
        kind="constraint", files=("blackchpok_ide/task_executor.py",), confidence=0.9,
        check=_has("blackchpok_ide/task_executor.py", "не вірити «готово»",
                   "class TaskValidator"),
    ),
    Fact(
        key="rule.marker_comments_only",
        content=(
            "Позначку боргу (TODO/FIXME/HACK/XXX) сканер автономного режиму "
            "вважає маркером лише на початку КОМЕНТАРЯ (`# TODO`, `// FIXME`). "
            "Підрядок TODO всередині слова (напр. `mastodon`) або в докстрінгу — "
            "не привід щось правити."
        ),
        kind="constraint", files=("blackchpok_ide/autonomous.py",), confidence=0.9,
        check=_has("blackchpok_ide/autonomous.py", "_MARKER_RE"),
    ),
    # ── Робочі правила для моделі ───────────────────────────────────────
    Fact(
        key="work.edit_not_rewrite",
        content=(
            "Для правки наявного файлу використовуй `edit_file` з точними "
            "`old_string`/`new_string`. Повний `write_file` на наявний тестовий "
            "файл стирає його зміст: саме так у цьому проєкті втрачали реальні "
            "перевірки в `tests/test_calc.py`."
        ),
        kind="lesson", files=("tests/test_calc.py",), confidence=0.8,
        check=_exists("tests"),
    ),
    Fact(
        key="work.check_syntax",
        content=(
            "`py_compile` перевіряє лише синтаксис. Файл із `return ` у кінці "
            "функції компілюється, але функція повертає `None` — тому після "
            "правки запускай тести, а не лише `python_check`."
        ),
        kind="lesson", files=("blackchpok_ide/agent_tools.py",), confidence=0.8,
        check=_has("blackchpok_ide/agent_tools.py", "python_check"),
    ),
    Fact(
        key="work.repeat_guard",
        content=(
            "Якщо інструмент відповів тим самим результатом 3 рази поспіль — "
            "це зациклення: зміни аргументи, візьми інший інструмент або чесно "
            "скажи, чого бракує. Повтор того самого виклику не допоможе."
        ),
        kind="lesson", files=("blackchpok_ide/agent.py",), confidence=0.85,
        check=_has("blackchpok_ide/agent.py", "REPEAT_LIMIT"),
    ),
    Fact(
        key="work.no_test_rewrite_loop",
        content=(
            "Не переписуй тестовий файл заради того, щоб тести «знайшлися». "
            "Якщо `unittest` каже «Ran 0 tests» — проблема в теці запуску "
            "(`-s tests`), а не у вмісті файлу."
        ),
        kind="lesson", files=("tests",), confidence=0.85,
        check=_exists("tests"),
    ),
)


@dataclass
class SeedReport:
    """Що з пакетом знань сталося під час запису."""

    added: int = 0
    confirmed: int = 0
    stale: list[str] = field(default_factory=list)
    failed: int = 0
    total: int = 0

    def describe(self) -> str:
        """Один рядок для журналу й панелі пам'яті."""
        parts = [f"Пакет знань: {self.added} нових"]
        if self.confirmed:
            parts.append(f"{self.confirmed} підтверджено")
        if self.stale:
            parts.append(f"{len(self.stale)} застарілих")
        if self.failed:
            parts.append(f"{self.failed} не записалось")
        return ", ".join(parts) + "."


def knowledge_facts(root: Path | str | None = None, *,
                    facts: Iterable[Fact] = KNOWLEDGE) -> list[Fact]:
    """Перевірені факти для цього проєкту (без неправдивих).

    ``root=None`` — не перевіряти нічого й віддати весь список (так зручно
    для перегляду в тестах). З текою — лишаються лише ті факти, чия перевірка
    пройшла.
    """
    items = list(facts)
    if root is None:
        return items
    base = Path(root)
    if not base.is_dir():
        return []
    result: list[Fact] = []
    for fact in items:
        if fact.check is None:
            result.append(fact)
            continue
        try:
            if fact.check(base):
                result.append(fact)
        except OSError:
            LOG.debug("Перевірка факту %s не вдалась", fact.key, exc_info=True)
    return result


def stale_facts(root: Path | str | None, *,
                facts: Iterable[Fact] = KNOWLEDGE) -> list[Fact]:
    """Факти, чия перевірка більше не проходить (їх не можна записувати)."""
    items = list(facts)
    if root is None:
        return []
    base = Path(root)
    fresh = {fact.key for fact in knowledge_facts(base, facts=items)}
    return [fact for fact in items if fact.key not in fresh]


def seed(service: Any, root: Path | str | None, *,
         facts: Iterable[Fact] = KNOWLEDGE, dry_run: bool = False) -> SeedReport:
    """Записати перевірені знання в пам'ять (NEUROMESH).

    ``service`` — будь-який об'єкт із ``remember`` (такий, як
    :class:`pcmm.service.Neuromesh`). Помилка одного факту не зриває решту:
    без пам'яті агент працює як раніше, лише без підказок.
    """
    items = list(facts)
    report = SeedReport(total=len(items))
    if dry_run:
        report.added = len(knowledge_facts(root, facts=items))
        report.stale = [fact.key for fact in stale_facts(root, facts=items)]
        return report

    remember = getattr(service, "remember", None)
    available = callable(remember) and bool(
        getattr(service, "ready", lambda: True)())
    for fact in items:
        if fact.check is not None:
            try:
                if not fact.check(Path(root) if root is not None else Path(".")):
                    report.stale.append(fact.key)
                    continue
            except OSError:
                report.stale.append(fact.key)
                continue
        if not available:
            report.failed += 1
            continue
        try:
            outcome = remember(
                fact.content, kind=fact.kind, source=SOURCE,
                provenance=f"knowledge:{fact.key}",
                confidence=float(fact.confidence),
                files=list(fact.files), tags=["знання", fact.key],
            )
        except TypeError:
            # Старіший сервіс без частини параметрів.
            try:
                outcome = remember(fact.content, kind=fact.kind, source=SOURCE)
            except Exception:                        # noqa: BLE001
                LOG.debug("Факт %s не записано", fact.key, exc_info=True)
                report.failed += 1
                continue
        except Exception:                            # noqa: BLE001
            LOG.debug("Факт %s не записано", fact.key, exc_info=True)
            report.failed += 1
            continue
        if isinstance(outcome, dict) and outcome.get("created") is False:
            report.confirmed += 1
        elif isinstance(outcome, dict) and outcome.get("duplicate"):
            report.confirmed += 1
        else:
            report.added += 1
    return report


def facts_for_files(paths: Sequence[str], *,
                    facts: Iterable[Fact] = KNOWLEDGE) -> list[Fact]:
    """Факти, що стосуються цих файлів (для підказки перед дією)."""
    wanted = {str(item).replace("\\", "/") for item in paths or () if str(item).strip()}
    if not wanted:
        return []
    result: list[Fact] = []
    for fact in facts:
        files = {name.replace("\\", "/") for name in fact.files}
        if files & wanted:
            result.append(fact)
    return result
