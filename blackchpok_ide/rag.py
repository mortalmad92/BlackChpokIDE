"""Міст між IDE та наявним рушієм RAG (``rag_engine.LocalRAG``).

Рушій ``rag_engine.py`` у корені проєкту — повноцінний (SQLite FTS5, BM25,
необов'язкові вектори, пам'ять). Доти його використовував лише MCP-сервер
(``server.py``), а сама IDE індексу не бачила взагалі: ні статусу, ні пошуку.

Цей модуль не переписує RAG і не робить паралельної реалізації — він лише
передає рушію ті самі функції робочої теки, якими користується решта IDE
(``workspace.safe_join``, ``workspace.walk_text_files`` тощо), і приводить
його текстові відповіді (JSON-рядки) до зручних для інтерфейсу структур.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import workspace as ws

LOG = logging.getLogger("blackchpok.rag")

#: Розширення, які індексуємо за замовчуванням (як у MCP-сервері).
DEFAULT_EXTENSIONS = (
    ".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".ini", ".cfg",
    ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".sql", ".sh", ".bat",
    ".ps1", ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs", ".java", ".kt",
)


def _engine_class():
    """Імпортувати рушій (він лежить у корені проєкту, не в пакеті)."""
    try:
        from rag_engine import LocalRAG  # type: ignore[import-not-found]
        return LocalRAG
    except ImportError as exc:  # pragma: no cover - залежить від розкладки
        LOG.warning("Рушій RAG недоступний: %s", exc)
        return None


@dataclass
class RagStatus:
    """Стан індексу для панелі."""

    ready: bool = False
    documents: int = 0
    chunks: int = 0
    vectors: int = 0
    memories: int = 0
    last_indexed: str = ""
    mode: str = ""
    database: str = ""
    fts5: bool = False
    error: str = ""

    @property
    def summary(self) -> str:
        if self.error:
            return f"Помилка: {self.error}"
        if not self.ready:
            return "Індекс не створено"
        parts = [f"{self.documents} файлів", f"{self.chunks} фрагментів"]
        if self.vectors:
            parts.append(f"{self.vectors} з векторами")
        return " · ".join(parts)


@dataclass
class RagHit:
    """Один результат пошуку."""

    path: str = ""
    start_line: int = 0
    end_line: int = 0
    score: float = 0.0
    preview: str = ""
    chunk_id: int = 0

    @property
    def location(self) -> str:
        if self.start_line and self.end_line and self.end_line != self.start_line:
            return f"{self.path}:{self.start_line}-{self.end_line}"
        if self.start_line:
            return f"{self.path}:{self.start_line}"
        return self.path


@dataclass
class RagAnswer:
    """Результат пошуку: список збігів і текст, який можна вставити в чат."""

    hits: list[RagHit] = field(default_factory=list)
    message: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


class RagService:
    """Обгортка над ``LocalRAG`` для вікна IDE."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self.engine: Any = None
        self._error = ""

    # ── життєвий цикл ──────────────────────────────────────────────────────
    @property
    def root(self) -> Path:
        return self._root

    @root.setter
    def root(self, value: Path | str) -> None:
        self.set_root(Path(value))

    def set_root(self, root: Path) -> None:
        """Перемкнути робочу теку (рушій прив'язаний до кореня)."""
        new_root = Path(root).resolve()
        if self.engine is not None and new_root == self._root:
            return
        self._root = new_root
        self.engine = None
        self._error = ""

    def available(self) -> bool:
        """Чи вдалось підключити рушій (модуль знайдено)."""
        return self._ensure() is not None

    def _ensure(self):
        if self.engine is not None:
            return self.engine
        engine_class = _engine_class()
        if engine_class is None:
            self._error = "Модуль rag_engine.py не знайдено."
            return None
        try:
            root = self._root.resolve()
            self.engine = engine_class(
                root,
                lambda relative, must_exist=False: ws.safe_join(root, relative),
                lambda folder: ws.walk_text_files(Path(folder)),
                lambda path, max_bytes=0: ws.read_text_file(Path(path))[0],
                lambda path: ws.relative_to_root(root, Path(path)),
            )
            self._error = ""
        except Exception as exc:  # noqa: BLE001 - RAG не має валити IDE
            LOG.warning("Не вдалось створити рушій RAG: %s", exc)
            self._error = str(exc)
            self.engine = None
        return self.engine

    # ── стан ───────────────────────────────────────────────────────────────
    def status(self) -> RagStatus:
        engine = self._ensure()
        if engine is None:
            return RagStatus(error=self._error or "Рушій недоступний")
        try:
            raw = json.loads(engine.status())
        except (TypeError, ValueError) as exc:
            return RagStatus(error=f"Нерозбірливий стан: {exc}")
        except Exception as exc:  # noqa: BLE001
            return RagStatus(error=f"{type(exc).__name__}: {exc}")
        if not isinstance(raw, dict):
            return RagStatus(error="Неочікуваний формат стану")
        documents = _as_int(raw.get("documents"))
        return RagStatus(
            ready=str(raw.get("status") or "") == "ready" and documents > 0,
            documents=documents,
            chunks=_as_int(raw.get("chunks")),
            vectors=_as_int(raw.get("chunks_with_embeddings")),
            memories=_as_int(raw.get("memories")),
            last_indexed=str(raw.get("last_indexed_at_utc") or ""),
            mode=str(raw.get("retrieval_mode") or ""),
            database=str(raw.get("database") or ""),
            fts5=bool(raw.get("fts5_available")),
        )

    # ── індексація ─────────────────────────────────────────────────────────
    def index(
        self,
        path: str = ".",
        *,
        extensions: str = "",
        force: bool = False,
        max_files: int = 5000,
    ) -> str:
        """Проіндексувати робочу теку (або вказаний шлях). Повертає текст."""
        engine = self._ensure()
        if engine is None:
            return self._error or "Рушій RAG недоступний."
        try:
            return engine.index_workspace(
                path=path or ".",
                extensions=extensions or ",".join(DEFAULT_EXTENSIONS),
                force_reindex=bool(force),
                max_files=max_files,
            )
        except Exception as exc:  # noqa: BLE001
            LOG.warning("Індексація не вдалась: %s", exc)
            return f"Помилка індексації: {type(exc).__name__}: {exc}"

    def clear(self, confirm: bool = True) -> str:
        """Очистити індекс."""
        engine = self._ensure()
        if engine is None:
            return self._error or "Рушій RAG недоступний."
        try:
            return engine.clear_index(confirm=bool(confirm))
        except Exception as exc:  # noqa: BLE001
            return f"Помилка очищення: {type(exc).__name__}: {exc}"

    def remove_path(self, path: str, confirm: bool = False) -> str:
        engine = self._ensure()
        if engine is None:
            return self._error or "Рушій RAG недоступний."
        try:
            return engine.remove_from_index(path, confirm=bool(confirm))
        except Exception as exc:  # noqa: BLE001
            return f"Помилка видалення з індексу: {type(exc).__name__}: {exc}"

    # ── пошук ──────────────────────────────────────────────────────────────
    def search(self, query: str, *, top_k: int = 8, path_prefix: str = "") -> RagAnswer:
        """Пошук фрагментів у проіндексованому проєкті."""
        clean = (query or "").strip()
        if not clean:
            return RagAnswer(message="Порожній запит.")
        engine = self._ensure()
        if engine is None:
            return RagAnswer(error=self._error or "Рушій RAG недоступний.")
        try:
            raw_text = engine.search(clean, top_k=top_k, path_prefix=path_prefix)
        except Exception as exc:  # noqa: BLE001
            return RagAnswer(error=f"{type(exc).__name__}: {exc}")
        return _parse_answer(raw_text)

    def context(self, query: str, *, top_k: int = 6, max_chars: int = 8000,
                path_prefix: str = "") -> RagAnswer:
        """Розширений контекст — для вставки в запит агенту."""
        clean = (query or "").strip()
        if not clean:
            return RagAnswer(message="Порожній запит.")
        engine = self._ensure()
        if engine is None:
            return RagAnswer(error=self._error or "Рушій RAG недоступний.")
        try:
            raw_text = engine.get_context(clean, top_k=top_k, max_chars=max_chars,
                                         path_prefix=path_prefix)
        except Exception as exc:  # noqa: BLE001
            return RagAnswer(error=f"{type(exc).__name__}: {exc}")
        return _parse_answer(raw_text)


# ─────────────────────────────────────────────────────────────────────────────
# Розбір відповідей рушія
# ─────────────────────────────────────────────────────────────────────────────

def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_answer(raw: Any) -> RagAnswer:
    """Перетворити відповідь рушія (JSON-рядок або текст) у :class:`RagAnswer`."""
    if not isinstance(raw, str):
        return RagAnswer(error="Неочікуваний тип відповіді")
    text = raw.strip()
    if not text:
        return RagAnswer(message="Порожня відповідь.")
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        # Рушій віддає звичайний текст, коли індекс порожній або запит дивний.
        return RagAnswer(message=text)
    if not isinstance(data, dict):
        return RagAnswer(message=text)
    if data.get("error"):
        return RagAnswer(error=str(data["error"]))
    raw_hits = data.get("results") or data.get("matches") or []
    hits: list[RagHit] = []
    if isinstance(raw_hits, list):
        for item in raw_hits:
            if not isinstance(item, dict):
                continue
            # Рушій віддає source/line_start/line_end/text; сумісні ключі
            # лишаємо на випадок іншої версії.
            hits.append(RagHit(
                path=str(item.get("source") or item.get("path") or ""),
                start_line=_as_int(item.get("line_start") or item.get("start_line")),
                end_line=_as_int(item.get("line_end") or item.get("end_line")),
                score=_as_float(item.get("score") or item.get("rank")),
                preview=str(item.get("text") or item.get("preview")
                            or item.get("snippet") or item.get("content") or "")[:2000],
                chunk_id=_as_int(item.get("chunk_id") or item.get("id")),
            ))
    return RagAnswer(hits=hits, message=str(data.get("message") or ""))


def format_for_prompt(answer: RagAnswer) -> str:
    """Текст для вставки в запит агенту (компактно, з джерелами)."""
    if answer.error:
        return ""
    if answer.message:
        return answer.message
    if not answer.hits:
        return ""
    chunks: list[str] = []
    for hit in answer.hits:
        body = hit.preview.strip()
        if not body:
            continue
        chunks.append(f"--- {hit.location} ---\n{body}")
    return "\n\n".join(chunks)


__all__ = [
    "DEFAULT_EXTENSIONS",
    "RagAnswer",
    "RagHit",
    "RagService",
    "RagStatus",
    "format_for_prompt",
]
