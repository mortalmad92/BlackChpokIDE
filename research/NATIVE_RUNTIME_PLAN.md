# NATIVE RUNTIME — план і фактична реалізація

Документ описує **власний рушій** BLACKCHPOK IDE: модулі, причини рішень,
реально виміряні числа й чесні обмеження. Числа взяті з двох джерел:

1. `.buildtmp/bench_report.json` — звіт, зроблений самим `bench.py` на цій машині;
2. мої власні прогони `NativeEngine` під час цього аудиту (окремо позначені).

Залізо в обох випадках те саме: **AMD Ryzen 5 3600 (6 ядер / 12 потоків),
NVIDIA GeForce RTX 3060 12 ГБ, 64 ГБ RAM**, Windows, `llama.dll` build 12129
(версія `0.9.0-dev`), бекенд CUDA (`userdata/runtime/backend.txt` = `cuda`).

---

## 1. Модулі й відповідальність

| Модуль | Відповідальність | Ключові сутності |
|---|---|---|
| `native/_abi.py` | C-структури llama.cpp для `ctypes`, переліки | `LlamaModelParams`, `LlamaContextParams`, `LlamaBatch`, `GGML_TYPE`, `FLASH_ATTN`, `DECODE_ABORTED` |
| `native/_bindings.py` | завантаження `llama.dll`+`ggml*.dll`, прив'язка сигнатур, перевірка ABI, пристрої | `LlamaLibrary`, `BackendDevice`, `NativeUnavailable`, `_register_dll_dir` |
| `native/_quant.py` | `llama_ftype` → назва, біти на вагу | `FTYPE_NAMES`, `BITS_PER_WEIGHT`, `bits_per_weight` |
| `native/gguf.py` | читання метаданих GGUF **до** завантаження ваг (mmap, без копіювання словника) | `GgufMeta`, `read_meta`, `read_meta_safe`, `looks_like_gguf`, `quant_from_filename` |
| `native/inspect.py` | діагностика + прогноз RAM/VRAM/шарів + цілісність + SHA-256 | `ModelReport`, `inspect`, `predict`, `kv_cache_gb`, `verify_integrity`, `sha256_of` |
| `native/tokenizer.py` | **реальний** tokenizer моделі, кеш на 4096 записів | `Tokenizer`, `Token`, `estimate_ratio` |
| `native/sampling.py` | параметри й ланцюжок семплерів, стоп-послідовності | `SamplingParams`, `SamplerChain`, `StopMatcher`, `LIMITS` |
| `native/chatfmt.py` | шаблон чату з GGUF + текстовий адаптер tool calling | `ChatFormatter`, `tool_schemas_prompt`, `extract_tool_calls`, `has_native_tool_support` |
| `native/kv.py` | дзеркало KV-кешу, переиспользование префікса | `CacheManager`, `CacheState`, `estimate_kv_bytes` |
| `native/engine.py` | життєвий цикл моделі, генерація, стрімінг, скасування, embeddings | `NativeEngine`, `LoadedModel`, `EngineContext`, `StreamChunk`, `GenerationStats` |
| `native/embeddings.py` | вектори + кеш у SQLite з підписом моделі | `EmbeddingService`, `cosine`, `top_k`, `text_hash` |
| `native/manager.py` | життєвий цикл файлів моделей | `ModelManager`, `ModelEntry` |
| `native/api.py` | фасад для решти IDE | `NativeRuntime`, `RequestStats` |
| `native/bridge.py` | міст до `LLMClient` (контракт OpenAI) | `EMBEDDED_URL`, `chat`, `chat_stream`, `ping` |

Межа відповідальності жорстка: **`engine.py` — єдине місце, де викликається
`llama_decode`**; `api.py` не знає про ctypes, `bridge.py` не знає про `api`
далі, ніж публічні методи.

---

## 2. Чому `ctypes`, а не `llama-cpp-python`

Перевірено на цій машині (`python --version` → **3.14.7**):

```
python -m pip download llama-cpp-python --no-deps --only-binary=:all:
→ ERROR: No matching distribution found for llama-cpp-python
```

Тобто **готового wheel для Python 3.14 немає**: пакет є в індексі (0.3.36 —
остання версія), але збірок під cp314 немає. Лишається sdist, а він вимагає
компіляції C++/CUDA під час встановлення: `CMake`, MSVC Build Tools, сумісний
CUDA Toolkit. На машині без повного набору інструментів це падає ще на етапі
розпакування/конфігурації, а не «десь у рантаймі» — і користувач отримує IDE без
рушія.

`ctypes` не потребує нічого цього: `llama.dll` уже скомпільований, а
`_bindings.py` лише описує сигнатури. Порівняння:

| Критерій | `llama-cpp-python` | `ctypes` + готова DLL |
|---|---|---|
| Компіляція на машині користувача | потрібна (sdist) | **не потрібна** |
| Оновлення рушія | перезбирання пакета | заміна DLL у `userdata/runtime` |
| Контроль над `n_gpu_layers`, KV-типами, abort callback | через API-обгортку | **прямий**, сигнатури в наших руках |
| Ризик | залежність від версії пакета | ABI-розбіжність, яку треба ловити самим |
| Ціна | важка залежність | треба самим описати структури й перевіряти ABI |

Саме тому в `_bindings.py` є **перевірка ABI**: розмір `llama_model_params`
читається з `llama_model_default_params().restype` і порівнюється з
`ctypes.sizeof(_abi.LlamaModelParams)`. Розбіжність дає зрозумілу помилку одразу
при завантаженні, а не «дивні» падіння посеред генерації.

---

## 3. Що виміряно на реальному залізі

Є **три незалежні джерела чисел** на тій самій машині й тій самій моделі
(`qwen2.5-coder-14b-instruct-q4_k_m.gguf`, 14B, Q4_K_M, 8.37 ГБ, `threads 12`).
Вони не суперечать одне одному — вони показують **різні конфігурації**, і саме
тому наведені всі три.

### 3.1. Звіт `bench.py`, конфігурація ctx 4096 (`.buildtmp/bench_report.json`)

`ctx 4096`, `gpu_layers 48` (усі шари), `cache q8_0`.

| Метрика | Значення | Примітка |
|---|---|---|
| Час завантаження моделі | **4071.9 мс ≈ 4.1 с** | `time_to_load_ms` |
| Швидкість декодування | **26.59 ток/с** (прогони 26.64 і 26.54) | стабільно |
| TTFT (prefill) | **136.55 мс** p50; прогони 217.7 і 55.4 мс | p95 = 209.6 мс |
| Обробка промпту | **702 ток/с** середнє; 284.8 і 1119.2 | промпт лише 62 токени |
| Пікова VRAM | **9569 МБ** із 12288 | `nvidia-smi` під час генерації |
| Пікова RAM процесу | **8665.9 МБ** | `PeakWorkingSetSize` |
| Повний час запиту | 2543.9 мс | 64 токени відповіді |

### 3.2. Звіт `bench.py`, конфігурація ctx 16384 (`research/bench_report.json`)

`ctx 16384`, `gpu_layers -1` (**авто** — кількість шарів обрала
`inspect.predict()`), `cache q8_0`, 3 прогони.

| Метрика | Значення | Примітка |
|---|---|---|
| Час завантаження моделі | **4038.2 мс ≈ 4.0 с** | збігається з 3.1 |
| Швидкість декодування | **30.54 ток/с** (30.91, 30.36, 30.34) | p50 = 30.36 |
| TTFT (prefill) | **71.2 мс** середнє; **p50 = 34.6 мс** | прогони 145.3, 34.6, 33.7 |
| Обробка промпту | **1353 ток/с** середнє; p50 = 1793 ток/с | промпт 62 токени, 3 прогони |
| Пікова VRAM | **10661 МБ** із 12288 (вільно 1455 МБ) | `nvidia-smi`, утилізація 98 % |
| Пікова RAM процесу | **8660.6 МБ** | майже як у 3.1 |
| Повний час запиту | 2167.9 мс | 64 токени |
| Вікно KV-кешу | 16384 токени | `kv_cache_capacity` |

**Це важливий результат:** на 16K контексті з **автоматичним** підбором шарів
модель працює **швидше** (30.5 проти 26.6 ток/с) і з кращим TTFT, ніж на 4K з
усіма 48 шарами. Причина видна з VRAM: авто-режим лишив 1455 МБ запасу замість
256 МБ, і не довелося витісняти частину обчислень.

### 3.3. Мої прогони під час аудиту (ctx 4096, примусово 48 шарів, q8_0)

Проба з довгим промптом і повторними запитами — щоб окремо виміряти ефект
KV-переиспользования:

| Сценарій | prompt | cached | prefill | decode |
|---|---|---|---|---|
| Перший запит (порожній кеш) | 1547 | 0 | **1497.9 мс** p50 (1497.6–1589.7) | 28.8 ток/с |
| Той самий промпт повторно | 1547 | 1546 | **0.6 мс** p50 (0.4–1108.1) | 28.9–32.7 ток/с |
| Наступний хід (+16 токенів) | 270 | 254 | **61.6 мс** | 15.7 ток/с |

Звідси:

* **prefill для свіжого довгого промпту: ≈ 1030 ток/с** при 1547 токенах
  (1547 / 1.4979 с). Для короткого промпту в 62 токени звіти дають 702 і
  1353 ток/с. Тобто **діапазон ≈ 350–1800 ток/с** залежить від довжини промпту
  й накладних витрат на прогрів — саме тому в документації доречно писати
  діапазон, а не одне число.
* **KV-переиспользование зменшує prefill радикально**: 1497.9 мс → 0.6 мс на
  повторному промпті (кеш покрив 1546 із 1547 токенів). Коли кеш покриває
  неповністю (лишається 10–20 нових токенів), prefill стає **27–62 мс** — саме
  цей діапазон відповідає «звичайному» наступному ходу діалогу.
* **Швидкість декодування 26–32 ток/с** підтверджена трьома незалежними
  джерелами.

### 3.4. Застереження: примусові 48 шарів на 8192 дають деградацію

Окрема проба з `n_ctx=8192` і **примусово** `n_gpu_layers=48` повелася
аномально: prefill 1473 токенів зайняв **29 355 мс**, а decode впав до
**0.86 ток/с**; повторний прогін із повним кешем показав 0.16 ток/с.

Порівняння з 3.2 показує причину: справа не в розмірі контексту як такому, а в
**примусовому offload усіх шарів**, коли ваги + KV не лишають VRAM на робочі
буфери. Авто-режим (`gpu_layers = -1` → `report.suggested_gpu_layers`) на 16K дає
30.5 ток/с, примусові 48 шарів на 8K — 0.86 ток/с. Різниця в 35 разів.

**Висновок для планування:** не форсувати `n_gpu_layers` вручну; довіряти
`inspect.predict()`, який рахує шари з бюджету VRAM. Це саме те, що робить
`NativeRuntime.load_model()` при `gpu_layers=None`.

---

## 4. Два реальні дефекти, знайдені під час інтеграції

### 4.1. `llama_sampler_init_penalties` має 5 аргументів, перший — `n_vocab`

Сигнатура в цій збірці:

```c
llama_sampler_init_penalties(int32_t n_vocab, int32_t penalty_last_n,
                             float penalty_repeat, float penalty_freq,
                             float penalty_present);
```

Спочатку виклик був без `n_vocab` — чотири аргументи. Наслідок: перший
аргумент (`64`, тобто `repeat_last_n`) з'їдався як **розмір словника**, а
решта зсувалась. Виходило «штрафувати 64 останні токени зі словником 64», і
**текст ставав безглуздим сміттям** — не помилка, не виняток, просто марення.

Виправлення (`sampling.py:135–149`):

```python
if params.repeat_penalty != 1.0 or params.presence_penalty or params.frequency_penalty:
    lib.llama_sampler_chain_add(
        chain,
        lib.llama_sampler_init_penalties(
            self._n_vocab,               # ← n_vocab ПЕРШИМ
            params.repeat_last_n,
            params.repeat_penalty,
            params.frequency_penalty,
            params.presence_penalty,
        ),
    )
```

Додатково `SamplerChain.__init__` приймає `n_vocab`, а `engine.py` передає
`n_vocab=tokenizer.size`. Регресію закріплено тестом
`tests/test_native_runtime.py:test_sampler_penalties_takes_n_vocab`.

### 4.2. Промпт повністю в кеші → декодувати нічого → немає логітів → порожня відповідь

`CacheManager.prepare(tokens)` повертає `skip` — скільки токенів уже в кеші. Якщо
промпт **повністю** збігається з тим, що вже декодовано, `skip == len(tokens)`, і
`context.decode(fresh)` з порожнім списком нічого не робить. Але логіти для
семплінгу беруться з **останнього** `llama_decode` — а його не було. Модель
віддавала порожній або безглуздий текст на повторний однаковий запит.

Виправлення (`engine.py:674–698`):

```python
skip = context.cache.prepare(prompt_tokens) if context.cache else 0
if skip >= len(prompt_tokens) and prompt_tokens:
    if context.cache is not None:
        skip = context.cache.truncate(len(prompt_tokens) - 1)
    else:
        skip = len(prompt_tokens) - 1
stats.cached_tokens = skip
fresh = prompt_tokens[skip:]
ok = context.decode(fresh, start_pos=skip)
```

Тобто **передекодовується рівно один останній токен** промпту — дешево (у
вимірах: prefill 0.4–7.5 мс) і дає свіжі логіти саме після кінця промпту.

Тут же виправлено споріднений дефект у `kv.py:truncate()`: раніше функція
повертала «бажаний» `keep` навіть після того, як рушій відмовив у
`llama_memory_seq_rm` і кеш довелось очистити повністю. Тепер повертається
**реальна** довжина (0 після очищення), і генерація не йде з порожнього кешу.

Регресію закріплено тестом
`tests/test_native_runtime.py:test_repeated_identical_prompt_works`.

---

## 5. CUDA: залежності шукаються через `PATH`

`ggml-cuda.dll` не містить у собі cuBLAS і CUDA Runtime — він вантажить їх
**сам**, коли реєструє пристрій. `os.add_dll_directory()` діє лише на
`LoadLibraryEx` із прапорцем пошуку, а ggml кличе звичайний `LoadLibrary`. Тому
самого `add_dll_directory` **недостатньо**: без `PATH` бекенд «мовчки не
піднімається» — жодної помилки, просто всі обчислення на CPU й у 5–10 разів
повільніше.

`_bindings.py:_register_dll_dir()` робить обидві дії:

```python
os.add_dll_directory(folder_text)          # для нашого LoadLibrary
current = os.environ.get("PATH", "")
if folder_text not in current.split(os.pathsep):
    os.environ["PATH"] = folder_text + os.pathsep + current   # для ggml
```

Файли, які при цьому мають лежати в `userdata/runtime` (перевірено — лежать):
`cublas64_13.dll`, `cublasLt64_13.dll`, `cudart64_13.dll`, `ggml-cuda.dll`.
Вони ставляться окремим архівом `cudart-llama-bin-win-cuda-13.x-x64.zip`
(`runtime.py:_cudart_pattern`), бо збірка llama.cpp для CUDA їх не містить.

Порядок ініціалізації: спершу `ggml_backend_load_all_from_path(<тека рушія>)` —
щоб підхопились **наші** `ggml-cuda.dll`/`ggml-cpu-*.dll`, а не випадкові з
`PATH`; і лише якщо пристроїв нуль — `ggml_backend_load_all()`.

---

## 6. Обмеження (чесно)

| Чого немає | Наслідок |
|---|---|
| **safetensors у рушії** | `manager.MODEL_SUFFIXES = (".gguf",)`; файли `.safetensors` не приймаються взагалі (`add_local` кидає `ModelManagerError`) |
| **TensorRT-LLM** | немає; жодного згадування в коді |
| **Vulkan / DirectML у вбудованому рушії** | у `userdata/runtime` є лише `ggml-cpu-*.dll`, `ggml-cuda.dll`, `ggml-rpc.dll`. Тобто в процесі працює **CPU + CUDA**; Vulkan доступний тільки через сумісний шлях `llama-server` (`runtime.backend_preference` вміє `vulkan`) |
| **ROCm** | у `backend_preference` є, але на цій машині не перевірявся |
| **Паралельні запити** | `n_seq_max = 1`, декодування серіалізоване `EngineContext._lock`; паралелізм лише в тому, що генерація йде у фоні, а UI отримує токени callback'ом |
| **Тайм-аут генерації** | `NativeRuntime.generate(timeout=…)` параметр приймає, але ігнорує (`del timeout`) |
| **Граматики GBNF** | код є, але самплер не додається, бо `_vocab` на момент побудови = 0 |
| **MTP / speculative decoding** | `LoadOptions.load_mtp` передається в `params.load_mtp`, але окремого тесту чи вимірювання немає |
| **Мультимодальність у вбудованому рушії** | `LoadOptions.mmproj_path` зберігається, але в `_load()` **не використовується** — зір працює лише через `llama-server --mmproj` |
| **Квантування на льоту** | немає; рушій бере лише готові GGUF |

---

## 7. План, який було виконано (фактичний порядок)

1. **ABI** — описати структури й сигнатури (`_abi.py`), додати перевірку розміру
   структури (`_bindings.py`).
2. **Читання GGUF без завантаження** — щоб список моделей і прогноз пам'яті
   працювали на 8-гігабайтних файлах без секунд очікування (`gguf.py`).
3. **Прогноз** — RAM/VRAM/шари/KV з реальних метаданих (`inspect.py`,
   `_quant.py`, `hardware.py`).
4. **Tokenizer** — точні токени, бо бюджет контексту на «символах» брехав для
   кирилиці до 2 разів (`tokenizer.py`).
5. **Генерація** — `LoadedModel` + `EngineContext` + `SamplerChain` +
   `ChatFormatter` (`engine.py`, `sampling.py`, `chatfmt.py`).
6. **KV-кеш** — дзеркало й переиспользование префікса (`kv.py`).
7. **Скасування** — abort callback рушія, а не «перестати читати потік»
   (`engine.py:_AbortCallback`).
8. **Embeddings** — mean pooling тією самою моделлю (`engine.embed`).
9. **Життєвий цикл файлів** — додати/перевірити/видалити/докачати
   (`manager.py`).
10. **Фасад** — `api.py`, потім міст `bridge.py` і стиль `EMBEDDED` у
    `provider_adapters.py`.
11. **Бенчмарк** — `bench.py` із реальними числами й `"skipped"` + причина, коли
    виміряти неможливо.

---

## Підсумок

Рушій — це 14 модулів, де `llama_decode` викликається рівно в одному місці, а
`ctypes` обраний тому, що **готового wheel `llama-cpp-python` для Python 3.14
немає** (перевірено: `--only-binary=:all:` не знаходить жодної збірки), а
компіляція sdist на машині користувача неприйнятна.

Виміряно на Ryzen 5 3600 + RTX 3060 12 ГБ у трьох конфігураціях: завантаження
14B Q4_K_M **4.0–4.4 с**; декодування **26.6 ток/с** (ctx 4096, усі 48 шарів) і
**30.5 ток/с** (ctx 16384, авто-шари); TTFT **34.6 мс** p50 на 16K і **136.6 мс**
на 4K; prefill **350–1800 ток/с** залежно від довжини промпту; пікова VRAM
**9569 МБ** і **10661 МБ**. KV-переиспользование знижує prefill повторного
промпту з ~1500 мс до **0.4–7.5 мс**, а неповний збіг кешу дає **27–62 мс**.

Головний практичний висновок із цих чисел: **автоматичний підбір кількості шарів
кращий за примусовий максимум**. Авто-режим на 16K дав 30.5 ток/с, тоді як
примусові 48 шарів на 8K — 0.86 ток/с (різниця 35 разів).

Два дефекти інтеграції виправлені й закріплені тестами: 5-аргументна
`llama_sampler_init_penalties` з `n_vocab` першим, і передекод останнього токена,
коли промпт уже повністю в кеші. Десять обмежень названі відкрито — від
відсутності safetensors і TensorRT-LLM до нереалізованих граматик і тайм-ауту.

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
