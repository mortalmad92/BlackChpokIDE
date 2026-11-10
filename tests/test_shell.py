"""Тести нового каркасу інтерфейсу: провайдери, режими, композиція вікна.

Запуск:  python tests/test_shell.py
Повертає 0, якщо всі твердження виконались.
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

failures = 0
checked = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures, checked
    checked += 1
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


# ─────────────────────────────────────────────────────────────────────────────
# Провайдери (без вікна)
# ─────────────────────────────────────────────────────────────────────────────

def test_providers() -> None:
    from blackchpok_ide import providers

    # 1. Характеристики беруться з назви, а не вигадуються.
    check("параметри з назви моделі", providers.params_from_name("qwen2.5-coder-7b") == 7.0,
          str(providers.params_from_name("qwen2.5-coder-7b")))
    check("параметри без цифр — нуль", providers.params_from_name("my-model") == 0.0)
    check("квантування з імені файлу",
          providers.quant_from_name("model-Q4_K_M.gguf") == "Q4_K_M",
          providers.quant_from_name("model-Q4_K_M.gguf"))
    check("без квантування — порожньо", providers.quant_from_name("model.gguf") == "")

    # 2. Локальні провайдери існують і не потребують ключа.
    local_keys = {p.key for p in providers.LOCAL_PROVIDERS}
    check("локальні провайдери визначені", len(local_keys) >= 4, ",".join(sorted(local_keys)))
    check("Ollama серед локальних", "ollama" in local_keys)
    check("LM Studio серед локальних", "lmstudio" in local_keys)
    check("локальний провайдер не потребує ключа",
          all(p.api_key == "local" for p in providers.LOCAL_PROVIDERS))
    check("усі локальні мають адресу або це «свій URL»",
          all(bool(p.base_url) or p.key == "custom-local"
              for p in providers.LOCAL_PROVIDERS))

    # 3. Визначення провайдера за адресою.
    key, kind = providers.detect_provider_key("http://127.0.0.1:11434/v1")
    check("Ollama розпізнано за адресою", (key, kind) == ("ollama", providers.LOCAL),
          f"{key}/{kind}")
    key, kind = providers.detect_provider_key("https://api.deepseek.com/v1")
    check("DeepSeek розпізнано як хмару", kind == providers.CLOUD, f"{key}/{kind}")

    # 4. Групування: локальні стоять першими.
    from blackchpok_ide.config import Settings

    entries = providers.catalogue(Settings())
    groups = providers.group(entries)
    check("каталог не порожній", bool(entries), f"{len(entries)} моделей")
    if groups:
        check("локальні йдуть першою групою", groups[0][0].startswith("ЛОКАЛЬ"),
              groups[0][0])
    else:
        check("локальні йдуть першою групою", False, "груп немає")

    # 5. Невідомі характеристики показуються як «—», а не вигадуються.
    unknown = providers.ModelEntry(name="x", provider_key="k", provider_label="L",
                                   kind=providers.LOCAL)
    check("невідомий контекст — «—»", unknown.context_text == "—", unknown.context_text)
    check("метадані містять вид і провайдера",
          "LOCAL" in unknown.meta_text and "L" in unknown.meta_text, unknown.meta_text)


# ─────────────────────────────────────────────────────────────────────────────
# Режими роботи
# ─────────────────────────────────────────────────────────────────────────────

def test_modes() -> None:
    from blackchpok_ide import modes, permissions
    from blackchpok_ide.config import Settings
    from blackchpok_ide.agent import AgentRunner
    from blackchpok_ide.agent_tools import ToolRegistry

    check("п'ять режимів", len(modes.MODES) == 5, str(len(modes.MODES)))
    check("ключі режимів", modes.keys() == ["chat", "agent", "code", "plan", "tools"],
          ",".join(modes.keys()))
    check("невідомий режим → типовий",
          modes.normalise("вигаданий") == modes.DEFAULT_MODE)
    check("кожен режим має підказку",
          all(bool(m.hint) for m in modes.MODES))
    check("кожен режим має реальні дозволи",
          all(m.permission in permissions.MODES for m in modes.MODES))

    settings = Settings()
    settings.agent.max_steps = 8
    modes.remember_base_steps(8)
    runner = AgentRunner(ToolRegistry(ROOT), settings.llm, settings.agent, ROOT)

    # «Чат» — без інструментів і один крок.
    modes.apply(settings, runner, modes.CHAT)
    check("чат: лише читання", runner.permission_mode == permissions.READ_ONLY,
          runner.permission_mode)
    check("чат: один крок", runner.max_steps == 1, str(runner.max_steps))
    check("чат: без схем інструментів", runner.tool_schemas() == [],
          str(len(runner.tool_schemas())))

    # «Код» — запис у робочій області, більше кроків, інструменти є.
    modes.apply(settings, runner, modes.CODE)
    check("код: запис у робочій області",
          runner.permission_mode == permissions.WORKSPACE, runner.permission_mode)
    check("код: дванадцять кроків", runner.max_steps == 12, str(runner.max_steps))
    check("код: інструменти доступні", len(runner.tool_schemas()) > 0,
          str(len(runner.tool_schemas())))

    # «План» — лише читання.
    modes.apply(settings, runner, modes.PLAN)
    check("план: лише читання", runner.permission_mode == permissions.READ_ONLY,
          runner.permission_mode)

    # Повернення до «Агент» має відновити базовий ліміт кроків.
    modes.apply(settings, runner, modes.AGENT)
    check("агент: базовий ліміт кроків", runner.max_steps == 8, str(runner.max_steps))

    # Режим НЕ має переписувати налаштування користувача.
    check("режим не змінює max_steps у налаштуваннях",
          settings.agent.max_steps == 8, str(settings.agent.max_steps))


# ─────────────────────────────────────────────────────────────────────────────
# Живе вікно
# ─────────────────────────────────────────────────────────────────────────────

def _neutralise() -> None:
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb
    import tkinter.simpledialog as sd

    mb.askyesno = lambda *a, **k: True
    mb.askyesnocancel = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    sd.askstring = lambda *a, **k: None
    sd.askinteger = lambda *a, **k: None
    fd.asksaveasfilename = lambda *a, **k: ""
    fd.askopenfilename = lambda *a, **k: ""
    fd.askdirectory = lambda *a, **k: ""


def test_window() -> None:
    from blackchpok_ide.config import Settings, settings_path, setup_logging
    from blackchpok_ide.main_window import BlackChpokIDE

    setup_logging()
    _neutralise()
    # Тест змінює ui.view у спільному файлі налаштувань, а наступні тести
    # (геометрія, режим чату) очікують свій стан. Зберігаємо й відновлюємо.
    target = settings_path()
    backup = target.read_text(encoding="utf-8") if target.exists() else None
    try:
        _run_window_checks(Settings, BlackChpokIDE)
    finally:
        try:
            if backup is not None:
                target.write_text(backup, encoding="utf-8")
            elif target.exists():
                target.unlink()
        except OSError:
            pass


def _run_window_checks(Settings, BlackChpokIDE) -> None:
    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.first_run_done = True
    settings.engine.auto_start = False
    settings.agent.queue_auto_run = False
    settings.ui.view = "workspace"
    settings.ui.sidebar_visible = True

    def pump(app, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            app.update()
            time.sleep(0.02)

    app = BlackChpokIDE(settings)
    app.geometry("1500x900")
    try:
        pump(app, 1.4)
        app.hide_welcome()
        pump(app, 0.5)

        # 1. Ліворуч — лише чати. Меню розділів прибрано: «Чати», «MCP»,
        #    «Проєкти», «База знань» і «Налаштування» забирали місце в
        #    колонці, призначеній для розмов. Тепер вони в діалозі
        #    налаштувань (вкладка «Розділи») і в меню «Вигляд».
        check("меню розділів прибрано", len(app._nav_buttons) == 0,
              str(len(app._nav_buttons)))
        check("є «Новий чат»", app.new_session_btn.winfo_ismapped() == 1)
        check("список чатів на місці", app.chat_list.winfo_ismapped() == 1)
        check("панель навігації всередині сайдбара",
              app.rail.winfo_width() > 0 and app.rail.winfo_width() <= app.sidebar.winfo_width(),
              f"rail={app.rail.winfo_width()} sidebar={app.sidebar.winfo_width()}")

        # 2. Заголовок сесії показує вид, режим і модель.
        check("заголовок сесії існує", app.header.winfo_ismapped() == 1)
        check("перемикач виду є", app.header.view_switch.current in ("chat", "workspace"),
              app.header.view_switch.current)

        # 3. Розділи ведуть на свої панелі.
        #    «Чати» й «Агенти» об'єднані: розділ «chats» веде на єдиний
        #    список сесій, а кроки агента («cases») — його підпункт.
        #    «Автономний» і «Автоматизації» більше не розділи меню: вони
        #    прив'язані до чату й проєкту (див. chat_mode_menu), тому їх
        #    маршрут перевіряємо окремо через PANEL_SECTIONS.
        routes = {
            "chats": "chats",
            "mcp": "mcp",
            "knowledge": "rag",
            "projects": "explorer",
        }
        for section, panel in routes.items():
            app._rail_action(section)
            pump(app, 0.12)
            check(f"розділ «{section}» веде на «{panel}»",
                  app._active_side == panel
                  and app._side_widgets[panel].winfo_ismapped() == 1,
                  f"{app._active_side}")

        # 4. Види: у робочій області три колонки, у чаті — одна.
        app.set_view("workspace")
        pump(app, 0.5)
        check("робоча область: діалог + редактор",
              len(app.h_split.panes()) >= 2 and app.centre.winfo_ismapped() == 1,
              f"{len(app.h_split.panes())}")
        app.set_view("chat")
        pump(app, 0.5)
        check("вид «чат»: редактор згорнуто",
              app._view == "chat" and app.centre.winfo_ismapped() == 0)
        check("вид «чат»: діалог на місці", app.conversation_host.winfo_ismapped() == 1)
        chat_w = app.conversation_host.winfo_width()
        check("вид «чат»: діалог ширший за колонку редактора", chat_w > 600, f"{chat_w} px")

        app.set_view("workspace")
        pump(app, 0.5)
        check("повернення до робочої області",
              app.centre.winfo_ismapped() == 1 and len(app.h_split.panes()) >= 2)

        # 5. Чат займає всю ширину панелі.
        # Раніше стрічка обмежувалась 920 px і центрувалась. Тепер вимога
        # інша: розмова має використовувати весь доступний простір, а
        # вузьку колонку можна повернути лише через ui.chat_max_width > 0.
        app.set_view("chat")
        pump(app, 0.6)
        feed_w = app.chat.feed.winfo_width()
        host_w = app.chat.winfo_width()
        check("чат займає всю ширину панелі",
              feed_w >= host_w - 20, f"feed={feed_w} host={host_w}")
        # Допуск 20 px: вертикальна смуга прокрутки (8 px) плюс рамка
        # полотна. Суворий допуск у 8 px робив тест нестабільним — він
        # проходив чи падав залежно від того, чи вміст перевищує висоту.

        # Вузьку колонку можна повернути явним обмеженням.
        app.settings.ui.chat_max_width = 700
        try:
            app.chat.scroll.max_content_width = 700
            app.chat.scroll._on_canvas_configure(
                type("E", (), {"width": host_w})())
            pump(app, 0.4)
            limited = app.chat.feed.winfo_width()
            check("обмеження ширини діє, коли задане",
                  limited <= 720, f"feed={limited}")
        finally:
            app.settings.ui.chat_max_width = 0
            app.chat.scroll.max_content_width = 0
            pump(app, 0.2)

        # 6. Селектор моделей відкривається й показує локальні та хмарні.
        app.show_model_selector()
        pump(app, 0.5)
        selector = app._model_selector
        check("селектор моделей відкрито", selector is not None and selector.visible)
        if selector is not None:
            groups = {("local" if e.is_local else "cloud") for e in selector.entries}
            check("селектор знає про локальні моделі", "local" in groups, str(groups))
            check("селектор знає про хмарні моделі", "cloud" in groups, str(groups))
            selector.close()
        pump(app, 0.2)

        # 7. Меню режимів перемикає режим по-справжньому.
        app.set_agent_mode("plan")
        pump(app, 0.2)
        check("режим «план» застосовано", app.agent.permission_mode == "read_only",
              app.agent.permission_mode)
        app.set_agent_mode("agent")
        pump(app, 0.2)
        check("режим «агент» застосовано", app.agent.permission_mode == "workspace",
              app.agent.permission_mode)

        # 8. Панель навігації згортається до рейки.
        before = app.sidebar.winfo_width()
        app.toggle_sidebar(False)
        pump(app, 0.3)
        check("панель навігації ховається", app.sidebar.winfo_ismapped() == 0)
        app.toggle_sidebar(True)
        pump(app, 0.3)
        check("панель навігації повертається",
              app.sidebar.winfo_ismapped() == 1 and app.sidebar.winfo_width() == before,
              f"{app.sidebar.winfo_width()} px")

        # 9. Старе API живих панелей збережено (сумісність).
        check("старий show_side працює",
              callable(getattr(app, "show_side", None)))
        check("_side_widgets на місці", len(app._side_widgets) >= 10,
              str(len(app._side_widgets)))
    finally:
        app.agent.cancel()
        app.destroy()
        pump(app, 0.2)


def theme_cap(app) -> int:
    from blackchpok_ide import theme

    return int(getattr(app.settings.ui, "chat_max_width", 0) or theme.CHAT_MAX_WIDTH)


def main() -> int:
    test_providers()
    print()
    test_modes()
    print()
    test_window()
    print()
    print(f"Перевірено тверджень: {checked}")
    print("Каркас інтерфейсу:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)


# ── unittest-обгортка (додано 10.11.2026) ──────────────────────────────────
# Для `python -m unittest discover` ці перевірки раніше були невидимі:
# файл — скрипт із власним main(), а не TestCase. Тепер discover запускає
# його й падає, якщо main() повернув ненульовий код. Запуск як скрипт
# (`python tests/test_shell.py`) поводиться як раніше.
import unittest as _unittest  # noqa: E402


class _ScriptSuite(_unittest.TestCase):
    def test_script_passes(self) -> None:
        code = main()
        self.assertEqual(code, 0, f"main() повернув {code}")
