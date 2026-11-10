"""Фасад NEUROMESH для IDE та інструментів агента.

Тут зведені всі операції, які потрібні агентові (``memory_search``,
``memory_store`` тощо) в один об'єкт із зрозумілим життєвим циклом:
відкрити базу, підвантажити вектори, віддати контекст, зберегти нові
факти, зробити бекап.

Ключова вимога: система мусить працювати НАВІТЬ без завантаженої моделі.
Тоді пошук іде лексемно (BM25), вектори не рахуються, і це чесно
позначається в статусі, а не маскується під «семантику».
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from .budget import BudgetGovernor, BudgetReport, ContextPiece
from .models import KINDS, Memory, make_summary
from .repository import MemoryRepository
from .retrieval import ContextPredictor, Hit, Prediction, Retriever, choose_policy
from .store import MemoryStore, StoreError, timestamped_backup

LOG = logging.getLogger("blackchpok.pcmm.service")

#: Скільки останніх спогадів питати на старті.
STARTUP_RECENT = 5
#: Частка вікна, яку дозволяємо віддати пам'яті (решта — завдання й історія).
MEMORY_WINDOW_SHARE = 0.38


@dataclass
class ContextBundle:
    """Готовий блок контексту зі спогадів."""

    report: BudgetReport = field(default_factory=BudgetReport)
    hits: list[Hit] = field(default_factory=list)
    prediction: Prediction | None = None
    tokens_saved: int = 0
    note: str = ""

    @property
    def text(self) -> str:
        return self.report.text

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "budget": self.report.to_dict(),
            "hits": [hit.to_dict() for hit in self.hits],
            "prediction": self.prediction.to_dict() if self.prediction else None,
            "tokens_saved": self.tokens_saved,
            "note": self.note,
        }


class Neuromesh:
    """Єдина точка входу до пам'яті NEUROMESH."""

    def __init__(self, db_path: str | Path | None = None, *,
                 embedder: Any | None = None,
                 counter: Any | None = None) -> None:
        self.store = MemoryStore(db_path)
        self.repository = MemoryRepository(self.store)
        self.retriever = Retriever(self.repository, embedder=embedder)
        self.predictor = ContextPredictor(self.repository, self.retriever)
        self.embedder = embedder
        self._lock = threading.RLock()
        self._counter = counter
        self._last_bundle: ContextBundle | None = None
        self._started = time.time()

    # ── конфігурація ──────────────────────────────────────────────────────
    def attach_engine(self, engine: Any) -> None:
        """Підключити рушій: дає вектори й реальний токенайзер."""
        from ..native.embeddings import EmbeddingService

        self.engine = engine
        db = self.store.path.parent / "vectors.db"
        self.embedder = EmbeddingService(engine, db_path=db)
        self.retriever.embedder = self.embedder
        self._counter = None

    def attach_embedder(self, embedder: Any) -> None:
        """Підключити готовий embedding-сервіс (наприклад, з рушія)."""
        self.embedder = embedder
        self.retriever.embedder = embedder

    def governor(self) -> BudgetGovernor:
        """Губернатор бюджету на реальному токенайзері, якщо він є."""
        engine = getattr(self, "engine", None)
        model = getattr(engine, "model", None) if engine else None
        tokenizer = getattr(model, "tokenizer", None) if model else None
        if tokenizer is not None:
            return BudgetGovernor.for_tokenizer(tokenizer)
        if self._counter is not None:
            return BudgetGovernor(self._counter, exact=True)
        return BudgetGovernor.heuristic()

    # ── запис ─────────────────────────────────────────────────────────────
    def remember(self, content: str, *, kind: str = "fact", source: str = "",
                 provenance: str = "", confidence: float = 0.6,
                 task: str = "", files: Sequence[str] | None = None,
                 tags: Sequence[str] | None = None,
                 with_vector: bool = True) -> dict[str, Any]:
        """Запам'ятати твердження (з вектором, якщо є рушій)."""
        vector: list[float] = []
        model_tag = ""
        if with_vector and self.embedder is not None:
            try:
                vector = self.embedder.encode_one(content)
                model_tag = getattr(self.embedder, "model_tag", "")
            except Exception:                        # noqa: BLE001
                LOG.debug("Вектор для спогаду не пораховано", exc_info=True)
        outcome = self.repository.remember(
            content, kind=kind, source=source, provenance=provenance,
            confidence=confidence, task=task, files=files or [], tags=tags or [],
            embedding=vector, embed_model=model_tag,
        )
        return outcome.to_dict()

    def remember_many(self, items: Iterable[dict]) -> list[dict[str, Any]]:
        """Пакетний запис (наприклад, після кроку агента)."""
        prepared: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            entry = dict(item)
            if self.embedder is not None:
                try:
                    entry["_vector"] = self.embedder.encode_one(content)
                except Exception:                    # noqa: BLE001
                    entry["_vector"] = []
            prepared.append(entry)
        results: list[dict[str, Any]] = []
        for entry in prepared:
            results.append(self.remember(
                str(entry.get("content") or ""),
                kind=str(entry.get("kind") or "fact"),
                source=str(entry.get("source") or ""),
                provenance=str(entry.get("provenance") or ""),
                confidence=float(entry.get("confidence") or 0.6),
                task=str(entry.get("task") or ""),
                files=entry.get("files") or [],
                tags=entry.get("tags") or [],
                with_vector=False,
            ))
        return results

    def link(self, src: str, dst: str, relation: str = "related",
             weight: float = 0.6) -> bool:
        return self.repository.add_link(src, dst, relation, weight)

    def update(self, memory_id: str, *, content: str = "",
               confidence: float | None = None, reason: str = "") -> dict[str, Any] | None:
        memory = self.repository.update(memory_id, content=content,
                                        confidence=confidence, reason=reason)
        if memory is None:
            return None
        if content and self.embedder is not None:
            try:
                vector = self.embedder.encode_one(content)
                with self.store.transaction() as conn:
                    conn.execute(
                        "UPDATE memories SET embedding = ?, embed_model = ? WHERE id = ?",
                        (json.dumps(vector) if vector else "",
                         getattr(self.embedder, "model_tag", ""), memory.id),
                    )
            except Exception:                        # noqa: BLE001
                LOG.debug("Вектор оновленого спогаду не збережено", exc_info=True)
        return memory.to_dict()

    def verify(self, memory_id: str, *, confidence: float | None = None,
               note: str = "") -> dict[str, Any] | None:
        """Підтвердити спогад (підвищити впевненість, зафіксувати перевірку)."""
        memory = self.repository.get(memory_id)
        if memory is None:
            return None
        target = confidence if confidence is not None else min(1.0, memory.confidence + 0.15)
        updated = self.repository.update(memory_id, confidence=target,
                                         reason=note or "підтверджено", actor="user")
        return updated.to_dict() if updated else None

    def forget(self, memory_id: str, *, confirm: bool = False) -> bool:
        return self.repository.forget(memory_id, confirm=confirm)

    # ── читання ───────────────────────────────────────────────────────────
    def search(self, query: str, *, limit: int = 12, kinds: Sequence[str] | None = None,
               task: str = "", files: Sequence[str] | None = None) -> dict[str, Any]:
        """Пошук по пам'яті з поясненням політики."""
        policy = choose_policy(query, vectors_ready=self.retriever.vectors_ready,
                               limit=limit)
        hits = self.retriever.search(query, limit=limit, kinds=kinds, task=task,
                                     files=files, policy=policy)
        return {
            "query": query,
            "policy": policy.describe(),
            "weights": {key: round(value, 3) for key, value in policy.weights.items()},
            "hits": [hit.to_dict() for hit in hits],
            "count": len(hits),
        }

    def recall(self, memory_id: str) -> dict[str, Any] | None:
        memory = self.repository.get(memory_id)
        if memory is None:
            return None
        return {
            "memory": memory.to_dict(),
            "links": self.repository.links(memory_id),
            "neighbours": {key: value.to_dict()
                           for key, value in self.repository.neighbours(memory_id).items()},
            "versions": self.repository.versions(memory_id),
        }

    def explain(self, memory_id: str) -> dict[str, Any] | None:
        """Пояснити, звідки спогад і на чому тримається впевненість."""
        memory = self.repository.get(memory_id)
        if memory is None:
            return None
        events = [item for item in self.repository.events(limit=200)
                  if str(item.get("memory_id")) == memory_id]
        return {
            "memory": memory.to_dict(),
            "why_confidence": (
                f"початкова {memory.confidence:.2f}; підтверджень {memory.hits}; "
                f"тип {memory.kind} (вага {memory.kind_weight})"
            ),
            "provenance": memory.provenance or memory.source or "невідомо",
            "history": events,
            "versions": self.repository.versions(memory_id),
            "links": self.repository.links(memory_id),
        }

    def predict(self, *, current_files: Sequence[str] = (),
                task: str = "", query: str = "", limit: int = 8) -> dict[str, Any]:
        return self.predictor.predict(current_files=current_files, task=task,
                                      query=query, limit=limit).to_dict()

    def task_history(self, *, task: str = "", limit: int = 30) -> list[dict[str, Any]]:
        return self.repository.task_history(task=task, limit=limit)

    def record_task(self, task: str, action: str, *, status: str = "ok",
                    detail: str = "", files: Sequence[str] | None = None,
                    tools: Sequence[str] | None = None) -> None:
        self.repository.record_task(task, action, status=status, detail=detail,
                                   files=files, tools=tools)

    def feedback(self, memory_id: str, *, useful: bool, note: str = "") -> dict[str, Any]:
        ok = self.repository.feedback(memory_id, useful=useful, note=note)
        return {"ok": ok, "memory_id": memory_id, "useful": useful}

    # ── контекст ──────────────────────────────────────────────────────────
    def project_context(self, *, query: str, window: int, task: str = "",
                        files: Sequence[str] = (),
                        kinds: Sequence[str] | None = None,
                        max_share: float = MEMORY_WINDOW_SHARE) -> ContextBundle:
        """Зібрати контекст зі спогадів під бюджет вікна моделі."""
        governor = self.governor()
        policy = choose_policy(query, vectors_ready=self.retriever.vectors_ready)
        hits = self.retriever.search(query, limit=24, kinds=kinds, task=task,
                                     files=files, policy=policy)
        prediction = self.predictor.predict(current_files=files, task=task,
                                           query=query, limit=6)
        known = {hit.memory.id for hit in hits}
        pieces: list[ContextPiece] = []
        # Критичні обмеження додаємо ПЕРШИМИ й окремо: навіть якщо запит про
        # щось інше, «ніколи не робити X» мусить бути в контексті. Це не
        # «магія» — просто обов'язковий шар, який губернатор не викине.
        for memory in self.repository.list(kind="constraint", limit=8):
            if memory.id in known:
                continue
            pieces.append(BudgetGovernor.memory_piece(
                memory, score=max(0.5, memory.confidence),
                reason="обов'язкове обмеження проєкту"))
        for hit in hits:
            pieces.append(BudgetGovernor.memory_piece(
                hit.memory, score=hit.score, reason=hit.explanation))
        for hit in prediction.memories:
            if hit.memory.id in known:
                continue
            pieces.append(BudgetGovernor.memory_piece(
                hit.memory, score=hit.score * 0.8, reason=hit.explanation))
        report = governor.fit(pieces, window=window, max_share=max_share)
        # Скільки токенів зекономлено: те, що не влізло, не пішло в промпт.
        saved = sum(piece.tokens for piece in report.dropped)
        bundle = ContextBundle(report=report, hits=hits, prediction=prediction,
                               tokens_saved=saved,
                               note="" if report.exact else
                               "Токени оцінені приблизно: модель не завантажена.")
        self._last_bundle = bundle
        return bundle

    def last_context(self) -> dict[str, Any] | None:
        return self._last_bundle.to_dict() if self._last_bundle else None

    def record_prediction_outcome(self, *, used_ids: Sequence[str]) -> dict[str, Any]:
        """Порахувати, наскільки прогноз був точним (реальний вимір)."""
        bundle = self._last_bundle
        if bundle is None or bundle.prediction is None:
            return {"predicted": 0, "used": len(used_ids), "hits": 0, "precision": 0.0}
        predicted = [hit.memory.id for hit in bundle.prediction.memories]
        return self.predictor.record_outcome(used_ids=used_ids,
                                             predicted_ids=predicted)

    # ── обслуговування ────────────────────────────────────────────────────
    def consolidate(self, *, dry_run: bool = False) -> dict[str, Any]:
        return self.repository.consolidate(dry_run=dry_run)

    def contradictions(self, *, unresolved_only: bool = True) -> list[dict[str, Any]]:
        return self.repository.contradictions(unresolved_only=unresolved_only)

    def resolve(self, contradiction_id: int, *, keep: str, resolution: str = "") -> bool:
        return self.repository.resolve_contradiction(
            contradiction_id, keep=keep, resolution=resolution)

    def backup(self, target: str | Path | None = None) -> dict[str, Any]:
        path = timestamped_backup(self.store) if target is None else self.store.backup(target)
        return {"path": str(path), "size_bytes": Path(path).stat().st_size}

    def restore(self, source: str | Path) -> bool:
        return self.store.restore(source)

    def backups(self) -> list[dict[str, Any]]:
        from .store import backup_dir

        return [
            {"path": str(item), "size_mb": round(item.stat().st_size / 1048576, 2),
             "modified": item.stat().st_mtime}
            for item in sorted(backup_dir().glob("memory-*.db"),
                               key=lambda entry: entry.name, reverse=True)
        ]

    def integrity(self) -> dict[str, Any]:
        return self.store.integrity()

    def reindex_vectors(self, *, limit: int = 5000) -> dict[str, Any]:
        """Порахувати вектори для спогадів, у яких їх немає."""
        if self.embedder is None:
            return {"ok": False, "reason": "немає embedding-сервісу", "updated": 0}
        rows = self.store.query(
            "SELECT id, content FROM memories WHERE embedding = '' LIMIT ?",
            (max(1, limit),))
        updated = 0
        for row in rows:
            try:
                vector = self.embedder.encode_one(str(row["content"]))
            except Exception:                        # noqa: BLE001
                LOG.debug("Вектор не пораховано для %s", row["id"], exc_info=True)
                continue
            if not vector:
                continue
            with self.store.transaction() as conn:
                conn.execute(
                    "UPDATE memories SET embedding = ?, embed_model = ? WHERE id = ?",
                    (json.dumps(vector), getattr(self.embedder, "model_tag", ""),
                     str(row["id"])),
                )
            updated += 1
        return {"ok": True, "updated": updated, "checked": len(rows)}

    def rebuild_search(self) -> bool:
        """Перебудувати FTS-індекс із основного сховища."""
        try:
            with self.store.transaction() as conn:
                conn.execute("INSERT INTO memory_fts(memory_fts) VALUES('rebuild')")
            return True
        except Exception:                            # noqa: BLE001
            LOG.warning("FTS-індекс не перебудовано", exc_info=True)
            return False

    def migrate_legacy_rag(self, *, limit: int = 500) -> dict[str, Any]:
        """Перенести спогади зі старого RAG (``rag_memory``), не ламаючи його.

        Стара таблиця лишається на місці: користувач може порівнювати
        обидві системи. Переносяться лише ті записи, яких ще немає.
        """
        from ..config import find_data_dir

        candidates = []
        for root in (Path(find_data_dir(".mcp_rag")), Path.cwd() / ".mcp_rag"):
            for name in ("index.sqlite3", "memoria_infinita.db"):
                candidate = root / name
                if candidate.exists():
                    candidates.append(candidate)
        imported = 0
        skipped = 0
        sources: list[str] = []
        import sqlite3

        for db in dict.fromkeys(candidates):
            try:
                conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
            except sqlite3.Error:
                continue
            try:
                tables = {row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                if "rag_memory" in tables:
                    rows = conn.execute(
                        "SELECT kind, content FROM rag_memory LIMIT ?", (limit,)).fetchall()
                    for kind, content in rows:
                        text = str(content or "").strip()
                        if not text:
                            continue
                        outcome = self.remember(
                            text, kind="fact" if kind not in KINDS else "preference",
                            source=f"rag:{db.name}", provenance=f"{db.name}:rag_memory",
                            confidence=0.55, with_vector=False,
                        )
                        if outcome["created"]:
                            imported += 1
                        else:
                            skipped += 1
                    sources.append(f"{db.name}:rag_memory")
                if "fatti_permanenti" in tables:
                    rows = conn.execute(
                        "SELECT fatto FROM fatti_permanenti LIMIT ?", (limit,)).fetchall()
                    for (text,) in rows:
                        body = str(text or "").strip()
                        if not body:
                            continue
                        outcome = self.remember(
                            body, kind="preference", source=f"rag:{db.name}",
                            provenance=f"{db.name}:fatti_permanenti",
                            confidence=0.6, with_vector=False,
                        )
                        if outcome["created"]:
                            imported += 1
                        else:
                            skipped += 1
                    sources.append(f"{db.name}:fatti_permanenti")
            except sqlite3.Error as exc:
                LOG.debug("Стара база %s недоступна: %s", db, exc)
            finally:
                conn.close()
        return {"imported": imported, "skipped": skipped, "sources": sources}

    def status(self) -> dict[str, Any]:
        """Стан пам'яті для інтерфейсу."""
        stats = self.repository.stats()
        governor = self.governor()
        accuracy = self.predictor.accuracy()
        embedder = self.embedder
        engine = getattr(self, "engine", None)
        tokenizer = None
        if engine is not None and getattr(engine, "model", None) is not None:
            tokenizer = getattr(engine.model, "tokenizer", None)
        return {
            "ok": True,
            "db": str(self.store.path),
            "version": self.store.version,
            "recent": [memory.to_dict() for memory in
                       self.repository.recent(STARTUP_RECENT)],
            "counts": {
                "memories": stats["total"],
                "active": stats["active"],
                "links": stats["links"],
                "conflicts": stats["conflicts"],
                "with_vectors": stats["with_vectors"],
            },
            "kinds": stats["kinds"],
            "search": self.retriever.stats(),
            "prediction": accuracy,
            "vectors": embedder.stats() if embedder is not None else {"ready": False},
            "tokens": {
                "exact": governor.exact,
                "source": "tokenizer моделі" if governor.exact else "оцінка (модель не завантажена)",
                "vocab": tokenizer.size if tokenizer is not None else 0,
            },
            "kinds_available": list(KINDS),
            "last_context": self.last_context(),
            "events": self.repository.events(limit=10),
            "uptime_s": round(time.time() - self._started, 1),
        }

    def close(self) -> None:
        try:
            self.store.close()
        except StoreError:
            pass


__all__ = ["ContextBundle", "MEMORY_WINDOW_SHARE", "Neuromesh", "STARTUP_RECENT"]
