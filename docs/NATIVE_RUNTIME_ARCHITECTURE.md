# Архітектура власного рушія BLACKCHPOK

Документ описує `blackchpok_ide/native/` — рушій, який виконує GGUF-моделі
**всередині процесу IDE**, без `llama-server`, LM Studio, Ollama чи Jan.
Усе нижче звірено з кодом; де чогось немає — це сказано прямо.

## 1. Діаграма модулів

```
                        ┌──────────────────────────────┐
                        │  решта IDE (чат, панелі)     │
                        └───────────────┬──────────────┘
                                        │ (контракт OpenAI)
                        ┌───────────────▼──────────────┐
                        │ bridge.py                    │  chat() / chat_stream()
                        │ native://blackchpok          │  list_models() / ping()
                        └───────────────┬──────────────┘
                                        │
                        ┌───────────────▼──────────────┐
                        │ api.py  NativeRuntime        │  list_models, load_model,
                        │ (єдина точка входу)          │  generate, cancel_generation,
                        └───┬───────────┬──────────────┘  count_tokens, benchmark_model…
                            │           │
        ┌───────────────────▼──┐   ┌────▼──────────────────┐
        │ manager.py           │   │ engine.py             │
        │ ModelManager         │   │ NativeEngine          │
        │ ModelEntry           │   │ LoadedModel           │
        └───┬──────────────┬───┘   │ EngineContext         │
            │              │       │ StreamChunk           │
            │              │       └──┬─────┬─────┬────────┘
            │              │          │     │     │
   ┌────────▼───────┐  ┌───▼──────┐   │     │     │
   │ inspect.py     │  │ gguf.py  │   │     │     │
   │ прогноз RAM/VRAM│ │ читання  │   │     │     │
   └────────┬───────┘  │ метаданих│   │     │     │
            │          └───┬──────┘   │     │     │
            │              │          │     │     │
   ┌────────▼───────┐  ┌───▼──────┐   │     │     │
   │ _quant.py      │  │hardware  │   │     │     │
   │ назви/біти     │  │ профіль  │   │     │     │
   └────────────────┘  └──────────┘   │     │     │
                                      │     │     │
        ┌─────────────────────────────▼┐  ┌─▼───┐ │
        │ _bindings.py  LlamaLibrary   │  │kv.py│ │
        │ ctypes + перевірка ABI       │  │Cache│ │
        │ _abi.py  C-структури         │  │Mgr  │ │
        └──────────────┬───────────────┘  └─────┘ │
                       │                          │
        ┌──────────────▼───────────────┐  ┌───────▼───────────┐
        │ llama.dll + ggml*.dll        │  │ tokenizer.py      │
        │ (userdata/runtime)           │  │ sampling.py       │
        └──────────────────────────────┘  │ chatfmt.py        │
                                          │ embeddings.py     │
                                          └───────────────────┘
```

Призначення кожного модуля зафіксоване в docstring `native/__init__.py`:
`_abi` — C-структури, `_bindings` — завантаження бібліотек і пристрої,
`gguf` — метадані без завантаження ваг, `_quant` — назви quantization,
`inspect` — діагностика й прогноз, `tokenizer` — реальний tokenizer моделі,
`sampling` — семплери й стоп-послідовності, `chatfmt` — шаблони чату й
tool calling, `kv` — KV-кеш, `engine` — життєвий цикл і генерація,
`embeddings` — вектори, `manager` — файли моделей, `api` — Runtime API.

Імпорт пакета дешевий: `native/__init__.py` експортує лише
`NativeUnavailable` і `library_ready`, важкі речі вантажаться ліниво.

## 2. Життєвий цикл моделі: load → generate → unload

### load

`NativeRuntime.load_model(path_or_key, ctx=0, gpu_layers=None, …)`:

1. `ModelManager.get()` знаходить `ModelEntry` (шлях, ім'я файлу або ключ).
2. `inspect.inspect(path, profile=hardware, ctx=ctx)` читає GGUF і рахує
   `suggested_ctx`, `suggested_gpu_layers`, `suggested_batch`,
   `suggested_threads`, `kv_cache_type`, `kv_in_ram`.
3. Будується `LoadOptions` (типові значення — з метаданих, не з констант).
4. `NativeEngine.load()` під `self._lock`:

   * спершу `unload()` — попередня модель звільняється, інакше VRAM/RAM
     подвоюються;
   * `inspect.inspect()` ще раз (помилки `GgufError` лише логуються);
   * до `OOM_RETRIES = 3` спроб: `LoadedModel` + `EngineContext`; якщо
     рушій не зміг виділити пам'ять, контекст ділиться навпіл, але не
     нижче `MIN_CTX = 512`;
   * успіх → `describe()` з фактичними числами (`llama_model_n_params`,
     `llama_model_n_layer`, `llama_context_default_params`, `llama_n_ctx`).

`LoadedModel._load()` ставить `use_extra_bufts = True`, `check_tensors` з
`verify_tensors`, `load_mtp`, `load_mode` = `mmap` / `mmap_mlock` / `none`.
`EngineContext._create()` ставить `n_ctx`, `n_batch`,
`n_ubatch = min(n_ubatch, n_batch)`, `n_seq_max = 1`, потоки, `flash_attn_type`,
`type_k`/`type_v` з `_abi.GGML_TYPE`, `offload_kqv`, `embeddings`,
`no_perf = False`, створює `CacheManager(capacity=n_ctx)` і реєструє
abort callback.

Паралельно `load_model` створює `EmbeddingService` з кешем
`<тека моделей>/../neuromesh/vectors.db`.

### generate

`generate()` — блокуюча обгортка над `generate_stream()`; вона лише збирає
`text`, `stats`, `tokens`, `tool_calls`, `finish_reason`.

`generate_stream()` (генератор):

1. Перевіряє, що модель і tokenizer є.
2. `SamplingParams().normalised()`; зовнішні `stop` додаються до тих, що в
   параметрах.
3. `_prepare_prompt()`: якщо передані `tools`, у системне повідомлення
   додається текстовий опис інструментів (`chatfmt.tool_schemas_prompt`),
   потім `ChatFormatter.render(add_assistant=True)`.
4. Промпт токенізується; якщо він не влазить у `n_ctx`, лишається хвіст:
   `keep = max(1, budget - min(max_tokens, max(64, budget // 4)))`.
5. Під `context._lock`: `reset_cancel()`, `cache.prepare(prompt_tokens)`
   дає `skip`, декодується тільки `prompt_tokens[skip:]`.
6. Цикл `for _ in range(settings.max_tokens)`: `chain.sample()`,
   перевірка `is_eog()`, `StopMatcher`, декодування одного токена,
   `cache.committed([token])`.
7. У `finally` — `decode_ms` і `chain.free()`; останній `StreamChunk(done=True)`
   віддає всю статистику.

Окремий випадок: якщо `skip >= len(prompt_tokens)` (промпт повністю в кеші),
кеш ріжеться до `len(prompt_tokens) - 1`, щоб отримати свіжі логіти —
інакше модель віддавала порожню відповідь.

### unload

`NativeEngine.unload()` під тим самим `_lock`: `EngineContext.free()`
(`llama_free`), `LoadedModel.free()` (`llama_model_free`), скидання
`model`/`context`/`_formatter`, `gc.collect()`. `shut_down()` у Runtime API
викликає саме це.

`switch_model()` = `unload()` + `load_model()`.

## 3. Потоки й блокування

| Об'єкт | Захист | Що серіалізує |
| --- | --- | --- |
| `LlamaLibrary._lock` (клас) | `threading.Lock` | створення єдиного екземпляра бібліотеки |
| `NativeEngine._lock` | `RLock` | `load`, `unload` — життєвий цикл |
| `EngineContext._lock` | `RLock` | кожне декодування й `embed` |
| `CacheManager._lock` | `RLock` | дзеркало KV-кешу |
| `Tokenizer._lock` | `RLock` | буфери `llama_tokenize`/`token_to_piece` |
| `ModelManager._lock` | `RLock` | кеш списку моделей |
| `NativeRuntime._lock` | `RLock` | лічильник `_pending`, історія запитів |

Практичні наслідки:

* Генерація може йти у фоновому потоці, а UI малює токени через callback
  (`on_text`) — tkinter при цьому не блокується; панелі передають дані через
  `queue` + `after`.
* Два одночасні декодування в одному контексті неможливі: другий потік
  чекає на `context._lock`.
* `NativeRuntime` тримає лічильник `_pending`; при `_pending >= MAX_PENDING`
  (8) кидається `RuntimeBusy` з проханням зачекати.
* Журнал запитів (`REQUEST`-історія, останні 200) поповнюється **лише при
  помилці** `EngineError`: у `generate`/`generate_stream` `_record()`
  викликається тільки з `except`. Успішні запити в цю історію не пишуться —
  тому панель показує лише останню *помилку*, а не останній запит загалом.

## 4. Чому один контекст на процес

1. `LlamaLibrary` — синглтон (`_instance`): `llama_backend_init` глобальний,
   а повторне завантаження DLL у той самий процес Windows не звільняє
   раніше виділену пам'ять.
2. `NativeEngine` має рівно одне поле `model` і одне `context`; `load()`
   завжди спершу вивантажує попередню модель.
3. `EngineContext` створюється з `n_seq_max = 1` — паралельні послідовності
   в одному контексті не використовуються.
4. Міст (`bridge`) тримає один екземпляр `NativeRuntime`; `main_window`
   явно викликає `native_bridge.set_runtime(self.native_runtime)`, бо другий
   екземпляр означав би дві копії 14B-моделі у VRAM (~9 ГБ кожна) і OOM.

Наслідок: «паралельність» тут — це черга запитів, а не паралельне
декодування. Паралелізм обчислень дає сам llama.cpp усередині одного
`llama_decode` (`n_threads`, `n_threads_batch`, CUDA-шари).

## 5. Скасування через abort callback

`EngineContext` має `threading.Event` `_cancel` і прапорець `_aborted`.
`cancel()` лише виставляє подію: перервати `llama_decode`, який уже
виконується, з Python неможливо.

Тому в контекст ставиться колбек рушія:

```python
ctx_params = lib.llama_context_default_params()
...
lib.llama_set_abort_callback(handle, self._abort_cb.pointer, None)
```

`_AbortCallback` будує `ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p)`;
трамплін повертає `bool(context.cancelled)`, а на будь-який виняток —
`True` (у C не можна падати). Посилання на C-функцію зберігається в
`self._abort_cb`, інакше збирач сміття звільнив би її й рушій викликав би
звільнену пам'ять.

Ланцюжок скасування:

1. `NativeRuntime.cancel_generation()` → `context.cancel()`.
2. У циклі генерації `should_stop()` (якщо переданий) теж викликає
   `context.cancel()`.
3. `llama_decode` повертає `_abi.DECODE_ABORTED` (= 2).
4. `_decode_chunk()` ставить `_aborted = True` і повертає `False`.
5. `generate_stream` виставляє `stats.cancelled = True`,
   `finish_reason = "cancelled"` і віддає `StreamChunk(done=True...)`.

Важливо: `stats.generated_tokens` рахує **фактично згенеровані** токени, тому
скасування справді зменшує це число (це перевіряє
`tests/test_native_runtime.py::TestEngineGeneration::test_cancel_stops_generation`).

## 6. Streaming

`StreamChunk` — `text`, `reasoning`, `done`, `stats`, `finish_reason`,
`tokens`, `tool_calls`. Проміжні чанки несуть лише `text`, останній —
`done=True` зі статистикою.

`StopMatcher` (див. `sampling.py`) тримає хвіст довжиною в найдовший стоп,
тому службові маркери (`<|im_end|>` тощо) не потрапляють у відповідь, а
легітимний текст, який лише починається так само, не «з'їдається». Залишок
віддається в кінці (`flush()`), якщо генерація не зупинилась стопом.

`Runtime API` загортає чанки у словники: проміжний —
`{"done": False, "text": ..., "reasoning": ...}`, фінальний —
`{"done": True, "finish_reason": ..., "stats": ..., "tool_calls": ..., "tokens": ...}`.

`bridge.chat_stream()` додатково віддає текст через `on_text` і повертає
відповідь у форматі OpenAI (`choices[0].message`, `usage`).

## 7. Чого тут немає

* Немає HTTP-сервера й портів: усе в процесі IDE (`llama-server` — окремий,
  сумісний шлях, див. `docs/INSTALLATION.md`).
* Немає паралельного декодування кількох запитів у одному контексті.
* Немає мультимодального (зорового) інференсу у власному рушії:
  `LoadOptions.mmproj_path` зберігається й повертається в `to_dict()`, але
  `engine.py` його не використовує (немає викликів `mtmd_*`). `--mmproj`
  передається лише в `runtime.ServerConfig` для `llama-server`.
* Немає тайм-аутів генерації: параметр `timeout` у `generate()` приймається,
  але всередині явно ігнорується (`del timeout` — «тайм-аут тримає виклик»).

## Підсумок

Рушій — це ctypes-обгортка над `llama.dll` у процесі IDE: `_bindings`
перевіряє ABI, `engine` тримає одну модель і один контекст (`n_seq_max = 1`),
декодування серіалізоване `RLock`, скасування йде через справжній abort
callback рушія (`DECODE_ABORTED = 2`), а стрімінг — це генератор
`generate_stream()`, де `StopMatcher` прибирає службові маркери. Генерація
виконується у фонових потоках панелей, а не в потоці tkinter.
