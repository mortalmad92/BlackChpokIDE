"""Переклад звичайної мови на конкретну дію агента.

Користувач не називає інструменти. Довша фраза перемагає коротшу,
щоб «знайди функцію» не плуталось із загальним «знайди».
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

RULES: list[tuple[str, tuple[str, ...]]] = [
    ("night_shift", ("нічна зміна до ранку", "працюй поки я сплю", "розбери чергу задач", "стан нічної зміни", "нічна зміна", "працюй до ранку")),
    ("undo_edit", ("відкоти останню", "відкоти зміну", "скасуй правку", "скасуй останню", "поверни як було", "поверни файл")),
    ("run_tests", ("запусти тести", "прожени тести", "run tests", "pytest", "запусти pytest", "виконай тести", "перевір тестами")),
    ("run_and_repair", ("полагодь", "виправ скрипт", "запусти і виправ", "автодебаг", "/debug", "debug ")),
    ("social_post", ("напиши пост", "згенеруй пост", "чернетка поста", "пост для", "опублікуй пост", "опублікуй в", "опублікуй у", "виклади пост", "запости", "пост у твіт", "пост в твіт", "пост у фейс", "пост в фейс", "пост у телеграм", "пост в телеграм")),
    ("build_project", ("напиши скрипт", "напиши програму", "створи скрипт", "зроби скрипт", "згенеруй", "/costruisci", "вайб", "напиши код", "створи файл", "створи сайт", "зроби сайт", "зроби лендінг", "створи лендінг", "створи сторінку", "зроби сторінку", "створи html", "зроби html", "створи додаток", "зроби додаток", "створи застосунок", "створи бота", "зроби бота", "створи телеграм бота", "створи гру", "створи api", "створи сервер", "зроби сервер", "зроби калькулятор", "створи калькулятор", "зроби todo", "створи todo", "напиши функцію", "напиши клас", "напиши модуль", "створи новий проєкт", "створи проєкт", "зроби проєкт", "напиши бота", "зроби бота", "напиши сайт", "зроби гру")),
    ("index_project", ("проіндексуй", "вивчи проєкт", "вивчи проект", "indicizza", "/indicizza", "запам'ятай код", "створи індекс", "онови індекс", "проіндексувати", "зроби індекс", "побудуй індекс")),
    ("launch_help", ("як запустити", "як запускати", "інструкція запуску", "come lanciarlo")),
    ("refresh_memory", ("онови пам'ять", "оновити пам'ять", "актуалізуй пам'ять", "прибери застаріле", "звіряй пам'ять", "почисти пам'ять")),
    ("memory_search", ("що ти пам'ятаєш", "пошук у пам'яті", "знайди в книгах", "що вивчив", "що ти знаєш про", "згадай", "пам'ятаєш", "довгостроков", "у пам'яті", "база знань", "пошук в базі знань", "що в пам'яті", "знайди спогади", "пошукай в пам'яті")),
    ("chat_history", ("що ми говорили", "історія чату", "пригадай розмову", "минула розмова")),
    ("set_engine", ("/modo", "перемкни модель", "режим gemini", "режим ollama", "режим lm studio")),
    ("install_package", ("встанови бібліотеку", "встанови пакет", "встанови програму", "постав бібліотеку", "постав пакет", "pip install", "npm install", "winget install")),
    ("project_context", ("контекст проєкту", "що вже є у файлі", "поточний стан файлів")),
    ("clear_cache", ("очисти кеш", "почисти кеш", "clear cache")),
    ("ask_browser_ai", ("запитай gemini", "запитай deepseek", "через браузер")),
    ("fetch_url", ("відкрий посилання", "відкрий сайт", "http://", "https://")),
    ("finance_brief", ("новини фінанс", "фінансові новини", "криптовалют", "крипта", "який койн", "який коин", "коли купити", "інвестиц", "ціна бітк", "курс бітк", "ринок крипт")),
    ("search_web", ("пошукай в інтернет", "пошукай в інтернеті", "пошукай", "загугли", "в гуглі", "search web", "вікіпедія", "що пишуть", "знайди в мережі", "яка погода", "погода в", "погода у")),
    ("review_code", ("перевір код", "перевір якість", "перевір файл на помилки", "код-рев'ю", "рев'ю коду", "знайди помилки в коді", "перевір безпеку коду")),
    ("diagnostics", ("перевір синтаксис", "чи компілюється", "syntax check")),
    ("find_symbol", ("де визначен", "де функці", "знайди функці", "знайди клас", "where is", "def ", "покажи функцію", "де клас", "де визначено", "пошук функції")),
    ("grep", ("знайди текст", "пошукай у файлах", "пошукай у коді", "grep ", "знайди в коді", "пошук по коду")),
    ("read_files", ("прочитай файли", "покажи файли")),
    ("read_file", ("прочитай", "покажи файл", "відкрий файл", "глянь файл", "read file", "покажи вміст", "виведи текст")),
    ("replace_lines", ("заміни рядки", "перепиши рядки")),
    ("replace_all", ("заміни всі", "заміни усюди")),
    ("replace_in_file", ("заміни в файлі", "заміни текст", "підміни")),
    ("append_file", ("допиши у файл", "додай у кінець")),
    ("write_file", ("запиши у файл", "перезапиши файл")),
    ("delete_file", ("видали файл", "прибери файл", "стерти файл")),
    ("copy_file", ("скопіюй файл", "копія файлу")),
    ("move_file", ("перейменуй файл", "перемісти файл")),
    ("mkdir", ("створи папку", "нова папка")),
    ("diff_files", ("порівняй файли", "різниця між файлами")),
    ("hash_file", ("хеш файлу", "sha256", "контрольна сума")),
    ("file_info", ("розмір файлу", "інфо про файл", "коли змінений")),
    ("glob_files", ("знайди файли", "усі файли", "всі py файли", "*.py")),
    ("list_dir", ("покажи папку", "що в папці", "список файлів", "вміст папки", "покажи структуру", "дерево папок", "покажи дерево")),
    ("db_schema", ("схема бази", "які таблиці", "структура бази", "колонки в базі")),
    ("preview_local", ("відкрий локальну сторінку", "перевір localhost", "глянь localhost", "локальна сторінка")),
    ("analyze_project", ("проаналізуй проєкт", "проаналізуй проект", "аналіз проєкту", "аналіз проекту", "які інструменти", "які б інструменти")),
    ("project_map", ("карта проєкту", "де що лежить", "огляд великого проєкту")),
    ("project_outline", ("структура проєкту", "структура проекту", "структуру", "огляд проєкту", "як влаштований")),
    ("git_show", ("покажи коміт", "git show")),
    ("git_log", ("історія коміт", "останні коміти", "git log")),
    ("git_diff", ("git diff", "покажи диф", "незакомічені зміни")),
    ("git_context", ("стан гіт", "git status", "що в гіті", "що змінилось в гіт")),
    ("run_shell", ("виконай команду", "запусти команду", "в терміналі", "run ")),
    ("todo_list", ("список задач", "що в задачах", "мої задачі")),
    ("todo_write", ("додай задачу", "нова задача")),
    ("list_rules", ("які правила", "покажи правила")),
    ("remember_project", ("запам'ятай для проєкту", "запам'ятай про проєкт", "у цьому проєкті")),
    ("save_rule", ("запам'ятай правило", "правило:", "нове правило", "запиши правило", "збережи правило", "додай правило", "запам'ятай назавжди")),
    ("rag_search", ("семантичний пошук", "rag")),
    ("env_which", ("де лежить команда", "where ")),
    ("system_info", ("інформація про систему", "системна інформація", "який python",
                        "яка версія python", "версія пітона", "system info", "system_info",
                        "про залізо", "характеристики пк")),
    ("list_intents", ("які дії ти вмієш", "що ти вмієш", "список дій", "list_intents",
                        "які інструменти", "перелік інструментів")),
]

_PATH = re.compile(r"((?:[\w./\\-]+)\.(?:py|js|ts|tsx|jsx|json|md|txt|html|css|yml|yaml|toml|ini|sql|ps1|bat))", re.I)
_IDENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\b")
_PKG = re.compile(r"(?:бібліотеку|пакет|install)\s+([A-Za-z0-9_.\-]+)", re.I)

LABELS = {
    "read_file": "прочитати файл",
    "read_files": "прочитати кілька файлів",
    "list_dir": "показати папку",
    "glob_files": "знайти файли",
    "grep": "знайти текст у коді",
    "find_symbol": "знайти функцію або клас",
    "project_outline": "показати структуру проєкту",
    "project_map": "карта великого проєкту",
    "analyze_project": "проаналізувати проєкт і показати наявні дії",
    "remember_project": "запам'ятати правило проєкту",
    "db_schema": "схема локальної бази",
    "preview_local": "відкрити локальну сторінку",
    "write_file": "записати файл",
    "append_file": "дописати файл",
    "replace_in_file": "замінити фрагмент",
    "replace_all": "замінити всі входження",
    "replace_lines": "замінити рядки",
    "delete_file": "видалити файл",
    "move_file": "перемістити файл",
    "copy_file": "скопіювати файл",
    "mkdir": "створити папку",
    "file_info": "інформація про файл",
    "hash_file": "порахувати хеш",
    "diff_files": "порівняти файли",
    "diagnostics": "перевірити синтаксис",
    "review_code": "перевірити код",
    "run_shell": "виконати команду",
    "run_tests": "запустити тести",
    "git_context": "стан git",
    "git_diff": "різниця git",
    "git_log": "історія комітів",
    "git_show": "показати коміт",
    "search_web": "пошук в інтернеті",
    "finance_brief": "огляд ринку і новин",
    "fetch_url": "відкрити посилання",
    "ask_browser_ai": "запитати браузерний ШІ",
    "rag_search": "пошук по локальній пам'яті",
    "memory_search": "пошук у вивчених книгах і коді",
    "refresh_memory": "звірити і оновити довгострокову пам'ять",
    "chat_history": "згадати розмову",
    "save_rule": "запам'ятати правило",
    "list_rules": "показати правила",
    "todo_write": "додати задачу",
    "todo_list": "показати задачі",
    "clear_cache": "очистити кеш",
    "index_project": "вивчити проєкт",
    "run_and_repair": "запустити і полагодити",
    "build_project": "написати і запустити скрипт",
    "social_post": "підготувати пост для соцмережі",
    "launch_help": "пояснити запуск",
    "set_engine": "перемкнути модель",
    "install_package": "встановити бібліотеку",
    "project_context": "зібрати контекст файлів",
    "system_info": "інформація про систему",
    "env_which": "знайти команду",
    "list_intents": "показати можливості",
    "talk": "відповісти з пам'яті",
    "undo_edit": "відкотити останню правку",
    "night_shift": "нічна черга задач до дедлайну",
}


@dataclass
class Decision:
    intent: str
    query: str
    file_path: str
    extra: str
    label: str


def _norm(text: str) -> str:
    return (
        (text or "")
        .lower()
        .replace("'", "")
        .replace("’", "")
        .replace("ʼ", "")
        .replace("`", "")
    )


def classify(text: str) -> Decision:
    raw = (text or "").strip()
    low = _norm(raw)
    best_intent, best_len = "talk", 0
    for intent, phrases in RULES:
        for phrase in phrases:
            needle = _norm(phrase)
            if needle and needle in low and len(needle) > best_len:
                best_intent, best_len = intent, len(needle)
    path = _extract_path(raw)
    query, extra = _slots(best_intent, raw, path)
    planned = shell_plan(raw)
    if planned and best_intent in {"talk", "install_package", "env_which", "system_info"}:
        if best_intent != "run_shell":
            return Decision("run_shell", planned, path, "180", "виконати в командному рядку")
    if best_intent == "run_shell" and not _looks_like_command(query):
        if planned:
            return Decision("run_shell", planned, path, "180", "виконати в командному рядку")
    return Decision(best_intent, query, path, extra, LABELS.get(best_intent, best_intent))


_CLI = {
    "python": "python", "python3": "python", "py": "python", "пітон": "python", "пайтон": "python",
    "pip": "pip", "node": "node", "nodejs": "node", "нода": "node", "ноду": "node",
    "npm": "npm", "нпм": "npm", "git": "git", "гіт": "git", "гіта": "git",
    "docker": "docker", "докер": "docker", "winget": "winget",
    "java": "java", "javac": "javac", "go": "go", "cargo": "cargo", "rustc": "rustc",
    "ollama": "ollama", "pytest": "pytest", "ffmpeg": "ffmpeg", "curl": "curl",
    "pwsh": "pwsh", "powershell": "powershell", "code": "code", "cursor": "cursor", "lms": "lms",
}
_PROGRAMS = {"git", "node", "docker", "ffmpeg", "java", "javac", "go", "cargo", "rustc", "cursor", "code", "ollama", "lms"}


def _py() -> str:
    return f'"{sys.executable}"'


def _safe_token(token: str) -> str:
    token = (token or "").strip(" .,!?:;\"'`")
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.\-]*", token):
        return token
    return ""


def _cli_name(token: str) -> str:
    key = _norm(token)
    if key in _CLI:
        return _CLI[key]
    safe = _safe_token(token)
    return safe if safe.lower() in _CLI.values() else ""


def _looks_like_command(text: str) -> bool:
    body = (text or "").strip()
    if not body or re.search(r"[А-Яа-яІіЇїЄєҐґ]", body):
        return False
    return bool(re.match(r"^[A-Za-z0-9_\"'.\\/: -]+$", body))


def shell_plan(text: str) -> str:
    """Звичайна фраза про встановлення або перевірку -> одна команда Windows. Порожньо, якщо це не термінал."""
    raw = (text or "").strip()
    low = _norm(raw)
    if not raw:
        return ""
    py = _py()

    if any(word in low for word in ("список програм", "що встановлено на комп", "winget list")):
        return "winget list"
    if any(word in low for word in ("список пакет", "які бібліотеки", "pip list", "що поставлено pip")):
        return f"{py} -m pip list"
    if "npm list" in low or "які npm" in low:
        return "npm list -g --depth=0"

    install = re.search(
        r"(?<![\w])(?:встанови|постав|доустанови|інсталюй|install)\s+(?:мені\s+)?(?:бібліотеку|пакет|модуль|програму|додаток|через\s+\w+)?\s*([^\n]+)",
        raw,
        flags=re.I,
    )
    if install:
        tail = install.group(1).strip()
        npm = "npm" in low or "нпм" in low
        program = any(word in low for word in ("програм", "додаток", "winget"))
        token = _safe_token(tail.split()[0]) if tail else ""
        cli = _cli_name(tail.split()[0]) if tail else ""
        if npm and token:
            flag = "-g " if "глобальн" in low else ""
            return f"npm install {flag}{token}"
        if (program or cli in _PROGRAMS) and token:
            return (
                "winget install --accept-package-agreements --accept-source-agreements "
                f"--disable-interactivity {token}"
            )
        if token:
            return f"{py} -m pip install {token}"
        return ""

    version = re.search(
        r"(?<![\w])версі[яю]\w*(?:\s+у)?(?:\s+пакета|\s+програми|\s+команди)?\s+([A-Za-zА-Яа-яІіЇїЄєҐґ0-9_.\-]+)",
        raw,
        flags=re.I,
    )
    if version:
        cli = _cli_name(version.group(1))
        if cli == "python":
            return f"{py} --version"
        if cli == "pip":
            return f"{py} -m pip --version"
        if cli:
            return f"{cli} --version"
        token = _safe_token(version.group(1))
        if token:
            return f"{py} -m pip show {token}"

    present = re.search(
        r"(?:чи встановлен\w*|чи інстальован\w*|чи є|чи стоїть|де лежить|where)\s+(?:команда|програма|бібліотека|пакет|модуль)?\s*([A-Za-zА-Яа-яІіЇїЄєҐґ0-9_.\-]+)",
        raw,
        flags=re.I,
    )
    if present:
        cli = _cli_name(present.group(1))
        if cli == "python":
            return f"where python & {py} --version"
        if cli == "pip":
            return f"{py} -m pip --version"
        if cli:
            return f"where {cli} & {cli} --version"
        token = _safe_token(present.group(1))
        if token and any(word in low for word in ("бібліотек", "пакет", "модул", "pip")):
            return f"{py} -m pip show {token}"
        if token:
            return f"where {token} & {token} --version"

    learn = re.search(
        r"(?:дізнайся|узнай|перевір|глянь)\s+(?:будь ласка\s+)?(?:яка\s+|яку\s+|чи\s+є\s+|чи\s+|версію\s+)?(?:версі[яю]\w*\s+)?([A-Za-zА-Яа-яІіЇїЄєҐґ0-9_.\-]+)",
        raw,
        flags=re.I,
    )
    if learn:
        cli = _cli_name(learn.group(1))
        if cli == "python":
            return f"{py} --version"
        if cli == "pip":
            return f"{py} -m pip --version"
        if cli:
            return f"where {cli} & {cli} --version"
    bare = re.search(r"(?:який|яка|яке)\s+([A-Za-zА-Яа-яІіЇїЄєҐґ0-9_.\-]+)\s*$", raw, flags=re.I)
    if bare:
        cli = _cli_name(bare.group(1))
        if cli == "python":
            return f"{py} --version"
        if cli == "pip":
            return f"{py} -m pip --version"
        if cli:
            return f"where {cli} & {cli} --version"
    return ""


def _extract_path(text: str) -> str:
    match = _PATH.search(text)
    if not match:
        return ""
    return match.group(1).strip("`\"'")


def _slots(intent: str, text: str, path: str) -> tuple[str, str]:
    low = text.lower()
    if intent == "find_symbol":
        named = re.search(r"(?:функці[юяі]|клас|function|class)\s+[«\"']?([A-Za-z_][\w]*)", text, re.I)
        if named:
            return named.group(1), ""
        idents = [item for item in _IDENT.findall(text) if item.lower() not in {"def", "class", "where", "file"}]
        return (idents[-1] if idents else ""), ""
    if intent == "install_package":
        found = _PKG.search(text)
        return (found.group(1) if found else ""), ""
    if intent == "save_rule":
        tail = re.split(r"правил[оа]:?", text, maxsplit=1, flags=re.I)
        return (tail[-1].strip(" :") if len(tail) > 1 else text), ""
    if intent == "search_web":
        tail = re.split(r"інтернет[іу]?|загугли|в гуглі|search web", low, maxsplit=1)
        return (text[len(text) - len(tail[-1]):].strip(" :") if len(tail) > 1 else text), ""
    if intent == "fetch_url":
        url = re.search(r"https?://\S+", text)
        return (url.group(0).rstrip(".,)") if url else text), ""
    if intent == "set_engine":
        for mode in ("gemini-pro", "gemini", "ollama", "lmstudio", "lm studio", "auto", "14b", "pi"):
            if mode in low:
                mapped = {"lm studio": "lmstudio", "14b": "lmstudio", "pi": "ollama"}.get(mode, mode)
                return mapped, ""
        return "auto", ""
    if intent == "ask_browser_ai":
        provider = "deepseek" if "deepseek" in low else "gemini"
        return text, provider
    if intent == "run_shell":
        tail = re.split(r"команду|в терміналі|run ", text, maxsplit=1, flags=re.I)
        return (tail[-1].strip(" :") if len(tail) > 1 else text), ""
    if intent == "grep":
        quoted = re.search(r"[\"'«](.+?)[\"'»]", text)
        return (quoted.group(1) if quoted else text), ""
    if intent == "run_tests":
        return "pytest", ""
    if intent == "write_file":
        rest = _PATH.sub("", text)
        rest = re.sub(r"запиши у файл|перезапиши файл", "", rest, flags=re.I).strip(" :")
        return rest, ""
    if intent in {"read_file", "diagnostics", "review_code", "launch_help", "file_info", "hash_file", "list_dir", "project_outline", "project_map", "analyze_project", "db_schema", "preview_local", "run_and_repair", "undo_edit"}:
        return "", ""
    if intent == "social_post":
        return text, ""
    if intent == "finance_brief":
        return text, ""
    if intent in {"build_project"}:
        return text, ""
    if intent in {"git_context", "git_diff", "git_log", "git_show", "system_info", "list_intents", "clear_cache", "todo_list", "list_rules"}:
        return "", ""
    if intent == "remember_project":
        return text, ""
    if intent == "todo_write":
        tail = re.split(r"задач[уа]:?", text, maxsplit=1, flags=re.I)
        return (tail[-1].strip(" :") if len(tail) > 1 else text), ""
    return text, ""