"""Статистика змін файлів для панелі «Зміни» BlackChpok IDE.

Модуль збирає перелік змінених файлів із кількістю доданих/видалених рядків —
так само, як це роблять сучасні агентні IDE. Джерела даних:

* ``git`` — ``git status --porcelain=v1 -z`` + ``git diff --numstat``;
* ``backup`` — резервні копії ``<файл>.bak``, які лишає ``workspace.write_text_file``
  (використовується, коли git недоступний або тека не є репозиторієм).

Тут немає tkinter і жодних мережевих викликів: модуль безпечно імпортувати
з будь-якого місця IDE, з тестів і з фонових потоків. Усі помилки git/файлової
системи ковтаються — панель «Зміни» ніколи не повинна валити застосунок.
"""

from __future__ import annotations

import difflib
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "FileChange",
    "ChangeSet",
    "count_line_diff",
    "read_text_safe",
    "diff_file_pair",
    "git_changes",
    "backup_changes",
    "detect_changes",
    "make_unified_diff",
    "preview_edit",
]

#: Скільки файлів найбільше показуємо в панелі (захист від величезних репозиторіїв).
MAX_FILES = 400

#: Поріг, після якого різницю рядків рахуємо лише за обмеженим вікном.
MAX_COUNT_LINES = 20_000

#: Розмір вікна порівняння для величезних файлів (6 000 рядків кожного боку).
_BOUND_WINDOW = 6_000

#: Суфікси, які ніколи не потрапляють у панель «Зміни».
SKIP_SUFFIXES = (".bak", ".pyc", ".pyo", ".pyc-check")

#: Теки, які не обходимо (збірка, кеші, віртуальні оточення, самий git).
SKIP_DIRS = frozenset(
    {".buildtmp", "__pycache__", ".venv", "node_modules", ".git", ".hg", ".svn"}
)

#: Українські підписи статусів для панелі.
STATUS_LABELS = {
    "added": "новий",
    "modified": "змінений",
    "deleted": "видалений",
    "renamed": "перейменований",
}


# --------------------------------------------------------------------------- #
# Модель даних
# --------------------------------------------------------------------------- #


@dataclass
class FileChange:
    """Один змінений файл у панелі «Зміни»."""

    path: str
    added: int = 0
    removed: int = 0
    status: str = "modified"
    is_binary: bool = False

    @property
    def total(self) -> int:
        """Скільки рядків зачеплено (додані + видалені)."""
        return self.added + self.removed

    @property
    def stat_text(self) -> str:
        """Текст статистики у стилі ``+13 -0`` (обидва числа показуємо завжди)."""
        return f"+{self.added} -{self.removed}"

    @property
    def status_label(self) -> str:
        """Український підпис статусу: «новий», «змінений», «видалений», «перейменований»."""
        return STATUS_LABELS.get(self.status, STATUS_LABELS["modified"])


@dataclass
class ChangeSet:
    """Набір змін робочої теки, готовий до показу в панелі."""

    files: list[FileChange] = field(default_factory=list)
    source: str = ""
    generated_at: float = field(default_factory=time.time)

    @property
    def added(self) -> int:
        """Сума доданих рядків по всіх файлах."""
        return sum(item.added for item in self.files)

    @property
    def removed(self) -> int:
        """Сума видалених рядків по всіх файлах."""
        return sum(item.removed for item in self.files)

    @property
    def summary_text(self) -> str:
        """Підсумок у стилі ``+2 655 -528`` (розряди розділені звичайним пробілом)."""
        return f"+{_fmt_count(self.added)} -{_fmt_count(self.removed)}"

    @property
    def is_empty(self) -> bool:
        """Чи немає жодної зміни."""
        return not self.files

    def top(self, n: int) -> list[FileChange]:
        """Найбільші зміни: список, відсортований за ``total`` спадаюче."""
        ordered = sorted(self.files, key=lambda item: item.total, reverse=True)
        if n <= 0:
            return []
        return ordered[:n]

    def by_status(self, status: str) -> list[FileChange]:
        """Усі файли з конкретним статусом (``added``/``modified``/...)."""
        return [item for item in self.files if item.status == status]


# --------------------------------------------------------------------------- #
# Допоміжні функції
# --------------------------------------------------------------------------- #


def _fmt_count(value: int) -> str:
    """Ціле з пробілом як розділювачем розрядів: ``2655`` -> ``2 655``."""
    return f"{value:,}".replace(",", " ")


def _split_lines(text: str) -> list[str]:
    """Розбити текст на рядки без збереження ``\\n``."""
    return text.splitlines()


def _is_skipped_name(name: str) -> bool:
    """Чи треба ігнорувати файл за його назвою (``.bak``, ``.pyc``, ``.pyc-check``)."""
    return name.lower().endswith(SKIP_SUFFIXES)


def _is_skipped_dir(name: str) -> bool:
    """Чи треба не заходити в теку (кеші, збірка, віртуальні оточення)."""
    return name.lower() in SKIP_DIRS


def _path_parts(path: str) -> list[str]:
    """Розбити шлях (POSIX або Windows) на частини."""
    return path.replace("\\", "/").split("/")


def _skip_path(path: str) -> bool:
    """Чи ігнорувати шлях із git: службові суфікси або заборонені теки."""
    parts = _path_parts(path)
    if any(_is_skipped_dir(part) for part in parts[:-1]):
        return True
    return _is_skipped_name(parts[-1])


def _relative_display(root: Path, path: Path) -> str:
    """Шлях відносно кореня у POSIX-вигляді; поза коренем — абсолютний."""
    try:
        return path.resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return path.as_posix()


# --------------------------------------------------------------------------- #
# Підрахунок рядків
# --------------------------------------------------------------------------- #


def _count_opcodes(old_lines: list[str], new_lines: list[str]) -> tuple[int, int]:
    """Порахувати додані/видалені рядки через ``SequenceMatcher``."""
    if old_lines == new_lines:
        return 0, 0
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    added = 0
    removed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        removed += i2 - i1
        added += j2 - j1
    return added, removed


def _tail_overlap(old_lines: list[str], new_lines: list[str]) -> int:
    """Скільки рядків спільного хвоста мають два тексти (для вирівнювання вікон)."""
    limit = min(len(old_lines), len(new_lines))
    count = 0
    while count < limit and old_lines[-1 - count] == new_lines[-1 - count]:
        count += 1
    return count


def _window(lines: list[str], offset: int) -> list[str]:
    """Вікно ``_BOUND_WINDOW`` рядків, починаючи з ``offset`` (з кінця — якщо не влазить)."""
    count = len(lines)
    if count <= _BOUND_WINDOW:
        return list(lines)
    start = min(max(0, offset), count - _BOUND_WINDOW)
    return list(lines[start : start + _BOUND_WINDOW])


def count_line_diff(old: str, new: str) -> tuple[int, int]:
    """Порахувати (додано, видалено) рядків між двома версіями тексту.

    Використовується ``difflib.SequenceMatcher`` над ``splitlines()``
    (без ``keepends``). Щоб панель «Зміни» не зависала на гігантських файлах
    (``SequenceMatcher`` квадратичний), працюємо дешево: якщо хоча б один бік
    довший за 20 000 рядків, порівнюємо лише обмежене вікно — до 6 000 рядків
    кожного боку. Зсув вікна компенсуємо спільним хвостом файлів, а різницю
    довжин, що лишилася поза вікном, додаємо як додані/видалені рядки.

    Наслідок компромісу: якщо в самій середині величезного файлу змінився
    рядок без зміни кількості рядків, така правка може лишитися непоміченою.
    Кількості ж (додано/видалено) лишаються коректними.
    """
    old_lines = _split_lines(old)
    new_lines = _split_lines(new)

    if len(old_lines) <= MAX_COUNT_LINES and len(new_lines) <= MAX_COUNT_LINES:
        return _count_opcodes(old_lines, new_lines)

    # Вирівнюємо вікна по спільному хвосту: якщо на початку файлу вставили
    # рядки, обидва вікна дивитимуться на той самий шматок тексту.
    shift = _tail_overlap(old_lines, new_lines)
    old_window = _window(old_lines, shift)
    new_window = _window(new_lines, shift)
    added, removed = _count_opcodes(old_window, new_window)

    old_hidden = max(0, len(old_lines) - len(old_window))
    new_hidden = max(0, len(new_lines) - len(new_window))
    if new_hidden > old_hidden:
        added += new_hidden - old_hidden
    elif old_hidden > new_hidden:
        removed += old_hidden - new_hidden
    return added, removed


# --------------------------------------------------------------------------- #
# Читання файлів
# --------------------------------------------------------------------------- #


def read_text_safe(path: Path, limit_bytes: int = 2_000_000) -> str | None:
    """Прочитати текстовий файл, не падаючи на смітті.

    Повертає ``None``, якщо файл бінарний (є NUL у перших 4096 байтах),
    недоступний для читання, не існує або більший за ``limit_bytes``.
    Кодування: спершу UTF-8, потім CP1251 (типові українські файли з Windows).
    """
    try:
        path = Path(path)
        if not path.is_file():
            return None
        if path.stat().st_size > limit_bytes:
            return None
        data = path.read_bytes()
    except (OSError, ValueError):
        return None

    if not data:
        return ""
    if b"\x00" in data[:4096]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("cp1251")
        except UnicodeDecodeError:
            return None


def _lines_of_file(path: Path) -> tuple[int, bool]:
    """Порахувати рядки файлу: (кількість, чи бінарний)."""
    text = read_text_safe(path)
    if text is None:
        return 0, True
    return len(_split_lines(text)), False


def _looks_binary(path: Path | None) -> bool:
    """Перевірити саме на бінарність (NUL у перших 4096 байтах), не на розмір."""
    if path is None:
        return True
    try:
        with open(path, "rb") as handle:
            return b"\x00" in handle.read(4096)
    except (OSError, ValueError):
        return True


def diff_file_pair(
    old_path: Path | None,
    new_path: Path | None,
    *,
    display: str = "",
) -> FileChange:
    """Порівняти дві версії файлу й повернути ``FileChange``.

    Будь-яка зі сторін може бути ``None`` або не існувати: тоді весь файл
    вважається доданим (є лише нова версія) або видаленим (лише стара).
    Старий бік — це зазвичай ``<файл>.bak``, новий — поточний файл.
    """
    old_exists = old_path is not None and _exists_file(old_path)
    new_exists = new_path is not None and _exists_file(new_path)
    reference = new_path or old_path
    if display:
        label = display
    elif reference is not None:
        label = _relative_display(Path.cwd(), Path(reference))
    else:
        label = ""

    old_text = read_text_safe(old_path) if old_exists and old_path is not None else None
    new_text = read_text_safe(new_path) if new_exists and new_path is not None else None

    if old_exists and not new_exists:
        if old_text is None:
            return FileChange(label, 0, 0, "deleted", is_binary=True)
        return FileChange(label, 0, len(_split_lines(old_text)), "deleted")

    if new_exists and not old_exists:
        if new_text is None:
            return FileChange(label, 0, 0, "added", is_binary=True)
        return FileChange(label, len(_split_lines(new_text)), 0, "added")

    if not old_exists and not new_exists:
        return FileChange(label, 0, 0, "deleted")

    if old_text is None or new_text is None:
        # Файл є, але його не прочитати: або бінарний (NUL-байти), або завеликий
        # понад ліміт. У першому випадку чесно позначаємо is_binary.
        return FileChange(
            label,
            0,
            0,
            "modified",
            is_binary=_looks_binary(old_path if old_text is None else new_path),
        )

    added, removed = count_line_diff(old_text, new_text)
    return FileChange(label, added, removed, "modified")


def _exists_file(path: Path) -> bool:
    """Чи існує саме файл (тека не вважається зміненим файлом)."""
    try:
        return Path(path).is_file()
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# Git
# --------------------------------------------------------------------------- #


def _run_git(root: Path, args: list[str], timeout: float) -> str | None:
    """Запустити ``git -C <root> <args>`` і повернути stdout або ``None``."""
    try:
        completed = subprocess.run(
            ["git", "-C", os.fspath(root), *args],
            capture_output=True,
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.decode("utf-8", errors="replace")


def _repo_root(root: Path) -> Optional[Path]:
    """Корінь репозиторію для ``root`` (підійманням угору) або ``None``."""
    try:
        current = Path(root).resolve()
    except OSError:
        return None
    for folder in (current, *current.parents):
        try:
            if (folder / ".git").exists():
                return folder
        except OSError:
            return None
    return None


def _repo_prefix(root: Path) -> str:
    """Префікс ``root`` відносно кореня репозиторію (``""``, якщо це корінь).

    Приклад: корінь ``C:/AI/proj``, тека ``C:/AI/proj/sub`` → ``"sub/"``.
    """
    top = _repo_root(root)
    if top is None:
        return ""
    try:
        inner = Path(root).resolve().relative_to(top)
    except (OSError, ValueError):
        return ""
    parts = [p for p in inner.parts if p not in ("", ".")]
    return ("/".join(parts) + "/") if parts else ""


def _parse_porcelain_z(raw: str) -> list[tuple[str, str, str]]:
    """Розібрати ``git status --porcelain=v1 -z`` у список (код, шлях, старий шлях).

    Формат ``-z``: ``XY<space>PATH\\0``, а для перейменувань/копій після цільового
    шляху йде ще одне поле — початковий шлях (``XY TO\\0FROM\\0``).
    """
    tokens = raw.split("\0")
    entries: list[tuple[str, str, str]] = []
    index = 0
    while index < len(tokens):
        entry = tokens[index]
        index += 1
        if len(entry) < 4:
            continue
        code = entry[:2]
        path = entry[3:]
        old_path = ""
        if "R" in code or "C" in code:
            if index < len(tokens):
                old_path = tokens[index]
                index += 1
        entries.append((code, path, old_path))
    return entries


def _expand_rename_path(name: str) -> tuple[str, str]:
    """Розгорнути стислий шлях перейменування з numstat.

    git пише ``docs/{old.md => new.md}`` або ``{old => new}/file.py``.
    Повертає пару (старий шлях, новий шлях); для звичайного шляху обидва рівні.
    """
    if "=>" not in name:
        return name, name
    if "{" not in name or "}" not in name:
        old_part, _, new_part = name.partition("=>")
        return old_part.strip(), new_part.strip()
    head, _, rest = name.partition("{")
    middle, _, tail = rest.partition("}")
    old_inner, _, new_inner = middle.partition("=>")
    old_name = f"{head}{old_inner.strip()}{tail}".replace("//", "/").strip()
    new_name = f"{head}{new_inner.strip()}{tail}".replace("//", "/").strip()
    return old_name, new_name


def _numstat_map(
    root: Path, args: list[str], timeout: float
) -> dict[str, tuple[int, int, bool]] | None:
    """Один виклик ``git diff --numstat`` зі зведенням у словник ``path -> (+, -, бінарний)``.

    Словник ключується і новим, і старим шляхом, щоб ``git status`` міг знайти
    статистику для перейменованих файлів.
    """
    raw = _run_git(root, args, timeout)
    if raw is None:
        return None
    result: dict[str, tuple[int, int, bool]] = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added_text, removed_text = parts[0], parts[1]
        binary = added_text.strip() == "-" or removed_text.strip() == "-"
        try:
            added = 0 if binary else int(added_text)
            removed = 0 if binary else int(removed_text)
        except ValueError:
            added, removed = 0, 0
        value = (added, removed, binary)
        name = parts[2]
        if len(parts) >= 4:
            # перейменування: стара й нова назви окремими полями
            result[name] = value
            result[parts[3]] = value
            continue
        old_name, new_name = _expand_rename_path(name)
        result[old_name] = value
        result[new_name] = value
    return result


def _numstat_single(
    root: Path, args: list[str], timeout: float, path: str = ""
) -> tuple[int, int, bool] | None:
    """Точковий ``git diff --numstat ... -- <path>`` для одного файлу.

    Спершу пробуємо взяти рядок саме для ``path`` (щоб не приписати чужий
    перейменований запис), і лише якщо такого немає — беремо єдиний рядок.
    """
    mapping = _numstat_map(root, args, timeout)
    if not mapping:
        return None
    if path and path in mapping:
        return mapping[path]
    if len(mapping) == 1:
        return next(iter(mapping.values()))
    return None


def _status_from_code(code: str) -> str:
    """Перетворити ``XY`` з porcelain у статус панелі «Зміни»."""
    xy = code[:2]
    if xy == "??":
        return "added"
    if "R" in xy:
        return "renamed"
    if "C" in xy:
        return "added"
    if "D" in xy:
        return "deleted"
    if "A" in xy:
        return "added"
    return "modified"


def _git_entry_change(
    root: Path,
    path: str,
    old_path: str,
    code: str,
    batch: dict[str, tuple[int, int, bool]],
    timeout: float,
) -> FileChange:
    """Побудувати ``FileChange`` для одного запису ``git status``."""
    status = _status_from_code(code)

    if code == "??":
        # Новий, ще не доданий у git файл — усі рядки вважаємо доданими.
        count, binary = _lines_of_file(root / path)
        return FileChange(path, count, 0, "added", is_binary=binary)

    stat = batch.get(path) or (batch.get(old_path) if old_path else None)
    if stat is None:
        # Зведеної статистики не було (напр. репозиторій без жодного коміту).
        stat = _numstat_single(root, ["diff", "--numstat", "HEAD", "--", path], timeout, path)
        if stat is None:
            stat = _numstat_single(root, ["diff", "--numstat", "--", path], timeout, path)

    if stat is None:
        # git не дав цифр — для наявного нового файлу рахуємо всі рядки доданими.
        if status in {"added", "modified"}:
            count, binary = _lines_of_file(root / path)
            if binary:
                return FileChange(path, 0, 0, status, is_binary=True)
            if status == "added":
                return FileChange(path, count, 0, status)
        return FileChange(path, 0, 0, status)

    added, removed, binary = stat
    if binary:
        return FileChange(path, 0, 0, status, is_binary=True)
    return FileChange(path, added, removed, status)


def git_changes(root: Path, *, timeout: float = 20.0) -> ChangeSet | None:
    """Зібрати зміни з git; ``None`` — якщо git недоступний або це не репозиторій.

    Кроки: ``git status --porcelain=v1 -z`` (розбір через NUL, перейменування
    дають додаткове поле старого шляху), далі зведений ``git diff --numstat HEAD``
    за один виклик (швидко навіть для сотень файлів), а для шляхів, яких у
    зведенні немає, — точковий ``git diff --numstat HEAD -- <path>`` і, якщо
    комітів ще немає, ``git diff --numstat -- <path>``. Невідстежені файли
    рахуються як повністю додані. Бінарні файли не читаємо (``is_binary=True``).
    Помилки не викидаються — назовні йде ``None``.
    """
    try:
        root = Path(root)
        # Дешева перевірка до запуску процесу: якщо ознак репозиторію немає
        # ні в теці, ні вище, ``git status`` лише згає час і поверне помилку.
        if not _looks_like_repo(root):
            return None
        # ``-- .`` обмежує вивід самою текою: без нього ``git -C <вкладена>``
        # показує зміни ВСЬОГО репозиторію, і панель «Зміни» для підтеки
        # виводила б чужі файли з кореня.
        raw = _run_git(root, ["status", "--porcelain=v1", "-z", "--", "."], timeout)
        if raw is None:
            return None
        entries = _parse_porcelain_z(raw)
        # Шляхи git віддає відносно КОРЕНЯ репозиторію. Для вкладеної теки
        # робимо їх відносними до неї — інакше назви в панелі не збігаються
        # з тим, що бачить користувач.
        prefix = _repo_prefix(root)
        if prefix:
            entries = [(_c, _p[len(prefix):] if _p.startswith(prefix) else _p, _o)
                       for _c, _p, _o in entries
                       if _p.startswith(prefix)]
        entries = _parse_porcelain_z(raw)

        batch = _numstat_map(root, ["diff", "--numstat", "HEAD"], timeout)
        if batch is None:
            batch = _numstat_map(root, ["diff", "--numstat"], timeout) or {}

        files: list[FileChange] = []
        for code, path, old_path in entries:
            if len(files) >= MAX_FILES:
                break
            if _skip_path(path):
                continue
            files.append(_git_entry_change(root, path, old_path, code, batch, timeout))
        return ChangeSet(files=files, source="git", generated_at=time.time())
    except Exception:  # noqa: BLE001 — панель не має падати через git
        return None


# --------------------------------------------------------------------------- #
# Резервні копії (без git)
# --------------------------------------------------------------------------- #


def backup_changes(root: Path, *, limit: int = 400) -> ChangeSet:
    """Зміни за резервними копіями ``*.bak`` — запасне джерело без git.

    ``workspace.write_text_file`` перед перезаписом кладе поруч ``<файл>.bak``.
    Для кожної такої копії порівнюємо ``<файл>.bak`` із поточним ``<файл>``;
    якщо поточного немає — статус «видалений». Шлях у панелі — відносний до
    ``root`` і без суфікса ``.bak``. Файли без реальної різниці відкидаємо,
    щоб панель не забивалася старими копіями. ``.bak`` у службових теках
    (``.buildtmp``, ``__pycache__``, ``.venv``, ``node_modules``, ``.git``)
    ігноруються. Результат відсортований за ``total`` спадаюче.

    **Кеш за ``mtime``.** Обхід теки й порядковий diff — найдорожча
    операція в застосунку: на цьому проєкті вона коштувала 4.8 с і
    виконувалась у конструкторі панелі, тобто до появи вікна. Тепер
    результат пари (``.bak``, файл) перевикористовується, поки не змінився
    жоден із них: `(mtime, size)` обох файлів — ключ кешу.
    """
    root = Path(root)
    found: list[FileChange] = []
    cap = max(0, limit)
    if cap == 0:
        return ChangeSet(files=[], source="backup", generated_at=time.time())
    try:
        for current, dirs, names in os.walk(root):
            dirs[:] = sorted(d for d in dirs if not _is_skipped_dir(d))
            for name in sorted(names):
                if not name.endswith(".bak") or len(name) <= 4:
                    continue
                backup = Path(current) / name
                target = backup.with_name(name[:-4])
                if _is_skipped_name(target.name):
                    continue
                if len(found) >= cap:
                    break
                display = _relative_display(root, target)
                key = _pair_key(backup, target)
                change = _CACHE.get(key) if key is not None else None
                if change is None:
                    try:
                        change = diff_file_pair(backup, target, display=display)
                    except OSError:
                        continue
                    if key is not None:
                        if len(_CACHE) >= _CACHE_LIMIT:
                            # Просте витіснення: кеш не має рости безмежно
                            # на проєктах із тисячами .bak-файлів.
                            _CACHE.clear()
                        _CACHE[key] = change
                elif change.path != display:
                    # Той самий файл, але шлях показу відрізняється
                    # (перейменування теки) — перерахуємо, щоб підпис був вірний.
                    change = diff_file_pair(backup, target, display=display)
                if change.total > 0 or change.is_binary:
                    found.append(change)
            if len(found) >= cap:
                break
    except OSError:
        pass

    found.sort(key=lambda item: item.total, reverse=True)
    return ChangeSet(files=found[:cap], source="backup", generated_at=time.time())


#: Кеш результатів diff між ``.bak`` і файлом: ключ → :class:`FileChange`.
#: Ключ включає ``(mtime, size)`` обох файлів, тому застарілі записи просто
#: ніколи не знаходяться — окремого прибирання не потрібне.
_CACHE: dict[tuple, FileChange] = {}
#: Стеля кешу: захист від нескінченного зростання на великих проєктах.
_CACHE_LIMIT = 4000


def _pair_key(backup: Path, target: Path) -> Optional[tuple]:
    """Ключ кешу для пари (.bak, файл) або ``None``, якщо стан не читається."""
    try:
        b = backup.stat()
    except OSError:
        return None
    try:
        t = target.stat()
        t_sig = (t.st_mtime_ns, t.st_size)
    except OSError:
        # Файл видалено — це теж стан, який треба закешувати.
        t_sig = None
    return (str(backup), b.st_mtime_ns, b.st_size, t_sig)


def clear_cache() -> None:
    """Скинути кеш diff (використовується тестами й кнопкою «Оновити»)."""
    _CACHE.clear()
    _NOT_A_REPO.clear()


#: Теки, для яких уже доведено, що git-репозиторію немає ні тут, ні вище.
#: Навіщо: ``git status`` — це запуск окремого процесу (~60 мс на Windows).
#: Коли git встановлено, але тека не є репозиторієм (звичайна тека проєкту,
#: тимчасова тека тесту), ціна платилась на КОЖЕН виклик ``detect_changes``,
#: і кеш резервних копій не давав жодного виграшу: 108 мс → 78 мс замість
#: 46 мс → 24 мс. Тепер негативний результат кешується, а сама перевірка —
#: це кілька ``stat`` замість породження процесу.
_NOT_A_REPO: set[str] = set()


def _looks_like_repo(root: Path) -> bool:
    """Чи є ознака репозиторію (тека або файл ``.git``) у теці або вище.

    Запуск git не потрібен: ``.git`` є в корені будь-якого робочого дерева,
    а вкладена тека репозиторію знаходиться підійманням угору. Якщо ознаки
    немає ніде — ``git -C`` гарантовано відповість «not a git repository»,
    тож процес можна не запускати взагалі.
    """
    key = os.fspath(root)
    if key in _NOT_A_REPO:
        return False
    try:
        current = Path(root).resolve()
    except OSError:
        return True          # не змогли перевірити — хай вирішує git
    for folder in (current, *current.parents):
        try:
            if (folder / ".git").exists():
                return True
        except OSError:
            return True      # недоступна тека — не робимо висновків
    _NOT_A_REPO.add(key)
    return False


def git_available() -> bool:
    """Чи є програма ``git`` у системі.

    Потрібно панелі «Зміни»: без git вона працює на резервних копіях, і
    користувач має бачити, чому історії комітів немає.
    """
    import shutil

    return shutil.which("git") is not None


def git_branch(root: Path, *, timeout: float = 5.0) -> str:
    """Назва поточної гілки (``""`` — не репозиторій або git відсутній).

    Навіщо окрема функція. Шапка вікна показує гілку й кількість змін
    (``header_bar.set_git``), але ``main_window`` читав
    ``getattr(self, "_git_branch", "")`` — атрибут, який **ніколи не
    присвоювався**. Через це git-чип завжди був порожнім («⑂ —»), хоч
    дані є. Тепер їх беруть звідси.
    """
    raw = _run_git(root, ["rev-parse", "--abbrev-ref", "HEAD"], timeout)
    if raw is None:
        return ""
    name = raw.strip().splitlines()[0].strip() if raw.strip() else ""
    # ``HEAD`` у відокремленому стані — це не гілка; показуємо короткий хеш.
    if name == "HEAD":
        sha = _run_git(root, ["rev-parse", "--short", "HEAD"], timeout)
        return (sha or "").strip()
    return name


def detect_changes(root: Path, *, prefer_git: bool = True) -> ChangeSet:
    """Визначити зміни робочої теки, завжди повертаючи ``ChangeSet``.

    Спершу пробуємо git (``source == "git"``); якщо git немає або це не
    репозиторій — переходимо на резервні копії ``*.bak`` (``source == "backup"``).
    """
    root = Path(root)
    if prefer_git:
        result = git_changes(root)
        if result is not None:
            return result
    return backup_changes(root)


# --------------------------------------------------------------------------- #
# Попередній перегляд змін
# --------------------------------------------------------------------------- #


def make_unified_diff(
    old: str,
    new: str,
    path: str = "",
    context: int = 3,
    max_lines: int = 400,
) -> str:
    """Побудувати читабельний unified diff для попереднього перегляду.

    Заголовки ``--- a/<path>`` / ``+++ b/<path>``, далі звичайні хунки
    (``difflib.unified_diff``). Якщо результат довший за ``max_lines``,
    обрізаємо його й додаємо український маркер
    ``… (показано перші N рядків)``. Порожній рядок — змін немає.
    """
    old_lines = _split_lines(old)
    new_lines = _split_lines(new)
    label = path or "-"
    raw = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{label}",
            tofile=f"b/{label}",
            n=max(0, context),
            lineterm="",
        )
    )
    if not raw:
        return ""
    if max_lines > 0 and len(raw) > max_lines:
        head = raw[:max_lines]
        head.append(f"… (показано перші {max_lines} рядків)")
        return "\n".join(head)
    return "\n".join(raw)


def preview_edit(
    old_text: str,
    old_string: str,
    new_string: str,
    *,
    path: str = "",
    context: int = 3,
) -> tuple[bool, str, tuple[int, int]]:
    """Попередній перегляд inline-правки для редактора.

    Повторює семантику агентського ``edit_file``: ``old_string`` мусить
    зустрічатися у тексті рівно один раз. Повертає
    ``(ok, текст, (додано, видалено))``; коли збіг не знайдено або він
    неоднозначний — ``ok=False`` і українське пояснення замість diff.
    """
    if old_string == "":
        return False, "Порожній рядок для заміни — потрібен непорожній унікальний фрагмент.", (0, 0)

    occurrences = old_text.count(old_string)
    if occurrences == 0:
        where = f" у файлі «{path}»" if path else ""
        return False, f"Рядок для заміни не знайдено{where}.", (0, 0)
    if occurrences > 1:
        where = f" у файлі «{path}»" if path else ""
        return (
            False,
            f"Рядок для заміни зустрічається {occurrences} разів{where} — "
            "потрібен унікальний збіг, додайте більше контексту.",
            (0, 0),
        )

    updated = old_text.replace(old_string, new_string, 1)
    if updated == old_text:
        return True, "", (0, 0)
    added, removed = count_line_diff(old_text, updated)
    return True, make_unified_diff(old_text, updated, path=path, context=context), (added, removed)
