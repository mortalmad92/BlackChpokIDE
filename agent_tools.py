"""Локальні дії агента. Кожну викликає master_agent_router за intent."""

from __future__ import annotations

import ast
import difflib
import fnmatch
import hashlib
import json
import os
import platform
import py_compile
import re
import shutil
import sqlite3
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable

from rag_engine import LocalRAG


SKIP_DIRS = {
    ".git", ".hg", ".svn", ".mcp_rag", "node_modules", ".venv", "venv",
    "__pycache__", ".pytest_cache", ".mypy_cache", "dist", "build",
}

MAX_OUT = 6000
MAX_READ_LINES = 150
Route = Callable[[str, str, str], str]


def _clip(text: str, limit: int = MAX_OUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… обрізано, ще {len(text) - limit} символів."


def edits_store(db_path: Path) -> Path:
    return db_path.parent / "last_edits.json"


def _load_edits(store: Path) -> list[dict]:
    if not store.exists():
        return []
    try:
        data = json.loads(store.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _save_edits(store: Path, rows: list[dict]) -> None:
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(rows[-30:], ensure_ascii=False, indent=2), encoding="utf-8")


def apply_text(path: Path, new_text: str, relative: Callable[[Path], str], store: Path) -> str:
    """Пише файл, лишає file.bak і короткий diff. Новий файл позначається як created."""
    created = not path.exists()
    old = ""
    bak_name = ""
    if path.is_file():
        old = path.read_text(encoding="utf-8", errors="replace")
        bak = Path(str(path) + ".bak")
        bak.write_text(old, encoding="utf-8", newline="\n")
        bak_name = str(bak)
    if new_text and not new_text.endswith("\n"):
        new_text += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_text, encoding="utf-8", newline="\n")
    rel = relative(path)
    rows = _load_edits(store)
    rows.append({
        "path": rel,
        "bak": bak_name,
        "created": created,
        "at": datetime.now().isoformat(timespec="seconds"),
    })
    _save_edits(store, rows)
    diff = "".join(difflib.unified_diff(
        old.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=rel + (".bak" if old else "/dev/null"),
        tofile=rel,
        n=2,
    ))
    if not diff:
        diff = "(текст не змінився)\n"
    if len(diff) > 2200:
        diff = diff[:2200] + "\n… diff обрізано\n"
    note = f"копія: {Path(bak_name).name}" if bak_name else "новий файл, відкат видалить його"
    return f"{note}\n{diff}"


_SHELL_PREFIX = re.compile(
    r"^\s*(?:cmd(?:\.exe)?|%COMSPEC%)\s+(?:/d\s+)?(?:/s\s+)?(?:/q\s+)?/c\s+(?P<rest>.+)$",
    re.IGNORECASE | re.DOTALL,
)


def unwrap_shell_prefix(command: str) -> str:
    """Прибрати зайве ``cmd /c`` з початку команди на Windows.

    ``subprocess`` із ``shell=True`` на Windows сам обгортає рядок у
    ``cmd.exe /c "…"``. Якщо модель пише ``cmd /c dir /b``, виходить
    ``cmd /c "cmd /c dir /b"`` — вкладений cmd.exe віддає
    «Parameter format not correct - "b"» і команда падає з кодом 1.
    Тому явний префікс знімаємо, лишаючи саму команду оболонці.
    """
    if os.name != "nt":
        return command
    match = _SHELL_PREFIX.match(command or "")
    if not match:
        return command
    rest = match.group("rest").strip()
    if len(rest) >= 2 and rest[0] == rest[-1] == '"':
        rest = rest[1:-1]
    return rest or command


def _run(args: list[str], cwd: Path, timeout: int = 60) -> str:
    try:
        proc = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"Час вичерпано ({timeout} с): {' '.join(args)}"
    except FileNotFoundError:
        return _missing_tool(args[0])
    body = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    # Windows іноді віддає «не розпізнано» замість FileNotFoundError.
    if proc.returncode != 0 and ("is not recognized" in body or "не є внутрішньою" in body):
        return _missing_tool(args[0])
    return _clip(f"exit={proc.returncode}\n{body}".rstrip() + "\n")


def _missing_tool(name: str) -> str:
    """Зрозуміла підказка замість сирого тексту cmd.exe."""
    hint = {
        "git": ("Git не встановлено (або його немає в PATH). Завантаж із https://git-scm.com/download/win "
                "і перезапусти IDE — тоді запрацюють git_status, git_diff, git_log, git_show."),
        "npm": "Node.js/npm не встановлено — постав із https://nodejs.org і перезапусти IDE.",
        "docker": "Docker не встановлено або не запущено.",
    }.get(name.lower())
    if hint:
        return f"Інструмент недоступний: {hint}"
    return f"Команду не знайдено: {name} (перевір PATH або встанови її)."


class AgentTools:
    def __init__(self, workspace: Path, safe_path, read_text, walk_files, relative, rag, db_path: Path):
        self.workspace = workspace
        self.safe_path = safe_path
        self.read_text = read_text
        self.walk_files = walk_files
        self.relative = relative
        self.rag = rag
        self.db_path = db_path

    def routes(self) -> dict[str, Route]:
        return {
            "system_info": lambda q, p, e: self.system_info(),
            "list_intents": lambda q, p, e: self.list_intents(),
            "list_dir": lambda q, p, e: self.list_dir(p or q or ".", e),
            "glob_files": lambda q, p, e: self.glob_files(q, p or ".", e),
            "grep": lambda q, p, e: self.grep(q, p or ".", e),
            "find_symbol": lambda q, p, e: self.find_symbol(q, p or "."),
            "project_outline": lambda q, p, e: self.project_outline(p or q or "."),
            "project_map": lambda q, p, e: self.project_map(p or q or "."),
            "analyze_project": lambda q, p, e: self.analyze_project(p or q or "."),
            "index_symbols": lambda q, p, e: self.index_symbols(p or q or "."),
            "db_schema": lambda q, p, e: self.db_schema(p or q or "."),
            "remember_project": lambda q, p, e: self.remember_project(q or p),
            "read_file": lambda q, p, e: self.read_file(p or q, e),
            "read_files": lambda q, p, e: self.read_files(q or p),
            "write_file": lambda q, p, e: self.write_file(p, q, append=False),
            "append_file": lambda q, p, e: self.write_file(p, q, append=True),
            "replace_in_file": lambda q, p, e: self.replace_in_file(p, q, e, all_matches=False),
            "replace_all": lambda q, p, e: self.replace_in_file(p, q, e, all_matches=True),
            "replace_lines": lambda q, p, e: self.replace_lines(p, e, q),
            "delete_file": lambda q, p, e: self.delete_file(p or q, e),
            "move_file": lambda q, p, e: self.move_file(p, e or q, copy=False),
            "copy_file": lambda q, p, e: self.move_file(p, e or q, copy=True),
            "mkdir": lambda q, p, e: self.mkdir(p or q),
            "file_info": lambda q, p, e: self.file_info(p or q),
            "hash_file": lambda q, p, e: self.hash_file(p or q),
            "diff_files": lambda q, p, e: self.diff_files(p, e or q),
            "diagnostics": lambda q, p, e: self.diagnostics(p or q),
            "review_code": lambda q, p, e: self.review_code(p or q or "."),
            "run_shell": lambda q, p, e: self.run_shell(q, e),
            "run_tests": lambda q, p, e: self.run_shell(q or "pytest", e or "180"),
            "git_context": lambda q, p, e: self.git_context(),
            "git_diff": lambda q, p, e: self.git_diff(q),
            "git_log": lambda q, p, e: self.git_log(q),
            "git_show": lambda q, p, e: self.git_show(q),
            "search_web": lambda q, p, e: self.search_web(q),
            "finance_brief": lambda q, p, e: self.finance_brief(q or p),
            "fetch_url": lambda q, p, e: self.fetch_url(q or p),
            "rag_search": lambda q, p, e: self.rag_search(q, p),
            "index_project": lambda q, p, e: self.index_project(p or q or "."),
            "save_rule": lambda q, p, e: self.save_rule(q),
            "list_rules": lambda q, p, e: self.list_rules(),
            "refresh_memory": lambda q, p, e: self.refresh_stored_facts(),
            "todo_write": lambda q, p, e: self.todo_write(q, e),
            "todo_list": lambda q, p, e: self.todo_list(),
            "clear_cache": lambda q, p, e: self.clear_cache(q),
            "env_which": lambda q, p, e: self.env_which(q),
            "undo_edit": lambda q, p, e: self.undo_edit(p or q),
            "night_shift": lambda q, p, e: self.night_shift(q or p),
        }

    def list_intents(self) -> str:
        groups = {
            "огляд": "system_info, list_intents, list_dir, glob_files, project_outline, project_map, file_info, env_which",
            "читання": "read_file, read_files, grep, find_symbol, hash_file, diff_files, diagnostics, review_code, db_schema",
            "великий проєкт": "index_symbols, project_map, analyze_project, remember_project, db_schema, preview_local",
            "запис": "write_file, append_file, replace_in_file, replace_all, replace_lines, mkdir, move_file, copy_file, delete_file, undo_edit",
            "термінал": "run_shell, run_tests",
            "git": "git_context, git_diff, git_log, git_show",
            "мережа": "search_web, fetch_url, ask_browser_ai, finance_brief, social_post",
            "пам'ять": "rag_search, save_rule, list_rules, refresh_memory, todo_write, todo_list, clear_cache, index_project, run_and_repair",
            "ніч": "night_shift",
        }
        return "\n".join(f"{name}: {items}" for name, items in groups.items())

    def system_info(self) -> str:
        return json.dumps({
            "python": platform.python_version(),
            "os": platform.platform(),
            "cpu": platform.processor(),
            "workspace": str(self.workspace),
            "rag": self.rag is not None,
            "db": str(self.db_path),
        }, ensure_ascii=False, indent=2)

    def list_dir(self, raw: str, extra: str) -> str:
        root = self.safe_path(raw or ".", must_exist=True)
        depth = int(extra) if extra.strip().isdigit() else 1
        lines = [f"{self.relative(root)}/"]
        self._tree(root, lines, depth, 0)
        return _clip("\n".join(lines))

    def _tree(self, folder: Path, lines: list[str], depth: int, level: int) -> None:
        if level >= depth:
            return
        try:
            entries = sorted(folder.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError as exc:
            lines.append(f"{'  ' * level}! {exc}")
            return
        for entry in entries:
            if entry.name in SKIP_DIRS or entry.name.startswith("."):
                continue
            rel = self.relative(entry)
            if entry.is_dir():
                lines.append(f"{rel}/")
                self._tree(entry, lines, depth, level + 1)
            else:
                lines.append(f"{rel}  ({entry.stat().st_size} B)")
            if len(lines) > 400:
                lines.append("… список обрізано")
                return

    def glob_files(self, pattern: str, root: str, extra: str) -> str:
        if not pattern.strip():
            return "Потрібен query з шаблоном, наприклад **/*.py"
        base = self.safe_path(root or ".", must_exist=True)
        pat = pattern.replace("\\", "/")
        found: list[str] = []
        for path in self.walk_files(base):
            rel = self.relative(path)
            if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(path.name, pat) or fnmatch.fnmatch(rel, extra or pat):
                found.append(rel)
            if len(found) >= 200:
                break
        if not found:
            return f"Нічого не знайдено для '{pattern}' у {self.relative(base)}"
        return _clip("\n".join(found))

    def grep(self, pattern: str, root: str, glob_pat: str) -> str:
        if not pattern.strip():
            return "Потрібен query з текстом або регулярним виразом."
        try:
            rx = re.compile(pattern)
        except re.error:
            rx = re.compile(re.escape(pattern))
        base = self.safe_path(root or ".", must_exist=True)
        hits: list[str] = []
        files = [base] if base.is_file() else list(self.walk_files(base))
        for path in files:
            rel = self.relative(path)
            if glob_pat and not (fnmatch.fnmatch(path.name, glob_pat) or fnmatch.fnmatch(rel, glob_pat)):
                continue
            if path.stat().st_size > 1_000_000:
                continue
            try:
                text = self.read_text(path)
            except (OSError, ValueError, UnicodeError):
                continue
            for num, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{rel}:{num}:{line.strip()[:240]}")
                    if len(hits) >= 80:
                        return _clip("\n".join(hits) + "\n… ліміт 80 збігів")
        return _clip("\n".join(hits) if hits else f"Збігів для '{pattern}' немає.")

    def find_symbol(self, name: str, root: str) -> str:
        name = name.strip()
        if not name:
            return "Потрібен query з назвою функції, класу або символу."
        cached = self._symbols_lookup(name)
        if cached:
            return cached
        base = self.safe_path(root or ".", must_exist=True)
        hits: list[str] = []
        files = [base] if base.is_file() else list(self.walk_files(base))
        for path in files:
            if path.suffix.lower() not in {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".cs", ".cpp", ".c", ".h", ".hpp", ".md"}:
                continue
            try:
                text = self.read_text(path)
            except (OSError, ValueError):
                continue
            rel = self.relative(path)
            if path.suffix.lower() == ".py":
                try:
                    tree = ast.parse(text)
                except SyntaxError:
                    tree = None
                if tree is not None:
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
                            hits.append(f"{rel}:{node.lineno}: {type(node).__name__} {node.name}")
                    if hits and len(hits) >= 40:
                        break
                    continue
            for num, line in enumerate(text.splitlines(), 1):
                if re.search(rf"\b{re.escape(name)}\b", line):
                    hits.append(f"{rel}:{num}:{line.strip()[:200]}")
                    if len(hits) >= 40:
                        break
        if hits:
            return _clip("\n".join(hits) + "\nІндекс символів цього ще не мав. Скажи «проіндексуй проєкт», щоб наступний пошук був по базі, без перечитування всього дерева.")
        return f"Символ '{name}' не знайдено. Для великого репозиторію спочатку скажи «проіндексуй проєкт»."

    def project_outline(self, raw: str) -> str:
        root = self.safe_path(raw or ".", must_exist=True)
        counts: dict[str, int] = {}
        dirs: list[str] = []
        for current, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            rel = self.relative(Path(current))
            if rel.count("/") < 3:
                dirs.append(rel + "/")
            for name in filenames:
                ext = Path(name).suffix.lower() or "(без розширення)"
                counts[ext] = counts.get(ext, 0) + 1
            if len(dirs) > 80:
                break
        ranked = ", ".join(f"{ext}:{n}" for ext, n in sorted(counts.items(), key=lambda kv: -kv[1])[:12])
        return _clip("Папки:\n" + "\n".join(dirs) + f"\n\nФайли за типом: {ranked}")

    def symbol_count(self) -> int:
        conn = self._db()
        try:
            return int(conn.execute("SELECT COUNT(*) FROM code_symbols").fetchone()[0])
        except sqlite3.Error:
            return 0
        finally:
            conn.close()

    def notes_brief(self) -> str:
        conn = self._db()
        try:
            rows = conn.execute("SELECT note FROM project_notes ORDER BY id DESC LIMIT 4").fetchall()
        except sqlite3.Error:
            return ""
        finally:
            conn.close()
        return " | ".join((row[0] or "").replace("\n", " ")[:140] for row in rows)

    def _symbols_lookup(self, name: str) -> str:
        conn = self._db()
        try:
            rows = conn.execute(
                "SELECT path, line, kind, signature FROM code_symbols WHERE name = ? ORDER BY path LIMIT 30",
                (name,),
            ).fetchall()
        except sqlite3.Error:
            return ""
        finally:
            conn.close()
        if not rows:
            return ""
        lines = [f"{row[0]}:{row[1]}: {row[2]} {name} {row[3] or ''}".rstrip() for row in rows]
        return "З індексу символів:\n" + "\n".join(lines)

    def index_symbols(self, raw: str) -> str:
        """Будує локальний індекс функцій і класів, щоб великий репозиторій не читався цілком."""
        root = self.safe_path(raw or ".", must_exist=True)
        files = [root] if root.is_file() else [
            path for path in self.walk_files(root)
            if path.suffix.lower() in {".py", ".js", ".ts", ".tsx", ".jsx"} and path.stat().st_size <= 400_000
        ]
        updated = 0
        skipped = 0
        symbols = 0
        conn = self._db()
        try:
            for path in files[:5000]:
                rel = self.relative(path)
                mtime = path.stat().st_mtime
                old = conn.execute("SELECT mtime FROM code_symbols WHERE path = ? LIMIT 1", (rel,)).fetchone()
                if old and abs(float(old[0] or 0) - mtime) < 1:
                    skipped += 1
                    continue
                try:
                    text = self.read_text(path)
                except (OSError, ValueError):
                    continue
                found = self._extract_symbols(path, text)
                conn.execute("DELETE FROM code_symbols WHERE path = ?", (rel,))
                conn.executemany(
                    "INSERT OR REPLACE INTO code_symbols(path, name, kind, line, signature, mtime) VALUES(?,?,?,?,?,?)",
                    [(rel, name, kind, line, signature, mtime) for name, kind, line, signature in found],
                )
                updated += 1
                symbols += len(found)
            conn.commit()
            total = int(conn.execute("SELECT COUNT(*) FROM code_symbols").fetchone()[0])
        finally:
            conn.close()
        return f"Індекс символів: оновлено файлів {updated}, без змін {skipped}, нових символів {symbols}, усього в базі {total}."

    def _extract_symbols(self, path: Path, text: str) -> list[tuple[str, str, int, str]]:
        found: list[tuple[str, str, int, str]] = []
        if path.suffix.lower() == ".py":
            try:
                tree = ast.parse(text)
            except SyntaxError:
                return found
            lines = text.splitlines()
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    kind = "class" if isinstance(node, ast.ClassDef) else "function"
                    signature = lines[node.lineno - 1].strip()[:160] if node.lineno <= len(lines) else node.name
                    found.append((node.name, kind, node.lineno, signature))
            return found
        pattern = re.compile(
            r"^\s*(?:export\s+)?(?:async\s+)?(?:function\s+([A-Za-z_$][\w$]*)|class\s+([A-Za-z_$][\w$]*))",
            re.M,
        )
        for match in pattern.finditer(text):
            name = match.group(1) or match.group(2)
            line = text.count("\n", 0, match.start()) + 1
            kind = "class" if match.group(2) else "function"
            found.append((name, kind, line, match.group(0).strip()[:160]))
        return found

    def remember_project(self, text: str) -> str:
        note = re.sub(
            r"^(запам['’ʼ]?ятай для проєкту|запам['’ʼ]?ятай про проєкт|у цьому проєкті)\s*:?\s*",
            "",
            (text or "").strip(),
            flags=re.I,
        ).strip()
        if len(note) < 4:
            return "Напиши, що запам'ятати про цей проєкт."
        note = note[:2000]
        digest = hashlib.sha256(note.encode("utf-8")).hexdigest()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        conn = self._db()
        try:
            rows = conn.execute("SELECT id, note FROM project_notes").fetchall()
            matches = [
                (LocalRAG.fact_overlap(note, row[1] or ""), int(row[0]))
                for row in rows
                if LocalRAG.same_fact(note, row[1] or "")
            ]
            matches.sort(reverse=True)
            if matches:
                keep = matches[0][1]
                for _score, other in matches[1:]:
                    conn.execute("DELETE FROM project_notes WHERE id=?", (other,))
                conn.execute(
                    "UPDATE project_notes SET note=?, note_hash=?, updated=? WHERE id=?",
                    (note, digest, now, keep),
                )
                conn.commit()
                message = f"Оновив нотатку проєкту, id={keep}: {note[:300]}"
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO project_notes(note, note_hash, updated) VALUES(?,?,?)",
                    (note, digest, now),
                )
                conn.commit()
                message = f"Запам'ятав для проєкту: {note[:300]}"
        finally:
            conn.close()
        if self.rag is not None and hasattr(self.rag, "remember"):
            self.rag.remember(note[:1500], "project")
        return message

    def db_schema(self, raw: str) -> str:
        target = self.safe_path(raw or ".", must_exist=True)
        if target.is_file():
            databases = [target] if target.suffix.lower() in {".db", ".sqlite", ".sqlite3"} else []
        else:
            databases = [
                path for path in self.walk_files(target)
                if path.suffix.lower() in {".db", ".sqlite", ".sqlite3"} and ".mcp_rag" not in path.parts
            ][:8]
        if not databases:
            return "У проєкті не видно файлів SQLite (.db, .sqlite). Вкажи шлях до бази."
        blocks = []
        for path in databases:
            try:
                conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
            except sqlite3.Error as exc:
                blocks.append(f"{self.relative(path)}: {exc}")
                continue
            try:
                tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
                lines = [f"{self.relative(path)}: {len(tables)} таблиць"]
                for table in tables[:20]:
                    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
                        continue
                    columns = conn.execute(f"PRAGMA table_info({table})").fetchall()
                    described = ", ".join(f"{col[1]}:{col[2] or 'any'}" for col in columns)
                    lines.append(f"  {table}({described})")
                blocks.append("\n".join(lines))
            except sqlite3.Error as exc:
                blocks.append(f"{self.relative(path)}: {exc}")
            finally:
                conn.close()
        return _clip("\n\n".join(blocks))

    def project_map(self, raw: str) -> str:
        outline = self.project_outline(raw)
        notes = self.notes_brief() or "нотаток проєкту ще немає"
        count = self.symbol_count()
        root = self.safe_path(raw or ".", must_exist=True)
        docs = []
        if root.is_dir():
            for path in self.walk_files(root):
                if path.suffix.lower() in {".md", ".mdx", ".rst"}:
                    docs.append(self.relative(path))
                if len(docs) >= 12:
                    break
        hint = "Символів у індексі: " + str(count) + "."
        if count == 0:
            hint += " Скажи «проіндексуй проєкт», щоб зібрати функції й класи без читання всього дерева."
        doc_line = "Документи: " + ", ".join(docs) if docs else "Окремих документів не видно."
        return _clip(f"{hint}\nНотатки: {notes}\n{doc_line}\n\n{outline}")

    def analyze_project(self, raw: str) -> str:
        """Фактичний розбір репозиторію. Не вигадує інструменти, яких немає в агенті."""
        root = self.safe_path(raw or ".", must_exist=True)
        markers = {
            "requirements.txt": "залежності Python",
            "pyproject.toml": "пакування Python",
            "package.json": "залежності Node",
            "Dockerfile": "контейнер",
            "docker-compose.yml": "compose",
            ".github/workflows": "GitHub Actions",
        }
        present = []
        missing = []
        for name, label in markers.items():
            candidate = root / name if root.is_dir() else root.parent / name
            if candidate.exists():
                present.append(f"{label}: {name}")
            else:
                missing.append(f"немає {name} ({label})")
        tests = 0
        if root.is_dir():
            for path in self.walk_files(root):
                if path.name.startswith("test_") or path.name.endswith("_test.py"):
                    tests += 1
        return _clip(
            "Це вже є в агенті, нові сервери підключати не треба:\n"
            + self.list_intents()
            + f"\n\nФайли проєкту:\n{self.project_map(raw)}\n\n"
            + "Знайдено: " + (", ".join(present) if present else "типових маркерів мало")
            + f"\nТестових файлів: {tests}."
            + "\nЧого немає у дереві: " + "; ".join(missing)
            + "\nНе пропонуй Kubernetes, Prometheus, сканер, лог-аналізатор, моніторинг, генератор документації чи менеджер агентів, якщо цього немає в списку дій вище."
            + "\nНе пиши «ймовірно»: призначення файлів бери з цього результату."
        )

    def read_file(self, raw: str, extra: str) -> str:
        path = self.safe_path(raw, must_exist=True)
        if path.is_dir():
            return self.list_dir(raw, "1")
        text = self.read_text(path)
        lines = text.splitlines()
        start, end = 1, len(lines)
        if extra.strip() and extra.strip().lower() != "raw":
            part = extra.replace(" ", "")
            if ":" in part:
                a, b = part.split(":", 1)
                start = int(a) if a else 1
                end = int(b) if b else len(lines)
            elif part.isdigit():
                start = int(part)
                end = min(len(lines), start + 199)
        start = max(1, start)
        end = min(len(lines), end)
        if end < start:
            return f"Порожній діапазон {start}:{end}. У файлі {len(lines)} рядків."
        if end - start + 1 > MAX_READ_LINES:
            end = start + MAX_READ_LINES - 1
        body = [f"{i}|{lines[i - 1]}" for i in range(start, end + 1)]
        more = len(lines) - end
        note = ""
        if more > 0:
            nxt = min(len(lines), end + MAX_READ_LINES)
            note = f"є ще {more} рядків, попроси діапазон {end + 1}:{nxt}\n"
        header = f"{self.relative(path)}  рядки {start}-{end} з {len(lines)}"
        return _clip(note + header + "\n" + "\n".join(body))

    def read_files(self, raw: str) -> str:
        paths = [p.strip() for p in re.split(r"[\n,;]", raw) if p.strip()]
        if not paths:
            return "Передай шляхи в query, по одному на рядок."
        chunks = []
        for item in paths[:12]:
            try:
                chunks.append(self.read_file(item, "1:80"))
            except Exception as exc:
                chunks.append(f"{item}: {type(exc).__name__}: {exc}")
        return _clip("\n\n".join(chunks))

    def write_file(self, raw: str, content: str, append: bool) -> str:
        if not raw.strip():
            return "Потрібен file_path."
        path = self.safe_path(raw, must_exist=False)
        old = self.read_text(path) if path.is_file() else ""
        new_text = (old + content) if append else content
        summary = apply_text(path, new_text, self.relative, edits_store(self.db_path))
        verb = "Дописано" if append else "Записано"
        return f"{verb} {self.relative(path)} ({path.stat().st_size} B)\n{summary}"

    def replace_in_file(self, raw: str, old: str, new: str, all_matches: bool) -> str:
        if not raw.strip() or old == "":
            return "Потрібні file_path і query (текст, який замінити)."
        path = self.safe_path(raw, must_exist=True)
        text = self.read_text(path)
        count = text.count(old)
        if count == 0:
            return f"Фрагмент не знайдено в {self.relative(path)}. Уточни query."
        if all_matches:
            updated = text.replace(old, new)
            replaced = count
        else:
            updated = text.replace(old, new, 1)
            replaced = 1
        summary = apply_text(path, updated, self.relative, edits_store(self.db_path))
        left = count - replaced
        return f"Замінено {replaced} у {self.relative(path)}. Залишилось входжень: {left}.\n{summary}"

    def replace_lines(self, raw: str, span: str, new_text: str) -> str:
        if ":" not in span:
            return "extra має бути діапазоном рядків, наприклад 10:12"
        path = self.safe_path(raw, must_exist=True)
        lines = self.read_text(path).splitlines()
        a, b = span.replace(" ", "").split(":", 1)
        start, end = int(a), int(b)
        if start < 1 or end > len(lines) or end < start:
            return f"Діапазон {start}:{end} поза файлом ({len(lines)} рядків)."
        fresh = new_text.splitlines()
        lines[start - 1:end] = fresh
        summary = apply_text(path, "\n".join(lines) + "\n", self.relative, edits_store(self.db_path))
        return f"Рядки {start}:{end} у {self.relative(path)} замінено на {len(fresh)} рядків.\n{summary}"

    def delete_file(self, raw: str, extra: str) -> str:
        path = self.safe_path(raw, must_exist=True)
        if path.resolve() == self.workspace.resolve():
            return "Відмова: не видаляю корінь робочої папки."
        if path.is_dir():
            if extra.strip() != "tree":
                return "Це папка. Для видалення дерева передай extra=tree."
            shutil.rmtree(path)
            return f"Папку видалено: {self.relative(path)}"
        path.unlink()
        return f"Файл видалено: {self.relative(path)}"

    def move_file(self, src: str, dst: str, copy: bool) -> str:
        if not src.strip() or not dst.strip():
            return "Потрібні file_path (звідки) і extra (куди)."
        source = self.safe_path(src, must_exist=True)
        target = self.safe_path(dst, must_exist=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        if copy:
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
            verb = "Скопійовано"
        else:
            shutil.move(str(source), str(target))
            verb = "Переміщено"
        return f"{verb}: {self.relative(source)} -> {self.relative(target)}"

    def mkdir(self, raw: str) -> str:
        path = self.safe_path(raw, must_exist=False)
        path.mkdir(parents=True, exist_ok=True)
        return f"Папка готова: {self.relative(path)}"

    def file_info(self, raw: str) -> str:
        path = self.safe_path(raw, must_exist=True)
        stat = path.stat()
        kind = "dir" if path.is_dir() else "file"
        return json.dumps({
            "path": self.relative(path),
            "kind": kind,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        }, ensure_ascii=False)

    def hash_file(self, raw: str) -> str:
        path = self.safe_path(raw, must_exist=True)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return f"{self.relative(path)} sha256={digest}"

    def diff_files(self, left: str, right: str) -> str:
        a = self.safe_path(left, must_exist=True)
        b = self.safe_path(right, must_exist=True)
        da = self.read_text(a).splitlines(keepends=True)
        db = self.read_text(b).splitlines(keepends=True)
        diff = "".join(difflib.unified_diff(da, db, fromfile=self.relative(a), tofile=self.relative(b)))
        return _clip(diff or "Файли однакові.")

    def diagnostics(self, raw: str) -> str:
        path = self.safe_path(raw, must_exist=True)
        if path.suffix.lower() != ".py":
            return "diagnostics зараз перевіряє синтаксис Python. Передай file_path на .py файл."
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            return f"Синтаксична помилка в {self.relative(path)}:\n{exc.msg}"
        return f"Синтаксис у порядку: {self.relative(path)}"

    def review_code(self, raw: str) -> str:
        """Перевіряє свій код: синтаксис, застарілі конструкції і ризиковані місця. Нічого не змінює."""
        target = self.safe_path(raw or ".", must_exist=True)
        if target.is_file():
            files = [target]
        else:
            files = [
                path for path in self.walk_files(target)
                if path.suffix.lower() in {".py", ".js", ".ts", ".tsx", ".jsx"}
            ][:40]
        if not files:
            return "Немає файлів коду для перевірки."
        findings: list[str] = []
        syntax_ok = 0
        for path in files:
            findings.extend(self._review_one(path))
            if path.suffix.lower() == ".py":
                try:
                    py_compile.compile(str(path), doraise=True)
                    syntax_ok += 1
                except py_compile.PyCompileError as exc:
                    findings.append(f"{self.relative(path)}: синтаксис: {exc.msg}")
        ruff = shutil.which("ruff")
        if ruff and any(path.suffix.lower() == ".py" for path in files):
            scope = str(target if target.is_dir() else target.parent)
            proc = subprocess.run(
                [ruff, "check", scope, "--select", "E,F,B", "--quiet"],
                cwd=self.workspace, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=60,
            )
            tail = ((proc.stdout or "") + (proc.stderr or "")).strip()
            if tail:
                findings.append("ruff:\n" + tail[:1500])
        if not findings:
            return f"Перевірив {len(files)} файлів. Синтаксис Python у порядку ({syntax_ok}). Зауважень немає."
        shown = findings[:35]
        more = len(findings) - len(shown)
        tail_note = f"\n… ще {more} зауважень." if more else ""
        return _clip(
            f"Перевірив {len(files)} файлів. Зауважень: {len(findings)}.\n"
            + "\n".join(shown)
            + tail_note
        )

    def _review_one(self, path: Path) -> list[str]:
        patterns = (
            (r"except\s*:", "голий except ховає помилку"),
            (r"\beval\s*\(", "eval виконує текст як код"),
            (r"\bexec\s*\(", "exec виконує текст як код"),
            (r"shell\s*=\s*True", "запуск команди через shell=True"),
            (r"(?i)(password|secret|api_key|token)\s*=\s*['\"][^'\"]{6,}['\"]", "схоже на секрет, записаний прямо в коді"),
            (r"\bdf\w*\.append\s*\(", "DataFrame.append прибрали в pandas 2, потрібен concat"),
            (r"asyncio\.get_event_loop\s*\(", "get_event_loop застарів, краще asyncio.run"),
            (r"\bos\.popen\s*\(", "os.popen застарів, краще subprocess.run"),
            (r"innerHTML\s*=", "запис у innerHTML легко перетворюється на XSS, якщо там чужий текст"),
        )
        try:
            text = self.read_text(path)
        except (OSError, ValueError) as exc:
            return [f"{self.relative(path)}: не прочитав ({exc})"]
        rel = self.relative(path)
        notes: list[str] = []
        for num, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            for pattern, message in patterns:
                if re.search(pattern, line):
                    notes.append(f"{rel}:{num}: {message}")
                    break
            if len(notes) >= 12:
                break
        if path.suffix.lower() == ".py":
            try:
                tree = ast.parse(text)
            except SyntaxError:
                tree = None
            if tree is not None:
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        for default in node.args.defaults + node.args.kw_defaults:
                            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                                notes.append(f"{rel}:{node.lineno}: у {node.name} змінюваний аргумент за замовчуванням")
                                break
        return notes[:12]

    def run_shell(self, command: str, extra: str) -> str:
        if not command.strip():
            return "Потрібен query з командою."
        timeout = int(extra) if extra.strip().isdigit() else 120
        timeout = max(1, min(timeout, 300))
        try:
            proc = subprocess.run(
                unwrap_shell_prefix(command), shell=True, cwd=self.workspace,
                capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            return _clip(f"Час вичерпано ({timeout} с)\n{exc.stdout or ''}\n{exc.stderr or ''}")
        return _clip(f"exit={proc.returncode}\n{(proc.stdout or '')}{(proc.stderr or '')}")

    def git_context(self) -> str:
        parts = [
            _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], self.workspace),
            _run(["git", "status", "--short", "--branch"], self.workspace),
            _run(["git", "diff", "--stat"], self.workspace),
        ]
        return _clip("\n".join(parts))

    def git_diff(self, query: str) -> str:
        args = ["git", "diff"]
        if query.strip():
            args.extend(["--", query.strip()])
        return _run(args, self.workspace)

    def git_log(self, query: str) -> str:
        limit = query.strip() if query.strip().isdigit() else "15"
        return _run(["git", "log", f"-n{limit}", "--oneline", "--decorate"], self.workspace)

    def git_show(self, query: str) -> str:
        rev = query.strip() or "HEAD"
        return _run(["git", "show", "--stat", "--format=fuller", rev], self.workspace)

    def finance_brief(self, query: str) -> str:
        """Ціни і заголовки з відкритих джерел. Не обирає угоду і не обіцяє прибуток."""
        coins = self._coin_markets(query)
        headlines = self._finance_headlines(query)
        lines = ["Огляд ринку. Це довідка з відкритих цифр, не порада купувати і не сигнал «коли входити»."]
        if coins:
            lines.append("Монети (USD, CoinGecko):")
            ordered = sorted(coins, key=lambda item: item.get("change_24h") or 0, reverse=True)
            for coin in ordered[:8]:
                price = coin["price"]
                change = coin.get("change_24h")
                change_text = "н/д" if change is None else f"{change:+.1f}% за 24 год"
                lines.append(
                    f"- {coin['name']} ({coin['symbol']}): ${price:,.4f} · {change_text} · обсяг ${coin['volume']:,.0f}"
                )
            leader = ordered[0]
            lines.append(
                f"За останню добу серед показаних найбільше змінився {leader['name']} ({leader['change_24h']:+.1f}%). "
                "Минула зміна ціни не каже, чи купувати."
            )
        else:
            lines.append("Ціни зараз не віддались. Спробуй ще раз трохи пізніше.")
        if headlines:
            lines.append("Свіжі заголовки:")
            lines.extend(f"- {title}" for title in headlines[:6])
        else:
            lines.append("Заголовки новин зараз не віддались.")
        lines.append("Рішення про гроші лишається за тобою. Можна втратити всю суму.")
        return _clip("\n".join(lines))

    def _coin_markets(self, query: str) -> list[dict]:
        known = {
            "бітк": "bitcoin", "bitcoin": "bitcoin", "btc": "bitcoin",
            "ефір": "ethereum", "ether": "ethereum", "eth": "ethereum",
            "солана": "solana", "sol": "solana", "solana": "solana",
            "рипл": "ripple", "xrp": "ripple",
            "дог": "dogecoin", "doge": "dogecoin",
            "тон": "the-open-network", "ton": "the-open-network",
        }
        low = (query or "").lower()
        ids = [coin_id for word, coin_id in known.items() if word in low]
        params = {"vs_currency": "usd", "order": "market_cap_desc", "per_page": "8", "page": "1", "price_change_percentage": "24h"}
        if ids:
            params["ids"] = ",".join(dict.fromkeys(ids))
            params["order"] = "market_cap_desc"
        url = "https://api.coingecko.com/api/v3/coins/markets?" + urllib.parse.urlencode(params)
        try:
            payload = self._http_json(url)
        except Exception:
            return []
        if not isinstance(payload, list):
            return []
        rows = []
        for item in payload:
            try:
                rows.append({
                    "name": str(item.get("name") or ""),
                    "symbol": str(item.get("symbol") or "").upper(),
                    "price": float(item.get("current_price") or 0),
                    "change_24h": None if item.get("price_change_percentage_24h") is None else float(item["price_change_percentage_24h"]),
                    "volume": float(item.get("total_volume") or 0),
                })
            except (TypeError, ValueError):
                continue
        return rows

    def _finance_headlines(self, query: str) -> list[str]:
        topic = (query or "криптовалюта фінанси").strip() or "криптовалюта фінанси"
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({
            "q": topic + " фінанси",
            "hl": "uk",
            "gl": "UA",
            "ceid": "UA:uk",
        })
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                xml = resp.read(400_000).decode("utf-8", errors="ignore")
        except Exception:
            return []
        titles = re.findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", xml, flags=re.S)
        clean = []
        for title in titles:
            text = re.sub(r"<[^>]+>", "", title)
            text = text.replace("&amp;", "&").replace("&#39;", "'").strip()
            if not text or text in clean:
                continue
            if "Google" in text and "Новин" in text:
                continue
            if text.strip('"') == topic or text.strip('"').startswith(topic):
                continue
            clean.append(text)
        return clean[:6]

    def _http_json(self, url: str):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))

    def search_web(self, query: str) -> str:
        """Збирає довідку з кількох відкритих сервісів: вікі, погода, курс, сторінки."""
        query = (query or "").strip()
        if not query:
            return "Потрібен query для пошуку."
        blocks = [f"Довідка з мережі для: {query}"]
        place = self._place_name(query)
        wiki = self._wiki_brief(place or query)
        if wiki:
            blocks.append(wiki)
        instant = self._ddg_instant(query)
        if instant:
            blocks.append(instant)
        weather = self._weather_brief(query)
        if weather:
            blocks.append(weather)
        rates = self._currency_brief(query)
        if rates:
            blocks.append(rates)
        pages = self._web_pages(query)
        if pages:
            blocks.append("Сторінки:\n" + pages)
        if len(blocks) == 1:
            return "Сервіси зараз нічого не віддали. Спробуй коротший запит або конкретне посилання."
        blocks.append("Якщо потрібен повний текст сторінки, попроси відкрити її посилання.")
        return _clip("\n\n".join(blocks))

    def _wiki_brief(self, query: str) -> str:
        for lang in ("uk", "en"):
            try:
                search_url = (
                    f"https://{lang}.wikipedia.org/w/api.php?"
                    + urllib.parse.urlencode({
                        "action": "query", "list": "search", "srsearch": query,
                        "utf8": "1", "format": "json", "srlimit": "1",
                    })
                )
                found = self._http_json(search_url)
                hits = ((found.get("query") or {}).get("search") or [])
                if not hits:
                    continue
                title = hits[0].get("title") or ""
                summary_url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title.replace(" ", "_"))
                summary = self._http_json(summary_url)
                extract = (summary.get("extract") or "").strip()
                page = summary.get("content_urls", {}).get("desktop", {}).get("page") or ""
                if not extract:
                    continue
                return f"Вікіпедія ({lang}): {title}\n{extract[:700]}\n{page}".rstrip()
            except Exception:
                continue
        return ""

    def _ddg_instant(self, query: str) -> str:
        url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode({
            "q": query, "format": "json", "no_html": "1", "skip_disambig": "1",
        })
        try:
            data = self._http_json(url)
        except Exception:
            return ""
        abstract = (data.get("AbstractText") or data.get("Answer") or "").strip()
        if not abstract:
            return ""
        heading = (data.get("Heading") or "DuckDuckGo").strip()
        source = (data.get("AbstractURL") or "").strip()
        return f"Коротка відповідь ({heading}):\n{abstract[:500]}\n{source}".rstrip()

    def _weather_brief(self, query: str) -> str:
        low = query.lower()
        if not any(word in low for word in ("погод", "weather", "температур", "прогноз")):
            return ""
        place = self._place_name(query) or "Київ"
        try:
            city = None
            for candidate in self._place_candidates(place):
                geo = self._http_json(
                    "https://geocoding-api.open-meteo.com/v1/search?"
                    + urllib.parse.urlencode({"name": candidate, "count": "1", "language": "uk"})
                )
                city = (geo.get("results") or [None])[0]
                if city:
                    break
            if not city:
                return f"Погода: місце «{place}» не знайшлось."
            forecast = self._http_json(
                "https://api.open-meteo.com/v1/forecast?"
                + urllib.parse.urlencode({
                    "latitude": city["latitude"],
                    "longitude": city["longitude"],
                    "current": "temperature_2m,wind_speed_10m,weather_code",
                    "timezone": "auto",
                })
            )
            current = forecast.get("current") or {}
            names = {0: "ясно", 1: "переважно ясно", 2: "мінлива хмарність", 3: "хмарно", 45: "туман", 61: "дощ", 63: "дощ", 71: "сніг", 80: "злива", 95: "гроза"}
            sky = names.get(int(current.get("weather_code") or 0), "змінна погода")
            return (
                f"Погода в {city.get('name')}, {city.get('country')}: "
                f"{current.get('temperature_2m')}°C, {sky}, вітер {current.get('wind_speed_10m')} км/год."
            )
        except Exception:
            return ""

    def _currency_brief(self, query: str) -> str:
        low = query.lower()
        if any(word in low for word in ("бітк", "крипт", "bitcoin", "ethereum")):
            return ""
        if not any(word in low for word in ("долар", "євро", "валют", "usd", "eur", "грив", "курс")):
            return ""
        try:
            data = self._http_json("https://api.frankfurter.app/latest?from=USD&to=UAH,EUR")
            rates = data.get("rates") or {}
            return (
                f"Курс на {data.get('date')} (Frankfurter): "
                f"1 USD = {rates.get('UAH')} UAH, 1 USD = {rates.get('EUR')} EUR."
            )
        except Exception:
            return ""

    def _place_name(self, query: str) -> str:
        found = re.search(r"погод[ауи]?\s+(?:в|у|на)\s+([A-Za-zА-Яа-яІіЇїЄєҐґ'’\-]{2,40})", query, flags=re.I)
        if found:
            return found.group(1).strip()
        return ""

    def _place_candidates(self, place: str) -> list[str]:
        names = [place]
        if len(place) > 4 and place.endswith(("і", "у", "ю", "ї")):
            names.append(place[:-1])
        return names

    def _web_pages(self, query: str) -> str:
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
        except Exception:
            return ""
        links = re.findall(
            r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            html, flags=re.I | re.S,
        ) or re.findall(
            r'<a[^>]*href="([^"]+)"[^>]*class="result__a"[^>]*>(.*?)</a>',
            html, flags=re.I | re.S,
        )
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)>', html, flags=re.I | re.S)
        rows = []
        for idx, (href, title) in enumerate(links[:5]):
            clean_title = re.sub(r"<[^>]+>", "", title).strip()
            snippet = re.sub(r"<[^>]+>", "", snippets[idx]).strip() if idx < len(snippets) else ""
            real = href
            parsed = urllib.parse.urlparse(href)
            target = urllib.parse.parse_qs(parsed.query).get("uddg", [])
            if target:
                real = urllib.parse.unquote(target[0])
            rows.append(f"{idx + 1}. {clean_title}\n   {snippet}\n   {real}")
        return "\n".join(rows)

    def fetch_url(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            return "query має бути http(s) адресою."
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "text/html,application/xhtml+xml,*/*",
        })
        raw = self._fetch_body(req)
        if raw is None:
            return (f"Не вдалось завантажити {url}: сертифікат або з'єднання. "
                    "Спробуй http:// або іншу адресу.")
        text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return f"Сторінка {url} порожня або без тексту."
        return _clip(text)

    @staticmethod
    def _fetch_body(req: "urllib.request.Request") -> str | None:
        """Завантажити сторінку, м'яко обходячи проблеми з сертифікатами.

        На Windows без свіжих кореневих сертифікатів (або за корпоративного
        проксі) стандартна перевірка падає з CERTIFICATE_VERIFY_FAILED. Для
        читання публічної сторінки це не критично, тому робимо один повтор
        без перевірки — і чесно позначаємо це в журналі.
        """
        import ssl

        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.read(500_000).decode("utf-8", errors="ignore")
        except urllib.error.URLError as exc:
            if not isinstance(exc.reason, ssl.SSLError) and "CERTIFICATE" not in str(exc):
                return None
        except Exception:  # noqa: BLE001 - мережа буває будь-якою
            return None
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        try:
            with urllib.request.urlopen(req, timeout=20, context=context) as resp:
                return resp.read(500_000).decode("utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            return None

    def rag_search(self, query: str, path_prefix: str) -> str:
        if self.rag is None:
            return "Локальний RAG не імпортовано."
        if not query.strip():
            return "Потрібен query для rag_search."
        recall = getattr(self.rag, "recall", None)
        if recall is not None:
            return _clip(recall(query, path_prefix=path_prefix or ""))
        return _clip(self.rag.search(query, path_prefix=path_prefix or ""))

    def index_project(self, raw: str) -> str:
        """Проіндексувати робочу теку для RAG (файли + пам'ять).

        Маршрут ``index_project`` був оголошений у списку інтентів, але
        обробника не існувало — тепер викликає справжній ``index_workspace``.
        """
        if self.rag is None:
            return "Локальний RAG не імпортовано, індексувати нема чим."
        root = self.safe_path(raw or ".", must_exist=True)
        index = getattr(self.rag, "index_workspace", None)
        if index is None:
            return "У RAG немає методу index_workspace."
        try:
            result = index(root)
        except TypeError:
            result = index()
        except Exception as exc:  # noqa: BLE001 - показуємо причину моделі
            return f"Індексація не вдалась: {type(exc).__name__}: {exc}"
        return _clip(result if isinstance(result, str) else str(result))

    def _db(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.execute("CREATE TABLE IF NOT EXISTS fatti_permanenti (id INTEGER PRIMARY KEY AUTOINCREMENT, fatto TEXT, reparto TEXT DEFAULT 'GENERALE', data TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS agent_todos (id INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT, status TEXT, updated TEXT)")
        conn.execute("""CREATE TABLE IF NOT EXISTS code_symbols (
            path TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
            line INTEGER NOT NULL, signature TEXT, mtime REAL,
            PRIMARY KEY(path, name, line)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_symbols_name ON code_symbols(name)")
        conn.execute("""CREATE TABLE IF NOT EXISTS project_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            note TEXT NOT NULL, note_hash TEXT NOT NULL UNIQUE, updated TEXT
        )""")
        return conn

    def refresh_stored_facts(self) -> str:
        """Лишає найновіше з схожих правил і фактів. Викликається саме, без окремого інструмента."""
        removed = 0
        conn = self._db()
        try:
            rows = conn.execute("SELECT id, fatto FROM fatti_permanenti ORDER BY id DESC").fetchall()
            kept: list[str] = []
            drop: list[int] = []
            for row in rows:
                text = row[1] or ""
                if any(LocalRAG.same_fact(text, previous) for previous in kept):
                    drop.append(int(row[0]))
                else:
                    kept.append(text)
            for item_id in drop:
                conn.execute("DELETE FROM fatti_permanenti WHERE id=?", (item_id,))
            if drop:
                conn.commit()
            removed = len(drop)
        finally:
            conn.close()
        rag_note = ""
        if self.rag is not None and hasattr(self.rag, "refresh_memory"):
            rag_note = self.rag.refresh_memory(force=True)
        return f"Правила звірено. Прибрано застарілих: {removed}. {rag_note}".strip()

    def save_rule(self, rule: str) -> str:
        rule = (rule or "").strip()
        if not rule:
            return "Потрібен query з правилом."
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        conn = self._db()
        try:
            rows = conn.execute("SELECT id, fatto FROM fatti_permanenti").fetchall()
            matches = [
                (LocalRAG.fact_overlap(rule, row[1] or ""), int(row[0]))
                for row in rows
                if LocalRAG.same_fact(rule, row[1] or "")
            ]
            matches.sort(reverse=True)
            if matches:
                keep = matches[0][1]
                for _score, other in matches[1:]:
                    conn.execute("DELETE FROM fatti_permanenti WHERE id=?", (other,))
                conn.execute(
                    "UPDATE fatti_permanenti SET fatto=?, reparto=?, data=? WHERE id=?",
                    (rule, "AGENT", now, keep),
                )
                conn.commit()
                message = f"Оновив правило, id={keep}."
                if len(matches) > 1:
                    message += f" Прибрано старіших: {len(matches) - 1}."
            else:
                conn.execute(
                    "INSERT INTO fatti_permanenti (fatto, reparto, data) VALUES (?, ?, ?)",
                    (rule, "AGENT", now),
                )
                conn.commit()
                row = conn.execute("SELECT last_insert_rowid()").fetchone()
                message = f"Правило збережено, id={row[0]}"
        finally:
            conn.close()
        if self.rag is not None and hasattr(self.rag, "remember"):
            message += " " + self.rag.remember(rule, "rule")
        return message

    def list_rules(self) -> str:
        self.refresh_stored_facts()
        conn = self._db()
        try:
            rows = conn.execute("SELECT id, data, fatto FROM fatti_permanenti ORDER BY id DESC LIMIT 30").fetchall()
        finally:
            conn.close()
        if not rows:
            return "Збережених правил немає."
        return _clip("\n".join(f"[{row[0]}] {row[1]} {row[2]}" for row in rows))

    def night_shift(self, phrase: str) -> str:
        from night_shift import start_or_status

        return start_or_status(self.workspace, self.db_path, phrase or "")

    def todo_write(self, task: str, extra: str) -> str:
        status = extra.strip().lower() or "pending"
        conn = self._db()
        try:
            if task.strip().isdigit() and status in {"pending", "done", "cancelled"}:
                conn.execute(
                    "UPDATE agent_todos SET status=?, updated=? WHERE id=?",
                    (status, datetime.now().isoformat(timespec="seconds"), int(task.strip())),
                )
                conn.commit()
                return f"Задачу {task.strip()} позначено як {status}."
            if not task.strip():
                return "query = текст задачі, або id задачі якщо extra = pending|done|cancelled."
            conn.execute(
                "INSERT INTO agent_todos (task, status, updated) VALUES (?, ?, ?)",
                (task.strip(), "pending", datetime.now().isoformat(timespec="seconds")),
            )
            conn.commit()
            row = conn.execute("SELECT last_insert_rowid()").fetchone()
        finally:
            conn.close()
        return f"Задачу додано, id={row[0]}"

    def todo_list(self) -> str:
        conn = self._db()
        try:
            rows = conn.execute("SELECT id, status, task FROM agent_todos ORDER BY id").fetchall()
        finally:
            conn.close()
        if not rows:
            return "Список задач порожній."
        return "\n".join(f"[{row[0]}] {row[1]} {row[2]}" for row in rows)

    def clear_cache(self, query: str) -> str:
        removed = 0
        for current, dirnames, _files in os.walk(self.workspace):
            for name in list(dirnames):
                if name in {"__pycache__", ".pytest_cache", ".mypy_cache"}:
                    target = Path(current) / name
                    if ".venv" in target.parts or "site-packages" in target.parts:
                        continue
                    shutil.rmtree(target, ignore_errors=True)
                    removed += 1
                    dirnames.remove(name)
        note = f"Прибрано кеш-папок: {removed}."
        if query.strip() in {"rag", "all"} and self.rag is not None and hasattr(self.rag, "reset"):
            self.rag.reset()
            note += " RAG reset викликано."
        return note

    def undo_edit(self, raw: str) -> str:
        store = edits_store(self.db_path)
        rows = _load_edits(store)
        wanted = (raw or "").strip().replace("\\", "/")
        chosen = None
        if wanted:
            for item in reversed(rows):
                rel = str(item.get("path", "")).replace("\\", "/")
                if rel == wanted or rel.endswith("/" + wanted) or rel.endswith(wanted):
                    chosen = item
                    break
        elif rows:
            chosen = rows[-1]
        if chosen:
            path = self.safe_path(str(chosen.get("path") or "."), must_exist=False)
            if chosen.get("created") and not chosen.get("bak"):
                if path.is_file():
                    path.unlink()
                rows.remove(chosen)
                _save_edits(store, rows)
                return f"Відкотив створення: видалено {chosen.get('path')}."
            bak = Path(str(chosen.get("bak") or ""))
            if bak.is_file():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(bak.read_text(encoding="utf-8", errors="replace"), encoding="utf-8", newline="\n")
                rows.remove(chosen)
                _save_edits(store, rows)
                return f"Повернув {chosen.get('path')} з копії {bak.name}."
        if wanted:
            return _run(["git", "checkout", "--", wanted], self.workspace)
        return "Немає збереженої правки для відкату."

    def env_which(self, name: str) -> str:
        if not name.strip():
            return "Потрібен query з назвою команди."
        found = shutil.which(name.strip())
        return found or f"'{name.strip()}' немає в PATH."


def self_test(tools: AgentTools, router: Callable[..., str]) -> str:
    """Перевіряє, що intent потрапляє в потрібну функцію і змінює файли."""
    sandbox = tools.safe_path(".mcp_rag/_router_self_test", must_exist=False)
    if sandbox.exists():
        shutil.rmtree(sandbox)
    sandbox.mkdir(parents=True)
    sample = sandbox / "sample.py"
    sample.write_text("def alpha():\n    return 1\n", encoding="utf-8")
    rel = tools.relative(sample)
    checks: list[tuple[str, str, bool]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append((name, detail, ok))

    outline = router("project_outline", "", ".", "")
    check("project_outline", "Папки:" in outline, outline[:80])
    listing = router("list_dir", "", ".mcp_rag/_router_self_test", "")
    check("list_dir", "sample.py" in listing, listing[:80])
    globbed = router("glob_files", "sample.py", ".mcp_rag/_router_self_test", "")
    check("glob_files", rel.replace("\\", "/") in globbed.replace("\\", "/"), globbed[:80])
    found = router("grep", "def alpha", ".mcp_rag/_router_self_test", "*.py")
    check("grep", "def alpha" in found, found[:80])
    symbol = router("find_symbol", "alpha", ".mcp_rag/_router_self_test", "")
    check("find_symbol", "alpha" in symbol, symbol[:80])
    read = router("read_file", "", rel, "1:2")
    check("read_file", "1|def alpha" in read, read[:80])
    replaced = router("replace_in_file", "return 1", rel, "return 2")
    check("replace_in_file", "Замінено 1" in replaced and "копія:" in replaced, replaced[:160])
    body = sample.read_text(encoding="utf-8")
    check("replace_landed", "return 2" in body, body)
    undone = router("undo_edit", "", rel, "")
    check("undo_edit", "Повернув" in undone, undone[:80])
    check("undo_landed", "return 1" in sample.read_text(encoding="utf-8"), sample.read_text(encoding="utf-8"))
    diag = router("diagnostics", "", rel, "")
    check("diagnostics", "порядку" in diag, diag)
    info = router("system_info", "", "", "")
    check("system_info", "workspace" in info, info[:60])
    intents = router("list_intents", "", "", "")
    check("list_intents", "grep" in intents and "git_diff" in intents, "catalog")
    missing = router("read_file", "", ".mcp_rag/_router_self_test/nope.py", "")
    check("missing_file", missing.startswith("Помилка"), missing[:80])
    unknown = router("not_a_tool", "", "", "")
    check("unknown_intent", "Невідомий intent" in unknown, unknown[:80])
    shutil.rmtree(sandbox, ignore_errors=True)
    bad = [f"{name}: {detail}" for name, detail, ok in checks if not ok]
    if bad:
        return "ROUTER FAIL\n" + "\n".join(bad)
    return f"ROUTER OK {len(checks)} checks"
