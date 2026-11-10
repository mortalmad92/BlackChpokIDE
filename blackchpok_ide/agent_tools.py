"""Інструменти агента: читання, запис, пошук, термінал, git.

Кожен інструмент — це чиста функція над робочою текою. Схеми описані окремо
у ``TOOL_SCHEMAS`` і передаються моделі у форматі OpenAI function calling.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import app_control
from . import imaging
from . import internet
from . import multiscale
from . import workspace as ws

LOG = logging.getLogger("blackchpok.tools")


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: str

    def as_text(self) -> str:
        return self.output


class ToolError(RuntimeError):
    """Помилка виконання інструмента (її бачить модель)."""


def memory_tool_schemas() -> list[dict[str, Any]]:
    """Схеми інструментів пам'яті NEUROMESH.

    Імпорт усередині функції: пакет ``pcmm`` тягне SQLite-сховище, і
    тягнути його під час імпорту реєстру немає сенсу — він потрібен лише
    тоді, коли пам'ять справді підключена.
    """
    from .pcmm.tools import MEMORY_TOOL_SCHEMAS

    return [dict(schema) for schema in MEMORY_TOOL_SCHEMAS]


def _memory_handler_for(tools: Any, name: str) -> Callable[..., str]:
    """Обгортка, яка проводить виклик через валідацію ``MemoryTools.call``.

    Реєстр передає аргументи як іменовані параметри, а ``call`` приймає
    словник — тому збираємо їх назад. Так схема лишається єдиним
    джерелом істини для аргументів.
    """

    def handler(**kwargs: Any) -> str:
        return tools.call(name, kwargs)

    handler.__name__ = name
    return handler


def _format_element(info: dict[str, Any]) -> str:
    """Елемент сторінки у вигляді, зручному моделі й людині.

    Модель має дізнатись із цього тексту, ЯКИЙ рядок коду змінити: тому
    першими йдуть селектор, класи й обчислені стилі, а не сирий JSON.
    """
    tag = info.get("tag") or "?"
    ident = f"#{info['id']}" if info.get("id") else ""
    classes = info.get("classes") or []
    class_text = "." + ".".join(str(name) for name in classes) if classes else ""
    rect = info.get("rect") or {}
    styles = info.get("styles") or {}
    parts = [f"Елемент: <{tag}{ident}{class_text}>"]
    selector = str(info.get("selector") or "")
    if selector:
        parts.append(f"CSS-селектор: {selector}")
    if info.get("text"):
        parts.append(f"Текст: {str(info['text'])[:160]}")
    if rect:
        parts.append("Розмір: {w}×{h} px, позиція ({x}, {y})".format(
            w=rect.get("width", "?"), h=rect.get("height", "?"),
            x=rect.get("x", "?"), y=rect.get("y", "?")))
    if styles:
        keys = ("display", "position", "color", "backgroundColor", "fontSize",
                "fontWeight", "margin", "padding", "borderRadius", "gap",
                "flexDirection", "opacity")
        shown = [f"{key}={styles[key]}" for key in keys
                 if styles.get(key) not in (None, "")]
        if shown:
            parts.append("Стилі: " + "; ".join(shown))
    attributes = info.get("attributes") or {}
    if attributes:
        shown_attrs = "; ".join(f'{name}="{value}"'
                                for name, value in list(attributes.items())[:8])
        parts.append(f"Атрибути: {shown_attrs}")
    if info.get("parent"):
        parts.append(f"Батько: <{info['parent']}>")
    if info.get("stylesheets"):
        parts.append(f"Таблиці стилів: {info['stylesheets']}")
    if info.get("pageUrl"):
        parts.append(f"Сторінка: {info['pageUrl']}")
    return "\n".join(parts)


def _format_audit(report: dict[str, Any]) -> str:
    """Звіт про перевірку сторінки: коротко, з конкретними проблемами."""
    counts = report.get("counts") or {}
    problems = report.get("problems") or {}
    lines = [
        f"Сторінка: {report.get('title') or '—'}",
        f"Адреса: {report.get('url') or '—'}",
        "Знайдено: {} посилань, {} кнопок, {} форм, {} зображень, {} заголовків".format(
            counts.get("links", 0), counts.get("buttons", 0),
            counts.get("forms", 0), counts.get("images", 0),
            counts.get("headings", 0)),
    ]
    titles = {
        "links": "Посилання",
        "buttons": "Кнопки",
        "forms": "Форми",
        "images": "Зображення",
        "headings": "Заголовки",
        "a11y": "Доступність",
    }
    total = 0
    for key, title in titles.items():
        rows = problems.get(key) or []
        if not rows:
            continue
        total += len(rows)
        lines.append(f"\n{title}:")
        for row in rows[:8]:
            if not isinstance(row, dict):
                continue
            target = row.get("text") or row.get("src") or row.get("tag") or ""
            lines.append(f"  · {row.get('issue', 'проблема')}"
                         + (f" — {target}" if target else ""))
        if len(rows) > 8:
            lines.append(f"  … ще {len(rows) - 8}")
    if not total:
        lines.append("\nПроблем не знайдено.")
    return "\n".join(lines)


def _parse_sizes(raw: str) -> list[tuple[int, int]]:
    """Розібрати ``"375x667,1280x800"`` у список розмірів (тихо)."""
    sizes: list[tuple[int, int]] = []
    for chunk in str(raw or "").replace(";", ",").split(","):
        piece = chunk.strip().lower().replace("×", "x").replace("*", "x")
        if not piece:
            continue
        left, _, right = piece.partition("x")
        try:
            width, height = int(left), int(right)
        except ValueError:
            continue
        if 120 <= width <= 8000 and 120 <= height <= 8000:
            sizes.append((width, height))
    return sizes


def _syntax_issue(target: Path, body: str) -> str:
    """Перевірити синтаксис Python-файлу, який збираємось записати.

    Повертає короткий опис помилки або порожній рядок. Для інших мов
    (js, html, json…) перевірки немає — тоді теж порожній рядок.

    Навіщо: локальні моделі регулярно пишуть ``input('ім'я: ')`` —
    апостроф усередині одинарних лапок. Файл записується, «успіх»
    звітується, а програма не запускається зовсім. Перевірка тут дає
    моделі шанс виправити це наступним кроком, а користувачу — побачити
    причину, а не порожній екран.
    """
    if target.suffix.lower() not in (".py", ".pyw", ".pyi"):
        return ""
    # JSON перевіряємо окремо: він теж часто генерується моделлю.
    try:
        compile(body, str(target), "exec", dont_inherit=True)
    except SyntaxError as exc:
        line = exc.lineno or 0
        text = (exc.text or "").strip()
        where = f"рядок {line}" + (f": {text[:80]}" if text else "")
        return f"{exc.msg} ({where})"
    except (ValueError, TypeError) as exc:
        return f"{type(exc).__name__}: {exc}"
    return ""


def _json_issue(target: Path, body: str) -> str:
    """Перевірити JSON-файл перед записом (часта помилка моделі — кома)."""
    if target.suffix.lower() != ".json":
        return ""
    import json

    try:
        json.loads(body)
    except json.JSONDecodeError as exc:
        return f"{exc.msg} (рядок {exc.lineno}, стовпець {exc.colno})"
    return ""


def _fuzzy_fragment(content: str, wanted: str) -> tuple[str, str] | None:
    """Знайти фрагмент, що майже збігається, і повернути РЕАЛЬНИЙ текст.

    Локальні моделі майже ніколи не відтворюють фрагмент точно: міняють
    одинарні лапки на подвійні, зсувають відступи, додають пробіли в кінці
    рядків. Раніше це зривало правку, і агент переписував файл цілком —
    а це ризик втратити код, якого він не бачив.

    Порівнюємо за «скелетом» рядка: без пробілів і без лапок. Перший
    знайдений збіг повертаємо разом із ТОЧНИМ текстом із файлу — далі
    заміна йде як звичайна точна.
    """
    if not wanted.strip():
        return None

    def skeleton(text: str) -> str:
        flat = re.sub(r"\s+", "", text)
        flat = flat.replace('"', "'")
        flat = flat.replace("’", "'").replace("`", "'")
        return flat

    target_key = skeleton(wanted)
    if len(target_key) < 8:
        return None            # закоротко: легко зачепити чуже
    lines = content.splitlines(keepends=True)
    wanted_lines = wanted.splitlines()
    if not wanted_lines:
        return None
    span = len(wanted_lines)
    # Ковзаємо вікном по файлу й порівнюємо скелет вікна зі скелетом запиту.
    for start in range(0, max(1, len(lines) - span + 1)):
        window = "".join(lines[start:start + span])
        if skeleton(window) == target_key:
            return window, wanted
    # Один рядок — шукаємо серед рядків окремо (частий випадок правки).
    if span == 1:
        for line in lines:
            if skeleton(line) == target_key:
                return line, wanted
    return None


class ToolRegistry:
    """Реєстр інструментів з обмеженням робочої теки."""

    def __init__(self, root: Path, *, confirm_commands: bool = False) -> None:
        self.root = Path(root).resolve()
        self.confirm_commands = confirm_commands
        self.command_guard: Callable[[str], bool] | None = None
        self._handlers: dict[str, Callable[..., str]] = {
            "read_file": self.read_file,
            "write_file": self.write_file,
            "edit_file": self.edit_file,
            "append_file": self.append_file,
            "list_dir": self.list_dir,
            "search_text": self.search_text,
            "find_files": self.find_files,
            "run_command": self.run_command,
            "git_status": self.git_status,
            "git_diff": self.git_diff,
            "project_tree": self.project_tree,
            "python_check": self.python_check,
            # Живе тестування застосунку проєкту (прив'язується вікном).
            "app_start": self.app_start,
            "app_stop": self.app_stop,
            "app_restart": self.app_restart,
            "app_status": self.app_status,
            "app_screenshot": self.app_screenshot,
            "project_screenshot": self.project_screenshot,
            # ── інтернет (завжди доступний, без MCP)
            "search_web": self.search_web,
            "fetch_url": self.fetch_url,
            "web_api": self.web_api,
            "web_open": self.web_open,
            "internet_status": self.internet_status,
            "app_windows": self.app_windows,
            "window_screenshot": self.window_screenshot,
            "app_logs": self.app_logs,
            "app_click": self.app_click,
            "app_type": self.app_type,
            "app_key": self.app_key,
            # ── живий браузер (CDP): сторінка як дані
            "web_url": self.web_url,
            "web_console": self.web_console,
            "web_inspect": self.web_inspect,
            "web_screenshot": self.web_screenshot,
            "web_audit": self.web_audit,
            "web_responsive": self.web_responsive,
            "web_click": self.web_click,
            "web_type": self.web_type,
            # ── DOM-міст Live Preview (структура сторінки як дані)
            "dom_tree": self.dom_tree,
            "dom_find_text": self.dom_find_text,
            "dom_styles": self.dom_styles,
            "dom_console": self.dom_console,
            # ── візуальні інструменти (робота із зображеннями як з даними)
            "capture_screen": self.capture_screen,
            "capture_region": self.capture_region,
            "crop_screenshot": self.crop_screenshot,
            "get_image_dimensions": self.get_image_dimensions,
            "get_screenshot_metadata": self.get_screenshot_metadata,
            "inspect_screenshot_regions": self.inspect_screenshot_regions,
            "compare_screenshots": self.compare_screenshots,
            "analyze_visual_difference": self.analyze_visual_difference,
            "list_screenshots": self.list_screenshots,
        }

    # ── прив'язка керування застосунком ────────────────────────────────────
    def attach_app_controller(self, controller) -> None:
        """Підключити :class:`app_control.AppController` вікна IDE.

        До прив'язки live-інструменти чесно відповідають, що керування
        застосунком ще не підключене (агент не має вигадувати стан).
        """
        self.app_controller = controller

    def attach_cdp_provider(self, provider) -> None:
        """Підключити постачальник CDP-сесії вбудованого браузера.

        ``provider`` — функція без аргументів, яка повертає
        :class:`cdp.CdpSession` або ``None``. Поки її немає, web-інструменти
        чесно кажуть, що сторінка недоступна — жодних вигаданих відповідей.
        """
        self.cdp_provider = provider

    def attach_browser_hwnd_provider(self, provider) -> None:
        """Підключити постачальник HWND вбудованого браузера.

        ``provider`` повертає дескриптор вікна Chromium, вставленого в IDE.
        Потрібен для ``project_screenshot``: знімок робиться САМЕ цього
        вікна, а не «першого-ліпшого Chrome» на машині (саме через це в
        чаті користувача з'являлось чуже темне вікно).
        """
        self.browser_hwnd_provider = provider

    def attach_page_opener(self, opener) -> None:
        """Підключити відкриття сторінки у вбудованому браузері.

        ``opener`` — функція ``(url) -> bool``, яку надає вікно IDE. Вона
        показує сторінку в панелі «Сайт» і повертає ``True``, якщо це
        вдалось.

        Навіщо окремий інструмент, а не лише ``fetch_url``: користувач
        просив, щоб агент «сам міг відкрити посилання і показати, де він
        знайшов інформацію». ``fetch_url`` лише ЧИТАЄ сторінку — людина
        її не бачить. ``web_open`` показує.
        """
        self.page_opener = opener

    def attach_memory(self, service) -> None:
        """Підключити пам'ять NEUROMESH (інструменти ``memory_*``).

        Реєстр не створює пам'ять сам: її життєвий цикл належить вікну IDE.
        До прив'язки інструментів ``memory_*`` просто немає, тож агент не
        може «викликати» те, чого немає, і не отримує фальшивих відповідей.
        """
        from .pcmm.tools import MemoryTools

        self.memory_service = service
        self.memory_tools = MemoryTools(service)
        # Реєстр викликає обробник напряму, тому аргументи перевіряє саме
        # ``MemoryTools.call``: без цього ``memory_search(limit=999)`` тихо
        # проходив би повз схему й показував моделі «все гаразд».
        for name in self.memory_tools.names:
            self._handlers[name] = _memory_handler_for(self.memory_tools, name)
        self._memory_schemas: list[dict[str, Any]] = memory_tool_schemas()
        LOG.info("Пам'ять NEUROMESH підключено: %d інструментів",
                 len(self.memory_tools.names))

    def detach_memory(self) -> None:
        """Відключити пам'ять (наприклад, при закритті бази)."""
        for name in list(getattr(self, "memory_tools", None).names
                         if getattr(self, "memory_tools", None) else []):
            self._handlers.pop(name, None)
        self.memory_tools = None
        self.memory_service = None
        self._memory_schemas = []

    def memory_schemas(self) -> list[dict[str, Any]]:
        """Схеми підключених інструментів пам'яті (порожньо, якщо немає)."""
        return list(getattr(self, "_memory_schemas", ()))

    def memory_ready(self) -> bool:
        return getattr(self, "memory_tools", None) is not None

    def tool_schemas(self) -> list[dict[str, Any]]:
        """Усі схеми цього реєстру: вбудовані + пам'ять."""
        return [*TOOL_SCHEMAS, *self.memory_schemas()]

    def _app(self):
        controller = getattr(self, "app_controller", None)
        if controller is None:
            raise ToolError(
                "Керування застосунком не підключене. Ці інструменти живуть "
                "у вікні IDE: запусти IDE, і вони запрацюють."
            )
        return controller

    # ── безпека ────────────────────────────────────────────────────────────
    def set_root(self, root: Path) -> None:
        self.root = Path(root).resolve()

    def resolve(self, relative: str) -> Path:
        return ws.safe_join(self.root, relative or ".")

    # ── інструменти ────────────────────────────────────────────────────────
    def read_file(self, path: str, start_line: int = 1, end_line: int = 0) -> str:
        target = self.resolve(path)
        content, _encoding = ws.read_text_file(target)
        lines = content.splitlines()
        rel = ws.relative_to_root(self.root, target)
        if not lines:
            return f"# {rel} (0 рядків)\n(файл порожній)"
        start = max(1, int(start_line or 1))
        end = int(end_line or 0) or len(lines)
        end = min(end, len(lines))
        if start > len(lines):
            raise ToolError(f"У файлі лише {len(lines)} рядків, а запитано з {start}.")
        if start > end:
            raise ToolError(f"Порожній діапазон рядків: {start}–{end}")
        body = "\n".join(f"{n:>5} | {lines[n - 1]}" for n in range(start, end + 1))
        if end < len(lines):
            body += f"\n… (файл має {len(lines)} рядків, показано до {end})"
        return f"# {rel} ({len(lines)} рядків)\n{body}"

    def write_file(self, path: str, content: str) -> str:
        target = self.resolve(path)
        body = content or ""
        issue = _syntax_issue(target, body) or _json_issue(target, body)
        # ── Захист від втрати наявного вмісту ──────────────────────────────
        # Локальна модель часто перезаписує файл, коли просили ДОПИСАТИ:
        # у notes.txt із трьома рядками лишався один новий, і попередній
        # текст зникав без попередження (перевірено наживо).
        # Тут не блокуємо запис — модель може справді переписувати файл, —
        # але кажемо їй про це в результаті, щоб наступним кроком вона
        # дописала загублене, якщо його просили зберегти.
        lost = ""
        if target.exists() and target.is_file():
            try:
                previous = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                previous = ""
            if previous.strip() and len(previous) > len(body) + 40:
                lost = (f"\nУВАГА: попередній вміст файлу був довший "
                        f"({len(previous)} символів, тепер {len(body)}). "
                        "Якщо просили ДОПИСАТИ — прочитай файл і допиши "
                        "загублене через edit_file.")
        ws.write_text_file(target, body)
        rel = ws.relative_to_root(self.root, target)
        message = (f"Записано {rel} ({len(body)} символів, "
                   f"{len(body.splitlines())} рядків).")
        if lost:
            message += lost
        if issue:
            # Синтаксис перевіряємо ОДРАЗУ й кажемо про помилку в результаті:
            # інакше агент «успішно» створював файл, який не запускається, і
            # користувач отримував «воно не працює» без пояснень.
            # Файл усе одно записано — агент має бачити свій текст і
            # виправити його наступним кроком.
            message += f"\nУВАГА: синтаксична помилка — {issue}"
            message += "\nВиправ цей файл зараз же (edit_file або write_file)."
        return message

    def edit_file(self, path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
        target = self.resolve(path)
        content, _encoding = ws.read_text_file(target)
        if old_string == "":
            raise ToolError("old_string не може бути порожнім; для нового файлу використай write_file.")
        count = content.count(old_string)
        if count == 0:
            # Точний збіг не знайдено — пробуємо пробачити типові розбіжності
            # локальних моделей: інші лапки, інші відступи, зайві пробіли.
            # Раніше будь-яка така дрібниця зривала правку з «фрагмент не
            # знайдено», і агент змушений був переписувати файл цілком —
            # а це вже ризик втратити чужий код.
            matched = _fuzzy_fragment(content, old_string)
            if matched is None:
                raise ToolError(
                    f"Фрагмент не знайдено у {path}. Прочитай файл ще раз "
                    "і візьми точний текст (разом з відступами).")
            actual, old_string = matched
            count = content.count(actual)
            old_string = actual
        if count > 1 and not replace_all:
            raise ToolError(f"Фрагмент трапляється {count} разів. Уточни текст або постав replace_all=true.")
        updated = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)
        issue = _syntax_issue(target, updated) or _json_issue(target, updated)
        ws.write_text_file(target, updated)
        message = f"Оновлено {ws.relative_to_root(self.root, target)}: замін {count if replace_all else 1}."
        if issue:
            message += f"\nУВАГА: синтаксична помилка — {issue}"
            message += "\nВиправ цей файл зараз же."
        return message

    def append_file(self, path: str, content: str) -> str:
        """Дописати текст у КІНЕЦЬ файлу (не перезаписуючи наявне).

        Навіщо окремий інструмент: на прохання «додай у notes.txt рядок»
        локальна модель викликала ``write_file`` і затирала весь попередній
        вміст — файл із трьох рядків ставав одним (перевірено наживо).
        ``edit_file`` тут теж не годиться: він вимагає точний фрагмент, а
        для дописування його немає.
        """
        target = self.resolve(path)
        body = content or ""
        if not body.strip():
            # Пробіли й порожній рядок теж нічого не дописують — краще
            # сказати прямо, ніж створити порожній файл.
            raise ToolError("Порожній content: нічого дописувати.")
        previous = ""
        if target.exists() and target.is_file():
            try:
                previous = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                previous = ""
        # Додаємо перевід рядка, якщо попередній вміст не закінчувався ним:
        # інакше новий текст приклеювався б до останнього рядка.
        joiner = ""
        if previous and not previous.endswith("\n"):
            joiner = "\n"
        updated = previous + joiner + body
        if not updated.endswith("\n"):
            updated += "\n"
        issue = _syntax_issue(target, updated) or _json_issue(target, updated)
        ws.write_text_file(target, updated)
        rel = ws.relative_to_root(self.root, target)
        message = (f"Дописано в {rel} ({len(body)} символів). "
                   f"Тепер файл має {len(updated)} символів, "
                   f"{len(updated.splitlines())} рядків.")
        if issue:
            message += f"\nУВАГА: синтаксична помилка — {issue}"
            message += "\nВиправ цей файл зараз же."
        return message

    def list_dir(self, path: str = ".") -> str:
        """Показати вміст теки.

        Поряд з переліком даємо ГОТОВІ підсумки за типами. Причина
        конкретна: на запит «скільки Python-файлів?» модель отримувала
        118 рядків і все одно називала вигадане число (100, 170, 211 — у
        трьох послідовних прогонах). Порахувати рядки самостійно вона не
        може, тому кількість мусить бути в результаті інструмента, а не
        виводитись моделлю.

        Межа ``rows[:400]`` теж позначалася як «усього записів» — тепер
        видно і справжню кількість, і те, що список показано не повністю.
        """
        target = self.resolve(path)
        if not target.is_dir():
            raise ToolError(f"Не папка: {path}")
        rows: list[str] = []
        by_suffix: dict[str, int] = {}
        files = 0
        dirs = 0
        for entry in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if entry.is_dir():
                dirs += 1
                rows.append(f"{entry.name}/")
                continue
            files += 1
            suffix = entry.suffix.lower() or "(без розширення)"
            by_suffix[suffix] = by_suffix.get(suffix, 0) + 1
            try:
                size = entry.stat().st_size
            except OSError:
                size = 0
            rows.append(f"{entry.name}  ({size:,} B)")
        shown = rows[:400]
        head = (f"{ws.relative_to_root(self.root, target)} — {len(rows)} записів "
                f"(файлів {files}, тек {dirs})")
        # ── Готові підсумки за типами ──────────────────────────────────────
        # Це найважливіше для запитань «скільки X-файлів?»: модель бачить
        # точне число й не мусить рахувати рядки (вона цього не вміє).
        if by_suffix:
            top = sorted(by_suffix.items(), key=lambda item: (-item[1], item[0]))[:8]
            summary = ", ".join(f"{suffix}: {count}" for suffix, count in top)
            head += f"\nПідсумок за типами: {summary}"
        body = "\n".join(shown)
        if len(rows) > len(shown):
            body += (f"\n… показано {len(shown)} з {len(rows)} записів "
                     f"(решту видно через find_files або list_dir у підтеці)")
        return head + ("\n" + body if rows else "\n(порожньо)")

    def search_text(self, query: str, glob: str = "", regex: bool = False, case: bool = False, limit: int = 120) -> str:
        hits = ws.search_text(self.root, query, glob=glob, regex=regex, case=case, limit=min(int(limit or 120), 300))
        if not hits:
            return f"Нічого не знайдено за «{query}»."
        lines = [f"{ws.relative_to_root(self.root, hit.path)}:{hit.line}: {hit.text}" for hit in hits]
        return f"Знайдено {len(hits)} збігів:\n" + "\n".join(lines)

    def find_files(self, pattern: str, limit: int = 200, path: str = "") -> str:
        """Знайти файли за шаблоном.

        ВАЖЛИВО про ліміт. Раніше результат мовчки обрізався на ``limit``
        рядках, і модель вважала, що це ПОВНИЙ список: на запит «скільки
        Python-файлів?» вона отримувала рівно 200 рядків і назвала «211» —
        вигадане число, хоч доказ виглядав справжнім. Тепер:

        * ``path`` дозволяє звузити пошук до теки (``root`` більше не
          потрібен як невідомий аргумент — він і був причиною помилки
          «unexpected keyword argument»);
        * обрізання ЯВНО позначене в тексті й супроводжується справжньою
          кількістю знайдених файлів, тож модель не може вигадати число;
        * ``limit=0`` повертає всі збіги (з розумним запобіжником).
        """
        import fnmatch as _fnmatch

        wanted = max(0, int(limit or 200))
        base = self.root
        text = (path or "").strip()
        if text:
            try:
                base = self.resolve(text)
            except ToolError:
                base = self.root
        matches: list[str] = []
        total = 0
        # ``limit == 0`` — «покажи всі»: розумний запобіжник 2000 рядків,
        # щоб відповідь не вибухнула, але й не обрізалась на 200.
        full_scan = int(limit or 0) == 0
        hard_cap = 2000 if full_scan else wanted
        for item in ws.walk_text_files(base):
            rel = ws.relative_to_root(self.root, item)
            if not (_fnmatch.fnmatch(rel, pattern)
                    or _fnmatch.fnmatch(item.name, pattern)):
                continue
            total += 1
            if len(matches) < hard_cap:
                matches.append(rel)
        if not matches:
            where = f" у «{text}»" if text else ""
            return f"Файлів за шаблоном «{pattern}»{where} не знайдено."
        lines = list(matches)
        if total > len(matches):
            lines.append(
                f"… показано {len(matches)} з {total} збігів (ліміт {limit}). "
                f"Усього файлів за шаблоном «{pattern}»: {total}. "
                f"Щоб побачити всі, повтори з limit=0 або звузь path.")
        else:
            lines.append(f"— усього: {total}")
        return "\n".join(lines)

    def run_command(self, command: str, timeout: int = 120, cwd: str = "") -> str:
        if not (command or "").strip():
            raise ToolError("Порожня команда.")
        workdir = self.resolve(cwd or ".")
        if self.confirm_commands and self.command_guard and not self.command_guard(command):
            raise ToolError("Користувач відхилив виконання команди.")
        timeout = max(5, min(int(timeout or 120), 900))
        try:
            proc = subprocess.run(
                unwrap_shell_prefix(command),
                shell=True,
                cwd=str(workdir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=_shell_env(),
            )
        except subprocess.TimeoutExpired:
            raise ToolError(f"Команда не завершилась за {timeout} с і була зупинена: {command}")
        body = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
        if len(body) > 12_000:
            body = body[:12_000] + "\n… вивід обрізано"
        return f"$ {command}\nexit={proc.returncode}\n{body}".rstrip()

    def git_status(self) -> str:
        return self._git("status --short --branch")

    def git_diff(self, path: str = "") -> str:
        args = "diff --stat"
        if path:
            args += f' -- "{path}"'
        return self._git(args)

    def _git(self, args: str) -> str:
        try:
            proc = subprocess.run(
                f"git {args}", shell=True, cwd=str(self.root), capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ToolError(_missing_git(exc)) from exc
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if proc.returncode != 0:
            if "is not recognized" in out or "не є внутрішньою" in out:
                return _missing_git(None)
            return f"git {args}: код {proc.returncode}\n{out or '(немає виводу)'}"
        return out or "(робоче дерево чисте)"

    def project_tree(self, depth: int = 3) -> str:
        depth = max(1, min(int(depth or 3), 6))
        root = self.root
        lines: list[str] = [f"{root.name}/"]

        def walk(folder: Path, prefix: str, level: int) -> None:
            if level > depth:
                return
            try:
                entries = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except OSError:
                return
            entries = [e for e in entries if e.name not in ws.SKIP_DIRS]
            for index, entry in enumerate(entries[:60]):
                last = index == min(len(entries), 60) - 1
                branch = "└── " if last else "├── "
                lines.append(f"{prefix}{branch}{entry.name}{'/' if entry.is_dir() else ''}")
                if entry.is_dir():
                    walk(entry, prefix + ("    " if last else "│   "), level + 1)

        walk(root, "", 1)
        return "\n".join(lines)

    def python_check(self, path: str) -> str:
        target = self.resolve(path)
        if not target.exists():
            raise ToolError(f"Файл не знайдено: {path}")
        if not target.is_file():
            raise ToolError(f"Це не файл: {path}")
        try:
            import py_compile

            py_compile.compile(str(target), doraise=True, cfile=str(target) + ".pyc-check")
            Path(str(target) + ".pyc-check").unlink(missing_ok=True)
            return f"{path}: синтаксис ок"
        except Exception as exc:  # noqa: BLE001 - показуємо текст помилки моделі
            return f"{path}: помилка синтаксису\n{exc}"

    # ── живе тестування застосунку ─────────────────────────────────────────
    def app_start(self) -> str:
        """Запустити застосунок проєкту у вбудованому прев'ю."""
        ok, detail = self._app().start()
        return (f"✓ Застосунок запущено. {detail}" if ok else f"✗ {detail}")

    def app_stop(self) -> str:
        return self._app().stop()

    def app_restart(self) -> str:
        ok, detail = self._app().restart()
        return (f"✓ Застосунок перезапущено. {detail}" if ok else f"✗ {detail}")

    def app_status(self) -> str:
        controller = self._app()
        recipe = controller.detect()
        parts = [f"Стан: {controller.describe()}"]
        if recipe is not None:
            parts.append(f"Стек: {recipe.icon} {recipe.label}"
                         + (f" — {recipe.reason}" if recipe.reason else ""))
        url = controller.url
        if url:
            parts.append(f"Адреса: {url}")
        return "\n".join(parts)

    def app_screenshot(self, title: str = "", save_to: str = "") -> str:
        """Скріншот: вікно проєкту, конкретне вікно або весь екран.

        Якщо заголовок НЕ задано, знімаємо вікно САМОГО проєкту (живий сайт
        у вбудованому браузері) — це майже завжди те, що потрібно. Раніше
        порожній заголовок означав «весь екран», і модель отримувала знімок
        робочого столу замість своєї сторінки (перевірено наживо: локальна
        модель обрала ``app_screenshot()`` і побачила весь екран).
        """
        if not title.strip():
            provider = getattr(self, "browser_hwnd_provider", None)
            hwnd = 0
            if provider is not None:
                try:
                    hwnd = int(provider() or 0)
                except Exception:  # noqa: BLE001
                    hwnd = 0
            if hwnd:
                return app_control.take_screenshot("", save_to or "", hwnd=hwnd)
        return app_control.take_screenshot(title or "", save_to or "")

    # ── візуальні інструменти ──────────────────────────────────────────────
    # Принцип: інструменти повертають ФАКТИ (шляхи, розміри, координати,
    # числа різниці). Розуміння вмісту робить модель, отримавши зображення
    # через ``image_url``. Інструмент не «описує» картинку замість моделі.
    def capture_screen(self, region: str = "") -> str:
        """Зняти весь екран (або область ``x,y,width,height``)."""
        from . import screenshot as shot

        rect = None
        text = (region or "").strip()
        if text:
            try:
                parts = [int(part.strip()) for part in text.split(",")]
            except ValueError as exc:
                raise ToolError("Область задається як x,y,ширина,висота "
                                "цілими числами.") from exc
            if len(parts) != 4:
                raise ToolError("Область задається як x,y,ширина,висота.")
            # у Win32 прямокутник — це МЕЖІ (left, top, right, bottom),
            # а користувач (і модель) задає РОЗМІР області. Без цього
            # перетворення знімок виходив іншого розміру (200×100 замість
            # 300×200), і ніщо про це не повідомляло.
            rect = shot.rect_from_size(parts[0], parts[1], parts[2], parts[3])
        target = imaging.shots_dir() / f"screen-{int(time.time() * 1000) % 100_000_000}.png"
        capture = shot.capture_screen(target, rect=rect)
        if not capture.ok:
            raise ToolError(capture.detail or "не вдалось зробити знімок")
        imaging.record("capture_screen", capture.path,
                       width=capture.width, height=capture.height)
        note = f"Скріншот {capture.width}×{capture.height}: {capture.path}"
        if capture.width > multiscale.TILE_SIZE or capture.height > multiscale.TILE_SIZE:
            note += ("\nЗображення велике: щоб прочитати дрібний текст, виклич "
                     "inspect_screenshot_regions із цим шляхом.")
        return note

    def capture_region(self, x: int = 0, y: int = 0,
                       width: int = 0, height: int = 0) -> str:
        """Зняти виділену прямокутну область екрана."""
        if width <= 0 or height <= 0:
            raise ToolError("Вкажи додатні width і height для області.")
        from . import screenshot as shot

        target = imaging.shots_dir() / f"region-{int(time.time() * 1000) % 100_000_000}.png"
        capture = shot.capture_screen(
            target, rect=shot.rect_from_size(int(x), int(y), int(width), int(height)))
        if not capture.ok:
            raise ToolError(capture.detail or "не вдалось зняти область")
        imaging.record("capture_region", capture.path,
                       box=[int(x), int(y), int(x) + int(width), int(y) + int(height)])
        return (f"Область {capture.width}×{capture.height} знято: {capture.path}\n"
                f"Координати на екрані: x={x}, y={y}, {width}×{height}")

    def crop_screenshot(self, path: str = "", x: int = 0, y: int = 0,
                        width: int = 0, height: int = 0) -> str:
        """Вирізати область зі знімка БЕЗ масштабування."""
        if not (path or "").strip():
            raise ToolError("Вкажи шлях до знімка.")
        target, note = imaging.crop(path, (int(x), int(y), int(width), int(height)))
        if target is None:
            raise ToolError(note)
        return note

    def get_image_dimensions(self, path: str = "") -> str:
        """Розміри зображення в пікселях."""
        if not (path or "").strip():
            raise ToolError("Вкажи шлях до зображення.")
        return imaging.image_info(path).text()

    def get_screenshot_metadata(self, path: str = "") -> str:
        """Повні метадані знімка: розмір, формат, вага, коли створено."""
        if not (path or "").strip():
            raise ToolError("Вкажи шлях до знімка.")
        info = imaging.image_info(path)
        lines = [info.text()]
        try:
            entries = [item for item in imaging.load_history()
                       if imaging.same_path(str(item.get("path")), path)]
        except Exception:  # noqa: BLE001
            entries = []
        if entries:
            lines.append("Історія цього файлу:")
            for item in entries[-4:]:
                lines.append(f"  • {item.get('kind')} — {item.get('stamp', '?')}")
        else:
            lines.append("У історії знімків цього файлу немає.")
        return "\n".join(lines)

    def list_screenshots(self, limit: int = 10) -> str:
        """Останні знімки й похідні зображення з історії.

        Потрібно, щоб агент міг повернутись до вже зробленого кадру («той
        самий екран, який я знімав на кроці 3»), а не робити новий знімок
        навмання.
        """
        wanted = max(1, min(int(limit or 10), 50))
        entries = imaging.recent(wanted)
        if not entries:
            return "Історія знімків порожня — ще не було жодного кадру."
        lines = [f"Останні {len(entries)} записів історії знімків:"]
        for item in reversed(entries):
            path = str(item.get("path") or "")
            exists = "✓" if Path(path).exists() else "✗ файлу вже немає"
            extra = ""
            box = item.get("box")
            if isinstance(box, (list, tuple)) and len(box) == 4:
                extra = f" · box=({box[0]},{box[1]})–({box[2]},{box[3]})"
            lines.append(f"  • {item.get('stamp', '?')} · {item.get('kind')} · "
                         f"{path}{extra} {exists}")
        return "\n".join(lines)

    def inspect_screenshot_regions(self, path: str = "", size: int = 0) -> str:
        """Нарізати великий скріншот на перекривні ділянки (multi-scale).

        Ділянки ріжуться з ОРИГІНАЛУ без масштабування, тож дрібний текст
        лишається читабельним. Координати кожної ділянки вказані відносно
        оригіналу.
        """
        if not (path or "").strip():
            raise ToolError("Вкажи шлях до скріншота.")
        wanted = int(size) if size else multiscale.TILE_SIZE
        plan, note = imaging.inspect_regions(path, size=max(256, wanted))
        if plan is None:
            raise ToolError(note)
        return note

    def compare_screenshots(self, first: str = "", second: str = "",
                            threshold: int = 0) -> str:
        """Порахувати піксельну різницю між двома знімками."""
        if not (first or "").strip() or not (second or "").strip():
            raise ToolError("Вкажи шляхи до двох знімків.")
        difference = imaging.compare(
            first, second, threshold=int(threshold) if threshold else 24)
        if not difference.ok:
            raise ToolError(difference.error)
        return difference.text()

    def analyze_visual_difference(self, first: str = "", second: str = "",
                                  threshold: int = 0) -> str:
        """Знайти, ЩО змінилось, і видати ділянки для перегляду моделлю.

        На відміну від ``compare_screenshots`` (лише числа), цей інструмент
        додатково ВИРІЗАЄ змінені ділянки з обох знімків і повертає їхні
        шляхи — щоб модель могла подивитись «до» і «після» окремо.
        """
        if not (first or "").strip() or not (second or "").strip():
            raise ToolError("Вкажи шляхи до двох знімків.")
        difference = imaging.compare(
            first, second, threshold=int(threshold) if threshold else 24)
        if not difference.ok:
            raise ToolError(difference.error)
        lines = [difference.text()]
        if not difference.boxes:
            lines.append("\nЗмінених ділянок не виділено — порівнювати нічого.")
            return "\n".join(lines)
        lines.append("\nВирізані ділянки (до / після) для візуальної перевірки:")
        for index, box in enumerate(difference.boxes[:4], start=1):
            x0, y0, x1, y1 = box
            width, height = max(1, x1 - x0), max(1, y1 - y0)
            before, note_before = imaging.crop(first, (x0, y0, width, height))
            after, note_after = imaging.crop(second, (x0, y0, width, height))
            lines.append(f"  {index}. ({x0},{y0})–({x1},{y1}):")
            lines.append(f"     до:    {before if before else note_before}")
            lines.append(f"     після: {after if after else note_after}")
        if len(difference.boxes) > 4:
            lines.append(f"  … і ще {len(difference.boxes) - 4} ділянок")
        return "\n".join(lines)

    # ── інтернет: пошук, сторінки, API ─────────────────────────────────────
    # Ці інструменти працюють ЗАВЖДИ, без MCP і без ключів: мережа — базова
    # можливість IDE, а не опція. Раніше ``search_web`` жив лише в MCP-сервері,
    # тож без підключеного MCP агент не мав інтернету зовсім.
    def search_web(self, query: str = "", limit: int = 0) -> str:
        """Пошук в інтернеті: факти, ціни, погода, курси, документація."""
        if not (query or "").strip():
            raise ToolError("Порожній запит для пошуку.")
        result = internet.search(query)
        text = result.as_text()
        if limit:
            text = text[: max(200, int(limit))]
        return text

    def fetch_url(self, url: str = "", limit: int = 0) -> str:
        """Завантажити сторінку й прочитати її як текст."""
        if not (url or "").strip():
            raise ToolError("Порожня адреса.")
        text = internet.fetch(url, limit=max(500, int(limit)) if limit else internet.DEFAULT_LIMIT)
        return text

    def web_open(self, url: str = "") -> str:
        """Показати сторінку людині у вбудованому браузері IDE.

        Це те, що користувач просив прямо: «щоб агент сам міг мені відкрити
        посилання і показати, де він знайшов інформацію». ``fetch_url``
        читає сторінку для моделі, а цей інструмент відкриває її на екрані.

        Адресу розуміє так само, як рядок адреси браузера: повна адреса,
        домен без схеми або навіть пошуковий запит словами.
        """
        from . import browser_panel

        clean = (url or "").strip().strip('"\'')
        if not clean:
            raise ToolError("Порожня адреса для відкриття.")
        target = browser_panel.normalise_url(clean)
        if not target:
            raise ToolError(f"Не схоже на адресу: «{clean}».")
        opener = getattr(self, "page_opener", None)
        if not callable(opener):
            # Вікно IDE не підключене (тести, фоновий режим). Чесно кажемо
            # це, а не вдаємо, що сторінку показано.
            raise ToolError(
                "Вбудований браузер недоступний: сторінку можна лише "
                f"прочитати інструментом fetch_url. Адреса: {target}")
        try:
            shown = bool(opener(target))
        except Exception as exc:                 # noqa: BLE001
            raise ToolError(f"Не вдалось відкрити сторінку: {exc}") from exc
        if not shown:
            raise ToolError(
                f"Браузер не відкрив адресу {target}. Перевір, чи вона "
                "доступна, і спробуй fetch_url, щоб прочитати її як текст.")
        return f"✓ Сторінку відкрито у вбудованому браузері: {target}"

    def web_api(self, url: str = "", method: str = "GET",
                body: str = "", content_type: str = "application/json") -> str:
        """HTTP-запит до API: перевірити ендпоінт проєкту або зовнішній сервіс."""
        if not (url or "").strip():
            raise ToolError("Порожня адреса API.")
        payload: Any = None
        if (body or "").strip():
            if "json" in (content_type or "").lower():
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError:
                    payload = body
            else:
                payload = body
        headers = {"Content-Type": content_type} if content_type else None
        return internet.http_request(url, method=method, body=payload,
                                     headers=headers)

    def internet_status(self) -> str:
        """Перевірити доступ до інтернету (чи є з'єднання зараз)."""
        ok, detail = internet.connectivity()
        return ("✓ " if ok else "✗ ") + detail

    def app_windows(self) -> str:
        """Перелік вікон, які можна зняти (щоб не гадати назву)."""
        return app_control.screenshot_windows()

    def window_screenshot(self, title: str = "", index: int = 0) -> str:
        """Знімок БУДЬ-ЯКОГО вікна Windows: редактор, термінал, IDE, браузер.

        Навіщо окремий інструмент. ``project_screenshot`` знімає лише
        вбудований браузер проєкту. Але агенту треба бачити й інше:
        відкритий редактор коду в IDE, вікно терміналу з помилкою, діалог
        системи, сторонню програму, яку користувач просив перевірити.

        ``index`` дозволяє вибрати N-не вікно з тих, що збіглись за назвою
        (напр. кілька вікон «Chrome»), коли потрібне конкретне.
        """
        from . import screenshot as shot

        query = (title or "").strip()
        windows = shot.find_windows(query, min_size=160) if query else \
            [w for w in shot.iter_windows() if w.width >= 160 and w.height >= 160]
        # Вікна самої IDE теж цікаві: редактор, термінал, діалоги.
        if not windows:
            hint = ("Вікон не знайдено. Виклич app_windows, щоб побачити "
                    "точні назви й класи." if query else
                    "Видимих вікон немає.")
            return f"✗ {hint}"
        position = max(0, min(int(index or 0), len(windows) - 1))
        info = windows[position]
        from .config import app_data_dir

        target = (app_data_dir() / "screenshots"
                  / f"win-{int(time.time() * 1000) % 100_000_000}.png")
        capture = shot.capture_window(info, target)
        if not capture.ok:
            alternatives = ", ".join(w.line()[:60] for w in windows[:5])
            return (f"✗ Не вдалось зняти «{info.title or info.class_name}»: "
                    f"{capture.detail}\nІнші вікна: {alternatives}")
        lines = [f"Скріншот вікна: {target}",
                 f"Вікно: {info.line()}"]
        if len(windows) > 1:
            others = ", ".join(w.title or w.class_name for w in windows[:6])
            lines.append(f"Збігів за запитом: {len(windows)} ({others}). "
                         f"Для іншого — index=1, 2…")
        return "\n".join(lines)

    def project_screenshot(self) -> str:
        """Знімок САМЕ вікна проєкту (вбудований браузер IDE).

        Навіщо окремий інструмент. ``app_screenshot(title="Chrome")`` на
        машині з відкритим Chrome знімав ЧУЖЕ вікно — на скріншоті
        користувача в чаті з'являлось темне незрозуміле зображення замість
        його сайту. Тут ми беремо дескриптор вікна безпосередньо з
        вбудованого браузера (``BrowserView.hwnd``), тому знімається рівно
        те, що показує Live Preview.
        """
        provider = getattr(self, "browser_hwnd_provider", None)
        hwnd = 0
        if provider is not None:
            try:
                hwnd = int(provider() or 0)
            except Exception:  # noqa: BLE001 - провайдер не має ламати агента
                hwnd = 0
        if not hwnd:
            return (
                "✗ Вікно проєкту зараз не відкрите. Зроби так:\n"
                "1) app_start — запустити сайт;\n"
                "2) відкрий Live Browser (шапка → 🌐), щоб з'явилось вікно;\n"
                "3) повтори project_screenshot."
            )
        return app_control.take_screenshot("", "", hwnd=hwnd)

    def app_logs(self, lines: int = 25) -> str:
        """Журнал запуску застосунку проєкту (помилки старту видно тут)."""
        return self._app().logs(max(5, min(200, int(lines or 25))))

    def app_click(self, x: int, y: int, double: bool = False, right: bool = False) -> str:
        """Клік у вікні застосунку за екранними координатами."""
        return app_control.click_at(int(x), int(y), double=bool(double), right=bool(right))

    def app_type(self, text: str, press_enter: bool = False) -> str:
        """Ввести текст у сфокусоване поле вікна застосунку."""
        return app_control.type_text(text or "", press_enter=bool(press_enter))

    def app_key(self, key: str = "enter") -> str:
        """Натиснути службову клавішу: enter, esc, tab, f5."""
        return app_control.press_key(key)

    # ── живий браузер: сторінка як дані (консолі, DOM, знімки) ─────────────
    def _session(self):
        """CDP-сесія вбудованого браузера (``None``, якщо її немає).

        ДОЗВІЛ. DOM-міст призначений для ВЛАСНОГО Live Preview. Правило
        було лише в коментарях, тож агент міг читати DOM будь-якого
        відкритого сайту — зокрема чужого, з особистими даними в полях.
        Тепер адреса перевіряється: локальні сторінки (``localhost``,
        ``127.0.0.1``, ``file://``) доступні завжди, а зовнішні — лише
        якщо користувач явно дозволив це в налаштуваннях.
        """
        provider = getattr(self, "cdp_provider", None)
        if provider is None:
            raise ToolError(
                "Вбудований браузер не підключений. Відкрий Live Browser "
                "(шапка → 🌐) або запусти сайт — тоді сторінка стане "
                "доступною для перевірки."
            )
        session = provider()
        if session is None:
            raise ToolError(
                "Сторінка ще не готова: у браузера немає порту налагодження. "
                "Запусти сайт кнопкою ▶ або відкрий Live Browser."
            )
        url = ""
        try:
            url = str(session.page_url() or "")
        except Exception:  # noqa: BLE001 - адреса не має ламати інструмент
            url = ""
        self._require_page_permission(url)
        return session

    def _require_page_permission(self, url: str) -> None:
        """Перевірити, чи можна читати цю сторінку через DOM-міст."""
        if not url:
            return
        from . import browser_panel

        try:
            local = browser_panel.is_local_url(url)
        except Exception:  # noqa: BLE001
            local = False
        if local:
            return
        if getattr(self, "allow_external_page_inspection", False):
            return
        raise ToolError(
            f"Сторінка «{url[:80]}» — не власний Live Preview. DOM-міст "
            f"призначений для локального сайту проєкту; для зовнішніх "
            f"сторінок потрібен явний дозвіл у налаштуваннях. "
            f"Для візуальної перевірки використай web_screenshot."
        )

    def web_url(self) -> str:
        """Адреса сторінки у вбудованому браузері."""
        session = self._session()
        return session.page_url() or f"Адреса невідома ({session.last_error or '—'})"

    def web_console(self, errors_only: bool = True, limit: int = 40) -> str:
        """Консоль сторінки: помилки JavaScript, ресурсів і HTTP.

        Саме цього раніше не було: помилка на сторінці існувала лише в
        очах користувача, і агент про неї не знав.
        """
        session = self._session()
        # Свіжі події: сторінка могла змінитись після останнього читання.
        session.evaluate("void 0")
        return session.console_text(errors_only=bool(errors_only),
                                    limit=max(1, min(200, int(limit or 40))))

    def web_inspect(self, selector: str = "", x: int = -1, y: int = -1) -> str:
        """Інспектор елемента: тег, класи, селектор, розміри, CSS.

        Або за CSS-селектором (``selector``), або за координатами сторінки
        (``x``, ``y``). Другий режим — це «натисни на елемент у браузері й
        покажи, що це таке».
        """
        session = self._session()
        if selector.strip():
            info = session.inspect_selector(selector.strip())
        elif x >= 0 and y >= 0:
            info = session.inspect_at(int(x), int(y))
        else:
            raise ToolError("Вкажи selector або координати x, y.")
        if not info:
            where = selector or f"({x}, {y})"
            return (f"Елемент не знайдено: {where}"
                    + (f" ({session.last_error})" if session.last_error else ""))
        return _format_element(info)

    def web_screenshot(self, save_to: str = "", full_page: bool = False) -> str:
        """Знімок САМЕ СТОРІНКИ (а не екрана) у PNG."""
        session = self._session()
        from .config import app_data_dir

        target = (save_to or "").strip()
        if not target:
            folder = app_data_dir() / "screenshots"
            target = str(folder / f"page-{int(time.time())}.png")
        saved = session.screenshot(target, full_page=bool(full_page))
        if not saved:
            return f"Не вдалось зробити знімок: {session.last_error or 'невідома причина'}"
        return f"Знімок сторінки: {saved}"

    def web_audit(self) -> str:
        """Перевірити сторінку: посилання, кнопки, форми, зображення, заголовки."""
        session = self._session()
        report = session.audit()
        if not report.get("ok"):
            return f"Перевірка не вдалась: {report.get('reason') or '—'}"
        return _format_audit(report)

    # ── DOM-міст Live Preview ──────────────────────────────────────────────
    # Дає зв'язок «вигляд → елемент → файл»: селектор, координати, стилі.
    # Це ДОПОВНЕННЯ до зору, а не заміна: анімації, canvas і псевдокласи
    # в DOM не видні, тому скріншот лишається джерелом істини про вигляд.
    def dom_tree(self, depth: int = 0, limit: int = 0,
                 selector: str = "") -> str:
        """Дерево DOM сторінки: теги, селектори, координати, текст."""
        session = self._session()
        if (selector or "").strip():
            from . import dom_bridge

            data, note = dom_bridge.element_styles(session, selector.strip())
            if data is None:
                return note
            return note
        from . import dom_bridge

        nodes, note = dom_bridge.dom_tree(
            session,
            depth=int(depth) if depth else dom_bridge.MAX_DEPTH,
            limit=int(limit) if limit else dom_bridge.MAX_NODES)
        if not nodes:
            return note
        lines = [note]
        for node in nodes:
            lines.append("  " + node.line())
        return "\n".join(lines)

    def dom_find_text(self, text: str = "", limit: int = 0) -> str:
        """Знайти елементи, у тексті яких є фрагмент (напр. назва кнопки)."""
        if not (text or "").strip():
            raise ToolError("Вкажи фрагмент тексту для пошуку.")
        session = self._session()
        from . import dom_bridge

        found = dom_bridge.by_text(
            session, text, limit=int(limit) if limit else 10)
        if not found:
            return f"На сторінці немає елемента з текстом «{text}»."
        lines = [f"Знайдено {len(found)} елементів із текстом «{text}»:"]
        for node in found:
            lines.append("  " + node.line())
        return "\n".join(lines)

    def dom_styles(self, selector: str = "") -> str:
        """Обчислені стилі елемента (display, шрифт, кольори, відступи)."""
        if not (selector or "").strip():
            raise ToolError("Вкажи CSS-селектор елемента.")
        session = self._session()
        from . import dom_bridge

        data, note = dom_bridge.element_styles(session, selector.strip())
        return note

    def dom_console(self, limit: int = 0) -> str:
        """Помилки сторінки (JS, ресурси) у структурованому вигляді."""
        session = self._session()
        from . import dom_bridge

        items, note = dom_bridge.console_errors(
            session, limit=int(limit) if limit else 20)
        if not items:
            return note
        lines = [note]
        for item in items:
            lines.append(f"  • {str(item.get('text') or item)[:160]}")
        return "\n".join(lines)

    def web_responsive(self, sizes: str = "") -> str:
        """Перевірити адаптивність на кількох розмірах екрана.

        ``sizes`` — рядок на кшталт ``375x667,768x1024,1280x800``. Порожній —
        стандартний набір.
        """
        session = self._session()
        rows = session.responsive_check(_parse_sizes(sizes))
        if not rows:
            return "Не вдалось перевірити розміри."
        lines = []
        for row in rows:
            width = row.get("width")
            height = row.get("height")
            if not row.get("ok", True):
                lines.append(f"· {width}×{height}: помилка — {row.get('reason')}")
                continue
            scroll = "є горизонтальна прокрутка" if row.get("horizontalScroll") else "без прокрутки"
            wide = row.get("wideElements") or []
            extra = f", {len(wide)} елементів ширші за екран" if wide else ""
            lines.append(f"· {width}×{height}: {scroll}{extra}")
        return "Адаптивність:\n" + "\n".join(lines)

    def web_click(self, selector: str = "", x: int = -1, y: int = -1) -> str:
        """Клікнути елемент на сторінці (за селектором або координатами)."""
        session = self._session()
        if selector.strip():
            ok = session.click_selector(selector.strip())
            return (f"Клікнуто: {selector}" if ok
                    else f"Елемент не знайдено: {selector}")
        if x >= 0 and y >= 0:
            ok = session.click_at(int(x), int(y))
            return f"Клік у точці ({x}, {y})" if ok else "Клік не вдався."
        raise ToolError("Вкажи selector або координати x, y.")

    def web_type(self, text: str, selector: str = "",
                 press_enter: bool = False) -> str:
        """Ввести текст у поле сторінки (спершу фокус, якщо дано селектор)."""
        session = self._session()
        if selector.strip():
            focused = session.evaluate(
                "(()=>{const e=document.querySelector("
                + json.dumps(selector.strip())
                + ");if(!e)return false;e.focus();return true;})()")
            if not focused:
                return f"Поле не знайдено: {selector}"
        if not session.type_text(text or ""):
            return "Текст не введено."
        if press_enter:
            session.press_key("enter")
        return f"Введено текст ({len(text or '')} символів)" + (
            " і натиснуто Enter." if press_enter else ".")

    # ── виклик ─────────────────────────────────────────────────────────────
    def handled_names(self) -> set[str]:
        """Назви інструментів, які реєстр справді вміє виконувати."""
        return set(self._handlers)

    def call(self, name: str, arguments: str | dict[str, Any]) -> ToolResult:
        handler = self._handlers.get(name)
        if handler is None:
            return ToolResult(False, f"Невідомий інструмент: {name}")
        if isinstance(arguments, str):
            raw = arguments.strip()
            if not raw:
                args: dict[str, Any] = {}
            else:
                try:
                    args = json.loads(raw)
                except json.JSONDecodeError as exc:
                    return ToolResult(False, f"Аргументи не JSON: {exc}")
        else:
            args = dict(arguments or {})
        try:
            output = handler(**args)
        except TypeError as exc:
            return ToolResult(False, f"Неправильні аргументи {name}: {exc}")
        except (ToolError, ws.WorkspaceError) as exc:
            return ToolResult(False, str(exc))
        except Exception as exc:  # noqa: BLE001 - агент має бачити будь-яку помилку
            return ToolResult(False, f"{type(exc).__name__}: {exc}")
        # Рядок, що починається з «✗», — це НЕВДАЧА, навіть якщо обробник
        # її повернув замість винятку. Без цього агент бачив «успіх» і
        # вважав, що знімок зроблено, хоч вікна не було.
        text = output if isinstance(output, str) else str(output or "")
        return ToolResult(not text.lstrip().startswith("✗"), text)


def _missing_git(exc: object = None) -> str:
    """Зрозуміле повідомлення, коли git не встановлено."""
    detail = f" ({exc})" if exc else ""
    return (
        "Git недоступний" + detail + ". Встанови його з https://git-scm.com/download/win "
        "і перезапусти IDE — тоді запрацюють git_status і git_diff."
    )


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


def _shell_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Прочитати текстовий файл робочої теки з номерами рядків.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Шлях відносно робочої теки"},
                    "start_line": {"type": "integer", "description": "Перший рядок (1)"},
                    "end_line": {"type": "integer", "description": "Останній рядок (0 = до кінця)"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Створити або повністю перезаписати файл. Стара версія зберігається як .bak.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string", "description": "Повний новий вміст файлу"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Замінити точний фрагмент у наявному файлі. old_string має бути унікальним.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                    "replace_all": {"type": "boolean", "description": "Замінити всі входження"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "append_file",
            "description": (
                "Дописати текст у кінець файлу, НЕ затираючи наявний вміст. "
                "Використовуй, коли просять «додай рядок», «допиши», "
                "«в кінці файлу». Для заміни фрагмента — edit_file, для "
                "нового файлу з нуля — write_file."),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Шлях відносно робочої теки"},
                    "content": {"type": "string", "description": "Текст, який дописати"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "Показати вміст папки робочої теки.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Папка, за замовчуванням ."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": "Пошук тексту в коді робочої теки.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "glob": {"type": "string", "description": "Фільтр імен, напр. *.py"},
                    "regex": {"type": "boolean"},
                    "case": {"type": "boolean"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_files",
            "description": "Знайти файли за glob-шаблоном, напр. '**/*.py'. "
                           "Для ПІДРАХУНКУ кількості вкажи limit=0: тоді у "
                           "відповіді буде справжня кількість файлів.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "limit": {"type": "integer",
                              "description": "Скільки шляхів показати; 0 = усі"},
                    "path": {"type": "string",
                             "description": "Звузити пошук до цієї теки"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Виконати команду в робочій теці (cmd.exe). Для перевірок: python -m unittest, py_compile, pytest.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout": {"type": "integer", "description": "Секунди, максимум 900"},
                    "cwd": {"type": "string", "description": "Підпапка для запуску"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Стан git-репозиторію (status --short --branch).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Короткий diff робочого дерева.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "project_tree",
            "description": "Дерево проєкту до заданої глибини.",
            "parameters": {
                "type": "object",
                "properties": {"depth": {"type": "integer"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "python_check",
            "description": "Перевірити синтаксис Python-файлу без запуску.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "app_start",
            "description": (
                "Запустити застосунок проєкту у вбудованому прев'ю IDE. "
                "Стек визначається автоматично (npm/vite, python, статика). "
                "Використовуй після змін, щоб перевірити результат."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "app_stop",
            "description": "Зупинити застосунок проєкту.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "app_restart",
            "description": (
                "Перезапустити застосунок проєкту (свіжий процес, новий порт). "
                "Використовуй, коли зміни не підхопились гарячим оновленням."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "app_status",
            "description": "Стан застосунку: запущений/зупинений, стек, адреса прев'ю.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "app_screenshot",
            "description": (
                "Знімок того, що зараз на екрані проєкту. Без заголовка "
                "знімає вікно ЖИВОГО САЙТУ проєкту (найчастіше це те, що "
                "потрібно). Можна вказати title=<частина заголовка вікна>, "
                "щоб зняти інше вікно, або title='*' для всього екрана. "
                "Картинка з'являється в чаті."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": ("Порожньо = вікно проєкту; '* ' = весь екран; "
                                        "інакше — частина заголовка вікна"),
                    },
                    "save_to": {"type": "string", "description": "Куди зберегти PNG (порожньо = типовий каталог)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "project_screenshot",
            "description": (
                "Знімок вікна САМОГО проєкту — вбудованого браузера IDE з "
                "живим сайтом. Це найкращий спосіб побачити результат своєї "
                "роботи: спершу app_start, потім цей інструмент. "
                "Зображення з'являється в чаті картинкою."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "window_screenshot",
            "description": (
                "Знімок БУДЬ-ЯКОГО вікна Windows: редактор коду, термінал, "
                "IDE, браузер, стороння програма. Використовуй, коли треба "
                "побачити, що на екрані в користувача — помилку в терміналі, "
                "вікно редактора, діалог системи. Без title знімає найбільше "
                "видиме вікно. Спершу app_windows, якщо назва невідома."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Частина заголовка або класу вікна (порожньо = найбільше вікно)"},
                    "index": {"type": "integer", "description": "Яке з кількох знайдених вікон зняти (0 — перше)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "app_windows",
            "description": (
                "Перелік вікон, які зараз можна зняти (заголовок, клас, "
                "розмір). Використовуй ПЕРЕД app_screenshot, якщо не знаєш "
                "точної назви вікна."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "app_logs",
            "description": (
                "Журнал запуску застосунку проєкту: помилки старту, "
                "повідомлення сервера. Використовуй, коли застосунок не "
                "запускається або сторінка порожня."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "lines": {"type": "integer", "description": "Скільки останніх рядків (5–200)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "app_click",
            "description": (
                "Клік у вікні застосунку за екранними координатами. "
                "Спершу зроби app_screenshot і прикинь координати елемента."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "double": {"type": "boolean", "description": "Подвійний клік"},
                    "right": {"type": "boolean", "description": "Права кнопка"},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "app_type",
            "description": "Ввести текст у сфокусоване поле вікна застосунку (клікни по полю перед цим).",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "press_enter": {"type": "boolean", "description": "Натиснути Enter після тексту"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "app_key",
            "description": "Натиснути службову клавішу: enter, esc, tab, f5.",
            "parameters": {
                "type": "object",
                "properties": {"key": {"type": "string", "description": "enter | esc | tab | f5"}},
            },
        },
    },
    # ── інтернет ───────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "ПОШУК В ІНТЕРНЕТІ. Використовуй завжди, коли потрібні свіжі "
                "дані: ціна криптовалюти чи акцій, курс валют, погода, новини, "
                "актуальна версія бібліотеки, документація. Також для "
                "перевірки фактів, у яких не впевнений. Не вигадуй свіжі дані "
                "з пам'яті — спитай мережу."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Пошуковий запит звичайною мовою"},
                    "limit": {"type": "integer", "description": "Обмежити довжину відповіді (символів)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": (
                "Завантажити вебсторінку й прочитати її як текст. "
                "Використовуй, коли треба документація, стаття або повний "
                "вміст сторінки за посиланням із пошуку."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Адреса http(s)://…"},
                    "limit": {"type": "integer", "description": "Скільки символів повернути"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_open",
            "description": (
                "Показати сторінку КОРИСТУВАЧУ у вбудованому браузері IDE. "
                "Викликай, коли людина просить «відкрий», «покажи», «де ти "
                "це знайшов» — тоді вона бачить справжню сторінку й може "
                "натискати на ній кнопки. Для читання вмісту моделлю є "
                "fetch_url."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string",
                            "description": "Адреса http(s)://…, домен або пошуковий запит"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_api",
            "description": (
                "HTTP-запит до API: перевірити, що створений тобою бекенд "
                "відповідає, або звернутись до зовнішнього сервісу. "
                "Повертає код відповіді й тіло."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Адреса ендпоінта"},
                    "method": {"type": "string", "description": "GET | POST | PUT | DELETE"},
                    "body": {"type": "string", "description": "Тіло запиту (JSON або текст)"},
                    "content_type": {"type": "string", "description": "application/json або text/plain"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "internet_status",
            "description": "Перевірити, чи є зараз доступ до інтернету.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    # ── живий браузер: сторінка як дані (CDP) ──────────────────────────────
    # Ці інструменти працюють із САМОЮ СТОРІНКОЮ, а не з картинкою: вони
    # читають консоль, DOM і розміри. Саме тому агент може знайти помилку
    # JavaScript і змінити конкретний елемент, а не вгадувати координати.
    {
        "type": "function",
        "function": {
            "name": "web_url",
            "description": "Адреса сторінки, відкритої у вбудованому браузері IDE.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_console",
            "description": (
                "Консоль сторінки у вбудованому браузері: помилки JavaScript, "
                "помилки завантаження ресурсів і HTTP 4xx/5xx. Використовуй, "
                "коли щось «не працює» — тут справжня причина, а не здогад."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "errors_only": {"type": "boolean", "description": "Лише помилки (типово true)"},
                    "limit": {"type": "integer", "description": "Скільки останніх записів (до 200)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_inspect",
            "description": (
                "Інспектор елемента сторінки: тег, id, класи, CSS-селектор, "
                "розміри, позиція й основні обчислені стилі. Дай selector "
                "(напр. 'button.buy') АБО координати x,y на сторінці. "
                "Результат показує, який саме код треба правити."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS-селектор елемента"},
                    "x": {"type": "integer", "description": "X у координатах сторінки"},
                    "y": {"type": "integer", "description": "Y у координатах сторінки"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_screenshot",
            "description": (
                "Знімок САМОЇ СТОРІНКИ (не екрана) у PNG. Працює навіть якщо "
                "вікно браузера перекрите. Дай full_page=true для повної висоти."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "save_to": {"type": "string", "description": "Шлях до PNG (порожньо = типовий)"},
                    "full_page": {"type": "boolean", "description": "Уся висота сторінки"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_audit",
            "description": (
                "Перевірка сторінки: посилання без href, кнопки нульового "
                "розміру, поля без name, зображення без alt, заголовки, "
                "доступність. Один виклик замість ручного огляду."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_responsive",
            "description": (
                "Перевірити адаптивність: чи з'являється горизонтальна "
                "прокрутка й чи вилазить вміст за екран на заданих розмірах."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sizes": {"type": "string", "description": "Напр. '375x667,768x1024,1280x800'"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_click",
            "description": (
                "Клікнути елемент сторінки за селектором (або координатами). "
                "На відміну від app_click, це справжній клік у сторінці: він "
                "точно влучає в елемент і не залежить від положення вікна."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string"},
                    "x": {"type": "integer", "description": "X у координатах сторінки"},
                    "y": {"type": "integer", "description": "Y у координатах сторінки"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_type",
            "description": "Ввести текст у поле сторінки (можна з Enter, напр. для форми).",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "selector": {"type": "string", "description": "Поле, куди вводити"},
                    "press_enter": {"type": "boolean"},
                },
                "required": ["text"],
            },
        },
    },
    # ── візуальні інструменти ──────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "capture_screen",
            "description": "Зняти весь екран. Повертає шлях до PNG. Для дрібного "
                           "тексту на великому екрані далі виклич "
                           "inspect_screenshot_regions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "region": {"type": "string",
                               "description": "Необов'язково: 'x,y,ширина,висота'"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "capture_region",
            "description": "Зняти прямокутну область екрана (x, y, ширина, висота).",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"}, "y": {"type": "integer"},
                    "width": {"type": "integer"}, "height": {"type": "integer"},
                },
                "required": ["x", "y", "width", "height"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "crop_screenshot",
            "description": "Вирізати область зі знімка БЕЗ масштабування. "
                           "Повертає шлях до нового PNG і координати.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "x": {"type": "integer"}, "y": {"type": "integer"},
                    "width": {"type": "integer"}, "height": {"type": "integer"},
                },
                "required": ["path", "x", "y", "width", "height"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_image_dimensions",
            "description": "Дізнатися розмір зображення в пікселях (PNG/JPEG/BMP).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_screenshot_metadata",
            "description": "Метадані знімка: розмір, формат, вага, історія файлу.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_screenshot_regions",
            "description": "Нарізати великий скріншот на перекривні ділянки з "
                           "ОРИГІНАЛУ (без зменшення). Повертає шляхи та "
                           "координати кожної ділянки.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "size": {"type": "integer",
                             "description": "Розмір ділянки в px (типово 1024)"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_screenshots",
            "description": "Порахувати піксельну різницю між двома знімками.",
            "parameters": {
                "type": "object",
                "properties": {
                    "first": {"type": "string"}, "second": {"type": "string"},
                    "threshold": {"type": "integer"},
                },
                "required": ["first", "second"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_visual_difference",
            "description": "Знайти, ЩО змінилось: числа різниці плюс вирізані "
                           "ділянки 'до' і 'після' для візуального порівняння.",
            "parameters": {
                "type": "object",
                "properties": {
                    "first": {"type": "string"}, "second": {"type": "string"},
                    "threshold": {"type": "integer"},
                },
                "required": ["first", "second"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_screenshots",
            "description": "Останні знімки й обрізки з історії (шлях, час, "
                           "координати області). Щоб повернутись до вже "
                           "зробленого кадру, а не робити новий навмання.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer",
                              "description": "Скільки останніх записів, типово 10"},
                },
                "required": [],
            },
        },
    },
    # ── DOM-міст Live Preview ──────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "dom_tree",
            "description": "Дерево DOM власного Live Preview: теги, CSS-"
                           "селектори, координати, текст. Дає точний зв'язок "
                           "«вигляд → елемент». Лише для сторінки IDE.",
            "parameters": {
                "type": "object",
                "properties": {
                    "depth": {"type": "integer", "description": "Глибина, типово 6"},
                    "limit": {"type": "integer", "description": "Максимум вузлів"},
                    "selector": {"type": "string",
                                 "description": "Замість дерева — стилі цього елемента"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dom_find_text",
            "description": "Знайти елементи сторінки, у тексті яких є фрагмент "
                           "(напр. напис на кнопці).",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dom_styles",
            "description": "Обчислені CSS-стилі елемента за селектором.",
            "parameters": {
                "type": "object",
                "properties": {"selector": {"type": "string"}},
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dom_console",
            "description": "Помилки сторінки Live Preview (JS, ресурси).",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
            },
        },
    },
]
