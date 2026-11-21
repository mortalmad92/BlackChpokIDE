"""Свіжий контекст на кожен запит: хід → пам'ять → чисте вікно.

Вимога користувача (21.11.2026): «не обов'язково тримати все в контексті
постійно! Треба зробити на один запит весь контекст, потім передача в
довгострокову пам'ять і новий контекст і так далі».

Головна небезпека такого режиму — ВТРАТА. Якщо вікно чиститься, а архів не
прийняв дані, контекст зникає назавжди. Тому ці тести перевіряють насамперед
«нічого не загубилось», а вже потім «вікно справді чисте».

Запуск: python -m unittest tests.test_fresh_context -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import config  # noqa: E402
from blackchpok_ide.agent import AgentRunner, AgentSession  # noqa: E402
from blackchpok_ide.agent_tools import ToolRegistry  # noqa: E402


def make_runner(*, turns: int = 6, fresh: bool = True) -> AgentRunner:
    """Раннер із наповненою історією (без мережі й без моделі).

    ``fresh`` тепер задається через ``context_mode``: режимів три
    (auto/fresh/full), і прапорець ``fresh_context`` замінено на них.
    """
    mode = "fresh" if fresh else "full"
    runner = AgentRunner(ToolRegistry(ROOT), config.LLMSettings(),
                         config.AgentSettings(context_mode=mode), ROOT)
    runner.settings_ref = None
    runner.tools_enabled = False
    for index in range(turns):
        runner.session.add_user(f"питання {index} " + "текст " * 30)
        runner.session.messages.append(
            {"role": "assistant", "content": f"відповідь {index} " + "дані " * 40})
    return runner


class TestTurnReset(unittest.TestCase):
    """Хід переїжджає в пам'ять, вікно лишається свіжим."""

    def test_archives_and_clears(self) -> None:
        runner = make_runner()
        archived: list[list] = []
        runner._archive_turn_context = lambda items: archived.append(list(items))
        before = len(runner.session.messages)
        moved = runner.turn_reset()
        self.assertGreater(moved, 0, "нічого не перенесено")
        self.assertEqual(moved, len(archived[0]),
                         "перенесено не те, що архівовано")
        self.assertLess(len(runner.session.messages), before,
                        "вікно не стало свіжим")
        self.assertEqual(before - moved, len(runner.session.messages))

    def test_last_exchange_stays(self) -> None:
        """Останній обмін лишається: без нього модель не знає, про що йшлося."""
        runner = make_runner()
        runner._archive_turn_context = lambda items: None
        last_user = runner.session.messages[-2]
        last_answer = runner.session.messages[-1]
        runner.turn_reset()
        self.assertIn(last_answer, runner.session.messages)
        self.assertIn(last_user, runner.session.messages,
                      "репліка користувача зникла")

    def test_archive_failure_keeps_context(self) -> None:
        """Архів не вдався — історія ЛИШАЄТЬСЯ (краще повне вікно)."""
        runner = make_runner()

        def boom(_items: list) -> None:
            raise RuntimeError("пам'ять недоступна")

        runner._archive_turn_context = boom
        before = list(runner.session.messages)
        moved = runner.turn_reset()
        self.assertEqual(moved, 0)
        self.assertEqual(runner.session.messages, before,
                         "контекст зник, хоч у пам'ять не потрапив")

    def test_private_mode_writes_nothing(self) -> None:
        runner = make_runner()
        runner.state.private = True
        archived: list[list] = []
        runner._archive_turn_context = lambda items: archived.append(list(items))
        before = len(runner.session.messages)
        self.assertEqual(runner.turn_reset(), 0)
        self.assertEqual(archived, [], "приватний режим писав у пам'ять")
        self.assertEqual(len(runner.session.messages), before)

    def test_short_history_is_left_alone(self) -> None:
        runner = make_runner(turns=1)
        runner._archive_turn_context = lambda items: None
        before = len(runner.session.messages)
        runner.turn_reset()
        self.assertEqual(len(runner.session.messages), before)

    def test_empty_history_is_harmless(self) -> None:
        runner = AgentRunner(ToolRegistry(ROOT), config.LLMSettings(),
                             config.AgentSettings(), ROOT)
        runner.tools_enabled = False
        runner._archive_turn_context = lambda items: None
        self.assertEqual(runner.turn_reset(), 0)

    def test_tool_results_travel_with_their_call(self) -> None:
        """Результат інструмента не лишається без свого виклику.

        Обірвана пара ``assistant(tool_calls)`` + ``tool`` ламає протокол:
        сервер відповідає помилкою 400 «tool_call_id не знайдено».
        """
        runner = AgentRunner(ToolRegistry(ROOT), config.LLMSettings(),
                             config.AgentSettings(), ROOT)
        runner.tools_enabled = False
        runner._archive_turn_context = lambda items: None
        for index in range(3):
            runner.session.add_user(f"крок {index}")
            runner.session.messages.append({
                "role": "assistant", "content": "",
                "tool_calls": [{"id": f"c{index}", "type": "function",
                                "function": {"name": "read_file",
                                             "arguments": "{}"}}]})
            runner.session.messages.append({
                "role": "tool", "tool_call_id": f"c{index}",
                "name": "read_file", "content": f"вміст {index}"})
        runner.turn_reset()
        kept = runner.session.messages
        call_ids = {str(c.get("id")) for message in kept
                    for c in (message.get("tool_calls") or [])}
        for message in kept:
            if message.get("role") == "tool":
                self.assertIn(str(message.get("tool_call_id")), call_ids,
                              f"результат {message.get('tool_call_id')} "
                              f"лишився без виклику: {kept}")


class TestSetting(unittest.TestCase):
    """Режим контексту керує поведінкою."""

    def test_default_is_adaptive(self) -> None:
        """Типово — ``auto``: глибина підбирається під запит."""
        self.assertEqual(config.AgentSettings().context_mode, "auto")

    def test_full_mode_keeps_history(self) -> None:
        runner = make_runner(fresh=False)
        archived: list[list] = []
        runner._archive_turn_context = lambda items: archived.append(list(items))
        before = len(runner.session.messages)
        self.assertEqual(runner._reset_context_after_turn(), 0)
        self.assertEqual(len(runner.session.messages), before)
        self.assertEqual(archived, [])

    def test_fresh_mode_resets(self) -> None:
        runner = make_runner(fresh=True)
        runner._archive_turn_context = lambda items: None
        before = len(runner.session.messages)
        self.assertGreater(runner._reset_context_after_turn(), 0)
        self.assertLess(len(runner.session.messages), before)

    def test_broken_archive_does_not_raise(self) -> None:
        runner = make_runner(fresh=True)

        def boom(_items: list) -> None:
            raise RuntimeError("навмисно")

        runner._archive_turn_context = boom
        self.assertEqual(runner._reset_context_after_turn(), 0)


class TestRealMemory(unittest.TestCase):
    """Справжній NEUROMESH: перенесене справді знаходиться пошуком."""

    def test_moved_turn_is_searchable(self) -> None:
        from blackchpok_ide import memory_bridge
        from blackchpok_ide.pcmm import Neuromesh

        database = Path(tempfile.mkdtemp()) / "memory.db"
        service = Neuromesh(database)
        try:
            runner = AgentRunner(ToolRegistry(ROOT), config.LLMSettings(),
                                 config.AgentSettings(context_mode="fresh"), ROOT)
            runner.tools_enabled = False
            runner.memory_bridge = memory_bridge.MemoryBridge(service)
            runner.session.add_user(
                "домовленість: порт сервера проєкту — 7777, не змінювати")
            runner.session.messages.append(
                {"role": "assistant",
                 "content": "Запам'ятав: порт сервера 7777."})
            runner.session.add_user("ще одне питання про інше " + "x " * 40)
            runner.session.messages.append(
                {"role": "assistant", "content": "відповідь " + "y " * 40})

            moved = runner.turn_reset()
            self.assertGreater(moved, 0, "хід не перенесено")

            found = service.search("який порт сервера", limit=5)
            texts = " ".join(hit["memory"]["content"]
                             for hit in found.get("hits") or [])
            self.assertIn("7777", texts,
                          f"домовленість не знайдена в пам'яті: {texts[:250]}")
        finally:
            service.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
