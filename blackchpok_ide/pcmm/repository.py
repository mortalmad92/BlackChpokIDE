"""Сховище спогадів: запис, пошук, зв'язки, консолідація, відновлення.

Рівень вище за :mod:`.store` (який відповідає лише за SQLite). Тут —
семантика пам'яті: що вважати дублікатом, як зливати факти, як шукати
кандидатів на конфлікт і як вести історію версій.

Принципи, закладені в код:

1. **Нічого не зникає.** Застарілий факт отримує ``superseded_by`` і
   лишається в базі; усі зміни пишуться в ``memory_versions``.
2. **Дублікат не створює нового рядка.** Той самий зміст (за хешем або
   за відбитком лексем) оновлює наявний спогад і підвищує впевненість.
3. **Впевненість зростає від підтверджень, а не від віку.** Кожне
   підтвердження з іншого джерела додає вагу; суперечність — знижує.
4. **Зв'язки — двонаправлені за змістом, але зберігаються напрямлено**
   (``caused``, ``fixed_by``), щоб граф можна було читати.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .models import (
    KINDS,
    Memory,
    RELATIONS,
    content_hash,
    contradiction_score,
    fingerprint,
    make_summary,
    merge_contents,
    overlap,
)
from .store import MemoryStore, StoreError

LOG = logging.getLogger("blackchpok.pcmm.repository")

#: Поріг перекриття, за якого два факти вважаємо тим самим.
DUPLICATE_THRESHOLD = 0.82
#: Поріг для кандидатів у конфлікт.
CONTRADICTION_THRESHOLD = 0.45
#: Скільки підтверджень дає максимальну впевненість.
MAX_CONFIRMATIONS = 5


@dataclass
class StoreOutcome:
    """Результат збереження спогаду."""

    memory: Memory
    created: bool = False
    duplicate: bool = False
    conflicts: list[str] = None            # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.conflicts is None:
            self.conflicts = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory": self.memory.to_dict(),
            "created": self.created,
            "duplicate": self.duplicate,
            "conflicts": list(self.conflicts),
        }


class MemoryRepository:
    """CRUD + пошук + консолідація над :class:`MemoryStore`."""

    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or MemoryStore()

    # ── запис ─────────────────────────────────────────────────────────────
    def save(self, memory: Memory, *, check_duplicates: bool = True,
             actor: str = "agent") -> StoreOutcome:
        """Зберегти спогад; повернути, чи це новий запис."""
        if not memory.content.strip():
            raise StoreError("Порожній спогад зберігати немає сенсу.")
        existing = None
        if check_duplicates:
            existing = self._find_duplicate(memory)
        if existing is not None:
            return self._confirm(existing, memory, actor=actor)

        conflicts = self._find_conflicts(memory) if check_duplicates else []
        columns = (
            "id, kind, content, summary, source, provenance, confidence, created_at, "
            "updated_at, accessed_at, hits, task, files, tags, valid_from, valid_to, "
            "superseded_by, fingerprint, content_hash, embedding, embed_model, checksum"
        )
        placeholders = ",".join("?" * 22)
        try:
            with self.store.transaction() as conn:
                conn.execute(
                    f"INSERT INTO memories ({columns}) VALUES ({placeholders})",
                    memory.to_row(),
                )
                conn.execute(
                    "INSERT INTO memory_events (memory_id, action, detail, actor, at) "
                    "VALUES (?,?,?,?,?)",
                    (memory.id, "remember", memory.summary[:300], actor, time.time()),
                )
        except sqlite3.IntegrityError:
            # Унікальність гарантує схема: навіть якщо перевірку дублікатів
            # вимкнено явно, той самий зміст не ляже двома рядками.
            found = self._find_duplicate(memory)
            if found is None:
                raise
            LOG.debug("Дублікат перехоплено унікальним індексом: %s", found.id)
            return self._confirm(found, memory, actor=actor)
        for other in conflicts:
            self.add_link(memory.id, other.id, "contradicts", 0.6, actor=actor,
                          quiet=True)
            self._record_contradiction(memory.id, other.id,
                                       "схожа тема, інший зміст")
        return StoreOutcome(memory=memory, created=True,
                            conflicts=[item.id for item in conflicts])

    def _find_duplicate(self, memory: Memory) -> Memory | None:
        """Знайти наявний спогад із тим самим змістом."""
        row = self.store.one(
            "SELECT * FROM memories WHERE content_hash = ?", (memory.content_hash,))
        if row is not None:
            return Memory.from_row(row)
        # Лексемний відбиток ловить перефразування з тим самим набором слів.
        rows = self.store.query(
            "SELECT * FROM memories WHERE fingerprint = ? AND kind = ? LIMIT 1",
            (memory.fingerprint, memory.kind),
        )
        return Memory.from_row(rows[0]) if rows else None

    def _confirm(self, existing: Memory, incoming: Memory, *, actor: str) -> StoreOutcome:
        """Підтвердити наявний спогад новим джерелом."""
        bonus = 0.10 if incoming.source and incoming.source != existing.source else 0.05
        existing.confidence = min(1.0, existing.confidence + bonus)
        existing.hits += 1
        existing.updated_at = time.time()
        if incoming.provenance and not existing.provenance:
            existing.provenance = incoming.provenance
        if incoming.files:
            existing.files = sorted({*existing.files, *incoming.files})
        if incoming.tags:
            existing.tags = sorted({*existing.tags, *incoming.tags})
        if incoming.task and not existing.task:
            existing.task = incoming.task
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE memories SET confidence = ?, hits = ?, updated_at = ?, "
                "provenance = ?, files = ?, tags = ?, task = ? WHERE id = ?",
                (existing.confidence, existing.hits, existing.updated_at,
                 existing.provenance,
                 json.dumps(existing.files, ensure_ascii=False),
                 json.dumps(existing.tags, ensure_ascii=False),
                 existing.task, existing.id),
            )
            conn.execute(
                "INSERT INTO memory_events (memory_id, action, detail, actor, at) "
                "VALUES (?,?,?,?,?)",
                (existing.id, "confirm", incoming.summary[:300], actor, time.time()),
            )
        return StoreOutcome(memory=existing, created=False, duplicate=True)

    def remember(self, content: str, *, kind: str = "fact", source: str = "",
                 provenance: str = "", confidence: float = 0.6,
                 task: str = "", files: Sequence[str] | None = None,
                 tags: Sequence[str] | None = None,
                 embedding: Sequence[float] | None = None,
                 embed_model: str = "", actor: str = "agent") -> StoreOutcome:
        """Швидкий запис спогаду з тексту."""
        memory = Memory(
            kind=kind if kind in KINDS else "fact",
            content=content,
            source=source,
            provenance=provenance,
            confidence=confidence,
            task=task,
            files=list(files or []),
            tags=list(tags or []),
            embedding=list(embedding or []),
            embed_model=embed_model,
        )
        return self.save(memory, actor=actor)

    def remember_many(self, items: Iterable[dict], *, actor: str = "agent") -> list[StoreOutcome]:
        """Пакетний запис (одна транзакція на елемент, але один виклик)."""
        outcomes: list[StoreOutcome] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            outcomes.append(self.remember(
                content,
                kind=str(item.get("kind") or "fact"),
                source=str(item.get("source") or ""),
                provenance=str(item.get("provenance") or ""),
                confidence=float(item.get("confidence") or 0.6),
                task=str(item.get("task") or ""),
                files=item.get("files") or [],
                tags=item.get("tags") or [],
                actor=actor,
            ))
        return outcomes

    # ── читання ───────────────────────────────────────────────────────────
    def get(self, memory_id: str) -> Memory | None:
        row = self.store.one("SELECT * FROM memories WHERE id = ?", (memory_id,))
        return Memory.from_row(row) if row else None

    def list(self, *, kind: str = "", limit: int = 50, offset: int = 0,
             active_only: bool = True, task: str = "") -> list[Memory]:
        clauses: list[str] = []
        params: list[Any] = []
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if task:
            clauses.append("task = ?")
            params.append(task)
        if active_only:
            clauses.append("superseded_by = ''")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([max(1, min(limit, 500)), max(0, offset)])
        rows = self.store.query(
            f"SELECT * FROM memories {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        )
        return [Memory.from_row(row) for row in rows]

    def recent(self, limit: int = 10) -> list[Memory]:
        return self.list(limit=limit)

    def count(self) -> int:
        row = self.store.one("SELECT COUNT(*) AS n FROM memories")
        return int(row["n"]) if row else 0

    def by_files(self, files: Iterable[str], *, limit: int = 30) -> list[Memory]:
        """Спогади, прив'язані до конкретних файлів (для префетчу)."""
        wanted = [item for item in {str(path) for path in files} if item]
        if not wanted:
            return []
        found: list[Memory] = []
        seen: set[str] = set()
        # SQLite не вміє шукати в JSON-масиві без розширення, тому
        # використовуємо LIKE по серіалізованому полю — воно коротке.
        for path in wanted[:20]:
            rows = self.store.query(
                "SELECT * FROM memories WHERE files LIKE ? AND superseded_by = '' "
                "ORDER BY updated_at DESC LIMIT ?",
                (f'%"{path}"%', limit),
            )
            for row in rows:
                memory = Memory.from_row(row)
                if memory.id in seen:
                    continue
                seen.add(memory.id)
                found.append(memory)
        found.sort(key=lambda item: item.updated_at, reverse=True)
        return found[:limit]

    # ── оновлення ─────────────────────────────────────────────────────────
    def update(self, memory_id: str, *, content: str = "", confidence: float | None = None,
               reason: str = "", actor: str = "agent") -> Memory | None:
        """Оновити зміст спогаду, зберігши попередню версію."""
        memory = self.get(memory_id)
        if memory is None:
            return None
        with self.store.transaction() as conn:
            conn.execute(
                "INSERT INTO memory_versions (memory_id, content, confidence, at, reason) "
                "VALUES (?,?,?,?,?)",
                (memory.id, memory.content, memory.confidence, time.time(), reason),
            )
            if content.strip():
                memory.content = content
                memory.summary = make_summary(content)
                memory.content_hash = content_hash(content)
                memory.fingerprint = fingerprint(content, memory.kind)
            if confidence is not None:
                memory.confidence = max(0.0, min(1.0, float(confidence)))
            memory.updated_at = time.time()
            conn.execute(
                "UPDATE memories SET content = ?, summary = ?, content_hash = ?, "
                "fingerprint = ?, confidence = ?, updated_at = ? WHERE id = ?",
                (memory.content, memory.summary, memory.content_hash,
                 memory.fingerprint, memory.confidence, memory.updated_at, memory.id),
            )
            conn.execute(
                "INSERT INTO memory_events (memory_id, action, detail, actor, at) "
                "VALUES (?,?,?,?,?)",
                (memory.id, "update", reason[:300] or "оновлено", actor, time.time()),
            )
        return memory

    def supersede(self, old_id: str, new_id: str, *, reason: str = "",
                  actor: str = "agent") -> bool:
        """Позначити старий спогад заміненим новим (без видалення)."""
        now = time.time()
        with self.store.transaction() as conn:
            cursor = conn.execute(
                "UPDATE memories SET superseded_by = ?, valid_to = ?, updated_at = ? "
                "WHERE id = ?",
                (new_id, now, now, old_id),
            )
            if cursor.rowcount == 0:
                return False
            conn.execute(
                "INSERT INTO memory_events (memory_id, action, detail, actor, at) "
                "VALUES (?,?,?,?,?)",
                (old_id, "supersede", f"{new_id}: {reason}"[:300], actor, now),
            )
        self.add_link(old_id, new_id, "supersedes", 0.9, actor=actor, quiet=True)
        return True

    def forget(self, memory_id: str, *, confirm: bool = False,
               actor: str = "user") -> bool:
        """Видалити спогад. Без ``confirm=True`` нічого не робить."""
        if not confirm:
            LOG.info("Видалення %s без підтвердження — скасовано", memory_id)
            return False
        memory = self.get(memory_id)
        if memory is None:
            return False
        with self.store.transaction() as conn:
            conn.execute(
                "INSERT INTO memory_versions (memory_id, content, confidence, at, reason) "
                "VALUES (?,?,?,?,?)",
                (memory.id, memory.content, memory.confidence, time.time(),
                 "видалено користувачем"),
            )
            conn.execute("DELETE FROM memories WHERE id = ?", (memory.id,))
        return True

    # ── зв'язки ───────────────────────────────────────────────────────────
    def add_link(self, src: str, dst: str, relation: str = "related",
                 weight: float = 0.5, *, actor: str = "agent",
                 quiet: bool = False) -> bool:
        if not src or not dst or src == dst:
            return False
        relation = relation if relation in RELATIONS else "related"
        weight = max(0.0, min(1.0, float(weight)))
        try:
            with self.store.transaction() as conn:
                conn.execute(
                    "INSERT INTO memory_links (src, dst, relation, weight, created_at) "
                    "VALUES (?,?,?,?,?) ON CONFLICT(src, dst, relation) DO UPDATE SET "
                    "weight = MAX(weight, excluded.weight)",
                    (src, dst, relation, weight, time.time()),
                )
                if not quiet:
                    conn.execute(
                        "INSERT INTO memory_events (memory_id, action, detail, actor, at) "
                        "VALUES (?,?,?,?,?)",
                        (src, "link", f"{relation} → {dst}"[:300], actor, time.time()),
                    )
            return True
        except StoreError:
            LOG.debug("Не вдалось створити зв'язок %s→%s", src, dst, exc_info=True)
            return False

    def links(self, memory_id: str) -> dict[str, list[dict[str, Any]]]:
        """Зв'язки спогаду в обидва боки."""
        outgoing = self.store.query(
            "SELECT dst AS other, relation, weight FROM memory_links WHERE src = ?",
            (memory_id,),
        )
        incoming = self.store.query(
            "SELECT src AS other, relation, weight FROM memory_links WHERE dst = ?",
            (memory_id,),
        )
        return {
            "out": [dict(row) for row in outgoing],
            "in": [dict(row) for row in incoming],
        }

    def neighbours(self, memory_id: str, *, depth: int = 1) -> dict[str, Memory]:
        """Обхід графа в ширину з обмеженням глибини (без повного скану)."""
        found: dict[str, Memory] = {}
        frontier = {memory_id}
        visited: set[str] = {memory_id}
        for _ in range(max(0, depth)):
            if not frontier:
                break
            marks = ",".join("?" * len(frontier))
            rows = self.store.query(
                f"SELECT src, dst FROM memory_links WHERE src IN ({marks}) "
                f"OR dst IN ({marks})",
                [*frontier, *frontier],
            )
            next_frontier: set[str] = set()
            for row in rows:
                for candidate in (str(row["src"]), str(row["dst"])):
                    if candidate in visited:
                        continue
                    visited.add(candidate)
                    next_frontier.add(candidate)
            for identifier in next_frontier:
                memory = self.get(identifier)
                if memory is not None:
                    found[identifier] = memory
            frontier = next_frontier
        return found

    def _record_contradiction(self, left: str, right: str, reason: str) -> None:
        with self.store.transaction() as conn:
            conn.execute(
                "INSERT INTO contradictions (left_id, right_id, reason, at) "
                "VALUES (?,?,?,?) ON CONFLICT(left_id, right_id) DO NOTHING",
                (left, right, reason, time.time()),
            )

    # ── конфлікти та консолідація ─────────────────────────────────────────
    def _find_conflicts(self, memory: Memory, *, limit: int = 40) -> list[Memory]:
        """Кандидати на конфлікт: схожа тема, інший зміст."""
        rows = self.store.query(
            "SELECT * FROM memories WHERE kind = ? AND superseded_by = '' "
            "ORDER BY updated_at DESC LIMIT ?",
            (memory.kind, limit),
        )
        conflicts: list[Memory] = []
        for row in rows:
            other = Memory.from_row(row)
            if other.id == memory.id:
                continue
            if contradiction_score(memory.content, other.content) >= CONTRADICTION_THRESHOLD:
                conflicts.append(other)
        return conflicts

    def contradictions(self, *, unresolved_only: bool = True,
                       limit: int = 50) -> list[dict[str, Any]]:
        where = "WHERE resolved = 0" if unresolved_only else ""
        rows = self.store.query(
            f"SELECT * FROM contradictions {where} ORDER BY at DESC LIMIT ?",
            (max(1, limit),),
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            left = self.get(str(row["left_id"]))
            right = self.get(str(row["right_id"]))
            result.append({
                "id": int(row["id"]),
                "left_id": str(row["left_id"]),
                "right_id": str(row["right_id"]),
                "reason": str(row["reason"]),
                "resolved": bool(row["resolved"]),
                "at": float(row["at"]),
                "left": left.to_dict() if left else None,
                "right": right.to_dict() if right else None,
            })
        return result

    def resolve_contradiction(self, contradiction_id: int, *, keep: str,
                              resolution: str = "", actor: str = "user") -> bool:
        """Вирішити конфлікт: ``keep`` — id спогаду, який лишається істинним."""
        row = self.store.one("SELECT * FROM contradictions WHERE id = ?",
                             (contradiction_id,))
        if row is None:
            return False
        left, right = str(row["left_id"]), str(row["right_id"])
        loser = right if keep == left else left
        winner = keep if keep in (left, right) else left
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE contradictions SET resolved = 1, resolution = ? WHERE id = ?",
                (resolution or f"лишено {winner}", contradiction_id),
            )
        self.supersede(loser, winner, reason=resolution or "вирішено конфлікт",
                       actor=actor)
        # Переможець стає впевненішим: конфлікт вирішено на його користь.
        memory = self.get(winner)
        if memory is not None:
            self.update(winner, confidence=min(1.0, memory.confidence + 0.15),
                        reason="вирішено на користь цього факту", actor=actor)
        return True

    def consolidate(self, *, dry_run: bool = False, actor: str = "system") -> dict[str, Any]:
        """Об'єднати дублікати й позначити суперечності.

        нічого не видаляється: дублікати зливаються у найстаріший запис
        (він стає «канонічним»), решта позначається заміненими.
        """
        report: dict[str, Any] = {
            "merged": [], "superseded": [], "contradictions": 0, "dry_run": dry_run,
        }
        rows = self.store.query(
            "SELECT * FROM memories WHERE superseded_by = '' ORDER BY created_at ASC")
        memories = [Memory.from_row(row) for row in rows]
        canonical: dict[str, Memory] = {}
        for memory in memories:
            key = f"{memory.kind}:{memory.content_hash}"
            twin = canonical.get(key)
            if twin is None:
                # Перевіряємо перефразування серед уже прийнятих.
                for candidate in canonical.values():
                    if candidate.kind == memory.kind and \
                            overlap(candidate.content, memory.content) >= DUPLICATE_THRESHOLD:
                        twin = candidate
                        break
            if twin is None:
                canonical[key] = memory
                continue
            report["merged"].append({
                "kept": twin.id, "dropped": memory.id,
                "similarity": round(overlap(twin.content, memory.content), 3),
            })
            if not dry_run:
                merged = merge_contents([twin, memory])
                if merged and merged != twin.content:
                    self.update(twin.id, content=merged,
                                confidence=min(1.0, max(twin.confidence,
                                                        memory.confidence) + 0.05),
                                reason="консолідація дублікатів", actor=actor)
                self.supersede(memory.id, twin.id, reason="дублікат", actor=actor)
                report["superseded"].append(memory.id)

        # Суперечності шукаємо лише серед активних і лише серед тих самих типів.
        by_kind: dict[str, list[Memory]] = {}
        for memory in canonical.values():
            by_kind.setdefault(memory.kind, []).append(memory)
        for items in by_kind.values():
            for index, left in enumerate(items):
                for right in items[index + 1:]:
                    if contradiction_score(left.content, right.content) >= CONTRADICTION_THRESHOLD:
                        report["contradictions"] += 1
                        if not dry_run:
                            self.add_link(left.id, right.id, "contradicts", 0.6,
                                          actor=actor, quiet=True)
                            self._record_contradiction(
                                left.id, right.id, "схожа тема, інший зміст")
        return report

    # ── службове ──────────────────────────────────────────────────────────
    def touch(self, memory_id: str) -> None:
        """Позначити використання спогаду (для часової актуальності)."""
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE memories SET hits = hits + 1, accessed_at = ? WHERE id = ?",
                (time.time(), memory_id),
            )

    def feedback(self, memory_id: str, *, useful: bool, note: str = "") -> bool:
        """Зворотний зв'язок: спогад був корисний чи ні."""
        memory = self.get(memory_id)
        if memory is None:
            return False
        delta = 0.08 if useful else -0.12
        with self.store.transaction() as conn:
            conn.execute(
                "INSERT INTO feedback (memory_id, useful, note, at) VALUES (?,?,?,?)",
                (memory_id, 1 if useful else 0, note[:500], time.time()),
            )
        self.update(memory_id, confidence=max(0.05, min(1.0,
                                                        memory.confidence + delta)),
                    reason="зворотний зв'язок", actor="user")
        return True

    def versions(self, memory_id: str) -> list[dict[str, Any]]:
        rows = self.store.query(
            "SELECT * FROM memory_versions WHERE memory_id = ? ORDER BY at DESC",
            (memory_id,),
        )
        return [dict(row) for row in rows]

    def events(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.store.query(
            "SELECT * FROM memory_events ORDER BY at DESC LIMIT ?", (max(1, limit),))
        return [dict(row) for row in rows]

    def record_task(self, task: str, action: str, *, status: str = "ok",
                    detail: str = "", files: Sequence[str] | None = None,
                    tools: Sequence[str] | None = None) -> None:
        """Записати крок історії завдань (для прогнозування контексту)."""
        with self.store.transaction() as conn:
            conn.execute(
                "INSERT INTO task_history (task, action, status, detail, files, tools, at) "
                "VALUES (?,?,?,?,?,?,?)",
                (task[:300], action[:200], status[:40], detail[:1000],
                 json.dumps(list(files or []), ensure_ascii=False),
                 json.dumps(list(tools or []), ensure_ascii=False), time.time()),
            )

    def task_history(self, *, task: str = "", limit: int = 50) -> list[dict[str, Any]]:
        if task:
            rows = self.store.query(
                "SELECT * FROM task_history WHERE task = ? ORDER BY at DESC LIMIT ?",
                (task[:300], max(1, limit)),
            )
        else:
            rows = self.store.query(
                "SELECT * FROM task_history ORDER BY at DESC LIMIT ?", (max(1, limit),))
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        total = self.count()
        active = self.store.one(
            "SELECT COUNT(*) AS n FROM memories WHERE superseded_by = ''")
        links = self.store.one("SELECT COUNT(*) AS n FROM memory_links")
        conflicts = self.store.one(
            "SELECT COUNT(*) AS n FROM contradictions WHERE resolved = 0")
        with_vectors = self.store.one(
            "SELECT COUNT(*) AS n FROM memories WHERE embedding != ''")
        kinds = self.store.query(
            "SELECT kind, COUNT(*) AS n FROM memories GROUP BY kind ORDER BY n DESC")
        return {
            "total": total,
            "active": int(active["n"]) if active else 0,
            "links": int(links["n"]) if links else 0,
            "conflicts": int(conflicts["n"]) if conflicts else 0,
            "with_vectors": int(with_vectors["n"]) if with_vectors else 0,
            "kinds": {str(row["kind"]): int(row["n"]) for row in kinds},
            "db": str(self.store.path),
            "version": self.store.version,
        }


__all__ = [
    "CONTRADICTION_THRESHOLD",
    "DUPLICATE_THRESHOLD",
    "MemoryRepository",
    "StoreOutcome",
]
