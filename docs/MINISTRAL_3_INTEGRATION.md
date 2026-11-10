# Ministral 3 14B — інтеграція

Дата: 2026-11-09. Усе нижче **перевірено реальним запуском** на RTX 3060 12 ГБ,
а не взято з назв файлів.

---

## 1. Що є на Hugging Face (перевірено HF API)

| Репозиторій | Формат | Файли |
|---|---|---|
| `mistralai/Ministral-3-14B-Instruct-2512` | safetensors | 17, `Mistral3ForConditionalGeneration` |
| `mistralai/Ministral-3-14B-Instruct-2512-GGUF` | **GGUF** | Q4_K_M 7.67 ГБ, Q5_K_M, Q8_0, BF16 |
| `mistralai/Ministral-3-14B-Reasoning-2512-GGUF` | **GGUF** | те саме + reasoning checkpoint |
| `ggml-org/Ministral-3-14B-Instruct-2512-GGUF` | GGUF | Q8_0 |

### Мультимодальність підтверджена метаданими

`config.json` офіційного репозиторію:

```json
"architectures": ["Mistral3ForConditionalGeneration"],
"model_type": "mistral3",
"vision_config": { "model_type": "pixtral", "hidden_size": 1024, "image_size": 1540 },
"image_token_index": 10,
"spatial_merge_size": 2,
"text_config": { "max_position_embeddings": 262144 }
```

Отже модель справді мультимодальна (Pixtral vision encoder + projector), і
заявлене вікно 256K підтверджене в конфігу.

### Проєктор (mmproj) існує, але з незвичною назвою

```
mistralai/…-Instruct-2512-GGUF:  Ministral-3-14B-Instruct-2512-BF16-mmproj.gguf  (0.82 ГБ)
ggml-org/…-Instruct-2512-GGUF:   mmproj-Ministral-3-14B-Instruct-2512-Q8_0.gguf  (0.44 ГБ)
```

**Це пастка.** Офіційний файл має `mmproj` у **кінці** імені. Код, який шукає
лише `mmproj-*.gguf`, його не знайде, і модель запуститься без зору — при
цьому виглядатиме, що все гаразд.

`model_hub.is_vision_projector()` тепер приймає обидві форми, а
`vision_projector_for()` має другий прохід через розпізнавання, а не лише
`glob` за підрядком.

---

## 2. Реальний запуск

```
--model  Ministral-3-14B-Instruct-2512-Q4_K_M.gguf      (7.67 ГБ)
--mmproj Ministral-3-14B-Instruct-2512-BF16-mmproj.gguf (0.82 ГБ)
--jinja --no-webui --ctx-size 8192 --n-gpu-layers 999
--cache-type-k q8_0 --cache-type-v q8_0 --image-min-tokens 1024
```

Результат: `READY: ministral-14b` без жодної помилки.

---

## 3. Зір працює (доведено)

Поданій картинці (скриншот хаба моделей) модель відповіла:

> ### Заголовки карток:
> 1. **Ministral 3 14B Instruct**
> 2. **Ministral 3 14B Reasoning**
>
> ### Підписи під зеленими значками:
> - Значок молотка — **Tool Calling**, *Виклик інструментів*
> - Значок ока — **Vision**, *Аналіз зображень*
> - Значок з кругом і лініями — **Reasoning**, *Складне міркування*
>
> Також є пояснення, що зелені значки з'являтимуться лише після успішної
> перевірки сумісності runtime та тестування відповідної функції.

Модель прочитала дрібний український текст і навіть відтворила нижній
підпис. Це означає, що зображення пройшло preprocessing і vision encoder.

---

## 4. Native tool calling працює (доведено)

Запит: «Покажи вміст папки blackchpok_ide», дві схеми (`list_dir`, `read_file`).

```json
tool_calls: [{"type": "function",
              "function": {"name": "list_dir",
                           "arguments": "{\"path\": \"blackchpok_ide\"}"}}]
content: ""
```

Модель обрала правильний інструмент, структуровані аргументи, без тексту
навколо. Формат — стандартний OpenAI `tool_calls`, який розуміє
`llm_client.ChatResult`.

---

## 5. Чесна таблиця можливостей

| Варіант | 🔨 Інструменти | 🧠 Reasoning | 👁 Vision |
|---|---|---|---|
| 14B Instruct | ✅ перевірено | ❌ не окрема reasoning-версія | ✅ перевірено (з mmproj) |
| 14B Reasoning | ✅ (той самий формат) | ✅ окремий checkpoint | ✅ (той самий mmproj) |
| 14B Base | не заявляємо | не заявляємо | лише за наявності mmproj |

**Важливо:** значок Vision ставиться лише тоді, коли файл `mmproj` реально
лежить на диску (див. `MODEL_CAPABILITIES.md`). Без нього модель працює як
текстова, і IDE це показує.

---

## 6. Chat template

Запуск із `--jinja` бере шаблон із GGUF-метаданих, а не з припущень про
родину. Офіційний репозиторій містить `chat_template.jinja` і
`SYSTEM_PROMPT.txt` — тобто шаблон не потрібно вгадувати. Це принципово:
шаблон Qwen або Llama зламав би маркери tool calling Ministral.

---

## 7. Пам'ять

| Складова | Розмір |
|---|---|
| ваги Q4_K_M | 7.67 ГБ |
| mmproj BF16 | 0.82 ГБ |
| KV (8K, q8_0) | ≈0.8 ГБ |
| накладні | 0.7 ГБ |
| **разом** | **≈10.0 ГБ** при бюджеті 11.0 ГБ |

Контекст 8K обраний навмисно: 256K із конфігу в 12 ГБ VRAM не влізе.
`hardware.fit()` підвищує контекст поступово й переходить на KV у RAM лише
за явним запитом користувача.

---

## 8. Як підключити

1. «Хаб моделей» → вставити `mistralai/Ministral-3-14B-Instruct-2512-GGUF`.
2. Завантажити `Q4_K_M` **і** `…-BF16-mmproj.gguf` (проєктор обов'язковий
   для зору).
3. Натиснути «Запустити».
4. Перевірити статус: має бути «зір: <назва проєктора>».

Для reasoning-варіанта — окремий репозиторій
`mistralai/Ministral-3-14B-Reasoning-2512-GGUF`. Це **інший checkpoint**, а не
режим; змішувати їх не можна.

---

## 9. Обмеження

* Перевірено на `llama.cpp b12129` (CUDA). Інші збірки можуть поводитись
  інакше.
* Офіційний `ggml-org` GGUF містить лише Q8_0 (13.37 ГБ) — для 12 ГБ VRAM
  це забагато, тому беремо `mistralai` Q4_K_M.
* Автоматичного тесту можливостей (подати картинку й перевірити опис) поки
  немає: перевірка обмежена фактом наявності проєктора й цим ручним тестом.
