# План ітерації: дебаг і доробка без нових модулів

Дата: 10.11.2026. Складено **після читання коду й живих вимірів** на цій машині
(Windows, Python 3.14.7, AMD Ryzen 5 3600, RTX 3060 12 ГБ). Кожне твердження
нижче має доказ — команду, файл і рядок. Де щось не перевірено — це написано.

**Обмеження, яке я тримав:** жодних нових бібліотек, жодних нових модулів
(нових *файлів* немає; внутрішнє розділення наявного коду дозволене).

---

## 0. Стан на момент аналізу

| Показник | Значення | Як заміряно |
|---|---|---|
| Модулів у пакеті | **145** `.py`, 84 110 рядків | обхід `blackchpok_ide/` |
| Тестів у `unittest discover` | **1961, усі OK** (3 skip) | `python -m unittest discover -s tests -v` |
| Тестових файлів на диску | **137** (114 `test_*.py` + 23 допоміжні) | обхід `tests/` |
| Файлів понад 1200 рядків | **6** | AST-підрахунок |
| Голих `except: pass` | **453** з 1656 обробників | regex по всьому пакету |

**Головний висновок.** Набір тестів зелений, самоперевірка проходить — і це
не означає, що продукт справний. Нижче шість дефектів, які зелений набір
**не бачить**, бо перевірки не туди дивляться.

---

## 1. Шість дефектів, знайдених живими вимірами

### 1.1. КРИТИЧНЕ: `run_all.py` падає одразу після першої групи

`tests/run_all.py` містить **дві** функції `main()`: одна на рядку 149,
друга — на рядку 191. Друга перекриває першу. Друга звертається до `_SCRIPTS`
(рядок 169), якої **ніде не оголошено**.

```
$ python tests/run_all.py --fast
[OK] Самоперевірка ядра (код 0)
Traceback (most recent call last):
  File "tests\run_all.py", line 187, in <module>
    raise SystemExit(main())
  File "tests\run_all.py", line 169, in main
    if name in _SCRIPTS:
NameError: name '_SCRIPTS' is not defined
```

**Наслідок:** «повний набір» складається з **одного** запуску
(`main.py --selftest`) і аварійно завершується. Заміряно: **0.77 с**. Для
порівняння, справжній `unittest discover` іде **191 с** — тобто 99.6% наміру
не виконується.

**Гірше:** `.github/workflows/tests.yml:73` запускає саме `run_all.py`. CI
падає на цьому кроці, тобто червоний — але README/плани цього не фіксують.

### 1.2. КРИТИЧНЕ: 39 тестових файлів не запускаються ніколи

`run_all.py` не згадує **39** із 114 `test_*.py` (жодного разу, навіть
рядком). Серед них найдорожчі:

```
test_intent_engine   test_lazy_tools      test_tool_orchestrator
test_response_engine test_rag_engine      test_neuromesh
test_startup_speed   test_timer_hygiene   test_runner_consistency
```

(Повний список — 39 імен; `test_v2_audit`, `test_native_runtime`,
`test_mcp_integration`, `test_task_queue_engine` **згадані** в `run_all.py`,
але до них прогін не доходить через п. 1.1.)

Причина: `discover_modules()` (рядок 121) шукає файли на диску, але прогін
зупиняється на `NameError` з п. 1.1, не дійшовши до циклу.

**Окремо:** **35** із 114 файлів написано як скрипти з власним `main()`, без
`unittest.TestCase`. Для `discover` вони невидимі. Я запустив усі 35 вручну:
**34 проходять, 1 падає**.

### 1.3. ВИСОКЕ: `test_work_log.py` справді зламаний (регресія, не застарілість)

```
File "tests\test_work_log.py", line 337, in test_reasoning_from_agent
    runner._loop(FakeClient())
File "blackchpok_ide\agent.py", line 3112, in _loop
    self.session.add_user(
AttributeError: 'FakeSession' object has no attribute 'add_user'
```

`agent.py:475` справді має `add_user`, а `FakeSession` у тесті — ні. Тест
відстав від коду. Оскільки файл невидимий для `discover` (п. 1.2), поломка
жила непоміченою.

### 1.4. КРИТИЧНЕ: запуск IDE триває **6.3–6.8 с**, а не 0.38 с

`docs/PLAN_AUDIT_UK.md` обіцяє «0.38 с». Заміряно на цій машині (3 прогони):

```
construct: 2251 ms | first paint: 4077 ms | TOTAL: 6328 ms
construct: 2296 ms | first paint: 3840 ms | TOTAL: 6786 ms
```

Розклад по джерелах (перехоплення `socket.connect` і `subprocess.run`):

| Джерело | Час | Доказ |
|---|---|---|
| 3× TCP-connect на `127.0.0.1:8080` | **3 × 2043 мс** | `socket.py:859:create_connection` |
| GGUF-метадані, 22× `read_meta` | **2257 мс** | `manager.py:196:_scan → _describe` |
| `nvidia-smi` ×4 | ~340 мс | `hardware.py:169:_run` |
| решта (tkinter) | ~500 мс | профіль |

**Чому connect коштує 2 с на локальній адресі:**

```
socket connect 127.0.0.1:8080: 2029 ms -> ConnectionRefusedError
socket connect 127.0.0.1:1234: 2036 ms -> ConnectionRefusedError
```

Це не помилка коду — це поведінка цієї машини (IPv6-then-IPv4 fallback /
фільтр). Але код **не має права чекати на це у головному потоці**.

Три виклики, що блокують:

1. `server_state.py:200` — `probe_server()` у фоновому потоці, але його
   результат **чекають** у `main_window._refresh_context`.
2. `main_window.py:2605` — `LLMClient(...).list_models()` з `timeout=4`,
   викликається з `context_panel._refresh_agent` (через `_active_tool_names`).
3. `agent.py:749` — `_server_slot_context()` з `timeout=4.0`, викликається з
   `agent.tool_schemas() → probe_context_window()`, а `tool_schemas()`
   викликає `main_window.py:5376` на **кожне** оновлення панелі контексту.

**Корінь:** `agent.probe_context_window()` (рядок 1190) робить мережевий
запит **синхронно**, а `tool_schemas()` (рядок 1562) викликає його, якщо
`_context_window` порожнє. Поки сервер не піднятий — порожнє завжди.

### 1.5. КРИТИЧНЕ: точний tokenizer **не доходить** до агента

`main_window._wire_exact_tokens()` (рядок ~7375) робить усе правильно:

```python
agent_module.set_token_counter(counter)
setter = getattr(self.agent, "set_token_counter", None)
if callable(setter):
    setter(counter)
```

Але:

* `AgentRunner.set_token_counter` **не існує** (є лише модульна функція
  `agent.py:180`). `getattr(...)` повертає `None` → **тихий no-op**.
* `agent.py:176` зберігає лічильник у `contextvars.ContextVar`, а агент
  працює в **окремому потоці** (`agent.py:1363`). Перевірено на Python 3.14.7:

  ```
  child thread sees: None
  ```

  `contextvars` **не успадковуються** новим потоком.

**Наслідок:** агент досі ріже історію евристикою. Заміряно на одному реченні:

```
TEXT: "Привіт! Скільки файлів у теці blackchpok_ide? Виклич інструмент…" (83 символи)
agent.AgentSession._tokens_in  : 50
context_stats.estimate_tokens  : 23      ← різниця у 2.2 раза
context_budget (1.6/3.6)       : 50
```

Тобто «виправлений» пункт аудиту від 08.11 — **косметичний**.

### 1.6. ВИСОКЕ: SQLite-з'єднання течуть

`with conn:` у `sqlite3` **не закриває** з'єднання — лише робить
commit/rollback. Перевірено:

```
CONNECTION STILL OPEN after with-block (leak confirmed)
```

Сайти: `native/embeddings.py:105, 199, 237, 252, 275` і `pcmm/store.py:369`.
Кожен виклик `encode`/`store`/кеш-влучання лишає відкритий дескриптор + WAL.
На Windows це зрештою блокує БД.

---

## 2. Мертвий код і дублювання (перевірено)

### 2.1. Мертвий код

| Що | Де | Стан |
|---|---|---|
| Друга `def main()` перекриває першу | `tests/run_all.py:191` | **є** |
| `_SCRIPTS` не оголошено | `tests/run_all.py:169` | **є** |
| `entry.is_projector` → `continue`, далі `if not entry.is_projector:` — недосяжне | `native/manager.py:197–201` | **є** |
| `_array_length()` завжди `0`, ніде не викликається | `native/gguf.py:267` | **є** |
| `ToolCallParser` оголошено, експортовано, не інстанційовано | `native/chatfmt.py:315` | **є** |
| `native_unload_on_exit` — лише оголошення | `config.py:451` | **є** |
| `live_browser_panel.py` (373 р.) — жодного імпортера | `tests/test_v2_audit.py:1829` згадує лише рядком | **є** |
| `nav_sidebar` імпортується лише для анотації типу | `main_window.py:1303` | **є** |
| `_git_branch` / `_git_changes` читаються, **ніколи не присвоюються** | `main_window.py:1159` | **є** |
| 8 методів `main_window` без жодного посилання | `_open_welcome`, `_speak_answer`, `_forget_centre`, … | **є** |
| `_show_full`: `if self.on_apply_code: pass` | `chat_panel.py:2964–2966` | **є** |
| `main_window.py:7759` кличе `self.chat.cancel_probe` — такого метода **немає** (є в `ModelBar`) | перевірено `hasattr`: `ChatPanel: False` | **є** |

### 2.2. Дублювання логіки

| Поняття | Скільки реалізацій | Де |
|---|---|---|
| «локальний чи хмарний» | **7** | `llm_client._is_local_url`, `providers.LocalProvider.is_local`, `providers.ModelEntry.is_local`, `auto_setup._is_local_url`, `main_window._model_summary`, `browser_panel.is_local_url`, `config.normalise` |
| Оцінка токенів | **4** | `agent.py:669`, `context_budget.py:198`, `context_stats.py:438`, `tool_lazy.py:611`, ще `pcmm/budget.py:117` |
| Застосування налаштувань до агента | **5 копій** | `main_window` 7296, 7183, 7560, 7340, 3287 |
| `self.agent.llm_settings = …` | **8 місць** | 3289, 3924, 5728, 6956, 7155, 7188, 7299, 7567 |
| Меню: нативні пункти + реєстр команд | **2 таблиці, 65 спільних підписів** | `_build_menu` 554–701 vs `_register_commands` 815–1131 |
| `_timer_alive` | **9 модулів** | main_window, chat_panel ×2, first_run, live_preview, model_hub_panel, preview_panel, terminal, voice_panel |
| Обгортка `threading.Thread(target=work)` | **13 місць** | main_window ×8, chat_panel ×2, settings_dialog ×3 |
| `on_status=self.set_status` | **20 місць** | main_window |

---

## 3. Порушення потокобезпеки (перевірено)

| № | Що | Де | Наслідок |
|---|---|---|---|
| T1 | `self.after(0, …)` з **фонового** потоку | `settings_dialog.py:1067` (виклик із `work()` 1051/1086) | Tkinter падає «main thread is not in main loop»; у `chat_panel.py:1462` це саме задокументовано як заборонене |
| T2 | `QueueExecutor(on_status=self.set_status, on_change=self._update_queue_badge)` | `main_window.py:298–299` | колбеки йдуть з потоку агента й **чіпають віджети** |
| T3 | `tool_schemas()` → мережевий `_server_slot_context` | `agent.py:1562 → 1564 → 749` | блокує UI на 2 с на кожне оновлення |
| T4 | `_pending` інкрементується в генераторі | `native/api.py:504–514` | покинутий генератор лишає `busy()=True` назавжди |
| T5 | 24 з 26 `after()` не зберігають id | `main_window` | таймери живуть довше за віджети |
| T6 | `check_same_thread=False` + спільне з'єднання | `pcmm/store.py:228` | конкурентні курсори |

---

## 4. Що з «виправленого» аудиту 08.11 насправді виправлено

Перевірив 11 тверджень по коду: **4 виправлено, 1 частково, 6 — ні**.

| Твердження | Реальний стан | Доказ |
|---|---|---|
| `del timeout` у `NativeRuntime.generate` | ✅ виправлено | `api.py:229` `deadline = …` |
| Граматики GBNF (`_vocab = 0`) | ✅ виправлено | `sampling.py:134` до `_build()` |
| Мертвий `if False` у `engine.py` | ✅ виправлено | немає входжень |
| Простій/VRAM для вбудованого рушія | ✅ виправлено | `power.py:131, 165, 211` |
| `native_gpu_layers/cache_type/flash_attn` | ⚠️ лише в **одному** місці | читаються в `main_window:2652`, **не** в `settings_dialog:1053`, `runtime_panel:423` |
| `bridge` обходить чергу й телеметрію | ❌ **не виправлено** | `bridge.py:112, 160` кличе `rt.engine.*` напряму; `busy()` завжди `False` |
| Мертва гілка в `manager._scan` | ❌ не виправлено | `manager.py:197–199` |
| `gguf._array_length` → 0 | ❌ не виправлено | `gguf.py:267` |
| `ToolCallParser` не використовується | ❌ не виправлено | `chatfmt.py:315` |
| `precision_at_k` не класична | ❌ не виправлено | `bench.py:318` |
| Точний tokenizer у агенті | ❌ **не працює** | п. 1.5 |

---

## 5. Порядок робіт

Кожен етап завершується зеленим `unittest` **і** зеленим `run_all`. Етапи
йдуть строго зверху вниз: без 1-го решта не має страховки.

### Етап 1 — повернути чесний тестовий раннер (≈4 год)

Без цього будь-яка наступна правка — навмання.

1.1. `tests/run_all.py`: видалити **другу** `main()` (рядки 186–389) або
     першу (149–187) — лишити одну. Оголосити `_SCRIPTS` (перелік модулів з
     власним `main()`), бо на неї вже посилається рядок 169.
1.2. Прогнати `run_all.py --fast` повністю; зафіксувати реальний список
     падінь (очікую щонайменше `test_work_log`).
1.3. Виправити `test_work_log.FakeSession` — додати `add_user` (п. 1.3).
     **Код не чіпаємо, тест відстав.**
1.4. Перевести 35 скриптів на `unittest.TestCase` **поступово**: спершу
     обгорнути наявний `main()` у `TestCase.test_all`, щоб `discover` їх
     бачив; переписувати по одному пізніше.
1.5. У `.github/workflows/tests.yml` лишити `run_all.py`, але додати крок
     `unittest discover` **окремо** — щоб один раннер не маскував інший.

**Критерій:** `run_all.py --fast` доходить до кінця й друкує
`Усе пройдено` або **точний** список падінь; `discover` бачить ≥95% файлів.

### Етап 2 — прибрати 6-секундний старт (≈6 год)

2.1. `agent._server_slot_context` — **заборонити** виклик із головного
     потоку: кеш на 60 с + `should_probe` як аргумент; у `tool_schemas()`
     використовувати **останнє відоме** вікно, а не робити запит.
2.2. `main_window._probe_server_alive` і `context_panel._collect_agent_state`
     — не чекати результат; показувати «перевіряю…».
2.3. `native/manager._scan` — кеш метаданих GGUF на диску
     (`userdata/models/.meta-cache.json`, ключ = шлях + mtime + size).
     Заміряно: 22 виклики `read_meta` = 2257 мс → стане 1 прохід ~720 мс,
     далі 0.
2.4. `server_state.PROBE_TIMEOUT` — зменшити до 0.6 с для локальних адрес
     (це health-check, а не робота з моделлю).

**Критерій:** `TOTAL to visible` < 1.5 с при непіднятому сервері
(зараз 6.3 с). Міряти тим самим скриптом, що в п. 1.4 звіту.

### Етап 3 — точний підрахунок токенів (≈3 год)

3.1. Замінити `contextvars` на звичайний модульний `Callable` у `agent.py`
     (або передавати лічильник у конструктор `AgentSession`).
3.2. Додати `AgentRunner.set_token_counter(counter)` — щоб `getattr` у
     `main_window._wire_exact_tokens` перестав бути тихим no-op.
3.3. Звести **4** евристики до **однієї** функції
     (`context_budget.estimate_tokens` як єдина точка).

**Критерій:** новий тест перевіряє, що лічильник, відданий з головного
потоку, видно в потоці агента; і що всі 4 місця дають однакове число.

### Етап 4 — надійність рушія й пам'яті (≈8 год)

4.1. `bridge.chat/chat_stream` — провести через `NativeRuntime.generate*`
     (черга, `_pending`, `_record`, таймаут). Зараз `busy()` бреше.
4.2. `generate_stream` — дати `timeout` і знімати `_pending` на
     `GeneratorExit`.
4.3. `sqlite3`: замінити `with conn:` на `contextlib.closing(...)` у 6 місцях
     (п. 1.6).
4.4. `engine.embed()` — не чистити спільний KV-кеш посеред ходу.
4.5. `engine.py:684–689` — коли промпт не влізає, **попереджати**, а не
     мовчки відрізати голову (там системний промпт з інструментами).
4.6. `native/manager.download` — прибирати `.part` при скасуванні.
     На диску вже лежить `Qwen3VL-32B-Instruct-Q4_K_M.gguf.part` = 945 МБ.

### Етап 5 — прибрати мертвий код і дублювання (≈6 год)

5.1. Видалити: `manager.py:197–199`, `gguf._array_length`, `chatfmt.ToolCallParser`,
     `live_browser_panel.py`, 8 методів `main_window`, `_show_full`-заглушку.
5.2. Звести 7 реалізацій «локальний/хмарний» до однієї
     (`provider_adapters.detect_style`).
5.3. Одне застосування налаштувань замість 5 копій (`apply_settings_to_agent()`).
5.4. Реєстр таймерів один на проєкт (`widgets.cancel_after` уже є).
5.5. `native_unload_on_exit` — або читати, або прибрати з `config.py`.

### Етап 6 — потокобезпека UI (≈4 год)

6.1. `settings_dialog._ui_text` — через чергу, як `main_window._ui_call`.
6.2. `QueueExecutor` — `on_status`/`on_change` обгорнути в `_ui_call`.
6.3. 24 `after()` без id — перевести на реєстр з п. 5.4.
6.4. `main_window.py:7759` — звертатись до `ModelBar.cancel_probe` або
     перейменувати метод у `ChatPanel`.

### Етап 7 — розділення `main_window.py` (≈16 год, **останнім**)

Лише після етапів 1–6. Файл 7858 рядків / 327 методів — це не «стиль», це
причина, чому дефекти живуть довго. Цільова структура (усі — наявні модулі,
без нових файлів-бібліотек):

| Винести | Рядків | Що саме |
|---|---|---|
| `ModelController` | ~990 | `_probe_server_alive`, `_autostart_*`, `_on_model_changed`, `probe_providers` |
| `LayoutController` | ~1360 | `_build_layout`, саші, `_remember_layout`, `_apply_responsive` |
| `PlanController` | ~530 | `_split_task_to_queue`, `_after_split`, `_queue_pump` |
| `CommandLayer` | ~550 | `_register_commands` (317 р. → 6 функцій), меню **з реєстру** |
| `SessionController` | ~320 | чати: `new_chat_session`, `close_chat`, `_sync_chat_*` |
| `BrowserController` | ~195 | сайти й вбудований браузер |
| `SidebarBuilder` + `CentreBuilder` | ~510 | `_build_sidebar`, `_build_centre` — таблицею |

**Критерій:** жоден файл > 1200 рядків; після кожного кроку — зелені тести.

---

## 6. Чого НЕ робити

* **Не переписувати на Qt/Electron.** Tkinter працює, 1961 тест захищає
  поведінку. Це місяці без функціонального виграшу.
* **Не вводити `asyncio`.** Увесь код на потоках + `_ui_call`; змішування
  двох моделей додасть гонок.
* **Не чіпати систему дозволів** — вона узгоджена й покрита тестами.
* **Не «оптимізувати» рендер чату** — вузьке місце не там.
* **Не додавати нові залежності.** `requirements.txt` оголошує
  `openai`, `ollama`, `pypdf`, `python-docx`, `pymupdf`, `pikepdf` — і
  **жодного з них код не імпортує**. Це борг, а не потреба: спершу
  прибрати зайве зі списку, а не додавати нове.

---

## 7. Як перевіряти прогрес

```powershell
python -m unittest discover -s tests          # має бути OK
python tests\run_all.py --fast                # має дійти до кінця
python main.py --selftest                     # має бути «успішно»
```

Вимірювані цілі:

| Метрика | Зараз | Ціль |
|---|---|---|
| `run_all --fast` доходить до кінця | **ні** (NameError) | так |
| Тестових файлів видно `discover` | **79 з 114** (35 невидимі) | ≥110 |
| Старт до першого кадру | **6.3 с** | < 1.5 с |
| Розбіжність оцінки токенів | **2.2×** | 1.0× |
| Точний tokenizer у агенті | ні | так |
| Файлів > 1200 рядків | 6 | 0 |
| Голих `except: pass` | 453 | < 300 |
| Реалізацій «локальний/хмарний» | 7 | 1 |
