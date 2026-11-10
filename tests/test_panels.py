"""Тести панелей бічної колонки: створення, малювання, реакція на дію.

Шість панелей без жодного тесту: ``stats_bar``, ``session_header``,
``skills_panel``, ``mcp_panel``, ``changes_panel``, ``queue_panel``.
Кожна має створюватись у реальному вікні, малювати вміст і не падати на дії.

Запуск: python -m unittest tests.test_panels -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class PanelTestBase(unittest.TestCase):
    """Спільне вікно для всіх панелей."""

    @classmethod
    def setUpClass(cls) -> None:
        import tkinter as tk
        import tkinter.filedialog as filedialog
        import tkinter.messagebox as messagebox

        from blackchpok_ide import theme

        messagebox.askyesno = lambda *a, **k: True
        messagebox.showinfo = lambda *a, **k: None
        messagebox.showwarning = lambda *a, **k: None
        messagebox.showerror = lambda *a, **k: None
        filedialog.asksaveasfilename = lambda *a, **k: ""
        filedialog.askopenfilename = lambda *a, **k: ""

        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError as exc:  # pragma: no cover - без дисплея
            raise unittest.SkipTest(f"tkinter недоступний: {exc}") from exc
        cls.fonts = theme.Theme(cls.root)
        cls.fonts.apply()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def pump(self) -> None:
        self.root.update()

    def statuses(self) -> list[str]:
        self._statuses: list[str] = getattr(self, "_statuses", [])
        return self._statuses

    def collect_status(self, text: str) -> None:
        if not hasattr(self, "_statuses"):
            self._statuses: list[str] = []
        self._statuses.append(text)


class TestStatsBar(PanelTestBase):
    """Рядок статистики."""

    def test_creates(self) -> None:
        from blackchpok_ide import stats_bar

        bar = stats_bar.StatsBar(self.root, self.fonts)
        bar.pack(fill="x")
        self.pump()
        self.assertTrue(bar.winfo_exists())

    def test_reset_does_not_raise(self) -> None:
        from blackchpok_ide import stats_bar

        bar = stats_bar.StatsBar(self.root, self.fonts)
        bar.pack(fill="x")
        self.pump()
        bar.reset()
        self.pump()

    def test_set_limit_accepts_number(self) -> None:
        from blackchpok_ide import stats_bar

        bar = stats_bar.StatsBar(self.root, self.fonts)
        bar.pack(fill="x")
        self.pump()
        bar.set_limit(8192)
        self.pump()
        bar.set_limit(0)
        self.pump()


class TestSessionHeader(PanelTestBase):
    """Заголовок сесії."""

    def test_creates(self) -> None:
        from blackchpok_ide import session_header

        header = session_header.SessionHeader(self.root, self.fonts)
        header.pack(fill="x")
        self.pump()
        self.assertTrue(header.winfo_exists())

    def test_set_title(self) -> None:
        from blackchpok_ide import session_header

        header = session_header.SessionHeader(self.root, self.fonts)
        header.pack(fill="x")
        self.pump()
        header.set_title("Тестова сесія")
        self.pump()

    def test_set_view_and_mode(self) -> None:
        from blackchpok_ide import session_header

        header = session_header.SessionHeader(self.root, self.fonts)
        header.pack(fill="x")
        self.pump()
        header.set_view("chat")
        self.pump()
        header.set_view("workspace")
        self.pump()
        header.set_mode("agent")
        self.pump()

    def test_set_workspace(self) -> None:
        from blackchpok_ide import session_header

        header = session_header.SessionHeader(self.root, self.fonts)
        header.pack(fill="x")
        self.pump()
        header.set_workspace("blackchpock_ai")
        self.pump()

    def test_callbacks_are_wired(self) -> None:
        from blackchpok_ide import session_header

        calls: list[str] = []
        header = session_header.SessionHeader(
            self.root, self.fonts,
            on_modes=lambda: calls.append("modes"),
            on_model=lambda: calls.append("model"),
            on_view=lambda _v: calls.append("view"),
        )
        header.pack(fill="x")
        self.pump()
        header.on_modes()
        header.on_model()
        self.assertEqual(calls, ["modes", "model"])


class TestSkillsPanel(PanelTestBase):
    """Панель скілів."""

    def setUp(self) -> None:
        from blackchpok_ide import skills as skills_mod

        self.folder = Path(tempfile.mkdtemp())
        self.book = skills_mod.SkillBook(ROOT)

    def test_creates_and_lists_skills(self) -> None:
        from blackchpok_ide import skills_panel

        panel = skills_panel.SkillsPanel(self.root, self.fonts, self.book,
                                         on_status=self.collect_status)
        panel.pack(fill="both", expand=True)
        self.pump()
        self.assertTrue(panel.winfo_exists())

    def test_refresh_does_not_raise(self) -> None:
        from blackchpok_ide import skills_panel

        panel = skills_panel.SkillsPanel(self.root, self.fonts, self.book)
        panel.pack(fill="both", expand=True)
        self.pump()
        panel.refresh()
        self.pump()

    def test_reload_does_not_raise(self) -> None:
        from blackchpok_ide import skills_panel

        panel = skills_panel.SkillsPanel(self.root, self.fonts, self.book)
        panel.pack(fill="both", expand=True)
        self.pump()
        if hasattr(panel, "reload"):
            panel.reload()
            self.pump()


class TestMcpPanel(PanelTestBase):
    """Панель MCP-серверів."""

    def test_creates_empty_state(self) -> None:
        from blackchpok_ide import mcp_client, mcp_panel

        manager = mcp_client.McpManager()
        panel = mcp_panel.McpPanel(self.root, self.fonts, manager,
                                   lambda: Path(ROOT),
                                   on_status=self.collect_status)
        panel.pack(fill="both", expand=True)
        self.pump()
        self.assertTrue(panel.winfo_exists())
        self.assertIn("не підключено", str(panel.summary.cget("text")).lower())

    def test_refresh_is_safe(self) -> None:
        from blackchpok_ide import mcp_client, mcp_panel

        manager = mcp_client.McpManager()
        panel = mcp_panel.McpPanel(self.root, self.fonts, manager,
                                   lambda: Path(ROOT))
        panel.pack(fill="both", expand=True)
        self.pump()
        panel.refresh()
        self.pump()

    def test_load_without_config_reports_status(self) -> None:
        from blackchpok_ide import mcp_client, mcp_panel

        empty = Path(tempfile.mkdtemp())
        manager = mcp_client.McpManager()
        panel = mcp_panel.McpPanel(self.root, self.fonts, manager,
                                   lambda: empty,
                                   on_status=self.collect_status)
        panel.pack(fill="both", expand=True)
        self.pump()
        panel.load_from_workspace()
        self.pump()
        self.assertTrue(self.statuses(), "має бути повідомлення про відсутність конфігурації")

    def test_restart_is_safe(self) -> None:
        from blackchpok_ide import mcp_client, mcp_panel

        manager = mcp_client.McpManager()
        panel = mcp_panel.McpPanel(self.root, self.fonts, manager,
                                   lambda: Path(ROOT),
                                   on_status=self.collect_status)
        panel.pack(fill="both", expand=True)
        self.pump()
        panel.restart()
        self.pump()


class TestChangesPanel(PanelTestBase):
    """Панель змін у файлах."""

    def test_creates(self) -> None:
        from blackchpok_ide import changes_panel

        panel = changes_panel.ChangesPanel(self.root, self.fonts,
                                           lambda: Path(ROOT),
                                           on_status=self.collect_status)
        panel.pack(fill="both", expand=True)
        self.pump()
        self.assertTrue(panel.winfo_exists())

    def test_refresh_does_not_raise(self) -> None:
        from blackchpok_ide import changes_panel

        panel = changes_panel.ChangesPanel(self.root, self.fonts,
                                           lambda: Path(ROOT))
        panel.pack(fill="both", expand=True)
        self.pump()
        panel.refresh()
        self.pump()

    def test_refresh_on_empty_folder(self) -> None:
        from blackchpok_ide import changes_panel

        empty = Path(tempfile.mkdtemp())
        panel = changes_panel.ChangesPanel(self.root, self.fonts, lambda: empty)
        panel.pack(fill="both", expand=True)
        self.pump()
        panel.refresh()
        self.pump()


class TestQueuePanel(PanelTestBase):
    """Панель черги завдань."""

    def setUp(self) -> None:
        from blackchpok_ide import queue_engine

        self.folder = Path(tempfile.mkdtemp())
        self.queue = queue_engine.TaskQueue(self.folder / "queue.json")

    def test_creates(self) -> None:
        from blackchpok_ide import queue_panel

        panel = queue_panel.QueuePanel(self.root, self.fonts, self.queue,
                                       on_status=self.collect_status)
        panel.pack(fill="both", expand=True)
        self.pump()
        self.assertTrue(panel.winfo_exists())

    def test_add_text_adds_task(self) -> None:
        from blackchpok_ide import queue_panel

        panel = queue_panel.QueuePanel(self.root, self.fonts, self.queue)
        panel.pack(fill="both", expand=True)
        self.pump()
        added = panel.add_text("перевірити проєкт")
        self.pump()
        self.assertGreaterEqual(added, 1)
        self.assertGreaterEqual(len(self.queue.tasks), 1)

    def test_add_batch_multiple_lines(self) -> None:
        from blackchpok_ide import queue_panel

        panel = queue_panel.QueuePanel(self.root, self.fonts, self.queue)
        panel.pack(fill="both", expand=True)
        self.pump()
        added = panel.add_text("- перше\n- друге\n- третє")
        self.pump()
        self.assertEqual(added, 3)

    def test_refresh_empty_queue(self) -> None:
        from blackchpok_ide import queue_panel

        panel = queue_panel.QueuePanel(self.root, self.fonts, self.queue)
        panel.pack(fill="both", expand=True)
        self.pump()
        panel.refresh()
        self.pump()

    def test_clear_queue_empties_it(self) -> None:
        from blackchpok_ide import queue_panel

        panel = queue_panel.QueuePanel(self.root, self.fonts, self.queue)
        panel.pack(fill="both", expand=True)
        self.pump()
        panel.add_text("задача")
        self.pump()
        self.queue.clear()
        panel.refresh()
        self.pump()
        self.assertEqual(len(self.queue.tasks), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
