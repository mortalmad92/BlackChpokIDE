"""Smoke-тест вікна: створює IDE, прокликує основні дії, закриває.

Запуск:  python tests/smoke_gui.py
Повертає 0, якщо вікно побудувалось і всі перевірені дії не кинули винятків.
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── ЗАХИСТ ВІД ПОШКОДЖЕННЯ СПРАВЖНІХ НАЛАШТУВАНЬ ────────────────────────────
#
# Історія дефекту. Цей скрипт робив ``Settings.load()`` → змінював
# ``engine.auto_start = False`` (щоб не піднімати справжню модель) →
# ``settings.save()``. ``save()`` писав у ФАЙЛ КОРИСТУВАЧА, бо шлях не було
# ізольовано. Після кожного такого прогону локальна модель перестала
# запускатись сама, а в чаті з'являлось «Запусти LM Studio або Ollama».
#
# Тепер усі дані тесту йдуть у тимчасову теку, а запис у справжній конфіг
# заборонено прапорцем ``BLACKCHPOK_NO_SAVE``. Обидва запобіжники — ДО
# імпорту пакета, бо шляхи обчислюються під час імпорту ``config``.
os.environ.setdefault("BLACKCHPOK_HOME", str(Path(tempfile.mkdtemp(prefix="bchp-smoke-"))))
os.environ["BLACKCHPOK_NO_SAVE"] = "1"

failures = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if condition else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures += 1


def _neutralise_dialogs() -> None:
    """У тестах не має бути модальних вікон — інакше процес зависає."""
    import tkinter.messagebox as mb
    import tkinter.simpledialog as sd

    mb.askyesno = lambda *a, **k: True
    mb.askyesnocancel = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    sd.askstring = lambda *a, **k: None
    sd.askinteger = lambda *a, **k: None
    # filedialog теж модальний
    import tkinter.filedialog as fd

    fd.asksaveasfilename = lambda *a, **k: ""
    fd.askopenfilename = lambda *a, **k: ""
    fd.askdirectory = lambda *a, **k: ""


def pump(app, seconds: float) -> None:
    """Крутити цикл подій заданий час, не блокуючись на mainloop()."""
    import time

    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def main() -> int:
    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()
    _neutralise_dialogs()
    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.llm.model = settings.llm.model or "test-model"
    # У тесті не піднімаємо справжню модель: інакше вікно саме запускає
    # llama-server і прогін стає повільним та залежним від диска.
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False
    settings.save()

    from blackchpok_ide.main_window import BlackChpokIDE

    app = BlackChpokIDE(settings)
    app.update_idletasks()
    app.update()
    # ── Тека мусить бути текою ТЕСТУ ─────────────────────────────────────
    # Вікно відновлює робочу теку з активної сесії. Коли в сховищі є чат з
    # іншою текою, застосунок (цілком законно) перемикається на неї — і
    # перевірки «пошук у проєкті» та «скіли знайдено» дивляться не туди.
    # Саме через це smoke падав лише в ізольованому середовищі реєстру
    # (``BLACKCHPOK_HOME`` без збережених чатів дає інший стан, ніж машина
    # розробника).
    if app._project_root() != ROOT:
        app._apply_workspace(ROOT)
        app.update()
    check("робоча тека — тека тесту", app._project_root() == ROOT,
          str(app._project_root()))
    check("вікно створено", app.winfo_exists() == 1, app.title())
    check("меню підключене", bool(app.cget("menu")), f"menu={app.cget('menu')!r}")
    check("панель стану на місці", app.status_bar.winfo_ismapped() == 1)

    # вкладки
    app.open_path(ROOT / "main.py")
    app.update()
    check("відкрито файл у вкладці", app.tabs.current() is not None)
    editor = app.tabs.current()
    check("номери рядків заповнені", editor is not None and int(editor.gutter.index("end-1c").split(".")[0]) > 10)

    # підсвітка прокрутилась без помилок
    editor.text.see("end")
    app.update()
    check("прокрутка файлу", int(editor.text.index("@0,0").split(".")[0]) >= 1)

    # перехід до рядка
    editor.goto_line(25)
    check("перехід до рядка 25", editor.current_line() == 25)

    # пошук у файлі
    found = editor.search("def ")
    check("пошук у редакторі", found)

    # створення нового файлу та вставка тексту
    fresh = app.tabs.new_file()
    fresh.text.insert("1.0", "print('test')\n")
    app.update()
    check("новий файл приймає текст", "print('test')" in fresh.get_text())

    # термінал
    app.terminal.run("echo blackchpok-smoke")
    pump(app, 1.5)
    check("термінал виконав команду", "blackchpok-smoke" in app.terminal.output.get("1.0", "end"))

    # офлайн-агент (без моделі)
    app.agent.agent_settings.offline_fallback = True
    app.agent.llm_settings.model = ""
    app.chat._send("покажи файли")
    pump(app, 2.0)
    history = app.chat.history.get("1.0", "end")
    check("офлайн-агент відповів", "list_dir" in history or "list_dir" in history.lower(),
          history[-120:].replace("\n", " "))

    # Хід агента міг створити/відновити чат, а чат несе ВЛАСНУ робочу теку.
    # Повертаємо теку тесту, інакше «пошук у проєкті» й «скіли» дивляться в
    # чужу папку (на машині розробника — ``C:\AI\site``).
    if app._project_root() != ROOT:
        app._apply_workspace(ROOT)
        pump(app, 0.5)

    # панелі
    app.toggle_sidebar()
    app.update()
    check("бічна панель перемикається", True)
    app.toggle_sidebar()
    app.show_bottom("search")
    app.update()
    app.project_search.search_for("def main")
    app.update()
    check("пошук у проєкті", len(app.project_search._hits) > 0, f"{len(app.project_search._hits)} збігів")

    # налаштування
    app.zoom(1)
    app.zoom(-1)
    check("масштаб шрифту", True)

    # закриття вкладки: спершу зберігаємо у теку тесту, щоб не було діалогу
    temp_file = ROOT / ".buildtmp" / "smoke_new_file.py"
    temp_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file.write_text(fresh.get_text(), encoding="utf-8")
    fresh.path = temp_file
    fresh.modified = False
    closed = app.tabs.close_tab(str(fresh.master))
    app.update()
    check("вкладку закрито", closed and temp_file.exists())
    temp_file.unlink(missing_ok=True)

    # закриття зі змінами має питати (діалог підмінений на «так»)
    dirty = app.tabs.new_file()
    dirty.text.insert("1.0", "x = 1\n")
    dirty.modified = True
    dirty_path = ROOT / ".buildtmp" / "smoke_dirty.py"
    dirty.path = dirty_path
    # вкладка має знати шлях, інакше збереження піде через діалог «Зберегти як»
    app.tabs.paths[str(dirty.master)] = dirty_path
    app.update()
    closed_dirty = app.tabs.close_tab(str(dirty.master))
    check("закриття незбереженої вкладки зберігає файл", closed_dirty and dirty_path.exists())
    dirty_path.unlink(missing_ok=True)

    # ── нові можливості ────────────────────────────────────────────────────
    # 1. Панелі рейки справді перемикаються
    for key in ("explorer", "outline", "skills", "queue", "mcp"):
        app.show_side(key)
        app.update()
        widget = app._side_widgets[key]
        check(f"панель «{key}» показана", widget.winfo_ismapped() == 1)
    check("стан рейки синхронізовано", app._active_side == "mcp")

    # 2. Кнопки закриття вкладок
    extra = app.tabs.new_file()
    app.update()
    before = app.tabs.count()
    tab = app.tabs._tabs[str(extra.master)]
    tab._on_close()
    app.update()
    check("хрестик на вкладці закриває її", app.tabs.count() == before - 1,
          f"{before} → {app.tabs.count()}")

    # 3. Черга задач через панель
    app.show_side("queue")
    # Черга зберігається між запусками — для тесту беремо чистий аркуш.
    app.task_queue.clear()
    app.task_queue.set_paused(False)
    app._update_queue_badge()
    app.update()
    # Пауза, щоб автозапуск не «з'їв» задачу до перевірки.
    app.task_queue.set_paused(True)
    app.agent.agent_settings.queue_auto_run = False
    app.queue_panel.entry.delete(0, "end")
    app.queue_panel.entry.insert(0, "перевір проєкт")
    app.queue_panel._add()
    pump(app, 0.4)
    active = [t for t in app.task_queue.tasks
              if t.status in ("очікує", "виконується")]
    check("задача додана в чергу", len(active) == 1,
          f"{len(active)} активних із {len(app.task_queue.tasks)}")
    check("бейдж черги оновився", "1" in app.chat.mode_label.cget("text"),
          app.chat.mode_label.cget("text"))
    app.task_queue.clear()
    app._update_queue_badge()
    app.update()

    # 4. Скіли
    app.show_side("skills")
    app.skills_panel.reload()
    app.update()
    check("скіли знайдено", len(app.skill_book.skills) >= 1,
          ",".join(s.name for s in app.skill_book.skills))

    # 5. Контекстна панель показує вкладки
    app.context.refresh()
    app.update()
    check("контекст знає про відкриті вкладки", len(app.tabs.tab_titles()) >= 1,
          f"{len(app.tabs.tab_titles())} вкладок")

    # 6. Чат: markdown і виклики інструментів малюються без помилок
    app.chat.new_chat()
    app.chat._add_assistant("Текст із `кодом`\n\n```python\nx = 1\n```\n\n- пункт")
    app.update()
    body = app.chat.transcript.get()
    check("markdown у чаті відмальовано", "пункт" in body, body[-60:].replace("\n", " "))

    # 7. Термінал: жива сесія приймає команди й повідомляє код виходу
    app.show_bottom("terminal")
    app.terminal.run("echo smoke-alive")
    pump(app, 1.5)
    terminal_out = app.terminal.output.get("1.0", "end")
    check("термінал виконав команду в живій сесії",
          "smoke-alive" in terminal_out and "код завершення: 0" in terminal_out,
          terminal_out.strip().splitlines()[-1][:60])
    check("сесія терміналу запущена",
          app.terminal.session is not None and app.terminal.session.running)

    app.agent.cancel()
    app.destroy()
    print()
    print("Smoke-тест:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)
