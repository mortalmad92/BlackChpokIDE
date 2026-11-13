"""Вікно, відкрите з ЯВНО заданою текою, не переїжджає в теку чужого чату.

Дефект (заміряно живим прогоном ``tools/check_plain_language_live.py``):

    СЦЕНАРІЙ: калькулятор      → OK, файл створено
    СЦЕНАРІЙ: привітання       → УВАГА: запит НЕ прийнято
      guard=False,
      chat_ws  = …\\plain-e8h26xw2   ← тека ПОПЕРЕДНЬОГО вікна
      agent_ws = …\\plain-vjzewvll   ← тека ЦЬОГО вікна

Причина: ``chat_store.ensure_active`` відновлює ОСТАННІЙ активний чат із
``chats.json`` — з іншої теки. Вікно перемикалося на теку того чату,
``_chat_folder_ready`` не сходився з робочою текою і повертав ``False``.
Запит не йшов, файли не створювались — «натиснув, нічого не сталося».

Правило, яке тепер діє:

* при СТАРТІ вікна з явно заданою текою — чат прив'язується до неї;
* усередині чату — навпаки, чат тримає свою теку (це перевіряє
  ``tests/test_chat_folder.py``).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestWindowWorkspaceWins(TestCase):
    """Чат успадкований — прив'язується до теки вікна."""

    def setUp(self) -> None:
        os.environ.setdefault("BLACKCHPOK_HOME",
                              tempfile.mkdtemp(prefix="bind-home-"))
        os.environ["BLACKCHPOK_NO_SAVE"] = "1"
        self.home = tempfile.mkdtemp(prefix="bind-case-")
        self.previous_home = os.environ.get("BLACKCHPOK_HOME")
        os.environ["BLACKCHPOK_HOME"] = self.home

    def tearDown(self) -> None:
        if self.previous_home:
            os.environ["BLACKCHPOK_HOME"] = self.previous_home

    @staticmethod
    def _dialogs() -> None:
        import tkinter.filedialog as fd
        import tkinter.messagebox as mb

        mb.askyesno = lambda *a, **k: True
        mb.showinfo = lambda *a, **k: None
        mb.showwarning = lambda *a, **k: None
        mb.showerror = lambda *a, **k: None
        fd.askdirectory = lambda *a, **k: ""

    def test_inherited_chat_rebinds_to_window_folder(self) -> None:
        """Друге вікно зі своєю текою мусить працювати в НІЙ."""
        self._dialogs()
        from blackchpok_ide.config import Settings
        from blackchpok_ide.main_window import BlackChpokIDE

        # 1. Перше вікно створює чат у СВОЇЙ теці.
        first_ws = Path(tempfile.mkdtemp(prefix="bind-first-"))
        settings = Settings.load()
        settings.workspace = str(first_ws)
        settings.first_run_done = True
        settings.project_chosen = True
        settings.engine.auto_start = False
        settings.agent.queue_auto_run = False
        app = BlackChpokIDE(settings)
        try:
            for _ in range(40):
                app.update()
            if app.chat_store.active() is None:
                app.chat_store.create(workspace=str(first_ws), title="перший")
                app.chat_store.save()
        finally:
            try:
                app.agent.cancel()
                app.destroy()
            except Exception:  # noqa: BLE001
                pass

        # 2. Друге вікно — ІНША тека, той самий chats.json.
        second_ws = Path(tempfile.mkdtemp(prefix="bind-second-"))
        settings2 = Settings.load()
        settings2.workspace = str(second_ws)
        settings2.first_run_done = True
        settings2.project_chosen = True
        settings2.engine.auto_start = False
        settings2.agent.queue_auto_run = False
        app2 = BlackChpokIDE(settings2)
        try:
            for _ in range(40):
                app2.update()
            active = app2.chat_store.active()
            self.assertIsNotNone(active, "чат не відновився")
            self.assertEqual(Path(active.workspace).resolve(),
                             second_ws.resolve(),
                             "чат лишився в теці попереднього вікна")
            self.assertEqual(Path(app2.agent.workspace).resolve(),
                             second_ws.resolve(),
                             "агент працює не в теці вікна")
            guard = getattr(app2.chat, "folder_guard", None)
            self.assertTrue(guard() if guard else True,
                            "сторож теки блокує запит у власній теці вікна")
        finally:
            try:
                app2.agent.cancel()
                app2.destroy()
            except Exception:  # noqa: BLE001
                pass


class TestChatKeepsItsFolderInside(TestCase):
    """Усередині чату діє ЗВОРОТНЕ правило: чат тримає свою теку.

    Це не суперечність: при старті вікно має волю (воно щойно відкрите з
    конкретною текою), а в роботі — чат, бо користувач свідомо його обрав.
    """

    def test_guard_snaps_agent_to_chat_folder(self) -> None:
        from types import SimpleNamespace

        from blackchpok_ide import chat_store
        from blackchpok_ide.main_window import BlackChpokIDE

        root = Path(tempfile.mkdtemp(prefix="keep-chat-"))
        left = root / "left"
        right = root / "right"
        left.mkdir()
        right.mkdir()
        store = chat_store.ChatStore(path=root / "chats.json")
        chat = store.create(title="лівий", workspace=str(left))
        store.set_active(chat.id)
        host = SimpleNamespace(
            chat_store=store,
            agent=SimpleNamespace(workspace=right),
            settings=SimpleNamespace(workspace=str(right)),
            applied=[],
        )

        def apply(folder: Path) -> None:
            host.applied.append(Path(folder))
            host.agent.workspace = Path(folder)
            host.settings.workspace = str(folder)

        host._apply_workspace = apply
        host.set_status = lambda text: None
        host.has_project = lambda: True
        ready = BlackChpokIDE._chat_folder_ready.__get__(host)
        self.assertTrue(ready())
        self.assertEqual(host.applied[-1].resolve(), left.resolve(),
                         "агент не повернувся в теку чату")


if __name__ == "__main__":
    main()
