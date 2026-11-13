# Архітектура рендерингу чату в BLACKCHPOK IDE

Документ описує **поточний** шлях тексту моделі до екрана, показує, де
саме губиться структура, і формулює вимоги до моделі повідомлення. Усі
назви й номери рядків перевірені читанням коду станом на 08.11.2026, 21:45.

---

## 1. Як зараз текст моделі доходить до екрана

### 1.1 Ланцюг подій

```
AgentRunner._loop()            agent.py:1751
   ├─ _emit("token", piece)    agent.py:1731  (у on_text)
   ├─ _emit("assistant", …)    agent.py:1829
   ├─ _emit("tool_call", …)    agent.py:1907
   └─ _emit("tool_result", …)  agent.py:1926
        │  черга queue.Queue[AgentEvent]
        ▼
ChatPanel._poll_events()       chat_panel.py:1997   кожні 90 мс
        ├─ _handle_event(event) chat_panel.py:2024
        └─ _flush_stream()      chat_panel.py:2087
```

`AgentEvent(kind, text, data)` — `agent.py:347`. Дозволені `kind`:
`status | assistant | tool_call | tool_result | error | done | token`, а
фактично ще `reasoning`, `reasoning_token`, `stats`.

### 1.2 Розподіл подій у `_handle_event`

| `kind` | Куди йде | Рядок |
|---|---|---|
| `assistant` | `_add_assistant(...)` | `chat_panel.py:2030` |
| `token` | `_on_token(piece)` → накопичення | `:2035`, `:2073` |
| `reasoning_token` | `_on_reasoning_token(piece)` | `:2037` |
| `tool_call` | `_add_tool_call` → журнал роботи | `:2039`, `:2633` |
| `tool_result` | `_add_tool_result` | `:2041`, `:2650` |
| `status` | `_add_status` + `_arrow_thought` | `:2043` |
| `stats` | `stats_bar.set_stats` | `:2053`–`2055` |
| `error` | `_note(kind="error")` | `:2057` |
| `done` | `_finish_work_log`, `set_busy(False)` | `:2059`–`2069` |

Дубль гілки `reasoning` **виправлено**: у `_handle_event` було дві гілки
`elif event.kind == "reasoning"`, і друга була недосяжною, бо Python
зупиняється на першому збігу. Через це `_arrow_thought()` для думок
моделі не викликався взагалі. Тепер одна гілка робить обидві речі:
пише думки в згорнутий журнал роботи (`_add_reasoning`) і показує
короткий рядок у зоні над формою (`_arrow_thought`).

### 1.3 Стрімінг більше НЕ втрачає структуру

Раніше `_flush_stream()` вставляв сирий рядок, і під час генерації
користувач бачив `**…**` та бектики. **Тепер це виправлено**:
`_flush_stream()` (`chat_panel.py:2087`) створює власний рендерер
`self._stream_renderer = markdown_view.MarkdownRenderer(...)` (`:2129`),
викликає `configure_tags()` (`:2132`) і перемальовує через
`renderer.render(text, clear=True)` (`:2140`). Коментар у коді (`:2090`–
`2097`) прямо описує це як виправлення: «поки модель писала, користувач
бачив сирий markdown… Тепер форматування стабільне від першого токена».

Незакритий блок коду — нормальний стан стріму: `parse_markdown` вважає
його кодом до кінця тексту (`markdown_view.py:155`, `:183`–`185`).

Каскадний шлях: `_add_assistant()` (`chat_panel.py:2183`) →
`_end_stream()` (`:2153`) прибирає тимчасову картку й повертає повний
текст → `_render_markdown()` (`:2225`) створює новий `tk.Text`,
`MarkdownRenderer` (`:2233`), `renderer.render(text, clear=True)` (`:2235`),
збирає блоки в `self._pending_code` (`:2238`). Дії картки — `:2220`–`:2222`.

### 1.4 Що вміє `markdown_view` (819 рядків)

| Функція / клас | Рядки | Роль |
|---|---|---|
| `Segment` | `60`–`74` | `kind`, `text`, `language`, `level`, `index` |
| `parse_markdown()` | `123`–`260` | чистий розбір без tkinter |
| `parse_inline()` | `303`–`324` | наголоси, інлайн-код, посилання |
| `plain_text()` | `332`–`362` | markdown без маркерів |
| `_LANGUAGE_EXT` | `376`–`395` | мова з шапки блоку → розширення для `syntax` |
| `code_language()` | `408` | назва мови за іменем файлу |
| `MarkdownRenderer` | `416`–`819` | малювання теґами |
| `COLLAPSE_AFTER` | `432` | 40 рядків до згортання блоку коду |
| `_HIGHLIGHT_LIMIT` | `369` | 24 000 символів — межа підсвітки |

`Segment.kind` фактично: `text`, `code`, `heading`, `bullet`, `quote`,
`table`, `hr` (`markdown_view.py:63`–`64`, `:751`–`768`). Значення
`rule_code` оголошене й обробляється, але `parse_markdown()` його **ніколи
не створює** — мертва гілка.

### 1.5 Де ще губиться структура

| Проблема | Причина в коді | Наслідок |
|---|---|---|
| Вкладені списки сплющуються | `_BULLET_RE` не враховує відступ (`markdown_view.py:83`), `_emit_bullet` малює один рівень (`:704`) | підпункти стають сусідами |
| Таблиця без вирівнювання | `_emit_table` рахує ширину за `len(cell)` у **символах** (`:726`–`742`), не в пікселях | кирилиця й латиниця «їдуть» |
| Довгі рядки коду переносяться | `tk.Text` створюється з `wrap="word"` (`chat_panel.py:2227`) | код ламається замість горизонтальної прокрутки |
| Посилання не клікаються | теґ `md_link` є, але `tag_bind` немає ніде в проєкті | URL видно, перейти не можна |
| Довга історія обрізається | `HISTORY_RENDER_LIMIT = 200` (`chat_panel.py:38`), `MAX_CANVAS_HEIGHT = 20000` (`widgets.py:380`) | старі повідомлення не видно, лише нотатка (`:1143`) |
| Висота картки обмежена | `_HARD_TEXT_LINES = 400` (`:47`), `_DEFAULT_BODY_LINES = 60` (`:42`) | дуже довгий текст обрізається по висоті |

Те, що вже зроблено: підсвітка синтаксису в чаті (`_insert_code`,
`markdown_view.py:629`, теґи `syn_*` через `_configure_syntax_tags`, `:664`),
згортання довгого блоку коду з чесним підписом (`:610`–`626`).

---

## 2. Модель `MessagePart`

Замість «рядка тексту + окремих карток» потрібна типізована модель,
узгоджена з полями, які вже є в `Segment` (`markdown_view.py:60`),
`Observation` (`tool_orchestrator.py:109`) і `ChatMessage.meta`
(`chat_store.py:214`).

```ts
type MessagePart =
  | TextPart
  | CodePart
  | DiffPart
  | FileReferencePart
  | ToolStatusPart;

interface PartBase {
  id: string;              // стабільний ідентифікатор у межах повідомлення
  index: number;           // порядок у повідомленні
  createdAt: number;       // epoch секунди, як у ChatMessage.timestamp
}

interface TextPart extends PartBase {
  kind: "text";
  markdown: string;        // сирий markdown; рендерер розбирає сам
}

interface CodePart extends PartBase {
  kind: "code";
  language: string;        // info-рядок fence; "" якщо не вказано
  code: string;            // без fence-маркерів
  closed: boolean;         // false, поки fence не закрито (стрімінг)
  highlight: boolean;      // чи застосовувати syntax.py
  collapsedAfter: number;  // 40 — COLLAPSE_AFTER
}

interface DiffPart extends PartBase {
  kind: "diff";
  path: string;            // відносно робочої теки
  oldText: string;
  newText: string;
  added: number;           // рахує make_diff_lines / count_line_diff
  removed: number;
  collapsed: boolean;      // стартовий стан згортання
  truncatedAfter: number;  // 400 — межа показу, як у _show_diff
}

interface FileReferencePart extends PartBase {
  kind: "file_reference";
  path: string;
  line?: number;
  exists: boolean;         // перевірено на диску на момент рендеру
}

interface ToolStatusPart extends PartBase {
  kind: "tool_status";
  tool: string;            // напр. "read_file"
  callId: string;          // Observation.call_id
  state: "running" | "ok" | "error" | "rejected";
  summary: string;         // Observation.for_user
  suspicious: string[];    // Observation.suspicious — не показувати дослівно
}
```

Що з цього вже працює в коді: `ToolStatusPart.summary` — це
`Observation.for_user` (`tool_orchestrator.py:140`) через
`summarise_for_user()` (`:202`), яке віддає **одне людське речення без
JSON і стектрейсів**. `ToolStatusPart.state` відповідає полям `ok`,
`rejected`, `duplicate` (`:117`–`125`). `ChatMessage.meta` уже є вільним
словником (`chat_store.py:214`), тож `meta["parts"]` не ламає сумісність:
`from_dict` відкидає все, що не є словником (`:239`–`243`).

Чого бракує: `CodePart.closed` і `DiffPart` як частини повідомлення — diff
досі окрема картка (`_show_diff`, `chat_panel.py:2260`).

---

## 3. Вимоги до Markdown-рендерера

### 3.1 Обов'язковий мінімум

| Елемент | Стан зараз | Вимога |
|---|---|---|
| Заголовки `#`…`######` | `md_h1`…`md_h3`, рівні 4–6 зводяться до 3 (`markdown_view.py:698`–`702`) | зберегти, додати відступ для 4–6 |
| Марковані списки `-`,`*`,`+` | працює (`:83`, `:704`) | додати рівні вкладеності за відступом |
| Нумеровані `1.`, `1)` | працює, `prefix` нормалізується (`:708`–`709`) | зберігати вихідний номер |
| Цитати `>` | працює, склеює сусідні рядки (`:235`–`246`) | додати вкладені цитати |
| Таблиці (pipe) | працює, `_starts_table` (`:112`) | вирівнювання в пікселях, не в символах |
| `inline code` | працює, включно з ` `` ` (`:87`) | без змін |
| Fenced-блоки ``` і ~~~ | працює, включно з незакритим (`:155`–`195`) | зберігати `closed` |
| Горизонтальна лінія | працює (`:218`–`222`) | без змін |
| Посилання | видно як `підпис (url)` (`:273`) | **клікабельні** через `tag_bind` |
| Горизонтальна прокрутка коду | немає, `wrap="word"` | `wrap="none"` + `xscrollcommand` |

### 3.2 Мови підсвітки

Підсвітка **вже підключена до чату**: `_insert_code()`
(`markdown_view.py:629`–`662`) бере `syntax.language_for(f"x.{ext}")`
(`:643`) і малює теґами `syn_<tag>`. Мову з шапки блоку зводить
`_LANGUAGE_EXT` (`:376`–`395`) — це ширший перелік, ніж у редакторі, бо
моделі пишуть по-різному (`python`, `py`, `Python3`, `bash`, `shell`):

| Група | Ключі в шапці |
|---|---|
| Python | `py`, `python`, `python3`, `pyi` |
| JavaScript | `js`, `javascript`, `node`, `mjs` |
| TypeScript | `ts`, `typescript`, `tsx`, `jsx` |
| Дані й розмітка | `json`, `jsonc`, `jsonl`, `html`, `htm`, `xml`, `svg` |
| Стилі | `css`, `scss`, `less` |
| SQL | `sql`, `sqlite` |
| Оболонки | `sh`, `bash`, `shell`, `zsh`, `ps1`, `powershell`, `pwsh`, `bat`, `cmd` |
| Конфіги | `yaml`, `yml`, `toml`, `ini`, `cfg`, `conf` |
| Документи | `md`, `markdown`, `mdx` |
| Системні мови | `c`, `h`, `cc`, `cpp`, `c++`, `hpp`, `cs`, `csharp`, `java`, `rs`, `rust`, `go`, `golang`, `kt`, `kotlin`, `swift`, `dart` |

Обмеження: блоки довші за `_HIGHLIGHT_LIMIT = 24_000` символів
(`:369`) малюються без підсвітки — свідомий компроміс (`:632`–`634`).

### 3.3 Згортання, копіювання, прокрутка

| Вимога | Як зроблено / що є |
|---|---|
| Згортання блоку коду | є: `COLLAPSE_AFTER = 40` (`:432`), заголовок «показано 40 з N рядків» (`:616`), підпис «… ще N рядків» (`:622`–`626`) |
| Копіювання блоку | `renderer.copy_code(index)` (`:805`); меню `_code_menu` (`chat_panel.py:2425`) |
| Копіювання всієї відповіді | `self._copy(self.transcript.get())` (`:2434`) |
| «Вставити в редактор» | `_insert_last_code` (`:2798`) бере **останній** блок |
| Горизонтальна прокрутка | **немає** — `wrap="word"` |
| Згортання diff | `_show_diff.toggle` через `pack`/`pack_forget` (`:2311`–`2323`) |
| Індекс блоку під курсором | `_code_index_at` (`:2437`–`2444`), `tag_ranges("md_code_header")` |

---

## 4. Стрімінг

### 4.1 Порядок подій, який гарантує код

```
status       "Запит до <модель>…"        agent.py:1583
token        …багато…                    agent.py:1731
reasoning_token …                        agent.py:1734
stats                                    agent.py:1791
reasoning    (повний блок)               agent.py:1799
assistant    (проміжний або фінальний)   agent.py:1829
tool_call                                agent.py:1907
tool_result                              agent.py:1926
… повторення …
done         ok=…, degraded=…            agent.py:1620
```

`assistant` із `final=False` — коментар моделі між кроками, не відповідь;
`_add_assistant` відправляє його в журнал роботи (`chat_panel.py:2196`–
`2203`).

### 4.2 Відкритий code fence

Під час стріму текст малює той самий `MarkdownRenderer`
(`chat_panel.py:2129`), тож незакритий fence одразу стає блоком коду:
`parse_markdown` трактує його як код до кінця тексту
(`markdown_view.py:155`, `:183`–`185`), а `_emit_code` (`:598`) малює
шапку, тіло й підвал. Коментар у `_flush_stream` (`chat_panel.py:2096`–
`2097`) фіксує саме це: «Незакритий блок коду — звичайний стан стріму…
тож блок не «стрибає»».

Ціна: `render(clear=True)` перемальовує весь текст на кожен тік
(`:2138`–`2140`), тобто O(n) на кожні 90 мс (`:2010`). Для довгих
відповідей це варто оптимізувати — тримати стабільні закриті блоки й
перемальовувати лише останній відкритий.

### 4.3 Часткові tool-call аргументи

Під час стріму аргументи приходять шматками:
`slot["arguments"] += str(function.get("arguments"))`
(`llm_client.py:1300`). Вони **не** потрапляють у чат:

* `_looks_like_tool_json()` (`llm_client.py:79`) притримує текст, що
  починається з `{`, ` ```json `, `<tool_call>`, `<tools>` (`:94`–`114`);
* назовні віддається лише те, що вже не може бути викликом (`:1277`–`1282`);
* після стріму залишок «притриманого» віддається, якщо виклику не стало
  (`:1353`–`1354`).

Додатковий шар — `response_engine.strip_protocol()` (`:111`): він чистить
фінальний текст від тегів, рамок агента й JSON-викликів **перед показом**.

### 4.4 Що НЕ можна показувати в чаті

| Що | Чому | Де відсікається |
|---|---|---|
| Сирий JSON виклику | користувач бачить `{"name": …}` | `strip_tool_json()` (`llm_client.py:338`), `strip_protocol()` (`response_engine.py:111`) |
| `<tool_call>`, `<tools>`, `<\|im_start\|>` | службові теги | `llm_client.py:355`–`357`; `response_engine.py:121`–`123` |
| Рамки, які додає сам агент | вони для моделі, не для людини | `response_engine.py:125`–`127` (`_AGENT_FRAME_RE`) |
| Повний вивід інструмента | «стіна» на 2000 символів | `_add_tool_result` показує 90 символів (`chat_panel.py:2682`), повний — у вікні `_show_full` (`:2735`) |
| Системні повідомлення | це не діалог | `_context_from_messages` їх пропускає (`main_window.py:3420`–`3422`) |
| Обіцянки дії | шум між викликами | `response_engine.promises_action()` (`:344`), приховування на `agent.py:1809` |
| «Запит до <модель>…» | дублює заголовок журналу | `_add_status` (`chat_panel.py:2610`–`2614`) |
| Chain-of-thought | окремий канал | `reasoning` іде в `_arrow_thought`, не в стрічку |
| Аргументи ін'єкції дослівно | можуть бути інструкцією | `Observation.suspicious` — лише лічильник у `report()` |

---

## 5. Diff-рендерер

### 5.1 Що є сьогодні

| Частина | Функція | Рядки |
|---|---|---|
| Порівняння | `difflib.unified_diff(..., n=2)` | `chat_panel.py:117`–`120` |
| Рядки | `make_diff_lines()` → пари «тип, текст», тип — `add`/`del`/`ctx` | `:115`–`129` |
| Підрахунок | `added`, `removed` | `:2272`–`2273` |
| Заголовок | `diff · <файл>` + `+N −M` | `:2282`–`2286` |
| Тіло | до 400 рядків, кожен ≤ 240 символів | `:2293`–`2306` |
| Обрізання | «… і ще N рядків» | `:2307`–`2309` |
| Згортання | клік по заголовку | `:2311`–`2323` |

Джерело «до» і «після»: `_maybe_show_diff()` (`chat_panel.py:2696`–`2733`)
бере поточний файл і `.bak`, який кладе `workspace.write_text_file()`
(`workspace.py:118`–`127`). Якщо `.bak` немає — diff не малюється (`:2720`).

### 5.2 Що треба виправити

1. **Рядки — `tk.Label` у `tk.Frame`** (`:2293`–`2306`). На 400 рядків це
   800+ віджетів; краще один `tk.Text` із теґами `diff_add`/`diff_del`/`diff_ctx`.
2. **Обрізання по 240 символах** (`:2304`) рве довгі рядки коду. Потрібна
   горизонтальна прокрутка.
3. **Немає номерів рядків**: `difflib` дає їх у хунках, але
   `make_diff_lines` відкидає перші два елементи (`list(diff)[2:]`) і не
   зберігає `@@`.
4. **Немає підсвітки синтаксису** всередині diff, хоч механізм `syn_*` уже
   є в `markdown_view.py:664`.
5. **Порожній diff не оброблено**: `_maybe_show_diff` виходить раніше
   (`:2724`–`2725`), але `_show_diff` напряму такого захисту не має.

### 5.3 Вимоги до нового diff-рендерера

| Вимога | Реалізація |
|---|---|
| Один віджет на блок | `tk.Text` + теґи, `state="disabled"` |
| Номери рядків обох версій | зберегти `@@ -a,b +c,d @@` із `difflib` |
| Підсвітка за мовою | `syntax.language_for()` (`syntax.py:174`), як у `_insert_code` |
| Горизонтальна прокрутка | `wrap="none"` + `xscrollcommand` |
| Згортання | `tag_configure("diff_body", elide=True)` |
| Межа показу з підписом | 400 рядків, як у `DiffPart.truncatedAfter` |
| Копіювання диффу | `difflib.unified_diff` як текст у буфер |
| Безпека | ніколи не показувати вміст файлу поза робочою текою |

---

## 6. Збереження й відновлення після перезапуску

### 6.1 Що зберігається

| Сутність | Поля | Рядки |
|---|---|---|
| `ChatMessage` | `role`, `text`, `timestamp`, `meta` | `chat_store.py:203`–`243` |
| `Chat` | `id`, `title`, `workspace`, `created_at`, `updated_at`, `messages`, `archived`, `pinned`, `model`, `effort`, `status`, `context` | `chat_store.py:251`–`333` |
| Файл сховища | `app_data_dir()/chats.json`, атомарний запис через `os.replace` | `chat_store.py:7`–`12`, `:193` |

`meta` — словник довільних даних (`chat_store.py:206`–`208`). Саме сюди
треба писати `MessagePart`: `meta["parts"] = [...]`. Сумісність не
ламається, бо `from_dict` відкидає все, що не є словником (`:239`–`243`).

### 6.2 Контекст агента

| Крок | Функція | Рядки |
|---|---|---|
| Знімок сесії | `AgentSession.snapshot()` | `agent.py:380`–`387` |
| Збереження | `ChatStore.store_context()` → `_clean_context()` | `chat_store.py:745`–`774` |
| Обмеження | `CONTEXT_KEEP = 120` | `chat_store.py:115`, `:153` |
| Відновлення | `ChatStore.load_context()` | `chat_store.py:776`–`781` |
| Застосування | `AgentSession.restore()` + `trim()` | `agent.py:389`–`425` |
| При перемиканні | `_save_chat_context` / `_load_chat_context` | `main_window.py:3357`, `:3372` |
| При повідомленні | `_remember_message` → `_save_chat_context` | `main_window.py:3504`–`3520` |

`_clean_context()` зберігає `tool_calls` і `tool_call_id`
(`chat_store.py:140`–`151`) — без цього наступний запит містив би
tool-результат без виклику, і сервер відповідав би 400.

### 6.3 Що губиться при перезапуску

| Втрата | Причина |
|---|---|
| `language` блоку коду | `ChatMessage.text` — плаский текст, `Segment` не зберігається |
| Diff-картки | вони не повідомлення; у `text` лишається результат інструмента |
| Роздуми (`reasoning`) | у сховище не пишуться взагалі |
| Посилання на «Результат інструмента» | `_show_full` бере текст із замикання, не з диска |
| Журнал роботи і стан згортання | `WorkLog` живе лише в пам'яті віджета |
| Метрики ходу | `TurnTrace` уже пишеться (`trace_store.py:303`), але не відновлюється в чат |

Висновок: щоб відновлення було точним, `MessagePart[]` треба писати в
`meta["parts"]`, а `text` лишати як «плаский» варіант для
`export_markdown` (`chat_store.py:798`) і сумісності зі старими версіями.

---

## 7. Чеклист ручної перевірки рендерера (10 пунктів)

1. **Заголовки.** Надіслати `# H1`, `## H2`, `### H3`. Перевірити: H1
   більший і білий, H2 акцентний, H3 звичайний, між ними є відступи
   (`md_h1` spacing1=10, `markdown_view.py:426`).
2. **Список із вкладеністю.** `- a`, `  - b`, `1. c`. Перевірити відступ
   для `b`; якщо немає — вкладеність не підтримується (поточний стан).
3. **Таблиця з кирилицею.** Колонки «Мова / Рівень», рядок «Python /
   високий». Перевірити рівність вертикальних рисок (сьогодні можуть
   «їхати» через `len()`).
4. **Inline-код із бектиками.** `` `a` `` і `` ``код із ` `` ``.
   Перевірити: обидва теґом `md_inline_code`, без зайвих бектиків.
5. **Незакритий блок коду.** Три бектики, мова, два рядки без закриття.
   Перевірити: після ходу це `Segment(kind="code")`, а не текст.
6. **Блок коду з довгим рядком.** Рядок на 200 символів. Сьогодні
   `wrap="word"` ламає його (дефект); очікування — горизонтальна прокрутка.
7. **Підсвітка мови.** Блок ```python``` і блок ```js```. Перевірити, що
   ключові слова пофарбовані (теґи `syn_keyword`), а невідома мова
   (` ```brainfuck `) малюється одним кольором без помилки.
8. **Згортання довгого блоку.** Блок на 60 рядків. Перевірити: показано
   40, у шапці «показано 40 з 60 рядків», у підвалі «… ще 20 рядків».
9. **Диф після правки.** Попросити `edit_file` для файлу з `.bak`.
   Перевірити: картка `diff · <файл>` із `+N −M`, згортання кліком, `+`
   зелені, `−` червоні (`theme.DIFF_ADD_BG` / `DIFF_DEL_BG`).
10. **Після перезапуску.** Закрити IDE, відкрити, вибрати той самий чат.
    Перевірити: повідомлення на місці, порядок, назва й контекст
    відновлені (`_load_chat_context`, `main_window.py:3372`).

Додатково: змінити тему й перевірити, що картки перемальовуються —
`retheme()` (`chat_panel.py:2829`) перебирає `card.renderer` і викликає
`render(content, clear=True)`.
