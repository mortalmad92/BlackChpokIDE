"""Інструменти пам'яті NEUROMESH для агента (``memory_*``).

Реалізує повний набір, який вимагає продукт:

``memory_search``           знайти релевантні спогади
``memory_recall``           дістати спогад із зв'язками й історією
``memory_store``            запам'ятати твердження
``memory_link``             зв'язати два спогади
``memory_update``           оновити зміст (із збереженням версії)
``memory_verify``           підтвердити достовірність
``memory_explain``          пояснити походження й впевненість
``memory_predict``          спрогнозувати потрібний контекст
``memory_project_context``  зібрати контекст під бюджет вікна
``memory_task_history``     історія кроків завдання
``memory_recover``          стан/бекапи/відновлення
``memory_feedback``         оцінити корисність спогаду

Кожен інструмент:
* валідовує аргументи за JSON-схемою (див. ``MEMORY_TOOL_SCHEMAS``);
* повертає ТЕКСТ (так вимагає наявний ``ToolResult``) із людино-читним
  підсумком, а структуровані дані лишаються в сервісі;
* ніколи не вигадує успіх: якщо пам'ять недоступна, повертає «✗ …», що
  наявний реєстр трактує як невдачу.

Модуль не залежить від tkinter: його використовують і агент, і панель
NEUROMESH, і тести.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Sequence

LOG = logging.getLogger("blackchpok.pcmm.tools")

#: Скільки результатів віддаємо в тексті (решта — у структурі).
TEXT_LIMIT = 6
#: Скільки символів одного спогаду показуємо в текстовій відповіді.
SNIPPET = 300


class MemoryToolError(RuntimeError):
    """Інструмент пам'яті не може виконати операцію."""


# ─────────────────────────────────────────────────────────────────────────────
# Валідація аргументів
# ─────────────────────────────────────────────────────────────────────────────

_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


@dataclass
class ValidationError:
    """Одна проблема в аргументах."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> list[ValidationError]:
    """Перевірити аргументи за JSON-схемою (підмножина стандарту).

    Підтримуються ``type``, ``required``, ``enum``, ``minimum``/``maximum``,
    ``items`` і вкладені ``properties``. Цього достатньо для наших схем і
    не тягне зовнішніх залежностей.
    """
    errors: list[ValidationError] = []
    # Схема може бути як «голим» описом параметрів, так і повною
    # OpenAI-схемою інструмента (``{"type": "function", "function": {...}}``).
    node: dict[str, Any] = schema or {}
    if isinstance(node.get("function"), dict):
        node = node["function"]
    # «Голий» опис параметрів розпізнаємо за наявністю ``properties``.
    if "parameters" not in node and "properties" in node:
        parameters = node
    else:
        parameters = node.get("parameters") or {}
    properties = parameters.get("properties") or {}
    required = parameters.get("required") or []

    for name in required:
        if name not in arguments or arguments[name] in (None, "", [], {}):
            errors.append(ValidationError(name, "обов'язковий аргумент відсутній"))

    for name, value in arguments.items():
        spec = properties.get(name)
        if spec is None:
            continue                       # невідомі поля ігноруємо
        expected = spec.get("type")
        if expected and expected in _TYPES:
            # bool — підклас int, тому перевіряємо окремо.
            if expected == "integer" and isinstance(value, bool):
                errors.append(ValidationError(name, "очікувалось ціле число"))
                continue
            if not isinstance(value, _TYPES[expected]):
                errors.append(ValidationError(
                    name, f"очікувався тип {expected}, отримано {type(value).__name__}"))
                continue
        if "enum" in spec and value not in spec["enum"]:
            errors.append(ValidationError(
                name, f"допустимі значення: {', '.join(map(str, spec['enum']))}"))
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in spec and value < spec["minimum"]:
                errors.append(ValidationError(name, f"мінімум {spec['minimum']}"))
            if "maximum" in spec and value > spec["maximum"]:
                errors.append(ValidationError(name, f"максимум {spec['maximum']}"))
        if isinstance(value, list) and spec.get("items"):
            item_type = spec["items"].get("type")
            if item_type in _TYPES:
                for index, item in enumerate(value):
                    if not isinstance(item, _TYPES[item_type]):
                        errors.append(ValidationError(
                            f"{name}[{index}]", f"очікувався тип {item_type}"))
                        break
    return errors


# ─────────────────────────────────────────────────────────────────────────────
# Схеми інструментів
# ─────────────────────────────────────────────────────────────────────────────

def _memory_kinds() -> list[str]:
    from .models import KINDS

    return list(KINDS)


MEMORY_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": (
                "Пошук у довготривалій пам'яті NEUROMESH: факти, рішення, помилки, "
                "виправлення, обмеження, залежності файлів. Повертає релевантні "
                "спогади з поясненням, чому кожен знайдено."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Що шукати"},
                    "limit": {"type": "integer", "description": "Скільки результатів (1-25)",
                              "minimum": 1, "maximum": 25},
                    "kind": {"type": "string", "description": "Фільтр за типом спогаду",
                             "enum": _memory_kinds()},
                    "task": {"type": "string", "description": "Назва поточного завдання"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_recall",
            "description": "Дістати спогад повністю: текст, зв'язки, сусіди, історія версій.",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "description": "Ідентифікатор спогаду"},
                },
                "required": ["memory_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_store",
            "description": (
                "Запам'ятати твердження надовго. Вказуй джерело: файл і рядок, "
                "інструмент або повідомлення користувача."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Саме твердження"},
                    "kind": {"type": "string", "enum": _memory_kinds(),
                             "description": "Тип: fact, decision, error, fix, task, "
                                            "dependency, tool, constraint, change, preference"},
                    "source": {"type": "string", "description": "Звідки взято"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1,
                                   "description": "Впевненість 0..1"},
                    "files": {"type": "array", "items": {"type": "string"},
                              "description": "Пов'язані файли"},
                    "task": {"type": "string", "description": "Завдання"},
                    "tags": {"type": "array", "items": {"type": "string"},
                             "description": "Теги"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_link",
            "description": "Зв'язати два спогади (caused, fixed_by, depends_on, "
                           "contradicts, supersedes, related, part_of).",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {"type": "string", "description": "Спогад-джерело"},
                    "dst": {"type": "string", "description": "Спогад-ціль"},
                    "relation": {"type": "string",
                                 "enum": ["caused", "fixed_by", "depends_on",
                                          "contradicts", "supersedes", "related",
                                          "part_of"],
                                 "description": "Тип зв'язку"},
                    "weight": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["src", "dst"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_update",
            "description": "Оновити зміст спогаду. Попередня версія зберігається в історії.",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string"},
                    "content": {"type": "string", "description": "Новий текст"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason": {"type": "string", "description": "Чому змінюємо"},
                },
                "required": ["memory_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_verify",
            "description": "Підтвердити достовірність спогаду (підвищує впевненість).",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "note": {"type": "string", "description": "Чим підтверджено"},
                },
                "required": ["memory_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_explain",
            "description": "Пояснити походження спогаду: джерело, історія, на чому "
                           "тримається впевненість.",
            "parameters": {
                "type": "object",
                "properties": {"memory_id": {"type": "string"}},
                "required": ["memory_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_predict",
            "description": "Спрогнозувати, який контекст знадобиться далі "
                           "(файли й спогади), за поточними файлами та завданням.",
            "parameters": {
                "type": "object",
                "properties": {
                    "files": {"type": "array", "items": {"type": "string"},
                              "description": "Відкриті файли"},
                    "task": {"type": "string"},
                    "query": {"type": "string", "description": "Що робимо зараз"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_project_context",
            "description": "Зібрати контекст зі спогадів під бюджет вікна моделі "
                           "й пояснити, що увійшло.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Тема запиту"},
                    "window": {"type": "integer", "description": "Розмір вікна в токенах",
                               "minimum": 256, "maximum": 2000000},
                    "task": {"type": "string"},
                    "files": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_task_history",
            "description": "Історія кроків завдання: що робили, які файли й інструменти.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Назва завдання (порожньо = усі)"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_recover",
            "description": "Стан пам'яті, цілісність, бекапи й відновлення.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string",
                               "enum": ["status", "integrity", "backup", "restore",
                                        "consolidate", "migrate_legacy"],
                               "description": "Що зробити"},
                    "path": {"type": "string", "description": "Файл бекапу для restore"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_feedback",
            "description": "Оцінити, чи спогад був корисний (впливає на впевненість).",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string"},
                    "useful": {"type": "boolean"},
                    "note": {"type": "string"},
                },
                "required": ["memory_id", "useful"],
            },
        },
    },
]

#: Імена всіх інструментів пам'яті.
MEMORY_TOOL_NAMES: tuple[str, ...] = tuple(
    schema["function"]["name"] for schema in MEMORY_TOOL_SCHEMAS
)

#: Схеми за іменем (для валідації).
MEMORY_SCHEMA_BY_NAME: dict[str, dict[str, Any]] = {
    schema["function"]["name"]: schema for schema in MEMORY_TOOL_SCHEMAS
}


# ─────────────────────────────────────────────────────────────────────────────
# Виконання
# ─────────────────────────────────────────────────────────────────────────────

def _snippet(text: str, limit: int = SNIPPET) -> str:
    body = " ".join((text or "").split())
    return body if len(body) <= limit else body[:limit] + "…"


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)[:6000]


class MemoryTools:
    """Виконавці ``memory_*`` поверх :class:`~.service.Neuromesh`."""

    def __init__(self, service: Any, *, max_results: int = TEXT_LIMIT) -> None:
        self.service = service
        self.max_results = max_results
        self._handlers: dict[str, Callable[..., str]] = {
            "memory_search": self.search,
            "memory_recall": self.recall,
            "memory_store": self.store,
            "memory_link": self.link,
            "memory_update": self.update,
            "memory_verify": self.verify,
            "memory_explain": self.explain,
            "memory_predict": self.predict,
            "memory_project_context": self.project_context,
            "memory_task_history": self.task_history,
            "memory_recover": self.recover,
            "memory_feedback": self.feedback,
        }

    # ── реєстрація ────────────────────────────────────────────────────────
    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._handlers)

    @property
    def handlers(self) -> dict[str, Callable[..., str]]:
        """Копія мапи «назва → обробник» (для реєстру інструментів)."""
        return dict(self._handlers)

    def handler(self, name: str) -> Callable[..., str] | None:
        return self._handlers.get(name)

    def call(self, name: str, arguments: dict[str, Any] | str | None = None) -> str:
        """Виконати інструмент із валідацією аргументів."""
        handler = self._handlers.get(name)
        if handler is None:
            return f"✗ Невідомий інструмент пам'яті: {name}"
        payload: dict[str, Any]
        if isinstance(arguments, str):
            try:
                payload = json.loads(arguments or "{}")
            except json.JSONDecodeError as exc:
                return f"✗ Аргументи не JSON: {exc}"
        else:
            payload = dict(arguments or {})
        schema = MEMORY_SCHEMA_BY_NAME.get(name)
        if schema is not None:
            errors = validate_arguments(schema, payload)
            if errors:
                return "✗ Неправильні аргументи: " + "; ".join(str(item) for item in errors)
        try:
            return handler(**payload)
        except TypeError as exc:
            return f"✗ Аргументи не підходять: {exc}"
        except Exception as exc:                     # noqa: BLE001 - агент має бачити все
            LOG.debug("Інструмент %s упав", name, exc_info=True)
            return f"✗ {type(exc).__name__}: {exc}"

    # ── окремі операції ───────────────────────────────────────────────────
    def search(self, query: str, limit: int = 8, kind: str = "",
               task: str = "") -> str:
        kinds = [kind] if kind else None
        data = self.service.search(query, limit=max(1, int(limit)), kinds=kinds,
                                   task=task)
        hits = data.get("hits") or []
        if not hits:
            return f"Пам'ять: нічого не знайдено за запитом «{_snippet(query, 80)}»."
        lines = [f"Знайдено {len(hits)} (політика: {data.get('policy', '')}):"]
        for hit in hits[:self.max_results]:
            memory = hit["memory"]
            lines.append(
                f"• [{memory['id']}] {memory['kind']} "
                f"(впевненість {memory['confidence']}): {_snippet(memory['content'])}\n"
                f"  чому: {hit.get('explanation', '')}"
            )
        return "\n".join(lines)

    def recall(self, memory_id: str) -> str:
        data = self.service.recall(memory_id)
        if not data:
            return f"✗ Спогад {memory_id} не знайдено."
        memory = data["memory"]
        lines = [
            f"[{memory['id']}] {memory['kind']} · впевненість {memory['confidence']}",
            f"Джерело: {memory.get('provenance') or memory.get('source') or 'невідомо'}",
            memory["content"][:1200],
        ]
        links = data.get("links") or {}
        if links.get("out") or links.get("in"):
            lines.append("Зв'язки:")
            for item in links.get("out", []):
                lines.append(f"  → {item['relation']} → {item['other']} ({item['weight']})")
            for item in links.get("in", []):
                lines.append(f"  ← {item['relation']} ← {item['other']} ({item['weight']})")
        neighbours = data.get("neighbours") or {}
        if neighbours:
            lines.append(f"Сусіди в графі: {len(neighbours)}")
        versions = data.get("versions") or []
        if versions:
            lines.append(f"Версій в історії: {len(versions)}")
        return "\n".join(lines)

    def store(self, content: str, kind: str = "fact", source: str = "",
              confidence: float = 0.7, files: Sequence[str] | None = None,
              task: str = "", tags: Sequence[str] | None = None) -> str:
        outcome = self.service.remember(
            content, kind=kind or "fact", source=source,
            provenance=source, confidence=float(confidence),
            task=task, files=files or [], tags=tags or [])
        memory = outcome["memory"]
        if outcome.get("duplicate"):
            return (f"Уже знаю це (спогад {memory['id']}, впевненість "
                    f"{memory['confidence']:.2f}). Підтверджено ще раз.")
        conflicts = outcome.get("conflicts") or []
        suffix = ""
        if conflicts:
            suffix = ("\n⚠ Можливий конфлікт із: " + ", ".join(conflicts[:5])
                      + ". Перевір memory_explain перед зміною рішення.")
        return f"Запам'ятав [{memory['id']}] {memory['kind']}: {_snippet(content)}{suffix}"

    def link(self, src: str, dst: str, relation: str = "related",
             weight: float = 0.6) -> str:
        ok = self.service.link(src, dst, relation, float(weight))
        if not ok:
            return f"✗ Не вдалось зв'язати {src} → {dst}."
        return f"Зв'язав {src} —[{relation}]→ {dst}."

    def update(self, memory_id: str, content: str = "",
               confidence: float | None = None, reason: str = "") -> str:
        updated = self.service.update(memory_id, content=content,
                                      confidence=confidence, reason=reason)
        if updated is None:
            return f"✗ Спогад {memory_id} не знайдено."
        return (f"Оновив [{updated['id']}]: {_snippet(updated['content'])}\n"
                f"Попередня версія збережена в історії.")

    def verify(self, memory_id: str, confidence: float | None = None,
               note: str = "") -> str:
        updated = self.service.verify(memory_id, confidence=confidence, note=note)
        if updated is None:
            return f"✗ Спогад {memory_id} не знайдено."
        return (f"Підтвердив [{updated['id']}], впевненість стала "
                f"{updated['confidence']:.2f}.")

    def explain(self, memory_id: str) -> str:
        data = self.service.explain(memory_id)
        if not data:
            return f"✗ Спогад {memory_id} не знайдено."
        memory = data["memory"]
        lines = [
            f"[{memory['id']}] {memory['kind']}: {_snippet(memory['content'], 400)}",
            f"Походження: {data['provenance']}",
            f"Впевненість: {data['why_confidence']}",
        ]
        for event in (data.get("history") or [])[:8]:
            lines.append(f"  · {event.get('action')}: {str(event.get('detail'))[:120]}")
        for version in (data.get("versions") or [])[:5]:
            lines.append(f"  ↺ версія: {_snippet(str(version.get('content')), 120)}"
                         f" ({version.get('reason') or 'без причини'})")
        return "\n".join(lines)

    def predict(self, files: Sequence[str] | None = None, task: str = "",
                query: str = "") -> str:
        data = self.service.predict(current_files=files or [], task=task, query=query)
        memories = data.get("memories") or []
        lines = [f"Прогноз (впевненість {data.get('confidence', 0)}): "
                 f"{data.get('reason') or 'сигналів мало'}"]
        if data.get("files"):
            lines.append("Файли, які ймовірно знадобляться:")
            for path in data["files"][:8]:
                lines.append(f"  · {path}")
        if memories:
            lines.append("Спогади, які варто підняти:")
            for item in memories[:self.max_results]:
                lines.append(f"  • [{item['memory']['id']}] "
                             f"{_snippet(item['memory']['content'], 200)}")
        else:
            lines.append("Спогадів для прогнозу поки немає.")
        return "\n".join(lines)

    def project_context(self, query: str, window: int = 8192, task: str = "",
                        files: Sequence[str] | None = None) -> str:
        bundle = self.service.project_context(query=query, window=int(window),
                                             task=task, files=files or [])
        lines = [
            f"Контекст із пам'яті: {bundle.report.used}/{bundle.report.budget} токенів "
            f"({'-точно' if bundle.report.exact else '-оцінка'}), "
            f"зекономлено {bundle.tokens_saved}.",
        ]
        if bundle.note:
            lines.append(bundle.note)
        if bundle.text:
            lines.append("")
            lines.append(bundle.text)
        for line in bundle.report.explain()[:self.max_results]:
            lines.append(f"  {line}")
        return "\n".join(lines)

    def task_history(self, task: str = "", limit: int = 30) -> str:
        rows = self.service.task_history(task=task, limit=int(limit))
        if not rows:
            return "Історія завдань порожня."
        lines = [f"Останні кроки ({len(rows)}):"]
        for row in rows[:min(self.max_results * 3, 30)]:
            files = row.get("files") or "[]"
            try:
                files_list = json.loads(files) if isinstance(files, str) else files
            except json.JSONDecodeError:
                files_list = []
            extra = f" · файли: {', '.join(files_list)}" if files_list else ""
            lines.append(f"  · [{row.get('status')}] {row.get('action')}"
                         f" — {_snippet(str(row.get('detail')), 120)}{extra}")
        return "\n".join(lines)

    def recover(self, action: str = "status", path: str = "") -> str:
        if action == "integrity":
            data = self.service.integrity()
            verdict = "гаразд" if data.get("ok") else "ПРОБЛЕМИ"
            problems = "; ".join(data.get("problems") or [])
            return (f"Цілісність: {verdict} (версія схеми {data.get('version')})\n"
                    f"База: {data.get('path')}\n{problems}".strip())
        if action == "backup":
            data = self.service.backup()
            return f"Бекап створено: {data['path']} ({data['size_bytes']} байт)"
        if action == "restore":
            if not path:
                return "✗ Для відновлення вкажи шлях до бекапу."
            ok = self.service.restore(path)
            return "Відновлено." if ok else "✗ Відновлення не вдалось."
        if action == "consolidate":
            report = self.service.consolidate()
            return ("Консолідація: злито "
                    f"{len(report.get('merged') or [])}, позначено застарілими "
                    f"{len(report.get('superseded') or [])}, конфліктів "
                    f"{report.get('contradictions', 0)}.")
        if action == "migrate_legacy":
            data = self.service.migrate_legacy_rag()
            return (f"Перенесено зі старого RAG: {data['imported']} "
                    f"(пропущено дублів {data['skipped']}) "
                    f"з {', '.join(data.get('sources') or []) or 'нічого'}")
        status = self.service.status()
        counts = status.get("counts") or {}
        backups = self.service.backups()
        return (f"Пам'ять: {counts.get('memories', 0)} спогадів "
                f"({counts.get('active', 0)} активних), "
                f"{counts.get('links', 0)} зв'язків, "
                f"{counts.get('conflicts', 0)} конфліктів, "
                f"{counts.get('with_vectors', 0)} з векторами.\n"
                f"Точність прогнозів: {status.get('prediction', {}).get('precision', 0)} "
                f"на {status.get('prediction', {}).get('samples', 0)} вимірах.\n"
                f"Бекапів: {len(backups)}.")

    def feedback(self, memory_id: str, useful: bool, note: str = "") -> str:
        data = self.service.feedback(memory_id, useful=bool(useful), note=note)
        if not data.get("ok"):
            return f"✗ Спогад {memory_id} не знайдено."
        return ("Вдячний: впевненість скориговано."
                if useful else "Врахую: знижую впевненість цього спогаду.")


def memory_tools_for(service: Any) -> MemoryTools:
    """Створити набір інструментів для сервісу пам'яті."""
    return MemoryTools(service)


__all__ = [
    "MEMORY_SCHEMA_BY_NAME",
    "MEMORY_TOOL_NAMES",
    "MEMORY_TOOL_SCHEMAS",
    "MemoryToolError",
    "MemoryTools",
    "SNIPPET",
    "TEXT_LIMIT",
    "ValidationError",
    "memory_tools_for",
    "validate_arguments",
]
