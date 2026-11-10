"""Тести меню моделі для чату: рівні зусилля й вибір моделі.

Запуск:  python tests/test_model_menu.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import effort  # noqa: E402

failures = 0
checked = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures, checked
    checked += 1
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


# ─────────────────────────────────────────────────────────────────────────────
# Рівні зусилля
# ─────────────────────────────────────────────────────────────────────────────

def test_efforts() -> None:
    labels = effort.labels()
    check("шість рівнів (включно з Deploy)", len(labels) == 6, str(labels))
    check("типовий перший", labels[0] == "За замовчуванням", labels[0])
    check("є «Ретельно»", "Ретельно" in labels)
    check("є «Максимум» для Deploy", "Максимум" in labels)
    check("є «Без міркувань»", "Без міркувань" in labels)

    check("типовий не додає полів", effort.payload_for("default") == {})
    low = effort.payload_for("low")
    check("низький рівень додає reasoning_effort", low.get("reasoning_effort") == "low")
    high = effort.payload_for("high")
    check("високий рівень — high", high.get("reasoning_effort") == "high")
    check("високий рівень має більший бюджет",
          high.get("thinking_budget", 0) > low.get("thinking_budget", 0),
          f"{high.get('thinking_budget')} > {low.get('thinking_budget')}")

    check("нормалізація невідомого", effort.normalise("асдфг") == "default")
    check("нормалізація відомого", effort.normalise("HIGH") == "high")
    check("підпис за ключем", effort.label_for("medium") == "Збалансовано")
    check("ключ за підписом", effort.key_for_label("Ретельно") == "high")
    check("опис не порожній", bool(effort.describe("high").strip()))

    check("старі назви моделей розпізнаються як reasoning",
          effort.is_reasoning_provider("deepseek")
          and effort.is_reasoning_provider("openai"))


def test_menu_rows() -> None:
    rows = effort.menu_rows("deepseek-reasoner", "high")
    check("два рядки меню", len(rows) == 2)
    check("перший рядок — модель",
          rows[0][0] == "Модель" and rows[0][1] == "deepseek-reasoner")
    check("другий — зусилля",
          rows[1][0] == "Зусилля" and rows[1][1] == "Ретельно")


# ─────────────────────────────────────────────────────────────────────────────
# Клієнт передає зусилля в API
# ─────────────────────────────────────────────────────────────────────────────

def test_client_effort() -> None:
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    seen: dict = {}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args) -> None:
            pass

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            seen["body"] = json.loads(self.rfile.read(length) or b"{}")
            payload = {"choices": [{"index": 0, "message": {
                "role": "assistant", "content": "ок"}}]}
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    from blackchpok_ide.llm_client import LLMClient

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        client = LLMClient(f"http://127.0.0.1:{port}/v1", "gpt-4o", "k",
                           timeout=5, reasoning_effort="high")
        client.chat([{"role": "user", "content": "тест"}])
        check("клієнт надсилає reasoning_effort",
              seen.get("body", {}).get("reasoning_effort") == "high",
              str(seen.get("body", {}).get("reasoning_effort")))

        client2 = LLMClient(f"http://127.0.0.1:{port}/v1", "gpt-4o", "k",
                            timeout=5, reasoning_effort="default")
        client2.chat([{"role": "user", "content": "тест"}])
        check("типовий рівень не надсилається",
              "reasoning_effort" not in seen.get("body", {}))

        client3 = LLMClient(f"http://127.0.0.1:{port}/v1", "deepseek-reasoner", "k",
                            timeout=5, reasoning_effort="high")
        client3.chat([{"role": "user", "content": "тест"}])
        body = seen.get("body", {})
        check("reasoning-модель без temperature", "temperature" not in body,
              str(sorted(body)))
    finally:
        server.shutdown()


# ─────────────────────────────────────────────────────────────────────────────
# Живе меню
# ─────────────────────────────────────────────────────────────────────────────

def test_live_menu() -> None:
    import tkinter as tk

    import tkinter.messagebox as mb
    import tkinter.simpledialog as sd

    mb.askyesno = lambda *a, **k: True
    mb.askyesnocancel = lambda *a, **k: True
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None
    sd.askstring = lambda *a, **k: None
    sd.askinteger = lambda *a, **k: None

    from blackchpok_ide import theme
    from blackchpok_ide.agent_tools import ToolRegistry
    from blackchpok_ide.chat_panel import ChatPanel
    from blackchpok_ide.config import Settings

    root = tk.Tk()
    root.geometry("700x700")
    fonts = theme.Theme(root)
    fonts.apply()
    picked: dict = {}
    panel = ChatPanel(root, fonts, Settings(), ToolRegistry(ROOT))
    panel.on_model_pick = lambda name: picked.__setitem__("model", name)
    panel.on_effort_pick = lambda key: picked.__setitem__("effort", key)
    panel.pack(fill="both", expand=True)

    def pump(seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            root.update()
            time.sleep(0.02)

    pump(0.4)

    check("кнопка моделі є", hasattr(panel, "model_button"))
    panel.set_chat_model("deepseek-reasoner", "default")
    pump(0.2)
    check("кнопка показує модель",
          "deepseek-reasoner" in panel.model_button.cget("text"),
          panel.model_button.cget("text"))

    panel.set_available_models(["deepseek-chat", "deepseek-reasoner", "gpt-4o"])
    panel.toggle_model_menu()
    pump(0.5)
    menu = panel._model_menu
    check("меню відкривається", menu is not None and menu.visible)
    check("головна картка має 2 рядки", len(menu._rows) == 2, str(len(menu._rows)))
    titles = [row.winfo_children()[0].cget("text") for row in menu._rows]
    check("рядки — Модель і Зусилля", titles == ["Модель", "Зусилля"], str(titles))

    menu.show_models()
    pump(0.3)
    check("список моделей показано", len(menu._rows) == 3, str(len(menu._rows)))
    menu._pick_model("gpt-4o")
    pump(0.3)
    check("модель обрано", picked.get("model") == "gpt-4o", str(picked))
    check("кнопка оновилась", "gpt-4o" in panel.model_button.cget("text"))

    menu.show_efforts()
    pump(0.3)
    check("список зусиль показано", len(menu._rows) == 6, str(len(menu._rows)))
    menu._pick_effort("high")
    pump(0.3)
    check("зусилля обрано", picked.get("effort") == "high", str(picked))
    check("кнопка показує зусилля",
          "ретельно" in panel.model_button.cget("text").lower(),
          panel.model_button.cget("text"))

    menu.close()
    pump(0.2)
    check("меню закривається", not menu.visible)

    root.destroy()


def test_chat_model_stored() -> None:
    """Модель зберігається за чатом, а не глобально."""
    from blackchpok_ide.chat_store import Chat

    chat = Chat(title="Чат A", model="deepseek-reasoner")
    chat.effort = "high"
    data = chat.to_dict()
    check("модель у словнику чату", data.get("model") == "deepseek-reasoner")
    check("зусилля у словнику чату", data.get("effort") == "high")

    restored = Chat.from_dict(data)
    check("модель відновлюється", restored.model == "deepseek-reasoner")
    check("зусилля відновлюється", restored.effort == "high")


def main() -> int:
    test_efforts()
    test_menu_rows()
    test_client_effort()
    test_live_menu()
    test_chat_model_stored()
    print()
    print(f"Перевірено тверджень: {checked}")
    print("Меню моделі:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


# ── unittest-обгортка (додано 10.11.2026) ──────────────────────────────────
# Для `python -m unittest discover` ці перевірки раніше були невидимі:
# файл — скрипт із власним main(), а не TestCase. Тепер discover запускає
# його й падає, якщо main() повернув ненульовий код. Запуск як скрипт
# (`python tests/test_model_menu.py`) поводиться як раніше.
import unittest as _unittest  # noqa: E402


class _ScriptSuite(_unittest.TestCase):
    def test_script_passes(self) -> None:
        code = main()
        self.assertEqual(code, 0, f"main() повернув {code}")
