"""Гібридний пошук по пам'яті: лексемний + векторний + граф + час.

Чому не «просто BM25» і не «просто косинус»:

* BM25 добре ловить збіг імен і шляхів (``agent_tools.read_file``), але
  провалюється на перефразуваннях;
* вектори ловлять зміст, але для точного імені інколи промахуються;
* граф дає те, чого немає в тексті: «це виправлення пов'язане з тією
  помилкою»;
* час важливий, бо застаріле рішення не має переважати свіже.

Тому оцінка — зважена сума, а ваги й набір каналів обирає
:class:`AdaptivePolicy` залежно від запиту. Це і є «адаптивна політика
пошуку»: не ганяємо всі механізми щоразу.

Усі ваги й формули — звичайні, відомі (BM25, косинус, RRF, часовий спад).
Власного «алгоритму» тут немає й не заявляється.
"""

from __future__ import annotations

import logging
import math
import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .models import KIND_WEIGHT, Memory, tokens_of
from .repository import MemoryRepository

LOG = logging.getLogger("blackchpok.pcmm.retrieval")

#: Ваги каналів за замовчуванням (сума = 1.0).
BASE_WEIGHTS = {
    "lexical": 0.34,
    "semantic": 0.34,
    "graph": 0.12,
    "temporal": 0.10,
    "confidence": 0.10,
}

#: Скільки кандидатів бере кожен канал.
CHANNEL_LIMIT = 60
#: Стала часового спаду: за 30 днів вага падає приблизно вдвічі.
TIME_HALF_LIFE_DAYS = 30.0

_QUOTED = re.compile(r'"([^"]+)"')
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{2,}|[\w\-/]+\.(?:py|js|ts|go|rs|java|cs|json|md)")


@dataclass
class SearchPolicy:
    """Які канали вмикати для цього запиту."""

    lexical: bool = True
    semantic: bool = True
    graph: bool = True
    temporal: bool = True
    weights: dict[str, float] = field(default_factory=lambda: dict(BASE_WEIGHTS))
    reason: str = ""
    limit: int = 12

    def describe(self) -> str:
        active = [name for name in ("lexical", "semantic", "graph", "temporal")
                  if getattr(self, name)]
        return f"{'+'.join(active) or 'lexical'} ({self.reason})"


def choose_policy(query: str, *, vectors_ready: bool, limit: int = 12) -> SearchPolicy:
    """Обрати канали пошуку під конкретний запит.

    Правила свідомо прості й передбачувані:

    * точний ідентифікатор (ім'я функції, шлях) → лексемний пошук;
    * довгий описовий запит → додаємо семантику;
    * немає векторів → семантика вимикається (а не «працює на нулях»);
    * короткий запит із кількох слів → граф і час майже не потрібні.
    """
    text = (query or "").strip()
    words = tokens_of(text)
    policy = SearchPolicy(limit=limit)
    policy.semantic = vectors_ready
    has_identifier = bool(_IDENTIFIER.search(text)) or bool(_QUOTED.search(text))
    if not vectors_ready:
        policy.weights["lexical"] += policy.weights["semantic"]
        policy.weights["semantic"] = 0.0
        policy.reason = "немає векторів — лише лексемний пошук"
    elif has_identifier:
        policy.weights["lexical"] = 0.52
        policy.weights["semantic"] = 0.24
        policy.weights["graph"] = 0.10
        policy.weights["temporal"] = 0.06
        policy.weights["confidence"] = 0.08
        policy.reason = "точний ідентифікатор"
    elif len(words) >= 6:
        policy.weights["lexical"] = 0.24
        policy.weights["semantic"] = 0.46
        policy.weights["graph"] = 0.12
        policy.weights["temporal"] = 0.08
        policy.weights["confidence"] = 0.10
        policy.reason = "описовий запит"
    else:
        policy.reason = "короткий запит"
    if len(words) <= 2:
        policy.graph = False
        policy.temporal = False
        policy.weights["lexical"] += BASE_WEIGHTS["graph"] * 0.5
        policy.weights["semantic"] += policy.weights["graph"] * 0.5
        policy.weights["graph"] = 0.0
        policy.weights["temporal"] = 0.0
    return policy


@dataclass
class Hit:
    """Один знайдений спогад із поясненням, чому він у списку."""

    memory: Memory
    score: float = 0.0
    channels: dict[str, float] = field(default_factory=dict)
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory": self.memory.to_dict(),
            "score": round(self.score, 4),
            "channels": {key: round(value, 4) for key, value in self.channels.items()},
            "explanation": self.explanation,
        }


class Retriever:
    """Гібридний пошук по пам'яті з поясненням оцінки."""

    def __init__(self, repository: MemoryRepository,
                 embedder: Any | None = None) -> None:
        self.repository = repository
        self.embedder = embedder
        self.store = repository.store
        self._stats = {
            "searches": 0, "hits_served": 0, "semantic_used": 0,
            "lexical_used": 0, "cache_hit": 0,
        }

    # ── публічне ──────────────────────────────────────────────────────────
    @property
    def vectors_ready(self) -> bool:
        """Чи є хоч один вектор у базі (без нього семантика не вмикається)."""
        row = self.store.one(
            "SELECT COUNT(*) AS n FROM memories WHERE embedding != ''")
        return bool(row and int(row["n"]) > 0)

    def search(self, query: str, *, limit: int = 12, kinds: Sequence[str] | None = None,
               task: str = "", files: Sequence[str] | None = None,
               policy: SearchPolicy | None = None,
               activate: bool = True) -> list[Hit]:
        """Знайти релевантні спогади."""
        self._stats["searches"] += 1
        text = (query or "").strip()
        if not text:
            return []
        chosen = policy or choose_policy(text, vectors_ready=self.vectors_ready,
                                         limit=limit)
        candidates: dict[str, dict[str, float]] = {}
        memories: dict[str, Memory] = {}

        if chosen.lexical:
            self._stats["lexical_used"] += 1
            self._lexical(text, kinds, candidates, memories)
        if chosen.semantic and self.embedder is not None:
            self._stats["semantic_used"] += 1
            self._semantic(text, kinds, candidates, memories)
        if chosen.graph:
            self._graph(candidates, memories)
        if files:
            self._by_files(files, candidates, memories)

        if not candidates:
            return []
        ranked: list[Hit] = []
        now = time.time()
        for identifier, channels in candidates.items():
            memory = memories.get(identifier)
            if memory is None:
                continue
            if kinds and memory.kind not in kinds:
                continue
            if task and memory.task and memory.task != task:
                # Чуже завдання не відкидаємо, але знижуємо — як і в пошуку.
                channels["task"] = channels.get("task", 0.0) * 0.6
            channels["temporal"] = self._temporal(memory, now) if chosen.temporal else 0.0
            channels["confidence"] = memory.confidence
            channels["kind"] = min(1.0, memory.kind_weight - 0.7) * 2.0
            total = 0.0
            for name, weight in chosen.weights.items():
                total += weight * channels.get(name, 0.0)
            total += 0.05 * channels.get("kind", 0.0)
            total += 0.08 * channels.get("task", 0.0)
            hit = Hit(memory=memory, score=total, channels=dict(channels))
            hit.explanation = self._explain(hit, chosen)
            ranked.append(hit)
        ranked.sort(key=lambda item: item.score, reverse=True)
        top = ranked[:max(1, limit)]
        if top:
            self._stats["hits_served"] += len(top)
        if activate:
            for hit in top:
                self.repository.touch(hit.memory.id)
        return top

    # ── канали ────────────────────────────────────────────────────────────
    def _lexical(self, query: str, kinds: Sequence[str] | None,
                 candidates: dict[str, dict[str, float]],
                 memories: dict[str, Memory]) -> None:
        """BM25 через FTS5; у разі відсутності — підрахунок збігів."""
        terms = [term for term in tokens_of(query)][:24]
        if not terms:
            return
        # FTS5 не має стемера, тому словоформи не збігаються: «небезпека» не
        # знаходить «небезпечний». Дві стандартні можливості FTS5 це лікують
        # частково: префіксний запит (``term*``) і скорочена основа. Друге —
        # свідомо груба евристика для слов'янських мов (відкидаємо до двох
        # останніх літер), і вона не прикидається лематизацією.
        parts: list[str] = []
        for term in terms:
            parts.append(f'"{term}"')
            if len(term) >= 4:
                parts.append(f'"{term}"*')
            if len(term) >= 7:
                stem = term[:-2]
                parts.append(f'"{stem}"*')
        fts_query = " OR ".join(parts)
        rows: list[sqlite3.Row] = []
        try:
            rows = self.store.query(
                """
                SELECT m.*, bm25(memory_fts) AS rank_score
                FROM memory_fts JOIN memories m ON m.rowid = memory_fts.rowid
                WHERE memory_fts MATCH ? AND m.superseded_by = ''
                ORDER BY rank_score LIMIT ?
                """,
                (fts_query, CHANNEL_LIMIT),
            )
        except sqlite3.Error as exc:
            LOG.debug("FTS-пошук не вдався (%s) — беру підрахунок збігів", exc)
        if not rows:
            rows = self._lexical_fallback(terms)
        if not rows:
            return
        # BM25 у SQLite від'ємний і менший = кращий — нормалізуємо в 0..1.
        scores = []
        for row in rows:
            raw = float(row["rank_score"]) if "rank_score" in row.keys() else 0.0
            scores.append(-raw)
        best = max(scores) if scores else 1.0
        worst = min(scores) if scores else 0.0
        span = max(best - worst, 1e-9)
        for row, score in zip(rows, scores):
            memory = Memory.from_row(row)
            memories[memory.id] = memory
            value = (score - worst) / span
            candidates.setdefault(memory.id, {})["lexical"] = value

    def _lexical_fallback(self, terms: list[str]) -> list[sqlite3.Row]:
        rows = self.store.query(
            "SELECT * FROM memories WHERE superseded_by = '' LIMIT 4000")
        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            haystack = f"{row['content']} {row['summary']} {row['tags']}".lower()
            hits = sum(haystack.count(term) for term in terms)
            if hits:
                scored.append((float(hits), row))
        scored.sort(key=lambda item: item[0], reverse=True)
        out = []
        for hits, row in scored[:CHANNEL_LIMIT]:
            clone = dict(row)
            clone["rank_score"] = -hits
            out.append(clone)                        # type: ignore[arg-type]
        return out                                   # type: ignore[return-value]

    def _semantic(self, query: str, kinds: Sequence[str] | None,
                  candidates: dict[str, dict[str, float]],
                  memories: dict[str, Memory]) -> None:
        if self.embedder is None:
            return
        try:
            query_vector = self.embedder.encode_one(query)
        except Exception:                            # noqa: BLE001
            LOG.debug("Вектор запиту не пораховано", exc_info=True)
            return
        if not query_vector:
            return
        rows = self.store.query(
            "SELECT * FROM memories WHERE embedding != '' AND superseded_by = '' "
            "LIMIT 5000")
        scored: list[tuple[float, sqlite3.Row]] = []
        import json

        for row in rows:
            try:
                vector = json.loads(row["embedding"])
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(vector, list) or len(vector) != len(query_vector):
                continue
            dot = sum(a * b for a, b in zip(query_vector, vector))
            scored.append((dot, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        for dot, row in scored[:CHANNEL_LIMIT]:
            memory = Memory.from_row(row)
            memories[memory.id] = memory
            candidates.setdefault(memory.id, {})["semantic"] = max(0.0, min(1.0, dot))

    def _graph(self, candidates: dict[str, dict[str, float]],
               memories: dict[str, Memory]) -> None:
        """Підтягнути сусідів знайдених спогадів (один крок, не обхід)."""
        seeds = sorted(candidates, key=lambda key: sum(candidates[key].values()),
                       reverse=True)[:8]
        if not seeds:
            return
        marks = ",".join("?" * len(seeds))
        rows = self.store.query(
            f"SELECT src, dst, weight FROM memory_links "
            f"WHERE src IN ({marks}) OR dst IN ({marks})",
            [*seeds, *seeds],
        )
        for row in rows:
            other = str(row["dst"]) if str(row["src"]) in seeds else str(row["src"])
            if other in candidates:
                continue
            memory = self.repository.get(other)
            if memory is None or memory.superseded_by:
                continue
            memories[memory.id] = memory
            candidates.setdefault(memory.id, {})["graph"] = float(row["weight"] or 0.5)

    def _by_files(self, files: Sequence[str], candidates: dict[str, dict[str, float]],
                  memories: dict[str, Memory]) -> None:
        """Спогади, прив'язані до поточних файлів (сильний сигнал)."""
        for memory in self.repository.by_files(files, limit=20):
            memories[memory.id] = memory
            entry = candidates.setdefault(memory.id, {})
            entry["task"] = max(entry.get("task", 0.0), 0.8)

    @staticmethod
    def _temporal(memory: Memory, now: float) -> float:
        """Часовий спад: свіже важливіше, але старе не стає нулем."""
        age_days = max(0.0, (now - memory.created_at) / 86400.0)
        decay = math.exp(-age_days / TIME_HALF_LIFE_DAYS)
        recency = memory.accessed_at / now if memory.accessed_at and now else 0.0
        return max(0.0, min(1.0, 0.7 * decay + 0.3 * recency))

    @staticmethod
    def _explain(hit: Hit, policy: SearchPolicy) -> str:
        """Пояснити, чому спогад потрапив у контекст."""
        parts: list[str] = []
        channels = hit.channels
        if channels.get("lexical", 0) > 0.25:
            parts.append(f"збіг слів {channels['lexical']:.2f}")
        if channels.get("semantic", 0) > 0.35:
            parts.append(f"схожість змісту {channels['semantic']:.2f}")
        if channels.get("graph", 0) > 0:
            parts.append("пов'язаний через граф")
        if channels.get("task", 0) > 0:
            parts.append("стосується поточного завдання/файлів")
        if channels.get("temporal", 0) > 0.6:
            parts.append("свіжий")
        parts.append(f"впевненість {hit.memory.confidence:.2f}")
        parts.append(f"тип {hit.memory.kind}")
        return f"{policy.describe()}: " + "; ".join(parts)

    def stats(self) -> dict[str, Any]:
        data = dict(self._stats)
        data["vectors_ready"] = self.vectors_ready
        return data


# ─────────────────────────────────────────────────────────────────────────────
# Прогнозування контексту (Predictive Context Prefetch)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Prediction:
    """Прогноз: які спогади й файли знадобляться наступними."""

    memories: list[Hit] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    reason: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "memories": [hit.to_dict() for hit in self.memories],
            "files": list(self.files),
            "reason": self.reason,
            "confidence": round(self.confidence, 3),
        }


class ContextPredictor:
    """Передбачення потрібного контексту за поточним станом роботи.

    Сигнали (усі — з реальної історії, не вигадані):

    1. **файли, які зараз відкриті** — найсильніший сигнал;
    2. **переходи між файлами** з ``task_history`` (хто за ким редагувався);
    3. **спогади про ці файли** й сусіди в графі;
    4. **незавершені завдання** (помилки без виправлення).

    Точність прогнозу зберігається в ``predictions`` і показується в
    інтерфейсі: обіцяти «розумне передбачення» без вимірювання не можна.
    """

    def __init__(self, repository: MemoryRepository, retriever: Retriever) -> None:
        self.repository = repository
        self.retriever = retriever
        self.store = repository.store

    def predict(self, *, current_files: Sequence[str] = (),
                task: str = "", query: str = "", limit: int = 8) -> Prediction:
        files = [str(item) for item in current_files if item]
        prediction = Prediction()
        signals: list[str] = []

        if files:
            signals.append("відкриті файли")
            for memory in self.repository.by_files(files, limit=limit):
                prediction.memories.append(Hit(memory=memory, score=memory.confidence,
                                               explanation="прив'язано до відкритого файлу"))
        history = self.repository.task_history(task=task, limit=60) if task else \
            self.repository.task_history(limit=60)
        transitions = self._transitions(history)
        for path in files:
            for following, weight in transitions.get(path, {}).items():
                if following not in prediction.files:
                    prediction.files.append(following)
                    signals.append(f"після {path} зазвичай іде {following}")
                del weight
        if query:
            for hit in self.retriever.search(query, limit=limit, activate=False):
                if any(existing.memory.id == hit.memory.id for existing in prediction.memories):
                    continue
                prediction.memories.append(hit)
        # Незавершені помилки — те, що найчастіше «забувається».
        for memory in self.repository.list(kind="error", limit=5):
            if memory.superseded_by:
                continue
            if not self._has_fix(memory.id):
                prediction.memories.append(Hit(
                    memory=memory, score=0.4,
                    explanation="помилка без зафіксованого виправлення"))
                signals.append("незакрита помилка")

        prediction.memories.sort(key=lambda hit: hit.score, reverse=True)
        prediction.memories = prediction.memories[:limit]
        if signals:
            prediction.reason = "; ".join(dict.fromkeys(signals))
            prediction.confidence = min(1.0, 0.25 + 0.15 * len(set(signals)))
        self._record(prediction)
        return prediction

    @staticmethod
    def _transitions(history: Sequence[dict[str, Any]]) -> dict[str, dict[str, float]]:
        """Порахувати переходи «файл A → файл B» з історії завдань."""
        import json

        counts: dict[str, dict[str, float]] = {}
        for row in history:
            try:
                files = json.loads(row.get("files") or "[]")
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(files, list):
                continue
            for index, path in enumerate(files):
                for following in files[index + 1:]:
                    if following == path:
                        continue
                    bucket = counts.setdefault(str(path), {})
                    bucket[str(following)] = bucket.get(str(following), 0.0) + 1.0
        for bucket in counts.values():
            total = sum(bucket.values()) or 1.0
            for key in bucket:
                bucket[key] = bucket[key] / total
        return counts

    def _has_fix(self, error_id: str) -> bool:
        links = self.repository.links(error_id)
        return any(
            str(item.get("relation")) in {"fixed_by", "supersedes"}
            for item in links["out"] + links["in"]
        )

    def _record(self, prediction: Prediction) -> None:
        try:
            with self.store.transaction() as conn:
                conn.execute(
                    "INSERT INTO predictions (context, predicted, score, at) "
                    "VALUES (?,?,?,?)",
                    (prediction.reason[:300],
                     ",".join(hit.memory.id for hit in prediction.memories)[:2000],
                     prediction.confidence, time.time()),
                )
        except Exception:                            # noqa: BLE001
            LOG.debug("Прогноз не записано", exc_info=True)

    def record_outcome(self, *, used_ids: Sequence[str], predicted_ids: Sequence[str],
                       context: str = "") -> dict[str, Any]:
        """Порахувати точність прогнозу (precision) і зберегти її."""
        used = {str(item) for item in used_ids if item}
        predicted = [str(item) for item in predicted_ids if item]
        hits = len(used & set(predicted))
        precision = (hits / len(predicted)) if predicted else 0.0
        try:
            with self.store.transaction() as conn:
                conn.execute(
                    "UPDATE predictions SET actual = ?, hit = ?, score = ? "
                    "WHERE id = (SELECT id FROM predictions ORDER BY id DESC LIMIT 1)",
                    (",".join(sorted(used))[:2000], 1 if hits else 0, precision),
                )
        except Exception:                            # noqa: BLE001
            LOG.debug("Результат прогнозу не записано", exc_info=True)
        return {"predicted": len(predicted), "used": len(used), "hits": hits,
                "precision": round(precision, 3), "context": context}

    def accuracy(self, limit: int = 200) -> dict[str, Any]:
        """Спостережувана точність прогнозів (не обіцянка, а вимір)."""
        rows = self.store.query(
            "SELECT score, hit, predicted, actual FROM predictions "
            "ORDER BY id DESC LIMIT ?", (max(1, limit),))
        if not rows:
            return {"samples": 0, "precision": 0.0, "hit_rate": 0.0}
        precisions = [float(row["score"] or 0.0) for row in rows]
        hits = sum(1 for row in rows if int(row["hit"] or 0))
        return {
            "samples": len(rows),
            "precision": round(sum(precisions) / len(precisions), 3),
            "hit_rate": round(hits / len(rows), 3),
            "last": rows[0]["score"] if rows else 0.0,
        }


__all__ = [
    "BASE_WEIGHTS",
    "CHANNEL_LIMIT",
    "ContextPredictor",
    "Hit",
    "Prediction",
    "Retriever",
    "SearchPolicy",
    "TIME_HALF_LIFE_DAYS",
    "choose_policy",
]
