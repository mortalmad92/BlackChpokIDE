# Відновлення пам'яті NEUROMESH

Практичний посібник: що робити, коли база пошкоджена, як зробити й
відновити бекап, що перевіряє `integrity_check`, чому не можна копіювати
файл під час WAL, як перебудувати FTS-індекс і вектори, як перенести дані
зі старого RAG.

Усе звірено з `blackchpok_ide/pcmm/store.py`, `service.py`,
`repository.py`, `tools.py`.

## 1. Де лежить база і що поруч

```
%APPDATA%\BlackChpokIDE\neuromesh\
    memory.db          # основна база
    memory.db-wal      # журнал WAL (може бути великим)
    memory.db-shm      # спільна пам'ять WAL
    vectors.db         # кеш векторів embeddings
    backups\           # бекапи memory-YYYYmmdd-HHMMSS.db
```

(`app_data_dir()` може бути іншою, якщо задано `BLACKCHPOK_HOME`.)
Перевірити фактичні шляхи:

```powershell
.\.venv\Scripts\python.exe -X utf8 -c "import sys;sys.path.insert(0,'.');from blackchpok_ide.pcmm.store import default_db_path, backup_dir;print(default_db_path());print(backup_dir())"
```

## 2. Що перевіряє `integrity_check`

`MemoryStore.integrity()` виконує `PRAGMA integrity_check` і повертає:

| Поле | Зміст |
| --- | --- |
| `ok` | `verdict.lower() == "ok"` |
| `verdict` | текст відповіді SQLite (`"ok"` або опис проблеми) |
| `problems` | список; при `ok` порожній, при помилці — вердикт або текст винятку |
| `path` | шлях до файлу |
| `db_bytes`, `wal_bytes`, `shm_bytes` | розміри трьох файлів |
| `version` | `PRAGMA user_version` (очікується 4) |

Важливо: `integrity_check` перевіряє **структуру** бази (сторінки, індекси,
B-дерева). Він **не** перевіряє логічну узгодженість даних — наприклад, чи
немає двох активних спогадів з однаковим `content_hash` (це нормально після
v4) або чи відповідає FTS-індекс вмісту `memories` (за це відповідають
тригери й `rebuild`).

Запуск:

```powershell
.\.venv\Scripts\python.exe -X utf8 -c "import sys,json;sys.path.insert(0,'.');from blackchpok_ide.pcmm import Neuromesh;m=Neuromesh();print(json.dumps(m.integrity(),ensure_ascii=False,indent=2));m.close()"
```

Реальний результат на здоровій базі:

```json
{"ok": true, "problems": [], "path": "C:\\Users\\Admin\\AppData\\Roaming\\BlackChpokIDE\\neuromesh\\memory.db",
 "verdict": "ok", "db_bytes": 126976, "wal_bytes": 0, "shm_bytes": 32768, "version": 4}
```

Через агента те саме робить `memory_recover` з `action: "integrity"`:
`Цілісність: гаразд (версія схеми 4)` + `База: <шлях>`.

## 3. Бекап

### Через код

```python
from blackchpok_ide.pcmm import Neuromesh

memory = Neuromesh()
print(memory.backup())          # {'path': '…\\backups\\memory-20261108-183844.db',
                                #  'size_bytes': 126976}
memory.close()
```

`Neuromesh.backup()` без аргумента → `timestamped_backup()`, яка:

1. формує `backups/memory-YYYYmmdd-HHMMSS.db`;
2. викликає `store.backup(target)` → `wal_checkpoint(TRUNCATE)` +
   `sqlite3.Connection.backup()`;
3. **видаляє** найстаріші бекапи, лишаючи `keep = 8` останніх.

Свій шлях: `memory.backup("D:/backups/my.db")` — тоді `timestamped_backup`
не викликається й ротації немає.

### Через панель

### Через агента і через панель

```
memory_recover {"action": "backup"}
→ Бекап створено: …\backups\memory-20261108-183844.db (126976 байт)
```

Панель «NEUROMESH Пам'ять» → кнопка **Бекап** → `service.backup()`;
повідомлення `Бекап: <шлях> (N байт)`. Список бекапів дає
`memory.backups()` — `[{'path', 'size_mb', 'modified'}]`.

## 4. Чому не можна копіювати файл під час WAL

У режимі WAL свіжі транзакції лежать у `memory.db-wal`, а не в
`memory.db`. `shutil.copy` основного файлу дасть **старіший** стан (без
останніх записів) або, якщо копіювання припало на момент checkpoint,
неузгоджений файл. Саме тому в коді бекап іде лише через
`sqlite3.Connection.backup()`: цей API читає базу через те саме з'єднання
й гарантує консистентний знімок. Коментар у `store.py` каже це прямо:
«Копіювати файл через `shutil.copy` не можна: у режимі WAL свіжі дані
лежать у `-wal`, і копія вийде старішою або битою».

Практичні наслідки:

* **Не** робіть `Copy-Item memory.db` як «бекап» — ви майже напевно
  втратите останні спогади.
* `checkpoint()` (`wal_checkpoint(TRUNCATE)`) переносить WAL в основний
  файл і обрізає його — але навіть після цього правильний спосіб —
  `backup()`, бо між чекпоінтом і копіюванням може пройти запис.
* Для архіву «намертво» (коли IDE закрита) копіювати **всі три** файли
  (`memory.db`, `-wal`, `-shm`) разом — але краще `backup()`.

Тест `test_backup_is_consistent_under_wal` перевіряє саме це: після 20
записів бекап відкривається окремим з'єднанням, проходить
`integrity_check` і містить ≥ 20 рядків.

## 5. Відновлення

```python
memory.restore(r"C:\Users\Admin\AppData\Roaming\BlackChpokIDE\neuromesh\backups\memory-20261108-183844.db")
# True
```

### Що робить `restore()` покроково

1. Бекап мусить існувати: інакше `StoreError("Бекап не знайдено: …")`.
2. **Перевірка перед відновленням**: окреме з'єднання, `PRAGMA
   integrity_check`; якщо не `ok` → `StoreError("Бекап пошкоджений —
   відновлення скасовано.")`.
3. Поточний `memory.db` копіюється в `memory.db.before-restore`.
4. Бекап копіюється на місце `memory.db`.
5. Видаляються `memory.db-wal` і `memory.db-shm` — інакше SQLite
   «доклеїв» би до нової бази старий журнал.
6. `_open()` заново: PRAGMA + міграції.

Через агента: `memory_recover {"action": "restore", "path": "…"}` →
`Відновлено.`; без `path` — `✗ Для відновлення вкажи шлях до бекапу.`

### Скасувати відновлення

Файл `memory.db.before-restore` лишається на місці — це «одна кнопка
назад»: якщо відновили не той бекап, закрийте IDE, видаліть
`memory.db`/`-wal`/`-shm` і перейменуйте `memory.db.before-restore` у
`memory.db`.

## 6. Що робити при пошкодженні бази

Порядок дій — від найбезпечнішого до найрадикальнішого.

### Крок 1. Діагностика

```powershell
.\.venv\Scripts\python.exe -X utf8 -c "import sys,json;sys.path.insert(0,'.');from blackchpok_ide.pcmm.store import MemoryStore;print(json.dumps(MemoryStore().integrity(),ensure_ascii=False,indent=2))"
```

Якщо процес падає ще на `MemoryStore()` з `StoreError` — база не
відкривається взагалі, переходьте до кроку 3.

### Крок 2. М'які засоби

* `checkpoint()` — перенести WAL. Часто «дивні» стани (старі дані,
  величезний `-wal`) лікуються саме цим.
* `vacuum()` — перебудувати файл, прибрати сміття. Робити на копії, не на
  оригіналі, якщо є найменший сумнів.
* `rebuild_search()` — перебудувати FTS (див. розділ 7).

Якщо `integrity_check` каже `ok`, а пошук «дивний» — це не пошкодження
бази, а розсинхронізація FTS-індексу; лікується `rebuild_search()`.

### Крок 3. Відновлення з бекапу

Найкращий шлях: `restore(<останній робочий бекап>)`. Втратите тільки те,
що з'явилось після бекапу.

### Крок 4. Рятування даних із пошкодженого файлу

Якщо бекапів немає: закрийте IDE, скопіюйте `memory.db` **разом із** `-wal`
і `-shm` в окрему теку й спробуйте `.recover` (утиліта `sqlite3` CLI) на
копії. У самій IDE інструмента для порятунку пошкодженого файлу **немає**.

### Крок 5. Нова база

Перейменуйте `neuromesh/` у `neuromesh.broken-<дата>/`, запустіть IDE —
`MemoryStore._open()` створить нову базу й застосує міграції 1→4. Далі за
потреби — `migrate_legacy_rag()`.

## 7. Перебудова FTS-індексу і векторів

### FTS

```python
memory.rebuild_search()      # True / False
```

Усередині — одна транзакція:
`INSERT INTO memory_fts(memory_fts) VALUES('rebuild')`. Це штатна команда
FTS5 для external-content таблиці: вона перечитує `memories` і будує індекс
заново. Викликати, коли пошук перестав знаходити очевидні речі, коли дані
вставлялися в обхід тригерів (імпорт, ручна правка, `UPDATE` безпосередньо
в SQL) або після масового видалення/оновлення. Повертає `False` (і пише
попередження в журнал), якщо SQLite відмовив — наприклад, коли таблиця
`memory_fts` фізично відсутня (тоді потрібна міграція; перевірте
`store.version`).

### Вектори

```python
memory.reindex_vectors(limit=5000)
# {'ok': True, 'updated': N, 'checked': M}
```

Бере `SELECT id, content FROM memories WHERE embedding = '' LIMIT ?` і
рахує вектори через `self.embedder.encode_one()`. Важливо:

* без embedding-сервісу повертає
  `{'ok': False, 'reason': 'немає embedding-сервісу', 'updated': 0}`;
* для роботи потрібна **завантажена модель** — інакше `EmbeddingService`
  кидає `EmbeddingUnavailable`, а `reindex_vectors` ловить виняток у
  `LOG.debug` і пропускає запис;
* кеш векторів лежить окремо, у `vectors.db`, і прив'язаний до підпису
  моделі `"<ім'я файлу>:<розмір>:<mtime>"`, тому після підміни файлу моделі
  старі вектори просто не використовуються.

Перерахувати вектори для вже наявних спогадів `reindex_vectors()` **не**
може: він бере лише ті, у кого `embedding = ''`. Потрібен явний
`UPDATE memories SET embedding = '', embed_model = ''` — у коді IDE такої
операції немає.

## 8. Перенесення зі старого RAG

```python
memory.migrate_legacy_rag(limit=500)
# {'imported': 25, 'skipped': 6, 'sources': ['index.sqlite3:rag_memory',
#                                            'memoria_infinita.db:fatti_permanenti']}
```

Шукає `<перша доступна тека даних>/.mcp_rag` і `<робоча тека>/.mcp_rag`,
у них — `index.sqlite3` і `memoria_infinita.db`. Читає через
`sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)` — **лише
читання**, стара база не змінюється («Стара таблиця лишається на місці»).

| Таблиця | Поля | `kind` |
| --- | --- | --- |
| `rag_memory` | `kind`, `content` | `"fact"`, якщо `kind` не входить у `KINDS`, інакше `"preference"` |
| `fatti_permanenti` | `fatto` | `"preference"` |

`source` = `rag:<ім'я файлу>`, `provenance` = `<файл>:<таблиця>`,
`confidence` = 0.55 (`rag_memory`) / 0.6 (`fatti_permanenti`),
`with_vector=False`. Повторний запуск безпечний: дублікати ловляться як
`duplicate` і йдуть у `skipped`. Через агента —
`memory_recover {"action": "migrate_legacy"}`; через панель — кнопка
**Зі старого RAG**.

## 9. Консолідація як «лікування» даних

Якщо база ціла, але містить дублікати (типова ситуація після зміни
нормалізації тексту або після міграції):

```python
memory.consolidate(dry_run=True)    # спершу подивитись, що буде
memory.consolidate()                # потім застосувати
```

Нічого не видаляється: дублікати зливаються в найстаріший запис, решта
отримує `superseded_by`, попередні версії — у `memory_versions`.
`dry_run=True` рахує, але не змінює нічого.

## 10. Чого в коді немає

* Автоматичного бекапу за розписом (cron/таймер) — бекап робить
  користувач або агент.
* Перевірки вільного місця перед бекапом: `free_space_gb()` існує, але
  `backup()` його не викликає.
* Відновлення окремих спогадів із бекапу — `restore()` замінює базу
  цілком.
* Інструмента порятунку пошкодженого файлу (`.recover`) — це робиться
  зовнішнім `sqlite3`.
* Автоматичного перерахунку векторів після зміни моделі — лише
  `reindex_vectors()` для тих, у кого `embedding = ''`.

## Підсумок

База лежить у `%APPDATA%\BlackChpokIDE\neuromesh\`; цілісність
перевіряється `PRAGMA integrity_check` (структура, не логіка) разом із
розмірами `-wal`/`-shm`. Бекап — тільки через SQLite Backup API після
`wal_checkpoint(TRUNCATE)`, бо копіювання файлу під час WAL дає битий або
застарілий знімок. Відновлення перевіряє бекап на цілісність, зберігає
поточну базу як `.before-restore` і прибирає `-wal`/`-shm` перед
повторним відкриттям. FTS перебудовується командою `'rebuild'`, вектори —
`reindex_vectors()` (лише для порожніх), а старі RAG-дані переносяться
`migrate_legacy_rag()` у режимі read-only, не ламаючи стару базу.
