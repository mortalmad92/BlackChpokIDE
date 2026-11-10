"""Скіли агента: текстові інструкції з ``.agents/skills/<назва>/SKILL.md``.

Формат такий самий, як у інших агентних середовищ: YAML-подібний заголовок
між ``---`` з полями ``name`` і ``description``, далі вільний текст інструкції.
Скіл можна ввімкнути — тоді його інструкція додається до системного промпта,
або вставити як задачу в чат чи чергу.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

LOG = logging.getLogger("blackchpok.skills")

SKILL_FILE = "SKILL.md"
SEARCH_DIRS = (".agents/skills", ".cursor/skills", ".dsh/skills", "skills")


@dataclass
class Skill:
    """Один скіл: назва, опис і повна інструкція."""

    name: str
    description: str = ""
    body: str = ""
    path: Optional[Path] = None
    enabled: bool = False
    source: str = ""

    @property
    def folder(self) -> str:
        return self.path.parent.name if self.path else self.name

    @property
    def prompt(self) -> str:
        """Текст, який додається до системного промпта, коли скіл увімкнено."""
        head = f"СКІЛ: {self.name}"
        if self.description:
            head += f" — {self.description}"
        body = self.body.strip()
        return f"{head}\n{body}" if body else head

    def preview(self, limit: int = 220) -> str:
        text = " ".join(self.body.split())
        return text if len(text) <= limit else text[: limit - 1] + "…"


def _split_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Відокремити заголовок ``---`` від тіла інструкції."""
    raw = (text or "").lstrip("\ufeff")
    if not raw.startswith("---"):
        return {}, raw
    lines = raw.splitlines()
    meta: dict[str, str] = {}
    body_start = 0
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            body_start = index + 1
            break
        key, sep, value = line.partition(":")
        if sep and key.strip():
            meta[key.strip().lower()] = value.strip().strip("'\"")
    else:
        return {}, raw
    return meta, "\n".join(lines[body_start:]).lstrip("\n")


def parse_skill(text: str, *, fallback_name: str = "") -> tuple[str, str, str]:
    """(назва, опис, тіло) з тексту SKILL.md."""
    meta, body = _split_front_matter(text)
    name = (meta.get("name") or fallback_name or "").strip()
    description = (meta.get("description") or "").strip()
    if not description:
        # Перший змістовний рядок без заголовка стає описом.
        for line in body.splitlines():
            stripped = line.strip().lstrip("#").strip()
            if stripped:
                description = stripped[:200]
                break
    return name or fallback_name, description, body


def load_skill(path: Path) -> Optional[Skill]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    name, description, body = parse_skill(text, fallback_name=path.parent.name)
    if not name:
        return None
    return Skill(name=name, description=description, body=body, path=path, source=str(path))


def discover_skills(root: Path) -> list[Skill]:
    """Знайти всі скіли в робочій теці (може бути порожньо)."""
    skills: list[Skill] = []
    seen: set[str] = set()
    root = Path(root)
    for relative in SEARCH_DIRS:
        folder = root / relative
        if not folder.is_dir():
            continue
        try:
            entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        for entry in entries:
            skill_path = entry / SKILL_FILE if entry.is_dir() else entry
            if entry.is_file() and entry.suffix.lower() != ".md":
                continue
            if not skill_path.is_file():
                continue
            skill = load_skill(skill_path)
            if skill is None or skill.name in seen:
                continue
            seen.add(skill.name)
            skills.append(skill)
    return skills


# ─────────────────────────────────────────────────────────────────────────────
# Шаблон нового скіла
# ─────────────────────────────────────────────────────────────────────────────

SKILL_TEMPLATE = """---
name: {name}
description: {description}
---

{body}
"""


def make_skill_text(name: str, description: str, body: str) -> str:
    return SKILL_TEMPLATE.format(
        name=name.strip() or "новий-скіл",
        description=description.strip() or "Короткий опис, коли застосовувати скіл.",
        body=body.strip() or "1. Що зробити.\n2. Як перевірити результат.",
    )


def create_skill(root: Path, name: str, description: str = "", body: str = "") -> Path:
    """Створити теку скіла й файл SKILL.md. Повертає шлях до файлу."""
    slug = re.sub(r"[^\w.-]+", "-", (name or "").strip().lower(), flags=re.UNICODE).strip("-")
    if not slug:
        slug = "новий-скіл"
    folder = Path(root) / SEARCH_DIRS[0] / slug
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / SKILL_FILE
    if not path.exists():
        path.write_text(make_skill_text(name or slug, description, body), encoding="utf-8")
    return path


def skills_prompt(skills: Iterable[Skill]) -> str:
    """Спільний блок інструкцій з увімкнених скілів."""
    active = [skill for skill in skills if skill.enabled]
    if not active:
        return ""
    chunks = [skill.prompt for skill in active]
    return "Активні скіли (виконуй їхні інструкції):\n\n" + "\n\n".join(chunks)


def tool_schemas() -> list[dict[str, object]]:
    """Схеми інструментів для агента: перелік і запуск скіла."""
    return [
        {
            "type": "function",
            "function": {
                "name": "list_skills",
                "description": "Показати доступні скіли (інструкції) робочої теки.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_skill",
                "description": "Прочитати повну інструкцію скіла за назвою.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "Назва скіла"}},
                    "required": ["name"],
                },
            },
        },
    ]


class SkillBook:
    """Реєстр скілів, який знає робочу теку й тримає позначки «увімкнено»."""

    def __init__(self, root: Path, enabled_names: Iterable[str] = ()) -> None:
        self.root = Path(root)
        self.skills: list[Skill] = []
        self.enabled: set[str] = set(enabled_names)
        self.reload()

    def reload(self) -> list[Skill]:
        self.skills = discover_skills(self.root)
        for skill in self.skills:
            skill.enabled = skill.name in self.enabled
        return self.skills

    def set_root(self, root: Path) -> None:
        self.root = Path(root)
        self.reload()

    def get(self, name: str) -> Optional[Skill]:
        key = (name or "").strip().lower()
        for skill in self.skills:
            if skill.name.lower() == key or skill.folder.lower() == key:
                return skill
        return None

    def toggle(self, name: str, enabled: Optional[bool] = None) -> bool:
        skill = self.get(name)
        if skill is None:
            return False
        skill.enabled = (not skill.enabled) if enabled is None else bool(enabled)
        if skill.enabled:
            self.enabled.add(skill.name)
        else:
            self.enabled.discard(skill.name)
        return skill.enabled

    def active(self) -> list[Skill]:
        return [skill for skill in self.skills if skill.enabled]

    def prompt(self) -> str:
        return skills_prompt(self.skills)

    def describe(self) -> str:
        """Текстовий перелік — його бачить агент через інструмент list_skills."""
        if not self.skills:
            return "Скілів не знайдено. Додай теку .agents/skills/<назва>/SKILL.md."
        lines = []
        for skill in self.skills:
            mark = "[x]" if skill.enabled else "[ ]"
            lines.append(f"{mark} {skill.name} — {skill.description or 'без опису'}")
        return "\n".join(lines)
