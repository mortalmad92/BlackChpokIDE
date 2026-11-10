# Формати моделей: GGUF, quantization, mmproj

Документ описує, які файли приймає власний рушій BLACKCHPOK, що саме з них
читається і чого він **не** вміє. Усе звірено з `native/gguf.py`,
`native/_quant.py`, `native/manager.py`, `native/inspect.py`.

## 1. Що приймається

`manager.MODEL_SUFFIXES = (".gguf",)` — це єдине розширення, яке менеджер
вважає моделлю. `add_local()` додатково перевіряє магію файлу:

```python
if not gguf.looks_like_gguf(target):
    raise ModelManagerError(f"{target.name} не є GGUF-файлом (немає магії GGUF).")
```

`looks_like_gguf()` читає перші 4 байти й порівнює з `GGUF_MAGIC = b"GGUF"`.

## 2. GGUF: розбір заголовка

Формат описаний у docstring `gguf.py` буквально так:

```
char   magic[4]      = "GGUF"
uint32 version
uint64 tensor_count
uint64 kv_count
далі пари «ключ-значення»: рядок = uint64 len + UTF-8 байти;
значення має uint32 type і власне дані. Тип 9 (ARRAY) рекурсивний.
```

Підтримувані версії — **1, 2 і 3**:

```python
if meta.version not in (1, 2, 3):
    raise GgufError(f"Непідтримувана версія GGUF: {meta.version}")
```

Тобто v2 і v3 (а також v1) читаються; v4+ — відмова з поясненням.

Типи значень (`GGUF_TYPE`) — усі 13:

| Код | Тип | Код | Тип |
| --- | --- | --- | --- |
| 0 | uint8 | 7 | bool |
| 1 | int8 | 8 | string |
| 2 | uint16 | 9 | array |
| 3 | int16 | 10 | uint64 |
| 4 | uint32 | 11 | int64 |
| 5 | int32 | 12 | float64 |
| 6 | float32 | | |

Захисти в читачі:

* файл менший за 24 байти — `GgufError("Файл замалий для GGUF.")`;
* довжина рядка `> 1 << 24` — `GgufError("Неправдоподібна довжина рядка…")`;
* `kv_count > 100_000` — `GgufError("Неправдоподібна кількість ключів GGUF.")`;
* вихід за межі файлу — `GgufError("Файл обірвано: метадані виходять за межі файлу.")`;
* вкладені масиви — `GgufError("Вкладені масиви не підтримуються.")`.

Читання йде через `mmap` (`mmap.ACCESS_READ`), тому гігабайтний файл не
копіюється в RAM.

### Що саме читається

`read_meta(path, keep_arrays=False)` — типово **не** вантажить великі
масиви. Для рядкових масивів (словник, мерджі) елементи пропускаються
(`reader.skip(...)`), а довжина запам'ятовується в `GgufMeta.array_lengths`.
Це зроблено навмисно: «150 тисяч рядків словника … з'їдали б пам'ять на
кожне відкриття списку моделей».

Обчислювані поля `GgufMeta`:

| Властивість | Джерело в GGUF | Поведінка, якщо немає |
| --- | --- | --- |
| `architecture` | `general.architecture` | `""` |
| `name` | `general.name` | `""` |
| `quant` | `general.file_type` → `_quant.ftype_name()`, далі `quant_from_filename()` | `"type <n>"` або `""` |
| `layer_count` | `<arch>.block_count` | `0` |
| `context_length` | `<arch>.context_length`, `n_ctx_train`, `context_size` (перше > 0) | `0` |
| `embedding_length` | `<arch>.embedding_length` | `0` |
| `head_count` | `<arch>.attention.head_count` | `0` |
| `head_count_kv` | `<arch>.attention.head_count_kv` | дорівнює `head_count` |
| `parameter_count` | `general.parameter_count` | `0` |
| `vocab_size` | довжина масиву `tokenizer.ggml.tokens` | `0` |
| `tokenizer_model` | `tokenizer.ggml.model` | `""` |
| `has_chat_template` | `tokenizer.chat_template` | `False` |
| `is_embedding_model` | наявність `<arch>.pooling_type`, або маркери `embed`, `bge-`, `e5-`, `gte-`, `nomic` у назві | `False` |
| `is_vision_projector` | ім'я починається з `mmproj`, або `arch` у `{clip, mtmd}`, або `clip.has_vision` | `False` |

Допоміжні функції:

* `read_meta_safe()` — те саме, але помилка лягає у `values["_error"]`;
* `iter_meta()` — потоковий перебір пар ключ-значення;
* `looks_like_gguf()` — швидка перевірка магії;
* `quant_from_filename()` — витягує позначку з імені файлу.

`quant_from_filename` шукає підрядок у такому порядку: `q8_k`, `q6_k`,
`q5_k_m`, `q5_k_s`, `q4_k_m`, `q4_k_s`, `q3_k_m`, `q3_k_s`, `q3_k_l`,
`q2_k`, `iq4_nl`, `iq4_xs`, `iq3_xxs`, `iq3_s`, `iq2_xs`, `iq2_xxs`,
`iq1_s`, `iq1_m`, `mxfp4`, `q8_0`, `q6_0`, `q5_1`, `q5_0`, `q4_1`, `q4_0`,
`q3_0`, `q2_0`, `f16`, `bf16`, `f32`. Приклади з тестів:
`"model-q4_k_m.gguf" → "Q4_K_M"`, `"x-Q8_0.gguf" → "Q8_0"`, `"plain.gguf" → ""`.

## 3. Quantization: перелік типів

`_quant.py` — копія `enum llama_ftype` тієї збірки, що стоїть у
`userdata/runtime`. `ftype_name(n)` повертає людську назву.

| Код | Назва | Код | Назва | Код | Назва |
| --- | --- | --- | --- | --- | --- |
| 0 | F32 | 18 | Q6_K | 36 | TQ1_0 |
| 1 | F16 | 19 | IQ2_XXS | 37 | TQ2_0 |
| 2 | Q4_0 | 20 | IQ2_XS | 38 | MXFP4_MOE |
| 3 | Q4_1 | 21 | Q2_K_S | 39 | NVFP4 |
| 7 | Q8_0 | 22 | IQ3_XS | 40 | Q1_0 |
| 8 | Q5_0 | 23 | IQ3_XXS | 41 | Q2_0 |
| 9 | Q5_1 | 24 | IQ1_S | 42 | F8_E4M3 |
| 10 | Q2_K | 25 | IQ4_NL | 1024 | невідомо |
| 11 | Q3_K_S | 26 | IQ3_S | | |
| 12 | Q3_K_M | 27 | IQ3_M | | |
| 13 | Q3_K_L | 28 | IQ2_S | | |
| 14 | Q4_K_S | 29 | IQ2_M | | |
| 15 | Q4_K_M | 30 | IQ4_XS | | |
| 16 | Q5_K_S | 31 | IQ1_M | | |
| 17 | Q5_K_M | 32 | BF16 | | |

`bits_per_weight(quant)` — скільки біт на вагу дає тип (для прогнозу
пам'яті). Значення з коду: `F32` 32.0, `F16`/`BF16` 16.0, `Q8_0` 8.5,
`F8_E4M3` 8.0, `Q6_K` 6.6, `Q5_K_M` 5.7, `Q5_K_S`/`Q5_1`/`Q5_0` 5.5,
`Q4_K_M` 4.8, `Q4_K_S` 4.6, `Q4_1`/`Q4_0`/`IQ4_NL` 4.5, `IQ4_XS` 4.3,
`MXFP4_MOE`/`NVFP4` 4.3, `Q3_K_L` 3.9, `Q3_K_M` 3.8, `IQ3_M` 3.6,
`Q3_K_S`/`IQ3_S` 3.5, `IQ3_XS` 3.3, `IQ3_XXS` 3.1, `IQ2_M` 2.7,
`Q2_K`/`Q2_K_S` 2.6, `IQ2_S` 2.5, `IQ2_XS` 2.4, `Q2_0` 2.2, `IQ2_XXS` 2.1,
`TQ2_0` 2.1, `IQ1_M` 1.8, `TQ1_0` 1.7, `IQ1_S` 1.6, `Q1_0` 1.1.

Невідомий тип → **4.8** (типове значення `ModelReport.bits_per_weight`).
Функція також розуміє довгі назви: `"Q4_K - Medium"` перетворюється на
`Q4_K_M`, `"Q4_K - Small"` — на `Q4_K_S` (аналогічно Q5_K, Q3_K).

## 4. mmproj (зір)

`mmproj` — окремий файл візуального проєктора, а не модель. Це
підтверджується в кількох місцях:

* `model_hub.is_vision_projector(name)` = `"mmproj" in name.lower() and
  name.lower().endswith(".gguf")`;
* `manager._projectors_in()` відбирає `*.gguf`, де ім'я починається з
  `mmproj` або містить `-mmproj`;
* `manager._scan()` такі файли у список моделей **не** додає;
* `gguf.GgufMeta.is_vision_projector` — `True` також для архітектур `clip`
  і `mtmd` або за наявності `clip.has_vision`;
* `inspect.predict()` для проєктора ставить `fits = "projector"` і нотатку
  «Це файл проєктора (mmproj), а не окрема модель».

Підбір проєктора до моделі — `_match_projector()` за «сімейством» у назві
(`qwen3vl`, `qwen3-vl`, `qwen2.5-vl`, `qwen2vl`, `llava`, `minicpm`,
`gemma3`, `internvl`); якщо сімейство не збіглося й у теці рівно один
проєктор — береться він; інакше — порожньо.

**Чесне обмеження:** власний рушій (`native/engine.py`) зорові можливості
**не реалізує**. `LoadOptions.mmproj_path` існує, зберігається й
повертається в `to_dict()`, `NativeRuntime.load_model(mmproj=…)` передає
`mmproj or entry.projector`, але в `engine.py` немає викликів `mtmd_*` або
подібних — шлях ні на що не впливає. Реальний `--mmproj` є лише в
`runtime.ServerConfig.command()` для `llama-server` (разом із
`--image-min-tokens 1024`).

У теці `userdata/models` цієї машини лежать
`mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf` (1.34 ГБ) і
`mmproj-Qwen3VL-8B-Instruct-F16.gguf` (1.16 ГБ) — вони не показані як моделі.

## 5. safetensors НЕ підтримується

Це важливо зафіксувати прямо: **рушій не вміє `safetensors`** (і не вміє
PyTorch `.bin`, `.pt`, `.pth`).

Підтвердження:

* `MODEL_SUFFIXES = (".gguf",)` — інші розширення відкидаються ще до
  читання;
* `add_local()` кидає `ModelManagerError("Підтримуються лише файли .gguf.")`;
* `gguf.read_meta()` вимагає магію `GGUF`, інакше
  `GgufError("Це не GGUF-файл (немає магії GGUF).")`;
* `llama_model_load_from_file` — єдиний шлях завантаження ваг у
  `LoadedModel._load()`, і він приймає GGUF.

`safetensors` згадується лише в тестових/демонстраційних даних
`model_hub` (файли, які показує пошук у HF/Civitai). Практичний висновок:
`safetensors` треба конвертувати в GGUF (наприклад, `convert_hf_to_gguf.py`
з llama.cpp) і, за потреби, квантувати (`llama-quantize.exe` є в
`userdata/runtime`). Сам процес конвертації в IDE **не реалізовано**.

## 6. `.part` файли

`.part` — це незавершене завантаження, а не модель. Правила:

* `manager.download()` пише у `<name>.gguf.part` (`destination.with_suffix(
  destination.suffix + ".part")`);
* перейменування в `<name>.gguf` відбувається **тільки** після
  `verify_integrity(part, expected_size=total)`;
* обірване завантаження лишає `.part` навмисно: «Завантаження можна
  продовжити — .part збережено»;
* наступний виклик `download()` з тим самим URL ставить
  `Range: bytes=<розмір .part>-` і дописує (`mode = "ab"`);
* якщо `.part` уже повний (розмір ≥ відомого `total`), докачка не потрібна —
  файл одразу проходить перевірку й перейменовується.

У теці цієї машини є `Qwen3VL-32B-Instruct-Q4_K_M.gguf.part` (990 МБ) —
саме незавершене завантаження, воно не показується в списку моделей, бо
`_scan()` бере лише `*.gguf`.

Що робити з `.part`:

1. **Продовжити** — повторити завантаження з тим самим URL і іменем файлу;
2. **Видалити** — якщо файл непотрібний (він не заважає, але займає місце);
3. **Перевірити вручну** — `.part` не є моделлю, завантажити його як
   модель неможливо: `add_local()` відмовить через розширення.

## 7. Перевірка цілісності файлу

`inspect.verify_integrity(path, expected_size=0)` перевіряє три речі, «які
реально ловлять обірване завантаження»:

1. файл існує й не порожній;
2. розмір збігається з `expected_size` (якщо передано) — інакше
   «не докачано N байт»;
3. магія `GGUF` (`looks_like_gguf`), далі — читабельність метаданих
   (`read_meta_safe`) і `tensor_count > 0` («У файлі немає тензорів — ваги не
   завантажені»).

Повний SHA-256 є окремою функцією `inspect.sha256_of(path, chunk=1<<20,
on_progress=…)` — вона **не** викликається автоматично: на 14-гігабайтному
файлі це десятки секунд.

## 8. Приклад

```python
from blackchpok_ide.native import gguf
from blackchpok_ide.native.inspect import verify_integrity, inspect
from blackchpok_ide.native._quant import ftype_name, bits_per_weight

path = r"C:\AI\blackchpock_ai\userdata\models\qwen2.5-coder-14b-instruct-q4_k_m.gguf"

meta = gguf.read_meta(path)
print(meta.version, meta.tensor_count, meta.kv_count)   # 3 579 29
print(meta.architecture, meta.quant)                    # qwen2 Q4_K_M
print(meta.layer_count, meta.context_length, meta.vocab_size)  # 48 131072 152064
print(meta.has_chat_template, meta.is_vision_projector) # True False

print(bits_per_weight("Q4_K - Medium"))   # 4.8
print(ftype_name(15))                     # Q4_K_M

print(verify_integrity(path)["ok"])       # True
print(inspect(path).summary())
# Qwen2.5 Coder 14B Instruct AWQ · Q4_K_M · 15.0B · ctx 128K · 8.4 ГБ
```

## Підсумок

Рушій читає GGUF версій 1–3 через `mmap`, не вантажачи великі масиви:
архітектура, шари, контекст тренування, голови, словник, шаблон чату й
quantization беруться з метаданих, тому прогноз RAM/VRAM не є здогадкою.
Типи quantization перекладаються з `enum llama_ftype` у людські назви й у
біти на вагу. `mmproj` розпізнається як проєктор і не показується як
модель, але у власному рушії зір **не реалізовано** — `--mmproj` працює
лише з `llama-server`. `safetensors` рушій не підтримує; `.part` — це
незавершене завантаження, яке або докачують, або видаляють.
