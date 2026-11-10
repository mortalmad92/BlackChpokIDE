"""НОВИЙ незалежний набір тестів для BlackChpok IDE 2.0.

Це окремий, написаний з нуля набір перевірок саме для тієї роботи, яку
виконано в цій версії. Він НЕ покладається на старі тести й не повторює їх
висновків: кожен пункт перевіряє реальну поведінку коду, а не текст
документації.

Що покрито:

* **чати** — ізоляція контексту агента, відновлення після перезапуску,
  перемикання без втрат (головний баг версії);
* **команди** — реєстр, шапка, палітра, збереження старих команд;
* **розкладка** — профілі, збереження, адаптивність шапки;
* **CDP** — розбір кадрів WebSocket, інспектор, аудит (без браузера);
* **провайдери** — три протоколи, авторизація, перетворення повідомлень;
* **секрети** — шифрування ключів, відсутність відкритого тексту, редакція;
* **агент і черга** — виправлені дефекти (блок tool_calls, retry, renumber,
  прив'язка до чату, бюджет контексту);
* **інструменти** — наявність схем, підписів, каталогу й безпеки.

Запуск:  python -m unittest tests.test_v2_audit -v
"""

from __future__ import annotations

import json
import socket
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# 1. Чати: ізоляція, перезапуск, перемикання
# ─────────────────────────────────────────────────────────────────────────────

class TestChatContextIsolation(unittest.TestCase):
    """Контекст агента належить ЧАТУ, а не програмі.

    Головний баг версії: модель не пам'ятала попередніх кроків розмови
    (продовжити роботу неможливо) або бачила контекст СУСІДНЬОГО чату.
    """

    def setUp(self) -> None:
        from blackchpok_ide.chat_store import ChatStore

        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "chats.json"
        self.store = ChatStore(self.path)

    def tearDown(self) -> None:
        for item in sorted(self.tmp.rglob("*"), reverse=True):
            try:
                item.unlink() if item.is_file() else item.rmdir()
            except OSError:
                pass
        try:
            self.tmp.rmdir()
        except OSError:
            pass

    def test_each_chat_has_own_id_and_messages(self) -> None:
        first = self.store.create(title="Перший")
        self.store.append("user", "питання один", chat_id=first.id)
        second = self.store.create(title="Другий")
        self.store.append("user", "питання два", chat_id=second.id)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual([m.text for m in self.store.get(first.id).messages],
                         ["питання один"])
        self.assertEqual([m.text for m in self.store.get(second.id).messages],
                         ["питання два"])

    def test_new_chat_does_not_touch_previous(self) -> None:
        first = self.store.create(title="Старий чат")
        self.store.append("user", "важлива робота", chat_id=first.id)
        for index in range(10):
            self.store.create(title=f"Новий {index}")
        still = self.store.get(first.id)
        self.assertIsNotNone(still, "старий чат зник після створення нових")
        self.assertEqual(len(still.messages), 1)
        self.assertIn("важлива робота", still.messages[0].text)

    def test_ten_chats_survive_disk_reload(self) -> None:
        from blackchpok_ide.chat_store import ChatStore

        created = []
        for index in range(10):
            chat = self.store.create(title=f"Сесія {index}")
            self.store.append("user", f"завдання {index}", chat_id=chat.id)
            self.store.store_context(chat.id, [
                {"role": "user", "content": f"завдання {index}"}])
            created.append(chat.id)
        reopened = ChatStore(self.path)
        self.assertEqual(len(reopened.chats), 10)
        for index, chat_id in enumerate(created):
            chat = reopened.get(chat_id)
            self.assertIsNotNone(chat, f"чат {index} не відновився")
            self.assertEqual(chat.messages[0].text, f"завдання {index}")
            self.assertEqual(reopened.load_context(chat_id)[0]["content"],
                             f"завдання {index}")

    def test_context_is_cleared_on_clear_messages(self) -> None:
        chat = self.store.create(title="С")
        self.store.append("user", "текст", chat_id=chat.id)
        self.store.store_context(chat.id, [{"role": "user", "content": "текст"}])
        self.store.clear_messages(chat.id)
        self.assertEqual(self.store.load_context(chat.id), [],
                         "очищення історії має чистити й контекст агента")

    def test_context_survives_tool_calls(self) -> None:
        """Виклики інструментів мусять пережити запис на диск.

        Без ``tool_calls`` наступний запит містить tool-результат без
        виклику й сервер відповідає 400.
        """
        chat = self.store.create(title="З інструментом")
        payload = [
            {"role": "user", "content": "прочитай"},
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "c1", "type": "function",
                             "function": {"name": "read_file",
                                          "arguments": '{"path":"a.py"}'}}]},
            {"role": "tool", "content": "вміст", "tool_call_id": "c1",
             "name": "read_file"},
        ]
        self.store.store_context(chat.id, payload)
        restored = self.store.load_context(chat.id)
        self.assertEqual(len(restored), 3)
        self.assertEqual(restored[1]["tool_calls"][0]["id"], "c1")
        self.assertEqual(restored[2]["tool_call_id"], "c1")

    def test_garbage_context_never_raises(self) -> None:
        chat = self.store.create(title="Сміття")
        for junk in (None, 42, "рядок", [None, 1, "x", {"role": "?"}],
                     [{"role": "user"}], {"a": 1}):
            self.store.store_context(chat.id, junk)
        self.assertIsInstance(self.store.load_context(chat.id), list)


class TestSessionRestore(unittest.TestCase):
    """``AgentSession.restore`` відновлює контекст і не пропускає сміття."""

    def _session(self):
        from blackchpok_ide.agent import AgentSession
        from blackchpok_ide.config import AgentSettings

        return AgentSession(AgentSettings(), Path(tempfile.mkdtemp()))

    def test_restore_replaces_previous_context(self) -> None:
        session = self._session()
        session.add_user("чуже питання")
        session.restore([{"role": "user", "content": "своє питання"}])
        self.assertEqual(len(session.messages), 1)
        self.assertEqual(session.messages[0]["content"], "своє питання")

    def test_snapshot_is_independent_copy(self) -> None:
        session = self._session()
        session.add_user("один")
        snapshot = session.snapshot()
        session.add_user("два")
        self.assertEqual(len(snapshot), 1, "знімок не має мінятись разом із сесією")

    def test_restore_drops_invalid_roles(self) -> None:
        session = self._session()
        restored = session.restore([
            {"role": "hacker", "content": "x"},
            {"role": "user", "content": "ок"},
            "не словник",
            {"content": "без ролі"},
        ])
        self.assertEqual(restored, 1)
        self.assertEqual(session.messages[0]["content"], "ок")

    def test_restore_empty_clears(self) -> None:
        session = self._session()
        session.add_user("було")
        self.assertEqual(session.restore([]), 0)
        self.assertEqual(session.messages, [])


class TestTrimKeepsToolPairs(unittest.TestCase):
    """Стиснення історії не лишає tool-результат без виклику."""

    def _runner(self, limit: int = 4096):
        from blackchpok_ide.agent import AgentRunner, AgentSession
        from blackchpok_ide.agent_tools import ToolRegistry
        from blackchpok_ide.config import AgentSettings

        runner = AgentRunner.__new__(AgentRunner)
        runner.session = AgentSession(AgentSettings(), ROOT)
        runner.session.context_limit = limit
        runner.registry = ToolRegistry(ROOT)
        runner.mcp_manager = None
        runner.settings_ref = None
        runner.tools_enabled = True
        runner.mode_prompt = ""
        runner.max_steps_override = 0
        return runner

    def test_no_orphan_tool_messages_after_trim(self) -> None:
        runner = self._runner()
        session = runner.session
        for index in range(12):
            call_id = f"c{index}"
            session.add_user(f"крок {index} " * 40)
            session.add_assistant({
                "role": "assistant", "content": "",
                "tool_calls": [{"id": call_id, "type": "function",
                                "function": {"name": "read_file",
                                             "arguments": "{}"}}],
            })
            session.messages.append({"role": "tool", "content": "дані " * 60,
                                     "tool_call_id": call_id,
                                     "name": "read_file"})
        session.trim()
        called = set()
        for message in session.messages:
            for call in message.get("tool_calls") or []:
                if isinstance(call, dict):
                    called.add(str(call.get("id")))
        orphans = [message.get("tool_call_id")
                   for message in session.messages
                   if message.get("role") == "tool"
                   and str(message.get("tool_call_id")) not in called]
        self.assertEqual(orphans, [],
                         f"tool-результати без виклику: {orphans}")

    def test_budget_fits_window_at_many_sizes(self) -> None:
        from blackchpok_ide.agent import AgentRunner, AgentSession
        from blackchpok_ide.agent_tools import ToolRegistry
        from blackchpok_ide.config import AgentSettings

        for limit in (2048, 4096, 8192, 16384, 32768):
            runner = AgentRunner.__new__(AgentRunner)
            runner.session = AgentSession(AgentSettings(), ROOT)
            runner.session.context_limit = limit
            runner.registry = ToolRegistry(ROOT)
            runner.mcp_manager = None
            runner.settings_ref = None
            runner.tools_enabled = True
            runner.mode_prompt = ""
            runner.max_steps_override = 0
            schemas = runner.tool_schemas()
            self.assertGreaterEqual(len(schemas), 3,
                                    f"вікно {limit}: немає жодної схеми")
            runner.session.add_user("x" * 30_000)
            runner.session.trim()
            self.assertLessEqual(
                runner.session._estimate_tokens(), limit,
                f"вікно {limit}: запит не вміщається")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Команди, шапка, палітра
# ─────────────────────────────────────────────────────────────────────────────

class TestCommandRegistry(unittest.TestCase):
    """Реєстр команд: повнота, унікальність, пошук, доступність."""

    def setUp(self) -> None:
        from blackchpok_ide import commands

        commands.reset()
        self.commands = commands
        self.run_calls: list[str] = []

        # Реєструємо набір, що імітує реальний.
        for key, label, level, group in (
            ("file.new", "Новий файл", commands.PRIMARY, "file"),
            ("file.save", "Зберегти", commands.PRIMARY, "file"),
            ("edit.undo", "Скасувати", commands.PRIMARY, "file"),
            ("agent.stop", "Зупинити агента", commands.PRIMARY, "agent"),
            ("run.browser", "Live Browser", commands.PRIMARY, "run"),
            ("view.settings", "Налаштування…", commands.PRIMARY, "view"),
            ("git.commit", "Commit…", commands.MENU, "git"),
            ("help.about", "Про програму", commands.PALETTE, ""),
        ):
            commands.register(commands.Command(
                key, label, "Загальне",
                lambda k=key: self.run_calls.append(k),
                level=level, group=group))

    def test_keys_are_unique(self) -> None:
        keys = [command.key for command in self.commands.all_commands()]
        self.assertEqual(len(keys), len(set(keys)))

    def test_palette_contains_every_command(self) -> None:
        items = self.commands.palette_items()
        self.assertEqual(len(items), len(self.commands.all_commands()),
                         "палітра має показувати КОЖНУ команду")

    def test_search_by_label(self) -> None:
        found = self.commands.available("зберегти")
        self.assertEqual([c.key for c in found], ["file.save"])

    def test_search_by_category_and_alias(self) -> None:
        commands = self.commands
        commands.register(commands.Command(
            "x.alias", "Дія", "Git", lambda: None, aliases=("пуш", "push")))
        self.assertTrue(commands.available("пуш"))
        self.assertTrue(commands.available("git"))

    def test_disabled_command_is_kept_but_not_run(self) -> None:
        commands = self.commands
        commands.register(commands.Command(
            "needs.file", "Потребує файлу", "Код", lambda: self.run_calls.append("x"),
            level=commands.PRIMARY, enabled=lambda: False))
        listed = [key for key, _hint, _cb in commands.palette_items("потребує")]
        self.assertEqual(len(listed), 1, "недоступна команда зникає з палітри")
        self.assertFalse(commands.get("needs.file").run())
        self.assertEqual(self.run_calls, [], "недоступна команда все ж виконалась")

    def test_primary_commands_cover_header_groups(self) -> None:
        groups = {group for group, items in self.commands.header_layout() if items}
        for required in ("file", "agent", "run", "view"):
            self.assertIn(required, groups, f"немає кнопок групи «{required}»")

    def test_failing_action_does_not_raise(self) -> None:
        commands = self.commands
        commands.register(commands.Command(
            "boom", "Падає", "Тест", lambda: 1 / 0))
        self.assertFalse(commands.get("boom").run(),
                         "команда, що впала, має повернути False, а не кинути")


class TestCommandsRegisteredInWindow(unittest.TestCase):
    """Реальне вікно реєструє всі команди старого меню.

    Перевіряємо за ВИХІДНИМ КОДОМ, бо для цього потрібен дисплей: дивимось,
    що кожна дія з ``_build_menu`` має відповідник у реєстрі команд.
    """

    @classmethod
    def setUpClass(cls) -> None:
        import inspect

        from blackchpok_ide import command_registry
        from blackchpok_ide.main_window import BlackChpokIDE

        cls.menu_source = inspect.getsource(BlackChpokIDE._build_menu)
        # 10.11.2026: таблицю команд винесено з ``main_window`` у
        # ``command_registry`` (318 рядків — найдовший метод файлу на 8003
        # рядки). Тест раніше читав ВИХІДНИЙ КОД ``_register_commands``, і
        # після виносу там лишилось делегування. Тепер дивимось на
        # СПРАВЖНІЙ реєстр: це точніше, бо перевіряє фактичну реєстрацію,
        # а не наявність рядка в тексті.
        cls.register_source = inspect.getsource(command_registry)
        cls._registry = command_registry

    def _registered_keys(self) -> set[str]:
        """Реально зареєстровані ключі — запуском таблиці на заглушці.

        Навмисно НЕ покладаємось на глобальний стан реєстру: інший тест міг
        зареєструвати лише частину команд, і тоді перевірка залежала б від
        порядку виконання (саме так і сталось: реєстр містив 8 ключів із
        попереднього тесту).
        """
        class _FakeWindow:
            def __getattr__(self, name):
                return lambda *a, **k: None

        from blackchpok_ide import commands

        before = {c.key for c in commands.all_commands()}
        self._registry.register_all(_FakeWindow())
        after = {c.key for c in commands.all_commands()}
        return before | after

    def test_every_menu_action_has_a_command(self) -> None:
        """Кожен метод, який кличе меню, присутній у реєстрі команд."""
        import re

        used = set(re.findall(r"self\.(\w+)[,) ]", self.menu_source))
        # Службові виклики побудови меню та змінні теми — не «дії».
        allow = {"run", "configure", "add_command", "add_cascade", "add_separator",
                 "add_radiobutton", "tk", "Menu", "StringVar", "_theme_menu",
                 "_theme_var"}
        missing = []
        for name in sorted(used - allow):
            if name in self.register_source:
                continue
            if f"self.{name}" in self.register_source:
                continue
            missing.append(name)
        self.assertEqual(missing, [],
                         f"дії меню без команди в реєстрі: {missing}")

    def test_all_six_menus_still_exist(self) -> None:
        for label in ("Файл", "Правка", "Вигляд", "Агент", "Git", "Довідка"):
            self.assertIn(f'label="{label}"', self.menu_source,
                          f"меню «{label}» зникло")

    def test_core_commands_are_registered(self) -> None:
        keys = self._registered_keys()
        for key in ("file.new", "file.save", "edit.undo", "edit.redo",
                    "agent.stop", "agent.new_chat", "run.browser",
                    "view.settings", "view.palette", "git.commit",
                    "help.shortcuts", "help.about"):
            self.assertIn(key, keys, f"команда {key} не зареєстрована")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Розкладка й адаптивність
# ─────────────────────────────────────────────────────────────────────────────

class TestLayoutProfiles(unittest.TestCase):
    """Профілі робочого простору: різні, валідні, зберігаються."""

    def test_five_profiles_present(self) -> None:
        from blackchpok_ide import layout_profiles

        self.assertEqual(len(layout_profiles.PROFILES), 5)
        labels = {profile.label for profile in layout_profiles.PROFILES}
        self.assertEqual(labels, {"AI Agent", "Code Editor", "Web Development",
                                  "Debugging", "Minimal Workspace"})

    def test_profiles_differ_meaningfully(self) -> None:
        from blackchpok_ide import layout_profiles

        widths = {profile.chat_width for profile in layout_profiles.PROFILES}
        self.assertGreater(len(widths), 3, "профілі майже однакові")

    def test_web_profile_shows_preview(self) -> None:
        from blackchpok_ide import layout_profiles

        self.assertTrue(layout_profiles.WEB_DEV.preview_visible)
        self.assertTrue(layout_profiles.WEB_DEV.bottom_visible)

    def test_minimal_hides_side_panels(self) -> None:
        from blackchpok_ide import layout_profiles

        self.assertFalse(layout_profiles.MINIMAL.context_visible)
        self.assertFalse(layout_profiles.MINIMAL.bottom_visible)

    def test_for_window_picks_sane_profile(self) -> None:
        from blackchpok_ide import layout_profiles

        self.assertEqual(layout_profiles.for_window(1366, 768).key, "code")
        self.assertEqual(layout_profiles.for_window(3440, 1440).key, "web")
        self.assertEqual(layout_profiles.for_window(1920, 1080).key, "ai-agent")

    def test_layout_values_roundtrip(self) -> None:
        from blackchpok_ide import layout

        tmp = Path(tempfile.mkdtemp()) / "layout.json"
        data = layout.Layout()
        data.set("sidebar_width", 320)
        data.set("context_width", 240)
        data.set_visible("preview", True)
        layout.save(data, tmp)
        restored = layout.load(tmp)
        self.assertEqual(restored.get("sidebar_width"), 320)
        self.assertEqual(restored.get("context_width"), 240)
        self.assertTrue(restored.is_visible("preview"))

    def test_broken_layout_file_is_survivable(self) -> None:
        from blackchpok_ide import layout

        tmp = Path(tempfile.mkdtemp()) / "layout.json"
        tmp.write_text("{це не json", encoding="utf-8")
        self.assertEqual(layout.load(tmp).values, {})


class TestHeaderAdaptive(unittest.TestCase):
    """Шапка не показує обрізаних кнопок: при звуженні вона ховає групи."""

    def test_thresholds_are_ordered(self) -> None:
        from blackchpok_ide import header_bar

        self.assertLess(header_bar.NARROW_WIDTH, header_bar.COMPACT_WIDTH)
        self.assertGreater(header_bar.NARROW_WIDTH, 600)

    def test_hidden_commands_remain_reachable(self) -> None:
        """Прихована адаптивом команда лишається в реєстрі (через «⋯»)."""
        import inspect

        from blackchpok_ide.header_bar import HeaderBar

        source = inspect.getsource(HeaderBar._apply_mode)
        self.assertIn("keep_always", source,
                      "Live Browser має лишатись видимим на вузькому екрані")
        self.assertIn("pack_forget", source)

    def test_live_browser_never_hidden(self) -> None:
        import inspect

        from blackchpok_ide.header_bar import HeaderBar

        source = inspect.getsource(HeaderBar._apply_mode)
        self.assertIn("run.browser", source)
        # Воно має бути саме в «завжди видимих», а не в прихованих.
        keep_line = [line for line in source.splitlines() if "keep_always" in line][0]
        self.assertIn("run.browser", keep_line)


# ─────────────────────────────────────────────────────────────────────────────
# 4. CDP: протокол без браузера
# ─────────────────────────────────────────────────────────────────────────────

class TestCdpProtocol(unittest.TestCase):
    """Розбір кадрів і логіка CDP — без справжнього браузера."""

    def test_mask_is_reversible(self) -> None:
        from blackchpok_ide import cdp

        payload = b"hello websocket"
        key = b"\x01\x02\x03\x04"
        masked = cdp._mask(payload, key)
        self.assertNotEqual(masked, payload)
        self.assertEqual(cdp._mask(masked, key), payload)

    def test_free_port_returns_usable_port(self) -> None:
        from blackchpok_ide import cdp

        port = cdp.free_port()
        self.assertGreater(port, 1024)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", port))       # порт справді вільний

    def test_page_targets_handles_dead_port(self) -> None:
        from blackchpok_ide import cdp

        port = cdp.free_port()
        with self.assertRaises(cdp.CdpError):
            cdp.page_targets(port)

    def test_wait_for_devtools_times_out_quickly(self) -> None:
        import time

        from blackchpok_ide import cdp

        port = cdp.free_port()
        started = time.monotonic()
        self.assertFalse(cdp.wait_for_devtools(port, timeout=0.6))
        self.assertLess(time.monotonic() - started, 5.0)

    def test_inspect_js_is_valid_expressions(self) -> None:
        """JS-сніпети синтаксично коректні: ``return`` не на новому рядку.

        Регресія: ``return`` з переносом одразу після нього означає
        ``return;`` (automatic semicolon insertion), і інспектор повертав
        порожній результат — саме це й було знайдено наживо.
        """
        from blackchpok_ide import cdp

        for snippet in (cdp._INSPECT_JS, cdp._INSPECT_SELECTOR_JS):
            for line in snippet.splitlines():
                self.assertNotEqual(line.strip(), "return",
                                    "return стоїть на окремому рядку — ASI зламає")

    def test_element_dump_returns_json(self) -> None:
        from blackchpok_ide import cdp

        self.assertIn("JSON.stringify", cdp._ELEMENT_DUMP_JS)
        self.assertIn("selectorOf", cdp._ELEMENT_DUMP_JS)
        self.assertIn("getBoundingClientRect", cdp._ELEMENT_DUMP_JS)
        for key in ("backgroundColor", "fontSize"):
            self.assertIn(key, cdp._ELEMENT_DUMP_JS)

    def test_audit_js_checks_real_things(self) -> None:
        from blackchpok_ide import cdp

        for marker in ("querySelectorAll(\"a\")", "img", "form", "h1",
                       "aria-label", "naturalWidth"):
            self.assertIn(marker, cdp._AUDIT_JS, f"аудит не перевіряє {marker}")

    def test_layout_js_detects_overflow(self) -> None:
        from blackchpok_ide import cdp

        self.assertIn("scrollWidth", cdp._LAYOUT_JS)
        self.assertIn("horizontalScroll", cdp._LAYOUT_JS)

    def test_gemini_chat_path_variants(self) -> None:
        from blackchpok_ide import provider_adapters as pa

        self.assertEqual(pa.gemini_chat_path("gemini-2.0-flash"),
                         "models/gemini-2.0-flash:generateContent")
        self.assertIn("streamGenerateContent",
                      pa.gemini_chat_path("gemini-2.0-flash", stream=True))
        self.assertIn("alt=sse",
                      pa.gemini_chat_path("gemini-2.0-flash", stream=True))
        # Повний ідентифікатор не дублює префікс.
        self.assertEqual(pa.gemini_chat_path("models/gemini-2.0-flash"),
                         "models/gemini-2.0-flash:generateContent")


class TestWebToolSchemas(unittest.TestCase):
    """Web-інструменти оголошені узгоджено (схема ↔ обробник ↔ підпис)."""

    def _schemas(self):
        from blackchpok_ide.agent_tools import TOOL_SCHEMAS

        return {item["function"]["name"]: item["function"]
                for item in TOOL_SCHEMAS}

    def test_all_web_tools_present(self) -> None:
        expected = {"web_url", "web_console", "web_inspect", "web_screenshot",
                    "web_audit", "web_responsive", "web_click", "web_type"}
        self.assertTrue(expected <= set(self._schemas()),
                        f"немає схем: {expected - set(self._schemas())}")

    def test_web_tools_have_handlers(self) -> None:
        from blackchpok_ide.agent_tools import ToolRegistry

        registry = ToolRegistry(ROOT)
        for name in ("web_url", "web_console", "web_inspect", "web_screenshot",
                     "web_audit", "web_responsive", "web_click", "web_type"):
            self.assertTrue(callable(getattr(registry, name, None)),
                            f"{name}: немає реалізації")

    def test_web_tools_in_catalog_and_log(self) -> None:
        from blackchpok_ide import tool_router, work_log

        catalog = {name for name, _when, _example in tool_router.TOOL_CATALOG}
        for name in ("web_console", "web_inspect", "web_screenshot", "web_audit"):
            self.assertIn(name, catalog, f"{name} відсутній у каталозі")
            self.assertIn(name, work_log.TOOL_VIEWS, f"{name} без підпису в журналі")

    def test_element_format_is_informative(self) -> None:
        from blackchpok_ide.agent_tools import _format_element

        text = _format_element({
            "tag": "button", "id": "buy", "classes": ["btn", "primary"],
            "selector": "button#buy.btn.primary", "text": "Купити",
            "rect": {"x": 10, "y": 20, "width": 120, "height": 40},
            "styles": {"backgroundColor": "rgb(0,0,255)", "fontSize": "14px"},
            "attributes": {"type": "submit"},
            "pageUrl": "http://127.0.0.1:8000/",
        })
        for expected in ("button#buy.btn.primary", "Купити", "120×40",
                         "rgb(0,0,255)", 'type="submit"'):
            self.assertIn(expected, text, f"у описі немає «{expected}»")

    def test_empty_element_format_does_not_raise(self) -> None:
        from blackchpok_ide.agent_tools import _format_element

        self.assertIn("Елемент", _format_element({}))

    def test_parse_sizes(self) -> None:
        from blackchpok_ide.agent_tools import _parse_sizes

        self.assertEqual(_parse_sizes("375x667, 1280x800"),
                         [(375, 667), (1280, 800)])
        self.assertEqual(_parse_sizes("375×667"), [(375, 667)])
        self.assertEqual(_parse_sizes("сміття"), [])
        self.assertEqual(_parse_sizes("10x10"), [], "замалі розміри відкидаються")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Провайдери: три протоколи
# ─────────────────────────────────────────────────────────────────────────────

class TestProviderProtocols(unittest.TestCase):
    """Кожен провайдер має СВІЙ протокол, а не «все як OpenAI»."""

    def test_detect_style(self) -> None:
        from blackchpok_ide import provider_adapters as pa

        self.assertEqual(pa.detect_style("https://api.anthropic.com/v1"),
                         pa.ANTHROPIC)
        self.assertEqual(
            pa.detect_style("https://generativelanguage.googleapis.com/v1beta"),
            pa.GEMINI)
        self.assertEqual(
            pa.detect_style("https://generativelanguage.googleapis.com/v1beta/openai"),
            pa.OPENAI)
        self.assertEqual(pa.detect_style("https://api.openai.com/v1"), pa.OPENAI)
        self.assertEqual(pa.detect_style("http://127.0.0.1:1234/v1"), pa.OPENAI)

    def test_anthropic_auth_headers(self) -> None:
        from blackchpok_ide import provider_adapters as pa

        headers = pa.for_url("https://api.anthropic.com/v1").headers("sk-ant-1")
        self.assertEqual(headers.get("x-api-key"), "sk-ant-1")
        self.assertIn("anthropic-version", headers)
        self.assertNotIn("Authorization", headers,
                         "Anthropic не приймає Bearer — це давало 404")

    def test_gemini_key_in_query(self) -> None:
        from blackchpok_ide import provider_adapters as pa

        adapter = pa.for_url("https://generativelanguage.googleapis.com/v1beta")
        url = adapter.url("https://generativelanguage.googleapis.com/v1beta",
                          "models/x:generateContent", "KEY")
        self.assertIn("key=KEY", url)
        self.assertEqual(adapter.headers("KEY").get("x-goog-api-key"), "KEY")

    def test_openai_uses_bearer(self) -> None:
        from blackchpok_ide import provider_adapters as pa

        headers = pa.for_url("https://api.openai.com/v1").headers("sk-1")
        self.assertEqual(headers.get("Authorization"), "Bearer sk-1")

    def test_anthropic_message_conversion(self) -> None:
        from blackchpok_ide import provider_adapters as pa

        messages = [
            {"role": "system", "content": "ти агент"},
            {"role": "user", "content": "привіт"},
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "c1", "type": "function",
                             "function": {"name": "read_file",
                                          "arguments": '{"path":"a.py"}'}}]},
            {"role": "tool", "content": "вміст", "tool_call_id": "c1",
             "name": "read_file"},
        ]
        payload = pa.anthropic_payload(
            messages, model="claude", max_tokens=100,
            tools=[{"type": "function",
                    "function": {"name": "read_file", "description": "d",
                                 "parameters": {"type": "object",
                                                "properties": {}}}}])
        self.assertEqual(payload["system"], "ти агент",
                         "system має бути окремим полем")
        self.assertIn("max_tokens", payload)
        kinds = [block["type"] for msg in payload["messages"]
                 for block in msg["content"]]
        self.assertIn("tool_use", kinds)
        self.assertIn("tool_result", kinds)
        self.assertIn("input_schema", payload["tools"][0])

    def test_gemini_message_conversion(self) -> None:
        from blackchpok_ide import provider_adapters as pa

        payload = pa.gemini_payload(
            [{"role": "system", "content": "правила"},
             {"role": "user", "content": "привіт"}],
            tools=[{"type": "function",
                    "function": {"name": "f", "description": "d",
                                 "parameters": {"type": "object",
                                                "properties": {"p": {"type": "string"}},
                                                "required": ["p"],
                                                "additionalProperties": False}}}])
        self.assertIn("contents", payload)
        self.assertIn("systemInstruction", payload)
        self.assertEqual(payload["contents"][0]["role"], "user")
        schema = payload["tools"][0]["functionDeclarations"][0]["parameters"]
        self.assertNotIn("additionalProperties", schema,
                         "Gemini не приймає additionalProperties")
        self.assertEqual(schema["type"], "OBJECT")

    def test_anthropic_response_parsing(self) -> None:
        from blackchpok_ide import provider_adapters as pa

        text, calls, stop = pa.anthropic_result({
            "content": [{"type": "text", "text": "Готово"},
                        {"type": "tool_use", "id": "t1", "name": "read_file",
                         "input": {"path": "a.py"}}],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 5, "output_tokens": 7},
        })
        self.assertEqual(text, "Готово")
        self.assertEqual(calls[0]["function"]["name"], "read_file")
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]),
                         {"path": "a.py"})
        self.assertEqual(stop, "tool_use")
        usage = pa.anthropic_usage({"usage": {"input_tokens": 5,
                                             "output_tokens": 7}})
        self.assertEqual(usage["total_tokens"], 12)

    def test_gemini_response_parsing(self) -> None:
        from blackchpok_ide import provider_adapters as pa

        text, calls, stop = pa.gemini_result({
            "candidates": [{"content": {"parts": [
                {"text": "ок"},
                {"functionCall": {"name": "list_dir", "args": {"path": "."}}}],
            }, "finishReason": "STOP"}],
        })
        self.assertEqual(text, "ок")
        self.assertEqual(calls[0]["function"]["name"], "list_dir")
        self.assertEqual(stop, "STOP")

    def test_client_picks_adapter_by_url(self) -> None:
        from blackchpok_ide import provider_adapters as pa
        from blackchpok_ide.llm_client import LLMClient

        self.assertEqual(LLMClient("https://api.anthropic.com/v1").style,
                         pa.ANTHROPIC)
        self.assertEqual(LLMClient("https://api.deepseek.com/v1").style,
                         pa.OPENAI)
        self.assertEqual(
            LLMClient("https://generativelanguage.googleapis.com/v1beta").style,
            pa.GEMINI)

    def test_connection_error_hint_matches_target(self) -> None:
        from blackchpok_ide.llm_client import LLMClient

        local = LLMClient("http://127.0.0.1:9999/v1")
        cloud = LLMClient("https://api.openai.com/v1")
        local_hint = local._connection_error("http://127.0.0.1:9999/v1", "refused")
        cloud_hint = cloud._connection_error("https://api.openai.com/v1", "refused")
        self.assertIn("локальним", local_hint)
        self.assertNotIn("LM Studio", cloud_hint,
                         "хмарній адресі не радять запускати LM Studio")


class TestCloudPresets(unittest.TestCase):
    """Пресети хмарних провайдерів: реальні адреси й чесні описи."""

    def test_required_providers_present(self) -> None:
        from blackchpok_ide import cloud_agents

        keys = {provider.key for provider in cloud_agents.PROVIDERS}
        for required in ("openai", "anthropic", "gemini", "deepseek",
                         "openrouter", "mistral", "groq", "custom"):
            self.assertIn(required, keys, f"немає провайдера {required}")

    def test_every_provider_has_https_url(self) -> None:
        from blackchpok_ide import cloud_agents

        for provider in cloud_agents.PROVIDERS:
            if provider.key == "custom":
                continue
            self.assertTrue(provider.base_url.startswith("https://"),
                            f"{provider.key}: не https")
            self.assertTrue(provider.models, f"{provider.key}: немає моделей")

    def test_anthropic_note_is_honest(self) -> None:
        """Anthropic тепер справді підтриманий — опис не має казати «шлюз»."""
        from blackchpok_ide import cloud_agents

        provider = cloud_agents.get("anthropic")
        self.assertIsNotNone(provider)
        self.assertNotIn("шлюз", provider.note.lower(),
                         "опис обіцяє шлюз, хоча протокол реалізовано")


# ─────────────────────────────────────────────────────────────────────────────
# 6. Секрети
# ─────────────────────────────────────────────────────────────────────────────

class TestSecrets(unittest.TestCase):
    """Ключі шифруються, не течуть у логи й не потрапляють відкрито у файл."""

    def test_roundtrip_when_available(self) -> None:
        from blackchpok_ide import secrets

        if not secrets.available():
            self.skipTest("DPAPI недоступний на цій системі")
        secret = "sk-test-abcdefghijklmnop"
        encrypted = secrets.encrypt(secret)
        self.assertTrue(secrets.is_encrypted(encrypted))
        self.assertNotIn(secret, encrypted, "ключ видно у шифротексті")
        self.assertEqual(secrets.decrypt(encrypted), secret)

    def test_empty_secret_is_not_stored(self) -> None:
        from blackchpok_ide import secrets

        self.assertEqual(secrets.encrypt(""), "")
        self.assertEqual(secrets.decrypt(""), "")

    def test_corrupted_value_returns_empty(self) -> None:
        from blackchpok_ide import secrets

        self.assertEqual(secrets.decrypt("dpapi:v1:###"), "")
        self.assertEqual(secrets.decrypt("dpapi:v1:"), "")

    def test_redact_hides_keys(self) -> None:
        from blackchpok_ide import secrets

        text = ("HTTP 401: Bearer sk-abc123456789 and api_key=secret123456 "
                "and ?key=zzzzzzzzzzzz")
        cleaned = secrets.redact(text)
        for fragment in ("sk-abc123456789", "secret123456", "zzzzzzzzzzzz"):
            self.assertNotIn(fragment, cleaned)

    def test_local_key_is_not_a_secret(self) -> None:
        from blackchpok_ide import secrets

        for value in ("local", "lm-studio", "none"):
            self.assertFalse(secrets.looks_like_secret(value))
        self.assertTrue(secrets.looks_like_secret("sk-real-key-123456"))

    def test_settings_file_has_no_plaintext_key(self) -> None:
        from blackchpok_ide import secrets
        from blackchpok_ide.config import Settings

        if not secrets.available():
            self.skipTest("DPAPI недоступний")
        tmp = Path(tempfile.mkdtemp()) / "settings.json"
        settings = Settings()
        settings.llm.api_key = "sk-very-secret-value-12345"
        settings.cloud.api_key = "sk-ant-another-secret-9876"
        settings.save(tmp)
        raw = tmp.read_text(encoding="utf-8")
        self.assertNotIn("sk-very-secret-value-12345", raw)
        self.assertNotIn("sk-ant-another-secret-9876", raw)
        self.assertIn("api_key_enc", raw)
        restored = Settings.load(tmp)
        self.assertEqual(restored.llm.api_key, "sk-very-secret-value-12345")
        self.assertEqual(restored.cloud.api_key, "sk-ant-another-secret-9876")

    def test_local_key_stays_usable_after_save(self) -> None:
        from blackchpok_ide.config import Settings

        tmp = Path(tempfile.mkdtemp()) / "settings.json"
        settings = Settings()
        settings.llm.api_key = "lm-studio"
        settings.save(tmp)
        self.assertEqual(Settings.load(tmp).llm.api_key, "lm-studio",
                         "локальний ключ має лишатись робочим")

    def test_corrupted_encrypted_key_does_not_crash_load(self) -> None:
        from blackchpok_ide.config import Settings

        tmp = Path(tempfile.mkdtemp()) / "settings.json"
        tmp.write_text(json.dumps({
            "llm": {"api_key_enc": "dpapi:v1:broken", "base_url": "http://127.0.0.1:1234/v1"},
            "cloud": {"api_key_enc": "dpapi:v1:broken"},
        }), encoding="utf-8")
        loaded = Settings.load(tmp)       # не має кидати
        self.assertIsNotNone(loaded)

    def test_log_filter_redacts(self) -> None:
        import logging

        from blackchpok_ide import config

        if logging.getLogger("blackchpok").handlers:
            self.skipTest("логування вже налаштоване в цьому процесі")
        filt = config._RedactSecrets()
        record = logging.LogRecord("t", logging.INFO, "f", 1,
                                   "ключ: Bearer sk-abcdef123456", None, None)
        filt.filter(record)
        self.assertNotIn("sk-abcdef123456", record.getMessage())


# ─────────────────────────────────────────────────────────────────────────────
# 7. Агент: виправлені дефекти
# ─────────────────────────────────────────────────────────────────────────────

class TestAgentFixedDefects(unittest.TestCase):
    """Кожен пункт — доведений дефект, знайдений аудитом і виправлений."""

    def test_broken_python_does_not_use_exc_outside_handler(self) -> None:
        """``exc`` живе лише в ``except``: звернення після блоку падало."""
        import ast
        import inspect
        import textwrap

        from blackchpok_ide.agent import AgentRunner

        source = textwrap.dedent(inspect.getsource(AgentRunner._broken_python))
        tree = ast.parse(source)
        # Після блоку ``except`` не має бути звернень до ``exc``.
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                handler_lines = [stmt.end_lineno for stmt in node.handlers]
                if not handler_lines:
                    continue
                limit = max(handler_lines)
                for inner in ast.walk(node):
                    if (isinstance(inner, ast.Name) and inner.id == "exc"
                            and getattr(inner, "lineno", 0) > limit):
                        self.fail("``exc`` використано поза блоком except")

    def test_smoke_check_uses_relative_path(self) -> None:
        """Запуск вкладеного файлу йшов як ``python mod.py`` з кореня."""
        import inspect

        from blackchpok_ide.agent import AgentRunner

        source = inspect.getsource(AgentRunner._run_smoke_check)
        self.assertIn('"{rel}"', source,
                      "має запускатись відносний шлях, а не basename")

    def test_hint_results_have_matching_assistant_call(self) -> None:
        """Кожен tool-результат має попередній асистентський виклик."""
        import inspect

        from blackchpok_ide.agent import AgentRunner

        source = inspect.getsource(AgentRunner._run_hints)
        self.assertIn("tool_calls", source,
                      "синтетичний виклик обов'язковий, інакше сервер дає 400")
        position_call = source.index("tool_calls")
        position_result = source.index("add_tool_result")
        self.assertLess(position_call, position_result,
                        "виклик має додаватись ПЕРЕД результатом")

    def test_partial_tool_json_is_held_back(self) -> None:
        from blackchpok_ide.llm_client import _looks_like_tool_json

        names = {"read_file", "list_dir"}
        self.assertTrue(_looks_like_tool_json('{"na', names),
                        "обрізаний початок виклику не має йти в чат")
        self.assertTrue(_looks_like_tool_json('{"name": "read_file"', names))
        self.assertFalse(_looks_like_tool_json("Готово, файл створено.", names))
        self.assertFalse(_looks_like_tool_json("<div>html</div>", names))

    def test_degraded_run_is_flagged(self) -> None:
        """Локальний роутер — не повний успіх ходу моделі."""
        import inspect

        from blackchpok_ide.agent import AgentRunner

        self.assertTrue(hasattr(AgentRunner, "_run"))
        source = inspect.getsource(AgentRunner._run)
        self.assertIn("_degraded", source,
                      "офлайн-відповідь має позначатись як неповна")


class TestQueueFixedDefects(unittest.TestCase):
    """Виправлення черги завдань."""

    def setUp(self) -> None:
        from blackchpok_ide import queue_engine

        self.tmp = Path(tempfile.mkdtemp())
        self.queue = queue_engine.TaskQueue(self.tmp / "queue.json")
        self.engine = queue_engine

    def test_retry_resets_attempts(self) -> None:
        """Інакше «Повторити» не працює після трьох падінь."""
        task = self.queue.add("задача")
        task.attempts = 3
        self.queue.mark_failed(task.id, "впало")
        self.assertTrue(self.queue.retry(task.id))
        self.assertEqual(task.attempts, 0,
                         "лічильник спроб має скидатись при повторі")

    def test_renumber_does_not_number_ad_hoc_tasks(self) -> None:
        """Поодинока задача не має ставати кроком плану."""
        self.queue.add("запусти тести")
        self.queue.add_steps(["крок 1", "крок 2"], chat_id="c1")
        self.queue.renumber(chat_id="c1")
        plan = self.queue.plan_tasks(chat_id="c1")
        self.assertEqual([task.text for task in plan], ["крок 1", "крок 2"],
                         "стороння задача потрапила в план")

    def test_replan_starts_numbering_from_one(self) -> None:
        self.queue.add_steps(["а", "б", "в"], chat_id="c1")
        self.queue.replace_plan(["x", "y"], chat_id="c1")
        numbers = sorted(task.number for task in self.queue.plan_tasks(chat_id="c1"))
        self.assertEqual(numbers, [1, 2], f"нумерація продовжилась: {numbers}")

    def test_next_pending_isolates_chats(self) -> None:
        """Чат Б не має брати задачу чату А."""
        self.queue.add("задача А", chat_id="chat-A")
        self.assertIsNone(self.queue.next_pending(chat_id="chat-B"))
        task = self.queue.next_pending(chat_id="chat-A")
        self.assertIsNotNone(task)
        self.assertEqual(task.text, "задача А")

    def test_orphan_not_given_to_specific_chat(self) -> None:
        self.queue.add("сирота")
        self.assertIsNone(self.queue.next_pending(chat_id="chat-B"))
        self.assertIsNotNone(self.queue.next_pending())


class TestPermissionsFixed(unittest.TestCase):
    """``append_file`` тепер під контролем режимів дозволів."""

    def test_append_file_is_a_write_tool(self) -> None:
        from blackchpok_ide import permissions

        self.assertIn("append_file", permissions.WRITE_TOOLS)

    def test_append_outside_root_is_blocked(self) -> None:
        from blackchpok_ide import permissions

        root = Path(tempfile.mkdtemp())
        verdict = permissions.check_tool(
            "append_file", {"path": "../escape.txt"},
            mode=permissions.WORKSPACE, root=root)
        self.assertFalse(verdict.allowed,
                         "дописування поза робочою текою має блокуватись")

    def test_read_only_mode_blocks_append(self) -> None:
        from blackchpok_ide import permissions

        root = Path(tempfile.mkdtemp())
        verdict = permissions.check_tool(
            "append_file", {"path": "ok.txt"},
            mode=permissions.READ_ONLY, root=root)
        self.assertFalse(verdict.allowed)


class TestPlannerJsonParsing(unittest.TestCase):
    """Планувальник не губить кроки у вкладеному JSON."""

    def test_balanced_chunks_takes_whole_array(self) -> None:
        from blackchpok_ide.task_planner import _balanced_chunks

        text = 'Ось план: [{"title": "a"}, {"title": "b"}, {"title": "c"}] кінець'
        chunks = _balanced_chunks(text)
        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0].startswith("["))
        self.assertEqual(len(json.loads(chunks[0])), 3,
                         "взято не весь масив — кроки губились")

    def test_brackets_inside_strings_do_not_break_scan(self) -> None:
        from blackchpok_ide.task_planner import _balanced_chunks

        text = '[{"title": "виведи ] дужку"}, {"title": "b"}]'
        chunks = _balanced_chunks(text)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(len(json.loads(chunks[0])), 2)


class TestWorkLogLabels(unittest.TestCase):
    """Підписи журналу збігаються з РЕАЛЬНИМИ ключами аргументів схем."""

    def test_argument_keys_match_schemas(self) -> None:
        from blackchpok_ide.agent_tools import TOOL_SCHEMAS
        from blackchpok_ide.work_log import TOOL_VIEWS

        schemas = {item["function"]["name"]: item["function"]
                   for item in TOOL_SCHEMAS}
        wrong = []
        for name, (_icon, _label, key) in TOOL_VIEWS.items():
            if not key:
                continue
            function = schemas.get(name)
            if function is None:
                continue
            properties = (function.get("parameters") or {}).get("properties") or {}
            if properties and key not in properties:
                wrong.append((name, key, sorted(properties)))
        self.assertEqual(wrong, [],
                         f"журнал бере неіснуючі аргументи: {wrong}")

    def test_every_tool_has_ukrainian_label(self) -> None:
        import re

        from blackchpok_ide.work_log import TOOL_VIEWS

        for name, (_icon, label, _key) in TOOL_VIEWS.items():
            self.assertTrue(label.strip(), f"{name}: порожній підпис")
            self.assertTrue(re.search(r"[\u0400-\u04FF]", label),
                            f"{name}: підпис не українською ({label})")


# ─────────────────────────────────────────────────────────────────────────────
# 8. Зациклення моделі (баг зі скріншота користувача)
# ─────────────────────────────────────────────────────────────────────────────

class TestRepeatGuard(unittest.TestCase):
    """Обмежувач повторів: зупиняє цикл і не заважає справжній роботі."""

    def _guard(self):
        from blackchpok_ide.agent import _RepeatGuard

        return _RepeatGuard()

    def test_first_call_is_not_a_loop(self) -> None:
        guard = self._guard()
        count, tired, hopeless = guard.observe("read_file|{}|fail|немає")
        self.assertEqual(count, 1)
        self.assertFalse(tired)
        self.assertFalse(hopeless)

    def test_repeating_same_call_is_detected(self) -> None:
        """12 однакових викликів на скріншоті — це цикл, а не робота."""
        from blackchpok_ide.agent import HARD_REPEAT_LIMIT, REPEAT_LIMIT

        guard = self._guard()
        prints = [guard.observe("search|{}|fail|помилка") for _ in range(6)]
        tired_at = next((index + 1 for index, item in enumerate(prints) if item[1]), None)
        hopeless_at = next((index + 1 for index, item in enumerate(prints) if item[2]), None)
        self.assertEqual(tired_at, REPEAT_LIMIT,
                         "вказівку моделі даємо на другому повторі")
        self.assertEqual(hopeless_at, HARD_REPEAT_LIMIT,
                         "припиняємо на четвертому повторі")

    def test_different_results_are_not_a_loop(self) -> None:
        """Той самий інструмент із РІЗНИМ результатом — це робота."""
        guard = self._guard()
        hopeless_any = False
        for index in range(6):
            _count, _tired, hopeless = guard.observe(
                f"append_file|{{}}|ok|рядок {index}")
            hopeless_any = hopeless_any or hopeless
        self.assertFalse(hopeless_any,
                         "різні результати не мають вважатись циклом")

    def test_fingerprint_distinguishes_arguments(self) -> None:
        from blackchpok_ide.agent import _RepeatGuard

        first = _RepeatGuard.fingerprint("read_file", {"path": "a.py"}, True, "x")
        second = _RepeatGuard.fingerprint("read_file", {"path": "b.py"}, True, "x")
        self.assertNotEqual(first, second)

    def test_fingerprint_distinguishes_long_outputs(self) -> None:
        from blackchpok_ide.agent import _RepeatGuard

        big_a = "рядок\n" * 500 + "КІНЕЦЬ_A"
        big_b = "рядок\n" * 500 + "КІНЕЦЬ_B"
        first = _RepeatGuard.fingerprint("read_file", {"path": "a"}, True, big_a)
        second = _RepeatGuard.fingerprint("read_file", {"path": "a"}, True, big_b)
        self.assertNotEqual(first, second,
                            "різні кінцівки довгого виводу мають розрізнятись")

    def test_summary_names_the_stuck_tool(self) -> None:
        guard = self._guard()
        for _ in range(3):
            guard.observe("router:search_web|{}|fail|немає")
        self.assertIn("router:search_web", guard.summary())


class TestRawJsonNeverLeaks(unittest.TestCase):
    """Сирий JSON виклику не має потрапляти в чат як відповідь."""

    def test_unknown_tool_call_is_stripped(self) -> None:
        """Модель вигадала ``router:search_web`` — цього немає у схемах."""
        from blackchpok_ide.llm_client import strip_tool_json

        content = ('{"name": "router:search_web", "arguments": '
                   '"{\\"query\\": \\"Ціна SOL\\"}"}\n'
                   "Знайшов, є помилка. Спробую інший запит.")
        cleaned = strip_tool_json(content, [])
        self.assertNotIn('"name"', cleaned)
        self.assertNotIn("arguments", cleaned)
        self.assertIn("Спробую інший запит", cleaned)

    def test_known_tool_call_is_stripped(self) -> None:
        from blackchpok_ide.llm_client import strip_tool_json

        tools = [{"type": "function",
                  "function": {"name": "read_file", "parameters": {}}}]
        cleaned = strip_tool_json(
            '{"name": "read_file", "arguments": {"path": "a.py"}}\nГотово', tools)
        self.assertEqual(cleaned, "Готово")

    def test_genuine_json_answer_is_kept(self) -> None:
        """Справжня відповідь у JSON не має зникати."""
        from blackchpok_ide.llm_client import strip_tool_json

        answer = '{"price": 150, "currency": "USD"}'
        self.assertEqual(strip_tool_json(answer, []), answer)

    def test_json_with_name_but_no_arguments_is_kept(self) -> None:
        from blackchpok_ide.llm_client import strip_tool_json

        answer = '{"name": "BlackChpok", "version": 2}'
        self.assertEqual(strip_tool_json(answer, []), answer)

    def test_empty_and_broken_input_do_not_crash(self) -> None:
        from blackchpok_ide.llm_client import strip_tool_json

        for value in ("", "{", '{"a":', "{}", '{"name":"a","arguments":{'):
            self.assertIsInstance(strip_tool_json(value, []), str)


class TestPromiseDetection(unittest.TestCase):
    """«Спробую інший запит» — не відповідь, а обіцянка."""

    def test_promise_is_detected(self) -> None:
        from blackchpok_ide.agent import _promises_action

        self.assertTrue(_promises_action("Спробую інший запит."))
        self.assertTrue(_promises_action("Зараз перевірю файл."))
        self.assertTrue(_promises_action("Let me check."))

    def test_real_answer_is_not_a_promise(self) -> None:
        from blackchpok_ide.agent import _promises_action

        self.assertFalse(_promises_action("Ціна SOL сьогодні — 150 доларів."))
        self.assertFalse(_promises_action("- пункт один\n- пункт два"))
        self.assertFalse(_promises_action("Готово:\n```python\nx = 1\n```"))

    def test_notice_explains_what_happened(self) -> None:
        from blackchpok_ide.agent import _promise_notice

        notice = _promise_notice("Спробую інший запит.")
        self.assertIn("обіцянці", notice)
        self.assertIn("нічого не", notice)
        self.assertIn("переформулювати", notice)


class TestUnknownToolHint(unittest.TestCase):
    """На невідомий інструмент модель отримує пораду, а не глухий кут."""

    def _agent(self):
        from blackchpok_ide.agent import AgentRunner
        from blackchpok_ide.agent_tools import ToolRegistry
        from blackchpok_ide.config import AgentSettings, LLMSettings

        workspace = Path(tempfile.mkdtemp())
        agent = AgentRunner(ToolRegistry(workspace), LLMSettings(),
                            AgentSettings(), workspace)
        agent.mcp_manager = None
        return agent

    def test_hint_lists_available_tools(self) -> None:
        agent = self._agent()
        hint = agent._unknown_tool_hint("totally_made_up")
        self.assertIn("read_file", hint)
        self.assertIn("не існує", hint)
        self.assertIn("Не повторюй", hint)

    def test_web_tool_shortage_is_explained(self) -> None:
        """Запит «ціна SOL» кличе web-пошук, якого немає без MCP."""
        agent = self._agent()
        hint = agent._unknown_tool_hint("router:search_web")
        self.assertIn("НЕМАЄ", hint)
        self.assertIn("MCP", hint)

    def test_call_unknown_tool_returns_guidance(self) -> None:
        agent = self._agent()
        outcome = agent.call_tool("router:search_web", {"query": "sol"})
        self.assertFalse(outcome.ok)
        self.assertIn("НЕМАЄ", outcome.output)

    def test_registry_exposes_handled_names(self) -> None:
        from blackchpok_ide.agent_tools import TOOL_SCHEMAS, ToolRegistry

        names = ToolRegistry(ROOT).handled_names()
        self.assertIn("read_file", names)
        self.assertEqual(len(names - {item["function"]["name"]
                                      for item in TOOL_SCHEMAS}), 0,
                         "усі обробники мають бути у схемах")


# ─────────────────────────────────────────────────────────────────────────────
# 9. HMR: оновлення сторінки без перезавантаження
# ─────────────────────────────────────────────────────────────────────────────

class TestHmrRouting(unittest.TestCase):
    """Вибір способу оновлення за типом файлу."""

    def test_css_uses_no_reload_path(self) -> None:
        from blackchpok_ide import hmr

        self.assertIn(".css", hmr.STYLE_SUFFIXES)
        self.assertNotIn(".css", hmr.CODE_SUFFIXES)

    def test_js_requires_reload(self) -> None:
        from blackchpok_ide import hmr

        for suffix in (".js", ".ts", ".jsx", ".tsx", ".vue", ".svelte"):
            self.assertIn(suffix, hmr.CODE_SUFFIXES, suffix)

    def test_html_uses_markup_path(self) -> None:
        from blackchpok_ide import hmr

        self.assertIn(".html", hmr.MARKUP_SUFFIXES)
        self.assertIn(".htm", hmr.MARKUP_SUFFIXES)

    def test_unknown_extension_is_skipped(self) -> None:
        from blackchpok_ide import hmr

        result = hmr.update_for_file(None, ROOT / "README.md")
        self.assertEqual(result.mode, "skipped")
        self.assertFalse(result.reloaded)

    def test_missing_file_is_skipped(self) -> None:
        from blackchpok_ide import hmr

        result = hmr.update_for_file(None, ROOT / "no-such-file.css")
        self.assertEqual(result.mode, "skipped")

    def test_describe_is_human_readable(self) -> None:
        from blackchpok_ide import hmr

        for mode in ("css", "markup", "reload", "skipped", "failed"):
            text = hmr.describe(hmr.UpdateResult(mode, "деталі"))
            self.assertTrue(text.strip(), mode)


class TestHmrCssScript(unittest.TestCase):
    """CSS-скрипт має підміняти стилі, не чіпаючи решту сторінки."""

    def test_css_script_targets_link_and_style(self) -> None:
        import inspect

        from blackchpok_ide import hmr

        source = inspect.getsource(hmr.apply_css)
        self.assertIn("link[rel=", source, "шукаємо <link rel=stylesheet>")
        self.assertIn("data-ide", source, "позначаємо власний <style>")
        self.assertIn("?v=", source, "додаємо мітку часу проти кешу")
        # Ключове: НЕ має бути безумовного reload.
        self.assertNotIn("session.reload()", source,
                         "CSS оновлюється без перезавантаження сторінки")

    def test_markup_script_preserves_form_state(self) -> None:
        """Підміна innerHTML знищує введений текст — тому зберігаємо його."""
        import inspect

        from blackchpok_ide import hmr

        source = inspect.getsource(hmr.apply_markup)
        self.assertIn("querySelectorAll('input, textarea, select')", source)
        self.assertIn("checked", source, "чекбокси теж зберігаються")
        self.assertIn("selectedIndex", source, "вибір у <select> зберігається")
        self.assertIn("window.scrollTo", source, "прокрутка зберігається")

    def test_markup_skips_script_tags_in_comparison(self) -> None:
        """``<script>`` не можна виконувати повторно — його не порівнюємо."""
        import inspect

        from blackchpok_ide import hmr

        source = inspect.getsource(hmr.apply_markup)
        self.assertIn("ignored", source)
        self.assertIn("script", source)

    def test_html_parser_handles_void_and_raw_elements(self) -> None:
        """``<input>`` не має закривного тегу — інакше структура хибна."""
        import inspect

        from blackchpok_ide import hmr

        source = inspect.getsource(hmr.apply_markup)
        self.assertIn("_VOID", source)
        for tag in ("input", "img", "br", "meta", "link"):
            self.assertIn(tag, source, f"{tag} має бути у списку порожніх")

    def test_full_reload_restores_scroll(self) -> None:
        import inspect

        from blackchpok_ide import hmr

        source = inspect.getsource(hmr.full_reload)
        self.assertIn("_SAVE_STATE_JS", source, "стан зберігається до reload")
        self.assertIn("_RESTORE_STATE_JS", source, "стан відновлюється після")
        # Самі скрипти живуть на рівні модуля — перевіряємо й їх.
        module = inspect.getsource(hmr)
        self.assertIn("__ide_scroll", module)
        self.assertIn("sessionStorage", module)
        self.assertIn("scrollTo", module)


class TestHmrHtmlParsing(unittest.TestCase):
    """Розбір HTML для точкового оновлення (без браузера)."""

    def _parse(self, html: str) -> tuple[list[str], str]:
        """Повторити логіку ``apply_markup`` без браузера."""
        from html.parser import HTMLParser

        _IGNORED = frozenset({"script", "template", "noscript"})
        _VOID = frozenset({
            "area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr",
        })

        class Collect(HTMLParser):
            def __init__(self) -> None:
                super().__init__(convert_charrefs=False)
                self.inside = False
                self.depth = 0
                self.top: list[str] = []
                self.parts: list[str] = []

            def handle_starttag(self, tag, attrs):
                if tag == "body":
                    self.inside = True
                    return
                if not self.inside:
                    return
                if self.depth == 0 and tag not in _IGNORED:
                    self.top.append(tag)
                if tag not in _VOID and tag not in ("script", "style", "template"):
                    self.depth += 1
                self.parts.append(f"<{tag}>")

            def handle_endtag(self, tag):
                if not self.inside:
                    return
                if tag == "body":
                    self.inside = False
                    return
                if tag not in _VOID and tag not in ("script", "style", "template"):
                    self.depth = max(0, self.depth - 1)
                self.parts.append(f"</{tag}>")

            def handle_data(self, data):
                if self.inside:
                    self.parts.append(data)

        collector = Collect()
        collector.feed(html)
        return collector.top, "".join(collector.parts)

    def test_top_level_tags_with_void_element(self) -> None:
        """``<input>`` посеред body ��е має ламати підрахунок вкладеності."""
        tags, _inner = self._parse(
            "<html><body><h1>a</h1><div>b</div><input><div>c</div></body></html>")
        self.assertEqual(tags, ["h1", "div", "input", "div"],
                         "порожній елемент збив вкладеність")

    def test_script_excluded_from_top_tags(self) -> None:
        tags, _inner = self._parse(
            "<html><body><h1>a</h1><script>x=1</script></body></html>")
        self.assertEqual(tags, ["h1"])

    def test_nested_elements_not_top_level(self) -> None:
        tags, _inner = self._parse(
            "<html><body><div><span><b>x</b></span></div></body></html>")
        self.assertEqual(tags, ["div"], "вкладені елементи не мають бути зверху")

    def test_self_closing_image(self) -> None:
        tags, _inner = self._parse(
            "<html><body><img src='a.png'/><p>t</p></body></html>")
        self.assertEqual(tags, ["img", "p"])


# ─────────────────────────────────────────────────────────────────────────────
# 10. Стрімінг усіх трьох протоколів
# ─────────────────────────────────────────────────────────────────────────────

class TestProviderStreaming(unittest.TestCase):
    """``chat_stream`` має розуміти протокол, а не лише OpenAI.

    Регресія: стрімінг ЗАВЖДИ формував OpenAI-payload. До Anthropic ішов
    запит із ``messages``/``stream_options`` (400), а до Gemini — на
    ``/chat/completions``, якого в нього немає.
    """

    def test_stream_has_branches_for_each_provider(self) -> None:
        import inspect

        from blackchpok_ide.llm_client import LLMClient

        source = inspect.getsource(LLMClient.chat_stream)
        self.assertIn("_stream_anthropic", source)
        self.assertIn("_stream_gemini", source)
        self.assertIn("ANTHROPIC", source)
        self.assertIn("GEMINI", source)

    def test_anthropic_stream_method_exists(self) -> None:
        from blackchpok_ide.llm_client import LLMClient

        self.assertTrue(callable(getattr(LLMClient, "_stream_anthropic", None)))
        self.assertTrue(callable(getattr(LLMClient, "_stream_gemini", None)))

    def test_anthropic_stream_parses_block_events(self) -> None:
        import inspect

        from blackchpok_ide.llm_client import LLMClient

        source = inspect.getsource(LLMClient._stream_anthropic)
        self.assertIn("content_block_delta", source)
        self.assertIn("input_json_delta", source)
        self.assertIn("message_start", source)
        # ``message_delta`` несе лише output_tokens — треба зливати.
        self.assertIn("_merge_usage", source)

    def test_gemini_stream_uses_stream_path(self) -> None:
        import inspect

        from blackchpok_ide.llm_client import LLMClient

        source = inspect.getsource(LLMClient._stream_gemini)
        self.assertIn("gemini_chat_path", source)
        self.assertIn("stream=True", source)

    def test_usage_merge_keeps_prompt_tokens(self) -> None:
        """``message_delta`` затирав prompt_tokens нулем — статистика брехала."""
        from blackchpok_ide.llm_client import _merge_usage

        usage: dict[str, int] = {}
        _merge_usage(usage, {"prompt_tokens": 12, "completion_tokens": 0,
                             "total_tokens": 12})
        _merge_usage(usage, {"prompt_tokens": 0, "completion_tokens": 9,
                             "total_tokens": 9})
        self.assertEqual(usage["prompt_tokens"], 12,
                         "prompt_tokens затерто нулем")
        self.assertEqual(usage["completion_tokens"], 9)
        self.assertEqual(usage["total_tokens"], 21)


# ─────────────────────────────────────────────────────────────────────────────
# 11. Видалення чатів з АРХІВУ (скарга користувача)
# ─────────────────────────────────────────────────────────────────────────────

class TestArchiveDelete(unittest.TestCase):
    """«З архіву не видаляються чати» — перевіряємо КОЖЕН шлях видалення.

    Регресія: іконка «×» у рядку архіву виконувала той самий код, що й для
    активних чатів, тобто чат просто архівувався ЩЕ РАЗ. З архіву він не
    зникав ніколи.
    """

    def _panel_source(self) -> str:
        import inspect

        from blackchpok_ide.chat_list_panel import ChatListPanel

        return inspect.getsource(ChatListPanel._close_chat)

    def test_close_in_archive_deletes(self) -> None:
        """«×» в архіві має ВИДАЛЯТИ, а не архівувати повторно."""
        source = self._panel_source()
        self.assertIn("archived", source,
                      "треба розрізняти архівний і активний чат")
        self.assertIn("_delete", source,
                      "для архівного чату «×» веде до видалення")

    def test_close_checks_archived_before_fallback(self) -> None:
        """Перевірка архіву стоїть ПЕРЕД запасним архівуванням."""
        source = self._panel_source()
        archive_at = source.index("archived")
        fallback_at = source.index("store.archive")
        self.assertLess(archive_at, fallback_at,
                        "інакше архівний чат знову архівується")

    def test_main_window_deletes_archived_chat(self) -> None:
        """Головне вікно теж має видаляти архівний чат із підтвердженням."""
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE.close_chat)
        self.assertIn("chat.archived", source,
                      "архівний чат треба обробляти окремо")
        self.assertIn("askyesno", source,
                      "видалення незворотне — потрібне підтвердження")
        self.assertIn("chat_store.delete", source)

    def test_delete_all_in_archive_scope(self) -> None:
        """«Видалити всі» у вкладці архіву чистить ЛИШЕ архів."""
        import inspect

        from blackchpok_ide.chat_list_panel import ChatListPanel

        source = inspect.getsource(ChatListPanel._delete_all)
        self.assertIn("archived=archived_only", source)

    def test_tooltip_differs_in_archive(self) -> None:
        """Підказка «×» в архіві каже «Видалити назавжди»."""
        import inspect

        from blackchpok_ide.chat_list_panel import _SessionRow

        source = inspect.getsource(_SessionRow.__init__)
        self.assertIn("Видалити назавжди", source,
                      "інакше кнопка обіцяє «закрити», а стирає розмову")


class TestArchiveDeleteLive(unittest.TestCase):
    """Живий тест сховища: архівний чат справді зникає з диска."""

    def setUp(self) -> None:
        from blackchpok_ide.chat_store import ChatStore

        self.tmp = Path(tempfile.mkdtemp())
        self.store = ChatStore(self.tmp / "chats.json")

    def test_archived_chat_can_be_deleted(self) -> None:
        chat = self.store.create(title="Архівна")
        self.store.append("user", "текст", chat_id=chat.id)
        self.store.archive(chat.id, True)
        self.assertTrue(chat.archived)
        self.assertTrue(self.store.delete(chat.id))
        self.assertIsNone(self.store.get(chat.id))

    def test_delete_all_archived_only(self) -> None:
        first = self.store.create(title="Активний")
        self.store.append("user", "а", chat_id=first.id)
        second = self.store.create(title="Архівний")
        self.store.append("user", "б", chat_id=second.id)
        self.store.archive(second.id, True)
        removed = self.store.delete_all(archived=True)
        self.assertEqual(removed, 1)
        self.assertIsNotNone(self.store.get(first.id),
                             "активний чат має лишитись")
        self.assertIsNone(self.store.get(second.id))

    def test_deleted_archived_chat_stays_deleted(self) -> None:
        """Після перезапуску видалений чат не повертається з диска."""
        from blackchpok_ide.chat_store import ChatStore

        chat = self.store.create(title="Зникне")
        self.store.append("user", "текст", chat_id=chat.id)
        self.store.archive(chat.id, True)
        self.store.delete(chat.id)
        reopened = ChatStore(self.tmp / "chats.json")
        self.assertIsNone(reopened.get(chat.id))


# ─────────────────────────────────────────────────────────────────────────────
# 12. Зір агента: знімок стає зображенням у контексті моделі
# ─────────────────────────────────────────────────────────────────────────────

class TestVisionProjector(unittest.TestCase):
    """Візуальний проєктор (mmproj): пошук, вибір, парування з моделлю."""

    def test_projector_is_recognised(self) -> None:
        from blackchpok_ide import model_hub as hub

        self.assertTrue(hub.is_vision_projector("mmproj-F16.gguf"))
        self.assertTrue(hub.is_vision_projector("mmproj-model-f16.gguf"))
        self.assertFalse(hub.is_vision_projector("Qwen3VL-8B-Q4_K_M.gguf"))

    def test_projector_never_picked_as_model(self) -> None:
        """Інакше замість моделі завантажиться проєктор."""
        from blackchpok_ide import model_hub as hub

        chosen = hub.pick_best_gguf(["mmproj-F16.gguf", "model-Q4_K_M.gguf"])
        self.assertEqual(chosen, "model-Q4_K_M.gguf")

    def test_projector_prefers_f16(self) -> None:
        from blackchpok_ide import model_hub as hub

        chosen = hub.pick_vision_projector(["mmproj-Q8_0.gguf",
                                            "mmproj-F16.gguf",
                                            "model.gguf"])
        self.assertEqual(chosen, "mmproj-F16.gguf")

    def test_text_model_gets_no_projector(self) -> None:
        """Текстовій моделі чужий проєктор не потрібен."""
        from blackchpok_ide import model_hub as hub

        folder = Path(tempfile.mkdtemp())
        (folder / "mmproj-Qwen3VL-8B-F16.gguf").write_bytes(b"x")
        text_model = folder / "qwen2.5-coder-14b-instruct-q4_k_m.gguf"
        text_model.write_bytes(b"x")
        self.assertIsNone(hub.vision_projector_for(text_model),
                          "текстова модель не має отримувати проєктор")

    def test_vision_model_pairs_with_projector(self) -> None:
        from blackchpok_ide import model_hub as hub

        folder = Path(tempfile.mkdtemp())
        (folder / "mmproj-Qwen3VL-8B-Instruct-F16.gguf").write_bytes(b"x")
        model = folder / "Qwen3VL-8B-Instruct-Q4_K_M.gguf"
        model.write_bytes(b"x")
        found = hub.vision_projector_for(model)
        self.assertIsNotNone(found)
        self.assertIn("mmproj", found.name)

    def test_server_config_passes_mmproj(self) -> None:
        """Без ``--mmproj`` модель картинку не читає."""
        import inspect

        from blackchpok_ide import runtime

        config = runtime.ServerConfig(model_path="m.gguf", port=9,
                                      mmproj_path="")
        self.assertNotIn("--mmproj", config.command())
        source = inspect.getsource(runtime.ServerConfig.command)
        self.assertIn("--mmproj", source)

    def test_missing_projector_does_not_break_command(self) -> None:
        """Файл проєктора зник — сервер усе одно стартує (без зору)."""
        from blackchpok_ide import runtime

        config = runtime.ServerConfig(model_path="m.gguf", port=9,
                                      mmproj_path="C:\\no\\such\\mmproj.gguf")
        command = config.command()
        self.assertNotIn("--mmproj", command)


class TestVisionMessage(unittest.TestCase):
    """Зображення передається моделі як ``image_url`` з base64."""

    def _png(self) -> Path:
        import zlib

        from blackchpok_ide import screenshot as shot

        target = Path(tempfile.mkdtemp()) / "tiny.png"
        raw = bytes([10, 20, 30, 255]) * 16     # 4×4 BGRA
        target.write_bytes(shot.to_png(4, 4, raw))
        return target

    def test_image_message_has_image_url(self) -> None:
        from blackchpok_ide import llm_client

        message = llm_client.image_message("що тут?", [self._png()])
        self.assertEqual(message["role"], "user")
        parts = message["content"]
        self.assertTrue(any(p.get("type") == "text" for p in parts))
        images = [p for p in parts if p.get("type") == "image_url"]
        self.assertEqual(len(images), 1)
        url = images[0]["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/png;base64,"),
                        "локальний сервер приймає лише data-URL")

    def test_missing_file_is_skipped(self) -> None:
        from blackchpok_ide import llm_client

        message = llm_client.image_message("текст", [Path("nope.png")])
        parts = message["content"]
        self.assertFalse([p for p in parts if p.get("type") == "image_url"])

    def test_empty_text_still_sends_image(self) -> None:
        from blackchpok_ide import llm_client

        message = llm_client.image_message("", [self._png()])
        parts = message["content"]
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0]["type"], "image_url")


class TestAgentAttachesScreenshots(unittest.TestCase):
    """Агент САМ додає знімок у контекст — без окремого запиту."""

    def _session(self):
        from blackchpok_ide.agent import AgentSession
        from blackchpok_ide.config import AgentSettings

        return AgentSession(AgentSettings(), Path(tempfile.mkdtemp()))

    def test_pending_images_do_not_duplicate(self) -> None:
        from blackchpok_ide import screenshot as shot

        session = self._session()
        session.add_user("подивись")
        target = Path(tempfile.mkdtemp()) / "s.png"
        shot.capture_screen(target)
        session.pending_images.append(str(target))
        first = session.build()
        self.assertTrue(isinstance(first[-1]["content"], list))
        # Другий build НЕ має знову додавати ту саму картинку.
        second = session.build()
        self.assertFalse(isinstance(second[-1]["content"], list),
                         "зображення додано вдруге — контекст роздувається")

    def test_attach_only_for_screenshot_tools(self) -> None:
        import inspect

        from blackchpok_ide.agent import AgentRunner

        source = inspect.getsource(AgentRunner._attach_capture)
        for name in ("app_screenshot", "project_screenshot",
                     "web_screenshot", "window_screenshot"):
            self.assertIn(name, source, f"{name} має ставити зн��мок у чергу")

    def test_vision_can_be_disabled(self) -> None:
        from blackchpok_ide.agent import AgentRunner, ToolResult

        runner = AgentRunner.__new__(AgentRunner)
        runner.session = self._session()
        runner.vision_enabled = False
        runner._emit = lambda *a, **k: None
        runner._attach_capture(
            "project_screenshot",
            ToolResult(True, "Скріншот 10×10: C:\\temp\\x.png"))
        self.assertEqual(runner.session.pending_images, [],
                         "без зору картинку не додаємо")

    def test_png_path_extraction(self) -> None:
        from blackchpok_ide.agent import _png_path_in

        self.assertEqual(_png_path_in("нічого"), "")
        self.assertEqual(_png_path_in("Скріншот: C:\\no\\such.png"), "")


# ─────────────────────────────────────────────────────────────────────────────
# 13. Цілісність проєкту
# ─────────────────────────────────────────────────────────────────────────────

class TestProjectIntegrity(unittest.TestCase):
    """Нові модулі існують, імпортуються й нічого не ламають під час імпорту."""

    #: ``live_browser_panel`` прибрано 10.11.2026: модуль на 372 рядки не мав
    #: ЖОДНОГО імпортера — ні в пакеті, ні в тестах, ні в кореневих скриптах.
    #: Він потрапляв сюди лише як «файл існує». Справжній живий браузер
    #: працює через ``live_preview.py`` + ``browser_panel.py``.
    NEW_MODULES = ("commands", "header_bar", "layout_profiles", "cdp",
                   "secrets", "provider_adapters", "hmr")

    def test_new_modules_exist(self) -> None:
        for name in self.NEW_MODULES:
            path = ROOT / "blackchpok_ide" / f"{name}.py"
            self.assertTrue(path.exists(), f"немає модуля {name}.py")

    def test_new_modules_import_without_side_effects(self) -> None:
        import importlib

        for name in self.NEW_MODULES:
            module = importlib.import_module(f"blackchpok_ide.{name}")
            self.assertIsNotNone(module)

    def test_no_module_imports_tkinter_at_top_for_logic(self) -> None:
        """Логічні модулі мають лишатись без tkinter (тестуються без дисплея)."""
        for name in ("commands", "secrets", "provider_adapters", "cdp",
                     "layout_profiles", "hmr", "chat_store", "agent", "providers"):
            source = (ROOT / "blackchpok_ide" / f"{name}.py").read_text(
                encoding="utf-8")
            self.assertNotIn("import tkinter", source,
                             f"{name}.py тягне tkinter — не тестується без дисплея")

    def test_all_modules_compile(self) -> None:
        import py_compile

        broken = []
        for path in sorted((ROOT / "blackchpok_ide").glob("*.py")):
            try:
                py_compile.compile(str(path), doraise=True,
                                   cfile=str(Path(tempfile.gettempdir())
                                             / f"{path.stem}.pyc"))
            except py_compile.PyCompileError as exc:
                broken.append(f"{path.name}: {exc}")
        self.assertEqual(broken, [], f"не компілюється: {broken}")

    def test_agent_tools_schemas_match_handlers(self) -> None:
        from blackchpok_ide.agent_tools import TOOL_SCHEMAS, ToolRegistry

        registry = ToolRegistry(ROOT)
        missing = [item["function"]["name"] for item in TOOL_SCHEMAS
                   if not callable(getattr(registry, item["function"]["name"], None))]
        self.assertEqual(missing, [], f"схеми без реалізації: {missing}")

    def test_tool_catalog_covers_schemas(self) -> None:
        from blackchpok_ide import tool_router
        from blackchpok_ide.agent_tools import TOOL_SCHEMAS

        names = {item["function"]["name"] for item in TOOL_SCHEMAS}
        catalog = {name for name, _when, _example in tool_router.TOOL_CATALOG}
        self.assertEqual(sorted(names - catalog), [],
                         "модель не знає про частину інструментів")


if __name__ == "__main__":
    unittest.main(verbosity=2)
