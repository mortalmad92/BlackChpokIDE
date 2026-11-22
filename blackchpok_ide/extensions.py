"""Саморозширення агента: власні інструменти й скіли з діалогу та інтернету.

Навіщо це. Локальна модель на 8k контексту не вміє всього, що вміють хмарні,
але вона щодня працює в ЦЬОМУ проєкті з ЦИМ користувачем. Якщо кожен
повторюваний ланцюжок дій («перевір реліз → збери .exe → онови changelog»)
лишається тільки в історії чату, модель щоразу вигадує його заново.

Модуль дає агенту ДВІ форми закріплення знання, обидві — звичайні файли в
робочій теці, які людина може прочитати, виправити й видалити:

* **скіл** — ``.agents/skills/<назва>/SKILL.md``: інструкція «як робити X»,
  яку агент бачить у промпті (див. :mod:`skills`);
* **інструмент** — ``.agents/tools/<назва>.json`` + ``.py``: справжня дія,
  яку агент викликає як ``custom:<назва>``. Тіло — Python-функція, тож
  інструмент не «вигаданий», а справді виконується в цьому проєкті.

ЧОГО ТУТ СВІДОМО НЕМАЄ:

* не пишемо в саму IDE (``blackchpok_ide/``) — тільки в робочу теку: інакше
  зламаний саморобний інструмент ламав би застосунок;
* не виконуємо код із мережі «як є»: інтернет дає ДЖЕРЕЛО, але текст
  інструкції та код інструмента створює модель і людина може переглянути
  їх у редакторі ПЕРЕД першим запуском;
* не робимо мережевих викликів самі — пошук виконує агент своїми
  інструментами (``search_web`` / ``fetch_url``) і передає нам уже готовий
  текст як джерело.

Модуль не тягне tkinter: його можна перевірити тестами без вікна.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import skills as skills_module

__all__ = [
    "CUSTOM_PREFIX",
    "CustomTool",
    "EXTENSION_TOOLS",
    "ExtensionResult",
    "ExtensionStore",
    "TOOL_SCHEMAS",
    "TOOLS_DIR",
    "custom_tool_schemas",
    "describe_extensions",
    "parse_custom_tool",
    "run_custom_tool",
    "safe_slug",
]

#: Назви інструментів саморозширення — їх агент обробляє окремо від реєстру.
EXTENSION_TOOLS = frozenset({
    "create_skill", "create_tool", "list_custom_tools", "learn_from_web",
})

LOG = logging.getLogger("blackchpok.extensions")

#: Тека, де живуть саморобні інструменти (у робочій теці проєкту).
TOOLS_DIR = ".agents/tools"
#: Префікс назви в реєстрі: ``custom:release_check``.
CUSTOM_PREFIX = "custom:"
#: Службове ім'я файлу опису інструмента.
TOOL_FILE = "TOOL.json"
#: Службове ім'я файлу з кодом інструмента.
CODE_FILE = "tool.py"
#: Максимальна довжина назви інструмента (щоб ``custom:<name>`` лишалось
#: коротким: довгі назви модель плутає під час виклику).
MAX_NAME = 40
#: Скільки саморобних інструментів взагалі показуємо моделі: більше — це вже
#: власна бібліотека, і вона має жити в MCP-сервері, а не в промпті.
MAX_TOOLS = 24
#: Версія формату опису. Потрібна, щоб майбутні зміни не ламали старі файли.
FORMAT_VERSION = 1


def safe_slug(name: str) -> str:
    """Ім'я файлу/теки з довільної назви (латиниця, цифри, дефіс)."""
    raw = (name or "").strip().lower()
    # Кирилиця в іменах інструментів ламає виклик: модель змішує регістр,
    # а ``custom:перевірка`` важко набрати без помилки. Тому транслітерація
    # не потрібна — просто лишаємо латиницю й цифри, решта стає дефісом.
    slug = re.sub(r"[^a-z0-9_.-]+", "-", raw).strip("-._")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:MAX_NAME] or ""


@dataclass
class CustomTool:
    """Один саморобний інструмент, описаний файлами в робочій теці."""

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    code: str = ""
    folder: Path | None = None
    created_at: float = 0.0
    source: str = ""
    #: Чи вже виконувався хоч раз (щоб показати «перевірений» у панелі).
    runs: int = 0
    ok_runs: int = 0
    last_error: str = ""
    enabled: bool = True

    @property
    def registry_name(self) -> str:
        """Назва, яку бачить модель: ``custom:<name>``."""
        return f"{CUSTOM_PREFIX}{self.name}"

    def schema(self) -> dict[str, Any]:
        """Схема у форматі OpenAI function calling."""
        params = self.parameters if isinstance(self.parameters, dict) else {}
        if not params:
            params = {"type": "object", "properties": {}}
        params.setdefault("type", "object")
        params.setdefault("properties", {})
        return {
            "type": "function",
            "function": {
                "name": self.registry_name,
                "description": (self.description or
                                f"Саморобний інструмент проєкту «{self.name}»."),
                "parameters": params,
            },
        }

    def describe(self) -> str:
        state = "перевірений" if self.ok_runs else ("проблемний" if self.last_error else "новий")
        return f"{self.name} — {self.description or 'без опису'} ({state})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "created_at": self.created_at,
            "source": self.source,
            "runs": self.runs,
            "ok_runs": self.ok_runs,
            "last_error": self.last_error,
            "enabled": self.enabled,
        }


def parse_custom_tool(folder: Path) -> CustomTool | None:
    """Прочитати інструмент із теки (``TOOL.json`` + ``tool.py``)."""
    folder = Path(folder)
    meta_path = folder / TOOL_FILE
    code_path = folder / CODE_FILE
    if not meta_path.is_file() or not code_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict):
        return None
    name = safe_slug(str(meta.get("name") or folder.name))
    if not name:
        return None
    try:
        code = code_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    parameters = meta.get("parameters")
    return CustomTool(
        name=name,
        description=str(meta.get("description") or "").strip(),
        parameters=parameters if isinstance(parameters, dict) else {},
        code=code,
        folder=folder,
        created_at=float(meta.get("created_at") or 0.0),
        source=str(meta.get("source") or ""),
        runs=int(meta.get("runs") or 0),
        ok_runs=int(meta.get("ok_runs") or 0),
        last_error=str(meta.get("last_error") or ""),
        enabled=bool(meta.get("enabled", True)),
    )


def discover_custom_tools(root: Path, *, limit: int = MAX_TOOLS) -> list[CustomTool]:
    """Усі саморобні інструменти робочої теки (новіші — першими)."""
    folder = Path(root) / TOOLS_DIR
    if not folder.is_dir():
        return []
    found: list[CustomTool] = []
    try:
        entries = [item for item in folder.iterdir() if item.is_dir()]
    except OSError:
        return []
    for entry in entries:
        tool = parse_custom_tool(entry)
        if tool is not None and tool.enabled:
            found.append(tool)
    found.sort(key=lambda item: item.created_at, reverse=True)
    return found[:max(1, int(limit))]


def custom_tool_schemas(root: Path, *, limit: int = MAX_TOOLS) -> list[dict[str, Any]]:
    """Схеми саморобних інструментів — для промпта моделі."""
    return [tool.schema() for tool in discover_custom_tools(root, limit=limit)]


@dataclass
class ExtensionResult:
    """Що саме створив агент (для повідомлення й журналу)."""

    ok: bool = False
    kind: str = ""            # "skill" | "tool"
    name: str = ""
    path: str = ""
    message: str = ""
    detail: str = ""


class ExtensionStore:
    """Сховище саморозширень: скіли й інструменти в робочій теці.

    ``root`` — тека проєкту. Клас навмисно не кешує вміст: людина може
    правити ``SKILL.md`` і ``tool.py`` вручну, і наступний виклик має бачити
    саме те, що на диску.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ── скіли ─────────────────────────────────────────────────────────────
    def create_skill(self, name: str, description: str = "", body: str = "",
                     *, source: str = "") -> ExtensionResult:
        """Створити скіл. Наявний скіл НЕ перезаписуємо без ``overwrite``."""
        clean = (name or "").strip()
        if not clean:
            return ExtensionResult(kind="skill", message="Порожня назва скіла.")
        # «Уже існував» визначаємо ДО запису — і без побічних ефектів:
        # ``create_skill`` навмисно не перезаписує наявний SKILL.md, тому
        # перевірка самим записом була б марною (раніше вона ще й подвійно
        # викликала ``create_skill`` і завжди звітувала «новий»).
        existed = skills_module.skill_path(self.root, clean).exists()
        try:
            path = skills_module.create_skill(self.root, clean, description, body)
        except OSError as exc:
            return ExtensionResult(kind="skill", name=clean,
                                   message=f"Скіл не створено: {exc}")
        return ExtensionResult(
            ok=True, kind="skill", name=clean, path=str(path),
            message=f"Скіл «{clean}» готовий: {path}",
            detail="уже існував, вміст не перезаписано" if existed else "новий",
        )

    def skills(self) -> list[skills_module.Skill]:
        return skills_module.discover_skills(self.root)

    # ── інструменти ───────────────────────────────────────────────────────
    def tools(self, *, limit: int = MAX_TOOLS) -> list[CustomTool]:
        return discover_custom_tools(self.root, limit=limit)

    def get_tool(self, name: str) -> CustomTool | None:
        slug = safe_slug(name)
        if not slug:
            return None
        for tool in self.tools(limit=MAX_TOOLS):
            if tool.name == slug:
                return tool
        return None

    def create_tool(self, name: str, description: str, code: str,
                    parameters: dict[str, Any] | None = None, *,
                    source: str = "", overwrite: bool = False) -> ExtensionResult:
        """Створити саморобний інструмент.

        ``code`` — тіло Python-функції ``run(**arguments)``. Модель пише його
        в редакторі, і людина бачить текст ПЕРЕД першим запуском. Файл
        перевіряється на синтаксис одразу: синтаксично зламаний інструмент
        не має потрапляти в реєстр, інакше кожен виклик падатиме.
        """
        slug = safe_slug(name)
        if not slug:
            return ExtensionResult(
                kind="tool",
                message=("Назва інструмента має містити латиницю або цифри "
                         "(напр. release_check): кирилицю модель плутає у виклику."))
        body = (code or "").strip()
        if not body:
            return ExtensionResult(kind="tool", name=slug,
                                   message="Порожній код інструмента.")
        folder = Path(self.root) / TOOLS_DIR / slug
        meta_path = folder / TOOL_FILE
        if meta_path.exists() and not overwrite:
            return ExtensionResult(
                ok=False, kind="tool", name=slug, path=str(meta_path),
                message=f"Інструмент «{slug}» уже існує. Передай overwrite=true, "
                        f"щоб замінити його.")
        problem = _syntax_problem(body)
        if problem:
            return ExtensionResult(kind="tool", name=slug,
                                   message=f"Код інструмента не компілюється: {problem}")
        try:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / CODE_FILE).write_text(body + "\n", encoding="utf-8")
            meta = {
                "format": FORMAT_VERSION,
                "name": slug,
                "description": (description or "").strip()[:400],
                "parameters": parameters if isinstance(parameters, dict) else {},
                "created_at": time.time(),
                "source": (source or "").strip()[:500],
                "runs": 0,
                "ok_runs": 0,
                "last_error": "",
                "enabled": True,
            }
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        except OSError as exc:
            return ExtensionResult(kind="tool", name=slug,
                                   message=f"Інструмент не створено: {exc}")
        return ExtensionResult(
            ok=True, kind="tool", name=slug, path=str(folder),
            message=(f"Інструмент «{slug}» створено: {folder}. "
                     f"Модель побачить його як {CUSTOM_PREFIX}{slug}."),
            detail=_interface_note(body),
        )

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """Увімкнути/вимкнути інструмент (вимкнений не показуємо моделі)."""
        tool = self.get_tool(name)
        if tool is None or tool.folder is None:
            return False
        meta_path = tool.folder / TOOL_FILE
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(meta, dict):
            return False
        meta["enabled"] = bool(enabled)
        try:
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        except OSError:
            return False
        return True

    def forget_tool(self, name: str) -> bool:
        """Видалити інструмент (тека зноситься повністю)."""
        tool = self.get_tool(name)
        if tool is None or tool.folder is None:
            return False
        import shutil

        try:
            shutil.rmtree(tool.folder)
        except OSError:
            return False
        return True

    def record_run(self, name: str, *, ok: bool, error: str = "") -> None:
        """Записати результат запуску: полічити спроби й останню помилку."""
        tool = self.get_tool(name)
        if tool is None or tool.folder is None:
            return
        meta_path = tool.folder / TOOL_FILE
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(meta, dict):
            return
        meta["runs"] = int(meta.get("runs") or 0) + 1
        if ok:
            meta["ok_runs"] = int(meta.get("ok_runs") or 0) + 1
            meta["last_error"] = ""
        else:
            meta["last_error"] = " ".join(str(error or "").split())[:400]
        try:
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        except OSError:
            LOG.debug("Результат запуску інструмента не записано", exc_info=True)


def _syntax_problem(code: str) -> str:
    """Синтаксична помилка коду інструмента (``""``, якщо все гаразд)."""
    import ast

    try:
        ast.parse(code)
    except SyntaxError as exc:
        return f"рядок {exc.lineno}: {exc.msg}"
    return ""


def _interface_note(code: str) -> str:
    """Коротка підказка, як інструмент викликатиме рушій."""
    if "def run(" in (code or ""):
        return "Точка входу: run(**arguments) — повертає рядок-результат."
    return ("У коді немає 'def run(...)': інструмент викликатися не зможе. "
            "Додай функцію run(**arguments) -> str.")


# ─────────────────────────────────────────────────────────────────────────────
# Схеми інструментів саморозширення (їх бачить модель)
# ─────────────────────────────────────────────────────────────────────────────

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_skill",
            "description": (
                "Створити ВЛАСНИЙ скіл проєкту (.agents/skills/<назва>/SKILL.md) — "
                "коротку інструкцію «як робити X саме тут». Використовуй, коли "
                "користувач пояснив правильний порядок дій або коли ти сам "
                "знайшов робочий рецепт (у діалозі чи в інтернеті). Скіл "
                "видно в промпті наступного разу й у панелі «Скіли»."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string",
                             "description": "Коротка назва скіла (латиниця, напр. release)"},
                    "description": {"type": "string",
                                    "description": "Коли застосовувати (один рядок)"},
                    "body": {"type": "string",
                             "description": "Інструкція: нумеровані кроки й команди"},
                    "source": {"type": "string",
                               "description": "Звідки знання: діалог, інтернет, лог"},
                },
                "required": ["name", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_tool",
            "description": (
                "Створити ВЛАСНИЙ інструмент проєкту (.agents/tools/<назва>) — "
                "Python-функцію run(**arguments), яку ти зможеш викликати як "
                "custom:<назва> наступного разу. Потрібен, коли дія повторюється "
                "і її можна закріпити кодом (перевірка релізу, збірка, аналіз "
                "файлів). Код ПЕРЕВІРЯЄТЬСЯ на синтаксис перед записом."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string",
                             "description": "Назва латиницею (напр. release_check)"},
                    "description": {"type": "string",
                                    "description": "Що робить інструмент (для моделі)"},
                    "code": {"type": "string",
                             "description": "Python-код із функцією run(**arguments) -> str"},
                    "parameters": {
                        "type": "object",
                        "description": "JSON-схема аргументів для function calling",
                    },
                    "source": {"type": "string",
                               "description": "Звідки взявся код (діалог/інтернет)"},
                    "overwrite": {"type": "boolean",
                                  "description": "Замінити наявний інструмент"},
                },
                "required": ["name", "description", "code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_custom_tools",
            "description": (
                "Показати власні інструменти й скіли проєкту, створені раніше "
                "(ім'я, опис, скільки разів працював, остання помилка)."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_from_web",
            "description": (
                "Взяти сторінку з інтернету як ДЖЕРЕЛО для нового скіла або "
                "інструмента: шукає, читає текст і зберігає його разом із "
                "посиланням. Далі створи скіл/інструмент через create_skill "
                "або create_tool, вказавши source=URL."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Що знайти"},
                    "url": {"type": "string",
                            "description": "Конкретна сторінка (замість пошуку)"},
                },
                "required": [],
            },
        },
    },
]


def describe_extensions(store: ExtensionStore) -> str:
    """Текстовий перелік для інструмента ``list_custom_tools``."""
    tools = store.tools()
    skills = store.skills()
    lines: list[str] = []
    lines.append(f"Власні інструменти: {len(tools)}")
    if tools:
        for tool in tools:
            runs = f"{tool.ok_runs}/{tool.runs}" if tool.runs else "ще не запускався"
            line = f"  • {CUSTOM_PREFIX}{tool.name} — {tool.description or 'без опису'} [{runs}]"
            if tool.last_error:
                line += f" · остання помилка: {tool.last_error[:120]}"
            lines.append(line)
    else:
        lines.append("  (немає — створи через create_tool)")
    lines.append(f"Власні скіли: {len(skills)}")
    for skill in skills[:12]:
        lines.append(f"  • {skill.name} — {skill.description or 'без опису'}")
    if not skills:
        lines.append("  (немає — створи через create_skill)")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Запуск саморобного інструмента
# ─────────────────────────────────────────────────────────────────────────────

#: Таймаут одного запуску (секунди). Саморобний код може зациклитись або
#: чекати на ввід — це не має вішати агента назавжди.
RUN_TIMEOUT = 60
#: Скільки символів результату повертаємо моделі (решта — обрізається).
MAX_OUTPUT = 20000

#: Скрипт-обгортка: виконується в ОКРЕМОМУ процесі. Ізоляція потрібна, бо
#: код інструмента написала модель: помилка в ньому не має валити IDE, а
#: зациклення — тримати головний потік.
_RUNNER = r'''
import json, sys, traceback
payload = json.loads(sys.stdin.read() or "{}")
code = payload.get("code") or ""
arguments = payload.get("arguments") or {}
namespace = {"__name__": "custom_tool"}
try:
    exec(compile(code, "<custom_tool>", "exec"), namespace)
    func = namespace.get("run")
    if not callable(func):
        raise SystemExit("У коді немає функції run(**arguments).")
    result = func(**arguments)
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    sys.stdout.write(text if isinstance(text, str) else str(text))
except SystemExit as exc:
    sys.stderr.write(str(exc) or "Помилка інструмента")
    raise SystemExit(2)
except Exception:
    sys.stderr.write(traceback.format_exc(limit=6))
    raise SystemExit(3)
'''


def run_custom_tool(tool: CustomTool, arguments: dict[str, Any] | None = None,
                    *, timeout: int = RUN_TIMEOUT) -> tuple[bool, str]:
    """Виконати саморобний інструмент в ОКРЕМОМУ процесі.

    Повертає ``(успіх, текст)``. Процес ізольований навмисно: код написала
    модель, і його помилка не має ламати IDE, а зациклення — вішати агента.
    """
    import subprocess
    import sys

    payload = json.dumps({"code": tool.code, "arguments": dict(arguments or {})},
                         ensure_ascii=False)
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _RUNNER],
            input=payload, text=True, encoding="utf-8", errors="replace",
            capture_output=True, timeout=max(5, int(timeout or RUN_TIMEOUT)),
            cwd=str(tool.folder) if tool.folder else None,
        )
    except subprocess.TimeoutExpired:
        return False, (f"Інструмент «{tool.name}» не завершився за "
                       f"{timeout} с — можливо, чекає на ввід або зациклився.")
    except OSError as exc:
        return False, f"Інструмент «{tool.name}» не запустився: {exc}"
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        detail = err or out or f"код виходу {proc.returncode}"
        return False, f"Інструмент «{tool.name}» впав:\n{detail[-2000:]}"
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT] + f"\n… (обрізано, усього {len(out)} символів)"
    return True, out or f"Інструмент «{tool.name}» завершився без результату."
