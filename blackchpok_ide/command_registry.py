"""Реєстр команд IDE: одна таблиця замість трьох місць.

Навіщо окремий модуль. ``_register_commands`` жив усередині
``main_window.py`` і займав **318 рядків** — це найдовший метод файлу на
8003 рядки. Він не чіпає tkinter безпосередньо: лише створює
:class:`commands.Command` із посиланнями на методи вікна. Тому його можна
винести, не змінюючи поведінки: сигнатура ``register_all(window)`` бере
вікно як аргумент, а ``self.`` замінено на ``window.``.

Що це дає: ``main_window`` стає коротшим на 318 рядків, а таблиця команд
опиняється там, де її шукатиме читач — поруч із ``commands.py``.

Нових зовнішніх залежностей немає: модуль імпортує лише ``commands``.
"""

from __future__ import annotations

from . import commands, layout_profiles

__all__ = ["register_all"]


def register_all(window) -> None:
    """Наповнити реєстр команд (ідемпотентно).

    Рівні: ``primary`` — кнопка в шапці, ``menu`` — випадаюче меню шапки,
    ``palette`` — лише палітра. Жодна команда зі старого меню не
    втрачається: усе, що не потрапило на шапку, доступне через «⋯»
    або Ctrl+Shift+P.
    """
    register = commands.register

    # ── Файл
    register(commands.Command(
        "file.new", "Новий файл", "Файл", window.new_file, "Ctrl+N",
        group="file", level=commands.PRIMARY, icon="＋"))
    register(commands.Command(
        "file.open", "Відкрити файл…", "Файл", window.open_file_dialog, "Ctrl+O",
        group="file", level=commands.PRIMARY, icon="▤"))
    register(commands.Command(
        "file.save", "Зберегти", "Файл", window.save_file, "Ctrl+S",
        group="file", level=commands.PRIMARY, icon="⤓",
        enabled=lambda: bool(window.tabs.current())))
    register(commands.Command(
        "file.quick_open", "Швидке відкриття файлу", "Файл", window.quick_open,
        "Ctrl+P", group="file", level=commands.MENU))
    register(commands.Command(
        "file.open_folder", "Відкрити папку…", "Файл", window.open_folder_dialog,
        group="file", level=commands.MENU))
    register(commands.Command(
        "file.save_as", "Зберегти як…", "Файл", window.save_file_as,
        "Ctrl+Shift+S", group="file", level=commands.MENU))
    register(commands.Command(
        "file.save_all", "Зберегти все", "Файл", lambda: window.tabs.save_all(),
        group="file", level=commands.MENU))
    register(commands.Command(
        "file.close_tab", "Закрити вкладку", "Файл", window.close_tab, "Ctrl+W",
        group="file", level=commands.MENU))
    register(commands.Command(
        "file.reopen_tab", "Відкрити закриту вкладку", "Файл", window.reopen_tab,
        "Ctrl+Shift+T", group="file", level=commands.MENU))
    register(commands.Command(
        "file.close_all", "Закрити всі вкладки", "Файл", window.close_all_tabs,
        group="file", level=commands.MENU))
    register(commands.Command(
        "file.start_screen", "Стартовий екран", "Файл", window.show_welcome,
        group="file", level=commands.MENU))
    register(commands.Command(
        "file.exit", "Вихід", "Файл", window.on_close, "Alt+F4",
        group="file", level=commands.MENU))

    # ── Правка
    register(commands.Command(
        "edit.undo", "Скасувати", "Правка", lambda: window._editor_event("<Control-z>"),
        "Ctrl+Z", group="file", level=commands.PRIMARY, icon="↶",
        enabled=lambda: bool(window.tabs.current())))
    register(commands.Command(
        "edit.redo", "Повторити", "Правка", lambda: window._editor_event("<Control-y>"),
        "Ctrl+Y", group="file", level=commands.PRIMARY, icon="↷",
        enabled=lambda: bool(window.tabs.current())))
    register(commands.Command(
        "edit.cut", "Вирізати", "Правка", lambda: window._editor_event("<<Cut>>"),
        "Ctrl+X", level=commands.PALETTE))
    register(commands.Command(
        "edit.copy", "Копіювати", "Правка", lambda: window._editor_event("<<Copy>>"),
        "Ctrl+C", level=commands.PALETTE))
    register(commands.Command(
        "edit.paste", "Вставити", "Правка", lambda: window._editor_event("<<Paste>>"),
        "Ctrl+V", level=commands.PALETTE))
    register(commands.Command(
        "edit.find", "Знайти в файлі…", "Правка", window.open_search, "Ctrl+F",
        level=commands.PALETTE))
    register(commands.Command(
        "edit.find_project", "Пошук у проєкті…", "Правка",
        window.open_project_search, "Ctrl+Shift+F", level=commands.PALETTE))
    register(commands.Command(
        "edit.goto", "Перейти до рядка…", "Правка",
        lambda: window.tabs.current() and window.tabs.current().focus_goto(),
        "Ctrl+G", level=commands.PALETTE))
    register(commands.Command(
        "edit.ast", "Показати AST-дерево", "Код", window.show_ast_tree,
        "Ctrl+Shift+A", level=commands.PALETTE))
    register(commands.Command(
        "edit.symbols", "Звіт про символи", "Код", window.show_symbols_report,
        level=commands.PALETTE))
    register(commands.Command(
        "edit.comment", "Формат: коментар", "Правка",
        lambda: window.tabs.current() and window.tabs.current()._toggle_comment(),
        "Ctrl+/", level=commands.PALETTE))

    # ── Агент
    register(commands.Command(
        "agent.new_chat", "Новий чат", "Чат", window.new_chat, "",
        group="agent", level=commands.MENU, icon="＋"))
    register(commands.Command(
        "agent.stop", "Зупинити агента", "Агент", window.stop_agent, "",
        group="agent", level=commands.PRIMARY, icon="■",
        enabled=lambda: bool(getattr(window.chat, "_busy", False))))
    register(commands.Command(
        "agent.send_file", "Надіслати поточний файл агенту", "Агент",
        window.send_file_to_agent, "Ctrl+Alt+Enter", group="agent",
        level=commands.MENU, enabled=lambda: bool(window.tabs.current())))
    register(commands.Command(
        "agent.explain", "Пояснити виділене", "Агент", window.explain_selection,
        group="agent", level=commands.MENU,
        enabled=lambda: bool(window.tabs.current())))
    register(commands.Command(
        "agent.fix", "Виправити виділене", "Агент", window.fix_selection,
        group="agent", level=commands.MENU,
        enabled=lambda: bool(window.tabs.current())))
    register(commands.Command(
        "agent.add_task", "Додати задачу в чергу", "Завдання", window.add_queue_dialog,
        "Ctrl+Alt+Q", group="agent", level=commands.MENU))
    register(commands.Command(
        "agent.run_next", "Запустити наступну задачу", "Завдання",
        window.run_next_task, group="agent", level=commands.MENU))
    register(commands.Command(
        "agent.task_center", "Центр завдань", "Завдання",
        lambda: window.show_bottom("tasks"), "Ctrl+Alt+W",
        group="agent", level=commands.MENU))
    register(commands.Command(
        "agent.pause_plan", "Призупинити план", "Завдання", window.pause_queue,
        group="agent", level=commands.MENU))
    register(commands.Command(
        "agent.resume_plan", "Продовжити план", "Завдання", window.resume_queue,
        group="agent", level=commands.MENU))
    register(commands.Command(
        "agent.stop_plan", "Зупинити виконання плану", "Завдання", window.stop_plan,
        group="agent", level=commands.MENU))
    register(commands.Command(
        "agent.replan", "Перепланувати залишок роботи", "Завдання",
        window.replan_now, group="agent", level=commands.MENU))
    register(commands.Command(
        "agent.plan_report", "Підсумковий звіт", "Завдання",
        window.finish_plan_report, group="agent", level=commands.MENU))
    register(commands.Command(
        "agent.autonomous", "Автономний режим: старт / стоп", "Агент",
        window.toggle_autonomous, "Ctrl+Alt+A", group="agent", level=commands.MENU))
    register(commands.Command(
        "agent.autonomous_panel", "Автономний режим: панель", "Агент",
        window.show_autonomous, group="agent", level=commands.MENU))
    register(commands.Command(
        "agent.unload_model", "Вивантажити модель із відеокарти", "Модель",
        window.unload_model_now, group="agent", level=commands.MENU))
    # Прибирання «сиріт» від попередніх запусків: якщо IDE колись
    # закрилась аварійно, llama-server міг лишитись живим і тримати
    # гігабайти VRAM. Кнопка дає змогу звільнити їх одразу.
    register(commands.Command(
        "agent.free_vram", "Звільнити відеопам'ять (прибрати залишкові рушії)",
        "Модель", window.free_vram_now, group="agent", level=commands.MENU))
    register(commands.Command(
        "agent.probe", "Перевірити модель", "Модель",
        lambda: window.probe_providers(), group="agent", level=commands.MENU))
    register(commands.Command(
        "agent.mcp_reload", "Перепідключити MCP", "Агент", window.reload_mcp,
        group="agent", level=commands.MENU))
    register(commands.Command(
        "agent.skills", "Скіли агента", "Агент", lambda: window.show_side("skills"),
        "Ctrl+Alt+K", level=commands.PALETTE))
    register(commands.Command(
        "agent.cases", "Кроки агента", "Агент", lambda: window.show_side("cases"),
        "Ctrl+Alt+D", level=commands.PALETTE))
    register(commands.Command(
        "agent.export_chat", "Експорт чату в Markdown", "Чат",
        window.export_current_chat, level=commands.PALETTE,
        enabled=lambda: bool(window.chat_store.active())))
    register(commands.Command(
        "agent.quality", "Якість агента (метрики)", "Агент",
        window.show_agent_quality, group="agent", level=commands.MENU))

    # ── Запуск
    register(commands.Command(
        "run.start", "Запустити проєкт", "Сайт", window.start_site, "",
        group="run", level=commands.PRIMARY, icon="▶",
        enabled=window.has_project))
    register(commands.Command(
        "run.stop", "Зупинити проєкт", "Сайт", window.stop_site, "",
        group="run", level=commands.PRIMARY, icon="⏹",
        enabled=window.has_project))
    register(commands.Command(
        "run.terminal", "Термінал", "Вигляд", window.toggle_bottom, "Ctrl+`",
        group="run", level=commands.PRIMARY, icon="⌨"))
    register(commands.Command(
        "run.browser", "Live Browser", "Сайт", window.open_live_browser, "",
        group="run", level=commands.PRIMARY, icon="🌐"))
    register(commands.Command(
        "run.open_url", "Відкрити адресу у вбудованому браузері…", "Сайт",
        window.open_url_dialog, "Ctrl+Alt+L", level=commands.PALETTE,
        enabled=window.has_project))
    register(commands.Command(
        "run.site_tab", "Сайт у нижній вкладці", "Сайт", window.open_site,
        "Ctrl+Alt+P", level=commands.PALETTE))
    register(commands.Command(
        "run.site_reload", "Оновити сторінку сайту", "Сайт", window.reload_site,
        level=commands.PALETTE, enabled=window.has_project))
    register(commands.Command(
        "view.theme_save", "Зберегти поточну тему", "Вигляд", window._save_theme,
        level=commands.PALETTE))
    register(commands.Command(
        "run.file", "Запустити поточний файл", "Код", window.run_current_file,
        "F5", level=commands.PALETTE, enabled=lambda: bool(window.tabs.current())))
    register(commands.Command(
        "run.tests", "Запустити тести", "Код", window.run_tests, "Ctrl+F5",
        level=commands.PALETTE, enabled=window.has_project))
    register(commands.Command(
        "run.terminal_interrupt", "Термінал: перервати команду", "Вигляд",
        lambda: window.terminal.interrupt(), "Ctrl+C", level=commands.PALETTE))
    register(commands.Command(
        "run.terminal_restart", "Термінал: перезапустити сесію", "Вигляд",
        lambda: window.terminal.restart(), level=commands.PALETTE))
    register(commands.Command(
        "run.terminal_clear", "Термінал: очистити", "Вигляд",
        lambda: window.terminal.clear(), "Ctrl+L", level=commands.PALETTE))

    # ── Git
    for key, label, command in (
        ("git.status", "Статус", "git status --short --branch"),
        ("git.diff", "Diff", "git diff"),
        ("git.log", "Історія", "git log --oneline -15"),
        ("git.add", "Додати все", "git add -A"),
        ("git.commit", "Commit…", 'git commit -m "оновлення з BlackChpok IDE"'),
        ("git.push", "Синхронізувати (push)", "git push"),
        ("git.pull", "Отримати зміни (pull)", "git pull"),
    ):
        register(commands.Command(
            key, label, "Git", lambda c=command: window.terminal.run(c),
            group="git", level=commands.MENU, enabled=window.has_project))

    # ── Вигляд
    register(commands.Command(
        "view.settings", "Налаштування…", "Вигляд", window.open_settings,
        "Ctrl+,", group="view", level=commands.PRIMARY, icon="⚙"))
    register(commands.Command(
        "view.palette", "Командна палітра…", "Вигляд", window.command_palette,
        "Ctrl+Shift+P", group="view", level=commands.MENU))
    register(commands.Command(
        "view.sidebar", "Бічна панель", "Вигляд", window.toggle_sidebar,
        "Ctrl+B", group="view", level=commands.MENU))
    register(commands.Command(
        "view.chat", "Панель агента", "Вигляд", window.toggle_chat,
        "Ctrl+Alt+B", group="view", level=commands.MENU))
    register(commands.Command(
        "view.context", "Колонка контексту", "Вигляд", window.toggle_context,
        group="view", level=commands.MENU))
    register(commands.Command(
        "view.preview", "Live Preview", "Вигляд", window.toggle_preview,
        "Ctrl+Alt+V", group="view", level=commands.MENU))
    register(commands.Command(
        "view.focus", "Тільки чат", "Вигляд", window.toggle_focus_mode,
        "Ctrl+Alt+F", group="view", level=commands.MENU))
    register(commands.Command(
        "view.model_hub", "Хаб моделей…", "Модель", window.open_model_hub,
        "Ctrl+Shift+M", group="view", level=commands.MENU))
    register(commands.Command(
        "view.wizard", "Майстер налаштування…", "Модель", window.open_first_run,
        group="view", level=commands.MENU))
    register(commands.Command(
        "view.rag", "Знання про проєкт (RAG)", "Вигляд",
        lambda: window.show_side("rag"), "Ctrl+Alt+I", level=commands.PALETTE))
    register(commands.Command(
        "view.tools", "Інструменти агента", "Вигляд",
        lambda: window.show_side("tools"), "Ctrl+Alt+T", level=commands.PALETTE))
    register(commands.Command(
        "view.queue", "Черга завдань", "Завдання",
        lambda: window.show_side("queue"), "Ctrl+Alt+Q", level=commands.PALETTE))
    register(commands.Command(
        "view.mcp", "MCP-сервери", "Вигляд", lambda: window.show_side("mcp"),
        level=commands.PALETTE))
    register(commands.Command(
        "view.theme_dark", "Тема: темна", "Вигляд",
        lambda: window.apply_theme_mode("dark"), level=commands.PALETTE))
    register(commands.Command(
        "view.theme_light", "Тема: світла", "Вигляд",
        lambda: window.apply_theme_mode("light"), level=commands.PALETTE))
    register(commands.Command(
        "view.reset_layout", "Скинути розкладку", "Вигляд", window.reset_layout,
        level=commands.PALETTE))
    register(commands.Command(
        "view.save_layout", "Зберегти розкладку", "Вигляд", window._remember_layout,
        level=commands.PALETTE))
    register(commands.Command(
        "view.zoom_in", "Збільшити шрифт", "Вигляд", lambda: window.zoom(1),
        "Ctrl+=", level=commands.PALETTE))
    register(commands.Command(
        "view.zoom_out", "Зменшити шрифт", "Вигляд", lambda: window.zoom(-1),
        "Ctrl+-", level=commands.PALETTE))

    # ── Профілі робочого простору
    for key, label, profile in (
        ("view.profile_agent", "Профіль: AI Agent", layout_profiles.AI_AGENT),
        ("view.profile_code", "Профіль: Code Editor", layout_profiles.CODE_EDITOR),
        ("view.profile_web", "Профіль: Web Development", layout_profiles.WEB_DEV),
        ("view.profile_debug", "Профіль: Debugging", layout_profiles.DEBUGGING),
        ("view.profile_minimal", "Профіль: Minimal Workspace",
         layout_profiles.MINIMAL),
    ):
        register(commands.Command(
            key, label, "Вигляд", lambda p=profile: window.apply_profile(p),
            level=commands.PALETTE))

    # ── Довідка
    register(commands.Command(
        "help.shortcuts", "Гарячі клавіші", "Довідка", window.show_shortcuts,
        level=commands.PALETTE))
    register(commands.Command(
        "help.about", "Про програму", "Довідка", window.show_about,
        level=commands.PALETTE))
    register(commands.Command(
        "help.log", "Показати журнал", "Довідка", window.show_log,
        level=commands.PALETTE))
    # Самодіагностика — у меню «⋯»: коли модель не працює, користувач
    # має знайти причину без читання коду й логів.
    register(commands.Command(
        "help.diagnostics", "Самодіагностика (чому модель не працює)",
        "Довідка", window.run_diagnostics,
        level=commands.MENU))
    register(commands.Command(
        "help.failures", "Приховані збої", "Довідка", window.show_failures,
        level=commands.PALETTE))
