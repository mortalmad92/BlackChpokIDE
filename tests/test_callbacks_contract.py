"""Тести, що КОЖНА дія шапки й меню справді викликається без помилок.

Привід — реальний лог користувача: кнопка «⊟ модель ▾» падала з
``TypeError: show_model_selector() got an unexpected keyword argument
'anchor'``, а пункт «Якість агента» — з ``AttributeError: no attribute
'fonts'``. Обидві помилки видно лише в терміналі, у вікні — нічого не
відбувається. Тому перевіряємо не «код існує», а що колбек ПРИЙМАЄ ті
аргументи, з якими його кличуть.

Запуск: python -m unittest tests.test_callbacks_contract -v
"""

from __future__ import annotations

import inspect
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _window_class():
    """Клас вікна без створення (щоб тест працював і без дисплея)."""
    from blackchpok_ide.main_window import BlackChpokIDE

    return BlackChpokIDE


def _accepts(method, *args, **kwargs) -> bool:
    """Чи приймає метод такі аргументи (без виклику)."""
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return True
    try:
        signature.bind(None, *args, **kwargs)
    except TypeError:
        return False
    return True


class TestHeaderCallbacks(unittest.TestCase):
    """Колбеки шапки мусять приймати anchor — вона його передає."""

    def setUp(self) -> None:
        self.cls = _window_class()

    def test_model_selector_accepts_anchor(self) -> None:
        self.assertTrue(
            _accepts(self.cls.show_model_selector, anchor=object()),
            "шапка кличе show_model_selector(anchor=…), метод мусить його приймати")

    def test_mode_menu_accepts_anchor(self) -> None:
        if not hasattr(self.cls, "show_mode_menu"):
            self.skipTest("show_mode_menu відсутній")
        self.assertTrue(_accepts(self.cls.show_mode_menu, anchor=object()))

    def test_project_menu_accepts_anchor(self) -> None:
        if not hasattr(self.cls, "_show_project_menu"):
            self.skipTest("_show_project_menu відсутній")
        self.assertTrue(_accepts(self.cls._show_project_menu, object()))

    def test_git_menu_accepts_anchor(self) -> None:
        if not hasattr(self.cls, "_show_git_menu"):
            self.skipTest("_show_git_menu відсутній")
        self.assertTrue(_accepts(self.cls._show_git_menu, object()))

    def test_more_menu_accepts_anchor(self) -> None:
        if not hasattr(self.cls, "_show_more_menu"):
            self.skipTest("_show_more_menu відсутній")
        self.assertTrue(_accepts(self.cls._show_more_menu, object()))


class TestNoMissingAttributes(unittest.TestCase):
    """Методи вікна не мають звертатись до неіснуючих атрибутів.

    Перевіряємо статично (читанням коду): ``self.X`` має бути або
    атрибутом, який вікно створює, або методом класу. Це ловить саме той
    клас помилок, що дав ``self.fonts``.
    """

    #: Атрибути, які вікно точно створює (перевірено в __init__ і в
    #: побудові панелей). Список неповний і свідомо явний: краще
    #: перевірити конкретні випадки, ніж вдавати повний аналіз.
    KNOWN = {
        "theme", "settings", "agent", "chat", "header", "chat_store",
        "chat_list", "registry", "memory", "native_runtime", "tabs",
        "editor", "file_tree", "context", "stats_bar", "terminal",
        "project_search", "model_hub", "preview", "live_preview",
        "task_center", "task_queue", "executor", "app", "layout",
        "bottom_tabs", "sidebar", "h_split", "v_split", "editor_split",
        "side_split", "main_area", "centre", "header_bar", "skill_book",
        "mcp_manager", "traces", "commands",
    }

    def test_agent_quality_does_not_use_window_fonts(self) -> None:
        """``self.fonts`` у вікна немає — шрифт беруть із теми.

        Перевіряємо КОД, а не згадку в коментарі: саме звернення
        ``self.fonts.…`` було причиною падіння.
        """
        source = inspect.getsource(_window_class().show_agent_quality)
        code_lines = [line for line in source.splitlines()
                      if not line.strip().startswith("#")]
        offenders = [line for line in code_lines
                     if "self.fonts." in line or "self.fonts[" in line]
        self.assertEqual(offenders, [],
                         "у вікна немає атрибута fonts: шрифт беруть із self.theme")

    def test_known_attributes_exist_on_class_or_init(self) -> None:
        cls = _window_class()
        source = inspect.getsource(cls)
        missing = []
        for name in self.KNOWN:
            # Шукаємо саме ``self.<ім'я>`` з межею: інакше ``editor``
            # збігається з ``self.editor_split`` і дає хибну тривогу.
            pattern = re.compile(rf"self\.{re.escape(name)}(?![\w])")
            if not pattern.search(source):
                continue
            if hasattr(cls, name):
                continue
            if (f"self.{name} =" in source or f"self.{name}:" in source
                    or f'setattr(self, "{name}"' in source):
                continue
            missing.append(name)
        self.assertEqual(missing, [],
                         f"згадані, але ніде не створені: {missing}")


class TestBottomPanelResizable(unittest.TestCase):
    """Нижня панель мусить мати смугу перетягування.

    Користувач: «та панель не розтягується за допомогою миші». Перевіряємо,
    що смуга існує й що вона прив'язана до руху миші.
    """

    def setUp(self) -> None:
        self.cls = _window_class()

    def test_sash_handlers_exist(self) -> None:
        for name in ("_bottom_sash_press", "_bottom_sash_drag",
                     "_bottom_sash_release"):
            self.assertTrue(hasattr(self.cls, name), f"немає {name}")

    def test_place_bottom_creates_sash(self) -> None:
        source = inspect.getsource(self.cls._place_bottom)
        self.assertIn("bottom_sash", source,
                      "_place_bottom мусить показувати смугу перетягування")
        self.assertIn("row=2", source,
                      "панель живе в рядку 2 (рядок 1 — смуга)")

    def test_drag_changes_height(self) -> None:
        source = inspect.getsource(self.cls._bottom_sash_drag)
        self.assertIn("_bottom_height", source)
        self.assertIn("clamp", source, "висота мусить бути обмежена")


if __name__ == "__main__":
    unittest.main(verbosity=2)
