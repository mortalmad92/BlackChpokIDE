# Сховище NEUROMESH: SQLite, PRAGMA, міграції, бекапи

`blackchpok_ide/pcmm/store.py` — уся робота з диском. Вимоги, які в коді
реалізовані буквально (з docstring модуля): WAL, `synchronous=FULL` для
критичних транзакцій, `foreign_keys=ON`, `busy_timeout`, версійовані
міграції через `PRAGMA user_version`, бекап **лише** через SQLite Backup
API, контроль цілісності.

## 1. Де лежить файл

```python
def default_db_path() -> Path:
    from ..config import app_data_dir
    return app_data_dir() / "neuromesh" / "memory.db"

def backup_dir() -> Path:
    folder = default_db_path().parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    return folder
```

`app_data_dir()` — перша доступна для запису тека з порядку:
`BLACKCHPOK_HOME` → `%APPDATA%\BlackChpokIDE` → `~/.blackchpokide` →
`%TEMP%\BlackChpokIDE` → `<тека програми>/userdata`.

Перевірено на цій машині:

```
C:\Users\Admin\AppData\Roaming\BlackChpokIDE\neuromesh\memory.db
C:\Users\Admin\AppData\Roaming\BlackChpokIDE\neuromesh\backups\
C:\Users\Admin\AppData\Roaming\BlackChpokIDE\neuromesh\vectors.db   # кеш embeddings
```

Шлях можна перевизначити: `MemoryStore(path)` / `Neuromesh(db_path)` — так
роблять тести (тимчасова тека) і бенчмарк пам'яті.

`MemoryStore.__init__(path=None, critical=True)`: створює батьківську теку,
відкриває `sqlite3.connect(timeout=BUSY_TIMEOUT_MS/1000, check_same_thread=False)`,
ставить `row_factory = sqlite3.Row`, застосовує PRAGMA і виконує `migrate()`.

## 2. PRAGMA

`_configure()` виконує (кожен — з `try/except`; невдача лише логується):

```sql
PRAGMA journal_mode=WAL
PRAGMA foreign_keys=ON
PRAGMA busy_timeout=8000
PRAGMA synchronous=FULL        -- або NORMAL, якщо critical=False
PRAGMA temp_store=MEMORY
PRAGMA cache_size=-16000
PRAGMA wal_autocheckpoint=500
```

| PRAGMA | Значення | Навіщо |
| --- | --- | --- |
| `journal_mode` | `WAL` | читачі не блокують запис, а запис — агента |
| `synchronous` | `FULL` (2) | втрата останнього спогаду неприпустима; швидкість запису не є вузьким місцем |
| `foreign_keys` | `ON` (1) | каскадне видалення `memory_links` разом зі спогадом |
| `busy_timeout` | `8000` мс | чекати на звільнення бази, а не падати одразу |
| `temp_store` | `MEMORY` | тимчасові таблиці в RAM |
| `cache_size` | `-16000` (≈16 МБ) | сторінковий кеш |
| `wal_autocheckpoint` | `500` сторінок | WAL не росте безмежно |

`BUSY_TIMEOUT_MS = 8000` використовується і як `timeout` для
`sqlite3.connect`.

Тести фіксують ці значення: `journal_mode = "wal"`,
`synchronous = 2`, `foreign_keys = 1`.

## 3. Схема таблиць

### Версія 1 — основа

**`memories`** (головна таблиця):

```sql
id            TEXT PRIMARY KEY
kind          TEXT NOT NULL
content       TEXT NOT NULL
summary       TEXT NOT NULL DEFAULT ''
source        TEXT NOT NULL DEFAULT ''
provenance    TEXT NOT NULL DEFAULT ''
confidence    REAL NOT NULL DEFAULT 0.5
created_at    REAL NOT NULL
updated_at    REAL NOT NULL
accessed_at   REAL NOT NULL DEFAULT 0
hits          INTEGER NOT NULL DEFAULT 0
task          TEXT NOT NULL DEFAULT ''
files         TEXT NOT NULL DEFAULT ''     -- JSON-масив
tags          TEXT NOT NULL DEFAULT ''     -- JSON-масив
valid_from    REAL NOT NULL DEFAULT 0
valid_to      REAL NOT NULL DEFAULT 0
superseded_by TEXT NOT NULL DEFAULT ''
fingerprint   TEXT NOT NULL DEFAULT ''
content_hash  TEXT NOT NULL DEFAULT ''
embedding     TEXT NOT NULL DEFAULT ''     -- JSON-масив float
embed_model   TEXT NOT NULL DEFAULT ''
checksum      TEXT NOT NULL DEFAULT ''
```

Індекси v1: `idx_mem_kind(kind)`, `idx_mem_created(created_at DESC)`,
`idx_mem_task(task)`, `idx_mem_hash(content_hash)` — спершу **UNIQUE**
(див. v4).

**`memory_links`**: `id INTEGER PRIMARY KEY AUTOINCREMENT`,
`src`/`dst` — `TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE`,
`relation TEXT NOT NULL DEFAULT 'related'`, `weight REAL NOT NULL DEFAULT 0.5`,
`created_at REAL NOT NULL`, `UNIQUE(src, dst, relation)`. Індекси:
`idx_link_src(src)`, `idx_link_dst(dst)`.

**`memory_events`**: `id`, `memory_id` (без FK), `action`, `detail`, `actor`
(типово `'system'`), `at`. Індекс `idx_events_at(at DESC)`.

**`task_history`**: `id`, `task`, `action`, `status` (типово `'ok'`),
`detail`, `files`, `tools`, `at`. Індекс `idx_task_history_at(at DESC)`.

**`predictions`**: `id`, `context`, `predicted`, `actual`, `score`, `hit`,
`at`. Без індексів. **`feedback`**: `id`, `memory_id`, `useful`, `note`, `at`.

**`stats`**: `key TEXT PRIMARY KEY`, `value REAL`, `updated_at REAL`.
Таблиця створюється, але в коді, який ми читали, ніде не заповнюється.

### Версія 2 — повнотекстовий індекс

```sql
CREATE VIRTUAL TABLE memory_fts USING fts5(
    content, summary, tags,
    content='memories', content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
)
```

Це **external-content** FTS5: дані живуть у `memories`, індекс лише
віддзеркалює. Синхронізація — три тригери: `memory_fts_ai` (AFTER INSERT) →
`INSERT INTO memory_fts(rowid, content, summary, tags)`; `memory_fts_ad`
(AFTER DELETE) → `INSERT INTO memory_fts(memory_fts, …) VALUES('delete', …)`;
`memory_fts_au` (AFTER UPDATE) → `'delete'` старого рядка + `INSERT` нового.

Токенізатор `unicode61 remove_diacritics 2` — саме тому українські слова
знаходяться без урахування діакритики; стемера немає (це компенсує
`retrieval._lexical`, додаючи префіксні й «скорочені» основи).

### Версія 3 — конфлікти й версії

**`contradictions`**: `id`, `left_id`, `right_id`, `reason`, `resolved`
(0/1), `resolution`, `at`, `UNIQUE(left_id, right_id)`.

**`memory_versions`**: `id`, `memory_id`, `content`, `confidence`, `at`,
`reason`. Індекс `idx_versions_mem(memory_id)`.

Саме сюди пишеться попередня версія при `update()` і `forget()` — факт
лишається в історії.

### Версія 4 — і чому вона потрібна

```python
4: (
    "DROP INDEX IF EXISTS idx_mem_hash",
    "CREATE INDEX IF NOT EXISTS idx_mem_hash ON memories(content_hash)",
    "CREATE INDEX IF NOT EXISTS idx_mem_fingerprint ON memories(fingerprint, kind)",
)
```

Причина описана в коментарі буквально: «`content_hash` більше НЕ
унікальний. Унікальність забороняла консолідацію історичних дублікатів.
Коли нормалізація тексту змінюється (а вона змінювалась: кінцева
пунктуація, регістр), у спадковій базі вже лежать два рядки з тим самим
змістом — і CONSTRAINT не давав їх злити, кидаючи `UNIQUE constraint
failed`. Дублікати тепер ловить застосунок (`MemoryRepository.save`), а база
гарантує лише швидкий пошук».

Тобто v4 — це свідома передача відповідальності за дублікати з SQL на
застосунок. Тест `test_duplicates_are_merged` імітує саме спадкову базу:
вставляє два рядки з однаковим `content_hash` через прямий `UPDATE` і
перевіряє, що `consolidate()` їх зливає.

### Підсумковий `PRAGMA user_version`

`SCHEMA_VERSION = 4`. `MemoryStore.migrate()` застосовує всі кроки
`version > current` послідовно, кожен — в одній транзакції:

```python
with conn:
    for statement in MIGRATIONS[version]:
        conn.execute(statement)
    conn.execute(f"PRAGMA user_version={version}")
```

Помилка на кроці → `StoreError("Міграція до версії N не вдалась: …")`.
Повторний виклик `migrate()` ідемпотентний (перевіряє
`current >= SCHEMA_VERSION`). `PRAGMA user_version=N` усередині `with conn:`
не є частиною транзакції для самого PRAGMA, тому після збою на наступному
кроці версія лишається на останньому успішному — що й потрібно.

## 4. Транзакції та доступ

```python
@contextmanager
def transaction(self):
    conn.execute("BEGIN IMMEDIATE")     # блокування на запис одразу
    try:
        yield conn
    except Exception:
        conn.rollback(); raise
    else:
        conn.commit()
```

`BEGIN IMMEDIATE` бере write-блокування відразу — менше шансів зловити
`SQLITE_BUSY` посеред транзакції. Якщо SQLite повідомив «within a
transaction» (вкладна транзакція), виняток ковтається навмисно.
Допоміжні: `execute(sql, params)`, `query(sql, params)` → `list[Row]`,
`one(sql, params)` → `Row | None`. Усі під `self._lock` (RLock).

## 5. Бекапи через Backup API

```python
def backup(self, target) -> Path:
    self.checkpoint()                         # wal_checkpoint(TRUNCATE)
    with sqlite3.connect(str(destination)) as backup_conn:
        self._connection().backup(backup_conn)
```

Чому не `shutil.copy`: у режимі WAL свіжі дані лежать у `-wal`, і копія
вийде старішою або битою (це прямо написано і в docstring, і в коментарі
до методу).

`Neuromesh.backup(target=None)`: `target=None` → `timestamped_backup(store)`,
інакше → `store.backup(target)`; повертає `{"path": str, "size_bytes": int}`.
`timestamped_backup(store, keep=8)` пише `backups/memory-YYYYmmdd-HHMMSS.db`
і **видаляє** найстаріші, лишаючи `keep` останніх (сортування за іменем,
тобто за часом).

## 6. Відновлення

`restore(source) -> bool`:

1. Бекап мусить існувати, інакше `StoreError("Бекап не знайдено: …")`.
2. **Перевірка бекапу перед відновленням**: окреме з'єднання,
   `PRAGMA integrity_check`; не `ok` →
   `StoreError("Бекап пошкоджений — відновлення скасовано.")`.
3. Поточний файл зберігається як `<path>.before-restore` (`shutil.copy2`).
4. `shutil.copy2(origin, self.path)`.
5. Видаляються залишки `-wal` і `-shm` — інакше SQLite «доклеїв» би до
   нової бази старий журнал.
6. `close()` перед усім цим, `_open()` після — PRAGMA й міграції
   застосовуються заново.

## 7. Цілісність і обслуговування

`integrity()` повертає `{"ok": bool, "verdict": str, "problems": [...],
"path": str, "db_bytes": int, "wal_bytes": int, "shm_bytes": int,
"version": int}`. `ok` = `verdict.lower() == "ok"` з
`PRAGMA integrity_check`; розміри `-wal`/`-shm` важливі: великий WAL
означає, що давно не було checkpoint.

`checkpoint()` — `PRAGMA wal_checkpoint(TRUNCATE)`, повертає `bool`.
`vacuum()` — `VACUUM`, повертає `bool`. `free_space_gb()` —
`shutil.disk_usage(path.parent).free / 1024**3`. `close()` робить `commit()`,
`PRAGMA optimize`, `close()` і ставить `_closed = True`; будь-яка подальша
робота дає `StoreError("Сховище закрито.")`.

## 8. Приклад

```python
from blackchpok_ide.pcmm.store import MemoryStore, SCHEMA_VERSION

store = MemoryStore()                      # або MemoryStore("D:/tmp/m.db")
print(store.path)                          # ...\neuromesh\memory.db
print(store.version, SCHEMA_VERSION)       # 4 4
print(store.integrity())                   # {'ok': True, 'verdict': 'ok', ...}

print(store.one("PRAGMA journal_mode")[0]) # wal
print(store.one("PRAGMA synchronous")[0])  # 2  (FULL)
print(store.one("PRAGMA foreign_keys")[0]) # 1

target = store.backup("D:/tmp/memory-copy.db")
print(target.exists())
store.close()
```

## 9. Що не реалізовано

* Таблиця `stats` створюється, але код її не заповнює й не читає.
* Немає шифрування файлу бази (SQLCipher не використовується).
* Немає автоматичного бекапу за розписом: бекап робить користувач (панель),
  інструмент `memory_recover` або тести.
* Немає дедуплікації на рівні SQL (див. v4) — лише `MemoryRepository`.

## Підсумок

База — один файл SQLite у `%APPDATA%\BlackChpokIDE\neuromesh\memory.db` з
WAL і `synchronous=FULL`; схема проходить 4 версійовані міграції, де v4
знімає UNIQUE з `content_hash` заради можливості зливати історичні
дублікати. Пошук іде через FTS5 з external content і трьома тригерами.
Бекап робиться виключно через `sqlite3.Connection.backup()` після
`wal_checkpoint(TRUNCATE)`, відновлення перевіряє бекап на цілісність і
зберігає поточний файл як `.before-restore`, прибираючи `-wal`/`-shm`.
