# GPU-бекенд: пристрої, offload, CUDA, обмеження

Документ описує, як власний рушій BLACKCHPOK визначає GPU, скільки шарів
віддає у відеопам'ять, звідки бере VRAM-резерв і що буде, якщо GPU немає.
Все звірено з кодом `blackchpok_ide/native/`, `hardware.py`, `runtime.py`.

## 1. Як визначаються пристрої: `ggml_backend_dev_*`

`_bindings.py` описує сигнатури ggml-функцій (`_GGML_SIGNATURES`):

| Функція | Сигнатура (ctypes) |
| --- | --- |
| `ggml_backend_load_all` | `()` |
| `ggml_backend_load_all_from_path` | `(c_char_p)` |
| `ggml_backend_dev_count` | `→ c_size_t` |
| `ggml_backend_dev_get` | `(c_size_t) → c_void_p` |
| `ggml_backend_dev_name` | `(c_void_p) → c_char_p` |
| `ggml_backend_dev_description` | `(c_void_p) → c_char_p` |
| `ggml_backend_dev_type` | `(c_void_p) → c_int32` |
| `ggml_backend_dev_memory` | `(c_void_p, size_t*, size_t*)` |

Порядок ініціалізації — `LlamaLibrary.backend_init()`:

1. спершу `ggml_backend_load_all_from_path(<тека рушія>)` — щоб підхопились
   саме наші `ggml-cuda.dll` і `ggml-cpu-*.dll`, а не випадкові з `PATH`;
2. якщо `ggml_backend_dev_count() == 0` — виклик `ggml_backend_load_all()`;
3. `_probe_devices()` перебирає індекси `0..count-1`, читає ім'я, опис, тип
   і пам'ять (`memory_free`, `memory_total`), формує `BackendDevice`;
4. `llama_backend_init()`.

Тип пристрою перекладається через `_abi.DEVICE_TYPE`:
`{0: "cpu", 1: "gpu", 2: "igpu", 3: "accel", 4: "meta"}`.
Невідомий код стає `"unknown"`.

`BackendDevice.to_dict()` віддає `index`, `name`, `description`, `kind`,
`memory_free_mb`, `memory_total_mb` (ділення на 1048576).

`gpu_devices` = пристрої з `kind` у `{"gpu", "igpu", "accel"}`.
`supports_gpu_offload` = значення `llama_supports_gpu_offload()`, а якщо
функції немає — просто «чи є хоч один GPU-пристрій».

Фактичний результат на цій машині (`bridge.runtime().library_info()`):

```json
{"ok": true, "version": "0.9.0-dev",
 "path": "C:\\AI\\blackchpock_ai\\userdata\\runtime\\llama.dll",
 "supports_gpu_offload": true,
 "devices": [
   {"index": 0, "name": "CUDA0", "description": "NVIDIA GeForce RTX 3060",
    "kind": "gpu", "memory_free_mb": 11255.0, "memory_total_mb": 12287.4},
   {"index": 1, "name": "CPU", "description": "AMD Ryzen 5 3600 6-Core Processor",
    "kind": "cpu", "memory_free_mb": 45444.3, "memory_total_mb": 65461.1}
 ]}
```

`llama_print_system_info()` для цієї збірки повертає:
`CUDA : ARCHS = 750,800,860,890,900,1200,1210 | USE_GRAPHS = 1 |
FA_QUANTS = q4_0-q4_0,q8_0-q8_0,f16-f16,bf16-bf16 | CPU : … AVX2 = 1 …`.

## 2. Як ставиться `n_gpu_layers`

Значення потрапляє у `llama_model_params.n_gpu_layers` у
`LoadedModel._load()`:

```python
params = lib.llama_model_default_params()
params.n_gpu_layers = int(self.options.n_gpu_layers)
```

Звідки воно береться:

* `NativeRuntime.load_model(..., gpu_layers=None)` — тоді використовується
  `report.suggested_gpu_layers` з `inspect.predict()`;
* явне число — використовується як є (`gpu_layers=0` означає «лише CPU»);
* панель «AI Runtime» передає поле «шарів на GPU» (порожнє = `None`);
* вкладка налаштувань зберігає `settings.engine.native_gpu_layers`
  (`-1` = авто), але `main_window._autostart_native_model()` викликає
  `load_model(..., gpu_layers=None)` — тобто на автозапуску використовується
  прогноз з метаданих, а не збережене число.

Значення `999` (або будь-яке ≥ кількості шарів) означає «усі шари на GPU»:
так робить `hardware.fit()` для режиму `gpu`.

## 3. Частковий offload

`inspect.predict()` вирішує, скільки шарів покласти на GPU:

```python
vram_budget = max(0.0, (profile.vram_gb or 0.0) - VRAM_RESERVE_GB)
```

Далі три гілки:

1. `vram_budget <= 0` → `fits = "cpu"`, `suggested_gpu_layers = 0`;
2. `weights_gb + kv_gb + overhead_gb <= vram_budget` → `fits = "gpu"`,
   `suggested_gpu_layers = layer_count` (або `999`, якщо шарів у метаданих
   немає);
3. інакше — `_partial_layers()`:

```python
per_layer = weights_gb / layer_count
free = vram_budget - overhead_gb - kv_gb * 0.5
layers = int(free / per_layer)          # обмежено [0, layer_count]
```

Якщо `layers >= max(4, layer_count // 3)` — режим `hybrid`; інакше, коли все
влізає в RAM, — `cpu`; якщо не влазить нікуди — `impossible`.

`kv_gb * 0.5` — свідома консервативність: половина KV-кешу лишається в
запасі (друга половина може піти в RAM або бути стиснутою).

Окремий модуль `hardware.fit()` (використовується для llama-server і для
рекомендацій) має ту саму ідею, але з іншими сталими: `CTX_LADDER`,
`MIN_CTX = 4096`, `RUNTIME_OVERHEAD_GB = 0.7` і перевага `q8_0` перед `f16`
для KV-кешу (у коментарі зафіксовано замір: 8K/16K — 32.2 проти 31.6 ток/с).

## 4. VRAM-резерв

| Стала | Значення | Де |
| --- | --- | --- |
| `inspect.VRAM_RESERVE_GB` | 1.0 ГБ | власний рушій |
| `hardware.VRAM_RESERVE_GB` | 1.0 ГБ | рекомендації |
| `inspect.RAM_RESERVE_GB` | 3.0 ГБ | власний рушій |
| `hardware.RAM_RESERVE_GB` | 3.0 ГБ | рекомендації |
| `inspect.RAM_SHARE` | 0.75 | частка RAM під модель |
| `hardware.RUNTIME_OVERHEAD_GB` | 0.7 ГБ | граф, буфери, токенізатор |

Формула бюджету RAM в `inspect.predict()`:
`ram_budget = max(0, min(ram_total - 3.0, ram_total * 0.75))`.

Резерв VRAM (1 ГБ) — це «драйвер, робочий стіл, інші застосунки». Він
віднімається **до** будь-яких розрахунків, тому `suggested_gpu_layers`
ніколи не обіцяє всю відеопам'ять.

## 5. Залежності CUDA

`ggml-cuda.dll` сама не містить CUDA runtime. `_register_dll_dir()` робить
дві речі, і саме другої достатньо для CUDA:

```python
os.add_dll_directory(folder_text)          # для LoadLibraryEx
os.environ["PATH"] = folder_text + os.pathsep + current   # для ggml
```

Коментар у коді прямо пояснює причину: `ggml` вантажить бекенди сам, тому
`cublas64_*.dll` і `cudart64_*.dll` знаходяться **через `PATH`**, а без них
CUDA-бекенд «мовчки не піднімається».

У цій інсталяції (`userdata/runtime`) лежать:
`cublas64_13.dll`, `cublasLt64_13.dll`, `cudart64_13.dll`, `ggml-cuda.dll`,
`ggml-base.dll`, `ggml.dll`, набір `ggml-cpu-*.dll` (від `sse42` до `zen4`),
`libomp.dll`.

Звідки вони беруться: `runtime.py` для бекенду `cuda` завантажує **два**
архіви — основний `llama-*-bin-win-cuda-{13.4|12.4}-x64.zip` і додатковий
`cudart-llama-bin-win-cuda-<версія>-x64.zip` (`_cudart_pattern`). Коментар:
«Збірка llama.cpp для CUDA їх не містить — без них llama-server просто не
стартує на чистій машині».

Перевірка, що CUDA справді піднялась (stderr при першому завантаженні):

```
ggml_cuda_init: found 1 CUDA devices (Total VRAM: 12287 MiB):
  Device 0: NVIDIA GeForce RTX 3060, compute capability 8.6, VMM: yes, VRAM: 12287 MiB
load_backend: loaded CUDA backend from ...\ggml-cuda.dll
load_backend: loaded CPU backend from ...\ggml-cpu-haswell.dll
```

Показати це самому:

```powershell
.\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'.'); from blackchpok_ide.native import bridge; print(bridge.runtime().library_info()['devices'])"
```

## 6. Що показує `nvidia-smi`

`NativeRuntime._nvidia_smi()` запускає:

```
nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu,driver_version --format=csv,noheader,nounits
```

Тайм-аут — 8 с, прапорець `CREATE_NO_WINDOW`, `capture_output=True`. Рядок
розбирається по комах; якщо частин менше семи — рядок пропускається.
Результат:

```python
{"name": str, "vram_total_mb": float, "vram_used_mb": float,
 "vram_free_mb": float, "utilization_percent": float,
 "temperature_c": float, "driver": str}
```

Якщо `nvidia-smi` немає, він не в `PATH` або повернув ненульовий код —
`get_gpu_status()["nvidia"]` буде `[]`, і панель напише
«GPU: nvidia-smi недоступний». Це не помилка рушія.

Приклад реального результату цієї машини (з `bench_report.json`):

```
NVIDIA GeForce RTX 3060 · 9569 / 12288 МБ · 3% · 49.91 °C · драйвер 621.01
```

Важливо: `nvidia-smi` показує **всю** зайняту VRAM на карті, а не лише нашу
модель. Тому в бенчмарку є окреме поле `vram_baseline_mb` — VRAM до
генерації.

`hardware._nvidia_gpus()` використовує коротший запит
(`name,memory.total,driver_version`) і округлює VRAM до 0.1 ГБ; якщо
`nvidia-smi` недоступний — бере дані з реєстру Windows
(`_windows_registry_gpus()`), де VRAM може бути 0.0.

## 7. CPU fallback

Кілька рівнів відступу:

1. `n_gpu_layers = 0` — усе на CPU, `ggml-cpu-*.dll` (тут —
   `ggml-cpu-haswell.dll`, обраний за інструкціями процесора).
2. `inspect.predict()` при `vram_budget <= 0` ставить `fits = "cpu"`,
   `suggested_gpu_layers = 0` і нотатку «GPU не знайдено — генерація йтиме
   на CPU».
3. `hardware.fit()` без GPU дає `LaunchPlan(gpu_layers=0, flash_attn="off",
   batch=256, cache_type="q8_0")`.
4. `main_window._autostart_local_model()`: якщо власний рушій не піднявся —
   пробує `llama-server` («не лишаємо користувача без моделі»).
5. Для OOM є ще один рівень: `NativeEngine.load()` до 3 разів ділить
   контекст навпіл (`MIN_CTX = 512`) — це допомагає й тоді, коли VRAM
   вистачило «майже».

Окремо: `count_tokens()` без завантаженої моделі повертає
`{"exact": False, "reason": "модель не завантажена…"}` — жодних «оцінок під
виглядом точності».

## 8. Обмеження

* **Tensor Cores не гарантовані.** У коді немає жодної перевірки чи
  налаштування Tensor Cores; використовується те, що зробила збірка
  llama.cpp (тут — `ARCHS = 750,800,860,890,900,1200,1210`). Твердження
  «Tensor Cores використовуються» було б вигадкою.
* **Немає Vulkan і DirectML у цій збірці.** У `userdata/runtime` немає
  `ggml-vulkan.dll`; `DirectML` не згадується в коді взагалі. `runtime.py`
  *уміє* поставити Vulkan-збірку (`backend_preference()` додає `"vulkan"`,
  якщо є GPU), але поточна інсталяція — CUDA (`backend.txt` = `cuda`).
* **Flash attention** залежить від збірки. `LoadOptions.flash_attn`
  приймає `on`/`off`/`auto` (`FLASH_ATTN = {"auto": -1, "off": 0, "on": 1}`),
  але чи справді FA працює — вирішує llama.cpp; у системній інформації цієї
  збірки є `FA_QUANTS = q4_0-q4_0,q8_0-q8_0,f16-f16,bf16-bf16`.
* **KV-кеш** може бути `f16`, `bf16`, `q8_0` (`_abi.GGML_TYPE`); `q4_0`,
  `q5_0`, `q5_1`, `q4_1` є в переліку `KV_BYTES` для прогнозу, але
  `inspect._pick_ctx()` реально обирає лише `q8_0` і `f16`.
* **Багатопристроєвість** не використовується: `split_mode`, `main_gpu`,
  `tensor_split` не задаються — беруться типові значення бібліотеки.
* **`--no-kv-offload`** (KV у RAM) є в `hardware.LaunchPlan` і
  `inspect.predict()` (`kv_in_ram`), а у власному рушії виражається через
  `offload_kqv = not report.kv_in_ram`.

## Підсумок

Пристрої визначаються через `ggml_backend_dev_*` після явного
`ggml_backend_load_all_from_path(<тека рушія>)`; `n_gpu_layers` приходить із
прогнозу `inspect.predict()` (або ставиться вручну, `0` = CPU); частковий
offload рахується як `(vram_budget − overhead − kv/2) / per_layer` з
порогом `max(4, layer_count // 3)` для режиму «гібрид»; VRAM-резерв — 1 ГБ,
RAM-резерв — 3 ГБ плюс 75 % як межа. CUDA працює лише тоді, коли
`cublas64_13.dll` і `cudart64_13.dll` знайдені через `PATH`, а реальну
зайняту VRAM показує `nvidia-smi`, не наші оцінки. Vulkan/DirectML у цій
збірці немає, Tensor Cores код не перевіряє.
