# Встановлення BlackChpok IDE

Покрокова інструкція для Windows. Усе нижче перевірено на цій машині
(`C:\AI\blackchpock_ai`); де щось не перевірялося — сказано прямо.

## 1. Вимоги

| Компонент | Вимога | Перевірено тут |
| --- | --- | --- |
| ОС | Windows (64-біт, x64) | Windows, `platform.machine()` = `AMD64` |
| Python | **3.11 або новіший** | **3.14.7** (`.venv`) |
| tkinter | входить у Python (галочка «tcl/tk» у інсталяторі) | є |
| Диск | місце під рушій (~1 ГБ) і моделі (4–20 ГБ кожна) | — |
| GPU | не обов'язковий; CUDA прискорює | NVIDIA RTX 3060 12 ГБ |
| RAM | 8 ГБ мінімум, 16+ бажано, 32+ для 14B | 64 ГБ |

Версія Python у самому проєкті не перевіряється кодом — `requirements.txt`
її не фіксує, README каже «Python 3.11 або новіший. На цій машині сервер
іде з `.venv` (зараз Python 3.14)». Тобто 3.14 — це **фактично перевірена**
версія, а 3.11+ — заявлена вимога.

## 2. Отримати код і створити оточення

```powershell
cd C:\AI\blackchpock_ai
.\install.bat
```

Що робить `install.bat`:

1. `py -m venv .venv` (або `python -m venv .venv`, якщо `py` немає);
2. перевіряє, що `.venv\Scripts\python.exe` існує — інакше підказка
   «потрібен Python 3.11+ з python.org (галочка "Add to PATH" і "tcl/tk")»;
3. `pip install --upgrade pip`; 4. `pip install -r requirements.txt`;
5. `python main.py --selftest` — консольна самоперевірка без вікна.

Якщо крок 4 упав, `install.bat` не зупиняється: пише, що IDE працює й без
цих залежностей (вони потрібні лише `server.py` — MCP-серверу).

Вручну — те саме:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`requirements.txt` (обов'язкові): `mcp[cli]>=2.0.0,<3.0.0`,
`pypdf>=5.0.0,<7.0.0`, `python-docx>=1.1.0,<2.0.0`, `openai>=1.40.0`,
`ollama>=0.3.0`, `pymupdf>=1.24.0`, `pikepdf>=9.0.0`. Опційні
(закоментовані): `numpy` (векторний пошук RAG, без нього — ключові слова),
`pillow` (скріншоти, зображення в чаті), `pygments` (підсвітка; є власна
простіша). **Власний рушій BLACKCHPOK не потребує жодного pip-пакета**: він
працює на `ctypes` зі стандартної бібліотеки плюс `sqlite3`, який входить у
Python.

## 3. Звідки береться llama.cpp

Є **два** шляхи, і їх варто не плутати.

### 3.1. Власний рушій (те, що описують інші документи)

Потрібні `llama.dll` і сусідні `ggml*.dll` у теці рушія. Тека —
`config.find_data_dir("runtime", marker="llama-server.exe")`, тобто перша з
таких, де вже щось є:

```
<app_data>/runtime        # %APPDATA%\BlackChpokIDE\runtime
<тека програми>/userdata/runtime
```

На цій машині:

```
C:\AI\blackchpock_ai\userdata\runtime\
    llama.dll (3835392 байт), ggml.dll, ggml-base.dll, ggml-cuda.dll,
    ggml-cpu-*.dll (15 варіантів), cublas64_13.dll, cublasLt64_13.dll,
    cudart64_13.dll, libomp.dll
    version.txt → b12129
    backend.txt → cuda
```

**IDE ставить цю збірку сама** через `runtime.py`:

* `latest_runtime_releases()` тягне останні релізи
  `https://api.github.com/repos/ggml-org/llama.cpp/releases`;
* `backend_preference(profile)` обирає порядок бекендів: `cuda` (якщо
  `has_cuda`), `rocm`, `vulkan` (якщо є будь-який GPU), `cpu`. Без профілю
  заліза — `["vulkan", "cpu"]`, на ARM — `["cpu"]`;
* `_asset_patterns()` шукає `bin-win-cpu-x64.zip`,
  `bin-win-cuda-13.4-x64.zip` / `bin-win-cuda-12.4-x64.zip`,
  `bin-win-rocm-*-x64.zip`, `bin-win-vulkan-x64.zip`; для CUDA додатково
  качається `cudart-llama-bin-win-cuda-<вер>-x64.zip` (там
  `cublas64_*.dll` і `cudart64_*.dll`);
* `EngineInstall` качає zip у теку рушія, розпаковує (з захистом від path
  traversal), видаляє zip, піднімає вміст вкладеної теки нагору й пише
  `version.txt` і `backend.txt`.

```python
from blackchpok_ide import hardware, runtime

job = runtime.EngineInstall(profile=hardware.detect(), on_status=print)
if not job.run_blocking():
    print("Помилка:", job.error)
print("Рушій:", job.installed_path)
```

У інтерфейсі це роблять: **Хаб моделей** → кнопка «Встановити рушій
llama.cpp» (`ModelHubPanel.install_engine()`) і **Майстер налаштування**
(`FirstRunWizard._work()`, етап «Встановлюю рушій llama.cpp (один раз)…»).

### 3.2. Сумісний `llama-server` (альтернативний шлях)

Той самий архів містить `llama-server.exe`. Якщо в налаштуваннях вимкнено
`engine.native`, IDE піднімає `llama-server` на вільному порту
(`LocalServer`, `--jinja --no-webui --api-key local`) і працює через HTTP.
Це не те саме, що власний рушій: там модель живе в окремому процесі.

## 4. Де лежать моделі

`model_hub.models_dir()` = `config.find_data_dir("models", marker=".gguf")`
— перша тека з `*.gguf` серед `<app_data>\models`,
`<тека програми>\userdata\models`, `<тека програми>\models`.

На цій машині — `C:\AI\blackchpock_ai\userdata\models`:

```
qwen2.5-coder-14b-instruct-q4_k_m.gguf   8 988 110 272 байт
Qwen3VL-8B-Instruct-Q4_K_M.gguf          5 027 784 800
Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf       1 929 901 056
mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf   1 338 428 128
mmproj-Qwen3VL-8B-Instruct-F16.gguf      1 159 029 824
Qwen3VL-32B-Instruct-Q4_K_M.gguf.part      990 904 320   # незавершене
```

Модель можна покласти туди вручну (файл `.gguf`) або завантажити через
Хаб моделей / `NativeRuntime.download_model()`.

## 5. Перший запуск

```powershell
.\run_ide.bat
```

`run_ide.bat`: якщо `.venv` немає — викликає `install.bat`; бере перший
аргумент як робочу теку проєкту (типово — поточна); запускає
`.venv\Scripts\python.exe main.py "<WORKSPACE>"`. Еквівалент напряму —
`.\.venv\Scripts\python.exe main.py "C:\AI\blackchpock_ai"`; ще є
`main.py --version` (назва й версія) і `main.py --selftest` (перевірка без
вікна).

Що відбувається далі:

1. Стартовий екран: поле запиту, вибір теки проєкту (обов'язковий).
2. У фоні — визначення заліза й авто-підйом локальної моделі: якщо
   `settings.engine.native = True`, `_autostart_native_model()` вантажить
   модель у **власний** рушій; інакше — піднімає `llama-server`.
3. Панелі «AI Runtime» і «NEUROMESH Пам'ять» доступні з налаштувань
   (вкладка «Розділи») або через `show_side("runtime")` / `("neuromesh")`.

## 6. Як вибрати власний рушій у налаштуваннях

**Налаштування → вкладка «AI Runtime»** (`SettingsDialog._runtime_tab`):

| Елемент | Що робить |
| --- | --- |
| «Модель для рушія» (Combobox) + «Список» | список локальних моделей через `bridge.list_models()`; кнопка перечитує його |
| «Контекст (0 = авто)» (Spinbox 0…131072, крок 1024) | `settings.engine.ctx_size`; 0 = авто за метаданими |
| «Шарів на GPU (-1 = авто)» (Spinbox -1…999) | `settings.engine.native_gpu_layers` |
| «Тип KV-кешу» (Combobox: авто, q8_0, q4_0, f16, bf16) | `settings.engine.native_cache_type`; «авто» → `""` |
| Прапорець «Використовувати власний рушій для чату (не llama-server)» | `settings.engine.native` |
| «Перевірити залізо» | `runtime.hardware(refresh=True)` + `runtime.inspect_model(модель)` у журнал |
| «Завантажити у рушій» | `bridge.runtime().load_model(модель, ctx=…)` у фоновому потоці |
| «Вивантажити» | `bridge.unload()` |
| «Бенчмарк» | `runtime.benchmark_model(runs=1, max_tokens=32)` |
| «Панель AI Runtime» | закриває діалог і відкриває бічну панель `runtime` |

Після відкриття вкладки `after(120, _runtime_auto_probe)` показує стан
рушія: `llama.cpp <версія> · <пристрої>` або «Рушій не встановлено: …».

Збереження (`_save`): `native_model`, `native_gpu_layers` (обрізано до
−1…999), `native_cache_type` (`""` для «авто»), `ctx_size` (2 048…131 072).
Пріоритет у `ctx_size` — за полем вкладки «AI Runtime», бо воно стосується
саме вбудованого рушія.

**Важливо:** коли модель завантажується, `main_window._on_native_model()`
перемикає весь чат на вбудований рушій:

```python
self.settings.llm.base_url = bridge.EMBEDDED_URL      # "native://blackchpok"
self.settings.llm.model = Path(path).stem
self.settings.llm.api_key = "local"
self.settings.llm.auto_detect = False
self.settings.engine.managed = True
self.settings.engine.model_path = str(path)
```

Тобто після «Завантажити у рушій» жодних додаткових перемикачів шукати не
треба.

## 7. Перевірка, що все працює

### 7.1. Самоперевірка IDE

```powershell
.\.venv\Scripts\python.exe main.py --selftest
```

Перевіряє налаштування, інструменти (`list_dir`, `project_tree`, відмову
невідомому інструменту, блокування шляху поза текою), підсвітку,
офлайн-роутер, схеми інструментів, пошук по файлах, визначення заліза,
підбір моделі, план запуску, каталог моделей, розбір посилань HF, вибір
квантизації, **вибір збірки рушія**, шлях до рушія, розбір виклику
інструмента з тексту, доступність теки моделей. Наприкінці пише
«Самоперевірка завершена: успішно» або «помилок N» і повертає
відповідний код.

### 7.2. Рушій завантажується

```powershell
.\.venv\Scripts\python.exe -X utf8 -c "import sys;sys.path.insert(0,'.');from blackchpok_ide.native import bridge;print(bridge.runtime().library_info())"
```

Очікувано: `{"ok": True, "version": "0.9.0-dev", "path": "...\\llama.dll",
"system": "CUDA : ARCHS = ...", "supports_gpu_offload": True,
"devices": [{"name": "CUDA0", ...}, {"name": "CPU", ...}]}`.

Якщо `ok: False` — рушія немає: встановіть його (розділ 3.1).

### 7.3. Модель видно

```powershell
.\.venv\Scripts\python.exe -X utf8 -c "import sys;sys.path.insert(0,'.');from blackchpok_ide.native import bridge;d=bridge.runtime().list_models();print(d['count'], d['folder'])"
```

### 7.4. Реальна генерація

```powershell
.\.venv\Scripts\python.exe -X utf8 -c "import sys;sys.path.insert(0,'.');from blackchpok_ide.native.api import NativeRuntime;rt=NativeRuntime();print(rt.load_model('qwen2.5-coder-14b-instruct-q4_k_m.gguf',ctx=2048)['description']);print(rt.generate([{'role':'user','content':'Скажи ОК'}],params={'max_tokens':8,'temperature':0})['text'])"
```

### 7.5. Пам'ять

```powershell
.\.venv\Scripts\python.exe -X utf8 -c "import sys,json;sys.path.insert(0,'.');from blackchpok_ide.pcmm import Neuromesh;m=Neuromesh();print(json.dumps(m.status()['counts'],ensure_ascii=False));print(m.integrity()['ok']);m.close()"
```

### 7.6. Тести

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_native_runtime -v
.\.venv\Scripts\python.exe -m unittest tests.test_neuromesh -v
.\.venv\Scripts\python.exe -m unittest tests.test_bench -v
.\run_tests.bat          # усе разом (tests\run_all.py)
.\run_tests.bat --fast   # без GUI
```

`run_tests.bat` підставляє `BLACKCHPOK_HOME=.buildtmp\apphome` і
`BLACKCHPOK_NO_SAVE=1`, щоб прогін не перезаписав справжні налаштування.
Тести рушія, які потребують файлів на диску, позначені `skipUnless` і на
чистій машині **пропускаються з причиною**, а не «проходять».

## 8. Типові проблеми

| Симптом | Причина | Що робити |
| --- | --- | --- |
| `Бібліотеку llama.dll не знайдено` | тека рушія порожня | встановити рушій (розділ 3.1) |
| `Несумісна версія llama.dll: llama_model_params має N байт` | інша збірка llama.cpp | поставити сумісну за ABI збірку |
| CUDA-пристрій не з'являється | немає `cublas64_*.dll`/`cudart64_*.dll` | перевірити, що файли в теці рушія |
| `Рушій не зміг завантажити модель` | обірваний файл або брак пам'яті | `verify_integrity()`, потім менший ctx |
| Моделі немає в списку | файл `.part` або не `.gguf` | докачати (`MODEL_FORMATS.md`) |
| `nvidia-smi недоступний` | утиліти немає в `PATH` | поставити драйвер NVIDIA; рушій працює й без неї |
| Чат не перемкнувся на рушій | `_on_native_model` упав | дивитись `status` — там буде причина |
| `Пам'ять недоступна: …` | права/зайнятий файл БД | див. `NEUROMESH_RECOVERY.md` |

Журнали: `<app_data>\ide.log` (`setup_logging()` пише через
`RotatingFileHandler`, 2 МБ × 3) і `userdata\runtime\server.log` (для
`llama-server`).

## 9. Збірка .exe (необов'язково)

`.\build_exe.bat` → `dist\BlackChpok.exe` (за `IDE_README_UK.md` — один
файл, ~14 МБ); специфікація — `BlackChpokIDE.spec`. Сам процес збірки в
межах цієї документації не перевірявся.

## Підсумок

Потрібен Python 3.11+ (перевірено на 3.14.7) і `install.bat`, який створює
`.venv` і ставить `requirements.txt`; власний рушій жодних pip-пакетів не
потребує. llama.cpp IDE завантажує сама через `runtime.py` з релізів
`ggml-org/llama.cpp` у `userdata/runtime` (разом із cudart-архівом для
CUDA). Моделі лежать у `userdata/models`, запуск — `run_ide.bat`. Власний
рушій вмикається на вкладці «AI Runtime» у налаштуваннях (модель, ctx,
шари на GPU, тип KV-кешу, прапорець «Використовувати власний рушій»), і
після завантаження модель чат автоматично переходить на
`native://blackchpok`. Перевірка — `main.py --selftest`, три набори тестів
і кілька однорядкових команд із розділу 7.
