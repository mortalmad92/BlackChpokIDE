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

    def key(self) -> str:
        """Ключ для захисту від повторів."""
        return f"{self.kind}|{self.path}|{self.title}"


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
    шукає добре відомі ознаки боргу — позначки TODO/FIXME, проковтнуті
    винятки, ``print`` замість журналу, дуже довгі файли й модулі без
    тестів. Кожна ідея стає окремою задачею агента, і саме агент вирішує,
    як її виконати.
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

        # 1. Позначки боргу: TODO / FIXME / HACK.
        for number, line in enumerate(lines, start=1):
            marker = next((m for m in ("TODO", "FIXME", "HACK", "XXX")
                           if m in line), "")
            if not marker:
                continue
            clean = " ".join(line.strip().lstrip("#/ ").split())[:140]
            ideas.append(Candidate(
                title=f"Розібрати позначку {marker} у {rel}:{number}",
                instruction=(
                    f"У файлі {rel} на рядку {number} є позначка {marker}: «{clean}». "
                    f"Прочитай файл інструментом read_file, зроби саме те, що просить "
                    f"позначка, прибери її й перевір синтаксис (python -m py_compile, "
                    f"якщо це .py). Змінюй лише цей файл."
                ),
                kind=KIND_CODE, path=rel, weight=3.0))
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
                kind=KIND_CODE, path=rel, weight=2.4))

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
                    kind=KIND_CODE, path=rel, weight=1.8))

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
                kind=KIND_CODE, path=rel, weight=1.2))

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
                        kind=KIND_VERIFY, path=rel, weight=2.0))

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
        """Знайти покращення й поставити їх у чергу від імені агента."""
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
        self.ideas_total = len(ideas)
        added = 0
        for idea in ideas:
            if added >= limit:
                break
            seen = self._seen.get(idea.key(), 0)
            if seen >= MAX_REPEATS:
                continue
            task = self.queue.add(idea.instruction, origin=ORIGIN_AGENT,
                                  file_hint=idea.path, chat_id=self.chat_id)
            if task is None:
                continue
            self._seen[idea.key()] = seen + 1
            added += 1
            self.plan.append(PlanItem(text=idea.title, kind=idea.kind, state="далі"))
        del self.plan[MAX_PLAN_ITEMS:]
        if added:
            self.log(f"Знайдено покращень: {added} — додано в чергу.", kind="info")
        else:
            self.log("Нових ідей не знайдено — перевірю проєкт ще раз пізніше.")
        self._changed()
        return added

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


def _same(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return str(left) == str(right)


__all__ = [
    "Candidate",
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
    "project_packages",
    "research_ideas",
]
