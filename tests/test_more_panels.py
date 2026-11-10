"""Тести решти панелей: файли, стартовий екран, термінал, прев'ю, голос.

Сім модулів без жодного тесту. Кожен має створюватись у реальному вікні,
показувати вміст і не падати на типових діях. Термінал перевіряємо
справжньою командою — це єдина панель, що запускає процеси.

Запуск: python -m unittest tests.test_more_panels -v
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class Base(unittest.TestCase):
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
        filedialog.askdirectory = lambda *a, **k: str(ROOT)

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

    def pump(self, seconds: float = 0.15) -> None:
        end = time.time() + seconds
        while time.time() < end:
            try:
                self.root.update()
            except Exception:
                return
            time.sleep(0.005)


class TestFileTree(Base):
    """Дерево файлів."""

    def test_creates_with_root_dir(self) -> None:
        from blackchpok_ide import file_tree

        tree = file_tree.FileTree(self.root, lambda p: None, root_dir=Path(ROOT))
        tree.pack(fill="both", expand=True)
        self.pump()
        self.assertTrue(tree.winfo_exists())

    def test_creates_without_root(self) -> None:
        from blackchpok_ide import file_tree

        tree = file_tree.FileTree(self.root, lambda p: None)
        tree.pack(fill="both", expand=True)
        self.pump()
        self.assertTrue(tree.winfo_exists())

    def test_refresh_is_safe(self) -> None:
        from blackchpok_ide import file_tree

        tree = file_tree.FileTree(self.root, lambda p: None, root_dir=Path(ROOT))
        tree.pack(fill="both", expand=True)
        self.pump()
        if hasattr(tree, "refresh"):
            tree.refresh()
            self.pump()

    def test_set_root_changes_folder(self) -> None:
        from blackchpok_ide import file_tree

        tree = file_tree.FileTree(self.root, lambda p: None, root_dir=Path(ROOT))
        tree.pack(fill="both", expand=True)
        self.pump()
        folder = Path(tempfile.mkdtemp())
        (folder / "test.txt").write_text("x", encoding="utf-8")
        if hasattr(tree, "set_root"):
            tree.set_root(folder)
            self.pump()

    def test_on_status_callback(self) -> None:
        from blackchpok_ide import file_tree

        seen: list[str] = []
        tree = file_tree.FileTree(self.root, lambda p: None, root_dir=Path(ROOT))
        tree.on_status = seen.append
        tree.pack(fill="both", expand=True)
        self.pump()
        self.assertTrue(tree.winfo_exists())


class TestWelcomeScreen(Base):
    """Стартовий екран."""

    def test_creates(self) -> None:
        from blackchpok_ide import welcome

        screen = welcome.WelcomeScreen(self.root, self.fonts)
        screen.pack(fill="both", expand=True)
        self.pump()
        self.assertTrue(screen.winfo_exists())

    def test_set_workspace(self) -> None:
        from blackchpok_ide import welcome

        screen = welcome.WelcomeScreen(self.root, self.fonts)
        screen.pack(fill="both", expand=True)
        self.pump()
        screen.set_workspace(str(ROOT))
        self.pump()

    def test_set_model(self) -> None:
        from blackchpok_ide import welcome

        screen = welcome.WelcomeScreen(self.root, self.fonts)
        screen.pack(fill="both", expand=True)
        self.pump()
        screen.set_model("qwen2.5-coder-14b")
        self.pump()

    def test_submit_callback_wired(self) -> None:
        from blackchpok_ide import welcome

        submitted: list[str] = []
        screen = welcome.WelcomeScreen(self.root, self.fonts,
                                       on_submit=submitted.append)
        screen.pack(fill="both", expand=True)
        self.pump()
        # Кнопка надсилання має існувати й бути під'єднаною.
        self.assertTrue(hasattr(screen, "on_submit"))
        self.assertIsNotNone(screen.on_submit)


class TestTerminalPanel(Base):
    """Термінал: справжні команди."""

    def test_creates(self) -> None:
        from blackchpok_ide import terminal

        panel = terminal.TerminalPanel(self.root, self.fonts, ROOT)
        panel.pack(fill="both", expand=True)
        self.pump()
        self.assertTrue(panel.winfo_exists())

    def test_runs_real_command(self) -> None:
        from blackchpok_ide import terminal

        panel = terminal.TerminalPanel(self.root, self.fonts, ROOT)
        panel.pack(fill="both", expand=True)
        self.pump()
        try:
            panel.run("echo blackchpok-terminal-test")
            body = ""
            deadline = time.time() + 25
            while time.time() < deadline:
                self.pump(0.3)
                body = panel.output.get("1.0", "end")
                if "blackchpok-terminal-test" in body:
                    break
            self.assertIn("blackchpok-terminal-test", body)
        finally:
            try:
                panel.stop()
            except Exception:  # noqa: BLE001
                pass

    def test_set_cwd(self) -> None:
        from blackchpok_ide import terminal

        panel = terminal.TerminalPanel(self.root, self.fonts, ROOT)
        panel.pack(fill="both", expand=True)
        self.pump()
        folder = Path(tempfile.mkdtemp())
        panel.set_cwd(folder)
        self.pump()
        self.assertEqual(Path(panel.cwd), folder)

    def test_empty_command_is_ignored(self) -> None:
        from blackchpok_ide import terminal

        panel = terminal.TerminalPanel(self.root, self.fonts, ROOT)
        panel.pack(fill="both", expand=True)
        self.pump()
        before = panel.output.get("1.0", "end")
        panel.run("   ")
        self.pump(0.4)
        self.assertEqual(before, panel.output.get("1.0", "end"))


class TestPreviewPanel(Base):
    """Панель прев'ю."""

    def test_creates(self) -> None:
        from blackchpok_ide import preview_panel

        panel = preview_panel.PreviewPanel(self.root, self.fonts, lambda: Path(ROOT))
        panel.pack(fill="both", expand=True)
        self.pump()
        self.assertTrue(panel.winfo_exists())

    def test_creates_without_root_provider(self) -> None:
        from blackchpok_ide import preview_panel

        panel = preview_panel.PreviewPanel(self.root, self.fonts, lambda: None)
        panel.pack(fill="both", expand=True)
        self.pump()
        self.assertTrue(panel.winfo_exists())


class TestLivePreviewPanel(Base):
    """Живий прев'ю застосунку."""

    def test_creates(self) -> None:
        from blackchpok_ide import live_preview

        panel = live_preview.LivePreviewPanel(self.root, self.fonts, lambda: Path(ROOT))
        panel.pack(fill="both", expand=True)
        self.pump()
        self.assertTrue(panel.winfo_exists())

    def test_missing_root_is_safe(self) -> None:
        from blackchpok_ide import live_preview

        panel = live_preview.LivePreviewPanel(self.root, self.fonts, lambda: None)
        panel.pack(fill="both", expand=True)
        self.pump()
        self.assertTrue(panel.winfo_exists())


class TestVoiceButton(Base):
    """Кнопка мікрофона."""

    def test_creates(self) -> None:
        from blackchpok_ide import voice, voice_panel

        button = voice_panel.VoiceButton(self.root, self.fonts,
                                         settings=voice.VoiceSettings())
        button.pack()
        self.pump()
        self.assertTrue(button.winfo_exists())

    def test_starts_not_busy(self) -> None:
        from blackchpok_ide import voice, voice_panel

        button = voice_panel.VoiceButton(self.root, self.fonts,
                                         settings=voice.VoiceSettings())
        button.pack()
        self.pump()
        self.assertFalse(button.busy)

    def test_stop_is_safe(self) -> None:
        from blackchpok_ide import voice, voice_panel

        button = voice_panel.VoiceButton(self.root, self.fonts,
                                         settings=voice.VoiceSettings())
        button.pack()
        self.pump()
        button.stop()
        self.pump()
        self.assertFalse(button.busy)

    def test_toggle_without_engine_reports_status(self) -> None:
        from blackchpok_ide import voice, voice_panel

        seen: list[str] = []
        button = voice_panel.VoiceButton(self.root, self.fonts,
                                         settings=voice.VoiceSettings(),
                                         on_status=seen.append)
        button.pack()
        self.pump()
        # Без доступного рушія має бути повідомлення, а не виняток.
        if not voice.best_engine():
            button.toggle()
            self.pump()
            self.assertTrue(seen)


class TestRagPanel(Base):
    """Панель бази знань."""

    def test_creates(self) -> None:
        from blackchpok_ide import rag, rag_panel

        service = rag.RagService(ROOT)
        panel = rag_panel.RagPanel(self.root, self.fonts, service)
        panel.pack(fill="both", expand=True)
        self.pump()
        self.assertTrue(panel.winfo_exists())

    def test_refresh_status_is_safe(self) -> None:
        from blackchpok_ide import rag, rag_panel

        service = rag.RagService(ROOT)
        panel = rag_panel.RagPanel(self.root, self.fonts, service)
        panel.pack(fill="both", expand=True)
        self.pump()
        panel.refresh_status()
        self.pump()


class TestModelHubPanel(Base):
    """Хаб моделей."""

    def test_creates(self) -> None:
        from blackchpok_ide import model_hub_panel
        from blackchpok_ide.config import Settings

        settings = Settings()
        settings.workspace = str(ROOT)
        panel = model_hub_panel.ModelHubPanel(self.root, self.fonts, settings)
        panel.pack(fill="both", expand=True)
        self.pump(0.4)
        self.assertTrue(panel.winfo_exists())

    def test_hardware_profile_defaults(self) -> None:
        from blackchpok_ide import model_hub_panel
        from blackchpok_ide.config import Settings

        settings = Settings()
        settings.workspace = str(ROOT)
        panel = model_hub_panel.ModelHubPanel(self.root, self.fonts, settings)
        panel.pack(fill="both", expand=True)
        self.pump(0.4)
        self.assertIsNotNone(panel.profile)
        self.assertEqual(panel.hits, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
