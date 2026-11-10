"""«Золотий» тест проєкту: усе інтерактивне — робоче.

Розділ 11 плану. Перевіряє одним прогоном, що жоден елемент інтерфейсу не
«мертвий»: меню ведуть до існуючих методів, панелі відкриваються,
інструменти викликаються, слэш-команди мають обробники, гарячі клавіші
вказують на реальні дії.

Це не заміна живим прогонам (``tests/live_every_button.py``), а швидка
страховка в CI: якщо хтось прибрав метод, до якого прив'язана кнопка —
тест упаде першим.

Запуск: python -m unittest tests.test_everything_works -v
"""

from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PKG = ROOT / "blackchpok_ide"


class TestMenuMethodsExist(unittest.TestCase):
    """Кожна дія меню веде до наявного методу вікна."""

    @classmethod
    def setUpClass(cls) -> None:
        from blackchpok_ide.main_window import BlackChpokIDE

        cls.window = BlackChpokIDE
        cls.available = set(dir(BlackChpokIDE))
        cls.source = (PKG / "main_window.py").read_text(encoding="utf-8")

    def test_no_missing_self_methods(self) -> None:
        """Усі ``self.метод(...)`` мають бути визначені в класі."""
        missing = set()
        for match in re.finditer(r"self\.([a-z_][a-z0-9_]{2,})\s*\(", self.source):
            name = match.group(1)
            if name not in self.available:
                missing.add(name)
        self.assertEqual(missing, set(), f"відсутні методи: {sorted(missing)}")

    def test_menu_commands_reference_real_methods(self) -> None:
        """Кожен ``self.X`` у побудові меню існує як метод або атрибут."""
        start = self.source.index("def _build_menu")
        end = self.source.index("def _build_layout")
        menu_source = self.source[start:end]
        # Атрибути, створені під час побудови вікна (не методи класу).
        instance_attrs = {"tabs", "chat", "header", "terminal", "context",
                          "file_tree", "outline", "settings", "theme", "layout",
                          "session", "registry", "agent", "chat_store"}
        missing = []
        for match in re.finditer(r"self\.([a-z_][a-z0-9_]{2,})\b", menu_source):
            name = match.group(1)
            if name in instance_attrs or name.startswith(("_theme", "_nav")):
                continue
            if name not in self.available:
                missing.append(name)
        self.assertEqual(missing, [], f"меню посилається на неіснуючі: {sorted(set(missing))}")

    def test_menu_has_expected_sections(self) -> None:
        for label in ("Файл", "Правка", "Вигляд", "Агент", "Git", "Довідка"):
            self.assertIn(f'label="{label}"', self.source, f"немає меню «{label}»")


class TestKeyboardShortcuts(unittest.TestCase):
    """Гарячі клавіші вказують на робочі дії."""

    def test_every_shortcut_handler_exists(self) -> None:
        from blackchpok_ide.main_window import BlackChpokIDE

        available = set(dir(BlackChpokIDE))
        source = (PKG / "main_window.py").read_text(encoding="utf-8")
        start = source.index("def _wire_shortcuts")
        end = source.index("def _wrap(", start)
        block = source[start:end]
        missing = []
        for match in re.finditer(r"self\.([a-z_][a-z0-9_]{2,})", block):
            name = match.group(1)
            if name not in available:
                missing.append(name)
        self.assertEqual(missing, [], f"клавіші ведуть на неіснуючі: {sorted(set(missing))}")

    def test_shortcuts_are_registered(self) -> None:
        source = (PKG / "main_window.py").read_text(encoding="utf-8")
        start = source.index("def _wire_shortcuts")
        block = source[start:start + 4000]
        count = len(re.findall(r'"<Control', block))
        self.assertGreaterEqual(count, 15, f"замало гарячих клавіш: {count}")


class TestPanelsOpen(unittest.TestCase):
    """Усі панелі бічної колонки існують у стеку."""

    @classmethod
    def setUpClass(cls) -> None:
        import tkinter as tk

        from blackchpok_ide import theme
        from blackchpok_ide.config import Settings
        from blackchpok_ide.main_window import BlackChpokIDE

        try:
            cls.app = BlackChpokIDE.__new__(BlackChpokIDE)
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError as exc:  # pragma: no cover - без дисплея
            raise unittest.SkipTest(f"tkinter недоступний: {exc}") from exc
        cls.fonts = theme.Theme(cls.root)
        cls.fonts.apply()
        cls.settings = Settings()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def test_expected_panel_keys_present_in_source(self) -> None:
        source = (PKG / "main_window.py").read_text(encoding="utf-8")
        start = source.index("self._side_widgets = {")
        end = source.index("}", start)
        block = source[start:end]
        for key in ("chats", "cases", "rag", "tools", "explorer", "outline",
                    "changes", "skills", "queue", "mcp"):
            self.assertIn(f'"{key}"', block, f"панель «{key}» не зареєстрована")

    def test_panel_sections_map_is_complete(self) -> None:
        from blackchpok_ide import main_window

        for key in main_window.SECTION_PANELS.values():
            self.assertIn(key, main_window.PANEL_TITLES,
                          f"панель «{key}» без заголовка")
            self.assertIn(key, main_window.PANEL_SECTIONS,
                          f"панель «{key}» без розділу")

    def test_every_panel_title_has_section(self) -> None:
        from blackchpok_ide import main_window

        for key in main_window.PANEL_TITLES:
            self.assertIn(key, main_window.PANEL_SECTIONS,
                          f"«{key}» має заголовок, але не має розділу")


class TestToolsComplete(unittest.TestCase):
    """Інструменти агента: схеми ↔ реалізація ↔ підписи."""

    def test_every_schema_has_method(self) -> None:
        from blackchpok_ide.agent_tools import TOOL_SCHEMAS, ToolRegistry

        registry = ToolRegistry(ROOT)
        available = {name for name in dir(registry) if not name.startswith("_")}
        missing = [item["function"]["name"] for item in TOOL_SCHEMAS
                   if item["function"]["name"] not in available]
        self.assertEqual(missing, [], f"схеми без реалізації: {missing}")

    def test_every_tool_has_human_label(self) -> None:
        from blackchpok_ide.agent_tools import TOOL_SCHEMAS
        from blackchpok_ide.work_log import TOOL_VIEWS

        missing = [item["function"]["name"] for item in TOOL_SCHEMAS
                   if item["function"]["name"] not in TOOL_VIEWS]
        self.assertEqual(missing, [], f"інструменти без підпису в журналі: {missing}")

    def test_tool_labels_are_ukrainian(self) -> None:
        from blackchpok_ide.work_log import TOOL_VIEWS

        latin = []
        for name, (_icon, label, _arg) in TOOL_VIEWS.items():
            # Дозволяємо латиницю лише в назвах на кшталт «Стан git».
            if label and not re.search(r"[\u0400-\u04FF]", label):
                latin.append((name, label))
        self.assertEqual(latin, [], f"підписи не українською: {latin}")

    def test_schemas_have_descriptions(self) -> None:
        from blackchpok_ide.agent_tools import TOOL_SCHEMAS

        for item in TOOL_SCHEMAS:
            func = item["function"]
            self.assertTrue(func.get("description"),
                            f"{func['name']}: немає опису")

    def test_schemas_declare_parameters_block(self) -> None:
        from blackchpok_ide.agent_tools import TOOL_SCHEMAS

        for item in TOOL_SCHEMAS:
            func = item["function"]
            params = func.get("parameters")
            # Блок параметрів має бути завжди; інструменти без аргументів
            # (git_status, app_screenshot) мають порожні властивості.
            self.assertIsInstance(params, dict, f"{func['name']}: немає parameters")
            self.assertEqual(params.get("type"), "object",
                             f"{func['name']}: parameters не object")


class TestSlashCommandsComplete(unittest.TestCase):
    """Кожна слэш-команда має обробник у чаті."""

    def test_every_command_handled(self) -> None:
        from blackchpok_ide import slash_commands

        source = (PKG / "chat_panel.py").read_text(encoding="utf-8")
        start = source.index("def _run_slash_command")
        end = source.index("def start_plan_mode", start)
        block = source[start:end]
        missing = [command.name for command in slash_commands.COMMANDS
                   if f'"{command.name}"' not in block]
        self.assertEqual(missing, [], f"команди без обробника: {missing}")

    def test_handler_covers_plan(self) -> None:
        source = (PKG / "chat_panel.py").read_text(encoding="utf-8")
        self.assertIn('name == "план"', source,
                      "команда /план має викликати start_plan_mode")

    def test_command_count_matches_test_expectations(self) -> None:
        from blackchpok_ide import slash_commands

        self.assertGreaterEqual(len(slash_commands.COMMANDS), 10)


class TestNoSilentCallbacks(unittest.TestCase):
    """Ключові колбеки не ковтають помилки безслідно."""

    def test_chat_panel_uses_safe_module(self) -> None:
        source = (PKG / "chat_panel.py").read_text(encoding="utf-8")
        self.assertIn("from . import (", source)
        self.assertIn("safe,", source)
        for needed in ("safe.call(self.on_message", "safe.call_quiet(self.on_event",
                       "safe.call_quiet(callback, text"):
            self.assertIn(needed, source, f"немає {needed}")

    def test_safe_module_available(self) -> None:
        from blackchpok_ide import safe

        self.assertTrue(callable(safe.call))
        self.assertTrue(callable(safe.call_quiet))

    def test_agent_has_no_bare_silent_handlers(self) -> None:
        source = (PKG / "agent.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if node.type is not None and not (
                    isinstance(node.type, ast.Name) and node.type.id == "Exception"):
                continue
            body = [item for item in node.body if not isinstance(item, ast.Pass)]
            if not body:
                offenders.append(node.lineno)
        self.assertEqual(offenders, [], f"agent.py: німі обробники {offenders}")


class TestModalWindowsGuarded(unittest.TestCase):
    """Модальні вікна й попапи керуються спільними помічниками."""

    def test_widgets_exports_helpers(self) -> None:
        from blackchpok_ide import widgets

        for name in ("place_window", "clamp_to_screen", "open_only_modal",
                     "register_popover", "close_popovers", "active_modal"):
            self.assertTrue(hasattr(widgets, name), f"немає {name}")

    def test_dialogs_use_helpers(self) -> None:
        for name in ("settings_dialog.py", "palette.py", "first_run.py"):
            source = (PKG / name).read_text(encoding="utf-8")
            self.assertIn("place_window", source, f"{name} не позиціює вікно")
            self.assertNotIn("self.grab_set()", source,
                             f"{name} захоплює введення напряму")

    def test_popovers_registered(self) -> None:
        for name in ("model_selector.py", "model_menu.py", "modes_menu.py",
                     "command_menu.py", "context_popover.py"):
            source = (PKG / name).read_text(encoding="utf-8")
            self.assertIn("register_popover", source, f"{name} не реєструє попап")
            self.assertIn("clamp_to_screen", source, f"{name} не обмежує позицію")


class TestCoreModulesImport(unittest.TestCase):
    """Усі модулі пакета імпортуються без помилок."""

    def test_all_modules_import(self) -> None:
        import importlib

        failures = []
        for path in sorted(PKG.glob("*.py")):
            name = path.stem
            if name == "__init__":
                continue
            try:
                importlib.import_module(f"blackchpok_ide.{name}")
            except Exception as exc:  # noqa: BLE001
                failures.append((name, f"{type(exc).__name__}: {exc}"))
        self.assertEqual(failures, [], f"не імпортуються: {failures}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
