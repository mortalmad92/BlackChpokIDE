"""Перевірка й доустановка середовища: пакети Python і зовнішні програми.

Ідея: перший запуск не має перетворюватись на «постав це сам». Модуль знає,
що саме потрібно IDE, перевіряє наявність і вміє поставити відсутнє:

* **пакети Python** — ставляться в поточне інтерпретаторське середовище через
  ``pip install`` (у .exe pip немає, тоді чесно кажемо «недоступно»);
* **зовнішні програми** (``git``, ``node``, ``npm``) — спершу ``winget``;
  якщо його немає або він відмовив, відкриваємо сторінку завантаження
  **у вбудованому браузері** (не в браузері користувача).

Модуль не тягне tkinter: він повертає стан і вміє кликати колбек прогресу.
Завдяки цьому логіку перевіряють тести без вікна.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

LOG = logging.getLogger("blackchpok.env")

#: Стани елемента середовища.
STATE_OK = "є"
STATE_MISSING = "немає"
STATE_OPTIONAL = "необов'язково"
STATE_UNKNOWN = "невідомо"

#: Скільки чекати на ``pip install`` (перша установка колес буває довгою).
PIP_TIMEOUT = 900
#: Скільки чекати на ``winget install``.
WINGET_TIMEOUT = 900

#: Прапорці, з якими запускаємо підпроцеси без вікна консолі.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class Requirement:
    """Один пакет Python, потрібний IDE."""

    #: Ім'я для pip (``python-docx``).
    package: str
    #: Модуль для імпорту (``docx``) — так перевіряємо реальну наявність.
    module: str
    #: Що втрачається без нього.
    purpose: str
    #: Без нього IDE не запуститься зовсім.
    required: bool = True
    #: Версія для показу (не для встановлення — ставимо останню сумісну).
    version: str = ""

    @property
    def label(self) -> str:
        return f"{self.package} {self.version}".strip()


@dataclass
class Tool:
    """Зовнішня програма (не пакет Python)."""

    #: Ім'я виконуваного файлу для ``shutil.which``.
    exe: str
    #: Людська назва.
    label: str
    #: Що без неї не працює.
    purpose: str
    #: Ідентифікатор пакета winget.
    winget_id: str = ""
    #: Сторінка завантаження (відкривається у вбудованому браузері).
    download_url: str = ""
    #: Без неї IDE все одно працює.
    optional: bool = True


@dataclass
class ItemState:
    """Стан одного елемента середовища (пакета або програми)."""

    key: str
    label: str
    purpose: str
    state: str = STATE_UNKNOWN
    detail: str = ""
    required: bool = True
    #: Чим ставити: ``pip``, ``winget`` або ``url`` (лише сторінка).
    install_kind: str = ""
    #: Аргументи для встановлення (pip-специфікація або winget-id).
    install_target: str = ""
    #: Сторінка завантаження для запасного шляху.
    download_url: str = ""

    @property
    def ok(self) -> bool:
        return self.state == STATE_OK

    @property
    def actionable(self) -> bool:
        """Чи можна щось зробити (поставити або відкрити сторінку)."""
        if self.ok:
            return False
        return bool(self.install_kind or self.download_url)

    def describe(self) -> str:
        parts = [self.label]
        if self.detail:
            parts.append(self.detail)
        return " · ".join(parts)


# ── Що саме потрібно IDE ───────────────────────────────────────────────────

#: Бібліотеки Python. Порядок — від найважливіших.
REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement("openai", "openai", "зв'язок із моделлю (OpenAI-сумісний API)",
                required=True),
    Requirement("mcp", "mcp", "MCP-сервери та їхні інструменти", required=True),
    Requirement("pypdf", "pypdf", "читання PDF у контексті", required=False),
    Requirement("python-docx", "docx", "читання .docx у контексті", required=False),
    Requirement("pymupdf", "pymupdf", "швидке читання PDF і рендер сторінок",
                required=False),
    Requirement("ollama", "ollama", "робота з локальним Ollama", required=False),
    Requirement("numpy", "numpy", "векторний пошук RAG", required=False),
    Requirement("pillow", "PIL", "скріншоти застосунку в чаті", required=False),
    Requirement("pygments", "pygments", "розширена підсвітка синтаксису",
                required=False),
)

#: Зовнішні програми.
TOOLS: tuple[Tool, ...] = (
    Tool("git", "Git", "історія комітів і точний diff",
         winget_id="Git.Git", download_url="https://git-scm.com/download/win"),
    Tool("node", "Node.js", "запуск Node.js-проєктів у живому прев'ю",
         winget_id="OpenJS.NodeJS.LTS", download_url="https://nodejs.org/uk/download"),
    Tool("npm", "npm", "менеджер пакетів для Node.js-проєктів",
         winget_id="", download_url="https://nodejs.org/uk/download"),
)

#: Мінімальна версія Python, з якою працює проєкт.
MIN_PYTHON = (3, 11)


# ── Перевірка ──────────────────────────────────────────────────────────────

def python_version_text() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def python_ok() -> bool:
    return sys.version_info[:2] >= MIN_PYTHON


def module_available(module: str) -> bool:
    """Чи можна імпортувати модуль (без виконання важкого коду)."""
    name = (module or "").strip()
    if not name:
        return False
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, AttributeError):
        # ``find_spec`` може кинути на зламаному пакеті — тоді вважаємо,
        # що його немає, і пропонуємо переустановку.
        return False


def tool_available(exe: str) -> bool:
    return bool(shutil.which(exe))


def pip_available() -> bool:
    """Чи можна взагалі ставити пакети в цьому середовищі.

    У зібраному .exe pip немає — там пакети вже всередині архіву, і чесна
    відповідь «недоступно» краща за спробу запустити неіснуючий модуль.
    """
    if getattr(sys, "frozen", False):
        return False
    try:
        import importlib.util

        return importlib.util.find_spec("pip") is not None
    except (ImportError, ValueError):
        return False


def winget_available() -> bool:
    return bool(shutil.which("winget"))


def check_requirements(
    *,
    requirements: Iterable[Requirement] = REQUIREMENTS,
) -> list[ItemState]:
    """Перевірити всі пакети Python."""
    can_install = pip_available()
    rows: list[ItemState] = []
    for req in requirements:
        present = module_available(req.module)
        rows.append(ItemState(
            key=req.package,
            label=req.label,
            purpose=req.purpose,
            state=STATE_OK if present else (
                STATE_MISSING if req.required else STATE_OPTIONAL),
            detail="" if present else ("відсутній" if req.required else "не встановлено"),
            required=req.required,
            install_kind="pip" if (not present and can_install) else "",
            install_target=req.package,
        ))
    return rows


def check_tools(*, tools: Iterable[Tool] = TOOLS) -> list[ItemState]:
    """Перевірити зовнішні програми."""
    can_winget = winget_available()
    rows: list[ItemState] = []
    for tool in tools:
        present = tool_available(tool.exe)
        rows.append(ItemState(
            key=tool.exe,
            label=tool.label,
            purpose=tool.purpose,
            state=STATE_OK if present else (
                STATE_OPTIONAL if tool.optional else STATE_MISSING),
            detail="" if present else "не знайдено в PATH",
            required=not tool.optional,
            install_kind="winget" if (not present and can_winget and tool.winget_id) else "",
            install_target=tool.winget_id,
            download_url=tool.download_url,
        ))
    return rows


def check_all() -> list[ItemState]:
    """Повний зріз: пакети й програми."""
    return check_requirements() + check_tools()


def summary(rows: Iterable[ItemState]) -> dict[str, int]:
    """Скільки чого (для заголовка майстра)."""
    result = {"ok": 0, "missing": 0, "optional": 0, "total": 0}
    for row in rows:
        result["total"] += 1
        if row.state == STATE_OK:
            result["ok"] += 1
        elif row.required:
            result["missing"] += 1
        else:
            result["optional"] += 1
    return result


def describe_problems(rows: Iterable[ItemState]) -> str:
    """Один рядок про те, чого бракує (або «усе на місці»)."""
    missing = [row.label for row in rows if row.state == STATE_MISSING]
    optional = [row.label for row in rows if row.state == STATE_OPTIONAL]
    if missing:
        return "Бракує: " + ", ".join(missing[:5])
    if optional:
        return ("Усе потрібне є. Необов'язкові, без них частина можливостей "
                "вимкнена: " + ", ".join(optional[:4]))
    return "Усі бібліотеки й програми на місці."


# ── Встановлення ───────────────────────────────────────────────────────────

@dataclass
class StepResult:
    """Результат однієї установки."""

    key: str
    ok: bool = False
    message: str = ""
    output: str = ""
    #: True, якщо замість тихої установки відкрили сторінку завантаження.
    opened_page: bool = False


def _run(command: list[str], *, timeout: int) -> tuple[int, str]:
    """Виконати команду й повернути (код, вивід). Помилки — у вивід."""
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return -1, f"Перевищено час очікування ({timeout} с)."
    except FileNotFoundError:
        return -1, f"Команду не знайдено: {command[0]}"
    except OSError as exc:
        return -1, str(exc)
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return int(proc.returncode), output


def install_package(
    package: str,
    *,
    on_status: Optional[Callable[[str], None]] = None,
) -> StepResult:
    """Поставити пакет Python через ``pip install``."""
    clean = (package or "").strip()
    if not clean:
        return StepResult(clean, False, "Порожнє ім'я пакета.")
    if not pip_available():
        return StepResult(
            clean, False,
            "pip недоступний у цьому середовищі — встанови пакет вручну "
            "або запусти IDE з коду з .venv.")
    _status(on_status, f"Встановлюю {clean}…")
    code, output = _run(
        [sys.executable, "-m", "pip", "install", "--upgrade", clean],
        timeout=PIP_TIMEOUT)
    if code == 0:
        # Перевіряємо саме імпорт: pip міг «успішно» нічого не зробити,
        # якщо пакет уже стоїть у непридатному стані.
        return StepResult(clean, True, f"{clean}: встановлено.", output)
    tail = output[-400:] if output else "без виводу"
    return StepResult(clean, False, f"{clean}: не вдалось поставити. {tail}", output)


def install_tool_with_winget(
    winget_id: str,
    *,
    label: str = "",
    on_status: Optional[Callable[[str], None]] = None,
) -> StepResult:
    """Поставити програму через ``winget install``."""
    clean = (winget_id or "").strip()
    name = label or clean
    if not clean:
        return StepResult(clean, False, "Немає ідентифікатора winget.")
    if not winget_available():
        return StepResult(clean, False, "winget недоступний у цій системі.")
    _status(on_status, f"Встановлюю {name} через winget…")
    code, output = _run(
        ["winget", "install", "--id", clean, "--exact", "--silent",
         "--accept-package-agreements", "--accept-source-agreements"],
        timeout=WINGET_TIMEOUT)
    if code == 0:
        return StepResult(clean, True, f"{name}: встановлено через winget.", output)
    # 0x8A150061 = «вже встановлено»: це не помилка для користувача.
    low = (output or "").lower()
    if "уже установлен" in low or "already installed" in low:
        return StepResult(clean, True, f"{name}: уже встановлено.", output)
    tail = output[-400:] if output else "без виводу"
    return StepResult(clean, False, f"{name}: winget не впорався. {tail}", output)


def _status(callback: Optional[Callable[[str], None]], text: str) -> None:
    if callback is None:
        return
    try:
        callback(text)
    except Exception:  # noqa: BLE001 - прогрес не має ламати установку
        LOG.debug("Колбек прогресу впав", exc_info=True)


def install_item(
    item: ItemState,
    *,
    on_status: Optional[Callable[[str], None]] = None,
) -> StepResult:
    """Поставити один елемент найкращим доступним способом.

    Порядок: ``pip`` → ``winget`` → сторінка завантаження у вбудованому
    браузері. Останній крок не «тиха установка», але він завжди працює й
    не лишає користувача з порожнім екраном.
    """
    if item.ok:
        return StepResult(item.key, True, f"{item.label}: уже є.")
    if item.install_kind == "pip":
        result = install_package(item.install_target or item.key, on_status=on_status)
        if result.ok:
            return result
        # pip не зміг — лишається сторінка, якщо вона є.
        if item.download_url and _open_page(item.download_url, on_status):
            result.opened_page = True
            result.message += " Відкрив сторінку завантаження."
        return result
    if item.install_kind == "winget":
        result = install_tool_with_winget(item.install_target, label=item.label,
                                          on_status=on_status)
        if result.ok:
            return result
        if item.download_url and _open_page(item.download_url, on_status):
            result.opened_page = True
            result.message += " Відкрив сторінку завантаження у вбудованому браузері."
        return result
    if item.download_url and _open_page(item.download_url, on_status):
        return StepResult(item.key, False,
                          f"{item.label}: відкрито сторінку завантаження. "
                          f"Встанови програму й натисни «Перевірити».",
                          opened_page=True)
    return StepResult(item.key, False, f"{item.label}: немає способу встановити автоматично.")


def _open_page(url: str, on_status: Optional[Callable[[str], None]]) -> bool:
    """Показати сторінку у ВБУДОВАНОМУ браузері IDE.

    Використовуємо спільний відкривач із :mod:`browser_panel` — саме він
    гарантує, що системний браузер не відкриється.
    """
    from . import browser_panel

    _status(on_status, f"Відкриваю у вбудованому браузері: {url}")
    return browser_panel.open_url(url)


def install_missing(
    rows: Iterable[ItemState],
    *,
    on_status: Optional[Callable[[str], None]] = None,
    on_step: Optional[Callable[[ItemState, StepResult], None]] = None,
    only_required: bool = False,
) -> list[StepResult]:
    """Поставити все, чого бракує (послідовно).

    ``only_required=True`` ставить лише те, без чого IDE не працює —
    користувач може не хотіти тягнути опційні бібліотеки.
    """
    results: list[StepResult] = []
    for item in rows:
        if item.ok:
            continue
        if only_required and not item.required:
            continue
        result = install_item(item, on_status=on_status)
        results.append(result)
        if on_step is not None:
            try:
                on_step(item, result)
            except Exception:  # noqa: BLE001 - показ результату не має ламати цикл
                LOG.debug("on_step упав", exc_info=True)
    return results


def reload_path() -> None:
    """Оновити ``PATH`` із реєстру Windows після встановлення програм.

    ``winget`` дописує шляхи в системний PATH, але поточний процес бачить
    стару копію — без цього щойно встановлений git «не знаходиться», і
    користувач бачить «не встановлено» одразу після установки.
    """
    if os.name != "nt":
        return
    try:
        import winreg
    except ImportError:  # pragma: no cover - не Windows
        return
    parts: list[str] = [os.environ.get("PATH", "")]
    for root, subkey in (
        (winreg.HKEY_LOCAL_MACHINE,
         r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        (winreg.HKEY_CURRENT_USER, r"Environment"),
    ):
        try:
            with winreg.OpenKey(root, subkey) as key:
                value, _kind = winreg.QueryValueEx(key, "Path")
                if value:
                    parts.append(str(value))
        except OSError:
            continue
    merged: list[str] = []
    seen: set[str] = set()
    for chunk in parts:
        for piece in str(chunk or "").split(os.pathsep):
            item = piece.strip()
            if not item or item.lower() in seen:
                continue
            seen.add(item.lower())
            merged.append(item)
    if merged:
        os.environ["PATH"] = os.pathsep.join(merged)


def refresh_states() -> list[ItemState]:
    """Перевірити все заново (після установки)."""
    reload_path()
    return check_all()


__all__ = [
    "ItemState",
    "MIN_PYTHON",
    "PIP_TIMEOUT",
    "REQUIREMENTS",
    "Requirement",
    "STATE_MISSING",
    "STATE_OK",
    "STATE_OPTIONAL",
    "STATE_UNKNOWN",
    "StepResult",
    "TOOLS",
    "Tool",
    "WINGET_TIMEOUT",
    "check_all",
    "check_requirements",
    "check_tools",
    "describe_problems",
    "install_item",
    "install_missing",
    "install_package",
    "install_tool_with_winget",
    "module_available",
    "pip_available",
    "python_ok",
    "python_version_text",
    "refresh_states",
    "reload_path",
    "summary",
    "tool_available",
    "winget_available",
]
