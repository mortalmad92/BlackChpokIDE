"""Повна автономія: без ліміту кроків, без підтверджень, з автозбереженням.

Фіксують вимоги користувача (21.11.2026):

  «Прибери мені цей ліміт кроків сраний!»
  «Прибери всі підтвердження і зроби режим повної автономії без людини»
  «прибери всі обмеження щоб агент міг працювати хоч 24/7 без вихідних»
  «Всі файли мають автоматично зберігатися»
  «night_shift.py нічний режим має працювати на власному рушії»

Що саме було зламано:

1. ``AgentSettings.max_steps = 8`` (потім 60) — довге завдання обривалось
   на півдорозі з «Досягнуто ліміт кроків». Нуль у налаштуваннях тихо
   ставав вісьмома кроками через ``max(1, ... or 8)``.
2. ``_step_ceiling`` обрізав навіть «безлімітний» режим: 300 кроків.
3. Поле «Максимум кроків агента» в налаштуваннях повертало стелю назад.
4. ``confirm_commands`` показував діалог посеред роботи й чекав до 10 хв.
5. Нічна зміна кликала LM Studio на ``127.0.0.1:1235`` замість власного
   рушія, і обрізала будь-яке прохання вісьмома годинами.

Запуск: python -m unittest tests.test_autonomy_unlimited -v
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BLACKCHPOK_NO_SAVE", "1")

from blackchpok_ide import agent as agent_module  # noqa: E402
from blackchpok_ide import modes  # noqa: E402
from blackchpok_ide.agent import AgentRunner  # noqa: E402
from blackchpok_ide.agent_tools import ToolRegistry  # noqa: E402
from blackchpok_ide.config import AgentSettings, LLMSettings, Settings  # noqa: E402


class TestNoStepLimit(unittest.TestCase):
    """Кроки не обмежені: робота визначає, коли спинитись."""

    def setUp(self) -> None:
        self.temp = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        self.settings = AgentSettings(max_steps=0)

    def _runner(self, **kwargs) -> AgentRunner:
        return AgentRunner(ToolRegistry(self.temp), LLMSettings(),
                           AgentSettings(**kwargs), self.temp)

    def test_default_setting_has_no_limit(self) -> None:
        """Типове налаштування — «без ліміту», а не 8 чи 60."""
        self.assertEqual(AgentSettings().max_steps, 0,
                         "типовий ліміт кроків повернувся")

    def test_zero_means_unlimited_not_eight(self) -> None:
        """``0`` не підміняється на 8 — саме це обрізало роботу."""
        runner = self._runner(max_steps=0)
        self.assertEqual(runner.max_steps, agent_module.UNLIMITED_STEPS)
        self.assertGreater(runner.step_budget, 10_000,
                           "бюджет усе ще обрізаний стелею")

    def test_no_ceiling_for_autonomy(self) -> None:
        """Рівень свободи дій більше не впирається в аварійну стелю."""
        runner = self._runner(max_steps=0)
        runner.set_autonomy("explorer")
        self.assertGreater(runner.step_budget, agent_module.STEP_BUDGET_CEILING,
                           "стеля кроків повернулась")

    def test_explicit_limit_still_works(self) -> None:
        """Хто свідомо поставив стелю — стеля діє."""
        runner = self._runner(max_steps=40)
        self.assertEqual(runner.max_steps, 40)
        self.assertTrue(runner.steps_are_limited())

    def test_stop_message_is_honest(self) -> None:
        """Без ліміту не можна казати «досягнуто ліміт кроків»."""
        runner = self._runner(max_steps=0)
        self.assertFalse(runner.steps_are_limited())
        limited = self._runner(max_steps=5)
        self.assertTrue(limited.steps_are_limited())

    def test_modes_do_not_impose_limits(self) -> None:
        """Режим описує дозволи й підказку, а не бюджет роботи."""
        self.assertEqual(modes.DEFAULT_MAX_STEPS, 0)
        for mode in modes.MODES:
            with self.subTest(mode=mode.key):
                self.assertEqual(mode.max_steps, 0,
                                 f"режим «{mode.label}» нав'язує ліміт кроків")


class TestNoConfirmations(unittest.TestCase):
    """Повна автономія: жодних діалогів посеред роботи."""

    def test_commands_are_not_confirmed(self) -> None:
        self.assertFalse(AgentSettings().confirm_commands,
                         "агент знову питає дозвіл на команди")

    def test_old_settings_still_lose_the_limit(self) -> None:
        """Старий settings.json не повертає ні ліміт, ні підтвердження."""
        data = {"agent": {"max_steps": 8, "confirm_commands": True}}
        loaded = Settings.from_dict(data)
        self.assertEqual(loaded.agent.max_steps, 0,
                         "старе значення 8 з файлу повернуло ліміт")
        self.assertFalse(loaded.agent.confirm_commands,
                         "старе «питати дозвіл» повернуло діалог")

    def test_custom_step_limit_survives(self) -> None:
        """Свідомо задане число кроків не стирається міграцією."""
        data = {"agent": {"max_steps": 40}}
        self.assertEqual(Settings.from_dict(data).agent.max_steps, 40)


class TestAutoSaveEnabled(unittest.TestCase):
    """Всі файли мають зберігатися самі."""

    def test_autosave_is_on_by_default(self) -> None:
        ui = Settings().ui
        self.assertTrue(getattr(ui, "auto_save", False),
                        "автозбереження вимкнене типово")
        self.assertGreater(float(getattr(ui, "auto_save_delay", 0) or 0), 0,
                           "немає затримки автозбереження")

    def test_editor_has_live_edit_flag(self) -> None:
        """Прапорець, яким автозбереження відрізняє незавершену правку."""
        source = (ROOT / "blackchpok_ide" / "editor.py").read_text(encoding="utf-8")
        self.assertIn("live_edit_active", source,
                      "редактор не має прапорця активної правки")


class TestDuplicatesArePrevented(unittest.TestCase):
    """Причина дублів у файлах: запис буфера з ДВОМА версіями тексту."""

    def test_flush_skips_live_edit(self) -> None:
        """Автозбереження пропускає файл, у якому йде жива правка."""
        source = (ROOT / "blackchpok_ide" / "tabs.py").read_text(encoding="utf-8")
        self.assertIn("live_edit_active", source,
                      "flush_modified не перевіряє активну правку")

    def test_window_flushes_saves_skip_live_edit(self) -> None:
        source = (ROOT / "blackchpok_ide" / "main_window.py").read_text(encoding="utf-8")
        self.assertIn("live_edit_active", source,
                      "збереження всіх вкладок пише буфер із двома версіями")

    def test_cancel_rejects_unfinished_block(self) -> None:
        """Обірвана правка відхиляється, а не лишається в буфері."""
        source = (ROOT / "blackchpok_ide" / "live_edit.py").read_text(encoding="utf-8")
        start = source.index("def cancel_timer")
        end = source.index("def _finish", start)
        body = source[start:end]
        self.assertIn("TAG_NEW", body,
                      "cancel_timer не прибирає нову версію з буфера")
        self.assertIn("_set_active(False)", body,
                      "cancel_timer не знімає прапорець активної правки")

    def test_no_duplicate_feed_block(self) -> None:
        """``feed_block`` оголошений рівно один раз."""
        source = (ROOT / "blackchpok_ide" / "live_edit.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("def feed_block("), 1,
                         "у модулі знову два оголошення feed_block")


class TestNightShiftOwnEngine(unittest.TestCase):
    """Нічна зміна працює на власному рушії, а не на LM Studio."""

    def setUp(self) -> None:
        import night_shift

        self.ns = night_shift

    def test_uses_own_engine(self) -> None:
        self.assertTrue(hasattr(self.ns, "own_engine_complete"),
                        "немає функції генерації через власний рушій")
        self.assertFalse(hasattr(self.ns, "lmstudio_complete"),
                         "LM Studio лишився шляхом нічної зміни")

    def test_main_wires_own_engine(self) -> None:
        source = (ROOT / "night_shift.py").read_text(encoding="utf-8")
        start = source.index("def main()")
        body = source[start:]
        self.assertIn("own_engine_complete", body,
                      "main() не підключив власний рушій")
        self.assertNotIn("lmstudio", body.lower(),
                         "main() досі кличе LM Studio")

    def test_no_http_dependency(self) -> None:
        """Жодного HTTP: рушій працює в процесі."""
        source = (ROOT / "night_shift.py").read_text(encoding="utf-8")
        self.assertNotIn("urllib.request", source,
                         "нічна зміна знову ходить у мережу за моделлю")

    def test_endless_phrase_is_recognised(self) -> None:
        """«24/7» і «без вихідних» не обрізаються вісьмома годинами."""
        for phrase in ("працюй 24/7", "працюй без вихідних",
                       "працюй без кінця", "працюй постійно"):
            with self.subTest(phrase=phrase):
                hours = self.ns.parse_hours(phrase)
                self.assertGreaterEqual(hours, self.ns.MAX_HOURS_UNLIMITED,
                                        f"«{phrase}» обрізано до {hours} год")

    def test_plain_hours_still_work(self) -> None:
        self.assertEqual(self.ns.parse_hours("попрацюй 4 години"), 4)

    def test_run_does_not_clip_endless_budget(self) -> None:
        """``run()`` не обрізає бюджет до MAX_HOURS для режиму 24/7."""
        source = (ROOT / "night_shift.py").read_text(encoding="utf-8")
        start = source.index("def run(self, hours")
        body = source[start:source.index("def _read_lock", start)]
        self.assertIn("MAX_HOURS_UNLIMITED", body,
                      "run() обрізає безкінечний бюджет")


if __name__ == "__main__":
    unittest.main(verbosity=2)
