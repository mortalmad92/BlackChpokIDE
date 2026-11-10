"""Діагностика нативного tool calling обраної моделі.

Питання, на яке відповідає скрипт: чи модель повертає СТРУКТУРОВАНИЙ
``tool_calls``, чи лише пише назву інструмента текстом? Від цього залежить,
чи потрібен тексто-text протокол (:func:`model_profile.text_tool_protocol`)
і чи агент узагалі може виконати правку.

Запуск: python tools/check_native_tools.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

BASE = "http://127.0.0.1:8080/v1"
API_KEY = "local"
MODEL = "qwen25vl3b"


def main() -> int:
    from blackchpok_ide.agent_tools import TOOL_SCHEMAS
    from blackchpok_ide.llm_client import LLMClient

    client = LLMClient(BASE, MODEL, API_KEY, timeout=180)
    tools = [item for item in TOOL_SCHEMAS
             if item["function"]["name"] in ("edit_file", "read_file",
                                             "write_file")]
    prompt = (
        "Файл calc.py містить:\n"
        "1 | def add(a, b):\n"
        "2 |     return a - b\n"
        "Треба замінити 'return a - b' на 'return a + b'. "
        "Виклич інструмент edit_file зі шляхом calc.py."
    )
    result = client.chat([{"role": "user", "content": prompt}],
                         tools=tools, tool_choice="auto")
    print("MODEL:", MODEL)
    print("CONTENT:", repr((result.content or "")[:300]))
    calls = result.tool_calls or []
    print("TOOL_CALLS:", [(call["function"]["name"],
                           call["function"]["arguments"]) for call in calls])

    # Той самий запит БЕЗ нативних схем: перевіряємо текстовий протокол.
    result2 = client.chat([{"role": "user", "content": prompt + (
        "\n\nВідповідай РІВНО одним JSON-об'єктом вигляду "
        '{"name": "edit_file", "arguments": {...}}')}], tools=None)
    print("TEXT ONLY:", repr((result2.content or "")[:300]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
