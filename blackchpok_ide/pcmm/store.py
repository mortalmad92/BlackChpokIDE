"""Сховище PCMM: SQLite з WAL, версійованими міграціями й бекапами.

Вимоги, які тут реалізовані буквально:

* **WAL** — читачі не блокують запис, а запис не блокує агента;
* **synchronous=FULL для критичних транзакцій** — втрата останнього
  спогаду неприйнятна; швидкість запису PCMM не є вузьким місцем;
* **foreign_keys=ON**, ``busy_timeout``, явні транзакції;
* **версійовані міграції** — ``PRAGMA user_version`` і послідовні кроки;
* **резервне копіювання через SQLite Backup API** — копіювання файлу
  «в лоб» під час WAL дає биту базу, тому тільки API;
* **контроль цілісності** — ``PRAGMA integrity_check`` і перевірка
  вільного місця перед записом великих обсягів.

Кеші (FTS-індекси, вектори) перебудовуються з основного сховища й ніколи
не є єдиним джерелом істини.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

LOG = logging.getLogger("blackchpok.pcmm.store")

#: Поточна версія схеми. Кожен крок міграції — окрема функція нижче.
SCHEMA_VERSION = 4

#: Скільки чекати на звільнення бази (секунди).
BUSY_TIMEOUT_MS = 8000


class StoreError(RuntimeError):
    """Сховище недоступне або зіпсоване."""


MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: (
        """
        CREATE TABLE IF NOT EXISTS memories (
            id          TEXT PRIMARY KEY,
            kind        TEXT NOT NULL,
            content     TEXT NOT NULL,
            summary     TEXT NOT NULL DEFAULT '',
            source      TEXT NOT NULL DEFAULT '',
            provenance  TEXT NOT NULL DEFAULT '',
            confidence  REAL NOT NULL DEFAULT 0.5,
            created_at  REAL NOT NULL,
            updated_at  REAL NOT NULL,
            accessed_at REAL NOT NULL DEFAULT 0,
            hits        INTEGER NOT NULL DEFAULT 0,
            task        TEXT NOT NULL DEFAULT '',
            files       TEXT NOT NULL DEFAULT '',
            tags        TEXT NOT NULL DEFAULT '',
            valid_from  REAL NOT NULL DEFAULT 0,
            valid_to    REAL NOT NULL DEFAULT 0,
            superseded_by TEXT NOT NULL DEFAULT '',
            fingerprint TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL DEFAULT '',
            embedding   TEXT NOT NULL DEFAULT '',
            embed_model TEXT NOT NULL DEFAULT '',
            checksum    TEXT NOT NULL DEFAULT ''
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_mem_kind ON memories(kind)",
        "CREATE INDEX IF NOT EXISTS idx_mem_created ON memories(created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_mem_task ON memories(task)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_mem_hash ON memories(content_hash)",
        """
        CREATE TABLE IF NOT EXISTS memory_links (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            src       TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
            dst       TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
            relation  TEXT NOT NULL DEFAULT 'related',
            weight    REAL NOT NULL DEFAULT 0.5,
            created_at REAL NOT NULL,
            UNIQUE(src, dst, relation)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_link_src ON memory_links(src)",
        "CREATE INDEX IF NOT EXISTS idx_link_dst ON memory_links(dst)",
        """
        CREATE TABLE IF NOT EXISTS memory_events (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id TEXT NOT NULL DEFAULT '',
            action    TEXT NOT NULL,
            detail    TEXT NOT NULL DEFAULT '',
            actor     TEXT NOT NULL DEFAULT 'system',
            at        REAL NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_events_at ON memory_events(at DESC)",
        """
        CREATE TABLE IF NOT EXISTS task_history (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            task      TEXT NOT NULL,
            action    TEXT NOT NULL,
            status    TEXT NOT NULL DEFAULT 'ok',
            detail    TEXT NOT NULL DEFAULT '',
            files     TEXT NOT NULL DEFAULT '',
            tools     TEXT NOT NULL DEFAULT '',
            at        REAL NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_task_history_at ON task_history(at DESC)",
        """
        CREATE TABLE IF NOT EXISTS predictions (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            context   TEXT NOT NULL,
            predicted TEXT NOT NULL,
            actual    TEXT NOT NULL DEFAULT '',
            score     REAL NOT NULL DEFAULT 0,
            hit       INTEGER NOT NULL DEFAULT 0,
            at        REAL NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS feedback (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id TEXT NOT NULL,
            useful    INTEGER NOT NULL DEFAULT 1,
            note      TEXT NOT NULL DEFAULT '',
            at        REAL NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS stats (
            key   TEXT PRIMARY KEY,
            value REAL NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL
        )
        """,
    ),
    2: (
        # Повнотекстовий індекс: лексемний пошук без зовнішніх сервісів.
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
            content, summary, tags,
            content='memories', content_rowid='rowid', tokenize='unicode61 remove_diacritics 2'
        )
        """,
        """
        CREATE TRIGGER IF NOT EXISTS memory_fts_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memory_fts(rowid, content, summary, tags)
            VALUES (new.rowid, new.content, new.summary, new.tags);
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS memory_fts_ad AFTER DELETE ON memories BEGIN
            INSERT INTO memory_fts(memory_fts, rowid, content, summary, tags)
            VALUES('delete', old.rowid, old.content, old.summary, old.tags);
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS memory_fts_au AFTER UPDATE ON memories BEGIN
            INSERT INTO memory_fts(memory_fts, rowid, content, summary, tags)
            VALUES('delete', old.rowid, old.content, old.summary, old.tags);
            INSERT INTO memory_fts(rowid, content, summary, tags)
            VALUES (new.rowid, new.content, new.summary, new.tags);
        END
        """,
    ),
    3: (
        # Конфлікти й версії: історія змін фактів без втрати попередніх.
        """
        CREATE TABLE IF NOT EXISTS contradictions (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            left_id   TEXT NOT NULL,
            right_id  TEXT NOT NULL,
            reason    TEXT NOT NULL DEFAULT '',
            resolved  INTEGER NOT NULL DEFAULT 0,
            resolution TEXT NOT NULL DEFAULT '',
            at        REAL NOT NULL,
            UNIQUE(left_id, right_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS memory_versions (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id TEXT NOT NULL,
            content   TEXT NOT NULL,
            confidence REAL NOT NULL,
            at        REAL NOT NULL,
            reason    TEXT NOT NULL DEFAULT ''
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_versions_mem ON memory_versions(memory_id)",
    ),
    4: (
        # ``content_hash`` більше НЕ унікальний.
        #
        # Чому: унікальність забороняла консолідацію історичних дублікатів.
        # Коли нормалізація тексту змінюється (а вона змінювалась: кінцева
        # пунктуація, регістр), у спадковій базі вже лежать два рядки з тим
        # самим змістом — і CONSTRAINT не давав їх злити, кидаючи
        # ``UNIQUE constraint failed``. Дублікати тепер ловить застосунок
        # (``MemoryRepository.save``), а база гарантує лише швидкий пошук.
        "DROP INDEX IF EXISTS idx_mem_hash",
        "CREATE INDEX IF NOT EXISTS idx_mem_hash ON memories(content_hash)",
        "CREATE INDEX IF NOT EXISTS idx_mem_fingerprint ON memories(fingerprint, kind)",
    ),
}


class MemoryStore:
    """Обгортка над SQLite-файлом пам'яті NEUROMESH."""

    def __init__(self, path: str | Path | None = None, *, critical: bool = True) -> None:
        self.path = Path(path) if path else default_db_path()
        self.critical = critical
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._closed = False
        self.last_error = ""
        self._open()

    # ── відкриття ─────────────────────────────────────────────────────────
    def _open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(str(self.path), timeout=BUSY_TIMEOUT_MS / 1000.0,
                                   check_same_thread=False)
        except sqlite3.Error as exc:
            raise StoreError(f"Не вдалось відкрити {self.path}: {exc}") from exc
        conn.row_factory = sqlite3.Row
        self._conn = conn
        self._configure()
        self.migrate()

    def _configure(self) -> None:
        conn = self._connection()
        pragmas = [
            "PRAGMA journal_mode=WAL",
            "PRAGMA foreign_keys=ON",
            f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}",
            # Критичні записи: хай повільно, зате не втрачаються.
            "PRAGMA synchronous=FULL" if self.critical else "PRAGMA synchronous=NORMAL",
            "PRAGMA temp_store=MEMORY",
            "PRAGMA cache_size=-16000",
            "PRAGMA wal_autocheckpoint=500",
        ]
        for statement in pragmas:
            try:
                conn.execute(statement)
            except sqlite3.Error:
                LOG.warning("Не застосовано %s", statement, exc_info=True)

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None or self._closed:
            raise StoreError("Сховище закрито.")
        return self._conn

    # ── міграції ──────────────────────────────────────────────────────────
    @property
    def version(self) -> int:
        try:
            row = self._connection().execute("PRAGMA user_version").fetchone()
            return int(row[0] if row else 0)
        except sqlite3.Error:
            return 0

    def migrate(self) -> int:
        """Застосувати всі відсутні кроки схеми."""
        current = self.version
        if current >= SCHEMA_VERSION:
            return current
        conn = self._connection()
        with self._lock:
            for version in sorted(MIGRATIONS):
                if version <= current:
                    continue
                LOG.info("Міграція пам'яті → версія %d", version)
                try:
                    with conn:
                        for statement in MIGRATIONS[version]:
                            conn.execute(statement)
                        conn.execute(f"PRAGMA user_version={version}")
                except sqlite3.Error as exc:
                    raise StoreError(
                        f"Міграція до версії {version} не вдалась: {exc}") from exc
                current = version
        return current

    # ── транзакції ────────────────────────────────────────────────────────
    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Явна транзакція з відкатом при помилці."""
        conn = self._connection()
        with self._lock:
            try:
                conn.execute("BEGIN IMMEDIATE")
            except sqlite3.Error as exc:
                if "within a transaction" not in str(exc):
                    raise StoreError(f"Не вдалось почати транзакцію: {exc}") from exc
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        conn = self._connection()
        with self._lock:
            return conn.execute(sql, params)

    def query(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        return list(self.execute(sql, params).fetchall())

    def one(self, sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
        return self.execute(sql, params).fetchone()

    # ── здоров'я ──────────────────────────────────────────────────────────
    def integrity(self) -> dict[str, Any]:
        """``PRAGMA integrity_check`` + розміри файлів."""
        result: dict[str, Any] = {"ok": False, "problems": [], "path": str(self.path)}
        try:
            row = self._connection().execute("PRAGMA integrity_check").fetchone()
            verdict = str(row[0]) if row else "?"
            result["verdict"] = verdict
            result["ok"] = verdict.lower() == "ok"
            if not result["ok"]:
                result["problems"].append(verdict)
        except sqlite3.Error as exc:
            result["problems"].append(str(exc))
        for suffix, label in (("", "db"), ("-wal", "wal"), ("-shm", "shm")):
            candidate = Path(str(self.path) + suffix)
            size = candidate.stat().st_size if candidate.exists() else 0
            result[f"{label}_bytes"] = size
        result["version"] = self.version
        return result

    def checkpoint(self) -> bool:
        """Перенести WAL у основний файл (щоб бекап був компактним)."""
        try:
            self._connection().execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return True
        except sqlite3.Error:
            LOG.warning("WAL checkpoint не вдався", exc_info=True)
            return False

    def vacuum(self) -> bool:
        try:
            self._connection().execute("VACUUM")
            return True
        except sqlite3.Error:
            LOG.warning("VACUUM не вдався", exc_info=True)
            return False

    # ── бекапи ────────────────────────────────────────────────────────────
    def backup(self, target: str | Path) -> Path:
        """Зробити консистентний бекап через SQLite Backup API.

        Копіювати файл через ``shutil.copy`` не можна: у режимі WAL свіжі
        дані лежать у ``-wal``, і копія вийде старішою або битою.
        """
        destination = Path(target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.checkpoint()
            # ``with sqlite3.connect(...)`` НЕ закриває з'єднання — лише
            # commit/rollback. Перевірено: після виходу з блоку з'єднання
            # далі працює. Для бекапу це означало відкритий дескриптор на
            # файл-призначення, а на Windows такий файл потім не
            # видалити/перейменувати.
            backup_conn = sqlite3.connect(str(destination))
            try:
                self._connection().backup(backup_conn)
            finally:
                backup_conn.close()
        except sqlite3.Error as exc:
            raise StoreError(f"Бекап не вдався: {exc}") from exc
        LOG.info("Бекап пам'яті: %s", destination)
        return destination

    def restore(self, source: str | Path) -> bool:
        """Відновити базу з бекапу (поточний файл зберігається як .before-restore)."""
        origin = Path(source)
        if not origin.exists():
            raise StoreError(f"Бекап не знайдено: {origin}")
        check = sqlite3.connect(str(origin))
        try:
            row = check.execute("PRAGMA integrity_check").fetchone()
            if not row or str(row[0]).lower() != "ok":
                raise StoreError("Бекап пошкоджений — відновлення скасовано.")
        finally:
            check.close()
        safety = Path(str(self.path) + ".before-restore")
        with self._lock:
            self.close()
            try:
                if self.path.exists():
                    shutil.copy2(self.path, safety)
                shutil.copy2(origin, self.path)
                for suffix in ("-wal", "-shm"):
                    leftover = Path(str(self.path) + suffix)
                    if leftover.exists():
                        leftover.unlink()
            except OSError as exc:
                raise StoreError(f"Відновлення не вдалось: {exc}") from exc
        self._closed = False
        self._conn = None
        self._open()
        return True

    def free_space_gb(self) -> float:
        try:
            return shutil.disk_usage(self.path.parent).free / 1024 ** 3
        except OSError:
            return 0.0

    # ── закриття ──────────────────────────────────────────────────────────
    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.commit()
                self._conn.execute("PRAGMA optimize")
            except sqlite3.Error as exc:
                # НЕ ковтаємо: якщо commit не пройшов, записані в памʼять
                # факти лишились лише в журналі WAL і можуть не потрапити
                # на диск. Раніше тут стояло `pass`, і користувач втрачав
                # памʼять без жодного повідомлення.
                LOG.warning("Не вдалось зафіксувати памʼять NEUROMESH: %s", exc)
            try:
                self._conn.close()
            except sqlite3.Error as exc:
                LOG.debug("З'єднання NEUROMESH не закрилось: %s", exc)
        self._conn = None
        self._closed = True

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:                       # pragma: no cover
        try:
            self.close()
        except Exception:                            # noqa: BLE001
            pass


def default_db_path() -> Path:
    """Типовий шлях бази пам'яті: ``<app_data>/neuromesh/memory.db``."""
    from ..config import app_data_dir

    return app_data_dir() / "neuromesh" / "memory.db"


def backup_dir() -> Path:
    folder = default_db_path().parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def timestamped_backup(store: MemoryStore, *, keep: int = 8) -> Path:
    """Бекап із міткою часу + ротація старих."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = backup_dir() / f"memory-{stamp}.db"
    store.backup(target)
    backups = sorted(backup_dir().glob("memory-*.db"), key=lambda item: item.name)
    for stale in backups[:-keep] if keep > 0 else []:
        try:
            stale.unlink()
        except OSError:
            pass
    return target


__all__ = [
    "BUSY_TIMEOUT_MS",
    "MIGRATIONS",
    "MemoryStore",
    "SCHEMA_VERSION",
    "StoreError",
    "backup_dir",
    "default_db_path",
    "timestamped_backup",
]
