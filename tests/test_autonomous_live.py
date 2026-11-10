"""Наскрізна перевірка автономного режиму у СПРАВЖНЬОМУ вікні IDE.

Перевіряє те, що видно користувачу: об'єднаний список чатів, іконки
закриття й архівування, панель автономного режиму, пріоритет задач
користувача й коректну зупинку зі збереженням файлів.

Запуск: python tests/test_autonomous_live.py
"""

from __future__ import annotations

import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

failures = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if condition else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures += 1


def pump(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def make_project() -> Path:
    """Тимчасовий проєкт, який справді має що покращувати."""
    root = Path(tempfile.mkdtemp())
    (root / "tests").mkdir()
    (root / "app").mkdir()
    (root / "app" / "core.py").write_text(
        "# TODO: доробити обробку помилок\n"
        "def run():\n"
        "    try:\n"
        "        return work()\n"
        "    except ValueError:\n"
        "        pass\n"
        + "print('debug')\n" * 8,
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Тестовий проєкт\n", encoding="utf-8")
    return root


def main() -> int:
    global failures
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb

    mb.askyesno = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    fd.asksaveasfilename = lambda *a, **k: ""
    fd.askopenfilename = lambda *a, **k: ""
    fd.askdirectory = lambda *a, **k: ""

    from blackchpok_ide import autonomous, queue_engine
    from blackchpok_ide.config import Settings, setup_logging
    from blackchpok_ide.main_window import BlackChpokIDE

    setup_logging()
    project = make_project()
    settings = Settings.load()
    settings.workspace = str(project)
    settings.first_run_done = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False     # керуємо чергою вручну
    settings.ui.view = "workspace"

    app = BlackChpokIDE(settings)
    app.withdraw()

    try:
        pump(app, 0.6)

        # ── 1. Об'єднані «Чати й агенти»
        app.show_side("chats")
        pump(app, 0.2)
        check("розділ «Чати й агенти» показано",
              app._active_side == "chats", app._active_side)
        # Вікно тесту приховане (withdraw), тому winfo_ismapped() завжди 0 —
        # перевіряємо, що панель справді стоїть у менеджері пакування.
        check("список сесій на екрані", bool(app.chat_list.winfo_manager()))
        # Ліва панель — ТІЛЬКИ чати: меню розділів прибрано, а заголовок
        # панелі більше не дублює вкладку «ЧАТИ Й АГЕНТИ» (він порожній для
        # чатів і показує «‹ до чатів» для інших панелей).
        title = str(app.panel_title.cget("text")).upper()
        check("заголовок панелі не дублює список чатів",
              title == "", title)
        check("меню розділів прибрано",
              len(getattr(app, "_nav_buttons", {})) == 0,
              str(len(getattr(app, "_nav_buttons", {}))))
        check("окремого розділу «Агенти» немає",
              "agents" not in {key for key, *_rest in __import__(
                  "blackchpok_ide.nav_sidebar", fromlist=["NAV_ITEMS"]).NAV_ITEMS})

        # ── 2. Іконки закриття й архівування біля чату
        chat = app.chat_store.create(title="Сесія з іконками")
        app.chat_list.refresh()
        pump(app, 0.2)
        row = app.chat_list._rows.get(chat.id)
        check("рядок сесії має іконку архівування",
              row is not None and row.archive_btn.winfo_exists())
        check("рядок сесії має іконку закриття",
              row is not None and row.close_btn.winfo_exists())

        # Закриття ПОРОЖНЬОГО чату видаляє його повністю (не архівує):
        # тримати в списку сесію без жодної репліки безглуздо, і саме через
        # архівування лічильник раніше зростав при кожному «×».
        closed = app.close_chat(chat.id)
        check("закриття чату спрацювало", closed)
        check("порожній чат видалено повністю", app.chat_store.get(chat.id) is None)

        # А чат З ІСТОРІЄЮ — архівується, щоб робота не пропала.
        busy_chat = app.chat_store.create(title="Чат із роботою")
        app.chat_store.append("user", "щось важливе")
        app.chat_list.refresh()
        pump(app, 0.2)
        app.close_chat(busy_chat.id)
        saved = app.chat_store.get(busy_chat.id)
        check("чат з історією пішов в архів",
              saved is not None and bool(saved.archived))

        # ── 3. Панель автономного режиму
        app.show_autonomous()
        pump(app, 0.2)
        check("панель автономного режиму показано",
              app._active_side == "autonomous", app._active_side)
        check("статус показує «вимкнено»",
              autonomous.STATE_OFF in str(app.autonomous_panel.state_label.cget("text")))
        check("кнопки Старт і Стоп на місці",
              app.autonomous_panel.start_btn.winfo_exists()
              and app.autonomous_panel.stop_btn.winfo_exists())
        check("поле для своєї задачі на місці",
              app.autonomous_panel.task_entry.winfo_exists())

        # ── 4. Старт режиму: агент сам наповнює чергу
        app.autonomous_engine.project = project
        # Модель є (фейкова назва) — старт не має відмовити через її відсутність.
        app.settings.llm.model = app.settings.llm.model or "test-model"
        app.start_autonomous()
        pump(app, 0.4)
        check("режим увімкнено",
              app.autonomous_engine.state == autonomous.STATE_RUNNING,
              app.autonomous_engine.state)
        check("агент сам додав задачі в чергу",
              len(app.task_queue.pending_of(queue_engine.ORIGIN_AGENT)) > 0,
              str(app.task_queue.counts_by_origin()))
        check("план людською мовою непорожній",
              bool(app.autonomous_engine.plan_rows()))
        check("журнал дій пише",
              len(app.autonomous_engine.recent_log()) > 0)

        # ── 5. Гаряче додавання задачі користувача = вищий пріоритет
        app.add_autonomous_task("виправ помилку в app/core.py")
        pump(app, 0.2)
        # Зупиняємо агента, якого міг підхопити цикл режиму, і повертаємо
        # його задачу в чергу: далі перевіряємо саме ПОРЯДОК виконання.
        app.stop_agent()
        pump(app, 0.3)
        if app.task_queue.running_id:
            app.task_queue.retry(app.task_queue.running_id)
            app.task_queue.running_id = ""
        nxt = app.task_queue.next_pending()
        check("задача користувача йде першою",
              nxt is not None and nxt.from_user, nxt.text if nxt else "—")
        check("панель показує обидва джерела",
              app.autonomous_engine.snapshot()["pending_user"] >= 1
              and app.autonomous_engine.snapshot()["pending_agent"] >= 1)

        # ── 6. Правило одного проєкту
        other = Path(tempfile.mkdtemp())
        allowed, reason = app.autonomous_engine.can_start(other)
        check("другий проєкт одночасно не вмикається", not allowed, reason)
        check("причина називає поточний проєкт",
              app.autonomous_engine.project.name in reason, reason)

        # ── 7. Коректна зупинка: файл дописується й зберігається
        target = project / "app" / "core.py"
        editor = app.tabs.open_file(target) and app.tabs.current()
        check("файл проєкту відкрито у редакторі", editor is not None)
        if editor is not None:
            editor.insert_text("\n# зміна агента перед зупинкою\n")
            pump(app, 0.1)
            check("у редакторі є незбережені зміни", bool(editor.modified))

        before = target.read_text(encoding="utf-8")
        app.stop_agent()      # агент вільний — зупинка завершується одразу
        app.stop_autonomous()
        pump(app, 0.5)
        check("режим вимкнено",
              app.autonomous_engine.state == autonomous.STATE_OFF,
              app.autonomous_engine.state)
        after = target.read_text(encoding="utf-8")
        check("файл дописано й збережено на диску", after != before)
        check("зміна справді потрапила у файл", "зміна агента" in after)
        check("задачі агента знято з черги",
              app.task_queue.pending_of(queue_engine.ORIGIN_AGENT) == [])
        # Задача користувача має ЛИШИТИСЬ. Якщо цикл режиму встиг узяти її
        # в роботу — це теж правильна поведінка (режим виконує чергу), тож
        # приймаємо або «очікує», або будь-який незавершений стан: головне,
        # що її не СКАСОВАНО разом із задачами агента.
        user_tasks = [t for t in app.task_queue.tasks
                      if t.origin == queue_engine.ORIGIN_USER]
        pending_user = app.task_queue.pending_of(queue_engine.ORIGIN_USER)
        alive = [t for t in user_tasks if t.status != queue_engine.CANCELLED]
        check("задачі користувача збережено",
              len(pending_user) >= 1 or (user_tasks and len(alive) == len(user_tasks)),
              f"у черзі: {len(pending_user)}, живих: {len(alive)}, "
              f"усього: {len(user_tasks)}")

        # ── 8. Адаптивні розміри: ліміт рядків рахується з екрана
        app._apply_responsive()
        pump(app, 0.2)
        metrics = app._chat_metrics
        check("адаптивна ширина чату обчислена", metrics.chat_width > 0,
              f"{metrics.chat_width}px")
        check("ліміт рядків відповідає екрану",
              metrics.body_lines >= 12, f"{metrics.body_lines} рядків")

        # ── 9. Вивантаження моделі: в автономному режимі не спрацьовує
        keeper = app.model_keeper
        keeper.tracker.policy.idle_seconds = 1
        keeper.tracker.last_touch -= 10_000
        allowed = keeper.tracker.should_unload(busy=False, autonomous=True, loaded=True)
        check("в автономному режимі модель не вивантажується", not allowed)
        allowed = keeper.tracker.should_unload(busy=False, autonomous=False, loaded=True)
        check("поза автономним режимом вивантаження дозволене", allowed)

        app.autonomous_engine.log("перевірку завершено", kind="ok")
        app.autonomous_panel.refresh()
        pump(app, 0.2)
        check("панель оновилась без помилок", app.autonomous_panel.winfo_exists())
    except Exception:  # noqa: BLE001 - показуємо повний стек
        traceback.print_exc()
        failures += 1
    finally:
        try:
            app.task_queue.clear()
            app.on_close()
        except Exception:  # noqa: BLE001
            traceback.print_exc()

    print()
    print("Автономний режим: успішно" if failures == 0 else f"Автономний режим: помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
