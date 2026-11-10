"""Міст до NEUROMESH: пам'ять бере участь у розумінні, а не лише в пошуку.

До цього шару пам'ять працювала «за викликом»: модель мала сама здогадатись
викликати ``memory_search``. Через це агент:

* перепитував те, що людина вже пояснювала в іншому чаті;
* повторював помилки, які вже були виправлені;
* не знав обмежень проєкту, поки про них не нагадаєш.

Тут пам'ять підключається до САМОГО розуміння запиту:

1. **перед ходом** — релевантні спогади додаються до промпту (з бюджетом
   вікна моделі, а не «все, що знайшлось»);
2. **обмеження** — критичні обмеження проєкту потрапляють у
   :class:`conversation.ConversationState` і діють до кінця завдання;
3. **після ходу** — факт «що змінили і як перевірили» запам'ятовується сам,
   щоб наступний хід не починався з нуля.

Навмисні обмеження, щоб це не стало «магією»:

* нічого не зберігається, якщо користувач сказав «не зберігай»;
* у пам'ять іде лише те, що підтверджено результатом інструмента (файл
  справді змінено, перевірка справді пройшла);
* помилка пам'яті не ламає хід агента — без неї все працює як раніше.

Модуль не тягне tkinter: його можна перевірити підробленим сервісом.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "MemoryBridge",
    "MemorySnapshot",
    "describe_snapshot",
    "format_memories",
]

LOG = logging.getLogger("blackchpok.memory_bridge")

#: Скільки спогадів максимум підкладаємо в промпт.
#:
#: Мало — бо пам'ять має допомагати, а не займати вікно. Кожен спогад
#: — це реально перевірений факт, тому шести зазвичай досить.
DEFAULT_LIMIT = 6

#: Скільки токенів максимум віддаємо пам'яті в контексті (частка вікна).
MEMORY_WINDOW_SHARE = 0.15

#: З якою впевненістю зберігаємо власний висновок агента.
#:
#: Не 1.0: агент зберігає ВЛАСНИЙ висновок, і людина має мати змогу його
#: виправити. Підтверджений користувачем факт підвищує впевненість.
SELF_CONFIDENCE = 0.6


@dataclass
class MemorySnapshot:
    """Що пам'ять дала для ЦЬОГО ходу (і чому саме це)."""

    memories: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    #: Токени, які зайняла пам'ять (0 — якщо невідомо).
    tokens: int = 0
    #: Спогади, які не влізли в бюджет (щоб не вдавати, що їх немає).
    dropped: int = 0
    note: str = ""

    @property
    def empty(self) -> bool:
        return not self.memories and not self.constraints

    def prompt_block(self) -> str:
        """Текст для моделі: факти й обмеження окремо."""
        parts: list[str] = []
        if self.constraints:
            parts.append("Обмеження проєкту з пам'яті (не порушуй):")
            parts.extend(f"- {item}" for item in self.constraints)
        if self.memories:
            parts.append("Що вже відомо про цей проєкт (з пам'яті):")
            parts.extend(f"- {item}" for item in self.memories)
        if self.dropped:
            parts.append(f"(ще {self.dropped} спогадів не вмістились у контекст)")
        return "\n".join(parts)


def format_memories(hits: Iterable[Mapping[str, Any]], *,
                    limit: int = DEFAULT_LIMIT) -> list[str]:
    """Перетворити результати пошуку пам'яті в людські рядки.

    Пам'ять повертає структуровані спогади; моделі ж потрібні речення.
    Джерело додаємо, бо воно — частина довіри до факту.
    """
    lines: list[str] = []
    for hit in hits or ():
        if not isinstance(hit, Mapping):
            continue
        memory = hit.get("memory") if isinstance(hit.get("memory"), Mapping) else hit
        content = str(memory.get("content") or "").strip()
        if not content:
            continue
        content = " ".join(content.split())
        if len(content) > 220:
            content = content[:219] + "…"
        source = str(memory.get("source") or "").strip()
        kind = str(memory.get("kind") or "").strip()
        suffix_bits = [item for item in (kind, source) if item]
        if suffix_bits:
            content += f" [{', '.join(suffix_bits)}]"
        lines.append(content)
        if len(lines) >= limit:
            break
    return lines


def describe_snapshot(snapshot: MemorySnapshot) -> str:
    """Один рядок для журналу: що пам'ять дала цього разу."""
    if snapshot.empty:
        return "Пам'ять: нічого релевантного."
    parts = [f"Пам'ять: {len(snapshot.memories)} спогадів"]
    if snapshot.constraints:
        parts.append(f"{len(snapshot.constraints)} обмежень")
    if snapshot.tokens:
        parts.append(f"~{snapshot.tokens} токенів")
    if snapshot.dropped:
        parts.append(f"{snapshot.dropped} не вмістилось")
    return ", ".join(parts) + "."


class MemoryBridge:
    """Підключення NEUROMESH до розуміння запиту й до запису результатів.

    ``service`` — будь-який об'єкт із методами ``search`` / ``project_context``
    / ``remember`` / ``record_task``. Саме такий інтерфейс має
    :class:`pcmm.service.Neuromesh`, але міст від нього не залежить:
    підроблений сервіс у тестах працює так само.
    """

    def __init__(self, service: Any = None) -> None:
        self.service = service

    # ── доступність ───────────────────────────────────────────────────────
    def ready(self) -> bool:
        """Чи можна користуватись пам'яттю (сервіс є й живий)."""
        if self.service is None:
            return False
        return any(callable(getattr(self.service, name, None))
                   for name in ("search", "project_context"))

    def attach(self, service: Any) -> None:
        """Підключити (або відключити, передавши ``None``) сервіс."""
        self.service = service

    # ── читання ───────────────────────────────────────────────────────────
    def snapshot(
        self,
        query: str,
        *,
        task: str = "",
        files: Sequence[str] = (),
        window: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> MemorySnapshot:
        """Що пам'ять знає про цей запит — з бюджетом під вікно моделі.

        Спершу пробуємо ``project_context`` (він сам стежить за бюджетом і
        додає критичні обмеження). Якщо його немає — звичайний пошук.
        Помилка пам'яті не має ламати хід: повертаємо порожній знімок.
        """
        if not self.ready():
            return MemorySnapshot(note="пам'ять не підключена")
        clean_query = " ".join((query or "").split())
        if not clean_query:
            return MemorySnapshot()

        if callable(getattr(self.service, "project_context", None)) and window > 0:
            snapshot = self._from_context(clean_query, task=task, files=files,
                                          window=window)
            if not snapshot.empty:
                return snapshot

        return self._from_search(clean_query, task=task, files=files, limit=limit)

    def _from_context(self, query: str, *, task: str,
                      files: Sequence[str], window: int) -> MemorySnapshot:
        """Контекст із губернатором бюджету: обмеження + релевантні факти."""
        try:
            bundle = self.service.project_context(
                query=query, window=max(256, int(window)), task=task,
                files=list(files), max_share=MEMORY_WINDOW_SHARE)
        except Exception:                            # noqa: BLE001
            LOG.info("project_context пам'яті не вдався", exc_info=True)
            return MemorySnapshot()

        report = getattr(bundle, "report", None)
        pieces = list(getattr(report, "pieces", ()) or ())
        dropped = len(list(getattr(report, "dropped", ()) or ()))
        tokens = int(getattr(report, "used", 0) or 0)

        memories: list[str] = []
        constraints: list[str] = []
        for piece in pieces:
            text = " ".join(str(getattr(piece, "text", "") or "").split())
            if not text:
                continue
            if len(text) > 220:
                text = text[:219] + "…"
            critical = bool(getattr(piece, "critical", False))
            label = str(getattr(piece, "label", "") or "")
            reason = str(getattr(piece, "reason", "") or "")
            body = f"{text} [{label}]" if label else text
            if critical or "обмеження" in reason:
                constraints.append(body)
            else:
                memories.append(body)
        return MemorySnapshot(memories=memories[:DEFAULT_LIMIT],
                              constraints=constraints[:DEFAULT_LIMIT],
                              tokens=tokens, dropped=dropped,
                              note=str(getattr(bundle, "note", "") or ""))

    def _from_search(self, query: str, *, task: str, files: Sequence[str],
                     limit: int) -> MemorySnapshot:
        """Запасний шлях: звичайний пошук по пам'яті."""
        try:
            result = self.service.search(query, limit=max(1, int(limit)),
                                         task=task, files=list(files) or None)
        except TypeError:
            # Сервіс старого зразка без ``files`` — не вважаємо це збоєм.
            try:
                result = self.service.search(query, limit=max(1, int(limit)))
            except Exception:                        # noqa: BLE001
                LOG.info("Пошук по пам'яті не вдався", exc_info=True)
                return MemorySnapshot()
        except Exception:                            # noqa: BLE001
            LOG.info("Пошук по пам'яті не вдався", exc_info=True)
            return MemorySnapshot()

        hits: Any = []
        if isinstance(result, Mapping):
            hits = result.get("hits") or []
        elif isinstance(result, list):
            hits = result
        memories = format_memories(hits, limit=limit)
        return MemorySnapshot(memories=memories,
                              note="" if memories else "нічого релевантного")

    def constraints(self, *, limit: int = 8) -> list[str]:
        """Критичні обмеження проєкту (окремо від пошуку за запитом).

        Обмеження діють завжди, а не лише коли про них спитали: саме тому
        вони читаються напряму й додаються до стану розмови.
        """
        if not self.ready():
            return []
        search = getattr(self.service, "search", None)
        if not callable(search):
            return []
        try:
            result = search("обмеження проєкту не можна порушувати",
                            limit=max(1, int(limit)), kinds=["constraint"])
        except TypeError:
            try:
                result = search("обмеження проєкту", limit=max(1, int(limit)))
            except Exception:                        # noqa: BLE001
                return []
        except Exception:                            # noqa: BLE001
            return []
        hits = result.get("hits") if isinstance(result, Mapping) else result
        return format_memories(hits or [], limit=limit)

    # ── запис ─────────────────────────────────────────────────────────────
    def remember_fact(self, content: str, *, kind: str = "fact",
                      source: str = "", files: Sequence[str] = (),
                      task: str = "", confidence: float = SELF_CONFIDENCE) -> bool:
        """Зберегти перевірений факт. ``False`` — якщо записати не вдалось."""
        body = " ".join((content or "").split())
        if not body:
            return False
        if not self.ready():
            return False
        remember = getattr(self.service, "remember", None)
        if not callable(remember):
            return False
        try:
            remember(body, kind=kind, source=source[:200],
                     files=[str(item) for item in files][:8],
                     confidence=max(0.0, min(1.0, float(confidence))))
        except TypeError:
            # Старіший сервіс без частини параметрів.
            try:
                remember(body, kind=kind, source=source[:200])
            except Exception:                        # noqa: BLE001
                LOG.info("Спогад не збережено", exc_info=True)
                return False
        except Exception:                            # noqa: BLE001
            LOG.info("Спогад не збережено", exc_info=True)
            return False
        del task
        return True

    def record_turn(self, *, task: str, action: str, status: str = "ok",
                    detail: str = "", files: Sequence[str] = (),
                    tools: Sequence[str] = ()) -> bool:
        """Записати хід у історію задач (для ``memory_task_history``)."""
        if not self.ready():
            return False
        record = getattr(self.service, "record_task", None)
        if not callable(record):
            return False
        try:
            record(task, action, status=status, detail=detail[:400],
                   files=[str(item) for item in files][:8],
                   tools=[str(item) for item in tools][:8])
        except Exception:                            # noqa: BLE001
            LOG.info("Хід не записано в історію пам'яті", exc_info=True)
            return False
        return True

    def apply_to_state(self, snapshot: MemorySnapshot,
                       state: Any = None) -> int:
        """Додати обмеження з пам'яті у стан розмови.

        Повертає кількість нових обмежень. Обмеження не дублюються: у
        стані вони зберігаються списком і діють до кінця завдання.
        """
        if state is None or snapshot.empty:
            return 0
        existing = list(getattr(state, "constraints", ()) or ())
        added = 0
        for item in snapshot.constraints:
            line = f"з пам'яті: {item}"
            if line not in existing:
                existing.append(line)
                added += 1
        try:
            state.constraints = existing
        except Exception:                            # noqa: BLE001
            return 0
        return added
