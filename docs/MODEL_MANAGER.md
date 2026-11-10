# Менеджер моделей (ModelManager)

`blackchpok_ide/native/manager.py` — життєвий цикл **файлів** GGUF-моделей:
список, метадані, додавання, перевірка цілісності, перейменування,
видалення з підтвердженням і завантаження з докачкою. Модуль не залежить
від tkinter і під час звичайного читання списку не робить мережевих
запитів — тільки локальний диск.

Другий, окремий менеджер — `model_hub` — лишається для пошуку моделей у
HF/GitHub/Civitai; `native/manager.py` про це прямо пише в docstring.

## 1. Де лежить тека моделей

```python
def models_dir() -> Path:
    from ..model_hub import models_dir as _models_dir
    return Path(_models_dir())
```

Тобто шлях не дублюється: менеджер бере його з `model_hub.models_dir()`, а
той — через `config.find_data_dir("models", marker=".gguf")`. Порядок
пошуку — `config.data_roots()`:

1. `app_data_dir()` — `BLACKCHPOK_HOME`, далі `%APPDATA%\BlackChpokIDE`,
   далі `~/.blackchpokide`, далі `%TEMP%\BlackChpokIDE`, далі
   `<тека програми>/userdata`;
2. `<тека програми>/userdata`;
3. `<тека програми>`.

Перша тека, у якій уже є `*.gguf`, і стає «текою моделей». Якщо такої
немає — повертається `app_data_dir()/models` (і вона створюється).

Перевірено на цій машині:

```
app_data_dir()  → C:\Users\Admin\AppData\Roaming\BlackChpokIDE
models_dir()    → C:\AI\blackchpock_ai\userdata\models
```

Тека бази пам'яті NEUROMESH лежить окремо:
`app_data_dir()/neuromesh/memory.db`. Кеш векторів для embeddings —
`<тека моделей>/../neuromesh/vectors.db` (так будує `NativeRuntime.load_model`).

Свій шлях можна задати явно: `ModelManager(folder)`.

## 2. ModelEntry

`@dataclass ModelEntry` — один файл моделі:

| Поле | Зміст |
| --- | --- |
| `path`, `name`, `size_gb`, `modified_at` | файл |
| `quant`, `architecture`, `layers`, `context`, `parameters_b` | з метаданих GGUF |
| `has_chat_template`, `is_projector`, `is_embedding` | властивості з GGUF |
| `fits`, `suggested_ctx`, `suggested_gpu_layers`, `vram_needed_gb`, `ram_needed_gb` | прогноз |
| `notes`, `error` | пояснення й текст помилки |
| `complete` | `True`, якщо метадані прочитано без помилки |
| `projector` | шлях до суміжного `mmproj`, якщо знайдено |

Похідні: `key` — `Path(path).stem`; `to_dict()` (округляє `size_gb`,
`parameters_b`, `vram_needed_gb`, `ram_needed_gb` до 2 знаків);
`summary()` — один рядок для списку.

## 3. Операції

### refresh

```python
manager.refresh(profile=None, force=True) -> list[ModelEntry]
```

* `force=False` і кеш молодший за 30 с — повертає кеш.
* `_scan()` перебирає `folder.iterdir()`, бере лише файли з
  `MODEL_SUFFIXES = (".gguf",)`, викликає `inspect.inspect(path, profile=…)`
  для кожного.
* Файли-проєктори (`mmproj`) у список **не потрапляють**; для кожної моделі
  шукається суміжний проєктор через `_match_projector`.
* Сортування — за `size_gb` спадно.

`_match_projector` спершу шукає «сімейство» у назві (`qwen3vl`, `qwen3-vl`,
`qwen2.5-vl`, `qwen2vl`, `llava`, `minicpm`, `gemma3`, `internvl`), інакше
бере єдиний проєктор у теці; якщо проєкторів кілька й сімейство не
збіглося — повертає порожній рядок.

### add_local

```python
manager.add_local(source, copy=False, on_progress=None) -> ModelEntry
```

* Перевірки: файл існує, розширення `.gguf`, `gguf.looks_like_gguf()` дає
  `True` (магія `GGUF`). Інакше — `ModelManagerError`.
* `copy=False` (типово) файл **не переноситься**: він лишається там, де
  лежить, а IDE просто бере його в обіг.
* `copy=True` копіює у теку моделей (`shutil.copy2`), попередньо
  перевіривши, що там немає однойменного файлу й що вистачає місця:
  `_free_gb(folder) >= size + DISK_MARGIN_GB` (1.0 ГБ запасу).

### delete

```python
manager.delete(key_or_path, confirm=False) -> bool
```

Без `confirm=True` повертає `False` і **не чіпає файл** — це зроблено
навмисно, бо видалення ваг незворотне. З підтвердженням:

1. `get()` знаходить запис (інакше `ModelManagerError`);
2. `path.resolve().relative_to(self.folder.resolve())` — файл поза текою
   моделей видаляти заборонено (це перевіряє й тест
   `test_foreign_file_is_not_deleted`);
3. `unlink()`, запис прибирається з кешу.

`NativeRuntime.delete_model()` додатково вивантажує модель, якщо шлях
збігається з завантаженою, і повертає `{"ok", "confirmed", "path"}`.

### verify

```python
manager.verify(key_or_path, expected_size=0) -> dict
```

Делегує в `inspect.verify_integrity()`: магія GGUF, читабельність
метаданих, `tensor_count > 0`, збіг розміру (якщо передано
`expected_size`). Повний SHA-256 не рахується — для цього є окрема
функція `inspect.sha256_of()`.

### rename

```python
manager.rename(key_or_path, new_name) -> ModelEntry
```

Порожня назва — помилка. Розширення `.gguf` додається саме, якщо його
немає. Якщо файл із такою назвою вже існує — `ModelManagerError`.
Використовується `Path.rename()` (у межах тієї самої теки).

### download

```python
manager.download(url, filename="", on_progress=None, on_status=None, cancel=None) -> dict
```

Алгоритм:

1. Ім'я: `filename` → останній сегмент URL → `"model.gguf"`; `.gguf`
   додається, якщо відсутнє.
2. `HEAD`-запит (тайм-аут 30 с) дає `Content-Length`; якщо не вдався —
   `total = 0` і завантаження йде без відомого розміру.
3. Перевірка місця: `needed_gb = max(0, total - already) / GB`, де
   `already` — поточний розмір `.part`. Потрібно `needed_gb + 1.0` ГБ.
4. `GET` із `Range: bytes=<already>-`, якщо `.part` уже є; режим `ab`/`wb`.
5. У циклі читається блок `CHUNK = 1 MiB`; `cancel()` перевіряється на
   кожному блоці й кидає `ModelManagerError("Завантаження скасовано.")`.
6. Якщо `total` відомий і `written < total` — помилка з текстом
   «Файл обірвано: … .part збережено», **файл не перейменовується**.
7. `verify_integrity(part, expected_size=total)`; якщо не `ok` — помилка з
   переліком проблем.
8. `os.replace(part, destination)` — атомарна заміна.

Повертає `{"path", "size_bytes", "size_gb", "integrity"}`.

`NativeRuntime.download_model()` додатково вимагає, щоб URL починався з
`http://` або `https://`.

### summary і export_index

`summary(profile=…)` повертає `folder`, `count`, `total_gb`, `free_gb`,
`models` (список `to_dict()`), `projectors` (шлях і розмір кожного
`mmproj`). `export_index(path)` пише цей самий звіт у JSON (для
діагностики й бенчмарків).

## 4. Контроль вільного місця

Єдине джерело — `_free_gb(path)` = `shutil.disk_usage(path).free / GB`
(0.0 при `OSError`). Запас `DISK_MARGIN_GB = 1.0` ГБ застосовується у двох
місцях: копіювання (`add_local`) і завантаження (`download`).

Місце перевіряється **до** запису. Під час самого завантаження повторної
перевірки немає: якщо диск заповниться посеред процесу, `OSError` під час
`handle.write()` перетвориться на `ModelManagerError("Завантаження
перервано: …")`, а `.part` лишиться на диску.

## 5. Що буває при збоях

| Ситуація | Поведінка |
| --- | --- |
| Файла немає / це тека | `ModelManagerError("Файл не знайдено: …")` |
| Не `.gguf` | `ModelManagerError("Підтримуються лише файли .gguf.")` |
| Немає магії GGUF | `ModelManagerError("… не є GGUF-файлом (немає магії GGUF).")` |
| Копіювання, а ім'я вже зайняте | `ModelManagerError("У теці моделей уже є X.")` |
| Мало місця | `ModelManagerError` з точними числами «потрібно / вільно» |
| Обірване завантаження | `.part` **зберігається**, виняток про байти |
| Пошкоджений файл після завантаження | `.part` не перейменовується, виняток зі списком проблем |
| Скасування завантаження | `ModelManagerError("Завантаження скасовано.")` |
| Спроба видалити файл поза текою | `ModelManagerError("Файл поза текою моделей … — не видаляю.")` |
| Видалення без `confirm=True` | повертає `False`, файл цілий |
| Перейменування в існуючу назву | `ModelManagerError("Файл X уже існує.")` |
| Теки моделей не існує | `refresh()` повертає порожній список (не падає) |
| Один файл не читається | у записі лишається `error`, `complete=False`; решта списку будується |

`_describe()` ніколи не кидає виняток назовні: `OSError` від `stat()` лягає
в `entry.error`, а `inspect.inspect()` повертає `ModelReport.error` замість
винятку.

Одна деталь для читача коду: у `_scan()` після `if entry.is_projector:
continue` стоїть ще одна перевірка `if not entry.is_projector:` — вона
завжди істинна, тобто надлишкова, але поведінки не змінює.

## 6. Приклад

```python
from blackchpok_ide.native import bridge

rt = bridge.runtime()

data = rt.list_models()
print(data["folder"], data["count"], data["free_gb"])
for model in data["models"]:
    print(model["key"], model["quant"], model["size_gb"], model["fits"])

# перевірити цілісність
print(rt.verify_model("qwen2.5-coder-14b-instruct-q4_k_m.gguf"))

# завантажити з докачкою (скасування — через cancel-колбек)
rt.download_model(
    "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf",
    on_status=lambda text: print("статус:", text),
    on_progress=lambda done, total: None,
    cancel=lambda: False,
)
```

## Підсумок

`ModelManager` працює лише з файлами `.gguf` у теці, яку визначає
`model_hub.models_dir()`: список будується з реальних метаданих GGUF,
додавання без `copy=True` не переносить файл, видалення вимагає
`confirm=True` і заборонене поза текою моделей, а завантаження пише
`<name>.part`, тримає 1 ГБ запасу на диску, підтримує `Range`-докачку і
перейменовує файл лише після успішної перевірки цілісності.
