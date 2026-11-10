# Захоплення екрана

Дата: 2026-11-09. Перевірено реальним знімком.

---

## 1. Що працює

`blackchpok_ide/screenshot.py` — власна реалізація на Win32 **без Pillow**:

| Функція | Призначення |
|---|---|
| `capture_screen(path, rect=None, hwnd=0)` | увесь екран або прямокутник |
| `capture_window(info, path)` | конкретне вікно за HWND |
| `find_windows(pattern)` | пошук вікон за заголовком, класом або PID |
| `to_png(buffer)` | кодування BMP → PNG через `zlib` |
| `shrink_png_file(src, dst, limit_mb)` | зменшення великих знімків |

Вікна знімаються через `PrintWindow` із `PW_RENDERFULLCONTENT`, тому
захоплюється й вміст, що частково поза екраном.

### Реальний прогін

```
screen: Capture(ok=True, path='…\cap_test.png', width=3440, height=1440)
        exists: True size: 317596
win: «Program Manager» · клас Progman · 3440×1440
win: «blackchpock_ai – Файловий провідник» · клас CabinetWClass · 3440×1408
win: «# BLACKCHPOK IDE — AUTONOMOUS» · клас Chrome_WidgetWin_1 · 3440×1400
win: «Написати промт для IDE - Google Chrome» · клас Chrome_WidgetWin_1
```

Знімок відкрито й перевірено візуально: на ньому справді видно робочий стіл.
`capture_screen` повертає **реальний PNG-артефакт**, а не рядок «успішно».

---

## 2. Інструменти для моделі

`agent_tools.py` надає моделі:

* `app_screenshot(title="")` — екран або вікно за частиною заголовка;
* `window_screenshot(title, index)` — конкретне вікно;
* `project_screenshot` — вікно проєкту;
* `web_screenshot` — сторінка через CDP;
* `app_windows` — перелік вікон (щоб модель знала, що захоплювати);
* `app_click` — натискання за координатами.

Кожен повертає **шлях до PNG**, а агент (`_attach_capture`) ставить цей шлях
у чергу `pending_images`, звідки він перетворюється на `image_url`.

---

## 3. Як зображення доходить до моделі

```
capture_screen → PNG на диску
        ↓
_attach_capture()            agent.py  ← лише якщо vision_enabled
        ↓
session.pending_images
        ↓
AgentSession.build() → llm_client.image_message()
        ↓
{"type": "image_url", "image_url": {"url": "data:image/png;base64,…"}}
        ↓
llama-server --mmproj … → vision encoder
```

Великі знімки (>8 МБ) зменшуються через `shrink_png_file`, інакше запит
перевищує ліміт локального сервера.

---

## 4. Прикріплення користувачем (виправлено)

Кнопка `＋` у полі введення раніше **читала будь-який файл як текст**:

```python
content = Path(path).read_text(encoding="utf-8", errors="replace")
```

Для PNG це давало сміття в полі введення, а модель не бачила нічого.

Тепер `_attach_file()` розрізняє типи:

* `.png .jpg .jpeg .webp .bmp .gif` → `_attach_image()` → `pending_images`;
* решта → блок коду в полі введення, як раніше.

Якщо модель без зору, показується чесне повідомлення, а не тиха відмова.

---

## 5. Безпека й приватність

* Захоплення ініціює **користувач** (кнопка) або **агент** явним викликом
  інструмента. Постійного фонового запису екрана немає.
* Захищений вміст Windows (DRM-вікна, екрани з `SetWindowDisplayAffinity`)
  не захоплюється — це системне обмеження, його не обходимо.
* Маскування паролів і чутливих полів **не реалізовано**. Це відкритий пункт.

---

## 6. Чого немає

| Можливість | Стан |
|---|---|
| `capture_region` як окремий інструмент | немає (є `rect` у `capture_screen`) |
| `capture_display` (вибір монітора) | немає (лише весь віртуальний екран) |
| `capture_live_preview` | частково (`web_screenshot` через CDP) |
| `compare_screenshots` | немає |
| `crop_image` | немає |
| Multi-scale аналіз (огляд + crops) | немає |
| Індикатор активного захоплення | немає |
| Маскування чутливих полів | немає |

Ці пункти описані в `VISUAL_AGENT.md` і `SCREENSHOT_TO_CODE.md` як наступні
кроки — не як виконана робота.
