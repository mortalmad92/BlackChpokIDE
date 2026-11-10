# Архітектура пам'яті NEUROMESH Ω (PCMM)

`blackchpok_ide/pcmm/` — Predictive Causal Memory Mesh. Це не «сховище
тексту», а набір тверджень із походженням, часом дії та впевненістю, з
гібридним пошуком і вимірюваним прогнозом контексту.

Склад пакета (з `pcmm/__init__.py`):

| Модуль | Відповідальність |
| --- | --- |
| `store` | SQLite: WAL, міграції, бекапи, цілісність |
| `models` | `Memory`: типи, provenance, впевненість, зв'язки |
| `repository` | запис, дублікати, конфлікти, версії, консолідація |
| `retrieval` | гібридний пошук + прогнозування контексту |
| `budget` | бюджет контексту на реальних токенах |
| `service` | фасад `Neuromesh` для IDE й інструментів агента |
| `tools` | 12 інструментів `memory_*` |

Важлива рамка з docstring: «Назви «алгоритмів» тут описові. Використані
відомі механізми: BM25 (FTS5), косинусна схожість векторів, Reciprocal Rank
Fusion, пошук у графі в ширину з обмеженою глибиною, часовий спад. Власних
«винаходів» не заявляється».

Уточнення щодо RRF: константа/формула RRF у коді **не** використовується —
оцінка є зваженою сумою каналів (`BASE_WEIGHTS`), а не reciprocal rank
fusion. Це варто знати, читаючи docstring.

## 1. Типи спогадів (KINDS)

```python
KINDS = ("fact", "decision", "error", "fix", "task",
         "dependency", "tool", "constraint", "change", "preference")
```

| Тип | Зміст | Тип | Зміст |
| --- | --- | --- | --- |
| `fact` | перевірене твердження про проєкт | `dependency` | залежність файлів/модулів |
| `decision` | прийняте рішення (і чому) | `tool` | результат інструмента |
| `error` | помилка, яка трапилась | `constraint` | технічне обмеження |
| `fix` | виправлення помилки | `change` | історія змін |
| `task` | завдання та його стан | `preference` | уподобання користувача |

Розширювати перелік можна, **перейменовувати не можна**: на назви спираються
ваги пошуку й інтерфейс. Невідомий `kind` у конструкторі `Memory`
замінюється на `"fact"`.

Ваги типів `KIND_WEIGHT` (обмеження й виправлення корисніші за «сирі» факти):

```
constraint 1.30 · fix 1.20 · decision 1.15 · fact 1.10 · preference 1.05
dependency 1.00 · error 0.95 · task 0.90 · change 0.85 · tool 0.80
```

У пошуку ця вага входить окремим доданком:
`channels["kind"] = min(1.0, kind_weight - 0.7) * 2.0`, далі
`total += 0.05 * channels["kind"]`.

## 2. Зв'язки (RELATIONS)

```python
RELATIONS = ("caused", "fixed_by", "depends_on",
             "contradicts", "supersedes", "related", "part_of")
```

Зберігаються напрямлено в `memory_links(src, dst, relation, weight)` з
`UNIQUE(src, dst, relation)` і `ON CONFLICT … weight = MAX(weight, excluded.weight)`.
Невідомий тип зв'язку в `add_link()` стає `"related"`; вага обрізається до
`0.0…1.0`. `links(memory_id)` повертає **обидва** напрямки:
`{"out": [...], "in": [...]}`. `neighbours(id, depth=1)` — обхід у ширину з
обмеженою глибиною (без повного скану).

## 3. Впевненість

`Memory.confidence` — число `0.0…1.0` (обрізається в `__post_init__`),
типове значення `0.6`. Вона **не** залежить від віку; її змінюють:

| Подія | Зміна | Де |
| --- | --- | --- |
| повторний запис із **іншого** джерела | `+0.10` | `repository._confirm` |
| повторний запис із того самого джерела | `+0.05` | `repository._confirm` |
| `memory_verify` / `Neuromesh.verify` | до `+0.15` (або явне значення) | `service.verify` |
| зворотний зв'язок «корисно» | `+0.08` | `repository.feedback` |
| зворотний зв'язок «не корисно» | `−0.12`, підлога `0.05` | `repository.feedback` |
| конфлікт вирішено на користь факту | до `+0.15` | `resolve_contradiction` |
| консолідація дублікатів | `max(conf) + 0.05` | `consolidate` |

Константа `MAX_CONFIRMATIONS = 5` описана в коді, але в розрахунках **не
використовується** — зростання впевненості обмежує лише `min(1.0, …)`.
Тобто «після 5 підтверджень впевненість максимальна» — це не те, що робить
код.

## 4. Provenance

Кожен спогад несе `source` (звідки: `agent_tools.py:150`, `ide.log`,
`benchmark`, `rag:<файл>`), `provenance` (точніше місце), `files` і `tags`
(JSON у базі), `task`, часові поля `created_at`/`updated_at`/`accessed_at`/
`hits`, `valid_from`/`valid_to` і `superseded_by` — чим замінено **замість
видалення**.

`Memory.is_active` = `not superseded_by and (not valid_to or valid_to > now)`;
`age_days` — вік у днях. Подвійний захист від дублікатів: `content_hash`
(точний зміст після нормалізації пунктуації й регістру) і `fingerprint`
(відбиток множини лексем разом із `kind`).

## 5. Гібридний пошук

Ваги за замовчуванням (`BASE_WEIGHTS`, сума = 1.0):

```python
{"lexical": 0.34, "semantic": 0.34, "graph": 0.12,
 "temporal": 0.10, "confidence": 0.10}
```

Канали:

* **lexical** — FTS5 `bm25(memory_fts)`, запит із лексем (`tokens_of`, до 24
  термів). FTS5 не має стемера, тому додаються варіанти: `"term"`,
  `"term"*` (слова ≥ 4 символів) і `"stem"*`, де `stem = term[:-2]` для слів
  ≥ 7 символів. BM25 у SQLite від'ємний — оцінка нормалізується в `0…1`
  через `(score - worst) / span`. Якщо FTS недоступний —
  `_lexical_fallback()` рахує входження підрядків серед перших 4000
  активних спогадів.
* **semantic** — косинус між вектором запиту й `embedding` спогадів (ліміт
  5000 рядків); вектори іншої розмірності пропускаються. Канал вмикається
  **лише** якщо в базі є хоч один вектор (`vectors_ready`).
* **graph** — сусіди 8 найкращих кандидатів з `memory_links` (один крок, не
  обхід); вага з `weight` зв'язку.
* **temporal** — `0.7 * exp(-age_days / 30) + 0.3 * (accessed_at / now)`,
  обрізано до `0…1`: свіже важливіше, але старе не стає нулем.
* **files** (окремо від політики) — прив'язані до переданих `files` спогади
  отримують `channels["task"] = 0.8`.

Підсумкова оцінка:

```python
total = Σ(weight[name] * channels[name] for name in policy.weights)
total += 0.05 * channels["kind"]
total += 0.08 * channels["task"]
```

`channels["confidence"] = memory.confidence` завжди (не залежить від
політики), `channels["temporal"]` = 0, якщо канал вимкнено. Кожен `Hit`
несе `channels` і `explanation` — текст на кшталт `"lexical+graph+temporal
(точний ідентифікатор): збіг слів 0.71; пов'язаний через граф; впевненість
0.80; тип constraint"`. Оцінка без пояснення заборонена (тест
`test_hit_explains_why`). Пошук за замовчуванням `activate=True` викликає
`repository.touch()`, тобто підвищує `hits` і `accessed_at` знайденого.

## 6. Адаптивна політика (`choose_policy`)

```python
def choose_policy(query, *, vectors_ready: bool, limit: int = 12) -> SearchPolicy
```

Правила (у порядку застосування):

1. `policy.semantic = vectors_ready`.
2. Якщо векторів немає — вага `semantic` переноситься в `lexical`, а
   `semantic` стає `0.0`; причина: «немає векторів — лише лексемний пошук».
3. Інакше, якщо в запиті є точний ідентифікатор (`_IDENTIFIER` —
   `agent_tools.read_file`, шлях із розширенням коду) **або** щось у
   лапках (`_QUOTED`):
   `lexical 0.52 · semantic 0.24 · graph 0.10 · temporal 0.06 · confidence 0.08`,
   причина «точний ідентифікатор».
4. Інакше, якщо лексем ≥ 6 (описовий запит):
   `lexical 0.24 · semantic 0.46 · graph 0.12 · temporal 0.08 · confidence 0.10`,
   причина «описовий запит».
5. Інакше — базові ваги, причина «короткий запит».
6. Якщо лексем ≤ 2: `graph` і `temporal` вимикаються, їхні ваги частково
   переходять у `lexical` (+`BASE_WEIGHTS["graph"] * 0.5` = 0.06) і
   `semantic` (+`weights["graph"] * 0.5`).

`SearchPolicy.describe()` повертає, наприклад, `"lexical+graph+temporal
(описовий запит)"` — саме цей рядок показує панель пам'яті й інструмент
`memory_search`.

Реальний приклад із `bench_report.json`: усі шість запитів ішли з
`"немає векторів — лише лексемний пошук"`, бо в тестовій базі векторів не
було. Для запиту з одного слова (`"shell"`) фактичні ваги:
`{'lexical': 0.74, 'semantic': 0.06, 'graph': 0.0, 'temporal': 0.0,
'confidence': 0.1}`.

**Дві особливості, які варто знати.** (1) У гілці `len(words) <= 2` вага
`weights["graph"] * 0.5` додається в `semantic` навіть тоді, коли канал
`semantic` уже вимкнено — тому в `search()["weights"]` може бути ненульовий
`semantic` при `policy.semantic == False`; на оцінку це не впливає, бо
канал не вмикається. (2) `_lexical()` нормалізує BM25 як
`(score - worst) / span`; коли знайдено **один** результат, `span = 1e-9` і
оцінка каналу виходить `0.0` — тому в `explanation` немає фрази «збіг
слів», хоча спогад знайдено саме лексемно.

## 7. Консолідація

`repository.consolidate(dry_run=False)`:

1. Бере всі активні спогади (`superseded_by = ''`) за зростанням
   `created_at` — найстаріший стає «канонічним».
2. Ключ групування: `f"{kind}:{content_hash}"`. Додатково перевіряється
   перефразування: `overlap(candidate.content, memory.content) >=
   DUPLICATE_THRESHOLD` (0.82) у межах того самого `kind`.
3. Дублікат → текст зливається (`merge_contents`, що відкидає фрагменти з
   `overlap > 0.8`), впевненість піднімається, дублікат отримує
   `superseded_by` **і не видаляється**.
4. Суперечності шукаються лише серед канонічних записів того самого типу:
   `contradiction_score(...) >= CONTRADICTION_THRESHOLD` (0.45) → зв'язок
   `contradicts` і запис у таблицю `contradictions`.

`contradiction_score()` — евристика: високе перекриття теми (Jaccard ≥ 0.25)
при достатній різниці (≥ 0.35) дає `jaccard*0.6 + differs*0.4` (+0.15,
якщо серед спільних лексем є ідентифікатори з `_`, `.` або `/`). У тестах є
`skipTest` на випадок, коли вона не знаходить конфлікт.
`resolve_contradiction(id, keep=<memory_id>)` лишає переможця активним
(`+0.15`), переможений отримує `superseded_by`.

## 8. Прогнозування (`ContextPredictor`)

`predict(current_files, task, query, limit=8)` використовує чотири сигнали,
«усі — з реальної історії, не вигадані»:

1. **відкриті файли** — `repository.by_files(files)`; score = `confidence`,
   explanation «прив'язано до відкритого файлу»;
2. **переходи між файлами** з `task_history` (`_transitions()` рахує
   нормовані частоти «файл A → файл B» у межах одного запису історії);
3. **пошук за запитом** — `retriever.search(query, activate=False)`;
4. **незакриті помилки** — `list(kind="error", limit=5)`, у яких немає
   зв'язку `fixed_by` або `supersedes`; score 0.4, explanation «помилка без
   зафіксованого виправлення».

`Prediction.confidence = min(1.0, 0.25 + 0.15 * <кількість різних сигналів>)`,
`reason` — список сигналів через `; `. Кожен прогноз пишеться в таблицю
`predictions`. Точність **вимірюється**, а не обіцяється:
`record_outcome(used_ids, predicted_ids)` рахує `precision = hits /
len(predicted)` і записує в останній рядок `predictions`, а
`accuracy(limit=200)` повертає `{"samples", "precision", "hit_rate", "last"}`.
`Neuromesh.record_prediction_outcome(used_ids=…)` бере останній
`ContextBundle` і передає його `prediction.memories` у `record_outcome`.

## 9. Бюджет контексту (`BudgetGovernor`)

Завдання: зібрати блок, який (1) влізе у вікно з запасом на відповідь,
(2) не має дублів, (3) зберігає критичні обмеження, (4) максимізує
«цінність на токен», (5) може пояснити включення.

Токени рахуються реальним tokenizer моделі:

```python
BudgetGovernor.for_tokenizer(tokenizer)   # tokenizer.count(text, add_special=False)
BudgetGovernor.heuristic()                # оцінка, exact=False
```

Евристика: `1.7` символа на токен, якщо кирилиці > 50 %, інакше `3.6`;
`governor.exact` честно показує, чи це точний підрахунок.
`fit(pieces, window, reserve_tokens=0, max_share=0.7)` рахує
`budget = max(0, int(window * max_share) - max(MIN_RESPONSE_TOKENS,
reserve_tokens))`, де `MIN_RESPONSE_TOKENS = 256`, `CRITICAL_SHARE = 0.5`.
Порядок: спершу критичні фрагменти (обмеження, уподобання) у межах
`max(budget * CRITICAL_SHARE, budget)`, далі решта за спаданням
`score / tokens`. Дублі відкидаються за нормалізованим текстом. Якщо не
ввійшло нічого, але щось є — додається найменший фрагмент.
Константа `RESPONSE_SHARE = 0.30` описана, але у формулі `fit()` не
використовується (запас задає `MIN_RESPONSE_TOKENS`).

`ContextBundle` у `service.project_context()` формується так:

1. `governor()` — на tokenizer моделі, якщо вона завантажена; інакше
   `heuristic()`;
2. `choose_policy` → `retriever.search(limit=24)`;
3. **обов'язкові обмеження**: `list(kind="constraint", limit=8)` додаються
   першими й окремо — «навіть якщо запит про щось інше, «ніколи не робити X»
   мусить бути в контексті»;
4. спогади з пошуку; 5. спогади з прогнозу зі score `* 0.8`;
6. `governor.fit(pieces, window=window, max_share=MEMORY_WINDOW_SHARE)` —
   типова частка вікна під пам'ять **0.38**.

`tokens_saved` — сума токенів фрагментів, що не влізли; `note` = «Токени
оцінені приблизно: модель не завантажена», якщо `exact=False`.

## 10. Робота без моделі

Ключова вимога (з docstring `service.py`): система працює **навіть без
завантаженої моделі**. Тоді пошук лексемний (BM25), вектори не рахуються, і
`status()["tokens"]["source"]` честно каже
`"оцінка (модель не завантажена)"`, а `search` вмикає лише лексеми.

## Підсумок

Пам'ять — це 10 типів тверджень із provenance, впевненістю та часом дії,
7 типів напрямлених зв'язків і принцип «застаріле позначається, а не
видаляється». Пошук — зважена сума п'яти каналів (`lexical 0.34`,
`semantic 0.34`, `graph 0.12`, `temporal 0.10`, `confidence 0.10`), які
`choose_policy()` вмикає й переважує залежно від запиту; кожен збіг
пояснює свою оцінку. Консолідація зливає дублікати в найстаріший запис,
прогноз спирається на відкриті файли, переходи в історії та незакриті
помилки (точність вимірюється в `predictions`), а бюджет контексту
рахується реальним tokenizer (або чесно позначається як оцінка) і ніколи
не викидає критичні обмеження.
