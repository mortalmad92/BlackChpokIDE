# API пам'яті NEUROMESH

Два рівні доступу: Python-клас `blackchpok_ide.pcmm.service.Neuromesh` і 12
інструментів агента `memory_*` (`pcmm/tools.py`) поверх того самого сервісу.
Приклади нижче — **реальний вивід цього коду** (запускалося на тимчасовій
базі через `MemoryTools.call()`).

## 1. Python-API

```python
from blackchpok_ide.pcmm import Neuromesh

memory = Neuromesh()                        # app_data_dir()/neuromesh/memory.db
memory = Neuromesh("D:/tmp/memory.db")      # явний шлях
memory.attach_engine(native_runtime.engine) # вектори й точні токени
memory.close()
```

### Запис

`remember(content, *, kind="fact", source="", provenance="", confidence=0.6,
task="", files=None, tags=None, with_vector=True) -> dict` — повертає
`{"memory": {...}, "created": bool, "duplicate": bool, "conflicts": [...]}`.
Повтор повертає `created=False, duplicate=True` і підвищує впевненість.

```python
memory.remember("run_command виконує shell=True у робочій теці.",
                kind="constraint", source="agent_tools.py:488", confidence=0.9)
# {'memory': {'id': 'm-3ebdc410106547c3', 'kind': 'constraint', …},
#  'created': True, 'duplicate': False, 'conflicts': []}
```
### Читання

| Метод | Повертає |
| --- | --- |
| `search(query, *, limit=12, kinds=None, task="", files=None)` | `query`, `policy`, `weights`, `hits`, `count` |
| `recall(memory_id)` | `memory`, `links` (`out`/`in`), `neighbours`, `versions` |
| `explain(memory_id)` | `memory`, `why_confidence`, `provenance`, `history`, `versions`, `links` |
| `predict(*, current_files=(), task="", query="", limit=8)` | `memories`, `files`, `reason`, `confidence` |
| `project_context(*, query, window, task="", files=(), kinds=None)` | `ContextBundle` → `text`, `budget`, `hits`, `prediction`, `tokens_saved`, `note` |
| `status()` | `ok`, `db`, `version`, `recent`, `counts`, `kinds`, `search`, `prediction`, `vectors`, `tokens`, `kinds_available`, `last_context`, `events`, `uptime_s` |
| `task_history(*, task="", limit=30)` | список кроків |
| `contradictions(*, unresolved_only=True)` | список конфліктів |

Елемент `hits` — `Hit.to_dict()`: `memory`, `score`, `channels`,
`explanation`. Реальний приклад:

```python
memory.search("shell", limit=3)
# {'policy': 'lexical (немає векторів — лише лексемний пошук)',
#  'weights': {'lexical': 0.74, 'semantic': 0.06, 'graph': 0.0,
#              'temporal': 0.0, 'confidence': 0.1},
#  'hits': [{'score': 0.15,
#            'channels': {'lexical': 0.0, 'temporal': 0.0,
#                         'confidence': 0.9, 'kind': 1.2},
#            'explanation': '…: впевненість 0.90; тип constraint'}],
#  'count': 1}
```

Довший описовий запит перемикає ваги:
`search("як саме виконуються команди в терміналі проєкту")["weights"]` →
`{'lexical': 0.68, 'semantic': 0.0, 'graph': 0.12, 'temporal': 0.1,
'confidence': 0.1}`, політика `lexical+graph+temporal`.

### Обслуговування

| Метод | Результат |
| --- | --- |
| `consolidate(*, dry_run=False)` | `{'merged': [...], 'superseded': [...], 'contradictions': int, 'dry_run': bool}` |
| `backup(target=None)` | `{'path': str, 'size_bytes': int}` |
| `restore(source)` | `bool` (перевіряє бекап на цілісність) |
| `backups()` | `[{'path', 'size_mb', 'modified'}]` |
| `integrity()` | `{'ok', 'verdict', 'problems', 'path', 'db_bytes', 'wal_bytes', 'shm_bytes', 'version'}` |
| `reindex_vectors(*, limit=5000)` | `{'ok', 'updated', 'checked'}` |
| `rebuild_search()` | `bool` |
| `migrate_legacy_rag(*, limit=500)` | `{'imported', 'skipped', 'sources'}` |

`migrate_legacy_rag` читає `<data_dir>/.mcp_rag` і `cwd/.mcp_rag`
(`index.sqlite3`, `memoria_infinita.db`) у режимі `mode=ro`, тому стара база
не змінюється. Реальний результат:
`{'imported': 25, 'skipped': 6, 'sources': ['index.sqlite3:rag_memory',
'memoria_infinita.db:fatti_permanenti']}`.

### Інші методи

`remember_many(items)`, `link(src, dst, relation="related", weight=0.6)`,
`update(memory_id, content="", confidence=None, reason="")`,
`verify(memory_id, confidence=None, note="")` (+0.15),
`forget(memory_id, confirm=False)`, `feedback(memory_id, *, useful, note="")`
(+0.08 / −0.12), `record_task(…)`, `resolve(contradiction_id, *, keep,
resolution="")`, `last_context()`, `record_prediction_outcome(*, used_ids)`,
`attach_embedder(embedder)`, `governor()`.

## 2. Інструменти `memory_*` (12)

```
memory_search, memory_recall, memory_store, memory_link, memory_update,
memory_verify, memory_explain, memory_predict, memory_project_context,
memory_task_history, memory_recover, memory_feedback
```

Схеми — `MEMORY_TOOL_SCHEMAS` (формат OpenAI), валідація —
`validate_arguments()` (`type`, `required`, `enum`, `minimum`/`maximum`,
`items`, вкладені `properties`).

```python
from blackchpok_ide.pcmm.tools import MemoryTools
tools = MemoryTools(memory)
tools.call("memory_search", {"query": "shell", "limit": 3})   # dict або JSON
```

Повертається **текст**. Текст, що починається з `✗`, — невдача (так його
трактує `ToolRegistry`). `TypeError` → `✗ Аргументи не підходять: …`,
інший виняток → `✗ <Тип>: <текст>`.

### memory_search

Параметри: `query` (обов'язковий), `limit` 1–25, `kind` з `KINDS`, `task`.

```
Знайдено 1 (політика: lexical (немає векторів — лише лексемний пошук)):
• [m-3ebdc410106547c3] constraint (впевненість 0.9): run_command виконує shell=True у робочій теці.
  чому: lexical (немає векторів — лише лексемний пошук): впевненість 0.90; тип constraint
```

Нічого: `Пам'ять: нічого не знайдено за запитом «…».`
Помилка схеми: `✗ Неправильні аргументи: limit: максимум 25`

### memory_recall

`{"memory_id": "…"}` →

```
[m-3ebdc410106547c3] constraint · впевненість 0.9
Джерело: agent_tools.py:488
run_command виконує shell=True у робочій теці.
```

Далі (якщо є) — `→ relation → id (weight)`, `← relation ← id (weight)`,
`Сусіди в графі: N`, `Версій в історії: N`. Не знайдено:
`✗ Спогад <id> не знайдено.`

### memory_store

`content` (обов'язковий), `kind`, `source`, `confidence` (типова **0.7** у
обробнику, у схемі 0–1), `files`, `task`, `tags`. `source` дублюється в
`provenance`.

```
Запам'ятав [m-3ebdc410106547c3] constraint: run_command виконує shell=True у робочій теці.
```

Повтор:
`Уже знаю це (спогад m-…, впевненість 1.00). Підтверджено ще раз.`
Якщо є схожі за темою факти, додається
`⚠ Можливий конфлікт із: <id>. Перевір memory_explain перед зміною рішення.`

### memory_link

`src`, `dst` (обов'язкові), `relation` ∈ `caused`, `fixed_by`, `depends_on`,
`contradicts`, `supersedes`, `related`, `part_of`, `weight` 0–1.

```
Зв'язав m-3ebdc410106547c3 —[fixed_by]→ m-3f4cc21b58ab4768.
```

Невдача (порожні id, `src == dst`, помилка БД):
`✗ Не вдалось зв'язати <src> → <dst>.`

### memory_update

`memory_id` (обов'язковий), `content`, `confidence`, `reason`.

```
Оновив [m-3f4cc21b58ab4768]: Виправлення: shell=False у run_command.
Попередня версія збережена в історії.
```

### memory_verify

`memory_id` (обов'язковий), `confidence`, `note`.
Без явної `confidence` береться `min(1.0, conf + 0.15)`.

```
Підтвердив [m-3f4cc21b58ab4768], впевненість стала 0.75.
```

### memory_explain

```
[m-3ebdc410106547c3] constraint: run_command виконує shell=True у робочій теці.
Походження: agent_tools.py:488
Впевненість: початкова 0.90; підтверджень 2; тип constraint (вага 1.3)
  · remember: run_command виконує shell=True у робочій теці.
  ↺ версія: … (причина)
```

### memory_predict

`files`, `task`, `query` (усі необов'язкові).

```
Прогноз (впевненість 0.4): відкриті файли
Спогадів для прогнозу поки немає.
```

Коли є що показати — додаються `Файли, які ймовірно знадобляться:` і
`Спогади, які варто підняти:`.

### memory_project_context

`query` (обов'язковий), `window` 256–2 000 000 (типове значення в обробнику
**8192**), `task`, `files`.

```
Контекст із пам'яті: 22/522 токенів (-оцінка), зекономлено 0.
Токени оцінені приблизно: модель не завантажена.

[constraint] (agent_tools.py:488) run_command виконує shell=True у робочій теці.
  + [constraint:6547c3] 22 ток · …, впевненість 0.90; тип constraint
```

`-оцінка` = `report.exact == False` (модель не завантажена).

### memory_task_history

`task` (порожньо = усі), `limit` 1–200.

```
Останні кроки (1):
  · [ok] read_file —  · файли: a.py
```

Порожньо: `Історія завдань порожня.`

### memory_recover

`action` ∈ `status`, `integrity`, `backup`, `restore`, `consolidate`,
`migrate_legacy`; `path` — для `restore`.

```
Пам'ять: 1 спогадів (1 активних), 0 зв'язків, 0 конфліктів, 0 з векторами.
Точність прогнозів: 0.2 на 2 вимірах.
Бекапів: 8.
```

```
Цілісність: гаразд (версія схеми 4)
База: C:\Users\…\neuromesh\memory.db
```

```
Бекап створено: …\backups\memory-20261108-183844.db (126976 байт)
Консолідація: злито 0, позначено застарілими 0, конфліктів 0.
Перенесено зі старого RAG: 25 (пропущено дублів 6) з index.sqlite3:rag_memory, memoria_infinita.db:fatti_permanenti
```

`restore` без `path`: `✗ Для відновлення вкажи шлях до бекапу.`

### memory_feedback

`memory_id`, `useful` (обов'язкові), `note`.

```
Вдячний: впевненість скориговано.
Врахую: знижую впевненість цього спогаду.
```

## 3. Як інструменти потрапляють до агента

`ToolRegistry.attach_memory(service)` створює `MemoryTools(service)`,
реєструє кожен обробник через `_memory_handler_for()` (щоб аргументи
проходили `MemoryTools.call`, тобто схему) і зберігає
`MEMORY_TOOL_SCHEMAS` у `_memory_schemas`. `detach_memory()` прибирає їх.
До `attach_memory` інструментів `memory_*` немає — «агент не може
«викликати» те, чого немає, і не отримує фальшивих відповідей».## 4. Приклад повного циклу

```python
from blackchpok_ide.pcmm import Neuromesh
from blackchpok_ide.pcmm.tools import MemoryTools

memory = Neuromesh()
tools = MemoryTools(memory)

tools.call("memory_store", {"content": "Контекст 16K дає 26–31 токен/с на RTX 3060.",
                            "kind": "fact", "source": "bench_report.json"})
print(tools.call("memory_search", {"query": "RTX 3060 токен за секунду"}))
print(tools.call("memory_project_context", {"query": "контекст", "window": 4096}))
print(tools.call("memory_recover", {"action": "backup"}))
memory.close()
```

## Підсумок

`Neuromesh` — фасад із 20+ методами, що повертають звичайні `dict` зі
стабільними ключами: запис, пошук, recall, explain, predict,
project_context, consolidate, backup/restore, status, migrate_legacy_rag.
Поверх нього `MemoryTools` дає рівно 12 інструментів `memory_*`: кожен
валідує аргументи за JSON-схемою, повертає людино-читний **текст** і
позначає будь-яку невдачу префіксом `✗`.
