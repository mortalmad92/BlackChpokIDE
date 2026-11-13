# NEUROMESH — план інтеграції пам'яті

Документ описує, **як пам'ять влаштована й підключена** до IDE. Усе перевірено
читанням `blackchpok_ide/pcmm/*.py` та викликів у `main_window.py`,
`agent_tools.py`, `agent.py`.

---

## 1. Призначення й межа

`pcmm` (Predictive Causal Memory Mesh) — довготривала пам'ять, яка зберігає
твердження **з походженням** і не втрачає підтверджені факти: застаріле
позначається, а не видаляється.

Що вона робить:

* зберігає 10 типів спогадів: `fact`, `decision`, `error`, `fix`, `task`,
  `dependency`, `tool`, `constraint`, `change`, `preference` (`models.KINDS`);
* шукає гібридно: лексеми (BM25 через FTS5) + вектори (косинус) + граф +
  часова свіжість;
* прогнозує, який контекст знадобиться далі, і **вимірює** точність прогнозу;
* збирає контекст під реальний бюджет токенів моделі;
* робить бекапи через SQLite Backup API.

Чого вона **не** робить: не замінює файловий RAG (`rag.py` / `rag_engine.py`)
для пошуку по коду проєкту — це окремі підсистеми, і стара лишається на місці.

---

## 2. Схема бази

Файл: `<app_data>/neuromesh/memory.db` (`store.default_db_path()` через
`config.app_data_dir()`). На цій машині:
`userdata/neuromesh/`, вектори — окремо в `vectors.db`.

### 2.1. `memories` — основний рядок спогаду

| Поле | Тип | Призначення |
|---|---|---|
| `id` | TEXT PK | `m-<16 hex>` (`Memory.__post_init__`) |
| `kind` | TEXT | один із 10 типів; невідомий приводиться до `fact` |
| `content` | TEXT | сам текст твердження |
| `summary` | TEXT | перший рядок/обрізане до 160 символів (`make_summary`) |
| `source` | TEXT | звідки взято (`rag:index.sqlite3`, `benchmark`, …) |
| `provenance` | TEXT | точніше: `файл:рядок`, `ім'я_таблиці` |
| `confidence` | REAL | 0..1, окремо від «важливості» |
| `created_at` / `updated_at` / `accessed_at` | REAL | час |
| `hits` | INTEGER | скільки разів використано/підтверджено |
| `task` | TEXT | до якого завдання належить |
| `files` | TEXT | JSON-масив шляхів |
| `tags` | TEXT | JSON-масив тегів |
| `valid_from` / `valid_to` | REAL | коли факт діяв |
| `superseded_by` | TEXT | чим замінено (**не видалення**) |
| `fingerprint` | TEXT | хеш відсортованих лексем + `kind` |
| `content_hash` | TEXT | точний хеш нормалізованого тексту |
| `embedding` | TEXT | JSON-вектор |
| `embed_model` | TEXT | підпис моделі (`ім'я:розмір:mtime`) |
| `checksum` | TEXT | зарезервовано (пишеться порожнім) |

Індекси: `idx_mem_kind`, `idx_mem_created`, `idx_mem_task`, `idx_mem_hash`
(після v4 — **неунікальний**), `idx_mem_fingerprint(fingerprint, kind)`.

### 2.2. Решта таблиць

| Таблиця | Призначення | Ключові поля |
|---|---|---|
| `memory_links` | напрямлений граф зв'язків | `src`, `dst`, `relation` (`caused`, `fixed_by`, `depends_on`, `contradicts`, `supersedes`, `related`, `part_of`), `weight`, `UNIQUE(src,dst,relation)` |
| `memory_events` | журнал дій | `memory_id`, `action` (`remember`/`confirm`/`update`/`supersede`/`link`), `detail`, `actor`, `at` |
| `task_history` | кроки завдань (для прогнозу переходів) | `task`, `action`, `status`, `detail`, `files` (JSON), `tools` (JSON), `at` |
| `predictions` | прогнози й вимір їх точності | `context`, `predicted`, `actual`, `score` (precision), `hit`, `at` |
| `feedback` | оцінка корисності | `memory_id`, `useful`, `note`, `at` |
| `stats` | лічильники (зарезервовано) | `key`, `value`, `updated_at` |
| `memory_fts` | FTS5-індекс, `content='memories'`, `tokenize='unicode61 remove_diacritics 2'` | `content`, `summary`, `tags` |
| `contradictions` | кандидати в конфлікт | `left_id`, `right_id`, `reason`, `resolved`, `resolution`, `UNIQUE(left_id,right_id)` |
| `memory_versions` | історія змін тексту | `memory_id`, `content`, `confidence`, `at`, `reason` |

Тригери `memory_fts_ai` / `_ad` / `_au` синхронізують FTS із `memories`
автоматично. FTS — **похідний** індекс: `Neuromesh.rebuild_search()` уміє
перебудувати його з основної таблиці, тож він не є єдиним джерелом істини.

Прагми (`store._configure`): `journal_mode=WAL`, `foreign_keys=ON`,
`busy_timeout=8000`, `synchronous=FULL` (для критичних записів),
`temp_store=MEMORY`, `cache_size=-16000`, `wal_autocheckpoint=500`.

---

## 3. Міграції v1 → v4

Механізм: `PRAGMA user_version` + словник `MIGRATIONS`, кожен крок — окрема
транзакція. `SCHEMA_VERSION = 4`. Міграція ідемпотентна: `migrate()` пропускає
кроки, які вже застосовані.

| Версія | Що додано | Навіщо |
|---|---|---|
| **v1** | `memories`, `memory_links`, `memory_events`, `task_history`, `predictions`, `feedback`, `stats` + індекси, зокрема `CREATE UNIQUE INDEX idx_mem_hash ON memories(content_hash)` | базовий скелет |
| **v2** | `memory_fts` (FTS5) + тригери `ai`/`ad`/`au` | лексемний пошук без зовнішніх сервісів |
| **v3** | `contradictions`, `memory_versions` + `idx_versions_mem` | конфлікти й історія версій без втрати попередніх текстів |
| **v4** | `DROP INDEX idx_mem_hash` → `CREATE INDEX idx_mem_hash` (**неунікальний**) + `idx_mem_fingerprint(fingerprint, kind)` | див. нижче |

### 3.1. Чому саме v4

Унікальний індекс по `content_hash` **блокував консолідацію історичних
дублікатів**.

Механізм виникнення проблеми:

1. `models.content_hash()` нормалізує текст (нижній регістр, зрізання кінцевої
   пунктуації), і ця нормалізація **змінювалась** у процесі розробки.
2. У спадковій базі вже лежать два рядки, які за **старою** нормалізацією мали
   різні хеші, а за новою — однакові.
3. `MemoryRepository.consolidate()` знаходить таку пару й намагається злити їх:
   `update(twin.id, content=merged, …)` + `supersede(memory.id, twin.id)`.
4. `update()` перераховує `content_hash` для канонічного рядка. Якщо новий хеш
   збігається з хешем рядка, який ще не встигли позначити застарілим, —
   `UNIQUE constraint failed`, і **вся транзакція відкочується**. Консолідація
   стає неможливою саме там, де вона найпотрібніша.

Коментар у коді фіксує це прямо (`store.py:196–208`): «унікальність забороняла
консолідацію історичних дублікатів… CONSTRAINT не давав їх злити, кидаючи
`UNIQUE constraint failed`».

Після v4:

* **база** гарантує лише швидкий пошук за `content_hash` (індекс лишається);
* **дублікати ловить застосунок** — `MemoryRepository._find_duplicate()`:
  спершу точний збіг `content_hash`, далі `fingerprint + kind` (перефразування
  з тим самим набором лексем);
* доданий `idx_mem_fingerprint(fingerprint, kind)` робить другий запит дешевим.

**Наслідок, який треба знати:** у `save()` лишився застарілий коментар
«Унікальність гарантує схема: навіть якщо перевірку дублікатів вимкнено явно,
той самий зміст не ляже двома рядками» (`repository.py:110–116`). Після v4 це
**вже не так**: якщо викликати `save(check_duplicates=False)`, два однакові
рядки ляжуть. Обробник `except sqlite3.IntegrityError` лишився як страховка для
баз, які ще не мігровано, і нічого не ламає, але коментар треба виправити.

---

## 4. Як пам'ять підключається

### 4.1. Ланцюг підключення

```
main_window.__init__
  │
  ├─ self.native_runtime = native_api.NativeRuntime()
  ├─ self.memory = self._open_memory()
  │      └─ Neuromesh()                    ← pcmm/service.py
  │      └─ service.attach_engine(self.native_runtime.engine)
  │             ├─ EmbeddingService(engine, db_path=…/vectors.db)
  │             └─ retriever.embedder = embedder
  │
  └─ self.registry.attach_memory(self.memory)     ← agent_tools.py:329
         ├─ self.memory_tools = MemoryTools(service)
         ├─ для кожного з 12 імен: _handlers[name] = _memory_handler_for(...)
         └─ self._memory_schemas = memory_tool_schemas()
```

Далі `agent.Agent.tool_schemas()`:

```python
schemas = list(TOOL_SCHEMAS)
schemas.extend(self.registry_memory_schemas())      # 12 memory_*
schemas.extend(skills_module.tool_schemas())
…
```

`registry_memory_schemas()` бере хвіст `registry.tool_schemas()` після
`len(TOOL_SCHEMAS)` — тобто рівно схеми пам'яті, і **порожній список**, якщо
пам'ять не підключена (`memory_ready()` → `False`).

### 4.2. Три рівні безпеки підключення

1. **Відсутність пам'яті не ламає IDE.** `_open_memory()` обгорнутий у
   `try/except`, повертає `None`, пише причину в рядок стану.
2. **Відсутність інструментів не бреше моделі.** Без `attach_memory` схем
   `memory_*` просто немає — модель не може «викликати» те, чого немає.
3. **Аргументи перевіряються.** `_memory_handler_for` загортає виклик у
   `MemoryTools.call()`, який проганяє `validate_arguments(schema, payload)`;
   без цього `memory_search(limit=999)` тихо проходив би повз схему.

### 4.3. Повторне підключення рушія

Коли модель завантажується, `main_window._on_native_model()` викликає
`self.memory.attach_engine(self.native_runtime.engine)` **ще раз** — щоб
`EmbeddingService` і `BudgetGovernor` підхопили новий завантажений рушій. Це
важливо, бо до завантаження моделі `self.embedder` дорівнює `None` і семантика
вимкнена.

### 4.4. 12 інструментів агента (`pcmm/tools.py`)

`memory_search`, `memory_recall`, `memory_store`, `memory_link`, `memory_update`,
`memory_verify`, `memory_explain`, `memory_predict`, `memory_project_context`,
`memory_task_history`, `memory_recover`, `memory_feedback`.

Кожен повертає **текст** (контракт `ToolResult`), а структуровані дані
лишаються в сервісі. Невдача позначається `✗ …`, що наявний реєстр трактує як
провал — успіх не вигадується.

### 4.5. Пам'ять як частина РОЗУМІННЯ, а не лише інструмент

Розділи 4.1–4.4 описують пам'ять «за викликом»: модель мала сама
здогадатись покликати `memory_search`. Через це агент перепитував те, що
людина вже пояснювала, і повторював виправлені помилки — саме на це
скаржився користувач («чат знову забув попереднє»).

Тепер пам'ять підключається до самого розуміння запиту через
`memory_bridge.MemoryBridge` (`blackchpok_ide/memory_bridge.py`):

```
AgentRunner.start()
  ├─ _prepare_understanding(text)      ← IntentFrame
  ├─ _recall_memory(text)              ← MemoryBridge.snapshot()
  │      ├─ project_context(query, window=…)   бюджет вікна моделі
  │      ├─ constraints()                      критичні обмеження проєкту
  │      └─ apply_to_state(snapshot, state)    → ConversationState.constraints
  ├─ _build_plan()                     ← planning.build_plan(intent, state)
  └─ _context_block()                  ← мета + стан + ПАМ'ЯТЬ + план + профіль
```

Після ходу `_remember_outcome()` пише назад **лише те, що підтверджено**:

| Що | Умова запису | Тип спогаду |
|---|---|---|
| «Змінено: calc.py» | `write_file`/`edit_file` повернув успіх | `change` |
| «Збій інструмента: …» | інструмент повернув помилку | `error` |
| Хід у історії задач | завжди, коли були виклики | `memory_task_history` |

Обмеження, які зроблені навмисно:

1. **нічого не пишеться**, якщо користувач сказав «не зберігай»
   (`ConversationState.private`);
2. **висновки агента мають впевненість 0.6**, а не 1.0: людина має змогу
   їх виправити;
3. **помилка пам'яті не ламає хід** — `MemoryBridge` ловить винятки й
   повертає порожній знімок;
4. **обмеження з пам'яті не дублюються** у стані (`apply_to_state`).

Перевіряється це без бази: підроблений сервіс із тим самим інтерфейсом
(`tests/test_planning_and_memory.py`, клас `FakeMemory`) і наскрізний
прогін `tests/test_new_layers_live.py`.

---

## 5. Реальні виміри

Джерело: `.buildtmp/bench_report.json`, `MemoryBenchmark` із `bench.py`.
Набір — власний, **6 запитів** (`bench.CASES`): «де виконуються команди», «як
читається файл», «який контекст у моделі», «що було з помилкою theme», «як
виправлено імпорт», «навіщо KV-кеш». `k = 3`, `window = 4096`.

| Метрика | Значення |
|---|---|
| **Recall@3** | **1.0** |
| **Precision@3** | **0.833** |
| **MRR** | **1.0** |
| Точність прогнозу (`prediction_accuracy`) | 0.4 на 6 вимірах |
| Економія токенів (`token_savings_share`) | 0.0 |
| Спогадів / активних / зв'язків / конфліктів | 6 / 6 / 0 / 0 |
| З векторами | 0 |

Усі 6 запитів дали `rank = 1`. Політика пошуку в звіті — «немає векторів — лише
лексемний пошук», тобто **семантика була вимкнена**, і результат тримається на
BM25 + граф + час.

### 5.1. Що ці числа насправді означають

Чесні застереження, які треба читати разом із цифрами:

1. **Набір крихітний і «дружній».** 6 запитів, 6 спогадів, запити складені з тих
   самих слів, що й спогади. Recall@3 = 1.0 на такому наборі — це перевірка
   працездатності, а не доказ якості пошуку.
2. **Precision@3 = 0.833 — не класична Precision@K.** Формула в
   `bench.py:318`: `precision = 1 / len(hits)`. Для запиту з 2 знайденими це 0.5,
   для 1 — 1.0. Середнє `(1+1+1+0.5+0.5+1)/6 = 0.833`. Частка релевантних серед
   перших K **не** рахується, бо для цього потрібна розмітка релевантності всіх
   результатів, а її в наборі немає.
3. **MRR = 1.0** означає лише «правильний спогад завжди перший» на цих 6 запитах.
4. **Економія токенів = 0.0** — при `window=4096` і шести коротких спогадах
   губернатор нічого не викинув, тому економити не було чого. Метрика
   рахується, але показує нуль; це не помилка, а межа набору.
5. **Точність прогнозу 0.4** — низька, і це очікувано: сигналів мало, історія
   завдань майже порожня. Число показано в панелі як є.

---

## 6. Що перенесено зі старого RAG і що ні

### 6.1. Перенесено (`Neuromesh.migrate_legacy_rag`)

Джерела: `<data>/.mcp_rag/index.sqlite3`, `<data>/.mcp_rag/memoria_infinita.db`
(а також `Path.cwd()/.mcp_rag`). Відкриваються **тільки для читання**
(`file:…?mode=ro`).

| Стара таблиця | Куди | Тип | Впевненість | Provenance |
|---|---|---|---|---|
| `rag_memory(kind, content)` | `memories` | `fact` (або `preference`, якщо `kind` не з KINDS) | 0.55 | `<db>:rag_memory` |
| `fatti_permanenti(fatto)` | `memories` | `preference` | 0.60 | `<db>:fatti_permanenti` |

Повертає `{"imported": N, "skipped": M, "sources": [...]}`; `skipped` — це
дублікати, які вже є в пам'яті. Вектори під час переносу **не рахуються**
(`with_vector=False`) — щоб міграція не залежала від завантаженої моделі; їх
додає окремо `reindex_vectors()`.

**Стара база не змінюється й не видаляється** — це навмисно: користувач може
порівнювати обидві системи.

### 6.2. Не перенесено

* **`rag_documents` / `rag_chunks` / `rag_fts`** — файловий індекс коду. Він
  лишається в `rag_engine.LocalRAG` і далі доступний через `rag.py:RagService`
  та панель RAG. Дублювати його в пам'ять немає сенсу: це різні речі — «що
  лежить у файлах» проти «що ми про проєкт знаємо».
* **Вектори старого RAG** — інша модель означає інший простір; змішувати
  заборонено, тому `EmbeddingService` тримає підпис моделі й не змішує
  розмірності (`_load_cached` пропускає рядки з іншим `dim`).
* **Зв'язки старого RAG** (якщо були) — переносяться лише тексти; граф
  будується заново через `add_link` / `consolidate`.

---

## 7. Життєвий цикл спогаду (як поводяться дані)

| Подія | Що відбувається | Де |
|---|---|---|
| Новий текст | `save()` → `_find_duplicate()` → якщо є збіг, `_confirm()` підвищує `confidence` (+0.10 з іншого джерела, +0.05 з того самого) | `repository.py:80–167` |
| Той самий текст із тим самим джерелом | `hits += 1`, `confidence` росте до 1.0 | `_confirm` |
| Оновлення | попередній текст пише в `memory_versions`, потім `UPDATE memories` | `update()` |
| Заміна факту | `superseded_by` + `valid_to`, зв'язок `supersedes`; **рядок лишається** | `supersede()` |
| Видалення | лише з `confirm=True`; перед `DELETE` текст пише в `memory_versions` з причиною «видалено користувачем» | `forget()` |
| Корисний/некорисний | `feedback` → `+0.08` / `-0.12` до `confidence` (мінімум 0.05) | `feedback()` |
| Консолідація | дублікати зливаються в **найстаріший** запис (він канонічний), решта `supersede`; суперечності пишуться в `contradictions` | `consolidate()` |
| Бекап | `checkpoint()` + `Connection.backup()`; ротація 8 файлів | `store.backup`, `timestamped_backup` |

---

## Підсумок

Пам'ять — це SQLite-база з 10 таблицями, FTS5-індексом і 4 версіями схеми.
Міграція **v4** прибрала унікальність `content_hash`, бо саме вона робила
консолідацію історичних дублікатів неможливою (`UNIQUE constraint failed` під час
злиття); тепер дублікати ловить застосунок за `content_hash` і `fingerprint`, а
база лише прискорює пошук.

Підключення — три рядки в `main_window`: створити `Neuromesh`, віддати йому
рушій, зареєструвати в `ToolRegistry`; далі 12 інструментів `memory_*`
потрапляють у `Agent.tool_schemas()`. Відсутність пам'яті або моделі не ламає
IDE й не маскується під успіх.

Виміри на власному наборі з 6 запитів: **Recall@3 = 1.0, Precision@3 = 0.833,
MRR = 1.0** — при вимкненій семантиці (векторів у базі не було). Це перевірка
працездатності, а не доказ якості: набір крихітний, а `Precision@3` рахується за
формулою `1/len(hits)`, а не як частка релевантних серед перших K.

## Актуальний статус на момент завершення робіт

Частину дефектів, описаних вище, **уже виправлено** після написання цього
документа. Щоб не читати реалізоване як зламане:

| Дефект | Стан | Де виправлено | Тест |
| --- | --- | --- | --- |
| Агент рахував токени по символах (`кирилиця/1.6`, `len/3.5`) | **виправлено**: точний `Tokenizer.count` через `llama_tokenize` | `agent.py` (`set_token_counter`), `context_stats.py` (`set_token_counter`), `main_window.py` (`_wire_exact_tokens`) | заміряно: 39 токенів замість 20 на українському реченні |
| Параметр `timeout` у `NativeRuntime.generate` ігнорувався (`del timeout`) | **виправлено**: тайм-аут перетворюється на `should_stop` і реально спиняє декодування | `native/api.py` | `test_timeout_actually_stops_generation` |
| Граматики GBNF не діяли (`_vocab = 0` на момент побудови) | **виправлено**: словник передається в конструктор; доданий захист від C++-винятку рушія на «літеральних» графах | `native/sampling.py`, `native/engine.py` | `test_grammar_restricts_output`, `test_broken_grammar_falls_back_without_crash` |
| `_record()` писав у журнал ЛИШЕ помилки | **виправлено**: успішні запити теж потрапляють в історію | `native/api.py` | `get_runtime_status()["requests"]` |
| Політика простою не бачила власний рушій | **виправлено**: `ModelKeeper` отримав `native_provider` і `native_start_provider` | `power.py`, `main_window.py` | вивантаження/пробудження вбудованого рушія |
| `engine.native_gpu_layers`, `native_cache_type`, `native_flash_attn` зберігались, але не читались | **виправлено**: автозапуск передає їх у `load_model` | `main_window.py::_autostart_native_model` | замір: 30.5 ток/с замість 26 |
| `gpu_layers = layer_count` лишав `lm_head` на CPU | **виправлено**: повний offload = `-1` | `native/inspect.py`, `native/engine.py` | `test_full_offload_means_all_layers` |
| Міст створював ДРУГИЙ екземпляр рушія (дві копії моделі у VRAM) | **виправлено**: `bridge.set_runtime(self.native_runtime)` у вікні | `main_window.py` | перевірено: `bridge.runtime() is win.native_runtime` |
| Вбудований рушій показувався як «хмара» | **виправлено**: схема `native://` перевіряється окремо | `main_window.py::_model_summary` | видно у підписі моделі |
| `config.LLMSettings.normalise` дописував `/v1` до `native://…` | **виправлено**: схема `native://` не нормалізується | `config.py` | перевірено roundtrip налаштувань |
| Різні факти вважались дублікатом («Запис 1» = «Запис 2») | **виправлено**: лексеми беруть цифри й односимвольні токени, кінцева пунктуація зрізається | `pcmm/models.py` | `test_different_numbers_are_different_facts` |
| Унікальний `content_hash` блокував консолідацію історичних дублікатів | **виправлено** міграцією v4: індекс неунікальний | `pcmm/store.py` | `test_duplicates_are_merged` |
| Критичні обмеження витіснялись із контексту | **виправлено**: обмеження додаються окремим шаром | `pcmm/service.py::project_context` | `test_critical_constraints_survive_small_budget` |
| `Precision@K` не була класичною precision | **не виправлено** (свідомо): формула `1/len(hits)` лишається, але описана в документації бенчмарку як «міра зайвих результатів» | `bench.py` | — |

### Що досі НЕ зроблено (чесно)

* Порівняння з Ollama та LM Studio не проводилось — інструментів немає в
  цьому середовищі; методика описана в `docs/NEUROMESH_BENCHMARKS.md`.
* safetensors не підтримується рушієм (тільки GGUF).
* `mmproj` (зір) у власному рушії не реалізовано — працює лише через
  сумісний `llama-server`.
* LoCoMo та LongMemEval не запускались: власний набір — 6 запитів.
* Vulkan і DirectML відсутні в цій збірці llama.cpp.
