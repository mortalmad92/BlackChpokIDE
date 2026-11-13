"""Регресії, знайдені живим прогоном у справжньому вікні.

Три вади, які робили агента фактично неробочим:

1. поле введення з'їдало ПЕРШИЙ символ («привіт» → «ривіт»), бо
   очищення підказки-заповнювача видаляло весь текст;
2. «New Agent» не ховав стартовий екран, тож поле введення й стрічка
   нового чату лишались під оверлеєм;
3. сирий JSON виклику інструмента (`{"name": …}`, `<tools>…</tools>`)
   просочувався в чат замість відповіді.

Запуск: python -m unittest tests.test_agent_live_ux -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import llm_client  # noqa: E402
from blackchpok_ide.agent_tools import TOOL_SCHEMAS  # noqa: E402


class TestToolJsonNotShown(unittest.TestCase):
    """Виклик інструмента не має потрапляти в текст відповіді."""

    def setUp(self) -> None:
        self.names = {item["function"]["name"] for item in TOOL_SCHEMAS}

    def test_bare_json_call_is_detected(self) -> None:
        self.assertTrue(llm_client._looks_like_tool_json(
            '{"name": "list_dir", "arguments": {}}', self.names))

    def test_tools_tag_is_detected(self) -> None:
        # Саме цю обгортку дає qwen2.5-coder у llama.cpp.
        self.assertTrue(llm_client._looks_like_tool_json(
            '<tools>\n{"name": "read_file", "arguments": {"path": "main.py"}}\n</tools>',
            self.names))

    def test_tool_call_tag_is_detected(self) -> None:
        self.assertTrue(llm_client._looks_like_tool_json(
            '<tool_call>{"name": "list_dir"}</tool_call>', self.names))

    def test_normal_text_is_not_detected(self) -> None:
        for text in ("Ось файли в теці:", "Готово. Прочитав main.py.",
                     "```python\nx = 1\n```"):
            self.assertFalse(llm_client._looks_like_tool_json(text, self.names), text)

    def test_strip_removes_tools_tag(self) -> None:
        raw = 'Готово!\n<tools>\n{"name": "list_dir", "arguments": {}}\n</tools>'
        cleaned = llm_client.strip_tool_json(raw, TOOL_SCHEMAS)
        self.assertNotIn("<tools>", cleaned)
        self.assertNotIn('"name"', cleaned)
        self.assertIn("Готово!", cleaned)

    def test_extract_reads_tools_tag(self) -> None:
        calls = llm_client.extract_tool_calls(
            '<tools>\n{"name": "list_dir", "arguments": {"path": "."}}\n</tools>',
            TOOL_SCHEMAS)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "list_dir")


class TestPlaceholderKeepsTypedText(unittest.TestCase):
    """Підказка-заповнювач не має з'їдати перший символ."""

    @classmethod
    def setUpClass(cls) -> None:
        import tkinter as tk

        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError as exc:  # pragma: no cover - без дисплея
            raise unittest.SkipTest(f"tkinter недоступний: {exc}") from exc

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def test_clear_placeholder_removes_only_placeholder(self) -> None:
        import tkinter as tk

        box = tk.Text(self.root)
        placeholder = "Напиши задачу агенту…"

        # Повторюємо логіку ChatPanel._clear_placeholder без побудови панелі.
        state = {"on": True}

        def clear() -> None:
            if not state["on"]:
                return
            state["on"] = False
            current = box.get("1.0", "end-1c")
            if current.startswith(placeholder):
                box.delete("1.0", f"1.0+{len(placeholder)}c")

        box.insert("1.0", placeholder)
        # Користувач друкує перший символ — текст стає «підказка + символ».
        box.insert("end", "п")
        clear()
        self.assertEqual(box.get("1.0", "end-1c"), "п",
                         "перший набраний символ має лишитись")
        box.destroy()

    def test_source_has_no_wholesale_delete(self) -> None:
        source = (ROOT / "blackchpok_ide" / "chat_panel.py").read_text(encoding="utf-8")
        start = source.index("def _clear_placeholder")
        block = source[start:start + 900]
        self.assertNotIn('delete("1.0", "end")\n', block,
                         "очищення підказки не має стирати весь вміст")


class TestNewAgentHidesWelcome(unittest.TestCase):
    """«New Agent» має прибирати стартовий екран."""

    def test_new_chat_session_hides_welcome(self) -> None:
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE._start_chat_in)
        self.assertIn("_hide_welcome", source,
                      "новий чат має ховати оверлей, інакше поле введення недоступне")


class TestLocalModelAdoption(unittest.TestCase):
    """Модель на диску має ставати вибраною без ручних налаштувань."""

    def test_adoption_method_exists(self) -> None:
        from blackchpok_ide.main_window import BlackChpokIDE

        self.assertTrue(hasattr(BlackChpokIDE, "_adopt_local_model"))

    def test_adoption_called_on_startup(self) -> None:
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE._startup)
        self.assertIn("_adopt_local_model", source)


class TestThreadSafety(unittest.TestCase):
    """Фонові потоки не мають торкатися tkinter."""

    #: Методи Tk, заборонені поза головним потоком.
    TK_CALLS = {
        "after", "after_idle", "after_cancel", "update", "update_idletasks",
        "winfo_exists", "winfo_children", "winfo_ismapped", "configure",
        "grid", "pack", "place", "event_generate", "nametowidget",
    }

    def _thread_targets(self, tree) -> set[str]:
        """Імена методів, які запускаються як target= у Thread(...)."""
        import ast

        targets: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "attr", "") or getattr(func, "id", "")
            if name != "Thread":
                continue
            for kw in node.keywords:
                if kw.arg != "target":
                    continue
                if isinstance(kw.value, ast.Attribute):
                    targets.add(kw.value.attr)
                elif isinstance(kw.value, ast.Name):
                    targets.add(kw.value.id)
        return targets

    def test_no_tk_calls_from_background_threads(self) -> None:
        """Жоден фоновий потік не викликає tkinter напряму.

        Раніше ``voice_panel``, ``mcp_panel`` і ``chat_panel`` кликали
        ``self.after()`` з робочого потоку: у Release-збірці це падає з
        «main thread is not in main loop» і вбиває застосунок.
        """
        import ast

        pkg = ROOT / "blackchpok_ide"
        offenders: list[str] = []
        for path in sorted(pkg.glob("*.py")):
            source = path.read_text(encoding="utf-8", errors="replace")
            if "Thread(" not in source:
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            targets = self._thread_targets(tree)
            if not targets:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef):
                    continue
                if node.name not in targets:
                    continue
                for inner in ast.walk(node):
                    if not isinstance(inner, ast.Call):
                        continue
                    func = inner.func
                    if not isinstance(func, ast.Attribute):
                        continue
                    if not isinstance(func.value, ast.Name):
                        continue
                    if func.value.id == "self" and func.attr in self.TK_CALLS:
                        offenders.append(f"{path.name}:{inner.lineno} "
                                         f"{node.name}() → self.{func.attr}()")
        self.assertEqual(offenders, [],
                         "виклики tkinter із фонових потоків:\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main(verbosity=2)
