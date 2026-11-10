"""Нічна зміна: черга задач, яка працює без чату.

Патч лишається лише коли автоматична перевірка стає кращою.
Той самий збій вдруге зупиняє задачу. Дедлайн і ліміт спроб теж зупиняють.
Вранці є журнал. Процес окремий від розмови, бо розмова засинає разом із ходом.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

TRIGGERS = (
    "нічна зміна до ранку",
    "працюй поки я сплю",
    "розбери чергу задач",
    "нічна зміна",
    "працюй до ранку",
)
ALLOWED_SUFFIXES = {".py", ".html", ".css", ".js", ".md", ".txt", ".json"}
MAX_HOURS = 8
DEFAULT_HOURS = 6
MAX_ATTEMPTS = 4
MAX_TASKS = 12


@dataclass
class CheckResult:
    exit_code: int
    output: str
    failures: int
    signature: str


def failure_signature(output: str) -> str:
    lines = [line.strip() for line in (output or "").splitlines() if line.strip()]
    for line in lines:
        if line.startswith("FAILED ") or "Error:" in line or line.startswith("E "):
            return line[:240]
    return lines[-1][:240] if lines else ""


def count_failures(exit_code: int, output: str) -> int:
    if exit_code == 0:
        return 0
    match = re.search(r"(\d+)\s+failed", output or "")
    if match:
        return int(match.group(1))
    failed_lines = len(re.findall(r"^FAILED\s", output or "", flags=re.M))
    return failed_lines or 1


def make_check(exit_code: int, output: str) -> CheckResult:
    return CheckResult(exit_code, output or "", count_failures(exit_code, output or ""), failure_signature(output or ""))


def is_better(before: CheckResult, after: CheckResult) -> bool:
    if after.exit_code != 0 and before.exit_code != 0 and after.signature and after.signature == before.signature:
        return False
    if after.exit_code == 0 and before.exit_code != 0:
        return True
    if after.exit_code != 0 and before.exit_code != 0 and after.failures < before.failures:
        return True
    return False


def parse_hours(phrase: str) -> int:
    """Скільки годин працювати вночі.

    Розуміє «на 4 год», «4 години», «3 год», «2 hours». Раніше шаблон вимагав
    саме слово «на», тому «попрацюй 4 години» тихо давало типовий час.
    """
    text = phrase or ""
    patterns = (
        r"на\s+(\d+)\s*год",
        r"(\d+)\s*годин",
        r"(\d+)\s*год",
        r"(\d+)\s*hour",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return max(1, min(int(match.group(1)), MAX_HOURS))
    return DEFAULT_HOURS


def wants_status(phrase: str) -> bool:
    low = (phrase or "").lower()
    return "стан ніч" in low or "як нічн" in low


def extra_tasks(phrase: str) -> list[str]:
    raw = phrase or ""
    low = raw.lower()
    tail = ""
    for trigger in TRIGGERS:
        at = low.find(trigger)
        if at >= 0:
            tail = raw[at + len(trigger):]
            break
    tail = tail.strip(" :.-")
    parts = re.split(r"[\n;]+", tail)
    tasks = []
    for part in parts:
        item = part.strip()
        if len(item) >= 8 and not item.lower().startswith("на ") and "стан ніч" not in item.lower():
            tasks.append(item[:500])
    return tasks


def parse_check(task: str, workspace: Path) -> list[str]:
    match = re.search(r"перевірка:\s*(.+)", task or "", flags=re.I)
    if not match:
        tests = list(workspace.glob("test_*.py")) + list((workspace / "tests").glob("test_*.py"))
        if tests:
            return default_test_command(workspace)
        return [sys.executable, "-m", "compileall", "-q", "."]
    body = match.group(1).strip()
    if re.search(r"[&|;<>`$]", body) or ".." in body:
        raise ValueError("Перевірка містить заборонені символи.")
    tokens = body.split()
    if tokens and tokens[0].lower() == "pytest":
        return [sys.executable, "-m", "pytest", *tokens[1:]]
    if len(tokens) >= 3 and tokens[0].lower() == "python" and tokens[1] == "-m" and tokens[2] in {"pytest", "unittest", "py_compile", "compileall"}:
        return [sys.executable, "-m", tokens[2], *tokens[3:]]
    raise ValueError("Перевірка може бути лише pytest, unittest, py_compile або compileall.")


def safe_target(workspace: Path, name: str) -> Path | None:
    raw = (name or "").strip().replace("\\", "/").lstrip("/")
    if not raw or ".." in Path(raw).parts:
        return None
    path = (workspace / raw).resolve()
    root = workspace.resolve()
    if path != root and root not in path.parents:
        return None
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        return None
    if path.name.lower().startswith(".env") or ".venv" in path.parts or ".mcp_rag" in path.parts:
        return None
    return path


def files_from_answer(answer: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    segments = re.split(r"### FILE:\s*([^\n#]+)", answer or "")
    if len(segments) > 1:
        for index in range(1, len(segments), 2):
            name = segments[index].strip(" #\r\n")
            raw = segments[index + 1] if index + 1 < len(segments) else ""
            blocks = re.findall(r"```(?:\w+)?\n(.*?)```", raw, re.DOTALL)
            code = "\n\n".join(blocks) if blocks else raw.strip()
            if name and code.strip():
                found.append((name, code.strip() + "\n"))
    if found:
        return found
    blocks = re.findall(r"```(?:python|html|css|javascript|js|json|markdown|md)?\n(.*?)```", answer or "", re.DOTALL)
    if len(blocks) == 1 and blocks[0].strip():
        return [("app.py", blocks[0].strip() + "\n")]
    return []


def clear_work_cache(workspace: Path) -> int:
    """Прибирає байткод і кеш тестів, щоб наступний запуск бачив щойно записаний код."""
    removed = 0
    skip = {".venv", "venv", ".git", "node_modules", ".mcp_rag"}
    for current, dirs, _files in os.walk(workspace):
        dirs[:] = [name for name in dirs if name not in skip and not name.startswith(".venv")]
        for name in list(dirs):
            if name not in {"__pycache__", ".pytest_cache", ".mypy_cache"}:
                continue
            target = Path(current) / name
            shutil.rmtree(target, ignore_errors=True)
            removed += 1
            dirs.remove(name)
    return removed


def read_context(workspace: Path, limit: int = 5000) -> str:
    """Збирає контекст з диска. Минулий запит до моделі сюди не входить."""
    skip = {".venv", "venv", ".git", "node_modules", ".mcp_rag", "__pycache__", ".pytest_cache"}
    files: list[Path] = []
    for pattern in ("*.py", "*.html", "*.css", "*.js", "*.md"):
        for path in workspace.rglob(pattern):
            if any(part in skip for part in path.parts):
                continue
            if path.is_file():
                files.append(path)
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    chunks: list[str] = []
    used = 0
    for path in files[:8]:
        text = path.read_text(encoding="utf-8", errors="replace")[:1200]
        block = f"--- {path.relative_to(workspace).as_posix()} ---\n{text}"
        if used + len(block) > limit:
            break
        chunks.append(block)
        used += len(block)
    return "\n\n".join(chunks) if chunks else "Файлів для контексту ще немає."


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=8, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return str(pid) in (out.stdout or "")


class NightRunner:
    def __init__(
        self,
        workspace: Path,
        db_path: Path,
        complete: Callable[[str], str],
        run_check: Callable[[list[str]], CheckResult],
        now: Callable[[], datetime] | None = None,
        max_attempts: int = MAX_ATTEMPTS,
        max_tasks: int = MAX_TASKS,
    ) -> None:
        self.workspace = workspace
        self.db_path = db_path
        self.complete = complete
        self.run_check = run_check
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.max_attempts = max_attempts
        self.max_tasks = max_tasks
        self.journal = workspace / ".mcp_rag" / "night_journal.md"
        self.lock_path = workspace / ".mcp_rag" / "night_shift.lock"

    def _db(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_todos (id INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT, status TEXT, updated TEXT)"
        )
        return conn

    def add_tasks(self, tasks: list[str]) -> list[int]:
        ids = []
        conn = self._db()
        try:
            stamp = self.now().isoformat(timespec="seconds")
            for task in tasks:
                conn.execute(
                    "INSERT INTO agent_todos (task, status, updated) VALUES (?, ?, ?)",
                    (task, "pending", stamp),
                )
                ids.append(int(conn.execute("SELECT last_insert_rowid()").fetchone()[0]))
            conn.commit()
        finally:
            conn.close()
        return ids

    def pending(self) -> list[tuple[int, str]]:
        conn = self._db()
        try:
            rows = conn.execute(
                "SELECT id, task FROM agent_todos WHERE status='pending' ORDER BY id LIMIT ?",
                (self.max_tasks,),
            ).fetchall()
        finally:
            conn.close()
        return [(int(row[0]), row[1]) for row in rows]

    def _set_status(self, task_id: int, status: str) -> None:
        conn = self._db()
        try:
            conn.execute(
                "UPDATE agent_todos SET status=?, updated=? WHERE id=?",
                (status, self.now().isoformat(timespec="seconds"), task_id),
            )
            conn.commit()
        finally:
            conn.close()

    def _apply(self, files: list[tuple[str, str]]) -> dict[Path, str | None]:
        snapshot: dict[Path, str | None] = {}
        for name, code in files:
            target = safe_target(self.workspace, name)
            if target is None:
                continue
            snapshot[target] = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(code if code.endswith("\n") else code + "\n", encoding="utf-8", newline="\n")
        return snapshot

    def _restore(self, snapshot: dict[Path, str | None]) -> None:
        for path, previous in snapshot.items():
            if previous is None:
                if path.is_file():
                    path.unlink()
            else:
                path.write_text(previous, encoding="utf-8", newline="\n")

    def work_one(self, task_id: int, task: str, deadline: datetime) -> str:
        self._set_status(task_id, "running")
        try:
            command = parse_check(task, self.workspace)
        except ValueError as exc:
            self._set_status(task_id, "stuck")
            return f"Задача {task_id} зупинена: {exc}"
        notes = [f"## Задача {task_id}", task[:300]]
        previous_signature = ""
        kept_patch = False
        for attempt in range(1, self.max_attempts + 1):
            if self.now() >= deadline:
                self._set_status(task_id, "pending")
                notes.append("Дедлайн. Задачу повернуто в чергу.")
                return "\n".join(notes)
            cleared = clear_work_cache(self.workspace)
            context = read_context(self.workspace)
            before = self.run_check(command)
            notes.append(f"Спроба {attempt}: контекст зібрано заново, кеш кроку скинуто ({cleared}).")
            if before.exit_code == 0 and kept_patch:
                self._set_status(task_id, "done")
                notes.append(f"Спроба {attempt}: перевірка зелена. Задачу закрито.")
                return "\n".join(notes)
            answer = self.complete(
                "Задача:\n" + task
                + "\n\nКонтекст з диска, без минулого кроку:\n" + context
                + "\n\nПеревірки командного рядка:\n" + (before.output or "")[-2500:]
                + "\n\nПоверни лише секції ### FILE: відносний/шлях і код у блоці. "
                "Не повторюй минулий текст. Патч має зменшити число падінь."
            )
            files = files_from_answer(answer)
            if not files:
                notes.append(f"Спроба {attempt}: модель не дала файлів.")
                if before.exit_code == 0:
                    self._set_status(task_id, "stuck")
                    notes.append("Перевірка вже зелена, а змін немає. Задачу зупинено, щоб не крутитись.")
                    return "\n".join(notes)
                continue
            snapshot = self._apply(files)
            if not snapshot:
                notes.append(f"Спроба {attempt}: шляхи файлів відхилено.")
                continue
            clear_work_cache(self.workspace)
            notes.append("Після запису кеш скинуто, наступний крок прочитає контекст з диска.")
            after = self.run_check(command)
            green_hold = before.exit_code == 0 and after.exit_code == 0
            if green_hold or is_better(before, after):
                kept_patch = True
                previous_signature = after.signature
                notes.append(
                    f"Спроба {attempt}: падінь {before.failures} -> {after.failures}. Патч лишився."
                )
                if after.exit_code == 0:
                    self._set_status(task_id, "done")
                    notes.append("Перевірка зелена. Задачу закрито.")
                    return "\n".join(notes)
                continue
            self._restore(snapshot)
            notes.append(
                f"Спроба {attempt}: краще не стало ({before.failures} -> {after.failures}). Патч відкочено."
            )
            if after.signature and after.signature == previous_signature:
                self._set_status(task_id, "stuck")
                notes.append("Той самий збій повторився. Задачу зупинено.")
                return "\n".join(notes)
            if after.signature and after.signature == before.signature:
                self._set_status(task_id, "stuck")
                notes.append("Збій не змінився. Задачу зупинено.")
                return "\n".join(notes)
            previous_signature = after.signature
        self._set_status(task_id, "stuck")
        notes.append("Ліміт спроб вичерпано.")
        return "\n".join(notes)

    def run(self, hours: int = DEFAULT_HOURS) -> str:
        started = self.now()
        deadline = started + timedelta(hours=max(1, min(hours, MAX_HOURS)))
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text(f"{os.getpid()}\n{started.isoformat(timespec='seconds')}\n", encoding="utf-8")
        blocks = [
            f"# Нічна зміна {started.strftime('%Y-%m-%d %H:%M')}",
            f"Бюджет: {hours} год, до {MAX_ATTEMPTS} спроб на задачу. "
            "Кожен крок читає контекст з диска, після запису скидає кеш і ганяє перевірки в командному рядку.",
        ]
        try:
            tasks = self.pending()
            if not tasks:
                blocks.append("Черга порожня.")
            for task_id, task in tasks:
                if self.now() >= deadline:
                    blocks.append(f"Задача {task_id} лишилась у черзі: дедлайн.")
                    continue
                blocks.append(self.work_one(task_id, task, deadline))
        finally:
            if self.lock_path.is_file():
                self.lock_path.unlink()
        text = "\n\n".join(blocks) + "\n"
        previous = self.journal.read_text(encoding="utf-8") if self.journal.is_file() else ""
        self.journal.write_text(previous + text, encoding="utf-8")
        return text


def _read_lock(lock_path: Path) -> int:
    if not lock_path.is_file():
        return 0
    try:
        return int(lock_path.read_text(encoding="utf-8").splitlines()[0].strip())
    except (OSError, ValueError, IndexError):
        return 0


def status_text(workspace: Path, alive: Callable[[int], bool] | None = None) -> str:
    journal = workspace / ".mcp_rag" / "night_journal.md"
    lock_path = workspace / ".mcp_rag" / "night_shift.lock"
    check_alive = alive or pid_alive
    pid = _read_lock(lock_path)
    running = bool(pid and check_alive(pid))
    tail = ""
    if journal.is_file():
        body = journal.read_text(encoding="utf-8", errors="replace")
        tail = body[-1200:]
    state = f"Нічна зміна працює, pid={pid}." if running else "Нічна зміна зараз не працює."
    if not tail:
        return state + " Журналу ще немає."
    return state + "\nОстаннє в журналі:\n" + tail


def queue_phrase(workspace: Path, db_path: Path, phrase: str) -> str:
    runner = NightRunner(workspace, db_path, complete=lambda _prompt: "", run_check=lambda _cmd: make_check(1, ""))
    if wants_status(phrase):
        return status_text(workspace)
    ids = runner.add_tasks(extra_tasks(phrase))
    added = f"У чергу додано: {ids}. " if ids else "Нових задач у фразі немає. "
    return added + status_text(workspace)


def start_or_status(workspace: Path, db_path: Path, phrase: str) -> str:
    if wants_status(phrase):
        return status_text(workspace)
    runner = NightRunner(workspace, db_path, complete=lambda _prompt: "", run_check=lambda _cmd: make_check(1, ""))
    ids = runner.add_tasks(extra_tasks(phrase))
    added = f"У чергу додано: {ids}. " if ids else ""
    lock_path = workspace / ".mcp_rag" / "night_shift.lock"
    pid = _read_lock(lock_path)
    if pid and pid_alive(pid):
        return added + f"Нічна зміна вже працює, pid={pid}. Журнал: .mcp_rag/night_journal.md"
    hours = parse_hours(phrase)
    log_path = workspace / ".mcp_rag" / "night_shift.out"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log_path, "a", encoding="utf-8")
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--hours", str(hours), "--workspace", str(workspace), "--db", str(db_path)],
        cwd=str(workspace),
        stdout=handle,
        stderr=subprocess.STDOUT,
        creationflags=flags,
        close_fds=True,
    )
    return (
        added
        + f"Нічна зміна пішла на {hours} год. Чат можна закрити. "
        + "Журнал: .mcp_rag/night_journal.md. Статус: «стан нічної зміни»."
    )


def lmstudio_complete(prompt: str) -> str:
    url = os.environ.get("MCP_LMSTUDIO_URL", "http://127.0.0.1:1235/v1").rstrip("/") + "/chat/completions"
    model = os.environ.get("MCP_LMSTUDIO_MODEL", "qwen/qwen3-vl-8b")
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": "Ти лагодиш локальний проєкт. Відповідай лише секціями ### FILE."},
            {"role": "user", "content": prompt},
        ],
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"] or ""


def run_command(command: list[str], workspace: Path, timeout: int = 180) -> CheckResult:
    try:
        proc = subprocess.run(
            command,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + "\n" + (exc.stderr or "") + "\nЧас перевірки вичерпано."
        return make_check(1, output)
    output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return make_check(proc.returncode, output)


def python_files(workspace: Path) -> list[Path]:
    skip = {".venv", "venv", ".git", "node_modules", ".mcp_rag", "__pycache__"}
    found: list[Path] = []
    for path in workspace.rglob("*.py"):
        if any(part in skip for part in path.parts):
            continue
        found.append(path)
        if len(found) >= 12:
            break
    return found


def has_tests(workspace: Path) -> bool:
    return bool(list(workspace.glob("test_*.py")) or list((workspace / "tests").glob("test_*.py")))


_UNITTEST_DRIVER = """
import sys, pathlib, unittest
from importlib.util import module_from_spec, spec_from_file_location
root = pathlib.Path(".").resolve()
sys.path.insert(0, str(root))
loader = unittest.TestLoader()
suite = unittest.TestSuite()
skip = {".venv", "venv", ".git", "node_modules", ".mcp_rag", "__pycache__"}
for path in root.rglob("test_*.py"):
    if any(part in skip for part in path.parts):
        continue
    spec = spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        continue
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    suite.addTests(loader.loadTestsFromModule(module))
if suite.countTestCases() == 0:
    print("Тестів не знайдено.")
    raise SystemExit(1)
result = unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
"""


def default_test_command(workspace: Path) -> list[str]:
    if importlib.util.find_spec("pytest") is not None:
        return [sys.executable, "-m", "pytest", "-q", "--tb=line"]
    return [sys.executable, "-c", _UNITTEST_DRIVER]


def suite_check(workspace: Path, command: list[str]) -> CheckResult:
    """Кілька перевірок у командному рядку. У відповідь іде один підсумок для храповика."""
    commands: list[tuple[list[str], int]] = []
    for path in python_files(workspace):
        commands.append(([sys.executable, "-m", "py_compile", str(path)], 30))
    commands.append((command, 180))
    app = workspace / "app.py"
    if app.is_file() and not has_tests(workspace):
        commands.append(([sys.executable, str(app)], 12))
    parts: list[str] = []
    worst = 0
    for cmd, timeout in commands:
        item = run_command(cmd, workspace, timeout=timeout)
        if "Час перевірки вичерпано" in item.output and "Traceback" not in item.output and "Error" not in item.output:
            item = make_check(0, item.output + "\nПроцес живий, час очікування вичерпано.")
        shown = " ".join(cmd)
        parts.append(f"$ {shown}\nexit={item.exit_code}\n{item.output[-700:]}")
        if item.exit_code != 0:
            worst = item.exit_code or 1
    output = "\n".join(parts)
    if worst == 0:
        # Підсумок має прямо казати «ok»: саме це читає агент і тест.
        # ``py_compile`` і ``pytest -q`` мовчать на успіху, тому без явного
        # слова «ok» результат виглядав як «нічого не перевірено».
        return make_check(0, "OK: усі перевірки пройдено.\n\n" + output)
    return make_check(worst, output)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=DEFAULT_HOURS)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--db", default="")
    args = parser.parse_args()
    workspace = Path(args.workspace).resolve()
    db_path = Path(args.db) if args.db else workspace / ".mcp_rag" / "memoria_infinita.db"
    runner = NightRunner(
        workspace,
        db_path,
        complete=lmstudio_complete,
        run_check=lambda command: suite_check(workspace, command),
    )
    print(runner.run(hours=args.hours))


if __name__ == "__main__":
    main()
