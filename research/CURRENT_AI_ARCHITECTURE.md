# Поточна архітектура AI-шару BLACKCHPOK IDE

Документ описує, **як улаштований AI-шар станом на 08.11.2026**. Усе
перевірено читанням коду; назви файлів і функцій наведені точно.

---

## 1. Два шляхи виконання моделі

IDE вміє говорити з моделлю **двома незалежними способами**, і вибір між ними
зберігається в налаштуваннях та в адресі `llm.base_url`.

### Шлях А — вбудований рушій у процесі (`native/`)

```
tkinter UI
   ↓
agent.py:Agent.step()
   ↓
llm_client.LLMClient.chat_stream()          ← style == EMBEDDED
   ↓
native/bridge.py:chat_stream()
   ↓
native/api.py:NativeRuntime
   ↓
native/engine.py:NativeEngine.generate_stream()
   ↓
llama_decode(...)   ← C-функція з llama.dll, завантаженої ctypes
```

Особливості цього шляху:

* **немає HTTP і немає другого процесу** — модель лежить у пам'яті IDE;
* `native/_bindings.py:LlamaLibrary` вантажить `llama.dll` + `ggml*.dll` і
  перевіряє ABI (розмір `llama_model_params` читається з самої бібліотеки);
* стрімінг іде callback'ами `on_text`, скасування — abort callback рушія;
* текст промпту формує **шаблон чату з GGUF** (`chatfmt.ChatFormatter`).

### Шлях Б — сумісність зі старим сервером

```
tkinter UI → agent.py → llm_client.LLMClient → urllib → HTTP
                                                          ↓
                    llama-server / LM Studio / Ollama / vLLM / хмара
```

Цей шлях **не видалено**. Він працює для:

| Провайдер | Адреса за замовчуванням | Де описано |
|---|---|---|
| Ollama | `http://127.0.0.1:11434/v1` | `providers.py:LOCAL_PROVIDERS` |
| LM Studio | `http://127.0.0.1:1234/v1` | `providers.py`, `config.LLMSettings.base_url` |
| llama.cpp (`llama-server`) | `http://127.0.0.1:8080/v1` | `providers.py`, `runtime.py:DEFAULT_PORT` |
| vLLM | `http://127.0.0.1:8000/v1` | `providers.py` |
| Anthropic | `api.anthropic.com` | `provider_adapters.py:_ANTHROPIC_ADAPTER` |
| Gemini | `generativelanguage.googleapis.com` | `provider_adapters.py:_GEMINI_ADAPTER` |
| OpenAI-сумісні хмари | будь-яка адреса | `provider_adapters.py:_OPENAI_ADAPTER` |

`runtime.py` уміє **сам поставити** `llama-server`: `EngineInstall` завантажує
архів `llama-*-bin-win-{cuda,rocm,vulkan,cpu}-*.zip` (для CUDA — ще й
`cudart-llama-bin-win-cuda-*.zip`), `LocalServer` піднімає процес на вільному
порту, `wait_ready()` чекає `/v1/models`.

### Як обирається шлях

1. `provider_adapters.detect_style(base_url)`:
   * `native://`, `inproc://`, `blackchpok://` → `EMBEDDED`;
   * `anthropic.com` → `ANTHROPIC`;
   * `generativelanguage.googleapis.com` без `/openai` → `GEMINI`;
   * решта → `OPENAI`.
2. `LLMClient.__init__` зберігає `self.style = detect_style(base_url)`.
3. У `chat()` / `chat_stream()` / `list_models()` / `ping()` є гілка
   `if self.style == EMBEDDED: return self._…_embedded(...)`.
4. `config.LLMSettings.normalise()` **не дописує `/v1`** до `native://…`
   (інакше схема губилась і стиль визначався б за шляхом).

---

## 2. Потокова схема (детально)

```
UI (chat_panel)
  │  підписка на події агента через queue
  ▼
agent.AgentRunner._ask()
  │  якщо agent_settings.stream → client.chat_stream(...)
  ▼
llm_client.LLMClient.chat_stream()
  │  style == EMBEDDED
  ▼
native.bridge.chat_stream(messages, model, tools, temperature, max_tokens,
                          on_text, on_reasoning, should_stop)
  │  _ensure_loaded(model) → NativeRuntime.load_model(...) якщо треба
  ▼
native.engine.NativeEngine.generate_stream(messages, params, tools, …)
  │
  ├─ _prepare_prompt(messages, tools)
  │     └─ якщо tools: chatfmt.tool_schemas_prompt(tools) → у system
  │     └─ ChatFormatter.render(…) → Jinja-шаблон із GGUF
  ├─ Tokenizer.encode(prompt, add_special=adds_bos)   [точні токени]
  ├─ обрізання, якщо prompt_tokens >= n_ctx
  ├─ CacheManager.prepare(prompt_tokens) → skip
  │     └─ якщо skip == len(prompt_tokens): truncate(len-1) — передекод останнього
  ├─ EngineContext.decode(fresh, start_pos=skip)      ← llama_decode
  ├─ SamplerChain(...)                                ← penalties→top_k→top_p→min_p→temp→dist
  ├─ цикл: sample → is_eog? → accept → token_text → StopMatcher.feed
  │        → yield StreamChunk(text=…)                ← сюди приходить UI
  │        → decode([token])                          ← KV поповнюється
  └─ yield StreamChunk(done=True, stats=…, tool_calls=…)
  ▼
bridge.chat_stream() → формат OpenAI: choices[0].message + usage
  ▼
LLMClient._stream_embedded() → ChatResult(content, tool_calls, finish_reason, usage)
  ▼
Agent → AgentEvent → UI
```

Ключові факти цієї схеми:

* `native/bridge.py:EMBEDDED_URL = "native://blackchpok"` — псевдо-адреса, яку
  бачить решта IDE.
* `bridge._usage()` переводить телеметрію рушія у формат `usage` OpenAI, зокрема
  `prompt_tokens_details.cached_tokens`.
* `bridge._strip_calls()` прибирає з тексту сирий JSON виклику, який уже став
  `tool_calls` — інакше користувач бачив би `{"tool": "write_file", …}`.
* `EngineContext._lock` серіалізує декодування: один контекст — один запит.

### 2.1. Важлива деталь: хто рахує токени

У цій схемі токени рахуються **двічі й по-різному**, і це варто знати:

| Хто | Як | Файл |
|---|---|---|
| рушій (обрізання промпту, статистика) | **точно**, через `llama_tokenize` | `tokenizer.py:count`, `engine.py:663–670` |
| бюджет пам'яті | **точно**, якщо рушій завантажений; інакше позначена оцінка | `pcmm/budget.py:BudgetGovernor.for_tokenizer` / `heuristic` |
| **агент** (стискання історії) | **оцінка по символах**, `кирилиця/1.6 + латиниця/3.6` | `agent.py:552–557` |
| смуга статистики контексту | **оцінка по символах**, `len/3.5` | `context_stats.py:407–415` |

Тобто в одному запиті можуть діяти три різні уявлення про кількість токенів.
Для українського тексту `agent._tokens_in` і `context_stats.estimate_tokens`
розходяться більш ніж удвічі. Деталі й план виправлення —
`research/FULL_PROJECT_AUDIT.md`, розділ 5.3.

---

## 3. Конфігурація

### 3.1. `LLMSettings` (`config.py:286`)

| Поле | Типове | Призначення |
|---|---|---|
| `base_url` | `http://127.0.0.1:1234/v1` | адреса провайдера |
| `model` | `""` | назва моделі (для вбудованого — `Path(path).stem`) |
| `api_key` | `"lm-studio"` | ключ; для вбудованого ставиться `"local"` |
| `temperature` | `0.2` | |
| `max_tokens` | `2048` | обмежується 256…32000 у `normalise()` |
| `timeout` | `300` | 10…1800 с |
| `auto_detect` | `True` | автопошук сервера; для вбудованого → `False` |
| `reasoning_effort` | `"default"` | `none/low/medium/high/max` |

**Про `base_url = "native://blackchpok"`.** Це значення **не є типовим у
конфігу** — воно записується під час роботи, коли модель завантажено у власний
рушій:

```python
# main_window.py:_on_native_model()
self.settings.llm.base_url = bridge.EMBEDDED_URL      # "native://blackchpok"
self.settings.llm.model = Path(path).stem
self.settings.llm.api_key = "local"
self.settings.llm.auto_detect = False
self.settings.engine.managed = True
self.settings.engine.model_path = str(path)
```

Факт із `userdata/settings.json` на цій машині: `base_url` =
`http://127.0.0.1:8080/v1`, тобто активно **сумісний шлях**, а не вбудований.

### 3.2. `EngineSettings` (`config.py:394`)

| Поле | Типове | Що робить **насправді** |
|---|---|---|
| `managed` | `False` | чи піднято сервер нашим рушієм |
| `model_path` | `""` | GGUF, який запускали останнім |
| `port` | `0` | порт керованого сервера |
| `backend` | `""` | `cuda/rocm/vulkan/cpu` (пише `runtime.EngineInstall`) |
| `auto_start` | `True` | піднімати модель при старті |
| `gpu_layers` | `-1` | `-1` = авто (для `llama-server`) |
| `ctx_size` | `0` | 0 = авто з плану; читається в `_autostart_native_model` |
| `unload_when_idle` | `True` | для `llama-server` через `power.ModelPower` |
| `idle_unload_seconds` | `300` | те саме |
| `native` | `False` | **перемикач**: `True` → власний рушій, `False` → `llama-server` |
| `native_model` | `""` | який GGUF вантажити у власний рушій |
| `native_gpu_layers` | `-1` | **зберігається, але не читається** (див. аудит 5.2) |
| `native_cache_type` | `""` | **зберігається, але не читається** |
| `native_flash_attn` | `"auto"` | **зберігається, але не читається** |
| `native_unload_on_exit` | `True` | **зберігається, але не читається** |

### 3.3. Що саме віддається рушію при завантаженні

`NativeRuntime.load_model()` **не бере параметри з конфігу** (окрім `ctx`), а
рахує їх із метаданих GGUF і профілю заліза:

```python
report = inspect_mod.inspect(entry.path, profile=self.hardware(), ctx=ctx)
options = LoadOptions(
    n_ctx        = int(ctx or report.suggested_ctx or 4096),
    n_gpu_layers = int(report.suggested_gpu_layers if gpu_layers is None else gpu_layers),
    n_batch      = int(batch or report.suggested_batch or 512),
    n_ubatch     = int(min(batch or report.suggested_batch or 512, 512)),
    n_threads    = int(threads or report.suggested_threads or 0),
    flash_attn   = flash_attn or "auto",
    cache_type_k = cache_type or report.kv_cache_type or "f16",
    cache_type_v = cache_type or report.kv_cache_type or "f16",
    offload_kqv  = not report.kv_in_ram,
    mmproj_path  = mmproj or entry.projector,
)
```

---

## 4. Як обирається модель

Три рівні, і всі три — реальні:

1. **Автозапуск при старті** — `main_window._autostart_local_model(local_names)`:
   * якщо `settings.engine.native` → `_autostart_native_model()`;
   * модель з `engine.native_model`; якщо порожньо — **найбільший локальний
     GGUF** (`max(entries, key=lambda item: item.size_gb)`);
   * якщо власний рушій не піднявся → лог `«пробую llama-server»` і сумісний шлях.
2. **Вручну** — панель `runtime_panel.RuntimePanel` (список моделей, контекст,
   шари GPU, кнопки «Завантажити/Вивантажити/Інспекція/Бенчмарк») або
   `settings_dialog` (секція AI Runtime).
3. **Селектор моделі** — `model_selector.py`, `providers.py`; для стилю
   `EMBEDDED` список дає `bridge.list_models()` (імена файлів без `.gguf`).

Після успішного завантаження завжди викликається
`main_window._on_native_model(path)`, який перемикає `llm.base_url` на
`native://blackchpok` і підключає рушій до пам'яті
(`self.memory.attach_engine(self.native_runtime.engine)`).

---

## 5. Як обирається контекст

`native/inspect.py:predict()` — детермінований, без «магії»:

1. `vram_budget = max(0, profile.vram_gb - 1.0)` (1 ГБ лишається драйверу).
2. `ram_budget  = max(0, min(ram_total - 3.0, ram_total * 0.75))`.
3. Драбина контекстів `_ctx_candidates()`: `32768, 24576, 16384, 12288, 8192,
   6144, 4096, 2048`, обмежена тренувальним контекстом моделі.
4. `_pick_ctx()` перебирає в порядку:
   * стиснутий кеш `q8_0`, потім `f16` — **усе у VRAM**;
   * ваги у VRAM, **KV-кеш у RAM** (`offload_kqv=False`);
   * усе в RAM.
5. `kv_cache_gb()` рахує обсяг за формулою llama.cpp:
   `layers × kv_heads × head_dim × 2 × ctx × bytes_per_element`.

Результат лягає в `report.suggested_ctx`, `report.kv_cache_type`,
`report.kv_in_ram`, і саме звідти його бере `load_model()`.

Запасний шлях, якщо контекст усе одно не створюється: `NativeEngine.load()` має
`OOM_RETRIES = 3` і кожну наступну спробу зменшує контекст удвічі, але не нижче
`MIN_CTX = 512`.

---

## 6. Як обираються шари GPU

`inspect.predict()`:

* `full_vram = weights_gb + kv_gb + overhead_gb` (overhead = 0.7 ГБ,
  `RUNTIME_OVERHEAD_GB`);
* якщо `full_vram <= vram_budget` → `fits = "gpu"`, шари =
  `max(layer_count, 1)` (або `999`, якщо шарів у метаданих немає);
* інакше `_partial_layers()`: `per_layer = weights_gb / layer_count`, і
  `layers = (vram_budget - overhead - kv*0.5) / per_layer`;
* якщо шарів виходить `>= max(4, layer_count // 3)` → `fits = "hybrid"`;
* якщо ні, але все влазить у RAM → `fits = "cpu"`, шари лишаються малими;
* якщо не влазить нікуди → `fits = "impossible"` і в `notes` пише, скільки
  потрібно й скільки є.

`fits` показується людині (`ModelEntry.summary()`: `GPU/гібрид/CPU/не влізе`) і
використовується для вибору кількості шарів при автозавантаженні.

Фактичне використання VRAM при цьому **не прогнозується, а вимірюється**:
`NativeRuntime.get_gpu_status()` кличе `nvidia-smi --query-gpu=memory.used,…`.

---

## 7. Пам'ять як частина AI-шару

`main_window.__init__`:

```python
self.native_runtime = native_api.NativeRuntime()
self.memory = self._open_memory()          # Neuromesh() або None
if self.memory is not None:
    self.registry.attach_memory(self.memory)
```

* `_open_memory()` створює `pcmm.Neuromesh()` і викликає
  `service.attach_engine(self.native_runtime.engine)` — з цього моменту пам'ять
  має і вектори (`EmbeddingService`), і **реальний tokenizer** для бюджету.
* `ToolRegistry.attach_memory()` додає 12 обробників `memory_*` і їхні схеми;
  `Agent.tool_schemas()` додає їх до списку схем, які бачить модель.
* Якщо база недоступна — `_open_memory()` повертає `None`, IDE працює далі, а
  інструментів `memory_*` просто немає (агент не може викликати те, чого немає).
* Пам'ять **не залежить** від завантаженої моделі: без неї пошук лексемний, а
  `budget` чесно повертає `exact=False`.

---

## 8. Що з цього видно користувачу

| Місце в інтерфейсі | Що показує | Джерело |
|---|---|---|
| шапка (`_model_summary`) | назва моделі + «вбудований рушій · online» або «локальна · online/offline» / «хмара · …» | `main_window.py:4635–4659` |
| смуга статистики | токени, % контексту, ток/с, влучання в кеш | `context_stats.py` |
| панель AI RUNTIME | версія рушія, пристрої ggml, VRAM `nvidia-smi`, RAM процесу, KV-кеш, журнал запитів | `runtime_panel.py` |
| панель NEUROMESH | спогади, зв'язки, конфлікти, точність прогнозів, бекапи | `neuromesh_panel.py` |
| налаштування | модель, ctx, шари, тип KV, «увімкнути власний рушій» | `settings_dialog.py:844–1114` |

---

## Підсумок

AI-шар має **дві рівноправні колії виконання**: вбудований рушій у процесі
(`native/`, без HTTP і без другого процесу) і сумісний HTTP-шлях до
`llama-server`/LM Studio/Ollama/vLLM/хмари. Вибір визначає `provider_adapters.
detect_style()` за адресою; `native://blackchpok` — псевдо-адреса вбудованого
рушія, яку ставить `_on_native_model()`, а не типове значення конфігу.

Контекст, тип KV-кешу й кількість шарів на GPU **не вгадуються**: вони
рахуються з метаданих GGUF і бюджетів VRAM/RAM у `inspect.predict()`, а фактичне
споживання VRAM зчитується з `nvidia-smi`. Пам'ять NEUROMESH підключається до
того самого рушія й використовує його tokenizer для точного бюджету контексту.

Окремо названо те, що псує цю картину: **агент і смуга статистики досі рахують
токени по символах, причому двома різними формулами** (розділ 2.1). Рушій і
пам'ять рахують точно, агент — ні. Це не приховано й зафіксовано в аудиті як
перший пункт боргу.

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
