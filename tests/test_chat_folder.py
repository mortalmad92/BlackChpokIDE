"""Один чат — одна тека, і робота не переходить у чужу.

Запуск: python -m unittest tests.test_chat_folder -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestChatFolderBinding(unittest.TestCase):
    def setUp(self) -> None:
        from blackchpok_ide import chat_store
        from blackchpok_ide.queue_engine import TaskQueue

        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.left = root / "left"
        self.right = root / "right"
        self.left.mkdir()
        self.right.mkdir()
        self.store = chat_store.ChatStore(path=root / "chats.json")
        self.queue = TaskQueue(path=root / "queue.json")
        self.same = chat_store.same_folder

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_second_folder_does_not_replace_the_first(self) -> None:
        chat = self.store.create(title="лівий", workspace=str(self.left))
        self.assertEqual(self.store.bind_workspace(chat.id, str(self.right)), "refused")
        self.assertTrue(self.same(self.store.get(chat.id).workspace, str(self.left)))
        self.assertEqual(self.store.bind_workspace(chat.id, str(self.left)), "same")

    def test_lookup_returns_the_chat_of_that_folder(self) -> None:
        left = self.store.create(title="лівий", workspace=str(self.left))
        right = self.store.create(title="правий", workspace=str(self.right))
        self.assertEqual(self.store.chat_for_workspace(str(self.left)).id, left.id)
        self.assertEqual(self.store.chat_for_workspace(str(self.right)).id, right.id)
        self.assertIsNone(self.store.chat_for_workspace(str(Path(self.tmp.name))))

    def test_queue_of_one_chat_does_not_run_in_the_other(self) -> None:
        left = self.store.create(title="лівий", workspace=str(self.left))
        right = self.store.create(title="правий", workspace=str(self.right))
        self.queue.add("писати у праву теку", chat_id=right.id)
        self.queue.add("писати у ліву теку", chat_id=left.id)
        self.queue.add("сирота без чату")
        own = self.queue.next_pending(chat_id=left.id)
        self.assertIsNotNone(own)
        self.assertEqual(own.chat_id, left.id)
        self.assertEqual(own.text, "писати у ліву теку")
        other = self.queue.next_pending(chat_id=right.id)
        self.assertEqual(other.chat_id, right.id)
        self.assertIsNone(self.queue.next_pending(chat_id="немає-такого-чату"))

    def test_request_snaps_agent_back_to_the_chat_folder(self) -> None:
        from blackchpok_ide.main_window import BlackChpokIDE

        chat = self.store.create(title="лівий", workspace=str(self.left))
        self.store.set_active(chat.id)
        host = SimpleNamespace(
            chat_store=self.store,
            agent=SimpleNamespace(workspace=self.right),
            settings=SimpleNamespace(workspace=str(self.right)),
            applied=[],
        )

        def apply(folder: Path) -> None:
            host.applied.append(Path(folder))
            host.agent.workspace = Path(folder)
            host.settings.workspace = str(folder)

        host._apply_workspace = apply
        host.set_status = lambda text: setattr(host, "status", text)
        host.has_project = lambda: True
        ready = BlackChpokIDE._chat_folder_ready.__get__(host)
        self.assertTrue(ready())
        self.assertEqual(host.applied[-1].resolve(), self.left.resolve())
        self.assertTrue(self.same(str(host.agent.workspace), str(self.left)))

    def test_missing_chat_folder_blocks_the_request(self) -> None:
        from blackchpok_ide.main_window import BlackChpokIDE

        gone = Path(self.tmp.name) / "немає"
        chat = self.store.create(title="битий", workspace=str(gone))
        self.store.set_active(chat.id)
        host = SimpleNamespace(
            chat_store=self.store,
            agent=SimpleNamespace(workspace=self.right),
            settings=SimpleNamespace(workspace=str(self.right)),
            status="",
        )
        host._apply_workspace = lambda folder: None
        host.set_status = lambda text: setattr(host, "status", text)
        host.has_project = lambda: True
        ready = BlackChpokIDE._chat_folder_ready.__get__(host)
        self.assertFalse(ready())
        self.assertIn("немає", host.status)

    def test_open_chat_applies_its_own_folder(self) -> None:
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE.open_chat)
        self.assertIn("_apply_workspace", source)
        self.assertNotIn("set_workspace(", source)
        pump = inspect.getsource(BlackChpokIDE._queue_pump)
        self.assertNotIn("_adopt_orphan_tasks()", pump)
