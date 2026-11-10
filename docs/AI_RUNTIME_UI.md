# Інтерфейс: вкладка «AI Runtime» і дві бічні панелі

Документ описує три місця, де користувач керує рушієм і пам'яттю:

1. **вкладка «AI Runtime»** у діалозі налаштувань
   (`SettingsDialog._runtime_tab`, `settings_dialog.py`);
2. **бічна панель «AI Runtime»** (`runtime_panel.RuntimePanel`);
3. **бічна панель «NEUROMESH Пам'ять»** (`neuromesh_panel.NeuromeshPanel`).

Для кожної кнопки вказано метод, який вона **справді** викликає.

## 0. Як дістатися

| Шлях | Що відкривається |
| --- | --- |
| Меню/кнопка налаштувань → вкладка **«AI Runtime»** | вкладка рушія |
| Налаштування → вкладка **«Розділи»** → «◉ AI Runtime» | закриває діалог і показує бічну панель `runtime` |
| Налаштування → вкладка **«Розділи»** → «∞ NEUROMESH Пам'ять» | бічна панель `neuromesh` |
| Вкладка «AI Runtime» → кнопка **«Панель AI Runtime»** | `_open_panel("runtime")` |
| Програмно | `app.show_side("runtime")` / `app.show_side("neuromesh")` |

`SettingsDialog._open_panel(key)` спершу `self.destroy()`, потім викликає
`on_open_panel(key)`; у `main_window` це `_open_panel_from_settings()` →
`show_side(key)` + статус «Відкрито панель: …».
Назви панелей беруться з `PANEL_TITLES`: `"AI Runtime"` і
`"NEUROMESH Пам'ять"`.

Обидві панелі створюються в `main_window` з живими сервісами:

```python
self.runtime_panel = runtime_panel.RuntimePanel(
    self.side_stack, self.theme, lambda: self.native_runtime,
    on_model_activated=self._on_native_model, on_status=self.set_status)

self.neuromesh_panel = neuromesh_panel.NeuromeshPanel(
    self.side_stack, self.theme, lambda: self.memory,
    on_open_memory=self._show_memory_item, on_status=self.set_status)
```

## 1. Вкладка «AI Runtime» у налаштуваннях

Вступний текст вкладки: «Власний рушій BLACKCHPOK виконує GGUF-моделі
просто в процесі IDE. LM Studio, Ollama чи llama-server для цього не
потрібні.»

### Рядок стану

`self.runtime_status` (`StringVar`, початково «перевіряю рушій…»)
заповнюється автоматично через `after(120, _runtime_auto_probe)`:

* `bridge.runtime().library_info()` → `ok: False` →
  `«Рушій не встановлено: <error>»`;
* `ok: True` → `«llama.cpp <version> · <пристрої>»`, де пристрої — це
  `name (memory_total_mb МБ)` для кожного з `devices`, або `«лише CPU»`.

### Поля

| Елемент | Змінна | Типове значення |
| --- | --- | --- |
| «Модель для рушія» (Combobox + кнопка «Список») | `native_model_var` | `settings.engine.native_model` |
| «Контекст (0 = авто)» (Spinbox 0…131072, крок 1024) | `native_ctx_var` | `settings.engine.ctx_size` |
| «Шарів на GPU (-1 = авто)» (Spinbox −1…999) | `native_layers_var` | `settings.engine.native_gpu_layers` |
| «Тип KV-кешу» (Combobox: авто, q8_0, q4_0, f16, bf16) | `native_cache_var` | `settings.engine.native_cache_type` або «авто» |
| Прапорець «Використовувати власний рушій для чату (не llama-server)» | `native_enabled_var` | `settings.engine.native` |

Список моделей заповнюється при відкритті вкладки (`_refresh_native_models`)
і кнопкою **«Список»** — обидва викликають `bridge.list_models()`
(без мережі, лише локальні `.gguf`).

### Кнопки

| Кнопка | Метод | Що викликає |
| --- | --- | --- |
| **Перевірити залізо** | `_runtime_probe_hardware()` | `runtime.hardware(refresh=True)` → `profile.summary()`, далі `runtime.inspect_model(модель)` → `display_name`, `quant`, `params_b`, `layer_count`, `fits`, `vram_needed_gb`, `ram_needed_gb`, `suggested_ctx`, `suggested_gpu_layers`, перші 3 `notes` — усе в журнал |
| **Завантажити у рушій** | `_runtime_load_model()` | у фоновому потоці `bridge.runtime().load_model(модель, ctx=<з поля>, on_progress=…)` |
| **Вивантажити** | `_runtime_unload_model()` | `bridge.unload()` → `{"unloaded": bool}` |
| **Бенчмарк** | `_runtime_benchmark()` | у фоновому потоці `runtime.benchmark_model(runs=1, max_tokens=32)` |
| **Панель AI Runtime** | `lambda: self._open_panel("runtime")` | закриває діалог, показує бічну панель |

Результати пишуться в текстове поле-журнал `runtime_log` через
`_runtime_text()` (з будь-якого потоку — через `_ui_text()` → `after(0, …)`).

**«Завантажити у рушій»** передає лише `ctx`. Шари на GPU й тип KV-кешу з
цієї вкладки в цей виклик **не передаються** (`gpu_layers=None` →
прогноз із метаданих). Вони зберігаються в налаштування й
використовуються під час автозапуску через
`main_window._autostart_native_model()`, який теж викликає
`load_model(..., ctx=settings.engine.ctx_size, gpu_layers=None)`.

Коли модель завантажено, `RuntimePanel` викликає `on_model_activated`, а
`main_window._on_native_model(path)` переводить чат на
`native://blackchpok` (див. `INSTALLATION.md`, розділ 6).

### Збереження

`_save()` зберігає:

```python
s.engine.native = bool(native_enabled_var.get())
s.engine.native_model = native_model            # якщо непорожній
s.engine.native_gpu_layers = max(-1, min(999, layers))
s.engine.native_cache_type = "" if cache_choice in ("", "авто") else cache_choice
if native_ctx > 0:
    s.engine.ctx_size = max(2048, min(131072, native_ctx))
```

Пріоритет контексту: поле вкладки «AI Runtime» перекриває загальне поле
контексту, «бо стосується саме вбудованого рушія».

## 2. Бічна панель «AI Runtime» (`runtime_panel.py`)

`RuntimePanel(tk.Frame)`; заголовок **«AI RUNTIME · ВЛАСНИЙ РУШІЙ»**.
Важке — у фонових потоках, результати — через `queue` + `after`.
`LIVE_INTERVAL = 3000` мс.

### Що показує

| Місце | Зміст |
| --- | --- |
| `lib_label` (рядок 1) | `тека: …` / `моделей: N · X ГБ · вільно Y ГБ` / `завантажено: <файл>` |
| `lib_label` (рядок 2, після статусу) | `llama.cpp <версія> · <пристрої не-CPU>` або `без GPU`; при `ok: False` — `рушій недоступний: <error>` |
| `metrics` | модель, `ctx`, шари GPU, тип KV, `KV: used/capacity токенів · переиспользовано N`, час завантаження; **останній запит**: `✓/✗ <operation> <мс>`, або «модель не завантажена» |
| `metrics` (рядок GPU) | `GPU: <назва> · used/total МБ · завантаження N% · T °C` або «GPU: nvidia-smi недоступний» |
| `metrics` (рядок RAM) | `RAM: система X/Y ГБ вільно · процес Z МБ` |
| `log_label` | результат бенчмарку або перевірки, повідомлення дій |
| `scroll` | картки моделей: назва, `quant · NB · ctx NK · X ГБ · режим`, прогноз `~VRAM · шари · ~RAM` |

Внутрішні методи оновлення: `refresh_models()` → `runtime.list_models()`
(типово `refresh=True`, тобто тека перечитується), `refresh_status()` →
`runtime.get_runtime_status()`, `runtime.get_gpu_status()`,
`runtime.get_memory_status()`. Живі показники оновлюються кожні 3 с через
`_live_tick()` → `refresh_status()`.

Кнопка **⟳** («Оновити все») → `refresh_all()` = `refresh_models()` +
`refresh_status()`.

### Клік по картці моделі

`_select(path)` заповнює поля `ctx` і `шарів на GPU`
(`model["suggested_ctx"]`, `model["suggested_gpu_layers"]`) і пише в статус
`Вибрано <назва> · ctx N · шарів на GPU M`.

### Кнопки

| Кнопка | Метод | Що викликає |
| --- | --- | --- |
| **Завантажити** | `run_load()` | у потоці `runtime.load_model(self._selected, ctx=<поле>, gpu_layers=<поле або None>, on_progress=…)`; далі `on_model_activated(path)` і `("reload", None)` |
| **Вивантажити** | `run_unload()` | `runtime.unload_model()`; повідомлення «Модель вивантажено.» / «Моделі в пам'яті не було.» |
| **Бенчмарк** | `run_benchmark()` | `runtime.benchmark_model(runs=2, max_tokens=64)`; показує `tokens_per_second`, p95, TTFT, p95, ctx, шари, VRAM |
| **Перевірити** | `run_inspect()` | `runtime.inspect_model(self._selected)`; показує `display_name · architecture · quant`, шари, ctx тренування, словник, наявність шаблону чату й цілісність |

Кнопка **Завантажити** без вибраної моделі: `«Спершу вибери модель у
списку.»`. Некоректне число в полі `ctx` → `0` (авто), у полі шарів →
`None` (авто).

Окремо: у `log_label` для перевірки рядок «tool calling: так/адаптер»
будується з `has_chat_template`, тобто це **не** перевірка наявності
нативних інструментів у шаблоні, а лише наявність шаблону. Справжня
перевірка — `chatfmt.has_native_tool_support()` у `engine.supports_native_tools`.

## 3. Бічна панель «NEUROMESH Пам'ять» (`neuromesh_panel.py`)

`NeuromeshPanel(tk.Frame)`; заголовок **«NEUROMESH Ω · ПАМ'ЯТЬ»`.
`RECENT_LIMIT = 12`, `EVENT_LIMIT = 6` (об'явлена константа; панель показує
`events[0]` як «остання подія»).

### Що показує

`summary_label` (4 рядки, з `service.status()`):

```
N спогадів · M зв'язків
конфліктів: K · з векторами: V
точність прогнозу: P (S вимірів)
токени: точні|оцінка · вектори: готові|немає
```

Нижче — список карток останніх 12 спогадів (`status()["recent"]`):
заголовок `<kind> · <confidence> · <останні 6 символів id>`, текст до 220
символів. Клік по картці → `on_open_memory(id)` →
`main_window._show_memory_item()` → `memory.explain(id)` у окремому вікні
(`show_text_window`): ID, тип, впевненість, походження, текст,
«на чому тримається впевненість», до 10 подій.

`status_line` показує повідомлення дії, а якщо дій не було > 5 с —
`остання подія: <action> — <detail>`.

### Поле пошуку

`Entry` + Enter або кнопка **⌕** → `run_search()`:

```python
service.search(query, limit=RECENT_LIMIT)   # limit=12
```

Результат замінює список: рядок `політика: <policy>`, далі картки з
`↳ <explanation>` під кожною. Порожній запит ігнорується.

### Кнопки

| Кнопка | Метод | Що викликає |
| --- | --- | --- |
| **Прогноз** | `run_predict()` | `service.predict(query=<з поля пошуку>, limit=8)`; показує `політика: прогноз (<confidence>): <reason>` + картки `memories`, і повідомлення `Прогноз: <reason>; файли: <…>` |
| **Консолідація** | `run_consolidate()` | `service.consolidate()`; повідомлення `Консолідація: злито N, застарілих M, конфліктів K.` + перечитування стану |
| **Бекап** | `run_backup()` | `service.backup()`; повідомлення `Бекап: <path> (<size> байт)` + перечитування |
| **Зі старого RAG** | `run_migrate()` | `service.migrate_legacy_rag()`; повідомлення `Перенесено N (дублів M) з <sources>` + перечитування |

Кнопка **⟳** у заголовку → `refresh()` → у потоці `service.status()`.

Усі чотири дії й пошук виконуються у фонових потоках
(`neuromesh-search`, `neuromesh-predict`, `neuromesh-consolidate`,
`neuromesh-backup`, `neuromesh-migrate`), тому довга консолідація не
«морозить» вікно.

### Чого панель не має

Кнопок для `restore`, `integrity`, `reindex_vectors`, `rebuild_search`,
`contradictions`, `resolve` — **немає**. Вони доступні через Python-API
(див. `NEUROMESH_API.md`) або через агента (`memory_recover` з `action:
"integrity"` / `"restore"`). Це варто знати, щоб не шукати їх в інтерфейсі.

## 4. Відповідність «кнопка → метод» (зведена таблиця)

| Панель | Кнопка | Метод API |
| --- | --- | --- |
| налаштування | Список | `bridge.list_models()` |
| налаштування | Перевірити залізо | `NativeRuntime.hardware(refresh=True)`, `NativeRuntime.inspect_model()` |
| налаштування | Завантажити у рушій | `NativeRuntime.load_model(ctx=…)` |
| налаштування | Вивантажити | `bridge.unload()` → `NativeRuntime.unload_model()` |
| налаштування | Бенчмарк | `NativeRuntime.benchmark_model(runs=1, max_tokens=32)` |
| налаштування | Панель AI Runtime | `SettingsDialog._open_panel("runtime")` |
| AI Runtime | ⟳ | `NativeRuntime.list_models()`, `get_runtime_status()`, `get_gpu_status()`, `get_memory_status()` |
| AI Runtime | Завантажити | `NativeRuntime.load_model(ctx=, gpu_layers=)` |
| AI Runtime | Вивантажити | `NativeRuntime.unload_model()` |
| AI Runtime | Бенчмарк | `NativeRuntime.benchmark_model(runs=2, max_tokens=64)` |
| AI Runtime | Перевірити | `NativeRuntime.inspect_model()` |
| NEUROMESH | ⟳ | `Neuromesh.status()` |
| NEUROMESH | ⌕ / Enter | `Neuromesh.search(query, limit=12)` |
| NEUROMESH | Прогноз | `Neuromesh.predict(query=, limit=8)` |
| NEUROMESH | Консолідація | `Neuromesh.consolidate()` |
| NEUROMESH | Бекап | `Neuromesh.backup()` |
| NEUROMESH | Зі старого RAG | `Neuromesh.migrate_legacy_rag()` |
| NEUROMESH | клік по картці | `main_window._show_memory_item()` → `Neuromesh.explain()` |

## 5. Деталь про «останній запит» на панелі рушія

`RuntimePanel._apply_metrics()` показує `status["requests"][-1]`. Але
`NativeRuntime._record()` викликається **лише при `EngineError`** у
`generate()`/`generate_stream()`. Тому в цьому рядку з'являться тільки
невдалі запити; успішна генерація його не оновлює. Якщо рядка немає —
генерацій з помилками ще не було (або вони не йшли через цей шлях).

## Підсумок

Вкладка «AI Runtime» у налаштуваннях — це налаштування й разові дії
(список моделей, перевірка заліза, завантаження/вивантаження, короткий
бенчмарк, перехід на бічну панель); після успішного завантаження чат
автоматично переходить на `native://blackchpok`. Бічна панель «AI Runtime»
дає живі показники (VRAM через `nvidia-smi`, RAM процесу, KV-кеш) і повний
бенчмарк на 2 прогони. Панель «NEUROMESH Пам'ять» показує статистику з
SQLite, шукає з поясненням політики, будує прогноз і робить консолідацію,
бекап та перенесення зі старого RAG — усе через реальні методи
`Neuromesh`. Кнопок для `restore`, `integrity` і перебудови індексів в
інтерфейсі немає; вони доступні через API й інструменти агента.

## Що вже виправлено (актуально)

| Було | Стало | Де |
| --- | --- | --- |
| Панель показувала лише помилки (успіхи не писались) | журнал містить і успішні запити | `native/api.py::_record` |
| «Локальна/хмара» для вбудованого рушія показувалась як «хмара» | окремий підпис «вбудований рушій · online/не завантажена» | `main_window.py::_model_summary` |
| Великий статус «● МОДЕЛЬ ОФЛАЙН» на живій вбудованій моделі: стан ставився через `server_responds("native://…")`, а в цієї адреси немає ні порту, ні HTTP — завжди `False` | `runtime.model_answers()` обирає рушій або мережу; шапка й крапка чату показують «● МОДЕЛЬ ОНЛАЙН» (заміряно: `#e2706b` → `#5ec98a`) | `runtime.py::model_answers`, `main_window.py::_confirm_model_online` |
| Діагностика для `native://` писала «ніхто не слухає» + «жоден локальний порт не відповідає», і додавала чужий `server.log`, де модель відповідала | три окремі питання (`available` / `model_loaded` / `model_answers`), звіт узгоджений, `report.ok = True` | `runtime.py::embedded_*`, `diagnostics.py::run` |
| Кнопка «Завантажити» передавала лише `ctx` | передаються ще `gpu_layers`, `cache_type`, `flash_attn` з налаштувань | `main_window.py::_autostart_native_model` |
| Тайм-аут генерації не діяв | діє через `should_stop`, повертає `timed_out: true` | `native/api.py::generate` |
| Простій не вивантажував вбудований рушій | вивантажує й будить назад | `power.py::ModelKeeper` |

## Чого в панелі немає (доступно через API/агента)

* відновлення з бекапу (`Neuromesh.restore`) — у панелі є лише створення бекапу;
* перевірка цілісності (`Neuromesh.integrity`) і перерахунок векторів
  (`reindex_vectors`) та перебудова FTS (`rebuild_search`);
* вирішення конфліктів (`resolve`) — список конфліктів видно, дію — ні.

Кожна з цих операцій доступна інструментові `memory_recover` і Python-API,
тож «кнопок, що нічого не роблять», немає — але й повного покриття UI
немає. Це свідоме обмеження обсягу, а не прихована функція.
