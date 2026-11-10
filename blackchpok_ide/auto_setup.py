"""Автоматичне створення скілів для агента без участі користувача.

Ідея: IDE сама дивиться на робочу теку (мова, тести, точки входу, збірка,
git), формує короткі правила саме для цього проєкту і кладе їх у
``.agents/skills/<назва>/SKILL.md``. Користувач нічого не налаштовує —
скіли просто з'являються й одразу працюють, бо їх читає ``skills.py``.

Модуль працює у три кроки:

1. :func:`profile_project` — швидкий знімок проєкту (без залежностей і
   без мережі).
2. :func:`propose_skills` — детермінований набір скілів за правилами
   (жодного LLM: однаковий проєкт дає однакові пропозиції).
3. :func:`install_proposals` — запис ``SKILL.md`` через ``skills.create_skill``.

Модуль не залежить від tkinter і не робить жодного мережевого виклику:
вибір моделі (:func:`describe_model_setup`) — чиста функція, а завантаження
моделі лишається за викликачем, який передає власний callable.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .skills import (
    SEARCH_DIRS,
    SKILL_FILE,
    create_skill,
    discover_skills,
    make_skill_text,
)
from .workspace import SKIP_DIRS, WorkspaceError, read_text_file

LOG = logging.getLogger("blackchpok.autosetup")

# ─────────────────────────────────────────────────────────────────────────────
# Константи сканування
# ─────────────────────────────────────────────────────────────────────────────

#: Теки, які не дають користі для профілю (метадані, збірки, дані користувача).
EXTRA_SKIP_DIRS = frozenset({"userdata", ".agents", ".buildtmp", "dist", "build"})
#: Повний перелік тек, у які сканер не заходить.
SKIP_DIR_NAMES = frozenset(SKIP_DIRS) | EXTRA_SKIP_DIRS

DEFAULT_MAX_FILES = 4000
#: Скільки файлів щонайбільше читаємо заради визначення фреймворків.
MAX_SCAN_FILES = 400
#: Скільки байтів читаємо з одного файлу під час пошуку фреймворків.
MAX_SCAN_BYTES = 64 * 1024
#: Скільки символів README зберігаємо в профілі.
README_LIMIT = 2000
#: Скільки пропозицій максимум віддаємо назовні.
MAX_PROPOSALS = 8

#: Розширення, які вважаємо кодом (для підрахунку мов).
LANGUAGE_EXTENSIONS = frozenset({
    ".py", ".pyw", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".rs", ".go", ".java", ".kt", ".kts", ".c", ".h", ".cc", ".cpp", ".hpp",
    ".cs", ".rb", ".php", ".lua", ".swift", ".dart", ".sql", ".sh", ".ps1",
    ".bat", ".cmd", ".vue", ".svelte", ".html", ".css", ".scss",
})

#: Розширення -> людська назва мови (українською).
LANGUAGE_NAMES: dict[str, str] = {
    ".py": "Python", ".pyw": "Python", ".pyi": "Python",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".rs": "Rust", ".go": "Go", ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin",
    ".c": "C", ".h": "C/C++", ".cc": "C++", ".cpp": "C++", ".hpp": "C++",
    ".cs": "C#", ".rb": "Ruby", ".php": "PHP", ".lua": "Lua", ".swift": "Swift",
    ".dart": "Dart", ".sql": "SQL", ".sh": "Shell", ".ps1": "PowerShell",
    ".bat": "Batch", ".cmd": "Batch", ".vue": "Vue", ".svelte": "Svelte",
    ".html": "HTML", ".css": "CSS", ".scss": "SCSS",
}

#: Файли-ознаки пакетного менеджера: (ім'я файлу, менеджер, порядок перевірки).
PACKAGE_MANAGERS: tuple[tuple[str, str], ...] = (
    ("cargo.toml", "cargo"),
    ("package.json", "npm"),
    ("pyproject.toml", "poetry"),
    ("requirements.txt", "pip"),
)

#: Типові точки входу проєкту.
ENTRY_POINT_NAMES: tuple[str, ...] = (
    "main.py", "app.py", "manage.py", "server.py", "index.js", "main.rs",
)

#: Файли налаштувань, які варто знати проєкту.
CONFIG_CANDIDATES: tuple[str, ...] = (
    ".flake8", "ruff.toml", ".ruff.toml", "setup.cfg", ".editorconfig",
    "pyproject.toml", "pytest.ini", "tox.ini", "mypy.ini", ".pylintrc",
    "requirements.txt", "package.json", "Cargo.toml", "tsconfig.json",
    "Makefile", ".pre-commit-config.yaml", "setup.py", "poetry.lock",
    ".gitignore",
)

#: Файли-ознаки збірки релізу.
BUILD_CANDIDATES: tuple[str, ...] = (
    "BlackChpokIDE.spec", "build_exe.bat", "build.bat", "package.json",
    "Cargo.toml", "Makefile", "pyproject.toml",
)

#: Ознаки технологій у тексті файлів: лише справжні рядки import/require,
#: щоб згадка «flask» у документації не робила проєкт flask-проєктом.
FRAMEWORK_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("tkinter", (r"^\s*(?:import|from)\s+tkinter\b",)),
    ("flask", (r"^\s*(?:import|from)\s+flask\b",)),
    ("django", (r"^\s*(?:import|from)\s+django\b",)),
    ("fastapi", (r"^\s*(?:import|from)\s+fastapi\b",)),
    ("pytest", (r"^\s*(?:import|from)\s+pytest\b",)),
    ("unittest", (r"^\s*(?:import|from)\s+unittest\b",)),
    ("react", (r"from\s+['\"]react['\"]", r"require\(\s*['\"]react['\"]")),
)

_FRAMEWORK_REGEXES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile("|".join(markers), re.MULTILINE))
    for name, markers in FRAMEWORK_MARKERS
)

#: Адреса локального сервера, який піднімає сама IDE.
LOCAL_SERVER_URL = "http://127.0.0.1:8080/v1"

#: Хости, які вважаємо локальними.
LOCAL_HOSTS = ("127.0.0.1", "localhost", "0.0.0.0", "[::1]", "::1", "host.docker.internal")


# ─────────────────────────────────────────────────────────────────────────────
# Частина A — профіль проєкту
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ProjectProfile:
    """Знімок проєкту: мови, тести, точки входу, збірка, спостереження."""

    root: str
    name: str
    languages: dict[str, int] = field(default_factory=dict)
    total_files: int = 0
    tests_dir: str = ""
    has_git: bool = False
    package_manager: str = ""
    entry_points: list[str] = field(default_factory=list)
    readme: str = ""
    #: Ім'я знайденого README (додаткове поле: потрібне, щоб не вигадувати назву).
    readme_file: str = ""
    config_files: list[str] = field(default_factory=list)
    #: Файли збірки проєкту (скрипт, специфікація PyInstaller).
    build_files: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def dominant_extension(self) -> str:
        """Розширення найпоширенішої мови ("" якщо коду немає)."""
        if not self.languages:
            return ""
        return max(self.languages.items(), key=lambda item: (item[1], item[0] != ".py"))[0]

    @property
    def language_label(self) -> str:
        """Назва основної мови для тексту скілів."""
        return LANGUAGE_NAMES.get(self.dominant_extension, self.dominant_extension or "код")

    def summary(self) -> str:
        """Один рядок для журналу."""
        tests = self.tests_dir or "без тестів"
        return (
            f"{self.name}: {self.language_label}, файлів {self.total_files}, "
            f"тести {tests}, пакети {self.package_manager or '—'}"
        )


def _ext_of(name: str) -> str:
    return os.path.splitext(name)[1].lower()


def _ignore_walk_error(_error: OSError) -> None:
    """Помилки доступу під час обходу просто пропускаємо."""


def _walk(root: Path, max_files: int) -> tuple[dict[str, int], int, set[str], list[Path]]:
    """Обійти теку: (мови, усього файлів, файли кореня, кандидати на читання)."""
    languages: dict[str, int] = {}
    total = 0
    top_files: set[str] = set()
    candidates: list[Path] = []
    candidate_cap = MAX_SCAN_FILES * 3
    for current, dirs, files in os.walk(root, onerror=_ignore_walk_error):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIR_NAMES and not d.startswith("."))
        files.sort()
        here = Path(current)
        at_root = here == root
        for name in files:
            low = name.lower()
            if low.endswith((".pyc", ".pyo", ".bak", ".tmp")):
                continue
            total += 1
            if at_root:
                top_files.add(low)
            ext = _ext_of(name)
            if ext in LANGUAGE_EXTENSIONS:
                languages[ext] = languages.get(ext, 0) + 1
                if len(candidates) < candidate_cap:
                    candidates.append(here / name)
            if total >= max_files:
                break
        if total >= max_files:
            break
    return languages, total, top_files, candidates


def _detect_package_manager(top_files: set[str]) -> str:
    for filename, manager in PACKAGE_MANAGERS:
        if filename in top_files:
            return manager
    return ""


def _read_readme(root: Path) -> tuple[str, str]:
    """(ім'я файлу, перші ~2000 символів) для README проєкту."""
    try:
        found = sorted(path for path in root.glob("README*") if path.is_file())
    except OSError:
        return "", ""
    for path in found:
        if path.suffix.lower() not in {".md", ".rst", ".txt", ""}:
            continue
        try:
            text, _encoding = read_text_file(path)
        except (OSError, WorkspaceError, ValueError):
            continue
        return path.name, text[:README_LIMIT]
    return "", ""


def _scan_frameworks(paths: Iterable[Path]) -> list[str]:
    """Знайти технології за рядками імпорту у перших MAX_SCAN_FILES файлах."""
    found: list[str] = []
    budget = MAX_SCAN_FILES
    for path in paths:
        if budget <= 0 or len(found) >= len(_FRAMEWORK_REGEXES):
            break
        if path.suffix.lower() not in LANGUAGE_EXTENSIONS:
            continue
        budget -= 1
        try:
            raw = path.read_bytes()[:MAX_SCAN_BYTES]
        except OSError:
            continue
        if b"\x00" in raw[:2048]:
            continue
        text = raw.decode("utf-8", errors="replace")
        for name, pattern in _FRAMEWORK_REGEXES:
            if name not in found and pattern.search(text):
                found.append(name)
    return found


def _make_notes(profile: ProjectProfile) -> list[str]:
    """Людські спостереження українською — по одному рядку на думку."""
    notes: list[str] = []
    if profile.languages:
        ext = profile.dominant_extension
        count = profile.languages.get(ext, 0)
        notes.append(f"Основна мова — {LANGUAGE_NAMES.get(ext, ext)}, файлів: {count}.")
        if len(profile.languages) > 1:
            others = ", ".join(
                f"{LANGUAGE_NAMES.get(key, key)}: {value}"
                for key, value in list(profile.languages.items())[1:4]
            )
            notes.append(f"Інші мови: {others}.")
    else:
        notes.append("Файлів із кодом не знайдено — проєкт порожній або містить лише дані.")
    notes.append(f"Усього файлів у проєкті: {profile.total_files}.")
    if profile.tests_dir:
        notes.append(f"Знайдено теку тестів «{profile.tests_dir}».")
    else:
        notes.append("Теки тестів (tests/, test/, spec/) не знайдено.")
    if profile.has_git:
        notes.append("Є git-репозиторій — зміни можна звіряти через git status і git diff.")
    if profile.package_manager:
        notes.append(f"Пакетний менеджер: {profile.package_manager}.")
    if profile.entry_points:
        notes.append("Точки входу: " + ", ".join(profile.entry_points) + ".")
    if profile.readme:
        notes.append(f"README прочитано ({len(profile.readme)} символів).")
    else:
        notes.append("README не знайдено — документації в проєкті немає.")
    if profile.frameworks:
        notes.append("Помічені технології: " + ", ".join(profile.frameworks) + ".")
    return notes


def profile_project(root: Path, *, max_files: int = DEFAULT_MAX_FILES) -> ProjectProfile:
    """Швидко зібрати профіль проєкту. Ніколи не кидає винятків.

    Обхід обмежений ``max_files`` файлами й пропускає теки з
    ``workspace.SKIP_DIRS`` плюс ``userdata``, ``.agents``, ``.buildtmp``,
    ``dist``, ``build`` та будь-які теки з крапкою на початку.
    """
    base = Path(root) if root is not None else Path(".")
    profile = ProjectProfile(root=str(base), name=base.name or str(base))
    if not base.is_dir():
        profile.notes.append("Теку проєкту не знайдено — профіль порожній.")
        return profile

    try:
        languages, total, top_files, candidates = _walk(base, max(1, int(max_files)))
    except OSError as exc:  # страховка: os.walk уже м'який, але раптом
        LOG.warning("Не вдалось обійти %s: %s", base, exc)
        languages, total, top_files, candidates = {}, 0, set(), []

    profile.languages = dict(
        sorted(languages.items(), key=lambda item: (-item[1], item[0]))
    )
    profile.total_files = total
    profile.has_git = (base / ".git").exists()
    for candidate in ("tests", "test", "spec"):
        if (base / candidate).is_dir():
            profile.tests_dir = candidate
            break
    profile.package_manager = _detect_package_manager(top_files)
    profile.entry_points = [name for name in ENTRY_POINT_NAMES if name in top_files]
    profile.config_files = [name for name in CONFIG_CANDIDATES if name.lower() in top_files]
    profile.build_files = [name for name in BUILD_CANDIDATES if name.lower() in top_files]
    profile.readme_file, profile.readme = _read_readme(base)
    profile.frameworks = _scan_frameworks(candidates) if candidates else []
    profile.notes = _make_notes(profile)
    return profile


# ─────────────────────────────────────────────────────────────────────────────
# Частина B — пропозиції скілів
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SkillProposal:
    """Готова пропозиція скіла: те, що можна одразу записати у файл."""

    name: str
    description: str
    body: str
    reason: str
    priority: int = 0
    auto: bool = True

    @property
    def text(self) -> str:
        """Повний текст SKILL.md (заголовок + інструкція)."""
        return make_skill_text(self.name, self.description, self.body)


def skill_slug(name: str) -> str:
    """Назва теки скіла — така сама, як у ``skills.create_skill``."""
    slug = re.sub(r"[^\w.-]+", "-", (name or "").strip().lower(), flags=re.UNICODE).strip("-")
    return slug or "новий-скіл"


def skill_path(root: Path, name: str) -> Path:
    """Шлях до ``SKILL.md`` для скіла з такою назвою."""
    return Path(root) / SEARCH_DIRS[0] / skill_slug(name) / SKILL_FILE


def existing_skill_names(root: Path) -> list[str]:
    """Назви скілів, які вже є в проєкті (і теки, і назви з заголовка)."""
    names: list[str] = []
    for skill in discover_skills(Path(root)):
        if skill.name and skill.name not in names:
            names.append(skill.name)
        folder = skill.folder
        if folder and folder not in names:
            names.append(folder)
    return names


def _name_keys(name: str) -> set[str]:
    raw = (name or "").strip().lower()
    return {raw, skill_slug(raw)} if raw else set()


def _test_command(profile: ProjectProfile) -> str:
    """Команда запуску тестів для цього проєкту."""
    frameworks = {item.lower() for item in profile.frameworks}
    configs = {item.lower() for item in profile.config_files}
    pytest_config = {"pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"} & configs
    # pytest — якщо він є в імпортах, має свій конфіг, або є конфіг-файл
    # пакування й жодного сліду unittest.
    use_pytest = "pytest" in frameworks or "pytest.ini" in configs or (
        bool(pytest_config) and "unittest" not in frameworks
    )
    if use_pytest:
        target = profile.tests_dir
        return f"python -m pytest {target} -q" if target else "python -m pytest -q"
    if profile.tests_dir:
        return f"python -m unittest discover -s {profile.tests_dir} -v"
    return "python -m unittest -v"


def _tests_proposal(profile: ProjectProfile) -> SkillProposal | None:
    frameworks = {item.lower() for item in profile.frameworks}
    if not profile.tests_dir and not ({"pytest", "unittest"} & frameworks):
        return None
    command = _test_command(profile)
    folder = profile.tests_dir or "теку з тестами"
    body = "\n".join(
        [
            f"1. Запусти тести перед змінами й після них: `{command}`.",
            "2. Якщо тест падає — прочитай текст помилки, знайди файл і рядок і виправ причину, а не сам тест.",
            "3. Не вимикай і не видаляй тести, щоб «позеленіло»; якщо тест справді застарів — скажи про це в підсумку.",
            "4. Нову поведінку перевіряй новим тестом у теці "
            f"{profile.tests_dir or 'tests'} і не додавай для цього нових залежностей без дозволу.",
            "5. У фінальній відповіді напиши, яку саме команду ти запускав і що вона показала.",
        ]
    )
    detected = ", ".join(sorted(frameworks & {"pytest", "unittest"})) or "теки тестів"
    return SkillProposal(
        name="tests",
        description="Як запускати тести цього проєкту і що робити з падіннями.",
        body=body,
        reason=f"У проєкті є {folder} і ознаки тестового фреймворку ({detected}) — "
        "агент має перевіряти зміни тестами.",
        priority=100,
    )


def _style_proposal(profile: ProjectProfile) -> SkillProposal | None:
    configs = {item.lower() for item in profile.config_files}
    style_configs = [
        name for name in (".flake8", "ruff.toml", ".ruff.toml", "setup.cfg", ".editorconfig", "pyproject.toml")
        if name in configs
    ]
    python_dominant = profile.dominant_extension == ".py"
    if not style_configs and not python_dominant:
        return None
    lines = [
        "1. Спершу подивись на сусідні файли того самого модуля і тримайся їхнього стилю "
        "(відступи, лапки, довжина рядків, назви).",
        "2. Змінюй лише те, що потрібно для задачі: жодного масового переформатування "
        "чи перейменувань «за компанію».",
        "3. Не переписуй файл цілком заради дрібної правки — роби точкову зміну.",
    ]
    if python_dominant:
        lines.append(
            "4. Перед завершенням перевір синтаксис змінених файлів: "
            "`python -m py_compile <файли>`."
        )
    checker = ""
    if "ruff.toml" in configs or ".ruff.toml" in configs:
        checker = "python -m ruff check ."
    elif ".flake8" in configs or "setup.cfg" in configs:
        checker = "python -m flake8 ."
    if checker:
        lines.append(f"{len(lines) + 1}. Якщо є конфігурація стилю — запусти перевірку: `{checker}`.")
    else:
        lines.append(
            f"{len(lines) + 1}. Не додавай нових лінтерів і не змінюй конфіги стилю, "
            "якщо про це не просили."
        )
    destination = ", ".join(style_configs) if style_configs else profile.language_label
    return SkillProposal(
        name="code-style",
        description="Правила стилю коду цього проєкту: мінімальні точкові правки.",
        body="\n".join(lines),
        reason=f"Основна мова — {profile.language_label}, знайдені налаштування стилю: {destination}.",
        priority=80,
    )


def _run_proposal(profile: ProjectProfile) -> SkillProposal | None:
    runnable: list[tuple[str, str]] = []
    for entry in profile.entry_points:
        suffix = Path(entry).suffix.lower()
        if suffix in {".py", ".pyw"}:
            runnable.append((entry, f"python {entry}"))
        elif suffix in {".js", ".mjs", ".cjs"}:
            runnable.append((entry, f"node {entry}"))
    if not runnable:
        return None
    first_entry, first_command = runnable[0]
    lines = [f"1. Запусти проєкт для ручної перевірки: `{first_command}`."]
    if len(runnable) > 1:
        others = ", ".join(f"`{command}` ({entry})" for entry, command in runnable[1:])
        lines.append(f"2. Інші точки входу: {others}.")
    lines.append(
        f"{len(lines) + 1}. Переконайся, що в консолі немає трасування помилок "
        "і застосунок доходить до робочого стану."
    )
    lines.append(
        f"{len(lines) + 1}. Закрий процес після перевірки: Ctrl+C у терміналі "
        "або штатне закриття вікна."
    )
    install_hint = "requirements.txt"
    if profile.package_manager == "poetry":
        install_hint = "pyproject.toml і poetry install"
    elif profile.package_manager == "npm":
        install_hint = "package.json і npm install"
    elif profile.package_manager == "cargo":
        install_hint = "Cargo.toml"
    lines.append(
        f"{len(lines) + 1}. Якщо для запуску бракує залежностей — перевір {install_hint} "
        "і скажи користувачу, чого саме не вистачає, замість тихої установки."
    )
    return SkillProposal(
        name="run-app",
        description="Як запустити цей проєкт, щоб перевірити зміни вручну.",
        body="\n".join(lines),
        reason=f"Знайдено точку входу {first_entry} — зміни можна перевірити запуском.",
        priority=70,
    )


def _git_proposal(profile: ProjectProfile) -> SkillProposal | None:
    if not profile.has_git:
        return None
    body = "\n".join(
        [
            "1. Перед роботою перевір стан: `git status --short` і `git diff`, щоб не зачепити чужі зміни.",
            "2. Не роби `git commit`, `git push`, `git reset` чи `git checkout`, якщо користувач прямо не просив.",
            "3. Не чіпай файли, не пов'язані з задачею, навіть якщо вони «виглядають неправильно».",
            "4. Після змін покажи `git diff --stat` і перелік файлів, які ти змінив.",
        ]
    )
    return SkillProposal(
        name="git-hygiene",
        description="Правила роботи з git у цьому проєкті: ніяких зайвих комітів.",
        body=body,
        reason="Проєкт під git — агент має звіряти зміни через git і не робити комітів без прохання.",
        priority=60,
    )


def _build_proposal(profile: ProjectProfile) -> SkillProposal | None:
    """Скіл збірки — лише коли в профілі справді є файли збірки."""
    known = {Path(item).name.lower() for item in profile.build_files}
    command = ""
    tool = ""
    dist_hint = "теці dist"
    if "build_exe.bat" in known:
        command, tool = "build_exe.bat", "скрипт build_exe.bat"
    elif "blackchpokide.spec" in known:
        command = "python -m PyInstaller BlackChpokIDE.spec --noconfirm"
        tool = "специфікація PyInstaller"
    elif "package.json" in known:
        command, tool = "npm run build", "npm-скрипт збірки"
    elif "cargo.toml" in known:
        command, tool = "cargo build --release", "cargo"
        dist_hint = "теці target/release"
    elif "build.bat" in known:
        command, tool = "build.bat", "скрипт build.bat"
    if not command:
        return None
    body = "\n".join(
        [
            f"1. Збери проєкт: `{command}`.",
            f"2. Перевір, що збірка завершилась без помилок, і подивись результат у {dist_hint}.",
            "3. Не змінюй файли збірки й конфіги пакування, якщо задача їх не стосується.",
            "4. Якщо збірка падає — покажи користувачу перші рядки помилки, а не переписуй скрипт навмання.",
        ]
    )
    return SkillProposal(
        name="build",
        description="Як зібрати реліз цього проєкту і де шукати результат.",
        body=body,
        reason=f"У проєкті є {tool} — збірку можна відтворити однією командою.",
        priority=50,
    )


def _docs_proposal(profile: ProjectProfile) -> SkillProposal | None:
    if not profile.readme.strip():
        return None
    readme_name = profile.readme_file or "README.md"
    body = "\n".join(
        [
            f"1. README проєкту — `{readme_name}`; перед відповіддю звірся з ним, щоб не суперечити документації.",
            "2. Змінив команду запуску, шлях чи порядок роботи — онови відповідний розділ README.",
            "3. Не переписуй README повністю: прав конкретні абзаци й зберігай наявну структуру.",
            "4. Якщо README суперечить коду — вважай код істиною і виправ README, а не код.",
        ]
    )
    return SkillProposal(
        name="docs",
        description="Тримати README у згоді з кодом цього проєкту.",
        body=body,
        reason=f"У проєкті є {readme_name} — документацію треба оновлювати разом із кодом.",
        priority=40,
    )


def propose_skills(
    profile: ProjectProfile,
    existing: Iterable[str] = (),
) -> list[SkillProposal]:
    """Правила-скіли для профілю: детерміновано, без LLM.

    ``existing`` — назви (або теки) уже наявних скілів; такі пропозиції
    відкидаються, щоб не перезаписувати роботу користувача.
    """
    taken: set[str] = set()
    for name in existing or ():
        taken |= _name_keys(str(name))

    candidates = [
        _tests_proposal(profile),
        _style_proposal(profile),
        _run_proposal(profile),
        _git_proposal(profile),
        _build_proposal(profile),
        _docs_proposal(profile),
    ]
    proposals = [item for item in candidates if item is not None]
    proposals = [item for item in proposals if not (_name_keys(item.name) & taken)]
    proposals.sort(key=lambda item: item.priority, reverse=True)
    return proposals[:MAX_PROPOSALS]


def install_proposals(
    root: Path,
    proposals: Iterable[SkillProposal],
    *,
    only_auto: bool = True,
    overwrite: bool = False,
) -> list[Path]:
    """Записати скіли у ``.agents/skills/<slug>/SKILL.md``.

    Повертає шляхи створених (або перезаписаних) файлів. Помилки запису
    лише журналюються — функція не падає посеред списку.
    """
    base = Path(root)
    created: list[Path] = []
    for proposal in proposals or ():
        name = str(getattr(proposal, "name", "") or "").strip()
        if not name:
            continue
        if only_auto and not bool(getattr(proposal, "auto", True)):
            continue
        target = skill_path(base, name)
        try:
            if target.exists() and not overwrite:
                LOG.info("Скіл «%s» уже існує — пропускаю", name)
                continue
            if target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    make_skill_text(
                        name,
                        str(getattr(proposal, "description", "") or ""),
                        str(getattr(proposal, "body", "") or ""),
                    ),
                    encoding="utf-8",
                )
            else:
                target = create_skill(
                    base,
                    name,
                    str(getattr(proposal, "description", "") or ""),
                    str(getattr(proposal, "body", "") or ""),
                )
        except OSError as exc:
            LOG.warning("Не вдалось записати скіл «%s»: %s", name, exc)
            continue
        created.append(target)
    return created


def build_plan(
    root: Path,
    *,
    max_files: int = DEFAULT_MAX_FILES,
) -> tuple[ProjectProfile, list[SkillProposal]]:
    """Профіль + пропозиції з урахуванням уже наявних скілів (зручність для GUI)."""
    profile = profile_project(root, max_files=max_files)
    return profile, propose_skills(profile, existing=existing_skill_names(root))


# ─────────────────────────────────────────────────────────────────────────────
# Частина C — вибір моделі (чиста функція, без мережі)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ModelPlan:
    """Що IDE має зробити з моделлю на старті."""

    base_url: str = ""
    model: str = ""
    action: str = ""
    note: str = ""
    reason: str = ""


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    """getattr без падінь: налаштування може бути будь-яким об'єктом."""
    try:
        return getattr(obj, name, default)
    except Exception:  # noqa: BLE001 — чужі об'єкти можуть кидати що завгодно
        return default


def _is_local_url(url: str) -> bool:
    """Чи адреса веде на локальний сервер.

    Делегує в :func:`provider_adapters.is_local_url` — ЄДИНУ реалізацію.
    Раніше тут був власний список ``LOCAL_HOSTS`` із 7 хостів, а
    ``llm_client`` мав інший; через це та сама адреса в різних місцях
    вважалась локальною або хмарною по-різному.
    """
    from .provider_adapters import is_local_url as _shared

    return _shared(url)


def _pick_local_model(model_path: str, models: list[str], configured: str) -> str:
    """Назва моделі без розширення .gguf для звіту."""
    for raw in (model_path, configured, models[0] if models else ""):
        text = str(raw or "").replace("\\", "/").strip()
        if not text:
            continue
        name = text.rsplit("/", 1)[-1]
        return name[:-5] if name.lower().endswith(".gguf") else name
    return ""


def describe_model_setup(
    settings: Any,
    *,
    engine_installed: bool,
    local_models: list[str],
    server_alive: bool,
) -> ModelPlan:
    """Вирішити, чим агент працюватиме цього запуску.

    Функція чиста: жодного читання файлів, жодного мережевого виклику.
    ``settings`` — будь-який об'єкт із полями ``llm.base_url``,
    ``llm.model``, ``engine.managed``, ``engine.model_path`` (типово
    :class:`blackchpok_ide.config.Settings`).
    """
    llm = _attr(settings, "llm")
    engine = _attr(settings, "engine")
    base_url = str(_attr(llm, "base_url", "") or "").strip()
    model = str(_attr(llm, "model", "") or "").strip()
    managed = bool(_attr(engine, "managed", False))
    model_path = str(_attr(engine, "model_path", "") or "").strip()
    models = [str(item).strip() for item in (local_models or []) if str(item).strip()]

    if base_url and server_alive:
        is_local = _is_local_url(base_url)
        return ModelPlan(
            base_url=base_url,
            model=model,
            action="local-server-ready" if is_local else "external-server",
            note=("Локальний" if is_local else "Зовнішній")
            + " OpenAI-сумісний сервер відповідає — можна писати запити одразу.",
            reason=f"У налаштуваннях вказано {base_url}, і сервер доступний."
            + (" Сервер піднято рушієм IDE." if managed else ""),
        )

    if models and engine_installed:
        chosen = _pick_local_model(model_path, models, model)
        return ModelPlan(
            base_url=LOCAL_SERVER_URL,
            model=chosen,
            action="local-server-ready",
            note="Рушій і модель уже на диску — IDE підніме локальний сервер сама.",
            reason=f"Знайдено моделей: {len(models)}; рушій llama.cpp встановлено, "
            f"беремо {chosen or 'першу модель'}.",
        )

    if engine_installed and not models:
        return ModelPlan(
            action="download-needed",
            note="Рушій llama.cpp є, але жодної GGUF-моделі немає — IDE запропонує завантажити.",
            reason="Без файлу моделі рушій запускати нічого; треба завантажити модель під це залізо.",
        )

    if models and not engine_installed:
        return ModelPlan(
            action="none",
            note="Файл моделі на диску є, але рушій llama.cpp не встановлено — запустити її нічим.",
            reason="Модель без рушія не працює: спершу треба встановити llama.cpp.",
        )

    detail = ""
    if base_url and not server_alive:
        detail = f" Сервер {base_url} не відповідає."
    return ModelPlan(
        action="none",
        note="Немає ні доступного сервера, ні моделі з рушієм — агент працюватиме в офлайн-режимі.",
        reason="Не налаштовано робочий OpenAI-сумісний сервер і не завантажено локальну модель."
        + detail,
    )


__all__ = [
    "EXTRA_SKIP_DIRS",
    "LANGUAGE_EXTENSIONS",
    "LANGUAGE_NAMES",
    "MAX_PROPOSALS",
    "ModelPlan",
    "ProjectProfile",
    "SkillProposal",
    "build_plan",
    "describe_model_setup",
    "existing_skill_names",
    "install_proposals",
    "profile_project",
    "propose_skills",
    "skill_path",
    "skill_slug",
]
