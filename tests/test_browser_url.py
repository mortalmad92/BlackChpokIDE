"""Тести вбудованого браузера: адреси, історія, спільний відкривач.

Головна вимога, яку тут зафіксовано: **жодна дія в IDE не має відкривати
системний браузер користувача**. Спершу саме через це клік «Встановити git»
викидав людину в Chrome на git-scm.com.

Запуск: python -m unittest tests.test_browser_url -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import browser_panel  # noqa: E402


def _calls_system_browser(text: str) -> bool:
    """Чи є в коді СПРАВЖНІЙ виклик ``webbrowser.open``.

    Просте ``"webbrowser.open" in text`` дає хибні спрацювання на докстрінгах
    і комментарях, тому розбираємо код через :mod:`ast` і дивимось на
    фактичні виклики атрибутів.
    """
    import ast

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "open":
            owner = func.value
            if isinstance(owner, ast.Name) and owner.id == "webbrowser":
                return True
            if isinstance(owner, ast.Attribute) and owner.attr == "webbrowser":
                return True
    return False


class TestNormaliseUrl(unittest.TestCase):
    """Перетворення введеного тексту на повну адресу."""

    def test_full_url_unchanged(self) -> None:
        self.assertEqual(browser_panel.normalise_url("https://git-scm.com/download/win"),
                         "https://git-scm.com/download/win")

    def test_adds_https(self) -> None:
        self.assertEqual(browser_panel.normalise_url("git-scm.com/download/win"),
                         "https://git-scm.com/download/win")

    def test_localhost_gets_http(self) -> None:
        """Локальні сервери майже ніколи не мають TLS."""
        self.assertEqual(browser_panel.normalise_url("localhost:8080"),
                         "http://localhost:8080")

    def test_loopback_gets_http(self) -> None:
        self.assertEqual(browser_panel.normalise_url("127.0.0.1:8000/app"),
                         "http://127.0.0.1:8000/app")

    def test_strips_spaces(self) -> None:
        self.assertEqual(browser_panel.normalise_url("  example.com  "),
                         "https://example.com")

    def test_empty_stays_empty(self) -> None:
        self.assertEqual(browser_panel.normalise_url(""), "")
        self.assertEqual(browser_panel.normalise_url("   "), "")

    def test_foreign_scheme_untouched(self) -> None:
        """``mailto:`` не можна переписувати на https — вийшла б нісенітниця."""
        self.assertEqual(browser_panel.normalise_url("mailto:a@b.c"), "mailto:a@b.c")

    def test_file_url_unchanged(self) -> None:
        self.assertEqual(browser_panel.normalise_url("file:///C:/a.html"),
                         "file:///C:/a.html")


class TestSchemeHelpers(unittest.TestCase):
    """Схема й «чи можна це показати»."""

    def test_scheme_of(self) -> None:
        self.assertEqual(browser_panel.scheme_of("https://x.com"), "https")
        self.assertEqual(browser_panel.scheme_of("http://127.0.0.1"), "http")
        self.assertEqual(browser_panel.scheme_of("file:///C:/a"), "file")
        self.assertEqual(browser_panel.scheme_of("mailto:a@b"), "mailto")
        self.assertEqual(browser_panel.scheme_of("no-scheme"), "")

    def test_showable(self) -> None:
        self.assertTrue(browser_panel.is_showable("https://x.com"))
        self.assertTrue(browser_panel.is_showable("http://localhost:1"))
        self.assertTrue(browser_panel.is_showable("file:///C:/a.html"))
        self.assertFalse(browser_panel.is_showable("mailto:a@b.c"))
        self.assertFalse(browser_panel.is_showable("vscode://open"))

    def test_local_detection(self) -> None:
        self.assertTrue(browser_panel.is_local_url("http://127.0.0.1:8000/"))
        self.assertTrue(browser_panel.is_local_url("http://localhost:3000/x"))
        self.assertTrue(browser_panel.is_local_url("file:///C:/a.html"))
        self.assertFalse(browser_panel.is_local_url("https://git-scm.com"))
        self.assertFalse(browser_panel.is_local_url("https://example.com/?h=localhost"))

    def test_file_url_for_existing_file(self) -> None:
        url = browser_panel.file_url(ROOT / "README_UK.md")
        self.assertTrue(url.startswith("file:///"))
        self.assertIn("README_UK.md", url)

    def test_file_url_for_missing_path(self) -> None:
        url = browser_panel.file_url(ROOT / "немає-такого-файлу.txt")
        # as_uri не перевіряє існування, тож адреса будується — це нормально.
        self.assertTrue(url == "" or url.startswith("file:///"))


class TestSharedOpener(unittest.TestCase):
    """Спільний відкривач: саме він не дає відкрити системний браузер."""

    def tearDown(self) -> None:
        browser_panel.set_url_opener(None)

    def test_no_opener_returns_false(self) -> None:
        browser_panel.set_url_opener(None)
        self.assertFalse(browser_panel.open_url("https://example.com"))

    def test_opener_receives_normalised_url(self) -> None:
        seen: list[str] = []
        browser_panel.set_url_opener(lambda url: seen.append(url) or True)
        browser_panel.open_url("git-scm.com/download/win")
        self.assertEqual(seen, ["https://git-scm.com/download/win"])

    def test_broken_opener_falls_through(self) -> None:
        def boom(_url: str) -> bool:
            raise RuntimeError("навмисно")

        browser_panel.set_url_opener(boom)
        self.assertFalse(browser_panel.open_url("https://example.com"))

    def test_empty_url_is_ignored(self) -> None:
        seen: list[str] = []
        browser_panel.set_url_opener(lambda url: seen.append(url) or True)
        self.assertFalse(browser_panel.open_url("   "))
        self.assertEqual(seen, [])

    def test_fallback_uses_system_browser_only_when_asked(self) -> None:
        """``fallback=True`` — єдиний шлях до системного браузера, і він
        використовується лише з консолі, не з інтерфейсу."""
        browser_panel.set_url_opener(None)
        with mock.patch("webbrowser.open", return_value=True) as opened:
            self.assertTrue(browser_panel.open_url("https://example.com", fallback=True))
        opened.assert_called_once()

    def test_no_fallback_by_default(self) -> None:
        browser_panel.set_url_opener(None)
        with mock.patch("webbrowser.open", return_value=True) as opened:
            browser_panel.open_url("https://example.com")
        opened.assert_not_called()


class TestNoSystemBrowserInSources(unittest.TestCase):
    """Статична перевірка: інтерфейс не має кликати системний браузер.

    Це найважливіший тест цього файлу: він ловить саме ту помилку, через
    яку «Встановити git» відкривав Chrome поверх IDE.
    """

    def test_ui_modules_do_not_call_webbrowser(self) -> None:
        ui_modules = (
            "changes_panel.py",
            "settings_dialog.py",
            "first_run.py",
            "model_hub_panel.py",
            "preview_panel.py",
            "live_preview.py",
            "tools_panel.py",
            "skills_panel.py",
            "queue_panel.py",
            "rag_panel.py",
        )
        offenders = []
        for name in ui_modules:
            path = ROOT / "blackchpok_ide" / name
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            if _calls_system_browser(text):
                offenders.append(name)
        self.assertEqual(offenders, [],
                         f"ці модулі відкривають системний браузер: {offenders}")

    def test_detector_ignores_docstring_mentions(self) -> None:
        """Згадка в докстрінгу — не виклик: раніше тест ловив саму згадку."""
        self.assertFalse(_calls_system_browser('"""Раніше тут був webbrowser.open."""'))
        self.assertFalse(_calls_system_browser("import webbrowser\n# webbrowser.open(x)"))
        self.assertTrue(_calls_system_browser("import webbrowser\nwebbrowser.open(x)"))

    def test_env_setup_opens_pages_via_browser_panel(self) -> None:
        text = (ROOT / "blackchpok_ide" / "env_setup.py").read_text(encoding="utf-8")
        self.assertIn("browser_panel.open_url", text)
        self.assertNotIn("webbrowser.open", text)

    def test_browser_panel_keeps_explicit_external_button(self) -> None:
        """Кнопка «↗» лишається — але це усвідомлена дія користувача."""
        text = (ROOT / "blackchpok_ide" / "browser_panel.py").read_text(encoding="utf-8")
        self.assertIn("def open_external", text)

    def test_whole_package_has_no_implicit_system_browser(self) -> None:
        """Жоден модуль пакета не кличе системний браузер напряму.

        Дозволено рівно два усвідомлені місця в ``browser_panel``: явна
        кнопка «↗» і запасний шлях ``open_url(fallback=True)``. Решта
        викликів — це та сама проблема, через яку клік по підпису адреси
        у панелі «Сайт» викидав користувача в Chrome.
        """
        offenders = []
        for path in sorted((ROOT / "blackchpok_ide").glob("*.py")):
            if path.name == "browser_panel.py":
                continue
            if _calls_system_browser(path.read_text(encoding="utf-8")):
                offenders.append(path.name)
        self.assertEqual(offenders, [],
                         f"ці модулі відкривають системний браузер: {offenders}")

    def test_address_click_copies_instead_of_opening_browser(self) -> None:
        """Клік по підпису адреси копіює її, а не відкриває системний браузер.

        Регресія: у ``preview_panel`` підпис був прив'язаний до
        ``view.open_external()`` — випадковий клік по адресі викидав з IDE.
        """
        text = (ROOT / "blackchpok_ide" / "preview_panel.py").read_text(encoding="utf-8")
        self.assertNotIn("view.open_external()", text,
                         "підпис адреси не має відкривати системний браузер")
        self.assertIn("_copy_address", text)

    def test_live_preview_external_is_explicit_button_only(self) -> None:
        """У Live Preview системний браузер — лише через кнопку «↗»."""
        text = (ROOT / "blackchpok_ide" / "live_preview.py").read_text(encoding="utf-8")
        self.assertIn("open_external", text)
        # Прив'язка має бути на IconButton, а не на підпис чи клік по всьому.
        self.assertIn('IconButton(actions, "↗", self._open_external', text)


class TestAddressBarLogic(unittest.TestCase):
    """Логіка переходу за адресою (без реального вікна браузера)."""

    def test_local_file_path_is_converted(self) -> None:
        """Локальний файл на диску стає file://-адресою."""
        target = ROOT / "README_UK.md"
        url = browser_panel.file_url(target)
        self.assertTrue(browser_panel.is_showable(url))
        self.assertTrue(browser_panel.is_local_url(url))

    def test_plain_domain_becomes_showable(self) -> None:
        url = browser_panel.normalise_url("example.com")
        self.assertTrue(browser_panel.is_showable(url))


if __name__ == "__main__":
    unittest.main(verbosity=2)
