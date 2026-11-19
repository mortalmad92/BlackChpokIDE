"""Запобіжники для команд агента: «чекає на ввід» і «пише гігабайти на диск».

Навіщо цей модуль. Живий випадок, через який він з'явився. Модель виконала

    python - > ui_contrast.tmp.txt 2>&1
    import itertools, sys
    …

Очікувалось «передати скрипт Python через stdin». Насправді рядок після
переводу рядка до stdin НЕ потрапляє: оболонка бачить команду ``python -``
(читати скрипт із stdin), запускає інтерпретатор, той не отримує нічого,
виходить у REPL — і **чекає на ввід вічно**. А ``2>&1`` спрямував увесь
шум REPL у файл. Кожна помилка `_pyrepl` — це кілька кілобайт, і за
25 хвилин набігло **3.5 ГБ**. Таймаут 120 с команду зупинив, але процес
пережив батька й писав далі.

Дві перевірки тут:

1. :func:`input_trap` — чи команда чекатиме на ввід, якого не буде.
2. :func:`redirect_risk` — чи команда перенаправляє вивід у файл, який
   може вирости без обмежень.

Обидві повертають **текст-пояснення** (не виняток): виклик вирішує, що
робити. Модуль не запускає жодних процесів і не залежить від tkinter —
його легко перевірити тестом.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

__all__ = [
    "MAX_REDIRECT_BYTES",
    "RedirectRisk",
    "input_hint",
    "input_trap",
    "redirect_hint",
    "redirect_risk",
    "redirect_targets",
]

#: Стеля для файлу, у який команда пише через ``>`` / ``>>``.
#:
#: 64 МБ — це багато для справжнього виводу (лог, звіт, дамп), але мало
#: для катастрофи: саме так файл-витік став би помітним ЗАЗДАЛЕГІДЬ, а не
#: через 3.5 ГБ. Змінна середовища ``BLACKCHPOK_MAX_REDIRECT_MB`` дозволяє
#: змінити межу, якщо комусь справді треба більше.
MAX_REDIRECT_BYTES = 64 * 1024 * 1024

#: Інтерпретатори, які вміють читати скрипт зі stdin через ``-``.
_STDIN_INTERPRETERS = (
    "python", "python3", "py", "node", "perl", "ruby", "php",
    "powershell", "pwsh", "bash", "sh",
)

#: Команди, що чекають на ввід, коли їм не передати даних.
_INTERACTIVE_COMMANDS = (
    "pause", "more", "timeout /t", "set /p", "choice",
    "read-host", "input(",
)

#: Місця, де ``-`` означає «читати з stdin» (а не «аргумент»).
#: Приклади: ``python - ``, ``node -``, ``py -3 -``, ``powershell -``.
_STDIN_PATTERN = re.compile(
    r"(?:^|[|&;(]\s*|\b)(?:"
    + "|".join(re.escape(name) for name in _STDIN_INTERPRETERS)
    + r")(?:\.exe)?(?:\s+-\d+(?:\.\d+)?)?\s+-(?=\s|$|>|\||&|;|\))",
    re.IGNORECASE,
)

#: Перенаправлення виводу у файл: ``> name``, ``>> name``, ``2> name``,
#: ``&> name``. Сюди НЕ входять ``2>&1`` і ``&1`` — це не файли.
_REDIRECT_PATTERN = re.compile(
    r"(?<![0-9&])>>?\s*(?P<target>\"[^\"]+\"|'[^']+'|[^\s|&;<>()]+)",
)

#: Службові «файли», які не є справжніми: ``nul``, ``/dev/null``.
_NULL_TARGETS = {"nul", "/dev/null", "$null", "nul:"}


@dataclass(frozen=True)
class RedirectRisk:
    """Одне перенаправлення у файл, яке варто перевірити."""

    #: Куди пише команда (як написано в команді).
    target: str
    #: Чи файл уже існує й скільки він важить.
    exists: bool
    size_bytes: int
    #: Чи це дописування (``>>``), а не перезапис.
    append: bool

    @property
    def megabytes(self) -> float:
        return round(self.size_bytes / (1024 ** 2), 1)

    def oversized(self, limit: int = MAX_REDIRECT_BYTES) -> bool:
        return self.size_bytes > limit


def input_trap(command: str) -> bool:
    """Чи команда чекатиме на ввід, якого ніхто не надішле.

    Перевіряються дві форми:

    * інтерпретатор із ``-`` (читає скрипт зі stdin) — але скрипт лежить
      у тексті КОМАНДИ, а не в stdin;
    * інтерактивна команда (``pause``, ``more``, ``timeout /t``…), яка без
      вводу просто висить.
    """
    text = _command_head(command)
    if not text:
        return False
    if _STDIN_PATTERN.search(text):
        # ``python -`` із переданим ввідом через ``echo … |`` — це вже
        # легітимно: дані прийдуть у stdin.
        if "|" not in text.split("-", 1)[0]:
            return True
    low = text.lower()
    for marker in _INTERACTIVE_COMMANDS:
        if marker in low:
            return True
    return False


def input_hint(command: str) -> str:
    """Пояснення моделі, ЩО зробити замість команди-пастки.

    Порожній рядок — пастки немає. Текст для моделі: він мусить підказати
    ІНШУ дію, щоб та не повторила те саме.
    """
    if not input_trap(command):
        return ""
    if _STDIN_PATTERN.search(_command_head(command)):
        return (
            "УВАГА: команда просить інтерпретатор читати скрипт зі СТАНДАРТНОГО "
            "ВВОДУ (`python -`), але код передано не в ввід, а в текст команди. "
            "Інтерпретатор не отримає скрипта, вийде в інтерактивний режим і "
            "чекатиме на ввід — команда висне, поки її не зупинять.\n"
            "Що зробити: запиши скрипт у файл через `write_file` (напр. "
            "`tools/my_script.py`) і запусти `python tools/my_script.py`. "
            "Або передай код у ввід: `echo <код> | python -`. "
            "Не повторюй ту саму команду — результат не зміниться.")
    return (
        "УВАГА: команда чекає на ввід користувача (пауза / гортання / "
        "очікування), а надсилати його нікому — вона висне до таймауту.\n"
        "Що зробити: прибери інтерактивну частину або передай дані "
        "аргументом чи через `|`. Не повторюй ту саму команду.")


def redirect_targets(command: str) -> list[tuple[str, bool]]:
    """Файли, у які команда перенаправляє вивід. [(ціль, чи_дописування)]."""
    found: list[tuple[str, bool]] = []
    for match in _REDIRECT_PATTERN.finditer(command or ""):
        target = match.group("target").strip()
        if len(target) >= 2 and target[0] == target[-1] and target[0] in "\"'":
            target = target[1:-1]
        if not target or target.lower() in _NULL_TARGETS:
            continue
        # ``2>&1`` уже відсіяно в регулярці, але ``>&2`` теж не файл.
        if target.startswith("&") or re.fullmatch(r"\d", target):
            continue
        append = match.group(0).lstrip().startswith(">>")
        found.append((target, append))
    return found


def redirect_risk(command: str, root: Optional[object] = None,
                  *, limit: int = MAX_REDIRECT_BYTES) -> Optional[RedirectRisk]:
    """Файл, у який команда перенаправляє вивід (None — таких немає).

    Повертає ризик і для БЕЗПЕЧНОГО (малого) файлу теж: виклик сам вирішує,
    чи блокувати (``oversized()``) чи лише повідомити розмір після роботи.
    ``None`` означає «перенаправлень у справжні файли немає взагалі»
    (``> nul``, ``2>&1``, порожня команда).

    ``root`` — робоча тека: відносний шлях рахуємо від неї.
    """
    targets = redirect_targets(command)
    if not targets:
        return None
    first: Optional[RedirectRisk] = None
    for target, append in targets:
        path = _resolve(target, root)
        if path is None:
            # Не вдалось розібрати шлях (напр. ``%TEMP%\x``) — вважаємо
            # невідомим: перенаправлення є, розмір не знаємо.
            risk = RedirectRisk(target=target, exists=False, size_bytes=0,
                                append=append)
        else:
            try:
                exists = path.exists()
                size = path.stat().st_size if exists and path.is_file() else 0
            except OSError:
                exists, size = False, 0
            risk = RedirectRisk(target=str(path), exists=exists,
                                size_bytes=size, append=append)
        # Завеликий файл — це вже привід блокувати, шукати далі не треба.
        if risk.oversized(limit):
            return risk
        if first is None:
            first = risk
    return first


def redirect_hint(risk: RedirectRisk, *, limit: int = MAX_REDIRECT_BYTES) -> str:
    """Пояснення для моделі: файл уже завеликий / ростиме без стелі."""
    if risk.oversized(limit):
        return (
            f"УВАГА: файл `{risk.target}` уже займає {risk.megabytes} МБ "
            f"(межа {round(limit / (1024 ** 2))} МБ). Запис у нього заблоковано, "
            "щоб не зайняти диск.\n"
            "Що зробити: видали файл (або напиши в інший), і не спрямовуй "
            "вивід команди, яка може працювати довго чи циклічно. Для "
            "перевірки достатньо перших рядків виводу — не перенаправляй "
            "його у файл.")
    return (
        f"УВАГА: вивід спрямовано у файл `{risk.target}`. Якщо команда "
        f"зациклиться або чекатиме на ввід, файл ростиме без обмежень "
        f"(межа {round(limit / (1024 ** 2))} МБ).\n"
        "Що зробити: спершу переконайся, що команда завершується сама. "
        "Не спрямовуй у файл інтерактивні команди й ті, що читають stdin.")


# ── внутрішнє ───────────────────────────────────────────────────────────────
def _command_head(command: str) -> str:
    """Перший рядок команди без хвоста-скрипта.

    Модель часто пише ``python - > out.txt \\n import sys …``. Для аналізу
    важливий саме ПЕРШИЙ рядок: решта — це код, а не команда оболонки.
    """
    clean = (command or "").strip()
    if not clean:
        return ""
    return clean.splitlines()[0].strip()


def _resolve(target: str, root: Optional[object]):
    """Шлях цілі перенаправлення (None — не вдалось обчислити)."""
    from pathlib import Path

    text = str(target or "").strip().strip('"').strip("'")
    if not text:
        return None
    if "$" in text or "%" in text:
        # Змінні середовища/підстановки — не розбираємо, вважаємо невідомим.
        return None
    try:
        path = Path(text)
        if not path.is_absolute():
            base = Path(str(root)) if root is not None else Path.cwd()
            path = base / path
        return path
    except (OSError, ValueError, TypeError):
        return None
