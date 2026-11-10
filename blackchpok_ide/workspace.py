"""Робота з файлами робочої теки: безпечні шляхи, читання, запис, пошук."""

from __future__ import annotations

import fnmatch
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

LOG = logging.getLogger("blackchpok.workspace")

MAX_READ_BYTES = 8 * 1024 * 1024
MAX_SEARCH_RESULTS = 400
SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build", "target",
    ".idea", ".vscode", ".mcp_rag", ".buildtmp", ".next", ".cache",
}
TEXT_EXT = {
    ".py", ".pyi", ".pyw", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".json", ".jsonc",
    ".md", ".mdx", ".txt", ".rst", ".html", ".htm", ".css", ".scss", ".less", ".xml", ".svg",
    ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".env", ".sql", ".sh", ".bash",
    ".ps1", ".bat", ".cmd", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".java", ".kt",
    ".go", ".rs", ".rb", ".php", ".lua", ".swift", ".dart", ".dockerfile", ".gitignore",
    ".editorconfig", ".vue", ".svelte", ".graphql", ".proto",
}

ENCODINGS = ("utf-8", "utf-8-sig", "cp1251", "latin-1")

# BOM → кодування. Перевіряємо ДО вгадування, бо cp1251 «успішно» декодує
# будь-які байти і без цього utf-16 читався б як сміття.
# ``utf-16`` / ``utf-32`` (без -le/-be) самі визначають порядок байтів за BOM
# і прибирають його з результату.
_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xfe\x00\x00", "utf-32"),
    (b"\x00\x00\xfe\xff", "utf-32"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
)


class WorkspaceError(RuntimeError):
    """Помилка роботи з файлами, яку можна показати користувачу."""


@dataclass(frozen=True)
class FileHit:
    path: Path
    line: int
    text: str


def is_text_file(path: Path) -> bool:
    if path.suffix.lower() in TEXT_EXT:
        return True
    if not path.suffix:
        try:
            chunk = path.read_bytes()[:2048]
        except OSError:
            return False
        return b"\x00" not in chunk
    return False


def decode_bytes(raw: bytes) -> tuple[str, str]:
    """Розпізнати кодування: спершу BOM, потім utf-8, потім cp1251."""
    for bom, encoding in _BOMS:
        if raw.startswith(bom):
            try:
                return raw.decode(encoding), encoding
            except UnicodeDecodeError:
                break
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8/replace"


def read_text_file(path: Path) -> tuple[str, str]:
    if not path.exists():
        raise WorkspaceError(f"Файл не знайдено: {path}")
    if not path.is_file():
        raise WorkspaceError(f"Це не файл: {path}")
    size = path.stat().st_size
    if size > MAX_READ_BYTES:
        raise WorkspaceError(f"Файл завеликий ({size / 1024 / 1024:.1f} МБ), редактор його не відкриє.")
    raw = path.read_bytes()
    if b"\x00" in raw[:4096]:
        raise WorkspaceError("Це бінарний файл — редактор показує лише текст.")
    content, encoding = decode_bytes(raw)
    return content.replace("\r\n", "\n").replace("\r", "\n"), encoding


def safe_join(root: Path, relative: str) -> Path:
    """Приєднати відносний шлях до кореня, не виходячи за його межі."""
    root = root.resolve()
    candidate = Path(relative)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if resolved != root:
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise WorkspaceError(f"Шлях «{relative}» поза робочою текою.") from exc
    return resolved


def relative_to_root(root: Path, path: Path) -> str:
    """Показати шлях відносно кореня; якщо він зовні — абсолютний."""
    try:
        return path.resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return str(path)


def write_text_file(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            backup = path.with_suffix(path.suffix + ".bak")
            try:
                backup.write_bytes(path.read_bytes())
            except OSError as exc:
                # Бекап не вдався — запис усе одно робимо (краще новий вміст,
                # ніж нічого), але користувач має знати, що відкотити зміну
                # не вийде. Раніше тут стояло `pass`: панель «Зміни»
                # показувала різницю зі старою копією, якої насправді немає.
                LOG.warning("Резервну копію %s не створено: %s",
                            backup.name, exc)
        path.write_text(content, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise WorkspaceError(f"Не вдалось записати {path.name}: {exc}") from exc


def walk_text_files(root: Path, *, limit: int = 20_000) -> Iterable[Path]:
    count = 0
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        base = Path(current)
        for name in files:
            path = base / name
            if path.suffix.lower() in {".pyc", ".pyo"} or name.endswith(".bak"):
                continue
            yield path
            count += 1
            if count >= limit:
                return


def search_text(
    root: Path,
    needle: str,
    *,
    glob: str = "",
    regex: bool = False,
    case: bool = False,
    limit: int = MAX_SEARCH_RESULTS,
) -> list[FileHit]:
    """Пошук рядків у текстових файлах робочої теки."""
    if not needle:
        return []
    pattern: re.Pattern[str] | None = None
    if regex:
        try:
            pattern = re.compile(needle, 0 if case else re.IGNORECASE)
        except re.error as exc:
            raise WorkspaceError(f"Помилка в регулярному виразі: {exc}") from exc
    lowered = needle if case else needle.lower()
    hits: list[FileHit] = []
    for path in walk_text_files(root):
        if glob and not fnmatch.fnmatch(path.name, glob) and not fnmatch.fnmatch(str(path), glob):
            continue
        if not is_text_file(path):
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:2048]:
            continue
        content, _encoding = decode_bytes(raw)
        for number, line in enumerate(content.splitlines(), start=1):
            matched = bool(pattern.search(line)) if pattern else (lowered in (line if case else line.lower()))
            if matched:
                hits.append(FileHit(path=path, line=number, text=line.strip()[:400]))
                if len(hits) >= limit:
                    return hits
    return hits


def quick_open_index(root: Path) -> list[Path]:
    files = []
    for path in walk_text_files(root):
        files.append(path)
        if len(files) >= 5000:
            break
    return files


def language_label(path: Path) -> str:
    from .syntax import language_for

    lang = language_for(path.name)
    return {
        "python": "Python", "javascript": "JavaScript", "typescript": "TypeScript",
        "clike": "C/C++/Java", "sql": "SQL", "shell": "Shell", "markdown": "Markdown",
        "json": "JSON", "html": "HTML", "css": "CSS", "yaml": "YAML", "plain": "Текст",
    }.get(lang.name, lang.name)
