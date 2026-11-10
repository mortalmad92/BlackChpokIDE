# Виправлення раунду: аварія рушія й порожній перелік файлів

Дата: 2026-11-10. Обидва дефекти знайдені **запуском**, а не читанням коду,
і обидва підтверджені стеком або виводом.

---

## 1. КРИТИЧНЕ: аварія всього процесу під час автономного режиму

### Симптом

`tests/test_autonomous_live.py` завершувався **кодом 0xC0000409**
(`STATUS_STACK_BUFFER_OVERRUN`, тобто падіння в C-коді) із повідомленням:

```
D:/a/llama.cpp/llama.cpp/src/llama-kv-cache.cpp:735:
GGML_ASSERT(seq_id >= 0 && (size_t) seq_id < seq_to_stream.size()) failed
```

Це не виняток Python. Це аварія **всього процесу IDE** — у реальній роботі
вона виглядала б як «програма раптово закрилась».

### Корінь (доведено faulthandler-ом)

`faulthandler` надрукував стек обох потоків у момент аварії:

```
Current thread 0x0000213c [Thread-13 (_run)] (most recent call first):
  File "blackchpok_ide/native/engine.py", line 385 in _decode_chunk
  File "blackchpok_ide/native/engine.py", line 364 in decode
  File "blackchpok_ide/native/engine.py", line 721 in generate_stream
  ...
  File "blackchpok_ide/agent.py", line 3043 in _loop

Thread 0x000027ac (most recent call first):
  File "blackchpok_ide/native/engine.py", line 403 in free
  File "blackchpok_ide/native/engine.py", line 570 in unload
  File "blackchpok_ide/native/api.py", line 527 in shut_down
  File "blackchpok_ide/main_window.py", line 7568 in on_close
```

**Два потоки одночасно на одному контексті:**

| Потік | Що робив | Який замок тримав |
|---|---|---|
| `Thread-13 (_run)` — агент | `llama_decode` у `_decode_chunk` | `context._lock` |
| головний — `on_close` | `EngineContext.free()` | **лише `engine._lock`** |

`unload()` брав `self._lock` (замок РУШІЯ) і звільняв контекст, не
дочекавшись поточного `llama_decode` (той тримає `context._lock` — ІНШИЙ
замок). Звільнена пам'ять використовувалась у C-коді → `GGML_ASSERT`.

Це та сама гонка, через яку «IDE іноді падала сама» після закриття вікна
під час роботи агента.

### Виправлення

`NativeEngine.unload()` тепер робить три кроки в такому порядку:

```python
with self._lock:                     # 1. замок рушія
    context.cancel()                 # 2. попросити генерацію зупинитись
    with context._lock:              # 3. дочекатись кінця llama_decode
        context.free()
```

Порядок блокувань узгоджений з усіма іншими місцями:
**`engine._lock` → `context._lock`**, ніколи навпаки. `RLock` дозволяє
повторний вхід, тому `load()` (який кличе `unload()` під тим самим замком)
працює без змін.

### Перевірка

```
python tests/test_autonomous_live.py    # було 0xC0000409 → стало EXIT=0
→ «Автономний режим: успішно»
```

---

## 2. `list_dir` не розпізнавався як перелік файлів

### Симптом

`tests/test_tool_router.py` падав:

```
[FAIL] відповідь містить реальний результат дії
       Готово. Результат: **list_dir** ``` . — 35 записів …
```

Агент викликав `list_dir` правильно, але відповідь показувала обрізаний
код-блок на 12 рядків, де були лише службові теки — **`blackchpok_ide/` і
`main.py` до відповіді не потрапляли**.

### Корінь (виміряно)

```
рядків: 37
схожих на файл: 34 з 37
поріг: 35
looks_like_file_list: False      ← перелік не визнано
```

Дві причини, обидві — у критерії «схожий на файл»:

1. **`.gitignore`** не визнавався файлом: у нього немає основи ДО крапки,
   тому `stem, dot, suffix = head.rpartition(".")` давав `stem=""` і
   перевірка `bool(dot and stem and …)` була хибною.
2. **Службові рядки** `list_dir` («`. — 35 записів …`», «`Підсумок за
   типами: …`») рахувались у співвідношенні як «не файли» й опускали його
   нижче порогу.

### Виправлення

Файл: [`response_engine.py`](../blackchpok_ide/response_engine.py)

* `_is_metadata_line()` — окремо розпізнає службові рядки `list_dir`;
  вони більше не псують критерій;
* `_file_like()` — приховані файли (`head.startswith(".") and
  head.count(".") >= 2`) визнаються файлами;
* `_format_result()` — службовий підсумок стає підзаголовком
  (`**list_dir** · . — 35 записів`), а не пунктом списку.

Додатково **прибрано дубль**: `agent.AgentRunner._looks_like_file_list`
була ДРУГОЮ копією того самого правила, і саме тому вони розійшлися.
Тепер вона делегує в `response_engine.looks_like_file_list` — одне джерело
істини.

### Результат

```
looks_like_file_list: True

**list_dir** · . — 35 записів (файлів 16, тек 19)

- .agents/
- .blackchpok_ide/        ← назви файлів тепер видно
- __pycache__/
- assets/
- blackchpok_ide/
…
```

```
python tests/test_tool_router.py    # EXIT=0
```

---

## 3. Крихкий тест, який перевіряв залишки, а не механізм

`tests/e2e_stabilization_demo.py::check_state_survives_restart` падав на
«модель не загубилась»: він читав `Settings.load()` і вимагав непорожній
`llm.model`. Але з `BLACKCHPOK_NO_SAVE=1` (який виставляє і `run_all`, і
реєстр) файл не створюється взагалі — тобто тест перевіряв не збереження, а
те, чи хтось раніше встиг записати модель.

**Стало:** тест бере поточний стан, вписує реальні значення, зберігає у
**тимчасовий** файл (явний шлях пишеться завжди) і читає назад. Перевіряє
саме механізм: модель, теку проєкту, шлях моделі, прапорець вбудованого
рушія.

---

## 4. Підсумок раунду

| Перевірка | Результат |
|---|---|
| `python -m unittest discover -s tests` | **Ran 2058 tests · OK (skipped=2)** |
| `python tests/run_all.py --fast` | **Усе пройдено** (104 модулі) |
| `python main.py --selftest` | exit 0, «успішно» |
| `python tests/check_style.py` | «Стиль у порядку» |
| `tools/audit_ui_completeness.py --strict` | **0 прогалин** (13 панелей) |
| `tools/check_settings_dialog.py` | **0 проблем**, збереження працює |
| `tests/test_autonomous_live.py` | **EXIT=0** (було падіння процесу) |
| `tests/test_tool_router.py` | **EXIT=0** (було FAIL) |
| `tests/e2e_stabilization_demo.py` | **EXIT=0** (було EXIT=1) |
