"""Тести адаптера моделі й збереження стану розмови.

Дві речі, які ламали агента найчастіше:

* схеми інструментів передавались моделі, яка нативного виклику не має;
* стан завдання (мета, обмеження) зникав після перезапуску програми.

Запуск: python -m unittest tests.test_model_profile tests.test_conversation
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import conversation, model_profile  # noqa: E402


class TestModelProfile(unittest.TestCase):
    """Профіль визначає, ЯК кликати інструменти для цієї моделі."""

    def test_strong_family_uses_native(self) -> None:
        profile = model_profile.profile_for("qwen2.5-coder-14b", "http://127.0.0.1:1234/v1")
        self.assertTrue(profile.native_tools)
        self.assertFalse(profile.text_protocol)
        self.assertGreater(profile.max_tools, model_profile.WEAK_MAX_TOOLS)

    def test_weak_model_uses_text_protocol(self) -> None:
        profile = model_profile.profile_for("tinyllama-1.1b", "http://127.0.0.1:1234/v1")
        self.assertFalse(profile.native_tools)
        self.assertTrue(profile.text_protocol)
        self.assertEqual(profile.max_tools, model_profile.WEAK_MAX_TOOLS)

    def test_small_window_uses_compact_prompt(self) -> None:
        profile = model_profile.profile_for(
            "qwen2.5-coder-14b", "http://127.0.0.1:1234/v1", context_window=4096)
        self.assertTrue(profile.compact_prompt)

    def test_large_window_keeps_full_prompt(self) -> None:
        profile = model_profile.profile_for(
            "qwen2.5-coder-14b", "http://127.0.0.1:1234/v1", context_window=32000)
        self.assertFalse(profile.compact_prompt)

    def test_unknown_model_is_safe(self) -> None:
        profile = model_profile.profile_for("", "native://blackchpok")
        self.assertTrue(profile.note)
        # Підказку формату додаємо — вона нешкідлива й допомагає.
        self.assertTrue(profile.text_protocol or profile.native_tools)

    def test_reasoning_and_vision_flags(self) -> None:
        profile = model_profile.profile_for("deepseek-r1-14b")
        self.assertTrue(profile.reasoning)
        vision = model_profile.profile_for("llava-v1.6-7b")
        self.assertTrue(vision.vision)

    def test_text_protocol_shows_exactly_one_format(self) -> None:
        text = model_profile.text_tool_protocol(("read_file", "list_dir"))
        self.assertIn('"name"', text)
        self.assertIn("read_file", text)
        # Один формат, а не три альтернативи: інакше модель їх змішує.
        self.assertEqual(text.count("arguments"), 1)

    def test_describe_is_human_text(self) -> None:
        profile = model_profile.profile_for("tinyllama-1.1b")
        text = profile.describe()
        self.assertIn("інструменти текстом", text)
        self.assertNotIn("{", text)


class TestPreferences(unittest.TestCase):
    """Довготривалі побажання відділяються від тимчасових інструкцій."""

    def test_explicit_rule_is_saved(self) -> None:
        found, private = conversation.extract_preferences(
            "завжди відповідай українською")
        self.assertFalse(private)
        self.assertEqual([(item.key, item.value) for item in found],
                         [("language", "українська")])

    def test_one_off_request_is_not_saved(self) -> None:
        found, _private = conversation.extract_preferences("зроби коротко")
        self.assertEqual(found, [])

    def test_remember_marker_is_saved(self) -> None:
        found, _private = conversation.extract_preferences(
            "запам'ятай: мінімальні правки")
        self.assertTrue(any(item.key == "code_style" for item in found))

    def test_private_request_blocks_saving(self) -> None:
        found, private = conversation.extract_preferences(
            "не зберігай це, завжди відповідай українською")
        self.assertTrue(private)
        self.assertEqual(found, [])

    def test_profile_prompt_is_short(self) -> None:
        profile = conversation.UserProfile()
        profile.remember(conversation.Preference("language", "українська"))
        block = profile.prompt_block()
        self.assertIn("українська", block)
        self.assertNotIn("{", block)

    def test_profile_round_trip(self) -> None:
        profile = conversation.UserProfile()
        profile.remember(conversation.Preference("language", "українська"))
        profile.remember(conversation.Preference("verbosity", "коротко"))
        restored = conversation.UserProfile.from_list(profile.to_list())
        self.assertEqual(restored.get("language"), "українська")
        self.assertEqual(restored.get("verbosity"), "коротко")
        self.assertEqual(restored.language(), "uk")

    def test_garbage_entries_are_skipped(self) -> None:
        restored = conversation.UserProfile.from_list(
            ["рядок", {"key": "", "value": "x"}, {"key": "a", "value": "b"}])
        self.assertEqual(len(restored.all()), 1)


class TestConversationState(unittest.TestCase):
    """Стан завдання переживає перезапуск і не губить обмежень."""

    def test_state_round_trip(self) -> None:
        state = conversation.ConversationState()
        state.observe_user_message(
            "Перероби збереження чатів, тільки щоб старі не видалялись")
        state.note_done("прочитав chat_store.py")
        restored = conversation.ConversationState.from_dict(state.to_dict())
        self.assertEqual(restored.constraints, state.constraints)
        self.assertEqual(restored.completed, ["прочитав chat_store.py"])

    def test_new_task_keeps_constraints(self) -> None:
        """«Не видаляй старі» діє й для наступного завдання в цьому чаті."""
        state = conversation.ConversationState()
        state.constraints = ["не видаляти наявні дані"]
        state.reset_task()
        self.assertEqual(state.constraints, ["не видаляти наявні дані"])

    def test_private_flag_round_trip(self) -> None:
        state = conversation.ConversationState()
        state.private = True
        self.assertTrue(conversation.ConversationState.from_dict(
            state.to_dict()).private)

    def test_corrupted_state_is_tolerated(self) -> None:
        restored = conversation.ConversationState.from_dict(
            {"constraints": "не список", "turns": "багато"})
        self.assertEqual(restored.constraints, [])
        self.assertEqual(restored.turns, 0)

    def test_prompt_block_has_no_json(self) -> None:
        state = conversation.ConversationState()
        state.goal = "Правка файлів"
        state.constraints = ["не ламати наявну поведінку"]
        block = state.prompt_block()
        self.assertIn("обмеження", block.lower())
        self.assertNotIn("{", block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
