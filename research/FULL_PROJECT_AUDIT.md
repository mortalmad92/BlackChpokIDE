# BLACKCHPOK IDE — повний аудит проєкту

Документ складено **після читання коду** (не з припущень). Кожне твердження нижче
можна перевірити за названим файлом і функцією. Де щось не реалізовано — це
написано прямо.

Дата аудиту: 08.11.2026. Робоча тека: `C:\AI\blackchpock_ai`.

---

## 1. Стек

| Шар | Що використано | Підтвердження |
|---|---|---|
| Мова | Python 3.14.7 | `python --version` у цій машині; `.venv` проєкту |
| GUI | tkinter / ttk, власна тема | `theme.py` (566 р.), усі панелі — `tk.Frame` |
| Сховище | SQLite (модуль `sqlite3` зі stdlib), WAL, FTS5 | `pcmm/store.py`, `rag_engine.py`, `native/embeddings.py` |
| Інференс | `llama.cpp` як **готові DLL**, виклик через `ctypes` | `native/_bindings.py`, `native/_abi.py` |
| Мережа | `urllib.request` (без `requests`) | `llm_client.py`, `model_hub.py`, `runtime.py` |
| Пакети | сторонніх залежностей немає; усе — stdlib | імпорти в модулях: `ctypes`, `hashlib`, `struct`, `mmap`, `sqlite3`, `subprocess` |

### Чому Rust НЕ використано

Це питання виникає щоразу, бо «швидкий рушій» асоціюється з Rust. Факти:

1. **У проєкті немає жодного файлу Rust.** Пошук `*.rs` і `Cargo.toml` по всьому
   дереву `C:\AI\blackchpock_ai` не дає результатів.
2. `rustc`/`cargo` **фізично є** в `C:\Users\<user>\.cargo\bin` (rustc 1.99.1), але
   **не прописані в `PATH`**: `Get-Command cargo, rustc` нічого не знаходить.
   Тобто збірка Rust-крейта «з коробки» не запуститься.
3. Головне — **Rust тут не потрібен для результату**. `native/` не реалізує
   обчислення тензорів на Python: він лише викликає вже скомпільований
   `llama.dll` (C/C++ + CUDA) через `ctypes`. Обчислювально важка частина
   однакова в обох варіантах: і Rust-обгортка, і `ctypes`-обгортка кликали б
   той самий `llama_decode`.

Ціна Rust-варіанта: другий тулчейн у збірці, `maturin`/`pyo3`, окрема
крос-компіляція під Windows + CUDA, і неможливість оновити рушій без
перезбирання. Ціна `ctypes`-варіанта: жодної компіляції — оновлення рушія
полягає в заміні DLL у `userdata/runtime`.

Висновок: **Rust не використано не тому, що «так простіше», а тому що
`ctypes` + готовий `llama.cpp` дає той самий результат без компіляції й без
другого тулчейну.** Обмеження цього вибору названі в
`research/NATIVE_RUNTIME_PLAN.md` (розділ «Обмеження»).

---

## 2. Структура пакета `blackchpok_ide/`

101 файл `.py` у пакеті, 104 файли тестів у `tests/`.

### 2.1. Ядро інтерфейсу

| Модуль | Призначення |
|---|---|
| `main_window.py` | головне вікно, збирання всіх панелей, життєвий цикл сервісів |
| `chat_panel.py` | діалог: картки повідомлень, tool-call блоки, diff |
| `editor.py`, `tabs.py`, `file_tree.py`, `outline_panel.py` | редактор і навігація по проєкту |
| `theme.py`, `widgets.py`, `layout.py`, `adaptive.py` | тема, віджети, розкладка, адаптивні розміри |
| `nav_sidebar.py`, `header_bar.py`, `stats_bar.py`, `palette.py` | навігація, шапка, смуга статистики, палітра команд |

### 2.2. Агент і його інструменти

| Модуль | Призначення |
|---|---|
| `agent.py` | автономний агент: кроки, виклики інструментів, MCP, скіли, планування контексту |
| `agent_tools.py` | `ToolRegistry` + 36 вбудованих інструментів (`read_file`, `write_file`, `run_command`, `search_web`, `web_*`, `app_*`…) |
| `tool_router.py` | підказки, який інструмент імовірно потрібен |
| `permissions.py` | режими `read_only` / `workspace` / `full` |
| `skills.py`, `social.py` | скіли й соціальні інструменти як додаткові схеми |
| `task_planner.py`, `task_executor.py`, `queue_engine.py` | планування, виконання кроків, черга задач |
| `autonomous.py` | безперервний режим роботи |
| `deep_mode.py`, `planner.py`, `work_log.py` | глибокий режим, плани, журнал робіт |

### 2.3. Зовнішні інтеграції

| Модуль | Призначення |
|---|---|
| `mcp_client.py` | MCP-сервери через stdio: `McpClient`, `McpManager` |
| `internet.py`, `browser_panel.py`, `cdp.py` | пошук/завантаження сторінок, вбудований браузер, CDP-сесія |
| `app_control.py`, `screenshot.py` | керування застосунками й знімки вікон |
| `voice.py` | розпізнавання й озвучення |
| `rag.py` | міст до `rag_engine.LocalRAG` (SQLite FTS5 + BM25 + необов'язкові вектори) |
| `model_hub.py` | пошук/завантаження GGUF із HF/GitHub/Civitai |
| `env_setup.py`, `auto_setup.py`, `first_run.py` | перший запуск, встановлення git/node, підбір моделі |
| `web_server.py`, `live_preview.py` | локальний сайт і живий прев'ю проєкту |

### 2.4. AI-шар (те, що змінилось найбільше)

| Модуль | Призначення |
|---|---|
| `llm_client.py` | HTTP-клієнт: OpenAI, Anthropic, Gemini, стрімінг, tool_calls |
| `provider_adapters.py` | справжні протоколи провайдерів + стиль `embedded` |
| `providers.py` | список локальних/хмарних провайдерів для селектора |
| `model_caps.py` | можливості моделі за назвою (vision/reasoning/context) |
| `context_stats.py` | токени, відсоток заповнення, швидкість, влучання в кеш |
| `native/` | **власний рушій** у процесі IDE (див. нижче) |
| `pcmm/` | **пам'ять NEUROMESH** (див. нижче) |
| `bench.py` | реальні виміри рушія й пам'яті |
| `hardware.py` | профіль заліза, бюджети VRAM/RAM, план запуску |
| `runtime.py` | авто-встановлення llama.cpp і керування `llama-server` (сумісний шлях) |

### 2.5. Підсистема `native/` (14 модулів + `__init__`)

```
_abi.py        структури llama.cpp для ctypes
_bindings.py   завантаження llama.dll/ggml*.dll, перевірка ABI, пристрої
_quant.py      назви quantization → біти на вагу
gguf.py        власний читач метаданих GGUF (без завантаження ваг)
inspect.py     діагностика моделі + прогноз RAM/VRAM/шарів + цілісність
tokenizer.py   реальний tokenizer моделі (не оцінка по символах)
sampling.py    параметри семплінгу, ланцюжок семплерів, стоп-послідовності
chatfmt.py     шаблони чату моделі + текстовий адаптер tool calling
kv.py          дзеркало KV-кешу, переиспользование префікса
engine.py      життєвий цикл моделі, генерація, стрімінг, скасування, embeddings
embeddings.py  локальні вектори + кеш у SQLite
manager.py     список/інспекція/додавання/видалення/завантаження моделей
api.py         NativeRuntime — єдина точка входу для решти IDE
bridge.py      міст до LLMClient (псевдо-адреса native://blackchpok)
```

### 2.6. Підсистема `pcmm/` (7 модулів + `__init__`)

```
store.py       SQLite: WAL, міграції v1..v4, бекапи, integrity_check
models.py      Memory: типи, provenance, впевненість, зв'язки, хеші
repository.py  запис, дублікати, конфлікти, версії, консолідація
retrieval.py   гібридний пошук (lexical+semantic+graph+temporal) + прогноз
budget.py      бюджет контексту на реальних токенах моделі
service.py     Neuromesh — фасад для IDE й агента
tools.py       12 інструментів memory_* + валідація аргументів за схемою
```

---

## 3. Наявні підсистеми

* **Агент** — `agent.py:Agent`. Режими `chat|agent|code|plan|tools`, ліміт кроків
  `AgentSettings.max_steps` (типово 8), скасування, стрімінг, відновлення
  виклику інструмента з тексту (`llm_client.extract_tool_calls`).
* **Інструменти** — `agent_tools.py:ToolRegistry`, 36 вбудованих схем плюс
  динамічно додані `memory_*`, скіли, соціальні, MCP.
* **MCP** — `mcp_client.py:McpManager`: stdio-транспорт, простори імен
  `<server>.<tool>`, підняття серверів із `.mcp.json`.
* **RAG** — `rag.py:RagService` над `rag_engine.LocalRAG` (SQLite FTS5, BM25,
  необов'язкові вектори). Окремо від пам'яті NEUROMESH.
* **Чати** — `chat_store.py:ChatStore` (JSON-сховище `userdata/chats.json`),
  картки, tool-call блоки, статуси.
* **Моделі** — `model_hub.py` (пошук/завантаження GGUF) і
  `native/manager.py` (життєвий цикл файлів: додати, перевірити, перейменувати,
  видалити, докачати).
* **Рушій** — `native/` (у процесі) і `runtime.py` (зовнішній `llama-server` як
  сумісний шлях).

---

## 4. Що було ДО змін і що стало

### 4.1. Було: зовнішній `llama-server` як обов'язковий

Факти з `runtime.py`:

* `runtime.py:EngineInstall` завантажує з GitHub архів `llama-*-bin-win-*.zip`,
  розпаковує в `userdata/runtime`, пише `version.txt` і `backend.txt`.
* `runtime.py:LocalServer.start()` піднімає **окремий процес**
  `llama-server.exe --model … --port … --api-key local --jinja --no-webui`,
  `wait_ready()` опитує `/v1/models` до 300 с.
* `runtime.py:AutoLauncher` робив усе це «з коробки».
* `config.py:LLMSettings.base_url` типово `http://127.0.0.1:1234/v1` — тобто
  розрахунок був на LM Studio; `providers.py` додатково знав Ollama (11434),
  llama.cpp (8080), vLLM (8000).

Наслідки, які це створювало: обов'язковий другий процес, «сирітські» сервери й
зайняті порти, скасування генерації лише через HTTP, а tokenizer/embeddings/KV
жили поза контролем IDE.

### 4.2. Стало: вбудований рушій у процесі

* `native/_bindings.py` вантажить `llama.dll` у **власний процес** через
  `ctypes.WinDLL`; `_register_dll_dir()` додає теку рушія в `PATH`, щоб
  підхоплювались `cublas64_*.dll` і `cudart64_*.dll`.
* `native/engine.py:NativeEngine` дає `load/unload/generate/generate_stream/embed`.
* `native/api.py:NativeRuntime` — фасад: `list_models`, `inspect_model`,
  `load_model`, `generate`, `generate_stream`, `cancel_generation`, `tokenize`,
  `detokenize`, `count_tokens`, `create_embeddings`, `get_runtime_status`,
  `get_gpu_status`, `get_memory_status`, `benchmark_model`.
* `native/bridge.py` подає рушій у вигляді, який уже вміє `LLMClient`:
  `EMBEDDED_URL = "native://blackchpok"`, `chat`, `chat_stream`, `list_models`,
  `ping`.
* `provider_adapters.py` дістав стиль `EMBEDDED`; `llm_client.py` у трьох місцях
  (`chat`, `chat_stream`, `list_models`, `ping`) перенаправляє виклик у `bridge`,
  **не роблячи жодного HTTP-запиту**.
* `main_window._on_native_model(path)` перемикає налаштування:
  `llm.base_url = bridge.EMBEDDED_URL`, `llm.model = Path(path).stem`,
  `llm.api_key = "local"`, `llm.auto_detect = False`, `engine.managed = True`.
* `config.py:LLMSettings.normalise()` **більше не дописує `/v1`** до
  `native://…`, інакше стиль провайдера визначався б неправильно.

**Сумісний шлях лишився.** `main_window._autostart_local_model()` спершу пробує
власний рушій (якщо `engine.native = True`), а якщо той не піднявся — падає на
`llama-server`. Тобто LM Studio / Ollama / llama.cpp / vLLM і далі працюють
через `providers.py`.

Стан на цій машині (факт із `userdata/settings.json`): `llm.base_url =
"http://127.0.0.1:8080/v1"`, `engine.managed = true`, `engine.ctx_size = 16384`,
прапорця `native` у файлі немає → типове `False`. Отже **зараз IDE на цій машині
налаштована на сумісний шлях `llama-server`, а не на вбудований рушій** —
вбудований шлях вмикається в «Налаштування → AI Runtime».

---

## 5. Дефекти, виявлені під час аудиту

### 5.1. Виявлені й **виправлені**

| Дефект | Як виправлено | Де саме |
|---|---|---|
| Не було перевірки цілісності моделі: обірваний `.part` виглядав як готова модель | завантаження пише в `<name>.part` і перейменовує лише після `verify_integrity`; перевіряються магія GGUF, читабельність метаданих, наявність тензорів, очікуваний розмір | `native/inspect.py:verify_integrity`, `native/manager.py:download` |
| Не було видалення моделей | `manager.delete()` вимагає `confirm=True`, інакше повертає `False` і **не чіпає файл**; додатково `path.resolve().relative_to(folder.resolve())` забороняє видаляти щось поза текою моделей | `native/manager.py:delete`, `native/api.py:delete_model` |
| Не було локальних embeddings — вектори залежали від зовнішнього сервера | `NativeEngine.embed()` рахує вектори тією самою моделлю (mean pooling усіх токенів), `EmbeddingService` кешує їх у SQLite з підписом моделі | `native/engine.py:embed`, `native/embeddings.py` |
| Оцінка токенів «символів на токен» | **частково**: для вбудованого рушія є точний підрахунок `Tokenizer.count` через `llama_tokenize`; `NativeRuntime.count_tokens` повертає `exact: True` лише коли модель завантажена; бюджет пам'яті й бенчмарк користуються саме ним. **Але сам агент досі рахує по символах** — див. 5.2 | `native/tokenizer.py:count`, `native/api.py:count_tokens`, `pcmm/budget.py:BudgetGovernor.for_tokenizer` |
| Дублювання визначення «локальний/хмарний» | частково зведено: стиль визначає `provider_adapters.detect_style`, а `native://` розпізнає `bridge.is_embedded_url` | `provider_adapters.py:detect_style`, `native/bridge.py:is_embedded_url` |

### 5.2. Виявлені й **НЕ виправлені** (чесно)

| Дефект | Деталі | Де видно |
|---|---|---|
| Оцінка токенів по символах **лишилась** і навіть **подвоєна** | див. деталі нижче | `context_stats.py:407–424`, `agent.py:552–557` |
| «Локальний/хмарний» визначається **шістьма** незалежними способами | `llm_client._is_local_url` (4 маркери), `providers.LocalProvider.is_local` (завжди `True`), `providers.ModelEntry.is_local` (`kind == LOCAL`), `auto_setup._is_local_url` (7 хостів), `main_window._model_summary` (інлайн-список + окрема перевірка `native://`), `browser_panel.is_local_url` (для URL сторінок), `config.LLMSettings.normalise` (інлайн-перевірка схеми) | усі перелічені файли |
| Параметр `timeout` у `NativeRuntime.generate` не працює | у тілі стоїть `del timeout` з коментарем «тайм-аут тримає виклик»; жодного таймера немає | `native/api.py:216–242` |
| `bridge` обходить чергу й телеметрію `NativeRuntime` | `bridge.chat`/`chat_stream` кличуть `rt.engine.generate*` напряму, тому `_pending` не зростає, а `bridge.busy()` завжди `False`; `_record()` теж не спрацьовує | `native/bridge.py:99–198`, `native/api.py:487–505` |
| Граматики (GBNF) фактично не працюють | `SamplerChain._build` викликає `llama_sampler_init_grammar(self._vocab, …)`, але `_vocab` на момент побудови = 0; `attach_vocab` викликається **після** `_build`. Самплер повертає 0 і тихо не додається | `native/sampling.py:112–170`, `native/engine.py:700–703` |
| Налаштування `engine.native_gpu_layers`, `native_cache_type`, `native_flash_attn`, `native_unload_on_exit` зберігаються, але **ніде не читаються** | grep по пакету: лише оголошення в `config.py` і запис у `settings_dialog.py`. Реальні значення завжди беруться з `inspect.predict()` | `config.py:412–418`, `settings_dialog.py:1094–1114` |
| Вивантаження на простій не діє для вбудованого рушія | `power.ModelPower` працює через `server_provider`, тобто лише з `llama-server`; для `NativeRuntime` такого механізму немає (є тільки `shut_down()` при виході) | `power.py:150–201`, `main_window.py:6483` |
| Мертвий код у гарячому циклі генерації | `emitted = matcher.flush() if False else ""` — вираз, що нічого не робить | `native/engine.py:735–736` |
| Мертвий код у менеджері моделей | `if entry.is_projector: continue` далі `if not entry.is_projector:` — друга умова недосяжна | `native/manager.py:183–187` |
| Заглушка, яка ніде не викликається | `gguf._array_length()` завжди повертає 0 | `native/gguf.py:267–270` |
| `ToolCallParser` описаний, експортований — і не використовується | розбір викликів іде після повної відповіді через `extract_tool_calls` | `native/chatfmt.py:315–398`, `native/engine.py:788–802` |
| `precision_at_k` у бенчмарку — не класична Precision@K | формула `1/len(hits)` дає середнє обернених кількостей знайденого, а не частку релевантних серед перших K. Число 0.833 зі звіту = `(1+1+1+0.5+0.5+1)/6` | `bench.py:318`, `.buildtmp/bench_report.json` |
| `token_savings_share = 0.0` у звіті | при `window=4096` і шести коротких спогадах губернатор нічого не викинув, тому економії немає — метрика рахується, але показує нуль | `bench.py:330–334`, `.buildtmp/bench_report.json` |
| Сміття в теці моделей | `Qwen3VL-32B-Instruct-Q4_K_M.gguf.part` (0.92 ГБ) лежить після невдалого завантаження; `manager._scan` його не показує, бо фільтрує за `.gguf` — але місце зайняте | `userdata/models/` |

### 5.3. Оцінка токенів: точний tokenizer є, але агент ним не користується

Це найважливіший із невиправлених пунктів, тому окремо й докладно.

**Що зроблено.** `native/tokenizer.py:Tokenizer.count()` рахує токени через
`llama_tokenize` тієї самої моделі. `NativeRuntime.count_tokens()` віддає
`{"count": N, "exact": True}` — або чесно `{"exact": False, "reason": "модель не
завантажена"}`. `BudgetGovernor.for_tokenizer()` і `MemoryBenchmark` користуються
саме цим.

**Де залишилась оцінка.** Агент, який **вирішує, скільки історії лишити в
промпті**, рахує по символах — і робить це **двома різними способами**:

```python
# agent.py:552-557
@staticmethod
def _tokens_in(text: str) -> int:
    cyrillic = sum(1 for ch in text if "\u0400" <= ch <= "\u04FF")
    latin = len(text) - cyrillic
    return int(cyrillic / 1.6 + latin / 3.6) + 8

# context_stats.py:407-415
def estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / 3.5))
```

Дві формули для однієї величини: `1.6/3.6` символа на токен в агенті проти
`3.5` у статистиці. Для українського тексту різниця між ними — **понад 2 рази**.

**Наслідок.** `_estimate_tokens()` використовується в `AgentSession.trim()` і в
петлі стискання історії (`agent.py:451`, `510`), тобто саме там, де ціна помилки
найвища: занижена оцінка → рушій відмовляє з переповненням контексту; завищена →
історія ріжеться завчасно й модель «забуває» сказане.

**Чому це не виправлено в цьому аудиті.** Заміна вимагає асинхронного доступу до
tokenizer'а з потоку агента (модель може бути не завантажена, а на стисканні
історії вона може завантажуватись) і кешу на кожен рядок. Це окрема робота зі
своїми тестами, а не правка одного рядка. Тому дефект зафіксований, а не
«замазаний».

**Що треба зробити (для наступної ітерації):** `Agent` має отримати
необов'язковий `token_counter` (як це вже зроблено в `BudgetGovernor`), і
використовувати `NativeRuntime.count_tokens` коли рушій завантажений; інакше —
**одна** евристика замість двох.

---

## 6. Таблиця «вимога → стан → де реалізовано»

| Вимога | Стан | Де реалізовано |
|---|---|---|
| Працювати без LM Studio/Ollama/llama-server | **так** | `native/_bindings.py`, `native/engine.py`, `native/bridge.py` |
| Не мати другого процесу й портів | **так** для вбудованого шляху | `native/engine.py` (усе в пам'яті процесу) |
| Стрімінг відповіді | **так** | `engine.generate_stream` → `bridge.chat_stream` → `llm_client._stream_embedded` |
| Скасування зупиняє обчислення, а не лише читання | **так**, через abort callback рушія | `engine.py:395–413`, `engine.py:313` |
| Реальний підрахунок токенів | **так** через `NativeRuntime.count_tokens`; **але агент для стискання історії рахує по символах** (5.3) | `tokenizer.py:count`, `api.py:count_tokens`, `budget.py`; натомість `agent.py:552–557`, `context_stats.py:407` |
| Переиспользование KV-кешу | **так** | `native/kv.py`, `engine.py:674–698` |
| Локальні embeddings без окремої моделі | **так** (mean pooling тією самою моделлю) | `engine.py:805–868`, `embeddings.py` |
| Перевірка цілісності файлу моделі | **так** (магія, метадані, тензори, розмір) | `inspect.py:verify_integrity` |
| Видалення моделі з підтвердженням | **так** | `manager.py:delete`, `api.py:delete_model` |
| Докачка завантаження | **так** (`Range`, `.part`) | `manager.py:download` |
| Прогноз RAM/VRAM і кількості шарів | **так**, з метаданих GGUF | `inspect.py:kv_cache_gb`, `inspect.py:predict` |
| Бенчмарк із реальними числами | **так** | `bench.py:EngineBenchmark`, `engine.py:benchmark` |
| Довготривала пам'ять із походженням | **так** | `pcmm/models.py`, `pcmm/repository.py` |
| Гібридний пошук по пам'яті | **так** (BM25+FTS5, косинус, граф, час) | `pcmm/retrieval.py:Retriever` |
| Бюджет контексту на реальних токенах | **так** з моделлю, **чесно позначена оцінка** без неї | `pcmm/budget.py` |
| Інструменти `memory_*` для агента | **так**, 12 штук | `pcmm/tools.py`, `agent_tools.py:attach_memory` |
| Міграції схеми пам'яті | **так**, `user_version` 1→4 | `pcmm/store.py:MIGRATIONS` |
| Бекап/відновлення пам'яті | **так**, через SQLite Backup API | `store.py:backup`, `store.py:restore` |
| Робота без завантаженої моделі | **так**: лексемний пошук, вектори не рахуються, статус це показує | `pcmm/service.py:status`, `retrieval.py:none` |
| Тайм-аут генерації | **НІ** (параметр ігнорується) | `api.py:216–242` |
| Автовивільнення VRAM на простій для вбудованого рушія | **НІ** | `power.py` (лише `llama-server`) |
| Граматики/GBNF для структурованого виводу | **НІ** (самплер не додається) | `sampling.py:158–162` |
| Підтримка safetensors у рушії | **НІ** (тільки GGUF) | `native/manager.py:MODEL_SUFFIXES` |
| Vulkan/DirectML/TensorRT у вбудованому рушії | **НІ** (лише те, що є в збірці llama.cpp) | `native/_bindings.py:GGML_DLLS` |
| Голосове керування | **так** | `voice.py` |
| MCP-сервери | **так** | `mcp_client.py` |
| Вбудований браузер і CDP | **так** | `browser_panel.py`, `cdp.py` |

---

## 7. Підсумок

Стек: **Python 3.14 + tkinter + SQLite + ctypes поверх готових DLL llama.cpp,
без Rust** — не через спрощення, а тому що Rust-обгортка кликала б той самий
`llama_decode`, вимагаючи другого тулчейну й компіляції.

Головна зміна архітектури: обов'язковий зовнішній `llama-server` замінено
**вбудованим рушієм у процесі IDE** (`native/`), а сумісний шлях залишено для
LM Studio / Ollama / llama.cpp / vLLM. Пам'ять `pcmm/` додано як окрему
підсистему з 12 інструментами агента.

Аудит підтвердив **13 невиправлених дефектів** (розділи 5.2 і 5.3). Найважливіші
з них:

1. **Агент досі рахує токени по символах**, причому двома різними формулами
   (`1.6/3.6` в `agent.py` проти `3.5` у `context_stats.py`) — різниця понад 2
   рази для українського тексту, і саме ця оцінка керує стисканням історії;
2. параметр `timeout` у `NativeRuntime.generate` приймається й ігнорується
   (`del timeout`);
3. міст `bridge` обходить чергу й телеметрію `NativeRuntime`, тому `busy()`
   завжди `False`;
4. граматики GBNF не працюють (самплер не додається через `_vocab = 0`);
5. чотири налаштування рушія (`native_gpu_layers`, `native_cache_type`,
   `native_flash_attn`, `native_unload_on_exit`) зберігаються, але не читаються;
6. «локальний/хмарний» визначається **шістьма** незалежними способами.

Ці пункти не приховані: вони або позначені в коді, або зафіксовані тут як борг,
який треба закрити в наступній ітерації. Окремо названо й те, чого система не
вміє принципово — safetensors, TensorRT-LLM, Vulkan/DirectML у вбудованому
рушії, тайм-аут генерації, автовивільнення VRAM на простій.

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
