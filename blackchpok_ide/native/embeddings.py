"""Локальний embedding-сервіс із кешем на диску.

Навіщо окремий шар поверх :meth:`NativeEngine.embed`:

* **Кеш.** Той самий фрагмент коду індексується повторно після кожної
  правки. Без кешу кожне оновлення коштує секунд GPU.
* **Стабільність.** Вектори зберігаються з підписом моделі й розмірністю:
  якщо модель змінилась, старі вектори не «тихо» дають нульову схожість,
  а чесно інвалідуються.
* **Батчі.** Один виклик рушія на кілька текстів, із прогресом.

Сховище — SQLite (той самий файл, що й у пам'яті NEUROMESH), таблиця
``embed_cache``. Ніяких зовнішніх серверів: вектори рахує завантажена
модель у процесі IDE.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, Sequence

LOG = logging.getLogger("blackchpok.native.embeddings")

#: Скільки символів максимум беремо в один фрагмент для вектора.
MAX_TEXT = 4000
#: Розмір батчу за замовчуванням.
BATCH = 8


def text_hash(text: str) -> str:
    """Стабільний ключ кешу для тексту."""
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:32]


@dataclass
class EmbeddingResult:
    """Результат для одного тексту."""

    key: str
    vector: list[float]
    cached: bool = False
    model: str = ""

    @property
    def dim(self) -> int:
        return len(self.vector)


class EmbeddingService:
    """Вектори текстів: локальний розрахунок + кеш у SQLite."""

    def __init__(self, engine: "object", db_path: str | Path | None = None, *,
                 model_tag: str = "", normalize: bool = True) -> None:
        self.engine = engine
        self.normalize = normalize
        self._model_tag = model_tag
        self._db_path = Path(db_path) if db_path else None
        self._lock = threading.RLock()
        self._dim = 0
        self._stats = {"computed": 0, "cached": 0, "batches": 0, "errors": 0}
        if self._db_path is not None:
            self._init_db()

    # ── ідентифікація моделі ──────────────────────────────────────────────
    @property
    def model_tag(self) -> str:
        """Підпис моделі: шлях + розмір + час зміни файлу.

        Саме цей рядок бере участь у ключі кешу, тому після підміни файлу
        моделі старі вектори автоматично стають недоступними.
        """
        if self._model_tag:
            return self._model_tag
        engine = self.engine
        path = getattr(engine, "model_path", "") or ""
        if not path:
            return "none"
        try:
            stat = Path(path).stat()
            self._model_tag = f"{Path(path).name}:{stat.st_size}:{int(stat.st_mtime)}"
        except OSError:
            self._model_tag = Path(path).name
        return self._model_tag

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def ready(self) -> bool:
        """Чи можна рахувати вектори зараз (модель завантажена)."""
        return bool(getattr(self.engine, "loaded", False))

    # ── база ──────────────────────────────────────────────────────────────
    def _init_db(self) -> None:
        assert self._db_path is not None
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS embed_cache (
                    key        TEXT PRIMARY KEY,
                    model      TEXT NOT NULL,
                    dim        INTEGER NOT NULL,
                    vector     TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_embed_model ON embed_cache(model, dim)"
            )
            conn.commit()

    @contextlib.contextmanager
    def _connect(self) -> "Iterator[sqlite3.Connection]":
        """З'єднання, яке СПРАВДІ закривається після блоку.

        ``with sqlite3.connect(...)`` у Python **не закриває** з'єднання —
        він лише робить commit/rollback. Перевірено: після виходу з блоку
        ``conn.execute("SELECT 1")`` і далі працює. Кожен ``encode`` /
        запис у кеш лишав відкритий дескриптор і WAL-файл; на Windows це
        зрештою блокує базу й не дає видалити/перейменувати файл.

        Тепер ``_connect`` — контекстний менеджер, тож усі п'ять місць
        використання закривають з'єднання автоматично.
        """
        assert self._db_path is not None
        conn = sqlite3.connect(str(self._db_path), timeout=10.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            with conn:                        # commit/rollback
                yield conn
        finally:
            conn.close()

    # ── основна операція ──────────────────────────────────────────────────
    def encode(self, texts: Sequence[str], *,
               on_progress: Callable[[int, int], None] | None = None,
               use_cache: bool = True) -> list[list[float]]:
        """Порахувати вектори для списку текстів (з кешем)."""
        cleaned = [(text or "")[:MAX_TEXT] for text in texts]
        if not cleaned:
            return []
        tag = self.model_tag
        keys = [f"{tag}:{text_hash(text)}" for text in cleaned]
        vectors: list[list[float] | None] = [None] * len(cleaned)

        if use_cache and self._db_path is not None:
            cached = self._load_cached(keys, tag)
            for index, vector in enumerate(cached):
                if vector is not None:
                    vectors[index] = vector
            with self._lock:
                self._stats["cached"] += sum(1 for item in vectors if item is not None)

        missing = [index for index, vector in enumerate(vectors) if vector is None]
        if missing:
            if not self.ready:
                raise EmbeddingUnavailable(
                    "Локальні embeddings недоступні: модель не завантажена. "
                    "Завантаж модель у розділі «AI Runtime».")
            produced = self._compute([cleaned[index] for index in missing],
                                     on_progress=on_progress)
            for position, index in enumerate(missing):
                vectors[index] = produced[position]
                if self._dim == 0 and produced[position]:
                    self._dim = len(produced[position])
            if use_cache and self._db_path is not None:
                self._store(keys, [vectors[index] for index in missing], tag,
                            [cleaned[index] for index in missing])
        return [vector or [] for vector in vectors]

    def encode_one(self, text: str, *, use_cache: bool = True) -> list[float]:
        result = self.encode([text], use_cache=use_cache)
        return result[0] if result else []

    def _compute(self, texts: list[str],
                 on_progress: Callable[[int, int], None] | None = None
                 ) -> list[list[float]]:
        engine = self.engine
        embed = getattr(engine, "embed", None)
        if embed is None:
            raise EmbeddingUnavailable("Рушій не вміє рахувати вектори.")
        out: list[list[float]] = []
        total = len(texts)
        for start in range(0, total, BATCH):
            chunk = texts[start:start + BATCH]
            try:
                produced = embed(chunk, normalize=self.normalize)
            except Exception as exc:                 # noqa: BLE001
                with self._lock:
                    self._stats["errors"] += 1
                raise EmbeddingUnavailable(f"Не вдалось порахувати вектори: {exc}") from exc
            with self._lock:
                self._stats["batches"] += 1
                self._stats["computed"] += len(produced)
            out.extend(produced)
            if on_progress is not None:
                on_progress(min(total, start + len(chunk)), total)
        return out

    # ── кеш ───────────────────────────────────────────────────────────────
    def _load_cached(self, keys: list[str], tag: str) -> list[list[float] | None]:
        result: list[list[float] | None] = [None] * len(keys)
        try:
            with self._connect() as conn:
                for start in range(0, len(keys), 400):
                    part = keys[start:start + 400]
                    marks = ",".join("?" * len(part))
                    rows = conn.execute(
                        f"SELECT key, dim, vector FROM embed_cache "
                        f"WHERE model = ? AND key IN ({marks})",
                        [tag, *part],
                    ).fetchall()
                    index_of = {key: start + offset for offset, key in enumerate(part)}
                    for key, dim, raw in rows:
                        if self._dim and int(dim) != self._dim:
                            continue        # інша розмірність — не змішуємо
                        try:
                            vector = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(vector, list) and vector:
                            result[index_of[key]] = [float(value) for value in vector]
                            if not self._dim:
                                self._dim = int(dim)
        except sqlite3.Error as exc:                 # pragma: no cover - рідко
            LOG.warning("Кеш векторів недоступний: %s", exc)
        return result

    def _store(self, keys: list[str], vectors: list[Sequence[float] | None],
               tag: str, texts: list[str]) -> None:
        rows = []
        now = time.time()
        for key, vector, text in zip(keys, vectors, texts):
            if not vector:
                continue
            rows.append((key, tag, len(vector),
                         json.dumps([round(float(value), 6) for value in vector]),
                         now))
        if not rows:
            return
        try:
            with self._connect() as conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO embed_cache"
                    "(key, model, dim, vector, created_at) VALUES (?,?,?,?,?)",
                    rows,
                )
                conn.commit()
        except sqlite3.Error as exc:                 # pragma: no cover
            LOG.warning("Не вдалось зберегти вектори: %s", exc)

    def invalidate(self, *, model: str = "") -> int:
        """Прибрати кеш (усе або лише для моделі)."""
        if self._db_path is None:
            return 0
        try:
            with self._connect() as conn:
                if model:
                    cursor = conn.execute("DELETE FROM embed_cache WHERE model = ?", (model,))
                else:
                    cursor = conn.execute("DELETE FROM embed_cache")
                conn.commit()
                return int(cursor.rowcount or 0)
        except sqlite3.Error:
            return 0

    def stats(self) -> dict[str, object]:
        with self._lock:
            data: dict[str, object] = dict(self._stats)
        data.update(
            {
                "model": self.model_tag,
                "dim": self._dim,
                "ready": self.ready,
                "db": str(self._db_path) if self._db_path else "",
            }
        )
        if self._db_path is not None:
            try:
                with self._connect() as conn:
                    row = conn.execute(
                        "SELECT COUNT(*), COUNT(DISTINCT model) FROM embed_cache").fetchone()
                    data["cached_vectors"] = int(row[0] or 0)
                    data["models_cached"] = int(row[1] or 0)
            except sqlite3.Error:
                pass
        return data


class EmbeddingUnavailable(RuntimeError):
    """Вектори порахувати неможливо (немає моделі або рушія)."""


# ─────────────────────────────────────────────────────────────────────────────
# Векторні операції без numpy
# ─────────────────────────────────────────────────────────────────────────────

def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Косинусна схожість; 0.0 для різних розмірностей (не «тихо» 1.0)."""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for a, b in zip(left, right):
        dot += a * b
        na += a * a
        nb += b * b
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / ((na ** 0.5) * (nb ** 0.5))


def top_k(query: Sequence[float], vectors: Iterable[tuple[str, Sequence[float]]],
          k: int = 10) -> list[tuple[str, float]]:
    """Найближчі сусіди за косинусом."""
    scored = [(key, cosine(query, vector)) for key, vector in vectors]
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:max(0, k)]


__all__ = [
    "BATCH",
    "MAX_TEXT",
    "EmbeddingResult",
    "EmbeddingService",
    "EmbeddingUnavailable",
    "cosine",
    "text_hash",
    "top_k",
]
