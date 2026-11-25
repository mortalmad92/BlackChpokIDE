"""Безперервний автономний покращувач проєкту (Continuous Autonomous Improver).

Це «мозок» автономного режиму. Він вирішує, ЩО робити далі, веде короткий
план людською мовою, пише журнал дій і наповнює наявну :class:`TaskQueue`.
Сам код він не редагує: правки робить той самий агент, що й у чаті, тим
самим інструментарієм (``read_file``, ``edit_file``, ``write_file``), тож
усе видно в редакторі — відкрита вкладка, підсвітка змін, diff у стрічці.

Свідомі обмеження (щоб модуль лишався перевірюваним):

* немає tkinter — жодного віджета, лише стан;
* немає власного потоку — рушій крокує за викликом ведучого (вікна IDE),
  тому його поведінку можна перевірити тестами без ``mainloop``;
* один проєкт за раз: автономний режим неможливо увімкнути для двох тек
  одночасно, і це перевіряється тут, а не лише в інтерфейсі.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from .queue_engine import ORIGIN_AGENT, ORIGIN_USER, TaskQueue

LOG = logging.getLogger("blackchpok.autonomous")

# ── Стан режиму ────────────────────────────────────────────────────────────
STATE_OFF = "вимкнено"
STATE_RUNNING = "працює"
STATE_STOPPING = "зупиняється"

# ── Види робіт (для позначок у плані й журналі) ────────────────────────────
KIND_ANALYSIS = "аналіз"
KIND_CODE = "код"
KIND_RESEARCH = "дослідження"
KIND_VERIFY = "перевірка"

#: Скільки пунктів плану показуємо (решта — «далі за планом»).
MAX_PLAN_ITEMS = 8
#: Скільки записів журналу тримаємо в пам'яті.
MAX_LOG = 300
#: Скільки задач агент ставить собі за один цикл.
SEED_PER_CYCLE = 2
#: Скільки разів ту саму ідею можна поставити в чергу (захист від циклу).
MAX_REPEATS = 2

#: Позначки боргу, які сканер узагалі вважає маркером.
DEBT_MARKERS = ("TODO", "FIXME", "HACK", "XXX")

#: Маркер рахуємо ЛИШЕ як початок коментаря: ``# TODO``, ``// FIXME``,
#: ``/* HACK``, ``<!-- XXX``, ``-- TODO`` (SQL/Lua) і ``; TODO``.
#:
#: Навіщо так суворо. Раніше маркер шукався як підрядок у рядку, і в чергу
#: пішли задачі, які неможливо виконати:
#:
#: * ``social.py``: рядок ``"mastodon": …`` містить «TODO» всередині слова
#:   MAS-TODO-N — «прибрати позначку» означало б зламати ключ;
#: * ``stream_apply.py``: коментар ``# ``\uXXXX`` …`` містить «XXX»;
#: * докстрінги з прикладами («… доказом «line 120 has TODO»»);
#: * тестові дані ``{"old_string": "TODO", …}``.
#:
#: Модель бралася за таку задачу, «правила» рядок, маркер лишався — і сканер
#: ставив її знову. Живий прогін 21.11.2026: 14 перезаписів одного
#: тест-файлу й 21 запуск тієї самої команди за годину.
_MARKER_RE = re.compile(
    r"(?:#|//|/\*|<!--|--|;)\s*(?P<marker>TODO|FIXME|HACK|XXX)\b",
    re.IGNORECASE)

#: Теки, які сканер не читає: сміття, залежності, збірки.
SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".buildtmp", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "userdata", ".mcp_rag", "assets", ".idea", ".vscode",
})
#: Розширення, які сканер вважає кодом.
CODE_SUFFIXES = frozenset({".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".vue"})
#: Скільки файлів максимум оглядаємо за один скан.
MAX_SCAN_FILES = 600
#: Файл, більший за це, не читаємо (це майже завжди дані, а не код).
MAX_FILE_BYTES = 400_000


# ─────────────────────────────────────────────────────────────────────────────
# Модель даних
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Candidate:
    """Одна знайдена ідея покращення."""

    title: str                      # людською мовою: «Прибрати TODO у x.py:12»
    instruction: str                # точне завдання для агента
    kind: str = KIND_CODE
    path: str = ""                  # файл, якого стосується ідея
    weight: float = 1.0            # більший — важливіший
    #: Номер рядка, якщо ідея стосується конкретного місця (0 — не стосується).
    line: int = 0
    #: Текст маркера боргу (``TODO``, ``FIXME``…), якщо це позначка.
    marker: str = ""
    #: Вид ідеї — стабільна ознака БЕЗ тексту рядка й без номера рядка.
    category: str = ""

    def key(self) -> str:
        """Ключ для захисту від повторів.

        Навіщо окремо від :attr:`title`. Колись ключем був увесь заголовок,
        а заголовок містить ТЕКСТ рядка з позначкою. Модель «правила» рядок
        (додавала слово, перейменовувала клас) — текст у заголовку змінювався,
        ключ ставав новим, лічильник ``MAX_REPEATS`` обнулявся, і та сама
        робота знову йшла в чергу. Живий прогін: цикл на ``test_sample.py``
        перезаписував файл ~14 разів за годину.

        Тепер ключ — «вид ідеї + файл» (для позначок — ще й маркер): він не
        залежить від того, як саме модель переписала рядок.
        """
        kind = self.category or self.kind
        if self.category == "marker" and self.marker:
            return f"{kind}|{self.path}|{self.marker.upper()}"
        return f"{kind}|{self.path}"


@dataclass
class PlanItem:
    """Пункт плану людською мовою."""

    text: str
    kind: str = KIND_ANALYSIS
    state: str = "далі"            # «зараз» | «далі» | «готово»
    origin: str = ORIGIN_AGENT


@dataclass
class LogEntry:
    """Один рядок журналу дій."""

    text: str
    at: float = field(default_factory=time.time)
    kind: str = "info"             # info | ok | error | user | stop

    @property
    def clock(self) -> str:
        try:
            return time.strftime("%H:%M:%S", time.localtime(self.at))
        except (OSError, ValueError):
            return ""


@dataclass
class Focus:
    """Що агент робить просто зараз (для заголовка панелі)."""

    text: str = ""
    kind: str = ""
    file: str = ""
    since: float = field(default_factory=time.time)

    @property
    def elapsed_text(self) -> str:
        seconds = max(0, int(time.time() - self.since))
        if seconds < 60:
            return f"{seconds} с"
        return f"{seconds // 60} хв"


# ─────────────────────────────────────────────────────────────────────────────
# Сканер проєкту: де взагалі є що покращувати
# ─────────────────────────────────────────────────────────────────────────────

def _iter_code_files(root: Path, *, limit: int = MAX_SCAN_FILES) -> list[Path]:
    """Файли коду під ``root`` без сміття, у стабільному порядку."""
    root = Path(root)
    found: list[Path] = []
    try:
        for path in sorted(root.rglob("*")):
            if len(found) >= limit:
                break
            try:
                if not path.is_file():
                    continue
            except OSError:
                continue
            if path.suffix.lower() not in CODE_SUFFIXES:
                continue
            parts = {part.lower() for part in path.relative_to(root).parts[:-1]}
            if parts & SKIP_DIRS:
                continue
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            found.append(path)
    except OSError:
        LOG.debug("Скан проєкту перервано", exc_info=True)
    return found


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _relative(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return path.name


def analyse_project(root: Path, *, limit: int = 24) -> list[Candidate]:
    """Знайти конкретні ідеї покращення в теці проєкту.

    Сканер навмисно простий і передбачуваний: він не «розуміє» код, а
    шукає добре відомі ознаки боргу — позначки TODO/FIXME **у коментарях**,
    проковтнуті винятки, ``print`` замість журналу, дуже довгі файли й
    модулі без тестів. Кожна ідея стає окремою задачею агента, і саме агент
    вирішує, як її виконати.

    Вид ідеї (``category``) — стабільна ознака для дедуплікації: вона не
    залежить від тексту рядка, тому правка рядка не робить із тієї самої
    задачі «нову».
    """
    root = Path(root)
    if not root.exists():
        return []
    files = _iter_code_files(root)
    ideas: list[Candidate] = []

    for path in files:
        rel = _relative(root, path)
        text = _read(path)
        if not text:
            continue
        lines = text.splitlines()

        # 1. Позначки боргу: TODO / FIXME / HACK — лише в КОМЕНТАРЯХ.
        for number, line in enumerate(lines, start=1):
            found = _MARKER_RE.search(line)
            if not found:
                continue
            marker = found.group("marker").upper()
            clean = " ".join(line.strip().lstrip("#/ ").split())[:140]
            ideas.append(Candidate(
                title=f"Розібрати позначку {marker} у {rel}:{number}",
                instruction=(
                    f"У файлі {rel} на рядку {number} є позначка {marker}: «{clean}». "
                    f"Прочитай файл інструментом read_file, зроби саме те, що просить "
                    f"позначка, прибери її й перевір синтаксис (python -m py_compile, "
                    f"якщо це .py). Змінюй лише цей файл."
                ),
                kind=KIND_CODE, path=rel, weight=3.0,
                line=number, marker=marker, category="marker"))
            break        # одна ідея на файл, щоб не завалити чергу

        # 2. Проковтнуті винятки: except ...: pass
        swallowed = _count_swallowed(lines)
        if swallowed >= 3:
            ideas.append(Candidate(
                title=f"Зробити видимими приховані помилки у {rel} ({swallowed} місць)",
                instruction=(
                    f"У файлі {rel} знайдено {swallowed} місць, де виняток "
                    f"проковтується (except → pass). Прочитай файл, додай "
                    f"LOG.debug або LOG.warning із контекстом у кожне таке місце, "
                    f"де це справді діагностика. Не змінюй поведінку успішного шляху."
                ),
                kind=KIND_CODE, path=rel, weight=2.4, category="swallowed"))

        # 3. print() замість журналу в бібліотечному коді.
        if path.suffix.lower() == ".py":
            prints = sum(1 for line in lines
                         if line.lstrip().startswith("print(") and "def " not in line)
            if prints >= 6:
                ideas.append(Candidate(
                    title=f"Замінити print() на журнал у {rel} ({prints} викликів)",
                    instruction=(
                        f"У файлі {rel} є {prints} викликів print(). Прочитай файл і "
                        f"заміни їх на logging (LOG.info/LOG.warning) з тим самим "
                        f"текстом. Якщо logging ще не налаштований у файлі — додай "
                        f"LOG = logging.getLogger(...). Перевір синтаксис."
                    ),
                    kind=KIND_CODE, path=rel, weight=1.8, category="prints"))

        # 4. Дуже довгий файл: його важко читати й супроводжувати.
        if len(lines) > 900:
            ideas.append(Candidate(
                title=f"Розділити завеликий файл {rel} ({len(lines)} рядків)",
                instruction=(
                    f"Файл {rel} має {len(lines)} рядків. Прочитай його структуру "
                    f"інструментом project_tree/read_file і запропонуй у відповіді "
                    f"план розділення на менші модулі. Нічого не переписуй без "
                    f"перевірки: спершу план, далі — один безпечний крок "
                    f"(винести допоміжні функції в новий модуль і оновити імпорти)."
                ),
                kind=KIND_CODE, path=rel, weight=1.2, category="huge_file"))

        # 5. Модуль без тестів: найдешевший спосіб зменшити ризик.
        if path.suffix.lower() == ".py" and path.parent.name not in SKIP_DIRS:
            tests_dir = root / "tests"
            if tests_dir.is_dir() and path.stem not in ("__init__", "conftest"):
                if not (tests_dir / f"test_{path.stem}.py").exists():
                    ideas.append(Candidate(
                        title=f"Додати тести для {rel}",
                        instruction=(
                            f"Для модуля {rel} немає тестів. Прочитай модуль і додай "
                            f"файл tests/test_{path.stem}.py з кількома тестами на "
                            f"найважливіші функції (unittest, без нових залежностей). "
                            f"Потім запусти: python -m unittest tests.test_{path.stem} "
                            f"і виправ падіння, якщо вони через твій же тест."
                        ),
                        kind=KIND_VERIFY, path=rel, weight=2.0, category="missing_tests"))

    # 6. Перевірка, що проєкт узагалі живий після змін.
    if (root / "tests").is_dir():
        ideas.append(Candidate(
            title="Прогнати повний набір тестів",
            instruction=("Запусти повний набір тестів: python -m unittest discover -s tests. "
                         "Якщо є падіння — знайди причину й виправ код (не тести). "
                         "Якщо все зелене — коротко відзвітуй кількість тестів."),
            kind=KIND_VERIFY, path="tests", weight=0.9))

    ideas.sort(key=lambda idea: (-idea.weight, idea.path, idea.title))
    # Дедуплікація за заголовком: той самий файл міг дати кілька схожих ідей.
    unique: list[Candidate] = []
    seen: set[str] = set()
    for idea in ideas:
        key = idea.key()
        if key in seen:
            continue
        seen.add(key)
        unique.append(idea)
        if len(unique) >= max(1, int(limit)):
            break
    return unique


def _syntax_error_line(src: str) -> tuple[int, str]:
    import ast as _ast
    try:
        _ast.parse(src)
        return 0, ""
    except SyntaxError as exc:
        return int(exc.lineno or 1), str(exc.msg or "SyntaxError")

def _count_swallowed(lines: list[str]) -> int:
    """Порахувати місця «except …: pass» (без важкого розбору AST)."""
    count = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped not in ("pass", "...") or index == 0:
            continue
        previous = lines[index - 1].strip()
        if previous.startswith("except") and previous.endswith(":"):
            count += 1
    return count


def research_ideas(packages: Iterable[str], *, limit: int = 3) -> list[Candidate]:
    """Ідеї з інтернету: кращі практики для залежностей проєкту.

    Сам пошук робить агент своїми інструментами (MCP ``search_web`` або
    вбудований веб-пошук), тому тут ми лише формулюємо задачу — це працює
    навіть без мережі й не гальмує інтерфейс.
    """
    ideas: list[Candidate] = []
    for name in list(packages)[:limit]:
        clean = str(name or "").strip()
        if not clean:
            continue
        ideas.append(Candidate(
            title=f"Знайти кращі практики для {clean}",
            instruction=(
                f"Знайди в інтернеті (інструмент search_web або MCP) актуальні "
                f"кращі практики використання бібліотеки {clean} і перевір, чи "
                f"проєкт їх дотримується. Далі зроби одну конкретну правку в коді, "
                f"якщо знайшов реальну проблему; інакше коротко відзвітуй, що все "
                f"гаразд, і нічого не змінюй."
            ),
            kind=KIND_RESEARCH, path="", weight=1.0))
    return ideas


def project_packages(root: Path, *, limit: int = 6) -> list[str]:
    """Назви залежностей з ``requirements.txt`` (для дослідницьких задач)."""
    names: list[str] = []
    target = Path(root) / "requirements.txt"
    if not target.exists():
        return names
    for line in _read(target).splitlines():
        clean = line.strip()
        if not clean or clean.startswith("#") or clean.startswith("-"):
            continue
        name = clean.split("==")[0].split(">=")[0].split("<")[0].split("[")[0].strip()
        if name and name not in names:
            names.append(name)
        if len(names) >= limit:
            break
    return names


# ─────────────────────────────────────────────────────────────────────────────
# Рушій режиму
# ─────────────────────────────────────────────────────────────────────────────

class AutonomousEngine:
    """Стан автономного режиму й рішення «що робити наступним».

    Ведучий (вікно IDE) кличе :meth:`tick` кілька разів на секунду й
    виконує повернену дію. Уся логіка вибору — тут, тому її видно тестам.
    """

    def __init__(
        self,
        *,
        queue: Optional[TaskQueue] = None,
        scan: Optional[Callable[..., list[Candidate]]] = None,
        on_change: Optional[Callable[[], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.queue = queue if queue is not None else TaskQueue()
        self.scan = scan or analyse_project
        self.on_change = on_change
        self.on_status = on_status
        self.state: str = STATE_OFF
        self.project: Optional[Path] = None
        #: Чат, якому належить режим. Задачі, які він ставить, дістають той
        #: самий ``chat_id``, тож зникають разом із чатом і не виснуть
        #: «сиротами» в панелі «Автоматизації».
        self.chat_id: str = ""
        self.focus = Focus()
        self.plan: list[PlanItem] = []
        self.log_entries: list[LogEntry] = []
        self.touched_files: list[str] = []
        self.cycles = 0
        self.tasks_done = 0
        self.tasks_failed = 0
        self.ideas_total = 0
        self.last_error = ""
        self._seen: dict[str, int] = {}
        self._stop_requested = False

    # ── стан ───────────────────────────────────────────────────────────────
    @property
    def active(self) -> bool:
        return self.state in (STATE_RUNNING, STATE_STOPPING)

    @property
    def stopping(self) -> bool:
        return self.state == STATE_STOPPING

    @property
    def project_text(self) -> str:
        return self.project.name if self.project else ""

    def snapshot(self) -> dict[str, object]:
        """Короткий зріз стану для панелі й статусбара."""
        counts = self.queue.counts_by_origin()
        return {
            "state": self.state,
            "project": self.project_text,
            "focus": self.focus.text,
            "focus_file": self.focus.file,
            "plan": len([item for item in self.plan if item.state != "готово"]),
            "pending_user": counts.get(ORIGIN_USER, 0),
            "pending_agent": counts.get(ORIGIN_AGENT, 0),
            "done": self.tasks_done,
            "failed": self.tasks_failed,
            "cycles": self.cycles,
            "touched": list(self.touched_files[-5:]),
            "error": self.last_error,
        }

    # ── журнал і план ──────────────────────────────────────────────────────
    def log(self, text: str, *, kind: str = "info") -> LogEntry:
        clean = (text or "").strip()
        entry = LogEntry(text=clean, kind=kind)
        if clean:
            self.log_entries.append(entry)
            if len(self.log_entries) > MAX_LOG:
                del self.log_entries[: len(self.log_entries) - MAX_LOG]
            LOG.info("[автономно] %s", clean)
        self._changed()
        return entry

    def _changed(self) -> None:
        if self.on_change is not None:
            try:
                self.on_change()
            except Exception:  # noqa: BLE001 - інтерфейс не має ламати режим
                LOG.debug("on_change автономного режиму впав", exc_info=True)

    def _status(self, text: str) -> None:
        if self.on_status is not None:
            try:
                self.on_status(text)
            except Exception:  # noqa: BLE001
                LOG.debug("on_status автономного режиму впав", exc_info=True)

    def set_plan(self, items: Iterable[tuple[str, str]], *, kind: str = KIND_ANALYSIS,
                 origin: str = ORIGIN_AGENT) -> None:
        """Замінити план. ``items`` — послідовність (текст, вид) або текст."""
        fresh: list[PlanItem] = []
        for index, item in enumerate(items):
            if isinstance(item, str):
                text, item_kind = item, kind
            else:
                text, item_kind = item[0], (item[1] or kind)
            clean = (text or "").strip()
            if not clean:
                continue
            fresh.append(PlanItem(text=clean, kind=item_kind,
                                  state="зараз" if index == 0 else "далі",
                                  origin=origin))
            if len(fresh) >= MAX_PLAN_ITEMS:
                break
        self.plan = fresh
        self._changed()

    def note_action(self, text: str, *, kind: str = KIND_CODE, file: str = "") -> None:
        """Перед кожною новою дією: оновити «зараз» і зсунути решту плану."""
        clean = (text or "").strip()
        if not clean:
            return
        for item in self.plan:
            if item.state == "зараз":
                item.state = "готово"
        self.plan.insert(0, PlanItem(text=clean, kind=kind, state="зараз"))
        del self.plan[MAX_PLAN_ITEMS:]
        self.focus = Focus(text=clean, kind=kind, file=file)
        self.touched_files = ([file] if file else []) + [f for f in self.touched_files
                                                        if f and f != file][:9]
        self.cycles += 1
        self._changed()
        self._status(f"Автономно: {clean}")

    def finish_action(self, *, ok: bool = True, note: str = "") -> None:
        """Позначити поточну дію завершеною."""
        for item in self.plan:
            if item.state == "зараз":
                item.state = "готово" if ok else "далі"
        if ok:
            self.tasks_done += 1
        else:
            self.tasks_failed += 1
        if note:
            self.log(note, kind="ok" if ok else "error")
        else:
            self._changed()

    def note_file(self, path: str) -> None:
        """Запам'ятати файл, який агент зараз править (для журналу й панелі)."""
        clean = (path or "").strip()
        if not clean:
            return
        if clean not in self.touched_files:
            self.touched_files.append(clean)
            del self.touched_files[:-10]
        if self.focus.file != clean:
            self.focus.file = clean
        self._changed()

    # ── керування ──────────────────────────────────────────────────────────
    def can_start(self, project: Path) -> tuple[bool, str]:
        """Чи можна ввімкнути режим для цієї теки (правило одного проєкту)."""
        target = Path(project)
        if not target.is_dir():
            return False, f"Тека не існує: {target}"
        if self.state == STATE_RUNNING and self.project is not None:
            if _same(target, self.project):
                return False, "Автономний режим уже працює для цього проєкту."
            return False, (f"Автономний режим уже увімкнено для «{self.project.name}». "
                           f"Спершу зупини його — одночасно може працювати лише один проєкт.")
        return True, ""

    def start(self, project: Path) -> tuple[bool, str]:
        # AUTONOMOUS_IDE_GUARD
        _ide_root = Path(__file__).resolve().parent.parent
        try:
            _p_cur = Path(str(getattr(self, "project", "") or "")).resolve()
            if _p_cur == _ide_root or _ide_root in _p_cur.parents:
                _safe = (Path.home() / "BlackChpokProjects")
                _safe.mkdir(parents=True, exist_ok=True)
                self.project = _safe
        except Exception:
            pass
        """Увімкнути режим. Повертає (успіх, повідомлення)."""
        target = Path(project)
        ok, reason = self.can_start(target)
        if not ok:
            if self.state == STATE_STOPPING:
                return False, "Спершу дочекайся завершення зупинки."
            return False, reason
        self.project = target
        self.state = STATE_RUNNING
        self._stop_requested = False
        self.last_error = ""
        self.plan = []
        self.focus = Focus()
        self.queue.set_paused(False)
        self.log(f"Автономний режим увімкнено для «{target.name}».", kind="ok")
        self._status(f"Автономний режим: {target.name}")
        self._changed()
        return True, f"Автономний режим увімкнено: {target}"

    def request_stop(self) -> str:
        """Попросити зупинку: поточний файл дописується до кінця.

        Повертає людське пояснення, яке показує панель.
        """
        if self.state == STATE_OFF:
            return "Автономний режим і так вимкнено."
        if self.state == STATE_STOPPING:
            return "Зупинка вже в процесі."
        self.state = STATE_STOPPING
        self._stop_requested = True
        self.log("Зупинка: агент дописує поточний файл і зберігає його.", kind="stop")
        self._status("Автономний режим: зупиняю після поточного кроку…")
        self._changed()
        return "Зупиняю після поточного кроку — файл буде дописано й збережено."

    def confirm_stop(self, *, reason: str = "") -> None:
        """Завершити зупинку: режим вимкнено, задачі агента знято з черги."""
        removed = 0
        try:
            removed = self.queue.suspend_pending(origin=ORIGIN_AGENT)
        except Exception:  # noqa: BLE001 - черга може бути недоступна
            LOG.debug("Не вдалось зняти задачі агента", exc_info=True)
        self.state = STATE_OFF
        self._stop_requested = False
        for item in self.plan:
            if item.state == "зараз":
                item.state = "готово"
        self.focus = Focus()
        tail = f" Знято з черги задач агента: {removed}." if removed else ""
        self.log((reason or "Автономний режим вимкнено.") + tail, kind="stop")
        self._status("Автономний режим вимкнено.")
        self._changed()

    # ── задачі ─────────────────────────────────────────────────────────────
    def add_user_task(self, text: str) -> tuple[bool, str]:
        """Гаряче додавання задачі користувача (вищий пріоритет)."""
        clean = (text or "").strip()
        if not clean:
            return False, "Порожня задача."
        task = self.queue.add(clean, origin=ORIGIN_USER, front=True,
                              chat_id=self.chat_id)
        if task is None:
            return False, "Не вдалось додати задачу."
        self.plan.insert(0, PlanItem(text=f"Задача від тебе: {_short(clean)}",
                                     kind=KIND_CODE, state="далі", origin=ORIGIN_USER))
        del self.plan[MAX_PLAN_ITEMS:]
        self.log(f"Додано твою задачу (вищий пріоритет): {_short(clean, 90)}", kind="user")
        return True, "Задачу додано — виконаю її першою."

    def seed(self, *, limit: int = SEED_PER_CYCLE) -> int:
        """Знайти покращення й поставити їх у чергу від імені агента.

        Дві перевірки перед постановкою задачі:

        1. **задача вже стоїть у черзі** з тим самим ключем ідеї — не дублюємо
           (раніше в живій черзі було по дві задачі на один і той самий файл:
           сканер віддавав ідею, ``_seen`` рахував її окремо, а черга вже
           містила копію);
        2. **мета вже досягнута** — для позначки боргу перевіряємо, чи маркер
           справді зник із файлу. Модель часто «править» рядок і не прибирає
           маркер; без цієї перевірки така сама задача йшла по колу.
        """
        if self.project is None or self.state != STATE_RUNNING:
            return 0
        try:
            ideas = list(self.scan(self.project, limit=max(limit * 3, 6)))
        except Exception as exc:  # noqa: BLE001 - скан не має валити режим
            self.last_error = f"скан проєкту: {exc}"
            self.log(f"Не вдалось просканувати проєкт: {exc}", kind="error")
            return 0
        packages = project_packages(self.project)
        if packages:
            ideas.extend(research_ideas(packages, limit=1))
        # ?? ??????????? ????????? ?????????? ????? ???????? ????-????? ??????? ??
        from types import SimpleNamespace as _SNS
        def _mk_idea(kind: str, path: str, title: str, instruction: str):
            return _SNS(
                kind=kind,
                path=path,
                title=title,
                instruction=instruction,
                key=lambda k=f"{kind}:{path}:{title}": k,
            )
        if not ideas and self.project and Path(self.project).is_dir():
            _root = Path(self.project)
            _ign = {".git", ".venv", "venv", "__pycache__", "node_modules"}
            _files = [
                f for f in sorted(_root.rglob("*"))
                if f.is_file() and not any(part in _ign for part in f.parts)
            ]
            _rel = {f.relative_to(_root).as_posix(): f for f in _files}
            if not _files:
                ideas.append(_mk_idea(
                    "feature",
                    "index.html",
                    "\u0421\u0442\u0432\u043e\u0440\u0438\u0442\u0438 \u0441\u0442\u0430\u0440\u0442\u043e\u0432\u0443 \u0430\u0440\u0445\u0456\u0442\u0435\u043a\u0442\u0443\u0440\u0443 \u043f\u0440\u043e\u0454\u043a\u0442\u0443 2026",
                    "\u0421\u0442\u0432\u043e\u0440\u0438 \u0441\u0443\u0447\u0430\u0441\u043d\u0438\u0439 \u0430\u0434\u0430\u043f\u0442\u0438\u0432\u043d\u0438\u0439 \u043f\u0440\u043e\u0454\u043a\u0442 2026 \u0440\u043e\u043a\u0443 \u0437 \u043c\u043e\u0434\u0443\u043b\u044c\u043d\u043e\u044e \u0441\u0442\u0440\u0443\u043a\u0442\u0443\u0440\u043e\u044e \u0444\u0430\u0439\u043b\u0456\u0432 \u0456 \u0437\u0430\u043f\u0443\u0441\u0442\u0438 \u0432 Live Preview.",
                ))
            else:
                for _rp, _fp in list(_rel.items())[:12]:
                    try:
                        _ln_cnt = len(_fp.read_text(encoding="utf-8", errors="ignore").splitlines())
                    except Exception:
                        _ln_cnt = 999
                    if _rp.endswith(".js") and _ln_cnt < 30:
                        ideas.append(_mk_idea(
                            "feature",
                            _rp,
                            f"\u0414\u043e\u0434\u0430\u0442\u0438 \u0456\u043d\u0442\u0435\u0440\u0430\u043a\u0442\u0438\u0432\u043d\u0443 \u043b\u043e\u0433\u0456\u043a\u0443 \u0443 {_rp}",
                            f"\u041f\u0440\u043e\u0447\u0438\u0442\u0430\u0439 {_rp} \u0442\u0430 \u043f\u043e\u0432'\u044f\u0437\u0430\u043d\u0456 \u0444\u0430\u0439\u043b\u0438 \u0456 \u0440\u0435\u0430\u043b\u0456\u0437\u0443\u0439 \u0441\u0443\u0447\u0430\u0441\u043d\u0443 \u0456\u043d\u0442\u0435\u0440\u0430\u043a\u0442\u0438\u0432\u043d\u0456\u0441\u0442\u044c 2026 \u0440\u043e\u043a\u0443.",
                        ))
                    elif _rp.endswith(".css") and _ln_cnt < 75:
                        ideas.append(_mk_idea(
                            "refactor",
                            _rp,
                            f"\u041f\u043e\u043a\u0440\u0430\u0449\u0438\u0442\u0438 \u0434\u0438\u0437\u0430\u0439\u043d 2026 \u0443 {_rp}",
                            f"\u041f\u0440\u043e\u0447\u0438\u0442\u0430\u0439 {_rp} \u0456 \u043e\u043d\u043e\u0432\u0438 \u0441\u0442\u0438\u043b\u0456 \u0434\u043e \u0441\u0442\u0430\u043d\u0434\u0430\u0440\u0442\u0443 2026 \u0440\u043e\u043a\u0443 (Bento Grid, Glassmorphism, \u0430\u0434\u0430\u043f\u0442\u0438\u0432\u043d\u0456\u0441\u0442\u044c).",
                        ))
                    elif _rp.endswith(".html") and _ln_cnt < 65:
                        ideas.append(_mk_idea(
                            "feature",
                            _rp,
                            f"\u0420\u043e\u0437\u0448\u0438\u0440\u0438\u0442\u0438 \u0441\u0435\u043a\u0446\u0456\u0457 \u0443 {_rp}",
                            f"\u041f\u0440\u043e\u0447\u0438\u0442\u0430\u0439 {_rp} \u0456 \u0434\u043e\u0434\u0430\u0439 \u0441\u0443\u0447\u0430\u0441\u043d\u0456 \u0441\u0435\u043a\u0446\u0456\u0457 \u0442\u0430 \u043f\u0435\u0440\u0435\u0432\u0456\u0440 \u0443 Live Preview.",
                        ))
                    elif _rp.endswith(".py") and _ln_cnt < 40 and not _rp.startswith("test"):
                        ideas.append(_mk_idea(
                            "feature",
                            _rp,
                            f"\u0420\u043e\u0437\u0432\u0438\u043d\u0443\u0442\u0438 \u0444\u0443\u043d\u043a\u0446\u0456\u043e\u043d\u0430\u043b \u0443 {_rp}",
                            f"\u041f\u0440\u043e\u0447\u0438\u0442\u0430\u0439 {_rp}, \u0434\u043e\u0434\u0430\u0439 \u0442\u0438\u043f\u0456\u0437\u0430\u0446\u0456\u044e \u0442\u0430 \u043e\u0431\u0440\u043e\u0431\u043a\u0443 \u043f\u043e\u043c\u0438\u043b\u043e\u043a.",
                        ))
                if not any("test" in k.lower() for k in _rel):
                    ideas.append(_mk_idea(
                        "test",
                        "tests_check.py",
                        "\u041f\u0435\u0440\u0435\u0432\u0456\u0440\u0438\u0442\u0438 \u0446\u0456\u043b\u0456\u0441\u043d\u0456\u0441\u0442\u044c \u043f\u0440\u043e\u0454\u043a\u0442\u0443",
                        "\u041f\u0435\u0440\u0435\u0432\u0456\u0440 \u0443\u0441\u0456 \u0444\u0430\u0439\u043b\u0438 \u043f\u0440\u043e\u0454\u043a\u0442\u0443 \u043d\u0430 \u0441\u0438\u043d\u0442\u0430\u043a\u0441\u0438\u0441 \u0442\u0430 \u0440\u043e\u0431\u043e\u0442\u0443 \u0432 Live Preview.",
                    ))
        #  ?????? 2 ? 3: ???? ???????? ???? ????????? -> ??????? ???????????? ??????? Gemini ??? ??????? ? ?????????
        if not ideas and self.project and Path(self.project).is_dir():
            _root2 = Path(self.project)
            _ign2 = {".git", ".venv", "venv", "__pycache__", "node_modules"}
            _fnames = [
                f.relative_to(_root2).as_posix()
                for f in sorted(_root2.rglob("*"))
                if f.is_file() and not any(part in _ign2 for part in f.parts)
            ][:20]
            _stack_desc = ", ".join(_fnames) if _fnames else "empty project"
            _got_remote = False
            try:
                import json as _j_au, urllib.request as _u_au
                from . import config as _cfg_au
                _st_obj = getattr(self, "settings", None) or _cfg_au.AppSettings.load()
                _gkey = str(getattr(_st_obj, "gemini_api_key", "") or "").strip()
                if _gkey:
                    _prompt_ai = (
                        "You are an autonomous lead software architect in 2026. "
                        f"Project files: [{_stack_desc}]. "
                        "Propose 2 concrete, high-value new features or improvements (2026 standards) not yet implemented. "
                        "Return ONLY JSON list of objects with keys: title, path, instruction (in Ukrainian, concise)."
                    )
                    _body = _j_au.dumps({"contents": [{"role": "user", "parts": [{"text": _prompt_ai}]}]}).encode("utf-8")
                    for _gm in ("gemini-flash-lite-latest", "gemini-flash-latest"):
                        try:
                            _url = f"https://googleapis.com{_gm}:generateContent?key={_gkey}"
                            _req = _u_au.Request(_url, data=_body, headers={"Content-Type": "application/json"})
                            with _u_au.urlopen(_req, timeout=10) as _resp:
                                _raw = _j_au.loads(_resp.read().decode("utf-8"))
                            _txt = _raw["candidates"]["content"]["parts"]["text"].strip()
                            if "```" in _txt:
                                _txt = _txt.split("```").replace("json", "", 1).strip()
                            _arr = _j_au.loads(_txt)
                            if isinstance(_arr, list):
                                for _it in _arr[:2]:
                                    if isinstance(_it, dict) and _it.get("title") and _it.get("instruction"):
                                        ideas.append(_mk_idea(
                                            "feature",
                                            str(_it.get("path") or (_fnames if _fnames else "main.py")),
                                            str(_it["title"])[:80],
                                            str(_it["instruction"]),
                                        ))
                                        _got_remote = True
                            if _got_remote:
                                self.log(f"\u2601\ufe0f Gemini ({_gm}) \u0437\u0433\u0435\u043d\u0435\u0440\u0443\u0432\u0430\u0432 {len(ideas)} \u043d\u043e\u0432\u0438\u0445 \u0456\u0434\u0435\u0439 \u0440\u043e\u0437\u0432\u0438\u0442\u043a\u0443 \u043f\u0440\u043e\u0454\u043a\u0442\u0443.", kind="info")
                                break
                        except Exception:
                            continue
            except Exception:
                pass
            if not _got_remote:
                try:
                    import urllib.request as _u_web, urllib.parse as _up_web, re as _re_web
                    _q_str = "modern web app UI UX features 2026" if any(x.endswith(".html") for x in _fnames) else "modern python software architecture features 2026"
                    _wurl = "https://duckduckgo.com" + _up_web.quote(_q_str)
                    _wreq = _u_web.Request(_wurl, headers={"User-Agent": "Mozilla/5.0"})
                    with _u_web.urlopen(_wreq, timeout=8) as _wresp:
                        _html = _wresp.read().decode("utf-8", errors="ignore")
                    _titles = _re_web.findall(r'class="result__a"[^>]*>(.*?)</a>', _html)
                    _clean_t = [_re_web.sub(r"<[^>]+>", "", t).strip() for t in _titles if t.strip()][:2]
                    for _ct in _clean_t:
                        ideas.append(_mk_idea(
                            "research",
                            _fnames if _fnames else "README.md",
                            f"\U0001f310 \u0406\u0434\u0435\u044f \u0437 \u043c\u0435\u0440\u0435\u0436\u0456: {_ct[:55]}",
                            f"\u0412\u043f\u0440\u043e\u0432\u0430\u0434\u044c \u0441\u0443\u0447\u0430\u0441\u043d\u0435 \u043f\u043e\u043a\u0440\u0430\u0449\u0435\u043d\u043d\u044f \u0437\u0430 \u0442\u0435\u043c\u043e\u044e '{_ct}' \u0443 \u043f\u043e\u0442\u043e\u0447\u043d\u0438\u0439 \u043f\u0440\u043e\u0454\u043a\u0442 2026 \u0440\u043e\u043a\u0443.",
                        ))
                    if ideas:
                        self.log("\U0001f310 \u0417\u043d\u0430\u0439\u0434\u0435\u043d\u043e \u0441\u0432\u0456\u0436\u0456 \u0456\u0434\u0435\u0457 \u0432 \u0456\u043d\u0442\u0435\u0440\u043d\u0435\u0442\u0456 \u0442\u0430 \u0434\u043e\u0434\u0430\u043d\u043e \u0432 \u0447\u0435\u0440\u0433\u0443.", kind="info")
                except Exception:
                    pass

        self.ideas_total = len(ideas)
        added = 0
        for idea in ideas:
            if added >= limit:
                break
            key = idea.key()
            seen = self._seen.get(key, 0)
            if seen >= MAX_REPEATS:
                continue
            if self._pending_has(key):
                # Та сама ідея вже чекає у черзі — не плодимо копію.
                continue
            task = self.queue.add(idea.instruction, origin=ORIGIN_AGENT,
                                  file_hint=idea.path, chat_id=self.chat_id,
                                  idea_key=key)
            if task is None:
                continue
            self._seen[key] = seen + 1
            added += 1
            self.plan.append(PlanItem(text=idea.title, kind=idea.kind, state="далі"))
        del self.plan[MAX_PLAN_ITEMS:]
        if added:
            self.log(f"Знайдено покращень: {added} — додано в чергу.", kind="info")
        else:
            self.log("Нових ідей не знайдено — перевірю проєкт ще раз пізніше.")
        self._changed()
        return added

    def _pending_has(self, key: str) -> bool:
        """Чи вже є в черзі незакрита задача з цим ключем ідеї."""
        try:
            tasks = list(self.queue.tasks)
        except Exception:  # noqa: BLE001 - черга може бути недоступна
            return False
        for task in tasks:
            if getattr(task, "settled", False):
                continue
            if str(getattr(task, "idea_key", "") or "") == key:
                return True
        return False

    def task_succeeded(self, *, idea_key: str, path: str = "") -> str:
        """Чи справді досягнуто мети задачі. Порожній рядок — так.

        Потрібно, щоб не вважати «готово» роботу, яка насправді не змінила
        нічого: позначка ``TODO`` лишилась у файлі, тест-файл перезаписано
        тим самим вмістом. Повертає людську причину, якщо мети не досягнуто.
        """
        return goal_problem(self.project, idea_key=idea_key, path=path)

    # ── рішення про наступний крок ─────────────────────────────────────────
    def tick(self, *, busy: bool, has_pending: bool) -> str:
        """Що робити ведучому просто зараз.

        Повертає одну з дій:

        * ``"off"`` — режим вимкнено, нічого не робити;
        * ``"stop_wait"`` — зупинка requested, але агент ще дописує файл;
        * ``"stop_finish"`` — агент вільний: можна завершувати зупинку;
        * ``"wait"`` — агент зайнятий, чекаємо;
        * ``"run"`` — є задача в черзі, її треба запустити;
        * ``"seed"`` — черга порожня, треба знайти нові покращення.
        """
        if self.state == STATE_OFF:
            return "off"
        if self.state == STATE_STOPPING:
            return "stop_wait" if busy else "stop_finish"
        if busy:
            return "wait"
        if has_pending:
            return "run"
        return "seed"

    def stop_requested(self) -> bool:
        return self._stop_requested

    # ── зручності для панелі ───────────────────────────────────────────────
    def pending_tasks(self, *, limit: int = 40):
        """Задачі для показу в панелі: спершу активна, далі черга."""
        rows = [task for task in self.queue.tasks
                if task.status in ("виконується", "очікує")]
        # Задачі користувача — вище: так видно, що їх не загублено.
        rows.sort(key=lambda task: (0 if task.from_user else 1))
        return rows[:limit]

    def plan_rows(self) -> list[tuple[str, str, str]]:
        """(текст, вид, стан) для малювання плану."""
        return [(item.text, item.kind, item.state) for item in self.plan]

    def recent_log(self, *, limit: int = 60) -> list[LogEntry]:
        return self.log_entries[-limit:]


def _short(text: str, limit: int = 70) -> str:
    clean = " ".join((text or "").split())
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


def goal_problem(project: Path | None, *, idea_key: str, path: str = "") -> str:
    """Мета задачі справді досягнута? Порожній рядок — так.

    Публічна (без підкреслення), бо її кличе ще й ``TaskValidator`` у
    ``task_executor``: перевірка результату кроку стоїть у двох місцях
    (виконавець черги і вікно), і обидві мусять брати мету з одного джерела.

    Перевіряється лише те, що справді можна перевірити без моделі: позначка
    боргу мусить ЗНИКНУТИ з файлу. Решта ідей (тести, рефакторинг) лишаються
    на розсуд виконавця — вигадувати для них формальний критерій означало б
    блокувати справжню роботу.
    """
    clean = str(idea_key or "").strip()
    if not clean.startswith("marker|") or not path or project is None:
        return ""
    marker = clean.rsplit("|", 1)[-1].strip().upper()
    if not marker:
        return ""
    try:
        body = (Path(project) / path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if _MARKER_RE.search(body):
        return f"позначка {marker} досі у файлі {path}"
    return ""


def _same(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return str(left) == str(right)


__all__ = [
    "Candidate",
    "DEBT_MARKERS",
    "Focus",
    "KIND_ANALYSIS",
    "KIND_CODE",
    "KIND_RESEARCH",
    "KIND_VERIFY",
    "LogEntry",
    "MAX_LOG",
    "MAX_PLAN_ITEMS",
    "PlanItem",
    "SEED_PER_CYCLE",
    "STATE_OFF",
    "STATE_RUNNING",
    "STATE_STOPPING",
    "AutonomousEngine",
    "analyse_project",
    "goal_problem",
    "project_packages",
    "research_ideas",
]
