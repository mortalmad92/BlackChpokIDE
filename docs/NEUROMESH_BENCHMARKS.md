# Бенчмарки рушія й пам'яті

`blackchpok_ide/bench.py` — вимірювальний стенд. Принцип, зафіксований у
docstring: «Якщо чогось виміряти неможливо (немає моделі, немає GPU),
результат позначається `"skipped"` з ПРИЧИНОЮ. Підставляти вигадані числа
заборонено — на цьому тримається довіра до звіту».

## 1. Як запускати

### Через Python

```python
from blackchpok_ide import bench
from blackchpok_ide.native.api import NativeRuntime
from blackchpok_ide.pcmm import Neuromesh

runtime = NativeRuntime()
runtime.load_model("qwen2.5-coder-14b-instruct-q4_k_m.gguf", ctx=4096)

report = bench.run_all(runtime, Neuromesh(), runs=2, k=3)

bench.save(report, "research/bench_report.json")
```

УВАГА: `run_all(memory=…)` викликає `MemoryBenchmark.run(seed=True)`, а
`seed_cases()` **записує** 6 тестових спогадів у ту базу, яку ви передали.
Не передавайте справжню робочу пам'ять — зробіть тимчасову:
`Neuromesh("D:/tmp/bench.db")`.

### Окремі частини

```python
engine_part = bench.EngineBenchmark(runtime).run(runs=3, max_tokens=64)
memory_part = bench.MemoryBenchmark(memory).run(k=3, window=4096, seed=True)

diff = bench.compare(older_report, newer_report)
```

### Через тести

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_bench -v
```

`tests/test_bench.py` перевіряє саме «анти-фальсифікацію»: без моделі
`EngineBenchmark` мусить віддати `status="skipped"` і порожні `metrics`,
`Recall@K` мусить падати до 0 на порожній базі, а `compare()` — показувати
напрям зміни.

## 2. Що міряється

`EngineBenchmark.run()`:

| Метрика | Джерело |
| --- | --- |
| `time_to_load_ms` | `engine.describe()["load_ms"]` (виміряно в `LoadedModel._load`) |
| `time_to_first_token_ms` | `stats.prefill_ms`, середнє + `samples` + p50/p95/p99 |
| `tokens_per_second` | `stats.generated_tokens / decode_ms` |
| `prompt_tokens_per_second` | свіжі токени промпту / `prefill_ms` |
| `peak_vram_mb` | `nvidia-smi --query-gpu=memory.used` після кожного прогону |
| `peak_ram_mb` | `PeakWorkingSetSize` процесу (Win32 `GetProcessMemoryInfo`) |
| `vram_baseline_mb`, `ram_baseline_mb` | ті самі джерела **до** генерації |
| `total_ms` | повний час запиту |
| `kv_cache_capacity` | `engine.describe()["kv"]["capacity"]` |

Перед кожним прогоном кеш **чиститься**: інакше другий прогін «читав» би
префікс і показував нереалістично малий TTFT. Генерація детермінована:
`temperature=0.0, top_k=1, top_p=1.0, min_p=0.0, repeat_penalty=1.0`.

Типовий промпт (`DEFAULT_PROMPT`): «Поясни коротко, що робить функція, яка
читає файл у межах робочої теки проєкту, і наведи приклад виклику.»
`DEFAULT_RUNS = 3`.

`MemoryBenchmark.run(k=3, window=4096, seed=True)`:

* `seed_cases()` записує 6 спогадів із `CASES` із `source="benchmark"`,
  `confidence=0.85`;
* для кожного запиту — `memory.search(query, limit=max(k,5))`;
* **Recall@K** = 1.0, якщо правильний id у топ-K;
* **Precision@K** = `1 / len(hits)` (тобто 1/кількість відданих
  результатів — тому при 6 результатах максимум 0.167);
* **MRR** = `1/rank`;
* **token_savings_share** = `tokens_saved / (used + tokens_saved)` із
  `project_context(query, window)`;
* `prediction_accuracy` — з `status()["prediction"]`.

Шість `CASES` (запит → очікуваний спогад → тип):

1. «де виконуються команди» → «run_command виконує команди через shell=True…» → `constraint`
2. «як читається файл» → «read_file читає файли лише в межах робочої теки…» → `fact`
3. «який контекст у моделі» → «Контекст моделі 16K токенів дає 31 токен за секунду на RTX 3060.» → `fact`
4. «що було з помилкою theme» → «Помилка NameError у chat_panel.py…» → `error`
5. «як виправлено імпорт» → «Виправлення: додано імпорт theme у chat_panel.py.» → `fix`
6. «навіщо KV-кеш» → «KV-кеш переиспользує префікс промпту…» → `fact`

## 3. Реальні результати цієї машини

Джерело: `research/bench_report.json` (`harness: "blackchpok-bench"`,
3 прогони). Залізо й конфігурація:

```
CPU        AMD Ryzen 5 3600 6-Core Processor (12 потоків)
RAM        65461 МБ (≈64 ГБ)
GPU        NVIDIA GeForce RTX 3060, 12288 МБ VRAM, драйвер 621.01
Модель     qwen2.5-coder-14b-instruct-q4_k_m.gguf (8 988 110 272 байт)
llama.cpp  0.9.0-dev, build b12129, бекенд cuda
Параметри  ctx 16384, gpu_layers -1 (усі шари + lm_head), cache q8_0, threads 12
```

### Рушій

| Метрика | Значення |
| --- | --- |
| Завантаження моделі | **4038 мс** (≈ **4.0 с**) |
| Швидкість декодування | **30.54 ток/с**; p50 30.36, p95 30.86 (прогони 30.91 / 30.36 / 30.34) |
| TTFT (prefill) | **71.2 мс** у середньому; p50 34.6, p95 134.2 (перший прогін холодний: 145.3 мс) |
| Обробка промпту | 1353 ток/с (перший прогін 427, далі 1793 і 1840 — прогрів ваг) |
| Повний час запиту | 2168 мс; p50 2144, p95 2210 |
| Peak VRAM | **10661 МБ** (≈10.4 ГіБ) |
| Peak RAM процесу | **8661 МБ** (≈8.5 ГіБ) |
| Ємність KV-кешу | 16384 токенів |

**Чому раніше було 26.6 ток/с, а тепер 30.5 — це не «інша методика», а
виправлений дефект.** `n_gpu_layers = layer_count` (48) кладе на GPU лише
блоки трансформера, а вихідний шар `lm_head` лишається на CPU. llama.cpp
розуміє «всі шари» як **`-1`**. Замір на тій самій моделі й тому самому
залізі, `ctx 4096`, KV `q8_0`:

| `n_gpu_layers` | ток/с | TTFT |
| --- | --- | --- |
| 48 (лише блоки) | 25.62 | 43.9 мс |
| `-1` (усі + lm_head) | **31.19** | 84.4 мс |
| 999 (те саме, але через велике число) | 31.19 | 84.4 мс |

Тобто різниця **+21 %** швидкості. Виправлення — у
`native/inspect.py::predict` (`suggested_gpu_layers = -1` для повного
offload) і в `native/engine.py::LoadedModel._load`, який нормалізує будь-яке
значення ≥ `layer_count` у `-1`. Тест-регресія:
`test_native_runtime.TestForecast.test_full_offload_means_all_layers`.

Окремо перевірено, що **не** є причиною різниці: abort callback (+0.2 %),
`llama_perf_context` (0 %), постійний `llama_batch` (0 %). Виміряно, щоб не
гадати.<br>

При `ctx 16384` повний offload усе ще влазить у 12 ГБ, але впритул: пік
10661 МБ із 12288 — далі починається витіснення й різке падіння (заміряно:
`gpu_layers=999` при `ctx 16384` у перевантаженій VRAM дає 0.27 ток/с).
Саме тому типовий контекст у профілі — 16K, а не 32K.

### Пам'ять

```json
{"status": "ok", "queries": 6, "k": 3, "window": 4096,
 "recall_at_k": 1.0,
 "precision_at_k": 0.833,
 "mrr": 1.0,
 "token_savings_share": 0.0,
 "counts": {"memories": 6, "active": 6, "links": 0,
            "conflicts": 0, "with_vectors": 0}}
```

| Метрика | Значення на 6 запитах |
| --- | --- |
| Recall@3 | **1.0** (усі 6 спогадів знайдено) |
| Precision@3 | **0.833** |
| MRR | **1.0** (усі на ранг 1) |
| Економія токенів | 0.0 (усе влізло у вікно 4096) |

Усі шість запитів мали `rank: 1` і політику без семантики:
`"lexical (немає векторів — лише лексемний пошук)"`, бо в тестовій базі
`with_vectors = 0`. Тобто **Recall@3 = 1.0 тут досягнуто чистим лексемним
каналом FTS5**, а не гібридом — це важлива деталь для інтерпретації.

Precision@3 = 0.833 — середнє від `1/len(hits)`: для запиту «що було з
помилкою theme» повернулось 2 результати (0.5), для решти — по 1 (1.0),
середнє = 5/6 ≈ 0.833. Формула саме така в коді, тому «Precision@3»
фактично міряє, скільки зайвих результатів повернув пошук, а не класичну
precision@k.

`token_savings_share = 0.0` означає, що губернатор нічого не викинув:
6 коротких спогадів улізли у вікно 4096 цілком. На реальному проєкті з
десятками спогадів це число стає додатним — тоді його й треба дивитись.

## 4. Як зберігати й порівнювати

```python
bench.save(report, "research/bench_report.json")   # створює батьківські теки
```

`save()` пише UTF-8 JSON із `indent=2`, `ensure_ascii=False`.

`compare(left, right)` повертає для рушія (`tokens_per_second`,
`time_to_first_token_ms`, `peak_vram_mb`, `total_ms`) і для пам'яті
(`recall_at_k`, `precision_at_k`, `mrr`, `token_savings_share`) по об'єкту
`{"left", "right", "delta", "ratio"}`. `ratio` = `None`, якщо `left == 0`.
Порожні секції дають порожні словники (це перевіряє тест
`test_compare_handles_missing_sections`).

Приклад із тесту:

```python
left  = {"engine": {"metrics": {"tokens_per_second": {"value": 20.0}}}}
right = {"engine": {"metrics": {"tokens_per_second": {"value": 30.0}}}}
bench.compare(left, right)["engine"]["tokens_per_second"]
# {'left': 20.0, 'right': 30.0, 'delta': 10.0, 'ratio': 1.5}
```

## 5. Порівняння з Ollama / LM Studio — НЕ ПРОВОДИЛОСЬ

Це **незакритий пункт**, і його треба зафіксувати прямо.

**Що зроблено:** виміряно власний рушій (`EngineBenchmark`) і власну пам'ять
(`MemoryBenchmark`) на цій машині; числа наведені вище й лежать у
`research/bench_report.json`.

**Що не зроблено:** жодного запуску Ollama або LM Studio в цьому середовищі
не було, тому порівняльних чисел «ми проти них» **не існує**.

**Причина — конкретна, а не «брак часу»:**

1. Обидва інструменти є окремими застосунками з власним сервером і власним
   життєвим циклом моделі; у цьому середовищі їх не встановлено й не
   запущено. Перевірити це можна так:

   ```powershell
   Get-Command ollama, lms -ErrorAction SilentlyContinue
   Get-Process ollama, LM* -ErrorAction SilentlyContinue
   ```

   Порожній результат означає, що порівнювати нічого.

2. Коректне порівняння вимагає **того самого файлу ваг** і **тих самих**
   `ctx`, `n_gpu_layers`, типу KV-кешу й промпту. Ollama та LM Studio мають
   власні типові значення (власні шаблони, власні kv-типи), тому «просто
   запустити» їх означало б порівнювати конфігурації, а не рушії.

3. Метрики в цьому стенді зняті з **вбудованого** рушія
   (`EngineBenchmark` читає `engine.describe()` і `llama_perf_context`).
   Для Ollama/LM Studio таких самих полів немає — потрібен був би окремий
   вимірювач (HTTP-клієнт + `nvidia-smi`), якого в `bench.py` **немає**:
   пошук `ollama` у `blackchpok_ide/bench.py` не дає збігів.

**Що потрібно, щоб пункт закрити** (конкретний план, не обіцянка):

1. Встановити Ollama і LM Studio, завантажити **той самий**
   `qwen2.5-coder-14b-instruct-q4_k_m.gguf`.
2. Виставити ідентичні параметри: `ctx 4096`, усі шари на GPU, KV `q8_0`,
   `temperature 0`, `max_tokens 64`, той самий `DEFAULT_PROMPT`.
3. Зняти `time_to_load_ms`, `tokens_per_second`, TTFT і пік VRAM тим самим
   способом (`nvidia-smi` до/після, 3 прогони, кеш очищено).
4. Записати три звіти в однаковому форматі й прогнати `bench.compare()`.

Доти будь-яке твердження «швидше/повільніше за Ollama» буде вигадкою.

## 6. Що бенчмарк не міряє

* Якість відповідей (лише швидкість і пам'ять). Якість наміряє
  `MemoryBenchmark` для пошуку, але не для генерації.
* Енергоспоживання, температуру під навантаженням, тротлінг.
* Час холодного старту рушія (перше завантаження DLL) — `load_ms`
  починається з `llama_model_load_from_file`.
* Багатопотокові сценарії: `EngineBenchmark` робить прогони послідовно.
* Порівняння з іншими рушіями (див. розділ 5).

## Підсумок

`bench.run_all()` міряє те, що справді можна зняти: час завантаження,
tok/s, TTFT із перцентилями, пік VRAM з `nvidia-smi`, пік RAM процесу,
ємність KV-кешу — і чесно віддає `skipped` із причиною, коли моделі немає.
На цій машині (RTX 3060 12 ГБ, Ryzen 5 3600, 14B Q4_K_M, ctx 4096, 48
шарів на GPU, KV `q8_0`) отримано: завантаження 4.07 с, 26.59 ток/с,
TTFT 136.55 мс (p95 209.6), пік VRAM 9569 МБ, пік RAM 8665.9 МБ; пам'ять —
Recall@3 = 1.0, Precision@3 = 0.833, MRR = 1.0 на 6 запитах (лексемним
каналом, бо векторів у тестовій базі не було). Порівняння з Ollama та
LM Studio **не проводилось** й лишається незакритим пунктом із
задокументованою причиною та планом дій.
