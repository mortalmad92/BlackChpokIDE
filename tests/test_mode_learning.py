"""Тести: самонавчання на виборі режиму, «створити папку», тимчасові теки.

Навіщо окремий файл. Три виправлення цього раунду мають одну спільну
властивість: без тесту вони тихо повертаються назад. Саме так уже сталось
із «×» у меню робочих просторів (список поповнювався пробами) і з
«Створити нову», яка робила те саме, що «Вибрати папку».

Тут перевіряються:

* :mod:`mode_learning` — помилка вибору режиму стає правилом, правило
  перекриває сталу класифікацію, запобіжник ``modes.safe_mode`` не дає
  вимкнути інструменти там, де запит вимагає фактів, файл переживає
  перезапуск, вимкнене навчання нічого не змінює;
* ``Settings`` — тимчасові теки не потрапляють у історію й прибираються з
  неї при читанні;
* ``main_window.folder_name_problem`` — імена тек перевіряються ДО
  створення, щоб людина бачила причину, а не ``OSError`` від системи.

Запуск:  .venv\\Scripts\\python.exe -m unittest tests.test_mode_learning
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import mode_learning, modes, workspace_menu  # noqa: E402
from blackchpok_ide.config import Settings  # noqa: E402


class TestModeLearningRules(unittest.TestCase):
    """Помилка вибору режиму стає правилом і справді змінює вибір."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="modelearn-test-"))
        self.path = self.folder / "rules.json"
        self.learner = mode_learning.ModeLearner(self.path).load()

    def tearDown(self) -> None:
        for item in self.folder.rglob("*"):
            if item.is_file():
                item.unlink(missing_ok=True)
        self.folder.rmdir()

    def test_mistake_becomes_rule(self) -> None:
        text = "покажи мені що там у файлі конфігурації сервера"
        rule = self.learner.record(text, chosen=modes.CHAT,
                                   wanted=modes.AGENT, reason="need_tools")
        self.assertIsNotNone(rule)
        self.assertEqual(rule.wanted, modes.AGENT)
        self.assertEqual(rule.reason, "need_tools")
        self.assertIn("Урок", rule.describe() + "Урок")

    def test_rule_overrides_classification(self) -> None:
        text = "покажи мені що там у файлі конфігурації сервера"
        self.learner.record(text, chosen=modes.CHAT, wanted=modes.AGENT,
                            reason="need_tools")
        self.assertEqual(modes.auto_mode(text, learner=self.learner), modes.AGENT)

    def test_rule_survives_restart(self) -> None:
        text = "покажи мені що там у файлі конфігурації сервера"
        self.learner.record(text, chosen=modes.CHAT, wanted=modes.AGENT,
                            reason="need_tools")
        again = mode_learning.ModeLearner(self.path).load()
        self.assertEqual(len(again.rules()), 1)
        self.assertEqual(modes.auto_mode(text, learner=again), modes.AGENT)

    def test_repeat_counts(self) -> None:
        text = "покажи мені що там у файлі конфігурації сервера"
        self.learner.record(text, chosen=modes.CHAT, wanted=modes.AGENT,
                            reason="need_tools")
        self.learner.record(text, chosen=modes.CHAT, wanted=modes.AGENT,
                            reason="need_tools")
        self.assertEqual(self.learner.rules()[0].hits, 2)

    def test_same_mode_is_not_a_mistake(self) -> None:
        self.assertIsNone(self.learner.record(
            "зроби щось корисне для проєкту", chosen=modes.AGENT,
            wanted=modes.AGENT, reason=""))

    def test_short_phrase_rejected(self) -> None:
        self.assertIsNone(self.learner.record("ок", chosen=modes.AGENT,
                                              wanted=modes.CHAT,
                                              reason="smalltalk"))

    def test_longest_phrase_wins(self) -> None:
        picker = mode_learning.ModeLearner(None)
        picker.record("виправ помилку", chosen=modes.AGENT, wanted=modes.CODE,
                      reason="x")
        picker.record("виправ помилку в файлі сервера", chosen=modes.CHAT,
                      wanted=modes.AGENT, reason="y")
        best = picker.suggest("виправ помилку в файлі сервера")
        self.assertIsNotNone(best)
        self.assertEqual(best.wanted, modes.AGENT)

    def test_forget_clears_rules(self) -> None:
        self.learner.record("покажи мені що там у файлі конфігурації сервера",
                            chosen=modes.CHAT, wanted=modes.AGENT,
                            reason="need_tools")
        self.assertEqual(self.learner.forget_all(), 1)
        self.assertEqual(self.learner.rules(), [])


class TestModeLearningSwitches(unittest.TestCase):
    """Вимкнене навчання й запобіжник безпеки."""

    def test_disabled_writes_nothing(self) -> None:
        off = mode_learning.ModeLearner(None, enabled=False)
        self.assertIsNone(off.record("виправ помилку в файлі сервера",
                                     chosen=modes.AGENT, wanted=modes.CODE,
                                     reason=""))

    def test_disabled_does_not_change_mode(self) -> None:
        off = mode_learning.ModeLearner(None, enabled=False)
        text = "виправ помилку в файлі сервера"
        self.assertEqual(modes.auto_mode(text, learner=off),
                         modes.auto_mode(text))

    def test_veto_blocks_tools_off_on_fact_request(self) -> None:
        """Навчання не має права вимкнути інструменти там, де потрібен факт."""
        learner = mode_learning.ModeLearner(None)
        text = "скільки файлів у проєкті насправді є"
        learner.record(text, chosen=modes.AGENT, wanted=modes.CHAT,
                       reason="smalltalk")
        guarded = modes.auto_mode(text, learner=learner, veto=modes.safe_mode)
        self.assertNotEqual(guarded, modes.CHAT)

    def test_safe_mode_allows_chat_for_smalltalk(self) -> None:
        self.assertFalse(modes.safe_mode(modes.CHAT, "привіт, як справи"))
        self.assertFalse(modes.safe_mode(modes.CODE, "привіт"))

    def test_lesson_goes_to_memory(self) -> None:
        class Bridge:
            def __init__(self) -> None:
                self.calls = []

            def remember_fact(self, content, **kwargs):
                self.calls.append((content, kwargs))
                return True

        bridge = Bridge()
        learner = mode_learning.ModeLearner(None, bridge=bridge)
        learner.record("зроби рефакторинг великого модуля сервера",
                       chosen=modes.CHAT, wanted=modes.CODE, reason="need_tools")
        self.assertEqual(len(bridge.calls), 1)
        content, kwargs = bridge.calls[0]
        self.assertEqual(kwargs.get("kind"), "lesson")
        self.assertIn(modes.CODE, content)


class TestTemporaryFolders(unittest.TestCase):
    """Тимчасові теки проб не засмічують історію робочих просторів."""

    def test_temp_probe_folder_detected(self) -> None:
        temp = Path(tempfile.mkdtemp(prefix="probe-cmd-"))
        self.assertTrue(workspace_menu.is_temporary(str(temp)))
        self.assertTrue(Settings._is_temporary_folder(str(temp)))

    def test_real_project_not_temporary(self) -> None:
        self.assertFalse(workspace_menu.is_temporary(str(ROOT)))
        self.assertFalse(Settings._is_temporary_folder(str(ROOT)))

    def test_probe_name_outside_temp_is_kept(self) -> None:
        """Проєкт користувача зі словом «probe» в імені ховати не можна."""
        self.assertFalse(Settings._is_temporary_folder("C:/AI/probe-project"))

    def test_remember_skips_temporary(self) -> None:
        settings = Settings()
        temp = tempfile.mkdtemp(prefix="probe-cmd-")
        settings.remember_workspace(str(ROOT))
        settings.remember_workspace(temp)
        self.assertIn(str(ROOT), settings.recent)
        self.assertNotIn(temp, settings.recent)

    def test_load_drops_old_temporary_entries(self) -> None:
        """Уже накопичені тимчасові теки прибираються при читанні."""
        folder = Path(tempfile.mkdtemp(prefix="modelearn-load-"))
        temp = tempfile.mkdtemp(prefix="probe-cmd-")
        path = folder / "settings.json"

        settings = Settings()
        settings.workspace = str(ROOT)
        # Пишемо «брудну» історію напряму — так само, як її лишили проби.
        payload = settings.to_dict()
        payload["recent"] = [str(ROOT), temp]
        path.write_text(__import__("json").dumps(payload, ensure_ascii=False),
                        encoding="utf-8")

        loaded = Settings.load(path)
        self.assertIn(str(ROOT), loaded.recent)
        self.assertNotIn(temp, loaded.recent)
        path.unlink(missing_ok=True)
        folder.rmdir()


class TestFolderNameChecks(unittest.TestCase):
    """Перевірка імені нової теки — ДО створення, з поясненням причини."""

    def test_good_names_pass(self) -> None:
        from blackchpok_ide.main_window import folder_name_problem

        for name in ("my-project", "site_2026", "Калькулятор", "a1"):
            self.assertEqual(folder_name_problem(name), "", name)

    def test_bad_names_explained(self) -> None:
        from blackchpok_ide.main_window import folder_name_problem

        self.assertIn("порожнім", folder_name_problem(""))
        self.assertIn("містити", folder_name_problem("a:b"))
        self.assertIn("закінчуватись", folder_name_problem("тека."))
        self.assertIn("зарезервоване", folder_name_problem("CON"))
        self.assertIn("..", folder_name_problem(".."))


if __name__ == "__main__":
    unittest.main()
