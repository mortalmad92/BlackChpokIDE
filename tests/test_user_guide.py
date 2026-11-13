"""Довідник користувача: генерується з реєстру, а не пишеться руками.

Причина появи цих тестів. Гарячі клавіші в ``show_shortcuts`` були
рукописним текстом і вже розійшлися з кодом: у переліку стояв
``Ctrl+D — дублювати рядок``, якого в реєстрі немає, натомість бракувало
команд, доданих пізніше. Користувач бачив клавішу, що нічого не робить, і
не бачив робочих.

Тепер довідник складається з тих самих ``Command``, які реально
зареєстровані. Ці тести фіксують саме цю властивість: довідка не може
«відстати» від коду, бо бере дані з нього.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import command_registry, commands, slash_commands, tool_router  # noqa: E402


class _FakeWindow:
    """Вікно-заглушка: реєстрація потребує лише наявності методів."""

    class _Tabs:
        @staticmethod
        def current():
            return None

        @staticmethod
        def save_all():
            return None

    tabs = _Tabs()

    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


def _register() -> None:
    commands.reset()
    command_registry.register_all(_FakeWindow())


class TestReferenceMatchesRegistry(TestCase):
    """Довідник мусить описувати РІВНО те, що є в реєстрі."""

    def setUp(self) -> None:
        _register()
        self.text = commands.reference_text()

    def test_every_registered_command_is_listed(self) -> None:
        """Жодна зареєстрована команда не може «зникнути» з довідника."""
        missing = [command.label for command in commands.all_commands()
                   if command.label not in self.text]
        self.assertEqual(missing, [], f"у довіднику немає команд: {missing}")

    def test_every_shortcut_in_guide_exists_in_registry(self) -> None:
        """Кожна клавіша з довідника справді зареєстрована.

        Саме цього не було: ``Ctrl+D`` показувався, але команди не існувало.
        """
        registered = {command.shortcut for command in commands.all_commands()
                      if command.shortcut}
        shown = {line.split()[0] for line in self.text.splitlines()
                 if line.strip().startswith(("Ctrl", "Alt", "F1", "F5", "Shift"))}
        unknown = {item for item in shown
                   if item not in registered and "/" not in item}
        self.assertEqual(unknown, set(),
                         f"довідник обіцяє неіснуючі клавіші: {sorted(unknown)}")

    def test_slash_commands_section_present(self) -> None:
        self.assertIn("Слеш-команди", self.text)
        for command in slash_commands.COMMANDS[:5]:
            self.assertIn(f"/{command.name}", self.text,
                          f"немає слеш-команди /{command.name}")

    def test_agent_phrases_section_present(self) -> None:
        """Користувач має бачити, ЩО можна просто написати словами."""
        self.assertIn("просто написати словами", self.text)
        example = tool_router.TOOL_CATALOG[0][2]
        self.assertIn(example, self.text,
                      f"немає прикладу фрази «{example}»")

    def test_guide_is_readable_length(self) -> None:
        """Довідка не порожня й не безмежна (її читатиме людина)."""
        lines = self.text.splitlines()
        self.assertGreater(len(lines), 40, "довідник занадто короткий")
        self.assertLess(len(lines), 600, "довідник занадто довгий")


class TestReferenceLinesForPalette(TestCase):
    """Рядки для палітри — той самий реєстр, згрупований для пошуку."""

    def setUp(self) -> None:
        _register()

    def test_lines_cover_all_commands(self) -> None:
        rows = commands.reference_lines()
        self.assertEqual(len(rows), len(commands.all_commands()))

    def test_lines_have_category_prefix(self) -> None:
        for label, _hint, _action in commands.reference_lines():
            self.assertIn("·", label, f"рядок без категорії: {label}")


class TestGuideCommandRegistered(TestCase):
    """Команда довідника мусить існувати й мати F1 у реєстрі."""

    def setUp(self) -> None:
        _register()

    def test_guide_command_exists(self) -> None:
        command = commands.get("help.guide")
        self.assertIsNotNone(command, "команди «Довідник користувача» немає")
        self.assertEqual(command.shortcut, "F1")

    def test_guide_command_enabled_by_default(self) -> None:
        self.assertTrue(commands.get("help.guide").is_enabled())


if __name__ == "__main__":
    main()
