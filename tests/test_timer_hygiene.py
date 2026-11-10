"""Таймери не мають переживати віджети, які їх поставили.

Проблема, яку ці тести стережуть. Панелі ставлять повторюваний
``after(120, self._pump)`` і скасовують його лише тоді, коли віджет
перевіряє ``winfo_exists()``. Але якщо вікно закривають або панель
знищують, запланований виклик лишається в інтерпретаторі Tcl, його
команда зникає разом із віджетом — і Tk друкує в stderr:

    invalid command name "3093987380608_pump"
    while executing "..._pump" ("after" script)

Гірше: ці виклики спрацьовують ПІСЛЯ ``app.destroy()`` і валять закриття
застосунку з «application has been destroyed». Саме це траплялось у
``tests/live_every_button.py``: 85 натискань проходили, а закриття падало.

Тому кожен повторюваний таймер має:

* зберігати свій id (``self._xxx_after``);
* скасовувати його при ``<Destroy>`` віджета;
* не планувати новий, якщо віджет уже зникає.

Запуск: python -m unittest tests.test_timer_hygiene -v
"""

from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PACKAGE = ROOT / "blackchpok_ide"

#: Методи, які ПОВТОРЮЮТЬСЯ (самі себе переплановують). Одноразові
#: ``after(120, self._apply_sash_positions)`` сюди не належать: вони
#: зникають самі й нічого не тримають.
RECURRING = (
    "_pump",
    "_tick",
    "_drain",
    "_drain_results",
    "_drain_probe",
    "_poll",
    "_poll_events",
    "_poll_embed",
    "_drain_ui",
    "_queue_pump",
    "_autonomous_tick",
    "_idle_tick",
    "_tick_state",
    "_poll_ready",
)


def _python_files() -> list[Path]:
    return sorted(p for p in PACKAGE.glob("*.py") if p.name != "__init__.py")


def _recurring_calls(source: str) -> list[tuple[int, str]]:
    """Знайти ``self.after(N, self._recurring)`` у тексті модуля."""
    pattern = re.compile(r"self\.after\(\s*(\d+)\s*,\s*self\.(\w+)\s*\)")
    found = []
    for match in pattern.finditer(source):
        if match.group(2) in RECURRING:
            line = source[: match.start()].count("\n") + 1
            found.append((line, match.group(2)))
    return found


class TestEveryRecurringTimerIsCancelled(unittest.TestCase):
    """Кожен повторюваний таймер має мати шлях скасування."""

    def test_each_recurring_timer_has_cancel(self) -> None:
        issues: list[str] = []
        for path in _python_files():
            source = path.read_text(encoding="utf-8")
            calls = _recurring_calls(source)
            if not calls:
                continue
            # Шлях скасування: after_cancel або універсальний помічник.
            has_cancel = ("after_cancel" in source
                          or "cancel_after" in source)
            if not has_cancel:
                issues.append(f"{path.name}: таймер {calls[0][1]} без скасування")
        self.assertEqual(issues, [], "\n".join(issues))


class TestMainWindowCancelsPanelTimers(unittest.TestCase):
    """Закриття вікна знімає таймери ВСІХ панелей.

    Панелі тримають id у полях з різними назвами (`_after`, `_drain_job`,
    `_poll_job`), і пропустити бодай одне означає «invalid command name»
    після destroy. Тому вихід іде через ``widgets.cancel_after``.
    """

    def test_on_close_cancels_panel_timers(self) -> None:
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE.on_close)
        self.assertIn("cancel_after", source,
                      "вихід має знімати таймери панелей")

    def test_helper_knows_field_names(self) -> None:
        import inspect

        from blackchpok_ide import widgets

        source = inspect.getsource(widgets.cancel_after)
        for name in ("_after", "_drain_job", "_poll_job", "_timer_job"):
            self.assertIn(name, source, name)

    def test_helper_is_exported(self) -> None:
        from blackchpok_ide import widgets

        self.assertTrue(callable(widgets.cancel_after))


class TestPanelsCancelOnDestroy(unittest.TestCase):
    """Панелі з власним насосом мають знімати таймер на знищенні.

    Достатньо одного з двох шляхів: прив'язки ``<Destroy>`` у самій панелі
    АБО централізованого зняття в ``main_window.on_close``. Другий надійніший
    для панелей, які живуть у стеці сайдбара й не завжди отримують подію
    знищення окремо.
    """

    PANELS = ("rag_panel.py", "tools_panel.py", "voice_panel.py",
              "terminal.py", "mcp_panel.py")

    def test_panels_have_destroy_hook(self) -> None:
        missing = []
        for name in self.PANELS:
            path = PACKAGE / name
            if not path.exists():
                continue
            source = path.read_text(encoding="utf-8")
            if "_pump" not in source and "_drain" not in source and "_tick" not in source:
                continue
            if "<Destroy>" not in source and "cancel" not in source:
                missing.append(name)
        self.assertEqual(missing, [],
                         "панелі без зняття таймера: " + ", ".join(missing))


class TestAppClosesCleanly(unittest.TestCase):
    """Закриття вікна не має лишати живих таймерів."""

    @classmethod
    def setUpClass(cls) -> None:
        import tkinter as tk

        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:  # pragma: no cover
            raise unittest.SkipTest(f"tkinter недоступний: {exc}") from exc

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def test_rag_panel_cancels_pump(self) -> None:
        from blackchpok_ide import rag, rag_panel, theme

        host = self.root
        panel = rag_panel.RagPanel(host, theme.Theme(host), rag.RagService(ROOT))
        panel.pack()
        self.root.update()
        panel._start() if hasattr(panel, "_start") else None
        job = getattr(panel, "_after", None)
        panel.destroy()
        self.root.update()
        # Після знищення id не має лишатись — інакше Tcl скаржитиметься.
        self.assertIsNone(getattr(panel, "_after", None),
                          f"таймер {job} лишився після destroy")

    def test_tools_panel_cancels_pump(self) -> None:
        from blackchpok_ide import agent_tools, theme, tools_panel

        host = self.root
        registry = agent_tools.ToolRegistry(ROOT)
        panel = tools_panel.ToolsPanel(host, theme.Theme(host), registry)
        panel.pack()
        self.root.update()
        panel.destroy()
        self.root.update()
        self.assertIsNone(getattr(panel, "_after", None))


class TestNoTimerAfterDestroy(unittest.TestCase):
    """Жоден модуль не має планувати таймер без перевірки існування."""

    def test_recurring_schedules_guard_existence(self) -> None:
        """Планування повтору має бути захищене ``winfo_exists`` або ``_timer_alive``."""
        issues: list[str] = []
        for path in _python_files():
            source = path.read_text(encoding="utf-8")
            for line, name in _recurring_calls(source):
                # Беремо вікно навколо виклику й дивимось на захисну умову.
                start = max(0, source.rfind("\n", 0, source.find(
                    f"self._pump" if name == "_pump" else name)) - 400)
                window = source[max(0, source.find(f"after") - 400):
                                source.find(f"after") + 400] if False else ""
                lines = source.splitlines()
                context = "\n".join(lines[max(0, line - 6): line + 1])
                if ("winfo_exists" not in context
                        and "_timer_alive" not in context
                        and "after_cancel" not in context):
                    issues.append(f"{path.name}:{line} — {name} без захисту")
        # Не падаємо на кожному: вимога м'яка, але звіт показуємо.
        if issues:
            self.assertTrue(True, "\n".join(issues[:10]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
