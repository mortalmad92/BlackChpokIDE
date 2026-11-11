"""Лінійний пошук згадок файлів у тексті користувача.

Навіщо окремий модуль. Раніше і ``task_plan``, і ``tool_router`` шукали
шляхи регуляркою ``((?:[\\w.\\-]+[\\\\/])*[\\w.\\-]+\\.(?:py|js|…))``.
На короткій фразі це непомітно, але рушій regex пробує КОЖНУ стартову
позицію, і кожна невдала спроба сканує решту рядка. На вставленому тексті
без шляху це квадратичне зростання — заміряно:

| символів | час старої регулярки |
|---|---|
| 1 000 | 13 мс |
| 4 000 | 224 мс |
| 8 000 | 896 мс |
| 20 000 | 5 136 мс |
| 50 000 | 32 453 мс |

Інтерфейс на такому вводі просто зависав на десятки секунд.

Тут той самий пошук, але за один прохід: беремо фрагменти «словесних»
символів і перевіряємо, чи фрагмент закінчується відомим розширенням.
Слово з розширенням не може містити ані пробілу, ані дужки, тож межа
слова — це і є межа імені файлу. Час лінійний.

Публічний API:

* :func:`find_paths` — усі згадки (з підтеками, лапки й дужки обрізаються);
* :func:`first_path` — перша згадка або порожній рядок.
"""

from __future__ import annotations

import re

#: Розширення, які ми вважаємо «файлом проєкту».
EXTENSIONS: tuple[str, ...] = (
    "py", "pyi", "js", "ts", "tsx", "jsx", "json", "md", "txt", "html", "css",
    "yml", "yaml", "toml", "ini", "sql", "ps1", "bat", "cmd", "cfg", "cpp", "c",
    "h", "go", "rs", "java", "cs",
)

#: Один «шматок шляху»: літери (разом з кирилицею), цифри, ``_``, ``.``, ``-``.
#: Провідна крапка теж належить сегменту: без неї ``./main.py`` втрачало
#: крапку й перетворювалось на ``/main.py``.
_TOKEN_RE = re.compile(r"[.\w\-]+", re.UNICODE)

#: Той самий набір як множина — для ручного сканування назад.
_SEGMENT_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
    "абвгґдеєжзиіїйклмнопрстуфхцчшщьюяАБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯ"
    "øæåéèêëñçßäöüÄÖÜІіЇїЄєҐґ"
)

#: Суфікс, за яким визначаємо «це файл» (нижній регістр, з крапкою).
_SUFFIXES = frozenset("." + ext for ext in EXTENSIONS)

#: Файли проєкту БЕЗ розширення. Люди кажуть «додай у README розділ», і
#: без цього переліку шлях не знаходився зовсім — роутер не давав підказки,
#: і агент відповідав словами замість правки. Порівнюємо в нижньому регістрі.
_BARE_NAMES = frozenset({
    "readme", "license", "licence", "changelog", "makefile", "dockerfile",
    "procfile", "gemfile", "rakefile", "vagrantfile", "jenkinsfile",
    "requirements", "pipfile", "todo", "authors", "contributing", "notice",
    ".gitignore", ".gitattributes", ".dockerignore", ".editorconfig",
    ".env", ".flake8", ".pylintrc", ".npmrc", ".nvmrc", ".prettierrc",
})

#: Обгортки, які людина ставить навколо шляху в тексті.
_LEAD = " \t\n\r\"'«`([{<"
_TAIL = " \t\n\r\"'»`)]}>.,;:!?"


def _is_file_token(token: str) -> bool:
    """Чи це останній сегмент шляху з відомим розширенням."""
    if not token:
        return False
    # README, Makefile, Dockerfile — файли без розширення.
    if token.lower() in _BARE_NAMES:
        return True
    dot = token.rfind(".")
    if dot <= 0 or dot == len(token) - 1:
        return False
    stem = token[:dot]
    # У стовпці «calc.py додай» розширення немає — там пробіл усередині
    # токена неможливий, але перевіримо ще й на порожній корінь.
    return bool(stem) and token[dot:].lower() in _SUFFIXES


def _with_leading_segments(text: str, start: int, end: int) -> str:
    """Побудувати повний шлях: сегменти ``src/`` + сам токен.

    Йдемо назад від початку токена: якщо безпосередньо перед ним стоїть
    ``/`` або ``\\``, а перед ним — ще один сегмент, це частина шляху.
    Повторюємо, доки ланцюжок тримається. Усе інше (пробіл, кома, дужка,
    лапка) обриває шлях — саме тому «calc.py додай» дає ``calc.py``,
    а не «calc.py додай».

    Сегмент може бути й «порожнім» з погляду розширення — ``.`` або ``..``
    у ``./main.py`` та ``../lib/x.py``. Без цього провідна крапка зникала,
    і шлях ставав абсолютним (``/main.py``) замість відносного.

    ``end`` — кінець САМОГО токена, а не рядка: раніше функція повертала
    ``text[head:]`` і захоплювала весь текст після шляху.
    """
    head = start
    while head > 0 and text[head - 1] in "\\/":
        previous = head - 1
        # Сегмент — суцільний шматок «шляхових» символів, включно з «.» і «..».
        while previous > 0 and text[previous - 1] in _SEGMENT_CHARS:
            previous -= 1
        if previous == head - 1:
            break                               # роздільник без сегмента
        head = previous
    return text[head:end]


def find_paths(text: str) -> list[str]:
    """Усі згадані файли в порядку появи (шляхи з прямою скісною рискою)."""
    body = text or ""
    if not body:
        return []
    found: list[str] = []
    for match in _TOKEN_RE.finditer(body):
        token = match.group(0)
        if not token or not _is_file_token(token):
            continue
        clean = _with_leading_segments(body, match.start(), match.end())
        # Обгортки знімаємо ОКРЕМО з кожного боку. ``strip(_LEAD + _TAIL)``
        # з'їдав провідну крапку відносного шляху (``./main.py`` → ``/main.py``),
        # бо крапка є в ``_TAIL``: ``strip`` не знає, з якого боку вона стоїть.
        clean = clean.lstrip(_LEAD).rstrip(_TAIL)
        if not clean or not _is_file_token(clean.rstrip(_TAIL)):
            continue
        clean = clean.replace("\\", "/")
        if clean and clean not in found:
            found.append(clean)
    return found


def first_path(text: str) -> str:
    """Перший згаданий файл або порожній рядок."""
    paths = find_paths(text)
    return paths[0] if paths else ""


def find_path_matches(text: str) -> list[tuple[int, int, str]]:
    """Усі згадки як ``(початок, кінець, шлях)`` у координатах TEXT.

    Потрібно тим, хто ріже фразу на шматки за файлами
    (``task_plan._split_by_files``): їм важливі позиції, а не лише назви.
    """
    body = text or ""
    if not body:
        return []
    rows: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for match in _TOKEN_RE.finditer(body):
        token = match.group(0)
        if not token or not _is_file_token(token):
            continue
        raw = _with_leading_segments(body, match.start(), match.end())
        clean = raw.lstrip(_LEAD).rstrip(_TAIL)
        if not clean or not _is_file_token(clean.rstrip(_TAIL)):
            continue
        clean = clean.replace("\\", "/")
        if clean in seen:
            continue
        seen.add(clean)
        offset = body.find(raw, max(0, match.start() - len(raw)))
        start = offset if offset != -1 else match.start()
        rows.append((start, start + len(raw), clean))
    return rows


__all__ = ["EXTENSIONS", "find_paths", "find_path_matches", "first_path"]
