"""Офлайн-роутер: виконує типові команди без моделі.

Використовує ``vibe_router`` з репозиторію, якщо він поруч (той самий набір
українських фраз, що й MCP-сервер), інакше — власні правила. Потрібен, коли
LM Studio або Ollama не запущені.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from .agent_tools import ToolRegistry

LOG = logging.getLogger("blackchpok.offline")


class OfflinePlanner:
    """Перетворює фразу українською на послідовність викликів інструментів."""

    def __init__(self, workspace: Path, registry: ToolRegistry) -> None:
        self.workspace = workspace
        self.registry = registry
        self._external = _load_external_rules()

    def plan(self, text: str) -> list[tuple[str, dict[str, Any]]]:
        phrase = (text or "").strip()
        if not phrase:
            return []
        low = phrase.lower()
        path = _extract_path(phrase)

        if _has(low, "дерево проєкту", "дерево проекту", "структура проєкту", "структура проекту", "project tree"):
            return [("project_tree", {"depth": 3})]
        if _has(low, "git status", "стан git", "стан гіт", "що змінилось"):
            return [("git_status", {})]
        if _has(low, "git diff", "покажи диф", "різниця git"):
            return [("git_diff", {})]
        if _has(low, "покажи файли", "список файлів", "що в папці", "вміст папки", "ls", "dir"):
            return [("list_dir", {"path": path or "."})]
        if _has(low, "перевір синтаксис", "syntax check", "чи компілюється"):
            if not path:
                return []
            return [("python_check", {"path": path})]
        if _has(low, "запусти", "виконай", "run "):
            command = _extract_command(phrase)
            if command:
                return [("run_command", {"command": command})]
        if _has(low, "знайди файли", "які файли", "find files"):
            pattern = _extract_pattern(phrase) or "*.py"
            return [("find_files", {"pattern": pattern})]
        if _has(low, "знайди", "пошукай", "search", "grep"):
            needle = _extract_needle(phrase)
            if needle:
                return [("search_text", {"query": needle})]
        if path and _has(low, "прочитай", "покажи", "відкрий", "read"):
            return [("read_file", {"path": path})]
        if path:
            # файл названо без дієслова — покажемо вміст
            return [("read_file", {"path": path})]
        return []


def _has(low: str, *needles: str) -> bool:
    return any(needle in low for needle in needles)


_PATH = re.compile(
    r"((?:[\w.\-]+[\\/])*[\w.\-]+\.(?:py|pyi|js|ts|tsx|jsx|json|md|txt|html|css|yml|yaml|toml|ini|sql|ps1|bat|cmd|cfg|cs|cpp|c|h|go|rs|java))",
    re.IGNORECASE,
)


def _extract_path(text: str) -> str:
    match = _PATH.search(text)
    if not match:
        return ""
    return match.group(1).strip("`\"'").replace("\\", "/")


_COMMAND = re.compile(
    r"(?:запусти|виконай|run)\s+(?:команду\s+)?[«\"']?(.+?)[»\"']?$",
    re.IGNORECASE,
)


def _extract_command(text: str) -> str:
    match = _COMMAND.search(text.strip())
    if not match:
        return ""
    command = match.group(1).strip(" `\"'")
    if not command or re.search(r"[А-Яа-яІіЇїЄєҐґ]{4,}", command):
        return ""
    return command


def _extract_pattern(text: str) -> str:
    match = re.search(r"(\*[\w.*?/\-]+|[\w\-]+\.(?:py|js|ts|json|md|txt))", text, re.IGNORECASE)
    return match.group(1) if match else ""


def _extract_needle(text: str) -> str:
    quoted = re.search(r"[«\"']([^»\"']{2,})[»\"']", text)
    if quoted:
        return quoted.group(1)
    match = re.search(r"(?:знайди|пошукай|search|grep)\s+(?:текст\s+|у файлах\s+|в коді\s+)?([^\n]+)", text, re.IGNORECASE)
    if not match:
        return ""
    needle = match.group(1).strip(" .,:;«»\"'")
    if len(needle) < 2:
        return ""
    return needle


def _load_external_rules():
    """Спробувати підключити vibe_router з репозиторію (необов'язково)."""
    try:
        import sys

        repo_root = Path(__file__).resolve().parent.parent
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        import vibe_router  # type: ignore

        return vibe_router
    except Exception as exc:  # noqa: BLE001 - модуль необов'язковий
        LOG.debug("vibe_router недоступний: %s", exc)
        return None


def describe(text: str) -> dict[str, Any]:
    """Для діагностики: що роутер зрозумів у фразі."""
    planner = OfflinePlanner(Path.cwd(), ToolRegistry(Path.cwd()))
    return {"steps": planner.plan(text), "external": bool(planner._external)}
