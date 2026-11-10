# Тестування агента

Дата: 2026-11-09.

---

## 1. Як запускати

```powershell
# Повний набір (ізольований від справжніх налаштувань)
python tests/run_all.py

# Швидкий
python tests/run_all.py --fast

# Самоперевірка ядра без вікна
python main.py --selftest

# Окремі модулі
python -m unittest tests.test_intent_engine -v
python -m unittest tests.test_model_hub -v
python -m unittest tests.test_task_queue_engine -v
```

---

## 2. Ізоляція від справжніх даних

`tests/run_all.py` виставляє:

```python
env["BLACKCHPOK_HOME"] = str(ROOT / ".buildtmp" / "apphome")
env["BLACKCHPOK_NO_SAVE"] = "1"
```

**Це критично.** Раніше `tests/smoke_gui.py` робив `settings.save()` у
справжній `userdata/settings.json`, записуючи `engine.auto_start = False`.
Після такого прогону локальна модель перестала запускатись сама.

Тепер і `smoke_gui.py` ізолює себе сам — **до імпорту пакета**:

```python
os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchp-smoke-"))
os.environ["BLACKCHPOK_NO_SAVE"] = "1"
```

Перевірка: після прогону `userdata/settings.json` не змінюється.

---

## 3. Живі тести (потребують моделі)

| Скрипт | Що перевіряє |
|---|---|
| `tests/e2e_real_agent.py` | агент створює файл на диску |
| `tests/test_deep_mode_live_model.py` | глибокий аналіз на живій моделі |
| `tests/screenshot_*.py` | знімки панелей |

Вони піднімають власний `llama-server`, тому тривалі. Для них потрібен
завантажений GGUF і встановлений рушій.

---

## 4. Регресійний набір: поточний стан

Станом на 2026-11-09 після виправлень:

| Модуль | Тести | Стан |
|---|---|---|
| `test_ide_core` | 47 | ✅ |
| `test_model_hub` | 42 | ✅ |
| `test_task_queue_engine` | 62 | ✅ |
| `test_intent_engine` | 26 | ✅ |
| `test_planning_and_memory` | 26 | ✅ |
| `test_response_engine` | 23 | ✅ |
| `test_no_duplication_and_greetings` | 15 | ✅ |
| `main.py --selftest` | 30+ | ✅ |

### Відомі розбіжності (не пов'язані з поточними змінами)

Чотири старі тести розійшлися з кодом ще до цього аудиту:

| Тест | Причина |
|---|---|
| `test_tool_router.py` | очікує префікс `mcp:search_web`, код віддає `search_web` |
| `test_work_log.py` | очікує ключ `file_path`, у схемі `path` |
| `test_tools_panel.py` | очікує 20 інструментів, їх 37 |
| `test_editor_files.py` | шукає `README_UK.md` у корені, файли в `docs/` |

Ці розбіжності існували до аудиту (файли не змінювались у цій сесії) і
потребують окремого рішення: або оновити очікування, або повернути поведінку.

---

## 5. Що варто додати

1. **Тест на «вигадану відповідь»**: питання про проєкт мусить дати
   `tool_call`, а не текст. Це та помилка, яка робила агента небезпечним.
2. **Тест на зображення в `_chat_only`**: `pending_images` не мають
   губитись на шляху «розмови».
3. **Тест на чесність значків**: модель із `-vl` без `mmproj` не повинна
   мати значка зору.
4. **Тест на відновлення**: `recovery_steps` зменшує вимоги монотонно.
5. **Тест ізоляції конфігу**: після `smoke_gui` справжній файл незмінний.

---

## 6. Ручна перевірка наскрізного сценарію

```powershell
# 1. Закрити IDE повністю
# 2. Запустити знову
python main.py

# 3. Перевірити, що модель піднялась сама:
#    панель стану → «модель запущено: …»
# 4. Запитати: «Скільки .py файлів у теці blackchpok_ide?»
#    Має бути РЕАЛЬНИЙ виклик інструмента і реальна цифра.
# 5. Прикріпити PNG кнопкою ＋ і запитати, що на ньому.
```

Очікувано: модель запускається автоматично, інструменти викликаються,
зображення доходить до vision encoder.
