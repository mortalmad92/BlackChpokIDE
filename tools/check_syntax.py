"""Швидка перевірка синтаксису змінених модулів."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FILES = [
    "blackchpok_ide/agent.py",
    "blackchpok_ide/tool_lazy.py",
    "blackchpok_ide/server_state.py",
    "blackchpok_ide/work_log.py",
    "blackchpok_ide/imaging.py",
    "blackchpok_ide/context_panel.py",
    "blackchpok_ide/main_window.py",
    "blackchpok_ide/mcp_client.py",
    "blackchpok_ide/config.py",
    "blackchpok_ide/model_hub.py",
    "blackchpok_ide/native/manager.py",
]

for name in FILES:
    path = ROOT / name
    text = path.read_text(encoding="utf-8")
    ast.parse(text)
    print(f"{len(text.splitlines()):5d} lines  {name}")
print("Усі модулі синтаксично коректні.")
