"""Налаштування з НОВІШОЇ версії IDE не мають ламати запуск.

Реальний сценарій: користувач оновив IDE, новіша версія дописала у
``settings.json`` нове поле, потім він відкотився на старішу версію — і
вона падала з ``TypeError: LLMSettings.__init__() got an unexpected keyword
argument``. Для користувача це «IDE не запускається після відкату».

Зачеплено було чотири місця: LLMSettings, UISettings, AgentSettings,
EngineSettings — усі створювались як ``Class(**data)`` без фільтрації.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import config  # noqa: E402


class SettingsOuterVersionCase(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp(prefix="future-settings-"))
        self._old_home = os.environ.get("BLACKCHPOK_HOME")
        self._old_save = os.environ.get("BLACKCHPOK_NO_SAVE")
        os.environ["BLACKCHPOK_HOME"] = str(self.home)
        os.environ["BLACKCHPOK_NO_SAVE"] = "1"

    def tearDown(self) -> None:
        import shutil

        for key, value in (("BLACKCHPOK_HOME", self._old_home),
                           ("BLACKCHPOK_NO_SAVE", self._old_save)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.home, ignore_errors=True)

    def _write(self, payload: dict) -> Path:
        path = self.home / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    # ── основне ──────────────────────────────────────────────────────────
    def test_unknown_fields_in_llm_do_not_break_load(self) -> None:
        self._write({
            "version": 999,
            "llm": {"model": "future-model", "unknown_field": {"deep": [1, 2]},
                    "another_new_one": "x"},
        })
        settings = config.Settings.load()
        self.assertEqual(settings.llm.model, "future-model",
                         "відоме поле втрачено через невідоме")

    def test_unknown_fields_in_ui_do_not_break_load(self) -> None:
        self._write({"ui": {"theme": "light", "brand_new": 42}})
        settings = config.Settings.load()
        self.assertEqual(settings.ui.theme, "light")

    def test_unknown_fields_in_agent_do_not_break_load(self) -> None:
        self._write({"agent": {"max_steps": 5, "future_flag": True}})
        settings = config.Settings.load()
        self.assertEqual(settings.agent.max_steps, 5)

    def test_unknown_fields_in_engine_do_not_break_load(self) -> None:
        self._write({"engine": {"native": True, "port": 9090, "next_thing": [1]}})
        settings = config.Settings.load()
        self.assertTrue(settings.engine.native)
        self.assertEqual(settings.engine.port, 9090)

    def test_unknown_top_level_section_ignored(self) -> None:
        self._write({"brand_new_section": {"a": 1}, "llm": {"model": "m1"}})
        settings = config.Settings.load()
        self.assertEqual(settings.llm.model, "m1")

    def test_known_fields_still_read(self) -> None:
        """Фільтр не має викидати РЕАЛЬНІ поля."""
        self._write({"llm": {"model": "keep-me", "temperature": 0.42},
                     "ui": {"theme": "dark"}})
        settings = config.Settings.load()
        self.assertEqual(settings.llm.model, "keep-me")
        self.assertAlmostEqual(settings.llm.temperature, 0.42, places=3)
        self.assertEqual(settings.ui.theme, "dark")

    def test_api_key_enc_still_not_passed_to_dataclass(self) -> None:
        """Шифротекст і далі не має потрапляти у конструктор."""
        self._write({"llm": {"model": "m", "api_key_enc": "ZmFrZQ=="}})
        settings = config.Settings.load()   # не має кинути
        self.assertEqual(settings.llm.model, "m")


class OnlyKnownHelperCase(unittest.TestCase):
    def test_filters_unknown_keys(self) -> None:
        data = {"model": "a", "nonexistent": 1, "temperature": 0.5}
        kept = config.Settings._only_known(config.LLMSettings, data)
        self.assertIn("model", kept)
        self.assertIn("temperature", kept)
        self.assertNotIn("nonexistent", kept)

    def test_handles_empty_and_none(self) -> None:
        self.assertEqual(config.Settings._only_known(config.LLMSettings, {}), {})
        self.assertEqual(config.Settings._only_known(config.LLMSettings, None), {})

    def test_non_dataclass_returns_data_unchanged(self) -> None:
        data = {"a": 1}
        self.assertEqual(config.Settings._only_known(dict, data), data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
