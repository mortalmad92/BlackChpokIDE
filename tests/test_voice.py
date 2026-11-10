"""Тести голосового керування: розпізнавання команд, рушії, очищення тексту.

``voice`` — 526 рядків без жодного тесту, хоч він вирішує, чи команда
користувача стане дією, чи звичайним запитом до агента.

Запуск: python -m unittest tests.test_voice -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import voice  # noqa: E402


class TestEngines(unittest.TestCase):
    """Вибір рушія розпізнавання."""

    def test_engines_list_has_both(self) -> None:
        engines = voice.engines()
        keys = {key for key, _ok, _desc in engines}
        self.assertEqual(keys, {"whisper", "windows"})

    def test_engine_entries_are_described(self) -> None:
        for key, ok, desc in voice.engines():
            self.assertIsInstance(ok, bool, key)
            self.assertTrue(desc, f"{key}: порожній опис")

    def test_best_engine_returns_known_key_or_empty(self) -> None:
        best = voice.best_engine()
        self.assertIn(best, ("whisper", "windows", ""))

    def test_windows_speech_availability_is_bool(self) -> None:
        self.assertIsInstance(voice.windows_speech_available(), bool)

    def test_whisper_cli_returns_path_or_none(self) -> None:
        result = voice.whisper_cli("")
        self.assertTrue(result is None or isinstance(result, Path))


class TestParseCommand(unittest.TestCase):
    """Голосова фраза → (ключ дії, підпис)."""

    def test_new_chat_phrase(self) -> None:
        self.assertEqual(voice.parse_command("новий чат"), ("new_chat", "Новий чат"))

    def test_stop_phrase(self) -> None:
        self.assertEqual(voice.parse_command("зупинись"), ("stop", "Зупинити агента"))

    def test_files_phrase(self) -> None:
        self.assertEqual(voice.parse_command("покажи файли"), ("files", "Показати файли"))

    def test_conversation_is_not_a_command(self) -> None:
        for text in ("привіт як справи", "дякую за допомогу", "розкажи вірш"):
            key, label = voice.parse_command(text)
            self.assertEqual(key, "", text)
            self.assertEqual(label, "", text)

    def test_parse_is_case_insensitive(self) -> None:
        lower = voice.parse_command("покажи файли")
        upper = voice.parse_command("ПОКАЖИ ФАЙЛИ")
        self.assertEqual(lower[0], upper[0])

    def test_empty_text_gives_no_command(self) -> None:
        self.assertEqual(voice.parse_command(""), ("", ""))


class TestWakeWord(unittest.TestCase):
    """Розпізнавання звертання до асистента."""

    def test_wake_word_detection_is_bool(self) -> None:
        for text in ("чпок, покажи файли", "просто текст", ""):
            self.assertIsInstance(voice.is_wake_word(text), bool)

    def test_strip_wake_word_returns_string(self) -> None:
        for text in ("чпок покажи файли", "просто текст"):
            self.assertIsInstance(voice.strip_wake_word(text), str)

    def test_strip_wake_word_never_lengthens_text(self) -> None:
        text = "чпок покажи файли"
        self.assertLessEqual(len(voice.strip_wake_word(text)), len(text))


class TestCleanForSpeech(unittest.TestCase):
    """Очищення markdown перед озвученням."""

    def test_removes_backticks(self) -> None:
        self.assertNotIn("`", voice.clean_for_speech("`код`"))

    def test_removes_bold_markers(self) -> None:
        self.assertNotIn("**", voice.clean_for_speech("**жирний** текст"))

    def test_removes_links_keeps_text(self) -> None:
        result = voice.clean_for_speech("[документація](https://example.com)")
        self.assertNotIn("https://example.com", result)
        self.assertIn("документація", result)

    def test_empty_text_stays_empty(self) -> None:
        self.assertEqual(voice.clean_for_speech("").strip(), "")

    def test_plain_text_is_unchanged(self) -> None:
        self.assertIn("звичайний текст", voice.clean_for_speech("звичайний текст"))


class TestShortText(unittest.TestCase):
    """Обрізання тексту для озвучення й статусбара."""

    def test_short_text_untouched(self) -> None:
        self.assertEqual(voice.short_text("коротко", 40), "коротко")

    def test_long_text_is_truncated_with_ellipsis(self) -> None:
        result = voice.short_text("a" * 300, 40)
        self.assertLessEqual(len(result), 41)
        self.assertTrue(result.endswith("…"))

    def test_empty_text(self) -> None:
        self.assertEqual(voice.short_text("", 40), "")

    def test_limit_respected_for_words(self) -> None:
        text = "слово " * 100
        self.assertLessEqual(len(voice.short_text(text, 30)), 31)


class TestVoiceSettings(unittest.TestCase):
    """Типові налаштування голосу."""

    def test_defaults_are_sane(self) -> None:
        settings = voice.VoiceSettings()
        self.assertIsInstance(settings.enabled, bool)
        self.assertIsInstance(settings.speak_replies, bool)
        self.assertGreater(settings.seconds, 0)
        self.assertTrue(settings.language)

    def test_language_has_value(self) -> None:
        self.assertTrue(voice.VoiceSettings().language)


class TestVoiceCommandsText(unittest.TestCase):
    """Довідка з голосових команд."""

    def test_help_text_is_not_empty(self) -> None:
        text = voice.voice_commands_text()
        self.assertTrue(text.strip())
        self.assertGreater(len(text), 20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
