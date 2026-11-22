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

#: Слова, які нічого не кажуть про тему запиту. Без них автовибір скілів
#: чіплявся за «цього», «який», «мені» в описах і вмикав не те.
_STOP_WORDS: frozenset[str] = frozenset({
    "цього", "який", "яка", "які", "мені", "тобі", "треба", "можна",
    "якщо", "коли", "чого", "щоб", "буде", "було", "вони", "воно",
    "проєкту", "проекту", "роботи", "робота", "зроби", "зробити",
    "потрібно", "справді", "тільки", "дуже", "тепер", "зараз",
})


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
    # Шлях приходить рядком від панелі скілів і з налаштувань; без
    # приведення ``path.read_text()`` падав ``AttributeError``.
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    name, description, body = parse_skill(text, fallback_name=path.parent.name)
    if not name:
        return None
    return Skill(name=name, description=description, body=body, path=path,
                 source=str(path))


#: Скільки символів інструкції вважаємо «змістовним скілом».
#:
#: Навіщо поріг. У проєкті лежали скіли-заглушки на два рядки (``тест``,
#: ``тест-ім'я``) — залишки перевірок. Вони успішно збігалися з будь-яким
#: запитом про тести й підкладали моделі порожню інструкцію замість
#: справжньої, витісняючи корисний скіл за лімітом місця.
MIN_SKILL_BODY = 80


def is_meaningful(skill: Skill) -> bool:
    """Чи скіл справді щось інструкує (а не заглушка на два рядки)."""
    body = " ".join(str(skill.body or "").split())
    return len(body) >= MIN_SKILL_BODY


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


def skill_path(root: Path, name: str) -> Path:
    """Шлях до ``SKILL.md`` для назви (БЕЗ створення теки чи файлу).

    Той самий слаг, який будує :func:`create_skill` — потрібен, щоб
    перевірити «скіл уже існує?» до запису, нічого не створюючи.
    """
    slug = re.sub(r"[^\w.-]+", "-", (name or "").strip().lower(),
                  flags=re.UNICODE).strip("-")
    if not slug:
        slug = "новий-скіл"
    return Path(root) / SEARCH_DIRS[0] / slug / SKILL_FILE


def create_skill(root: Path, name: str, description: str = "", body: str = "") -> Path:
    """Створити теку скіла й файл SKILL.md. Повертає шлях до файлу."""
    path = skill_path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            make_skill_text(name or path.parent.name, description, body),
            encoding="utf-8")
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
    """Реєстр скілів, який знає робочу теку й тримає позначки «увімкнено».

    Увімкнені скіли ЗБЕРІГАЮТЬСЯ (``.agents/skills-enabled.json`` у робочій
    теці). Раніше позначки жили лише в пам'яті процесу: користувач вмикав
    скіл у панелі, перезапускав IDE — і агент знову працював без інструкцій
    проєкту. Саме тому «скіли є, але агент ними не користується».
    """

    #: Файл зі списком увімкнених скілів (у робочій теці проєкту).
    STATE_FILE = ".agents/skills-enabled.json"

    def __init__(self, root: Path, enabled_names: Iterable[str] = ()) -> None:
        self.root = Path(root)
        self.skills: list[Skill] = []
        #: Увімкнені вручну (з налаштувань або панелі).
        self.enabled: set[str] = set(enabled_names)
        #: Увімкнені автоматично — ті, що стосуються поточного запиту
        #: (див. :meth:`auto_enable`). Окремий набір, щоб автовибір не
        #: переписував ручний вибір людини.
        self.auto: set[str] = set()
        self.reload()
        self._load_state()

    # ── збереження вибору ──────────────────────────────────────────────────
    def _state_path(self) -> Path:
        return self.root / self.STATE_FILE

    def _load_state(self) -> None:
        """Підтягнути збережений список увімкнених скілів."""
        import json

        try:
            raw = self._state_path().read_text(encoding="utf-8")
        except OSError:
            return
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            LOG.debug("Файл увімкнених скілів пошкоджено — ігнорую")
            return
        names = data.get("enabled") if isinstance(data, dict) else data
        if not isinstance(names, list):
            return
        for name in names:
            clean = str(name or "").strip()
            if clean:
                self.enabled.add(clean)
        self._apply_enabled()

    def _save_state(self) -> None:
        """Зберегти вибір людини (автовибір не зберігаємо)."""
        import json

        path = self._state_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Атомарний запис: обірваний файл означав би втрату вибору.
            temp = path.with_suffix(".json.tmp")
            temp.write_text(json.dumps({"enabled": sorted(self.enabled)},
                                       ensure_ascii=False, indent=1),
                            encoding="utf-8")
            temp.replace(path)
        except OSError:
            LOG.debug("Вибір скілів не збережено", exc_info=True)

    def _apply_enabled(self) -> None:
        for skill in self.skills:
            skill.enabled = (skill.name in self.enabled
                             or skill.name in self.auto)

    def reload(self) -> list[Skill]:
        self.skills = discover_skills(self.root)
        self._apply_enabled()
        return self.skills

    def set_root(self, root: Path) -> None:
        self.root = Path(root)
        self.auto.clear()
        self.reload()
        self._load_state()

    def get(self, name: str) -> Optional[Skill]:
        key = (name or "").strip().lower()
        for skill in self.skills:
            if skill.name.lower() == key or skill.folder.lower() == key:
                return skill
        return None

    def toggle(self, name: str, enabled: Optional[bool] = None) -> bool:
        """Увімкнути/вимкнути скіл ВРУЧНУ й зберегти вибір."""
        skill = self.get(name)
        if skill is None:
            return False
        skill.enabled = (not skill.enabled) if enabled is None else bool(enabled)
        if skill.enabled:
            self.enabled.add(skill.name)
            self.auto.discard(skill.name)
        else:
            self.enabled.discard(skill.name)
            self.auto.discard(skill.name)
            skill.enabled = False
        self._save_state()
        return skill.enabled

    def active(self) -> list[Skill]:
        return [skill for skill in self.skills if skill.enabled]

    # ── автовибір під запит ────────────────────────────────────────────────
    def auto_enable(self, text: str, *, limit: int = 3) -> list[Skill]:
        """Увімкнути скіли, які стосуються ЦЬОГО запиту.

        Навіщо. Увімкнені вручну скіли — вибір людини, і він діє завжди. Але
        тримати всі 13 скілів у кожному промпті марнотратно: інструкція про
        збірку релізу не потрібна, коли просять пояснити функцію.

        Тут — дешевий збіг за словами опису скіла й тексту запиту. Це не
        «магія»: скіл з описом «як запускати тести» вмикається на «запусти
        тести», і його інструкція потрапляє в промпт ДО дії.

        Словозміни враховуються грубо, за основою слова: «тестах», «тести» й
        «тестів» мають спільний початок, і без цього запит «виправ баг у
        тестах» не вмикав скіл про тести (заміряно на цьому ж проєкті).

        Повертає список увімкнених автоматично (для журналу).
        """
        body = " ".join(str(text or "").lower().split())
        if not body:
            return []
        words = {part for part in re.split(r"[^\w\u0400-\u04FF]+", body)
                 if len(part) >= 4 and part not in _STOP_WORDS}
        if not words:
            return []
        scored: list[tuple[int, str, Skill]] = []
        for skill in self.skills:
            # Заглушки не підбираємо: вони збігаються з будь-яким запитом і
            # витісняють справжній скіл за лімітом місця в промпті.
            if not is_meaningful(skill):
                continue
            haystack = f"{skill.name} {skill.description}".lower()
            hits = 0
            for word in words:
                if word in haystack:
                    hits += 1
                    continue
                # Основа слова: «тестах» ↔ «тести» ↔ «тестів» мають спільні
                # перші чотири літери. Довша основа не збігалась («теста»
                # проти «тести»), і запит «виправ баг у тестах» не вмикав
                # скіл про тести — заміряно на цьому ж проєкті.
                stem = word[:4]
                if len(stem) >= 4 and stem in haystack:
                    hits += 1
            if not hits:
                continue
            # Ручний вибір уже діє — не дублюємо його в автовибір.
            if skill.name in self.enabled:
                continue
            scored.append((-hits, skill.name, skill))
        scored.sort()
        chosen: list[Skill] = []
        self.auto.clear()
        for _hits, _name, skill in scored[:max(0, int(limit))]:
            self.auto.add(skill.name)
            skill.enabled = True
            chosen.append(skill)
        # Скіли, які більше не актуальні, вимикаємо: інакше автовибір лишався
        # б назавжди й накопичував інструкції з минулих завдань.
        for skill in self.skills:
            if skill.name in self.enabled:
                continue
            if skill.name not in self.auto:
                skill.enabled = False
        return chosen

    def prompt(self) -> str:
        """Блок інструкцій для системного промпта.

        Окремо позначаємо скіл, який користувач увімкнув САМ: його інструкція
        важливіша за автоматично підібрану, і тест-охоронець
        (``test_features``) перевіряє саме такий блок.
        """
        block = skills_prompt(self.skills)
        manual = [skill for skill in self.skills
                  if skill.enabled and skill.name in self.enabled]
        auto = [skill for skill in self.skills
                if skill.enabled and skill.name not in self.enabled]
        parts: list[str] = []
        if manual:
            parts.append(skills_prompt(manual))
        if auto:
            # Автоматично підібрані — окремим блоком: модель має знати, що це
            # доречно ЗАРАЗ, а не постійне правило проєкту.
            parts.append("Скіли, доречні для поточного запиту:\n\n"
                         + "\n\n".join(skill.prompt for skill in auto))
        return "\n\n".join(part for part in parts if part).strip() or block

    def describe(self) -> str:
        """Текстовий перелік — його бачить агент через інструмент list_skills."""
        if not self.skills:
            return "Скілів не знайдено. Додай теку .agents/skills/<назва>/SKILL.md."
        lines = []
        for skill in self.skills:
            mark = "[x]" if skill.enabled else "[ ]"
            source = ""
            if skill.enabled:
                source = " (авто)" if skill.name in self.auto else ""
            lines.append(
                f"{mark} {skill.name}{source} — "
                f"{skill.description or 'без опису'}")
        return "\n".join(lines)
