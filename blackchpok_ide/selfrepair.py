"""Саморемонт: агент перевіряє СЕБЕ, знаходить зламане й виправляє.

Навіщо окремий модуль. У реальній роботі (див. скріншоти користувача) агент
не міг виконати просте завдання — створити ``calculator.py`` — і замість
цього писав у чат «готовий код, який можна зберегти вручну». Причина була
не в моделі: власна політика IDE блокувала кожен ``write_file``. Модель про
це здогадалась («the write/append tools are blocked by some safety guard?»),
але нічого не могла вдіяти — у неї не було способу подивитись, ЩО саме її
блокує.

Цей модуль дає такий спосіб. Він робить три речі:

1. **Діагностує себе** — перевіряє те, що справді може зламатись у процесі
   роботи: синтаксис власних модулів, цілісність файлів налаштувань і
   пам'яті, доступність теки проєкту, узгодженість реєстру інструментів.
2. **Пояснює причину** — кожна знахідка має код, людське пояснення й
   підказку, ЩО зробити. Без цього «щось зламалось» — не діагноз.
3. **Ремонтує те, що можна ремонтувати безпечно** — і повідомляє про все,
   чого автоматично не торкається.

Принципове обмеження, закладене в код: **модуль ніколи не править файли
навмання**. Автоматичне виправлення дозволене лише там, де результат
перевіряється тут же (скомпілювати після правки, перечитати після запису) і
де помилка має єдине очевидне виправлення. Усе інше — звіт із пропозицією,
яку виконує модель інструментом.

Модуль не тягне tkinter і не робить мережевих викликів: його можна
перевірити на тимчасовій теці.
"""

from __future__ import annotations

import json
import logging
import os
import py_compile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

__all__ = [
    "Finding",
    "RepairReport",
    "diagnose",
    "format_report",
    "repair_self",
    "self_check_sources",
]

LOG = logging.getLogger("blackchpok.selfrepair")

#: Рівні знахідок. ``FAIL`` — робота неможлива, ``WARN`` — працює, але
#: поводитиметься не так, як очікує людина, ``INFO`` — спостереження.
FAIL = "fail"
WARN = "warn"
INFO = "info"

#: Скільки байт читати з файлу налаштувань, щоб не з'їсти пам'ять.
_SETTINGS_READ_LIMIT = 4_000_000


@dataclass
class Finding:
    """Одна знахідка саморемонту."""

    code: str                       # стабільний ідентифікатор (для тестів)
    level: str
    title: str
    detail: str = ""
    #: Що зробити людині або моделі.
    hint: str = ""
    #: Чи виправлено це автоматично під час прогону.
    fixed: bool = False
    #: Шлях, якого стосується знахідка (для переходу в редакторі).
    path: str = ""

    def line(self) -> str:
        mark = {FAIL: "✗", WARN: "!", INFO: "·"}.get(self.level, "·")
        body = f"{mark} {self.title}"
        if self.fixed:
            body += " (виправлено автоматично)"
        if self.detail:
            body += f" — {self.detail}"
        return body


def _plural(count: int, one: str, few: str, many: str) -> str:
    """Українська форма множини: 1 помилка, 2 помилки, 5 помилок."""
    tail_two = count % 100
    tail_one = count % 10
    if tail_two in (11, 12, 13, 14):
        word = many
    elif tail_one == 1:
        word = one
    elif tail_one in (2, 3, 4):
        word = few
    else:
        word = many
    return f"{count} {word}"


@dataclass
class RepairReport:
    """Результат самоперевірки."""

    findings: list[Finding] = field(default_factory=list)
    #: Скільки файлів перевірено (для чесного звіту).
    checked: int = 0
    #: Скільки виправлено автоматично.
    fixed: int = 0

    @property
    def failed(self) -> list[Finding]:
        return [item for item in self.findings if item.level == FAIL]

    @property
    def warned(self) -> list[Finding]:
        return [item for item in self.findings if item.level == WARN]

    @property
    def ok(self) -> bool:
        return not self.failed

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)
        if finding.fixed:
            self.fixed += 1

    def summary(self) -> str:
        """Один рядок для журналу."""
        files = _plural(self.checked, "файл", "файли", "файлів")
        if not self.findings:
            return f"Самоперевірка: усе гаразд (перевірено {files})."
        parts = []
        if self.failed:
            parts.append(_plural(len(self.failed), "помилка", "помилки", "помилок"))
        if self.warned:
            parts.append(_plural(len(self.warned), "застереження",
                                 "застереження", "застережень"))
        if self.fixed:
            parts.append(_plural(self.fixed, "виправлено", "виправлено",
                                 "виправлено"))
        return ("Самоперевірка: " + ", ".join(parts)
                + f". Перевірено {files}.")


# ── перевірка синтаксису власних модулів ────────────────────────────────────

def self_check_sources(root: str | Path, *, limit: int = 0) -> list[tuple[str, str]]:
    """Скомпілювати модулі пакета й повернути ``[(шлях, помилка)]``.

    Навіщо саме компіляція, а не «прочитати й подивитись». ``py_compile``
    — це та сама перевірка, яку зробить Python під час імпорту. Якщо вона
    проходить, модуль справді завантажиться; жодна інша перевірка цього не
    гарантує.

    ``limit`` > 0 обмежує кількість файлів (щоб перевірка великого
    проєкту не блокувала хід агента).
    """
    base = Path(root)
    if not base.exists():
        return []
    broken: list[tuple[str, str]] = []
    seen = 0
    for path in sorted(base.rglob("*.py")):
        # Теки кешу й віртуального середовища не є кодом проєкту.
        parts = {part.lower() for part in path.parts}
        if parts & {"__pycache__", ".venv", "venv", "site-packages", "node_modules"}:
            continue
        seen += 1
        if limit and seen > limit:
            break
        try:
            py_compile.compile(str(path), doraise=True, cfile=_temp_cfile())
        except py_compile.PyCompileError as exc:
            broken.append((str(path), _compile_message(exc)))
        except (OSError, ValueError) as exc:
            broken.append((str(path), f"не читається: {exc}"))
    return broken


def _temp_cfile() -> str:
    """Тимчасовий шлях для ``.pyc``, щоб не смітити в теці проєкту.

    ``py_compile.compile`` за замовчуванням пише ``__pycache__`` поруч із
    файлом. Саморемонт не має лишати по собі сміття в чужому проєкті.
    """
    handle, path = tempfile.mkstemp(suffix=".pyc")
    os.close(handle)
    try:
        os.unlink(path)
    except OSError:
        pass
    return path


def _compile_message(exc: Exception) -> str:
    """Витягти з ``PyCompileError`` людський рядок без службового шуму."""
    text = str(getattr(exc, "msg", "") or exc)
    body = " ".join(str(text).split())
    return body[:300]


# ── перевірка файлів стану ──────────────────────────────────────────────────

def _check_json_file(path: Path, code: str, title: str,
                     report: RepairReport) -> None:
    """Перевірити, що файл стану — валідний JSON (або його немає)."""
    if not path.exists():
        return
    report.checked += 1
    try:
        size = path.stat().st_size
    except OSError as exc:
        report.add(Finding(code=code, level=WARN, title=title,
                           detail=f"файл недоступний: {exc}", path=str(path)))
        return
    if size == 0:
        report.add(Finding(
            code=f"{code}.empty", level=WARN, title=title,
            detail="файл порожній",
            hint="Налаштування відновляться з типових; попередній вміст втрачено.",
            path=str(path)))
        return
    if size > _SETTINGS_READ_LIMIT:
        report.add(Finding(
            code=f"{code}.huge", level=INFO, title=title,
            detail=f"файл завеликий ({size // 1024} КБ)",
            path=str(path)))
        return
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        report.add(Finding(code=f"{code}.unreadable", level=FAIL, title=title,
                           detail=f"не читається: {exc}", path=str(path)))
        return
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        report.add(Finding(
            code=f"{code}.broken", level=FAIL, title=title,
            detail=f"пошкоджений JSON (рядок {exc.lineno}: {exc.msg})",
            hint=("Файл буде прочитано як типові налаштування. "
                  "Відновлення з резервної копії — у Налаштуваннях."),
            path=str(path)))


# ── діагностика ────────────────────────────────────────────────────────────

def diagnose(*, workspace: str | Path = "", settings_path: str | Path = "",
             package_root: str | Path = "", source_limit: int = 0,
             registry_names: Iterable[str] | None = None) -> RepairReport:
    """Перевірити власний стан IDE й повернути звіт.

    Усі параметри необов'язкові: викликач передає те, що знає. Модуль
    нічого не вигадує — якщо шлях не передано, відповідна перевірка просто
    не виконується, і у звіті це видно (``checked`` лишається меншим).
    """
    report = RepairReport()

    # 1. Тека проєкту — без неї агент не може ні читати, ні писати.
    if workspace:
        root = Path(workspace)
        if not root.exists():
            report.add(Finding(
                code="workspace.missing", level=FAIL,
                title="Робоча тека не існує",
                detail=str(root),
                hint="Відкрий іншу теку проєкту (Файл → Відкрити).",
                path=str(root)))
        elif not root.is_dir():
            report.add(Finding(
                code="workspace.not_dir", level=FAIL,
                title="Робочий шлях — не тека",
                detail=str(root), path=str(root)))
        else:
            report.checked += 1
            if not os.access(root, os.W_OK):
                report.add(Finding(
                    code="workspace.readonly", level=WARN,
                    title="У робочу теку не можна писати",
                    detail=str(root),
                    hint=("Агент зможе лише читати. Перевір права доступу "
                          "або відкрий теку, яка належить тобі."),
                    path=str(root)))

    # 2. Файл налаштувань — пошкоджений JSON означає «все повернулось до
    #    типових», і користувач не розуміє, чому зникли його параметри.
    if settings_path:
        _check_json_file(Path(settings_path), "settings",
                         "Файл налаштувань", report)

    # 3. Синтаксис власних модулів: якщо IDE зламала сама себе (напр.
    #    агент відредагував свій же модуль і зробив помилку), це видно
    #    одразу, а не після перезапуску.
    if package_root:
        broken = self_check_sources(package_root, limit=source_limit)
        report.checked += 1
        for path, message in broken[:8]:
            report.add(Finding(
                code="source.broken", level=FAIL,
                title=f"Синтаксис зламано: {Path(path).name}",
                detail=message,
                hint="Виправ цей файл — інакше IDE не запуститься після перезапуску.",
                path=path))

    # 4. Реєстр інструментів: порожній реєстр означає, що модель не може
    #    нічого зробити, хоч виглядає як «модель не відповідає».
    if registry_names is not None:
        names = [str(name) for name in registry_names if str(name).strip()]
        report.checked += 1
        if not names:
            report.add(Finding(
                code="tools.empty", level=FAIL,
                title="Реєстр інструментів порожній",
                detail="модель не отримає жодної дії",
                hint="Перезапусти IDE; якщо не допомогло — перевір реєстр MCP."))
        else:
            for required in ("read_file", "write_file"):
                if required not in names:
                    report.add(Finding(
                        code=f"tools.missing.{required}", level=FAIL,
                        title=f"Немає інструмента «{required}»",
                        detail="агент не зможе працювати з файлами",
                        hint="Перезапусти IDE, щоб відновити вбудований реєстр."))

    return report


# ── безпечний ремонт ───────────────────────────────────────────────────────

def repair_self(report: RepairReport, *,
                workspace: str | Path = "") -> RepairReport:
    """Виправити те, що можна виправити безпечно, і позначити це у звіті.

    Що ремонтується автоматично:

    * **синтаксис власного модуля** — лише якщо виправлення перевіряється
      негайною компіляцією (детерміновані випадки на зразок апострофа
      всередині подвійних лапок);
    * **відсутня робоча тека** — створюється, бо її відсутність завжди
      помилка конфігурації, а не вибір користувача.

    Чого НЕ робимо ніколи:

    * не переписуємо файли стану «на око» — пошкоджений JSON лишаємо
      людині, бо вгадати втрачений вміст неможливо;
    * не чіпаємо файли поза робочою текою;
    * не «ремонтуємо» код, який компілюється.
    """
    for finding in report.findings:
        if finding.fixed:
            continue
        if finding.code == "workspace.missing" and finding.path:
            try:
                Path(finding.path).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                finding.detail = f"{finding.detail} (створити не вдалось: {exc})"
                continue
            finding.fixed = True
            report.fixed += 1
        elif finding.code == "source.broken" and finding.path:
            if _try_fix_quotes(Path(finding.path)):
                finding.fixed = True
                report.fixed += 1
    return report


#: Заміна апострофа всередині подвійних лапок — детермінований випадок.
def _try_fix_quotes(path: Path) -> bool:
    """Спробувати виправити лапки й ПЕРЕВІРИТИ результат компіляцією.

    Повертає True лише тоді, коли після правки файл справді компілюється.
    Інакше файл лишається незміненим: псувати чужий код «навмання» гірше,
    ніж показати помилку.
    """
    try:
        original = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    fixed = _swap_quotes(original)
    if fixed == original:
        return False
    try:
        compile(fixed, str(path), "exec", dont_inherit=True)
    except SyntaxError:
        return False
    try:
        path.write_text(fixed, encoding="utf-8")
    except OSError:
        return False
    LOG.info("Саморемонт: виправлено лапки у %s", path)
    return True


def _swap_quotes(body: str) -> str:
    """Поміняти зовнішні одинарні лапки на подвійні в зламаних рядках.

    Правило навмисно вузьке й перевірене: у рядку, який Python НЕ МОЖЕ
    скомпілювати через лапки, беремо ПЕРШУ одинарну лапку як відкривну й
    ОСТАННЮ як закривну. Це єдиний випадок, який трапляється в практиці
    агента:

        input('Введіть ім'я: ')   →   input("Введіть ім'я: ")

    Рядок, який компілюється, не чіпаємо взагалі — інакше саморемонт
    «виправляв» би коректний код.
    """
    lines: list[str] = []
    for line in body.splitlines(keepends=True):
        fixed = _swap_line(line)
        lines.append(fixed if fixed is not None else line)
    return "".join(lines)


def _swap_line(line: str) -> str | None:
    """Один рядок: None — правка не потрібна або неможлива."""
    text = line.rstrip("\n")
    newline = "\n" if line.endswith("\n") else ""
    if "'" not in text and '"' not in text:
        return None
    # Рядок компілюється — у ньому немає проблеми з лапками.
    try:
        compile(text, "<line>", "exec", dont_inherit=True)
        return None
    except SyntaxError as exc:
        message = (exc.msg or "").lower()
        if not any(word in message
                   for word in ("string", "quote", "unterminated", "eol")):
            return None
    except (ValueError, TypeError):
        return None
    first = text.find("'")
    last = text.rfind("'")
    if first < 0 or last <= first:
        return None
    inner = text[first + 1:last]
    if '"' in inner:
        return None                    # конфлікт із подвійними лапками
    fixed = text[:first] + '"' + inner + '"' + text[last + 1:] + newline
    try:
        compile(fixed.rstrip("\n"), "<line>", "exec", dont_inherit=True)
    except SyntaxError:
        return None
    return fixed



# ── звіт ───────────────────────────────────────────────────────────────────

def format_report(report: RepairReport) -> str:
    """Готовий текст для чату або журналу."""
    head = report.summary()
    if not report.findings:
        return head
    lines = [head, ""]
    for finding in report.findings:
        lines.append(finding.line())
        if finding.hint and not finding.fixed:
            lines.append(f"   → {finding.hint}")
    return "\n".join(lines)
