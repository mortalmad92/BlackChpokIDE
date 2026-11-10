"""Р“РѕР»РѕРІРЅРµ РІС–РєРЅРѕ BlackChpok IDE Сѓ СЃС‚РёР»С– СЃСѓС‡Р°СЃРЅРѕРіРѕ Р°РіРµРЅС‚РЅРѕРіРѕ СЂРµРґР°РєС‚РѕСЂР°.

Р РѕР·РєР»Р°РґРєР° РїРѕРІС‚РѕСЂСЋС” РґРёР·Р°Р№РЅ, РґРѕ СЏРєРѕРіРѕ РјРё РїСЂР°РіРЅРµРјРѕ:

    в”Њв”Ђв”Ђв”Ђв”Ђв”¬в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”¬в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”¬в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”ђ
    в”‚    в”‚  Р±С–С‡РЅР° РїР°РЅРµР»СЊ  в”‚   СЂРµРґР°РєС‚РѕСЂ / РЅРёР¶РЅСЏ      в”‚  Р°РіРµРЅС‚        в”‚
    в”‚СЂРµР№Рєв”‚  (РїСЂРѕРІС–РґРЅРёРє,   в”‚   РїР°РЅРµР»СЊ (С‚РµСЂРјС–РЅР°Р»,     в”‚  (С‡Р°С‚)        в”‚
    в”‚    в”‚  СЃРєС–Р»Рё, С‡РµСЂРіР°) в”‚   РїРѕС€СѓРє, С…Р°Р±, MCP)      в”‚  + РєРѕРЅС‚РµРєСЃС‚   в”‚
    в””в”Ђв”Ђв”Ђв”Ђв”ґв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”ґв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”ґв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”

РЈСЃРµ, С‰Рѕ РЅР°С‚РёСЃРєР°С”С‚СЊСЃСЏ, СЃРїСЂР°РІРґС– РїСЂР°С†СЋС”: РєРЅРѕРїРєРё СЂРµР№РєРё РїРµСЂРµРјРёРєР°СЋС‚СЊ РїР°РЅРµР»С–,
РІРєР»Р°РґРєРё Р·Р°РєСЂРёРІР°СЋС‚СЊСЃСЏ С…СЂРµСЃС‚РёРєРѕРј, С‚РµСЂРјС–РЅР°Р» С‚СЂРёРјР°С” Р¶РёРІСѓ СЃРµСЃС–СЋ, Р° С‡РµСЂРіР° Р·Р°РґР°С‡
РІРёРєРѕРЅСѓС”С‚СЊСЃСЏ С‚РёРј СЃР°РјРёРј Р°РіРµРЅС‚РѕРј, С‰Рѕ Р№ С‡Р°С‚.
"""

from __future__ import annotations

import atexit
import logging
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

from . import (
    adaptive,
    app_control,
    auto_setup,
    autonomous,
    autonomous_panel,
    browser_panel,
    cases_panel,
    changes_panel,
    chat_list_panel,
    chat_mode_menu,
    chat_store,
    commands,    context_panel,
    command_registry,
    conversation,
    deep_mode,
    diff_stats,
    header_bar,
    layout_profiles,
    mcp_client,
    mcp_panel,
    mcp_watch,
    cloud_agents,
    effort,
    layout,
    memory_bridge,
    modes,
    modes_menu,
    model_selector,
    nav_sidebar,
    permissions,
    planner,
    power,
    project_gate,
    providers,
    pulse,
    rag,
    rag_panel,
    safe,
    server_state,
    session_header,
    task_plan,
    tools_panel,
    queue_engine,
    trace_store,
    voice,
    queue_panel,
    shell_session,
    skills as skills_module,
    skills_panel,
    task_center,
    task_executor,
    task_planner,
    theme,
    welcome,
    widgets,
    workspace as ws,
    workspace_menu,
)
from .agent import AgentRunner
from .agent_tools import ToolRegistry
from . import agent_tools
from .app_control import AppController
from .chat_panel import ChatPanel
from .config import APP_NAME, APP_VERSION, Settings, load_session, save_session
from . import model_hub as hub
from . import hardware
from . import runtime
from .editor import CodeEditor
from .file_tree import FileTree
from .first_run import FirstRunWizard
from .model_hub_panel import ModelHubPanel
from . import neuromesh_panel, runtime_panel
from .native import api as native_api
from .native import bridge as native_bridge
from .outline_panel import OutlinePanel
from .palette import Palette, ProjectSearch, SearchDialog
from .preview_panel import PreviewPanel
from .live_preview import LivePreviewPanel
from .settings_dialog import SettingsDialog
from .tabs import EditorTabs
from .terminal import TerminalPanel

WELCOME_TEXT = """# BlackChpok IDE
Р›РѕРєР°Р»СЊРЅР° IDE Р· Р°РіРµРЅС‚РѕРј Сѓ СЃС‚РёР»С– СЃСѓС‡Р°СЃРЅРѕРіРѕ Р°РіРµРЅС‚РЅРѕРіРѕ СЂРµРґР°РєС‚РѕСЂР°.

## Р— С‡РѕРіРѕ РїРѕС‡Р°С‚Рё

1. Р’С–РґРєСЂРёР№ С‚РµРєСѓ РїСЂРѕС”РєС‚Сѓ: **Р¤Р°Р№Р» в†’ Р’С–РґРєСЂРёС‚Рё РїР°РїРєСѓ**.
2. РџС–РґРєР»СЋС‡Рё РјРѕРґРµР»СЊ: **Р’РёРіР»СЏРґ в†’ РҐР°Р± РјРѕРґРµР»РµР№** (`Ctrl+Shift+M`). IDE РІРёР·РЅР°С‡РёС‚СЊ
   Р·Р°Р»С–Р·Рѕ, РїС–РґР±РµСЂРµ РјРѕРґРµР»СЊ, РїРѕСЃС‚Р°РІРёС‚СЊ СЂСѓС€С–Р№ llama.cpp С– РїС–РґРєР»СЋС‡РёС‚СЊ СѓСЃРµ СЃР°РјР°.
   РњРѕР¶РЅР° РІРєР°Р·Р°С‚Рё Р№ Р±СѓРґСЊ-СЏРєРёР№ OpenAI-СЃСѓРјС–СЃРЅРёР№ СЃРµСЂРІРµСЂ (LM Studio, Ollama).
3. РќР°РїРёС€Рё Р·Р°РґР°С‡Сѓ РІ С‡Р°С‚С– РїСЂР°РІРѕСЂСѓС‡. РђРіРµРЅС‚ СЃР°Рј РїСЂРѕС‡РёС‚Р°С” С„Р°Р№Р»Рё, РІРЅРµСЃРµ Р·РјС–РЅРё Р№
   Р·Р°РїСѓСЃС‚РёС‚СЊ РїРµСЂРµРІС–СЂРєРё.

## Р©Рѕ С” РІ РѕР±РѕР»РѕРЅС†С–

- **Р§РµСЂРіР° Р·Р°РІРґР°РЅСЊ** вЂ” СЃРєР»Р°РґР°Р№ Р·Р°РґР°С‡С– СЃРїРёСЃРєРѕРј, Р°РіРµРЅС‚ РІРёРєРѕРЅСѓС” С—С… РѕРґРЅСѓ Р·Р° РѕРґРЅРѕСЋ.
- **РЎРєС–Р»Рё** вЂ” С‚РµРєР° `.agents/skills/<РЅР°Р·РІР°>/SKILL.md` Р· С–РЅСЃС‚СЂСѓРєС†С–С”СЋ РґР»СЏ Р°РіРµРЅС‚Р°.
- **MCP-СЃРµСЂРІРµСЂРё** вЂ” С–РЅСЃС‚СЂСѓРјРµРЅС‚Рё С–Р· Р·РѕРІРЅС–С€РЅС–С… РїСЂРѕС†РµСЃС–РІ (`.mcp.json` Сѓ РїСЂРѕС”РєС‚С–).
- **Р’Р±СѓРґРѕРІР°РЅРёР№ С‚РµСЂРјС–РЅР°Р»** вЂ” Р¶РёРІР° СЃРµСЃС–СЏ cmd.exe: `cd`, Р·РјС–РЅРЅС– Р№ venv Р·Р±РµСЂС–РіР°СЋС‚СЊСЃСЏ.

## Р“Р°СЂСЏС‡С– РєР»Р°РІС–С€С–

| РљР»Р°РІС–С€С– | Р”С–СЏ |
| --- | --- |
| `Ctrl+P` | С€РІРёРґРєРµ РІС–РґРєСЂРёС‚С‚СЏ С„Р°Р№Р»Сѓ |
| `Ctrl+Shift+P` | РїР°Р»С–С‚СЂР° РєРѕРјР°РЅРґ |
| `Ctrl+Shift+M` | С…Р°Р± РјРѕРґРµР»РµР№ |
| `Ctrl+F` / `Ctrl+Shift+F` | РїРѕС€СѓРє Сѓ С„Р°Р№Р»С– / Сѓ РїСЂРѕС”РєС‚С– |
| `Ctrl+S` / `Ctrl+W` | Р·Р±РµСЂРµРіС‚Рё / Р·Р°РєСЂРёС‚Рё РІРєР»Р°РґРєСѓ |
| `Ctrl+B` / `Ctrl+Alt+B` / `Ctrl+`` ` | РїСЂРѕРІС–РґРЅРёРє / Р°РіРµРЅС‚ / С‚РµСЂРјС–РЅР°Р» |
| `Ctrl+Alt+K` / `Ctrl+Alt+Q` | СЃРєС–Р»Рё / С‡РµСЂРіР° Р·Р°РІРґР°РЅСЊ |
| `F5` / `Ctrl+F5` | Р·Р°РїСѓСЃС‚РёС‚Рё С„Р°Р№Р» / С‚РµСЃС‚Рё |
"""

LOG = logging.getLogger("blackchpok.ui")

#: РџСЂРµС„С–РєСЃ РїРѕРІС–РґРѕРјР»РµРЅРЅСЏ РїСЂРѕ Р·Р±С–Р№ Р’Р›РђРЎРќРћР“Рћ СЂСѓС€С–СЏ.
#:
#: РџРѕС‚СЂС–Р±РµРЅ, С‰РѕР± РІС–РґСЂС–Р·РЅРёС‚Рё РїРѕРјРёР»РєСѓ РІС–Рґ СѓСЃРїС–С…Сѓ: ``_autostart_native_model``
#: РїРѕРІРµСЂС‚Р°С” Р РЇР”РћРљ РІ РѕР±РѕС… РІРёРїР°РґРєР°С… (СѓСЃРїС–С… вЂ” В«РІР»Р°СЃРЅРёР№ СЂСѓС€С–Р№: РЅР°Р·РІР° В· ctxвЂ¦В»),
#: С– Р±РµР· РѕРєСЂРµРјРѕРіРѕ РјР°СЂРєРµСЂР° С‚РµРєСЃС‚ РїРѕРјРёР»РєРё РІРёРіР»СЏРґР°РІ СЏРє СѓСЃРїС–С€РЅРёР№ СЂРµР·СѓР»СЊС‚Р°С‚ вЂ”
#: С„РѕР»Р±РµРє РЅР° llama-server РЅРµ Р·Р°РїСѓСЃРєР°РІСЃСЏ РІР·Р°РіР°Р»С–.
NATIVE_FAILURE_PREFIX = "вњ— РІР»Р°СЃРЅРёР№ СЂСѓС€С–Р№: "


class _Point:
    """РњС–РЅС–РјР°Р»СЊРЅР° В«РїРѕРґС–СЏВ» Р· РєРѕРѕСЂРґРёРЅР°С‚Р°РјРё РґР»СЏ ``context_menu``.

    ``widgets.context_menu`` С‡РёС‚Р°С” Р»РёС€Рµ ``x_root``/``y_root``. РџРµСЂРµРґР°РІР°С‚Рё
    СЃРїСЂР°РІР¶РЅСЋ РїРѕРґС–СЋ С‚СѓС‚ РЅРµ РјРѕР¶РЅР° (РјРµРЅСЋ РІС–РґРєСЂРёРІР°С” РєРЅРѕРїРєР°, Р° РЅРµ РјРёС€РєР°), С‚РѕРјСѓ
    РІРёРєРѕСЂРёСЃС‚РѕРІСѓС”РјРѕ С†РµР№ РїСЂРѕСЃС‚РёР№ РЅРѕСЃС–Р№ РєРѕРѕСЂРґРёРЅР°С‚.
    """

    __slots__ = ("x_root", "y_root")

    def __init__(self, x: int, y: int) -> None:
        self.x_root = int(x)
        self.y_root = int(y)

#: РљСѓРґРё РІРµРґРµ РєРѕР¶РµРЅ СЂРѕР·РґС–Р» РЅР°РІС–РіР°С†С–С—: РєР»СЋС‡ СЂРѕР·РґС–Р»Сѓ в†’ РїР°РЅРµР»СЊ Р±С–С‡РЅРѕС— РєРѕР»РѕРЅРєРё.
#: ``None`` РѕР·РЅР°С‡Р°С” В«С†Рµ РѕРєСЂРµРјР° РґС–СЏ, Р° РЅРµ РїР°РЅРµР»СЊВ» (РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏ).
#:
#: В«Р§Р°С‚РёВ» Р№ В«РђРіРµРЅС‚РёВ» вЂ” РѕРґРёРЅ СЂРѕР·РґС–Р»: РєРѕР¶РЅР° СЂРѕР·РјРѕРІР° С– С” СЃРµСЃС–СЏ Р°РіРµРЅС‚Р°, С‚РѕР¶
#: РѕРєСЂРµРјС– РїСѓРЅРєС‚Рё РјРµРЅСЋ Р»РёС€Рµ Р·РјСѓС€СѓРІР°Р»Рё РїРµСЂРµРјРёРєР°С‚РёСЃСЊ РјС–Р¶ РґРІРѕРјР° СЃРїРёСЃРєР°РјРё С‚РѕРіРѕ
#: СЃР°РјРѕРіРѕ. РўРµРїРµСЂ С†Рµ ``chats`` (С”РґРёРЅР° РїР°РЅРµР»СЊ СЃРµСЃС–Р№).
SECTION_PANELS: dict[str, str] = {
    "chats": "chats",
    "mcp": "mcp",
    "projects": "explorer",
    "knowledge": "rag",
    "runtime": "runtime",
    "neuromesh": "neuromesh",
}

#: РџР°РЅРµР»СЊ в†’ СЂРѕР·РґС–Р» РЅР°РІС–РіР°С†С–С—, РґРѕ СЏРєРѕРіРѕ РІРѕРЅР° РЅР°Р»РµР¶РёС‚СЊ (РґР»СЏ РїС–РґСЃРІС–С‚РєРё).
#: В«РђРІС‚РѕРЅРѕРјРЅРёР№В», С‡РµСЂРіР° Р№ СЃРєС–Р»Рё РЅР°Р»РµР¶Р°С‚СЊ С‡Р°С‚Сѓ: РІРѕРЅРё РїСЂРёРІ'СЏР·Р°РЅС– РґРѕ СЃРµСЃС–С— Р№
#: РїСЂРѕС”РєС‚Сѓ, Р° РЅРµ РґРѕ РІСЃСЊРѕРіРѕ Р·Р°СЃС‚РѕСЃСѓРЅРєСѓ (РґРёРІ. ``chat_mode_menu``).
PANEL_SECTIONS: dict[str, str] = {
    "chats": "chats",
    "cases": "chats",          # В«РЎРїСЂР°РІРёВ» вЂ” С†Рµ Р¶РёРІС– РєСЂРѕРєРё С‚С–С”С— Р¶ СЃРµСЃС–С—
    "autonomous": "chats",
    "queue": "chats",
    "skills": "chats",
    "mcp": "mcp",
    "tools": "mcp",
    "explorer": "projects",
    "search": "projects",
    "changes": "projects",
    "outline": "projects",
    "rag": "knowledge",
    "runtime": "runtime",
    "neuromesh": "neuromesh",
}

#: Р—Р°РіРѕР»РѕРІРєРё РїР°РЅРµР»РµР№ Р±С–С‡РЅРѕС— РєРѕР»РѕРЅРєРё (С‰РѕР± РєРѕСЂРёСЃС‚СѓРІР°С‡ Р±Р°С‡РёРІ, РґРµ РІС–РЅ).
PANEL_TITLES: dict[str, str] = {
    "chats": "Р§Р°С‚Рё Р№ Р°РіРµРЅС‚Рё",
    "cases": "РљСЂРѕРєРё Р°РіРµРЅС‚Р°",
    "autonomous": "РђРІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј",
    "queue": "Р§РµСЂРіР° Р·Р°РІРґР°РЅСЊ",
    "skills": "РЎРєС–Р»Рё Р°РіРµРЅС‚Р°",
    "mcp": "MCP-СЃРµСЂРІРµСЂРё",
    "tools": "Р†РЅСЃС‚СЂСѓРјРµРЅС‚Рё",
    "explorer": "Р¤Р°Р№Р»Рё РїСЂРѕС”РєС‚Сѓ",
    "changes": "Р—РјС–РЅРё Сѓ С„Р°Р№Р»Р°С…",
    "outline": "РЎС‚СЂСѓРєС‚СѓСЂР° С„Р°Р№Р»Сѓ",
    "rag": "Р‘Р°Р·Р° Р·РЅР°РЅСЊ",
    "runtime": "AI Runtime",
    "neuromesh": "NEUROMESH РџР°Рј'СЏС‚СЊ",
}


def _plan_text_for(task) -> str:
    """РљРѕСЂРѕС‚РєРёР№ РѕРїРёСЃ Р·Р°РґР°С‡С– Р»СЋРґСЃСЊРєРѕСЋ РјРѕРІРѕСЋ РґР»СЏ РїР»Р°РЅСѓ Р°РІС‚РѕРЅРѕРјРЅРѕРіРѕ СЂРµР¶РёРјСѓ."""
    who = "С‚РІРѕСЏ Р·Р°РґР°С‡Р°" if getattr(task, "from_user", False) else "РїРѕРєСЂР°С‰РµРЅРЅСЏ"
    text = " ".join(str(getattr(task, "text", "") or "").split())
    if len(text) > 110:
        text = text[:109] + "вЂ¦"
    return f"{who}: {text}"


def task_planner_available(settings: Settings) -> bool:
    """Р§Рё С” РЅР°Р»Р°С€С‚РѕРІР°РЅР° РјРѕРґРµР»СЊ, СЏРєС–Р№ РјРѕР¶РЅР° РґРѕСЂСѓС‡РёС‚Рё РїР»Р°РЅСѓРІР°РЅРЅСЏ.

    РџРµСЂРµРІС–СЂСЏС”РјРѕ Р»РёС€Рµ Р·Р°РїРѕРІРЅРµРЅС–СЃС‚СЊ РЅР°Р»Р°С€С‚СѓРІР°РЅСЊ, Р±РµР· РјРµСЂРµР¶С–: СЃР°Рј Р·Р°РїРёС‚ РґРѕ
    РјРѕРґРµР»С– РѕРґРЅР°РєРѕРІРѕ РїРѕРєР°Р¶Рµ РїРѕРјРёР»РєСѓ, СЏРєС‰Рѕ СЃРµСЂРІРµСЂ РЅРµ РїС–РґРЅСЏС‚РёР№. Р¦СЏ РїРµСЂРµРІС–СЂРєР°
    РїРѕС‚СЂС–Р±РЅР°, С‰РѕР± РЅРµ СЃС‚Р°РІРёС‚Рё РІ С‡РµСЂРіСѓ В«РєСЂРѕРєВ» Р±РµР· РјРѕРґРµР»С– Р№ РЅРµ РІРґР°РІР°С‚Рё, С‰Рѕ
    РїР»Р°РЅ С–СЃРЅСѓС”.
    """
    try:
        return bool(str(getattr(settings.llm, "model", "") or "").strip())
    except AttributeError:
        return False


class BlackChpokIDE(tk.Tk):
    """Р’С–РєРЅРѕ Р·Р°СЃС‚РѕСЃСѓРЅРєСѓ: Р·Р±РёСЂР°С” РІСЃС– РїР°РЅРµР»С– СЂР°Р·РѕРј."""

    #: РЎРєС–Р»СЊРєРё СЃРµРєСѓРЅРґ РєСЂРѕРє РјРѕР¶Рµ Р»РёС€Р°С‚РёСЃСЏ В«Р°РєС‚РёРІРЅРёРјВ» Р±РµР· СЂРѕР±РѕС‚Рё Р°РіРµРЅС‚Р°,
    #: РїРµСЂС€ РЅС–Р¶ РІРІР°Р¶Р°С‚Рё Р№РѕРіРѕ Р·Р°РІРёСЃР»РёРј С– РїРѕРІРµСЂРЅСѓС‚Рё РІ С‡РµСЂРіСѓ.
    #:
    #: Р§РёСЃР»Рѕ РЅРµ РјР°Р»Рµ РЅР°РІРјРёСЃРЅРѕ: РјС–Р¶ РїРѕР·РЅР°С‡РµРЅРЅСЏРј РєСЂРѕРєСѓ Р№ СЃС‚Р°СЂС‚РѕРј РїРѕС‚РѕРєСѓ
    #: Р°РіРµРЅС‚Р° РјРёРЅР°С” РєС–Р»СЊРєР° С‚С–РєС–РІ, С– РјРёС‚С‚С”РІР° РїРµСЂРµРІС–СЂРєР° РїРѕРІРµСЂС‚Р°Р»Р° РєСЂРѕРє Сѓ
    #: С‡РµСЂРіСѓ РїСЂСЏРјРѕ РїС–Рґ С‡Р°СЃ СЂРѕР±РѕС‚Рё.
    STALE_STEP_SECONDS = 25.0

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.session = load_session()
        self.title(f"{APP_NAME} {APP_VERSION}")
        # РќР° РІРµСЃСЊ РµРєСЂР°РЅ Р·Р° Р·Р°РјРѕРІС‡СѓРІР°РЅРЅСЏРј: Р°РіРµРЅС‚РЅР° IDE РјР°С” Р±Р°РіР°С‚Рѕ РєРѕР»РѕРЅРѕРє,
        # С– РЅР° РјР°Р»РµРЅСЊРєРѕРјСѓ РІС–РєРЅС– РґС–Р°Р»РѕРі СЃС‚Р°С” РІСѓР·СЊРєРѕСЋ СЃРјСѓР¶РєРѕСЋ. Р РѕР·РјС–СЂ РІС–РєРЅР°
        # Р·Р°РїР°Рј'СЏС‚РѕРІСѓС”С‚СЊСЃСЏ РјС–Р¶ Р·Р°РїСѓСЃРєР°РјРё, С‚РѕР¶ РєРѕСЂРёСЃС‚СѓРІР°С‡ РјРѕР¶Рµ Р·РјС–РЅРёС‚Рё Р№РѕРіРѕ
        # РјРёС€РєРѕСЋ, С– РЅР°СЃС‚СѓРїРЅРёР№ Р·Р°РїСѓСЃРє РІС–РґРєСЂРёС”С‚СЊСЃСЏ С‚Р°Рє СЃР°РјРѕ.
        self.minsize(1020, 640)
        self._apply_start_geometry()
        self._apply_icon()

        self.theme = theme.Theme(self, settings.ui.font_family, settings.ui.font_size)
        # РўРµРјР° Р· РЅР°Р»Р°С€С‚СѓРІР°РЅСЊ (С‚РёРїРѕРІРѕ С‚РµРјРЅР°) РґС–С” РѕРґСЂР°Р·Сѓ вЂ” РґРѕ РїРѕР±СѓРґРѕРІРё РІС–РґР¶РµС‚С–РІ,
        # С‚РѕР¶ Р¶РѕРґРЅРѕРіРѕ В«СЃРІС–С‚Р»РѕРіРѕ СЃРїР°Р»Р°С…СѓВ» РїСЂРё СЃС‚Р°СЂС‚С–.
        theme.set_mode(getattr(settings.ui, "theme", theme.DEFAULT_MODE))
        self.theme.apply()

        root = Path(settings.workspace or Path.cwd())
        if not root.exists():
            root = Path.cwd()
        self.settings.workspace = str(root)
        self.registry = ToolRegistry(root, confirm_commands=settings.agent.confirm_commands)
        self.registry.command_guard = self._confirm_command
        # Р—Р±РµСЂРµР¶РµРЅРёР№ СЂРµР¶РёРј РґРѕР·РІРѕР»С–РІ РґС–С” РѕРґСЂР°Р·Сѓ РїС–СЃР»СЏ СЃС‚Р°СЂС‚Сѓ.
        self.permission_mode = permissions.normalise_mode(settings.agent.permission_mode)
        self.current_goal = ""

        # Р”РІРёРіСѓРЅРё
        self.skill_book = skills_module.SkillBook(root)
        self.task_queue = queue_engine.TaskQueue()
        # в”Ђв”Ђ РІРёРєРѕРЅР°РІРµС†СЊ РїР»Р°РЅСѓ: РІРµРґРµ РєСЂРѕРєРё С‡РµСЂРіРё СЂРµР°Р»СЊРЅРёРјРё РґС–СЏРјРё Р°РіРµРЅС‚Р°.
        # РЎС‚РІРѕСЂСЋС”С‚СЊСЃСЏ Р”Рћ СЂРѕР·РєР»Р°РґРєРё, Р±Рѕ С†РµРЅС‚СЂ Р·Р°РІРґР°РЅСЊ Сѓ РЅРёР¶РЅС–Р№ РїР°РЅРµР»С– РІР¶Рµ
        # РїРѕРєР°Р·СѓС” РєРЅРѕРїРєРё, РїС–РґРєР»СЋС‡РµРЅС– РґРѕ РЅСЊРѕРіРѕ. РЎР°Рј Р°РіРµРЅС‚ СЃС‚РІРѕСЂСЋС”С‚СЊСЃСЏ
        # РїС–Р·РЅС–С€Рµ вЂ” РІРёРєРѕРЅР°РІРµС†СЊ РєР»РёС‡Рµ Р№РѕРіРѕ Р»РёС€Рµ РїС–Рґ С‡Р°СЃ СЂРѕР±РѕС‚Рё РєСЂРѕРєСѓ.
        self.executor = task_executor.QueueExecutor(
            self.task_queue,
            validator=task_executor.TaskValidator(self._project_root),
            on_run_step=self._run_plan_step,
            # РљРѕР»Р±РµРєРё Р№РґСѓС‚СЊ С–Р· РџРћРўРћРљРЈ РђР“Р•РќРўРђ, Р° С‡С–РїР°СЋС‚СЊ РІС–РґР¶РµС‚Рё. Tkinter
            # С†СЊРѕРіРѕ РЅРµ РґРѕР·РІРѕР»СЏС”: ``set_status`` С– ``_update_queue_badge``
            # Р·РІРµСЂС‚Р°СЋС‚СЊСЃСЏ РґРѕ СЃС‚Р°С‚СѓСЃР±Р°СЂР°, РїР°РЅРµР»С– С‡РµСЂРіРё, С†РµРЅС‚СЂСѓ Р·Р°РІРґР°РЅСЊ С–
            # РїР°РЅРµР»С– РєРѕРЅС‚РµРєСЃС‚Сѓ. РўРѕРјСѓ РјР°СЂС€Р°Р»С–Р·СѓС”РјРѕ РІ РіРѕР»РѕРІРЅРёР№ РїРѕС‚С–Рє вЂ” С‚Р°Рє
            # СЃР°РјРѕ, СЏРє С†Рµ РІР¶Рµ Р·СЂРѕР±Р»РµРЅРѕ РґР»СЏ ``mcp_watcher`` РЅРёР¶С‡Рµ.
            on_status=lambda text: self._ui_call(self.set_status, text),
            on_change=lambda: self._ui_call(self._update_queue_badge),
            chat_id_provider=self._active_chat_id,
        )
        #: Р§Рё РєСЂРѕРє С‡РµСЂРіРё Р·Р°СЂР°Р· РІРёРєРѕРЅСѓС” Р°РіРµРЅС‚ (С‰РѕР± РІС–РґСЂС–Р·РЅСЏС‚Рё Р·РІРёС‡Р°Р№РЅРёР№ С‡Р°С‚).
        self._plan_step_active = False
        #: РћСЃС‚Р°РЅРЅС–Р№ РїР»Р°РЅ, СЏРєРёР№ СЃРєР»Р°Р»Р° РјРѕРґРµР»СЊ (С‰РѕР± РїРѕРєР°Р·Р°С‚Рё/РїРµСЂРµРїР»Р°РЅСѓРІР°С‚Рё).
        self._last_plan: list[task_planner.PlanStep] = []
        self._planning = False
        self.mcp_manager = mcp_client.McpManager()
        # РќР°РіР»СЏРґР°С‡ MCP: РїРµСЂС–РѕРґРёС‡РЅРѕ РїРµСЂРµРІС–СЂСЏС”, С‰Рѕ СЃРµСЂРІРµСЂРё Р–РР’Р†, Р° РЅРµ Р»РёС€Рµ
        # В«РєРѕР»РёСЃСЊ С–РЅС–С†С–Р°Р»С–Р·СѓРІР°Р»РёСЃСЊВ». Р‘РµР· РЅСЊРѕРіРѕ РїРѕРјРµСЂР»РёР№ Р°Р±Рѕ Р·Р°РІРёСЃР»РёР№ СЃРµСЂРІРµСЂ
        # Р»РёС€Р°РІСЃСЏ Р·С– СЃС‚Р°С‚СѓСЃРѕРј В«РїСЂР°С†СЋС”В», С– Р°РіРµРЅС‚ РѕС‚СЂРёРјСѓРІР°РІ РїРѕРјРёР»РєРё РЅР° РєРѕР¶РЅРѕРјСѓ
        # РІРёРєР»РёРєСѓ. РЈСЃРїС–С€РЅС– СЃРµСЂРІРµСЂРё РЅР°РіР»СЏРґР°С‡ РЅРµ С‡С–РїР°С”.
        self.mcp_watcher = mcp_watch.Watcher(
            self.mcp_manager,
            on_status=lambda text: self._ui_call(self.set_status, text))
        self.chat_store = chat_store.ChatStore()
        self.case_book = cases_panel.CaseBook()
        # RAG: РЅР°СЏРІРЅРёР№ СЂСѓС€С–Р№ rag_engine.py, РїС–РґРєР»СЋС‡РµРЅРёР№ РґРѕ IDE.
        self.rag_service = rag.RagService(root)
        # в”Ђв”Ђ BLACKCHPOK NATIVE RUNTIME + NEUROMESH в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        # Р СѓС€С–Р№ РѕРґРёРЅ РЅР° РїСЂРѕС†РµСЃ; РІС–РЅ РЅРµ РїРѕС‚СЂРµР±СѓС” llama-server, LM Studio С‡Рё
        # Ollama. РџР°Рј'СЏС‚СЊ вЂ” РѕРєСЂРµРјР° SQLite-Р±Р°Р·Р° РІ С‚РµС†С– РґР°РЅРёС… Р·Р°СЃС‚РѕСЃСѓРЅРєСѓ.
        self.native_runtime = native_api.NativeRuntime()
        # РњР†РЎРў РјСѓСЃРёС‚СЊ Р±Р°С‡РёС‚Рё РЎРђРњР• Р¦Р•Р™ РµРєР·РµРјРїР»СЏСЂ. Р†РЅР°РєС€Рµ ``bridge.runtime()``
        # СЃС‚РІРѕСЂРёС‚СЊ РґСЂСѓРіРёР№ СЂСѓС€С–Р№ Р·С– СЃРІРѕС”СЋ РјРѕРґРµР»Р»СЋ вЂ” С– Сѓ VRAM РѕРїРёРЅСЏС‚СЊСЃСЏ РґРІС–
        # РєРѕРїС–С— (14B в‰€ 9 Р“Р‘ РєРѕР¶РЅР°), С‚РѕР±С‚Рѕ OOM Р·Р°РјС–СЃС‚СЊ СЂРѕР±РѕС‚Рё.
        native_bridge.set_runtime(self.native_runtime)
        self.memory = self._open_memory()
        if self.memory is not None:
            try:
                self.registry.attach_memory(self.memory)
            except Exception:                        # noqa: BLE001
                LOG.warning("РџР°Рј'СЏС‚СЊ РЅРµ РїС–РґРєР»СЋС‡РµРЅРѕ РґРѕ СЂРµС”СЃС‚СЂСѓ", exc_info=True)
        self.layout = layout.load()
        # Р–РёРІРµ С‚РµСЃС‚СѓРІР°РЅРЅСЏ: Р°РіРµРЅС‚ Р·Р°РїСѓСЃРєР°С”/РєР»С–РєР°С”/Р·РЅС–РјР°С” СЃРєСЂС–РЅС€РѕС‚Рё Р·Р°СЃС‚РѕСЃСѓРЅРєСѓ.
        self.app = AppController(self._project_root)
        self.registry.attach_app_controller(self.app)
        # РЎС‚РѕСЂС–РЅРєР° СЏРє РґР°РЅС–: Р°РіРµРЅС‚ С‡РёС‚Р°С” РєРѕРЅСЃРѕР»СЊ, DOM С– СЂРѕР±РёС‚СЊ Р·РЅС–РјРѕРє РЎРђРњРћР‡
        # СЃС‚РѕСЂС–РЅРєРё С‡РµСЂРµР· CDP. РџСЂРѕРІР°Р№РґРµСЂ Р»С–РЅРёРІРёР№ вЂ” РЅР° РјРѕРјРµРЅС‚ СЂРµС”СЃС‚СЂР°С†С–С—
        # РІР±СѓРґРѕРІР°РЅРѕРіРѕ Р±СЂР°СѓР·РµСЂР° С‰Рµ РЅРµРјР°С”.
        self.registry.attach_cdp_provider(self._browser_cdp)
        # Р”РѕР·РІС–Р» РЅР° DOM-РјС–СЃС‚ Р—РћР’РќР†РЁРќР†РҐ СЃС‚РѕСЂС–РЅРѕРє Р±РµСЂРµС‚СЊСЃСЏ Р· РЅР°Р»Р°С€С‚СѓРІР°РЅСЊ.
        # РўРёРїРѕРІРѕ РІРёРјРєРЅРµРЅРёР№: РјС–СЃС‚ С–СЃРЅСѓС” РґР»СЏ РІР»Р°СЃРЅРѕРіРѕ Live Preview, Р° С‡РёС‚Р°РЅРЅСЏ
        # С‡СѓР¶РѕРіРѕ СЃР°Р№С‚Сѓ вЂ” С†Рµ РґРѕСЃС‚СѓРї РґРѕ РѕСЃРѕР±РёСЃС‚РёС… РґР°РЅРёС… Сѓ РїРѕР»СЏС… С„РѕСЂРјРё.
        try:
            self.registry.allow_external_page_inspection = bool(
                getattr(self.settings.mcp, "allow_external_page_inspection", False))
        except AttributeError:
            self.registry.allow_external_page_inspection = False
        # Р”РµСЃРєСЂРёРїС‚РѕСЂ РІС–РєРЅР° РІР±СѓРґРѕРІР°РЅРѕРіРѕ Р±СЂР°СѓР·РµСЂР° вЂ” РґР»СЏ Р·РЅС–РјРєР° РЎРђРњР• РїСЂРѕС”РєС‚Сѓ
        # (Р° РЅРµ В«РїРµСЂС€РѕРіРѕ-Р»С–РїС€РѕРіРѕ ChromeВ» РЅР° РјР°С€РёРЅС– РєРѕСЂРёСЃС‚СѓРІР°С‡Р°).
        self.registry.attach_browser_hwnd_provider(self._browser_hwnd)
        # РџРѕРєР°Р· СЃС‚РѕСЂС–РЅРєРё Р»СЋРґРёРЅС–: Р°РіРµРЅС‚ РјРѕР¶Рµ РІС–РґРєСЂРёС‚Рё РїРѕСЃРёР»Р°РЅРЅСЏ РІ РїР°РЅРµР»С–
        # В«РЎР°Р№С‚В» С– РїРѕРєР°Р·Р°С‚Рё, РґРµ СЃР°РјРµ РІС–РЅ Р·РЅР°Р№С€РѕРІ С–РЅС„РѕСЂРјР°С†С–СЋ.
        self.registry.attach_page_opener(self.open_url_in_browser)

        self._active_side = "chats"
        self._mcp_busy = False
        self._queue_pump_after: Optional[str] = None
        self._ui_after: Optional[str] = None
        self._resize_after: Optional[str] = None
        self._ui_queue: "queue.Queue[tuple[object, tuple[object, ...]]]" = queue.Queue()
        self._running_task_id = ""
        self._setup_busy = False
        self._welcome_shown = False
        self._setup_note = ""
        #: Р§Рё РїРѕРєР°Р·Р°РЅР° РїСЂР°РІР° РєРѕР»РѕРЅРєР° Р¶РёРІРѕРіРѕ РїСЂРµРІ'СЋ Р·Р°СЃС‚РѕСЃСѓРЅРєСѓ.
        self._preview_shown = False
        #: Р РµР¶РёРј СЂРѕР±РѕС‚Рё Р°РіРµРЅС‚Р° (СЂРµР°Р»СЊРЅС– РґРѕР·РІРѕР»Рё + РєСЂРѕРєРё, РґРёРІ. :mod:`modes`).
        self.agent_mode = modes.normalise(getattr(settings.ui, "mode", modes.DEFAULT_MODE))
        #: РЎРїР»РёРІРЅС– РєР°СЂС‚РєРё (СЃРµР»РµРєС‚РѕСЂ РјРѕРґРµР»С–, РјРµРЅСЋ СЂРµР¶РёРјС–РІ).
        self._model_selector = None
        self._mode_menu = None
        self._probe = None
        self._probe_summary = ""
        self._probe_after: Optional[str] = None
        #: Р РµР·СѓР»СЊС‚Р°С‚Рё РїРµСЂРµРІС–СЂРєРё РїСЂРѕРІР°Р№РґРµСЂС–РІ: РєР»СЋС‡ в†’ ProbeOutcome.
        self._probe_state: dict[str, providers.ProbeOutcome] = {}
        #: True, РїРѕРєРё РїР°РЅРµР»СЊ РЅР°РІС–РіР°С†С–С— СЃС…РѕРІР°РЅР° Р°РІС‚РѕРјР°С‚РёС‡РЅРѕ С‡РµСЂРµР· РІСѓР·СЊРєРµ РІС–РєРЅРѕ.
        self._sidebar_auto_hidden = False
        #: True, РєРѕР»Рё РїР°РЅРµР»СЊ Р·РіРѕСЂРЅСѓС‚Р° РґРѕ СЂРµР№РєРё (Р»РёС€Р°СЋС‚СЊСЃСЏ СЃР°РјС– С–РєРѕРЅРєРё).
        self._sidebar_collapsed = False
        #: Р•РєСЂР°РЅ В«СЃРїРµСЂС€Сѓ РІРёР±РµСЂРё РїСЂРѕС”РєС‚В» (Р·Р°РјС–СЃС‚СЊ С‡Р°С‚Сѓ). ``None`` вЂ” РЅРµ РїРѕРєР°Р·Р°РЅРѕ.
        self.project_gate: Optional[project_gate.ProjectGate] = None
        #: Р’РёР±С–СЂ РєРѕСЂРёСЃС‚СѓРІР°С‡Р° С‰РѕРґРѕ РєРѕР»РѕРЅРєРё РєРѕРЅС‚РµРєСЃС‚Сѓ: None = Р°РІС‚РѕРјР°С‚РёС‡РЅРѕ.
        self._context_user_choice: Optional[bool] = None
        #: РћСЃС‚Р°РЅРЅС– РѕР±С‡РёСЃР»РµРЅС– Р°РґР°РїС‚РёРІРЅС– СЂРѕР·РјС–СЂРё РґС–Р°Р»РѕРіСѓ (РґРёРІ. :mod:`adaptive`).
        self._chat_metrics = adaptive.metrics_for(
            screen=adaptive.screen_size(self),
            sidebar=self.settings.ui.sidebar_width,
        )
        self._chat_lines_limit = self._chat_metrics.body_lines
        #: Р СѓС€С–Р№ Р°РІС‚РѕРЅРѕРјРЅРѕРіРѕ СЂРµР¶РёРјСѓ. РЎС‚РІРѕСЂСЋС”С‚СЊСЃСЏ РґРѕ СЂРѕР·РєР»Р°РґРєРё: РїР°РЅРµР»СЊ
        #: Р°РІС‚РѕРЅРѕРјРЅРѕРіРѕ СЂРµР¶РёРјСѓ РІР¶Рµ Р№РѕРіРѕ РїРѕРєР°Р·СѓС”. Р§РµСЂРіР° вЂ” РўРђ РЎРђРњРђ, С‰Рѕ РІ
        #: РїР°РЅРµР»С– Р·Р°РІРґР°РЅСЊ: С–РЅР°РєС€Рµ Р·Р°РґР°С‡С– Р°РіРµРЅС‚Р° Р№ Р·Р°РґР°С‡С– РєРѕСЂРёСЃС‚СѓРІР°С‡Р° Р¶РёР»Рё Р±
        #: Сѓ РґРІРѕС… СЃРїРёСЃРєР°С… С– РіСѓР±РёР»РёСЃСЊ РјС–Р¶ РЅРёРјРё.
        self.autonomous_engine = autonomous.AutonomousEngine(
            queue=self.task_queue,
            on_change=self._after_autonomous_change,
            on_status=self.set_status,
        )
        #: Р—СѓРїРёРЅРєР° Р°РіРµРЅС‚Р° Р№ РІРёРІР°РЅС‚Р°Р¶РµРЅРЅСЏ РјРѕРґРµР»С– Р· РІС–РґРµРѕРєР°СЂС‚Рё.
        self._managed_server = None
        self.model_keeper = power.ModelKeeper(
            server_provider=lambda: getattr(self, "_managed_server", None),
            start_provider=self._wake_model,
            on_status=self.set_status,
            # Р’Р»Р°СЃРЅРёР№ СЂСѓС€С–Р№ С‚РµР¶ РјР°С” РІС–РґРґР°РІР°С‚Рё VRAM РЅР° РїСЂРѕСЃС‚РѕС—: С–РЅР°РєС€Рµ 10 Р“Р‘
            # Р·Р°Р»РёС€Р°СЋС‚СЊСЃСЏ Р·Р°Р№РЅСЏС‚РёРјРё, РЅР°РІС–С‚СЊ РєРѕР»Рё РєРѕСЂРёСЃС‚СѓРІР°С‡ РїС–С€РѕРІ.
            native_provider=lambda: getattr(self, "native_runtime", None),
            native_start_provider=self._wake_native_model,
        )
        self.model_keeper.tracker.policy.enabled = bool(
            getattr(self.settings.engine, "unload_when_idle", True))
        self.model_keeper.tracker.policy.idle_seconds = int(
            getattr(self.settings.engine, "idle_unload_seconds", 300) or 300)
        self.model_keeper.tracker.policy.normalise()
        # в”Ђв”Ђ Р„РґРёРЅРµ РґР¶РµСЂРµР»Рѕ РїСЂР°РІРґРё РїСЂРѕ СЃС‚Р°РЅ СЃРµСЂРІРµСЂР° в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        # Р Р°РЅС–С€Рµ СЃС‚Р°РЅ Р·Р±РёСЂР°Р»Рё С‡РѕС‚РёСЂРё СЂС–Р·РЅС– РјС–СЃС†СЏ Р· СЂС–Р·РЅРёРјРё С‚Р°Р№РјР°СѓС‚Р°РјРё, С–
        # РІРѕРЅРё СЃСѓРїРµСЂРµС‡РёР»Рё РѕРґРЅРµ РѕРґРЅРѕРјСѓ: В«onlineВ» РїСЂРё РјРµСЂС‚РІРѕРјСѓ СЃРµСЂРІРµСЂС–,
        # 32768 Сѓ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏС… РїСЂРѕС‚Рё 16384 Сѓ СЃРµСЂРІРµСЂР°. РўРµРїРµСЂ СѓСЃС– РїРёС‚Р°СЋС‚СЊ
        # РћР”РРќ РєРµС€, Р° РјРµСЂРµР¶Р° С…РѕРґРёС‚СЊ Р»РёС€Рµ Сѓ С„РѕРЅРѕРІРѕРјСѓ РїРѕС‚РѕС†С–.
        self.server_state = server_state.ServerStateCache(
            settings_provider=lambda: self.settings,
            server_provider=lambda: getattr(self, "_managed_server", None),
            on_update=self._on_server_state,
        )
        #: РўРµРєР°, РґР»СЏ СЏРєРѕС— РІРІС–РјРєРЅРµРЅРѕ Р°РІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј (None вЂ” РІРёРјРєРЅРµРЅРѕ).
        self.project: Optional[Path] = None
        self._idle_after: Optional[str] = None
        self._autonomous_after: Optional[str] = None
        #: True, РїРѕРєРё С‡РµРєР°С”РјРѕ, С‰РѕР± Р°РіРµРЅС‚ РґРѕРїРёСЃР°РІ С„Р°Р№Р» РїРµСЂРµРґ РІРёРјРєРЅРµРЅРЅСЏРј СЂРµР¶РёРјСѓ.
        self._autonomous_stop_pending = False

        self._build_layout()
        self._build_menu()
        self._build_status()

        self.agent = AgentRunner(self.registry, settings.llm, settings.agent, root)
        self.agent.skill_book = self.skill_book
        self.agent.mcp_manager = self.mcp_manager
        self.agent.on_finished = self._on_agent_finished
        self.agent.settings_ref = self.settings
        # В«Р©Рѕ РІ С†СЊРѕРјСѓ С„Р°Р№Р»С–В» вЂ” СЂРѕСѓС‚РµСЂ РЅРµ Р±Р°С‡РёС‚СЊ РІС–РєРЅР°, С‚РѕР¶ Р°РєС‚РёРІРЅРёР№ С„Р°Р№Р»
        # СЂРµРґР°РєС‚РѕСЂР° РїС–РґСЃС‚Р°РІР»СЏС” Р°РіРµРЅС‚ С‡РµСЂРµР· С†РµР№ РїСЂРѕРІР°Р№РґРµСЂ.
        self.agent.active_path_provider = self._current_editor_path
        # в”Ђв”Ђ РџРѕСЃС‚С–Р№РЅС– РїРѕР±Р°Р¶Р°РЅРЅСЏ Р№ РІРёРјС–СЂСЋРІР°РЅРЅСЏ СЏРєРѕСЃС‚С– в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        # РџРѕР±Р°Р¶Р°РЅРЅСЏ Р¶РёРІСѓС‚СЊ Сѓ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏС… (Р»СЋРґРёРЅР° Р±Р°С‡РёС‚СЊ С– РєРµСЂСѓС” РЅРёРјРё),
        # traces вЂ” Сѓ СЂРѕР±РѕС‡С–Р№ С‚РµС†С– РїСЂРѕРіСЂР°РјРё: РІРѕРЅРё РїРѕС‚СЂС–Р±РЅС– РґР»СЏ РїРѕСЂС–РІРЅСЏРЅРЅСЏ
        # РєРѕРЅС„С–РіСѓСЂР°С†С–Р№, Р° РЅРµ РґР»СЏ С‰РѕРґРµРЅРЅРѕС— СЂРѕР±РѕС‚Рё.
        self._attach_profile(self.agent)
        self._attach_traces(self.agent)
        # РџР°Рј'СЏС‚СЊ NEUROMESH Р±РµСЂРµ СѓС‡Р°СЃС‚СЊ Сѓ СЂРѕР·СѓРјС–РЅРЅС– Р·Р°РїРёС‚Сѓ: С„Р°РєС‚Рё Р№
        # РѕР±РјРµР¶РµРЅРЅСЏ РїСЂРѕС”РєС‚Сѓ РїРѕС‚СЂР°РїР»СЏСЋС‚СЊ Сѓ РєРѕРЅС‚РµРєСЃС‚ Р”Рћ Р·Р°РїРёС‚Сѓ РґРѕ РјРѕРґРµР»С–.
        self._attach_memory_bridge(self.agent)
        self.chat.attach_runner(self.agent)
        self.chat._workspace_root = root
        # РђРґР°РїС‚РёРІРЅРёР№ Р»С–РјС–С‚ СЂСЏРґРєС–РІ РѕРґРЅС–С”С— РІС–РґРїРѕРІС–РґС–: РЅР° РјР°Р»РѕРјСѓ РµРєСЂР°РЅС–
        # РІС–РґРїРѕРІС–РґСЊ РЅРµ РјР°С” Р·Р°Р±РёСЂР°С‚Рё РІСЃСЋ СЃС‚СЂС–С‡РєСѓ, РЅР° РІРµР»РёРєРѕРјСѓ вЂ” РѕР±СЂС–Р·Р°С‚РёСЃСЊ.
        try:
            self.chat.set_max_lines(self._chat_lines_limit)
        except (tk.TclError, AttributeError):
            LOG.debug("РќРµ РІРґР°Р»РѕСЃСЊ Р·Р°РґР°С‚Рё Р°РґР°РїС‚РёРІРЅРёР№ Р»С–РјС–С‚ СЂСЏРґРєС–РІ", exc_info=True)

        self._wire_shortcuts()
        # РЈРІРµСЃСЊ Р·Р°СЃС‚РѕСЃСѓРЅРѕРє РІС–РґРєСЂРёРІР°С” СЃС‚РѕСЂС–РЅРєРё Р›РРЁР• Сѓ РІР±СѓРґРѕРІР°РЅРѕРјСѓ Р±СЂР°СѓР·РµСЂС–.
        # Р‘РµР· С†СЊРѕРіРѕ РїР°РЅРµР»СЊ Р·РјС–РЅ РєР»РёРєР°Р»Р° webbrowser.open С– РІРёРєРёРґР°Р»Р°
        # РєРѕСЂРёСЃС‚СѓРІР°С‡Р° РІ Chrome РЅР° СЃС‚РѕСЂС–РЅРєСѓ Р·Р°РІР°РЅС‚Р°Р¶РµРЅРЅСЏ git.
        browser_panel.set_url_opener(self.open_url_in_browser)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        # в”Ђв”Ђ РђРІР°СЂС–Р№РЅРёР№ РІРёС…С–Рґ: Р·РІС–Р»СЊРЅРёС‚Рё РІС–РґРµРѕРєР°СЂС‚Сѓ РЅР°РІС–С‚СЊ РїСЂРё Р·Р±РѕС— в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        # РЁС‚Р°С‚РЅРёР№ С€Р»СЏС… вЂ” ``on_close``. РђР»Рµ СЏРєС‰Рѕ РїСЂРѕРіСЂР°РјР° РІРїР°РґРµ, С—С— РІР±'СЋС‚СЊ
        # С‡РµСЂРµР· РґРёСЃРїРµС‚С‡РµСЂ Р·Р°РґР°С‡ Р°Р±Рѕ Р·Р°РєСЂРёС”С‚СЊСЃСЏ РІС–РєРЅРѕ РєРѕРЅСЃРѕР»С–, ``on_close``
        # РЅРµ РІРёРєРѕРЅР°С”С‚СЊСЃСЏ, С– ``llama-server`` Р»РёС€РёС‚СЊСЃСЏ Р¶РёРІРёРј С–Р· 8вЂ“11 Р“Р‘ VRAM.
        # РўРѕРґС– РєРѕСЂРёСЃС‚СѓРІР°С‡ РЅРµ РјРѕР¶Рµ Р·Р°РїСѓСЃС‚РёС‚Рё РіСЂСѓ, РїРѕРєРё РІСЂСѓС‡РЅСѓ РЅРµ Р·РЅР°Р№РґРµ
        # РїСЂРѕС†РµСЃ. ``atexit`` РІРёРєРѕРЅСѓС”С‚СЊСЃСЏ РїСЂРё Р·РІРёС‡Р°Р№РЅРѕРјСѓ Р·Р°РІРµСЂС€РµРЅРЅС– РїСЂРѕС†РµСЃСѓ
        # Python С– РїСЂРё ``sys.exit``.
        atexit.register(self._release_model_now)
        self._drain_ui()
        self.after(150, self._startup)
        self.after(700, lambda: self.probe_providers(silent=True))

    # в”Ђв”Ђ С–РєРѕРЅРєР° в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _cleanup_orphans_quietly(self) -> None:
        """РџСЂРёР±СЂР°С‚Рё В«СЃРёСЂС–С‚СЃСЊРєС–В» СЂСѓС€С–С— Сѓ С„РѕРЅС– (РЅРµ Р·Р°РІР°Р¶Р°СЋС‡Рё СЃС‚Р°СЂС‚Сѓ)."""
        try:
            removed = runtime.cleanup_stale_processes()
        except Exception:  # noqa: BLE001 - СЃС‚Р°СЂС‚ РЅРµ РјР°С” РїР°РґР°С‚Рё
            LOG.debug("РџСЂРёР±РёСЂР°РЅРЅСЏ СЃРёСЂС–С‚ РЅРµ РІРґР°Р»РѕСЃСЊ", exc_info=True)
            return
        if removed:
            LOG.info("РќР° СЃС‚Р°СЂС‚С– РїСЂРёР±СЂР°РЅРѕ Р·Р°Р»РёС€РєРѕРІРёС… СЂСѓС€С–С—РІ: %s", removed)
            try:
                self._ui_call(self.set_status,
                              f"Р—РІС–Р»СЊРЅРµРЅРѕ РІС–РґРµРѕРїР°Рј'СЏС‚СЊ: Р·СѓРїРёРЅРµРЅРѕ "
                              f"Р·Р°Р»РёС€РєРѕРІРёС… СЂСѓС€С–С—РІ вЂ” {removed}")
            except Exception:  # noqa: BLE001
                pass

    def _apply_start_geometry(self) -> None:
        """Р’С–РґРєСЂРёС‚Рё РІС–РєРЅРѕ РЅР° РІРµСЃСЊ РµРєСЂР°РЅ (Р°Р±Рѕ Р·Р±РµСЂРµР¶РµРЅРёРј СЂРѕР·РјС–СЂРѕРј).

        Р§РѕРјСѓ РЅР° РІРµСЃСЊ РµРєСЂР°РЅ: РІ IDE С‡РѕС‚РёСЂРё РєРѕР»РѕРЅРєРё вЂ” РЅР°РІС–РіР°С†С–СЏ, РґС–Р°Р»РѕРі,
        СЂРµРґР°РєС‚РѕСЂ С– РєРѕРЅС‚РµРєСЃС‚. РЈ РІС–РєРЅС– 1560Г—940 РґС–Р°Р»РѕРі Р»РёС€Р°РІСЃСЏ РІСѓР·СЊРєРѕСЋ
        СЃРјСѓР¶РєРѕСЋ, Р° С„РѕСЂРјР° РІРІРѕРґСѓ Р·РЅРёРєР°Р»Р° Р·Р° РјРµР¶Р°РјРё РµРєСЂР°РЅР°. РљРѕСЂРёСЃС‚СѓРІР°С‡ РїСЂРѕСЃРёРІ:
        В«СЂРѕР·С€РёСЂРёС‚Рё РІС–РєРЅР° РЅР° РїРѕРІРЅРѕРјСѓ РµРєСЂР°РЅС–В».

        РЇРєС‰Рѕ РєРѕСЂРёСЃС‚СѓРІР°С‡ Р·РјС–РЅРёРІ СЂРѕР·РјС–СЂ РјРёС€РєРѕСЋ, ``_remember_layout`` Р·Р±РµСЂС–Рі
        Р№РѕРіРѕ вЂ” С‚РѕРґС– РІС–РґРєСЂРёРІР°С”РјРѕ СЃР°РјРµ С‚РѕР№ СЂРѕР·РјС–СЂ, Р° РЅРµ РЅР°РІ'СЏР·СѓС”РјРѕ СЃРІС–Р№.
        """
        saved = None
        try:
            saved = self.layout.get("window_size", "") if hasattr(self, "layout") else None
        except Exception:  # noqa: BLE001
            saved = None
        if saved and isinstance(saved, str) and "x" in saved:
            try:
                self.geometry(saved)
                return
            except tk.TclError:
                pass
        # РўРёРїРѕРІРѕ вЂ” РјР°РєСЃРёРјР°Р»СЊРЅРёР№ СЂРѕР±РѕС‡РёР№ РїСЂРѕСЃС‚С–СЂ РµРєСЂР°РЅР° (Р±РµР· РїР°РЅРµР»С– Р·Р°РґР°С‡).
        try:
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
            self.geometry(f"{max(1020, screen_w)}x{max(640, screen_h - 80)}+0+0")
        except tk.TclError:
            self.geometry("1560x940")
        # Р РѕР·РіРѕСЂРЅСѓС‚Рё РЅР° РІРµСЃСЊ РµРєСЂР°РЅ РїС–СЃР»СЏ РїРѕР±СѓРґРѕРІРё вЂ” С‰РѕР± Tk РЅРµ СЃРєРёРЅСѓРІ
        # СЂРѕР·РјС–СЂ, РєРѕР»Рё РІС–РґР¶РµС‚Рё РїРѕС‡РЅСѓС‚СЊ РїСЂРѕСЃРёС‚Рё РјС–СЃС†Рµ.
        try:
            self.state("zoomed")
        except tk.TclError:
            pass
        # РџС–СЃР»СЏ СЂРѕР·РіРѕСЂС‚Р°РЅРЅСЏ СЃР°С€С– РўР Р•Р‘Рђ РїРµСЂРµСЂР°С…СѓРІР°С‚Рё: РІРѕРЅРё Р±СѓР»Рё СЂРѕР·СЃС‚Р°РІР»РµРЅС–
        # РїС–Рґ РїРѕС‡Р°С‚РєРѕРІРёР№ СЂРѕР·РјС–СЂ, С– РїСЂРё 3440 px РґС–Р°Р»РѕРі Р»РёС€Р°РІСЃСЏ РІСѓР·СЊРєРѕСЋ
        # СЃРјСѓР¶РєРѕСЋ Р·Р»С–РІР°, Р° СЂРµС€С‚Р° РІС–РєРЅР° вЂ” РїРѕСЂРѕР¶РЅСЊРѕСЋ.
        for delay in (60, 240, 600):
            self._sash_after(delay)

    def _apply_icon(self) -> None:
        from .config import resource_dir

        icon = resource_dir() / "assets" / "icon.ico"
        if icon.exists():
            try:
                self.iconbitmap(str(icon))
            except tk.TclError:
                pass

    # в”Ђв”Ђ РјРµРЅСЋ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="РќРѕРІРёР№ С„Р°Р№Р»", accelerator="Ctrl+N", command=self.new_file)
        file_menu.add_command(label="Р’С–РґРєСЂРёС‚Рё С„Р°Р№Р»вЂ¦", accelerator="Ctrl+O", command=self.open_file_dialog)
        file_menu.add_command(label="Р’С–РґРєСЂРёС‚Рё РїР°РїРєСѓвЂ¦", command=self.open_folder_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Р—Р±РµСЂРµРіС‚Рё", accelerator="Ctrl+S", command=self.save_file)
        file_menu.add_command(label="Р—Р±РµСЂРµРіС‚Рё СЏРєвЂ¦", accelerator="Ctrl+Shift+S", command=self.save_file_as)
        file_menu.add_command(label="Р—Р±РµСЂРµРіС‚Рё РІСЃРµ", command=lambda: self.tabs.save_all())
        file_menu.add_separator()
        file_menu.add_command(label="Р—Р°РєСЂРёС‚Рё РІРєР»Р°РґРєСѓ", accelerator="Ctrl+W", command=self.close_tab)
        file_menu.add_command(label="Р’С–РґРєСЂРёС‚Рё Р·Р°РєСЂРёС‚Сѓ РІРєР»Р°РґРєСѓ", accelerator="Ctrl+Shift+T",
                              command=self.reopen_tab)
        file_menu.add_command(label="Р—Р°РєСЂРёС‚Рё РІСЃС– РІРєР»Р°РґРєРё", command=self.close_all_tabs)
        file_menu.add_command(label="РЎС‚Р°СЂС‚РѕРІРёР№ РµРєСЂР°РЅ", command=self.show_welcome)
        file_menu.add_separator()
        file_menu.add_command(label="Р’РёС…С–Рґ", accelerator="Alt+F4", command=self.on_close)
        menubar.add_cascade(label="Р¤Р°Р№Р»", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="РЎРєР°СЃСѓРІР°С‚Рё", accelerator="Ctrl+Z", command=lambda: self._editor_event("<Control-z>"))
        edit_menu.add_command(label="РџРѕРІС‚РѕСЂРёС‚Рё", accelerator="Ctrl+Y", command=lambda: self._editor_event("<Control-y>"))
        edit_menu.add_separator()
        edit_menu.add_command(label="Р’РёСЂС–Р·Р°С‚Рё", accelerator="Ctrl+X", command=lambda: self._editor_event("<<Cut>>"))
        edit_menu.add_command(label="РљРѕРїС–СЋРІР°С‚Рё", accelerator="Ctrl+C", command=lambda: self._editor_event("<<Copy>>"))
        edit_menu.add_command(label="Р’СЃС‚Р°РІРёС‚Рё", accelerator="Ctrl+V", command=lambda: self._editor_event("<<Paste>>"))
        edit_menu.add_separator()
        edit_menu.add_command(label="Р—РЅР°Р№С‚Рё РІ С„Р°Р№Р»С–вЂ¦", accelerator="Ctrl+F", command=self.open_search)
        edit_menu.add_command(label="РџРѕС€СѓРє Сѓ РїСЂРѕС”РєС‚С–вЂ¦", accelerator="Ctrl+Shift+F", command=self.open_project_search)
        edit_menu.add_command(label="РџРµСЂРµР№С‚Рё РґРѕ СЂСЏРґРєР°вЂ¦", accelerator="Ctrl+G",
                              command=lambda: self.tabs.current() and self.tabs.current().focus_goto())
        edit_menu.add_separator()
        edit_menu.add_command(label="РљРѕРјР°РЅРґРЅР° РїР°Р»С–С‚СЂР°вЂ¦", accelerator="Ctrl+Shift+P", command=self.command_palette)
        edit_menu.add_command(label="РЁРІРёРґРєРµ РІС–РґРєСЂРёС‚С‚СЏвЂ¦", accelerator="Ctrl+P", command=self.quick_open)
        edit_menu.add_separator()
        edit_menu.add_command(label="РџРѕРєР°Р·Р°С‚Рё AST-РґРµСЂРµРІРѕ", accelerator="Ctrl+Shift+A",
                              command=self.show_ast_tree)
        edit_menu.add_command(label="Р—РІС–С‚ РїСЂРѕ СЃРёРјРІРѕР»Рё", command=self.show_symbols_report)
        edit_menu.add_command(label="Р¤РѕСЂРјР°С‚: РєРѕРјРµРЅС‚Р°СЂ", accelerator="Ctrl+/",
                              command=lambda: self.tabs.current() and self.tabs.current()._toggle_comment())
        menubar.add_cascade(label="РџСЂР°РІРєР°", menu=edit_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="РўС–Р»СЊРєРё С‡Р°С‚", accelerator="Ctrl+Alt+F",
                              command=self.toggle_focus_mode)
        view_menu.add_separator()
        view_menu.add_command(label="Р‘С–С‡РЅР° РїР°РЅРµР»СЊ", accelerator="Ctrl+B", command=self.toggle_sidebar)
        view_menu.add_command(label="РџР°РЅРµР»СЊ Р°РіРµРЅС‚Р°", accelerator="Ctrl+Alt+B", command=self.toggle_chat)
        view_menu.add_command(label="РљРѕР»РѕРЅРєР° РєРѕРЅС‚РµРєСЃС‚Сѓ", command=self.toggle_context)
        view_menu.add_command(label="Live Preview", accelerator="Ctrl+Alt+V", command=self.toggle_preview)
        view_menu.add_command(label="РўРµСЂРјС–РЅР°Р»", accelerator="Ctrl+`", command=self.toggle_bottom)
        view_menu.add_command(label="РЎР°Р№С‚ Сѓ Р±СЂР°СѓР·РµСЂС–", accelerator="Ctrl+Alt+P",
                              command=self.open_site)
        view_menu.add_separator()
        view_menu.add_command(label="Р—Р°РїСѓСЃС‚РёС‚Рё Р·Р°СЃС‚РѕСЃСѓРЅРѕРє", command=self.start_site)
        view_menu.add_command(label="Р—СѓРїРёРЅРёС‚Рё Р·Р°СЃС‚РѕСЃСѓРЅРѕРє", command=self.stop_site)
        view_menu.add_command(label="РћРЅРѕРІРёС‚Рё СЃС‚РѕСЂС–РЅРєСѓ", command=self.reload_site)
        view_menu.add_command(label="Р’С–РґРєСЂРёС‚Рё Р°РґСЂРµСЃСѓ Сѓ РІР±СѓРґРѕРІР°РЅРѕРјСѓ Р±СЂР°СѓР·РµСЂС–вЂ¦",
                              accelerator="Ctrl+Alt+L", command=self.open_url_dialog)
        view_menu.add_separator()
        # Р Р°РґС–Рѕ-РїСѓРЅРєС‚Рё: РіР°Р»РѕС‡РєР° РїРѕРєР°Р·СѓС” РїРѕС‚РѕС‡РЅСѓ С‚РµРјСѓ Р±РµР· СЂСѓС‡РЅРѕРіРѕ РїРµСЂРµСЂР°С…СѓРЅРєСѓ.
        self._theme_var = tk.StringVar(value=theme.current_mode())
        theme_menu = tk.Menu(view_menu, tearoff=0)
        theme_menu.add_radiobutton(
            label="РўРµРјРЅР°", variable=self._theme_var, value="dark",
            command=lambda: self.apply_theme_mode("dark"))
        theme_menu.add_radiobutton(
            label="РЎРІС–С‚Р»Р° (cream)", variable=self._theme_var, value="light",
            command=lambda: self.apply_theme_mode("light"))
        theme_menu.add_separator()
        theme_menu.add_command(label="Р—Р±РµСЂРµРіС‚Рё РїРѕС‚РѕС‡РЅСѓ С‚РµРјСѓ", command=self._save_theme)
        view_menu.add_cascade(label="РўРµРјР°", menu=theme_menu)
        self._theme_menu = theme_menu
        view_menu.add_separator()
        view_menu.add_command(label="РЎРєС–Р»Рё Р°РіРµРЅС‚Р°", accelerator="Ctrl+Alt+K", command=lambda: self.show_side("skills"))
        view_menu.add_command(label="РљСЂРѕРєРё Р°РіРµРЅС‚Р°", accelerator="Ctrl+Alt+D", command=lambda: self.show_side("cases"))
        view_menu.add_command(label="РђРІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј", accelerator="Ctrl+Alt+A",
                              command=self.show_autonomous)
        view_menu.add_command(label="Р—РЅР°РЅРЅСЏ РїСЂРѕ РїСЂРѕС”РєС‚ (RAG)", accelerator="Ctrl+Alt+I",
                              command=lambda: self.show_side("rag"))
        view_menu.add_command(label="Р†РЅСЃС‚СЂСѓРјРµРЅС‚Рё Р°РіРµРЅС‚Р°", accelerator="Ctrl+Alt+T",
                              command=lambda: self.show_side("tools"))
        view_menu.add_command(label="Р§РµСЂРіР° Р·Р°РІРґР°РЅСЊ", accelerator="Ctrl+Alt+Q", command=lambda: self.show_side("queue"))
        view_menu.add_command(label="MCP-СЃРµСЂРІРµСЂРё", command=lambda: self.show_side("mcp"))
        view_menu.add_separator()
        view_menu.add_command(label="РҐР°Р± РјРѕРґРµР»РµР№вЂ¦", accelerator="Ctrl+Shift+M", command=self.open_model_hub)
        view_menu.add_command(label="РњР°Р№СЃС‚РµСЂ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏ (Р±С–Р±Р»С–РѕС‚РµРєРё, РїСЂРѕРіСЂР°РјРё, РјРѕРґРµР»СЊ)вЂ¦",
                              command=self.open_first_run)
        view_menu.add_separator()
        view_menu.add_separator()
        view_menu.add_command(label="РЎРєРёРЅСѓС‚Рё СЂРѕР·РєР»Р°РґРєСѓ", command=self.reset_layout)
        view_menu.add_command(label="Р—Р±РµСЂРµРіС‚Рё СЂРѕР·РєР»Р°РґРєСѓ", command=self._remember_layout)
        view_menu.add_command(label="Р—Р±С–Р»СЊС€РёС‚Рё С€СЂРёС„С‚", accelerator="Ctrl+=", command=lambda: self.zoom(1))
        view_menu.add_command(label="Р—РјРµРЅС€РёС‚Рё С€СЂРёС„С‚", accelerator="Ctrl+-", command=lambda: self.zoom(-1))
        view_menu.add_separator()
        view_menu.add_command(label="РќР°Р»Р°С€С‚СѓРІР°РЅРЅСЏвЂ¦", accelerator="Ctrl+,", command=self.open_settings)
        view_menu.add_command(label="РџРѕРєР°Р·Р°С‚Рё Р¶СѓСЂРЅР°Р»", command=self.show_log)
        menubar.add_cascade(label="Р’РёРіР»СЏРґ", menu=view_menu)

        agent_menu = tk.Menu(menubar, tearoff=0)
        agent_menu.add_command(label="РќР°РґС–СЃР»Р°С‚Рё РїРѕС‚РѕС‡РЅРёР№ С„Р°Р№Р» Р°РіРµРЅС‚Сѓ", accelerator="Ctrl+Alt+Enter",
                               command=self.send_file_to_agent)
        agent_menu.add_command(label="РџРѕСЏСЃРЅРёС‚Рё РІРёРґС–Р»РµРЅРµ", command=self.explain_selection)
        agent_menu.add_command(label="Р’РёРїСЂР°РІРёС‚Рё РІРёРґС–Р»РµРЅРµ", command=self.fix_selection)
        agent_menu.add_separator()
        agent_menu.add_command(label="Р”РѕРґР°С‚Рё Р·Р°РґР°С‡Сѓ РІ С‡РµСЂРіСѓ", accelerator="Ctrl+Alt+Q", command=self.add_queue_dialog)
        agent_menu.add_command(label="Р—Р°РїСѓСЃС‚РёС‚Рё РЅР°СЃС‚СѓРїРЅСѓ Р·Р°РґР°С‡Сѓ", command=self.run_next_task)
        agent_menu.add_command(label="Р—СѓРїРёРЅРёС‚Рё Р°РіРµРЅС‚Р°", command=self.stop_agent)
        agent_menu.add_separator()
        # в”Ђв”Ђ РїР»Р°РЅ СЂРѕР±РѕС‚Рё: С†РµРЅС‚СЂ Р·Р°РІРґР°РЅСЊ С– РєРµСЂСѓРІР°РЅРЅСЏ РЅРёРј
        agent_menu.add_command(label="Р¦РµРЅС‚СЂ Р·Р°РІРґР°РЅСЊ", accelerator="Ctrl+Alt+W",
                               command=lambda: self.show_bottom("tasks"))
        agent_menu.add_command(label="РџСЂРёР·СѓРїРёРЅРёС‚Рё РїР»Р°РЅ", command=self.pause_queue)
        agent_menu.add_command(label="РџСЂРѕРґРѕРІР¶РёС‚Рё РїР»Р°РЅ", command=self.resume_queue)
        agent_menu.add_command(label="Р—СѓРїРёРЅРёС‚Рё РІРёРєРѕРЅР°РЅРЅСЏ РїР»Р°РЅСѓ", command=self.stop_plan)
        agent_menu.add_command(label="РџРµСЂРµРїР»Р°РЅСѓРІР°С‚Рё Р·Р°Р»РёС€РѕРє СЂРѕР±РѕС‚Рё", command=self.replan_now)
        agent_menu.add_command(label="РџС–РґСЃСѓРјРєРѕРІРёР№ Р·РІС–С‚", command=self.finish_plan_report)
        agent_menu.add_separator()
        agent_menu.add_command(label="РђРІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј: СЃС‚Р°СЂС‚ / СЃС‚РѕРї",
                               accelerator="Ctrl+Alt+A", command=self.toggle_autonomous)
        agent_menu.add_command(label="РђРІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј: РїР°РЅРµР»СЊ", command=self.show_autonomous)
        agent_menu.add_command(label="Р’РёРІР°РЅС‚Р°Р¶РёС‚Рё РјРѕРґРµР»СЊ С–Р· РІС–РґРµРѕРєР°СЂС‚Рё",
                               command=self.unload_model_now)
        agent_menu.add_separator()
        agent_menu.add_command(label="РќРѕРІРёР№ С‡Р°С‚", command=self.new_chat)
        agent_menu.add_command(label="РџРµСЂРµРІС–СЂРёС‚Рё РјРѕРґРµР»СЊ", command=lambda: self.probe_providers())
        agent_menu.add_command(label="РџРµСЂРµРїС–РґРєР»СЋС‡РёС‚Рё MCP", command=self.reload_mcp)
        agent_menu.add_separator()
        # Р РµР°Р»СЊРЅС– С†РёС„СЂРё РїСЂРѕ С‚Рµ, СЏРє Р°РіРµРЅС‚ РїСЂР°С†СЋС”: С—С… РјРѕР¶РЅР° РїРѕРєР°Р·Р°С‚Рё Р№
        # РїРѕСЂС–РІРЅСЏС‚Рё РјС–Р¶ РєРѕРЅС„С–РіСѓСЂР°С†С–СЏРјРё, РЅР° РІС–РґРјС–РЅСѓ РІС–Рґ В«СЃС‚Р°Р»Рѕ РєСЂР°С‰РµВ».
        agent_menu.add_command(label="РЇРєС–СЃС‚СЊ Р°РіРµРЅС‚Р° (РјРµС‚СЂРёРєРё)", command=self.show_agent_quality)
        menubar.add_cascade(label="РђРіРµРЅС‚", menu=agent_menu)

        git_menu = tk.Menu(menubar, tearoff=0)
        git_menu.add_command(label="РЎС‚Р°С‚СѓСЃ", command=lambda: self.terminal.run("git status --short --branch"))
        git_menu.add_command(label="Diff", command=lambda: self.terminal.run("git diff"))
        git_menu.add_command(label="Р†СЃС‚РѕСЂС–СЏ", command=lambda: self.terminal.run("git log --oneline -15"))
        git_menu.add_command(label="Р”РѕРґР°С‚Рё РІСЃРµ", command=lambda: self.terminal.run("git add -A"))
        menubar.add_cascade(label="Git", menu=git_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Р“Р°СЂСЏС‡С– РєР»Р°РІС–С€С–", command=self.show_shortcuts)
        help_menu.add_command(label="РџСЂРѕ РїСЂРѕРіСЂР°РјСѓ", command=self.show_about)
        menubar.add_cascade(label="Р”РѕРІС–РґРєР°", menu=help_menu)

        self.configure(menu=menubar)

    # в”Ђв”Ђ СЂРѕР·РєР»Р°РґРєР° в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _build_layout(self) -> None:
        """Р—С–Р±СЂР°С‚Рё РѕР±РѕР»РѕРЅРєСѓ: РЅР°РІС–РіР°С†С–СЏ | Р·Р°РіРѕР»РѕРІРѕРє СЃРµСЃС–С— + СЂРѕР±РѕС‡Р° РѕР±Р»Р°СЃС‚СЊ.

        РљРѕРјРїРѕР·РёС†С–СЏ РЅР°РІРјРёСЃРЅРѕ РїРѕРІС‚РѕСЂСЋС” РѕСЂРіР°РЅС–Р·Р°С†С–СЋ СЂРѕР±РѕС‡РѕРіРѕ РїСЂРѕСЃС‚РѕСЂСѓ СЃСѓС‡Р°СЃРЅРѕС—
        Р°РіРµРЅС‚РЅРѕС— РѕР±РѕР»РѕРЅРєРё: РІСѓР·СЊРєР° РЅР°РІС–РіР°С†С–СЏ Р·Р»С–РІР°, С†РµРЅС‚СЂР°Р»СЊРЅР° РєРѕР»РѕРЅРєР° РґС–Р°Р»РѕРіСѓ
        РєРѕРјС„РѕСЂС‚РЅРѕС— С€РёСЂРёРЅРё, СЂРѕР±РѕС‡Р° РѕР±Р»Р°СЃС‚СЊ (СЂРµРґР°РєС‚РѕСЂ) РїСЂР°РІРѕСЂСѓС‡, РєРѕРЅС‚РµРєСЃС‚ вЂ”
        РѕРєСЂРµРјРѕСЋ РєРѕР»РѕРЅРєРѕСЋ Р·Р° Р±Р°Р¶Р°РЅРЅСЏРј.

            в”Њв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”¬в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”ђ
            в”‚ РЅР°РІ. в”‚  Р·Р°РіРѕР»РѕРІРѕРє СЃРµСЃС–С—                             в”‚
            в”‚      в”њв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”¤
            в”‚ РїР°РЅРµР»СЊв”‚  РґС–Р°Р»РѕРі (С†РµРЅС‚СЂ)  в”‚  СЂРѕР±РѕС‡Р° РѕР±Р»Р°СЃС‚СЊ  в”‚ РєРѕРЅС‚РµРєСЃС‚в”‚
            в”‚      в”‚  в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ  в”‚                  в”‚         в”‚
            в”‚      в”‚  РєРѕРјРїРѕР·РµСЂ         в”‚                  в”‚         в”‚
            в””в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”ґв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”
        """
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        outer = tk.Frame(self, bg=theme.BG, bd=0, highlightthickness=0)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(1, weight=1)
        self.outer = outer

        # в”Ђв”Ђ РЅРѕРІР° РІРµСЂС…РЅСЏ С€Р°РїРєР°: С€РІРёРґРєРёР№ РґРѕСЃС‚СѓРї РґРѕ РІСЃСЊРѕРіРѕ, С‰Рѕ СЂРѕР±РёС‚СЊ Р»СЋРґРёРЅР°.
        # Р’РѕРЅР° Р№РґРµ РџР•Р РЁРћР®, РЅР°Рґ РїР°РЅРµР»СЏРјРё, С– С‚СЂРёРјР°С” РІР»Р°СЃРЅСѓ РІРёСЃРѕС‚Сѓ: С†Рµ РіРѕР»РѕРІРЅР°
        # РїР°РЅРµР»СЊ РєРµСЂСѓРІР°РЅРЅСЏ, Р° РЅРµ С‰Рµ РѕРґРёРЅ СЂСЏРґРѕРє Сѓ СЂРѕР±РѕС‡С–Р№ РѕР±Р»Р°СЃС‚С–.
        self._build_header(outer)

        # Р›С–РІР° РїР°РЅРµР»СЊ Р¶РёРІРµ Сѓ РІР»Р°СЃРЅРѕРјСѓ PanedWindow: С‚Р°Рє С—С— РјРµР¶Сѓ РјРѕР¶РЅР° С‚СЏРіРЅСѓС‚Рё
        # РјРёС€РµСЋ. Р Р°РЅС–С€Рµ РІРѕРЅР° Р±СѓР»Р° Р·РІРёС‡Р°Р№РЅРёРј Frame С–Р· С„С–РєСЃРѕРІР°РЅРѕСЋ С€РёСЂРёРЅРѕСЋ вЂ”
        # Р·РјС–РЅРёС‚Рё С—С— РјРѕР¶РЅР° Р±СѓР»Рѕ Р»РёС€Рµ РІ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏС…, С‡РѕРіРѕ РЅС–С…С‚Рѕ РЅРµ СЂРѕР±РёС‚СЊ.
        from tkinter import ttk

        self.side_split = ttk.PanedWindow(outer, orient="horizontal")
        self.side_split.grid(row=1, column=0, columnspan=2, sticky="nsew")
        self._build_sidebar(self.side_split)
        self._build_centre(self.side_split)

        # РЎР°С€С– СЃС‚Р°РІРёРјРѕ РєС–Р»СЊРєР° СЂР°Р·С–РІ: РїР°РЅРµР»С– РґРѕРґР°СЋС‚СЊСЃСЏ РІР¶Рµ РїС–СЃР»СЏ РїРµСЂС€РѕС—
        # СЂРѕР·РєР»Р°РґРєРё, С– РѕРґРЅРѕРіРѕ after_idle РЅРµ РІРёСЃС‚Р°С‡Р°С”.
        self._sash_after(0)
        self._sash_after(120)
        self._sash_after(420)
        # Р’С–РєРЅРѕ РјРѕР¶СѓС‚СЊ СЂРѕР·С‚СЏРіРЅСѓС‚Рё Р°Р±Рѕ Р·РІСѓР·РёС‚Рё вЂ” С‚РѕРґС– СЃР°С€С– С‚СЂРµР±Р° РїРµСЂРµСЂР°С…СѓРІР°С‚Рё.
        self.bind("<Configure>", self._on_root_configure, add="+")
        # РљРѕСЂРёСЃС‚СѓРІР°С‡ СЂСѓС…Р°С” РјРµР¶С– вЂ” Р·Р°РїР°Рј'СЏС‚РѕРІСѓС”РјРѕ С†Рµ.
        # Р’Р°Р¶Р»РёРІРѕ: РїС–СЃР»СЏ СЂСѓС…Сѓ РјРёС€РµСЋ СЃР°С€С– РќР• РїРµСЂРµСЂР°С…РѕРІСѓСЋС‚СЊСЃСЏ, С–РЅР°РєС€Рµ
        # ``_apply_sash_positions`` РїРѕРІРµСЂС‚Р°Р»Р° Р± С—С… РЅР° РјС–СЃС†Рµ Р№ РїР°РЅРµР»СЊ
        # В«РЅРµ СЂРѕР·С€РёСЂСЋРІР°Р»Р°СЃСЊВ» вЂ” СЃР°РјРµ РЅР° С†Рµ СЃРєР°СЂР¶РёРІСЃСЏ РєРѕСЂРёСЃС‚СѓРІР°С‡.
        self._user_dragging = False
        for widget in ("h_split", "v_split", "editor_split", "side_split"):
            split = getattr(self, widget, None)
            if split is None:
                continue
            split.bind("<ButtonPress-1>", self._on_sash_press, add="+")
            split.bind("<ButtonRelease-1>", self._on_sash_release, add="+")

        # РўРµРїРµСЂ, РєРѕР»Рё РІСЃС– РїР°РЅРµР»С– СЃС‚РІРѕСЂРµРЅС–, РјРѕР¶РЅР° Р±РµР·РїРµС‡РЅРѕ Р·Р°СЂРµС”СЃС‚СЂСѓРІР°С‚Рё
        # РєРѕРјР°РЅРґРё: РєРѕР¶РЅР° Р· РЅРёС… РїРѕСЃРёР»Р°С”С‚СЊСЃСЏ РЅР° СЂРµР°Р»СЊРЅС– РІС–РґР¶РµС‚Рё.
        self._register_commands()
        self._refresh_header()

    def _on_sash_press(self, _event=None) -> None:
        """РџРѕС‡Р°РІСЃСЏ СЂСѓС… РјРµР¶С–: РїРµСЂРµСЂР°С…СѓРЅРєРё СЂРѕР·РєР»Р°РґРєРё РЅР° РїР°СѓР·С–."""
        self._user_dragging = True
        job = getattr(self, "_resize_after", None)
        if job is not None:
            try:
                self.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
            self._resize_after = None

    # в”Ђв”Ђ РЅРѕРІР° С€Р°РїРєР° С‚Р° СЂРµС”СЃС‚СЂ РєРѕРјР°РЅРґ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _build_header(self, outer: tk.Misc) -> None:
        """Р—С–Р±СЂР°С‚Рё РІРµСЂС…РЅСЋ РїР°РЅРµР»СЊ С€РІРёРґРєРѕРіРѕ РґРѕСЃС‚СѓРїСѓ.

        РЁР°РїРєР° вЂ” С†Рµ РЅРµ В«РєСЂР°СЃРёРІР° СЃРјСѓР¶РєР°В»: РєРѕР¶РЅР° С—С— РєРЅРѕРїРєР° РІРёРєРѕРЅСѓС” С‚Сѓ СЃР°РјСѓ
        РєРѕРјР°РЅРґСѓ, С‰Рѕ Р№ РїСѓРЅРєС‚ РјРµРЅСЋ, Р±Рѕ РІСЃС– РІРѕРЅРё Р·Р°СЂРµС”СЃС‚СЂРѕРІР°РЅС– РІ
        :mod:`commands`. Р—Р°РІРґСЏРєРё С†СЊРѕРјСѓ РЅРµРјР°С” РґРІРѕС… СЃРїРёСЃРєС–РІ, СЏРєС– РјРѕР¶СѓС‚СЊ
        СЂРѕР·С–Р№С‚РёСЃСЊ.
        """
        self.header_bar = header_bar.HeaderBar(
            outer,
            self.theme,
            on_command=self.run_command,
            on_menu=self._header_menu,
            on_palette=self.command_palette,
            on_project_menu=lambda anchor: self._show_project_menu(anchor),
            on_model_menu=lambda anchor: self.show_model_selector(anchor=anchor),
            on_agent_menu=lambda anchor: self.show_mode_menu(anchor=anchor),
            on_git_menu=lambda anchor: self._show_git_menu(anchor),
            on_more_menu=lambda anchor: self._show_more_menu(anchor),
            # РљР»С–Рє РїРѕ РІРµР»РёРєРѕРјСѓ СЃС‚Р°С‚СѓСЃСѓ РјРѕРґРµР»С– РІС–РґРєСЂРёРІР°С” СЃР°РјРѕРґС–Р°РіРЅРѕСЃС‚РёРєСѓ:
            # РєРѕСЂРёСЃС‚СѓРІР°С‡ Р±Р°С‡РёС‚СЊ РЅРµ Р»РёС€Рµ В«РѕС„Р»Р°Р№РЅВ», Р° Р№ РїСЂРёС‡РёРЅСѓ.
            on_status_click=self._on_model_status_click,
        )
        self.header_bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        # Р СЏРґРѕРє С€Р°РїРєРё РјСѓСЃРёС‚СЊ РјР°С‚Рё Р’Р›РђРЎРќРЈ РІРёСЃРѕС‚Сѓ: Р±РµР· С†СЊРѕРіРѕ grid СЃС‚РёСЃРєР°РІ
        # С€Р°РїРєСѓ РґРѕ РІРјС–СЃС‚Сѓ (34 px), С– Р·Р±С–Р»СЊС€РµРЅС– С–РєРѕРЅРєРё РѕР±СЂС–Р·Р°Р»РёСЃСЊ Р·РІРµСЂС…Сѓ Р№
        # Р·РЅРёР·Сѓ. ``minsize`` С‚СЂРёРјР°С” РІРёСЃРѕС‚Сѓ, РЅР°РІС–С‚СЊ РєРѕР»Рё РґС–С‚Рё РЅРёР¶С‡С–.
        try:
            outer.rowconfigure(0, minsize=header_bar.HEADER_HEIGHT)
        except tk.TclError:
            pass
        # Р РµС”СЃС‚СЂР°С†С–СЋ РєРѕРјР°РЅРґ РІС–РґРєР»Р°РґРµРЅРѕ РґРѕ РєС–РЅС†СЏ ``_build_layout``: С‡Р°СЃС‚РёРЅР°
        # РєРѕРјР°РЅРґ РїРѕСЃРёР»Р°С”С‚СЊСЃСЏ РЅР° РІС–РґР¶РµС‚Рё (С‚РµСЂРјС–РЅР°Р», РІРєР»Р°РґРєРё, С‡Р°С‚), СЏРєРёС… РЅР°
        # РјРѕРјРµРЅС‚ СЃС‚РІРѕСЂРµРЅРЅСЏ С€Р°РїРєРё С‰Рµ РЅРµРјР°С”.

    def _register_commands(self) -> None:
        """РќР°РїРѕРІРЅРёС‚Рё СЂРµС”СЃС‚СЂ РєРѕРјР°РЅРґ (С–РґРµРјРїРѕС‚РµРЅС‚РЅРѕ).

        РЎР°РјР° С‚Р°Р±Р»РёС†СЏ Р¶РёРІРµ РІ :mod:`command_registry` вЂ” С‚СѓС‚ Р»РёС€Р°С”С‚СЊСЃСЏ
        Р»РёС€Рµ РґРµР»РµРіСѓРІР°РЅРЅСЏ, С‰РѕР± СЂРµС€С‚Р° РєРѕРґСѓ РєР»РёРєР°Р»Р° СЏРє СЂР°РЅС–С€Рµ.
        """
        command_registry.register_all(self)
    def run_command(self, key: str) -> bool:
        """Р’РёРєРѕРЅР°С‚Рё РєРѕРјР°РЅРґСѓ Р· СЂРµС”СЃС‚СЂСѓ (С€Р°РїРєР°, РїР°Р»С–С‚СЂР°, РјРµРЅСЋ вЂ” СѓСЃРµ С‡РµСЂРµР· РЅРµС—)."""
        command = commands.get(key)
        if command is None:
            LOG.debug("РќРµРІС–РґРѕРјР° РєРѕРјР°РЅРґР°: %s", key)
            return False
        ok = command.run()
        if not ok and command.enabled is not None:
            self.set_status(f"В«{command.label}В» Р·Р°СЂР°Р· РЅРµРґРѕСЃС‚СѓРїРЅР°.")
        self._refresh_header()
        return ok

    def _refresh_header(self) -> None:
        """РџРѕРєР°Р·Р°С‚Рё РІ С€Р°РїС†С– СЂРµР°Р»СЊРЅРёР№ СЃС‚Р°РЅ (РЅРµ РІРёРіР°РґР°РЅРёР№)."""
        bar = getattr(self, "header_bar", None)
        if bar is None:
            return
        name = Path(self.settings.workspace).name if self.has_project() else ""
        bar.set_project(name, workspace=str(self.settings.workspace or ""))
        try:
            mode = modes.get(getattr(self, "agent_mode", modes.DEFAULT_MODE))
            bar.set_agent(mode.label, busy=bool(getattr(self.chat, "_busy", False)))
        except Exception:  # noqa: BLE001 - С€Р°РїРєР° РЅРµ РјР°С” Р»Р°РјР°С‚Рё СЃС‚Р°СЂС‚
            LOG.debug("Р РµР¶РёРј Р°РіРµРЅС‚Р° РЅРµРґРѕСЃС‚СѓРїРЅРёР№", exc_info=True)
        entry = providers.current_entry(self.settings)
        bar.set_model(entry.name, local=entry.is_local, online=entry.online)
        # Git-С‡РёРї СЂР°РЅС–С€Рµ С‡РёС‚Р°РІ ``_git_branch``/``_git_changes``, СЏРєС–
        # РќР†РљРћР›Р РЅРµ РїСЂРёСЃРІРѕСЋРІР°Р»РёСЃСЊ вЂ” С‚РѕР±С‚Рѕ Р·Р°РІР¶РґРё РїРѕРєР°Р·СѓРІР°РІ В«в‘‚ вЂ”В».
        # РўРµРїРµСЂ Р±РµСЂРµРјРѕ СЃРїСЂР°РІР¶РЅС– РґР°РЅС– (Р· РєРµС€РµРј: _refresh_header С‡Р°СЃС‚РёР№).
        branch, changes = self._git_badge_state()
        bar.set_git(branch, changes)
        for key in ("file.save", "edit.undo", "edit.redo", "agent.stop"):
            command = commands.get(key)
            if command is not None:
                bar.set_command_enabled(key, command.is_enabled())

    def _git_badge_state(self) -> tuple[str, int]:
        """Р“С–Р»РєР° Р№ РєС–Р»СЊРєС–СЃС‚СЊ Р·РјС–РЅ РґР»СЏ С€Р°РїРєРё (РєРµС€ 15 СЃ, С‰РѕР± РЅРµ СЃРјРёРєР°С‚Рё git).

        ``git`` вЂ” Р·РѕРІРЅС–С€РЅС–Р№ РїСЂРѕС†РµСЃ; РІРёРєР»РёРєР°С‚Рё Р№РѕРіРѕ РЅР° РєРѕР¶РЅРµ РѕРЅРѕРІР»РµРЅРЅСЏ С€Р°РїРєРё
        РѕР·РЅР°С‡Р°Р»Рѕ Р± РґРµСЃСЏС‚РєРё Р·Р°РїСѓСЃРєС–РІ РЅР° СЃРµРєСѓРЅРґСѓ. РўРѕРјСѓ РєРµС€СѓС”РјРѕ, Р° git-РєРѕРјР°РЅРґР°
        Р№РґРµ Р»РёС€Рµ РєРѕР»Рё С‚РµРєР° СЃРїСЂР°РІРґС– С” СЂРµРїРѕР·РёС‚РѕСЂС–С”Рј.
        """
        root = self._project_root()
        if root is None:
            return "", 0
        now = time.time()
        cached = getattr(self, "_git_badge_cache", None)
        if cached is not None and (now - cached[0]) < 15.0:
            return cached[1], cached[2]
        branch = ""
        changes = 0
        try:
            branch = diff_stats.git_branch(root)
            if branch:
                change_set = diff_stats.detect_changes(root, prefer_git=True)
                changes = len(getattr(change_set, "files", []) or [])
        except Exception:  # noqa: BLE001 - С€Р°РїРєР° РЅРµ РјР°С” Р»Р°РјР°С‚Рё РІС–РєРЅРѕ
            LOG.debug("РЎС‚Р°РЅ git РґР»СЏ С€Р°РїРєРё РЅРµРґРѕСЃС‚СѓРїРЅРёР№", exc_info=True)
        self._git_badge_cache = (now, branch, changes)
        return branch, changes

    def _header_menu(self, which: str, anchor=None) -> None:
        """РњРµРЅСЋ С€Р°РїРєРё: ``git`` С– В«в‹ЇВ».

        РћРєСЂРµРјС– РїСѓРЅРєС‚Рё В«Р¤Р°Р№Р»/РџСЂР°РІРєР°/Р’РёРіР»СЏРґВ» С‚СѓС‚ РЅРµ РїРѕС‚СЂС–Р±РЅС–: Сѓ РІС–РєРЅР° РІР¶Рµ С”
        СЃРїСЂР°РІР¶РЅС” РЅР°С‚РёРІРЅРµ РјРµРЅСЋ (``_build_menu``), С– РґСѓР±Р»СЋРІР°С‚Рё Р№РѕРіРѕ РІ С€Р°РїС†С–
        РѕР·РЅР°С‡Р°Р»Рѕ РїРѕРєР°Р·СѓРІР°С‚Рё С‚РѕР№ СЃР°РјРёР№ СЃРїРёСЃРѕРє РґРІС–С‡С–.
        """
        if which == "git":
            self._show_git_menu(anchor)
        elif which == "more":
            self._show_more_menu(anchor)

    def _menu_items_for(self, group: str) -> list[tuple[str, Optional[object]]]:
        """РџСѓРЅРєС‚Рё РјРµРЅСЋ РіСЂСѓРїРё: ``(РїС–РґРїРёСЃ, РґС–СЏ|None)``; ``None`` вЂ” СЂРѕР·РґС–Р»СЋРІР°С‡."""
        rows: list[tuple[str, Optional[object]]] = []
        for command in commands.all_commands():
            if command.group != group or command.level == commands.PRIMARY:
                continue
            if command.level not in (commands.MENU, commands.PALETTE):
                continue
            label = command.label
            if command.shortcut:
                label = f"{label}\t{command.shortcut}"
            if not command.is_enabled():
                # РќРµРґРѕСЃС‚СѓРїРЅС– РїСѓРЅРєС‚Рё Р»РёС€Р°С”РјРѕ РІРёРґРёРјРёРјРё, Р°Р»Рµ Р±РµР· РґС–С—.
                rows.append((label, None))
            else:
                rows.append((label, command.run))
        return rows

    def _popup(self, anchor, rows: list[tuple[str, Optional[object]]]) -> None:
        """РџРѕРєР°Р·Р°С‚Рё РІРёРїР°РґР°СЋС‡Рµ РјРµРЅСЋ Р±С–Р»СЏ РєРЅРѕРїРєРё С€Р°РїРєРё."""
        if not rows:
            return
        try:
            x = anchor.winfo_rootx()
            y = anchor.winfo_rooty() + anchor.winfo_height()
        except tk.TclError:
            return
        try:
            widgets.context_menu(self, rows, _Point(x, y))
        except tk.TclError:
            return

    def _show_git_menu(self, anchor=None) -> None:
        rows = self._menu_items_for("git")
        self._popup(anchor or self.header_bar.git_btn, rows)

    def _show_more_menu(self, anchor=None) -> None:
        """В«в‹ЇВ»: СѓСЃРµ, С‰Рѕ РЅРµ РїРѕС‚СЂР°РїРёР»Рѕ РЅР° С€Р°РїРєСѓ вЂ” Р¶РѕРґРЅР° РєРѕРјР°РЅРґР° РЅРµ РіСѓР±РёС‚СЊСЃСЏ."""
        rows: list[tuple[str, Optional[object]]] = []
        for category in commands.categories_present():
            items = [command for command in commands.all_commands()
                     if command.category == category
                     and command.level != commands.PRIMARY]
            if not items:
                continue
            if rows:
                rows.append(("", None))
            rows.append((f"вЂ” {category} вЂ”", None))
            for command in items:
                label = command.label
                if command.shortcut:
                    label = f"{label}\t{command.shortcut}"
                rows.append((label, command.run if command.is_enabled() else None))
        self._popup(anchor or self.header_bar.more_btn, rows)

    def _show_project_menu(self, anchor=None) -> None:
        rows: list[tuple[str, Optional[object]]] = [
            ("Р’С–РґРєСЂРёС‚Рё РїР°РїРєСѓвЂ¦", self.open_folder_dialog),
            ("РЎС‚РІРѕСЂРёС‚Рё РїСЂРѕС”РєС‚вЂ¦", self.create_project_folder),
        ]
        recent = [path for path in getattr(self.settings, "recent", []) if path]
        if recent:
            rows.append(("", None))
            rows.append(("вЂ” РћСЃС‚Р°РЅРЅС– вЂ”", None))
            for path in recent[:8]:
                label = f"{Path(path).name}  В·  {path}"
                rows.append((label, lambda p=path: self.open_recent_folder(p)))
        self._popup(anchor or self.header_bar.project_btn, rows)

    def _on_sash_release(self, _event=None) -> None:
        """Р СѓС… Р·Р°РІРµСЂС€РµРЅРѕ: Р·Р±РµСЂС–РіР°С”РјРѕ РЅРѕРІРёР№ СЂРѕР·РјС–СЂ С– РїРѕРІРµСЂС‚Р°С”РјРѕ СЂРѕР·СЂР°С…СѓРЅРєРё."""
        self._user_dragging = False
        self._remember_layout()

    #: Р—РІРѕСЂРѕС‚РЅР° СЃСѓРјС–СЃРЅС–СЃС‚СЊ: СЂР°РЅС–С€Рµ С†Рµ Р±СѓР»Р° РѕРєСЂРµРјР° СЂРµР№РєР° С–РєРѕРЅРѕРє.
    @property
    def rail(self) -> tk.Widget:
        """Р РµР№РєР° РЅР°РІС–РіР°С†С–С— вЂ” С‚РµРїРµСЂ С†Рµ Р·Р°РіРѕР»РѕРІРѕРє Р±С–С‡РЅРѕС— РїР°РЅРµР»С–."""
        return getattr(self, "nav_head", self.sidebar)

    # 1. Р‘С–С‡РЅР° РїР°РЅРµР»СЊ: РЅР°РІС–РіР°С†С–СЏ, РїСЂРѕС”РєС‚, С–СЃС‚РѕСЂС–СЏ СЃРµСЃС–Р№, РїР°РЅРµР»С– СЂРѕР·РґС–Р»С–РІ
    def _build_sidebar(self, outer: tk.Misc) -> None:
        self.sidebar = tk.Frame(outer, bg=theme.BG_ALT,
                                width=self.settings.ui.sidebar_width,
                                bd=0, highlightthickness=0)
        # Р”С–С‚Рё РїР°РЅРµР»С– РїР°РєСѓСЋС‚СЊСЃСЏ, С‚РѕРјСѓ СЃР°РјРµ pack_propagate С‚СЂРёРјР°С” С€РёСЂРёРЅСѓ.
        self.sidebar.pack_propagate(False)
        try:
            self.side_split.add(self.sidebar, weight=0)
        except (AttributeError, tk.TclError):
            LOG.debug("РџР°РЅРµР»СЊ РЅРµ РґРѕРґР°Р»Р°СЃСЊ Сѓ PanedWindow", exc_info=True)
            self.sidebar.grid(row=0, column=0, sticky="ns")

        # в”Ђв”Ђ Р±СЂРµРЅРґ + Р·РіРѕСЂС‚Р°РЅРЅСЏ
        head = tk.Frame(self.sidebar, bg=theme.BG_ALT)
        head.pack(fill="x", padx=theme.SPACE_LG, pady=(theme.SPACE_LG, theme.SPACE_MD))
        self.nav_head = head

        self.brand_icon = tk.Label(head, text="в—¤", bg=theme.BG_ALT, fg=theme.ACCENT,
                                   font=("Segoe UI", 13, "bold"))
        self.brand_icon.pack(side="left")
        self.brand_label = tk.Label(head, text="BlackChpok", bg=theme.BG_ALT,
                                    fg=theme.FG_BRIGHT, font=self.theme.ui_h2, anchor="w")
        self.brand_label.pack(side="left", padx=(theme.SPACE_SM, 0))
        self.collapse_btn = widgets.IconButton(
            head, "В«", self.toggle_sidebar, bg=theme.BG_ALT, fg=theme.FG_FAINT,
            font=("Segoe UI", 9), tooltip="Р—РіРѕСЂРЅСѓС‚Рё РїР°РЅРµР»СЊ (Ctrl+B)")
        self.collapse_btn.pack(side="right")

        # в”Ђв”Ђ РіРѕР»РѕРІРЅР° РґС–СЏ: РЅРѕРІРёР№ С‡Р°С‚ (РїС–РґРїРёСЃ СѓРєСЂР°С—РЅСЃСЊРєРѕСЋ)
        self.new_session_btn = tk.Label(
            self.sidebar, text="пј‹  РќРѕРІРёР№ С‡Р°С‚", bg=theme.BTN_BG, fg=theme.BTN_FG,
            font=("Segoe UI", 10, "bold"), padx=12, pady=8, cursor="hand2", anchor="w",
        )
        self.new_session_btn.pack(fill="x", padx=theme.SPACE_MD, pady=(0, theme.SPACE_MD))
        self.new_session_btn.bind("<Enter>", lambda _e: self.new_session_btn.configure(bg=theme.BTN_HOVER))
        self.new_session_btn.bind("<Leave>", lambda _e: self.new_session_btn.configure(bg=theme.BTN_BG))
        self.new_session_btn.bind("<Button-1>", lambda _e: self.new_chat_session())
        widgets.Tip(self.new_session_btn, "РЎС‚РІРѕСЂРёС‚Рё РЅРѕРІРѕРіРѕ Р°РіРµРЅС‚Р° (Ctrl+Alt+N)")

        # в”Ђв”Ђ РјРµРЅСЋ СЂРѕР·РґС–Р»С–РІ РџР РР‘Р РђРќРћ: Р»С–РІРѕСЂСѓС‡ Р»РёС€РёР»РёСЃСЊ СЃР°РјС– С‡Р°С‚Рё.
        # Р Р°РЅС–С€Рµ С‚СѓС‚ СЃС‚РѕСЏР»Рё В«Р§Р°С‚Рё Р№ Р°РіРµРЅС‚РёВ», В«MCP ToolsВ», В«РџСЂРѕС”РєС‚РёВ», В«Р‘Р°Р·Р°
        # Р·РЅР°РЅСЊВ», В«РќР°Р»Р°С€С‚СѓРІР°РЅРЅСЏВ» вЂ” Рї'СЏС‚СЊ РїСѓРЅРєС‚С–РІ, СЏРєС– Р·Р°Р№РјР°Р»Рё РјС–СЃС†Рµ РІ
        # РєРѕР»РѕРЅС†С–, РїСЂРёР·РЅР°С‡РµРЅС–Р№ РґР»СЏ СЂРѕР·РјРѕРІ. РўРµРїРµСЂ СѓСЃРµ С†Рµ РІ РјРµРЅСЋ В«Р’РёРіР»СЏРґВ» С–
        # РІ РґС–Р°Р»РѕР·С– РЅР°Р»Р°С€С‚СѓРІР°РЅСЊ, Р° Р»С–РІР° РїР°РЅРµР»СЊ РїРѕРєР°Р·СѓС” Р»РёС€Рµ С‡Р°С‚Рё.
        self.nav_host = None
        self._nav_buttons: dict[str, nav_sidebar.NavButton] = {}

        # в”Ђв”Ђ С€РІРёРґРєРёР№ РґРѕСЃС‚СѓРї: С‚Рµ, С‰Рѕ РїРѕС‚СЂС–Р±РЅРѕ С‰РѕС…РІРёР»РёРЅРё.
        # Р¦Рµ РќР• РјРµРЅСЋ СЂРѕР·РґС–Р»С–РІ (Р№РѕРіРѕ СЃРІС–РґРѕРјРѕ РїСЂРёР±СЂР°РЅРѕ): С‡РѕС‚РёСЂРё С†С–Р»С– вЂ”
        # С‡Р°С‚Рё, С†РµРЅС‚СЂ Р·Р°РІРґР°РЅСЊ, С„Р°Р№Р»Рё РїСЂРѕС”РєС‚Сѓ Р№ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏ. РљРѕР¶РЅР° РІРµРґРµ РЅР°
        # СЂРµР°Р»СЊРЅСѓ РїР°РЅРµР»СЊ, С‚РѕР¶ РєРѕСЂРёСЃС‚СѓРІР°С‡Сѓ РЅРµ С‚СЂРµР±Р° С€СѓРєР°С‚Рё С—С… Сѓ РјРµРЅСЋ.
        nav_row = tk.Frame(self.sidebar, bg=theme.BG_ALT)
        nav_row.pack(fill="x", padx=theme.SPACE_MD, pady=(0, theme.SPACE_SM))
        self.quick_nav: dict[str, widgets.HoverLabel] = {}
        for key, caption, command, tip in (
            ("chats", "в—Ќ Р§Р°С‚Рё", lambda: self.show_side("chats"),
             "Р†СЃС‚РѕСЂС–СЏ СЂРѕР·РјРѕРІ С– Р¶РёРІС– СЃРµСЃС–С— Р°РіРµРЅС‚Р°"),
            ("tasks", "в‰Ў Р—Р°РІРґР°РЅРЅСЏ", lambda: self.show_bottom("tasks"),
             "Р§РµСЂРіР° РєСЂРѕРєС–РІ Р»РѕРєР°Р»СЊРЅРѕРіРѕ Р°РіРµРЅС‚Р° (Ctrl+Alt+W)"),
            ("explorer", "в–¤ Р¤Р°Р№Р»Рё", lambda: self.show_side("explorer"),
             "Р¤Р°Р№Р»Рё Р№ РїР°РїРєРё РїСЂРѕС”РєС‚Сѓ"),
            ("settings", "вљ™", self.open_settings,
             "РќР°Р»Р°С€С‚СѓРІР°РЅРЅСЏ (Ctrl+,)"),
        ):
            chip = widgets.HoverLabel(
                nav_row, text=caption, command=command, bg=theme.BG_ALT,
                fg=theme.FG_FAINT, hover_bg=theme.BG_HOVER,
                hover_fg=theme.FG_BRIGHT, active_bg=theme.BG_ACTIVE,
                active_fg=theme.FG_BRIGHT, font=("Segoe UI", 8),
                padx=theme.SPACE_SM, pady=2, anchor="center")
            chip.pack(side="left", padx=(0, 2))
            widgets.Tip(chip, tip)
            self.quick_nav[key] = chip

        widgets.Divider(self.sidebar, colour=theme.BORDER, padx=theme.SPACE_MD)

        # в”Ђв”Ђ СЃРјСѓРіР° В«РЅР°Р·Р°РґВ» РґР»СЏ РїР°РЅРµР»РµР№, РІС–РґРєСЂРёС‚РёС… С–Р· РЅР°Р»Р°С€С‚СѓРІР°РЅСЊ.
        # РЎР°Рј Р·Р°РіРѕР»РѕРІРѕРє (В«Р§РђРўР Р™ РђР“Р•РќРўРВ») РЅРµ РјР°Р»СЋС”РјРѕ: РєРѕР»Рё Р»С–РІРѕСЂСѓС‡ Р»РёС€РёР»РёСЃСЊ
        # С‚С–Р»СЊРєРё С‡Р°С‚Рё, РІС–РЅ РґСѓР±Р»СЋРІР°РІ РІРєР»Р°РґРєСѓ СЃРїРёСЃРєСѓ С‚РёРј СЃР°РјРёРј СЃР»РѕРІРѕРј.
        panel_head = tk.Frame(self.sidebar, bg=theme.BG_ALT)
        panel_head.pack(fill="x", padx=theme.SPACE_LG, pady=(theme.SPACE_MD, 2))

        self.panel_home = widgets.HoverLabel(
            panel_head, text="", command=self._panel_home, bg=theme.BG_ALT,
            fg=theme.FG_DIM, hover_bg=theme.BG_ALT, hover_fg=theme.FG_BRIGHT,
            font=("Segoe UI", 10), padx=0, pady=0, anchor="w")
        self.panel_home.pack(side="left", padx=(0, theme.SPACE_SM))

        self.panel_title = tk.Label(panel_head, text="", bg=theme.BG_ALT,
                                    fg=theme.FG_FAINT, font=self.theme.ui_tiny, anchor="w")
        self.panel_title.pack(side="left")

        # в”Ђв”Ђ СЃС‚РµРє РїР°РЅРµР»РµР№ СЂРѕР·РґС–Р»С–РІ: С–СЃС‚РѕСЂС–СЏ СЃРµСЃС–Р№, С„Р°Р№Р»Рё, RAG, MCPвЂ¦
        # Р¦Рµ С– С” В«С–СЃС‚РѕСЂС–СЏ СЃРµСЃС–Р№ С– СЂРѕР±РѕС‡С– РїСЂРѕС”РєС‚РёВ» Р· РјР°РєРµС‚Р°: РґР»СЏ СЂРѕР·РґС–Р»Сѓ
        # В«Р§Р°С‚РёВ» С‚СѓС‚ Р¶РёРІРµ Р¶РёРІРёР№ СЃРїРёСЃРѕРє СЂРѕР·РјРѕРІ Р·С– СЃС…РѕРІРёС‰Р°.
        self.side_stack = tk.Frame(self.sidebar, bg=theme.BG_ALT)
        self.side_stack.pack(fill="both", expand=True)

        self.chat_list = chat_list_panel.ChatListPanel(
            self.side_stack, self.theme, store=self.chat_store,
            on_open=self.open_chat, on_new=self.new_chat_session,
            on_status=self.set_status,
            on_close_chat=self.close_chat,
            on_cleared=self._after_chats_cleared,
        )

        self.cases_panel = cases_panel.CasesPanel(
            self.side_stack, self.theme, self.case_book,
            on_status=self.set_status,
            on_focus_chat=lambda: self.show_chat(True),
        )

        self.autonomous_panel = autonomous_panel.AutonomousPanel(
            self.side_stack, self.theme, self.autonomous_engine,
            on_start=self.start_autonomous,
            on_stop=self.stop_autonomous,
            on_add_task=self.add_autonomous_task,
            on_pick_project=self.pick_autonomous_project,
            on_status=self.set_status,
            on_open_file=self._open_relative,
        )

        self.rag_panel = rag_panel.RagPanel(
            self.side_stack, self.theme, self.rag_service,
            on_open_path=lambda path, line: self.open_path(Path(path), line),
            on_insert_context=self._insert_rag_context,
            on_status=self.set_status,
        )

        self.tools_panel = tools_panel.ToolsPanel(
            self.side_stack, self.theme, self.registry,
            mcp_manager=self.mcp_manager,
            on_status=self.set_status,
            on_result=self._on_tool_result,
        )

        self.file_tree = FileTree(self.side_stack, self.open_path,
                                  root_dir=(Path(self.settings.workspace)
                                            if self.has_project() else None))
        self.file_tree.on_status = self.set_status
        self.file_tree.on_terminal = lambda folder: (self.terminal.set_cwd(folder),
                                                     self.show_bottom("terminal"))

        self.outline = OutlinePanel(self.side_stack, self.theme, on_goto=self._goto_line)
        self.skills_panel = skills_panel.SkillsPanel(
            self.side_stack, self.theme, self.skill_book,
            on_status=self.set_status,
            on_use=self._use_skill,
            on_queue=self._queue_skill,
            on_open_file=lambda path: self.open_path(Path(path)),
        )
        self.queue_panel = queue_panel.QueuePanel(
            self.side_stack, self.theme, self.task_queue,
            on_run_next=self.run_next_task,
            on_status=self.set_status,
            on_show_task=self._show_queue_task,
            on_changed=self._update_queue_badge,
        )
        # Р—Р°РґР°С‡С– С‡РµСЂРіРё РїСЂРёРІ'СЏР·СѓСЋС‚СЊСЃСЏ РґРѕ Р°РєС‚РёРІРЅРѕРіРѕ С‡Р°С‚Сѓ: РєРѕР»Рё С‡Р°С‚ РІРёРґР°Р»СЏСЋС‚СЊ,
        # Р№РѕРіРѕ Р·Р°РґР°С‡С– Р·РЅРёРєР°СЋС‚СЊ СЂР°Р·РѕРј С–Р· РЅРёРј, Р° РЅРµ РІРёРєРѕРЅСѓСЋС‚СЊСЃСЏ В«РІ РЅС–РєСѓРґРёВ».
        self.queue_panel.chat_id_provider = lambda: str(
            getattr(self.chat_store, "active_id", "") or "")
        self.mcp_panel = mcp_panel.McpPanel(
            self.side_stack, self.theme, self.mcp_manager,
            self._project_root,
            on_status=self.set_status,
            on_restart=self.reload_mcp,
            # РќР°РіР»СЏРґР°С‡ РїРµСЂРµРґР°С”С‚СЊСЃСЏ РїР°РЅРµР»С–: С–РЅР°РєС€Рµ В«Р”С–Р°РіРЅРѕСЃС‚РёРєР°В» РЅРµРґРѕСЃСЏР¶РЅР°, Р°
            # СЃРµСЂРІРµСЂРё, РїС–РґРЅСЏС‚С– Р· РїР°РЅРµР»С–, Р»РёС€Р°СЋС‚СЊСЃСЏ Р±РµР· РєРѕРЅС‚СЂРѕР»СЋ Р¶РёРІСѓС‡РѕСЃС‚С–.
            watcher=getattr(self, "mcp_watcher", None),
        )
        self.changes_panel = changes_panel.ChangesPanel(
            self.side_stack, self.theme, self._project_root,
            on_open_path=lambda path: self.open_path(Path(path)),
            on_status=self.set_status,
            on_show_diff=self.show_diff_for,
        )
        # в”Ђв”Ђ Р’Р»Р°СЃРЅРёР№ СЂСѓС€С–Р№ С– РїР°Рј'СЏС‚СЊ NEUROMESH в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        # РћР±РёРґРІС– РїР°РЅРµР»С– РїСЂР°С†СЋСЋС‚СЊ С–Р· Р¶РёРІРёРјРё СЃРµСЂРІС–СЃР°РјРё РІС–РєРЅР°: СЂСѓС€С–Р№ РѕРґРёРЅ РЅР°
        # РїСЂРѕС†РµСЃ (``native_runtime``), РїР°Рј'СЏС‚СЊ вЂ” РѕРґРЅР° Р±Р°Р·Р° РЅР° РєРѕСЂРёСЃС‚СѓРІР°С‡Р°.
        self.runtime_panel = runtime_panel.RuntimePanel(
            self.side_stack, self.theme, lambda: self.native_runtime,
            on_model_activated=self._on_native_model,
            on_status=self.set_status,
        )
        self.neuromesh_panel = neuromesh_panel.NeuromeshPanel(
            self.side_stack, self.theme, lambda: self.memory,
            on_open_memory=self._show_memory_item,
            on_status=self.set_status,
        )
        self._side_widgets = {
            "chats": self.chat_list,
            "cases": self.cases_panel,
            "autonomous": self.autonomous_panel,
            "rag": self.rag_panel,
            "tools": self.tools_panel,
            "explorer": self.file_tree,
            "outline": self.outline,
            "changes": self.changes_panel,
            "skills": self.skills_panel,
            "queue": self.queue_panel,
            "mcp": self.mcp_panel,
            "runtime": self.runtime_panel,
            "neuromesh": self.neuromesh_panel,
        }

        # в”Ђв”Ђ РїС–РґРІР°Р»: СЂРѕР±РѕС‡Р° С‚РµРєР° Р№ Р»РѕРєР°Р»СЊРЅРёР№ СЃС‚Р°РЅ
        foot = tk.Frame(self.sidebar, bg=theme.BG_ALT)
        foot.pack(fill="x", side="bottom", padx=theme.SPACE_SM, pady=(0, theme.SPACE_SM))
        self.nav_foot = foot

        self.project_row = tk.Frame(foot, bg=theme.BG_ALT, cursor="hand2")
        self.project_row.pack(fill="x")
        self.project_icon = tk.Label(self.project_row, text="рџ—‚", bg=theme.BG_ALT,
                                     fg=theme.FG_FAINT, font=("Segoe UI", 9))
        self.project_icon.pack(side="left", padx=(theme.SPACE_SM, theme.SPACE_SM))
        self.project_label = tk.Label(self.project_row, text="РЅРµ РѕР±СЂР°РЅРѕ", bg=theme.BG_ALT,
                                      fg=theme.FG_DIM, font=("Segoe UI", 8), anchor="w")
        self.project_label.pack(side="left", fill="x", expand=True, pady=2)
        for widget in (self.project_row, self.project_icon, self.project_label):
            widget.bind("<Button-1>", lambda _e: self.open_folder_dialog())
        widgets.Tip(self.project_row, "Р—РјС–РЅРёС‚Рё СЂРѕР±РѕС‡Сѓ С‚РµРєСѓ РїСЂРѕС”РєС‚Сѓ")

        state_row = tk.Frame(foot, bg=theme.BG_ALT)
        state_row.pack(fill="x")
        self.local_label = tk.Label(state_row, text="в—Џ Р»РѕРєР°Р»СЊРЅРѕ", bg=theme.BG_ALT,
                                    fg=theme.FG_FAINT, font=("Segoe UI", 8), anchor="w")
        self.local_label.pack(side="left", padx=(theme.SPACE_SM, 0), pady=(0, 2))
        widgets.Tip(self.local_label, "Local-first: РґР°РЅС– Р№ РјРѕРґРµР»С– Р»РёС€Р°СЋС‚СЊСЃСЏ РЅР° С†СЊРѕРјСѓ РєРѕРјРї'СЋС‚РµСЂС–")
        widgets.IconButton(state_row, "в—”", self.open_settings, bg=theme.BG_ALT,
                           fg=theme.FG_FAINT, font=("Segoe UI", 10),
                           tooltip="РќР°Р»Р°С€С‚СѓРІР°РЅРЅСЏ (Ctrl+,)").pack(side="right")

    # 2. Р¦РµРЅС‚СЂ: Р·Р°РіРѕР»РѕРІРѕРє СЃРµСЃС–С— + СЂРѕР±РѕС‡Р° РѕР±Р»Р°СЃС‚СЊ
    def _build_centre(self, outer: tk.Misc) -> None:
        self.main_area = tk.Frame(outer, bg=theme.BG, bd=0, highlightthickness=0)
        self.main_area.columnconfigure(0, weight=1)
        self.main_area.rowconfigure(1, weight=1)
        try:
            self.side_split.add(self.main_area, weight=1)
        except (AttributeError, tk.TclError):
            self.main_area.grid(row=0, column=1, sticky="nsew")

        from tkinter import ttk

        # 2a. Р—Р°РіРѕР»РѕРІРѕРє СЃРµСЃС–С— вЂ” РЅР° РІСЃСЋ С€РёСЂРёРЅСѓ СЂРѕР±РѕС‡РѕС— РѕР±Р»Р°СЃС‚С–.
        self.header = session_header.SessionHeader(
            self.main_area, self.theme,
            on_modes=self.show_mode_menu,
            on_model=self.show_model_selector,
            on_view=self.set_view,
            on_workspace=lambda: self.set_view("workspace"),
            on_context=self.toggle_context,
            on_chat_mode=self.show_chat_mode_menu,
        )
        self.header.grid(row=0, column=0, sticky="ew")

        # 2b. Р“РѕСЂРёР·РѕРЅС‚Р°Р»СЊРЅРёР№ РїРѕРґС–Р»: РґС–Р°Р»РѕРі | СЂРѕР±РѕС‡Р° РѕР±Р»Р°СЃС‚СЊ | РєРѕРЅС‚РµРєСЃС‚.
        self.h_split = ttk.PanedWindow(self.main_area, orient="horizontal")
        self.h_split.grid(row=1, column=0, sticky="nsew")

        # в”Ђв”Ђ РєРѕР»РѕРЅРєР° РґС–Р°Р»РѕРіСѓ (Р¦Р•РќРўР РђР›Р¬РќРђ)
        self.conversation_host = tk.Frame(self.h_split, bg=theme.BG, bd=0,
                                          highlightthickness=0)
        self.conversation_host.columnconfigure(0, weight=1)
        self.conversation_host.rowconfigure(0, weight=1)
        self.chat_column = self.conversation_host

        # Р’РµСЂС‚РёРєР°Р»СЊРЅРёР№ РїРѕРґС–Р»: СЃС‚СЂС–С‡РєР° РґС–Р°Р»РѕРіСѓ Р·РІРµСЂС…Сѓ, РєРѕРјРїРѕР·РµСЂ Р·РЅРёР·Сѓ.
        self.v_split = ttk.PanedWindow(self.conversation_host, orient="vertical")
        self.v_split.grid(row=0, column=0, sticky="nsew")

        # РљРѕРјРїРѕР·РµСЂ Р¶РёРІРµ Сѓ РІР»Р°СЃРЅС–Р№ РІС–РґС†РµРЅС‚СЂРѕРІР°РЅС–Р№ РєРѕР»РѕРЅС†С– вЂ” С‚С–С”С— СЃР°РјРѕС— С€РёСЂРёРЅРё,
        # С‰Рѕ Р№ СЃС‚СЂС–С‡РєР° РґС–Р°Р»РѕРіСѓ, С‚РѕР¶ РїРѕР»Рµ РІРІРѕРґСѓ РЅРµ СЂРѕР·С‚СЏРіСѓС”С‚СЊСЃСЏ РЅР° РІРµСЃСЊ РµРєСЂР°РЅ.
        self.composer_host = widgets.CenteredColumn(
            self.conversation_host, bg=theme.BG_ALT,
            max_width=int(getattr(self.settings.ui, "chat_max_width", 0)
                          or theme.CHAT_MAX_WIDTH),
            gutter=theme.SPACE_XL,
        )

        self.chat = ChatPanel(self.conversation_host, self.theme, self.settings,
                              self.registry, on_status=self.set_status,
                              composer_parent=self.composer_host.inner)
        self.chat.on_apply_code = self._apply_code_from_chat
        self.chat.on_queue_task = self._queue_from_chat
        self.chat.on_split_task = self._split_task_to_queue
        self.chat.on_open_queue = lambda: self.show_side("queue")
        self.chat.on_open_skills = lambda: self.show_side("skills")
        self.chat.on_new_chat = self._on_new_chat
        self.chat.on_busy_change = self._on_chat_busy
        self.chat.on_message = self._remember_message
        # РџС–РґРєР°Р·РєРё РЅР°Рґ РїРѕР»РµРј (В«РџРѕСЏСЃРЅРё С„Р°Р№Р»В» С‚РѕС‰Рѕ) РјР°СЋС‚СЊ Р±Р°С‡РёС‚Рё СЂРµР°Р»СЊРЅРёР№ С„Р°Р№Р».
        # Р—РІРµСЂС‚Р°С”РјРѕСЃСЊ Р»С–РЅРёРІРѕ: РІРєР»Р°РґРєРё СЃС‚РІРѕСЂСЋСЋС‚СЊСЃСЏ РїС–Р·РЅС–С€Рµ Р·Р° РїР°РЅРµР»СЊ С‡Р°С‚Сѓ,
        # С‚РѕР¶ РїСЂСЏРјРµ ``self.tabs`` С‚СѓС‚ РїР°РґР°Р»Рѕ Р· AttributeError РЅР° СЃС‚Р°СЂС‚С–.
        self.chat.current_path_provider = self._current_editor_path
        self.chat.on_permission_change = self._on_permission_change
        self.chat.on_set_goal = self._set_goal
        self.chat.on_feedback = self._save_feedback
        self.chat.on_pick_model = self.show_model_selector
        self.chat.on_export = self.export_current_chat
        self.chat.on_use_skill = self._use_skill_by_name
        self.chat.on_model_pick = self._on_chat_model_pick
        # РџС–РіСѓР»РєРё РЅР°Рґ РїРѕР»РµРј РІРІРѕРґСѓ: С‚Р° СЃР°РјР° С‚РµРєР° Р№ С‚РѕР№ СЃР°РјРёР№ СЂРµР¶РёРј, С‰Рѕ Р№ Сѓ
        # С€Р°РїС†С–, Р°Р»Рµ С‚Р°Рј, РґРµ РєРѕСЂРёСЃС‚СѓРІР°С‡ РїРёС€Рµ Р·Р°РґР°С‡Сѓ.
        self.chat.on_workspace_menu = self.show_workspace_menu
        self.chat.on_mode_menu = self.show_mode_menu
        self.chat.on_effort_pick = self._on_chat_effort_pick
        self.chat.on_voice_query = self._on_voice_query
        self.chat.on_voice_action = self._on_voice_action
        # Р„РґРёРЅРёР№ С€Р»СЋР· РґРѕ Р°РіРµРЅС‚Р°: Р±РµР· РІРёР±СЂР°РЅРѕС— С‚РµРєРё РїСЂРѕС”РєС‚Сѓ Р·Р°РїРёС‚ РЅРµ СЃС‚Р°СЂС‚СѓС”.
        # Р Р°РЅС–С€Рµ РїРµСЂРµРІС–СЂРєР° СЃС‚РѕСЏР»Р° Р»РёС€Рµ РІ В«РќРѕРІРёР№ С‡Р°С‚В» С‚Р° В«Р’С–РґРєСЂРёС‚Рё С‡Р°С‚В», С‚РѕР¶
        # СЃС‚Р°СЂС‚РѕРІРёР№ РµРєСЂР°РЅ, РіРѕР»РѕСЃ, СЃРєС–Р»Рё Р№ С‡РµСЂРіР° Р·Р°РїСѓСЃРєР°Р»Рё Р°РіРµРЅС‚Р° Р· РґРѕРјР°С€РЅСЊРѕСЋ
        # С‚РµРєРѕСЋ РєРѕСЂРёСЃС‚СѓРІР°С‡Р°.
        self.chat.project_ready = self.has_project
        self.chat.on_need_project = self._show_project_gate
        # в”Ђв”Ђ РџС–РґР№РѕРј РјРѕРґРµР»С– РЅР° РїРµСЂС€Сѓ Р¶ РґС–СЋ РєРѕСЂРёСЃС‚СѓРІР°С‡Р° в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        # РњРѕРґРµР»СЊ РІРёРІР°РЅС‚Р°Р¶СѓС”С‚СЊСЃСЏ С‡РµСЂРµР· РїСЂРѕСЃС‚С–Р№ (С†Рµ РїСЂР°РІРёР»СЊРЅР° РµРєРѕРЅРѕРјС–СЏ VRAM),
        # Р°Р»Рµ СЂР°РЅС–С€Рµ РќР†РљРћР›Р РЅРµ РїС–РґРЅС–РјР°Р»Р°СЃСЊ РЅР°Р·Р°Рґ: ``model_keeper.reload()``
        # РЅРµ РІРёРєР»РёРєР°РІСЃСЏ РЅС–РґРµ. Р§РµСЂРµР· С†Рµ РїС–СЃР»СЏ 5 С…РІ РїР°СѓР·Рё РєРѕР¶РµРЅ Р·Р°РїРёС‚ РїР°РґР°РІ С–Р·
        # В«РјРѕРґРµР»СЊ РЅРµРґРѕСЃС‚СѓРїРЅР°В», С– Р·РґР°РІР°Р»РѕСЃСЊ, С‰Рѕ РІРѕРЅР° РІР·Р°РіР°Р»С– РЅРµ СЃС‚Р°СЂС‚СѓС”
        # (СЂРµР°Р»СЊРЅРёР№ Р»РѕРі: СЃС‚Р°СЂС‚ Рѕ 19:03, РІРёРІР°РЅС‚Р°Р¶РµРЅРЅСЏ Рѕ 19:08, РїРѕРјРёР»РєР° Рѕ 19:10).
        self.chat.before_send = self._before_agent_request
        self.chat.on_title_change = self.header.set_title
        # В«РЎРїСЂР°РІРёВ»: РєРѕР¶РµРЅ Р·Р°РїРёС‚ в†’ СЃРїСЂР°РІР°, РєРѕР¶РЅР° РїРѕРґС–СЏ Р°РіРµРЅС‚Р° в†’ РєСЂРѕРє Сѓ РЅС–Р№.
        self.chat.on_case_start = self._case_begin
        self.chat.on_event = self._case_on_event
        # РЎС‚Р°РЅ С‡Р°С‚Сѓ (СЃРїС–РЅРµСЂ, РЅР°Р·РІР°, РґРѕСЃС‚СѓРїРЅС–СЃС‚СЊ РјРѕРґРµР»С–) РїРѕРєР°Р·СѓС”РјРѕ РІ Р·Р°РіРѕР»РѕРІРєСѓ.
        self.chat.bind_header(self.header.title_label, self.header.status_dot)
        self._apply_voice_settings()

        self.v_split.add(self.chat, weight=3)
        self.v_split.add(self.composer_host, weight=0)
        # РљРѕРјРїРѕР·РµСЂ вЂ” РќР•Р—РњР†РќРќРђ С‡Р°СЃС‚РёРЅР° С–РЅС‚РµСЂС„РµР№СЃСѓ: Сѓ РЅСЊРѕРјСѓ РїРёС€СѓС‚СЊ Р·Р°РІРґР°РЅРЅСЏ.
        # ``PanedWindow`` С‚СЂРёРјР°С” РїР°РЅРµР»СЊ С–Р· ``weight=0`` СЃС‚Р°Р»РѕСЋ, Р°Р»Рµ РєРѕР»Рё
        # СЃС‚СЂС–С‡РєР° РґС–Р°Р»РѕРіСѓ РїСЂРѕСЃРёС‚СЊ Р±С–Р»СЊС€Рµ РјС–СЃС†СЏ (РґРѕРІРіР° РІС–РґРїРѕРІС–РґСЊ, РєР°СЂС‚РєР°
        # Р°РЅР°Р»С–Р·Сѓ, РµС‚Р°РїРё), Tk СЃС‚РёСЃРєР°С” СЃР°РјРµ РєРѕРјРїРѕР·РµСЂ вЂ” С– РїРѕР»Рµ РІРІРѕРґСѓ
        # Р·РЅРёРєР°С” Р·Р° РЅРёР¶РЅС–Рј РєСЂР°С”Рј. РљРѕСЂРёСЃС‚СѓРІР°С‡ Р±Р°С‡РёРІ РїРѕСЂРѕР¶РЅСЋ СЃРјСѓРіСѓ Р·Р°РјС–СЃС‚СЊ
        # С„РѕСЂРјРё (В«С„РѕСЂРјР° РІР·Р°РіР°Р»С– РґРµСЃСЊ РІРЅРёР·Сѓ С…РѕРІР°С”С‚СЊСЃСЏВ»).
        #
        # РўРѕРјСѓ: (1) РєРѕРјРїРѕР·РµСЂ РјР°С” РІР»Р°СЃРЅСѓ РјС–РЅС–РјР°Р»СЊРЅСѓ РІРёСЃРѕС‚Сѓ, (2) РІРµСЂС‚РёРєР°Р»СЊРЅРёР№
        # СЃР°С€ РЅРµ РјРѕР¶РЅР° РїРѕСЃСѓРЅСѓС‚Рё РЅРёР¶С‡Рµ Р·Р° РЅРµС—.
        try:
            self.composer_host.configure(height=theme.COMPOSER_HEIGHT)
            self.composer_host.pack_propagate(False)
        except (tk.TclError, AttributeError):
            pass
        self._chat_shown = True
        self._composer_shown = True
        self._focus_mode = False
        self._view = "chat"

        # в”Ђв”Ђ СЂРѕР±РѕС‡Р° РѕР±Р»Р°СЃС‚СЊ: СЂРµРґР°РєС‚РѕСЂ + РЅРёР¶РЅС– РІРєР»Р°РґРєРё
        centre = tk.Frame(self.h_split, bg=theme.BG, bd=0, highlightthickness=0)
        centre.rowconfigure(0, weight=1)
        centre.columnconfigure(0, weight=1)
        self.centre = centre

        self.editor_split = tk.Frame(centre, bg=theme.BG, bd=0, highlightthickness=0)
        self.editor_split.grid(row=0, column=0, sticky="nsew")
        self.editor_split.rowconfigure(0, weight=1)
        self.editor_split.columnconfigure(0, weight=1)

        self.tabs = EditorTabs(
            self.editor_split, self.theme, self.settings,
            on_status=self.set_status,
            on_cursor=self._on_cursor,
            on_saved=self._on_saved,
            on_changed=self._on_tabs_changed,
            on_new_tab=self.new_file,
            on_analysis=self._on_editor_analysis,
        )
        self.tabs.grid(row=0, column=0, sticky="nsew")

        # в”Ђв”Ђ СЃРјСѓРіР° РїРµСЂРµС‚СЏРіСѓРІР°РЅРЅСЏ РјС–Р¶ СЂРµРґР°РєС‚РѕСЂРѕРј С– РЅРёР¶РЅСЊРѕСЋ РїР°РЅРµР»Р»СЋ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        # Р Р°РЅС–С€Рµ РІРёСЃРѕС‚Р° РЅРёР¶РЅСЊРѕС— РїР°РЅРµР»С– Р±СѓР»Р° Р¤Р†РљРЎРћР’РђРќРћР® (grid Р· height), С–
        # РєРѕСЂРёСЃС‚СѓРІР°С‡ РЅРµ РјС–Рі С—С— СЂРѕР·С‚СЏРіРЅСѓС‚Рё: В«РїР°РЅРµР»СЊ РЅРµ СЂРѕР·С‚СЏРіСѓС”С‚СЊСЃСЏ РїРѕ
        # СЂРѕР·РјС–СЂР°С…В». РўРµРїРµСЂ РјС–Р¶ СЂРµРґР°РєС‚РѕСЂРѕРј С– РїР°РЅРµР»Р»СЋ Р»РµР¶РёС‚СЊ С‚РѕРЅРєР° СЃРјСѓРіР°,
        # СЏРєСѓ С‚СЏРіРЅСѓС‚СЊ РјРёС€РµСЋ вЂ” СЏРє Сѓ Р±СѓРґСЊ-СЏРєС–Р№ IDE.
        self.bottom_sash = tk.Frame(
            self.editor_split, bg=theme.BORDER, bd=0, highlightthickness=0,
            height=6, cursor="sb_v_double_arrow")
        self.bottom_sash.grid(row=1, column=0, sticky="ew")
        self.bottom_sash.grid_remove()
        self.bottom_sash.bind("<ButtonPress-1>", self._bottom_sash_press)
        self.bottom_sash.bind("<B1-Motion>", self._bottom_sash_drag)
        self.bottom_sash.bind("<ButtonRelease-1>", self._bottom_sash_release)
        self.bottom_sash.bind("<Enter>",
                              lambda _e: self.bottom_sash.configure(bg=theme.ACCENT))
        self.bottom_sash.bind("<Leave>",
                              lambda _e: self.bottom_sash.configure(bg=theme.BORDER))
        #: Р’РёСЃРѕС‚Р° РїР°РЅРµР»С–, РїРѕРєРё РєРѕСЂРёСЃС‚СѓРІР°С‡ С‚СЏРіРЅРµ СЃРјСѓРіСѓ.
        self._sash_drag_from = 0
        self._sash_drag_height = 0

        self.bottom_tabs = ttk.Notebook(self.editor_split)
        self.terminal = TerminalPanel(self.bottom_tabs, self.theme, Path(self.settings.workspace))
        self.terminal.on_status = self.set_status
        self.project_search = ProjectSearch(self.bottom_tabs, self.theme,
                                            self._project_root)
        self.project_search.on_open = lambda path, line: self.open_path(path, line)
        self.model_hub = ModelHubPanel(self.bottom_tabs, self.theme, self.settings,
                                       on_model_ready=self._on_hub_model_ready)
        self.preview = LivePreviewPanel(self.bottom_tabs, self.theme,
                                        self._project_root,
                                        on_status=self.set_status,
                                        app=self.app)
        # в”Ђв”Ђ Р¦РµРЅС‚СЂ Р·Р°РІРґР°РЅСЊ: С‡РµСЂРіР° Р»РѕРєР°Р»СЊРЅРѕРіРѕ Р°РіРµРЅС‚Р° СЏРє РїРѕРІРЅРѕС†С–РЅРЅР° РїР°РЅРµР»СЊ.
        # РљРЅРѕРїРєРё С‚СѓС‚ РІРёРєР»РёРєР°СЋС‚СЊ СЃРїСЂР°РІР¶РЅС– РґС–С— РІРёРєРѕРЅР°РІС†СЏ, Р° РЅРµ РјР°Р»СЋСЋС‚СЊ СЃС‚Р°РЅ.
        self.task_center = task_center.TaskCenter(
            self.bottom_tabs, self.theme, self.task_queue,
            executor=self.executor,
            on_pause=self.pause_queue,
            on_resume=self.resume_queue,
            on_stop=self.stop_plan,
            on_retry=self.retry_plan_task,
            on_clear=self.clear_plan_finished,
            on_run_next=self.run_next_task,
            on_add_task=self._queue_from_panel,
            on_open_file=self._open_project_file,
            on_status=self.set_status,
            chat_id_provider=self._active_chat_id,
        )
        self.bottom_tabs.add(self.task_center, text="  в‰Ў Р—Р°РІРґР°РЅРЅСЏ  ")
        self.bottom_tabs.add(self.terminal, text="  РўРµСЂРјС–РЅР°Р»  ")
        self.bottom_tabs.add(self.project_search, text="  РџРѕС€СѓРє  ")
        self.bottom_tabs.add(self.model_hub, text="  РҐР°Р± РјРѕРґРµР»РµР№  ")
        self.bottom_tabs.add(self.preview, text="  рџЊђ РЎР°Р№С‚  ")
        self._bottom_shown = False
        self._bottom_height = int(self.settings.ui.bottom_height or 200)
        if self.settings.ui.bottom_visible:
            # РџРѕРєР°Р·СѓС”РјРѕ С‡РµСЂРµР· С‚Сѓ СЃР°РјСѓ С„СѓРЅРєС†С–СЋ, С‰Рѕ Р№ СЂРµС€С‚Р° РєРѕРґСѓ: РІРѕРЅР° СЃС‚Р°РІРёС‚СЊ
            # СЃРјСѓРіСѓ РїРµСЂРµС‚СЏРіСѓРІР°РЅРЅСЏ Р№ РїСЂР°РІРёР»СЊРЅРёР№ РЅРѕРјРµСЂ СЂСЏРґРєР°.
            self._place_bottom(True)

        # РЎС‚Р°СЂС‚РѕРІРёР№ РµРєСЂР°РЅ Р¶РёРІРµ РїРѕРІРµСЂС… РљРћР›РћРќРљР Р”Р†РђР›РћР“РЈ: С†Рµ СЃС‚Р°РЅ В«СЃРµСЃС–С— С‰Рµ
        # РЅРµРјР°С”В», С– РІС–РЅ РјР°С” Р±СѓС‚Рё С‚Р°Рј, РґРµ РєРѕСЂРёСЃС‚СѓРІР°С‡ РѕС‡С–РєСѓС” РїРѕС‡Р°С‚Рё СЂРѕР±РѕС‚Сѓ.
        # Р’РђР–Р›РР’Рћ: СЃР°Рј РєРѕРЅС‚РµР№РЅРµСЂ РЅРµ СЂРѕР·РјС–С‰СѓС”РјРѕ С‚СѓС‚. ``place`` СЃС‚Р°РІРёРІ Р±Рё
        # РїРѕСЂРѕР¶РЅС–Р№ РєР°РґСЂ РїРѕРІРµСЂС… СЃС‚СЂС–С‡РєРё РґС–Р°Р»РѕРіСѓ РІР¶Рµ РїС–Рґ С‡Р°СЃ РїРѕР±СѓРґРѕРІРё РІС–РєРЅР°, С–
        # РєРѕР»Рё СЃРµСЃС–СЏ РјР°С” С–СЃС‚РѕСЂС–СЋ (welcome РЅРµ РїРѕРєР°Р·СѓС”С‚СЊСЃСЏ), РѕРІРµСЂР»РµР№ Р»РёС€Р°РІСЃСЏ Р±
        # РЅР°Р·Р°РІР¶РґРё вЂ” СЂРѕР·РјРѕРІР° РІРёРіР»СЏРґР°Р»Р° РїРѕСЂРѕР¶РЅСЊРѕСЋ. РџРѕРєР°Р·СѓС” Р№РѕРіРѕ Р»РёС€Рµ
        # :meth:`show_welcome`.
        self.workspace_host = tk.Frame(self.conversation_host, bg=theme.BG, bd=0,
                                       highlightthickness=0)

        # в”Ђв”Ђ РєРѕР»РѕРЅРєР° РєРѕРЅС‚РµРєСЃС‚Сѓ
        self.context_host = tk.Frame(self.h_split, bg=theme.BG_ALT,
                                     width=self.settings.ui.context_width, bd=0,
                                     highlightthickness=0)
        self.context_host.pack_propagate(False)
        self.context = context_panel.ContextPanel(
            self.context_host, self.theme, self._project_root,
            on_open_path=lambda path: self.open_path(Path(path)),
            on_close_tab=self.tabs.close_tab,
            on_select_tab=self.tabs.select,
            on_status=self.set_status,
            on_open_settings=self.open_settings,
            on_open_tools=lambda: self.show_side("tools"),
            on_toggle_collapse=self.toggle_context,
        )
        self.context.pack(fill="both", expand=True)
        self.context.tabs_provider = self.tabs.tab_titles
        self.context.active_tab_provider = self.tabs.current_key
        # Р–РёРІС– РґР°РЅС– РїСЂРѕ Р°РіРµРЅС‚Р°: СЃС‚Р°РЅ С–Р· С‡РµСЂРіРё, РјРѕРґРµР»СЊ С–Р· РЅР°Р»Р°С€С‚СѓРІР°РЅСЊ,
        # Р·Р°РїРѕРІРЅРµРЅРЅСЏ РєРѕРЅС‚РµРєСЃС‚Сѓ Р·С– СЃС‚Р°С‚РёСЃС‚РёРєРё С‡Р°С‚Сѓ, С–РЅСЃС‚СЂСѓРјРµРЅС‚Рё Р· СЂРµС”СЃС‚СЂСѓ.
        self.context.agent_status_provider = self._agent_status_text
        self.context.model_provider = self._model_summary
        self.context.context_provider = self._context_usage
        self.context.tools_provider = self._active_tool_names
        # РЎС‚Р°РЅ Р»С–РЅРёРІРѕРіРѕ СЂРµС”СЃС‚СЂСѓ Р№ С‡РµСЃРЅС–СЃС‚СЊ РїС–РґСЂР°С…СѓРЅРєСѓ С‚РѕРєРµРЅС–РІ вЂ” Р· СЂРµР°Р»СЊРЅРёС…
        # РјРµС…Р°РЅС–Р·РјС–РІ, Р° РЅРµ РґРµРєРѕСЂР°С‚РёРІРЅС– С‡РёСЃР»Р°.
        self.context.registry_provider = self._registry_state_for_panel
        self.context.exact_counter_provider = self._counter_is_exact
        self.context.budget_provider = self._budget_state_for_panel

        # в”Ђв”Ђ РїСЂР°РІР° РєРѕР»РѕРЅРєР°: Р¶РёРІРёР№ РїСЂРµРІ'СЋ Р·Р°СЃС‚РѕСЃСѓРЅРєСѓ (Р°РіРµРЅС‚ С‚РµСЃС‚СѓС” С‚СѓС‚).
        self.preview_host = tk.Frame(self.h_split, bg=theme.BG_ALT,
                                     width=theme.PREVIEW_WIDTH, bd=0,
                                     highlightthickness=0)
        self.preview_host.pack_propagate(False)
        self.live_preview = LivePreviewPanel(
            self.preview_host, self.theme,
            self._project_root,
            on_status=self.set_status,
            app=self.app,
        )
        self.live_preview.pack(fill="both", expand=True)
        # в”Ђв”Ђ СЃС‚РѕСЂС–РЅРєР° СЏРє РґР°РЅС–: С–РЅСЃРїРµРєС‚РѕСЂ, РєРѕРЅСЃРѕР»СЊ, Р·РЅС–РјРѕРє, РїРµСЂРµРІС–СЂРєРё в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        # РџР°РЅРµР»СЊ РЅРµ Р·РЅР°С” РїСЂРѕ CDP РЅР°РїСЂСЏРјСѓ вЂ” РІРѕРЅР° РєР»РёС‡Рµ С†С– РєРѕР»Р±РµРєРё, Р° РІРѕРЅРё РІР¶Рµ
        # Р±РµСЂСѓС‚СЊ СЃРµСЃС–СЋ РІР±СѓРґРѕРІР°РЅРѕРіРѕ Р±СЂР°СѓР·РµСЂР°. РўР°Рє РїР°РЅРµР»СЊ РјРѕР¶РЅР° С‚РµСЃС‚СѓРІР°С‚Рё Р±РµР·
        # РјРµСЂРµР¶С– Р№ Р±РµР· Chromium.
        self.live_preview.on_inspect_at = self._inspect_page_at
        self.live_preview.on_send_element = self.send_element_to_agent
        self.live_preview.console_provider = self._page_console
        self.live_preview.action_provider = self._page_action
        # в”Ђв”Ђ РЎРїСЂР°РІР¶РЅС–Р№ HMR: РѕРЅРѕРІР»РµРЅРЅСЏ СЃС‚РѕСЂС–РЅРєРё Р·Р° РўРРџРћРњ С„Р°Р№Р»Сѓ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        # РџР°РЅРµР»СЊ РїСЂРµРІ'СЋ СЃР°РјР° РІРёРєР»РёРєР°С” ``hmr.update_for_file``: CSS РїС–РґРјС–РЅСЋС”С‚СЊСЃСЏ
        # Р±РµР· РїРµСЂРµР·Р°РІР°РЅС‚Р°Р¶РµРЅРЅСЏ, HTML вЂ” С‚РѕС‡РєРѕРІРѕ, JS вЂ” С–Р· РІС–РґРЅРѕРІР»РµРЅРЅСЏРј СЃС‚Р°РЅСѓ.
        # Р‡Р№ РїРѕС‚СЂС–Р±РЅС– РґРІС– СЂРµС‡С–: Р¶РёРІР° CDP-СЃРµСЃС–СЏ С– С€Р»СЏС… Р·Р±РµСЂРµР¶РµРЅРѕРіРѕ С„Р°Р№Р»Сѓ.
        self.live_preview.inner.hmr_session_provider = self._browser_cdp
        self.live_preview.inner.saved_path_provider = self._current_editor_path
        for holder in (self.live_preview.inner, self.preview):
            try:
                holder.saved_path_provider = self._current_editor_path
            except AttributeError:
                pass

        self.h_split.add(self.conversation_host, weight=1)
        self.h_split.add(centre, weight=1)
        self.h_split.add(self.context_host, weight=0)
        self._context_shown = True
        # РџСЂРµРІ'СЋ С…РѕРІР°С”РјРѕ Р·Р° Р·Р°РјРѕРІС‡СѓРІР°РЅРЅСЏРј: РІРѕРЅРѕ Р·'СЏРІР»СЏС”С‚СЊСЃСЏ РєРЅРѕРїРєРѕСЋ
        # В«Live PreviewВ» Р°Р±Рѕ Р°РІС‚РѕРјР°С‚РёС‡РЅРѕ, РєРѕР»Рё Р°РіРµРЅС‚ Р·Р°РїСѓСЃРєР°С” Р·Р°СЃС‚РѕСЃСѓРЅРѕРє.
        self._preview_shown = False

    def _build_status(self) -> None:
        bar = tk.Frame(self, bg=theme.BG_ALT, height=24, bd=0, highlightthickness=0)
        bar.grid(row=1, column=0, sticky="ew")
        bar.grid_propagate(False)
        self.status_bar = bar

        self.status_label = tk.Label(bar, text="Р“РѕС‚РѕРІРѕ", bg=theme.BG_ALT, fg=theme.FG_DIM,
                                     font=("Segoe UI", 8), anchor="w")
        self.status_label.pack(side="left", padx=theme.SPACE_LG)

        # в”Ђв”Ђ С–РЅРґРёРєР°С‚РѕСЂ РїСЂРёС…РѕРІР°РЅРёС… Р·Р±РѕС—РІ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        # РЈ РєРѕРґС– Р±Р°РіР°С‚Рѕ РјС–СЃС†СЊ, РґРµ РІРёРЅСЏС‚РѕРє РєРѕРІС‚Р°С”С‚СЊСЃСЏ, С‰РѕР± С–РЅС‚РµСЂС„РµР№СЃ РЅРµ
        # РїР°РґР°РІ. Р‘РµР· С†СЊРѕРіРѕ РїС–РґРїРёСЃСѓ С‚Р°РєС– Р·Р±РѕС— РЅРµРІРёРґРёРјС–: РєРЅРѕРїРєР° РЅР°С‚РёСЃРЅСѓР»Р°СЃСЊ,
        # Р°Р»Рµ В«РЅС–С‡РѕРіРѕ РЅРµ СЃС‚Р°Р»РѕСЃСЏВ», С– РїСЂРёС‡РёРЅРё РЅРµ РІРёРґРЅРѕ РЅС–РґРµ.
        self.failure_label = tk.Label(
            bar, text="", bg=theme.BG_ALT, fg=theme.WARN,
            font=("Segoe UI", 8), cursor="hand2")
        self.failure_label.pack(side="left", padx=(theme.SPACE_SM, 0))
        self.failure_label.bind("<Button-1>", lambda _e: self.show_failures())
        widgets.Tip(self.failure_label, "РџСЂРёС…РѕРІР°РЅС– Р·Р±РѕС— вЂ” РЅР°С‚РёСЃРЅРё, С‰РѕР± РїРѕР±Р°С‡РёС‚Рё")
        try:
            safe.on_failure(self._on_hidden_failure)
        except Exception:  # noqa: BLE001 - С–РЅРґРёРєР°С‚РѕСЂ РЅРµ РјР°С” Р»Р°РјР°С‚Рё СЃС‚Р°СЂС‚
            LOG.debug("РќРµ РІРґР°Р»РѕСЃСЊ РїС–РґРїРёСЃР°С‚РёСЃСЊ РЅР° СЂРµС”СЃС‚СЂ Р·Р±РѕС—РІ", exc_info=True)

        self.cursor_label = tk.Label(bar, text="Ln 1, Col 1", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                     font=("Segoe UI", 8))
        self.cursor_label.pack(side="right", padx=theme.SPACE_LG)

        self.ast_label = tk.Label(bar, text="", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                  font=("Segoe UI", 8))
        self.ast_label.pack(side="right", padx=theme.SPACE_MD)

        self.lang_label = tk.Label(bar, text="вЂ”", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                   font=("Segoe UI", 8))
        self.lang_label.pack(side="right", padx=theme.SPACE_MD)

        self.agent_label = tk.Label(bar, text="Р°РіРµРЅС‚: РѕС‡С–РєСѓС”", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                    font=("Segoe UI", 8))
        self.agent_label.pack(side="right", padx=theme.SPACE_MD)

        # Р‘РµР· РІРёР±СЂР°РЅРѕРіРѕ РїСЂРѕС”РєС‚Сѓ РЅРµ РїРѕРєР°Р·СѓС”РјРѕ С€Р»СЏС… РґРѕРјР°С€РЅСЊРѕС— С‚РµРєРё: С–РЅР°РєС€Рµ
        # СЃС‚Р°С‚СѓСЃР±Р°СЂ РєР°Р·Р°РІ В«C:\Users\<С–Рј'СЏ>В», РЅС–Р±Рё Р°РіРµРЅС‚ СѓР¶Рµ РїСЂР°С†СЋС” С‚Р°Рј.
        self.ws_label = tk.Label(
            bar, text=(str(self.settings.workspace) if self.has_project() else "С‚РµРєСѓ РЅРµ РѕР±СЂР°РЅРѕ"),
            bg=theme.BG_ALT, fg=theme.FG_FAINT, font=("Segoe UI", 8))
        self.ws_label.pack(side="right", padx=theme.SPACE_LG)

    def _on_root_configure(self, event=None) -> None:
        """РџРµСЂРµСЂР°С…СѓРІР°С‚Рё СЃР°С€С– РїС–СЃР»СЏ Р·РјС–РЅРё СЂРѕР·РјС–СЂСѓ РІС–РєРЅР° (Р· РЅРµРІРµР»РёРєРѕСЋ РїР°СѓР·РѕСЋ)."""
        if event is not None and event.widget is not self:
            return
        if self._resize_after is not None:
            try:
                self.after_cancel(self._resize_after)
            except (tk.TclError, ValueError):
                pass
        try:
            self._resize_after = self.after(120, self._apply_after_resize)
        except tk.TclError:
            self._resize_after = None

    def _apply_after_resize(self) -> None:
        self._resize_after = None
        self._apply_responsive()
        self._apply_sash_positions()

    def _apply_responsive(self) -> None:
        """РђРґР°РїС‚РёРІРЅР° РєРѕРјРїРѕР·РёС†С–СЏ: СЂРѕР·РјС–СЂРё РґС–Р°Р»РѕРіСѓ Р№ РїР°РЅРµР»РµР№ РїС–Рґ РµРєСЂР°РЅ.

        РўСЂРё РєРѕР»РѕРЅРєРё (РґС–Р°Р»РѕРі + СЂРµРґР°РєС‚РѕСЂ + РєРѕРЅС‚РµРєСЃС‚) РјР°СЋС‚СЊ СЃРµРЅСЃ Р»РёС€Рµ РЅР°
        С€РёСЂРѕРєРѕРјСѓ РµРєСЂР°РЅС–. РљРѕР»Рё РјС–СЃС†СЏ Р±СЂР°РєСѓС”, Р·РЅРёРєР°С” СЃР°РјРµ РєРѕР»РѕРЅРєР° РєРѕРЅС‚РµРєСЃС‚Сѓ:
        СЂРµРґР°РєС‚РѕСЂ Р»РёС€Р°С”С‚СЊСЃСЏ, Р±Рѕ РІС–РЅ С– С” СЂРѕР±РѕС‡Р° РѕР±Р»Р°СЃС‚СЊ.

        РЇРєС‰Рѕ РєРѕСЂРёСЃС‚СѓРІР°С‡ РЎРђРњ РїРµСЂРµРјРёРєР°РІ РєРѕРЅС‚РµРєСЃС‚, Р№РѕРіРѕ РІРёР±С–СЂ РїРѕРІР°Р¶Р°С”С‚СЊСЃСЏ вЂ”
        С–РЅР°РєС€Рµ РїР°РЅРµР»СЊ РїРѕРІРµСЂС‚Р°Р»Р°СЃСЊ Р±Рё С‰РѕСЂР°Р·Сѓ РїС–СЃР»СЏ Р·РјС–РЅРё СЂРѕР·РјС–СЂСѓ РІС–РєРЅР°.
        """
        try:
            total = self.h_split.winfo_width()
        except tk.TclError:
            return
        if total <= 1:
            return
        self._apply_adaptive_chat(total)
        # в”Ђв”Ђ РєРѕР»РѕРЅРєР° РєРѕРЅС‚РµРєСЃС‚Сѓ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        # РЈ СЂРµР¶РёРјС– В«Р§Р°С‚В» (Р±РµР· СЂРµРґР°РєС‚РѕСЂР°) РєРѕРЅС‚РµРєСЃС‚ Р·Р°Р±РёСЂР°РІ 359 px Сѓ С‡Р°С‚Сѓ Р№
        # Р»РёС€Р°РІ Р№РѕРіРѕ РІСѓР·СЊРєРѕСЋ СЃРјСѓР¶РєРѕСЋ РїРѕСЃРµСЂРµРґРёРЅС–. РҐРѕРІР°С”РјРѕ С—С—, РєРѕР»Рё СЂРµРґР°РєС‚РѕСЂ
        # РЅРµ РїРѕРєР°Р·Р°РЅРёР№: РєРѕСЂРёСЃС‚СѓРІР°С‡ РїСЂРёР№С€РѕРІ СЃСЋРґРё СЂРѕР·РјРѕРІР»СЏС‚Рё, Р° РЅРµ РґРёРІРёС‚РёСЃСЊ
        # СЃРїРёСЃРѕРє С„Р°Р№Р»С–РІ.
        chat_only = self._view != "workspace"
        if self._context_user_choice is None:
            want_context = total >= 1180 and not self._focus_mode and not chat_only
            if want_context != self._context_shown:
                self._context_shown = want_context
                self._reorder_panes(
                    with_centre=(self._view == "workspace" and self._centre_in_split()))
        # Р РµРґР°РєС‚РѕСЂ С…РѕРІР°С”РјРѕ Р»РёС€Рµ РІ СЂРµР¶РёРјС– В«С‚С–Р»СЊРєРё С‡Р°С‚В» вЂ” С†Рµ СЏРІРЅРёР№ РІРёР±С–СЂ.
        if self._focus_mode and self._centre_in_split():
            self._reorder_panes(with_centre=False)

    def _apply_adaptive_chat(self, total_width: int) -> None:
        """РџС–РґС–РіРЅР°С‚Рё С€РёСЂРёРЅСѓ РєРѕР»РѕРЅРєРё РґС–Р°Р»РѕРіСѓ Р№ Р»С–РјС–С‚ СЂСЏРґРєС–РІ РїС–Рґ РµРєСЂР°РЅ.

        РЁРёСЂРёРЅР° СЃС‚СЂС–С‡РєРё РЅРµ РјР°С” Р±СѓС‚Рё СЃС‚Р°Р»РѕСЋ: РЅР° РЅРѕСѓС‚Р±СѓС†С– 1366 px В«РєРѕРјС„РѕСЂС‚РЅС–В»
        920 px Р»РёС€Р°Р»Рё СЂРµРґР°РєС‚РѕСЂСѓ СЃРјСѓР¶РєСѓ, Р° РЅР° 4K СЂРѕР·РјРѕРІР° СЂРѕР·С‚СЏРіСѓРІР°Р»Р°СЃСЊ РЅР°
        РїС–РІ РµРєСЂР°РЅР°. РўСѓС‚ СЂР°С…СѓС”РјРѕ С€РёСЂРёРЅСѓ Р· РµРєСЂР°РЅР° Р№ РїРѕС‚РѕС‡РЅРѕРіРѕ РІС–РєРЅР°, Р°
        РєС–Р»СЊРєС–СЃС‚СЊ РІРёРґРёРјРёС… СЂСЏРґРєС–РІ РѕРґРЅС–С”С— РІС–РґРїРѕРІС–РґС– вЂ” Р· РІРёСЃРѕС‚Рё СЃС‚СЂС–С‡РєРё.
        """
        try:
            screen = adaptive.screen_size(self)
            height = self.conversation_host.winfo_height()
        except tk.TclError:
            return
        metrics = adaptive.metrics_for(
            screen=screen,
            window=(total_width, max(0, height) or self.winfo_height()),
            feed_height=max(0, height),
            sidebar=int(self.settings.ui.sidebar_width or 264),
            min_width=320,
            max_width=int(getattr(self.settings.ui, "chat_max_width", 0) or 0),
        )
        previous = getattr(self, "_chat_metrics", None)
        self._chat_metrics = metrics
        if previous is not None and previous.body_lines != metrics.body_lines:
            self._chat_lines_limit = metrics.body_lines
            try:
                self.chat.set_max_lines(metrics.body_lines)
            except (tk.TclError, AttributeError):
                pass
        # Р’СѓР·СЊРєРёР№ РµРєСЂР°РЅ: РєРѕСЂРѕС‚С€С– РЅР°Р·РІРё РІ СЃРїРёСЃРєСѓ СЃРµСЃС–Р№ С– Р·РіРѕСЂРЅСѓС‚С– СЃР»СѓР¶Р±РѕРІС–
        # РїС–РґРїРёСЃРё РєРѕРјРїРѕР·РµСЂР° (С†Рµ СЂРѕР±РёС‚СЊ СЃР°Рј ChatPanel Р·Р° С€РёСЂРёРЅРѕСЋ).
        try:
            self.chat_list.set_compact(metrics.compact)
        except (tk.TclError, AttributeError):
            pass

    def _apply_sash_positions(self) -> None:
        """Р РѕР·СЃС‚Р°РІРёС‚Рё СЃР°С€С– Р·Р° С‚РёРј, СЏРєС– РїР°РЅРµР»С– Р·Р°СЂР°Р· Сѓ СЂРѕР·РєР»Р°РґС†С–.

        РџР°РЅРµР»РµР№ РјРѕР¶Рµ Р±СѓС‚Рё РІС–Рґ 1 РґРѕ 4: РґС–Р°Р»РѕРі, СЂРѕР±РѕС‡Р° РѕР±Р»Р°СЃС‚СЊ, РєРѕРЅС‚РµРєСЃС‚ С–
        Р¶РёРІРёР№ РїСЂРµРІ'СЋ вЂ” РєРѕР¶РЅР° С…РѕРІР°С”С‚СЊСЃСЏ РѕРєСЂРµРјРѕ. РўРѕРјСѓ РќР• РјРѕР¶РЅР° Р·РІРµСЂС‚Р°С‚РёСЃСЊ РґРѕ
        СЃР°С€С–РІ С„С–РєСЃРѕРІР°РЅРёРјРё С–РЅРґРµРєСЃР°РјРё: Сѓ ``PanedWindow`` Р· N РїР°РЅРµР»СЏРјРё С” Р»РёС€Рµ
        N-1 СЃР°С€С–РІ. Р Р°РЅС–С€Рµ СЃР°РјРµ С‡РµСЂРµР· С†Рµ СЂРѕР·РєР»Р°РґРєР° Р»Р°РјР°Р»Р°СЃСЊ, С‰РѕР№РЅРѕ
        Р·'СЏРІР»СЏР»Р°СЃСЊ С‡РµС‚РІРµСЂС‚Р° РїР°РЅРµР»СЊ.

        РђР»РіРѕСЂРёС‚Рј: Р·Р±РёСЂР°С”РјРѕ С„Р°РєС‚РёС‡РЅРёР№ РїРѕСЂСЏРґРѕРє РїР°РЅРµР»РµР№, СЂР°С…СѓС”РјРѕ Р±Р°Р¶Р°РЅСѓ С€РёСЂРёРЅСѓ
        РєРѕР¶РЅРѕС—, РґР°Р»С– СЃС‚Р°РІРёРјРѕ СЃР°С€ Р·Р° РЅР°РєРѕРїРёС‡РµРЅРѕСЋ СЃСѓРјРѕСЋ.

        Р’РђР–Р›РР’Рћ РїСЂРѕ В«Р·Р°РІРёСЃР°РЅРЅСЏВ». РќР° СЃС‚Р°СЂС‚С– С†СЏ С„СѓРЅРєС†С–СЏ РІРёРєР»РёРєР°Р»Р°СЃСЊ 8 СЂР°Р·С–РІ
        (``after_idle`` + 120 РјСЃ + 420 РјСЃ + РїС–СЃР»СЏ РєРѕР¶РЅРѕРіРѕ ``grid``), С– РєРѕР¶РµРЅ
        РІРёРєР»РёРє СЂРѕР±РёС‚СЊ ``update_idletasks()`` вЂ” С‚РѕР±С‚Рѕ РїРѕРІРЅРёР№ РїРµСЂРµСЂР°С…СѓРЅРѕРє
        СЂРѕР·РєР»Р°РґРєРё. Р—Р°РјС–СЂСЏРЅРѕ РїСЂРѕС„С–Р»РµСЂРѕРј: 0.57 СЃ С–Р· РїРµСЂС€РѕРіРѕ РєР°РґСЂСѓ, С–
        С–РЅС‚РµСЂС„РµР№СЃ Р·Р°СЃС‚РёРіР°РІ. РўРµРїРµСЂ Р·Р°РїРёС‚Рё Р—Р›РР’РђР®РўР¬РЎРЇ: СЃРєС–Р»СЊРєРё Р± СЂР°Р·С–РІ С—С— РЅРµ
        РїРѕРєР»РёРєР°Р»Рё, СЃРїСЂР°РІР¶РЅС–Р№ РїРµСЂРµСЂР°С…СѓРЅРѕРє РІС–РґР±СѓРґРµС‚СЊСЃСЏ РѕРґРёРЅ СЂР°Р·, РєРѕР»Рё
        С–РЅС‚РµСЂС„РµР№СЃ РІС–РґРїРѕС‡РёРЅРµ.
        """
        # Р—Р»РёРІР°С”РјРѕ РІРёРєР»РёРєРё: РїР»Р°РЅСѓС”РјРѕ РѕРґРёРЅ РІС–РґРєР»Р°РґРµРЅРёР№ РїРµСЂРµСЂР°С…СѓРЅРѕРє.
        if getattr(self, "_sash_pending", False):
            return
        self._sash_pending = True
        try:
            job = self.after_idle(self._do_apply_sash)
        except tk.TclError:
            self._sash_pending = False
            return
        # Р†РґРµРЅС‚РёС„С–РєР°С‚РѕСЂ С‚РµР¶ С‚СЂРµР±Р° Р·РЅР°С‚Рё: ``after_idle`` Р»РёС€Р°С” РєРѕРјР°РЅРґСѓ РІ Tcl,
        # С– РїС–СЃР»СЏ ``destroy()`` РІРѕРЅР° РїР°РґР°С” Р· В«invalid command nameВ».
        jobs = getattr(self, "_sash_jobs", None)
        if jobs is None:
            jobs = self._sash_jobs = []
        jobs.append(job)

    def _sash_after(self, delay: int) -> None:
        """Р—Р°РїР»Р°РЅСѓРІР°С‚Рё РїРµСЂРµСЂР°С…СѓРЅРѕРє СЃР°С€С–РІ С– Р—РђРџРђРњ'РЇРўРђРўР С–РґРµРЅС‚РёС„С–РєР°С‚РѕСЂ.

        Р‘РµР· Р·Р°РїР°Рј'СЏС‚РѕРІСѓРІР°РЅРЅСЏ РІС–РґРєР»Р°РґРµРЅС– РІРёРєР»РёРєРё Р»РёС€Р°Р»РёСЃСЊ Сѓ Tcl РїС–СЃР»СЏ
        ``destroy()``: Tk РґСЂСѓРєСѓРІР°РІ Сѓ stderr

            invalid command name "1234_apply_sash_positions"

        Р° ``tests/live_every_button.py`` РїР°РґР°РІ РЅР° СЃР°РјРѕРјСѓ Р·Р°РєСЂРёС‚С‚С– РІС–РєРЅР° вЂ”
        РїС–СЃР»СЏ 77 СѓСЃРїС–С€РЅРёС… РЅР°С‚РёСЃРєР°РЅСЊ. РўРµРїРµСЂ СѓСЃС– РІРѕРЅРё Р·РЅС–РјР°СЋС‚СЊСЃСЏ СЂР°Р·РѕРј С–Р·
        РІС–РєРЅРѕРј (РґРёРІ. ``on_close``).
        """
        try:
            job = self.after(delay, self._apply_sash_positions)
        except tk.TclError:
            return
        jobs = getattr(self, "_sash_jobs", None)
        if jobs is None:
            jobs = self._sash_jobs = []
        jobs.append(job)
        # РЎРїРёСЃРѕРє РЅРµ РјР°С” СЂРѕСЃС‚Рё Р±РµР·РєС–РЅРµС‡РЅРѕ: СЃРїСЂР°С†СЊРѕРІР°РЅС– С–РґРµРЅС‚РёС„С–РєР°С‚РѕСЂРё
        # Р»РёС€Р°С”РјРѕ Р»РёС€Рµ РЅР° С‡Р°СЃ, РґРѕРєРё С—С… РјРѕР¶РЅР° СЃРєР°СЃСѓРІР°С‚Рё.
        if len(jobs) > 24:
            del jobs[: len(jobs) - 24]

    def _schedule_sash_retry(self) -> None:
        """РЎРїСЂРѕР±СѓРІР°С‚Рё СЂРѕР·СЃС‚Р°РІРёС‚Рё СЃР°С€С– С‰Рµ СЂР°Р·, РєРѕР»Рё РІС–РєРЅРѕ РѕС‚СЂРёРјР°С” СЂРѕР·РјС–СЂ.

        Р“РµРѕРјРµС‚СЂС–СЏ РЅРµРґРѕСЃС‚СѓРїРЅР° Р»РёС€Рµ РЅР° СЃР°РјРѕРјСѓ РїРѕС‡Р°С‚РєСѓ (``winfo_width()`` == 1).
        РџРѕРІС‚РѕСЂСЋС”РјРѕ РљР†Р›Р¬РљРђ СЂР°Р·С–РІ С–Р· РЅР°СЂРѕСЃС‚Р°РЅРЅСЏРј РїР°СѓР·Рё, Р° РЅРµ РЅРµСЃРєС–РЅС‡РµРЅРЅРѕ:
        СЏРєС‰Рѕ РІС–РєРЅРѕ С‚Р°Рє С– РЅРµ РїРѕРєР°Р·Р°Р»Рё, С†Рµ РЅРµ РїСЂРёРІС–Рґ РєСЂСѓС‚РёС‚Рё С‚Р°Р№РјРµСЂ РІС–С‡РЅРѕ.
        """
        attempts = getattr(self, "_sash_retry", 0)
        if attempts >= 4:
            return
        self._sash_retry = attempts + 1
        delay = 80 * (attempts + 1)
        self._sash_after(delay)

    def _do_apply_sash(self) -> None:
        """РЎРїСЂР°РІР¶РЅС–Р№ РїРµСЂРµСЂР°С…СѓРЅРѕРє СЃР°С€С–РІ (РѕРґРёРЅ СЂР°Р· РЅР° СЃРµСЂС–СЋ Р·Р°РїРёС‚С–РІ)."""
        self._sash_pending = False
        try:
            # РљРѕСЂРёСЃС‚СѓРІР°С‡ С‚СЏРіРЅРµ РјРµР¶Сѓ вЂ” Р№РѕРіРѕ СЂРѕР·РјС–СЂ РЅРµРґРѕС‚РѕСЂРєР°РЅРЅРёР№. Р†РЅР°РєС€Рµ
            # РїРµСЂРµСЂР°С…СѓРЅРѕРє РЅР° РєРѕР¶РЅСѓ РїРѕРґС–СЋ <Configure> РїРѕРІРµСЂС‚Р°РІ СЃР°С€ РЅР° РјС–СЃС†Рµ,
            # С– РїР°РЅРµР»СЊ В«РЅРµ СЂРѕР·С€РёСЂСЋРІР°Р»Р°СЃСЊ РјРёС€РєРѕСЋВ».
            if getattr(self, "_user_dragging", False):
                return
            panes = [str(pane) for pane in self.h_split.panes()]
            total = self.h_split.winfo_width()
            if total <= 0:
                # Р’С–РєРЅРѕ С‰Рµ РЅРµ РѕС‚СЂРёРјР°Р»Рѕ РіРµРѕРјРµС‚СЂС–С— (РїРµСЂС€РёР№ РєР°РґСЂ, РїСЂРёС…РѕРІР°РЅРµ
                # РІС–РєРЅРѕ Р°Р±Рѕ ``winfo_width() == 1`` РґРѕ ``update_idletasks``).
                # Р Р°РЅС–С€Рµ С‚СѓС‚ РїСЂРѕСЃС‚Рѕ РІРёС…РѕРґРёР»Рё вЂ” С– СЃР°С€С– Р»РёС€Р°Р»РёСЃСЊ РЅР° 0, С‚РѕР±С‚Рѕ
                # Р·Р±РµСЂРµР¶РµРЅР° СЂРѕР·РєР»Р°РґРєР° РќР• РІС–РґРЅРѕРІР»СЋРІР°Р»Р°СЃСЊ, С…РѕС‡ С„Р°Р№Р» Р±СѓРІ
                # РїСЂР°РІРёР»СЊРЅРёР№. РџС–Рґ РЅР°РІР°РЅС‚Р°Р¶РµРЅРЅСЏРј (РїРѕРІРЅРёР№ РЅР°Р±С–СЂ С‚РµСЃС‚С–РІ) РїРµСЂС€РёР№
                # РєР°РґСЂ Р·Р°РїС–Р·РЅСЋС”С‚СЊСЃСЏ, С– ``test_layout_persist`` РїР°РґР°РІ Р·
                # В«Р±СѓР»Рѕ (620, 480), СЃС‚Р°Р»Рѕ (0, 480)В». РўРѕРјСѓ РЅРµ Р·РґР°С”РјРѕСЃСЊ, Р°
                # РїРёС‚Р°С”РјРѕ РіРµРѕРјРµС‚СЂС–СЋ РЅР°РїСЂСЏРјСѓ Р№ РїСЂРѕР±СѓС”РјРѕ С‰Рµ СЂР°Р· РїС–Р·РЅС–С€Рµ.
                try:
                    self.update_idletasks()
                except tk.TclError:
                    return
                total = self.h_split.winfo_width()
                if total <= 0:
                    self._schedule_sash_retry()
                    self._apply_v_sash()
                    return
            if len(panes) < 2:
                self._apply_v_sash()
                return
            # Р“РµРѕРјРµС‚СЂС–СЏ С” вЂ” Р»С–С‡РёР»СЊРЅРёРє РїРѕРІС‚РѕСЂС–РІ Р±С–Р»СЊС€Рµ РЅРµ РїРѕС‚СЂС–Р±РµРЅ.
            self._sash_retry = 0

            # РЎРєС–Р»СЊРєРё РјС–СЃС†СЏ РІС–РґРґР°С‚Рё РєРѕР¶РЅС–Р№ РїР°РЅРµР»С– РїСЂР°РІРѕСЂСѓС‡ РІС–Рґ РґС–Р°Р»РѕРіСѓ.
            # РњРµР¶С– вЂ” Р°Р±СЃРѕР»СЋС‚РЅС–, Р° РЅРµ В«С‚СЂРµС‚РёРЅР° РІС–РєРЅР°В»: Р·Р±РµСЂРµР¶РµРЅРµ Р·РЅР°С‡РµРЅРЅСЏ Р·
            # РїРѕРїРµСЂРµРґРЅСЊРѕРіРѕ Р·Р°РїСѓСЃРєСѓ РјРѕРіР»Рѕ Р±СѓС‚Рё Р·Р°РїРёСЃР°РЅРµ РІ С–РЅС€С–Р№ РєРѕРјРїРѕР·РёС†С–С—
            # (РЅР°РїСЂ. РєРѕР»Рё РєРѕР»РѕРЅРєР° РєРѕРЅС‚РµРєСЃС‚Сѓ Р·Р°Р№РјР°Р»Р° РїС–РІ РµРєСЂР°РЅР°), С– С‚РѕРґС–
            # РІРѕРЅРѕ Р·'С—РґР°Р»Рѕ РјС–СЃС†Рµ РІ СЂРµРґР°РєС‚РѕСЂР°.
            ctx_w = layout.clamp(
                self.layout.get("context_width", self.settings.ui.context_width),
                170, theme.CONTEXT_MAX_WIDTH)
            prev_w = layout.clamp(
                self.layout.get("preview_width", theme.PREVIEW_WIDTH),
                theme.PREVIEW_MIN_WIDTH, theme.PREVIEW_MAX_WIDTH)

            has_centre = any(p.endswith(str(self.centre)) for p in panes)

            # в”Ђв”Ђ С€РёСЂРёРЅР° РґС–Р°Р»РѕРіСѓ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
            # Р—Р±РµСЂРµР¶РµРЅРёР№ РІРёР±С–СЂ РєРѕСЂРёСЃС‚СѓРІР°С‡Р° Р°Р±Рѕ Р°РґР°РїС‚РёРІРЅРёР№ СЂРѕР·СЂР°С…СѓРЅРѕРє. РЎС‚РµР»СЋ
            # Р·Р°РґР°С” Р·Р°Р»РёС€РѕРє РїС–СЃР»СЏ РїСЂР°РІРёС… РєРѕР»РѕРЅРѕРє С– РјС–РЅС–РјСѓРјСѓ СЂРµРґР°РєС‚РѕСЂР°.
            fixed_right = 0
            for p in panes:
                if p.endswith(str(self.context_host)):
                    fixed_right += ctx_w
                elif p.endswith(str(self.preview_host)):
                    fixed_right += prev_w
            # РњС–РЅС–РјСѓРј РґС–Р°Р»РѕРіСѓ вЂ” РђР‘РЎРћР›Р®РўРќРР™, Р° РЅРµ В«Рї'СЏС‚Р° С‡Р°СЃС‚РёРЅР° РІС–РєРЅР°В».
            # Р Р°РЅС–С€Рµ С‚СѓС‚ СЃС‚РѕСЏР»Рѕ ``total * 0.20``: РЅР° РµРєСЂР°РЅС– 3189 px С†Рµ 637 px,
            # С– Р·Р±РµСЂРµР¶РµРЅР° С€РёСЂРёРЅР° 620 В«РЅРµ РІС–РґРЅРѕРІР»СЋРІР°Р»Р°СЃСЊВ» РїС–СЃР»СЏ РїРµСЂРµР·Р°РїСѓСЃРєСѓ вЂ”
            # РјРµР¶Р° РїРѕРІРµСЂС‚Р°Р»Р°СЃСЊ РЅР° 637. РљРѕСЂРёСЃС‚СѓРІР°С‡, СЏРєРёР№ СЃР°Рј Р·РІСѓР·РёРІ РґС–Р°Р»РѕРі,
            # РјР°С” РїСЂР°РІРѕ РЅР° СЃРІС–Р№ РІРёР±С–СЂ; РѕР±РјРµР¶СѓС”РјРѕ Р»РёС€Рµ С‚РёРј, С‰РѕР± РїР°РЅРµР»СЊ
            # Р»РёС€Р°Р»Р°СЃСЊ СЂРѕР±РѕС‡РѕСЋ.
            chat_min = 240
            editor_min = 200 if has_centre else 0
            ceiling = max(chat_min, total - fixed_right - editor_min)
            default_w = int(getattr(self._chat_metrics, "chat_width", 0) or 0)
            if not default_w:
                default_w = int(total * 0.42) if has_centre else ceiling
            saved = self.layout.get("chat_split", default_w)
            # РђРґР°РїС‚РёРІРЅР° С€РёСЂРёРЅР° С‚СѓС‚ вЂ” РўРРџРћР’Р• Р·РЅР°С‡РµРЅРЅСЏ, Р° РЅРµ СЃС‚РµР»СЏ: СЏРєС‰Рѕ
            # РєРѕСЂРёСЃС‚СѓРІР°С‡ СЃР°Рј РїРѕС‚СЏРіРЅСѓРІ РјРµР¶Сѓ, Р№РѕРіРѕ РІРёР±С–СЂ РІР°Р¶Р»РёРІС–С€РёР№.
            chat_w = layout.clamp(saved, chat_min, ceiling)
            if not has_centre:
                # Р РµРґР°РєС‚РѕСЂР° РЅРµРјР°С” вЂ” РґС–Р°Р»РѕРі Р·Р°Р№РјР°С” РІРµСЃСЊ Р·Р°Р»РёС€РѕРє.
                chat_w = ceiling

            # в”Ђв”Ђ Р±Р°Р¶Р°РЅР° С€РёСЂРёРЅР° РљРћР–РќРћР‡ РїР°РЅРµР»С– в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
            # РџР°РЅРµР»С– РґС–Р»СЏС‚СЊСЃСЏ РЅР° РґРІР° РІРёРґРё:
            #   * С„С–РєСЃРѕРІР°РЅС– (РєРѕРЅС‚РµРєСЃС‚, РїСЂРµРІ'СЋ) вЂ” РјР°СЋС‚СЊ СЃРІРѕСЋ С€РёСЂРёРЅСѓ;
            #   * РіРЅСѓС‡РєС– (РґС–Р°Р»РѕРі, СЂРѕР±РѕС‡Р° РѕР±Р»Р°СЃС‚СЊ) вЂ” РґС–Р»СЏС‚СЊ Р·Р°Р»РёС€РѕРє.
            #
            # РќР°РєРѕРїРёС‡СѓРІР°С‚Рё РїРѕР·РёС†С–СЋ В«РґРѕРґР°СЋ С€РёСЂРёРЅСѓ РєРѕР¶РЅРѕРіРѕВ» РќР• РјРѕР¶РЅР°: Сѓ
            # РіРЅСѓС‡РєРѕС— РїР°РЅРµР»С– РІР»Р°СЃРЅРѕС— С€РёСЂРёРЅРё РЅРµРјР°С”, С– СЃР°С€ Р·Р° РЅРµСЋ Р»РёС€Р°РІСЃСЏ Р±
            # РЅР° РјС–СЃС†С– РїРѕРїРµСЂРµРґРЅСЊРѕРіРѕ вЂ” СЂРµРґР°РєС‚РѕСЂ СЃС‚РёСЃРєР°РІСЃСЏ РґРѕ РЅСѓР»СЏ, Р°
            # РєРѕРЅС‚РµРєСЃС‚ Р·Р°Р±РёСЂР°РІ РїС–РІ РµРєСЂР°РЅР° (РїРµСЂРµРІС–СЂРµРЅРѕ: 647 px).
            widths: dict[int, int] = {}
            fixed_total = 0
            flexible: list[int] = []
            for index, pane in enumerate(panes):
                if pane.endswith(str(self.context_host)):
                    widths[index] = ctx_w
                    fixed_total += ctx_w
                elif pane.endswith(str(self.preview_host)):
                    widths[index] = prev_w
                    fixed_total += prev_w
                elif pane.endswith(str(self.conversation_host)):
                    widths[index] = chat_w
                    fixed_total += chat_w
                else:
                    flexible.append(index)      # СЂРѕР±РѕС‡Р° РѕР±Р»Р°СЃС‚СЊ

            # Р—Р°Р»РёС€РѕРє РґС–Р»РёРјРѕ РјС–Р¶ РіРЅСѓС‡РєРёРјРё РїР°РЅРµР»СЏРјРё РїРѕСЂС–РІРЅСѓ.
            if flexible:
                rest = max(0, total - fixed_total)
                share = rest // len(flexible)
                for position_index, index in enumerate(flexible):
                    # РћСЃС‚Р°РЅРЅС–Р№ Р·Р°Р±РёСЂР°С” Р·Р°Р»РёС€РѕРє, С‰РѕР± СЃСѓРјР° Р±СѓР»Р° С‚РѕС‡РЅРѕ total.
                    widths[index] = (rest - share * (len(flexible) - 1)
                                     if position_index == len(flexible) - 1
                                     else share)

            # в”Ђв”Ђ СЃС‚Р°РІРёРјРѕ СЃР°С€С– Р·Р° РЅР°РєРѕРїРёС‡РµРЅРѕСЋ СЃСѓРјРѕСЋ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
            position = 0
            for index, pane in enumerate(panes[:-1]):
                position += widths.get(index, 0)
                # РЎР°С€ РЅРµ РјРѕР¶Рµ СЃС‚РѕСЏС‚Рё Р±Р»РёР¶С‡Рµ РЅС–Р¶ 60 px РґРѕ РєСЂР°СЋ.
                position = layout.clamp(position, 60, max(60, total - 60))
                self.h_split.sashpos(index, position)
            # РџРµСЂРµРІС–СЂСЏС”РјРѕ, С‰Рѕ Tk СЃРїСЂР°РІРґС– Р·Р°СЃС‚РѕСЃСѓРІР°РІ РїРѕР·РёС†С–СЋ. РџРѕРєРё РІРЅСѓС‚СЂС–С€РЅСЏ
            # СЂРѕР·РєР»Р°РґРєР° РЅРµ РїРµСЂРµСЂР°С…РѕРІР°РЅР° (``total`` С‰РѕР№РЅРѕ СЃС‚Р°РІ >0, Р°Р»Рµ Tk С‰Рµ
            # РЅРµ СЂРѕР·РєР»Р°РІ РїР°РЅРµР»С–), ``sashpos(i, N)`` РїСЂРёР№РјР°С”С‚СЊСЃСЏ Р№ С‚СѓС‚-С‚Р°РєРё
            # СЃРєРёРґР°С”С‚СЊСЃСЏ Сѓ РІС–Рґ'С”РјРЅРµ Р·РЅР°С‡РµРЅРЅСЏ вЂ” РїР°РЅРµР»СЊ В«Р·Р»РёРїР°С”С‚СЊСЃСЏВ» РІ 0, С–
            # Р·Р±РµСЂРµР¶РµРЅР° СЂРѕР·РєР»Р°РґРєР° РќР• РІС–РґРЅРѕРІР»СЋС”С‚СЊСЃСЏ. РЎР°РјРµ С†Рµ РґР°РІР°Р»Рѕ
            # В«Р±СѓР»Рѕ (620, 480), СЃС‚Р°Р»Рѕ (0, 480)В» Сѓ ``test_layout_persist``.
            self._verify_sash_applied(widths, panes)
            self._apply_v_sash()
        except (tk.TclError, ValueError):
            pass

    def _verify_sash_applied(self, widths: dict[int, int],
                             panes: list[str]) -> None:
        """РџРµСЂРµРєРѕРЅР°С‚РёСЃСЊ, С‰Рѕ СЃР°С€С– СЃС‚Р°Р»Рё С‚Р°Рј, РєСѓРґРё С—С… РїРѕСЃС‚Р°РІРёР»Рё.

        ``PanedWindow.sashpos(i, N)`` РЅРµ РіР°СЂР°РЅС‚СѓС” РЅРµРіР°Р№РЅРѕРіРѕ СЂРµР·СѓР»СЊС‚Р°С‚Сѓ: СЏРєС‰Рѕ
        Tk С‰Рµ РЅРµ СЂРѕР·РєР»Р°РІ РїР°РЅРµР»С–, Р·РЅР°С‡РµРЅРЅСЏ РїСЂРёР№РјР°С”С‚СЊСЃСЏ, Р° РїРѕС‚С–Рј СЃРєРёРґР°С”С‚СЊСЃСЏ.
        РўРѕРјСѓ С‡РёС‚Р°С”РјРѕ С„Р°РєС‚РёС‡РЅС– РїРѕР·РёС†С–С— Р№, СЏРєС‰Рѕ СЂРѕР·Р±С–Р¶РЅС–СЃС‚СЊ С”, РїР»Р°РЅСѓС”РјРѕ РѕРґРёРЅ
        РїРѕРІС‚РѕСЂРЅРёР№ РїРµСЂРµСЂР°С…СѓРЅРѕРє вЂ” СѓР¶Рµ РїС–СЃР»СЏ С‚РѕРіРѕ, СЏРє Tk Р·Р°РІРµСЂС€РёС‚СЊ СЂРѕР·РєР»Р°РґРєСѓ.
        """
        expected = 0
        ok = True
        for index in range(len(panes) - 1):
            expected += widths.get(index, 0)
            expected = layout.clamp(expected, 60, max(60, self.h_split.winfo_width() - 60))
            try:
                actual = self.h_split.sashpos(index)
            except tk.TclError:
                return
            if actual < 60:
                ok = False
                break
        if not ok:
            self._schedule_sash_retry()

    def _apply_v_sash(self) -> None:
        """Р РѕР·СЃС‚Р°РІРёС‚Рё РІРµСЂС‚РёРєР°Р»СЊРЅС– СЃР°С€С– (СЃС‚СЂС–С‡РєР° / РєРѕРјРїРѕР·РµСЂ, СЂРµРґР°РєС‚РѕСЂ / РЅРёР·)."""
        try:
            # Р›С–РІР° РїР°РЅРµР»СЊ: С€РёСЂРёРЅР° Р· СЂРѕР·РєР»Р°РґРєРё Р°Р±Рѕ Р·Р±РµСЂРµР¶РµРЅР°, РѕР±РјРµР¶РµРЅР° С‚Р°Рє,
            # С‰РѕР± С†РµРЅС‚СЂСѓ Р»РёС€Р°Р»РѕСЃСЊ РјС–СЃС†Рµ РЅР°РІС–С‚СЊ РЅР° РІСѓР·СЊРєРѕРјСѓ РІС–РєРЅС–.
            try:
                split_w = self.side_split.winfo_width()
                if split_w > 40 and self.sidebar.winfo_ismapped():
                    saved = self.layout.get("sidebar_width",
                                            int(self.settings.ui.sidebar_width or 300))
                    limit = max(180, int(split_w * 0.45))
                    width = layout.clamp(saved, 180, limit)
                    if self._sidebar_collapsed:
                        width = theme.RAIL_COLLAPSED_WIDTH
                    if self.side_split.sashpos(0) != width:
                        self.side_split.sashpos(0, width)
            except (tk.TclError, ValueError, AttributeError):
                pass
            height = self.v_split.winfo_height()
            if height > 0:
                row = self.layout.get("composer_height", self.settings.ui.composer_height)
                # РљРѕРјРїРѕР·РµСЂ РќР†РљРћР›Р РЅРµ РјР°С” Р·РЅРёРєР°С‚Рё: РІС–РЅ РїРѕС‚СЂС–Р±РµРЅ РїС–Рґ С‡Р°СЃ СЂРѕР±РѕС‚Рё
                # Р°РіРµРЅС‚Р° РЅР°Р№Р±С–Р»СЊС€Рµ вЂ” С‰РѕР± РґРѕРїРёСЃР°С‚Рё СѓС‚РѕС‡РЅРµРЅРЅСЏ. РќРёР¶РЅСЏ РјРµР¶Р° вЂ”
                # theme.COMPOSER_HEIGHT (РїС–РґРєР°Р·РєРё + РїРѕР»Рµ + СЂСЏРґРѕРє РјРѕРґРµР»С–);
                # РІРµСЂС…РЅСЏ Р»РёС€Р°С” СЃС‚СЂС–С‡С†С– С‰РѕРЅР°Р№РјРµРЅС€Рµ 200 px, С‰РѕР± Р±СѓР»Рѕ РІРёРґРЅРѕ
                # С…РѕС‡ РєС–Р»СЊРєР° РїРѕРІС–РґРѕРјР»РµРЅСЊ.
                #
                # Р Р°РЅС–С€Рµ РІРµСЂС…РЅСЏ РјРµР¶Р° Р±СѓР»Р° ``height - 40%``: РЅР° РІРёСЃРѕРєРѕРјСѓ РІС–РєРЅС–
                # (1272 px) С†Рµ 764 px, С– Р·Р±РµСЂРµР¶РµРЅР° РІРёСЃРѕС‚Р° 792 РЅРµ
                # РІС–РґРЅРѕРІР»СЋРІР°Р»Р°СЃСЊ вЂ” РјРµР¶Р° В«СЃРїРѕРІР·Р°Р»Р°В» РЅР° 508 Р·Р°РјС–СЃС‚СЊ 480.
                # РўРµРїРµСЂ РѕР±РјРµР¶РµРЅРЅСЏ Р°Р±СЃРѕР»СЋС‚РЅРµ, Р° РЅРµ РїСЂРѕРїРѕСЂС†С–Р№РЅРµ: РІРёР±С–СЂ
                # РєРѕСЂРёСЃС‚СѓРІР°С‡Р° РїРµСЂРµР¶РёРІР°С” РїРµСЂРµР·Р°РїСѓСЃРє.
                low = theme.COMPOSER_HEIGHT
                high = max(low, height - 200)
                row = layout.clamp(row, low, high)
                target = max(0, height - row)
                if self.v_split.sashpos(0) != target:
                    self.v_split.sashpos(0, target)
            inner = self.editor_split.winfo_height()
            if self._bottom_shown and inner > 0:
                bottom = self.layout.get("bottom_height", self._bottom_height)
                # РќРµ РјРµРЅС€Рµ 180 px: С–РЅР°РєС€Рµ С…Р°Р± РјРѕРґРµР»РµР№ РЅРµ РІРјС–С‰Р°С” СЃРїРёСЃРѕРє
                # СЂРµР·СѓР»СЊС‚Р°С‚С–РІ С– РїРѕРєР°Р·СѓС” Р»РёС€Рµ СЂСЏРґРѕРє РїРѕС€СѓРєСѓ.
                bottom = layout.clamp(bottom, 180, max(200, inner - 160))
                self._bottom_height = bottom
                try:
                    self.bottom_tabs.configure(height=bottom)
                except tk.TclError:
                    pass
        except (tk.TclError, ValueError):
            pass

    def _remember_layout(self) -> None:
        """Р—Р°РїР°Рј'СЏС‚Р°С‚Рё РїРѕС‚РѕС‡РЅС– РїРѕР·РёС†С–С— СЃР°С€С–РІ."""
        try:
            # Р РѕР·РјС–СЂ РІС–РєРЅР°: РєРѕСЂРёСЃС‚СѓРІР°С‡ РјС–Рі СЂРѕР·С‚СЏРіРЅСѓС‚Рё Р№РѕРіРѕ РјРёС€РєРѕСЋ, С–
            # РЅР°СЃС‚СѓРїРЅРёР№ Р·Р°РїСѓСЃРє РјР°С” РІС–РґРєСЂРёС‚РёСЃСЊ С‚Р°Рє СЃР°РјРѕ (РґРёРІ. _apply_start_geometry).
            try:
                if self.state() != "zoomed":
                    self.layout.set("window_size",
                                    f"{self.winfo_width()}x{self.winfo_height()}")
                elif self.layout.get("window_size", ""):
                    # Р РѕР·РіРѕСЂРЅСѓС‚Рµ РІС–РєРЅРѕ РїРµСЂРµРєСЂРёРІР°С” Р·Р±РµСЂРµР¶РµРЅРёР№ СЂРѕР·РјС–СЂ вЂ” С‚РѕРґС–
                    # РїСЂРёР±РёСЂР°С”РјРѕ Р№РѕРіРѕ, С‰РѕР± РЅР°СЃС‚СѓРїРЅРёР№ Р·Р°РїСѓСЃРє Р·РЅРѕРІСѓ Р±СѓРІ РїРѕРІРЅРёРј.
                    try:
                        self.layout.values.pop("window_size", None)
                    except (AttributeError, TypeError):
                        pass
            except (tk.TclError, ValueError, AttributeError):
                pass
            # РЁРёСЂРёРЅР° Р»С–РІРѕС— РїР°РЅРµР»С– вЂ” С—С— С‚РµРїРµСЂ РјРѕР¶РЅР° С‚СЏРіРЅСѓС‚Рё РјРёС€РµСЋ.
            try:
                if self._sidebar_visible() and not self._sidebar_collapsed:
                    width = int(self.side_split.sashpos(0))
                    if width >= 180:
                        self.layout.set("sidebar_width", width)
                        # РўСЂРёРјР°С”РјРѕ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏ РІ Р·РіРѕРґС– Р· СЂРѕР·РєР»Р°РґРєРѕСЋ: РїР°РЅРµР»СЊ
                        # РІС–РґРєСЂРёРІР°С”С‚СЊСЃСЏ С‚С–С”СЋ Р¶ С€РёСЂРёРЅРѕСЋ С– Р· РЅР°Р»Р°С€С‚СѓРІР°РЅСЊ.
                        self.settings.ui.sidebar_width = width
            except (tk.TclError, ValueError, AttributeError):
                pass
            total = self.h_split.winfo_width()
            panes = [str(pane) for pane in self.h_split.panes()]
            if total > 0 and len(panes) >= 2:
                self.layout.set("chat_split", self.h_split.sashpos(0))
                last = total
                if len(panes) >= 3 and self._context_shown:
                    self.layout.set("context_width", max(170, total - self.h_split.sashpos(1)))
                if self._preview_shown and len(panes) >= 2:
                    # РџСЂРµРІ'СЋ вЂ” Р·Р°РІР¶РґРё РѕСЃС‚Р°РЅРЅСЏ РїР°РЅРµР»СЊ: Р№РѕРіРѕ С€РёСЂРёРЅР° С†Рµ
                    # РІС–РґСЃС‚Р°РЅСЊ РІС–Рґ РѕСЃС‚Р°РЅРЅСЊРѕРіРѕ СЃР°С€Р° РґРѕ РїСЂР°РІРѕРіРѕ РєСЂР°СЋ.
                    try:
                        pos = self.h_split.sashpos(len(panes) - 2)
                        width = total - pos
                        if width > 100:
                            self.layout.set("preview_width", width)
                    except (tk.TclError, ValueError):
                        pass
            height = self.v_split.winfo_height()
            if height > 0:
                self.layout.set("composer_height", height - self.v_split.sashpos(0))
            if self._bottom_shown:
                self.layout.set("bottom_height", self._bottom_height)
            layout.save(self.layout)
        except (tk.TclError, ValueError):
            pass

    def reset_layout(self) -> None:
        """РЎРєРёРЅСѓС‚Рё СЂРѕР·РєР»Р°РґРєСѓ РґРѕ С‚РёРїРѕРІРёС… Р·РЅР°С‡РµРЅСЊ."""
        self.layout = layout.Layout()
        layout.save(self.layout)
        self._sash_after(0)
        self.set_status("Р РѕР·РєР»Р°РґРєСѓ СЃРєРёРЅСѓС‚Рѕ РґРѕ С‚РёРїРѕРІРѕС—.")

    def _auto_context(self, show: bool) -> None:
        """РЈРІС–РјРєРЅСѓС‚Рё/РІРёРјРєРЅСѓС‚Рё РєРѕР»РѕРЅРєСѓ РєРѕРЅС‚РµРєСЃС‚Сѓ (Р·Р°РІР¶РґРё РѕСЃС‚Р°РЅРЅСЊРѕСЋ)."""
        if show == self._context_shown:
            return
        self._context_shown = bool(show)
        self._reorder_panes(with_centre=(getattr(self, "_view", "chat") == "workspace"))
        if show:
            try:
                self.context.refresh()
            except tk.TclError:
                pass

    # в”Ђв”Ђ РіР°СЂСЏС‡С– РєР»Р°РІС–С€С– в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _wire_shortcuts(self) -> None:
        bindings = {
            "<Control-n>": lambda e: self.new_file(),
            "<Control-o>": lambda e: self.open_file_dialog(),
            "<Control-s>": lambda e: self.save_file(),
            "<Control-Shift-S>": lambda e: self.save_file_as(),
            "<Control-w>": lambda e: self.close_tab(),
            "<Control-Shift-T>": lambda e: self.reopen_tab(),
            "<Control-p>": lambda e: self.quick_open(),
            "<Control-Shift-P>": lambda e: self.command_palette(),
            "<Control-Shift-M>": lambda e: self.open_model_hub(),
            "<Control-Shift-F>": lambda e: self.open_project_search(),
            "<Control-f>": lambda e: self.open_search(),
            "<Control-b>": lambda e: self.toggle_sidebar(),
            "<Control-Alt-b>": lambda e: self.toggle_chat(),
            "<Control-Alt-v>": lambda e: self.toggle_preview(),
            "<Control-grave>": lambda e: self.toggle_bottom(),
            "<Control-comma>": lambda e: self.open_settings(),
            "<Control-equal>": lambda e: self.zoom(1),
            "<Control-minus>": lambda e: self.zoom(-1),
            "<Control-Alt-Return>": lambda e: self.send_file_to_agent(),
            "<Control-Alt-q>": lambda e: self.add_queue_dialog(),
            "<Control-Alt-w>": lambda e: self.show_bottom("tasks"),
            "<Control-Alt-s>": lambda e: self.stop_plan(),
            "<Control-Alt-k>": lambda e: self.show_side("skills"),
            "<Control-Alt-d>": lambda e: self.show_side("cases"),
            "<Control-Alt-a>": lambda e: self.toggle_autonomous(),
            "<Control-Alt-i>": lambda e: self.show_side("rag"),
            "<Control-Alt-t>": lambda e: self.show_side("tools"),
            "<Control-Alt-f>": lambda e: self.toggle_focus_mode(),
            "<Control-Alt-r>": lambda e: self.reset_layout(),
            "<Control-Shift-A>": lambda e: self.show_ast_tree(),
            "<Control-Alt-p>": lambda e: self.open_site(),
            "<Control-Alt-l>": lambda e: self.open_url_dialog(),
            "<Control-F5>": lambda e: self.run_tests(),
            "<F5>": lambda e: self.run_current_file(),
        }
        for sequence, handler in bindings.items():
            self.bind_all(sequence, self._wrap(handler), add="+")

        # Clicking anywhere outside a popup (or switching apps) must close it:
        # an -topmost card left on screen looks like a frozen second window.
        self.bind("<FocusOut>", self._on_window_deactivate, add="+")
        self.bind("<Button-1>", self._on_root_click, add="+")
        # Р‘СѓРґСЊ-СЏРєРёР№ РІРІС–Рґ РєРѕСЂРёСЃС‚СѓРІР°С‡Р° = В«РІС–РЅ РїСЂР°С†СЋС”В»: С‚Р°Р№РјРµСЂ РІРёРІР°РЅС‚Р°Р¶РµРЅРЅСЏ
        # РјРѕРґРµР»С– СЃРєРёРґР°С”С‚СЊСЃСЏ. РЎР»СѓС…Р°С”РјРѕ РЅР° СЂС–РІРЅС– РІС–РєРЅР°, С‚РѕР¶ РєР»Р°РІС–С€С– РІ
        # СЂРµРґР°РєС‚РѕСЂС– Р№ Сѓ РїРѕР»С– С‡Р°С‚Сѓ С‚РµР¶ СЂР°С…СѓСЋС‚СЊСЃСЏ.
        for sequence in ("<KeyPress>", "<ButtonPress>", "<MouseWheel>"):
            try:
                self.bind_all(sequence, self._wake_on_action, add="+")
            except tk.TclError:
                pass

    def _on_root_click(self, event=None) -> None:
        """РљР»С–Рє Сѓ РіРѕР»РѕРІРЅРѕРјСѓ РІС–РєРЅС– Р·Р°РєСЂРёРІР°С” СЃРїР»РёРІРЅС– РєР°СЂС‚РєРё.

        РљР°СЂС‚РєРё РјР°СЋС‚СЊ ``-topmost``; Р±РµР· С†СЊРѕРіРѕ РІРѕРЅРё Р»РёС€Р°Р»РёСЃСЊ РЅР° РµРєСЂР°РЅС– РїС–СЃР»СЏ
        РїРµСЂРµС…РѕРґСѓ РґРѕ С–РЅС€РѕС— РґС–С— Р№ РїРµСЂРµРєСЂРёРІР°Р»Рё РґС–Р°Р»РѕРіРё.
        """
        if event is not None and event.widget is not self:
            return
        self._close_popovers()

    def _wrap(self, handler):
        def inner(event=None):
            try:
                return handler(event)
            except Exception as exc:  # noqa: BLE001 - РЅРµ Р»Р°РјР°С”РјРѕ РѕР±СЂРѕР±РєСѓ РєР»Р°РІС–С€
                self.set_status(f"РџРѕРјРёР»РєР° РґС–С—: {exc}")
                return None

        return inner

    # в”Ђв”Ђ СЃС‚Р°СЂС‚ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _startup(self) -> None:
        self.set_status(f"Р РѕР±РѕС‡Р° С‚РµРєР°: {self.settings.workspace}")
        # Р—Р°СЃС‚РѕСЃСѓРІР°С‚Рё Р·Р±РµСЂРµР¶РµРЅРёР№ СЂРµР¶РёРј РґРѕР·РІРѕР»С–РІ РґРѕ С‡Р°С‚Сѓ Р№ Р°РіРµРЅС‚Р°.
        try:
            self.chat.set_permission_mode(self.permission_mode)
        except (tk.TclError, AttributeError):
            pass
        self.agent.permission_mode = self.permission_mode
        # Р—Р°РїР°Рј'СЏС‚Р°С‚Рё Р±Р°Р·РѕРІРёР№ Р»С–РјС–С‚ РєСЂРѕРєС–РІ: СЂРµР¶РёРјРё РЅРµ РјР°СЋС‚СЊ Р№РѕРіРѕ РїРµСЂРµРїРёСЃСѓРІР°С‚Рё.
        modes.remember_base_steps(self.settings.agent.max_steps)
        # Р РµР¶РёРј СЂРѕР±РѕС‚Рё: РґРѕР·РІРѕР»Рё, Р»С–РјС–С‚ РєСЂРѕРєС–РІ С– РїС–РґРєР°Р·РєР° РјРѕРґРµР»С–.
        self.set_agent_mode(self.agent_mode)
        self._apply_cloud_provider()
        # РЇРєС‰Рѕ РјРѕРґРµР»СЊ РЅРµ РІРёР±СЂР°РЅР°, Р° GGUF Р»РµР¶РёС‚СЊ РЅР° РґРёСЃРєСѓ вЂ” РїС–РґС…РѕРїРёС‚Рё С—С—.
        # Р†РЅР°РєС€Рµ Р°РіРµРЅС‚ РїРёС€Рµ В«РњРѕРґРµР»СЊ РЅРµ РІРёР±СЂР°РЅР°В» Р№ РјРѕРІС‡РєРё Р№РґРµ РІ РѕС„Р»Р°Р№РЅ-СЂРѕСѓС‚РµСЂ,
        # С…РѕС‡ РјРѕРґРµР»СЊ Сѓ РєРѕСЂРёСЃС‚СѓРІР°С‡Р° РІР¶Рµ С”.
        self._adopt_local_model()
        self._sync_chat_model()
        # Р‘РµР· РІРёР±СЂР°РЅРѕРіРѕ РїСЂРѕС”РєС‚Сѓ РЅРµ РїРѕРєР°Р·СѓС”РјРѕ РІРјС–СЃС‚ РґРѕРјР°С€РЅСЊРѕС— С‚РµРєРё: Сѓ
        # РїСЂРѕРІС–РґРЅРёРєСѓ Р№ РїР°РЅРµР»С– В«Р—РјС–РЅРёВ» Р·'СЏРІР»СЏР»РёСЃСЊ ``AppData``, ``NTUSER.DAT``
        # С‚Р° С–РЅС€Рµ, С– С†Рµ РІРёРіР»СЏРґР°Р»Рѕ С‚Р°Рє, РЅС–Р±Рё Р°РіРµРЅС‚ СѓР¶Рµ РїСЂР°С†СЋС” РІ РґРѕРјС–.
        start = Path(self.settings.workspace) if self.has_project() else None
        self.terminal.set_cwd(start or Path(self.settings.workspace))
        self.set_project(str(start) if start else "")
        self._show_side_initial()
        # РџС–РґРїРёСЃ РјРѕРґРµР»С– РІ С‡Р°С‚С– РјР°С” Р±СѓС‚Рё РїСЂР°РІРёР»СЊРЅРёРј РѕРґСЂР°Р·Сѓ, Р° РЅРµ РїС–СЃР»СЏ РїРµСЂС€РѕС—
        # РїРµСЂРµРІС–СЂРєРё СЃРµСЂРІРµСЂР° вЂ” С–РЅР°РєС€Рµ Р·Р°РіРѕР»РѕРІРѕРє РїРѕРєР°Р·СѓС” В«РјРѕРґРµР»СЊ РЅРµ РІРёР±СЂР°РЅР°В».
        self._on_model_changed()
        self._ensure_chat()
        self._adopt_orphan_tasks()
        self.nav_refresh_history()

        if self.settings.ui.restore_session:
            for raw in (self.session.get("tabs") or [])[:12]:
                path = Path(raw)
                if path.exists():
                    self.tabs.open_file(path)

        # РџРѕС‡Р°С‚РєРѕРІРёР№ РІРёРґ: РґС–Р°Р»РѕРі Р°Р±Рѕ СЂРѕР±РѕС‡Р° РѕР±Р»Р°СЃС‚СЊ (СЏРє Р·Р±РµСЂС–Рі РєРѕСЂРёСЃС‚СѓРІР°С‡).
        self._view = ""
        self.set_view(getattr(self.settings.ui, "view", "chat"))

        self._sync_rail_state()
        self._refresh_context()
        self._update_queue_badge()
        # РџСЂРёР±РёСЂР°С”РјРѕ СЂСѓС€С–С—, С‰Рѕ Р»РёС€РёР»РёСЃСЊ РІС–Рґ РїРѕРїРµСЂРµРґРЅСЊРѕРіРѕ Р·Р°РїСѓСЃРєСѓ IDE. РЇРєС‰Рѕ
        # РїСЂРѕРіСЂР°РјР° Р·Р°РєСЂРёР»Р°СЃСЊ Р°РІР°СЂС–Р№РЅРѕ, РІРѕРЅРё РґРѕСЃС– С‚СЂРёРјР°СЋС‚СЊ РІС–РґРµРѕРїР°Рј'СЏС‚СЊ вЂ”
        # С– РєРѕСЂРёСЃС‚СѓРІР°С‡ Р±Р°С‡РёС‚СЊ В«С‰РѕСЃСЊ РіСЂСѓР·РёС‚СЊ РІС–РґРµРѕРєР°СЂС‚СѓВ» С‰Рµ РґРѕ СЃС‚Р°СЂС‚Сѓ РјРѕРґРµР»С–.
        # Р РѕР±РёРјРѕ Сѓ С„РѕРЅС–, С‰РѕР± РЅРµ Р·Р°С‚СЂРёРјСѓРІР°С‚Рё РїРµСЂС€РёР№ РєР°РґСЂ.
        threading.Thread(target=self._cleanup_orphans_quietly, daemon=True,
                         name="cleanup-orphans").start()
        # в”Ђв”Ђ РџРѕСЂСЏРґРѕРє Р·Р°РїСѓСЃРєСѓ: СЃРїРµСЂС€Сѓ РњРћР”Р•Р›Р¬, РїРѕС‚С–Рј MCP в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        # Р Р°РЅС–С€Рµ MCP СЃС‚Р°СЂС‚СѓРІР°РІ С‡РµСЂРµР· 400 РјСЃ, Р° Р°РІС‚РѕР·Р°РїСѓСЃРє РјРѕРґРµР»С– вЂ” С‡РµСЂРµР·
        # 900 РјСЃ: MCP РїС–РґРЅС–РјР°РІСЃСЏ Р”Рћ РјРѕРґРµР»С– Р№ РјС–Рі РїР°РґР°С‚Рё СЃР°РјРµ С‡РµСЂРµР· С†Рµ
        # (СЃРµСЂРІРµСЂ, С‰Рѕ С‡РµРєР°С” РјРѕРґРµР»СЊ, РЅРµ РІСЃС‚РёРіР°РІ). РўРµРїРµСЂ Р°РІС‚РѕР·Р°РїСѓСЃРє С–РґРµ
        # РїРµСЂС€РёРј, Р° MCP вЂ” Р· ``_after_auto_setup``, РєРѕР»Рё РјРѕРґРµР»СЊ СѓР¶Рµ РіРѕС‚РѕРІР°.
        #
        # РЇРєС‰Рѕ Р°РІС‚РѕР·Р°РїСѓСЃРє РІРёРјРєРЅРµРЅРѕ Р°Р±Рѕ РјРѕРґРµР»С– РЅРµРјР°С”, ``_after_auto_setup``
        # СѓСЃРµ РѕРґРЅРѕ РІРёРєР»РёС‡Рµ ``_load_mcp_async``: MCP РЅРµ РјР°С” С‡РµРєР°С‚Рё РІС–С‡РЅРѕ.
        self.after(400, self._auto_setup_in_background)
        self.after(2600, self._load_mcp_if_not_started)
        self._queue_pump()
        # РџСЂРѕСЃС‚С–Р№: Сѓ РЅРµР°РІС‚РѕРЅРѕРјРЅРѕРјСѓ СЂРµР¶РёРјС– РјРѕРґРµР»СЊ РІС–РґРґР°С” РїР°Рј'СЏС‚СЊ РІС–РґРµРѕРєР°СЂС‚Рё,
        # РєРѕР»Рё РєРѕСЂРёСЃС‚СѓРІР°С‡ РЅРµ РїСЂР°С†СЋС”. РўС–Рє Р»РµРіРєРёР№ (СЂР°Р· РЅР° 20 СЃ).
        self._idle_tick()
        if not self.settings.first_run_done:
            self.after(600, self.open_first_run)
        elif not self.has_project():
            # РџСЂРѕС”РєС‚Сѓ С‰Рµ РЅРµ РІРёР±СЂР°РЅРѕ: Р·Р°РјС–СЃС‚СЊ РїРѕСЂРѕР¶РЅСЊРѕРіРѕ С‡Р°С‚Сѓ РїРѕРєР°Р·СѓС”РјРѕ
            # РµРєСЂР°РЅ РІРёР±РѕСЂСѓ С‚РµРєРё вЂ” Р°РіРµРЅС‚ РЅРµ РјРѕР¶Рµ РїСЂР°С†СЋРІР°С‚Рё Р±РµР· РЅРµС—.
            self.after(120, self._show_project_gate)
        else:
            # РЎС‚Р°СЂС‚РѕРІРёР№ РµРєСЂР°РЅ РїРѕРєР°Р·СѓС”РјРѕ Р»РёС€Рµ РєРѕР»Рё РІ Р°РєС‚РёРІРЅС–Р№ СЃРµСЃС–С— С‰Рµ РЅРµРјР°С”
            # Р¶РѕРґРЅРѕРіРѕ РїРѕРІС–РґРѕРјР»РµРЅРЅСЏ. РЇРєС‰Рѕ С–СЃС‚РѕСЂС–СЏ С” вЂ” РѕРґСЂР°Р·Сѓ РІС–РґРЅРѕРІР»СЋС”РјРѕ С‡Р°С‚,
            # С–РЅР°РєС€Рµ welcome-РѕРІРµСЂР»РµР№ РїРµСЂРµРєСЂРёРІР°С” СЃС‚СЂС–С‡РєСѓ С– В«С–СЃС‚РѕСЂС–СЏ Р·РЅРёРєР°С”В».
            active = self.chat_store.active()
            if active is not None and active.message_count:
                self.open_chat(active.id)
            else:
                self.after(120, self.show_welcome)

    def _project_root(self) -> Optional[Path]:
        """РўРµРєР° РїСЂРѕС”РєС‚Сѓ РґР»СЏ РїР°РЅРµР»РµР№ вЂ” Р°Р±Рѕ ``None``, РїРѕРєРё С—С— РЅРµ РІРёР±СЂР°РЅРѕ.

        РџР°РЅРµР»С– В«Р—РјС–РЅРёВ» Р№ РїСЂРѕРІС–РґРЅРёРє СЂР°РЅС–С€Рµ Р±СЂР°Р»Рё ``settings.workspace``
        РЅР°РїСЂСЏРјСѓ. РћСЃРєС–Р»СЊРєРё С‚Р°Рј С‚РёРїРѕРІРѕ РґРѕРјР°С€РЅСЏ С‚РµРєР°, РІРѕРЅРё СЃРєР°РЅСѓРІР°Р»Рё
        ``C:\\Users\\<С–Рј'СЏ>`` С– РїРѕРєР°Р·СѓРІР°Р»Рё ``AppData`` С‚Р° СЃР»СѓР¶Р±РѕРІС– С„Р°Р№Р»Рё.
        """
        if not self.has_project():
            return None
        try:
            return Path(self.settings.workspace)
        except (TypeError, ValueError):
            return None

    def set_project(self, path: str) -> None:
        """РџРѕРєР°Р·Р°С‚Рё СЂРѕР±РѕС‡РёР№ РїСЂРѕС”РєС‚ Сѓ Р±С–С‡РЅС–Р№ РїР°РЅРµР»С–, С€Р°РїС†С– Р№ РїС–РіСѓР»С†С– С‡Р°С‚Сѓ."""
        name = Path(path).name if path else ""
        try:
            self.project_label.configure(text=name or "РЅРµ РѕР±СЂР°РЅРѕ")
        except (tk.TclError, AttributeError):
            pass
        try:
            self.header.set_workspace(name)
        except (tk.TclError, AttributeError):
            pass
        # РџС–РіСѓР»РєР° РЅР°Рґ РїРѕР»РµРј РІРІРѕРґСѓ РїРѕРєР°Р·СѓС” С‚Сѓ СЃР°РјСѓ С‚РµРєСѓ: Р»СЋРґРёРЅР° РїРёС€Рµ Р·Р°РґР°С‡Сѓ
        # Р№ Р±Р°С‡РёС‚СЊ, Сѓ СЏРєС–Р№ С‚РµС†С– РїСЂР°С†СЋРІР°С‚РёРјРµ Р°РіРµРЅС‚, РЅРµ РґРёРІР»СЏС‡РёСЃСЊ Сѓ С€Р°РїРєСѓ.
        try:
            self.chat.set_workspace(name, path=str(path or ""))
        except (tk.TclError, AttributeError):
            pass

    def _active_chat_id(self) -> str:
        """Р†РґРµРЅС‚РёС„С–РєР°С‚РѕСЂ Р°РєС‚РёРІРЅРѕРіРѕ С‡Р°С‚Сѓ (``""`` вЂ” С‡РµСЂРЅРµС‚РєР° Р°Р±Рѕ С‡Р°С‚Сѓ РЅРµРјР°С”)."""
        try:
            return str(getattr(self.chat_store, "active_id", "") or "")
        except AttributeError:
            return ""

    def _adopt_orphan_tasks(self) -> int:
        """РџСЂРёРІ'СЏР·Р°С‚Рё Р·Р°РґР°С‡С– Р±РµР· РІР»Р°СЃРЅРёРєР° РґРѕ Р°РєС‚РёРІРЅРѕРіРѕ С‡Р°С‚Сѓ.

        Р”Рѕ РІРёРїСЂР°РІР»РµРЅРЅСЏ РєСЂРѕРєРё РїР»Р°РЅСѓ Р№ Р·Р°РґР°С‡С– Р°РІС‚РѕРЅРѕРјРЅРѕРіРѕ СЂРµР¶РёРјСѓ РґРѕРґР°РІР°Р»РёСЃСЊ
        Р±РµР· ``chat_id`` вЂ” РїС–СЃР»СЏ РІРёРґР°Р»РµРЅРЅСЏ С‡Р°С‚Сѓ РІРѕРЅРё Р»РёС€Р°Р»РёСЃСЊ Сѓ С‡РµСЂР·С–
        В«СЃРёСЂРѕС‚Р°РјРёВ» Р№ РІРёСЃС–Р»Рё РІ РїР°РЅРµР»С– В«РђРІС‚РѕРјР°С‚РёР·Р°С†С–С—В» (СЃР°РјРµ С†Рµ РІРёРґРЅРѕ РЅР°
        СЃРєСЂС–РЅС€РѕС‚С– РєРѕСЂРёСЃС‚СѓРІР°С‡Р°: С‚СЂРё Р·Р°РґР°С‡С–, СЏРєС– РјР°Р»Рё Р·РЅРёРєРЅСѓС‚Рё Р· С‡Р°С‚РѕРј).

        РўРµРїРµСЂ РєРѕР¶РЅР° РЅРѕРІР° Р·Р°РґР°С‡Р° РјР°С” РІР»Р°СЃРЅРёРєР°; СЃС‚Р°СЂС– РґС–СЃС‚Р°СЋС‚СЊ Р°РєС‚РёРІРЅРёР№ С‡Р°С‚,
        С‰РѕР± РІРёРґР°Р»РµРЅРЅСЏ С‡Р°С‚Сѓ РїСЂРёР±РёСЂР°Р»Рѕ Р№ С—С….
        """
        chat = self.chat_store.active()
        if chat is None:
            return 0
        adopted = self.task_queue.adopt_orphans(chat.id)
        if adopted:
            LOG.info("РџСЂРёРІ'СЏР·Р°РЅРѕ Р·Р°РґР°С‡ Р±РµР· С‡Р°С‚Сѓ РґРѕ %s: %s", chat.id, adopted)
            self._update_queue_badge()
        return adopted

    def nav_refresh_history(self) -> None:
        """РћРЅРѕРІРёС‚Рё СЃРїРёСЃРѕРє СЃРµСЃС–Р№ Сѓ Р±С–С‡РЅС–Р№ РїР°РЅРµР»С–."""
        try:
            self.chat_list.refresh()
        except (tk.TclError, AttributeError):
            pass
        try:
            self.chat_list.set_active(getattr(self.chat_store, "active_id", ""))
        except (tk.TclError, AttributeError):
            pass

    def show_welcome(self) -> None:
        """РџРѕРєР°Р·Р°С‚Рё СЃС‚Р°СЂС‚РѕРІРёР№ РµРєСЂР°РЅ Р·Р°РїРёС‚Сѓ (РІРёР±С–СЂ С‚РµРєРё Р°Р±Рѕ РїРµСЂС€РёР№ Р·Р°РїРёС‚)."""
        if not getattr(self, "_welcome_shown", False):
            self._build_welcome()
        try:
            self.welcome.pack(fill="both", expand=True)
            self.welcome.set_workspace(self.settings.workspace)
            self.welcome.set_model(self.settings.llm.model)
            self.workspace_host.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.workspace_host.lift()
        except (tk.TclError, AttributeError):
            pass
        self._welcome_shown = True

    def hide_welcome(self) -> None:
        self._hide_welcome()

    # в”Ђв”Ђ СЃС‚Р°СЂС‚РѕРІРёР№ РµРєСЂР°РЅ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _build_welcome(self) -> None:
        """Р’РµР»РёРєРёР№ РµРєСЂР°РЅ Р·Р°РїРёС‚Сѓ вЂ” С‚Рµ, С‰Рѕ РІРёРґРЅРѕ РѕРґСЂР°Р·Сѓ РїС–СЃР»СЏ Р·Р°РїСѓСЃРєСѓ."""
        self.welcome = welcome.WelcomeScreen(
            self.workspace_host,
            self.theme,
            on_submit=self._start_from_welcome,
            on_open_folder=self.open_folder_dialog,
            on_hint=self._on_welcome_hint,
            workspace=self.settings.workspace,
            model_label=self.settings.llm.model,
        )
        self.welcome.pack(fill="both", expand=True)
        self._welcome_shown = True
        # РџРµСЂС€РёР№ Р·Р°РїСѓСЃРє Р±РµР· Р¶РѕРґРЅРѕРіРѕ РІС–РґРєСЂРёС‚РѕРіРѕ С„Р°Р№Р»Сѓ вЂ” РїРѕРєР°Р·СѓС”РјРѕ СЃР°РјРµ Р·Р°РїРёС‚,
        # Р° РЅРµ РїРѕСЂРѕР¶РЅС–Р№ СЂРµРґР°РєС‚РѕСЂ.
        return None

    def _hide_welcome(self) -> None:
        # РҐРѕСЃС‚ Р·РЅС–РјР°С”РјРѕ Р·Р°РІР¶РґРё, РЅР°РІС–С‚СЊ СЏРєС‰Рѕ РїСЂР°РїРѕСЂРµС†СЊ СѓР¶Рµ СЃРєРёРЅСѓС‚Рѕ: РѕРІРµСЂР»РµР№
        # РјС–Рі Р»РёС€РёС‚РёСЃСЊ РІС–Рґ РїРѕРїРµСЂРµРґРЅСЊРѕРіРѕ РїРѕРєР°Р·Сѓ (РЅР°РїСЂ. РїС–СЃР»СЏ РІС–РґРєСЂРёС‚С‚СЏ С‡Р°С‚Сѓ
        # Р· С–СЃС‚РѕСЂС–С”СЋ), С– С‚РѕРґС– РІС–РЅ РїРµСЂРµРєСЂРёРІР°С” СЃС‚СЂС–С‡РєСѓ РґС–Р°Р»РѕРіСѓ.
        if getattr(self, "_welcome_shown", False):
            try:
                self.welcome.pack_forget()
            except (tk.TclError, AttributeError):
                pass
        try:
            self.workspace_host.place_forget()
        except tk.TclError:
            pass
        self._welcome_shown = False

    def _start_from_welcome(self, text: str) -> None:
        """РџРµСЂС€РёР№ Р·Р°РїРёС‚ Р·С– СЃС‚Р°СЂС‚РѕРІРѕРіРѕ РµРєСЂР°РЅР°: РІС–РґРєСЂРёРІР°С”РјРѕ СЂРѕР±РѕС‡Сѓ РѕР±Р»Р°СЃС‚СЊ.

        РЎРїРµСЂС€Сѓ РїРµСЂРµРІС–СЂСЏС”РјРѕ С‚РµРєСѓ РїСЂРѕС”РєС‚Сѓ Р№ Р»РёС€Рµ РїРѕС‚С–Рј С…РѕРІР°С”РјРѕ СЃС‚Р°СЂС‚РѕРІРёР№ РµРєСЂР°РЅ:
        С–РЅР°РєС€Рµ Р·Р°РїРёС‚ Р±РµР· РїСЂРѕС”РєС‚Сѓ Р·Р°Р±РёСЂР°РІ РµРєСЂР°РЅ, РЅС–С‡РѕРіРѕ РЅРµ РЅР°РґСЃРёР»Р°РІ, С–
        РєРѕСЂРёСЃС‚СѓРІР°С‡ Р»РёС€Р°РІСЃСЏ РїРµСЂРµРґ РїРѕСЂРѕР¶РЅС–Рј С‡Р°С‚РѕРј Р±РµР· РїРѕСЏСЃРЅРµРЅРЅСЏ.
        """
        if not self.has_project():
            # РЎС‚Р°СЂС‚РѕРІРёР№ РµРєСЂР°РЅ Р»РёС€Р°С”С‚СЊСЃСЏ РЅР° РјС–СЃС†С– вЂ” РІС–РЅ С– С” РІРёР±РѕСЂРѕРј С‚РµРєРё.
            # РўРµРєСЃС‚ Р·Р°РїРёС‚Сѓ РЅРµ РІС‚СЂР°С‡Р°С”РјРѕ: РєРѕСЂРёСЃС‚СѓРІР°С‡ РѕРґСЂР°Р·Сѓ Р№РѕРіРѕ РїРѕР±Р°С‡РёС‚СЊ.
            try:
                self.welcome.set_text(text)
            except (tk.TclError, AttributeError):
                pass
            self._show_project_gate(
                reason="Р§Р°С‚ РІС–РґРєСЂРёС”С‚СЊСЃСЏ, С‰РѕР№РЅРѕ Р±СѓРґРµ РІРёР±СЂР°РЅРѕ С‚РµРєСѓ РїСЂРѕС”РєС‚Сѓ.")
            self.set_status("РЎРїРµСЂС€Сѓ РІРёР±РµСЂРё РїР°РїРєСѓ РїСЂРѕС”РєС‚Сѓ вЂ” Р±РµР· РЅРµС— Р°РіРµРЅС‚Сѓ РЅС–РґРµ РїСЂР°С†СЋРІР°С‚Рё.")
            return
        self._hide_welcome()
        self._ensure_chat()
        self.show_chat(True)
        self.chat._send(text)

    def _on_welcome_hint(self, title: str, _prompt: str) -> None:
        self.set_status(f"РџС–РґРєР°Р·РєР°: {title}")

    def _ensure_chat(self) -> None:
        """Р“Р°СЂР°РЅС‚СѓРІР°С‚Рё Р°РєС‚РёРІРЅРёР№ С‡Р°С‚ вЂ” Р°Р»Рµ Р»РёС€Рµ РєРѕР»Рё С” СЂРѕР±РѕС‡РёР№ РїСЂРѕС”РєС‚.

        Р‘РµР· РІРёР±СЂР°РЅРѕС— С‚РµРєРё С‡Р°С‚ РЅРµ СЃС‚РІРѕСЂСЋС”С‚СЊСЃСЏ: С–РЅР°РєС€Рµ РЅР° СЃС‚Р°СЂС‚С– Р·'СЏРІР»СЏРІСЃСЏ Р±
        В«РќРѕРІРёР№ Р°РіРµРЅС‚В», РїСЂРёРІ'СЏР·Р°РЅРёР№ РґРѕ РґРѕРјР°С€РЅСЊРѕС— С‚РµРєРё РєРѕСЂРёСЃС‚СѓРІР°С‡Р°, С– РїРµСЂС€РёР№
        Р¶ Р·Р°РїРёС‚ РїСЂР°РІРёРІ Р±Рё С„Р°Р№Р»Рё РЅРµ С‚Р°Рј, РґРµ С‚СЂРµР±Р°.

        Р—Р°РѕРґРЅРѕ РїСЂРёР±РёСЂР°С”РјРѕ РїРѕСЂРѕР¶РЅС– С‡Р°С‚Рё, С‰Рѕ Р»РёС€РёР»РёСЃСЊ РІС–Рґ РїРѕРїРµСЂРµРґРЅС–С… СЃРµСЃС–Р№:
        СЂР°РЅС–С€Рµ РєРѕР¶РЅРµ РЅР°С‚РёСЃРєР°РЅРЅСЏ В«Г—В» СЃС‚РІРѕСЂСЋРІР°Р»Рѕ РЅРѕРІРёР№ С‡Р°С‚ В«РїСЂРѕ Р·Р°РїР°СЃВ», С–
        С—С… РЅР°РєРѕРїРёС‡СѓРІР°Р»РѕСЃСЊ РґРµСЃСЏС‚РєР°РјРё (РїРµСЂРµРІС–СЂРµРЅРѕ: 35 РїРѕСЂРѕР¶РЅС–С… С–Р· 36).
        """
        dropped = self._prune_empty_chats()
        if dropped:
            LOG.info("РџСЂРёР±СЂР°РЅРѕ РїРѕСЂРѕР¶РЅС–С… С‡Р°С‚С–РІ: %s", dropped)
        if not self.has_project():
            return None
        if not getattr(self.chat_store, "chats", []):
            created = self.new_chat_session()
            return self.chat_store.active() if created else None
        try:
            chat = self.chat_store.ensure_active(workspace=str(self.settings.workspace),
                                                 model=self.settings.llm.model)
            # РљРѕРЅС‚РµРєСЃС‚ РІС–РґРЅРѕРІР»СЋС”РјРѕ Р№ С‚СѓС‚: ``ensure_active`` РѕР±РёСЂР°С” С‡Р°С‚ Р±РµР·
            # РїСЂРѕС…РѕРґР¶РµРЅРЅСЏ С‡РµСЂРµР· ``open_chat`` (РЅР°РїСЂ. РїС–СЃР»СЏ РІРёР±РѕСЂСѓ С‚РµРєРё).
            if chat is not None and chat.id:
                self._load_chat_context(chat.id)
            self.chat_list.refresh()
            self._sync_chat_title()
            return chat
        except Exception:  # noqa: BLE001 - С‡Р°С‚ РЅРµ РјР°С” Р»Р°РјР°С‚Рё СЃС‚Р°СЂС‚
            return None

    def _prune_empty_chats(self) -> int:
        """Р’РёРґР°Р»РёС‚Рё С‡Р°С‚Рё Р±РµР· Р¶РѕРґРЅРѕРіРѕ РїРѕРІС–РґРѕРјР»РµРЅРЅСЏ (Р»РёС€РёС‚Рё Р°РєС‚РёРІРЅРёР№).

        РђРєС‚РёРІРЅРёР№ РїРѕСЂРѕР¶РЅС–Р№ С‡Р°С‚ вЂ” С†Рµ РЅРѕСЂРјР°Р»СЊРЅРёР№ СЃС‚Р°РЅ В«С‰РѕР№РЅРѕ СЃС‚РІРѕСЂРёРІ С– С‰Рµ РЅРµ
        РЅР°РїРёСЃР°РІВ»; Р№РѕРіРѕ РЅРµ С‡С–РїР°С”РјРѕ.
        """
        store = self.chat_store
        try:
            active = str(getattr(store, "active_id", "") or "")
            keep = [chat for chat in store.chats
                    if chat.message_count or chat.id == active or chat.pinned]
            dropped = len(store.chats) - len(keep)
            if dropped:
                store.chats = keep
                store.save()
            return dropped
        except Exception:  # noqa: BLE001 - РїСЂРёР±РёСЂР°РЅРЅСЏ РЅРµ РјР°С” Р»Р°РјР°С‚Рё СЃС‚Р°СЂС‚
            LOG.debug("РќРµ РІРґР°Р»РѕСЃСЊ РїСЂРёР±СЂР°С‚Рё РїРѕСЂРѕР¶РЅС– С‡Р°С‚Рё", exc_info=True)
            return 0

    def _auto_setup_in_background(self) -> None:
        """РўРёС…Рѕ РїС–РґРіРѕС‚СѓРІР°С‚Рё РїСЂРѕС”РєС‚: РїСЂРѕС„С–Р»СЊ, СЃРєС–Р»Рё, РјРѕРґРµР»СЊ С– СЃРµСЂРІРµСЂ.

        РљРѕСЂРёСЃС‚СѓРІР°С‡ Р·Р°РїСѓСЃРєР°С” РїСЂРѕРіСЂР°РјСѓ Р№ РѕРґСЂР°Р·Сѓ РѕС‚СЂРёРјСѓС” СЂРѕР±РѕС‡Сѓ РјРѕРґРµР»СЊ: СЏРєС‰Рѕ
        Р»РѕРєР°Р»СЊРЅР° РјРѕРґРµР»СЊ СѓР¶Рµ С” вЂ” IDE СЃР°РјР° РїС–РґРЅС–РјР°С” СЃРµСЂРІРµСЂ; СЏРєС‰Рѕ С”
        РЅР°Р»Р°С€С‚РѕРІР°РЅРёР№ Р·РѕРІРЅС–С€РЅС–Р№ СЃРµСЂРІРµСЂ вЂ” РІРёРєРѕСЂРёСЃС‚РѕРІСѓС” Р№РѕРіРѕ.
        """
        if self._setup_busy:
            return
        self._setup_busy = True
        root = Path(self.settings.workspace)

        def work() -> None:
            result: dict = {}
            try:
                profile, proposals = auto_setup.build_plan(root)
                installed = auto_setup.install_proposals(root, proposals)
                result.update(profile=profile, installed=installed)
            except Exception as exc:  # noqa: BLE001 - Р°РІС‚РѕРЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏ РЅРµ РєСЂРёС‚РёС‡РЅРµ
                LOG.warning("РџСЂРѕС„С–Р»СЊ/СЃРєС–Р»Рё РЅРµ РІРґР°Р»РёСЃСЊ: %s", exc, exc_info=True)

            try:
                local = [p.name for p in hub.local_models()]
                engine_ok = runtime.engine_installed()
                alive = self._server_alive()
                plan = auto_setup.describe_model_setup(
                    self.settings, engine_installed=engine_ok,
                    local_models=local, server_alive=alive,
                )
                result["plan"] = plan
                # в”Ђв”Ђ РџРѕСЂСЏРґРѕРє Р·Р°РїСѓСЃРєСѓ РјРѕРґРµР»С– в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
                # Р’Р›РђРЎРќРР™ СЂСѓС€С–Р№ вЂ” РіРѕР»РѕРІРЅРёР№ С€Р»СЏС…: РјРѕРґРµР»СЊ РїСЂР°С†СЋС” РІСЃРµСЂРµРґРёРЅС–
                # РїСЂРѕС†РµСЃСѓ IDE, Р±РµР· СЃС‚РѕСЂРѕРЅРЅС–С… СЃРµСЂРІС–СЃС–РІ. Р”Р»СЏ РЅСЊРѕРіРѕ РЅРµ РїРѕС‚СЂС–Р±РµРЅ
                # РЅС– Р¶РёРІРёР№ HTTP-СЃРµСЂРІРµСЂ, РЅС– ``llama-server``: РґРѕСЃС‚Р°С‚РЅСЊРѕ
                # РІСЃС‚Р°РЅРѕРІР»РµРЅРѕРіРѕ СЂСѓС€С–СЏ Р№ С„Р°Р№Р»Сѓ РјРѕРґРµР»С–.
                #
                # Р Р°РЅС–С€Рµ СѓРјРѕРІРѕСЋ Р±СѓР»Рѕ ``not alive``, С‚РѕР±С‚Рѕ РЅР°С‚РёРІРЅРёР№ СЂСѓС€С–Р№
                # СѓР·Р°РіР°Р»С– РЅРµ РїСЂРѕР±СѓРІР°РІСЃСЏ, РїРѕРєРё РЅРµ РЅР°Р»Р°С€С‚РѕРІР°РЅРѕ Р·РѕРІРЅС–С€РЅС–Р№
                # СЃРµСЂРІРµСЂ вЂ” СЃР°РјРµ С‚РѕРјСѓ РјРѕРґРµР»СЊ В«РЅРµ РІС–РґРїРѕРІС–РґР°Р»Р°В».
                wants_native = bool(getattr(self.settings.engine, "native", True))
                if (wants_native and engine_ok and local
                        and getattr(self.settings.engine, "auto_start", True)):
                    result["started"] = self._autostart_local_model(local)
                elif (not alive and engine_ok and local
                        and plan.action == "local-server-ready"
                        and getattr(self.settings.engine, "auto_start", True)):
                    result["started"] = self._autostart_local_model(local)
            except Exception as exc:  # noqa: BLE001
                LOG.warning("РџС–РґР±С–СЂ РјРѕРґРµР»С– РЅРµ РІРґР°РІСЃСЏ: %s", exc, exc_info=True)

            self._ui_call(self._after_auto_setup, result)

        threading.Thread(target=work, daemon=True).start()

    def _server_alive(self, *, fresh: bool = False) -> bool:
        """Р§Рё РІС–РґРїРѕРІС–РґР°С” РЅР°Р»Р°С€С‚РѕРІР°РЅРёР№ OpenAI-СЃСѓРјС–СЃРЅРёР№ СЃРµСЂРІРµСЂ.

        Р’РђР–Р›РР’Рћ РїСЂРѕ В«Р·Р°РІРёСЃР°РЅРЅСЏВ»: С†Рµ РјРµСЂРµР¶РµРІРёР№ Р·Р°РїРёС‚ С–Р· С‚Р°Р№РјР°СѓС‚РѕРј 4 СЃ, С–
        РІРёРєР»РёРєР°С‚Рё Р№РѕРіРѕ Р· РїРѕС‚РѕРєСѓ С–РЅС‚РµСЂС„РµР№СЃСѓ РќР• РњРћР–РќРђ. Р—Р°РјС–СЂСЏРЅРѕ РїСЂРѕС„С–Р»РµСЂРѕРј:
        РїРµСЂС€РёР№ РєР°РґСЂ Р·Р°СЃС‚РёРіР°РІ РЅР° 2.4 СЃ СЃР°РјРµ С‚СѓС‚ (``_model_summary`` в†’
        ``_server_alive`` в†’ ``list_models``).

        РўРµРїРµСЂ С„СѓРЅРєС†С–СЏ РїСЂР°С†СЋС” С‚Р°Рє:

        * РїРѕРІРµСЂС‚Р°С” РћРЎРўРђРќРќР†Р™ РІС–РґРѕРјРёР№ СЃС‚Р°РЅ (РєРµС€), РЅРµ С‡РµРєР°СЋС‡Рё РЅР° РјРµСЂРµР¶Сѓ;
        * СЏРєС‰Рѕ СЃС‚Р°РЅ РЅРµРІС–РґРѕРјРёР№ Р°Р±Рѕ Р·Р°СЃС‚Р°СЂС–Р»РёР№ вЂ” Р·Р°РїСѓСЃРєР°С” РїРµСЂРµРІС–СЂРєСѓ Сѓ Р¤РћРќР†,
          Р° РїР°РЅРµР»СЊ РѕРЅРѕРІРёС‚СЊСЃСЏ, РєРѕР»Рё РІС–РґРїРѕРІС–РґСЊ РїСЂРёР№РґРµ.
        """
        cached = getattr(self, "_alive_cache", None)
        if cached is not None and not fresh \
                and (time.time() - cached[1]) < 5.0:
            return cached[0]
        # РЎРїРµСЂС€Сѓ вЂ” С„РѕРЅРѕРІР° РїРµСЂРµРІС–СЂРєР°, С– Р»РёС€Рµ РїРѕС‚С–Рј (Р·Р° РЅР°СЏРІРЅРѕСЃС‚С–) РєРµС€.
        self._probe_server_alive()
        if cached is not None:
            return cached[0]
        return False

    def _probe_server_alive(self) -> None:
        """РџРµСЂРµРІС–СЂРёС‚Рё СЃРµСЂРІРµСЂ Сѓ С„РѕРЅРѕРІРѕРјСѓ РїРѕС‚РѕС†С– (С–РЅС‚РµСЂС„РµР№СЃ РЅРµ С‡РµРєР°С”)."""
        if getattr(self, "_alive_probe_running", False):
            return
        self._alive_probe_running = True
        base_url = str(self.settings.llm.base_url or "")
        api_key = str(self.settings.llm.api_key or "")

        def work() -> None:
            alive = False
            try:
                # Р”Р»СЏ РІР±СѓРґРѕРІР°РЅРѕРіРѕ СЂСѓС€С–СЏ ``list_models()`` РїРѕРєР°Р·СѓС” Р¤РђР™Р›Р РЅР°
                # РґРёСЃРєСѓ, Р° РЅРµ Р·Р°РІР°РЅС‚Р°Р¶РµРЅСѓ РјРѕРґРµР»СЊ: РІРѕРЅР° РїРѕРІРµСЂС‚Р°Р»Р° В«Р¶РёРІРёР№В» РЅР°РІС–С‚СЊ
                # С‚РѕРґС–, РєРѕР»Рё РјРѕРґРµР»СЊ РЅРµ РІ РїР°Рј'СЏС‚С–. ``model_answers`` РґР»СЏ
                # ``native://`` РїРёС‚Р°С” СЃР°РјРµ СЂСѓС€С–Р№.
                if runtime.embedded_url(base_url):
                    alive = runtime.embedded_model_loaded()
                else:
                    from .llm_client import LLMClient

                    LLMClient(base_url, api_key=api_key, timeout=4).list_models()
                    alive = True
            except Exception:  # noqa: BLE001 - СЃРµСЂРІРµСЂ РјРѕР¶Рµ Р±СѓС‚Рё РІС–РґСЃСѓС‚РЅС–Р№
                alive = False
            finally:
                self._alive_probe_running = False
            self._alive_cache = (alive, time.time())
            # РџР°РЅРµР»СЊ РєРѕРЅС‚РµРєСЃС‚Сѓ РјР°С” РїРѕРєР°Р·Р°С‚Рё СЃРїСЂР°РІР¶РЅС–Р№ СЃС‚Р°РЅ, С‰РѕР№РЅРѕ РґС–Р·РЅР°С”РјРѕСЃСЊ.
            self._ui_call(self._after_alive_probe)

        threading.Thread(target=work, daemon=True, name="alive-probe").start()

    def _after_alive_probe(self) -> None:
        """РћРЅРѕРІРёС‚Рё РїС–РґРїРёСЃ РјРѕРґРµР»С– РїС–СЃР»СЏ С„РѕРЅРѕРІРѕС— РїРµСЂРµРІС–СЂРєРё СЃРµСЂРІРµСЂР°."""
        try:
            self._refresh_header()
        except Exception:  # noqa: BLE001 - РїС–РґРїРёСЃ РЅРµ РјР°С” Р»Р°РјР°С‚Рё РІС–РєРЅРѕ
            LOG.debug("РЁР°РїРєСѓ РЅРµ РѕРЅРѕРІР»РµРЅРѕ", exc_info=True)
        try:
            self.context.refresh()
        except (tk.TclError, AttributeError):
            pass

    def _autostart_native_model(self) -> str:
        """Р—Р°РІР°РЅС‚Р°Р¶РёС‚Рё РјРѕРґРµР»СЊ Сѓ Р’Р›РђРЎРќРР™ СЂСѓС€С–Р№ (Р±РµР· llama-server).

        РњРѕРґРµР»СЊ Р±РµСЂРµС‚СЊСЃСЏ Р· ``engine.native_model``; СЏРєС‰Рѕ С‚Р°Рј РїРѕСЂРѕР¶РЅСЊРѕ вЂ”
        РЅР°Р№Р±С–Р»СЊС€РёР№ Р»РѕРєР°Р»СЊРЅРёР№ GGUF. РџРѕСЂРѕР¶РЅС–Р№ СЂСЏРґРѕРє Сѓ РІС–РґРїРѕРІС–РґС– РѕР·РЅР°С‡Р°С”
        В«РЅРµ РІРґР°Р»РѕСЃСЊВ», С– С‚РѕРґС– РІРёРєР»РёРє РїРµСЂРµС…РѕРґРёС‚СЊ РЅР° СЃСѓРјС–СЃРЅРёР№ С€Р»СЏС….
        """
        try:
            entries = self.native_runtime.manager.local_models()
        except Exception as exc:                     # noqa: BLE001
            LOG.warning("РњРѕРґРµР»С– РґР»СЏ РІР»Р°СЃРЅРѕРіРѕ СЂСѓС€С–СЏ РЅРµРґРѕСЃС‚СѓРїРЅС–: %s", exc)
            return ""
        wanted = str(getattr(self.settings.engine, "native_model", "") or "")
        chosen = None
        if wanted:
            chosen = next((item for item in entries
                           if item.key == wanted or Path(item.name).name == wanted
                           or item.path == wanted), None)
        if chosen is None and entries:
            chosen = max(entries, key=lambda item: item.size_gb)
        if chosen is None:
            return ""
        # РџР°СЂР°РјРµС‚СЂРё Р· РЅР°Р»Р°С€С‚СѓРІР°РЅСЊ РњРЈРЎРЇРўР¬ Р·Р°СЃС‚РѕСЃРѕРІСѓРІР°С‚РёСЃСЊ: С–РЅР°РєС€Рµ РєРѕСЂРёСЃС‚СѓРІР°С‡
        # РІРёР±РёСЂР°С” В«24 С€Р°СЂРёВ» С‡Рё В«f16-РєРµС€В», Р° СЂСѓС€С–Р№ РјРѕРІС‡РєРё Р±РµСЂРµ Р°РІС‚Рѕ.
        stored_layers = int(getattr(self.settings.engine, "native_gpu_layers", -1))
        stored_cache = str(getattr(self.settings.engine, "native_cache_type", "") or "")
        stored_flash = str(getattr(self.settings.engine, "native_flash_attn", "auto") or "auto")
        try:
            info = self.native_runtime.load_model(
                chosen.path,
                ctx=int(getattr(self.settings.engine, "ctx_size", 0) or 0),
                gpu_layers=None if stored_layers == -1 else stored_layers,
                cache_type=stored_cache,
                flash_attn=stored_flash)
        except Exception as exc:                     # noqa: BLE001
            LOG.warning("Р’Р»Р°СЃРЅРёР№ СЂСѓС€С–Р№ РЅРµ Р·Р°РІР°РЅС‚Р°Р¶РёРІ РјРѕРґРµР»СЊ: %s", exc)
            return f"{NATIVE_FAILURE_PREFIX}{exc}"[:120]
        self._on_native_model(info.get("path") or chosen.path)
        note = f" В· ctx {info.get('context_actual', 0)}"
        return f"РІР»Р°СЃРЅРёР№ СЂСѓС€С–Р№: {chosen.key}{note}"
    def _stop_managed_server(self, *, reason: str = "") -> bool:
        """Р—СѓРїРёРЅРёС‚Рё РїРѕРїРµСЂРµРґРЅС–Р№ РєРµСЂРѕРІР°РЅРёР№ СЂСѓС€С–Р№, С‰РѕР± РЅРµ С‚СЂРёРјР°С‚Рё VRAM РґРІС–С‡С–.

        РџРѕРІРµСЂС‚Р°С” True, СЏРєС‰Рѕ С‰РѕСЃСЊ СЃРїСЂР°РІРґС– Р·СѓРїРёРЅРёР»Рё. РџРѕРјРёР»РєСѓ РЅРµ РїСЂРёС…РѕРІСѓС”РјРѕ:
        СЏРєС‰Рѕ РїСЂРѕС†РµСЃ РЅРµ Р·Р°РІРµСЂС€РёРІСЃСЏ, РІС–РЅ РґР°Р»С– С‚СЂРёРјР°С” РІС–РґРµРѕРїР°Рј'СЏС‚СЊ, С–
        РєРѕСЂРёСЃС‚СѓРІР°С‡ РјР°С” РїСЂРѕ С†Рµ РґС–Р·РЅР°С‚РёСЃСЊ, Р° РЅРµ С€СѓРєР°С‚Рё РїСЂРёС‡РёРЅСѓ СЃР°РјРѕС‚СѓР¶РєРё.
        """
        server = getattr(self, "_managed_server", None)
        if server is None:
            return False
        try:
            if not getattr(server, "running", False):
                self._managed_server = None
                return False
        except Exception:  # noqa: BLE001 - СЃС‚Р°РЅ РїСЂРѕС†РµСЃСѓ РјРѕР¶Рµ Р±СѓС‚Рё РЅРµРґРѕСЃС‚СѓРїРЅРёР№
            LOG.debug("РЎС‚Р°РЅ СЂСѓС€С–СЏ РЅРµ РїСЂРѕС‡РёС‚Р°РЅРѕ", exc_info=True)
        try:
            server.stop()
        except Exception as exc:  # noqa: BLE001 - РїРѕРєР°Р·СѓС”РјРѕ РїСЂРёС‡РёРЅСѓ
            LOG.warning("Р СѓС€С–Р№ РЅРµ Р·СѓРїРёРЅРёРІСЃСЏ (%s): %s", reason, exc,
                        exc_info=True)
            self.set_status(f"РќРµ РІРґР°Р»РѕСЃСЊ Р·СѓРїРёРЅРёС‚Рё РїРѕРїРµСЂРµРґРЅС–Р№ СЂСѓС€С–Р№: {exc}")
            return False
        self._managed_server = None
        LOG.info("РџРѕРїРµСЂРµРґРЅС–Р№ СЂСѓС€С–Р№ Р·СѓРїРёРЅРµРЅРѕ: %s", reason or "РїРµСЂРµР·Р°РїСѓСЃРє")
        return True

    def _autostart_local_model(self, local_names: list[str]) -> str:
        """РџС–РґРЅСЏС‚Рё РјРѕРґРµР»СЊ РїСЂРё СЃС‚Р°СЂС‚С– IDE.

        Р”РІР° С€Р»СЏС…Рё, С– РІРёР±С–СЂ РјС–Р¶ РЅРёРјРё Р·Р±РµСЂС–РіР°С”С‚СЊСЃСЏ РІ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏС…:

        * ``engine.native`` вЂ” Р’Р›РђРЎРќРР™ СЂСѓС€С–Р№ (``llama.dll`` Сѓ С†СЊРѕРјСѓ РїСЂРѕС†РµСЃС–);
        * С–РЅР°РєС€Рµ вЂ” СЃСѓРјС–СЃРЅРёР№ ``llama-server`` (СЏРє Р±СѓР»Рѕ СЂР°РЅС–С€Рµ).

        РџРѕРІРµСЂС‚Р°С” РєРѕСЂРѕС‚РєРёР№ С‚РµРєСЃС‚ СЂРµР·СѓР»СЊС‚Р°С‚Сѓ РґР»СЏ РїР°РЅРµР»С– СЃС‚Р°РЅСѓ.
        """
        if getattr(self.settings.engine, "native", False):
            native = self._autostart_native_model()
            # РЈР’РђР–РќРћ: РїРѕРјРёР»РєР° С‚СѓС‚ С‚РµР¶ РЅРµРїРѕСЂРѕР¶РЅС–Р№ СЂСЏРґРѕРє. Р Р°РЅС–С€Рµ ``if native:
            # return native`` РІРІР°Р¶Р°РІ РџРћР’Р†Р”РћРњР›Р•РќРќРЇ РџР Рћ РџРћРњРР›РљРЈ СѓСЃРїС–С…РѕРј, С–
            # С„РѕР»Р±РµРє РЅР° llama-server РЅРµ РІРёРєРѕРЅСѓРІР°РІСЃСЏ РІР·Р°РіР°Р»С–: РєРѕСЂРёСЃС‚СѓРІР°С‡
            # Р»РёС€Р°РІСЃСЏ Р±РµР· РјРѕРґРµР»С–, С…РѕС‡ СЂРѕР±РѕС‡РёР№ С€Р»СЏС… Р±СѓРІ РїРѕСЂСѓС‡.
            if native and not native.startswith(NATIVE_FAILURE_PREFIX):
                return native
            if native:
                LOG.warning("Р’Р»Р°СЃРЅРёР№ СЂСѓС€С–Р№ РЅРµ СЃС‚Р°СЂС‚СѓРІР°РІ (%s) вЂ” РїСЂРѕР±СѓСЋ llama-server",
                            native)
            else:
                LOG.warning("Р’Р»Р°СЃРЅРёР№ СЂСѓС€С–Р№ РЅРµ СЃС‚Р°СЂС‚СѓРІР°РІ вЂ” РїСЂРѕР±СѓСЋ llama-server")
        from .model_hub import models_dir

        chosen = self.settings.engine.model_path or ""
        path = Path(chosen) if chosen and Path(chosen).exists() else None
        if path is None:
            preferred = self.settings.llm.model
            candidates = [models_dir() / name for name in local_names]
            for candidate in candidates:
                if preferred and preferred in candidate.name:
                    path = candidate
                    break
            if path is None:
                # РќР°Р№Р±С–Р»СЊС€Р° РјРѕРґРµР»СЊ вЂ” Р·Р°Р·РІРёС‡Р°Р№ РЅР°Р№СЂРѕР·СѓРјРЅС–С€Р°, СЏРєСѓ РІР¶Рµ СЃРєР°С‡Р°Р»Рё.
                path = max(candidates, key=lambda p: p.stat().st_size if p.exists() else 0)
        if not path or not path.exists():
            return "РЅРµРјР°С” С„Р°Р№Р»Сѓ РјРѕРґРµР»С–"

        try:
            profile = hardware.detect()
            choice = self.chat_panel_choice(path)
            # в”Ђв”Ђ РћРґРёРЅ СЂСѓС€С–Р№, Р° РЅРµ РґРІР° в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
            # Р—РђРњР†Р РЇРќРћ Р–РР’РРњ РџР РћР“РћРќРћРњ: РїС–СЃР»СЏ РІРёРІР°РЅС‚Р°Р¶РµРЅРЅСЏ С‡РµСЂРµР· РїСЂРѕСЃС‚С–Р№
            # ``launch_with_recovery`` РїС–РґРЅСЏРІ РќРћР’РР™ СЃРµСЂРІРµСЂ РЅР° 8081 (8080 С‰Рµ
            # РЅРµ РІСЃС‚РёРі Р·РІС–Р»СЊРЅРёС‚РёСЃСЊ), Р° ``settings.llm.base_url`` РЅР° РјРёС‚СЊ
            # Р»РёС€Р°РІСЃСЏ РЅР° 8080. Р”РІР° РїСЂРѕС†РµСЃРё ``llama-server`` РѕРґРЅРѕС‡Р°СЃРЅРѕ
            # С‚СЂРёРјР°Р»Рё VRAM: 7.7 + 7.7 Р“Р‘ РЅР° РєР°СЂС‚С†С– 12 Р“Р‘.
            #
            # РўРµРїРµСЂ СЃС‚Р°СЂРёР№ РєРµСЂРѕРІР°РЅРёР№ СЃРµСЂРІРµСЂ Р·СѓРїРёРЅСЏС”РјРѕ РџР•Р Р•Р” Р·Р°РїСѓСЃРєРѕРј РЅРѕРІРѕРіРѕ.
            self._stop_managed_server(reason="РїРµСЂРµР·Р°РїСѓСЃРє РїРµСЂРµРґ РїС–РґР№РѕРјРѕРј РјРѕРґРµР»С–")
            # в”Ђв”Ђ Р—С–СЂ: РїСЂРёС”РґРЅСѓС”РјРѕ РІС–Р·СѓР°Р»СЊРЅРёР№ РїСЂРѕС”РєС‚РѕСЂ, СЏРєС‰Рѕ РІС–РЅ С” в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
            # Р‘РµР· ``--mmproj`` РјСѓР»СЊС‚РёРјРѕРґР°Р»СЊРЅР° РјРѕРґРµР»СЊ РќР• Р±Р°С‡РёС‚СЊ Р·РѕР±СЂР°Р¶РµРЅСЊ:
            # llama.cpp РїСЂРёР№РјР°С” РєР°СЂС‚РёРЅРєСѓ РІ Р·Р°РїРёС‚С–, Р°Р»Рµ РјРѕРґРµР»СЊ С—С— РЅРµ С‡РёС‚Р°С”.
            projector = hub.vision_projector_for(path)
            # в”Ђв”Ђ Р—Р°РїСѓСЃРє С–Р· Р°РІС‚РѕРјР°С‚РёС‡РЅРёРј РІС–РґРЅРѕРІР»РµРЅРЅСЏРј в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
            # Р Р°РЅС–С€Рµ С‚СѓС‚ Р±СѓРІ РѕРґРёРЅ-С”РґРёРЅРёР№ С€Р°РЅСЃ: СЏРєС‰Рѕ GPU РЅРµ РІРїРѕСЂР°РІСЃСЏ Р·
            # РєРѕРЅС‚РµРєСЃС‚РѕРј, Р°РіРµРЅС‚ РїРёСЃР°РІ В«СЃРµСЂРІРµСЂ РЅРµ РїС–РґРЅСЏРІСЃСЏВ» С– Р»РёС€Р°РІ
            # РєРѕСЂРёСЃС‚СѓРІР°С‡Р° Р±РµР· РјРѕРґРµР»С–. РўРµРїРµСЂ ``launch_with_recovery`` СЃР°Рј
            # Р·РјРµРЅС€СѓС” РєРѕРЅС‚РµРєСЃС‚ С– offload, Р°Р¶ РґРѕ С‡РёСЃС‚РѕРіРѕ CPU, С– РїРѕРІРµСЂС‚Р°С”
            # СЃРїСЂР°РІР¶РЅСЋ РїСЂРёС‡РёРЅСѓ, СЏРєС‰Рѕ РЅРµ РґРѕРїРѕРјРѕРіР»Рѕ Р¶РѕРґРЅРµ.
            servers, detail = runtime.launch_with_recovery(
                path,
                choice=choice,
                profile=profile,
                alias=path.stem,
                mmproj_path=str(projector) if projector else "",
                on_status=lambda text: self._ui_call(self.set_status, text),
            )
            if not servers:
                return f"СЃРµСЂРІРµСЂ РЅРµ РїС–РґРЅСЏРІСЃСЏ: {detail[:160]}"
            server = servers[-1]
            self._managed_server = server
            base_url = server.base_url
            used_plan = server.config.plan
            self.settings.llm.base_url = base_url
            self.settings.llm.model = path.stem
            self.settings.llm.api_key = runtime.MANAGED_API_KEY
            self.settings.engine.managed = True
            self.settings.engine.model_path = str(path)
            self.settings.engine.port = server.config.port
            self.settings.engine.ctx_size = int(
                (used_plan.ctx_size if used_plan else 0) or 0)
            self.settings.save()
            # РЎРјСѓРіР° СЃС‚Р°С‚РёСЃС‚РёРєРё РјР°С” РїРѕРєР°Р·СѓРІР°С‚Рё СЂРµР°Р»СЊРЅРµ РІС–РєРЅРѕ РєРѕРЅС‚РµРєСЃС‚Сѓ.
            self._context_limit = int((used_plan.ctx_size if used_plan else 0) or 0)
            self._ui_call(self._apply_context_limit)
            # в”Ђв”Ђ РџРѕСЂС‚ РјС–Рі Р·РјС–РЅРёС‚РёСЃСЊ (8080 Р·Р°Р№РЅСЏС‚РёР№) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
            # РЎР°РјРµ С‚СѓС‚ РЅР°СЂРѕРґР¶СѓРІР°Р»Р°СЃСЊ СЂРѕР·Р±С–Р¶РЅС–СЃС‚СЊ В«С–РЅС‚РµСЂС„РµР№СЃ РїРѕРєР°Р·СѓС” РѕРґРЅСѓ
            # Р°РґСЂРµСЃСѓ, Р° Р·Р°РїРёС‚Рё Р№РґСѓС‚СЊ РЅР° С–РЅС€СѓВ». РЎС‚Р°РЅ СЃРµСЂРІРµСЂР° СЃРєРёРґР°С”РјРѕ Р№
            # РѕРїРёС‚СѓС”РјРѕ Р—РђРќРћР’Рћ Р·Р° РЅРѕРІРѕСЋ Р°РґСЂРµСЃРѕСЋ вЂ” С‚РѕРґС– С– РІС–РєРЅРѕ, С– Р°РіРµРЅС‚
            # Р±Р°С‡Р°С‚СЊ С‚РѕР№ СЃР°РјРёР№ РїРѕСЂС‚ С– С‚Рµ СЃР°РјРµ РІС–РєРЅРѕ РєРѕРЅС‚РµРєСЃС‚Сѓ.
            try:
                self.server_state.set_local(running=True)
                self.server_state.invalidate(reason="РјРѕРґРµР»СЊ Р·Р°РїСѓС‰РµРЅРѕ")
                self.server_state.refresh(background=True)
            except (AttributeError, tk.TclError):
                LOG.debug("РЎС‚Р°РЅ СЃРµСЂРІРµСЂР° РЅРµ РѕРЅРѕРІР»РµРЅРѕ РїС–СЃР»СЏ Р·Р°РїСѓСЃРєСѓ РјРѕРґРµР»С–",
                          exc_info=True)
            self._invalidate_model_state(reason="РјРѕРґРµР»СЊ Р·Р°РїСѓС‰РµРЅРѕ")
            # РџСЂР°РїРѕСЂРµС†СЊ Р·РѕСЂСѓ РґР»СЏ Р°РіРµРЅС‚Р°: РїРµСЂРµРґР°РІР°С‚Рё Р·РЅС–РјРєРё СЏРє Р·РѕР±СЂР°Р¶РµРЅРЅСЏ
            # РјРѕР¶РЅР° Р›РРЁР• С‚РѕРґС–, РєРѕР»Рё СЃРµСЂРІРµСЂ СЃРїСЂР°РІРґС– Р·Р°РїСѓС‰РµРЅРѕ Р· РїСЂРѕС”РєС‚РѕСЂРѕРј.
            try:
                self.agent.vision_enabled = bool(projector)
            except AttributeError:
                pass
            note = (f" В· Р·С–СЂ: {projector.name}" if projector else "")
            return f"РјРѕРґРµР»СЊ Р·Р°РїСѓС‰РµРЅРѕ: {path.stem}{note}"
        except Exception as exc:  # noqa: BLE001 - РїРѕРєР°Р·СѓС”РјРѕ РїСЂРёС‡РёРЅСѓ
            LOG.warning("РђРІС‚РѕР·Р°РїСѓСЃРє РјРѕРґРµР»С– РЅРµ РІРґР°РІСЃСЏ: %s", exc, exc_info=True)
            return f"Р°РІС‚РѕР·Р°РїСѓСЃРє РЅРµ РІРґР°РІСЃСЏ: {exc}"

    def chat_panel_choice(self, path: Path):
        """РћС†С–РЅРёС‚Рё РјРѕРґРµР»СЊ Р·Р° РЅР°Р·РІРѕСЋ С„Р°Р№Р»Сѓ (РґР»СЏ РїР°СЂР°РјРµС‚СЂС–РІ Р·Р°РїСѓСЃРєСѓ)."""
        name = path.name.lower()
        for token, params, layers in (("0.5b", 0.5, 24), ("1.5b", 1.5, 28), ("3b", 3.0, 36),
                                      ("4b", 4.0, 36), ("7b", 7.0, 28), ("8b", 8.0, 32),
                                      ("14b", 14.0, 48), ("32b", 32.0, 64), ("70b", 70.0, 80)):
            if token in name:
                size_gb = params * 0.62
                return hardware.ModelChoice(str(path.parent), path.name, path.stem,
                                            params, size_gb, 0.0, "", layers)
        size_gb = max(0.5, path.stat().st_size / 2**30) if path.exists() else 2.0
        return hardware.ModelChoice(str(path.parent), path.name, path.stem,
                                    max(1.0, size_gb / 0.62), size_gb, 0.0, "", 32)

    def _confirm_model_online(self, detail: str = "") -> None:
        """РџРµСЂРµРІС–СЂРёС‚Рё Р¤РђРљРўРР§РќРћ, С‡Рё РјРѕРґРµР»СЊ РІС–РґРїРѕРІС–РґР°С”, С– РїРѕРєР°Р·Р°С‚Рё РїСЂР°РІРґСѓ.

        РќР°РІС–С‰Рѕ РѕРєСЂРµРјРёР№ РјРµС‚РѕРґ. РџС–СЃР»СЏ Р°РІС‚РѕР·Р°РїСѓСЃРєСѓ СЂСѓС€С–Р№ РјС–Рі РїС–РґРЅСЏС‚РёСЃСЊ РЅР°
        Р†РќРЁРћРњРЈ РїРѕСЂС‚Сѓ (8080 Р·Р°Р№РЅСЏРІ Steam в†’ 8081), С– ``llm.base_url``
        Р»РёС€Р°РІСЃСЏ СЃС‚Р°СЂРёРј. РЎС‚Р°С‚СѓСЃ Сѓ С€Р°РїС†С– РїСЂРё С†СЊРѕРјСѓ РїРѕРєР°Р·СѓРІР°РІ В«РћР¤Р›РђР™РќВ», С…РѕС‡
        РјРѕРґРµР»СЊ РїСЂР°С†СЋРІР°Р»Р° вЂ” СЃР°РјРµ С†Рµ РІРёРіР»СЏРґР°Р»Рѕ СЏРє В«РјРѕРґРµР»СЊ РЅРµ СЃС‚Р°СЂС‚СѓС”В».

        РњРµС‚РѕРґ СѓР·РіРѕРґР¶СѓС” Р°РґСЂРµСЃСѓ Р№ СЃС‚Р°РІРёС‚СЊ СЃС‚Р°С‚СѓСЃ Р·Р° Р Р•РђР›Р¬РќРћР® РІС–РґРїРѕРІС–РґРґСЋ
        СЃРµСЂРІРµСЂР°, Р° РЅРµ Р·Р° РЅР°СЏРІРЅС–СЃС‚СЋ РЅР°Р·РІРё РјРѕРґРµР»С–.
        """
        self._reconcile_server_url()
        url = str(self.settings.llm.base_url or "")
        key = str(self.settings.llm.api_key or "")
        try:
            # ``model_answers``, Р° РЅРµ ``server_responds``: РґР»СЏ РІР±СѓРґРѕРІР°РЅРѕРіРѕ
            # СЂСѓС€С–СЏ (``native://blackchpok``) HTTP-РїРµСЂРµРІС–СЂРєРё РЅРµ С–СЃРЅСѓС”, С–
            # СЃР°РјРµ С‡РµСЂРµР· С†Рµ С€Р°РїРєР° РїРѕРєР°Р·СѓРІР°Р»Р° В«в—Џ РњРћР”Р•Р›Р¬ РћР¤Р›РђР™РќВ» РЅР° Р¶РёРІС–Р№
            # РјРѕРґРµР»С– (Р·Р°РјС–СЂСЏРЅРѕ: engine.loaded=True, ctx 32768, GPU 48).
            online = runtime.model_answers(url, api_key=key, timeout=1.5)
        except Exception:  # noqa: BLE001 - РїРµСЂРµРІС–СЂРєР° РЅРµ РјР°С” Р»Р°РјР°С‚Рё СЃС‚Р°СЂС‚
            online = False
        try:
            self.header_bar.set_model_status(
                online, detail=(f"{self.settings.llm.model} В· {url}"
                                if online else f"{detail or 'СЃРµСЂРІРµСЂ РЅРµ РІС–РґРїРѕРІС–РґР°С”'}"))
        except (tk.TclError, AttributeError):
            pass
        try:
            self.chat.set_online(online, detail if online else "")
        except (tk.TclError, AttributeError):
            pass
        if online:
            LOG.info("РњРѕРґРµР»СЊ РѕРЅР»Р°Р№РЅ: %s @ %s", self.settings.llm.model, url)
        else:
            LOG.warning("РњРѕРґРµР»СЊ РѕС„Р»Р°Р№РЅ РїС–СЃР»СЏ Р°РІС‚РѕР·Р°РїСѓСЃРєСѓ: %s", detail[:160])

    def _after_auto_setup(self, result: dict) -> None:
        self._setup_busy = False
        try:
            self.skill_book.reload()
            self.skills_panel.refresh()
        except (tk.TclError, AttributeError):
            pass
        installed = result.get("installed") or []
        plan = result.get("plan")
        started = str(result.get("started") or "").strip()
        parts: list[str] = []
        if installed:
            parts.append(f"СЃС‚РІРѕСЂРµРЅРѕ СЃРєС–Р»С–РІ: {len(installed)}")
        if plan is not None:
            parts.append(f"РјРѕРґРµР»СЊ: {plan.action}")
            if getattr(plan, "note", ""):
                self._setup_note = plan.note
        # в”Ђв”Ђ Р РµР·СѓР»СЊС‚Р°С‚ РђР’РўРћР—РђРџРЈРЎРљРЈ РјРѕРґРµР»С– в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        # ``result["started"]`` Р·Р°РїРёСЃСѓРІР°РІСЃСЏ Сѓ С„РѕРЅС–, Р°Р»Рµ РЅС–РґРµ РЅРµ С‡РёС‚Р°РІСЃСЏ:
        # РїСЂРёС‡РёРЅР° РЅРµРІРґР°С‡С– Р°РІС‚РѕР·Р°РїСѓСЃРєСѓ РіСѓР±РёР»Р°СЃСЊ, С– РєРѕСЂРёСЃС‚СѓРІР°С‡ Р±Р°С‡РёРІ Р»РёС€Рµ
        # В«РјРѕРґРµР»СЊ: local-server-readyВ», С…РѕС‡ СЃРµСЂРІРµСЂ С‚Р°Рє С– РЅРµ РїС–РґРЅСЏРІСЃСЏ.
        if started:
            if started.startswith(NATIVE_FAILURE_PREFIX) or started.startswith("СЃРµСЂРІРµСЂ РЅРµ РїС–РґРЅСЏРІСЃСЏ"):
                parts.append(f"Р·Р°РїСѓСЃРє: {started[:120]}")
                self.set_status("РђРІС‚РѕР·Р°РїСѓСЃРє РјРѕРґРµР»С– РЅРµ РІРґР°РІСЃСЏ В· " + started[:160])
                try:
                    self.header_bar.set_model_status(False, detail=started[:120])
                except (tk.TclError, AttributeError):
                    pass
            else:
                parts.append(f"РјРѕРґРµР»СЊ РїС–РґРЅСЏС‚Рѕ: {started[:60]}")
                # в”Ђв”Ђ Р“РѕР»РѕРІРЅРµ: РїС–СЃР»СЏ СѓСЃРїС–С€РЅРѕРіРѕ Р°РІС‚РѕР·Р°РїСѓСЃРєСѓ РїРѕРєР°Р·Р°С‚Рё РћРќР›РђР™Рќ в”Ђв”Ђ
                # Р”РµС„РµРєС‚, С‡РµСЂРµР· СЏРєРёР№ РєРѕСЂРёСЃС‚СѓРІР°С‡ Р±Р°С‡РёРІ В«РјРѕРґРµР»СЊ РЅРµ СЃС‚Р°СЂС‚СѓС”В»:
                # СЂСѓС€С–Р№ РїС–РґРЅС–РјР°РІСЃСЏ (Сѓ Р»РѕР·С– РІРёРґРЅРѕ В«РЎС‚Р°СЂС‚ СЂСѓС€С–СЏВ» Р№ Р·Р°РІР°РЅС‚Р°Р¶РµРЅРЅСЏ
                # РјРѕРґРµР»С–), Р°Р»Рµ СЃС‚Р°С‚СѓСЃ Сѓ С€Р°РїС†С– Р»РёС€Р°РІСЃСЏ В«РћР¤Р›РђР™РќВ», Р±Рѕ РїС–СЃР»СЏ
                # Р°РІС‚РѕР·Р°РїСѓСЃРєСѓ РЅС–С…С‚Рѕ РЅРµ РѕРЅРѕРІР»СЋРІР°РІ РЅС– СЃС‚Р°РЅ, РЅС– Р°РґСЂРµСЃСѓ. РўРµРїРµСЂ
                # РїРµСЂРµРІС–СЂСЏС”РјРѕ Р¤РђРљРўРР§РќРћ Р№ РїРѕРєР°Р·СѓС”РјРѕ РїСЂР°РІРґСѓ.
                self._confirm_model_online(started)
        if parts:
            self.set_status("РђРІС‚РѕРЅР°Р»Р°РіРѕРґР¶РµРЅРЅСЏ В· " + " В· ".join(parts))
        # в”Ђв”Ђ MCP РїС–СЃР»СЏ РјРѕРґРµР»С– в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        # Р’РёРјРѕРіР° РїРѕСЂСЏРґРєСѓ: СЃРїРµСЂС€Сѓ РјРѕРґРµР»СЊ, РїРѕС‚С–Рј MCP. Р Р°РЅС–С€Рµ MCP СЃС‚Р°СЂС‚СѓРІР°РІ
        # С‡РµСЂРµР· 400 РјСЃ, Р° Р°РІС‚РѕР·Р°РїСѓСЃРє РјРѕРґРµР»С– вЂ” С‡РµСЂРµР· 900 РјСЃ, С‚РѕР±С‚Рѕ MCP
        # РїС–РґРЅС–РјР°РІСЃСЏ Р”Рћ РјРѕРґРµР»С– Р№ РјС–Рі СѓРїР°СЃС‚Рё СЃР°РјРµ С‡РµСЂРµР· С†Рµ.
        if started and not started.startswith(NATIVE_FAILURE_PREFIX) \
                and "РЅРµ РїС–РґРЅСЏРІСЃСЏ" not in started:
            self.after(200, self._load_mcp_async)
        # РЎС‚Р°СЂС‚РѕРІРёР№ РµРєСЂР°РЅ РјР°С” РїРѕРєР°Р·Р°С‚Рё СЂРµР°Р»СЊРЅРёР№ СЃС‚Р°РЅ СЃРєС–Р»С–РІ С– РјРѕРґРµР»С–.
        if getattr(self, "_welcome_shown", False):
            try:
                self.welcome.set_workspace(self.settings.workspace)
                self.welcome.set_model(self.settings.llm.model)
            except tk.TclError:
                pass

    # в”Ђв”Ђ СЃР°Р№С‚ Сѓ РІР±СѓРґРѕРІР°РЅРѕРјСѓ Р±СЂР°СѓР·РµСЂС– в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def open_site(self) -> None:
        """РџРѕРєР°Р·Р°С‚Рё СЃР°Р№С‚ РїСЂРѕС”РєС‚Сѓ Сѓ РІР±СѓРґРѕРІР°РЅРѕРјСѓ Р±СЂР°СѓР·РµСЂС– Р№ Р·Р°РїСѓСЃС‚РёС‚Рё Р№РѕРіРѕ.

        РЎС‚РѕСЂС–РЅРєР° Р¶РёРІРµ РІ **РѕРґРЅС–Р№** РєРѕР»РѕРЅС†С– Live Preview РїСЂР°РІРѕСЂСѓС‡. Р Р°РЅС–С€Рµ С‚СѓС‚
        РґРѕРґР°С‚РєРѕРІРѕ РІС–РґРєСЂРёРІР°Р»Р°СЃСЊ РІРєР»Р°РґРєР° В«рџЊђ РЎР°Р№С‚В» Р·РЅРёР·Сѓ, С– РІРёС…РѕРґРёР»Рѕ РґРІР°
        РЅРµР·Р°Р»РµР¶РЅС– РІР±СѓРґРѕРІР°РЅС– Р±СЂР°СѓР·РµСЂРё РґР»СЏ С‚С–С”С— СЃР°РјРѕС— Р°РґСЂРµСЃРё: РґРІР° РїСЂРѕС†РµСЃРё
        Chromium, РґРІС– РєРѕРїС–С— СЃС‚РѕСЂС–РЅРєРё Р№ Р·Р°РїР»СѓС‚Р°РЅРёР№ СЃС‚Р°РЅ (РєРЅРѕРїРєР° В«в– В» РІ РѕРґРЅС–Р№
        РїР°РЅРµР»С– РЅРµ Р·СѓРїРёРЅСЏР»Р° РґСЂСѓРіСѓ).
        """
        self.toggle_preview(True)
        if not self.app.running:
            self.start_site()
        else:
            self.live_preview.open_url(self.app.url)
            self.set_status(self.app.describe())

    def start_site(self) -> None:
        """Р—Р°РїСѓСЃС‚РёС‚Рё Р·Р°СЃС‚РѕСЃСѓРЅРѕРє РїСЂРѕС”РєС‚Сѓ С– РїРѕРєР°Р·Р°С‚Рё Р№РѕРіРѕ Сѓ РІР±СѓРґРѕРІР°РЅРѕРјСѓ Р±СЂР°СѓР·РµСЂС–.

        Р’Р°Р¶Р»РёРІРѕ Р№С‚Рё С‡РµСЂРµР· ``live_preview.start_server``, Р° РЅРµ РєР»РёРєР°С‚Рё
        ``self.app.start()`` РЅР°РїСЂСЏРјСѓ: РєРѕРЅС‚СЂРѕР»РµСЂ Р»РёС€Рµ РїС–РґРЅС–РјР°С” СЃРµСЂРІРµСЂ, Р°
        РїРѕРєР°Р· СЃС‚РѕСЂС–РЅРєРё Сѓ РІР±СѓРґРѕРІР°РЅРѕРјСѓ РІС–РєРЅС– СЂРѕР±РёС‚СЊ СЃР°РјРµ РєРѕР»РѕРЅРєР° РїСЂРµРІ'СЋ.
        Р Р°РЅС–С€Рµ С‡РµСЂРµР· С†Рµ В«Р—Р°РїСѓСЃС‚РёС‚Рё СЃР°Р№С‚В» РїС–РґРЅС–РјР°Р»Рѕ СЃРµСЂРІРµСЂ, Р°Р»Рµ РІС–РєРЅРѕ
        Р»РёС€Р°Р»РѕСЃСЊ РїРѕСЂРѕР¶РЅС–Рј вЂ” СЃС‚РѕСЂС–РЅРєР° РЅРµ РІС–РґРєСЂРёРІР°Р»Р°СЃСЊ.
        """
        self.toggle_preview(True)
        self.live_preview.start_server()
        controller = self.app
        if controller.running:
            self.set_status(controller.describe())
        else:
            self.set_status("РЎР°Р№С‚ РЅРµ Р·Р°РїСѓС‰РµРЅРѕ вЂ” РїРµСЂРµРІС–СЂ СЃС‚РµРє РїСЂРѕС”РєС‚Сѓ.")

    def stop_site(self) -> None:
        # Р—СѓРїРёРЅСЏС”РјРѕ С‡РµСЂРµР· РєРѕР»РѕРЅРєСѓ РїСЂРµРІ'СЋ: РІРѕРЅР° С‚СЂРёРјР°С” С– СЃРµСЂРІРµСЂ, С– Р±СЂР°СѓР·РµСЂ,
        # С– СЃР°РјР° РїСЂРёР±РёСЂР°С” Р·Р° СЃРѕР±РѕСЋ РІР±СѓРґРѕРІР°РЅРµ РІС–РєРЅРѕ.
        self.live_preview.stop_all()
        self.set_status("Р—Р°СЃС‚РѕСЃСѓРЅРѕРє Р·СѓРїРёРЅРµРЅРѕ.")

    def reload_site(self) -> None:
        self.live_preview.reload_page()

    # в”Ђв”Ђ РІР±СѓРґРѕРІР°РЅРёР№ Р±СЂР°СѓР·РµСЂ РґР»СЏ РґРѕРІС–Р»СЊРЅРёС… Р°РґСЂРµСЃ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def open_url_in_browser(self, url: str) -> bool:
        """Р’С–РґРєСЂРёС‚Рё Р°РґСЂРµСЃСѓ Сѓ РІР±СѓРґРѕРІР°РЅРѕРјСѓ Р±СЂР°СѓР·РµСЂС– IDE (РќР• РІ Р±СЂР°СѓР·РµСЂС– РџРљ).

        Р¦Рµ С”РґРёРЅР° С‚РѕС‡РєР° РІС…РѕРґСѓ РґР»СЏ РІСЃС–С… РјРѕРґСѓР»С–РІ: РїР°РЅРµР»СЊ Р·РјС–РЅ, С…Р°Р± РјРѕРґРµР»РµР№,
        РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏ Р№ РјР°Р№СЃС‚РµСЂ РїРµСЂС€РѕРіРѕ Р·Р°РїСѓСЃРєСѓ РєР»РёС‡СѓС‚СЊ С—С— Р·Р°РјС–СЃС‚СЊ
        ``webbrowser.open``. РўРѕРјСѓ РєР»С–Рє В«Р’СЃС‚Р°РЅРѕРІРёС‚Рё gitВ» Р±С–Р»СЊС€Рµ РЅРµ РІРёРєРёРґР°С”
        РєРѕСЂРёСЃС‚СѓРІР°С‡Р° Р· Р·Р°СЃС‚РѕСЃСѓРЅРєСѓ.

        РџРѕСЂСЏРґРѕРє РґС–Р№:

        1. РЅРѕСЂРјР°Р»С–Р·СѓРІР°С‚Рё Р°РґСЂРµСЃСѓ (``git-scm.com`` в†’ ``https://git-scm.com``);
        2. РїРѕРєР°Р·Р°С‚Рё РєРѕР»РѕРЅРєСѓ Live Preview (С‚Р°Рј Р¶РёРІРµ РІР±СѓРґРѕРІР°РЅРёР№ Р±СЂР°СѓР·РµСЂ);
        3. РїРѕРєР°Р·Р°С‚Рё СЂСЏРґРѕРє Р°РґСЂРµСЃРё вЂ” С‰РѕР± РјРѕР¶РЅР° Р±СѓР»Рѕ РїС–С‚Рё РґР°Р»С– СЃР°РјРѕРјСѓ;
        4. РІС–РґРєСЂРёС‚Рё СЃС‚РѕСЂС–РЅРєСѓ.
        """
        target = browser_panel.normalise_url(url)
        if not target:
            return False
        if not browser_panel.is_showable(target):
            self.set_status(f"РђРґСЂРµСЃСѓ {target} РІР±СѓРґРѕРІР°РЅРµ РІС–РєРЅРѕ РЅРµ РІС–РґРєСЂРёРІР°С”.")
            return False
        self.toggle_preview(True)
        try:
            self.live_preview.show_address_bar()
        except (tk.TclError, AttributeError):
            pass
        ok = False
        try:
            ok = bool(self.live_preview.open_url(target))
        except (tk.TclError, AttributeError) as exc:
            LOG.debug("Р’Р±СѓРґРѕРІР°РЅРёР№ Р±СЂР°СѓР·РµСЂ РЅРµРґРѕСЃС‚СѓРїРЅРёР№: %s", exc, exc_info=True)
        if not ok:
            # Р‘СЂР°СѓР·РµСЂР° РІ СЃРёСЃС‚РµРјС– РјРѕР¶Рµ РЅРµ Р±СѓС‚Рё Р·РѕРІСЃС–Рј вЂ” С‚РѕРґС– С‡РµСЃРЅРѕ РєР°Р¶РµРјРѕ.
            self.set_status("РќРµ РІРґР°Р»РѕСЃСЊ РІС–РґРєСЂРёС‚Рё СЃС‚РѕСЂС–РЅРєСѓ Сѓ РІР±СѓРґРѕРІР°РЅРѕРјСѓ Р±СЂР°СѓР·РµСЂС–. "
                            f"РђРґСЂРµСЃР°: {target}")
            return False
        self.set_status(f"Р’С–РґРєСЂРёС‚Рѕ Сѓ РІР±СѓРґРѕРІР°РЅРѕРјСѓ Р±СЂР°СѓР·РµСЂС–: {target}")
        return True

    def open_url_dialog(self) -> None:
        """Р—Р°РїРёС‚Р°С‚Рё Р°РґСЂРµСЃСѓ Р№ РїРѕРєР°Р·Р°С‚Рё С—С— Сѓ РІР±СѓРґРѕРІР°РЅРѕРјСѓ Р±СЂР°СѓР·РµСЂС–."""
        from tkinter import simpledialog

        current = ""
        try:
            current = self.live_preview.inner.view.url or ""
        except (tk.TclError, AttributeError):
            current = ""
        url = simpledialog.askstring(
            "Р’С–РґРєСЂРёС‚Рё Р°РґСЂРµСЃСѓ",
            "РђРґСЂРµСЃР° (Р»РѕРєР°Р»СЊРЅРёР№ СЃР°Р№С‚ Р°Р±Рѕ СЃС‚РѕСЂС–РЅРєР° Р· С–РЅС‚РµСЂРЅРµС‚Сѓ):",
            initialvalue=current or "https://", parent=self)
        if url:
            self.open_url_in_browser(url)

    def open_local_page(self, path: Path) -> bool:
        """РџРѕРєР°Р·Р°С‚Рё Р»РѕРєР°Р»СЊРЅРёР№ HTML-С„Р°Р№Р» Сѓ РІР±СѓРґРѕРІР°РЅРѕРјСѓ Р±СЂР°СѓР·РµСЂС–."""
        target = browser_panel.file_url(path)
        if not target:
            self.set_status(f"Р¤Р°Р№Р» РЅРµ Р·РЅР°Р№РґРµРЅРѕ: {path}")
            return False
        return self.open_url_in_browser(target)


    def apply_theme_mode(self, mode: str) -> None:
        """РџРµСЂРµРјРєРЅСѓС‚Рё СЃРІС–С‚Р»Сѓ/С‚РµРјРЅСѓ С‚РµРјСѓ Р№ Р·Р±РµСЂРµРіС‚Рё РІРёР±С–СЂ.

        Р’РёР±С–СЂ РѕРґСЂР°Р·Сѓ РїРёС€РµС‚СЊСЃСЏ РІ ``settings.json``, С‚РѕР¶ РЅР°СЃС‚СѓРїРЅРёР№ Р·Р°РїСѓСЃРє
        РІС–РґРєСЂРёРІР°С”С‚СЊСЃСЏ РІ С‚С–Р№ СЃР°РјС–Р№ С‚РµРјС–. РћРєСЂС–Рј РєРѕР»СЊРѕСЂС–РІ РІС–РґР¶РµС‚С–РІ
        РїРµСЂРµРјР°Р»СЊРѕРІСѓС”С‚СЊСЃСЏ Р№ РїС–РґСЃРІС–С‚РєР° СЃРёРЅС‚Р°РєСЃРёСЃСѓ: С‚РµРіРё РІ ``Text`` С‚СЂРёРјР°СЋС‚СЊ
        РІР»Р°СЃРЅС– РєРѕР»СЊРѕСЂРё Р№ СЃР°РјС– РЅРµ РѕРЅРѕРІР»СЋСЋС‚СЊСЃСЏ.
        """
        theme.switch_mode(mode, root=self, theme_obj=self.theme)
        self.settings.ui.theme = theme.current_mode()
        self.settings.save()
        try:
            self.chat.apply_font()
        except (tk.TclError, AttributeError):
            pass
        try:
            # РЎРєРёРґР°С”РјРѕ РєРµС€ В«РѕСЃС‚Р°РЅРЅСЊРѕС— С‚РµРјРёВ» СЃС‚СЂС–С‡РєРё Р№ РїРµСЂРµРјР°Р»СЊРѕРІСѓС”РјРѕ РєР°СЂС‚РєРё.
            self.chat.retheme()
        except (tk.TclError, AttributeError):
            pass
        try:
            # РўРµРіРё РїС–РґСЃРІС–С‚РєРё РІ СЂРµРґР°РєС‚РѕСЂР°С… Р±РµСЂСѓС‚СЊ РєРѕР»СЊРѕСЂРё Р· theme.SYNTAX_COLORS.
            self.tabs.apply_settings()
        except (tk.TclError, AttributeError):
            pass
        try:
            self._update_theme_menu()
        except (tk.TclError, AttributeError):
            pass
        self.set_status(f"РўРµРјР°: {'С‚РµРјРЅР°' if theme.current_mode() == 'dark' else 'СЃРІС–С‚Р»Р°'} "
                        f"(Р·Р±РµСЂРµР¶РµРЅРѕ).")

    def _update_theme_menu(self) -> None:
        """РџРѕРєР°Р·Р°С‚Рё РІ РјРµРЅСЋ, СЏРєР° С‚РµРјР° Р°РєС‚РёРІРЅР° (СЂР°РґС–Рѕ-РіР°Р»РѕС‡РєР°)."""
        var = getattr(self, "_theme_var", None)
        if var is not None:
            try:
                var.set(theme.current_mode())
            except tk.TclError:
                pass

    def _save_theme(self) -> None:
        """Р—Р±РµСЂРµРіС‚Рё РїРѕС‚РѕС‡РЅСѓ С‚РµРјСѓ РІ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏС… (Р±РµР· РїРµСЂРµРјРёРєР°РЅРЅСЏ)."""
        self.settings.ui.theme = theme.current_mode()
        self.settings.save()
        self.set_status(f"РўРµРјСѓ Р·Р±РµСЂРµР¶РµРЅРѕ: {'С‚РµРјРЅР°' if theme.current_mode() == 'dark' else 'СЃРІС–С‚Р»Р°'}.")

    def show_ast_tree(self) -> None:
        """РџРѕРєР°Р·Р°С‚Рё СЃРёСЂРµ AST-РґРµСЂРµРІРѕ РїРѕС‚РѕС‡РЅРѕРіРѕ С„Р°Р№Р»Сѓ."""
        from . import ast_index

        editor = self.tabs.current()
        if editor is None:
            self.set_status("РЎРїРѕС‡Р°С‚РєСѓ РІС–РґРєСЂРёР№ С„Р°Р№Р».")
            return
        result = ast_index.analyse(editor.get_text())
        if result.problem is not None:
            self.show_text_window(
                f"AST В· {editor.filename}",
                f"Р¤Р°Р№Р» РЅРµ СЂРѕР·Р±РёСЂР°С”С‚СЊСЃСЏ вЂ” СЂСЏРґРѕРє {result.problem.line}:\n"
                f"{result.problem.short}\n\n(РІРёРїСЂР°РІ РїРѕРјРёР»РєСѓ, С‰РѕР± РїРѕР±Р°С‡РёС‚Рё РґРµСЂРµРІРѕ)",
            )
            return
        rows = ast_index.tree_rows(result.tree, limit=600)
        lines = [f"AST РґР»СЏ {editor.filename}", "=" * 40,
                 f"РЎРёРјРІРѕР»С–РІ: {len(result.symbols)} В· РІСѓР·Р»С–РІ: {len(rows)} В· "
                 f"СЂРѕР·Р±С–СЂ: {result.elapsed:.1f} РјСЃ", ""]
        for depth, name, snippet in rows:
            lines.append(f"{'  ' * depth}{name}" + (f"  {snippet}" if snippet else ""))
        self.show_text_window(f"AST В· {editor.filename}", "\n".join(lines))

    def show_symbols_report(self) -> None:
        """РџРѕРІРЅРёР№ Р·РІС–С‚ РїСЂРѕ СЃРёРјРІРѕР»Рё: РїС–РґРїРёСЃРё, РґРѕРєСѓ, РґРµРєРѕСЂР°С‚РѕСЂРё."""
        from . import ast_index

        editor = self.tabs.current()
        if editor is None:
            return
        result = ast_index.analyse(editor.get_text())
        lines = [f"РЎРёРјРІРѕР»Рё {editor.filename}", "=" * 40, result.metrics.summary, ""]
        if result.problem is not None:
            lines.append(f"вљ  СЂСЏРґРѕРє {result.problem.line}: {result.problem.short}")
            lines.append("")
        for sym in result.symbols:
            indent = "  " * sym.depth
            lines.append(f"{indent}{sym.label}  вЂ” СЂСЏРґРѕРє {sym.line}"
                         f"вЂ“{sym.end_line or sym.line}")
            if sym.decorators:
                lines.append(f"{indent}    РґРµРєРѕСЂР°С‚РѕСЂРё: {', '.join(sym.decorators)}")
            if sym.docstring:
                lines.append(f"{indent}    {sym.docstring}")
        for imported in result.imports:
            lines.append(f"{imported.icon} {imported.name} вЂ” СЂСЏРґРѕРє {imported.line}")
        self.show_text_window(f"РЎРёРјРІРѕР»Рё В· {editor.filename}", "\n".join(lines))

    def show_diff_for(self, path: Path) -> None:
        """РџРѕРєР°Р·Р°С‚Рё diff РјС–Р¶ СЂРµР·РµСЂРІРЅРѕСЋ РєРѕРїС–С”СЋ С„Р°Р№Р»Сѓ С‚Р° РїРѕС‚РѕС‡РЅРѕСЋ РІРµСЂСЃС–С”СЋ."""
        path = Path(path)
        backup = Path(str(path) + ".bak")
        try:
            new_text = diff_stats.read_text_safe(path) or ""
            old_text = diff_stats.read_text_safe(backup) or ""
        except Exception as exc:  # noqa: BLE001
            self.set_status(f"РќРµ РІРґР°Р»РѕСЃСЊ РїСЂРѕС‡РёС‚Р°С‚Рё diff: {exc}")
            return
        self.show_text_window(
            f"diff В· {path.name}",
            diff_stats.make_unified_diff(old_text, new_text, path.name),
        )

    def show_text_window(self, title: str, text: str) -> None:
        """РџСЂРѕСЃС‚Рµ РІС–РєРЅРѕ Р· РјРѕРЅРѕС€РёСЂРёРЅРЅРёРј С‚РµРєСЃС‚РѕРј (diff, СЂРµР·СѓР»СЊС‚Р°С‚, Р¶СѓСЂРЅР°Р»)."""
        win = tk.Toplevel(self)
        win.title(title)
        win.configure(bg=theme.BG)
        win.transient(self)
        box = tk.Text(win, wrap="none", bg=theme.BG_EDITOR, fg=theme.FG, bd=0,
                      highlightthickness=0, font=self.theme.mono_small, padx=12, pady=10)
        box.pack(fill="both", expand=True, padx=8, pady=8)
        for tag, colour in (("add", theme.SUCCESS), ("del", theme.ERROR)):
            box.tag_configure(tag, foreground=colour)
        for line in (text or "(РїРѕСЂРѕР¶РЅСЊРѕ)").splitlines():
            tag = "add" if line.startswith("+") and not line.startswith("+++") else (
                "del" if line.startswith("-") and not line.startswith("---") else "")
            box.insert("end", line + "\n", tag)
        box.configure(state="disabled")
        footer = tk.Frame(win, bg=theme.BG)
        footer.pack(fill="x", padx=8, pady=(0, 8))
        widgets.Chip(footer, "РљРѕРїС–СЋРІР°С‚Рё", lambda: self._copy_text(text)).pack(side="left")
        widgets.Chip(footer, "Р—Р°РєСЂРёС‚Рё", win.destroy).pack(side="right")
        # Р’С–РєРЅРѕ РјР°С” Р±СѓС‚Рё РІ РјРµР¶Р°С… РµРєСЂР°РЅР°, Р° РЅРµ В«900x600 Р· Р»С–РІРѕРіРѕ РІРµСЂС…РЅСЊРѕРіРѕ РєСѓС‚Р°В».
        widgets.place_window(win, width=900, height=600, center_on=self)

    def _copy_text(self, text: str) -> None:
        try:
            self.clipboard_clear()
            self.clipboard_append(text or "")
        except tk.TclError:
            pass

    def _show_side_initial(self) -> None:
        # РЎРїРёСЃРѕРє С‡Р°С‚С–РІ РјР°С” Р±СѓС‚Рё Р·Р°РІР¶РґРё РІС–РґРєСЂРёС‚РёР№ Р·Р»С–РІР°.
        self.show_side("chats")

    def _open_welcome(self) -> None:
        """РџРѕСЂРѕР¶РЅС–Р№ РїСЂРѕС”РєС‚: РїРѕРєР°Р·Р°С‚Рё РєРѕСЂРѕС‚РєСѓ РґРѕРІС–РґРєСѓ Р·Р°РјС–СЃС‚СЊ С‡РѕСЂРЅРѕРіРѕ РµРєСЂР°РЅР°."""
        editor = self.tabs.new_file()
        editor.filename = "Р›Р°СЃРєР°РІРѕ РїСЂРѕСЃРёРјРѕ.md"
        editor.set_text(WELCOME_TEXT)
        self.tabs.rename_tab(editor, "Р›Р°СЃРєР°РІРѕ РїСЂРѕСЃРёРјРѕ")
        editor.set_readonly(True)

    # в”Ђв”Ђ MCP в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _ui_call(self, func, *args) -> None:
        """Р’РёРєРѕРЅР°С‚Рё РѕРЅРѕРІР»РµРЅРЅСЏ С–РЅС‚РµСЂС„РµР№СЃСѓ Р· РіРѕР»РѕРІРЅРѕРіРѕ РїРѕС‚РѕРєСѓ.

        Р¤РѕРЅРѕРІС– РїРѕС‚РѕРєРё РЅРµ РјР°СЋС‚СЊ РїСЂР°РІР° РєР»РёРєР°С‚Рё ``after()`` Р±РµР·РїРѕСЃРµСЂРµРґРЅСЊРѕ:
        tkinter РЅРµ РїРѕС‚РѕРєРѕР±РµР·РїРµС‡РЅРёР№, С– РІ Release-Р·Р±С–СЂС†С– С†Рµ РїР°РґР°С” Р·
        В«main thread is not in main loopВ». РўРѕРјСѓ Р»РёС€Рµ СЃРєР»Р°РґР°С”РјРѕ РІ С‡РµСЂРіСѓ.
        """
        self._ui_queue.put((func, args))


    def _timer_alive(self) -> bool:
        """Р§Рё РјРѕР¶РЅР° С‰Рµ РїР»Р°РЅСѓРІР°С‚Рё ``after`` (РІС–РґР¶РµС‚ С–СЃРЅСѓС” Р№ РІС–РєРЅРѕ Р¶РёРІРµ)."""
        try:
            return bool(self.winfo_exists())
        except Exception:  # noqa: BLE001 - РІС–РґР¶РµС‚ СѓР¶Рµ Р·РЅРёС‰РµРЅРѕ
            return False

    def _drain_ui(self) -> None:
        try:
            for _ in range(100):
                try:
                    func, args = self._ui_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    func(*args)
                except tk.TclError:
                    pass
                except Exception as exc:  # noqa: BLE001 - РѕРґРЅРµ РѕРЅРѕРІР»РµРЅРЅСЏ РЅРµ РјР°С”
                    # РІР°Р»РёС‚Рё РІРµСЃСЊ С†РёРєР»: С–РЅР°РєС€Рµ РЅР°СЃС‚СѓРїРЅС– РѕРЅРѕРІР»РµРЅРЅСЏ РіСѓР±Р»СЏС‚СЊСЃСЏ.
                    LOG.warning("РџРѕРјРёР»РєР° РѕРЅРѕРІР»РµРЅРЅСЏ С–РЅС‚РµСЂС„РµР№СЃСѓ: %s", exc, exc_info=True)
        finally:
            try:
                if self.winfo_exists():
                    self._ui_after = (self.after(80, self._drain_ui) if self._timer_alive() else None)
            except tk.TclError:
                self._ui_after = None

    def _load_mcp_if_not_started(self) -> None:
        """Р—Р°РїСѓСЃС‚РёС‚Рё MCP, СЏРєС‰Рѕ Р°РІС‚РѕР·Р°РїСѓСЃРє РјРѕРґРµР»С– Р№РѕРіРѕ РЅРµ Р·Р°РїСѓСЃС‚РёРІ.

        РџРѕСЂСЏРґРѕРє Р¶РёС‚С‚С”РІРѕРіРѕ С†РёРєР»Сѓ: РјРѕРґРµР»СЊ в†’ inference в†’ MCP. РћСЃРЅРѕРІРЅСѓ СЃРїСЂРѕР±Сѓ
        СЂРѕР±РёС‚СЊ ``_after_auto_setup``; С†РµР№ РІРёРєР»РёРє вЂ” Р·Р°РїРѕР±С–Р¶РЅРёРє РЅР° РІРёРїР°РґРѕРє,
        РєРѕР»Рё Р°РІС‚РѕСЂРѕР·РєР»Р°РґРєР° РјРѕРґРµР»С– РІРёРјРєРЅРµРЅР° Р°Р±Рѕ С‚СЂРёРІР°С” РґРѕРІС€Рµ: MCP РЅРµ РјР°С”
        С‡РµРєР°С‚Рё РІС–С‡РЅРѕ, Р°Р»Рµ Р№ РЅРµ РјР°С” СЃС‚Р°СЂС‚СѓРІР°С‚Рё Р РђРќР†РЁР• Р·Р° РјРѕРґРµР»СЊ.
        """
        if getattr(self, "_mcp_loaded", False) or self._mcp_busy:
            return
        self._load_mcp_async()

    def _load_mcp_async(self) -> None:
        if not self.settings.mcp.enabled or self._mcp_busy:
            return
        # РџРѕР·РЅР°С‡Р°С”РјРѕ СЃРїСЂРѕР±Сѓ: РґР°Р»С– Р°Р±Рѕ ``_after_mcp``, Р°Р±Рѕ С‚РёС…РёР№ РІРёС…С–Рґ
        # (РЅРµРјР°С” РєРѕРЅС„С–РіС–РІ) вЂ” РІ РѕР±РѕС… РІРёРїР°РґРєР°С… РїРѕРІС‚РѕСЂРЅРёР№ Р°РІС‚РѕР·Р°РїСѓСЃРє РЅРµ РїРѕС‚СЂС–Р±РµРЅ.
        self._mcp_loaded = True
        root = Path(self.settings.workspace)
        paths = mcp_panel.workspace_config_paths(root)
        if not paths:
            return
        configs = mcp_client.McpManager.load_configs(paths)
        configs = [c for c in configs if c.name not in set(self.settings.mcp.servers)]
        if not configs:
            return
        self._mcp_busy = True
        self.set_status(f"РџС–РґРєР»СЋС‡Р°СЋ MCP-СЃРµСЂРІРµСЂРё: {len(configs)}вЂ¦")
        # РќР°РіР»СЏРґР°С‡ РјР°С” Р·РЅР°С‚Рё РєРѕРЅС„С–РіРё, С‰РѕР± СѓРјС–С‚Рё РїРµСЂРµР·Р°РїСѓСЃС‚РёС‚Рё СЃРµСЂРІРµСЂ.
        try:
            self.mcp_watcher.remember(configs)
        except Exception:  # noqa: BLE001 - РЅР°РіР»СЏРґР°С‡ РЅРµ РјР°С” Р»Р°РјР°С‚Рё СЃС‚Р°СЂС‚
            LOG.debug("РљРѕРЅС„С–РіРё MCP РЅРµ РїРµСЂРµРґР°РЅРѕ РЅР°РіР»СЏРґР°С‡Сѓ", exc_info=True)

        def work() -> None:
            statuses = self.mcp_manager.start_all(configs)
            self._ui_call(self._after_mcp, statuses)

        threading.Thread(target=work, daemon=True).start()

    def _after_mcp(self, statuses: dict[str, str]) -> None:
        self._mcp_busy = False
        self._mcp_loaded = True
        running = sum(1 for state in statuses.values() if state == "РїСЂР°С†СЋС”")
        self.mcp_panel.refresh()
        self.set_status(f"MCP: РїСЂР°С†СЋС” {running} Р· {len(statuses)} В· С–РЅСЃС‚СЂСѓРјРµРЅС‚С–РІ "
                        f"{len(self.mcp_manager.tool_catalog())}")
        # РџС–СЃР»СЏ СЃС‚Р°СЂС‚Сѓ РІРјРёРєР°С”РјРѕ РЅР°РіР»СЏРґР°С‡: РІС–РЅ РїРµСЂРµРІС–СЂСЏС‚РёРјРµ Р–РР’Р†РЎРўР¬ СЃРµСЂРІРµСЂС–РІ,
        # Р° РЅРµ Р»РёС€Рµ С„Р°РєС‚ В«initialize РЅРµ РІРїР°РІВ». Р‘РµР· С†СЊРѕРіРѕ РїРѕРјРµСЂР»РёР№ СЃРµСЂРІРµСЂ
        # Р»РёС€Р°РІСЃСЏ Р·С– СЃС‚Р°С‚СѓСЃРѕРј В«РїСЂР°С†СЋС”В».
        if statuses and not self.mcp_watcher.running:
            try:
                self.mcp_watcher.start()
            except Exception:  # noqa: BLE001 - РЅР°РіР»СЏРґР°С‡ РЅРµРѕР±РѕРІ'СЏР·РєРѕРІРёР№
                LOG.debug("MCP-РЅР°РіР»СЏРґР°С‡ РЅРµ Р·Р°РїСѓСЃС‚РёРІСЃСЏ", exc_info=True)

    def reload_mcp(self) -> None:
        if self._mcp_busy:
            return
        self._mcp_busy = True

        def work() -> None:
            try:
                self.mcp_manager.stop_all()
            finally:
                root = Path(self.settings.workspace)
                configs = mcp_client.McpManager.load_configs(mcp_panel.workspace_config_paths(root))
                configs = [c for c in configs if c.name not in set(self.settings.mcp.servers)]
                try:
                    self.mcp_watcher.remember(configs)
                except Exception:  # noqa: BLE001
                    LOG.debug("РљРѕРЅС„С–РіРё MCP РЅРµ РѕРЅРѕРІР»РµРЅРѕ", exc_info=True)
                statuses = self.mcp_manager.start_all(configs) if configs else {}
                self._ui_call(self._after_mcp, statuses)

        threading.Thread(target=work, daemon=True).start()

    # в”Ђв”Ђ Р°РіРµРЅС‚ С– РјРѕРґРµР»СЊ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _on_model_changed(self) -> None:
        model = self.settings.llm.model or "РјРѕРґРµР»СЊ РЅРµ РІРёР±СЂР°РЅР°"
        self.agent.llm_settings = self.settings.llm
        self.agent.agent_settings = self.settings.agent
        self.chat.set_online(bool(self.settings.llm.model))
        # в”Ђв”Ђ РџС–СЃР»СЏ Р·РјС–РЅРё РјРѕРґРµР»С– Р’РЎР• СЃС‚Р°СЂРµ СЃС‚Р°С” РЅРµРґС–Р№СЃРЅРёРј в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        # Р’С–РєРЅРѕ РєРѕРЅС‚РµРєСЃС‚Сѓ, РЅР°Р±С–СЂ СЃС…РµРј С–РЅСЃС‚СЂСѓРјРµРЅС‚С–РІ С– СЃС‚Р°РЅ СЃРµСЂРІРµСЂР° РѕРїРёСЃСѓРІР°Р»Рё
        # Р†РќРЁРЈ РјРѕРґРµР»СЊ. Р Р°РЅС–С€Рµ РІРѕРЅРё Р»РёС€Р°Р»РёСЃСЊ, С– Р°РіРµРЅС‚ РЅР°РґСЃРёР»Р°РІ РїСЂРѕРјРїС‚,
        # СЂРѕР·СЂР°С…РѕРІР°РЅРёР№ РЅР° РїРѕРїРµСЂРµРґРЅС” РІС–РєРЅРѕ: С†Рµ С– РґР°РІР°Р»Рѕ РѕР±СЂРёРІ Р·'С”РґРЅР°РЅРЅСЏ
        # (``WinError 10054``) РѕРґСЂР°Р·Сѓ РїС–СЃР»СЏ РїРµСЂРµРјРёРєР°РЅРЅСЏ.
        self._invalidate_model_state(reason=f"РїРµСЂРµРјРёРєР°РЅРЅСЏ РЅР° {model}")
        self._apply_context_limit()
        # в”Ђв”Ђ РћР”РРќ РїС–РґРїРёСЃ РІ СѓСЃС–С… РјС–СЃС†СЏС… в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        # Р Р°РЅС–С€Рµ С‚СѓС‚ СЃС‚Р°РІРёРІСЃСЏ Р»РёС€Рµ РїС–РґРїРёСЃ РєРѕРјРїРѕР·РµСЂР°, С‚РѕРјСѓ РїС–РіСѓР»РєР° СЃРµСЃС–С—
        # пј€``session_header``пј‰Р›РРЁРђР›РђРЎР¬ В«РјРѕРґРµР»СЊ РЅРµ РІРёР±СЂР°РЅР°В» РЅР°Р·Р°РІР¶РґРё: С—С—
        # РѕРЅРѕРІР»СЋРІР°РІ С‚С–Р»СЊРєРё СЃРµР»РµРєС‚РѕСЂ РјРѕРґРµР»С–, Р° РЅРµ СЃС‚Р°СЂС‚. РќР° СЃРєСЂС–РЅС€РѕС‚С–
        # РєРѕСЂРёСЃС‚СѓРІР°С‡Р° С†Рµ РІРёРіР»СЏРґР°Р»Рѕ СЏРє В«РґРІС– СЂС–Р·РЅС– РјРѕРґРµР»С– РІРёР±СЂР°РЅС–В».
        self._sync_model_labels()
        self.set_status(f"РњРѕРґРµР»СЊ: {model} @ {self.settings.llm.base_url}")

    def _invalidate_model_state(self, *, reason: str = "") -> None:
        """РЎРєРёРЅСѓС‚Рё РІСЃРµ РїРѕС…С–РґРЅРµ РІС–Рґ РјРѕРґРµР»С–: РєРѕРЅС‚РµРєСЃС‚, СЃС…РµРјРё, СЃС‚Р°РЅ СЃРµСЂРІРµСЂР°.

        Р¦Рµ РћР”РќРђ С‚РѕС‡РєР° С–РЅРІР°Р»С–РґР°С†С–С—. Р Р°РЅС–С€Рµ РєРѕР¶РЅРµ РјС–СЃС†Рµ СЃРєРёРґР°Р»Рѕ СЃРІРѕС” (Р°Р±Рѕ РЅРµ
        СЃРєРёРґР°Р»Рѕ РЅС–С‡РѕРіРѕ), С– РїС–СЃР»СЏ РїРµСЂРµРјРёРєР°РЅРЅСЏ РјРѕРґРµР»С– Р°РіРµРЅС‚ РїСЂР°С†СЋРІР°РІ С–Р·
        Р·Р°СЃС‚Р°СЂС–Р»РёРј РІС–РєРЅРѕРј РєРѕРЅС‚РµРєСЃС‚Сѓ.
        """
        self._ctx_limit_cache = None
        self._context_limit = 0
        try:
            self.server_state.invalidate(reason=reason)
        except (AttributeError, tk.TclError):
            LOG.debug("РЎС‚Р°РЅ СЃРµСЂРІРµСЂР° РЅРµ СЃРєРёРЅСѓС‚Рѕ", exc_info=True)
        try:
            self.agent.invalidate_tool_cache(reason=reason)
        except (AttributeError, tk.TclError):
            LOG.debug("РљРµС€ С–РЅСЃС‚СЂСѓРјРµРЅС‚С–РІ РЅРµ СЃРєРёРЅСѓС‚Рѕ", exc_info=True)
        try:
            self.agent.set_requested_context(
                int(self.settings.engine.ctx_size or 0))
        except (AttributeError, tk.TclError):
            pass
        # РђРіРµРЅС‚ РјР°С” РџР•Р Р•Р’РР—РќРђР§РРўР РІС–РєРЅРѕ Р· РЅРѕРІРѕРіРѕ СЃРµСЂРІРµСЂР°, Р° РЅРµ РІР·СЏС‚Рё СЃС‚Р°СЂРµ.
        try:
            self.agent._context_window = None
            self.agent._context_budget = None
        except AttributeError:
            pass
        LOG.info("РЎС‚Р°РЅ РјРѕРґРµР»С– СЃРєРёРЅСѓС‚Рѕ: %s", reason or "Р·РјС–РЅР° РјРѕРґРµР»С–")

    def _on_server_state(self, state) -> None:
        """РћРЅРѕРІРёС‚Рё С–РЅС‚РµСЂС„РµР№СЃ Р·Р° СѓР·РіРѕРґР¶РµРЅРёРј СЃС‚Р°РЅРѕРј СЃРµСЂРІРµСЂР°.

        Р’РёРєР»РёРєР°С”С‚СЊСЃСЏ Р· С„РѕРЅРѕРІРѕРіРѕ РїРѕС‚РѕРєСѓ РѕРїРёС‚СѓРІР°РЅРЅСЏ, С‚РѕРјСѓ РІСЃС– РґС–С— Р· РІС–РґР¶РµС‚Р°РјРё
        Р№РґСѓС‚СЊ С‡РµСЂРµР· :meth:`_ui_call`.
        """
        def apply() -> None:
            try:
                self._alive_cache = (bool(state.reachable), time.time())
            except AttributeError:
                pass
            # РљРѕРЅС‚РµРєСЃС‚ Р±РµСЂРµРјРѕ Р—Р’Р†Р”РЎР, Р° РЅРµ Р· РІР»Р°СЃРЅРѕРіРѕ РѕРїРёС‚СѓРІР°РЅРЅСЏ: С–РЅР°РєС€Рµ
            # С–РЅС‚РµСЂС„РµР№СЃ С– Р°РіРµРЅС‚ Р·РЅРѕРІСѓ РїРѕРєР°Р·СѓРІР°Р»Рё Р± СЂС–Р·РЅС– С‡РёСЃР»Р°.
            if state.context and state.context != int(self._context_limit or 0):
                self._context_limit = int(state.context)
                self._ctx_limit_cache = (int(state.context), time.time())
                try:
                    self.chat.set_context_limit(int(state.context))
                    self.agent.set_context_limit(int(state.context))
                except (tk.TclError, AttributeError):
                    LOG.debug("Р›С–РјС–С‚ РєРѕРЅС‚РµРєСЃС‚Сѓ РЅРµ Р·Р°СЃС‚РѕСЃРѕРІР°РЅРѕ", exc_info=True)
            try:
                self._refresh_header()
                self.context.refresh()
            except (tk.TclError, AttributeError):
                LOG.debug("РџР°РЅРµР»СЊ РЅРµ РѕРЅРѕРІР»РµРЅРѕ РїС–СЃР»СЏ СЃС‚Р°РЅСѓ СЃРµСЂРІРµСЂР°",
                          exc_info=True)
            # РљРѕСЂРёСЃС‚СѓРІР°С‡ РјР°С” Р±Р°С‡РёС‚Рё Р РћР—Р‘Р†Р–РќР†РЎРўР¬, Р° РЅРµ Р·РґРѕРіР°РґСѓРІР°С‚РёСЃСЊ.
            if state.reachable and not state.model_matches:
                self.set_status(
                    f"РЈРІР°РіР°: СЃРµСЂРІРµСЂ РѕР±СЃР»СѓРіРѕРІСѓС” В«{state.model_loaded}В», Р° РІ "
                    f"РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏС… В«{state.model_configured}В».")

        self._ui_call(apply)

    def _apply_context_limit(self) -> None:
        """РџРµСЂРµРґР°С‚Рё С‡Р°С‚Сѓ СЂРѕР·РјС–СЂ РІС–РєРЅР° РєРѕРЅС‚РµРєСЃС‚Сѓ РґР»СЏ СЃРјСѓРіРё СЃС‚Р°С‚РёСЃС‚РёРєРё.

        Р’РђР–Р›РР’Рћ РїСЂРѕ В«Р·Р°РІРёСЃР°РЅРЅСЏВ». Р Р°РЅС–С€Рµ С‚СѓС‚ Р‘Р•Р—РЈРњРћР’РќРћ Р№С€РѕРІ РјРµСЂРµР¶РµРІРёР№ Р·Р°РїРёС‚
        РґРѕ ``/props``. РЇРєС‰Рѕ СЃРµСЂРІРµСЂ РЅРµ Р·Р°РїСѓС‰РµРЅРѕ, Р·'С”РґРЅР°РЅРЅСЏ РІРёСЃС–Р»Рѕ РґРѕ С‚Р°Р№РјР°СѓС‚Сѓ
        (3 СЃ), С– С–РЅС‚РµСЂС„РµР№СЃ Р·Р°СЃС‚РёРіР°РІ РќРђ РЎРўРђР РўР† вЂ” РїСЂРѕС„С–Р»РµСЂ РїРѕРєР°Р·Р°РІ 5.1 СЃ РЅР°
        РїРµСЂС€РѕРјСѓ РєР°РґСЂС– (Р· РЅРёС… 2.1 СЃ С‚СѓС‚). РўРµРїРµСЂ:

        * СЃРїРµСЂС€Сѓ Р±РµСЂРµРјРѕ РІС–РґРѕРјРµ С‡РёСЃР»Рѕ Р· РЅР°Р»Р°С€С‚СѓРІР°РЅСЊ (Р±РµР· РјРµСЂРµР¶С– РІР·Р°РіР°Р»С–);
        * РјРµСЂРµР¶Сѓ РїРёС‚Р°С”РјРѕ Р›РРЁР• Сѓ С„РѕРЅС–, Р° СЂРµР·СѓР»СЊС‚Р°С‚ Р·Р°СЃС‚РѕСЃРѕРІСѓС”РјРѕ РїС–Р·РЅС–С€Рµ.

        РўР°Рє СЃС‚Р°СЂС‚ РЅС–РєРѕР»Рё РЅРµ Р±Р»РѕРєСѓС”С‚СЊСЃСЏ РјРµСЂРµР¶РµСЋ.
        """
        limit = int(getattr(self, "_context_limit", 0) or 0)
        if not limit:
            limit = int(self.settings.engine.ctx_size or 0)
        if not limit:
            # Р§РёСЃР»Р° РЅРµРјР°С” РЅС– РІ РїР°Рј'СЏС‚С–, РЅС– РІ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏС… вЂ” РїРёС‚Р°С”РјРѕ
            # ``_server_context_limit``, СЏРєРёР№ РІС–РґРґР°С” РљР•РЁ (РјРµСЂРµР¶С– С‚СѓС‚ РЅРµРјР°С”)
            # С– СЃР°Рј СЃС‚Р°РІРёС‚СЊ С„РѕРЅРѕРІРµ РѕРїРёС‚СѓРІР°РЅРЅСЏ.
            limit = int(self._server_context_limit() or 0)
        if not limit:
            # РќРµРІС–РґРѕРјРѕ вЂ” РїРѕРєР°Р·СѓС”РјРѕ С‚РёРїРѕРІРµ Р№ РїРёС‚Р°С”РјРѕ СЃРµСЂРІРµСЂ Сѓ Р¤РћРќР†.
            limit = 8192
        try:
            self.chat.set_context_limit(limit)
            self.agent.set_context_limit(limit)
        except (tk.TclError, AttributeError):
            pass
        # в”Ђв”Ђ Р—Р°СЏРІР»РµРЅРµ в‰  СЂРµР°Р»СЊРЅРµ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        # ``launch_with_recovery`` РјРѕР¶Рµ СЃР°Рј Р·РјРµРЅС€РёС‚Рё РєРѕРЅС‚РµРєСЃС‚ (С‰РѕР± РјРѕРґРµР»СЊ
        # РІР»С–Р·Р»Р° Сѓ VRAM): Сѓ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏС… Р»РёС€Р°С”С‚СЊСЃСЏ 32768, Р° СЃРµСЂРІРµСЂ РїСЂР°С†СЋС”
        # Р· 16384. РђРіРµРЅС‚ РІРёР·РЅР°С‡Р°С” РЎРџР РђР’Р–РќР„ РІС–РєРЅРѕ СЃР°Рј (``/props``), С‚РѕРјСѓ
        # Р·Р°СЏРІР»РµРЅРµ С‡РёСЃР»Рѕ РїРµСЂРµРґР°С”РјРѕ Р№РѕРјСѓ Р»РёС€Рµ СЏРє Р·Р°РїР°СЃРЅРёР№ РІР°СЂС–Р°РЅС‚ вЂ” С–РЅР°РєС€Рµ
        # РІС–РЅ РїРѕРІС–СЂРёС‚СЊ 32768 С– РЅР°РґС–С€Р»Рµ Р·Р°РІРµР»РёРєРёР№ РїСЂРѕРјРїС‚.
        try:
            self.agent.set_requested_context(int(self.settings.engine.ctx_size or 0))
        except (tk.TclError, AttributeError):
            pass

    def _probe_context_async(self) -> None:
        """РЎРїРёС‚Р°С‚Рё РєРѕРЅС‚РµРєСЃС‚ СЃРµСЂРІРµСЂР° Сѓ С„РѕРЅРѕРІРѕРјСѓ РїРѕС‚РѕС†С– (РЅРµ Р±Р»РѕРєСѓСЋС‡Рё UI)."""
        if getattr(self, "_ctx_probe_running", False):
            return
        cached = getattr(self, "_ctx_limit_cache", None)
        if cached is not None and (time.time() - cached[1]) < 30.0:
            return                      # РЅРµС‰РѕРґР°РІРЅРѕ РІР¶Рµ РїРёС‚Р°Р»Рё
        self._ctx_probe_running = True

        def work() -> None:
            value = 0
            try:
                value = self._probe_server_context()
            except Exception:  # noqa: BLE001 - С„РѕРЅ РЅРµ РјР°С” РїР°РґР°С‚Рё
                LOG.debug("РћРїРёС‚СѓРІР°РЅРЅСЏ РєРѕРЅС‚РµРєСЃС‚Сѓ РІРїР°Р»Рѕ", exc_info=True)
            finally:
                self._ctx_probe_running = False
            if value:
                self._ui_call(self._apply_probed_context, value)

        threading.Thread(target=work, daemon=True,
                         name="ctx-probe").start()

    def _apply_probed_context(self, value: int) -> None:
        """Р—Р°СЃС‚РѕСЃСѓРІР°С‚Рё РєРѕРЅС‚РµРєСЃС‚, СЏРєРёР№ РїРѕРІРµСЂРЅСѓРІ СЃРµСЂРІРµСЂ (Сѓ РіРѕР»РѕРІРЅРѕРјСѓ РїРѕС‚РѕС†С–)."""
        if value <= 0:
            return
        self._ctx_limit_cache = (value, time.time())
        self._context_limit = int(value)
        try:
            self.chat.set_context_limit(int(value))
            self.agent.set_context_limit(int(value))
        except (tk.TclError, AttributeError):
            pass

    def _server_context_limit(self) -> int:
        """РЎРїРёС‚Р°С‚Рё РІ Р·Р°РїСѓС‰РµРЅРѕРіРѕ СЃРµСЂРІРµСЂР°, Р· СЏРєРёРј РєРѕРЅС‚РµРєСЃС‚РѕРј РІС–РЅ РїСЂР°С†СЋС”.

        llama.cpp РІС–РґРґР°С” ``/props`` С–Р· ``n_ctx``. Р¦Рµ С”РґРёРЅРµ С‡РµСЃРЅРµ РґР¶РµСЂРµР»Рѕ
        С‡РёСЃР»Р°: Сѓ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏС… РјРѕР¶Рµ СЃС‚РѕСЏС‚Рё В«Р°РІС‚РѕВ», Р° LM Studio С‡Рё Ollama
        РјР°СЋС‚СЊ РІР»Р°СЃРЅС– Р·РЅР°С‡РµРЅРЅСЏ.

        Р’РђР–Р›РР’Рћ: СЂРµР·СѓР»СЊС‚Р°С‚ РљР•РЁРЈР„РўР¬РЎРЇ, Р° СЃР°РјР° С„СѓРЅРєС†С–СЏ РќР• РІРёРєР»РёРєР°С”С‚СЊСЃСЏ Р·
        С–РЅС‚РµСЂС„РµР№СЃСѓ РЅР°РїСЂСЏРјСѓ вЂ” С‚С–Р»СЊРєРё Р· С„РѕРЅРѕРІРѕРіРѕ РїРѕС‚РѕРєСѓ
        (:meth:`_probe_context_async`). Р†РЅР°РєС€Рµ РїРµСЂС€РёР№ РєР°РґСЂ Р·Р°СЃС‚РёРіР°РІ РґРѕ
        С‚Р°Р№РјР°СѓС‚Сѓ Р·'С”РґРЅР°РЅРЅСЏ (Р·Р°РјС–СЂСЏРЅРѕ РїСЂРѕС„С–Р»РµСЂРѕРј: 2.1 СЃ).
        """
        cached = getattr(self, "_ctx_limit_cache", None)
        if cached is not None and (time.time() - cached[1]) < 30.0:
            return cached[0]
        value = self._probe_server_context()
        self._ctx_limit_cache = (value, time.time())
        return value

    def _probe_server_context(self) -> int:
        """Р’С–РєРЅРѕ РєРѕРЅС‚РµРєСЃС‚Сѓ Р· Р„Р”РРќРћР“Рћ РґР¶РµСЂРµР»Р° СЃС‚Р°РЅСѓ (Р±РµР· РІР»Р°СЃРЅРѕРіРѕ Р·Р°РїРёС‚Сѓ).

        Р Р°РЅС–С€Рµ С‚СѓС‚ Р±СѓРІ РѕРєСЂРµРјРёР№ ``urllib``-Р·Р°РїРёС‚ РґРѕ ``/props`` Р· С‚Р°Р№РјР°СѓС‚РѕРј
        3 СЃ вЂ” Рї'СЏС‚Рµ РјС–СЃС†Рµ РІ РїСЂРѕС”РєС‚С–, СЏРєРµ РїРёС‚Р°Р»Рѕ С‚Рµ СЃР°РјРµ. Р§РµСЂРµР· С†Рµ С–РЅС‚РµСЂС„РµР№СЃ
        С– Р°РіРµРЅС‚ РјРѕРіР»Рё РїРѕРєР°Р·Р°С‚Рё Р Р†Р—РќР† С‡РёСЃР»Р° РґР»СЏ РѕРґРЅРѕРіРѕ СЃРµСЂРІРµСЂР°: С…С‚Рѕ РІСЃС‚РёРі
        СЃРїРёС‚Р°С‚Рё, С‚РѕР№ С– РїСЂР°РІРёР№.

        РўРµРїРµСЂ СЃС‚Р°РЅ СЃРµСЂРІРµСЂР° Р·Р±РёСЂР°С” :mod:`blackchpok_ide.server_state`, С– СЃР°РјРµ
        Р·РІС–РґС‚Рё Р±РµСЂРµС‚СЊСЃСЏ С‡РёСЃР»Рѕ. РЇРєС‰Рѕ СЃРІС–Р¶РѕРіРѕ РЅРµРјР°С” вЂ” РїРѕРІРµСЂС‚Р°С”РјРѕ 0 С–
        Р·Р°РїСѓСЃРєР°С”РјРѕ С„РѕРЅРѕРІРµ РѕРїРёС‚СѓРІР°РЅРЅСЏ: С–РЅС‚РµСЂС„РµР№СЃ РЅРµ Р±Р»РѕРєСѓС”С‚СЊСЃСЏ РјРµСЂРµР¶РµСЋ.

        Р’РђР–Р›РР’Рћ РґР»СЏ РІР±СѓРґРѕРІР°РЅРѕРіРѕ СЂСѓС€С–СЏ: ``server_state`` РѕРїРёСЃСѓС” HTTP-СЃРµСЂРІРµСЂ С–
        РїСЂРѕ ``llama.dll`` Сѓ С†СЊРѕРјСѓ РїСЂРѕС†РµСЃС– РЅРµ Р·РЅР°С” РќР†Р§РћР“Рћ. РўРѕРјСѓ РґР»СЏ РЅР°С‚РёРІРЅРѕРіРѕ
        СЂСѓС€С–СЏ С‡РёСЃР»Рѕ Р±РµСЂРµС‚СЊСЃСЏ Р· СЃР°РјРѕС— РјРѕРґРµР»С– (``describe()["context_actual"]``)
        вЂ” С†Рµ Р Р•РђР›Р¬РќР• РІС–РєРЅРѕ, Р· СЏРєРёРј СЂСѓС€С–Р№ Р·Р°РІР°РЅС‚Р°Р¶РёРІСЃСЏ, Р° РЅРµ Р·Р°СЏРІР»РµРЅРµ РІ
        РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏС….
        """
        # в”Ђв”Ђ Р’Р±СѓРґРѕРІР°РЅРёР№ СЂСѓС€С–Р№: С”РґРёРЅРµ С‡РµСЃРЅРµ РґР¶РµСЂРµР»Рѕ вЂ” Р·Р°РІР°РЅС‚Р°Р¶РµРЅР° РјРѕРґРµР»СЊ в”Ђв”Ђв”Ђ
        native_limit = self._native_context_limit()
        if native_limit:
            return native_limit
        try:
            state = self.server_state.snapshot()
        except AttributeError:
            return 0
        if state.context and state.age <= server_state.STALE_SECONDS:
            return int(state.context)
        # РЎРІС–Р¶РѕРіРѕ С‡РёСЃР»Р° РЅРµРјР°С” вЂ” РїРёС‚Р°С”РјРѕ Сѓ С„РѕРЅС–, Р° РїРѕРєРё С‰Рѕ РІС–РґРґР°С”РјРѕ РІС–РґРѕРјРµ.
        try:
            if not state.reachable and not state.running:
                self.server_state.refresh(background=True)
        except (AttributeError, tk.TclError):
            LOG.debug("Р¤РѕРЅРѕРІРµ РѕРїРёС‚СѓРІР°РЅРЅСЏ РєРѕРЅС‚РµРєСЃС‚Сѓ РЅРµ Р·Р°РїСѓСЃС‚РёР»РѕСЃСЊ", exc_info=True)
        return int(state.context or 0)

    def _native_context_limit(self) -> int:
        """РЎРїСЂР°РІР¶РЅС” РІС–РєРЅРѕ РєРѕРЅС‚РµРєСЃС‚Сѓ Р·Р°РІР°РЅС‚Р°Р¶РµРЅРѕС— РјРѕРґРµР»С– Сѓ РІР»Р°СЃРЅРѕРјСѓ СЂСѓС€С–С—.

        РџРѕРІРµСЂС‚Р°С” 0, СЏРєС‰Рѕ СЂСѓС€С–Р№ РЅС–С‡РѕРіРѕ РЅРµ Р·Р°РІР°РЅС‚Р°Р¶РёРІ Р°Р±Рѕ РІС–РЅ РІРёРјРєРЅРµРЅРёР№ вЂ”
        С‚РѕРґС– РґС–С” Р·РІРёС‡Р°Р№РЅРёР№ С€Р»СЏС… С‡РµСЂРµР· ``server_state``.
        """
        if not bool(getattr(self.settings.engine, "native", True)):
            return 0
        try:
            engine = self.native_runtime.engine
        except AttributeError:
            return 0
        if not getattr(engine, "loaded", False):
            return 0
        model = getattr(engine, "model", None)
        if model is None:
            return 0
        try:
            described = model.describe()
        except Exception:                            # noqa: BLE001
            return 0
        # ``describe()`` РІС–РґРґР°С” СЃР»РѕРІРЅРёРє С–Р· С„Р°РєС‚РёС‡РЅРёРјРё С‡РёСЃР»Р°РјРё СЂСѓС€С–СЏ.
        if isinstance(described, dict):
            return int(described.get("context_actual")
                       or described.get("context") or 0)
        context = getattr(engine, "context", None)
        return int(getattr(context, "n_ctx", 0) or 0)

    def _apply_code_from_chat(self, code: str, key: str) -> None:
        editor = self.tabs.current()
        if not editor:
            editor = self.tabs.new_file()
        selection = editor.selected_text()
        if selection:
            editor.text.delete("sel.first", "sel.last")
        editor.insert_text(code)
        self.chat.set_busy(False)
        self.set_status("РљРѕРґ С–Р· С‡Р°С‚Сѓ РІСЃС‚Р°РІР»РµРЅРѕ РІ СЂРµРґР°РєС‚РѕСЂ. РџРµСЂРµРІС–СЂ С– Р·Р±РµСЂРµР¶Рё (Ctrl+S).")

    def send_to_agent(self, text: str, *, submit: bool = True) -> None:
        self.show_chat(True)
        if submit:
            self._set_agent_state("РїСЂР°С†СЋС”")
            self.chat._send(text)
        else:
            self.chat.input.delete("1.0", "end")
            self.chat.input.insert("1.0", text)
            self.chat.input.focus_set()

    def send_file_to_agent(self) -> None:
        editor = self.tabs.current()
        path = self.tabs.current_path()
        if not editor:
            return
        name = path.name if path else "РїРѕС‚РѕС‡РЅРёР№ С„Р°Р№Р»"
        relative = ws.relative_to_root(Path(self.settings.workspace), path) if path else name
        self.send_to_agent(
            f"РџСЂРѕС‡РёС‚Р°Р№ С„Р°Р№Р» {relative} С–РЅСЃС‚СЂСѓРјРµРЅС‚РѕРј read_file С– РїРѕСЏСЃРЅРё, С‰Рѕ РІС–РЅ СЂРѕР±РёС‚СЊ."
        )

    def explain_selection(self) -> None:
        editor = self.tabs.current()
        if not editor:
            return
        selection = editor.selected_text().strip()
        if not selection:
            self.set_status("Р’РёРґС–Р»Рё С‚РµРєСЃС‚, СЏРєРёР№ С‚СЂРµР±Р° РїРѕСЏСЃРЅРёС‚Рё.")
            return
        self.send_to_agent("РџРѕСЏСЃРЅРё С†РµР№ РєРѕРґ:\n\n```\n" + selection[:6000] + "\n```")

    def fix_selection(self) -> None:
        editor = self.tabs.current()
        path = self.tabs.current_path()
        if not editor or not path:
            return
        selection = editor.selected_text().strip()
        relative = ws.relative_to_root(Path(self.settings.workspace), path)
        prompt = (f"РЈ С„Р°Р№Р»С– {relative} РІРёРїСЂР°РІ РїСЂРѕР±Р»РµРјСѓ РІ С†СЊРѕРјСѓ С„СЂР°РіРјРµРЅС‚С–, Р·РјС–РЅРё РІРЅРµСЃРё "
                  f"С–РЅСЃС‚СЂСѓРјРµРЅС‚РѕРј edit_file:\n\n```\n{selection[:4000]}\n```")
        self.send_to_agent(prompt)

    def new_chat(self) -> None:
        self.new_chat_session()

    # в”Ђв”Ђ С‡Р°С‚Рё в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def has_project(self) -> bool:
        """Р§Рё РІРёР±СЂР°РЅРѕ СЂРѕР±РѕС‡Сѓ С‚РµРєСѓ РїСЂРѕС”РєС‚Сѓ.

        Р”РІР° РІРёРїР°РґРєРё, СЏРєС– СЂР°РЅС–С€Рµ Р·Р»РёРІР°Р»РёСЃСЏ РІ РѕРґРёРЅ:

        * ``workspace`` РїРѕСЂРѕР¶РЅСЏ Р°Р±Рѕ РЅРµ С–СЃРЅСѓС” вЂ” С‚РµРєРё РЅРµРјР°С”;
        * ``workspace`` РґРѕСЂС–РІРЅСЋС” РґРѕРјР°С€РЅС–Р№ С‚РµС†С– вЂ” С†Рµ СЃС‚Р°РЅ В«С‰Рµ РЅС–С‡РѕРіРѕ РЅРµ
          РІРёР±СЂР°РЅРѕВ», Р±Рѕ СЃР°РјРµ С‚СѓРґРё РїС–РґСЃС‚Р°РІР»СЏС”С‚СЊСЃСЏ С‚РµРєР° Р·Р° Р·Р°РјРѕРІС‡СѓРІР°РЅРЅСЏРј.

        Р”СЂСѓРіРёР№ РІРёРїР°РґРѕРє РЅРµ РјР°С” Р±Р»РѕРєСѓРІР°С‚Рё РЅР°Р·Р°РІР¶РґРё: СЏРєС‰Рѕ РєРѕСЂРёСЃС‚СѓРІР°С‡ **СЃРІС–РґРѕРјРѕ**
        РІРёР±СЂР°РІ РґРѕРјР°С€РЅСЋ С‚РµРєСѓ, РїСЂР°РїРѕСЂРµС†СЊ ``project_chosen`` С†Рµ РїР°Рј'СЏС‚Р°С”, С– С‡Р°С‚
        РїСЂР°С†СЋС”. Р†РЅР°РєС€Рµ РєРЅРѕРїРєР° В«Р’РёР±СЂР°С‚Рё РїР°РїРєСѓВ» РЅР° РІРёР±С–СЂ РґРѕРјР°С€РЅСЊРѕС— С‚РµРєРё
        РЅС–С‡РѕРіРѕ Р± РЅРµ Р·РјС–РЅСЋРІР°Р»Р° вЂ” РµРєСЂР°РЅ Р»РёС€Р°РІСЃСЏ Р± РЅР° РјС–СЃС†С–.
        """
        path = str(self.settings.workspace or "").strip()
        if not path:
            return False
        root = Path(path)
        if not root.is_dir():
            return False
        try:
            is_home = root.resolve() == Path.home().resolve()
        except OSError:
            is_home = False
        if is_home and not getattr(self.settings, "project_chosen", False):
            return False
        return True

    def _show_project_gate(self, *, reason: str = "") -> None:
        """РџРѕРєР°Р·Р°С‚Рё РµРєСЂР°РЅ РІРёР±РѕСЂСѓ РїСЂРѕС”РєС‚Сѓ Р·Р°РјС–СЃС‚СЊ С‡Р°С‚Сѓ."""
        self._close_project_gate()
        gate = project_gate.ProjectGate(
            self.conversation_host, self.theme,
            on_pick=self.open_folder_dialog,
            on_create=self.create_project_folder,
        )
        gate.set_hint(reason)
        # РџРѕРєР°Р·СѓС”РјРѕ, Р· С‡РёРј РєРѕСЂРёСЃС‚СѓРІР°С‡ РїСЂР°С†СЋРІР°С‚РёРјРµ, С– РґР°С”РјРѕ РїСЂРѕРґРѕРІР¶РёС‚Рё Р· С†С–С”СЋ
        # Р¶ С‚РµРєРѕСЋ: СЂР°РЅС–С€Рµ РµРєСЂР°РЅ Р»РёС€Рµ РїСЂРѕСЃРёРІ РІРёР±СЂР°С‚Рё РїР°РїРєСѓ, РЅР°РІС–С‚СЊ СЏРєС‰Рѕ РІРѕРЅР°
        # РІР¶Рµ РІРёР±СЂР°РЅР° вЂ” С– В«РЅРѕРІРёР№ С‡Р°С‚В» С‰РѕСЂР°Р·Сѓ РІРёРјР°РіР°РІ С€СѓРєР°С‚Рё С—С— Р·Р°РЅРѕРІРѕ.
        current = str(self.settings.workspace or "").strip()
        if current and Path(current).is_dir():
            gate.set_current(current, on_use=self._use_current_project)
        self.project_gate = gate
        # Р•РєСЂР°РЅ РїРѕРєР°Р·СѓС”РјРѕ РїРѕРІРµСЂС… РѕР±Р»Р°СЃС‚С– РґС–Р°Р»РѕРіСѓ: СЃР°РјР° РїРѕР±СѓРґРѕРІР° РІС–РґР¶РµС‚Р° С‰Рµ РЅРµ
        # РѕР·РЅР°С‡Р°С”, С‰Рѕ Р№РѕРіРѕ РІРёРґРЅРѕ, Р° Р±РµР· С†СЊРѕРіРѕ РєРѕСЂРёСЃС‚СѓРІР°С‡ Р±Р°С‡РёРІ РїРѕСЂРѕР¶РЅС–Р№ С‡Р°С‚
        # Р·Р°РјС–СЃС‚СЊ РїРѕСЏСЃРЅРµРЅРЅСЏ, С‡РѕРјСѓ РЅС–С‡РѕРіРѕ РЅРµ РїСЂР°С†СЋС”.
        try:
            gate.place(relx=0, rely=0, relwidth=1, relheight=1)
            gate.lift()
        except tk.TclError:
            LOG.debug("Р•РєСЂР°РЅ РІРёР±РѕСЂСѓ РїСЂРѕС”РєС‚Сѓ РЅРµ РІРґР°Р»РѕСЃСЏ РїРѕРєР°Р·Р°С‚Рё", exc_info=True)

    def _use_current_project(self) -> None:
        """РџСЂРѕРґРѕРІР¶РёС‚Рё Р· СѓР¶Рµ РІРёР±СЂР°РЅРѕСЋ С‚РµРєРѕСЋ (РєРЅРѕРїРєР° РЅР° РµРєСЂР°РЅС– РІРёР±РѕСЂСѓ)."""
        current = str(self.settings.workspace or "").strip()
        if not current or not Path(current).is_dir():
            self._show_project_gate(reason="Р¦СЏ С‚РµРєР° Р±С–Р»СЊС€Рµ РЅРµ С–СЃРЅСѓС” вЂ” РІРёР±РµСЂРё С–РЅС€Сѓ.")
            return
        # РЎРІС–РґРѕРјРµ РїС–РґС‚РІРµСЂРґР¶РµРЅРЅСЏ РІРёР±РѕСЂСѓ: Р±РµР· РїСЂР°РїРѕСЂС†СЏ РґРѕРјР°С€РЅСЏ С‚РµРєР° РІРІР°Р¶Р°Р»Р°СЃСЊ
        # Р±Рё В«РЅС–С‡РѕРіРѕ РЅРµ РІРёР±СЂР°РЅРѕВ» С– РµРєСЂР°РЅ РїРѕРІРµСЂС‚Р°РІСЃСЏ Р± Р·РЅРѕРІСѓ.
        self.settings.remember_workspace(current)
        safe.call_quiet(self.settings.save)
        self._close_project_gate()
        self.new_chat_session()
        self.set_status(f"РџСЂР°С†СЋСЋ Р· С‚РµРєРѕСЋ: {current}")

    def _close_project_gate(self) -> None:
        gate = getattr(self, "project_gate", None)
        self.project_gate = None
        if gate is None:
            return
        try:
            gate.destroy()
        except tk.TclError:
            pass

    def _after_chats_cleared(self, removed: int) -> None:
        """РЈСЃС– С‡Р°С‚Рё РІРёРґР°Р»РµРЅРѕ: РѕС‡РёСЃС‚РёС‚Рё СЃС‚СЂС–С‡РєСѓ, Р·Р°РіРѕР»РѕРІРѕРє С– С‡РµСЂРіСѓ."""
        try:
            self.chat.reset()
        except (tk.TclError, AttributeError):
            LOG.debug("РЎС‚СЂС–С‡РєСѓ РЅРµ РІРґР°Р»РѕСЃСЊ РѕС‡РёСЃС‚РёС‚Рё", exc_info=True)
        # РљРѕРЅС‚РµРєСЃС‚ Р°РіРµРЅС‚Р° РЅР°Р»РµР¶Р°РІ РІРёРґР°Р»РµРЅРёРј С‡Р°С‚Р°Рј вЂ” РїРѕС‡РёРЅР°С”РјРѕ Р· С‡РёСЃС‚РѕРіРѕ.
        try:
            self.agent.session.reset()
        except AttributeError:
            LOG.debug("РЎРµСЃС–СЏ Р°РіРµРЅС‚Р° С‰Рµ РЅРµ СЃС‚РІРѕСЂРµРЅР°", exc_info=True)
        # Р§РµСЂРіР° РЅР°Р»РµР¶РёС‚СЊ С‡Р°С‚Р°Рј: СЏРєС‰Рѕ С‡Р°С‚С–РІ РЅРµРјР°С”, РІРёРєРѕРЅСѓРІР°С‚Рё РЅС–С‡РѕРіРѕ.
        queue_dropped = len(self.task_queue.tasks)
        if queue_dropped:
            self.task_queue.clear()
            self._update_queue_badge()
        self._sync_chat_title()
        try:
            self.chat_list.set_active("")
            self.chat_list.refresh()
        except (tk.TclError, AttributeError):
            pass
        self.nav_refresh_history()
        message = f"Р’РёРґР°Р»РµРЅРѕ РІСЃС– С‡Р°С‚Рё: {removed}."
        if queue_dropped:
            message += f" Р§РµСЂРіСѓ РѕС‡РёС‰РµРЅРѕ: {queue_dropped} Р·Р°РґР°С‡."
        self.set_status(message)

    def create_project_folder(self) -> None:
        """РЎС‚РІРѕСЂРёС‚Рё РЅРѕРІСѓ С‚РµРєСѓ РїСЂРѕС”РєС‚Сѓ Р№ РѕРґСЂР°Р·Сѓ С—С— РІС–РґРєСЂРёС‚Рё."""
        from tkinter import simpledialog

        name = simpledialog.askstring(
            "РќРѕРІРёР№ РїСЂРѕС”РєС‚",
            "РќР°Р·РІР° С‚РµРєРё РїСЂРѕС”РєС‚Сѓ (Р±СѓРґРµ СЃС‚РІРѕСЂРµРЅР° РїРѕСЂСѓС‡ С–Р· РїРѕС‚РѕС‡РЅРѕСЋ):",
            parent=self)
        if not name or not name.strip():
            return
        clean = re.sub(r'[<>:"/\\|?*]', "_", name.strip()) or "project"
        base = Path(self.settings.workspace)
        if not base.is_dir() or not self.has_project():
            base = Path.home() / "Projects"
        target = base / clean
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("РќРµ РІРґР°Р»РѕСЃСЊ СЃС‚РІРѕСЂРёС‚Рё",
                                 f"{target}\n\n{exc}", parent=self)
            return
        self.set_workspace(target)

    def new_chat_session(self) -> bool:
        """РџС–РґРіРѕС‚СѓРІР°С‚Рё РЅРѕРІРёР№ С‡Р°С‚. Р‘РµР· РІРёР±СЂР°РЅРѕРіРѕ РїСЂРѕС”РєС‚Сѓ вЂ” СЃРїРµСЂС€Сѓ РІРёР±С–СЂ С‚РµРєРё.

        Р§Р°С‚ РќР• Р·Р°РїРёСЃСѓС”С‚СЊСЃСЏ Сѓ СЃС…РѕРІРёС‰Рµ РѕРґСЂР°Р·Сѓ: Р·Р°РїРёСЃ Сѓ СЃРїРёСЃРєСѓ Р·'СЏРІР»СЏС”С‚СЊСЃСЏ Р·
        РїРµСЂС€РёРј РїРѕРІС–РґРѕРјР»РµРЅРЅСЏРј (РґРёРІ. ``_remember_message``). Р Р°РЅС–С€Рµ РєРѕР¶РЅРµ
        РЅР°С‚РёСЃРєР°РЅРЅСЏ В«пј‹ РќРѕРІРёР№ С‡Р°С‚В» СЃС‚РІРѕСЂСЋРІР°Р»Рѕ РїРѕСЂРѕР¶РЅС–Р№ Р·Р°РїРёСЃ, С– СЃРїРёСЃРѕРє
        Р·Р°РїРѕРІРЅСЋРІР°РІСЃСЏ СЂСЏРґРєР°РјРё В«Р‘РµР· РЅР°Р·РІРёВ» Р· РЅСѓР»РµРј РїРѕРІС–РґРѕРјР»РµРЅСЊ вЂ” СЃР°РјРµ С‚Рµ, С‰Рѕ
        РІРёРґРЅРѕ РЅР° СЃРєСЂС–РЅС€РѕС‚С– РєРѕСЂРёСЃС‚СѓРІР°С‡Р°.

        РџРѕРІРµСЂС‚Р°С” ``True``, СЏРєС‰Рѕ СЃРµСЃС–СЋ РїС–РґРіРѕС‚РѕРІР»РµРЅРѕ. РљРЅРѕРїРєР° В«РќРѕРІРёР№ С‡Р°С‚В»,
        РјРµРЅСЋ Р№ СЃС‚Р°СЂС‚РѕРІРёР№ РµРєСЂР°РЅ РІРµРґСѓС‚СЊ СЃСЋРґРё, С‚РѕР¶ РїРµСЂРµРІС–СЂРєР° РѕРґРЅР° РЅР° РІСЃС– РІС…РѕРґРё.
        """
        if not self.has_project():
            self._show_project_gate(
                reason="Р§Р°С‚ РІС–РґРєСЂРёС”С‚СЊСЃСЏ, С‰РѕР№РЅРѕ Р±СѓРґРµ РІРёР±СЂР°РЅРѕ С‚РµРєСѓ РїСЂРѕС”РєС‚Сѓ.")
            self.set_status("РЎРїРµСЂС€Сѓ РІРёР±РµСЂРё РїР°РїРєСѓ РїСЂРѕС”РєС‚Сѓ вЂ” Р±РµР· РЅРµС— Р°РіРµРЅС‚Сѓ РЅС–РґРµ РїСЂР°С†СЋРІР°С‚Рё.")
            return False
        # РђРіРµРЅС‚ Р·Р°СЂР°Р· РїСЂР°С†СЋС” вЂ” РїРµСЂРµРјРёРєР°РЅРЅСЏ Р·РЅРёС‰РёР»Рѕ Р± РїРѕС‚РѕС‡РЅРёР№ С…С–Рґ: СЃС‚СЂС–С‡РєР°
        # РѕС‡РёС‰Р°С”С‚СЊСЃСЏ, Р° РїРѕС‚С–Рє Р°РіРµРЅС‚Р° РїСЂРѕРґРѕРІР¶СѓС” РґРѕРїРёСЃСѓРІР°С‚Рё Сѓ Р’Р–Р• РћР§РР©Р•РќРЈ
        # СЃРµСЃС–СЋ, С– СЂРµР·СѓР»СЊС‚Р°С‚ РїРѕРїРµСЂРµРґРЅСЊРѕС— Р·Р°РґР°С‡С– Р·РЅРёРєР°С” (Р° С‡Р°СЃС‚РєРѕРІРѕ С‰Рµ Р№
        # Р·Р±РµСЂС–РіР°С”С‚СЊСЃСЏ РїС–Рґ РЅРѕРІРёРј chat_id). РўРѕРјСѓ СЃРїРµСЂС€Сѓ Р·СѓРїРёРЅСЏС”РјРѕ.
        if self.agent.busy:
            self.set_status("РђРіРµРЅС‚ С‰Рµ РїСЂР°С†СЋС” вЂ” РґРѕС‡РµРєР°Р№СЃСЏ Р·Р°РІРµСЂС€РµРЅРЅСЏ Р°Р±Рѕ Р·СѓРїРёРЅРё Р№РѕРіРѕ (в– ), "
                            "РїРѕС‚С–Рј СЃС‚РІРѕСЂРё РЅРѕРІРёР№ С‡Р°С‚.")
            return False
        self._close_project_gate()
        # Р—РЅС–РјР°С”РјРѕ Р· Р°РєС‚РёРІРЅРѕСЃС‚С– РїРѕРїРµСЂРµРґРЅС–Р№ С‡Р°С‚, Р°Р»Рµ РЅРµ С‡С–РїР°С”РјРѕ Р№РѕРіРѕ Р·Р°РїРёСЃ:
        # СЂРѕР·РјРѕРІР° Р»РёС€Р°С”С‚СЊСЃСЏ РІ СЃРїРёСЃРєСѓ, РґРѕРєРё РІ РЅС–Р№ С” РїРѕРІС–РґРѕРјР»РµРЅРЅСЏ.
        #
        # РљРѕРЅС‚РµРєСЃС‚ Р°РіРµРЅС‚Р° Р·Р±РµСЂС–РіР°С”РјРѕ РџР•Р Р•Р” РѕС‡РёС‰РµРЅРЅСЏРј: С–РЅР°РєС€Рµ РјРѕРґРµР»СЊ
        # РІС‚СЂР°С‡Р°Р»Р° РІСЃРµ, С‰Рѕ Р·РЅР°Р»Р° РїСЂРѕ РїРѕРїРµСЂРµРґРЅСЋ СЂРѕР·РјРѕРІСѓ, С– РїРѕРІРµСЂРЅСѓС‚РёСЃСЊ РґРѕ
        # РЅРµС— Р±СѓР»Рѕ РЅРµРјРѕР¶Р»РёРІРѕ вЂ” СЃР°РјРµ С†Рµ РІС–РґС‡СѓРІР°Р»РѕСЃСЊ СЏРє В«С‡Р°С‚ Р·РЅРёРєВ».
        previous = str(getattr(self.chat_store, "active_id", "") or "")
        if previous:
            self._save_chat_context(previous)
        self._pending_chat = True
        self.chat_store.set_active("")
        self._hide_welcome()
        self.chat.reset()
        # РќРѕРІРёР№ С‡Р°С‚ РїРѕС‡РёРЅР°С”С‚СЊСЃСЏ Р· Р§РРЎРўРћР“Рћ РєРѕРЅС‚РµРєСЃС‚Сѓ вЂ” Р¶РѕРґРЅРёС… СЃР»С–РґС–РІ
        # РїРѕРїРµСЂРµРґРЅСЊРѕРіРѕ РґС–Р°Р»РѕРіСѓ РІ СЃРµСЃС–С— Р°РіРµРЅС‚Р°.
        try:
            self.agent.session.reset()
        except AttributeError:
            LOG.debug("РЎРµСЃС–СЏ Р°РіРµРЅС‚Р° С‰Рµ РЅРµ СЃС‚РІРѕСЂРµРЅР°", exc_info=True)
        self.chat_list.refresh()
        self._sync_chat_title()
        self._sync_chat_model()
        self._sync_chat_queue()
        self._focus_composer()
        self.set_status("РќРѕРІРёР№ С‡Р°С‚: Р·Р°РїРёС€Рё РїРµСЂС€Рµ Р·Р°РІРґР°РЅРЅСЏ вЂ” С– СЃРµСЃС–СЏ Р·'СЏРІРёС‚СЊСЃСЏ Сѓ СЃРїРёСЃРєСѓ.")
        return True

    def _pending_chat_active(self) -> bool:
        """Р§Рё Р·Р°СЂР°Р· РІС–РґРєСЂРёС‚Рѕ В«С‡РµСЂРЅРµС‚РєСѓВ» С‡Р°С‚Сѓ, С‰Рµ РЅРµ Р·Р°РїРёСЃР°РЅСѓ Сѓ СЃС…РѕРІРёС‰Рµ."""
        return bool(getattr(self, "_pending_chat", False)) and not self.chat_store.active()

    def _ensure_pending_chat(self) -> None:
        """РЎС‚РІРѕСЂРёС‚Рё Р·Р°РїРёСЃ С‡Р°С‚Сѓ РїСЂРё РїРµСЂС€РѕРјСѓ РїРѕРІС–РґРѕРјР»РµРЅРЅС– С‡РµСЂРЅРµС‚РєРё.

        Р’РёРєР»РёРєР°С”С‚СЊСЃСЏ Р»РёС€Рµ С‚РѕРґС–, РєРѕР»Рё РєРѕСЂРёСЃС‚СѓРІР°С‡ СЃРїСЂР°РІРґС– С‰РѕСЃСЊ РЅР°РґС–СЃР»Р°РІ:
        С‚Р°Рє Сѓ СЃРїРёСЃРєСѓ РЅРµ Р±СѓРІР°С” РїРѕСЂРѕР¶РЅС–С… СЃРµСЃС–Р№, С– РєРѕР¶РµРЅ Р·Р°РїРёСЃ РјР°С” РІР»Р°СЃРЅРёРєР°
        (``chat_id``), РґРѕ СЏРєРѕРіРѕ РїСЂРёРІ'СЏР·СѓСЋС‚СЊСЃСЏ Р·Р°РґР°С‡С– С‡РµСЂРіРё.
        """
        if self.chat_store.active():
            self._pending_chat = False
            return
        if not self.has_project():
            return
        chat = self.chat_store.create(workspace=str(self.settings.workspace),
                                      model=self.settings.llm.model)
        self._pending_chat = False
        self.chat_list.refresh()
        self._sync_chat_title()
        self._sync_chat_model()
        LOG.info("РЎС‚РІРѕСЂРµРЅРѕ С‡Р°С‚ %s РЅР° РїРµСЂС€Рµ РїРѕРІС–РґРѕРјР»РµРЅРЅСЏ", chat.id)

    def _focus_composer(self) -> None:
        """РџРѕСЃС‚Р°РІРёС‚Рё РєСѓСЂСЃРѕСЂ Сѓ РїРѕР»Рµ РІРІРµРґРµРЅРЅСЏ (С‰РѕР± РѕРґСЂР°Р·Сѓ РјРѕР¶РЅР° Р±СѓР»Рѕ РїРёСЃР°С‚Рё)."""
        try:
            self.chat.input_box.focus_set()
        except (tk.TclError, AttributeError):
            pass

    def open_chat(self, chat_id: str) -> None:
        """Р’С–РґРєСЂРёС‚Рё Р·Р±РµСЂРµР¶РµРЅРёР№ С‡Р°С‚: С–СЃС‚РѕСЂС–СЏ Р№ РљРћРќРўР•РљРЎРў Р°РіРµРЅС‚Р° РІС–РґРЅРѕРІР»СЋСЋС‚СЊСЃСЏ.

        Р‘РµР· РІРёР±СЂР°РЅРѕС— С‚РµРєРё РїСЂРѕС”РєС‚Сѓ С‡Р°С‚ РЅРµ РІС–РґРєСЂРёРІР°С”С‚СЊСЃСЏ: С–РЅР°РєС€Рµ Р°РіРµРЅС‚ РїРѕС‡Р°РІ
        Р±Рё РїСЂР°С†СЋРІР°С‚Рё Р· С„Р°Р№Р»Р°РјРё РІ РґРѕРјР°С€РЅС–Р№ С‚РµС†С– РєРѕСЂРёСЃС‚СѓРІР°С‡Р°.

        Р“РѕР»РѕРІРЅРµ С‚СѓС‚ вЂ” :meth:`_load_chat_context`. Р Р°РЅС–С€Рµ РІС–РґРєСЂРёС‚С‚СЏ С‡Р°С‚Сѓ
        РјР°Р»СЋРІР°Р»Рѕ Р»РёС€Рµ СЃС‚СЂС–С‡РєСѓ, Р° СЃРµСЃС–СЏ Р°РіРµРЅС‚Р° Р»РёС€Р°Р»Р°СЃСЊ РІС–Рґ РїРѕРїРµСЂРµРґРЅСЊРѕС—
        СЂРѕР·РјРѕРІРё: РјРѕРґРµР»СЊ Р°Р±Рѕ РЅРµ Р±Р°С‡РёР»Р° РІР»Р°СЃРЅРѕС— С–СЃС‚РѕСЂС–С— (РїСЂРѕРґРѕРІР¶РёС‚Рё СЂРѕР±РѕС‚Сѓ
        РЅРµРјРѕР¶Р»РёРІРѕ), Р°Р±Рѕ Р±Р°С‡РёР»Р° Р§РЈР–РЈ. РўРµРїРµСЂ РєРѕРЅС‚РµРєСЃС‚ РїРµСЂРµРјРёРєР°С”С‚СЊСЃСЏ СЂР°Р·РѕРј С–Р·
        С‡Р°С‚РѕРј, Р° РїРѕС‚РѕС‡РЅРёР№ Р·Р±РµСЂС–РіР°С”С‚СЊСЃСЏ РїРµСЂРµРґ РїРµСЂРµРјРёРєР°РЅРЅСЏРј.
        """
        if not self.has_project():
            self._show_project_gate(
                reason="Р’РёР±РµСЂРё С‚РµРєСѓ РїСЂРѕС”РєС‚Сѓ вЂ” С– С†РµР№ С‡Р°С‚ РІС–РґРєСЂРёС”С‚СЊСЃСЏ.")
            self.set_status("РЎРїРµСЂС€Сѓ РІРёР±РµСЂРё РїР°РїРєСѓ РїСЂРѕС”РєС‚Сѓ.")
            return
        chat = self.chat_store.get(chat_id)
        if chat is None:
            return
        if self.agent.busy:
            self.set_status("РђРіРµРЅС‚ С‰Рµ РїСЂР°С†СЋС” вЂ” РґРѕС‡РµРєР°Р№СЃСЏ Р·Р°РІРµСЂС€РµРЅРЅСЏ Р°Р±Рѕ Р·СѓРїРёРЅРё Р№РѕРіРѕ (в– ).")
            return
        self._close_project_gate()
        previous = str(getattr(self.chat_store, "active_id", "") or "")
        if previous and previous != chat_id:
            self._save_chat_context(previous)
        self._pending_chat = False
        self.chat_store.set_active(chat_id)
        self._hide_welcome()          # РѕРІРµСЂР»РµР№ СЃС‚Р°СЂС‚РѕРІРѕРіРѕ РµРєСЂР°РЅР° С…РѕРІР°С”РјРѕ
        self.chat.show_history(chat.messages)
        self._load_chat_context(chat_id)
        self.chat_list.refresh()
        self._sync_chat_title()
        self._sync_chat_model()
        self._sync_chat_queue()
        self.set_status(f"Р’С–РґРєСЂРёС‚Рѕ С‡Р°С‚: {chat.title or 'Р‘РµР· РЅР°Р·РІРё'}")

    # в”Ђв”Ђ РєРѕРЅС‚РµРєСЃС‚ Р°РіРµРЅС‚Р°: РѕРґРёРЅ РЅР° С‡Р°С‚ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _save_chat_context(self, chat_id: str) -> bool:
        """Р—Р±РµСЂРµРіС‚Рё РєРѕРЅС‚РµРєСЃС‚ Р°РіРµРЅС‚Р° РІ Р·Р°РїРёСЃ С‡Р°С‚Сѓ (РїРµСЂРµРґ РїРµСЂРµРјРёРєР°РЅРЅСЏРј/РІРёС…РѕРґРѕРј)."""
        if not chat_id:
            return False
        session = getattr(self.agent, "session", None)
        if session is None:
            return False
        try:
            self.chat_store.store_context(chat_id, session.snapshot())
            # РЎС‚Р°РЅ СЂРѕР·СѓРјС–РЅРЅСЏ Р·Р°РІРґР°РЅРЅСЏ вЂ” РѕРєСЂРµРјРѕ: РІС–РЅ РїРµСЂРµР¶РёРІР°С” РїРµСЂРµР·Р°РїСѓСЃРє С–
            # СЃР°РјРµ РІС–РЅ РЅРµ РґР°С” Р°РіРµРЅС‚РѕРІС– РїРµСЂРµРїРёС‚СѓРІР°С‚Рё РІР¶Рµ РїРѕСЏСЃРЅРµРЅРµ.
            state = getattr(self.agent, "state", None)
            if state is not None:
                self.chat_store.store_state(chat_id, state.to_dict())
        except Exception:  # noqa: BLE001 - РїРµСЂРµРјРёРєР°РЅРЅСЏ РЅРµ РјР°С” Р»Р°РјР°С‚Рё РєРѕРЅС‚РµРєСЃС‚
            LOG.warning("РќРµ РІРґР°Р»РѕСЃСЊ Р·Р±РµСЂРµРіС‚Рё РєРѕРЅС‚РµРєСЃС‚ С‡Р°С‚Сѓ %s", chat_id,
                        exc_info=True)
            return False
        return True

    def _load_chat_context(self, chat_id: str) -> int:
        """Р’С–РґРЅРѕРІРёС‚Рё РєРѕРЅС‚РµРєСЃС‚ Р°РіРµРЅС‚Р° Р· Р·Р°РїРёСЃСѓ С‡Р°С‚Сѓ.

        РџРѕСЂСЏРґРѕРє: Р·Р±РµСЂРµР¶РµРЅРёР№ РєРѕРЅС‚РµРєСЃС‚ Р°РіРµРЅС‚Р° в†’ РїРѕРІС–РґРѕРјР»РµРЅРЅСЏ С‡Р°С‚Сѓ. Р”СЂСѓРіРµ
        РґР¶РµСЂРµР»Рѕ РїРѕС‚СЂС–Р±РЅРµ РґР»СЏ СЃС‚Р°СЂРёС… С‡Р°С‚С–РІ (РґРѕ РїРѕСЏРІРё РїРѕР»СЏ ``context``) С– РґР»СЏ
        СЂРѕР·РјРѕРІ, РґРµ РїРѕРІС–РґРѕРјР»РµРЅРЅСЏ РґРѕРґР°РІР°Р»РёСЃСЊ Р±РµР· С…РѕРґСѓ Р°РіРµРЅС‚Р°: Р±РµР· РЅСЊРѕРіРѕ Р°РіРµРЅС‚
        РІС–РґРєСЂРёРІР°РІ С‡Р°С‚ Р· С–СЃС‚РѕСЂС–С”СЋ РЅР° РµРєСЂР°РЅС–, Р°Р»Рµ В«РЅРµ РїР°Рј'СЏС‚Р°РІВ» РЅС–С‡РѕРіРѕ.
        РџРѕСЂРѕР¶РЅС–Р№ СЂРµР·СѓР»СЊС‚Р°С‚ вЂ” РЅРѕСЂРјР°Р»СЊРЅРёР№ СЃС‚Р°РЅ РЅРѕРІРѕРіРѕ С‡Р°С‚Сѓ: СЃРµСЃС–СЏ РѕС‡РёС‰СѓС”С‚СЊСЃСЏ.
        """
        session = getattr(self.agent, "session", None)
        if session is None:
            return 0
        try:
            messages = self.chat_store.load_context(chat_id)
            if not messages:
                messages = self._context_from_messages(chat_id)
            restored = session.restore(messages)
        except Exception:  # noqa: BLE001 - СЃС‚Р°СЂС‚ С‡Р°С‚Сѓ РЅРµ РјР°С” РїР°РґР°С‚Рё
            LOG.warning("РќРµ РІРґР°Р»РѕСЃСЊ РІС–РґРЅРѕРІРёС‚Рё РєРѕРЅС‚РµРєСЃС‚ С‡Р°С‚Сѓ %s", chat_id,
                        exc_info=True)
            try:
                session.reset()
            except Exception:  # noqa: BLE001
                pass
            return 0
        if restored:
            LOG.info("Р’С–РґРЅРѕРІР»РµРЅРѕ РєРѕРЅС‚РµРєСЃС‚ С‡Р°С‚Сѓ %s: %s РїРѕРІС–РґРѕРјР»РµРЅСЊ", chat_id, restored)
        # РЎС‚Р°РЅ СЂРѕР·СѓРјС–РЅРЅСЏ Р·Р°РІРґР°РЅРЅСЏ: РјРµС‚Р°, РѕР±РјРµР¶РµРЅРЅСЏ, РѕР±'С”РєС‚Рё Р·РіР°РґРєРё. Р‘РµР·
        # РЅСЊРѕРіРѕ Р°РіРµРЅС‚ Сѓ РІС–РґРЅРѕРІР»РµРЅРѕРјСѓ С‡Р°С‚С– РЅРµ Р·РЅР°РІ Р±Рё, РЅР°Рґ С‡РёРј РїСЂР°С†СЋС”, С–
        # РїРµСЂРµРїРёС‚СѓРІР°РІ Р±Рё С‚Рµ, С‰Рѕ Р»СЋРґРёРЅР° РІР¶Рµ РїРѕСЏСЃРЅРёР»Р°.
        try:
            self.agent.state = conversation.ConversationState.from_dict(
                self.chat_store.load_state(chat_id))
        except Exception:  # noqa: BLE001
            LOG.debug("РЎС‚Р°РЅ С‡Р°С‚Сѓ РЅРµ РІС–РґРЅРѕРІР»РµРЅРѕ", exc_info=True)
            self.agent.state = conversation.ConversationState()
        return restored

    def _context_from_messages(self, chat_id: str) -> list[dict]:
        """РџРѕР±СѓРґСѓРІР°С‚Рё РєРѕРЅС‚РµРєСЃС‚ Р°РіРµРЅС‚Р° Р· РІРёРґРёРјРёС… РїРѕРІС–РґРѕРјР»РµРЅСЊ С‡Р°С‚Сѓ.

        Р’РёРєРѕСЂРёСЃС‚РѕРІСѓС”С‚СЊСЃСЏ СЏРє Р·Р°РїР°СЃРЅРёР№ С€Р»СЏС…: РїС–СЃР»СЏ РїРµСЂРµР·Р°РїСѓСЃРєСѓ СЃС‚Р°СЂРѕС— РІРµСЂСЃС–С—
        РїСЂРѕРіСЂР°РјРё РєРѕРЅС‚РµРєСЃС‚Сѓ Р°РіРµРЅС‚Р° С‰Рµ РЅРµРјР°С”, Р° С–СЃС‚РѕСЂС–СЏ СЂРѕР·РјРѕРІРё РІР¶Рµ С”.
        """
        chat = self.chat_store.get(chat_id)
        if chat is None:
            return []
        rows: list[dict] = []
        for message in chat.messages:
            role = getattr(message, "role", "")
            text = (getattr(message, "text", "") or "").strip()
            if not text:
                continue
            if role == "user":
                rows.append({"role": "user", "content": text})
            elif role == "assistant":
                rows.append({"role": "assistant", "content": text})
            # ``system``/``tool`` Р»РёС€Р°С”РјРѕ РѕСЃС‚РѕСЂРѕРЅСЊ: С†Рµ СЃР»СѓР¶Р±РѕРІС– РїРѕР·РЅР°С‡РєРё
            # СЃС‚СЂС–С‡РєРё, Р° РЅРµ РїРѕРІС–РґРѕРјР»РµРЅРЅСЏ РґС–Р°Р»РѕРіСѓ, С– СЃРµСЂРІРµСЂ С—С… РЅРµ РїСЂРёР№РјРµ
            # Р±РµР· РІС–РґРїРѕРІС–РґРЅРѕРіРѕ tool_call.
        # РћСЃС‚Р°РЅРЅС– 40 СЂРµРїР»С–Рє РґРѕСЃС‚Р°С‚РЅСЊРѕ, С‰РѕР± РїСЂРѕРґРѕРІР¶РёС‚Рё СЂРѕР·РјРѕРІСѓ: СЂРµС€С‚Сѓ
        # РѕРґРЅР°РєРѕРІРѕ РїС–РґСЂС–Р¶Рµ ``AgentSession.trim`` РїС–Рґ РІС–РєРЅРѕ РјРѕРґРµР»С–.
        return rows[-40:]

    def _sync_chat_queue(self) -> None:
        """РџРѕРєР°Р·Р°С‚Рё РІ РїР°РЅРµР»С– С‡Р°С‚Сѓ С‡РµСЂРіСѓ РЎРђРњР• С†СЊРѕРіРѕ С‡Р°С‚Сѓ.

        Р Р°РЅС–С€Рµ Р±РµР№РґР¶ РїРѕРєР°Р·СѓРІР°РІ Р·Р°РґР°С‡С– РІСЃС–С… С‡Р°С‚С–РІ РѕРґСЂР°Р·Сѓ: Сѓ РЅРѕРІРѕРјСѓ С‡Р°С‚С–
        РІРёСЃС–Р»Рѕ В«Р§РµСЂРіР°: 3В» РІС–Рґ РїРѕРїРµСЂРµРґРЅСЊРѕРіРѕ, С– РєРѕСЂРёСЃС‚СѓРІР°С‡ Р±Р°С‡РёРІ С‡СѓР¶Сѓ СЂРѕР±РѕС‚Сѓ.
        """
        chat_id = self._active_chat_id()
        try:
            tasks = [task for task in self.task_queue.tasks
                     if not chat_id or not getattr(task, "chat_id", "")
                     or task.chat_id == chat_id]
            self.chat.set_queue_count(len(tasks), tasks)
        except (tk.TclError, AttributeError):
            LOG.debug("РќРµ РІРґР°Р»РѕСЃСЊ РѕРЅРѕРІРёС‚Рё Р±РµР№РґР¶ С‡РµСЂРіРё", exc_info=True)

    def _reconcile_server_url(self) -> None:
        """РЈР·РіРѕРґРёС‚Рё Р°РґСЂРµСЃСѓ СЃРµСЂРІРµСЂР° Р· С‚РёРј, С‰Рѕ РЎРџР РђР’Р”Р† СЃР»СѓС…Р°С”.

        РќР°РІС–С‰Рѕ. РџРѕСЂС‚ СЂСѓС€С–СЏ В«РїР»Р°РІР°С”В»: СЏРєС‰Рѕ 8080 Р·Р°Р№РјР°С” С–РЅС€Р° РїСЂРѕРіСЂР°РјР° (Steam
        РЅР° С†С–Р№ РјР°С€РёРЅС–), llama-server Р±РµСЂРµ 8081 вЂ” Р° РІ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏС… Р»РёС€Р°С”С‚СЊСЃСЏ
        8080. РўРѕРґС– РєРѕР¶РµРЅ Р·Р°РїРёС‚ РґС–СЃС‚Р°С” HTTP 404, С– РІ С–РЅС‚РµСЂС„РµР№СЃС– С†Рµ РІРёРіР»СЏРґР°С”
        СЏРє В«РјРѕРґРµР»СЊ РЅРµ РїСЂР°С†СЋС”В», С…РѕС‡ РІРѕРЅР° РїСЂР°С†СЋС”.

        Р¤СѓРЅРєС†С–СЏ РќР• РІРіР°РґСѓС”: СЏРєС‰Рѕ РЅС–С‡РѕРіРѕ РЅРµ РІС–РґРїРѕРІС–РґР°С”, РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏ РЅРµ
        Р·РјС–РЅСЋСЋС‚СЊСЃСЏ Р№ РІРµР»РёРєРёР№ СЃС‚Р°С‚СѓСЃ РїРѕРєР°Р·СѓС” РѕС„Р»Р°Р№РЅ. Р—РјС–РЅР° РІС–РґР±СѓРІР°С”С‚СЊСЃСЏ Р»РёС€Рµ
        С‚РѕРґС–, РєРѕР»Рё СЂРѕР±РѕС‡РёР№ СЃРµСЂРІРµСЂ СЃРїСЂР°РІРґС– Р·РЅР°Р№РґРµРЅРѕ.

        Р’РђР–Р›РР’Рћ РїСЂРѕ С€РІРёРґРєС–СЃС‚СЊ. РџРµСЂРµРІС–СЂРєР° ``server_responds`` РЅР° РЅРµРїС–РґРЅСЏС‚РѕРјСѓ
        СЃРµСЂРІРµСЂС– РєРѕС€С‚СѓС” РґРѕ 4.6 СЃ (С‚СЂРё HTTP-СЃРїСЂРѕР±Рё, РєРѕР¶РЅР° РІРїРёСЂР°С”С‚СЊСЃСЏ РІ
        С‚Р°Р№РјР°СѓС‚ вЂ” РЅР° С†С–Р№ РјР°С€РёРЅС– connect РґРѕ Р·Р°РєСЂРёС‚РѕРіРѕ РїРѕСЂС‚Сѓ С‡РµРєР°С” РІРµСЃСЊ
        С‚Р°Р№РјР°СѓС‚). Р Р°РЅС–С€Рµ С†Рµ РІРёРєРѕРЅСѓРІР°Р»РѕСЃСЊ Сѓ Р“РћР›РћР’РќРћРњРЈ РїРѕС‚РѕС†С– РїС–Рґ С‡Р°СЃ
        РїРµСЂС€РѕРіРѕ РєР°РґСЂСѓ, С– СЃС‚Р°СЂС‚ Р·Р°Р№РјР°РІ 6.3 СЃ. РўРµРїРµСЂ СЃР°РјР° РїРµСЂРµРІС–СЂРєР° Р№РґРµ Сѓ
        С„РѕРЅРѕРІРёР№ РїРѕС‚С–Рє, Р° СЂРµР·СѓР»СЊС‚Р°С‚ Р·Р°СЃС‚РѕСЃРѕРІСѓС”С‚СЊСЃСЏ С‡РµСЂРµР· ``_ui_call`` вЂ”
        С–РЅС‚РµСЂС„РµР№СЃ РјР°Р»СЋС”С‚СЊСЃСЏ РѕРґСЂР°Р·Сѓ, Р°РґСЂРµСЃР° СѓР·РіРѕРґР¶СѓС”С‚СЊСЃСЏ Р·Р° СЃРµРєСѓРЅРґСѓ-РґРІС–.
        """
        configured = str(self.settings.llm.base_url or "")
        # Р’Р±СѓРґРѕРІР°РЅРёР№ СЂСѓС€С–Р№: РїРѕСЂС‚Сѓ РЅРµРјР°С” Р№ В«РїР»Р°РІР°С‚РёВ» РЅС–С‡РѕРјСѓ. Р Р°РЅС–С€Рµ С‚СѓС‚
        # РІРёРєРѕРЅСѓРІР°РІСЃСЏ РїРѕС€СѓРє РїРѕ 8 РїРѕСЂС‚Р°С…, С– РґР»СЏ ``native://blackchpok``
        # С€СѓРєР°С‚Рё Р±СѓР»Рѕ РЅС–С‡РѕРіРѕ вЂ” Р»РёС€Рµ РіР°СЏРЅРѕ С‡Р°СЃ.
        if runtime.embedded_url(configured):
            return
        low = configured.lower()
        if configured and not any(marker in low for marker in
                                  ("127.0.0.1", "localhost", "0.0.0.0")):
            return   # С…РјР°СЂР°/Р·РѕРІРЅС–С€РЅС–Р№ СЃРµСЂРІРµСЂ: РїРѕСЂС‚ РЅРµ В«РїР»Р°РІР°С”В»
        if getattr(self, "_reconcile_running", False):
            return
        self._reconcile_running = True
        key = str(self.settings.llm.api_key or "")

        def work() -> None:
            found = ""
            try:
                if configured and runtime.server_responds(configured,
                                                          api_key=key):
                    return
                found = runtime.discover_server_url(configured, api_key=key)
            except Exception:  # noqa: BLE001 - СѓР·РіРѕРґР¶РµРЅРЅСЏ РЅРµ РјР°С” Р»Р°РјР°С‚Рё СЃС‚Р°СЂС‚
                LOG.debug("РЈР·РіРѕРґР¶РµРЅРЅСЏ Р°РґСЂРµСЃРё СЃРµСЂРІРµСЂР° РЅРµ РІРґР°Р»РѕСЃСЊ", exc_info=True)
                return
            finally:
                self._reconcile_running = False
            if found and found.rstrip("/") != configured.rstrip("/"):
                self._ui_call(lambda: self._apply_reconciled_url(configured, found))

        threading.Thread(target=work, daemon=True,
                         name="reconcile-server-url").start()

    def _apply_reconciled_url(self, configured: str, found: str) -> None:
        """Р—Р°СЃС‚РѕСЃСѓРІР°С‚Рё Р·РЅР°Р№РґРµРЅСѓ Р°РґСЂРµСЃСѓ (СѓР¶Рµ РІ РіРѕР»РѕРІРЅРѕРјСѓ РїРѕС‚РѕС†С–)."""
        LOG.info("РђРґСЂРµСЃР° СЃРµСЂРІРµСЂР° СѓР·РіРѕРґР¶РµРЅР°: %s в†’ %s", configured, found)
        self.settings.llm.base_url = found
        self.settings.llm.api_key = runtime.MANAGED_API_KEY
        safe.call_quiet(self.settings.save, where="Р·Р±РµСЂРµР¶РµРЅРЅСЏ Р°РґСЂРµСЃРё СЃРµСЂРІРµСЂР°")
        self.agent.llm_settings = self.settings.llm
        self.set_status(f"РђРґСЂРµСЃСѓ СЃРµСЂРІРµСЂР° СѓР·РіРѕРґР¶РµРЅРѕ Р· СЂРѕР±РѕС‡РѕСЋ: {found}")

    def _adopt_local_model(self) -> None:
        """РџС–РґС…РѕРїРёС‚Рё Р»РѕРєР°Р»СЊРЅСѓ РјРѕРґРµР»СЊ, СЏРєС‰Рѕ РІ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏС… РЅР°Р·РІР° РїРѕСЂРѕР¶РЅСЏ.

        РљРѕСЂРёСЃС‚СѓРІР°С‡ РјС–Рі СЃРєР°С‡Р°С‚Рё GGUF С– РЅРµ РѕР±СЂР°С‚Рё Р№РѕРіРѕ РІСЂСѓС‡РЅСѓ; Р±РµР· С†СЊРѕРіРѕ
        СЂСЏРґРѕРє РјРѕРґРµР»С– РїРѕРєР°Р·СѓС” В«РјРѕРґРµР»СЊ РЅРµ РІРёР±СЂР°РЅР°В», Р° Р°РіРµРЅС‚ С–РґРµ РІ РѕС„Р»Р°Р№РЅ-СЂРѕСѓС‚РµСЂ
        Р·Р°РјС–СЃС‚СЊ СЂРѕР±РѕС‚Рё Р· РјРѕРґРµР»Р»СЋ.
        """
        if self.settings.llm.model.strip():
            # РњРѕРґРµР»СЊ СѓР¶Рµ РІРёР±СЂР°РЅР° вЂ” Р°Р»Рµ Р°РґСЂРµСЃР° РјРѕРіР»Р° Р·Р°СЃС‚Р°СЂС–С‚Рё (РїРѕСЂС‚
            # Р·РјС–РЅРёРІСЃСЏ РїС–СЃР»СЏ РїРµСЂРµР·Р°РїСѓСЃРєСѓ). РЈР·РіРѕРґР¶СѓС”РјРѕ С—С— РџР•Р Р•Р” РїРµСЂС€РёРј
            # Р·Р°РїРёС‚РѕРј, С–РЅР°РєС€Рµ Р°РіРµРЅС‚ СЃС‚СѓРєР°С” РІ Р·Р°Р№РЅСЏС‚РёР№ РїРѕСЂС‚ С– РґС–СЃС‚Р°С” 404.
            self._reconcile_server_url()
            return
        if getattr(self.settings.llm, "base_url", "").strip() and \
                "127.0.0.1" not in self.settings.llm.base_url and \
                "localhost" not in self.settings.llm.base_url:
            return          # Р·РѕРІРЅС–С€РЅС–Р№ СЃРµСЂРІРµСЂ вЂ” РјРѕРґРµР»СЊ РІРёР·РЅР°С‡Р°С” РІС–РЅ
        try:
            local = [p for p in hub.local_models() if p.suffix.lower() == ".gguf"]
        except Exception:  # noqa: BLE001 - С…Р°Р± РјРѕР¶Рµ Р±СѓС‚Рё РЅРµРґРѕСЃС‚СѓРїРЅРёР№
            local = []
        if not local:
            return
        chosen = self.settings.engine.model_path
        path = Path(chosen) if chosen and Path(chosen).exists() else None
        if path is None:
            path = max(local, key=lambda p: p.stat().st_size if p.exists() else 0)
        self.settings.llm.model = path.stem
        # URL С– РєР»СЋС‡ РјР°СЋС‚СЊ РІС–РґРїРѕРІС–РґР°С‚Рё СЂСѓС€С–СЋ, СЏРєРёР№ РѕР±СЃР»СѓРіРѕРІСѓС” С†СЋ РјРѕРґРµР»СЊ:
        # С–РЅР°РєС€Рµ Р°РіРµРЅС‚ СЃС‚СѓРєР°С” РІ LM Studio РЅР° 1234 С– РјРѕРІС‡РєРё Р№РґРµ РІ РѕС„Р»Р°Р№РЅ-СЂРѕСѓС‚РµСЂ.
        port = int(getattr(self.settings.engine, "port", 0) or 0) or runtime.DEFAULT_PORT
        current_url = str(self.settings.llm.base_url or "")
        if not current_url or "1234" in current_url:
            self.settings.llm.base_url = f"http://127.0.0.1:{port}/v1"
        key = str(self.settings.llm.api_key or "").strip().lower()
        if not key or key in ("lm-studio", "none"):
            self.settings.llm.api_key = runtime.MANAGED_API_KEY
        self.settings.engine.model_path = str(path)
        # Р—Р±РµСЂРµР¶РµРЅРЅСЏ РЅРµ РјР°С” Р»Р°РјР°С‚Рё СЃС‚Р°СЂС‚, Р°Р»Рµ Р№РѕРіРѕ Р·Р±С–Р№ С‚СЂРµР±Р° Р±Р°С‡РёС‚Рё:
        # С–РЅР°РєС€Рµ РјРѕРґРµР»СЊ В«РїС–РґС…РѕРїРёР»Р°СЃСЊВ», Р° РїС–СЃР»СЏ РїРµСЂРµР·Р°РїСѓСЃРєСѓ Р·РЅРѕРІСѓ РЅРµ
        # РІРёР±СЂР°РЅР°, С– РїСЂРёС‡РёРЅСѓ РЅРµ Р·РЅР°Р№С‚Рё.
        safe.call_quiet(self.settings.save, where="Р·Р±РµСЂРµР¶РµРЅРЅСЏ РІРёР±СЂР°РЅРѕС— РјРѕРґРµР»С–")
        self.set_status(f"РњРѕРґРµР»СЊ: {path.stem}")

    def _current_editor_path(self) -> Optional[Path]:
        """РџРѕС‚РѕС‡РЅРёР№ С„Р°Р№Р» СЂРµРґР°РєС‚РѕСЂР° (``None``, СЏРєС‰Рѕ РЅС–С‡РѕРіРѕ РЅРµ РІС–РґРєСЂРёС‚Рѕ).

        Р’РёРєР»РёРєР°С”С‚СЊСЃСЏ Р· РїР°РЅРµР»С– С‡Р°С‚Сѓ РїС–Рґ С‡Р°СЃ РїС–РґРєР°Р·РѕРє РЅР°Рґ РїРѕР»РµРј; РІРєР»Р°РґРєРё
        РјРѕР¶СѓС‚СЊ Р±СѓС‚Рё С‰Рµ РЅРµ СЃС‚РІРѕСЂРµРЅС– вЂ” С‚РѕРґС– РїСЂРѕСЃС‚Рѕ РЅРµРјР°С” С„Р°Р№Р»Сѓ.
        """
        tabs = getattr(self, "tabs", None)
        if tabs is None:
            return None
        try:
            return tabs.current_path()
        except (tk.TclError, AttributeError):
            return None

    def _sync_chat_title(self) -> None:
        chat = self.chat_store.active()
        title = (chat.title if chat else "") or "РќРѕРІРёР№ С‡Р°С‚"
        try:
            self.chat.set_title(title)
        except (tk.TclError, AttributeError):
            pass

    def _remember_message(self, role: str, text: str) -> None:
        """Р—Р±РµСЂРµРіС‚Рё РїРѕРІС–РґРѕРјР»РµРЅРЅСЏ; СЃР°РјРµ С‚СѓС‚ РЅР°СЂРѕРґР¶СѓС”С‚СЊСЃСЏ Р·Р°РїРёСЃ С‡Р°С‚Сѓ.

        В«РќРѕРІРёР№ С‡Р°С‚В» РіРѕС‚СѓС” РїРѕСЂРѕР¶РЅСЋ СЃС‚СЂС–С‡РєСѓ Р±РµР· Р·Р°РїРёСЃСѓ РІ СЃС…РѕРІРёС‰Рµ, С‚РѕР¶ РїРµСЂС€РёР№
        Р·Р°РїРёСЃ СЃС‚РІРѕСЂСЋС”С‚СЊСЃСЏ РЅР° РїРµСЂС€Рµ СЃРїСЂР°РІР¶РЅС” РїРѕРІС–РґРѕРјР»РµРЅРЅСЏ. Р‘РµР· С‚РµРєРё РїСЂРѕС”РєС‚Сѓ
        Р·Р°РїРёСЃ РЅРµ СЃС‚РІРѕСЂСЋС”РјРѕ: С‚Р°РєРёР№ С‡Р°С‚ РЅРµ РјР°С” РґРѕ С‡РѕРіРѕ РїСЂРёРІ'СЏР·Р°С‚РёСЃСЊ.
        """
        if not self.chat_store.active():
            self._ensure_pending_chat()
        if not self.chat_store.active():
            return
        self.chat_store.append(role, text)
        # РљРѕРЅС‚РµРєСЃС‚ Р°РіРµРЅС‚Р° Р·Р±РµСЂС–РіР°С”РјРѕ СЂР°Р·РѕРј С–Р· РїРѕРІС–РґРѕРјР»РµРЅРЅСЏРј: РЅР°РІС–С‚СЊ СЏРєС‰Рѕ
        # РїСЂРѕРіСЂР°РјСѓ Р·Р°РєСЂРёСЋС‚СЊ РїРѕСЃРµСЂРµРґ СЂРѕР±РѕС‚Рё, СЂРѕР·РјРѕРІР° РІС–РґРЅРѕРІРёС‚СЊСЃСЏ РїРѕРІРЅС–СЃС‚СЋ.
        chat_id = self._active_chat_id()
        if chat_id:
            self._save_chat_context(chat_id)
        self.chat_list.refresh()
        self._sync_chat_title()

    # в”Ђв”Ђ РїРѕСЃС‚С–Р№РЅС– РїРѕР±Р°Р¶Р°РЅРЅСЏ Р№ РІРёРјС–СЂСЋРІР°РЅРЅСЏ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _attach_profile(self, runner: "AgentRunner") -> None:
        """РџС–РґРєР»СЋС‡РёС‚Рё Р·Р±РµСЂРµР¶РµРЅС– РїРѕСЃС‚С–Р№РЅС– РїРѕР±Р°Р¶Р°РЅРЅСЏ РґРѕ Р°РіРµРЅС‚Р°."""
        try:
            runner.profile = conversation.UserProfile.from_list(
                self.settings.preferences)
        except Exception:                            # noqa: BLE001
            LOG.debug("РџРѕР±Р°Р¶Р°РЅРЅСЏ РЅРµ РїСЂРѕС‡РёС‚Р°РЅРѕ", exc_info=True)
            runner.profile = conversation.UserProfile()

    def _save_profile(self) -> None:
        """Р—Р°РїРёСЃР°С‚Рё РїРѕР±Р°Р¶Р°РЅРЅСЏ Сѓ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏ (РїС–СЃР»СЏ РєРѕР¶РЅРѕРіРѕ С…РѕРґСѓ).

        РџРёС€РµРјРѕ Р»РёС€Рµ РєРѕР»Рё СЃРїРёСЃРѕРє СЃРїСЂР°РІРґС– Р·РјС–РЅРёРІСЃСЏ: С–РЅР°РєС€Рµ РєРѕР¶РµРЅ С…С–Рґ
        РїРµСЂРµР·Р°РїРёСЃСѓРІР°РІ Р±Рё С„Р°Р№Р» РЅР°Р»Р°С€С‚СѓРІР°РЅСЊ.
        """
        runner = getattr(self, "agent", None)
        profile = getattr(runner, "profile", None)
        if profile is None:
            return
        try:
            fresh = profile.to_list()
        except Exception:                            # noqa: BLE001
            return
        if fresh == list(self.settings.preferences):
            return
        self.settings.preferences = fresh
        try:
            self.settings.save()
        except Exception:                            # noqa: BLE001
            LOG.debug("РџРѕР±Р°Р¶Р°РЅРЅСЏ РЅРµ Р·Р±РµСЂРµР¶РµРЅРѕ", exc_info=True)

    def _attach_traces(self, runner: "AgentRunner") -> None:
        """РџС–РґРєР»СЋС‡РёС‚Рё СЃС…РѕРІРёС‰Рµ РїСЂРѕРіРѕРЅС–РІ (РґР»СЏ РјРµС‚СЂРёРє С– РЅР°РІС‡Р°Р»СЊРЅРёС… РїСЂРёРєР»Р°РґС–РІ)."""
        try:
            from .config import app_data_dir

            path = app_data_dir() / "agent_traces.jsonl"
            runner.traces = trace_store.TraceStore(path)
        except Exception:                            # noqa: BLE001
            LOG.debug("РЎС…РѕРІРёС‰Рµ traces РЅРµРґРѕСЃС‚СѓРїРЅРµ", exc_info=True)
            runner.traces = None

    def _attach_memory_bridge(self, runner: "AgentRunner") -> None:
        """РџС–РґРєР»СЋС‡РёС‚Рё РїР°Рј'СЏС‚СЊ NEUROMESH РґРѕ СЂРѕР·СѓРјС–РЅРЅСЏ Р·Р°РїРёС‚Сѓ.

        РЎРµСЂРІС–СЃ СЃС‚РІРѕСЂСЋС”С‚СЊСЃСЏ РІ ``__init__`` (``self.memory``), Р°Р»Рµ С‚РѕРґС–
        Р°РіРµРЅС‚Р° С‰Рµ РЅРµРјР°С”. РўРѕРјСѓ РјС–СЃС‚ РїС–РґРєР»СЋС‡Р°С”РјРѕ РѕРєСЂРµРјРѕ вЂ” С– РїРѕРІС‚РѕСЂРЅРѕ, РєРѕР»Рё
        РїР°Рј'СЏС‚СЊ РїРµСЂРµСЃС‚РІРѕСЂСЋС”С‚СЊСЃСЏ.
        """
        try:
            existing = getattr(runner, "memory_bridge", None)
            if existing is None:
                runner.memory_bridge = memory_bridge.MemoryBridge(self.memory)
            else:
                existing.attach(self.memory)
        except Exception:                            # noqa: BLE001
            LOG.debug("РџР°Рј'СЏС‚СЊ РЅРµ РїС–РґРєР»СЋС‡РµРЅР° РґРѕ Р°РіРµРЅС‚Р°", exc_info=True)

    def show_agent_quality(self) -> None:
        """РџРѕРєР°Р·Р°С‚Рё Р·РІС–С‚ РїСЂРѕ СЏРєС–СЃС‚СЊ Р°РіРµРЅС‚Р° (СЂРµР°Р»СЊРЅС– С†РёС„СЂРё, РЅРµ РѕР±С–С†СЏРЅРєРё)."""
        runner = getattr(self, "agent", None)
        store = getattr(runner, "traces", None)
        if store is None:
            messagebox.showinfo(APP_NAME, "Р’РёРјС–СЂСЋРІР°РЅРЅСЏ РІРёРјРєРЅРµРЅРѕ РІ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏС….")
            return
        summary = store.summary()
        report = trace_store.format_report(summary)
        window = tk.Toplevel(self)
        window.title("РЇРєС–СЃС‚СЊ Р°РіРµРЅС‚Р°")
        window.configure(bg=theme.BG)
        window.geometry("760x560")
        window.transient(self)
        # РЁСЂРёС„С‚ Р±РµСЂРµРјРѕ Р· С‚РµРјРё РІС–РєРЅР° (``self.theme``), Р° РЅРµ Р· ``self.fonts``:
        # С‚Р°РєРѕРіРѕ Р°С‚СЂРёР±СѓС‚Р° Сѓ РІС–РєРЅР° РЅРµРјР°С”, С– РєРЅРѕРїРєР° РјРµРЅСЋ РїР°РґР°Р»Р° Р·
        # AttributeError Р·Р°РјС–СЃС‚СЊ С‚РѕРіРѕ, С‰РѕР± РїРѕРєР°Р·Р°С‚Рё Р·РІС–С‚.
        mono = getattr(getattr(self, "theme", None), "mono_small", None) \
            or ("Consolas", 9)
        box = tk.Text(window, wrap="word", bg=theme.BG_EDITOR, fg=theme.FG, bd=0,
                      highlightthickness=0, font=mono,
                      padx=12, pady=10)
        box.pack(fill="both", expand=True, padx=8, pady=8)
        box.insert("1.0", report)
        box.configure(state="disabled")
        widgets.Chip(window, "Р—Р°РєСЂРёС‚Рё", window.destroy).pack(anchor="e", padx=10,
                                                            pady=(0, 10))

    def _on_new_chat(self) -> None:
        self._refresh_context()
        self.chat_list.refresh()

    def _on_chat_busy(self, busy: bool) -> None:
        self._set_agent_state("РїСЂР°С†СЋС”" if busy else "РѕС‡С–РєСѓС”")
        # РҐС–Рґ Р·Р°РІРµСЂС€РёРІСЃСЏ вЂ” Р·Р±РµСЂС–РіР°С”РјРѕ РїРѕР±Р°Р¶Р°РЅРЅСЏ, СЏРєС– РјРѕРіР»Рё Р·'СЏРІРёС‚РёСЃСЊ Сѓ
        # СЂРѕР·РјРѕРІС– (В«Р·Р°РІР¶РґРё РІС–РґРїРѕРІС–РґР°Р№ СѓРєСЂР°С—РЅСЃСЊРєРѕСЋВ»). РџРёС€РµРјРѕ Р»РёС€Рµ Р·РјС–РЅРё.
        if not busy:
            self._save_profile()
        # РЎС‚Р°С‚СѓСЃ СЃРµСЃС–С— РІ СЃРїРёСЃРєСѓ Р°РіРµРЅС‚С–РІ: РїСЂР°С†СЋС” / Р·Р°РІРµСЂС€РµРЅРѕ. РџРѕСЂРѕР¶РЅСЏ СЃРµСЃС–СЏ
        # Р±РµР· РїРѕРІС–РґРѕРјР»РµРЅСЊ Р»РёС€Р°С”С‚СЊСЃСЏ idle вЂ” С—Р№ С‰Рµ РЅС–С‡РѕРіРѕ В«Р·Р°РІРµСЂС€СѓРІР°С‚РёВ».
        chat = self.chat_store.active()
        if chat is not None:
            if busy:
                state = "working"
            elif chat.message_count:
                state = "done"
            else:
                state = "idle"
            self.chat_store.set_status(chat.id, state)
            self.chat_list.update_row_status(chat.id, state)
        # РђРіРµРЅС‚ СЃР°РјРµ Р·Р°РєС–РЅС‡РёРІ СЂРѕР±РѕС‚Сѓ, Р° Р°РІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј С‡РµРєР°РІ РЅР° С†Рµ, С‰РѕР±
        # Р·СѓРїРёРЅРёС‚РёСЃСЊ. Р—Р°РІРµСЂС€СѓС”РјРѕ Р·Р°СЂР°Р·, Р° РЅРµ РЅР° РЅР°СЃС‚СѓРїРЅРѕРјСѓ С‚С–РєСѓ: С–РЅР°РєС€Рµ
        # Р·СѓРїРёРЅРєР° В«РІРёСЃРёС‚СЊВ» РґРѕ 2.5 СЃ С– РєРѕСЂРёСЃС‚СѓРІР°С‡ РЅРµ СЂРѕР·СѓРјС–С”, С‰Рѕ СЃС‚Р°Р»РѕСЃСЊ.
        if not busy and self._autonomous_stop_pending:
            self._finish_autonomous_stop()

    def stop_agent(self) -> None:
        self.chat.stop()

    # в”Ђв”Ђ Р°РІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def show_autonomous(self) -> None:
        """Р’С–РґРєСЂРёС‚Рё РїР°РЅРµР»СЊ Р°РІС‚РѕРЅРѕРјРЅРѕРіРѕ СЂРµР¶РёРјСѓ РІ Р±С–С‡РЅС–Р№ РєРѕР»РѕРЅС†С–."""
        self.show_side("autonomous")

    def pick_autonomous_project(self) -> None:
        """РћР±СЂР°С‚Рё С‚РµРєСѓ РїСЂРѕС”РєС‚Сѓ РґР»СЏ Р°РІС‚РѕРЅРѕРјРЅРѕРіРѕ СЂРµР¶РёРјСѓ."""
        current = self.autonomous_engine.project or Path(self.settings.workspace)
        folder = filedialog.askdirectory(parent=self, title="РўРµРєР° РґР»СЏ Р°РІС‚РѕРЅРѕРјРЅРѕРіРѕ СЂРµР¶РёРјСѓ",
                                         initialdir=str(current))
        if not folder:
            return
        target = Path(folder)
        ok, reason = self.autonomous_engine.can_start(target)
        if not ok:
            self.set_status(reason)
            messagebox.showinfo("РђРІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј", reason, parent=self)
            return
        # РўРµРєР° СЃС‚Р°С” СЂРѕР±РѕС‡РѕСЋ: Р°РіРµРЅС‚ РїСЂР°РІРёС‚СЊ СЃР°РјРµ С—С—, С– С„Р°Р№Р»Рё РІРёРґРЅРѕ РІ СЂРµРґР°РєС‚РѕСЂС–.
        self.set_workspace(target)
        self.autonomous_engine.project = target
        self.autonomous_panel.refresh()
        self.set_status(f"РђРІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј: РѕР±СЂР°РЅРѕ {target}")

    def start_autonomous(self) -> None:
        """РЈРІС–РјРєРЅСѓС‚Рё Р±РµР·РїРµСЂРµСЂРІРЅРёР№ СЂРµР¶РёРј РїРѕРєСЂР°С‰РµРЅРЅСЏ РїСЂРѕС”РєС‚Сѓ.

        Р РµР¶РёРј РїСЂРёРІ'СЏР·Р°РЅРёР№ РґРѕ РљРћРќРљР Р•РўРќРћР“Рћ С‡Р°С‚Сѓ Р№ С‚РµРєРё: Р·Р°РґР°С‡С–, СЏРєС– РІС–РЅ
        СЃС‚Р°РІРёС‚СЊ, РґС–СЃС‚Р°СЋС‚СЊ ``chat_id`` С†СЊРѕРіРѕ С‡Р°С‚Сѓ, С– Р·РЅРёРєР°СЋС‚СЊ СЂР°Р·РѕРј С–Р· РЅРёРј.
        Р‘РµР· РїСЂРёРІ'СЏР·РєРё РІРѕРЅРё РІРёСЃС–Р»Рё РІ РїР°РЅРµР»С– В«РђРІС‚РѕРјР°С‚РёР·Р°С†С–С—В» РЅР°Р·Р°РІР¶РґРё.
        """
        if not self.settings.llm.model:
            messagebox.showwarning(
                "РђРІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј",
                "РЎРїРµСЂС€Сѓ РїС–РґРєР»СЋС‡Рё РјРѕРґРµР»СЊ (РҐР°Р± РјРѕРґРµР»РµР№ Р°Р±Рѕ РїРµСЂС€РёР№ Р·Р°РїСѓСЃРє): "
                "Р±РµР· РјРѕРґРµР»С– Р°РіРµРЅС‚ РЅРµ РјРѕР¶Рµ РїСЂР°РІРёС‚Рё РєРѕРґ.",
                parent=self)
            return
        if not self.has_project():
            self._show_project_gate(
                reason="РђРІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј РїРѕС‚СЂРµР±СѓС” С‚РµРєРё РїСЂРѕС”РєС‚Сѓ.")
            self.set_status("РЎРїРµСЂС€Сѓ РІРёР±РµСЂРё РїР°РїРєСѓ РїСЂРѕС”РєС‚Сѓ вЂ” Р°РІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј РїСЂР°С†СЋС” РІ РЅС–Р№.")
            return
        project = self.autonomous_engine.project or Path(self.settings.workspace)
        ok, message = self.autonomous_engine.start(project)
        if not ok:
            self.set_status(message)
            messagebox.showinfo("РђРІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј", message, parent=self)
            return
        # Р—Р°РґР°С‡С– СЂРµР¶РёРјСѓ РЅР°Р»РµР¶Р°С‚РёРјСѓС‚СЊ РїРѕС‚РѕС‡РЅРѕРјСѓ С‡Р°С‚Сѓ. РЇРєС‰Рѕ С‡Р°С‚ С‰Рµ С‡РµСЂРЅРµС‚РєР° вЂ”
        # СЃС‚РІРѕСЂСЋС”РјРѕ Р·Р°РїРёСЃ: СЂРµР¶РёРј РјР°С” РІР»Р°СЃРЅРёРєР°, С–РЅР°РєС€Рµ Р·Р°РґР°С‡С– СЃС‚Р°РЅСѓС‚СЊ СЃРёСЂРѕС‚Р°РјРё.
        self._ensure_pending_chat()
        self.autonomous_engine.chat_id = str(
            getattr(self.chat_store, "active_id", "") or "")
        self.project = project
        self._autonomous_stop_pending = False
        self.autonomous_engine.seed(limit=autonomous.SEED_PER_CYCLE)
        self.show_side("autonomous")
        self.show_chat(True)
        self.autonomous_panel.refresh()
        self._autonomous_tick()
        self._update_queue_badge()
        self.set_status(f"РђРІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј СѓРІС–РјРєРЅРµРЅРѕ: {project.name}")

    def _agent_working(self) -> bool:
        """Р§Рё Р°РіРµРЅС‚ СЃРїСЂР°РІРґС– С‰Рµ РІРёРєРѕРЅСѓС” С…С–Рґ.

        Р‘РµСЂРµРјРѕ РїСЂР°РїРѕСЂРµС†СЊ С‡Р°С‚Сѓ, Р° РЅРµ Р»РёС€Рµ Р¶РёС‚С‚СЏ РїРѕС‚РѕРєСѓ: РЅРёС‚РєР° РјРѕР¶Рµ РІР¶Рµ
        РґРѕРїРёСЃР°С‚Рё РІС–РґРїРѕРІС–РґСЊ, Р°Р»Рµ С‰Рµ РЅРµ РІСЃС‚РёРіРЅСѓС‚Рё Р·Р°РІРµСЂС€РёС‚РёСЃСЊ, С– С‚РѕРґС–
        Р·СѓРїРёРЅРєР° С‡РµРєР°Р»Р° Р± РЅР° В«РјРµСЂС‚РІРёР№В» СЃС‚Р°РЅ Р·Р°Р№РІС– СЃРµРєСѓРЅРґРё.
        """
        try:
            return bool(getattr(self.chat, "_busy", False))
        except Exception:  # noqa: BLE001 - РІС–РґР¶РµС‚ РјС–Рі Р±СѓС‚Рё Р·РЅРёС‰РµРЅРёР№
            return bool(getattr(self.agent, "busy", False))

    def stop_autonomous(self) -> None:
        """РљРѕСЂРµРєС‚РЅР° Р·СѓРїРёРЅРєР°: РїРѕС‚РѕС‡РЅРёР№ С„Р°Р№Р» РґРѕРїРёСЃСѓС”С‚СЊСЃСЏ Р№ Р·Р±РµСЂС–РіР°С”С‚СЊСЃСЏ."""
        if not self.autonomous_engine.active:
            self.set_status("РђРІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј С– С‚Р°Рє РІРёРјРєРЅРµРЅРѕ.")
            return
        message = self.autonomous_engine.request_stop()
        self._autonomous_stop_pending = True
        self.autonomous_panel.refresh()
        self.set_status(message)
        # РЇРєС‰Рѕ Р°РіРµРЅС‚ Р·Р°СЂР°Р· РЅС–С‡РѕРіРѕ РЅРµ СЂРѕР±РёС‚СЊ вЂ” Р·Р°РІРµСЂС€СѓС”РјРѕ РїСЂРѕСЃС‚Рѕ Р·Р°СЂР°Р·.
        if not self._agent_working():
            self._finish_autonomous_stop()

    def _finish_autonomous_stop(self) -> None:
        """Р”РѕРїРёСЃР°С‚Рё С„Р°Р№Р» (Р·Р±РµСЂРµРіС‚Рё РІСЃРµ) С– РІРёРјРєРЅСѓС‚Рё СЂРµР¶РёРј."""
        if not self.autonomous_engine.active or not self._autonomous_stop_pending:
            return
        self._autonomous_stop_pending = False
        saved = self._save_all_silently()
        reason = "РђРІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј РІРёРјРєРЅРµРЅРѕ."
        if saved:
            reason += f" Р—Р±РµСЂРµР¶РµРЅРѕ С„Р°Р№Р»С–РІ: {saved}."
        self.autonomous_engine.confirm_stop(reason=reason)
        try:
            self.autonomous_panel.refresh()
        except (tk.TclError, AttributeError):
            pass
        self._update_queue_badge()
        self.set_status("РђРІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј РІРёРјРєРЅРµРЅРѕ вЂ” СѓСЃС– Р·РјС–РЅРё Р·Р±РµСЂРµР¶РµРЅРѕ.")

    def _save_all_silently(self) -> int:
        """Р—Р±РµСЂРµРіС‚Рё РІСЃС– Р·РјС–РЅРµРЅС– РІРєР»Р°РґРєРё, РЅРµ РїРёС‚Р°СЋС‡Рё РЅС–С‡РѕРіРѕ.

        Р¦Рµ С‚Р° СЃР°РјР° В«РґРѕРїРёСЃРєР° РґРѕ РєС–РЅС†СЏВ», СЏРєРѕС— РІРёРјР°РіР°С” РєРѕСЂРµРєС‚РЅР° Р·СѓРїРёРЅРєР°:
        Р¶РѕРґРЅРѕРіРѕ РЅРµР·Р°РєС–РЅС‡РµРЅРѕРіРѕ С„Р°Р№Р»Сѓ РЅРµ Р»РёС€Р°С”С‚СЊСЃСЏ. Р‘РµР·С–РјРµРЅРЅС– С„Р°Р№Р»Рё
        РїСЂРѕРїСѓСЃРєР°С”РјРѕ вЂ” РґР»СЏ РЅРёС… РЅРµРјР°С” С€Р»СЏС…Сѓ, С– РјРѕРІС‡РєРё Р·Р±РµСЂС–РіР°С‚Рё С—С… РЅС–РєСѓРґРё.
        """
        tabs = getattr(self, "tabs", None)
        if tabs is None:
            return 0
        count = 0
        for frame_id in list(getattr(tabs, "_order", [])):
            editor = tabs.editors.get(frame_id)
            path = tabs.paths.get(frame_id)
            if editor is None or path is None:
                continue
            if not getattr(editor, "modified", False):
                continue
            try:
                ws.write_text_file(path, editor.get_text())
                editor.modified = False
                tab = tabs._tabs.get(frame_id) if hasattr(tabs, "_tabs") else None
                if tab is not None:
                    tab.set_title(Path(path).name, False)
                count += 1
            except Exception:  # noqa: BLE001 - Р·СѓРїРёРЅРєР° РЅРµ РјР°С” РїР°РґР°С‚Рё РЅР° РґРёСЃРєСѓ
                LOG.warning("РќРµ РІРґР°Р»РѕСЃСЊ Р·Р±РµСЂРµРіС‚Рё %s РїС–Рґ С‡Р°СЃ Р·СѓРїРёРЅРєРё", path, exc_info=True)
        if count:
            # РџРµСЂРµРјР°Р»СЊРѕРІСѓРІР°РЅРЅСЏ РІРєР»Р°РґРѕРє вЂ” РєРѕСЃРјРµС‚РёРєР°, Р°Р»Рµ Р·Р±С–Р№ С„С–РєСЃСѓС”РјРѕ: СЏРєС‰Рѕ
            # РІРѕРЅРѕ РїР°РґР°С”, РєРѕСЂРёСЃС‚СѓРІР°С‡ Р±Р°С‡РёС‚СЊ В«Р·С–СЂРѕС‡РєСѓВ» Р·РјС–РЅ РЅР°РІС–С‚СЊ РїС–СЃР»СЏ
            # Р·Р±РµСЂРµР¶РµРЅРЅСЏ Р№ РЅРµ СЂРѕР·СѓРјС–С”, С‡РѕРјСѓ.
            safe.call_quiet(tabs._notify_changed,
                            where="РѕРЅРѕРІР»РµРЅРЅСЏ РїРѕР·РЅР°С‡РѕРє РІРєР»Р°РґРѕРє")
        return count

    def add_autonomous_task(self, text: str) -> None:
        """Р“Р°СЂСЏС‡Рµ РґРѕРґР°С‚Рё СЃРІРѕСЋ Р·Р°РґР°С‡Сѓ РІ Р°РІС‚РѕРЅРѕРјРЅСѓ С‡РµСЂРіСѓ (РІРёС‰РёР№ РїСЂС–РѕСЂРёС‚РµС‚)."""
        ok, message = self.autonomous_engine.add_user_task(text)
        self.set_status(message)
        if ok:
            self._update_queue_badge()
            self.autonomous_panel.refresh()
            # Р РµР¶РёРј РІРёРјРєРЅРµРЅРѕ вЂ” Р·Р°РґР°С‡Р° РІСЃРµ РѕРґРЅРѕ РІ С‡РµСЂР·С– Р№ РІРёРєРѕРЅР°С”С‚СЊСЃСЏ РїС–СЃР»СЏ СЃС‚Р°СЂС‚Сѓ.
            if not self.autonomous_engine.active:
                self.set_status(message + " РќР°С‚РёСЃРЅРё В«РЎС‚Р°СЂС‚В», С‰РѕР± Р°РіРµРЅС‚ РїРѕС‡Р°РІ.")

    def _after_autonomous_change(self) -> None:
        """Р СѓС€С–Р№ Р·РјС–РЅРёРІСЃСЏ вЂ” РѕРЅРѕРІРёС‚Рё РїР°РЅРµР»СЊ С– Р±РµР№РґР¶ (Р· РіРѕР»РѕРІРЅРѕРіРѕ РїРѕС‚РѕРєСѓ)."""
        if not self._timer_alive():
            return
        try:
            self.autonomous_panel.refresh()
        except (tk.TclError, AttributeError):
            pass

    def _autonomous_tick(self) -> None:
        """РЎРµСЂС†Рµ СЂРµР¶РёРјСѓ: СЂР°Р· РЅР° РєС–Р»СЊРєР° СЃРµРєСѓРЅРґ РІРёСЂС–С€СѓС”, С‰Рѕ СЂРѕР±РёС‚Рё РґР°Р»С–."""
        try:
            engine = self.autonomous_engine
            if engine.state == autonomous.STATE_OFF:
                self._autonomous_after = None
                return
            busy = self._agent_working()
            # Р Р°С…СѓС”РјРѕ Р»РёС€Рµ Р·Р°РґР°С‡С– РЎР’РћР“Рћ С‡Р°С‚Сѓ: С‡СѓР¶С– РЅРµ РјР°СЋС‚СЊ РІРІР°Р¶Р°С‚РёСЃСЊ
            # СЂРѕР±РѕС‚РѕСЋ С†СЊРѕРіРѕ СЃРµР°РЅСЃСѓ, С–РЅР°РєС€Рµ СЂРµР¶РёРј С‡РµРєР°РІ Р±Рё РЅР° РЅРёС… РґР°СЂРµРјРЅРѕ.
            pending = self.task_queue.next_pending(
                chat_id=self._active_chat_id()) is not None
            action = engine.tick(busy=busy, has_pending=pending)
            if action == "stop_wait":
                # РђРіРµРЅС‚ РґРѕРїРёСЃСѓС” С„Р°Р№Р» вЂ” РЅРµ С‡С–РїР°С”РјРѕ Р№РѕРіРѕ, Р»РёС€Рµ РїРѕРєР°Р·СѓС”РјРѕ СЃС‚Р°РЅ.
                self.set_status("РђРІС‚РѕРЅРѕРјРЅРѕ: РґРѕРїРёСЃСѓСЋ РїРѕС‚РѕС‡РЅРёР№ С„Р°Р№Р», РґР°Р»С– Р·СѓРїРёРЅСЋСЃСЊвЂ¦")
            elif action == "stop_finish":
                self._finish_autonomous_stop()
                self._autonomous_after = None
                return
            elif action == "run":
                self._autonomous_run_next()
            elif action == "seed":
                added = engine.seed(limit=autonomous.SEED_PER_CYCLE)
                self.autonomous_panel.refresh()
                if added:
                    self._autonomous_run_next()
                else:
                    self.set_status("РђРІС‚РѕРЅРѕРјРЅРѕ: РЅРѕРІРёС… С–РґРµР№ РЅРµРјР°С”, РїРѕРІС‚РѕСЂСЋ Р°РЅР°Р»С–Р· Р·Р° С…РІРёР»РёРЅСѓ.")
        except Exception as exc:  # noqa: BLE001 - С‚С–Рє РЅРµ РјР°С” РІР°Р»РёС‚Рё РІС–РєРЅРѕ
            LOG.warning("РўС–Рє Р°РІС‚РѕРЅРѕРјРЅРѕРіРѕ СЂРµР¶РёРјСѓ РІРїР°РІ: %s", exc, exc_info=True)
            self.set_status(f"РђРІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј: РїРѕРјРёР»РєР° РєСЂРѕРєСѓ вЂ” {exc}")
        try:
            if self.winfo_exists():
                self._autonomous_after = (self.after(2500, self._autonomous_tick)
                                          if self._timer_alive() else None)
        except tk.TclError:
            self._autonomous_after = None

    def _autonomous_run_next(self) -> None:
        """Р—Р°РїСѓСЃС‚РёС‚Рё РЅР°СЃС‚СѓРїРЅСѓ Р·Р°РґР°С‡Сѓ С‡РµСЂРіРё РІ СЂР°РјРєР°С… Р°РІС‚РѕРЅРѕРјРЅРѕРіРѕ СЂРµР¶РёРјСѓ."""
        task = self.task_queue.next_pending(chat_id=self._active_chat_id())
        if task is None:
            return
        engine = self.autonomous_engine
        engine.note_action(_plan_text_for(task), kind=autonomous.KIND_CODE,
                           file=task.file_hint)
        self.autonomous_panel.refresh()
        self.run_next_task(task)

    def _open_relative(self, path: str) -> None:
        """Р’С–РґРєСЂРёС‚Рё С„Р°Р№Р» РїСЂРѕС”РєС‚Сѓ Р·Р° РІС–РґРЅРѕСЃРЅРёРј С€Р»СЏС…РѕРј (Р· РїР°РЅРµР»С– Р°РІС‚РѕРЅРѕРјРЅРѕРіРѕ СЂРµР¶РёРјСѓ)."""
        clean = (path or "").strip()
        if not clean:
            return
        root = self.autonomous_engine.project or Path(self.settings.workspace)
        target = Path(root) / clean
        if target.exists():
            self.open_path(target)
        elif clean:
            self.set_status(f"Р¤Р°Р№Р» РЅРµ Р·РЅР°Р№РґРµРЅРѕ: {clean}")

    # в”Ђв”Ђ РїСЂРѕСЃС‚С–Р№: РІРёРІР°РЅС‚Р°Р¶РµРЅРЅСЏ РјРѕРґРµР»С– Р· РІС–РґРµРѕРєР°СЂС‚Рё в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _wake_model(self) -> None:
        """РџС–РґРЅСЏС‚Рё Р»РѕРєР°Р»СЊРЅСѓ РјРѕРґРµР»СЊ, СЏРєС‰Рѕ С—С— РІРёРІР°РЅС‚Р°Р¶РёР»Рё РїС–Рґ С‡Р°СЃ РїСЂРѕСЃС‚РѕСЋ."""
        if self.model_keeper.loaded:
            return
        local = []
        try:
            local = [p.name for p in hub.local_models() if p.suffix.lower() == ".gguf"]
        except Exception:  # noqa: BLE001 - С…Р°Р± РјРѕР¶Рµ Р±СѓС‚Рё РЅРµРґРѕСЃС‚СѓРїРЅРёР№
            pass
        if local:
            self._autostart_local_model(local)

    def _wake_native_model(self) -> bool:
        """Р—Р°РІР°РЅС‚Р°Р¶РёС‚Рё РјРѕРґРµР»СЊ РЅР°Р·Р°Рґ Сѓ РІР»Р°СЃРЅРёР№ СЂСѓС€С–Р№ РїС–СЃР»СЏ РїСЂРѕСЃС‚РѕСЋ."""
        try:
            if self.native_runtime.loaded:
                return True
            result = self._autostart_native_model()
            return bool(result) and self.native_runtime.loaded
        except Exception:  # noqa: BLE001 - РЅРµ Р»Р°РјР°С”РјРѕ С‚С–Рє РїСЂРѕСЃС‚РѕСЋ
            LOG.debug("Р’Р»Р°СЃРЅРёР№ СЂСѓС€С–Р№ РЅРµ СЂРѕР·Р±СѓРґРёРІСЃСЏ", exc_info=True)
            return False

    def _before_agent_request(self) -> None:
        """РџРµСЂРµРґ РєРѕР¶РЅРёРј Р·Р°РїРёС‚РѕРј: РїС–РґРЅСЏС‚Рё РјРѕРґРµР»СЊ, СЏРєС‰Рѕ С—С— РІРёРІР°РЅС‚Р°Р¶РёРІ РїСЂРѕСЃС‚С–Р№."""
        try:
            self._wake_model_if_needed()
        except Exception:  # noqa: BLE001 - РїС–РґР№РѕРј РЅРµ РјР°С” Р±Р»РѕРєСѓРІР°С‚Рё Р·Р°РїРёС‚
            LOG.debug("РџС–РґР№РѕРј РјРѕРґРµР»С– РїРµСЂРµРґ Р·Р°РїРёС‚РѕРј РЅРµ РІРґР°РІСЃСЏ", exc_info=True)

    def _idle_tick(self) -> None:
        """Р Р°Р· РЅР° РєС–Р»СЊРєР° СЃРµРєСѓРЅРґ: С‡Рё РЅРµ С‡Р°СЃ РІС–РґРґР°С‚Рё РїР°Рј'СЏС‚СЊ РІС–РґРµРѕРєР°СЂС‚Рё."""
        try:
            keeper = self.model_keeper
            busy = self._agent_working()
            autonomous_on = self.autonomous_engine.active
            if keeper.poll(busy=busy, autonomous=autonomous_on):
                self._note_model_unloaded()
        except Exception as exc:  # noqa: BLE001 - С„РѕРЅРѕРІРёР№ С‚С–Рє РЅРµ РјР°С” Р»Р°РјР°С‚Рё РІС–РєРЅРѕ
            LOG.debug("РўС–Рє РїСЂРѕСЃС‚РѕСЋ РІРїР°РІ: %s", exc, exc_info=True)
        try:
            if self.winfo_exists():
                self._idle_after = (self.after(20000, self._idle_tick)
                                    if self._timer_alive() else None)
        except tk.TclError:
            self._idle_after = None

    def _note_model_unloaded(self) -> None:
        """РњРѕРґРµР»СЊ РїС–С€Р»Р° Р· РІС–РґРµРѕРєР°СЂС‚Рё: СЃРєР°Р·Р°С‚Рё РїСЂРѕ С†Рµ Р№ Р·Р°РїР°Рј'СЏС‚Р°С‚Рё СЃС‚Р°РЅ.

        РќР°РІС–С‰Рѕ РѕРєСЂРµРјРёР№ РјРµС‚РѕРґ. РЈ Р»РѕР·С– РєРѕСЂРёСЃС‚СѓРІР°С‡Р° Р±СѓР»Рѕ С‚Р°Рє:

            19:03:50  РЎС‚Р°СЂС‚ СЂСѓС€С–СЏ: вЂ¦ --port 8080 вЂ¦
            19:08:50  РњРѕРґРµР»СЊ РІРёРІР°РЅС‚Р°Р¶РµРЅРѕ РїС–СЃР»СЏ 0 СЃ РїСЂРѕСЃС‚РѕСЋ
            19:10:31  РђРґСЂРµСЃР° 8080 РЅРµ СЃР»СѓС…Р°С” в†’ РјРѕРґРµР»СЊ РЅРµРґРѕСЃС‚СѓРїРЅР°

        РњРѕРґРµР»СЊ РІРёРІР°РЅС‚Р°Р¶РёР»Р°СЃСЊ С‡РµСЂРµР· 5 С…РІ РїСЂРѕСЃС‚РѕСЋ вЂ” С– Р‘Р†Р›Р¬РЁР• РќР†РљРћР›Р РЅРµ
        РїС–РґРЅСЏР»Р°СЃСЊ: ``model_keeper.reload()`` РЅРµ РІРёРєР»РёРєР°РІСЃСЏ РЅС–РґРµ РІ РїСЂРѕС”РєС‚С–.
        РљРѕСЂРёСЃС‚СѓРІР°С‡ Р±Р°С‡РёРІ В«РјРѕРґРµР»СЊ РЅРµ СЃС‚Р°СЂС‚СѓС”В», С…РѕС‡ РІРѕРЅР° СЃС‚Р°СЂС‚СѓРІР°Р»Р°.

        РўРµРїРµСЂ СЃС‚Р°РЅ Р·Р°РїР°Рј'СЏС‚РѕРІСѓС”С‚СЊСЃСЏ (``_model_unloaded_by_idle``), С– РїРµСЂС€Р°
        Р¶ РґС–СЏ РєРѕСЂРёСЃС‚СѓРІР°С‡Р° РїС–РґРЅС–РјР°С” РјРѕРґРµР»СЊ РЅР°Р·Р°Рґ.
        """
        self._model_unloaded_by_idle = True
        # РЎС‚Р°РЅ СЃРµСЂРІРµСЂР° С‚РµРїРµСЂ Р†РќРЁРР™: РІС–РЅ Р±С–Р»СЊС€Рµ РЅРµ РѕР±СЃР»СѓРіРѕРІСѓС” РјРѕРґРµР»СЊ.
        # Р‘РµР· С†СЊРѕРіРѕ С–РЅС‚РµСЂС„РµР№СЃ РїСЂРѕРґРѕРІР¶СѓРІР°РІ РїРѕРєР°Р·СѓРІР°С‚Рё В«onlineВ» С– СЃС‚Р°СЂРµ РІС–РєРЅРѕ
        # РєРѕРЅС‚РµРєСЃС‚Сѓ, С…РѕС‡ СЃРµСЂРІРµСЂ СѓР¶Рµ Р·СѓРїРёРЅРµРЅРѕ.
        try:
            self.server_state.set_local(running=False)
            self.server_state.invalidate(reason="РјРѕРґРµР»СЊ РІРёРІР°РЅС‚Р°Р¶РµРЅРѕ С‡РµСЂРµР· РїСЂРѕСЃС‚С–Р№")
        except (AttributeError, tk.TclError):
            LOG.debug("РЎС‚Р°РЅ СЃРµСЂРІРµСЂР° РЅРµ РѕРЅРѕРІР»РµРЅРѕ РїС–СЃР»СЏ РІРёРІР°РЅС‚Р°Р¶РµРЅРЅСЏ", exc_info=True)
        self.set_status("РњРѕРґРµР»СЊ РІРёРІР°РЅС‚Р°Р¶РµРЅРѕ Р· РІС–РґРµРѕРєР°СЂС‚Рё вЂ” РІРѕРЅР° РІС–Р»СЊРЅР° РґР»СЏ "
                        "С–РЅС€РёС… Р·Р°РґР°С‡. РџС–РґРЅС–РјРµС‚СЊСЃСЏ СЃР°РјР° РЅР° РЅР°СЃС‚СѓРїРЅРёР№ Р·Р°РїРёС‚.")
        try:
            self.header_bar.set_model_status(
                False, detail="РІРёРІР°РЅС‚Р°Р¶РµРЅРѕ С‡РµСЂРµР· РїСЂРѕСЃС‚С–Р№ вЂ” РїС–РґРЅС–РјРµС‚СЊСЃСЏ РЅР° Р·Р°РїРёС‚")
        except (tk.TclError, AttributeError):
            pass
        try:
            self.autonomous_panel.refresh()
        except (tk.TclError, AttributeError):
            pass

    def _wake_model_if_needed(self) -> bool:
        """РџС–РґРЅСЏС‚Рё РјРѕРґРµР»СЊ, СЏРєС‰Рѕ С—С— РІРёРІР°РЅС‚Р°Р¶РёРІ РїСЂРѕСЃС‚С–Р№. ``True`` вЂ” РїС–РґРЅСЏР»Рё.

        Р’РёРєР»РёРєР°С”С‚СЊСЃСЏ РџР•Р Р•Р” РІС–РґРїСЂР°РІРєРѕСЋ Р·Р°РїРёС‚Сѓ Р°РіРµРЅС‚Сѓ: РєРѕСЂРёСЃС‚СѓРІР°С‡ РїРѕРІРµСЂРЅСѓРІСЃСЏ
        РїС–СЃР»СЏ РїР°СѓР·Рё, РјРѕРґРµР»СЊ СѓР¶Рµ РЅРµ РІ РїР°Рј'СЏС‚С–, С– Р±РµР· С†СЊРѕРіРѕ РєРѕР¶РµРЅ С‚Р°РєРёР№
        Р·Р°РїРёС‚ Р·Р°РєС–РЅС‡СѓРІР°РІСЃСЏ Р± В«РјРѕРґРµР»СЊ РЅРµРґРѕСЃС‚СѓРїРЅР°В».
        """
        if not getattr(self, "_model_unloaded_by_idle", False):
            return False
        keeper = getattr(self, "model_keeper", None)
        if keeper is None:
            return False
        if keeper.loaded:
            # РњРѕРґРµР»СЊ СѓР¶Рµ РґРµСЃСЊ Р·Р°РІР°РЅС‚Р°Р¶РµРЅР° вЂ” РїСЂРѕСЃС‚Рѕ Р·РЅС–РјР°С”РјРѕ РїСЂР°РїРѕСЂРµС†СЊ.
            self._model_unloaded_by_idle = False
            return False
        try:
            self.model_keeper.touch()
            ok = keeper.reload()
        except Exception as exc:  # noqa: BLE001 - РїС–РґР№РѕРј РЅРµ РјР°С” Р»Р°РјР°С‚Рё Р·Р°РїРёС‚
            LOG.warning("РњРѕРґРµР»СЊ РЅРµ РїС–РґРЅСЏР»Р°СЃСЊ РїС–СЃР»СЏ РїСЂРѕСЃС‚РѕСЋ: %s", exc,
                        exc_info=True)
            return False
        if ok:
            self._model_unloaded_by_idle = False
            # РњРѕРґРµР»СЊ РїС–РґРЅСЏР»Р°СЃСЊ вЂ” РєРѕРЅС‚РµРєСЃС‚ С– РЅР°Р±С–СЂ СЃС…РµРј РњРћР–РЈРўР¬ Р±СѓС‚Рё С–РЅС€РёРјРё.
            # РЎРєРёРґР°С”РјРѕ С—С…, С‰РѕР± РїРµСЂС€РёР№ Р¶Рµ Р·Р°РїРёС‚ РЅРµ РїС–С€РѕРІ С–Р· СЃС‚Р°СЂРёРј РІС–РєРЅРѕРј.
            self._invalidate_model_state(reason="РјРѕРґРµР»СЊ РїС–РґРЅСЏС‚Рѕ РїС–СЃР»СЏ РїСЂРѕСЃС‚РѕСЋ")
            try:
                self.server_state.set_local(running=True)
                self.server_state.refresh(background=True)
            except (AttributeError, tk.TclError):
                LOG.debug("РЎС‚Р°РЅ СЃРµСЂРІРµСЂР° РЅРµ РѕРЅРѕРІР»РµРЅРѕ РїС–СЃР»СЏ РїС–РґР№РѕРјСѓ", exc_info=True)
            self.set_status("РњРѕРґРµР»СЊ Р·РЅРѕРІСѓ Р·Р°РІР°РЅС‚Р°Р¶РµРЅР° вЂ” РІРёРєРѕРЅСѓСЋ Р·Р°РїРёС‚.")
            LOG.info("РњРѕРґРµР»СЊ РїС–РґРЅСЏС‚Рѕ РЅР°Р·Р°Рґ РїС–СЃР»СЏ РїСЂРѕСЃС‚РѕСЋ")
            return True
        return False

    def unload_model_now(self) -> None:
        """РљРЅРѕРїРєР° РјРµРЅСЋ: РЅРµРіР°Р№РЅРѕ Р·РІС–Р»СЊРЅРёС‚Рё РІС–РґРµРѕРєР°СЂС‚Сѓ."""
        if self.model_keeper.unload():
            self.set_status("РњРѕРґРµР»СЊ РІРёРІР°РЅС‚Р°Р¶РµРЅРѕ Р· РІС–РґРµРѕРєР°СЂС‚Рё.")
        else:
            self.set_status("РњРѕРґРµР»СЊ СѓР¶Рµ РІРёРІР°РЅС‚Р°Р¶РµРЅР° Р°Р±Рѕ РЅРµСЋ РєРµСЂСѓС” Р·РѕРІРЅС–С€РЅС–Р№ СЃРµСЂРІРµСЂ.")

    def free_vram_now(self) -> None:
        """РљРЅРѕРїРєР° РјРµРЅСЋ: Р·РІС–Р»СЊРЅРёС‚Рё РІС–РґРµРѕРєР°СЂС‚Сѓ РїРѕРІРЅС–СЃС‚СЋ.

        РљСЂС–Рј С€С‚Р°С‚РЅРѕРіРѕ РІРёРІР°РЅС‚Р°Р¶РµРЅРЅСЏ РјРѕРґРµР»С– РїСЂРёР±РёСЂР°С” В«СЃРёСЂС–С‚СЃСЊРєС–В» РїСЂРѕС†РµСЃРё
        ``llama-server``, С‰Рѕ Р»РёС€РёР»РёСЃСЊ РІС–Рґ РїРѕРїРµСЂРµРґРЅС–С… Р·Р°РїСѓСЃРєС–РІ IDE. РЎР°РјРµ РІРѕРЅРё
        С‚СЂРёРјР°СЋС‚СЊ РІС–РґРµРѕРїР°Рј'СЏС‚СЊ, РєРѕР»Рё РєРѕСЂРёСЃС‚СѓРІР°С‡ Р·Р°РєСЂРёРІ РїСЂРѕРіСЂР°РјСѓ, Р° РіСЂСѓ
        Р·Р°РїСѓСЃС‚РёС‚Рё РЅРµ РјРѕР¶Рµ.
        """
        self._release_model_now()
        try:
            self.set_status("Р’С–РґРµРѕРїР°Рј'СЏС‚СЊ Р·РІС–Р»СЊРЅРµРЅРѕ: СЂСѓС€С–С— IDE Р·СѓРїРёРЅРµРЅРѕ. "
                            "Р’С–РґРµРѕРєР°СЂС‚Р° РІС–Р»СЊРЅР° РґР»СЏ С–РЅС€РёС… РїСЂРѕРіСЂР°Рј.")
        except tk.TclError:
            pass

    def toggle_autonomous(self) -> None:
        if self.autonomous_engine.state == autonomous.STATE_OFF:
            self.start_autonomous()
        else:
            self.stop_autonomous()

    def close_chat(self, chat_id: str) -> bool:
        """Р—Р°РєСЂРёС‚Рё С‡Р°С‚ Р·С– СЃРїРёСЃРєСѓ (С–РєРѕРЅРєР° В«Г—В» Сѓ СЂСЏРґРєСѓ СЃРµСЃС–С—).

        РџРѕРІРµРґС–РЅРєР° Р·Р°Р»РµР¶РёС‚СЊ РІС–Рґ С‚РѕРіРѕ, С‡Рё С” РІ С‡Р°С‚С– СЂРѕР±РѕС‚Р°:

        * **РїРѕСЂРѕР¶РЅС–Р№ С‡Р°С‚** (Р¶РѕРґРЅРѕРіРѕ РїРѕРІС–РґРѕРјР»РµРЅРЅСЏ) вЂ” РІРёРґР°Р»СЏС”С‚СЊСЃСЏ РїРѕРІРЅС–СЃС‚СЋ:
          С‚СЂРёРјР°С‚Рё РІ СЃРїРёСЃРєСѓ В«РќРѕРІРёР№ Р°РіРµРЅС‚В» Р±РµР· Р¶РѕРґРЅРѕС— СЂРµРїР»С–РєРё Р±РµР·РіР»СѓР·РґРѕ, С–
          СЃР°РјРµ С‡РµСЂРµР· С†Рµ Р»С–С‡РёР»СЊРЅРёРє Р·СЂРѕСЃС‚Р°РІ РїСЂРё РєРѕР¶РЅРѕРјСѓ РЅР°С‚РёСЃРєР°РЅРЅС– В«Г—В»;
        * **С‡Р°С‚ Р· С–СЃС‚РѕСЂС–С”СЋ** вЂ” Р°СЂС…С–РІСѓС”С‚СЊСЃСЏ, С‰РѕР± СЂРѕР±РѕС‚Р° РЅРµ РїСЂРѕРїР°Р»Р°;
        * СЏРєС‰Рѕ Р·Р°РєСЂРёРІР°СЋС‚СЊ Р°РєС‚РёРІРЅРёР№ вЂ” Р·РІС–Р»СЊРЅСЏС”РјРѕ Р°РіРµРЅС‚Р° Р№ РїРѕРєР°Р·СѓС”РјРѕ
          РЅР°СЃС‚СѓРїРЅРёР№ РЅР°СЏРІРЅРёР№ С‡Р°С‚ (Р° СЏРєС‰Рѕ С—С… РЅРµРјР°С” вЂ” РµРєСЂР°РЅ РІРёР±РѕСЂСѓ РїСЂРѕС”РєС‚Сѓ).

        Р Р°РЅС–С€Рµ С‚СѓС‚ Р±РµР·СѓРјРѕРІРЅРѕ РєР»РёРєР°РІСЃСЏ ``new_chat_session()``: РєРѕР¶РЅРµ
        РЅР°С‚РёСЃРєР°РЅРЅСЏ В«Г—В» СЃС‚РІРѕСЂСЋРІР°Р»Рѕ РќРћР’РР™ С‡Р°С‚, С– Р»С–С‡РёР»СЊРЅРёРє Сѓ РїР°РЅРµР»С– Р·СЂРѕСЃС‚Р°РІ
        Р·Р°РјС–СЃС‚СЊ С‚РѕРіРѕ, С‰РѕР± Р·РјРµРЅС€СѓРІР°С‚РёСЃСЊ.
        """
        chat = self.chat_store.get(chat_id)
        if chat is None:
            return False
        if self.agent.busy and getattr(self.chat_store, "active_id", "") == chat_id:
            self.set_status("РђРіРµРЅС‚ С‰Рµ РїСЂР°С†СЋС” вЂ” СЃРїРµСЂС€Сѓ Р·СѓРїРёРЅРё Р№РѕРіРѕ (в– ).")
            return False

        empty = chat.message_count == 0
        active = getattr(self.chat_store, "active_id", "") == chat_id
        # Р—Р°РґР°С‡С– С‡РµСЂРіРё, РїСЂРёРІ'СЏР·Р°РЅС– РґРѕ С†СЊРѕРіРѕ С‡Р°С‚Сѓ, РіРёРЅСѓС‚СЊ СЂР°Р·РѕРј С–Р· РЅРёРј.
        dropped = self.task_queue.remove_for_chat(chat_id)
        if dropped:
            self._update_queue_badge()
        # в”Ђв”Ђ Р§Р°С‚ Р· РђР РҐР†Р’РЈ Р·Р°РєСЂРёРІР°С”С‚СЊСЃСЏ РѕСЃС‚Р°С‚РѕС‡РЅРѕ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        # В«Г—В» РІ Р°СЂС…С–РІС– РѕР·РЅР°С‡Р°С” В«РІРёРґР°Р»РёС‚РёВ», С– РїС–РґС‚РІРµСЂРґР¶РµРЅРЅСЏ С‚СѓС‚ РѕР±РѕРІ'СЏР·РєРѕРІРµ:
        # РґС–СЏ РЅРµР·РІРѕСЂРѕС‚РЅР°. Р Р°РЅС–С€Рµ Р°СЂС…С–РІРЅРёР№ С‡Р°С‚ РїСЂРѕСЃС‚Рѕ Р°СЂС…С–РІСѓРІР°РІСЃСЏ С‰Рµ СЂР°Р· С–
        # Р· Р°СЂС…С–РІСѓ РЅРµ Р·РЅРёРєР°РІ вЂ” СЃР°РјРµ РЅР° С†Рµ СЃРєР°СЂР¶РёРІСЃСЏ РєРѕСЂРёСЃС‚СѓРІР°С‡.
        if chat.archived and not empty:
            if not messagebox.askyesno(
                    "Р’РёРґР°Р»РёС‚Рё С‡Р°С‚ Р· Р°СЂС…С–РІСѓ",
                    f"Р’РёРґР°Р»РёС‚Рё В«{chat.title or 'Р‘РµР· РЅР°Р·РІРё'}В» РѕСЃС‚Р°С‚РѕС‡РЅРѕ?\n\n"
                    "Р†СЃС‚РѕСЂС–СЏ СЂРѕР·РјРѕРІРё Р·РЅРёРєРЅРµ Р±РµР· РјРѕР¶Р»РёРІРѕСЃС‚С– РІС–РґРЅРѕРІР»РµРЅРЅСЏ.",
                    parent=self):
                return False
            self.chat_store.delete(chat_id)
            note = "Р§Р°С‚ РІРёРґР°Р»РµРЅРѕ Р· Р°СЂС…С–РІСѓ."
        elif empty:
            # РџРѕСЂРѕР¶РЅС–Р№ С‡Р°С‚ РЅРµРјР° С‡РѕРіРѕ Р°СЂС…С–РІСѓРІР°С‚Рё вЂ” РІРёРґР°Р»СЏС”РјРѕ РѕСЃС‚Р°С‚РѕС‡РЅРѕ.
            self.chat_store.delete(chat_id)
            note = "РџРѕСЂРѕР¶РЅС–Р№ С‡Р°С‚ РїСЂРёР±СЂР°РЅРѕ."
        else:
            self.chat_store.archive(chat_id, True)
            note = "Р§Р°С‚ РїРµСЂРµРЅРµСЃРµРЅРѕ РІ Р°СЂС…С–РІ."

        if active:
            # РљРѕРЅС‚РµРєСЃС‚ Р·Р°РєСЂРёС‚РѕРіРѕ С‡Р°С‚Сѓ Р±С–Р»СЊС€Рµ РЅРµ РїРѕС‚СЂС–Р±РµРЅ Сѓ СЃРµСЃС–С— Р°РіРµРЅС‚Р°:
            # С–РЅР°РєС€Рµ РЅР°СЃС‚СѓРїРЅРёР№ С‡Р°С‚ РїРѕС‡РёРЅР°РІСЃСЏ Р± С–Р· С‡СѓР¶РѕС— С–СЃС‚РѕСЂС–С—.
            try:
                self.agent.session.reset()
            except AttributeError:
                LOG.debug("РЎРµСЃС–СЏ Р°РіРµРЅС‚Р° С‰Рµ РЅРµ СЃС‚РІРѕСЂРµРЅР°", exc_info=True)
            self.chat_store.set_active("")
            self._save_all_silently()
            # РќРµ СЃС‚РІРѕСЂСЋС”РјРѕ РЅРѕРІРёР№ С‡Р°С‚ В«РїСЂРѕ Р·Р°РїР°СЃВ»: РїРѕРєР°Р·СѓС”РјРѕ РЅР°СЏРІРЅРёР№, Р° СЏРєС‰Рѕ
            # С—С… РЅРµРјР°С” вЂ” РµРєСЂР°РЅ РІРёР±РѕСЂСѓ РїСЂРѕС”РєС‚Сѓ.
            remaining = self.chat_store.visible()
            if remaining:
                self.open_chat(remaining[0].id)
            else:
                try:
                    self.chat.reset()
                except (tk.TclError, AttributeError):
                    pass
                self._sync_chat_title()
                self._sync_chat_queue()
                self._show_project_gate(
                    reason="Р§Р°С‚С–РІ РЅРµРјР°С”. Р’РёР±РµСЂРё РїСЂРѕС”РєС‚ С– СЃС‚РІРѕСЂРё РЅРѕРІРёР№ С‡Р°С‚.")
        self.chat_list.refresh()
        self.nav_refresh_history()
        self.set_status(note)
        return True

    def _wake_on_action(self, _event=None) -> None:
        """Р‘СѓРґСЊ-СЏРєР° РґС–СЏ РєРѕСЂРёСЃС‚СѓРІР°С‡Р° СЃРєРёРґР°С” С‚Р°Р№РјРµСЂ РїСЂРѕСЃС‚РѕСЋ.

        РљР»РёС‡РµС‚СЊСЃСЏ РЅР° РєРѕР¶РЅРµ РЅР°С‚РёСЃРєР°РЅРЅСЏ РєР»Р°РІС–С€С– Р№ РєРѕР¶РµРЅ РєР»С–Рє, С‚РѕРјСѓ СЂРѕР±РѕС‚Р°
        С‚СѓС‚ РјР°С” Р±СѓС‚Рё РјС–РЅС–РјР°Р»СЊРЅРѕСЋ: РѕРґРЅРµ РїСЂРёСЃРІРѕС”РЅРЅСЏ С‡Р°СЃСѓ. РЎРєРёРґР°РЅРЅСЏ С‚Р°Р№РјРµСЂР°
        РЅРµ РјР°С” РєРёРґР°С‚Рё РІРёРЅСЏС‚РєС–РІ вЂ” РІРѕРЅРѕ РІРёСЃРёС‚СЊ РЅР° ``bind_all`` С– Р·Р±С–Р№
        Р·Р»Р°РјР°РІ Р±Рё РІРµСЃСЊ РІРІС–Рґ Сѓ Р·Р°СЃС‚РѕСЃСѓРЅРєСѓ.
        """
        tracker = getattr(getattr(self, "model_keeper", None), "tracker", None)
        if tracker is not None:
            tracker.last_touch = time.time()

    def _confirm_command(self, command: str) -> bool:
        """Р”РѕР·РІС–Р» РЅР° РєРѕРјР°РЅРґСѓ.

        РђРІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј: Р°РіРµРЅС‚ РЅРµ РїРёС‚Р°С” РїС–РґС‚РІРµСЂРґР¶РµРЅРЅСЏ Р№ РЅРµ Р±Р»РѕРєСѓС”С‚СЊСЃСЏ.
        Р”С–Р°Р»РѕРі РїРѕРєР°Р·СѓС”РјРѕ Р»РёС€Рµ С‚РѕРґС–, РєРѕР»Рё РєРѕСЂРёСЃС‚СѓРІР°С‡ СЃР°Рј СѓРІС–РјРєРЅСѓРІ
        В«РїРёС‚Р°С‚Рё РґРѕР·РІС–Р» РЅР° РєРѕРјР°РЅРґРёВ» РІ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏС…. Р Р°РЅС–С€Рµ РґС–Р°Р»РѕРі
        Р·'СЏРІР»СЏРІСЃСЏ Р·Р°РІР¶РґРё С– Р·СѓРїРёРЅСЏРІ СЂРѕР±РѕС‚Сѓ РїРѕСЃРµСЂРµРґ Р·Р°РІРґР°РЅРЅСЏ вЂ” РЅР° РЅСЊРѕРіРѕ
        РЅС–С…С‚Рѕ РЅРµ РІС–РґРїРѕРІС–РґР°РІ, С– Р°РіРµРЅС‚ С‡РµРєР°РІ РґРѕ 10 С…РІРёР»РёРЅ.
        """
        if not self.settings.agent.confirm_commands:
            return True
        if threading.current_thread() is threading.main_thread():
            return self._ask_command(command)
        done = threading.Event()
        answer = {"value": False}

        def ask() -> None:
            try:
                answer["value"] = self._ask_command(command)
            finally:
                done.set()

        self._ui_call(ask)
        # Р›СЋРґРёРЅР° РјРѕР¶Рµ РґСѓРјР°С‚Рё РґРѕРІРіРѕ вЂ” Р°Р»Рµ Р°РіРµРЅС‚ РЅРµ РјР°С” РІРёСЃС–С‚Рё РІС–С‡РЅРѕ.
        if not done.wait(timeout=600):
            return False
        return bool(answer["value"])

    def _ask_command(self, command: str) -> bool:
        return messagebox.askyesno(
            "Р”РѕР·РІРѕР»РёС‚Рё РєРѕРјР°РЅРґСѓ?",
            f"РђРіРµРЅС‚ С…РѕС‡Рµ РІРёРєРѕРЅР°С‚Рё:\n\n{command}\n\nР”РѕР·РІРѕР»РёС‚Рё?",
            parent=self,
        )

    # в”Ђв”Ђ С‡РµСЂРіР° Р·Р°РґР°С‡ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _queue_from_chat(self, text: str) -> int:
        added = self.queue_panel.add_text(text)
        self._update_queue_badge()
        if added:
            self.show_side("queue")
        return added

    def _split_task_to_queue(self, text: str) -> None:
        """РЎРєР»Р°СЃС‚Рё РїР»Р°РЅ РІРµР»РёРєРѕРіРѕ Р·Р°РІРґР°РЅРЅСЏ Р»РѕРєР°Р»СЊРЅРѕСЋ РјРѕРґРµР»Р»СЋ Р№ РЅР°РїРѕРІРЅРёС‚Рё С‡РµСЂРіСѓ.

        Р—РјС–СЃС‚ РєСЂРѕРєС–РІ РІРёР·РЅР°С‡Р°С” РЎРђРњРђ РјРѕРґРµР»СЊ: РѕРєСЂРµРјРёРј РєРѕСЂРѕС‚РєРёРј Р·Р°РїРёС‚РѕРј РІРѕРЅР°
        РїРѕРІРµСЂС‚Р°С” РЅСѓРјРµСЂРѕРІР°РЅРёР№ СЃРїРёСЃРѕРє С–Р· РЅР°Р·РІР°РјРё, РѕРїРёСЃР°РјРё Р№ Р·Р°Р»РµР¶РЅРѕСЃС‚СЏРјРё.
        Р¦РµР№ РјРµС‚РѕРґ Р»РёС€Рµ РґР°С” С—Р№ РєРѕРЅС‚РµРєСЃС‚ РїСЂРѕС”РєС‚Сѓ (СЃС‚РµРє С– С„Р°Р№Р»Рё), РїРµСЂРµРІС–СЂСЏС”
        РІС–РґРїРѕРІС–РґСЊ С– РїРµСЂРµРґР°С” РєСЂРѕРєРё РІ :class:`queue_engine.TaskQueue`.

        РЇРєС‰Рѕ РјРѕРґРµР»СЊ РЅРµ Р·РјРѕРіР»Р° РґР°С‚Рё РїР»Р°РЅ (РЅРµРјР°С” Р·РІ'СЏР·РєСѓ, РґРёРІРЅР° РІС–РґРїРѕРІС–РґСЊ),
        СЃС‚Р°РІРёРјРѕ Р·Р°РІРґР°РЅРЅСЏ РѕРґРЅС–С”СЋ Р·Р°РґР°С‡РµСЋ вЂ” РєСЂР°С‰Рµ С‚Р°Рє, РЅС–Р¶ РЅС–С‡РѕРіРѕ, С–
        РїРѕРІС–РґРѕРјР»СЏС”РјРѕ РїСЂРёС‡РёРЅСѓ Р·Р°РјС–СЃС‚СЊ РІРёРіР°РґР°РЅРѕРіРѕ РїР»Р°РЅСѓ.
        """
        clean = (text or "").strip()
        if not clean:
            return
        if self.agent.busy:
            self.set_status("РђРіРµРЅС‚ Р·Р°Р№РЅСЏС‚РёР№ вЂ” СЂРѕР·Р±РёС‚С‚СЏ РїРѕСЃС‚Р°РІРёРјРѕ РїС–СЃР»СЏ Р·Р°РІРµСЂС€РµРЅРЅСЏ.")
            return
        if getattr(self, "_planning", False):
            LOG.info("РџР»Р°РЅСѓРІР°РЅРЅСЏ РІР¶Рµ С‚СЂРёРІР°С” вЂ” РїРѕРІС‚РѕСЂРЅРёР№ Р·Р°РїРёС‚ С–РіРЅРѕСЂСѓСЋ")
            return
        # Р—Р°С…РёСЃС‚ РІС–Рґ РїРѕРґРІС–Р№РЅРѕРіРѕ СЂРѕР·Р±РёС‚С‚СЏ: Р·Р°РїРёС‚ РјС–Рі РїСЂРёР№С‚Рё РґРІС–С‡С– (РїРѕРґРІС–Р№РЅРёР№
        # РєР»С–Рє, Enter+РєРЅРѕРїРєР°, РїРѕРІС‚РѕСЂРЅРёР№ РІРёРєР»РёРє Р·С– СЃС‚СЂС–С‡РєРё). Р”РІР° РїР»Р°РЅРё РїС–РґСЂСЏРґ
        # РґР°Р»Рё 9 С– 12 РєСЂРѕРєС–РІ Сѓ С‡РµСЂР·С– вЂ” Р·Р°РґР°С‡С– РґСѓР±Р»СЋРІР°Р»РёСЃСЊ, С– Р°РіРµРЅС‚ СЂРѕР±РёРІ
        # РѕРґРЅСѓ Р№ С‚Сѓ СЃР°РјСѓ СЂРѕР±РѕС‚Сѓ РґРІС–С‡С–.
        now = time.time()
        last = getattr(self, "_split_request", (0.0, ""))
        if last[1] == clean and (now - last[0]) < 5.0:
            LOG.info("РџРѕРІС‚РѕСЂРЅРµ СЂРѕР·Р±РёС‚С‚СЏ С‚РѕРіРѕ СЃР°РјРѕРіРѕ Р·Р°РїРёС‚Сѓ вЂ” РїСЂРѕРїСѓСЃРєР°СЋ")
            return
        self._split_request = (now, clean)
        self._planning = True
        self.show_bottom("tasks")
        self.set_status("РЎРєР»Р°РґР°СЋ РїР»Р°РЅ РєСЂРѕРєС–РІ Р»РѕРєР°Р»СЊРЅРѕСЋ РјРѕРґРµР»Р»СЋвЂ¦")
        # РЎС‚Р°РЅ Р°РіРµРЅС‚Р° РјР°С” РїРѕРєР°Р·Р°С‚Рё, С‰Рѕ СЂРѕР±РѕС‚Р° Р™Р”Р•. Р‘РµР· С†СЊРѕРіРѕ РІС–РєРЅРѕ
        # РїРѕРєР°Р·СѓРІР°Р»Рѕ В«Р°РіРµРЅС‚: РѕС‡С–РєСѓС”В», С…РѕС‡ РјРѕРґРµР»СЊ Р°РєС‚РёРІРЅРѕ СЃРєР»Р°РґР°Р»Р° РїР»Р°РЅ вЂ”
        # РєРѕСЂРёСЃС‚СѓРІР°С‡ РґСѓРјР°РІ, С‰Рѕ РЅР°С‚РёСЃРє РЅРµ СЃРїСЂР°С†СЋРІР°РІ (СЃР°РјРµ С‚Р°Рє С– СЃС‚Р°Р»РѕСЃСЏ
        # Сѓ Р¶РёРІРѕРјСѓ РїСЂРѕРіРѕРЅС–: РїР»Р°РЅ СЃРєР»Р°РґР°РІСЃСЏ 15 СЃРµРєСѓРЅРґ, Р° С–РЅРґРёРєР°С‚РѕСЂ СЃС‚РѕСЏРІ).
        self._set_agent_state("РїСЂР°С†СЋС”")
        try:
            self.chat.set_busy(True)
        except (tk.TclError, AttributeError):
            pass
        # РљРѕРЅС‚РµРєСЃС‚ РїСЂРѕС”РєС‚Сѓ Р№ РїРµСЂРµР»С–Рє С–РЅСЃС‚СЂСѓРјРµРЅС‚С–РІ: Р±РµР· РЅРёС… РјРѕРґРµР»СЊ РїР»Р°РЅСѓС”
        # В«РІР·Р°РіР°Р»С–В» Р№ С‡Р°СЃС‚Рѕ РїСЂРѕРїРѕРЅСѓС” С‡СѓР¶РёР№ СЃС‚РµРє.
        root = self._project_root()
        context = ""
        try:
            context = deep_mode.project_context(root)
        except Exception:  # noqa: BLE001 - РєРѕРЅС‚РµРєСЃС‚ РЅРµ РјР°С” Р»Р°РјР°С‚Рё РїР»Р°РЅСѓРІР°РЅРЅСЏ
            LOG.debug("РљРѕРЅС‚РµРєСЃС‚ РїСЂРѕС”РєС‚Сѓ РЅРµРґРѕСЃС‚СѓРїРЅРёР№", exc_info=True)
        tool_names = [schema["function"]["name"] for schema in agent_tools.TOOL_SCHEMAS]
        llm = self.settings.llm

        def work() -> None:
            result = task_planner.plan_with_model(
                clean, llm, context=context, tool_names=tool_names)
            self._ui_call(self._after_split, clean, result)

        threading.Thread(target=work, daemon=True).start()

    def _after_split(self, brief: str, result: "task_planner.PlanResult") -> None:
        """РџРѕСЃС‚Р°РІРёС‚Рё РїР»Р°РЅ РјРѕРґРµР»С– РІ С‡РµСЂРіСѓ Р№ РѕРґСЂР°Р·Сѓ РїРѕС‡Р°С‚Рё РІРёРєРѕРЅР°РЅРЅСЏ."""
        self._planning = False
        # РљСЂРѕРєРё РїР»Р°РЅСѓ РЅР°СЂРѕРґР¶СѓСЋС‚СЊСЃСЏ Р· РїРѕРІС–РґРѕРјР»РµРЅРЅСЏ РІ С‡Р°С‚С–, С‚РѕР¶ РІРѕРЅРё РЅР°Р»РµР¶Р°С‚СЊ
        # Р№РѕРјСѓ Р¶: С–РЅР°РєС€Рµ РїС–СЃР»СЏ РІРёРґР°Р»РµРЅРЅСЏ С‡Р°С‚Сѓ Р·Р°РґР°С‡С– Р»РёС€Р°Р»РёСЃСЊ Сѓ С‡РµСЂР·С–
        # В«СЃРёСЂРѕС‚Р°РјРёВ» Р№ Р°РіРµРЅС‚ РїСЂРѕРґРѕРІР¶СѓРІР°РІ С—С… РІРёРєРѕРЅСѓРІР°С‚Рё.
        owner = self._active_chat_id()
        steps = result.steps if result is not None else []

        if not steps:
            # РџР»Р°РЅ РЅРµ СЃРєР»Р°РІСЃСЏ вЂ” СЃС‚Р°РІРёРјРѕ Р·Р°РїРёС‚ РћР”РќР†Р„Р® Р·Р°РґР°С‡РµСЋ.
            reason = getattr(result, "error", "") or "РЅРµРІС–РґРѕРјР° РїСЂРёС‡РёРЅР°"
            task = self.task_queue.add(brief, chat_id=owner)
            if task is not None:
                task.add_history("note", f"РїР»Р°РЅ РЅРµ СЃРєР»Р°РІСЃСЏ: {reason[:160]}")
                self.task_queue.save()
            self._set_agent_state("РѕС‡С–РєСѓС”")
            self._finish_planning_ui()
            self.set_status(f"РџР»Р°РЅ РЅРµ СЃРєР»Р°РІСЃСЏ ({reason[:60]}) вЂ” Р·Р°РІРґР°РЅРЅСЏ РІ С‡РµСЂР·С– РѕРґРЅРёРј РєСЂРѕРєРѕРј.")
            self._update_queue_badge()
            # РњРѕРґРµР»СЊ РЅРµРґРѕСЃС‚СѓРїРЅР° вЂ” РїСЂРѕР±СѓС”РјРѕ РІРёРєРѕРЅР°С‚Рё СЏРє Р·РІРёС‡Р°Р№РЅРёР№ Р·Р°РїРёС‚,
            # С‰РѕР± РєРѕСЂРёСЃС‚СѓРІР°С‡ РЅРµ Р»РёС€РёРІСЃСЏ РЅС– Р· С‡РёРј.
            if not task_planner_available(self.settings):
                return
            self._start_plan_execution()
            return

        # Р”СЂСѓРіРёР№ Р·Р°С…РёСЃС‚ РІС–Рґ РґСѓР±Р»СЋРІР°РЅРЅСЏ вЂ” Р·Р° РЎРљР›РђР”РћРњ РїР»Р°РЅСѓ. РџРµСЂС€РѕРіРѕ (Р·Р°
        # С‚РµРєСЃС‚РѕРј Р·Р°РїРёС‚Сѓ) РЅРµ РґРѕСЃРёС‚СЊ: РїРѕРєРё РјРѕРґРµР»СЊ СЃРєР»Р°РґР°С” РїР»Р°РЅ, РєРѕСЂРёСЃС‚СѓРІР°С‡
        # РјС–Рі РЅР°РґС–СЃР»Р°С‚Рё С‚РѕР№ СЃР°РјРёР№ С‚РµРєСЃС‚ С–С‰Рµ СЂР°Р·, С– РѕР±РёРґРІР° РїР»Р°РЅРё Р»СЏРіР°Р»Рё РІ
        # С‡РµСЂРіСѓ (РЅР° СЃРєСЂС–РЅС€РѕС‚С–: 24 Р·Р°РґР°С‡С– Р·Р°РјС–СЃС‚СЊ 12).
        key = (brief.strip()[:200], tuple(step.title.strip() for step in steps))
        if getattr(self, "_last_plan_key", None) == key:
            LOG.info("РўРѕР№ СЃР°РјРёР№ РїР»Р°РЅ СѓР¶Рµ РґРѕРґР°РЅРѕ вЂ” РїСЂРѕРїСѓСЃРєР°СЋ РґСѓР±Р»СЊ")
            self._finish_planning_ui()
            return
        self._last_plan_key = key
        self._last_plan = list(steps)

        # РќРѕРІРµ РІРµР»РёРєРµ Р·Р°РІРґР°РЅРЅСЏ Р·Р°РјС–РЅСЋС” РїРѕРїРµСЂРµРґРЅС–Р№ РЅРµР·Р°РІРµСЂС€РµРЅРёР№ РїР»Р°РЅ С†СЊРѕРіРѕ
        # С‡Р°С‚Сѓ: С–РЅР°РєС€Рµ СЃС‚Р°СЂР° С‡РµСЂРіР° Р·РјС–С€СѓРІР°Р»Р°СЃСЊ С–Р· РЅРѕРІРѕСЋ РјРµС‚РѕСЋ.
        dropped = self.task_queue.drop_plan(chat_id=owner)
        created = self.task_queue.add_steps(result.rows(), chat_id=owner, goal=brief)
        # РЎРјСѓРіР° РµС‚Р°РїС–РІ РЅР°Рґ РєРѕРјРїРѕР·РµСЂРѕРј РїРѕРєР°Р·СѓС” С‚РѕР№ СЃР°РјРёР№ РїРѕРґС–Р».
        try:
            stages = [task_plan.stage_from_text(step.title, index)
                      for index, step in enumerate(steps)]
            self.chat.stage_strip.set_stages(stages, goal=brief)
        except (tk.TclError, AttributeError):
            LOG.debug("РЎРјСѓРіР° РµС‚Р°РїС–РІ РЅРµРґРѕСЃС‚СѓРїРЅР°", exc_info=True)

        total = len(created)
        LOG.info("Р—Р°РІРґР°РЅРЅСЏ СЂРѕР·Р±РёС‚Рѕ РЅР° %d РєСЂРѕРєС–РІ", total)
        self._finish_planning_ui()
        # РЈ С‡Р°С‚С– РїРѕРєР°Р·СѓС”РјРѕ СЃР°Рј РїР»Р°РЅ вЂ” РєРѕСЂРёСЃС‚СѓРІР°С‡ Р±Р°С‡РёС‚СЊ, С‰Рѕ СЃР°РјРµ СЂРѕР±РёС‚РёРјРµ
        # Р°РіРµРЅС‚, С‰Рµ РґРѕ РїРѕС‡Р°С‚РєСѓ СЂРѕР±РѕС‚Рё.
        try:
            self.chat._note(task_planner.plan_markdown(brief, steps))
        except (tk.TclError, AttributeError):
            LOG.debug("РџР»Р°РЅ РЅРµ РїРѕС‚СЂР°РїРёРІ Сѓ С‡Р°С‚", exc_info=True)
        self.set_status(
            f"РџР»Р°РЅ РіРѕС‚РѕРІРёР№: {total} РєСЂРѕРєС–РІ Сѓ С‡РµСЂР·С–"
            + (f" (Р·Р°РјС–РЅРµРЅРѕ {dropped} СЃС‚Р°СЂРёС…)" if dropped else ""))
        self._update_queue_badge()
        self.task_center.refresh()
        self._start_plan_execution()

    def _finish_planning_ui(self) -> None:
        """РџРѕРІРµСЂРЅСѓС‚Рё С–РЅРґРёРєР°С‚РѕСЂРё РїС–СЃР»СЏ СЃРєР»Р°РґР°РЅРЅСЏ РїР»Р°РЅСѓ."""
        self._set_agent_state("РѕС‡С–РєСѓС”")
        try:
            self.chat.set_busy(False)
        except (tk.TclError, AttributeError):
            pass

    def _start_plan_execution(self) -> None:
        """Р—Р°РїСѓСЃС‚РёС‚Рё РїРµСЂС€РёР№ РіРѕС‚РѕРІРёР№ РєСЂРѕРє РїР»Р°РЅСѓ (С‡РµСЂРµР· РІРёРєРѕРЅР°РІРµС†СЊ)."""
        if self.task_queue.paused or self.agent.busy:
            return
        self.executor.start_next()
        self._update_queue_badge()

    # в”Ђв”Ђ РєСЂРѕРє РїР»Р°РЅСѓ РІРёРєРѕРЅСѓС” СЃРїСЂР°РІР¶РЅС–Р№ Р°РіРµРЅС‚ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _run_plan_step(self, task: queue_engine.QueueTask, prompt: str) -> bool:
        """Р—Р°РїСѓСЃС‚РёС‚Рё РѕРґРёРЅ РєСЂРѕРє РїР»Р°РЅСѓ СЂРµР°Р»СЊРЅРёРј Р°РіРµРЅС‚СЃСЊРєРёРј С†РёРєР»РѕРј.

        Р’РёРєР»РёРєР°С”С‚СЊСЃСЏ РІРёРєРѕРЅР°РІС†РµРј: РІС–РЅ СѓР¶Рµ РїРѕР·РЅР°С‡РёРІ РєСЂРѕРє СЏРє Р°РєС‚РёРІРЅРёР№. РўСѓС‚ РјРё
        Р»РёС€Рµ РІС–РґРґР°С”РјРѕ СЃС„РѕСЂРјСѓР»СЊРѕРІР°РЅРёР№ Р·Р°РїРёС‚ С‚РѕРјСѓ СЃР°РјРѕРјСѓ Р°РіРµРЅС‚Сѓ, С‰Рѕ РїСЂР°С†СЋС” РІ
        С‡Р°С‚С–, вЂ” Р· С–РЅСЃС‚СЂСѓРјРµРЅС‚Р°РјРё, РґРѕР·РІРѕР»Р°РјРё Р№ MCP.

        РџРѕРІРµСЂС‚Р°С” ``False``, СЏРєС‰Рѕ Р·Р°РїРёС‚ РЅРµ РїС–С€РѕРІ (Р°РіРµРЅС‚ Р·Р°Р№РЅСЏС‚РёР№ Р°Р±Рѕ РЅРµРјР°С”
        С‚РµРєРё): С‚РѕРґС– РІРёРєРѕРЅР°РІРµС†СЊ РїРѕРІРµСЂРЅРµ РєСЂРѕРє Сѓ С‡РµСЂРіСѓ, Р° РЅРµ Р»РёС€РёС‚СЊ Р№РѕРіРѕ
        В«РІРёСЃС–С‚РёВ» РІ СЃС‚Р°РЅС– В«Р°РЅР°Р»С–Р·В».
        """
        # РљСЂРѕРє Р·С– СЃРєС–Р»Р° РІРёРєРѕРЅСѓС” СЃР°РјРµ СЃРєС–Р»: Р№РѕРіРѕ С–РЅСЃС‚СЂСѓРєС†С–СЏ РІР°Р¶Р»РёРІС–С€Р° Р·Р°
        # Р·Р°РіР°Р»СЊРЅРёР№ С‚РµРєСЃС‚ РєСЂРѕРєСѓ.
        if task.skill:
            skill = self.skill_book.get(task.skill)
            if skill is not None:
                prompt = self._skill_prompt(skill)
        self._plan_step_active = True
        self._running_task_id = task.id
        self.show_chat(True)
        self._set_agent_state("РїСЂР°С†СЋС”")
        label = f"{task.number:02d}" if task.number else "вЂ”"
        self.set_status(f"РљСЂРѕРє {label}: {task.title[:60]}вЂ¦")
        chat = self.chat_store.active()
        if chat is not None:
            self.chat_store.set_status(chat.id, "working")
            self.chat_list.update_row_status(chat.id, "working")
        self.task_center.refresh()
        # ``plan_step=True``: С†Рµ РіРѕС‚РѕРІРёР№ РєСЂРѕРє РїР»Р°РЅСѓ. Р РѕР·Р±РёРІР°С‚Рё Р№РѕРіРѕ РІРґСЂСѓРіРµ
        # РЅРµ РјРѕР¶РЅР° вЂ” С–РЅР°РєС€Рµ Р·Р°РјС–СЃС‚СЊ РІРёРєРѕРЅР°РЅРЅСЏ Р·Р°РїСѓСЃРєР°Р»РѕСЃСЊ РЅРѕРІРµ РїР»Р°РЅСѓРІР°РЅРЅСЏ
        # (СЂРµРєСѓСЂСЃС–СЏ, Сѓ СЏРєС–Р№ Р°РіРµРЅС‚ РЅРµ СЂРѕР±РёРІ Р¶РѕРґРЅРѕС— С„Р°Р№Р»РѕРІРѕС— РґС–С—).
        started = self.chat._send(prompt, deep=False, plan_step=True)
        if not started:
            self._plan_step_active = False
            self._running_task_id = ""
            LOG.info("РљСЂРѕРє %s РЅРµ Р·Р°РїСѓСЃС‚РёРІСЃСЏ вЂ” РїРѕРІРµСЂС‚Р°СЋ РІ С‡РµСЂРіСѓ", task.id)
        return bool(started)

    def _queue_skill(self, skill: skills_module.Skill) -> None:
        added = self.queue_panel.add_text(self._skill_prompt(skill), skill=skill.name)
        self._update_queue_badge()
        self.set_status(f"РЎРєС–Р» В«{skill.name}В» РґРѕРґР°РЅРѕ РІ С‡РµСЂРіСѓ ({added})")

    # в”Ђв”Ђ РєРµСЂСѓРІР°РЅРЅСЏ С‡РµСЂРіРѕСЋ Р· С†РµРЅС‚СЂСѓ Р·Р°РІРґР°РЅСЊ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def pause_queue(self) -> None:
        """РџР°СѓР·Р°: РЅРѕРІС– РєСЂРѕРєРё РЅРµ СЃС‚Р°СЂС‚СѓСЋС‚СЊ, РїРѕС‚РѕС‡РЅРёР№ РґРѕРІРѕРґРёС‚СЊ СЂРѕР±РѕС‚Сѓ."""
        self.task_queue.set_paused(True)
        self.set_status("Р§РµСЂРіСѓ РїРѕСЃС‚Р°РІР»РµРЅРѕ РЅР° РїР°СѓР·Сѓ вЂ” РїРѕС‚РѕС‡РЅРёР№ РєСЂРѕРє РґРѕС‚СЏРіРЅРµ СЂРѕР±РѕС‚Сѓ.")
        self._update_queue_badge()

    def resume_queue(self) -> None:
        """РџСЂРѕРґРѕРІР¶РёС‚Рё С‡РµСЂРіСѓ (Р·РЅС–РјР°С” РїР°СѓР·Сѓ Р№ РїРѕРІРµСЂС‚Р°С” РїСЂРёР·СѓРїРёРЅРµРЅС– РєСЂРѕРєРё)."""
        self.executor.resume()
        self._update_queue_badge()
        self._start_plan_execution()

    def stop_plan(self) -> None:
        """Р—СѓРїРёРЅРёС‚Рё РІРёРєРѕРЅР°РЅРЅСЏ: Р°РєС‚РёРІРЅРёР№ РєСЂРѕРє в†’ В«РїСЂРёР·СѓРїРёРЅРµРЅРѕВ», Р°РіРµРЅС‚ СЃРїРёРЅСЏС”С‚СЊСЃСЏ."""
        self.executor.stop(reason="Р·СѓРїРёРЅРµРЅРѕ РєРѕСЂРёСЃС‚СѓРІР°С‡РµРј")
        if self.agent.busy:
            self.agent.cancel()
        self._plan_step_active = False
        self._running_task_id = ""
        self._set_agent_state("РѕС‡С–РєСѓС”")
        self.set_status("Р’РёРєРѕРЅР°РЅРЅСЏ Р·СѓРїРёРЅРµРЅРѕ. РќР°С‚РёСЃРЅРё В«РџСЂРѕРґРѕРІР¶РёС‚РёВ», С‰РѕР± С–С‚Рё РґР°Р»С–.")
        self._update_queue_badge()

    def retry_plan_task(self, task_id: str) -> None:
        """РџРѕРІС‚РѕСЂРёС‚Рё РЅРµРІРґР°Р»РёР№ РєСЂРѕРє (РїС–Рґ РєРѕРЅС‚СЂРѕР»РµРј Р»С–РјС–С‚Сѓ СЃРїСЂРѕР±)."""
        if self.executor.retry(task_id):
            task = self.task_queue.get(task_id)
            label = f"{task.number:02d}" if task and task.number else "вЂ”"
            self.set_status(f"РљСЂРѕРє {label} РїРѕРІРµСЂРЅСѓС‚Рѕ РІ С‡РµСЂРіСѓ.")
        else:
            self.set_status("Р¦РµР№ РєСЂРѕРє Р·Р°СЂР°Р· РЅРµ РјРѕР¶РЅР° РїРѕРІС‚РѕСЂРёС‚Рё.")
        self._update_queue_badge()

    def clear_plan_finished(self) -> None:
        """РџСЂРёР±СЂР°С‚Рё Р·Р°РІРµСЂС€РµРЅС– РєСЂРѕРєРё Р· С‡РµСЂРіРё."""
        removed = self.executor.clear_finished()
        self.set_status(f"РџСЂРёР±СЂР°РЅРѕ Р·Р°РІРµСЂС€РµРЅРёС… РєСЂРѕРєС–РІ: {removed}")
        self._update_queue_badge()

    def _queue_from_panel(self, text: str) -> None:
        """РљСЂРѕРє, РґРѕРґР°РЅРёР№ РІСЂСѓС‡РЅСѓ Р· С†РµРЅС‚СЂСѓ Р·Р°РІРґР°РЅСЊ."""
        task = self.task_queue.add(text, chat_id=self._active_chat_id(),
                                   origin=queue_engine.ORIGIN_USER)
        if task is not None:
            self.task_queue.renumber(chat_id=self._active_chat_id())
            self.set_status("РљСЂРѕРє РґРѕРґР°РЅРѕ РІ С‡РµСЂРіСѓ.")
        self._update_queue_badge()

    def _open_project_file(self, name: str) -> None:
        """Р’С–РґРєСЂРёС‚Рё С„Р°Р№Р» РєСЂРѕРєСѓ РІ СЂРµРґР°РєС‚РѕСЂС– (С€Р»СЏС… РІС–РґРЅРѕСЃРЅРёР№ РґРѕ РїСЂРѕС”РєС‚Сѓ)."""
        root = self._project_root()
        if root is None:
            self.set_status("РЎРїРµСЂС€Сѓ РІРёР±РµСЂРё С‚РµРєСѓ РїСЂРѕС”РєС‚Сѓ.")
            return
        candidate = Path(name)
        if not candidate.is_absolute():
            candidate = Path(root) / name
        if not candidate.exists():
            # РњРѕРґРµР»СЊ РјРѕРіР»Р° РІРєР°Р·Р°С‚Рё Р»РёС€Рµ С–Рј'СЏ С„Р°Р№Р»Сѓ вЂ” С€СѓРєР°С”РјРѕ РІ РїСЂРѕС”РєС‚С–.
            found = next(iter(Path(root).rglob(Path(name).name)), None)
            if found is None:
                self.set_status(f"Р¤Р°Р№Р» РЅРµ Р·РЅР°Р№РґРµРЅРѕ: {name}")
                return
            candidate = found
        self.open_path(candidate)

    def replan_now(self) -> None:
        """РџРѕРїСЂРѕСЃРёС‚Рё РјРѕРґРµР»СЊ РїРµСЂРµРїР»Р°РЅСѓРІР°С‚Рё Р·Р°Р»РёС€РѕРє СЂРѕР±РѕС‡РѕРіРѕ РїР»Р°РЅСѓ.

        Р’РёРєРѕСЂРёСЃС‚РѕРІСѓС”С‚СЊСЃСЏ, РєРѕР»Рё РїС–РґС…С–Рґ РЅРµ СЃРїСЂР°С†СЋРІР°РІ: РјРѕРґРµР»СЊ Р±Р°С‡РёС‚СЊ РїРѕС‚РѕС‡РЅРёР№
        СЃС‚Р°РЅ РєСЂРѕРєС–РІ С– РїРѕРІРµСЂС‚Р°С” РѕРЅРѕРІР»РµРЅРёР№ СЃРїРёСЃРѕРє. РЈР¶Рµ РІРёРєРѕРЅР°РЅС– РєСЂРѕРєРё
        Р·Р±РµСЂС–РіР°СЋС‚СЊСЃСЏ вЂ” РІРѕРЅРё СЂРµР°Р»СЊРЅРѕ Р·РјС–РЅРёР»Рё С„Р°Р№Р»Рё.
        """
        if getattr(self, "_planning", False):
            self.set_status("РџР»Р°РЅСѓРІР°РЅРЅСЏ РІР¶Рµ С‚СЂРёРІР°С”.")
            return
        owner = self._active_chat_id()
        plan = self.task_queue.plan_tasks(chat_id=owner)
        if not plan:
            self.set_status("РќРµРјР°С” РїР»Р°РЅСѓ РґР»СЏ РїРµСЂРµРїР»Р°РЅСѓРІР°РЅРЅСЏ.")
            return
        goal = next((str(task.goal) for task in plan if task.goal), "")
        if not goal:
            goal = str(getattr(self, "_last_goal", "") or "РїСЂРѕРґРѕРІР¶РёС‚Рё СЂРѕР±РѕС‚Сѓ")
        self._planning = True
        self.set_status("РњРѕРґРµР»СЊ РїРµСЂРµРїР»Р°РЅРѕРІСѓС” СЂРѕР±РѕС‚СѓвЂ¦")
        self._set_agent_state("РїСЂР°С†СЋС”")
        root = self._project_root()
        context = ""
        try:
            context = deep_mode.project_context(root)
        except Exception:  # noqa: BLE001
            LOG.debug("РљРѕРЅС‚РµРєСЃС‚ РґР»СЏ РїРµСЂРµРїР»Р°РЅСѓРІР°РЅРЅСЏ РЅРµРґРѕСЃС‚СѓРїРЅРёР№", exc_info=True)
        existing = task_planner.plan_as_text(plan)
        tool_names = [schema["function"]["name"] for schema in agent_tools.TOOL_SCHEMAS]
        llm = self.settings.llm

        def work() -> None:
            result = task_planner.plan_with_model(
                goal, llm, context=context, tool_names=tool_names,
                existing=existing, replan=True)
            self._ui_call(self._after_replan, result)

        threading.Thread(target=work, daemon=True).start()

    def _after_replan(self, result: "task_planner.PlanResult") -> None:
        """Р—Р°РјС–РЅРёС‚Рё РЅРµР·Р°РІРµСЂС€РµРЅС– РєСЂРѕРєРё РЅРѕРІРёРј РїР»Р°РЅРѕРј РјРѕРґРµР»С–."""
        self._planning = False
        self._finish_planning_ui()
        if result is None or not result.steps:
            reason = getattr(result, "error", "") or "РјРѕРґРµР»СЊ РЅРµ РґР°Р»Р° РєСЂРѕРєС–РІ"
            self.set_status(f"РџРµСЂРµРїР»Р°РЅСѓРІР°РЅРЅСЏ РЅРµ РІРґР°Р»РѕСЃСЊ: {reason[:80]}")
            return
        owner = self._active_chat_id()
        created = self.task_queue.replace_plan(
            result.rows(), chat_id=owner,
            goal=self.task_queue.plan_tasks(chat_id=owner)[0].goal
            if self.task_queue.plan_tasks(chat_id=owner) else "")
        self._last_plan = list(result.steps)
        self._update_queue_badge()
        try:
            self.chat._note("**РџР»Р°РЅ РѕРЅРѕРІР»РµРЅРѕ** вЂ” Р·Р°Р»РёС€РѕРє СЂРѕР±РѕС‚Рё РїРµСЂРµРїР»Р°РЅРѕРІР°РЅРѕ:\n\n"
                            + task_planner.plan_markdown("", result.steps))
        except (tk.TclError, AttributeError):
            LOG.debug("РћРЅРѕРІР»РµРЅРёР№ РїР»Р°РЅ РЅРµ РїРѕС‚СЂР°РїРёРІ Сѓ С‡Р°С‚", exc_info=True)
        self.set_status(f"РџР»Р°РЅ РѕРЅРѕРІР»РµРЅРѕ: {len(created)} РєСЂРѕРєС–РІ.")
        self._start_plan_execution()

    def finish_plan_report(self) -> None:
        """РџРѕРєР°Р·Р°С‚Рё РїС–РґСЃСѓРјРєРѕРІРёР№ Р·РІС–С‚ РїРѕ РїР»Р°РЅСѓ РІ С‡Р°С‚С–."""
        report = self.executor.report(chat_id=self._active_chat_id())
        try:
            self.chat._note(report)
        except (tk.TclError, AttributeError):
            self.set_status(report.splitlines()[0] if report else "Р—РІС–С‚ РїРѕСЂРѕР¶РЅС–Р№.")
            return
        self.show_chat(True)
        self.set_status("РџС–РґСЃСѓРјРєРѕРІРёР№ Р·РІС–С‚ вЂ” Сѓ С‡Р°С‚С–.")

    def add_queue_dialog(self) -> None:
        self.show_side("queue")
        try:
            self.queue_panel.entry.focus_set()
        except tk.TclError:
            pass

    def _update_queue_badge(self) -> None:
        active_states = set(queue_engine.ACTIVE_STATUSES) | {queue_engine.PENDING}
        pending = [t for t in self.task_queue.tasks if t.status in active_states]
        try:
            self.chat.set_queue_count(len(pending), tasks=pending)
        except (tk.TclError, AttributeError):
            pass
        try:
            self.queue_panel.refresh()
        except (tk.TclError, AttributeError):
            pass
        try:
            self.task_center.refresh()
        except (tk.TclError, AttributeError):
            LOG.debug("Р¦РµРЅС‚СЂ Р·Р°РІРґР°РЅСЊ РЅРµ РѕРЅРѕРІРёРІСЃСЏ", exc_info=True)
        # РљРѕР»РѕРЅРєР° РєРѕРЅС‚РµРєСЃС‚Сѓ РїРѕРєР°Р·СѓС” С‚РѕР№ СЃР°РјРёР№ СЃС‚Р°РЅ Р°РіРµРЅС‚Р° Р· С‡РµСЂРіРё вЂ” Р±РµР·
        # С†СЊРѕРіРѕ РїС–РґРїРёСЃ В«РїСЂР°С†СЋС” В· РєСЂРѕРє 3В» Р·Р°СЃС‚РёРіР°РІ РЅР° РїРµСЂС€РѕРјСѓ РєСЂРѕС†С–.
        try:
            if self._context_shown:
                self.context._refresh_agent()
        except (tk.TclError, AttributeError):
            LOG.debug("РЎС‚Р°РЅ Р°РіРµРЅС‚Р° РЅРµ РѕРЅРѕРІРёРІСЃСЏ", exc_info=True)
        # РљРЅРѕРїРєР° СЂРµР¶РёРјСѓ С‡Р°С‚Сѓ РїРѕРєР°Р·СѓС”, С‰Рѕ СЃР°РјРµ С†РµР№ С‡Р°С‚ СЂРѕР±РёС‚СЊ Сѓ С„РѕРЅС–.
        try:
            owner = str(getattr(self.chat_store, "active_id", "") or "")
            mine = [t for t in pending
                    if not getattr(t, "chat_id", "") or str(t.chat_id) == owner]
            self.header.set_chat_mode(
                autonomous=self.autonomous_engine.active, queue_count=len(mine))
        except (tk.TclError, AttributeError):
            pass

    def _queue_pump(self) -> None:
        """Р Р°Р· РЅР° РєС–Р»СЊРєР° СЃРµРєСѓРЅРґ: СЏРєС‰Рѕ Р°РіРµРЅС‚ РІС–Р»СЊРЅРёР№, СѓР·СЏС‚Рё РЅР°СЃС‚СѓРїРЅСѓ Р·Р°РґР°С‡Сѓ.

        РџС–Рґ С‡Р°СЃ Р·СѓРїРёРЅРєРё Р°РІС‚РѕРЅРѕРјРЅРѕРіРѕ СЂРµР¶РёРјСѓ РЅРѕРІС– Р·Р°РґР°С‡С– РќР• Р±РµСЂРµРјРѕ: С–РЅР°РєС€Рµ
        С‰РѕР№РЅРѕ Р·РІС–Р»СЊРЅРµРЅРёР№ Р°РіРµРЅС‚ С…Р°РїР°РІ Р±Рё РЅР°СЃС‚СѓРїРЅСѓ Р·Р°РґР°С‡Сѓ Р· С‡РµСЂРіРё Р№ СЂРµР¶РёРј
        РЅС–РєРѕР»Рё РЅРµ Р·Р°РІРµСЂС€СѓРІР°РІСЃСЏ Р±.
        """
        try:
            if (self.settings.agent.queue_auto_run and not self.task_queue.paused
                    and not self._autonomous_stop_pending
                    and self.autonomous_engine.state != autonomous.STATE_STOPPING
                    and not self.task_queue.running_id and not self.agent.busy
                    # Р‘РµР· С‚РµРєРё РїСЂРѕС”РєС‚Сѓ С‡РµСЂРіР° РЅРµ СЂСѓС…Р°С”С‚СЊСЃСЏ: С–РЅР°РєС€Рµ РЅР°СЃРѕСЃ
                    # РІРёРєР»РёРєР°РІ Р±Рё run_next_task С‰РѕСЃРµРєСѓРЅРґРё Р№ С‰РѕСЂР°Р·Сѓ РїРѕРєР°Р·СѓРІР°РІ
                    # Р±Рё РµРєСЂР°РЅ РІРёР±РѕСЂСѓ С‚РµРєРё.
                    and self.has_project()
                    # Р’РёРєРѕРЅР°РІРµС†СЊ Р·РЅР°С” РїСЂРѕ Р·Р°Р»РµР¶РЅРѕСЃС‚С– РєСЂРѕРєС–РІ, С‚РѕРјСѓ РїРёС‚Р°С”РјРѕ
                    # Р№РѕРіРѕ, Р° РЅРµ СЃР°РјСѓ С‡РµСЂРіСѓ.
                    and self.executor.next_task() is not None):
                self.run_next_task()
        except Exception as exc:  # noqa: BLE001 - С„РѕРЅРѕРІРёР№ РЅР°СЃРѕСЃ РЅРµ РјР°С” Р»Р°РјР°С‚Рё РІС–РєРЅРѕ
            # РќР°СЃРѕСЃ СЃРїСЂР°С†СЊРѕРІСѓС” РєРѕР¶РЅС– 1.2 СЃ; Р±РµР·С€СѓРјРЅРёР№ Р·Р±С–Р№ РѕР·РЅР°С‡Р°РІ Р±Рё, С‰Рѕ
            # С‡РµСЂРіР° РїСЂРѕСЃС‚Рѕ РїРµСЂРµСЃС‚Р°Р»Р° СЂСѓС…Р°С‚РёСЃСЊ С– РЅС–С…С‚Рѕ РЅРµ Р·РЅР°С” С‡РѕРјСѓ.
            safe.record_failure("Р·Р°РїСѓСЃРє Р·Р°РґР°С‡С– Р· С‡РµСЂРіРё", exc)
            LOG.warning("РќР°СЃРѕСЃ С‡РµСЂРіРё РІРїР°РІ", exc_info=True)
        try:
            # Р§РµСЂРіР° СЃС‚РѕС—С‚СЊ, Р±Рѕ Р°РєС‚РёРІРЅРёР№ РєСЂРѕРє В«Р·Р°РІРёСЃВ» (Р°РіРµРЅС‚ Р·РІС–Р»СЊРЅРёРІСЃСЏ, Р°
            # СЃС‚Р°С‚СѓСЃ Р»РёС€РёРІСЃСЏ Р°РєС‚РёРІРЅРёРј) вЂ” РїРѕРІРµСЂС‚Р°С”РјРѕ Р№РѕРіРѕ РІ С‡РµСЂРіСѓ, С–РЅР°РєС€Рµ
            # РІРёРєРѕРЅР°РЅРЅСЏ РЅРµ СЂСѓС…Р°С‚РёРјРµС‚СЊСЃСЏ РЅС–РєРѕР»Рё.
            #
            # РџРµСЂРµРІС–СЂРєР° РЅР°РІРјРёСЃРЅРѕ Р§РђРЎРћР’Рђ, Р° РЅРµ РјРёС‚С‚С”РІР°. Р Р°РЅС–С€Рµ СѓРјРѕРІР°
            # В«Р°РіРµРЅС‚ РЅРµ busyВ» СЃРїСЂР°С†СЊРѕРІСѓРІР°Р»Р° РІ РїСЂРѕРјС–Р¶РєСѓ РјС–Р¶ ``mark_running``
            # С– С„Р°РєС‚РёС‡РЅРёРј СЃС‚Р°СЂС‚РѕРј РїРѕС‚РѕРєСѓ Р°РіРµРЅС‚Р°: РєСЂРѕРє РїРѕРІРµСЂС‚Р°РІСЃСЏ РІ С‡РµСЂРіСѓ
            # РїСЂРѕСЃС‚Рѕ РїС–Рґ С‡Р°СЃ СЂРѕР±РѕС‚Рё, С– РїР°РЅРµР»СЊ РїРѕРєР°Р·СѓРІР°Р»Р° В«РіРѕС‚РѕРІРѕ РґРѕ
            # Р·Р°РїСѓСЃРєСѓВ» Р·Р°РјС–СЃС‚СЊ В«РІРёРєРѕРЅСѓС”С‚СЊСЃСЏВ». РўРµРїРµСЂ РєСЂРѕРє РІРІР°Р¶Р°С”РјРѕ Р·Р°РІРёСЃР»РёРј,
            # Р»РёС€Рµ СЏРєС‰Рѕ РІС–РЅ Р°РєС‚РёРІРЅРёР№ РґРѕРІС€Рµ Р·Р° ``STALE_STEP_SECONDS``.
            now = time.time()
            running_task = self.task_queue.get(self.task_queue.running_id) \
                if self.task_queue.running_id else None
            if (running_task is not None and not self.agent.busy
                    and not self._plan_step_active
                    and not self.executor.busy):
                started = float(running_task.started_at or 0.0)
                if started and (now - started) > self.STALE_STEP_SECONDS:
                    stale = self.task_queue.requeue_running()
                    if stale is not None:
                        LOG.info("Р—Р°РІРёСЃР»РёР№ РєСЂРѕРє %s РїРѕРІРµСЂРЅСѓС‚Рѕ РІ С‡РµСЂРіСѓ "
                                 "(Р°РєС‚РёРІРЅРёР№ %.0f СЃ)", stale.id, now - started)
                        self._update_queue_badge()
        except Exception:  # noqa: BLE001 - РїСЂРёР±РёСЂР°РЅРЅСЏ РЅРµ РјР°С” Р»Р°РјР°С‚Рё РІС–РєРЅРѕ
            LOG.debug("РќРµ РІРґР°Р»РѕСЃСЊ РїРµСЂРµРІС–СЂРёС‚Рё Р·Р°РІРёСЃР»РёР№ РєСЂРѕРє", exc_info=True)
        try:
            if self.winfo_exists():
                self._queue_pump_after = (self.after(1200, self._queue_pump) if self._timer_alive() else None)
        except tk.TclError:
            self._queue_pump_after = None

    def run_next_task(self, task: Optional[queue_engine.QueueTask] = None) -> None:
        """Р—Р°РїСѓСЃС‚РёС‚Рё Р·Р°РґР°С‡Сѓ Р· С‡РµСЂРіРё (РЅР°СЃС‚СѓРїРЅСѓ Р°Р±Рѕ РєРѕРЅРєСЂРµС‚РЅСѓ).

        ``task`` РїРµСЂРµРґР°С” Р°РІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј, РєРѕР»Рё РІР¶Рµ РѕР±СЂР°РІ Р·Р°РґР°С‡Сѓ Р№ РїРѕРєР°Р·Р°РІ
        РїР»Р°РЅ: С–РЅР°РєС€Рµ РјС–Р¶ В«РѕР±СЂР°РЅРёРјВ» С– В«Р·Р°РїСѓС‰РµРЅРёРјВ» СЃС‚Р°РЅ С‡РµСЂРіРё РјС–Рі Р·РјС–РЅРёС‚РёСЃСЊ.

        Р’РёРєРѕРЅР°РЅРЅСЏ Р№РґРµ С‡РµСЂРµР· :class:`task_executor.QueueExecutor`: РІС–РЅ
        РїРµСЂРµРІС–СЂСЏС” Р·Р°Р»РµР¶РЅРѕСЃС‚С–, РІРµРґРµ Р»С–С‡РёР»СЊРЅРёРє СЃРїСЂРѕР± С– СЃР°Рј СЃС‚Р°РІРёС‚СЊ СЃС‚Р°С‚СѓСЃРё.
        """
        if self.agent.busy:
            self.set_status("РђРіРµРЅС‚ Р·Р°Р№РЅСЏС‚РёР№ вЂ” Р·Р°РґР°С‡Р° СЃС‚Р°СЂС‚СѓС” РїС–СЃР»СЏ Р·Р°РІРµСЂС€РµРЅРЅСЏ РїРѕС‚РѕС‡РЅРѕС—.")
            return
        # Р‘РµР· С‚РµРєРё РїСЂРѕС”РєС‚Сѓ Р·Р°РґР°С‡Сѓ РЅРµ Р·Р°РїСѓСЃРєР°С”РјРѕ. РџРµСЂРµРІС–СЂРєР° СЃС‚РѕС—С‚СЊ Р”Рћ
        # ``mark_running``: С–РЅР°РєС€Рµ РІС–РґРјРѕРІР° С€Р»СЋР·Сѓ РІ ``chat._send`` Р»РёС€Р°Р»Р° Р±
        # Р·Р°РґР°С‡Сѓ РІ СЃС‚Р°РЅС– В«РІ СЂРѕР±РѕС‚С–В» РЅР°Р·Р°РІР¶РґРё, С– С‡РµСЂРіР° Р±С–Р»СЊС€Рµ РЅРµ СЂСѓС…Р°Р»Р°СЃСЊ Р±Рё.
        if not self.has_project():
            # РџР°СѓР·Рё РќР• СЃС‚Р°РІРёРјРѕ: РІРѕРЅР° Р»РёС€РёР»Р°СЃСЊ Р±Рё Р№ РїС–СЃР»СЏ РІРёР±РѕСЂСѓ С‚РµРєРё, С– С‡РµСЂРіР°
            # РјРѕРІС‡РєРё СЃС‚РѕСЏР»Р° Р±. Р”РѕСЃС‚Р°С‚РЅСЊРѕ РЅРµ Р·Р°РїСѓСЃРєР°С‚Рё Р·Р°РґР°С‡Сѓ вЂ” РЅР°СЃРѕСЃ
            # ``_queue_pump`` СЃР°Рј РЅРµ С‡С–РїР°С” С‡РµСЂРіСѓ, РїРѕРєРё РїСЂРѕС”РєС‚Сѓ РЅРµРјР°С”.
            self._show_project_gate(
                reason="Р’РёР±РµСЂРё С‚РµРєСѓ РїСЂРѕС”РєС‚Сѓ вЂ” С– С‡РµСЂРіР° РїСЂРѕРґРѕРІР¶РёС‚СЊ СЂРѕР±РѕС‚Сѓ.")
            self.set_status("Р§РµСЂРіР° С‡РµРєР°С”: СЃРїРµСЂС€Сѓ РІРёР±РµСЂРё РїР°РїРєСѓ РїСЂРѕС”РєС‚Сѓ.")
            return
        if task is not None:
            # РљРѕРЅРєСЂРµС‚РЅСѓ Р·Р°РґР°С‡Сѓ (РІС–Рґ Р°РІС‚РѕРЅРѕРјРЅРѕРіРѕ СЂРµР¶РёРјСѓ) Р·Р°РїСѓСЃРєР°С”РјРѕ РЅР°РїСЂСЏРјСѓ.
            self.executor.start(task)
            self._update_queue_badge()
            return
        # РђРІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј РјС–Рі РїРѕРєР»Р°СЃС‚Рё Р·Р°РґР°С‡Сѓ РІ С‡РµСЂРіСѓ вЂ” РІРёРєРѕРЅР°РІРµС†СЊ Р·РЅР°Р№РґРµ
        # РЅР°Р№РїРµСЂС€Сѓ Р“РћРўРћР’РЈ (Р· РІРёРєРѕРЅР°РЅРёРјРё Р·Р°Р»РµР¶РЅРѕСЃС‚СЏРјРё).
        started = self.executor.start_next()
        if started is None:
            blocked = self.task_queue.waiting_on_dependencies(
                chat_id=self._active_chat_id())
            if blocked:
                self.set_status(
                    f"Р§РµСЂРіР° С‡РµРєР°С” РЅР° РїРѕРїРµСЂРµРґРЅС– РєСЂРѕРєРё: {len(blocked)}.")
            else:
                self.set_status("Р§РµСЂРіР° РїРѕСЂРѕР¶РЅСЏ Р°Р±Рѕ РЅР° РїР°СѓР·С–.")
        self._update_queue_badge()

    def _skill_prompt(self, skill: skills_module.Skill) -> str:
        return (f"Р—Р°СЃС‚РѕСЃСѓР№ СЃРєС–Р» В«{skill.name}В».\n\n"
                f"РћРїРёСЃ: {skill.description}\n\nР†РЅСЃС‚СЂСѓРєС†С–СЏ:\n{skill.body.strip()}")

    def _verify_task_result(self, text: str) -> tuple[bool, str]:
        """РџРµСЂРµРІС–СЂРёС‚Рё, С‰Рѕ Р·Р°РґР°С‡Р° С‡РµСЂРіРё СЃРїСЂР°РІРґС– РґР°Р»Р° СЂРµР·СѓР»СЊС‚Р°С‚ РЅР° РґРёСЃРєСѓ.

        Р“РѕР»РѕРІРЅР° РїР°СЃС‚РєР° Р»РѕРєР°Р»СЊРЅРёС… РјРѕРґРµР»РµР№: Сѓ РІС–РґРїРѕРІС–РґС– РЅР°РїРёСЃР°РЅРѕ В«Р¤Р°Р№Р»
        СЃС‚РІРѕСЂРµРЅРѕВ», Р° РЅР° РґРёСЃРєСѓ Р№РѕРіРѕ РЅРµРјР°С”. РўРѕРјСѓ Р·Р°РґР°С‡Сѓ, СЏРєР° Р·РіР°РґСѓС” С€Р»СЏС… РґРѕ
        С„Р°Р№Р»Сѓ, РЅРµ Р·Р°СЂР°С…РѕРІСѓС”РјРѕ, РїРѕРєРё С†СЊРѕРіРѕ С„Р°Р№Р»Сѓ РЅРµ С–СЃРЅСѓС”.

        РџРѕРІРµСЂС‚Р°С” (СѓСЃРїС–С…, РїРѕСЏСЃРЅРµРЅРЅСЏ).
        """
        answer = text or ""
        if not answer.strip():
            return False, "РїРѕСЂРѕР¶РЅСЏ РІС–РґРїРѕРІС–РґСЊ"
        # РЁСѓРєР°С”РјРѕ Р·РіР°РґР°РЅС– С€Р»СЏС…Рё Р· СЂРѕР·С€РёСЂРµРЅРЅСЏРј С„Р°Р№Р»Сѓ.
        mentioned = set()
        for match in re.finditer(r"[\w./\\-]+\.(?:js|json|html|css|ejs|env|db|md)\b", answer):
            mentioned.add(match.group(0).replace("/", "\\").lstrip(".\\"))
        mentioned = {name for name in mentioned if len(name) > 3}
        if not mentioned:
            # Р¤Р°Р№Р»С–РІ РЅРµ Р·РіР°РґР°РЅРѕ вЂ” Р·Р°РґР°С‡Р° Р±СѓР»Р° РЅРµ РїСЂРѕ СЃС‚РІРѕСЂРµРЅРЅСЏ С„Р°Р№Р»Сѓ.
            return True, ""
        root = Path(self.settings.workspace)
        missing = []
        for name in sorted(mentioned):
            candidate = root / name
            if not candidate.exists():
                # РњРѕРґРµР»СЊ РјРѕРіР»Р° РІРєР°Р·Р°С‚Рё Р»РёС€Рµ С–Рј'СЏ Р±РµР· РїР°РїРєРё.
                if not any(p.name == Path(name).name
                           for p in root.rglob(Path(name).name)):
                    missing.append(name)
        if len(missing) == len(mentioned):
            return False, "С„Р°Р№Р»С–РІ РЅРµРјР°С” РЅР° РґРёСЃРєСѓ: " + ", ".join(missing[:3])
        return True, ""

    def _on_agent_finished(self, ok: bool, text: str) -> None:
        """РђРіРµРЅС‚ Р·Р°РІРµСЂС€РёРІ СЂРѕР±РѕС‚Сѓ вЂ” Р·Р°РєСЂРёРІР°С”РјРѕ РїРѕС‚РѕС‡РЅРёР№ РєСЂРѕРє РїР»Р°РЅСѓ.

        Р’РёРєР»РёРєР°С”С‚СЊСЃСЏ Р· РџРћРўРћРљРЈ Р°РіРµРЅС‚Р°. ``TaskQueue._changed`` РєР»РёС‡Рµ
        ``queue_panel.refresh``, Р° С†Рµ РІС–РґР¶РµС‚Рё tkinter вЂ” Р· С‡СѓР¶РѕРіРѕ РїРѕС‚РѕРєСѓ РІРѕРЅРё
        РєРёРґР°СЋС‚СЊ В«main thread is not in main loopВ» С– РѕРЅРѕРІР»РµРЅРЅСЏ РіСѓР±РёС‚СЊСЃСЏ.
        РўРѕРјСѓ РЅР° С‡Р°СЃ Р·РјС–РЅРё РІС–РґС‡С–РїР»СЋС”РјРѕ РєРѕР»Р±РµРє, Р° РїР°РЅРµР»СЊ РѕРЅРѕРІР»СЋС”РјРѕ С‡РµСЂРµР· С‡РµСЂРіСѓ
        РіРѕР»РѕРІРЅРѕРіРѕ С†РёРєР»Сѓ.

        РЎС‚Р°С‚СѓСЃ СЃС‚Р°РІРёС‚СЊ РІРёРєРѕРЅР°РІРµС†СЊ: РІС–РЅ РїРµСЂРµРІС–СЂСЏС” СЂРµР·СѓР»СЊС‚Р°С‚
        (:class:`task_executor.TaskValidator`) С– Р»РёС€Рµ С‚РѕРґС– Р·Р°РєСЂРёРІР°С” РєСЂРѕРє
        СЏРє В«РіРѕС‚РѕРІРѕВ». РњРѕРґРµР»СЊ РЅРµ РјРѕР¶Рµ РѕРіРѕР»РѕСЃРёС‚Рё СѓСЃРїС–С… СЃР°РјР°.
        """
        task_id = getattr(self, "_running_task_id", "")
        if not task_id:
            return
        self._running_task_id = ""
        # Р—Р°РґР°С‡Сѓ РїСЂРѕ С„Р°Р№Р»Рё РЅРµ Р·Р°СЂР°С…РѕРІСѓС”РјРѕ Р±РµР· С„Р°Р№Р»Сѓ РЅР° РґРёСЃРєСѓ вЂ” С–РЅР°РєС€Рµ С‡РµСЂРіР°
        # РїРѕРєР°Р·СѓС” В«РіРѕС‚РѕРІРѕВ» С‚Р°Рј, РґРµ СЂРѕР±РѕС‚Рё РЅРµ СЃС‚Р°Р»РѕСЃСЏ.
        verified, reason = self._verify_task_result(text)
        if ok and not verified:
            ok = False
            LOG.info("Р—Р°РґР°С‡Р° %s РЅРµ РїС–РґС‚РІРµСЂРґР¶РµРЅР°: %s", task_id, reason)
        saved = self.task_queue.on_change
        self.task_queue.on_change = None
        try:
            if getattr(self, "_plan_step_active", False):
                # РљСЂРѕРє РїР»Р°РЅСѓ Р·Р°РєСЂРёРІР°С” РІРёРєРѕРЅР°РІРµС†СЊ вЂ” Р· РїРµСЂРµРІС–СЂРєРѕСЋ СЂРµР·СѓР»СЊС‚Р°С‚Сѓ
                # Р№ Р·Р°РїРёСЃРѕРј Р·РјС–РЅРµРЅРёС… С„Р°Р№Р»С–РІ Сѓ Р¶СѓСЂРЅР°Р» РєСЂРѕРєСѓ.
                self._plan_step_active = False
                files = self._collect_changed_files(task_id)
                self.executor.finish(
                    ok, text,
                    changed=files,
                    error=(text or reason or "РєСЂРѕРє Р·Р°РІРµСЂС€РёРІСЃСЏ Р· РїРѕРјРёР»РєРѕСЋ"),
                )
            elif ok:
                self.task_queue.mark_done(task_id, text)
            else:
                self.task_queue.mark_failed(task_id, text or reason or "РЅРµРІС–РґРѕРјР° РїРѕРјРёР»РєР°")
        finally:
            self.task_queue.on_change = saved
        self._ui_call(self._after_task_finished, ok)

    def _collect_changed_files(self, task_id: str) -> list[str]:
        """Р¤Р°Р№Р»Рё, СЏРєС– Р°РіРµРЅС‚ СЃРїСЂР°РІРґС– Р·Р°РїРёСЃР°РІ РїС–Рґ С‡Р°СЃ С†СЊРѕРіРѕ РєСЂРѕРєСѓ."""
        task = self.task_queue.get(task_id)
        if task is None:
            return []
        names = [str(name) for name in task.files_changed if str(name).strip()]
        # Р”РѕРґР°С‚РєРѕРІРѕ вЂ” Р· Р¶СѓСЂРЅР°Р»Сѓ РІРёРєР»РёРєС–РІ write_file/edit_file.
        names.extend(task_executor.files_from_history(task.history))
        # Р›РёС€Р°С”РјРѕ С‚С–Р»СЊРєРё С‚Рµ, С‰Рѕ РЎРџР РђР’Р”Р† С” С„Р°Р№Р»РѕРј Сѓ РїСЂРѕС”РєС‚С–: Сѓ С‚РµРєСЃС‚С– РІРёРєР»РёРєСѓ
        # С‚СЂР°РїР»СЏСЋС‚СЊСЃСЏ ``unittest.TestCase``, ``self.assertEqual`` С‚Р° С–РЅС€С–
        # Р°С‚СЂРёР±СѓС‚Рё РєРѕРґСѓ, С– РІРѕРЅРё РїРѕС‚СЂР°РїР»СЏР»Рё РІ В«Р·РјС–РЅРµРЅС– С„Р°Р№Р»РёВ» СЏРє РІРёРіР°РґРєР°.
        root = self._project_root()
        verified: list[str] = []
        for name in dict.fromkeys(names):
            clean = name.replace("/", "\\").lstrip(".\\")
            if not clean:
                continue
            # ``.bak`` вЂ” С†Рµ РІР»Р°СЃРЅР° РєРѕРїС–СЏ СЂРµРґР°РєС‚РѕСЂР°, Р° РЅРµ СЂРµР·СѓР»СЊС‚Р°С‚ СЂРѕР±РѕС‚Рё
            # Р°РіРµРЅС‚Р°: Сѓ Р·РІС–С‚С– РІРѕРЅР° РІРёРіР»СЏРґР°Р»Р° СЏРє Р·РјС–РЅРµРЅРёР№ С„Р°Р№Р».
            if clean.lower().endswith(".bak"):
                continue
            if root is None:
                verified.append(clean)
                continue
            if (Path(root) / clean).is_file():
                verified.append(clean)
                continue
            short = Path(clean).name
            if any(p.is_file() for p in Path(root).rglob(short)):
                verified.append(clean)
        return verified

    def _speak_answer(self, text: str) -> None:
        """РћР·РІСѓС‡РёС‚Рё С‚РµРєСЃС‚ РІС–РґРїРѕРІС–РґС– (СЏРєС‰Рѕ С†Рµ РІРІС–РјРєРЅРµРЅРѕ)."""
        try:
            self._on_agent_answer_for_voice(text)
        except Exception:  # noqa: BLE001 - РіРѕР»РѕСЃ РЅРµ РјР°С” Р»Р°РјР°С‚Рё СЂРѕР±РѕС‚Сѓ
            LOG.warning("РћР·РІСѓС‡РµРЅРЅСЏ РІС–РґРїРѕРІС–РґС– РЅРµ РІРґР°Р»РѕСЃСЊ", exc_info=True)

    def _after_task_finished(self, ok: bool) -> None:
        self._update_queue_badge()
        self._set_agent_state("РіРѕС‚РѕРІРѕ" if ok else "РїРѕРјРёР»РєР°")
        # Р•С‚Р°Рї Сѓ СЃРјСѓР·С– РЅР°Рґ РєРѕРјРїРѕР·РµСЂРѕРј СЂСѓС…Р°С”С‚СЊСЃСЏ СЂР°Р·РѕРј С–Р· Р·Р°РґР°С‡РµСЋ С‡РµСЂРіРё:
        # В«РІРёРєРѕРЅСѓС”С‚СЊСЃСЏВ» в†’ В«РіРѕС‚РѕРІРѕВ», Р° РЅР°СЃС‚СѓРїРЅРёР№ СЃС‚Р°С” РїРѕС‚РѕС‡РЅРёРј.
        #
        # ``ok`` РїРµСЂРµРґР°С”РјРѕ РљР›Р®Р§Р•Рњ: ``advance_stage`` РїСЂРёР№РјР°С” Р»РёС€Рµ
        # ``*, ok`` (РїРѕР·РёС†С–Р№РЅРёР№ РІРёРєР»РёРє РєРёРґР°РІ TypeError, С– РµС‚Р°РїРё РЅРµ СЂСѓС…Р°Р»РёСЃСЊ
        # Р·РѕРІСЃС–Рј вЂ” Р·Р±С–Р№ Р±СѓР»Рѕ РІРёРґРЅРѕ Р»РёС€Рµ РІ Р¶СѓСЂРЅР°Р»С– РїСЂРёС…РѕРІР°РЅРёС… Р·Р±РѕС—РІ).
        safe.call_quiet(self.chat.advance_stage, ok=ok,
                        where="СЂСѓС… РµС‚Р°РїС–РІ Р·Р°РґР°С‡С–")
        # Р§РµСЂРіР°: РЅР°СЃС‚СѓРїРЅС– Р·Р°РґР°С‡С– РїРѕР·РЅР°С‡Р°СЋС‚СЊ СЃРµСЃС–СЋ СЏРє queued.
        pending = [t for t in self.task_queue.tasks
                   if t.status in {queue_engine.PENDING, queue_engine.RUNNING}]
        chat = self.chat_store.active()
        if chat is not None and pending:
            self.chat_store.set_status(chat.id, "queued")
            self.chat_list.update_row_status(chat.id, "queued")
        self._maybe_continue_plan(ok)

    def _maybe_continue_plan(self, ok: bool) -> None:
        """РџРµСЂРµР№С‚Рё РґРѕ РЅР°СЃС‚СѓРїРЅРѕРіРѕ РєСЂРѕРєСѓ РїР»Р°РЅСѓ Р°Р±Рѕ Р·Р°РІРµСЂС€РёС‚Рё СЂРѕР±РѕС‚Сѓ Р·РІС–С‚РѕРј.

        РђРІС‚РѕРїСЂРѕРґРѕРІР¶РµРЅРЅСЏ вЂ” РѕСЃРЅРѕРІРЅР° РІРёРјРѕРіР°: РєРѕСЂРёСЃС‚СѓРІР°С‡ РґР°РІ РѕРґРЅРµ РІРµР»РёРєРµ
        Р·Р°РІРґР°РЅРЅСЏ, С– Р°РіРµРЅС‚ РјР°С” РїСЂРѕР№С‚Рё РїР»Р°РЅ СЃР°Рј. РџР°СѓР·Р° Р·СѓРїРёРЅСЏС” С†Рµ, Р°Р»Рµ РЅРµ
        РІС‚СЂР°С‡Р°С” РїСЂРѕРіСЂРµСЃ.
        """
        if not self.settings.agent.queue_auto_run:
            return
        if self._autonomous_stop_pending:
            return
        owner = self._active_chat_id()
        plan = self.task_queue.plan_tasks(chat_id=owner)
        if not plan:
            return
        running = [t for t in self.task_queue.tasks if t.active]
        if running or self.task_queue.paused:
            self.task_center.refresh()
            return
        ready = self.task_queue.next_pending(chat_id=owner)
        if ready is not None:
            # РќР°СЃС‚СѓРїРЅРёР№ РєСЂРѕРє СЃС‚Р°СЂС‚СѓС” РІ РЅР°СЃС‚СѓРїРЅРѕРјСѓ С‚С–РєСѓ РіРѕР»РѕРІРЅРѕРіРѕ С†РёРєР»Сѓ, С‰РѕР±
            # С–РЅС‚РµСЂС„РµР№СЃ СѓСЃС‚РёРі РїРµСЂРµРјР°Р»СЋРІР°С‚Рё СЃС‚Р°С‚СѓСЃ РїРѕРїРµСЂРµРґРЅСЊРѕРіРѕ.
            self.after(120, self._start_plan_execution)
            return
        # Р‘С–Р»СЊС€Рµ РіРѕС‚РѕРІРёС… РєСЂРѕРєС–РІ РЅРµРјР°С”: Р°Р±Рѕ РІСЃРµ Р·Р°РІРµСЂС€РµРЅРѕ, Р°Р±Рѕ Р»РёС€РёР»РёСЃСЊ
        # Р·Р°Р±Р»РѕРєРѕРІР°РЅС– (С—С…РЅС– Р·Р°Р»РµР¶РЅРѕСЃС‚С– РІРїР°Р»Рё) вЂ” С‚РѕРґС– РїРѕРєР°Р·СѓС”РјРѕ Р·РІС–С‚.
        if all(t.settled for t in plan):
            self._finish_plan()

    def _finish_plan(self) -> None:
        """РџРѕРєР°Р·Р°С‚Рё РїС–РґСЃСѓРјРѕРє С– РїСЂРёР±СЂР°С‚Рё СЃРјСѓРіСѓ РµС‚Р°РїС–РІ."""
        report = self.executor.report(chat_id=self._active_chat_id())
        try:
            self.chat._note(report)
        except (tk.TclError, AttributeError):
            LOG.debug("Р—РІС–С‚ РЅРµ РїРѕС‚СЂР°РїРёРІ Сѓ С‡Р°С‚", exc_info=True)
        try:
            self.chat.finish_stages(ok=True)
        except (tk.TclError, AttributeError):
            pass
        progress = self.task_queue.progress()
        self.set_status(
            f"РџР»Р°РЅ Р·Р°РІРµСЂС€РµРЅРѕ: {progress['done']} Р· {progress['total']} РєСЂРѕРєС–РІ"
            + (f", РїРѕРјРёР»РѕРє {progress['errors']}" if progress["errors"] else ""))
        self.task_center.refresh()
        LOG.info("РџР»Р°РЅ Р·Р°РІРµСЂС€РµРЅРѕ: %s", progress)

    def _set_agent_state(self, state: str) -> None:
        colours = {
            "РѕС‡С–РєСѓС”": theme.FG_FAINT,
            "РїСЂР°С†СЋС”": theme.ACCENT,
            "РіРѕС‚РѕРІРѕ": theme.SUCCESS,
            "РїРѕРјРёР»РєР°": theme.ERROR,
        }
        try:
            self.agent_label.configure(text=f"Р°РіРµРЅС‚: {state}",
                                       fg=colours.get(state, theme.FG_FAINT))
        except tk.TclError:
            pass

    def _show_queue_task(self, task: queue_engine.QueueTask) -> None:
        text = f"{task.status}\n\n{task.text}"
        if task.result:
            text += f"\n\n--- СЂРµР·СѓР»СЊС‚Р°С‚ ---\n{task.result}"
        if task.error:
            text += f"\n\n--- РїРѕРјРёР»РєР° ---\n{task.error}"
        self.chat._note(text, kind="error" if task.error else "info")

    # в”Ђв”Ђ Р¶РёРІС– РґР°РЅС– РґР»СЏ РєРѕР»РѕРЅРєРё РєРѕРЅС‚РµРєСЃС‚Сѓ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _agent_status_text(self) -> str:
        """Р©Рѕ СЂРѕР±РёС‚СЊ Р°РіРµРЅС‚ РїСЂРѕСЃС‚Рѕ Р·Р°СЂР°Р· (Р· СЂРµР°Р»СЊРЅРѕРіРѕ СЃС‚Р°РЅСѓ)."""
        active = next((t for t in self.task_queue.tasks if t.active), None)
        if active is not None:
            label = f"{active.number:02d}" if active.number else "вЂ”"
            step = task_executor.describe_status(active)
            return f"РїСЂР°С†СЋС” В· РєСЂРѕРє {label} В· {step[:48]}"
        if self.agent.busy:
            return "РїСЂР°С†СЋС” В· РІС–РґРїРѕРІС–РґР°С” РЅР° Р·Р°РїРёС‚"
        progress = self.task_queue.progress()
        if self.task_queue.paused:
            return "РїР°СѓР·Р° В· С‡РµСЂРіР° Р·СѓРїРёРЅРµРЅР°"
        if progress["errors"]:
            return f"РїРѕРјРёР»РєР° В· РєСЂРѕРєС–РІ Р· РїРѕРјРёР»РєРѕСЋ {progress['errors']}"
        if progress["pending"]:
            waiting = self.task_queue.waiting_on_dependencies(
                chat_id=self._active_chat_id())
            if waiting and len(waiting) == progress["pending"]:
                return f"РѕС‡С–РєСѓС” В· С‡РµРєР°С” РЅР° РїРѕРїРµСЂРµРґРЅС– РєСЂРѕРєРё"
            return f"РѕС‡С–РєСѓС” В· Сѓ С‡РµСЂР·С– {progress['pending']} РєСЂРѕРєС–РІ"
        if progress["total"] and progress["done"] == progress["total"]:
            return f"Р·Р°РІРµСЂС€РµРЅРѕ В· СѓСЃС– {progress['total']} РєСЂРѕРєС–РІ"
        return "РѕС‡С–РєСѓС” Р·Р°РІРґР°РЅРЅСЏ"

    def _model_summary(self) -> tuple[str, str]:
        """РќР°Р·РІР° РїРѕС‚РѕС‡РЅРѕС— РјРѕРґРµР»С– Р№ РІРёРґ РїС–РґРєР»СЋС‡РµРЅРЅСЏ (Р»РѕРєР°Р»СЊРЅР° / С…РјР°СЂР°).

        Р’РёРґ РІРёР·РЅР°С‡Р°С”РјРѕ Р·Р° РђР”Р Р•РЎРћР®, Р° РЅРµ Р·Р° РЅР°СЏРІРЅС–СЃС‚СЋ РЅР°Р»Р°С€С‚СѓРІР°РЅСЊ С…РјР°СЂРё:
        СЂР°РЅС–С€Рµ Р»РѕРєР°Р»СЊРЅР° РјРѕРґРµР»СЊ РЅР° 127.0.0.1:8080 РїРѕРєР°Р·СѓРІР°Р»Р°СЃСЊ СЏРє В«С…РјР°СЂР°В»,
        С‰РѕР№РЅРѕ РІ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏС… Р»РёС€Р°РІСЃСЏ Р±СѓРґСЊ-СЏРєРёР№ Р·Р°РїРёСЃ С…РјР°СЂРЅРѕРіРѕ РїСЂРѕРІР°Р№РґРµСЂР°.
        """
        name = str(getattr(self.settings.llm, "model", "") or "").strip()
        if not name:
            return "РЅРµ РІРёР±СЂР°РЅР°", "РЅР°С‚РёСЃРЅРё, С‰РѕР± РІРёР±СЂР°С‚Рё"
        base_url = str(getattr(self.settings.llm, "base_url", "") or "").lower()
        # Р’Р±СѓРґРѕРІР°РЅРёР№ СЂСѓС€С–Р№ Р¶РёРІРµ РІ С†СЊРѕРјСѓ Р¶ РїСЂРѕС†РµСЃС– вЂ” С†Рµ РЅР°Р№Р»РѕРєР°Р»СЊРЅС–С€Рµ, С‰Рѕ Р±СѓРІР°С”,
        # Р°Р»Рµ Р№РѕРіРѕ Р°РґСЂРµСЃР° (``native://blackchpok``) РЅРµ РјС–СЃС‚РёС‚СЊ Р¶РѕРґРЅРѕРіРѕ
        # Р»РѕРєР°Р»СЊРЅРѕРіРѕ РјР°СЂРєРµСЂР°, С‚РѕРјСѓ РїРµСЂРµРІС–СЂСЏС”РјРѕ СЃС…РµРјСѓ РћРљР Р•РњРћ.
        if base_url.startswith(("native://", "inproc://", "blackchpok://")):
            state = "online" if self.native_runtime.engine.loaded else "РЅРµ Р·Р°РІР°РЅС‚Р°Р¶РµРЅР°"
            return name, f"РІР±СѓРґРѕРІР°РЅРёР№ СЂСѓС€С–Р№ В· {state}"
        is_local = any(marker in base_url for marker in (
            "127.0.0.1", "localhost", "0.0.0.0", "::1", "192.168.", "10."))
        if is_local:
            kind = "Р»РѕРєР°Р»СЊРЅР° В· online" if self._server_alive() else "Р»РѕРєР°Р»СЊРЅР° В· offline"
        else:
            cloud = getattr(self.settings.cloud, "provider", "") \
                if hasattr(self.settings, "cloud") else ""
            kind = f"С…РјР°СЂР° В· {cloud}" if str(cloud).strip() else "С…РјР°СЂР°"
        return name, kind

    def _context_usage(self) -> tuple[int, int]:
        """(РІРёРєРѕСЂРёСЃС‚Р°РЅРѕ, Р»С–РјС–С‚) С‚РѕРєРµРЅС–РІ РєРѕРЅС‚РµРєСЃС‚Сѓ Р· СЂРµР°Р»СЊРЅРѕС— СЃС‚Р°С‚РёСЃС‚РёРєРё."""
        try:
            stats = self.chat.stats_bar.stats
            used = int(stats.prompt_tokens or 0)
            limit = int(stats.context_limit or 0)
            return used, limit
        except (AttributeError, TypeError, ValueError):
            return 0, 0

    def _active_tool_names(self) -> list[str]:
        """Р†РЅСЃС‚СЂСѓРјРµРЅС‚Рё, СЂРµР°Р»СЊРЅРѕ РґРѕСЃС‚СѓРїРЅС– Р°РіРµРЅС‚Сѓ РІ РїРѕС‚РѕС‡РЅРѕРјСѓ СЂРµР¶РёРјС–.

        ``probe_window=False``: С†Рµ Р†РќРўР•Р Р¤Р•Р™РЎРќРђ РґРѕРІС–РґРєР° (СЃРєС–Р»СЊРєРѕРј СЃС…РµРјР°Рј
        РІРёСЃС‚Р°С‡РёР»Рѕ РјС–СЃС†СЏ), С– РІРѕРЅР° РѕРЅРѕРІР»СЋС”С‚СЊСЃСЏ РєС–Р»СЊРєР° СЂР°Р·С–РІ РЅР° СЃРµРєСѓРЅРґСѓ.
        Р’РёР·РЅР°С‡РµРЅРЅСЏ РІС–РєРЅР° СЂРѕР±РёС‚СЊ РјРµСЂРµР¶РµРІРёР№ Р·Р°РїРёС‚, С‚РѕР¶ Сѓ РіРѕР»РѕРІРЅРѕРјСѓ РїРѕС‚РѕС†С–
        Р№РѕРіРѕ РЅРµ СЂРѕР±РёРјРѕ вЂ” С–РЅР°РєС€Рµ РїРµСЂС€РёР№ РєР°РґСЂ С‡РµРєР°РІ РґРѕ 1 СЃ (Р·Р°РјС–СЂСЏРЅРѕ).
        """
        try:
            schemas = self.agent.tool_schemas(probe_window=False)
        except Exception:  # noqa: BLE001 - РїР°РЅРµР»СЊ РЅРµ РјР°С” РїР°РґР°С‚Рё
            return []
        names = []
        for schema in schemas:
            function = schema.get("function") if isinstance(schema, dict) else None
            if isinstance(function, dict) and function.get("name"):
                names.append(str(function["name"]))
        return names

    def _registry_state_for_panel(self) -> dict:
        """РЎС‚Р°РЅ СЂРµС”СЃС‚СЂСѓ С–РЅСЃС‚СЂСѓРјРµРЅС‚С–РІ РґР»СЏ РїР°РЅРµР»С– РєРѕРЅС‚РµРєСЃС‚Сѓ (СЂРµР°Р»СЊРЅС– С‡РёСЃР»Р°)."""
        try:
            return self.agent.tool_registry_state()
        except (AttributeError, TypeError):
            return {}

    def _counter_is_exact(self) -> bool:
        """Р§Рё РїС–РґСЂР°С…РѕРІСѓСЋС‚СЊСЃСЏ С‚РѕРєРµРЅРё СЃРїСЂР°РІР¶РЅС–Рј tokenizer РјРѕРґРµР»С–."""
        from . import context_stats as context_stats_module

        try:
            return bool(context_stats_module.estimate_is_exact())
        except (AttributeError, TypeError):
            return False

    def _budget_state_for_panel(self) -> dict:
        """Р РѕР·РїРѕРґС–Р» Р±СЋРґР¶РµС‚Сѓ РєРѕРЅС‚РµРєСЃС‚Сѓ (РІС–РєРЅРѕ/РІС–РґРїРѕРІС–РґСЊ/С–СЃС‚РѕСЂС–СЏ/СЃС…РµРјРё)."""
        budget = getattr(self.agent, "_context_budget", None)
        if budget is None:
            return {}
        return {
            "window": int(getattr(budget, "window", 0) or 0),
            "answer": int(getattr(budget, "answer", 0) or 0),
            "history": int(getattr(budget, "history", 0) or 0),
            "tools": int(getattr(budget, "tools", 0) or 0),
            "system": int(getattr(budget, "system", 0) or 0),
            "safety": int(getattr(budget, "safety", 0) or 0),
        }

    # в”Ђв”Ђ RAG в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _insert_rag_context(self, text: str) -> None:
        """РџРѕРєР»Р°СЃС‚Рё Р·РЅР°Р№РґРµРЅРёР№ С„СЂР°РіРјРµРЅС‚ Сѓ РїРѕР»Рµ Р·Р°РїРёС‚Сѓ СЏРє РєРѕРЅС‚РµРєСЃС‚."""
        clean = (text or "").strip()
        if not clean:
            return
        try:
            self.chat.insert_context(clean)
        except (tk.TclError, AttributeError):
            return
        self.show_chat(True)
        self.set_status("Р¤СЂР°РіРјРµРЅС‚ РґРѕРґР°РЅРѕ РІ Р·Р°РїРёС‚.")

    def refresh_rag_status(self) -> None:
        """РћРЅРѕРІРёС‚Рё СЃС‚Р°РЅ RAG РїС–СЃР»СЏ Р·РјС–РЅРё СЂРѕР±РѕС‡РѕС— С‚РµРєРё."""
        try:
            self.rag_service.set_root(Path(self.settings.workspace))
            self.rag_panel.refresh_status()
        except (tk.TclError, AttributeError):
            pass

    def _on_tool_result(self, output: str, ok: bool) -> None:
        """Р РµР·СѓР»СЊС‚Р°С‚ СЂСѓС‡РЅРѕРіРѕ РІРёРєР»РёРєСѓ С–РЅСЃС‚СЂСѓРјРµРЅС‚Р° вЂ” РїРѕРєР°Р·Р°С‚Рё РІ С‡Р°С‚С–."""
        head = (output or "").strip()
        if not head:
            return
        try:
            self.chat._note(("вњ“ " if ok else "вњ— ") + head[:800],
                            kind="info" if ok else "error")
        except (tk.TclError, AttributeError):
            pass

    # в”Ђв”Ђ СЃР°Р№С‚ РїСЂРѕС”РєС‚Сѓ: Р°РіРµРЅС‚ РїС–РґРЅСЏРІ вЂ” РїРѕРєР°Р·СѓС”РјРѕ РѕРґСЂР°Р·Сѓ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _show_site_if_started(self, name: str, ok: bool, text: str) -> None:
        """РџРѕРєР°Р·Р°С‚Рё СЃР°Р№С‚ Сѓ РїР°РЅРµР»С– В«РЎР°Р№С‚В», РєРѕР»Рё Р°РіРµРЅС‚ Р№РѕРіРѕ Р·Р°РїСѓСЃС‚РёРІ.

        РљРѕСЂРёСЃС‚СѓРІР°С‡ РїСЂРѕСЃРёРІ: В«Р°РіРµРЅС‚ РєРѕР»Рё РїРёС€Рµ СЃР°Р№С‚ РІРјС–РІ РІРјРёРєР°С‚Рё Р±СЂР°СѓР·РµСЂ С–
        РїРѕРєР°Р·СѓРІР°С‚Рё РјРµРЅС– РЅР°РіР»СЏРґРЅРѕ РіРѕС‚РѕРІРёР№ РїСЂРѕРґСѓРєС‚В». Р Р°РЅС–С€Рµ ``app_start``
        РїС–РґРЅС–РјР°РІ СЃРµСЂРІРµСЂ, Р°Р»Рµ РїР°РЅРµР»СЊ РїСЂРѕ С†Рµ РЅРµ Р·РЅР°Р»Р° вЂ” СЃР°Р№С‚ Р¶РёРІ Сѓ С„РѕРЅС–,
        С– Р»СЋРґРёРЅР° РЅРµ Р±Р°С‡РёР»Р° СЂРµР·СѓР»СЊС‚Р°С‚Сѓ, РґРѕРєРё РЅРµ РЅР°С‚РёСЃРЅРµ В«РЎР°Р№С‚В» РІСЂСѓС‡РЅСѓ.

        Р’РёРєР»РёРєР°С”С‚СЊСЃСЏ Р· РѕР±СЂРѕР±РЅРёРєР° РїРѕРґС–Р№ Р°РіРµРЅС‚Р°, С‚РѕРјСѓ РЅС–С‡РѕРіРѕ РЅРµ СЂРѕР±РёС‚СЊ,
        СЏРєС‰Рѕ С–РЅСЃС‚СЂСѓРјРµРЅС‚ РЅРµ РїСЂРѕ СЃР°Р№С‚ Р°Р±Рѕ СЏРєС‰Рѕ Р·Р°РїСѓСЃРє РЅРµ РІРґР°РІСЃСЏ.
        """
        if not ok or name not in ("app_start", "app_restart", "project_screenshot"):
            return
        live = getattr(self, "live_preview", None)
        controller = getattr(self, "app", None)
        if live is None or controller is None:
            return
        try:
            url = controller.url
        except Exception:                            # noqa: BLE001
            url = ""
        if not url:
            return
        # РџРѕРєР°Р·СѓС”РјРѕ РїР°РЅРµР»СЊ С– РІС–РґРєСЂРёРІР°С”РјРѕ Р°РґСЂРµСЃСѓ вЂ” Р»СЋРґРёРЅР° РѕРґСЂР°Р·Сѓ Р±Р°С‡РёС‚СЊ
        # СЃРІС–Р№ СЃР°Р№С‚ С– РјРѕР¶Рµ РЅР°С‚РёСЃРєР°С‚Рё РєРЅРѕРїРєРё, СЏРє Сѓ Р·РІРёС‡Р°Р№РЅРѕРјСѓ Р±СЂР°СѓР·РµСЂС–.
        try:
            self.show_bottom("site")
            live.open_url(url)
            self.set_status(f"РЎР°Р№С‚ РїСЂРѕС”РєС‚Сѓ РІС–РґРєСЂРёС‚Рѕ: {url}")
        except (tk.TclError, AttributeError):
            LOG.debug("РџР°РЅРµР»СЊ В«РЎР°Р№С‚В» РЅРµ РІС–РґРєСЂРёР»Р°СЃСЊ", exc_info=True)
        del text

    # в”Ђв”Ђ СЃРїСЂР°РІРё: Р¶РёРІС– РєСЂРѕРєРё СЂРѕР±РѕС‚Рё Р°РіРµРЅС‚Р° в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _case_begin(self, text: str) -> None:
        """РќРѕРІРёР№ Р·Р°РїРёС‚ вЂ” РІС–РґРєСЂРёРІР°С”РјРѕ СЃРїСЂР°РІСѓ Р№ СЂРѕР·РіРѕСЂС‚Р°С”РјРѕ С—С— РІ РїР°РЅРµР»С–."""
        self.case_book.begin(text)
        try:
            self.cases_panel.expand_active()
            self.cases_panel.refresh()
        except (tk.TclError, AttributeError):
            pass

    def _case_on_event(self, event) -> None:
        """РџРµСЂРµРєР»Р°СЃС‚Рё РїРѕРґС–СЋ Р°РіРµРЅС‚Р° РІ РєСЂРѕРє СЃРїСЂР°РІРё."""
        kind = getattr(event, "kind", "")
        text = (getattr(event, "text", "") or "").strip()
        data = getattr(event, "data", {}) or {}
        # РљСЂРѕРє РїР»Р°РЅСѓ С‡РµСЂРіРё РІРµРґРµ РІР»Р°СЃРЅРёР№ Р¶СѓСЂРЅР°Р»: РєРѕР¶РЅР° СЂРµР°Р»СЊРЅР° РґС–СЏ Р°РіРµРЅС‚Р°
        # РїРѕС‚СЂР°РїР»СЏС” РІ РЅСЊРѕРіРѕ, С‰РѕР± РєР°СЂС‚РєР° В«С‰Рѕ Р·СЂРѕР±РёР»Р° РјРѕРґРµР»СЊВ» РїРѕРєР°Р·СѓРІР°Р»Р°
        # СЃРїСЂР°РІР¶РЅС– РІРёРєР»РёРєРё Р№ СЂРµР·СѓР»СЊС‚Р°С‚Рё, Р° РЅРµ РїРµСЂРµРєР°Р· РІС–РґРїРѕРІС–РґС–.
        # ``getattr`` РїРѕС‚СЂС–Р±РµРЅ, Р±Рѕ РјРµС‚РѕРґ РІРёРєР»РёРєР°СЋС‚СЊ С– С‚РµСЃС‚Рё РЅР° В«Р·Р°РіР»СѓС€С†С–В»
        # Р±РµР· РїРѕРІРЅРѕРіРѕ СЃС‚Р°РЅСѓ РІС–РєРЅР°.
        if getattr(self, "_plan_step_active", False):
            self._note_plan_activity(kind, text, data)
        try:
            if kind == "status":
                if text:
                    # В«Р—Р°РїРёС‚ РґРѕ РјРѕРґРµР»С–вЂ¦В» вЂ” РѕРєСЂРµРјР° РІС–С…Р°, РЅРµ РєСЂРѕРє С–РЅСЃС‚СЂСѓРјРµРЅС‚Р°.
                    self.case_book.add_step(text)
            elif kind == "tool_call":
                self.case_book.add_step(text or f"{data.get('name', 'С–РЅСЃС‚СЂСѓРјРµРЅС‚')}",
                                        key=str(data.get("call_id") or ""))
            elif kind == "tool_result":
                self.case_book.finish_step(
                    key=str(data.get("call_id") or ""),
                    text=data.get("name") or "",
                    ok=bool(data.get("ok", True)),
                )
                # РђРіРµРЅС‚ Р·Р°РїСѓСЃС‚РёРІ Р·Р°СЃС‚РѕСЃСѓРЅРѕРє вЂ” РѕРґСЂР°Р·Сѓ РїРѕРєР°Р·СѓС”РјРѕ РїСЂРµРІ'СЋ.
                if (str(data.get("name")) == "app_start"
                        and bool(data.get("ok", False))):
                    self._ui_call(self._auto_show_preview)
            elif kind == "tool_call":
                # Р“РѕС‚СѓС”РјРѕСЃСЊ РґРѕ СЃРєСЂС–РЅС€РѕС‚Р°: РїСЂРµРІ'СЋ РјР°С” Р±СѓС‚Рё РІРёРґРёРјРёРј.
                if str(data.get("name")) == "app_screenshot":
                    self._ui_call(self._auto_show_preview)
            elif kind == "error":
                self.case_book.add_step(text or "РџРѕРјРёР»РєР°", status=cases_panel.FAILED)
            elif kind == "done":
                ok = bool(data.get("ok", True))
                summary = getattr(self.chat.runner, "last_answer", "") if self.chat.runner else ""
                error = getattr(self.chat.runner, "last_error", "") if self.chat.runner else ""
                self.case_book.end(ok=ok, summary=summary, error=error)
        except Exception:  # noqa: BLE001 - СЃРїСЂР°РІРё РЅРµ РјР°СЋС‚СЊ Р»Р°РјР°С‚Рё Р°РіРµРЅС‚Р°
            LOG.debug("РќРµ РІРґР°Р»РѕСЃСЊ РѕРЅРѕРІРёС‚Рё СЃРїСЂР°РІСѓ", exc_info=True)

    def _note_plan_activity(self, kind: str, text: str,
                            data: dict) -> None:
        """Р—Р°РїРёСЃР°С‚Рё СЂРµР°Р»СЊРЅСѓ РґС–СЋ Р°РіРµРЅС‚Р° РІ Р¶СѓСЂРЅР°Р» РїРѕС‚РѕС‡РЅРѕРіРѕ РєСЂРѕРєСѓ С‡РµСЂРіРё."""
        task = self.executor.current
        if task is None:
            return
        try:
            if kind == "status" and text:
                self.executor.note_step(text)
            elif kind == "tool_call":
                name = str(data.get("name") or "")
                arguments = str(data.get("arguments") or "")
                label = f"{name}({arguments})" if arguments else name
                task.add_history("tool", label)
                self.executor.note_step(label, status=queue_engine.RUNNING)
            elif kind == "tool_result":
                name = str(data.get("name") or "С–РЅСЃС‚СЂСѓРјРµРЅС‚")
                ok = bool(data.get("ok", True))
                head = " ".join((text or "").split())[:220]
                task.add_history("tool_ok" if ok else "tool_fail",
                                 f"{name}: {head}" if head else name)
                if name in ("write_file", "edit_file"):
                    self._collect_task_files(task, name, head)
            elif kind == "error" and text:
                task.add_history("error", text)
                self.executor.note_step(text, status=queue_engine.RUNNING)
            elif kind == "reasoning" and text:
                # Р’РёРјРѕРіР°: РїРѕРєР°Р·СѓРІР°С‚Рё РљРћР РћРўРљРР™ РЎРўРђРўРЈРЎ РµС‚Р°РїСѓ, Р° РЅРµ РІРЅСѓС‚СЂС–С€РЅС–
                # РїСЂРёС…РѕРІР°РЅС– РјС–СЂРєСѓРІР°РЅРЅСЏ РјРѕРґРµР»С–. РЎРёСЂС– reasoning-С‚РµРєСЃС‚Рё РІР¶Рµ
                # Р¶РёРІСѓС‚СЊ Сѓ Р·РіРѕСЂРЅСѓС‚РѕРјСѓ Р¶СѓСЂРЅР°Р»С– СЂРѕР±РѕС‚Рё РІ С‡Р°С‚С– (С†Рµ РЅР°СЏРІРЅР°
                # С„СѓРЅРєС†С–СЏ), Р° РІ РєР°СЂС‚С†С– РєСЂРѕРєСѓ РјР°С” Р±СѓС‚Рё Р»РёС€Рµ СЃС‚РёСЃР»РёР№ РїС–РґРїРёСЃ:
                # РїРµСЂС€Рµ СЂРµС‡РµРЅРЅСЏ, РѕР±СЂС–Р·Р°РЅРµ РґРѕ 90 СЃРёРјРІРѕР»С–РІ.
                first = " ".join(text.split()).split(". ")[0][:90]
                self.executor.note_step(f"РјС–СЂРєСѓСЋ: {first}", status=queue_engine.RUNNING)
            self.task_center.refresh()
        except Exception:  # noqa: BLE001 - Р¶СѓСЂРЅР°Р» РєСЂРѕРєСѓ РЅРµ РјР°С” Р»Р°РјР°С‚Рё Р°РіРµРЅС‚Р°
            LOG.debug("Р–СѓСЂРЅР°Р» РєСЂРѕРєСѓ РЅРµ РѕРЅРѕРІРёРІСЃСЏ", exc_info=True)

    def _collect_task_files(self, task: queue_engine.QueueTask, tool: str,
                            text: str) -> None:
        """Р”РѕРґР°С‚Рё РґРѕ РєСЂРѕРєСѓ С„Р°Р№Р»Рё, СЏРєС– Р°РіРµРЅС‚ СЃРїСЂР°РІРґС– Р·Р°РїРёСЃР°РІ.

        Р‘РµСЂРµРјРѕ Р»РёС€Рµ С‚Рµ, С‰Рѕ РЎРҐРћР–Р• РЅР° С€Р»СЏС… РґРѕ С„Р°Р№Р»Сѓ:

        * С–РјРµРЅР° РІС–РґРЅРѕСЃРЅРѕ РїСЂРѕС”РєС‚Сѓ (Сѓ РІРёРІРѕРґС– Р±СѓРІР°С” РїРѕРІРЅРёР№ С€Р»СЏС… вЂ” Р№РѕРіРѕ
          РїСЂРёРІРѕРґРёРјРѕ РґРѕ РІС–РґРЅРѕСЃРЅРѕРіРѕ);
        * СЂРѕР·С€РёСЂРµРЅРЅСЏ Р· РІС–РґРѕРјРѕРіРѕ РїРµСЂРµР»С–РєСѓ ``task_executor.CODE_SUFFIXES``.

        Р Р°РЅС–С€Рµ СЃСЋРґРё РїРѕС‚СЂР°РїР»СЏР»Рѕ Р±СѓРґСЊ-С‰Рѕ Р· РєСЂР°РїРєРѕСЋ вЂ” ``calc.add``,
        ``unittest.TestCase``, ``self.assertEq``. РЈ Р·РІС–С‚С– С†Рµ РІРёРіР»СЏРґР°Р»Рѕ СЏРє
        В«Р·РјС–РЅРµРЅС– С„Р°Р№Р»РёВ», С– РєРѕСЂРёСЃС‚СѓРІР°С‡ Р±Р°С‡РёРІ РІРёРіР°РґР°РЅС– РЅР°Р·РІРё.
        """
        import re as _re

        root = self._project_root()
        suffixes = "|".join(
            _re.escape(item.lstrip("."))
            for item in task_executor.CODE_SUFFIXES)
        pattern = _re.compile(
            r"[\w./\\-]+\.(?:" + suffixes + r")\b", _re.IGNORECASE)
        written: list[str] = []
        for match in pattern.finditer(text or ""):
            name = match.group(0)
            if root is not None:
                candidate = Path(name)
                if candidate.is_absolute():
                    try:
                        name = str(candidate.relative_to(Path(root)))
                    except ValueError:
                        # РџРѕР·Р° РїСЂРѕС”РєС‚РѕРј вЂ” Р»РёС€Р°С”РјРѕ С‚С–Р»СЊРєРё С–Рј'СЏ С„Р°Р№Р»Сѓ.
                        name = candidate.name
            name = name.replace("/", "\\").lstrip(".\\")
            if not name:
                continue
            # РЎР»СѓР¶Р±РѕРІС– В«С…РІРѕСЃС‚РёВ» РЅР° РєС€С‚Р°Р»С‚ ``unittest.TestCase`` Р°Р±Рѕ
            # ``self.assertEqual`` вЂ” С†Рµ Р°С‚СЂРёР±СѓС‚Рё РєРѕРґСѓ, Р° РЅРµ С„Р°Р№Р»Рё. Р¤Р°Р№Р»
            # РјСѓСЃРёС‚СЊ С–СЃРЅСѓРІР°С‚Рё РІ РїСЂРѕС”РєС‚С– (Р°Р±Рѕ РјР°С‚Рё С‚РёРїРѕРІРµ СЂРѕР·С€РёСЂРµРЅРЅСЏ Р№
            # СЂРѕР·РґС–Р»СЊРЅРёРє С€Р»СЏС…Сѓ), С–РЅР°РєС€Рµ С†Рµ РІРёРіР°РґРєР° Р· С‚РµРєСЃС‚Сѓ РІРёРєР»РёРєСѓ.
            if root is not None:
                exists = (Path(root) / name).exists()
                if not exists:
                    found = next((p for p in Path(root).rglob(Path(name).name)
                                  if p.is_file()), None)
                    if found is None:
                        continue
            if name not in written:
                written.append(name)
        task.files_changed = list(dict.fromkeys(list(task.files_changed) + written))

    # в”Ђв”Ђ СЃРєС–Р»Рё в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    # в”Ђв”Ђ СЂРµР¶РёРј РґРѕР·РІРѕР»С–РІ, С†С–Р»СЊ, РІС–РґРіСѓРє в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _on_permission_change(self, mode: str) -> None:
        """Р РµР¶РёРј РґРѕР·РІРѕР»С–РІ Р·РјС–РЅРёРІСЃСЏ РІ РєРѕРјРїРѕР·РµСЂС– вЂ” Р·Р°СЃС‚РѕСЃРѕРІСѓС”РјРѕ РґРѕ Р°РіРµРЅС‚Р° Р№ СЂРµС”СЃС‚СЂСѓ."""
        active = permissions.normalise_mode(mode)
        self.agent.permission_mode = active
        self.settings.agent.permission_mode = active
        self.settings.save()
        # В«РџРёС‚Р°С‚Рё РґРѕР·РІС–Р» РЅР° РєРѕРјР°РЅРґРёВ» вЂ” РѕРєСЂРµРјРёР№ РїРµСЂРµРјРёРєР°С‡; Сѓ РїРѕРІРЅРѕРјСѓ РґРѕСЃС‚СѓРїС–
        # РІС–РЅ Р»РёС€Р°С”С‚СЊСЃСЏ СЏРє С”, РІ С–РЅС€РёС… СЂРµР¶РёРјР°С… РєРѕРјР°РЅРґРё Р№ С‚Р°Рє РѕР±РјРµР¶РµРЅС–.
        self.registry.confirm_commands = (self.settings.agent.confirm_commands
                                          and active != permissions.FULL)
        self.set_status(f"Р”РѕР·РІРѕР»Рё: {permissions.label_for(active)}")

    def _set_goal(self, text: str) -> None:
        """Р—Р°РїР°Рј'СЏС‚Р°С‚Рё С†С–Р»СЊ СЃРµСЃС–С— Р№ РїРѕРєР°Р·Р°С‚Рё С—С— РІ Р·Р°РіРѕР»РѕРІРєСѓ С‡Р°С‚Сѓ."""
        goal = (text or "").strip()
        if not goal:
            return
        self.current_goal = goal
        # Р‘Р»РѕРє В«РџРѕС‚РѕС‡РЅР° С†С–Р»СЊВ» Р¶РёРІРµ РІ РєР°СЂС‚С†С– РіР»РёР±РѕРєРѕРіРѕ Р°РЅР°Р»С–Р·Сѓ.
        try:
            self.chat.set_goal(goal)
        except (tk.TclError, AttributeError):
            LOG.debug("Р¦С–Р»СЊ РЅРµ РїРѕС‚СЂР°РїРёР»Р° РІ РєР°СЂС‚РєСѓ Р°РЅР°Р»С–Р·Сѓ", exc_info=True)
        chat = self.chat_store.active()
        if chat is not None:
            self.chat_store.append("system", f"Р¦С–Р»СЊ СЃРµСЃС–С—: {goal}")
            self.chat_list.refresh()
        self.set_status(f"Р¦С–Р»СЊ: {goal[:80]}")
        try:
            self.chat._note(f"Р¦С–Р»СЊ СЃРµСЃС–С—: {goal}")
        except (tk.TclError, AttributeError):
            pass

    def _save_feedback(self, text: str) -> None:
        """Р—Р±РµСЂРµРіС‚Рё РІС–РґРіСѓРє РїСЂРѕ СЃРµСЃС–СЋ Сѓ С„Р°Р№Р» РїРѕСЂСѓС‡ С–Р· РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏРјРё."""
        from .config import app_data_dir

        target = app_data_dir() / "feedback.md"
        stamp = time.strftime("%Y-%m-%d %H:%M")
        try:
            with target.open("a", encoding="utf-8") as handle:
                handle.write(f"\n## {stamp}\n{text.strip()}\n")
            self.set_status(f"Р’С–РґРіСѓРє Р·Р±РµСЂРµР¶РµРЅРѕ: {target}")
        except OSError as exc:
            self.set_status(f"РќРµ РІРґР°Р»РѕСЃСЊ Р·Р±РµСЂРµРіС‚Рё РІС–РґРіСѓРє: {exc}")

    # в”Ђв”Ђ РјРѕРґРµР»СЊ РґР»СЏ РїРѕС‚РѕС‡РЅРѕРіРѕ С‡Р°С‚Сѓ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    # в”Ђв”Ђ РіРѕР»РѕСЃ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _apply_voice_settings(self) -> None:
        """РџРµСЂРµРґР°С‚Рё РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏ РіРѕР»РѕСЃСѓ Сѓ РІС–РґР¶РµС‚ РєРЅРѕРїРєРё."""
        cfg = self.settings.voice
        try:
            vs = self.chat.voice_settings
            vs.enabled = bool(cfg.enabled)
            vs.auto_send = bool(cfg.auto_send)
            vs.speak_replies = bool(cfg.speak_replies)
            vs.language = cfg.language or "uk-UA"
            vs.whisper_dir = cfg.whisper_dir
            vs.model_path = cfg.model_path
            vs.seconds = float(cfg.seconds or 5.0)
        except (tk.TclError, AttributeError):
            pass

    def _on_voice_query(self, text: str) -> None:
        """Р РѕР·РїС–Р·РЅР°РЅСѓ С„СЂР°Р·Сѓ РЅР°РґС–СЃР»Р°С‚Рё Р°РіРµРЅС‚Сѓ."""
        self.show_chat(True)
        self._set_agent_state("РїСЂР°С†СЋС”")
        self.chat._send(text)

    def _on_voice_action(self, action: str) -> None:
        """Р“РѕР»РѕСЃРѕРІР° РєРѕРјР°РЅРґР° С–РЅС‚РµСЂС„РµР№СЃСѓ."""
        if action == "files":
            self.show_side("explorer")
        elif action == "terminal":
            self.show_bottom("terminal")

    def _on_agent_answer_for_voice(self, text: str) -> None:
        """РћР·РІСѓС‡РёС‚Рё РІС–РґРїРѕРІС–РґСЊ, СЏРєС‰Рѕ РіРѕР»РѕСЃ СѓРІС–РјРєРЅРµРЅРѕ."""
        if not self.settings.voice.speak_replies and not getattr(self.chat, "speak_last", False):
            return
        self.chat.speak_text(text)

    def _on_chat_model_pick(self, name: str) -> None:
        """РњРѕРґРµР»СЊ РѕР±СЂР°РЅР° РґР»СЏ С†СЊРѕРіРѕ С‡Р°С‚Сѓ вЂ” Р·Р°СЃС‚РѕСЃСѓРІР°С‚Рё РґРѕ Р°РіРµРЅС‚Р° Р№ Р·Р±РµСЂРµРіС‚Рё.

        Р’РђР–Р›РР’Рћ РїСЂРѕ СѓР·РіРѕРґР¶РµРЅС–СЃС‚СЊ. Р Р°РЅС–С€Рµ С‚СѓС‚ Р·РјС–РЅСЋРІР°РІСЃСЏ Р›РРЁР•
        ``llm.model``, Р° ``engine.model_path`` Р»РёС€Р°РІСЃСЏ РІРєР°Р·СѓРІР°С‚Рё РЅР° С–РЅС€Сѓ
        РјРѕРґРµР»СЊ. РЎР°РјРµ С‚Р°Рє Сѓ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏС… РѕРїРёРЅРёР»РёСЃСЊ В«MinistralВ» РІ РѕРґРЅРѕРјСѓ
        РїРѕР»С– Р№ В«qwen2.5-coder-14bВ» Сѓ РґСЂСѓРіРѕРјСѓ вЂ” С– РІС–РєРЅРѕ РїРѕРєР°Р·СѓРІР°Р»Рѕ РѕР±РёРґРІС–.

        РўРµРїРµСЂ РѕР±РёРґРІР° РїРѕР»СЏ СѓР·РіРѕРґР¶СѓСЋС‚СЊСЃСЏ, СЏРєС‰Рѕ РјРѕРґРµР»СЊ С” Р»РѕРєР°Р»СЊРЅРёРј С„Р°Р№Р»РѕРј.
        """
        name = (name or "").strip()
        if not name:
            return
        self.settings.llm.model = name
        # в”Ђв”Ђ РЈР·РіРѕРґРёС‚Рё С€Р»СЏС… РґРѕ С„Р°Р№Р»Сѓ РјРѕРґРµР»С– в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        # ``engine.model_path`` вЂ” С†Рµ С‚Рµ, С‰Рѕ РЎРџР РђР’Р”Р† Р·Р°РІР°РЅС‚Р°Р¶СѓС” СЂСѓС€С–Р№. РЇРєС‰Рѕ
        # РІС–РЅ РІРєР°Р·СѓС” РЅР° С–РЅС€РёР№ С„Р°Р№Р», РЅС–Р¶ РІРёР±СЂР°РЅР° РјРѕРґРµР»СЊ, С–РЅС‚РµСЂС„РµР№СЃ РїРѕРєР°Р·СѓС”
        # РѕРґРЅСѓ РјРѕРґРµР»СЊ, Р° РїСЂР°С†СЋС” С–РЅС€Р°.
        self._adopt_model_path_for(name)
        self.agent.llm_settings = self.settings.llm
        self.settings.save()
        self._invalidate_model_state(reason=f"РІРёР±С–СЂ РјРѕРґРµР»С– {name}")
        self._apply_context_limit()
        chat = self.chat_store.active()
        if chat is not None:
            chat.model = name
            self.chat_store.save()
        # РћРґРёРЅ РїС–РґРїРёСЃ РјРѕРґРµР»С– вЂ” РІ СѓСЃС–С… РІС–РґР¶РµС‚Р°С….
        self._sync_model_labels()
        self.set_status(f"РњРѕРґРµР»СЊ С†СЊРѕРіРѕ С‡Р°С‚Сѓ: {name}")

    def _adopt_model_path_for(self, name: str) -> bool:
        """Р—РЅР°Р№С‚Рё С„Р°Р№Р» РјРѕРґРµР»С– Р·Р° РЅР°Р·РІРѕСЋ Р№ Р·Р°РїРёСЃР°С‚Рё Р№РѕРіРѕ РІ ``engine.model_path``.

        РџРѕРІРµСЂС‚Р°С” True, СЏРєС‰Рѕ С€Р»СЏС… РѕРЅРѕРІР»РµРЅРѕ. РЇРєС‰Рѕ С„Р°Р№Р»Сѓ РЅРµРјР°С” (С…РјР°СЂРЅР° РјРѕРґРµР»СЊ
        Р°Р±Рѕ РЅР°Р·РІР° Р±РµР· РІС–РґРїРѕРІС–РґРЅРёРєР°) вЂ” С€Р»СЏС… РћР§РР©РђР„РўР¬РЎРЇ: РєСЂР°С‰Рµ В«РЅРµ Р·Р°РґР°РЅРѕВ»,
        РЅС–Р¶ С€Р»СЏС… РґРѕ Р·РѕРІСЃС–Рј С–РЅС€РѕС— РјРѕРґРµР»С–, СЏРєРёР№ СЂСѓС€С–Р№ Р·Р°РІР°РЅС‚Р°Р¶РёС‚СЊ Р·Р°РјС–СЃС‚СЊ
        РІРёР±СЂР°РЅРѕС—.
        """
        wanted = (name or "").strip().lower()
        if not wanted:
            return False
        candidates: list[Path] = []
        try:
            candidates = list(hub.local_models())
        except Exception:  # noqa: BLE001 - РґРёСЃРє РјРѕР¶Рµ Р±СѓС‚Рё РЅРµРґРѕСЃС‚СѓРїРЅРёР№
            LOG.debug("Р›РѕРєР°Р»СЊРЅС– РјРѕРґРµР»С– РЅРµРґРѕСЃС‚СѓРїРЅС–", exc_info=True)
        exact = [path for path in candidates if path.stem.lower() == wanted]
        if not exact:
            exact = [path for path in candidates
                     if wanted in path.stem.lower()]
        current = self.settings.engine.model_path
        if exact:
            chosen = exact[0]
            if str(current) != str(chosen):
                LOG.info("РЁР»СЏС… РјРѕРґРµР»С– СѓР·РіРѕРґР¶РµРЅРѕ: %s в†’ %s", current, chosen.name)
            self.settings.engine.model_path = str(chosen)
            return True
        # Р¤Р°Р№Р»Сѓ РЅРµРјР°С”: С€Р»СЏС… РґРѕ С–РЅС€РѕС— РјРѕРґРµР»С– Р»РёС€Р°С‚Рё РЅРµ РјРѕР¶РЅР°.
        if current and Path(str(current)).stem.lower() != wanted:
            LOG.info("РЁР»СЏС… РјРѕРґРµР»С– РѕС‡РёС‰РµРЅРѕ: РІС–РЅ РІРєР°Р·СѓРІР°РІ РЅР° %s, Р° РІРёР±СЂР°РЅРѕ %s",
                     Path(str(current)).name, name)
            self.settings.engine.model_path = ""
        return False

    def _on_chat_effort_pick(self, key: str) -> None:
        """Р С–РІРµРЅСЊ Р·СѓСЃРёР»Р»СЏ РґР»СЏ reasoning-РјРѕРґРµР»РµР№."""
        level = effort.get(key)
        self.settings.llm.reasoning_effort = level.key
        if not level.is_default and level.temperature is not None:
            self.settings.llm.temperature = level.temperature
        self.settings.save()
        chat = self.chat_store.active()
        if chat is not None:
            meta = getattr(chat, "effort", "")
            setattr(chat, "effort", level.key)
            self.chat_store.save()
        self.set_status(f"Р—СѓСЃРёР»Р»СЏ РјРѕРґРµР»С–: {level.label}")

    def _sync_chat_model(self) -> None:
        """РџС–РґСЃС‚Р°РІРёС‚Рё РјРѕРґРµР»СЊ РїРѕС‚РѕС‡РЅРѕРіРѕ С‡Р°С‚Сѓ (Р°Р±Рѕ С‚РёРїРѕРІСѓ) Сѓ РєРѕРјРїРѕР·РµСЂ."""
        chat = self.chat_store.active()
        model = (getattr(chat, "model", "") if chat is not None else "") or self.settings.llm.model
        effort_key = (getattr(chat, "effort", "") if chat is not None else "") or "default"
        try:
            self.chat.set_chat_model(model, effort_key)
            self.chat.set_available_models(self._known_models())
        except (tk.TclError, AttributeError):
            pass

    def _known_models(self) -> list[str]:
        """Р’С–РґРѕРјС– РјРѕРґРµР»С–: Р· РїСЂРѕРІР°Р№РґРµСЂР° + РїРѕС‚РѕС‡РЅР° + Р»РѕРєР°Р»СЊРЅС–."""
        models: list[str] = []
        cloud = getattr(self.settings, "cloud", None)
        if cloud is not None and getattr(cloud, "provider", ""):
            models.extend(cloud_agents.models_for(cloud.provider))
        try:
            models.extend("" if not p.name else p.stem for p in hub.local_models())
        except Exception:  # noqa: BLE001
            LOG.debug("РќРµ РІРґР°Р»РѕСЃСЊ РїСЂРѕС‡РёС‚Р°С‚Рё Р»РѕРєР°Р»СЊРЅС– РјРѕРґРµР»С–", exc_info=True)
        current = self.settings.llm.model
        if current and current not in models:
            models.insert(0, current)
        seen: set[str] = set()
        unique: list[str] = []
        for name in models:
            if name and name not in seen:
                seen.add(name)
                unique.append(name)
        return unique

    def export_current_chat(self) -> None:
        """Р•РєСЃРїРѕСЂС‚ РїРѕС‚РѕС‡РЅРѕС— СЂРѕР·РјРѕРІРё Сѓ Markdown."""
        chat = self.chat_store.active()
        if chat is None:
            self.set_status("РќРµРјР°С” Р°РєС‚РёРІРЅРѕС— СЂРѕР·РјРѕРІРё РґР»СЏ РµРєСЃРїРѕСЂС‚Сѓ.")
            return
        from tkinter import filedialog

        target = filedialog.asksaveasfilename(
            parent=self, title="Р•РєСЃРїРѕСЂС‚ Р¶СѓСЂРЅР°Р»Сѓ СЃРµСЃС–С—", defaultextension=".md",
            initialfile=f"{(chat.title or 'chat')[:40]}.md",
            filetypes=[("Markdown", "*.md"), ("РЈСЃС– С„Р°Р№Р»Рё", "*.*")],
        )
        if not target:
            return
        try:
            Path(target).write_text(self.chat_store.export_markdown(chat.id),
                                    encoding="utf-8")
            self.set_status(f"Р•РєСЃРїРѕСЂС‚РѕРІР°РЅРѕ: {target}")
        except OSError as exc:
            self.set_status(f"РќРµ РІРґР°Р»РѕСЃСЊ Р·Р±РµСЂРµРіС‚Рё: {exc}")

    def _use_skill_by_name(self, name: str) -> None:
        skill = self.skill_book.get(name)
        if skill is None:
            self.set_status(f"РЎРєС–Р»Р° В«{name}В» РЅРµ Р·РЅР°Р№РґРµРЅРѕ.")
            return
        self._use_skill(skill)

    def _use_skill(self, skill: skills_module.Skill) -> None:
        self.show_chat(True)
        self.chat._send(self._skill_prompt(skill))
        self.set_status(f"РЎРєС–Р» В«{skill.name}В» РЅР°РґС–СЃР»Р°РЅРѕ Р°РіРµРЅС‚Сѓ.")

    # в”Ђв”Ђ С„Р°Р№Р»Рё в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def open_folder_dialog(self) -> None:
        """Р’РёР±СЂР°С‚Рё С‚РµРєСѓ РїСЂРѕС”РєС‚Сѓ Р№ РѕРґСЂР°Р·Сѓ РїС–РґРєР»СЋС‡РёС‚Рё С—С—.

        ``initialdir`` РјР°С” РІРєР°Р·СѓРІР°С‚Рё РЅР° РЎРџР РђР’Р–РќР® С‚РµРєСѓ: СЏРєС‰Рѕ Р·Р±РµСЂРµР¶РµРЅР° С‚РµРєР°
        Р·РЅРёРєР»Р° (С„Р»РµС€РєР°, РїРµСЂРµРЅРµСЃРµРЅРёР№ РїСЂРѕС”РєС‚), РґС–Р°Р»РѕРі РЅР° Windows С‚РёС…Рѕ РЅРµ
        РІС–РґРєСЂРёРІР°РІСЃСЏ Р№ РєРЅРѕРїРєР° В«Р’РёР±СЂР°С‚Рё РїР°РїРєСѓВ» РІРёРіР»СЏРґР°Р»Р° РјРµСЂС‚РІРѕСЋ.
        """
        start = str(self.settings.workspace or "")
        if not start or not Path(start).is_dir():
            start = str(Path.home())
        folder = filedialog.askdirectory(parent=self, title="Р’РёР±СЂР°С‚Рё РїР°РїРєСѓ РїСЂРѕС”РєС‚Сѓ",
                                         initialdir=start, mustexist=True)
        if not folder:
            # РљРѕСЂРёСЃС‚СѓРІР°С‡ СЃРєР°СЃСѓРІР°РІ вЂ” С†Рµ РЅРµ РїРѕРјРёР»РєР°, Р°Р»Рµ РµРєСЂР°РЅ РјР°С” С†Рµ СЃРєР°Р·Р°С‚Рё.
            gate = getattr(self, "project_gate", None)
            if gate is not None:
                try:
                    gate.set_hint("РўРµРєСѓ РЅРµ РІРёР±СЂР°РЅРѕ. РЎРїСЂРѕР±СѓР№ С‰Рµ СЂР°Р·.")
                except (tk.TclError, AttributeError):
                    pass
            return
        self.set_workspace(Path(folder))

    def _autonomous_other_project(self, folder: Path) -> bool:
        """Р§Рё Р°РІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј Р·Р°СЂР°Р· РїСЂР°С†СЋС” РґР»СЏ Р†РќРЁРћР‡ С‚РµРєРё."""
        engine = getattr(self, "autonomous_engine", None)
        if engine is None or not engine.active or engine.project is None:
            return False
        try:
            return engine.project.resolve() != Path(folder).resolve()
        except OSError:
            return True

    def _confirm_autonomous_project_switch(self, folder: Path) -> bool:
        """РЎРїРёС‚Р°С‚Рё РїС–РґС‚РІРµСЂРґР¶РµРЅРЅСЏ РїРµСЂРµРґ Р·РјС–РЅРѕСЋ С‚РµРєРё РїС–Рґ Р°РІС‚РѕРЅРѕРјРЅРёРј СЂРµР¶РёРјРѕРј."""
        engine = self.autonomous_engine
        current = engine.project.name if engine.project else "?"
        answer = messagebox.askyesno(
            "РђРІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј",
            f"РђРІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј РїСЂР°С†СЋС” РґР»СЏ В«{current}В».\n\n"
            f"РџРµСЂРµР№С‚Рё РЅР° В«{folder.name}В»? Р РµР¶РёРј Р±СѓРґРµ Р—РЈРџРРќР•РќРћ, С– Р№РѕРіРѕ Р·Р°РґР°С‡С– "
            f"Р·РЅС–РјСѓС‚СЊСЃСЏ Р· С‡РµСЂРіРё вЂ” Р°РіРµРЅС‚ РЅРµ РїСЂР°РІРёС‚РёРјРµ С„Р°Р№Р»Рё С–РЅС€РѕРіРѕ РїСЂРѕС”РєС‚Сѓ.",
            parent=self)
        if not answer:
            self.set_status("Р—РјС–РЅСѓ РїСЂРѕС”РєС‚Сѓ СЃРєР°СЃРѕРІР°РЅРѕ: Р°РІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј РїСЂР°С†СЋС” РґР°Р»С–.")
        return bool(answer)

    def set_workspace(self, folder: Path) -> None:
        folder = Path(folder).resolve()
        if not folder.is_dir():
            messagebox.showerror("РџР°РїРєР°", f"РќРµ С–СЃРЅСѓС”: {folder}", parent=self)
            return
        # РђРІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј РїСЂРёРІ'СЏР·Р°РЅРёР№ РґРѕ С‚РµРєРё: РјРѕРІС‡РєРё РїРµСЂРµРЅРѕСЃРёС‚Рё Р№РѕРіРѕ РЅР°
        # С–РЅС€РёР№ РїСЂРѕС”РєС‚ РЅРµР±РµР·РїРµС‡РЅРѕ вЂ” Р°РіРµРЅС‚ РїРѕС‡Р°РІ Р±Рё РїСЂР°РІРёС‚Рё С‡СѓР¶С– С„Р°Р№Р»Рё Р±РµР·
        # РІС–РґРѕРјР° РєРѕСЂРёСЃС‚СѓРІР°С‡Р°. РўРѕРјСѓ СЃРїРµСЂС€Сѓ Р·СѓРїРёРЅСЏС”РјРѕ Р№ РїРёС‚Р°С”РјРѕ РїС–РґС‚РІРµСЂРґР¶РµРЅРЅСЏ.
        if self._autonomous_other_project(folder):
            if not self._confirm_autonomous_project_switch(folder):
                return
            self.stop_autonomous()
        self.settings.remember_workspace(str(folder))
        self.settings.save()
        self.registry.set_root(folder)
        self.agent.set_workspace(folder)
        self.file_tree.set_root(folder)
        self.terminal.set_cwd(folder)
        self.skill_book.set_root(folder)
        self.skills_panel.refresh()
        self.ws_label.configure(text=str(folder))
        # `os.chdir` С‚СѓС‚ Р‘РЈР’, Р°Р»Рµ РІС–РЅ Р·РјС–РЅСЋС” СЂРѕР±РѕС‡Сѓ С‚РµРєСѓ Р’РЎР¬РћР“Рћ РїСЂРѕС†РµСЃСѓ:
        # С†Рµ Р»Р°РјР°С” Р±СѓРґСЊ-СЏРєРµ РїР°СЂР°Р»РµР»СЊРЅРµ РІРёРєРѕСЂРёСЃС‚Р°РЅРЅСЏ РїР°РєРµС‚Р° СЏРє Р±С–Р±Р»С–РѕС‚РµРєРё
        # Р№ СЂРѕР±РёС‚СЊ РїРѕРІРµРґС–РЅРєСѓ Р·Р°Р»РµР¶РЅРѕСЋ РІС–Рґ РїРѕСЂСЏРґРєСѓ РґС–Р№. РЈСЃС– РїС–РґСЃРёСЃС‚РµРјРё
        # (С‚РµСЂРјС–РЅР°Р», web-СЃРµСЂРІРµСЂ, С–РЅСЃС‚СЂСѓРјРµРЅС‚Рё) РѕС‚СЂРёРјСѓСЋС‚СЊ С‚РµРєСѓ СЏРІРЅРѕ вЂ”
        # `set_cwd`/`cwd=`, С‚РѕР¶ РіР»РѕР±Р°Р»СЊРЅР° Р·РјС–РЅР° РЅРµ РїРѕС‚СЂС–Р±РЅР°.
        self.title(f"{APP_NAME} {APP_VERSION} вЂ” {folder.name}")
        self._refresh_context()
        self.refresh_rag_status()
        self.after(300, self._load_mcp_async)
        self.set_status(f"Р’С–РґРєСЂРёС‚Рѕ РїСЂРѕС”РєС‚: {folder}")
        self._refresh_header()
        # РџСЂРѕС”РєС‚ РІРёР±СЂР°РЅРѕ вЂ” С‚РµРїРµСЂ С‡Р°С‚ РјРѕР¶РЅР° РІС–РґРєСЂРёРІР°С‚Рё. РЇРєС‰Рѕ РєРѕСЂРёСЃС‚СѓРІР°С‡
        # РїСЂРёР№С€РѕРІ СЃСЋРґРё Р· РµРєСЂР°РЅР° РІРёР±РѕСЂСѓ, РїРѕРІРµСЂС‚Р°С”РјРѕ Р№РѕРіРѕ РІ СЂРѕР·РјРѕРІСѓ.
        self._close_project_gate()
        if not self.chat_store.active():
            self.new_chat_session()

    def open_recent_folder(self, folder: str) -> None:
        """Р’С–РґРєСЂРёС‚Рё РїСЂРѕС”РєС‚ Р·С– СЃРїРёСЃРєСѓ РѕСЃС‚Р°РЅРЅС–С… (РјРµРЅСЋ РїСЂРѕС”РєС‚Сѓ РІ С€Р°РїС†С–)."""
        path = Path(str(folder or "").strip())
        if not path.is_dir():
            self.set_status(f"РўРµРєРё Р±С–Р»СЊС€Рµ РЅРµРјР°С”: {folder}")
            # РџСЂРёР±РёСЂР°С”РјРѕ В«РјРµСЂС‚РІРёР№В» РїСѓРЅРєС‚, С‰РѕР± РјРµРЅСЋ РЅРµ РїСЂРѕРїРѕРЅСѓРІР°Р»Рѕ РЅРµС–СЃРЅСѓСЋС‡Сѓ С‚РµРєСѓ.
            try:
                if str(path) in self.settings.recent:
                    self.settings.recent.remove(str(path))
                    self.settings.save()
            except Exception:  # noqa: BLE001 - С‡РёСЃС‚РєР° РјРµРЅСЋ РЅРµ РєСЂРёС‚РёС‡РЅР°
                LOG.debug("РќРµ РІРґР°Р»РѕСЃСЊ РїСЂРёР±СЂР°С‚Рё С‚РµРєСѓ Р· РѕСЃС‚Р°РЅРЅС–С…", exc_info=True)
            return
        self.set_workspace(path)

    # в”Ђв”Ђ РїСЂРѕС„С–Р»С– СЂРѕР±РѕС‡РѕРіРѕ РїСЂРѕСЃС‚РѕСЂСѓ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def apply_profile(self, profile) -> None:
        """Р—Р°СЃС‚РѕСЃСѓРІР°С‚Рё РіРѕС‚РѕРІРёР№ РїСЂРѕС„С–Р»СЊ СЂРѕР·РєР»Р°РґРєРё.

        РџСЂРѕС„С–Р»СЊ Р·РјС–РЅСЋС” Р›РРЁР• СЂРѕР·РјС–СЂРё Р№ РІРёРґРёРјС–СЃС‚СЊ РїР°РЅРµР»РµР№. Р’С–РЅ РЅРµ С‡С–РїР°С”
        РІС–РґРєСЂРёС‚РёС… С„Р°Р№Р»С–РІ, С‡Р°С‚С–РІ С– С‡РµСЂРіРё вЂ” С†Рµ РєРѕРјРїРѕРЅСѓРІР°РЅРЅСЏ, Р° РЅРµ СЃС‚Р°РЅ СЂРѕР±РѕС‚Рё.
        """
        if profile is None:
            return
        ui = self.settings.ui
        if profile.sidebar_width:
            ui.sidebar_width = int(profile.sidebar_width)
            self.layout.set("sidebar_width", profile.sidebar_width)
        ui.chat_width = int(profile.chat_width)
        if profile.context_width:
            ui.context_width = int(profile.context_width)
            self.layout.set("context_width", profile.context_width)
        if profile.preview_width:
            self.layout.set("preview_width", profile.preview_width)
        if profile.bottom_height:
            ui.bottom_height = int(profile.bottom_height)
            self.layout.set("bottom_height", profile.bottom_height)
        ui.chat_visible = bool(profile.chat_visible)
        ui.context_visible = bool(profile.context_visible)
        ui.bottom_visible = bool(profile.bottom_visible)

        # РџР°РЅРµР»С–: РїРѕРєР°Р·Р°С‚Рё С‚Рµ, С‰Рѕ РІ РїСЂРѕС„С–Р»С–, СЃС…РѕРІР°С‚Рё СЂРµС€С‚Сѓ.
        self.show_chat(profile.chat_visible)
        self.toggle_sidebar(profile.sidebar_width > 0)
        self.toggle_context(profile.context_visible)
        self.toggle_preview(profile.preview_visible)
        self._bottom_height = max(120, int(profile.bottom_height or 0))
        self.toggle_bottom(profile.bottom_visible)
        if profile.sidebar_width:
            try:
                self.sidebar.configure(width=int(profile.sidebar_width))
            except tk.TclError:
                pass
        self._apply_responsive()
        self._apply_sash_positions()
        self._remember_layout()
        self._refresh_header()
        self.set_status(f"РџСЂРѕС„С–Р»СЊ СЂРѕР±РѕС‡РѕРіРѕ РїСЂРѕСЃС‚РѕСЂСѓ: {profile.label}")

    # в”Ђв”Ђ Live Browser (РѕРєСЂРµРјР° СЂРѕР±РѕС‡Р° РѕР±Р»Р°СЃС‚СЊ Р· РїРѕРґС–Р»РѕРј РµРєСЂР°РЅР°) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def open_live_browser(self, url: str = "") -> bool:
        """Р’С–РґРєСЂРёС‚Рё Live Browser: СЃР°Р№С‚ РїСЂР°РІРѕСЂСѓС‡, РєРѕРґ С– С‡Р°С‚ Р»С–РІРѕСЂСѓС‡.

        Р¦Рµ РЅРµ В«С‰Рµ РѕРґРЅР° РІРєР»Р°РґРєР° Р±СЂР°СѓР·РµСЂР°В», Р° СЂРѕР±РѕС‡РёР№ СЂРµР¶РёРј: Р»С–РІР° С‡Р°СЃС‚РёРЅР° вЂ”
        СЂРµРґР°РєС‚РѕСЂ С– РґС–Р°Р»РѕРі Р· Р°РіРµРЅС‚РѕРј, РїСЂР°РІР° вЂ” Р·Р°РїСѓС‰РµРЅРёР№ СЃР°Р№С‚. РЎРїС–РІРІС–РґРЅРѕС€РµРЅРЅСЏ
        РјРѕР¶РЅР° С‚СЏРіРЅСѓС‚Рё РјРёС€РµСЋ (СЃР°С€), С– РІРѕРЅРѕ Р·Р°РїР°Рј'СЏС‚РѕРІСѓС”С‚СЊСЃСЏ.
        """
        # 1. РџСЂР°РІР° РєРѕР»РѕРЅРєР° Р· СЃР°Р№С‚РѕРј.
        self.toggle_preview(True)
        # 2. РЎР°Р№С‚: СЏРєС‰Рѕ Р°РґСЂРµСЃСѓ РЅРµ РґР°Р»Рё вЂ” Р±РµСЂРµРјРѕ РІР¶Рµ Р·Р°РїСѓС‰РµРЅРёР№ Р»РѕРєР°Р»СЊРЅРёР№
        #    СЃРµСЂРІРµСЂ Р°Р±Рѕ РїС–РґРЅС–РјР°С”РјРѕ Р№РѕРіРѕ РґР»СЏ РїСЂРѕС”РєС‚Сѓ.
        target = str(url or "").strip()
        if not target:
            target = self._running_site_url()
        if not target:
            if not self.has_project():
                self._show_project_gate(
                    reason="Live Browser РІС–РґРєСЂРёС”С‚СЊСЃСЏ, С‰РѕР№РЅРѕ Р±СѓРґРµ РІРёР±СЂР°РЅРѕ РїСЂРѕС”РєС‚.")
                self.set_status("РЎРїРµСЂС€Сѓ РІРёР±РµСЂРё С‚РµРєСѓ РїСЂРѕС”РєС‚Сѓ.")
                return False
            started = self.start_site()
            target = self._running_site_url() if started else ""
        if target:
            self.open_url_in_browser(target)
        # 3. Р—Р»С–РІР° вЂ” С„Р°Р№Р»Рё Р№ РґС–Р°Р»РѕРі: РїСЂР°С†СЋРІР°С‚Рё Р· РєРѕРґРѕРј РїРѕСЂСѓС‡ С–Р· СЂРµР·СѓР»СЊС‚Р°С‚РѕРј.
        self.show_side("explorer")
        self.show_chat(True)
        self.set_status("Live Browser: СЃР°Р№С‚ РїСЂР°РІРѕСЂСѓС‡, РєРѕРґ С– Р°РіРµРЅС‚ Р»С–РІРѕСЂСѓС‡. "
                        "РњРµР¶Сѓ РјРѕР¶РЅР° С‚СЏРіРЅСѓС‚Рё, С€РёСЂРёРЅСѓ Р·Р±РµСЂРµР¶РµРЅРѕ.")
        return True

    def _running_site_url(self) -> str:
        """РђРґСЂРµСЃР° РІР¶Рµ Р·Р°РїСѓС‰РµРЅРѕРіРѕ Р»РѕРєР°Р»СЊРЅРѕРіРѕ СЃР°Р№С‚Сѓ (``""``, СЏРєС‰Рѕ РЅРµ Р·Р°РїСѓС‰РµРЅРѕ)."""
        for holder in (getattr(self, "live_preview", None),
                       getattr(self, "preview", None)):
            url = getattr(holder, "url", "") if holder is not None else ""
            if url:
                return str(url)
        return ""

    def _browser_view(self):
        """Р’Р±СѓРґРѕРІР°РЅРёР№ Р±СЂР°СѓР·РµСЂ (РїСЂР°РІР° РєРѕР»РѕРЅРєР° Р°Р±Рѕ РЅРёР¶РЅСЏ РІРєР»Р°РґРєР° В«РЎР°Р№С‚В»)."""
        live = getattr(self, "live_preview", None)
        view = getattr(getattr(live, "inner", None), "view", None)
        if view is not None:
            return view
        return getattr(getattr(self, "preview", None), "view", None)

    def _browser_hwnd(self) -> int:
        """Р”РµСЃРєСЂРёРїС‚РѕСЂ РІС–РєРЅР° РІР±СѓРґРѕРІР°РЅРѕРіРѕ Р±СЂР°СѓР·РµСЂР° (0 вЂ” РІС–РєРЅР° РЅРµРјР°С”).

        РџРѕС‚СЂС–Р±РµРЅ, С‰РѕР± Р°РіРµРЅС‚ Р·РЅС–РјР°РІ РЎРђРњР• РІС–РєРЅРѕ РїСЂРѕС”РєС‚Сѓ. РџРѕС€СѓРє В«Р·Р° Р·Р°РіРѕР»РѕРІРєРѕРј
        ChromeВ» РЅР° РјР°С€РёРЅС– РєРѕСЂРёСЃС‚СѓРІР°С‡Р° Р·РЅР°С…РѕРґРёРІ С‡СѓР¶Рµ РІС–РєРЅРѕ вЂ” СЃР°РјРµ С‚РѕРјСѓ РІ С‡Р°С‚С–
        Р·'СЏРІР»СЏРІСЃСЏ С‚РµРјРЅРёР№ РЅРµР·СЂРѕР·СѓРјС–Р»РёР№ Р·РЅС–РјРѕРє Р·Р°РјС–СЃС‚СЊ Р№РѕРіРѕ СЃР°Р№С‚Сѓ.
        """
        view = self._browser_view()
        if view is None:
            return 0
        try:
            hwnd = int(getattr(view, "hwnd", 0) or 0)
        except (TypeError, ValueError):
            return 0
        return hwnd if hwnd else 0

    def _browser_cdp(self):
        """CDP-СЃРµСЃС–СЏ РІР±СѓРґРѕРІР°РЅРѕРіРѕ Р±СЂР°СѓР·РµСЂР° РґР»СЏ С–РЅСЃС‚СЂСѓРјРµРЅС‚С–РІ Р°РіРµРЅС‚Р°.

        РџРѕРІРµСЂС‚Р°С” ``None``, РїРѕРєРё СЃС‚РѕСЂС–РЅРєРё РЅРµРјР°С”: С–РЅСЃС‚СЂСѓРјРµРЅС‚ С‚РѕРґС– С‡РµСЃРЅРѕ РєР°Р¶Рµ
        В«Р±СЂР°СѓР·РµСЂ РЅРµ РїС–РґРєР»СЋС‡РµРЅРёР№В» Р·Р°РјС–СЃС‚СЊ РІРёРіР°РґР°РЅРѕС— РІС–РґРїРѕРІС–РґС–.
        """
        view = self._browser_view()
        if view is None:
            return None
        try:
            return view.ensure_cdp()
        except Exception:  # noqa: BLE001 - С–РЅСЃС‚СЂСѓРјРµРЅС‚ РЅРµ РјР°С” Р»Р°РјР°С‚Рё Р°РіРµРЅС‚Р°
            LOG.warning("CDP РЅРµРґРѕСЃС‚СѓРїРЅРёР№", exc_info=True)
            return None

    # в”Ђв”Ђ С–РЅСЃРїРµРєС‚РѕСЂ РµР»РµРјРµРЅС‚С–РІ Сѓ Live Browser в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _inspect_page_at(self, x: int, y: int) -> dict:
        """РџСЂРѕС‡РёС‚Р°С‚Рё РµР»РµРјРµРЅС‚ СЃС‚РѕСЂС–РЅРєРё РІ С‚РѕС‡С†С– (РєРѕРѕСЂРґРёРЅР°С‚Рё РЎРўРћР Р†РќРљР)."""
        session = self._browser_cdp()
        if session is None:
            return {}
        try:
            return session.inspect_at(int(x), int(y))
        except Exception:  # noqa: BLE001 - С–РЅСЃРїРµРєС‚РѕСЂ РЅРµ РјР°С” Р»Р°РјР°С‚Рё РІС–РєРЅРѕ
            LOG.warning("Р†РЅСЃРїРµРєС‚РѕСЂ СЃС‚РѕСЂС–РЅРєРё РІРїР°РІ", exc_info=True)
            return {}

    def _page_console(self) -> tuple[list[str], int]:
        """РљРѕРЅСЃРѕР»СЊ СЃС‚РѕСЂС–РЅРєРё: (СЂСЏРґРєРё, РєС–Р»СЊРєС–СЃС‚СЊ РїРѕРјРёР»РѕРє)."""
        session = self._browser_cdp()
        if session is None:
            return ([], 0)
        try:
            entries = session.console_entries()
            errors = session.errors_count()
            return ([entry.as_line() for entry in entries], errors)
        except Exception:  # noqa: BLE001
            LOG.warning("РљРѕРЅСЃРѕР»СЊ СЃС‚РѕСЂС–РЅРєРё РЅРµРґРѕСЃС‚СѓРїРЅР°", exc_info=True)
            return ([], 0)

    def _page_action(self, name: str) -> str:
        """Р”С–С— РЅР°Рґ СЃС‚РѕСЂС–РЅРєРѕСЋ РґР»СЏ РїР°РЅРµР»С– РїСЂРµРІ'СЋ: Р·РЅС–РјРѕРє, Р°СѓРґРёС‚, Р°РґР°РїС‚РёРІРЅС–СЃС‚СЊ."""
        session = self._browser_cdp()
        if session is None:
            return "Р‘СЂР°СѓР·РµСЂ РЅРµ РїС–РґРєР»СЋС‡РµРЅРёР№: Р·Р°РїСѓСЃС‚Рё СЃР°Р№С‚ РєРЅРѕРїРєРѕСЋ в–¶."
        key = (name or "").strip().lower()
        try:
            if key == "screenshot":
                return self.registry.call("web_screenshot", {}).output
            if key == "audit":
                return self.registry.call("web_audit", {}).output
            if key == "responsive":
                return self.registry.call("web_responsive", {}).output
        except Exception as exc:  # noqa: BLE001 - РґС–СЏ РЅРµ РјР°С” Р»Р°РјР°С‚Рё РІС–РєРЅРѕ
            LOG.warning("Р”С–СЏ СЃС‚РѕСЂС–РЅРєРё В«%sВ» РІРїР°Р»Р°", key, exc_info=True)
            return f"{type(exc).__name__}: {exc}"
        return f"РќРµРІС–РґРѕРјР° РґС–СЏ: {name}"

    def inspect_element_at(self, x: int, y: int) -> dict:
        """РџСЂРѕС‡РёС‚Р°С‚Рё РµР»РµРјРµРЅС‚ СЃС‚РѕСЂС–РЅРєРё РІ С‚РѕС‡С†С– (РґР»СЏ РїР°РЅРµР»С– РїСЂРµРІ'СЋ)."""
        return self._inspect_page_at(x, y)

    def send_element_to_agent(self, info: dict, request: str = "") -> None:
        """РџРµСЂРµРґР°С‚Рё РІРёР±СЂР°РЅРёР№ РµР»РµРјРµРЅС‚ Сѓ РєРѕРЅС‚РµРєСЃС‚ Р°РіРµРЅС‚Р°.

        Р¦Рµ С‚Р° СЃР°РјР° РґС–СЏ, СЏРєРѕС— Р±СЂР°РєСѓРІР°Р»Рѕ: В«РЅР°С‚РёСЃРЅРё РЅР° РєРЅРѕРїРєСѓ РІ Р±СЂР°СѓР·РµСЂС– Р№
        СЃРєР°Р¶Рё, С‰Рѕ Р· РЅРµСЋ Р·СЂРѕР±РёС‚РёВ». РђРіРµРЅС‚ РѕС‚СЂРёРјСѓС” СЃРµР»РµРєС‚РѕСЂ, РєР»Р°СЃРё, СЂРѕР·РјС–СЂРё Р№
        СЃС‚РёР»С– вЂ” С‚РѕР±С‚Рѕ СЂС–РІРЅРѕ С‚Рµ, С‰Рѕ РїРѕС‚СЂС–Р±РЅРѕ, С‰РѕР± Р·РЅР°Р№С‚Рё РєРѕРґ С– Р·РјС–РЅРёС‚Рё Р№РѕРіРѕ.

        Р—Р°РїРёС‚ РќР• Р·Р°РјС–РЅСЋС” С‚Рµ, С‰Рѕ РєРѕСЂРёСЃС‚СѓРІР°С‡ СѓР¶Рµ РЅР°РїРёСЃР°РІ: СЏРєС‰Рѕ РІ РїРѕР»С– С”
        С‚РµРєСЃС‚, РІС–РЅ СЃС‚Р°С” РїСЂРѕС…Р°РЅРЅСЏРј (С†Рµ РЅР°Р№РїСЂРёСЂРѕРґРЅС–С€РёР№ СЃРїРѕСЃС–Р± вЂ” СЃРїРµСЂС€Сѓ
        РЅР°РїРёСЃР°С‚Рё В«Р·СЂРѕР±Рё Р±С–Р»СЊС€РѕСЋВ», РїРѕС‚С–Рј РІРёР±СЂР°С‚Рё РµР»РµРјРµРЅС‚).
        """
        if not info:
            self.set_status("Р•Р»РµРјРµРЅС‚ РЅРµ РІРёР±СЂР°РЅРѕ вЂ” РЅР°С‚РёСЃРЅРё РЅР° РЅСЊРѕРіРѕ Сѓ Р±СЂР°СѓР·РµСЂС–.")
            return
        text = agent_tools._format_element(info)
        typed = ""
        try:
            current = self.chat.input_box.get("1.0", "end-1c").strip()
            # РџР»РµР№СЃС…РѕР»РґРµСЂ вЂ” РЅРµ С‚РµРєСЃС‚ РєРѕСЂРёСЃС‚СѓРІР°С‡Р°.
            if current and current != getattr(self.chat, "_placeholder", None):
                typed = current
        except (tk.TclError, AttributeError):
            typed = ""
        ask = (request or "").strip() or typed
        prompt = (
            "РћСЃСЊ РµР»РµРјРµРЅС‚, СЏРєРёР№ СЏ РІРёР±СЂР°РІ Сѓ Live Browser:\n\n"
            f"{text}\n\n"
            "Р—РЅР°Р№РґРё РІС–РґРїРѕРІС–РґРЅРёР№ РєРѕРґ Сѓ РїСЂРѕС”РєС‚С– (Р·Р° СЃРµР»РµРєС‚РѕСЂРѕРј, РєР»Р°СЃР°РјРё Р№ "
            "СЃС‚РёР»СЏРјРё) С– РІРёРєРѕРЅР°Р№ РјРѕС” РїСЂРѕС…Р°РЅРЅСЏ.\n\n"
            f"РџСЂРѕС…Р°РЅРЅСЏ: {ask or '(РґРѕРїРёС€Рё С‚СѓС‚, С‰Рѕ Р·СЂРѕР±РёС‚Рё Р· С†РёРј РµР»РµРјРµРЅС‚РѕРј)'}"
        )
        self.show_chat(True)
        self.chat.set_text(prompt)
        self.set_status("Р•Р»РµРјРµРЅС‚ РїРµСЂРµРґР°РЅРѕ Р°РіРµРЅС‚Сѓ вЂ” РґРѕРїРёС€Рё РїСЂРѕС…Р°РЅРЅСЏ Р№ РЅР°С‚РёСЃРЅРё Enter.")

    def new_file(self) -> None:
        self.tabs.new_file()
        self.set_status("РќРѕРІРёР№ С„Р°Р№Р»")

    def open_file_dialog(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Р’С–РґРєСЂРёС‚Рё С„Р°Р№Р»",
                                          initialdir=self.settings.workspace)
        if path:
            self.open_path(Path(path))

    def open_path(self, path: Path, line: int = 0) -> None:
        if self.tabs.open_file(path, line=line):
            # Р¤Р°Р№Р» РІС–РґРєСЂРёС‚Рѕ вЂ” СЃС‚Р°СЂС‚РѕРІРёР№ РµРєСЂР°РЅ Р±С–Р»СЊС€Рµ РЅРµ РїРѕС‚СЂС–Р±РµРЅ.
            self._hide_welcome()
            self.file_tree.reveal(path)
            self._remember_tab(path)
            self.outline.update_for(self.tabs.current())
            self._refresh_context()

    def save_file(self) -> None:
        self.tabs.save_current()
        self.outline.update_for(self.tabs.current())
        self._refresh_context()

    def save_file_as(self) -> None:
        self.tabs.save_as()
        self._refresh_context()

    def close_tab(self) -> None:
        self.tabs.close_current()
        self._refresh_context()

    def reopen_tab(self) -> None:
        """Р’С–РґРєСЂРёС‚Рё РѕСЃС‚Р°РЅРЅСЋ Р·Р°РєСЂРёС‚Сѓ РІРєР»Р°РґРєСѓ."""
        self.hide_welcome()
        if self.tabs.reopen_last_closed():
            self.set_status("Р’РєР»Р°РґРєСѓ РІС–РґРЅРѕРІР»РµРЅРѕ.")

    def _recent_closed_tabs(self) -> list[tuple[str, str, callable]]:
        items: list[tuple[str, str, callable]] = []
        for path in self.tabs.closed_paths()[:10]:
            items.append((
                f"Р’С–РґРєСЂРёС‚Рё Р·РЅРѕРІСѓ: {path.name}",
                "",
                lambda p=path: (self.hide_welcome(), self.tabs.reopen_path(p)),
            ))
        return items

    def close_all_tabs(self) -> None:
        self.tabs.close_all()
        self._refresh_context()

    def _remember_tab(self, path: Path) -> None:
        tabs = [str(p) for p in self.tabs.all_paths()]
        self.session["tabs"] = tabs[-12:]

    def _on_saved(self, path: Path) -> None:
        self.file_tree.refresh()
        # Р—Р°СЃС‚РѕСЃСѓРЅРѕРє Сѓ Р¶РёРІРѕРјСѓ РїСЂРµРІ'СЋ РѕРЅРѕРІР»СЋС”С‚СЊСЃСЏ РѕРґСЂР°Р·Сѓ (hot reload).
        # Р—Р±С–Р№ С‚СѓС‚ РЅРµ РјР°С” Р»Р°РјР°С‚Рё Р·Р±РµСЂРµР¶РµРЅРЅСЏ, Р°Р»Рµ Р№ РЅРµ РјР°С” Р·РЅРёРєР°С‚Рё: СЂР°РЅС–С€Рµ
        # СЃС‚РѕСЂС–РЅРєР° РїСЂРµРІ'СЋ РїСЂРѕСЃС‚Рѕ РЅРµ РѕРЅРѕРІР»СЋРІР°Р»Р°СЃСЊ Р±РµР· Р¶РѕРґРЅРѕРіРѕ СЃР»С–РґСѓ.
        safe.call_quiet(self.live_preview.on_file_saved,
                        where="РѕРЅРѕРІР»РµРЅРЅСЏ Р¶РёРІРѕРіРѕ РїСЂРµРІ'СЋ")
        self.set_status(f"Р—Р±РµСЂРµР¶РµРЅРѕ {path.name}")
        self._refresh_context()

    def _on_tabs_changed(self) -> None:
        self._refresh_context()

    def _refresh_context(self) -> None:
        # ``refresh()`` СѓР¶Рµ РѕРЅРѕРІР»СЋС” СЃС‚Р°РЅ Р°РіРµРЅС‚Р° (РїРµСЂС€Р° СЃРµРєС†С–СЏ РїР°РЅРµР»С–), С‚РѕР¶
        # РѕРєСЂРµРјРёР№ РІРёРєР»РёРє ``_refresh_agent`` С‚СѓС‚ Р±СѓРІ Р”РЈР‘Р›Р•Рњ: РїР°РЅРµР»СЊ
        # РїРµСЂРµР±СѓРґРѕРІСѓРІР°Р»Р°СЃСЊ РґРІС–С‡С– РЅР° РєРѕР¶РЅРµ РѕРЅРѕРІР»РµРЅРЅСЏ. Р—Р°РјС–СЂСЏРЅРѕ РїСЂРѕС„С–Р»РµСЂРѕРј вЂ”
        # С†РµР№ Р·Р°Р№РІРёР№ РІРёРєР»РёРє РїРѕРґРІРѕСЋРІР°РІ РІР°СЂС‚С–СЃС‚СЊ РЅР°Р№РґРѕСЂРѕР¶С‡РѕС— РѕРїРµСЂР°С†С–С—
        # С–РЅС‚РµСЂС„РµР№СЃСѓ.
        try:
            self.context.refresh()
        except (tk.TclError, AttributeError):
            pass

    def _on_editor_analysis(self, editor, result) -> None:
        """AST-Р°РЅР°Р»С–Р· Р·Р°РІРµСЂС€РёРІСЃСЏ вЂ” РѕРЅРѕРІРёС‚Рё РїР°РЅРµР»СЊ СЃС‚СЂСѓРєС‚СѓСЂРё Р№ СЃРјСѓРіСѓ СЃС‚Р°РЅСѓ."""
        if editor is not self.tabs.current():
            return
        try:
            self.outline.show_analysis(result, editor.current_line())
        except (tk.TclError, AttributeError):
            pass
        metrics = getattr(result, "metrics", None)
        if metrics is not None:
            self.ast_label.configure(
                text=f"{metrics.code_lines} СЂСЏРґРєС–РІ В· {metrics.functions}Ж’ В· "
                     f"{metrics.classes}в—€ В· {result.elapsed:.1f} РјСЃ")
        problem = getattr(result, "problem", None)
        if problem is not None:
            self.set_status(f"РЎРёРЅС‚Р°РєСЃРёСЃ: СЂСЏРґРѕРє {problem.line} вЂ” {problem.short}")
        elif getattr(result, "ok", False):
            count = len(getattr(result, "symbols", []))
            self.set_status(f"AST: {count} СЃРёРјРІРѕР»С–РІ В· {result.elapsed:.1f} РјСЃ")

    def _on_cursor(self, editor: CodeEditor) -> None:
        self.cursor_label.configure(text=f"Ln {editor.current_line()}, Col {editor.current_column()}")
        self.lang_label.configure(text=ws.language_label(editor.path or Path(editor.filename)))
        if self._active_side == "outline" and self.outline.winfo_ismapped():
            self.outline.highlight_line(editor.current_line())

    def _goto_line(self, line: int) -> None:
        editor = self.tabs.current()
        if editor:
            editor.goto_line(line)

    def run_current_file(self) -> None:
        path = self.tabs.current_path()
        if not path:
            self.set_status("РЎРїРѕС‡Р°С‚РєСѓ Р·Р±РµСЂРµР¶Рё С„Р°Р№Р».")
            return
        if self.tabs.current() and self.tabs.current().modified:
            self.tabs.save_current()
        self.show_bottom("terminal")
        if path.suffix == ".py":
            self.terminal.run(f'"{sys.executable}" "{path}"')
        elif path.suffix in {".bat", ".cmd"}:
            self.terminal.run(f'"{path}"')
        else:
            self.set_status(f"F5 Р·Р°РїСѓСЃРєР°С” Р»РёС€Рµ .py С‚Р° .bat (С„Р°Р№Р» {path.suffix}).")

    def run_tests(self) -> None:
        self.show_bottom("terminal")
        self.terminal.run(f'"{sys.executable}" -m unittest discover -s tests -v')

    # в”Ђв”Ђ РїРѕС€СѓРє С– РїР°Р»С–С‚СЂР° в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def open_search(self) -> None:
        editor = self.tabs.current()
        if editor:
            SearchDialog(self, self.theme, editor)

    def open_project_search(self) -> None:
        self.show_bottom("search")
        self.project_search.query_entry.focus_set()

    def search_project_for(self, needle: str) -> None:
        self.show_bottom("search")
        self.project_search.search_for(needle)

    def quick_open(self) -> None:
        root = Path(self.settings.workspace)
        files = ws.quick_open_index(root)
        items = [
            (ws.relative_to_root(root, path), "", lambda p=path: self.open_path(p))
            for path in files
        ]
        Palette(self, self.theme, "РЁРІРёРґРєРµ РІС–РґРєСЂРёС‚С‚СЏ С„Р°Р№Р»Сѓ", items)

    def command_palette(self) -> None:
        """РџР°Р»С–С‚СЂР° РєРѕРјР°РЅРґ (Ctrl+Shift+P): СѓСЃС– РєРѕРјР°РЅРґРё Р· СЂРµС”СЃС‚СЂСѓ.

        Р”Р¶РµСЂРµР»Рѕ вЂ” :mod:`commands`, С‚РѕРјСѓ РІ РїР°Р»С–С‚СЂС– С” РљРћР–РќРђ РєРѕРјР°РЅРґР° РїСЂРѕРіСЂР°РјРё,
        РІРєР»СЋС‡РЅРѕ Р· С‚РёРјРё, С‰Рѕ Р¶РёРІСѓС‚СЊ Сѓ РІРёРїР°РґР°СЋС‡РёС… РјРµРЅСЋ С€Р°РїРєРё. РќРµРґРѕСЃС‚СѓРїРЅС– Р·Р°СЂР°Р·
        РєРѕРјР°РЅРґРё РЅРµ Р·РЅРёРєР°СЋС‚СЊ, Р° РїРѕРєР°Р·СѓСЋС‚СЊСЃСЏ Р· РїРѕРјС–С‚РєРѕСЋ В«РЅРµРґРѕСЃС‚СѓРїРЅРѕВ».
        """
        self._close_popovers()
        items = commands.palette_items()
        if not items:
            self.set_status("Р РµС”СЃС‚СЂ РєРѕРјР°РЅРґ РїРѕСЂРѕР¶РЅС–Р№ вЂ” С†Рµ РїРѕРјРёР»РєР° С–РЅС–С†С–Р°Р»С–Р·Р°С†С–С—.")
            return
        Palette(self, self.theme, "РљРѕРјР°РЅРґРЅР° РїР°Р»С–С‚СЂР°", items,
                placeholder="РљРѕРјР°РЅРґР° Р°Р±Рѕ РєР°С‚РµРіРѕСЂС–СЏвЂ¦")

    def _command_items(self) -> list[tuple[str, str, callable]]:
        """РЎСѓРјС–СЃРЅС–СЃС‚СЊ: СЃС‚Р°СЂС– РІРёРєР»РёРєРё РѕС‚СЂРёРјСѓСЋС‚СЊ С‚РѕР№ СЃР°РјРёР№ СЃРїРёСЃРѕРє, С‰Рѕ Р№ РїР°Р»С–С‚СЂР°."""
        return commands.palette_items()

    # в”Ђв”Ђ РїР°РЅРµР»С– в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _rail_action(self, key: str) -> None:
        """Р”С–СЏ РЅР°РІС–РіР°С†С–С—: СЂРѕР·РґС–Р», РїР°РЅРµР»СЊ Р°Р±Рѕ РѕРєСЂРµРјР° РєРѕРјР°РЅРґР°."""
        if key == "settings":
            self.open_settings()
            return
        if key == "hub":
            self.open_model_hub()
            return
        if key == "search":
            self.open_project_search()
            self._sync_rail_state("search")
            return
        # Р РѕР·РґС–Р»Рё РЅР°РІС–РіР°С†С–С— РІРµРґСѓС‚СЊ РЅР° СЃРІРѕСЋ В«РґРѕРјР°С€РЅСЋВ» РїР°РЅРµР»СЊ.
        panel = SECTION_PANELS.get(key)
        if panel is not None:
            self.show_side(panel)
            return
        self.show_side(key)

    def show_side(self, key: str) -> None:
        """РџРѕРєР°Р·Р°С‚Рё РѕРґРЅСѓ Р· РїР°РЅРµР»РµР№ Р±С–С‡РЅРѕС— РєРѕР»РѕРЅРєРё."""
        # РџР°РЅРµР»СЊ Р¶РёРІРµ РІ PanedWindow: РїРѕРІРµСЂС‚Р°С”РјРѕ С—С— СЃР°РјРµ С‚СѓРґРё, Р° РЅРµ С‡РµСЂРµР·
        # grid() вЂ” `grid()` РІРёРєРёРґР°РІ РІС–РґР¶РµС‚ С–Р· PanedWindow, С– СЃР°Р№РґР±Р°СЂ Р·РЅРёРєР°РІ
        # (РїРµСЂРµРІС–СЂРµРЅРѕ: РїС–СЃР»СЏ show_side Сѓ side_split Р»РёС€Р°Р»Р°СЃСЊ РѕРґРЅР° РїР°РЅРµР»СЊ).
        if not self._sidebar_visible():
            self._sidebar_add()
        widget = self._side_widgets.get(key)
        if widget is None:
            widget = self.file_tree
            key = "explorer"
        for child in self.side_stack.winfo_children():
            child.pack_forget()
        # Р—Р°РіРѕР»РѕРІРѕРє РїР°РЅРµР»С–: РєРѕСЂРёСЃС‚СѓРІР°С‡ Р±Р°С‡РёС‚СЊ, РґРµ СЃР°РјРµ РІС–РЅ РїРµСЂРµР±СѓРІР°С”.
        self._paint_panel_title(key)
        widget.pack(fill="both", expand=True)
        self._active_side = key
        if key == "outline":
            self.outline.update_for(self.tabs.current())
        elif key == "skills":
            self.skills_panel.refresh()
        elif key == "queue":
            self.queue_panel.refresh()
        elif key == "mcp":
            self.mcp_panel.refresh()
        elif key == "rag":
            self.rag_panel.refresh_status()
        elif key == "tools":
            self.tools_panel.refresh()
        elif key == "changes":
            self.changes_panel.refresh()
        self._sync_rail_state(key)

    def _paint_panel_title(self, key: str) -> None:
        """Р—Р°РіРѕР»РѕРІРѕРє РїР°РЅРµР»С–: РЅР°Р·РІР° Р№ С€Р»СЏС… РЅР°Р·Р°Рґ РґРѕ СЃРїРёСЃРєСѓ С‡Р°С‚С–РІ.

        Р”Р»СЏ СЃР°РјРёС… С‡Р°С‚С–РІ Р·Р°РіРѕР»РѕРІРѕРє РЅРµ РїРѕРєР°Р·СѓС”РјРѕ вЂ” СЃРїРёСЃРѕРє РјР°С” РІР»Р°СЃРЅСѓ РІРєР»Р°РґРєСѓ
        В«Р§РђРўР Р™ РђР“Р•РќРўРВ», С– РїС–РґРїРёСЃ РЅР°Рґ РЅРµСЋ Р»РёС€Рµ РґСѓР±Р»СЋРІР°РІ С—С—.
        """
        title = "" if key == "chats" else PANEL_TITLES.get(key, "").upper()
        try:
            self.panel_title.configure(text=title)
        except (tk.TclError, AttributeError):
            pass
        # РљРЅРѕРїРєР° В«РЅР°Р·Р°Рґ РґРѕ СЃРїРёСЃРєСѓ С‡Р°С‚С–РІВ»: Р±СѓРґСЊ-СЏРєР° С–РЅС€Р° РїР°РЅРµР»СЊ РјР°С” С€Р»СЏС… РЅР°Р·Р°Рґ.
        try:
            if title:
                self.panel_home.configure(text="вЂ№ РґРѕ С‡Р°С‚С–РІ", fg=theme.FG_DIM)
            else:
                self.panel_home.configure(text="", fg=theme.BG_ALT)
        except (tk.TclError, AttributeError):
            pass

    def _panel_home(self) -> None:
        """РџРѕРІРµСЂРЅСѓС‚РёСЃСЊ РґРѕ СЃРїРёСЃРєСѓ С‡Р°С‚С–РІ С–Р· Р±СѓРґСЊ-СЏРєРѕС— РїР°РЅРµР»С–."""
        if self._active_side != "chats":
            self.show_side("chats")

    def _sync_rail_state(self, active: str = "") -> None:
        """РџС–РґСЃРІС–С‚РёС‚Рё С‡Р°С‚ СЏРє Р°РєС‚РёРІРЅРёР№ СЂРѕР·РґС–Р» Р»С–РІРѕС— РїР°РЅРµР»С–.

        РџСѓРЅРєС‚С–РІ РЅР°РІС–РіР°С†С–С— Р±С–Р»СЊС€Рµ РЅРµРјР°С”: Р»С–РІРѕСЂСѓС‡ Р»РёС€РёР»РёСЃСЊ СЃР°РјС– С‡Р°С‚Рё, С‚РѕР¶
        РїС–РґСЃРІС–С‡СѓРІР°С‚Рё РЅС–С‡РѕРіРѕ вЂ” Р°Р»Рµ РІРёРґС–Р»РµРЅРЅСЏ Р°РєС‚РёРІРЅРѕРіРѕ С‡Р°С‚Сѓ РІ СЃРїРёСЃРєСѓ
        Р»РёС€Р°С”С‚СЊСЃСЏ РѕР±РѕРІ'СЏР·РєРѕРІРёРј.
        """
        try:
            self.chat_list.set_active(getattr(self.chat_store, "active_id", ""))
        except (tk.TclError, AttributeError):
            pass
        # РЁРІРёРґРєРёР№ РґРѕСЃС‚СѓРї РїС–РґСЃРІС–С‡СѓС” С‚Рµ, РґРµ РєРѕСЂРёСЃС‚СѓРІР°С‡ Р·Р°СЂР°Р· РїРµСЂРµР±СѓРІР°С”.
        for key, chip in getattr(self, "quick_nav", {}).items():
            try:
                chip.set_active(key == active)
            except (tk.TclError, AttributeError):
                continue

    def toggle_sidebar(self, show: bool | None = None) -> None:
        """РџРѕРєР°Р·Р°С‚Рё/СЃС…РѕРІР°С‚Рё РЅР°РІС–РіР°С†С–Р№РЅСѓ РїР°РЅРµР»СЊ.

        РџР°РЅРµР»СЊ Р¶РёРІРµ РІ ``side_split`` (``PanedWindow``), С‚РѕРјСѓ РїРѕРєР°Р·Р°С‚Рё С—С— вЂ”
        С†Рµ ``add``, Р° СЃС…РѕРІР°С‚Рё вЂ” ``forget``. Р Р°РЅС–С€Рµ С‚СѓС‚ Р±СѓР»Рё ``grid``/
        ``grid_remove``, С‰Рѕ РїСЂР°С†СЋРІР°Р»Рѕ Р»РёС€Рµ РґР»СЏ Р·РІРёС‡Р°Р№РЅРѕРіРѕ ``Frame``.
        """
        visible = self._sidebar_visible()
        if show is None:
            show = not visible
        if bool(show) == visible:
            self._sync_rail_state()
            return
        if show:
            self._sidebar_collapsed = False
            self.sidebar.configure(width=self.layout.get(
                "sidebar_width", int(self.settings.ui.sidebar_width or 300)))
            self._sidebar_add()
            self.show_side(self._active_side or "chats")
        else:
            self._sidebar_forget()
            self._sync_rail_state("")
        self._sash_after(0)

    def _sidebar_visible(self) -> bool:
        """Р§Рё РїР°РЅРµР»СЊ СЃРїСЂР°РІРґС– РІ СЂРѕР·РєР»Р°РґС†С–.

        РџРµСЂРµРІС–СЂСЏС”РјРѕ ``PanedWindow.panes()``, Р° РЅРµ ``winfo_ismapped()``:
        РїСЂРёС…РѕРІР°РЅРµ РІС–РєРЅРѕ (``withdraw``) Р°Р±Рѕ Р·РіРѕСЂРЅСѓС‚Рµ РІС–РєРЅРѕ OS РґР°С”
        ``ismapped() == 0`` РЅР°РІС–С‚СЊ С‚РѕРґС–, РєРѕР»Рё РїР°РЅРµР»СЊ СЃС‚РѕС—С‚СЊ Сѓ СЂРѕР·РєР»Р°РґС†С–.
        РќР° С†СЊРѕРјСѓ РІР¶Рµ СЃРїС–С‚РєРЅСѓР»РёСЃСЊ: С€РёСЂРёРЅР° СЃР°Р№РґР±Р°СЂР° РЅРµ Р·Р±РµСЂС–РіР°Р»Р°СЃСЊ, Р±Рѕ
        РїРµСЂРµРІС–СЂРєР° В«РІРёРґРёРјРѕСЃС‚С–В» С…РёР±РЅРѕ РєР°Р·Р°Р»Р° В«РїР°РЅРµР»С– РЅРµРјР°С”В».
        """
        try:
            return any(str(pane).endswith(str(self.sidebar))
                       for pane in self.side_split.panes())
        except (tk.TclError, AttributeError):
            return False

    def _sidebar_add(self) -> None:
        """РџРѕРІРµСЂРЅСѓС‚Рё РїР°РЅРµР»СЊ Сѓ ``PanedWindow`` РїРµСЂС€РѕСЋ (Р»С–РІРѕСЂСѓС‡)."""
        try:
            panes = [str(pane) for pane in self.side_split.panes()]
        except (tk.TclError, AttributeError):
            panes = []
        if any(pane.endswith(str(self.sidebar)) for pane in panes):
            return
        # ``add`` РґРѕРґР°С” РІ РєС–РЅРµС†СЊ, С‚РѕРјСѓ РїРµСЂРµР±СѓРґРѕРІСѓС”РјРѕ РїРѕСЂСЏРґРѕРє СЏРІРЅРѕ.
        try:
            for pane in panes:
                self.side_split.forget(pane)
            self.side_split.add(self.sidebar, weight=0)
            self.side_split.add(self.main_area, weight=1)
        except tk.TclError:
            LOG.debug("РќРµ РІРґР°Р»РѕСЃСЊ РїРѕРІРµСЂРЅСѓС‚Рё РїР°РЅРµР»СЊ Сѓ СЂРѕР·РєР»Р°РґРєСѓ", exc_info=True)

    def _sidebar_forget(self) -> None:
        try:
            self.side_split.forget(self.sidebar)
        except tk.TclError:
            LOG.debug("РќРµ РІРґР°Р»РѕСЃСЊ РїСЂРёР±СЂР°С‚Рё РїР°РЅРµР»СЊ С–Р· СЂРѕР·РєР»Р°РґРєРё", exc_info=True)

    # в”Ђв”Ђ РІРёРґ СЂРѕР±РѕС‡РѕС— РѕР±Р»Р°СЃС‚С– в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def set_view(self, view: str) -> None:
        """РџРµСЂРµРјРєРЅСѓС‚Рё РІРёРґ: ``chat`` (РґС–Р°Р»РѕРі РЅР° РІРµСЃСЊ С†РµРЅС‚СЂ) Р°Р±Рѕ ``workspace``.

        Р¦Рµ С– С” РїРµСЂРµРјРёРєР°РЅРЅСЏ В«Chat в†” Agent WorkspaceВ» С–Р· Р·Р°РіРѕР»РѕРІРєР° СЃРµСЃС–С—:
        Сѓ СЂРµР¶РёРјС– С‡Р°С‚Сѓ С†РµРЅС‚СЂР°Р»СЊРЅР° РєРѕР»РѕРЅРєР° Р·Р°Р±РёСЂР°С” РІРµСЃСЊ РїСЂРѕСЃС‚С–СЂ, Сѓ СЂРµР¶РёРјС–
        СЂРѕР±РѕС‡РѕС— РѕР±Р»Р°СЃС‚С– РїРѕСЂСѓС‡ С–Р· РґС–Р°Р»РѕРіРѕРј РїРѕРєР°Р·СѓС”С‚СЊСЃСЏ СЂРµРґР°РєС‚РѕСЂ.
        """
        target = "workspace" if (view or "").lower().startswith("work") else "chat"
        previous = getattr(self, "_view", "")
        self._view = target
        if self.settings.ui.view != target:
            self.settings.ui.view = target
            # Р’РёР±С–СЂ РІРёРґСѓ РїРµСЂРµР¶РёРІР°С” РїРµСЂРµР·Р°РїСѓСЃРє, СЏРє С– СЂРѕР·РєР»Р°РґРєР° РїР°РЅРµР»РµР№.
            self.settings.save()
        self._chat_shown = True
        self._reorder_panes(with_centre=(target == "workspace"))
        self.header.set_view(target)
        if target == "workspace" and self._bottom_shown:
            # РќРёР¶РЅСЏ РїР°РЅРµР»СЊ РјР°С” Р±СѓС‚Рё РІРёРґРёРјРѕСЋ, СЏРєС‰Рѕ С—С— РІС–РґРєСЂРёРІР°Р»Рё.
            self._place_bottom(True)
        if previous != target:
            self.set_status("Р РѕР±РѕС‡Р° РѕР±Р»Р°СЃС‚СЊ: СЂРµРґР°РєС‚РѕСЂ С– С‚РµСЂРјС–РЅР°Р»." if target == "workspace"
                            else "Р”С–Р°Р»РѕРі Р· Р°РіРµРЅС‚РѕРј РЅР° РІРµСЃСЊ РµРєСЂР°РЅ.")

    def _centre_in_split(self) -> bool:
        try:
            return any(str(pane).endswith(str(self.centre)) for pane in self.h_split.panes())
        except tk.TclError:
            return False

    def _insert_centre(self) -> None:
        """РџРѕРІРµСЂРЅСѓС‚Рё СЂРѕР±РѕС‡Сѓ РѕР±Р»Р°СЃС‚СЊ Сѓ СЂРѕР·РєР»Р°РґРєСѓ РќРђ РЎР’РћР„ РјС–СЃС†Рµ.

        ``ttk.PanedWindow.add`` РґРѕРґР°С” РїР°РЅРµР»СЊ Сѓ РєС–РЅРµС†СЊ С– РЅРµ РјР°С” РѕРїС†С–С—
        ``-before``, С‚РѕРјСѓ РїС–СЃР»СЏ РїРѕРІС‚РѕСЂРЅРѕРіРѕ РїРѕРєР°Р·Сѓ СЂРµРґР°РєС‚РѕСЂ РѕРїРёРЅСЏРІСЃСЏ Р±
        РїСЂР°РІРѕСЂСѓС‡ РІС–Рґ РєРѕР»РѕРЅРєРё РєРѕРЅС‚РµРєСЃС‚Сѓ. РџРµСЂРµР±СѓРґРѕРІСѓС”РјРѕ РїРѕСЂСЏРґРѕРє СЏРІРЅРѕ:
        РґС–Р°Р»РѕРі в†’ СЂРѕР±РѕС‡Р° РѕР±Р»Р°СЃС‚СЊ в†’ РєРѕРЅС‚РµРєСЃС‚.
        """
        if self._centre_in_split():
            return
        self._reorder_panes(with_centre=True)

    def _reorder_panes(self, *, with_centre: bool) -> None:
        """Р РѕР·СЃС‚Р°РІРёС‚Рё РїР°РЅРµР»С– Сѓ СЃС‚Р°Р»РѕРјСѓ РїРѕСЂСЏРґРєСѓ (РґС–Р°Р»РѕРі, СЂРµРґР°РєС‚РѕСЂ, РєРѕРЅС‚РµРєСЃС‚, РїСЂРµРІ'СЋ)."""
        wanted: list[tuple[tk.Widget, int]] = []
        if self._chat_shown:
            wanted.append((self.conversation_host, 1))
        if with_centre:
            wanted.append((self.centre, 1))
        if self._context_shown:
            wanted.append((self.context_host, 0))
        if self._preview_shown:
            wanted.append((self.preview_host, 0))
        try:
            for pane in self.h_split.panes():
                try:
                    self.h_split.forget(pane)
                except tk.TclError:
                    pass
            for widget, weight in wanted:
                self.h_split.add(widget, weight=weight)
        except tk.TclError:
            return
        self._sash_after(0)

    # в”Ђв”Ђ Р¶РёРІРёР№ РїСЂРµРІ'СЋ (РїСЂР°РІР° РєРѕР»РѕРЅРєР°) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def toggle_preview(self, show: bool | None = None) -> bool:
        """РџРѕРєР°Р·Р°С‚Рё/СЃС…РѕРІР°С‚Рё РєРѕР»РѕРЅРєСѓ Live Preview С–Р· Р·Р°СЃС‚РѕСЃСѓРЅРєРѕРј."""
        target = (not self._preview_shown) if show is None else bool(show)
        if target == self._preview_shown:
            return self._preview_shown
        self._preview_shown = target
        self._reorder_panes(with_centre=(self._view == "workspace"
                                         and self._centre_in_split()))
        if target:
            try:
                self.live_preview.inner.detect()
            except (tk.TclError, AttributeError):
                pass
        return self._preview_shown

    def _auto_show_preview(self) -> None:
        """РђРіРµРЅС‚ Р·Р°РїСѓСЃС‚РёРІ Р·Р°СЃС‚РѕСЃСѓРЅРѕРє вЂ” РїРѕРєР°Р·СѓС”РјРѕ СЃР°Р№С‚ С– РІС–РґРєСЂРёРІР°С”РјРѕ Р°РґСЂРµСЃСѓ.

        Р Р°РЅС–С€Рµ С‚СѓС‚ Р»РёС€Рµ РІРјРёРєР°Р»Р°СЃСЊ РїСЂР°РІР° РєРѕР»РѕРЅРєР°, С– РІРѕРЅР° РјРѕРіР»Р° Р»РёС€РёС‚РёСЃСЊ С–Р·
        РїРѕСЂРѕР¶РЅС–Рј Р±СЂР°СѓР·РµСЂРѕРј: Р»СЋРґРёРЅР° Р±Р°С‡РёР»Р° РїР°РЅРµР»СЊ, Р°Р»Рµ РЅРµ СЃР°Р№С‚. РўРµРїРµСЂ
        РІС–РґРєСЂРёРІР°С”РјРѕ СЂРµР°Р»СЊРЅСѓ Р°РґСЂРµСЃСѓ СЃРµСЂРІРµСЂР°.
        """
        if not self.app.running:
            return
        if not self._preview_shown:
            self.toggle_preview(True)
        url = ""
        try:
            url = self.app.url
        except Exception:                            # noqa: BLE001
            url = ""
        if not url:
            return
        try:
            self.live_preview.open_url(url)
            self.set_status(f"РЎР°Р№С‚ РїСЂРѕС”РєС‚Сѓ РІС–РґРєСЂРёС‚Рѕ: {url}")
        except (tk.TclError, AttributeError):
            LOG.debug("РќРµ РІРґР°Р»РѕСЃСЊ РІС–РґРєСЂРёС‚Рё СЃР°Р№С‚ Сѓ РїСЂРµРІ'СЋ", exc_info=True)

    def _forget_centre(self) -> None:
        try:
            self.h_split.forget(self.centre)
        except tk.TclError:
            pass

    def show_chat(self, show: bool = True) -> None:
        """РџРѕРєР°Р·Р°С‚Рё Р°Р±Рѕ СЃС…РѕРІР°С‚Рё РєРѕР»РѕРЅРєСѓ СЂРѕР·РјРѕРІРё."""
        if show == self._chat_shown:
            return
        self._chat_shown = bool(show)
        self._reorder_panes(with_centre=(getattr(self, "_view", "chat") == "workspace"))

    def toggle_chat(self) -> None:
        self.show_chat(not self._chat_shown)

    # в”Ђв”Ђ СЂРµР¶РёРј В«С‚С–Р»СЊРєРё С‡Р°С‚В» в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def toggle_focus_mode(self, enabled: bool | None = None) -> bool:
        """Р РµР¶РёРј СЂРѕР±РѕС‚Рё Р»РёС€Рµ Р· С‡Р°С‚РѕРј: СѓСЃРµ С–РЅС€Рµ вЂ” Р·Р° Р±Р°Р¶Р°РЅРЅСЏРј.

        РљРѕР»Рё РІРІС–РјРєРЅРµРЅРѕ, СЂРµРґР°РєС‚РѕСЂ, РЅРёР¶РЅС– РІРєР»Р°РґРєРё Р№ РєРѕР»РѕРЅРєР° РєРѕРЅС‚РµРєСЃС‚Сѓ
        Р·РіРѕСЂС‚Р°СЋС‚СЊСЃСЏ, Р° СЂРѕР·РјРѕРІР° Р·Р°Р№РјР°С” РІС–РєРЅРѕ. РџСЂРѕРІС–РґРЅРёРє, СЃРєС–Р»Рё, С‡РµСЂРіСѓ Р№
        СЃРїСЂР°РІРё РјРѕР¶РЅР° РІС–РґРєСЂРёС‚Рё Р·РІРёС‡Р°Р№РЅРёРј СЃРїРѕСЃРѕР±РѕРј вЂ” РІРѕРЅРё РЅС–РєСѓРґРё РЅРµ Р·РЅРёРєР°СЋС‚СЊ,
        РїСЂРѕСЃС‚Рѕ РЅРµ Р·Р°Р±РёСЂР°СЋС‚СЊ РјС–СЃС†СЏ Р·Р° Р·Р°РјРѕРІС‡СѓРІР°РЅРЅСЏРј.
        """
        target = (not self._focus_mode) if enabled is None else bool(enabled)
        if target == self._focus_mode:
            return self._focus_mode
        self._focus_mode = target

        if target:
            self._saved_focus_state = {
                "context": self._context_shown,
                "bottom": self._bottom_shown,
                "view": self._view,
            }
            self._chat_shown = True
            self._context_shown = False
            self._view = "chat"
            if self._bottom_shown:
                self._place_bottom(False)
            self._reorder_panes(with_centre=False)
            self.header.set_view("chat")
        else:
            saved = getattr(self, "_saved_focus_state", {}) or {}
            self._chat_shown = True
            self._context_shown = bool(saved.get("context", True))
            self._view = saved.get("view", "workspace")
            self._reorder_panes(with_centre=(self._view == "workspace"))
            self.header.set_view(self._view)
            if saved.get("bottom"):
                self._place_bottom(True)

        self._sync_focus_button()
        self.set_status("Р РµР¶РёРј В«С‚С–Р»СЊРєРё С‡Р°С‚В» СѓРІС–РјРєРЅРµРЅРѕ." if target
                        else "Р РµР¶РёРј В«С‚С–Р»СЊРєРё С‡Р°С‚В» РІРёРјРєРЅРµРЅРѕ.")
        return self._focus_mode

    def _sync_focus_button(self) -> None:
        """РџС–РґСЃРІС–С‚РёС‚Рё РєРЅРѕРїРєСѓ СЂРµР¶РёРјСѓ, СЏРєС‰Рѕ РІРѕРЅР° С”."""
        button = getattr(self, "_focus_button", None)
        if button is None:
            return
        try:
            button.set_active(self._focus_mode)
        except (tk.TclError, AttributeError):
            pass

    def toggle_context(self, show: bool | None = None) -> None:
        """РџРѕРєР°Р·Р°С‚Рё Р°Р±Рѕ СЃС…РѕРІР°С‚Рё РєРѕР»РѕРЅРєСѓ РєРѕРЅС‚РµРєСЃС‚Сѓ (СЏРІРЅРёР№ РІРёР±С–СЂ РєРѕСЂРёСЃС‚СѓРІР°С‡Р°)."""
        target = (not self._context_shown) if show is None else bool(show)
        self._context_user_choice = target
        self._auto_context(target)

    def show_bottom(self, which: str = "terminal") -> None:
        """РџРѕРєР°Р·Р°С‚Рё РЅРёР¶РЅСЋ РІРёСЃСѓРІРЅСѓ РїР°РЅРµР»СЊ (С‚РµСЂРјС–РЅР°Р», РїРѕС€СѓРє, С…Р°Р±, СЃР°Р№С‚).

        Р’РѕРЅР° Р¶РёРІРµ РїС–Рґ СЂРµРґР°РєС‚РѕСЂРѕРј Сѓ СЂРѕР±РѕС‡С–Р№ РѕР±Р»Р°СЃС‚С– Р№ Р·Р°Р№РјР°С” СЂС–РІРЅРѕ Р·Р°РґР°РЅСѓ
        РІРёСЃРѕС‚Сѓ вЂ” РЅРµ В«Р·'С—РґР°СЋС‡РёВ» РІРµСЃСЊ РµРєСЂР°РЅ. РЈ СЂРµР¶РёРјС– РґС–Р°Р»РѕРіСѓ РІРѕРЅР° СЃР°РјР°
        РІС–РґРєСЂРёРІР°С” СЂРѕР±РѕС‡Сѓ РѕР±Р»Р°СЃС‚СЊ, Р±Рѕ С–РЅР°РєС€Рµ С—С— РЅРµ Р±СѓР»Рѕ Р± РІРёРґРЅРѕ.
        """
        if not self._bottom_shown:
            self._place_bottom(True)
        if self._view != "workspace" and not self._centre_in_split():
            self.set_view("workspace")
        else:
            self._insert_centre()
        if which == "search":
            self.bottom_tabs.select(self.project_search)
        elif which == "hub":
            self.bottom_tabs.select(self.model_hub)
        elif which == "site":
            self.bottom_tabs.select(self.preview)
        elif which in ("tasks", "queue", "task_center"):
            self.bottom_tabs.select(self.task_center)
        else:
            self.bottom_tabs.select(self.terminal)

    def _place_bottom(self, show: bool) -> None:
        """Р РѕР·РјС–СЃС‚РёС‚Рё/РїСЂРёР±СЂР°С‚Рё РЅРёР¶РЅСЋ РїР°РЅРµР»СЊ СЂР°Р·РѕРј Р·С– СЃРјСѓРіРѕСЋ РїРµСЂРµС‚СЏРіСѓРІР°РЅРЅСЏ."""
        try:
            self.editor_split.rowconfigure(1, weight=0)
            self.editor_split.rowconfigure(2, weight=0)
            if show:
                # РЎРјСѓРіР° РІРёС‰Рµ РїР°РЅРµР»С–: СЃР°РјРµ Р·Р° РЅРµС— С‚СЏРіРЅСѓС‚СЊ, С‰РѕР± Р·РјС–РЅРёС‚Рё РІРёСЃРѕС‚Сѓ.
                self.bottom_sash.grid()
                self.bottom_tabs.grid(row=2, column=0, sticky="nsew")
                height = int(getattr(self, "_bottom_height", 200) or 200)
                self.bottom_tabs.configure(height=height)
                self._bottom_shown = True
            else:
                self.bottom_sash.grid_remove()
                self.bottom_tabs.grid_remove()
                self._bottom_shown = False
        except tk.TclError:
            return
        self._sash_after(0)

    # в”Ђв”Ђ РїРµСЂРµС‚СЏРіСѓРІР°РЅРЅСЏ РІРёСЃРѕС‚Рё РЅРёР¶РЅСЊРѕС— РїР°РЅРµР»С– в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _bottom_sash_press(self, event) -> None:
        """РџРѕС‡Р°Р»Рё С‚СЏРіРЅСѓС‚Рё СЃРјСѓРіСѓ: Р·Р°РїР°Рј'СЏС‚Р°С‚Рё РїРѕС‡Р°С‚РєРѕРІС– РєРѕРѕСЂРґРёРЅР°С‚Рё."""
        self._sash_drag_from = int(event.y_root)
        self._sash_drag_height = int(self.bottom_tabs.winfo_height()
                                     or self._bottom_height or 200)
        # РџРѕРєРё С‚СЏРіРЅРµРјРѕ вЂ” РЅРµ РїРµСЂРµСЂР°С…РѕРІСѓС”РјРѕ СЂРѕР·РєР»Р°РґРєСѓ, С–РЅР°РєС€Рµ РїР°РЅРµР»СЊ
        # В«СЃС‚СЂРёР±Р°Р»Р°В» Р± РЅР°Р·Р°Рґ РЅР° Р·Р±РµСЂРµР¶РµРЅСѓ РІРёСЃРѕС‚Сѓ.
        self._user_dragging = True

    def _bottom_sash_drag(self, event) -> None:
        """РўСЏРіРЅРµРјРѕ СЃРјСѓРіСѓ: РІРёСЃРѕС‚Р° РїР°РЅРµР»С– Р·РјС–РЅСЋС”С‚СЊСЃСЏ Р·Р° СЂСѓС…РѕРј РјРёС€С–."""
        try:
            total = self.editor_split.winfo_height()
        except tk.TclError:
            return
        if total <= 0:
            return
        delta = int(event.y_root) - int(self._sash_drag_from)
        # РўСЏРіРЅРµРјРѕ Р’Р“РћР РЈ вЂ” РїР°РЅРµР»СЊ СЂРѕСЃС‚Рµ.
        wanted = self._sash_drag_height - delta
        # РњРµР¶С–: РїР°РЅРµР»СЊ РЅРµ РјРµРЅС€Р° Р·Р° 120 px (С‰РѕР± Р±Р°С‡РёС‚Рё СЂСЏРґРѕРє Р°РґСЂРµСЃРё) С– РЅРµ
        # Р±С–Р»СЊС€Р° Р·Р° 80% СЂРѕР±РѕС‡РѕС— РѕР±Р»Р°СЃС‚С– (СЂРµРґР°РєС‚РѕСЂ РјР°С” Р»РёС€Р°С‚РёСЃСЊ РІРёРґРёРјРёРј).
        low, high = 120, max(160, int(total * 0.8))
        height = layout.clamp(wanted, low, high)
        if height == self._bottom_height:
            return
        self._bottom_height = height
        try:
            self.bottom_tabs.configure(height=height)
        except tk.TclError:
            pass

    def _bottom_sash_release(self, _event=None) -> None:
        """Р’С–РґРїСѓСЃС‚РёР»Рё СЃРјСѓРіСѓ: Р·Р°РїР°Рј'СЏС‚Р°С‚Рё РЅРѕРІСѓ РІРёСЃРѕС‚Сѓ."""
        self._user_dragging = False
        self._remember_layout()
        self.set_status(f"Р’РёСЃРѕС‚Р° РїР°РЅРµР»С–: {self._bottom_height} px")

    def toggle_bottom(self, show: bool | None = None) -> None:
        """РџРѕРєР°Р·Р°С‚Рё/СЃС…РѕРІР°С‚Рё РЅРёР¶РЅСЋ РїР°РЅРµР»СЊ (``None`` вЂ” РїРµСЂРµРјРєРЅСѓС‚Рё СЃС‚Р°РЅ)."""
        target = (not self._bottom_shown) if show is None else bool(show)
        if target:
            self.show_bottom("terminal")
        elif self._bottom_shown:
            self._place_bottom(False)

    def zoom(self, delta: int) -> None:
        size = max(8, min(30, self.settings.ui.font_size + delta))
        self.settings.ui.font_size = size
        self.theme.set_family(self.settings.ui.font_family, size)
        self.tabs.apply_settings()
        self.chat.apply_font()
        self.terminal.output.configure(font=self.theme.mono_small)
        self.terminal.entry.configure(font=self.theme.mono_small)
        self.settings.save()
        self.set_status(f"Р РѕР·РјС–СЂ С€СЂРёС„С‚Сѓ: {size}")

    # в”Ђв”Ђ РїСЂРѕРІР°Р№РґРµСЂРё С‚Р° РјРѕРґРµР»С– в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def probe_providers(self, silent: bool = False) -> None:
        """РџРµСЂРµРІС–СЂРёС‚Рё Р»РѕРєР°Р»СЊРЅС– СЃРµСЂРІРµСЂРё Р№ РїРѕРєР°Р·Р°С‚Рё СЃРїСЂР°РІР¶РЅС–Р№ СЃС‚Р°С‚СѓСЃ РјРѕРґРµР»РµР№.

        РҐРјР°СЂРЅС– РїСЂРѕРІР°Р№РґРµСЂРё РЅРµ РїРµСЂРµРІС–СЂСЏС”РјРѕ Р°РІС‚РѕРјР°С‚РёС‡РЅРѕ вЂ” С†Рµ Р·Р°Р№РІРёР№ С‚СЂР°С„С–Рє С–
        РІРёРјРѕРіР° РєР»СЋС‡Р°. Р”Р»СЏ Р»РѕРєР°Р»СЊРЅРёС… РјРµСЂРµР¶Р° С†Рµ ``GET /models``, С‚РѕР±С‚Рѕ СЂРµР°Р»СЊРЅРёР№
        СЃС‚Р°РЅ СЃРµСЂРІРµСЂР°, Р° РЅРµ РїСЂРёРїСѓС‰РµРЅРЅСЏ.
        """
        targets = providers.probe_targets(self.settings)
        if self._probe is not None:
            try:
                self._probe.cancel()
            except Exception:  # noqa: BLE001
                pass
        self._probe = providers.ProviderProbe(targets, timeout=4)
        self._probe.start()
        if not silent:
            self.set_status(f"РџРµСЂРµРІС–СЂСЏСЋ Р»РѕРєР°Р»СЊРЅС– СЃРµСЂРІРµСЂРё: {len(targets)}вЂ¦")
        self._drain_probe()

    def _drain_probe(self) -> None:
        self._probe_after = None
        outcomes: list[providers.ProbeOutcome] = []
        if self._probe is not None:
            outcomes = self._probe.drain()
        if outcomes:
            self._probe_state.update({item.key: item for item in outcomes})
            self._apply_probe_results(outcomes)
        running = self._probe is not None and self._probe.running
        if running:
            try:
                self._probe_after = self.after(180, self._drain_probe)
            except tk.TclError:
                self._probe_after = None

    def _apply_probe_results(self, outcomes: list[providers.ProbeOutcome]) -> None:
        found = [item for item in outcomes if item.ok]
        online = sum(1 for item in found)
        total = len(self._probe_state)
        self._probe_summary = (f"Р»РѕРєР°Р»СЊРЅРёС… РѕРЅР»Р°Р№РЅ: {online} Р· {total}" if total
                               else "СЃРµСЂРІРµСЂРё РЅРµ РїРµСЂРµРІС–СЂРµРЅРѕ")
        # РџРѕС‚РѕС‡РЅРёР№ СЃРµСЂРІРµСЂ РІС–РґРїРѕРІС–РІ вЂ” РјРѕРґРµР»СЊ СЃРїСЂР°РІРґС– РґРѕСЃС‚СѓРїРЅР°.
        current_url = (self.settings.llm.base_url or "").rstrip("/")
        for item in outcomes:
            if item.base_url.rstrip("/") != current_url:
                continue
            if item.ok and not self.settings.llm.model and item.models:
                self.settings.llm.model = item.models[0]
            self._refresh_model_state(online=item.ok, detail=item.detail)
        # Р›РѕРєР°Р»СЊРЅРёР№ СЃС‚Р°РЅ Сѓ РїС–РґРІР°Р»С– РЅР°РІС–РіР°С†С–С—.
        local_online = [item for item in found
                        if providers._kind_of(item.base_url) == providers.LOCAL]
        try:
            if local_online:
                self.local_label.configure(text=f"в—Џ {local_online[0].key}", fg=theme.SUCCESS)
            elif total:
                self.local_label.configure(text="в—Џ Р»РѕРєР°Р»СЊРЅРѕ", fg=theme.FG_FAINT)
        except (tk.TclError, AttributeError):
            pass
        if self._model_selector is not None and self._model_selector.visible:
            self._fill_model_selector()

    def _refresh_model_state(self, *, online: bool, detail: str = "") -> None:
        """РћРЅРѕРІРёС‚Рё РїРѕРєР°Р· Р°РєС‚РёРІРЅРѕС— РјРѕРґРµР»С– Р’ РЈРЎР†РҐ РјС–СЃС†СЏС… вЂ” Р· РѕРґРЅРѕРіРѕ РґР¶РµСЂРµР»Р°.

        Р”Р•Р¤Р•РљРў (СЃРєСЂС–РЅС€РѕС‚ РєРѕСЂРёСЃС‚СѓРІР°С‡Р°): С€Р°РїРєР° Р№ РїР°РЅРµР»СЊ РєРѕРЅС‚РµРєСЃС‚Сѓ РїРѕРєР°Р·СѓРІР°Р»Рё
        ``qwen2.5-coder-14b``, Р° РїС–РіСѓР»РєР° РІ РєСѓС‚С–, СЂСЏРґРѕРє РєРѕРјРїРѕР·РµСЂР° Р№ СЃС‚Р°С‚СѓСЃ вЂ”
        ``Ministral-3-14B``. РџСЂРёС‡РёРЅР°: РїС–РґРїРёСЃРё РѕРЅРѕРІР»СЋРІР°Р»РёСЃСЊ Р Р†Р—РќРРњР С€Р»СЏС…Р°РјРё,

        * ``header_bar`` (С€Р°РїРєР°) вЂ” Р»РёС€Рµ Р· ``_refresh_header()``;
        * ``session_header`` (РїС–РіСѓР»РєР°) С– ``chat`` вЂ” Р· ``_sync_active_model()``;
        * РєРѕРјРїРѕР·РµСЂ вЂ” СѓР·Р°РіР°Р»С– Р· РјРѕРґРµР»С– Р§РђРўРЈ (``chat.model``), СЏРєР° Р»РёС€Р°Р»Р°СЃСЊ
          РІС–Рґ РїРѕРїРµСЂРµРґРЅСЊРѕРіРѕ РІРёР±РѕСЂСѓ.

        Р§РµСЂРµР· С†Рµ РІ РѕРґРЅРѕРјСѓ РІС–РєРЅС– Р¶РёР»Рё Р”Р’Рђ СЂС–Р·РЅС– Р·РЅР°С‡РµРЅРЅСЏ, С– РєРѕСЂРёСЃС‚СѓРІР°С‡
        СЃР»СѓС€РЅРѕ РїРёС‚Р°РІ В«С‡РѕРјСѓ РІРёР±СЂР°РЅС– РґРІС– РјРѕРґРµР»С–?В».

        РўРµРїРµСЂ СѓСЃС– РїС–РґРїРёСЃРё СЃС‚Р°РІР»СЏС‚СЊСЃСЏ РћР”РќРРњ РІРёРєР»РёРєРѕРј С– Р· РћР”РќРћР“Рћ РґР¶РµСЂРµР»Р° вЂ”
        ``providers.current_entry(settings)``. Р¦Рµ С”РґРёРЅРµ РјС–СЃС†Рµ, РґРµ РјРѕРґРµР»СЊ
        РїРµСЂРµС‚РІРѕСЂСЋС”С‚СЊСЃСЏ РЅР° РїС–РґРїРёСЃ.
        """
        entry = providers.current_entry(self.settings)
        entry.online = online
        self.header.set_model(entry)
        self.chat.set_online(online, detail)
        # Р’Р•Р›РРљРР™ СЃС‚Р°С‚СѓСЃ Сѓ С€Р°РїС†С–: В«в—Џ РњРћР”Р•Р›Р¬ РћРќР›РђР™Рќ / РћР¤Р›РђР™РќВ». РЎР°РјРµ РІС–РЅ
        # РґР°С” РІС–РґРїРѕРІС–РґСЊ РЅР° РіРѕР»РѕРІРЅРµ РїРёС‚Р°РЅРЅСЏ РєРѕСЂРёСЃС‚СѓРІР°С‡Р° РѕРґРЅРёРј РїРѕРіР»СЏРґРѕРј.
        try:
            self.header_bar.set_model_status(
                bool(online),
                detail=detail or f"{entry.name} В· {self.settings.llm.base_url}")
        except (tk.TclError, AttributeError):
            pass
        self._sync_model_labels(entry)

    def _sync_model_labels(self, entry: "providers.ModelEntry" = None) -> None:
        """РџРѕСЃС‚Р°РІРёС‚Рё РћР”РРќ РїС–РґРїРёСЃ РјРѕРґРµР»С– РІ СѓСЃС– РІС–РґР¶РµС‚Рё, С‰Рѕ С—С— РїРѕРєР°Р·СѓСЋС‚СЊ.

        Р¦Рµ С”РґРёРЅР° С‚РѕС‡РєР°. Р Р°РЅС–С€Рµ С—С… Р±СѓР»Рѕ С‚СЂРё, С– РІРѕРЅРё СЂРѕР·С…РѕРґРёР»РёСЃСЊ: С€Р°РїРєР°
        Р±СЂР°Р»Р° РјРѕРґРµР»СЊ С–Р· РЅР°Р»Р°С€С‚СѓРІР°РЅСЊ, РєРѕРјРїРѕР·РµСЂ вЂ” С–Р· Р·Р°РїРёСЃСѓ С‡Р°С‚Сѓ, РїС–РіСѓР»РєР° вЂ”
        Р· С‚СЂРµС‚СЊРѕРіРѕ РІРёРєР»РёРєСѓ. РўРµРїРµСЂ РґР¶РµСЂРµР»Рѕ РѕРґРЅРµ Р№ РѕР±РѕРІКјСЏР·РєРѕРІРµ.
        """
        if entry is None:
            entry = providers.current_entry(self.settings)
        name = entry.name
        # 1. РЁР°РїРєР° (header_bar) вЂ” СЃР°РјРµ РІРѕРЅР° РїРѕРєР°Р·СѓС” В«вЉџ РјРѕРґРµР»СЊ В· Р»РѕРєР°Р»СЊРЅР° в–ѕВ».
        bar = getattr(self, "header_bar", None)
        if bar is not None:
            try:
                bar.set_model(name, local=entry.is_local, online=entry.online)
            except (tk.TclError, AttributeError):
                LOG.debug("РџС–РґРїРёСЃ РјРѕРґРµР»С– РІ С€Р°РїС†С– РЅРµ РѕРЅРѕРІР»РµРЅРѕ", exc_info=True)
        # 2. РџС–РіСѓР»РєР° СЃРµСЃС–С— РїС–Рґ РЅР°Р·РІРѕСЋ С‡Р°С‚Сѓ.
        header = getattr(self, "header", None)
        if header is not None:
            try:
                header.set_model(entry)
            except (tk.TclError, AttributeError):
                LOG.debug("РџС–РґРїРёСЃ РјРѕРґРµР»С– РІ РїС–РіСѓР»С†С– РЅРµ РѕРЅРѕРІР»РµРЅРѕ", exc_info=True)
        # 3. РљРЅРѕРїРєР° РјРѕРґРµР»С– РІ РєРѕРјРїРѕР·РµСЂС–. Р’РђР–Р›РР’Рћ: СЃС‚Р°РІРёРјРѕ РјРѕРґРµР»СЊ
        #    РЅР°Р»Р°С€С‚СѓРІР°РЅСЊ, Р° РЅРµ В«РјРѕРґРµР»СЊ С‡Р°С‚СѓВ» вЂ” С–РЅР°РєС€Рµ РїС–СЃР»СЏ Р·РјС–РЅРё РјРѕРґРµР»С–
        #    РІ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏС… РєРѕРјРїРѕР·РµСЂ РїРѕРєР°Р·СѓРІР°РІ СЃС‚Р°СЂСѓ (СЃР°РјРµ С†Рµ Р№ Р±СѓР»Рѕ).
        chat = getattr(self, "chat", None)
        if chat is not None:
            try:
                chat.chat_model = name
                chat.set_model_label(name)
                chat._paint_model_button()
            except (tk.TclError, AttributeError):
                LOG.debug("РџС–РґРїРёСЃ РјРѕРґРµР»С– РІ РєРѕРјРїРѕР·РµСЂС– РЅРµ РѕРЅРѕРІР»РµРЅРѕ", exc_info=True)
        # 4. Р—Р°РїРёСЃ Р°РєС‚РёРІРЅРѕРіРѕ С‡Р°С‚Сѓ вЂ” С‰РѕР± РїС–СЃР»СЏ РїРµСЂРµР·Р°РїСѓСЃРєСѓ Р±СѓР»Рѕ С‚Рµ СЃР°РјРµ.
        store = getattr(self, "chat_store", None)
        try:
            active = store.active() if store is not None else None
        except (AttributeError, tk.TclError):
            active = None
        if active is not None and getattr(active, "model", "") != name:
            try:
                active.model = name
                store.save()
            except Exception:  # noqa: BLE001 - С–СЃС‚РѕСЂС–СЏ РЅРµ РјР°С” Р»Р°РјР°С‚Рё РїРѕРєР°Р·
                LOG.debug("РњРѕРґРµР»СЊ С‡Р°С‚Сѓ РЅРµ Р·Р±РµСЂРµР¶РµРЅРѕ", exc_info=True)

    def _sync_active_model(self) -> None:
        """РЎСѓРјС–СЃРЅС–СЃС‚СЊ: С‚Рµ СЃР°РјРµ, С‰Рѕ :meth:`_sync_model_labels`."""
        self._sync_model_labels()

    def show_model_selector(self, anchor: object = None) -> None:
        """Р’С–РґРєСЂРёС‚Рё СЃРµР»РµРєС‚РѕСЂ РјРѕРґРµР»РµР№.

        ``anchor`` вЂ” РІС–РґР¶РµС‚, РЅР°Рґ СЏРєРёРј РїРѕРєР°Р·Р°С‚Рё СЃРїРёСЃРѕРє (РєРЅРѕРїРєР° РјРѕРґРµР»С– РІ
        С€Р°РїС†С– Р°Р±Рѕ РєРѕРјРїРѕР·РµСЂ). РЁР°РїРєР° РїРµСЂРµРґР°С” Р№РѕРіРѕ СЏРІРЅРѕ: Р±РµР· С†СЊРѕРіРѕ СЃРїРёСЃРѕРє
        РІС–РґРєСЂРёРІР°РІСЃСЏ РЅР°Рґ РєРѕРјРїРѕР·РµСЂРѕРј РЅР°РІС–С‚СЊ С‚РѕРґС–, РєРѕР»Рё РЅР°С‚РёСЃРЅСѓР»Рё РєРЅРѕРїРєСѓ
        РІРіРѕСЂС–, С– РІРёРіР»СЏРґР°РІ В«РїСЂРёРєР»РµС”РЅРёРјВ» РґРѕ С‡СѓР¶РѕРіРѕ РјС–СЃС†СЏ.
        """
        if self._model_selector is None:
            self._model_selector = model_selector.ModelSelector(
                self, self.theme, self.settings,
                on_pick=self._on_model_selected,
                on_refresh=self.probe_providers,
                on_manage=self.open_settings,
            )
        elif self._model_selector.visible:
            self._model_selector.close()
            return
        self._fill_model_selector()
        target = anchor or getattr(self.chat, "composer_card", None) \
            or self.header.model_label
        self._model_selector.show_above(target)

    def _fill_model_selector(self) -> None:
        if self._model_selector is None:
            return
        entries = providers.catalogue(self.settings, probed=self._probe_state)
        local = sum(1 for entry in entries if entry.is_local and entry.online)
        summary = self._probe_summary or f"С‚РѕС‡РѕРє РІС…РѕРґСѓ: {len(entries)}"
        if local:
            summary = f"Р»РѕРєР°Р»СЊРЅРёС… РіРѕС‚РѕРІРѕ: {local} В· {summary}"
        self._model_selector.set_entries(entries, summary=summary)

    def _on_model_selected(self, entry: providers.ModelEntry) -> None:
        """РљРѕСЂРёСЃС‚СѓРІР°С‡ РІРёР±СЂР°РІ РјРѕРґРµР»СЊ Сѓ СЃРµР»РµРєС‚РѕСЂС–."""
        providers.apply_choice(self.settings, entry)
        self.agent.llm_settings = self.settings.llm
        chat = self.chat_store.active()
        if chat is not None:
            try:
                chat.model = entry.name
                self.chat_store.save()
            except Exception:  # noqa: BLE001 - С–СЃС‚РѕСЂС–СЏ РЅРµ РјР°С” Р»Р°РјР°С‚Рё РІРёР±С–СЂ
                LOG.warning("РќРµ РІРґР°Р»РѕСЃСЊ Р·Р±РµСЂРµРіС‚Рё РјРѕРґРµР»СЊ Сѓ С‡Р°С‚С–", exc_info=True)
        self.chat.set_chat_model(entry.name, self.chat.chat_effort)
        self._on_model_changed()
        # Р РµР°Р»СЊРЅРёР№ СЃС‚Р°РЅ вЂ” Р· РїРµСЂРµРІС–СЂРєРё РїСЂРѕРІР°Р№РґРµСЂР°, Р° РЅРµ В«РјРѕРґРµР»СЊ РІРёР±СЂР°РЅРѕ, РѕС‚Р¶Рµ
        # РѕРЅР»Р°Р№РЅВ». Р Р°РЅС–С€Рµ С‚СѓС‚ СЃС‚РѕСЏР»Рѕ ``entry.online or True``: СѓРјРѕРІР° Р·Р°РІР¶РґРё
        # С–СЃС‚РёРЅРЅР°, С‚РѕР¶ Р·РµР»РµРЅРёР№ С–РЅРґРёРєР°С‚РѕСЂ СЃРІС–С‚РёРІСЃСЏ РЅР°РІС–С‚СЊ РґР»СЏ РЅРµРґРѕСЃС‚СѓРїРЅРѕРіРѕ
        # СЃРµСЂРІРµСЂР°, С– РєРѕСЂРёСЃС‚СѓРІР°С‡ Р±Р°С‡РёРІ В«РїСЂР°С†СЋС”В» РїРµСЂРµРґ СЂРµР°Р»СЊРЅРѕСЋ РїРѕРјРёР»РєРѕСЋ.
        self._refresh_model_state(online=entry.online)
        kind = "Р»РѕРєР°Р»СЊРЅР°" if entry.is_local else "С…РјР°СЂРЅР°"
        self.set_status(f"РњРѕРґРµР»СЊ: {entry.name} В· {entry.provider_label} ({kind})")

    def show_mode_menu(self, anchor: object = None) -> None:
        """РњРµРЅСЋ СЂРµР¶РёРјС–РІ СЂРѕР±РѕС‚Рё Р°РіРµРЅС‚Р° (СЂРµР°Р»СЊРЅС– РґРѕР·РІРѕР»Рё Р№ РєСЂРѕРєРё).

        ``anchor`` РїРµСЂРµРґР°С” С€Р°РїРєР° Р°Р±Рѕ РїС–РіСѓР»РєР° РєРѕРјРїРѕР·РµСЂР°: РјРµРЅСЋ РјСѓСЃРёС‚СЊ
        РІС–РґРєСЂРёС‚РёСЃСЊ РїС–Рґ РўР†Р„Р® РєРЅРѕРїРєРѕСЋ, СЏРєСѓ РЅР°С‚РёСЃРЅСѓР»Рё, Р° РЅРµ РїС–Рґ РїС–РґРїРёСЃРѕРј
        СЂРµР¶РёРјСѓ РІ С€Р°РїС†С–.
        """
        if self._mode_menu is not None and self._mode_menu.visible:
            self._mode_menu.close()
            return
        self._mode_menu = modes_menu.ModeMenu(
            self, self.theme, self._on_mode_selected, current=self.agent_mode)
        self._mode_menu.show_below(anchor or self.header.mode_label)

    def show_workspace_menu(self, anchor: object = None) -> None:
        """РњРµРЅСЋ СЂРѕР±РѕС‡РѕРіРѕ РїСЂРѕСЃС‚РѕСЂСѓ: РїРѕС‚РѕС‡РЅР° С‚РµРєР°, РѕСЃС‚Р°РЅРЅС–, В«РґРѕРґР°С‚РёВ».

        Р¦Рµ С‚РѕР№ СЃР°РјРёР№ РІРёР±С–СЂ, С‰Рѕ Р№ Сѓ С€Р°РїС†С–, Р°Р»Рµ РґРѕСЃС‚СѓРїРЅРёР№ С–Р· РїС–РіСѓР»РєРё РЅР°Рґ
        РїРѕР»РµРј РІРІРѕРґСѓ. РџРѕРєР°Р·СѓСЋС‚СЊСЃСЏ Р»РёС€Рµ Р Р•РђР›Р¬РќР† С‚РµРєРё: РїРѕС‚РѕС‡РЅР° (СЏРєС‰Рѕ С–СЃРЅСѓС”)
        С– С‚С– Р·С– СЃРїРёСЃРєСѓ РѕСЃС‚Р°РЅРЅС–С…, С‰Рѕ РґРѕСЃС– РЅР° РґРёСЃРєСѓ. РњРµСЂС‚РІС– РїСѓРЅРєС‚Рё РЅРµ
        РјР°Р»СЋСЋС‚СЊСЃСЏ вЂ” СЂР°РЅС–С€Рµ РІРёР±С–СЂ Р·РЅРёРєР»РѕС— С‚РµРєРё РІРёРіР»СЏРґР°РІ СЏРє РїРѕР»РѕРјРєР° РєРЅРѕРїРєРё.
        """
        menu = getattr(self, "_workspace_menu", None)
        if menu is not None:
            try:
                menu.destroy()
            except tk.TclError:
                pass
            self._workspace_menu = None
            return
        current = str(self.settings.workspace or "") if self.has_project() else ""
        menu = workspace_menu.WorkspaceMenu(
            self, self.theme,
            current=current,
            recent=list(getattr(self.settings, "recent", []) or []),
            on_pick=self._pick_workspace_from_chat,
            on_add=self.open_folder_dialog,
        )
        self._workspace_menu = menu
        target = anchor or getattr(self.chat, "workspace_btn", None) \
            or self.header.workspace_btn
        menu.show_at(target)

    def _pick_workspace_from_chat(self, path: str) -> None:
        """РўРµРєСѓ РІРёР±СЂР°РЅРѕ РїС–РіСѓР»РєРѕСЋ РІ С‡Р°С‚С– вЂ” Р·Р°СЃС‚РѕСЃСѓРІР°С‚Рё С‚С–С”СЋ Р¶ Р»РѕРіС–РєРѕСЋ, С‰Рѕ Р№ С€Р°РїРєР°."""
        folder = Path(str(path or "").strip())
        if not folder.is_dir():
            self.set_status(f"РўРµРєРё Р±С–Р»СЊС€Рµ РЅРµРјР°С”: {path}")
            return
        if self.has_project():
            try:
                same = Path(self.settings.workspace).resolve() == folder.resolve()
            except OSError:
                same = False
            if same:
                self.set_status(f"РЈР¶Рµ РїСЂР°С†СЋСЋ Р· С‚РµРєРѕСЋ: {folder}")
                return
        self.set_workspace(folder)

    def show_chat_mode_menu(self) -> None:
        """РЎРїР»РёРІРЅРµ РјРµРЅСЋ СЂРµР¶РёРјСѓ С‡Р°С‚Сѓ: Р°РІС‚РѕРЅРѕРјРЅРёР№ С– Р°РІС‚РѕРјР°С‚РёР·Р°С†С–С—.

        Р¦С– РґРІР° РїСѓРЅРєС‚Рё РїСЂРёР±СЂР°РЅРѕ Р· Р»С–РІРѕРіРѕ РјРµРЅСЋ: РІРѕРЅРё СЃС‚РѕСЃСѓСЋС‚СЊСЃСЏ РєРѕРЅРєСЂРµС‚РЅРѕС—
        СЃРµСЃС–С— Р№ С‚РµРєРё, Р° РЅРµ РІСЃСЊРѕРіРѕ Р·Р°СЃС‚РѕСЃСѓРЅРєСѓ. РњРµРЅСЋ РїРѕРєР°Р·СѓС”, РґРѕ СЏРєРѕРіРѕ С‡Р°С‚Сѓ
        Р№ РїСЂРѕС”РєС‚Сѓ РІРѕРЅРё РЅР°Р»РµР¶Р°С‚СЊ, С– СЃР°РјРµ С‚РѕРјСѓ РІ РЅСЊРѕРјСѓ РІРёРґРЅРѕ С– РЅР°Р·РІСѓ С‡Р°С‚Сѓ,
        С– С‚РµРєСѓ.
        """
        menu = getattr(self, "_chat_mode_menu", None)
        if menu is not None:
            try:
                menu.destroy()
            except tk.TclError:
                pass
            self._chat_mode_menu = None
            return
        pending = [t for t in self.task_queue.tasks
                   if t.status in {queue_engine.PENDING, queue_engine.RUNNING}]
        owner = str(getattr(self.chat_store, "active_id", "") or "")
        mine = [t for t in pending
                if not getattr(t, "chat_id", "") or str(t.chat_id) == owner]
        chat = self.chat_store.active()
        menu = chat_mode_menu.ChatModeMenu(
            self, self.theme,
            chat_title=(chat.title if chat else "") or "РќРѕРІРёР№ С‡Р°С‚",
            project=self._project_root().name if self._project_root() else "",
            autonomous_on=self.autonomous_engine.active,
            autonomous_state=self.autonomous_engine.state,
            queue_count=len(mine),
            on_autonomous=self._toggle_autonomous_for_chat,
            on_automations=lambda: self.show_side("queue"),
            on_pick_project=self.open_folder_dialog,
        )
        self._chat_mode_menu = menu
        menu.show_at(self.header.chat_mode_label)

    def _toggle_autonomous_for_chat(self) -> None:
        """РЎС‚Р°СЂС‚/Р·СѓРїРёРЅРєР° Р°РІС‚РѕРЅРѕРјРЅРѕРіРѕ СЂРµР¶РёРјСѓ РґР»СЏ РџРћРўРћР§РќРћР“Рћ С‡Р°С‚Сѓ Р№ РїСЂРѕС”РєС‚Сѓ."""
        if self.autonomous_engine.active:
            self.stop_autonomous()
            return
        self.start_autonomous()

    def _on_mode_selected(self, key: str) -> None:
        self.set_agent_mode(key)

    def set_agent_mode(self, key: str) -> None:
        """Р—Р°СЃС‚РѕСЃСѓРІР°С‚Рё СЂРµР¶РёРј: РґРѕР·РІРѕР»Рё, Р»С–РјС–С‚ РєСЂРѕРєС–РІ, РїС–РґРєР°Р·РєР° Р°РіРµРЅС‚Сѓ."""
        mode = modes.apply(self.settings, self.agent, key)
        self.agent_mode = mode.key
        self.settings.ui.mode = mode.key
        self.settings.agent.mode = mode.key
        self.settings.save()
        # РЎРёРЅС…СЂРѕРЅС–Р·СѓРІР°С‚Рё РїРµСЂРµРјРёРєР°С‡ РґРѕР·РІРѕР»С–РІ Сѓ РєРѕРјРїРѕР·РµСЂС– Р· СЂРµР¶РёРјРѕРј.
        try:
            self.chat.set_permission_mode(mode.permission)
        except (tk.TclError, AttributeError):
            pass
        self.header.set_mode(mode.key)
        self.header.set_status("idle", mode.hint)
        # РџС–РіСѓР»РєР° РЅР°Рґ РїРѕР»РµРј РІРІРѕРґСѓ РїРѕРєР°Р·СѓС” С‚РѕР№ СЃР°РјРёР№ СЂРµР¶РёРј: С†Рµ С‚Рµ, С‰Рѕ Р°РіРµРЅС‚
        # СЃРїСЂР°РІРґС– Р·Р°СЃС‚РѕСЃСѓС” (РґРѕР·РІРѕР»Рё, РєСЂРѕРєРё, С–РЅСЃС‚СЂСѓРјРµРЅС‚Рё), Р° РЅРµ РїС–РґРїРёСЃ.
        try:
            self.chat.set_mode(mode.label, icon=mode.icon,
                               accent=mode.key != modes.CHAT)
        except (tk.TclError, AttributeError):
            pass
        self.set_status(f"Р РµР¶РёРј: {mode.label} В· {mode.hint}")

    # в”Ђв”Ђ С…Р°Р± РјРѕРґРµР»РµР№ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def open_model_hub(self) -> None:
        self.show_bottom("hub")
        self.model_hub.start()

    def open_first_run(self) -> None:
        self._close_popovers()
        wizard = FirstRunWizard(self, self.theme, self.settings, on_done=self._after_first_run)
        wizard.focus_set()

    def _after_first_run(self, connected: bool) -> None:
        if not connected:
            self.set_status("РњР°Р№СЃС‚РµСЂ Р·Р°РєСЂРёС‚Рѕ. РњРѕРґРµР»СЊ РјРѕР¶РЅР° РЅР°Р»Р°С€С‚СѓРІР°С‚Рё РїС–Р·РЅС–С€Рµ С‡РµСЂРµР· В«РҐР°Р± РјРѕРґРµР»РµР№В».")
            # Р‘С–Р±Р»С–РѕС‚РµРєРё Р№ РїСЂРѕРіСЂР°РјРё РјРѕРіР»Рё Р·РјС–РЅРёС‚РёСЃСЊ вЂ” РїРµСЂРµС‡РёС‚СѓС”РјРѕ СЃС‚Р°РЅ, С‰РѕР±
            # РїР°РЅРµР»С– РѕРґСЂР°Р·Сѓ Р±Р°С‡РёР»Рё, С‰Рѕ С‚РµРїРµСЂ РґРѕСЃС‚СѓРїРЅРѕ (РЅР°РїСЂ. Р·'СЏРІРёРІСЃСЏ git).
            self.after(300, self._refresh_after_env_change)
            return
        self._on_model_changed()
        self.probe_providers(silent=True)
        self._refresh_after_env_change()
        self.set_status(f"РњРѕРґРµР»СЊ РїС–РґРєР»СЋС‡РµРЅР°: {self.settings.llm.model or 'Р»РѕРєР°Р»СЊРЅРёР№ СЃРµСЂРІРµСЂ'}")

    def _refresh_after_env_change(self) -> None:
        """РџС–СЃР»СЏ РјР°Р№СЃС‚СЂР°: РѕРЅРѕРІРёС‚Рё РїР°РЅРµР»С–, СЏРєС– Р·Р°Р»РµР¶Р°С‚СЊ РІС–Рґ РїСЂРѕРіСЂР°Рј С– РїР°РєРµС‚С–РІ."""
        try:
            self.changes_panel.refresh()
        except (tk.TclError, AttributeError):
            LOG.debug("РџР°РЅРµР»СЊ Р·РјС–РЅ РЅРµ РѕРЅРѕРІРёР»Р°СЃСЊ", exc_info=True)
        try:
            self.rag_panel.refresh_status()
        except (tk.TclError, AttributeError):
            LOG.debug("РЎС‚Р°С‚СѓСЃ RAG РЅРµ РѕРЅРѕРІРёРІСЃСЏ", exc_info=True)
        try:
            self.refresh_rag_status()
        except (tk.TclError, AttributeError):
            pass

    def _apply_cloud_provider(self) -> bool:
        """РЇРєС‰Рѕ РІ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏС… С” С…РјР°СЂРЅРёР№ Р°РіРµРЅС‚ вЂ” РїС–РґРєР»СЋС‡РёС‚Рё Р№РѕРіРѕ Р·Р°РјС–СЃС‚СЊ Р»РѕРєР°Р»СЊРЅРѕРіРѕ."""
        cloud = getattr(self.settings, "cloud", None)
        if cloud is None or not getattr(cloud, "enabled", False):
            return False
        url = cloud_agents.normalise_base_url(cloud.base_url)
        if not url or not cloud.api_key.strip():
            return False
        self.settings.llm.base_url = url
        self.settings.llm.api_key = cloud.api_key
        if cloud.model:
            self.settings.llm.model = cloud.model
        self.settings.llm.max_tokens = max(256, int(cloud.max_tokens or 2048))
        self.settings.llm.temperature = float(cloud.temperature or 0.3)
        # РҐРјР°СЂРЅРёР№ Р°РіРµРЅС‚ СѓР¶Рµ Р·Р°РїСѓС‰РµРЅРёР№ вЂ” Р»РѕРєР°Р»СЊРЅРёР№ СЂСѓС€С–Р№ РЅРµ РїРѕС‚СЂС–Р±РµРЅ.
        self.settings.engine.auto_start = False
        self.agent.llm_settings = self.settings.llm
        provider = cloud_agents.get(cloud.provider)
        name = provider.label if provider else "С…РјР°СЂР°"
        reasoning = " В· reasoning" if cloud_agents.is_reasoning_model(cloud.model) else ""
        self.set_status(f"РҐРјР°СЂРЅРёР№ Р°РіРµРЅС‚: {name} В· {cloud.model}{reasoning}")
        self._cloud_active = True
        return True

    def _on_hub_model_ready(self, base_url: str, model_name: str) -> None:
        from .runtime import MANAGED_API_KEY

        # в”Ђв”Ђ Р’РёРІР°РЅС‚Р°Р¶РµРЅРЅСЏ РїРѕРїРµСЂРµРґРЅСЊРѕС— РјРѕРґРµР»С– в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        # РљРѕР»Рё РєРѕСЂРёСЃС‚СѓРІР°С‡ Р·Р°РїСѓСЃРєР°С” Р†РќРЁРЈ РјРѕРґРµР»СЊ С–Р· С…Р°Р±Р°, РїРѕРїРµСЂРµРґРЅС–Р№
        # РєРµСЂРѕРІР°РЅРёР№ СЃРµСЂРІРµСЂ РјСѓСЃРёС‚СЊ Р±СѓС‚Рё Р·СѓРїРёРЅРµРЅРёР№. Р†РЅР°РєС€Рµ РґРІС– РјРѕРґРµР»С–
        # РѕРґРЅРѕС‡Р°СЃРЅРѕ С‚СЂРёРјР°СЋС‚СЊ РІС–РґРµРѕРїР°Рј'СЏС‚СЊ: РїРµСЂС€Р° РІР¶Рµ РЅРµ РїРѕС‚СЂС–Р±РЅР°, Р°Р»Рµ
        # Р·Р°Р№РјР°С” РіС–РіР°Р±Р°Р№С‚Рё, С– РґСЂСѓРіР° РЅРµ РІР»С–Р·Р°С” (РїРµСЂРµРІС–СЂРµРЅРѕ:
        # tests/test_model_switch_live.py).
        #
        # ``_release_models`` СѓР¶Рµ РІРјС–С” С†Рµ СЂРѕР±РёС‚Рё (РІС–РЅ Р¶Рµ РІРёРєР»РёРєР°С”С‚СЊСЃСЏ РїСЂРё
        # Р·Р°РєСЂРёС‚С‚С– IDE), С‚РѕРјСѓ РІРёРєРѕСЂРёСЃС‚РѕРІСѓС”РјРѕ СЃР°РјРµ Р№РѕРіРѕ вЂ” РѕРґРЅР° Р»РѕРіС–РєР° РЅР°
        # РІСЃС– РІРёРїР°РґРєРё, Р° РЅРµ РєРѕРїС–СЏ.
        previous = getattr(self, "_managed_server", None)
        previous_url = ""
        if previous is not None:
            previous_url = str(getattr(previous, "base_url", "") or "")
            if previous_url.rstrip("/") != str(base_url or "").rstrip("/"):
                self._stop_previous_model(previous, previous_url)

        self.settings.llm.base_url = base_url
        self.settings.llm.model = model_name
        self.settings.llm.api_key = MANAGED_API_KEY
        self.settings.engine.managed = True
        self.settings.save()
        self.agent.llm_settings = self.settings.llm
        # Р§Рё РјР°С” С†СЏ РјРѕРґРµР»СЊ Р·С–СЂ: РїРµСЂРµРІС–СЂСЏС”РјРѕ, С‡Рё Р·РЅР°Р№С€РѕРІСЃСЏ РїСЂРѕС”РєС‚РѕСЂ РґР»СЏ
        # Р·Р°РІР°РЅС‚Р°Р¶РµРЅРѕРіРѕ С„Р°Р№Р»Сѓ. РўР°Рє Р°РіРµРЅС‚ Р·РЅР°С”, С‡Рё РјРѕР¶РЅР° РїРµСЂРµРґР°РІР°С‚Рё Р·РЅС–РјРєРё
        # СЏРє Р·РѕР±СЂР°Р¶РµРЅРЅСЏ (Р· РїСЂРѕС”РєС‚РѕСЂРѕРј) С‡Рё Р»РёС€Рµ СЏРє С€Р»СЏС….
        vision = False
        try:
            for path in hub.local_models():
                if path.stem == model_name or path.name == model_name:
                    vision = hub.vision_projector_for(path) is not None
                    break
        except Exception:  # noqa: BLE001 - РїРµСЂРµРІС–СЂРєР° РЅРµ РјР°С” Р»Р°РјР°С‚Рё СЃС‚Р°СЂС‚
            LOG.debug("РџРµСЂРµРІС–СЂРєР° Р·РѕСЂСѓ РЅРµ РІРґР°Р»Р°СЃСЊ", exc_info=True)
        try:
            self.agent.vision_enabled = vision
        except AttributeError:
            pass
        self.probe_providers(silent=True)
        note = " В· Р·С–СЂ СѓРІС–РјРєРЅРµРЅРѕ" if vision else ""
        self.set_status(f"РњРѕРґРµР»СЊ РіРѕС‚РѕРІР°: {model_name} В· {base_url}{note}")

    def _stop_previous_model(self, server, url: str = "") -> None:
        """Р—СѓРїРёРЅРёС‚Рё РїРѕРїРµСЂРµРґРЅСЋ РјРѕРґРµР»СЊ РџР•Р Р•Р” Р·Р°РїСѓСЃРєРѕРј РЅРѕРІРѕС— (Р·РІС–Р»СЊРЅРёС‚Рё VRAM).

        РџРѕСЂСЏРґРѕРє РІР°Р¶Р»РёРІРёР№: СЃРїРµСЂС€Сѓ Р·СѓРїРёРЅРєР°, РїРѕС‚С–Рј Р·РјС–РЅР° РЅР°Р»Р°С€С‚СѓРІР°РЅСЊ. Р†РЅР°РєС€Рµ
        Р°РіРµРЅС‚ СЏРєСѓСЃСЊ РјРёС‚СЊ СЃС‚СѓРєР°С” РЅР° СЃС‚Р°СЂСѓ Р°РґСЂРµСЃСѓ, Р° СЃС‚Р°СЂРёР№ РїСЂРѕС†РµСЃ С‰Рµ Р¶РёРІРµ.
        """
        self.set_status(f"Р’РёРІР°РЅС‚Р°Р¶СѓСЋ РїРѕРїРµСЂРµРґРЅСЋ РјРѕРґРµР»СЊ{f' ({url})' if url else ''}вЂ¦")
        try:
            server.stop()
        except Exception:  # noqa: BLE001 - Р·СѓРїРёРЅРєР° РЅРµ РјР°С” Р»Р°РјР°С‚Рё РїРµСЂРµРјРёРєР°РЅРЅСЏ
            LOG.debug("РџРѕРїРµСЂРµРґРЅС–Р№ СЃРµСЂРІРµСЂ РЅРµ Р·СѓРїРёРЅРёРІСЃСЏ", exc_info=True)
        if getattr(self, "_managed_server", None) is server:
            self._managed_server = None
        # РЎРµСЂРІРµСЂ С–Р· РїР°РЅРµР»С– С…Р°Р±Р° вЂ” РѕРєСЂРµРјРµ РїРѕР»Рµ; Р·СѓРїРёРЅСЏС”РјРѕ Р№ Р№РѕРіРѕ, СЏРєС‰Рѕ С†Рµ
        # С–РЅС€РёР№ РѕР±'С”РєС‚ (С…Р°Р± РјС–Рі С‚СЂРёРјР°С‚Рё РІР»Р°СЃРЅРёР№ РµРєР·РµРјРїР»СЏСЂ).
        try:
            hub_server = getattr(self.model_hub, "server", None)
            if hub_server is not None and hub_server is not server:
                hub_server.stop()
                self.model_hub.server = None
        except Exception:  # noqa: BLE001
            LOG.debug("РЎРµСЂРІРµСЂ С…Р°Р±Р° РЅРµ Р·СѓРїРёРЅРёРІСЃСЏ", exc_info=True)
        # РќР°Р№РЅР°РґС–Р№РЅС–С€Рµ: РґРѕР±РёС‚Рё Р±СѓРґСЊ-СЏРєС– СЂСѓС€С–С—, СЏРєС– РјРё СЃР°РјС– Р·Р°РїРёСЃР°Р»Рё.
        try:
            removed = runtime.cleanup_stale_processes()
            if removed:
                LOG.info("Р—СѓРїРёРЅРµРЅРѕ Р·Р°Р»РёС€РєРѕРІРёС… СЂСѓС€С–С—РІ: %s", removed)
        except Exception:  # noqa: BLE001
            LOG.debug("РџСЂРёР±РёСЂР°РЅРЅСЏ СЂСѓС€С–С—РІ РЅРµ РІРґР°Р»РѕСЃСЊ", exc_info=True)
        self.set_status(f"РџРѕРїРµСЂРµРґРЅСЋ РјРѕРґРµР»СЊ РІРёРІР°РЅС‚Р°Р¶РµРЅРѕ{f' ({url})' if url else ''}.")

    # в”Ђв”Ђ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _close_popovers(self) -> None:
        """Р—Р°РєСЂРёС‚Рё РІСЃС– СЃРїР»РёРІРЅС– РєР°СЂС‚РєРё (РјРѕРґРµР»СЊ, СЂРµР¶РёРјРё, РєРѕРЅС‚РµРєСЃС‚, РјРµРЅСЋ РєРѕРјР°РЅРґ).

        РџСЂРѕР±Р»РµРјР°, СЏРєСѓ С†Рµ Р»С–РєСѓС”: РєР°СЂС‚РєР° В«РњРѕРґРµР»СЊВ» РјР°С” РїСЂР°РїРѕСЂРµС†СЊ ``-topmost`` С–
        Р»РёС€Р°Р»Р°СЃСЊ РЅР° РµРєСЂР°РЅС–, РєРѕР»Рё Р·РІРµСЂС…Сѓ РІС–РґРєСЂРёРІР°РІСЃСЏ РјРѕРґР°Р»СЊРЅРёР№ РґС–Р°Р»РѕРі. Р”РІР°
        РІС–РєРЅР° РѕРґРЅРѕС‡Р°СЃРЅРѕ вЂ” РєРѕСЂРёСЃС‚СѓРІР°С‡ Р±Р°С‡РёРІ В«РґРІР° РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏВ», Р° РІРІРµРґРµРЅРЅСЏ
        РіСѓР±РёР»РѕСЃСЊ РјС–Р¶ РЅРёРјРё.
        """
        try:
            widgets.close_popovers()
        except Exception:  # noqa: BLE001 - РїСЂРёР±РёСЂР°РЅРЅСЏ РЅРµ РјР°С” Р»Р°РјР°С‚Рё РґС–СЋ
            pass

    def _on_window_deactivate(self, event=None) -> None:
        """Р“РѕР»РѕРІРЅРµ РІС–РєРЅРѕ РІС‚СЂР°С‚РёР»Рѕ С„РѕРєСѓСЃ вЂ” РїСЂРёР±РёСЂР°С”РјРѕ СЃРїР»РёРІРЅС– РєР°СЂС‚РєРё.

        РћР±РµСЂРµР¶РЅРѕ: РєР°СЂС‚РєР° С‚РµР¶ Р·Р°Р±РёСЂР°С” С„РѕРєСѓСЃ (Сѓ РЅРµС— РїРѕР»Рµ РїРѕС€СѓРєСѓ), С– С‚РѕРґС–
        ``FocusOut`` РїСЂРёС…РѕРґРёС‚СЊ РѕРґСЂР°Р·Сѓ РїС–СЃР»СЏ РІС–РґРєСЂРёС‚С‚СЏ вЂ” Р·Р°РєСЂРёРІР°С‚Рё РІ С†РµР№
        РјРѕРјРµРЅС‚ РЅРµ РјРѕР¶РЅР°, С–РЅР°РєС€Рµ РєР°СЂС‚РєР° В«РјРёРіРѕС‚РёС‚СЊВ» С– Р·РЅРёРєР°С”. РўРѕРјСѓ РїРµСЂРµРІС–СЂСЏС”РјРѕ,
        Р§РР™ СЃР°РјРµ РІС–РґР¶РµС‚ РѕС‚СЂРёРјР°РІ С„РѕРєСѓСЃ: СЏРєС‰Рѕ С†Рµ РЅР°С€Рµ СЃРїР»РёРІРЅРµ РІС–РєРЅРѕ вЂ”
        Р»РёС€Р°С”РјРѕ РєР°СЂС‚РєСѓ РІС–РґРєСЂРёС‚РѕСЋ.
        """
        if event is not None and getattr(event, "widget", None) is not self:
            return
        # РњРѕРґР°Р»СЊРЅРёР№ РґС–Р°Р»РѕРі Р·Р°Р±РёСЂР°С” С„РѕРєСѓСЃ вЂ” РєР°СЂС‚РєРё РІС–РЅ СѓР¶Рµ РїСЂРёР±СЂР°РІ СЃР°Рј.
        if widgets.active_modal() is not None:
            return
        try:
            focused = self.focus_get()
        except (tk.TclError, KeyError):
            focused = None
        if focused is not None and widgets.is_popover_widget(focused):
            return
        self._close_popovers()

    def open_settings(self) -> None:
        # РЎРїРµСЂС€Сѓ РїСЂРёР±РёСЂР°С”РјРѕ СЃРїР»РёРІРЅС– РєР°СЂС‚РєРё: С–РЅР°РєС€Рµ РІРѕРЅРё Р»РёС€Р°СЋС‚СЊСЃСЏ РїРѕРІРµСЂС…
        # Р°Р±Рѕ РїРѕСЂСЏРґ С–Р· РјРѕРґР°Р»СЊРЅРёРј РґС–Р°Р»РѕРіРѕРј.
        self._close_popovers()
        SettingsDialog(self, self.theme, self.settings, on_saved=self._after_settings,
                       on_open_hub=self.open_model_hub,
                       on_open_panel=self._open_panel_from_settings,
                       on_first_run=self.open_first_run)

    def _open_panel_from_settings(self, key: str) -> None:
        """Р’С–РґРєСЂРёС‚Рё РїР°РЅРµР»СЊ РїСЂРѕРіСЂР°РјРё Р· РґС–Р°Р»РѕРіСѓ РЅР°Р»Р°С€С‚СѓРІР°РЅСЊ.

        Р›С–РІР° РєРѕР»РѕРЅРєР° РїРѕРєР°Р·СѓС” Р»РёС€Рµ С‡Р°С‚Рё, С‚РѕРјСѓ В«MCPВ», В«РџСЂРѕС”РєС‚РёВ», В«Р‘Р°Р·Р° Р·РЅР°РЅСЊВ»
        С– СЂРµС€С‚Р° С‚РµРїРµСЂ РІС–РґРєСЂРёРІР°СЋС‚СЊСЃСЏ Р·РІС–РґСЃРё. РџР°РЅРµР»СЊ РїРѕРєР°Р·СѓС”РјРѕ РїСЂР°РІРѕСЂСѓС‡ РІС–Рґ
        РґС–Р°Р»РѕРіСѓ вЂ” С‚Р°Рє С—С— РІРёРґРЅРѕ, Р° РЅРµ С…РѕРІР°С”РјРѕ Р·Р° РїРµСЂРµРјРёРєР°С‡РµРј.
        """
        if not self._sidebar_visible():
            self._sidebar_add()
        self.show_side(key)
        self.set_status(f"Р’С–РґРєСЂРёС‚Рѕ РїР°РЅРµР»СЊ: {PANEL_TITLES.get(key, key)}")

    def _after_settings(self) -> None:
        self.registry.confirm_commands = self.settings.agent.confirm_commands
        self.agent.agent_settings = self.settings.agent
        self.agent.llm_settings = self.settings.llm
        # РџРѕР»С–С‚РёРєР° РїСЂРѕСЃС‚РѕСЋ РјРѕРіР»Р° Р·РјС–РЅРёС‚РёСЃСЊ Сѓ РІРєР»Р°РґС†С– В«РђРіРµРЅС‚В».
        try:
            policy = self.model_keeper.tracker.policy
            policy.enabled = bool(getattr(self.settings.engine, "unload_when_idle", True))
            policy.idle_seconds = int(
                getattr(self.settings.engine, "idle_unload_seconds", 300) or 300)
            policy.normalise()
        except Exception:  # noqa: BLE001 - РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏ РЅРµ РјР°СЋС‚СЊ Р»Р°РјР°С‚Рё РІС–РєРЅРѕ
            LOG.debug("РќРµ РІРґР°Р»РѕСЃСЊ Р·Р°СЃС‚РѕСЃСѓРІР°С‚Рё РїРѕР»С–С‚РёРєСѓ РїСЂРѕСЃС‚РѕСЋ", exc_info=True)
        # РўРµРјСѓ РјРѕРіР»Рё Р·РјС–РЅРёС‚Рё Сѓ РІРєР»Р°РґС†С– В«Р РµРґР°РєС‚РѕСЂВ» вЂ” Р·Р°СЃС‚РѕСЃРѕРІСѓС”РјРѕ РґРѕ РІСЃСЊРѕРіРѕ
        # РІС–РєРЅР° (РїРµСЂРµС„Р°СЂР±СѓРІР°РЅРЅСЏ СЂРµРґР°РєС‚РѕСЂС–РІ С– РєР°СЂС‚РѕРє С‡Р°С‚Сѓ СЂРѕР±РёС‚СЊ С†РµР№ РјРµС‚РѕРґ).
        if self.settings.ui.theme != theme.current_mode():
            self.apply_theme_mode(self.settings.ui.theme)
        self.theme.set_family(self.settings.ui.font_family or self.theme.mono_family,
                              self.settings.ui.font_size)
        self.tabs.apply_settings()
        self.probe_providers(silent=True)
        self._on_model_changed()
        self._apply_voice_settings()
        # в”Ђв”Ђ РЈР’Р†РњРљРќРЈР›Р Р’Р›РђРЎРќРР™ Р РЈРЁР†Р™ вЂ” Р—РђР’РђРќРўРђР–РРўР РњРћР”Р•Р›Р¬ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        # РџСЂР°РїРѕСЂС†СЏ Р±СѓР»Рѕ Р·Р°РјР°Р»Рѕ: Р°РґСЂРµСЃР° Р»РёС€Р°Р»Р°СЃСЊ HTTP, Р° РјРѕРґРµР»СЊ Сѓ СЂСѓС€С–Р№ РЅРµ
        # Р·Р°РІР°РЅС‚Р°Р¶СѓРІР°Р»Р°СЃСЊ СѓР·Р°РіР°Р»С–, С‚РѕР¶ РїРµСЂС€РёР№ Р¶Рµ Р·Р°РїРёС‚ С–С€РѕРІ Сѓ РјРµСЂРµР¶Сѓ Р№ РїР°РґР°РІ
        # Р· В«[WinError 10061] target machine actively refused itВ».
        # РўРµРїРµСЂ Р·Р±РµСЂРµР¶РµРЅРЅСЏ РЅР°Р»Р°С€С‚СѓРІР°РЅСЊ СЃРїСЂР°РІРґС– РІРјРёРєР°С” СЂСѓС€С–Р№.
        self._apply_engine_choice()
        self.set_status("РќР°Р»Р°С€С‚СѓРІР°РЅРЅСЏ Р·Р±РµСЂРµР¶РµРЅРѕ.")

    def _apply_engine_choice(self) -> None:
        """РџСЂРёРІРµСЃС‚Рё СЃС‚Р°РЅ СЂСѓС€С–СЏ Сѓ РІС–РґРїРѕРІС–РґРЅС–СЃС‚СЊ РґРѕ РЅР°Р»Р°С€С‚СѓРІР°РЅСЊ.

        Р’РёРєР»РёРєР°С”С‚СЊСЃСЏ РїС–СЃР»СЏ Р·Р±РµСЂРµР¶РµРЅРЅСЏ РЅР°Р»Р°С€С‚СѓРІР°РЅСЊ С– РїСЂРё СЃС‚Р°СЂС‚С–. РџСЂР°РІРёР»Р°:

        * СѓРІС–РјРєРЅРµРЅРѕ РІР±СѓРґРѕРІР°РЅРёР№ СЂСѓС€С–Р№ вЂ” РјРѕРґРµР»СЊ РњРЈРЎРРўР¬ Р±СѓС‚Рё Р·Р°РІР°РЅС‚Р°Р¶РµРЅР°, С–РЅР°РєС€Рµ
          РЅР°СЃС‚СѓРїРЅРёР№ Р·Р°РїРёС‚ РїС–РґРµ РІ РїРѕСЂРѕР¶РЅРµС‡Сѓ;
        * РІРёРјРєРЅРµРЅРѕ вЂ” Р·РІС–Р»СЊРЅСЏС”РјРѕ РІС–РґРµРѕРїР°Рј'СЏС‚СЊ, С‰РѕР± РЅРµ С‚СЂРёРјР°С‚Рё С—С— РЅР°РјР°СЂРЅРѕ.
        """
        wants_native = bool(getattr(self.settings.engine, "native", True))
        if wants_native:
            if self.native_runtime.loaded:
                # РЈР¶Рµ Р·Р°РІР°РЅС‚Р°Р¶РµРЅРѕ вЂ” Р»РёС€Р°С”С‚СЊСЃСЏ РїРµСЂРµРєРѕРЅР°С‚РёСЃСЊ, С‰Рѕ С‡Р°С‚ РґРёРІРёС‚СЊСЃСЏ
                # СЃР°РјРµ РЅР° РІР±СѓРґРѕРІР°РЅРёР№ СЂСѓС€С–Р№.
                if not str(self.settings.llm.base_url or "").startswith("native://"):
                    self._on_native_model(self.native_runtime.model_path or "")
                return
            result = self._autostart_native_model()
            if result and not result.startswith(NATIVE_FAILURE_PREFIX):
                LOG.info("Р СѓС€С–Р№ СѓРІС–РјРєРЅРµРЅРѕ Р· РЅР°Р»Р°С€С‚СѓРІР°РЅСЊ: %s", result)
                self.set_status(f"Р’Р»Р°СЃРЅРёР№ СЂСѓС€С–Р№: {result}")
            elif result:
                self.set_status(
                    f"Р’Р»Р°СЃРЅРёР№ СЂСѓС€С–Р№ РЅРµ Р·Р°РІР°РЅС‚Р°Р¶РёРІСЃСЏ: {result[len(NATIVE_FAILURE_PREFIX):]}")
            return
        # Р СѓС€С–Р№ РІРёРјРєРЅРµРЅРѕ вЂ” Р·РІС–Р»СЊРЅСЏС”РјРѕ РїР°Рј'СЏС‚СЊ, Р°Р»Рµ РЅРµ С‡С–РїР°С”РјРѕ HTTP-Р°РґСЂРµСЃСѓ,
        # СЏРєСѓ РєРѕСЂРёСЃС‚СѓРІР°С‡ РјС–Рі РЅР°Р»Р°С€С‚СѓРІР°С‚Рё РЅР°РІРјРёСЃРЅРѕ.
        if self.native_runtime.loaded:
            try:
                self.native_runtime.unload_model()
                self.set_status("Р’Р»Р°СЃРЅРёР№ СЂСѓС€С–Р№ РІРёРјРєРЅРµРЅРѕ вЂ” РІС–РґРµРѕРїР°Рј'СЏС‚СЊ Р·РІС–Р»СЊРЅРµРЅРѕ.")
            except Exception as exc:                 # noqa: BLE001
                LOG.warning("РќРµ РІРґР°Р»РѕСЃСЊ РІРёРІР°РЅС‚Р°Р¶РёС‚Рё РјРѕРґРµР»СЊ: %s", exc)

    # в”Ђв”Ђ РІР»Р°СЃРЅРёР№ СЂСѓС€С–Р№ С– РїР°Рј'СЏС‚СЊ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _open_memory(self):
        """Р’С–РґРєСЂРёС‚Рё РїР°Рј'СЏС‚СЊ NEUROMESH (Р°Р±Рѕ С‡РµСЃРЅРѕ РїРѕРІРµСЂРЅСѓС‚Рё ``None``).

        РџР°Рј'СЏС‚СЊ РЅРµ РјР°С” Р»Р°РјР°С‚Рё СЃС‚Р°СЂС‚ IDE: СЏРєС‰Рѕ Р±Р°Р·Р° РЅРµРґРѕСЃС‚СѓРїРЅР° (РїСЂР°РІР°,
        РїРѕС€РєРѕРґР¶РµРЅРЅСЏ, Р·Р°Р№РЅСЏС‚РёР№ С„Р°Р№Р»), Р·Р°СЃС‚РѕСЃСѓРЅРѕРє РїСЂР°С†СЋС” РґР°Р»С–, Р° РїР°РЅРµР»СЊ
        РїРѕРєР°Р·СѓС” РїСЂРёС‡РёРЅСѓ.
        """
        try:
            from .pcmm import Neuromesh

            service = Neuromesh()
            service.attach_engine(self.native_runtime.engine)
            return service
        except Exception as exc:                     # noqa: BLE001
            LOG.warning("РџР°Рј'СЏС‚СЊ NEUROMESH РЅРµРґРѕСЃС‚СѓРїРЅР°: %s", exc, exc_info=True)
            self.set_status(f"РџР°Рј'СЏС‚СЊ РЅРµРґРѕСЃС‚СѓРїРЅР°: {exc}")
            return None

    def _on_native_model(self, path: str) -> None:
        """РњРѕРґРµР»СЊ Р·Р°РІР°РЅС‚Р°Р¶РµРЅРѕ Сѓ РІР»Р°СЃРЅРёР№ СЂСѓС€С–Р№: РїС–РґРєР»СЋС‡РёС‚Рё С—С— РґРѕ С‡Р°С‚Сѓ.

        РЎР°РјРµ С‚СѓС‚ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏ РїРµСЂРµРјРёРєР°СЋС‚СЊСЃСЏ РЅР° РІР±СѓРґРѕРІР°РЅРёР№ СЂСѓС€С–Р№, С‰РѕР± Р°РіРµРЅС‚
        РїРѕС‡Р°РІ РїСЂР°С†СЋРІР°С‚Рё Р· РјРѕРґРµР»Р»СЋ, СЏРєСѓ РІРёРєРѕРЅР°Р»Р° СЃР°РјР° IDE вЂ” Р±РµР·
        llama-server С– Р±РµР· СЂСѓС‡РЅРѕРіРѕ Р·Р°РїСѓСЃРєСѓ СЃС‚РѕСЂРѕРЅРЅС–С… РїСЂРѕРіСЂР°Рј.

        в”Ђв”Ђ Р§РћРњРЈ РџРћРўР Р†Р‘Р•Рќ ``_ui_call`` в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        РњРµС‚РѕРґ РєР»РёС‡РµС‚СЊСЃСЏ Р· Р¤РћРќРћР’РћР“Рћ РїРѕС‚РѕРєСѓ Р°РІС‚РѕР·Р°РїСѓСЃРєСѓ
        (``_auto_setup_in_background`` в†’ ``_autostart_local_model``). РўСѓС‚
        Р·РјС–РЅСЋСЋС‚СЊСЃСЏ РІС–РґР¶РµС‚Рё (``_on_model_changed`` в†’ РїС–РґРїРёСЃРё, ``set_status`` в†’
        СЃС‚Р°С‚СѓСЃР±Р°СЂ), Р° tkinter РїРѕР·Р° РіРѕР»РѕРІРЅРёРј РїРѕС‚РѕРєРѕРј РїР°РґР°С”:

            RuntimeError: main thread is not in main loop

        Р§РµСЂРµР· С†Рµ С‡Р°С‚ РќР• РїРµСЂРµРјРёРєР°РІСЃСЏ РЅР° РІР±СѓРґРѕРІР°РЅРёР№ СЂСѓС€С–Р№: РјРѕРґРµР»СЊ
        Р·Р°РІР°РЅС‚Р°Р¶РµРЅР°, Р° Р·Р°РїРёС‚Рё Р№РґСѓС‚СЊ РЅР° СЃС‚Р°СЂСѓ HTTP-Р°РґСЂРµСЃСѓ. РўРµРїРµСЂ СѓСЃРµ
        С–РЅС‚РµСЂС„РµР№СЃРЅРµ РІРёРєРѕРЅСѓС”С‚СЊСЃСЏ РІ РіРѕР»РѕРІРЅРѕРјСѓ РїРѕС‚РѕС†С–, Р° РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏ
        Р·Р±РµСЂС–РіР°СЋС‚СЊСЃСЏ РѕРґСЂР°Р·Сѓ (С†Рµ РЅРµ РІС–РґР¶РµС‚).
        """
        from .native import bridge

        # Р§Р°СЃС‚РёРЅСѓ, СЏРєР° С‡С–РїР°С” Р’Р†Р”Р–Р•РўР, РІРёРєРѕРЅСѓС”РјРѕ РІ РіРѕР»РѕРІРЅРѕРјСѓ РїРѕС‚РѕС†С–.
        def apply_ui() -> None:
            try:
                self._on_model_changed()
                if self.memory is not None:
                    self.memory.attach_engine(self.native_runtime.engine)
                self._attach_memory_bridge(self.agent)
                self._wire_exact_tokens()
                self.set_status(
                    f"Р’Р»Р°СЃРЅРёР№ СЂСѓС€С–Р№: РјРѕРґРµР»СЊ В«{Path(path).stem}В» РіРѕС‚РѕРІР° РґРѕ С‡Р°С‚Сѓ.")
            except (tk.TclError, AttributeError) as exc:
                LOG.warning("РџС–РґРїРёСЃРё РјРѕРґРµР»С– РЅРµ РѕРЅРѕРІР»РµРЅРѕ: %s", exc)

        try:
            bridge.remember_model("")
            self.settings.llm.base_url = bridge.EMBEDDED_URL
            self.settings.llm.model = Path(path).stem
            self.settings.llm.api_key = "local"
            self.settings.llm.auto_detect = False
            self.settings.engine.managed = True
            self.settings.engine.model_path = str(path)
            # РљРѕРЅС‚РµРєСЃС‚ вЂ” С„Р°РєС‚РёС‡РЅРёР№, Р· СЏРєРёРј СЂСѓС€С–Р№ Р·Р°РІР°РЅС‚Р°Р¶РёРІСЃСЏ.
            limit = self._native_context_limit()
            if limit:
                self.settings.engine.ctx_size = int(limit)
                self._context_limit = int(limit)
            safe.call_quiet(self.settings.save)
            # РђРіРµРЅС‚ Р±Р°С‡РёС‚СЊ С‚Сѓ СЃР°РјСѓ Р°РґСЂРµСЃСѓ вЂ” С†Рµ С‡РёСЃС‚РёР№ Python, Р±РµР· tkinter.
            self.agent.llm_settings = self.settings.llm
            self._context_limit = int(limit or self._context_limit or 0)
        except Exception as exc:                     # noqa: BLE001
            LOG.warning("РќРµ РІРґР°Р»РѕСЃСЊ Р°РєС‚РёРІСѓРІР°С‚Рё РјРѕРґРµР»СЊ: %s", exc, exc_info=True)
            # Р›СЏРјР±РґР° РІРёРєРѕРЅСѓС”С‚СЊСЃСЏ РџР†Р—РќР†РЁР•, РєРѕР»Рё Р·РјС–РЅРЅР° ``exc`` СѓР¶Рµ Р·РЅРёС‰РµРЅР°
            # (Python РїСЂРёР±РёСЂР°С” С—С— РїС–СЃР»СЏ РІРёС…РѕРґСѓ Р· ``except``), С‚РѕРјСѓ Р±РµСЂРµРјРѕ
            # Р·РЅС–РјРѕРє С‚РµРєСЃС‚Сѓ Р·Р°СЂР°Р· вЂ” С–РЅР°РєС€Рµ Р·Р°РјС–СЃС‚СЊ РїСЂРёС‡РёРЅРё Р±СѓРІ NameError.
            detail = str(exc)
            self._ui_call(lambda: self.set_status(
                f"РњРѕРґРµР»СЊ Р·Р°РІР°РЅС‚Р°Р¶РµРЅР°, Р°Р»Рµ С‡Р°С‚ РЅРµ РїРµСЂРµРјРєРЅСѓРІСЃСЏ: {detail}"))
            return
        # Р†РЅС‚РµСЂС„РµР№СЃ вЂ” Сѓ РіРѕР»РѕРІРЅРѕРјСѓ РїРѕС‚РѕС†С–.
        self._ui_call(apply_ui)

    def _wire_exact_tokens(self) -> None:
        """РџС–РґРєР»СЋС‡РёС‚Рё С‚РѕС‡РЅРёР№ РїС–РґСЂР°С…СѓРЅРѕРє С‚РѕРєРµРЅС–РІ РґРѕ Р°РіРµРЅС‚Р° Р№ СЃС‚Р°С‚РёСЃС‚РёРєРё.

        Р‘РµР· С†СЊРѕРіРѕ Р°РіРµРЅС‚ СЂР°С…СѓС” С‚РѕРєРµРЅРё Р·Р° В«СЃРёРјРІРѕР»Рё / 3.5В», С– РґР»СЏ СѓРєСЂР°С—РЅСЃСЊРєРѕС—
        РєРёСЂРёР»РёС†С– РїРѕРјРёР»СЏС”С‚СЊСЃСЏ Р±С–Р»СЊС€ РЅС–Р¶ СѓРґРІС–С‡С–: С–СЃС‚РѕСЂС–СЏ Р°Р±Рѕ СЂС–Р¶РµС‚СЊСЃСЏ
        Р·Р°РІС‡Р°СЃРЅРѕ, Р°Р±Рѕ РїРµСЂРµРїРѕРІРЅСЋС” РІС–РєРЅРѕ. РўРѕС‡РЅРёР№ tokenizer Р·Р°РІР°РЅС‚Р°Р¶РµРЅРѕС—
        РјРѕРґРµР»С– РІР¶Рµ С” вЂ” Р»РёС€Р°С”С‚СЊСЃСЏ РІС–РґРґР°С‚Рё Р№РѕРіРѕ С‚РёРј, С…С‚Рѕ РІРёСЂС–С€СѓС”, СЃРєС–Р»СЊРєРё
        С‚РµРєСЃС‚Сѓ РІР»С–Р·Рµ.
        """
        model = getattr(self.native_runtime.engine, "model", None)
        tokenizer = getattr(model, "tokenizer", None) if model else None
        if tokenizer is None:
            return
        def counter(text: str) -> int:
            """РўРѕС‡РЅР° РєС–Р»СЊРєС–СЃС‚СЊ С‚РѕРєРµРЅС–РІ Сѓ С‚РµРєСЃС‚С– Р·Р° tokenizer РјРѕРґРµР»С–."""
            return tokenizer.count(str(text or ""), add_special=False)

        from . import agent as agent_module
        from . import context_stats as context_stats_module

        agent_module.set_token_counter(counter)
        setter = getattr(self.agent, "set_token_counter", None)
        if callable(setter):
            setter(counter)
        # РЎРјСѓРіР° СЃС‚Р°С‚РёСЃС‚РёРєРё С‚РµР¶ РјР°С” СЂР°С…СѓРІР°С‚Рё С‚С– СЃР°РјС– С‚РѕРєРµРЅРё.
        context_stats_module.set_token_counter(counter)

    def _show_memory_item(self, memory_id: str) -> None:
        """РџРѕРєР°Р·Р°С‚Рё РґРµС‚Р°Р»С– СЃРїРѕРіР°РґСѓ (РІРёРєР»РёРє С–Р· РїР°РЅРµР»С– РїР°Рј'СЏС‚С–)."""
        if self.memory is None:
            return
        data = self.memory.explain(memory_id)
        if not data:
            self.set_status(f"РЎРїРѕРіР°Рґ {memory_id} РЅРµ Р·РЅР°Р№РґРµРЅРѕ.")
            return
        memory = data["memory"]
        lines = [
            f"ID: {memory['id']}",
            f"РўРёРї: {memory['kind']} В· РІРїРµРІРЅРµРЅС–СЃС‚СЊ {memory['confidence']}",
            f"РџРѕС…РѕРґР¶РµРЅРЅСЏ: {data.get('provenance') or 'РЅРµРІС–РґРѕРјРѕ'}",
            "",
            str(memory.get("content") or ""),
            "",
            f"Р’РїРµРІРЅРµРЅС–СЃС‚СЊ: {data.get('why_confidence')}",
        ]
        for event in (data.get("history") or [])[:10]:
            lines.append(f"В· {event.get('action')}: {str(event.get('detail'))[:160]}")
        self.show_text_window(f"РЎРїРѕРіР°Рґ {memory_id[-8:]}", "\n".join(lines))

    # в”Ђв”Ђ СЃС‚Р°С‚СѓСЃ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def set_status(self, text: str) -> None:
        try:
            self.status_label.configure(text=text)
        except tk.TclError:
            return

    def _on_hidden_failure(self, count: int) -> None:
        """Р РµС”СЃС‚СЂ Р·Р±РѕС—РІ РїРѕРІС–РґРѕРјРёРІ РїСЂРѕ РЅРѕРІРёР№: РѕРЅРѕРІРёС‚Рё С–РЅРґРёРєР°С‚РѕСЂ.

        РљР»РёС‡РµС‚СЊСЃСЏ Р· Р±СѓРґСЊ-СЏРєРѕРіРѕ РїРѕС‚РѕРєСѓ, С‚РѕРјСѓ Р»РёС€Рµ СЃС‚Р°РІРёРјРѕ РѕРЅРѕРІР»РµРЅРЅСЏ РІ С‡РµСЂРіСѓ
        РіРѕР»РѕРІРЅРѕРіРѕ С†РёРєР»Сѓ вЂ” tkinter РЅРµ РїРѕС‚РѕРєРѕР±РµР·РїРµС‡РЅРёР№.
        """
        try:
            self._ui_call(self._paint_failures, count)
        except Exception:  # noqa: BLE001 - С–РЅРґРёРєР°С‚РѕСЂ РЅРµ РјР°С” Р»Р°РјР°С‚Рё СЂРѕР±РѕС‚Сѓ
            LOG.debug("РќРµ РІРґР°Р»РѕСЃСЊ РїРѕСЃС‚Р°РІРёС‚Рё РѕРЅРѕРІР»РµРЅРЅСЏ С–РЅРґРёРєР°С‚РѕСЂР°", exc_info=True)

    def _paint_failures(self, count: int) -> None:
        try:
            if count <= 0:
                self.failure_label.configure(text="")
            else:
                self.failure_label.configure(text=f"вљ  РїСЂРёС…РѕРІР°РЅРёС… Р·Р±РѕС—РІ: {count}")
        except tk.TclError:
            pass

    def show_failures(self) -> None:
        """РџРѕРєР°Р·Р°С‚Рё СЃРїРёСЃРѕРє РїСЂРёС…РѕРІР°РЅРёС… Р·Р±РѕС—РІ Сѓ СЂРµРґР°РєС‚РѕСЂС–."""
        rows = safe.failures()
        if not rows:
            messagebox.showinfo("РџСЂРёС…РѕРІР°РЅС– Р·Р±РѕС—",
                                "Р—Р±РѕС—РІ РЅРµ Р·Р°С„С–РєСЃРѕРІР°РЅРѕ.", parent=self)
            return
        import time as _time

        lines = ["# РџСЂРёС…РѕРІР°РЅС– Р·Р±РѕС—", "",
                 f"РЈСЃСЊРѕРіРѕ: {len(rows)} (РѕСЃС‚Р°РЅРЅС– Р·РІРµСЂС…Сѓ)", ""]
        for stamp, where, kind, text in reversed(rows):
            clock = _time.strftime("%H:%M:%S", _time.localtime(stamp))
            lines.append(f"## {clock} В· {where}")
            lines.append(f"`{kind}`: {text}")
            lines.append("")
        lines.append("_РџРѕРІРЅРёР№ СЃС‚РµРє вЂ” Сѓ Р¶СѓСЂРЅР°Р»С– `ide.log`._")
        editor = self.tabs.new_file()
        editor.filename = "РїСЂРёС…РѕРІР°РЅС–-Р·Р±РѕС—.md"
        editor.set_text("\n".join(lines))
        self.tabs.rename_tab(editor, "РџСЂРёС…РѕРІР°РЅС– Р·Р±РѕС—")
        self.set_status(f"РџСЂРёС…РѕРІР°РЅРёС… Р·Р±РѕС—РІ: {len(rows)}")

    def show_log(self) -> None:
        from .config import app_data_dir

        log_file = app_data_dir() / "ide.log"
        if not log_file.exists():
            messagebox.showinfo("Р–СѓСЂРЅР°Р»", "Р–СѓСЂРЅР°Р» С‰Рµ РїРѕСЂРѕР¶РЅС–Р№.", parent=self)
            return
        self.tabs.open_file(log_file)

    # в”Ђв”Ђ СЃР°РјРѕРґС–Р°РіРЅРѕСЃС‚РёРєР° Р№ РІРёРІС–Рґ РїРѕРјРёР»РѕРє в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def run_diagnostics(self) -> None:
        """РЎР°РјРѕРґС–Р°РіРЅРѕСЃС‚РёРєР°: С‡РѕРјСѓ РјРѕРґРµР»СЊ РЅРµ РїСЂР°С†СЋС” вЂ” Р· РїСЂРёС‡РёРЅРѕСЋ Р№ РІРёРїСЂР°РІР»РµРЅРЅСЏРј.

        РЈ Р»РѕР·С– РєРѕСЂРёСЃС‚СѓРІР°С‡Р° РјРѕРґРµР»СЊ РїСЂР°С†СЋРІР°Р»Р° РЅР° 8081 (8080 С‚СЂРёРјР°РІ Steam), Р°
        РєР»С–С”РЅС‚ СЃС‚СѓРєР°РІ Сѓ 8080 вЂ” С– РІ С–РЅС‚РµСЂС„РµР№СЃС– С†Рµ Р±СѓР»Рѕ РїСЂРѕСЃС‚Рѕ В«РјРѕРґРµР»СЊ
        РЅРµРґРѕСЃС‚СѓРїРЅР°В». Р”С–Р°РіРЅРѕСЃС‚РёРєР° РїСЂРѕС…РѕРґРёС‚СЊ Р»Р°РЅС†СЋРі В«СЂСѓС€С–Р№ в†’ С„Р°Р№Р» в†’ РїРѕСЂС‚ в†’
        РєР»СЋС‡ в†’ РІС–РґРїРѕРІС–РґСЊВ» С– РїРѕРєР°Р·СѓС”, РґРµ СЃР°РјРµ РѕР±СЂРёРІ.
        """
        self.show_bottom("terminal")
        terminal = getattr(self, "terminal", None)

        def note(text: str) -> None:
            if terminal is not None:
                try:
                    terminal.write_text(text + "\n")
                    return
                except (tk.TclError, AttributeError):
                    pass
            LOG.info("%s", text)

        note("в”Ђв”Ђ РЎРђРњРћР”Р†РђР“РќРћРЎРўРРљРђ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ")
        self.set_status("РЎР°РјРѕРґС–Р°РіРЅРѕСЃС‚РёРєР°: РїРµСЂРµРІС–СЂСЏСЋ СЂСѓС€С–Р№, РїРѕСЂС‚ С– РјРѕРґРµР»СЊвЂ¦")

        def work() -> None:
            from . import diagnostics

            try:
                report = diagnostics.run(
                    settings=self.settings,
                    engine_log_tail=lambda n: self._engine_log_tail(n),
                )
            except Exception as exc:  # noqa: BLE001 - РґС–Р°РіРЅРѕСЃС‚РёРєР° РЅРµ РјР°С” РїР°РґР°С‚Рё
                self._ui_call(note, f"вњ— РґС–Р°РіРЅРѕСЃС‚РёРєР° РІРїР°Р»Р°: {exc}")
                return
            self._ui_call(self._after_diagnostics, report)

        threading.Thread(target=work, daemon=True, name="diagnostics").start()

    def _engine_log_tail(self, lines: int = 25) -> str:
        """РћСЃС‚Р°РЅРЅС– СЂСЏРґРєРё Р»РѕРіСѓ СЂСѓС€С–СЏ (``server.log``)."""
        try:
            path = runtime.runtime_dir() / "server.log"
            if not path.exists():
                return ""
            raw = path.read_text(encoding="utf-8", errors="replace")
            return "\n".join(raw.splitlines()[-max(1, int(lines)):])
        except (OSError, AttributeError):
            return ""

    def _after_diagnostics(self, report) -> None:
        """РџРѕРєР°Р·Р°С‚Рё Р·РІС–С‚ Сѓ С‚РµСЂРјС–РЅР°Р»С– Р№ РѕРЅРѕРІРёС‚Рё РІРµР»РёРєРёР№ СЃС‚Р°С‚СѓСЃ РјРѕРґРµР»С–."""
        text = report.text()
        terminal = getattr(self, "terminal", None)
        if terminal is not None:
            try:
                terminal.write_text(text + "\n")
            except (tk.TclError, AttributeError):
                LOG.info("Р”С–Р°РіРЅРѕСЃС‚РёРєР°:\n%s", text)
        else:
            LOG.info("Р”С–Р°РіРЅРѕСЃС‚РёРєР°:\n%s", text)
        # РЎС‚Р°С‚СѓСЃ Сѓ С€Р°РїС†С– вЂ” Р·Р° С„Р°РєС‚РёС‡РЅРѕСЋ РІС–РґРїРѕРІС–РґРґСЋ РјРѕРґРµР»С–.
        answered = any(item.name == "Р’С–РґРїРѕРІС–РґСЊ РјРѕРґРµР»С–" and item.ok
                       for item in report.checks)
        try:
            self.header.set_model_status(
                True if answered else False,
                detail=report.verdict[:160])
        except (tk.TclError, AttributeError):
            pass
        # РђРґСЂРµСЃР° РІ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏС… Р·Р°СЃС‚Р°СЂС–Р»Р° вЂ” РїСЂРѕРїРѕРЅСѓС”РјРѕ РІРёРїСЂР°РІРёС‚Рё РѕРґСЂР°Р·Сѓ.
        if report.working_url and not report.ok:
            from . import diagnostics as diagnostics_mod
            stale = any(item.name == "Р РѕР±РѕС‡РёР№ РїРѕСЂС‚"
                        and item.status == diagnostics_mod.WARN
                        for item in report.checks)
            if stale:
                if messagebox.askyesno(
                        "РђРґСЂРµСЃР° СЃРµСЂРІРµСЂР°",
                        f"РЈ РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏС… {self.settings.llm.base_url}, Р°Р»Рµ "
                        f"СЂРѕР±РѕС‡РёР№ СЃРµСЂРІРµСЂ РЅР° {report.working_url}.\n\n"
                        f"РџРµСЂРµРјРєРЅСѓС‚РёСЃСЊ РЅР° СЂРѕР±РѕС‡Сѓ Р°РґСЂРµСЃСѓ?",
                        parent=self):
                    self._apply_working_url(report.working_url)
                    return
        self.set_status(report.verdict[:200])

    def _apply_working_url(self, url: str) -> None:
        """Р—Р°РїРёСЃР°С‚Рё СЂРѕР±РѕС‡Сѓ Р°РґСЂРµСЃСѓ СЃРµСЂРІРµСЂР° Р№ РѕРґСЂР°Р·Сѓ РїРµСЂРµРІС–СЂРёС‚Рё С—С—."""
        if not url:
            return
        self.settings.llm.base_url = url
        self.settings.llm.api_key = runtime.MANAGED_API_KEY
        safe.call_quiet(self.settings.save, where="Р·Р±РµСЂРµР¶РµРЅРЅСЏ Р°РґСЂРµСЃРё СЃРµСЂРІРµСЂР°")
        self.agent.llm_settings = self.settings.llm
        try:
            self.header.set_model_status(True, detail=f"СЃРµСЂРІРµСЂ: {url}")
        except (tk.TclError, AttributeError):
            pass
        self.set_status(f"РђРґСЂРµСЃСѓ СЃРµСЂРІРµСЂР° РІРёРїСЂР°РІР»РµРЅРѕ: {url}")
        terminal = getattr(self, "terminal", None)
        if terminal is not None:
            try:
                terminal.write_text(f"вњ“ Р°РґСЂРµСЃСѓ СЃРµСЂРІРµСЂР° РІРёРїСЂР°РІР»РµРЅРѕ: {url}\n")
            except (tk.TclError, AttributeError):
                pass
        self._on_model_changed()
        self.probe_providers(silent=True)

    def _on_model_status_click(self) -> None:
        """РљР»С–Рє РїРѕ РІРµР»РёРєРѕРјСѓ СЃС‚Р°С‚СѓСЃСѓ РјРѕРґРµР»С– в†’ СЃР°РјРѕРґС–Р°РіРЅРѕСЃС‚РёРєР°."""
        self.run_diagnostics()

    def show_shortcuts(self) -> None:
        text = (
            "Р“РђР РЇР§Р† РљР›РђР’Р†РЁР†\n\n"
            "Ctrl+N          РЅРѕРІРёР№ С„Р°Р№Р»\n"
            "Ctrl+O          РІС–РґРєСЂРёС‚Рё С„Р°Р№Р»\n"
            "Ctrl+S          Р·Р±РµСЂРµРіС‚Рё\n"
            "Ctrl+Shift+S    Р·Р±РµСЂРµРіС‚Рё СЏРє\n"
            "Ctrl+W          Р·Р°РєСЂРёС‚Рё РІРєР»Р°РґРєСѓ\n"
            "Ctrl+P          С€РІРёРґРєРµ РІС–РґРєСЂРёС‚С‚СЏ С„Р°Р№Р»Сѓ\n"
            "Ctrl+Shift+P    РєРѕРјР°РЅРґРЅР° РїР°Р»С–С‚СЂР°\n"
            "Ctrl+F          РїРѕС€СѓРє Сѓ С„Р°Р№Р»С–\n"
            "Ctrl+Shift+F    РїРѕС€СѓРє Сѓ РїСЂРѕС”РєС‚С–\n"
            "Ctrl+G          РїРµСЂРµР№С‚Рё РґРѕ СЂСЏРґРєР°\n"
            "Ctrl+/          РєРѕРјРµРЅС‚СѓРІР°С‚Рё СЂСЏРґРѕРє\n"
            "Ctrl+D          РґСѓР±Р»СЋРІР°С‚Рё СЂСЏРґРѕРє\n"
            "Ctrl+B          Р±С–С‡РЅР° РїР°РЅРµР»СЊ\n"
            "Ctrl+Alt+B      РїР°РЅРµР»СЊ Р°РіРµРЅС‚Р°\n"
            "Ctrl+Alt+K      СЃРєС–Р»Рё Р°РіРµРЅС‚Р°\n"
            "Ctrl+Alt+Q      С‡РµСЂРіР° Р·Р°РІРґР°РЅСЊ\n"
            "Ctrl+`          С‚РµСЂРјС–РЅР°Р»\n"
            "Ctrl+C          РїРµСЂРµСЂРІР°С‚Рё РєРѕРјР°РЅРґСѓ РІ С‚РµСЂРјС–РЅР°Р»С–\n"
            "Ctrl+= / Ctrl+- СЂРѕР·РјС–СЂ С€СЂРёС„С‚Сѓ\n"
            "Ctrl+Alt+Enter  РЅР°РґС–СЃР»Р°С‚Рё С„Р°Р№Р» Р°РіРµРЅС‚Сѓ\n"
            "F5              Р·Р°РїСѓСЃС‚РёС‚Рё С„Р°Р№Р»\n"
            "Ctrl+F5         Р·Р°РїСѓСЃС‚РёС‚Рё С‚РµСЃС‚Рё\n"
            "Ctrl+,          РЅР°Р»Р°С€С‚СѓРІР°РЅРЅСЏ\n"
        )
        messagebox.showinfo(APP_NAME, text, parent=self)

    def show_about(self) -> None:
        messagebox.showinfo(
            "РџСЂРѕ РїСЂРѕРіСЂР°РјСѓ",
            f"{APP_NAME} {APP_VERSION}\n\n"
            "Р›РѕРєР°Р»СЊРЅР° IDE Р· Р°РіРµРЅС‚РѕРј Сѓ СЃС‚РёР»С– СЃСѓС‡Р°СЃРЅРѕРіРѕ Р°РіРµРЅС‚РЅРѕРіРѕ СЂРµРґР°РєС‚РѕСЂР°.\n"
            "РњРѕРґРµР»СЊ: Р±СѓРґСЊ-СЏРєРёР№ OpenAI-СЃСѓРјС–СЃРЅРёР№ СЃРµСЂРІРµСЂ (LM Studio, Ollama, llama.cpp).\n"
            "Р‘РµР· РјРѕРґРµР»С– РїСЂР°С†СЋС” РІР±СѓРґРѕРІР°РЅРёР№ РѕС„Р»Р°Р№РЅ-СЂРѕСѓС‚РµСЂ С–РЅСЃС‚СЂСѓРјРµРЅС‚С–РІ.\n\n"
            f"Р РѕР±РѕС‡Р° С‚РµРєР°: {self.settings.workspace}\n"
            f"РќР°Р»Р°С€С‚СѓРІР°РЅРЅСЏ: {self.settings.save()}\n",
            parent=self,
        )

    # в”Ђв”Ђ РєРѕСЂРµРєС‚РЅРµ Р·Р°РєСЂРёС‚С‚СЏ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    def _release_model_now(self) -> None:
        """Р—РІС–Р»СЊРЅРёС‚Рё РІС–РґРµРѕРїР°Рј'СЏС‚СЊ: Р·СѓРїРёРЅРёС‚Рё РІСЃС– СЂСѓС€С–С—, СЏРєРёРјРё РєРµСЂСѓС” IDE.

        Р¦Рµ РѕРєСЂРµРјРёР№ РјРµС‚РѕРґ, Р° РЅРµ С‡Р°СЃС‚РёРЅР° ``on_close``, Р±Рѕ Р№РѕРіРѕ С‚СЂРµР±Р° РІРёРєР»РёРєР°С‚Рё
        Р· РєС–Р»СЊРєРѕС… РјС–СЃС†СЊ: РїС–Рґ С‡Р°СЃ Р·Р°РєСЂРёС‚С‚СЏ РІС–РєРЅР°, РІ Р°РІР°СЂС–Р№РЅРѕРјСѓ РѕР±СЂРѕР±РЅРёРєСѓ
        (``atexit``) С– РїСЂРё РІРёС…РѕРґС– Р· РїРѕРјРёР»РєРѕСЋ. Р†РґРµРјРїРѕС‚РµРЅС‚РЅРёР№: РїРѕРІС‚РѕСЂРЅРёР№ РІРёРєР»РёРє
        Р±РµР·РїРµС‡РЅРёР№.

        Р©Рѕ Р·СѓРїРёРЅСЏС”РјРѕ:
        1. РєРµСЂРѕРІР°РЅРёР№ ``llama-server`` (``_managed_server``);
        2. СЃРµСЂРІРµСЂ С–Р· С…Р°Р±Р° РјРѕРґРµР»РµР№ (``model_hub.server``);
        3. РІР»Р°СЃРЅРёР№ РІР±СѓРґРѕРІР°РЅРёР№ СЂСѓС€С–Р№ (``native_runtime``);
        4. Р±СѓРґСЊ-СЏРєС– Р·Р°Р»РёС€РєРѕРІС– СЂСѓС€С–С—, Р·Р°РїРёСЃР°РЅС– Сѓ С„Р°Р№Р» PID.
        """
        released = False
        # 1. РљРµСЂРѕРІР°РЅРёР№ СЃРµСЂРІРµСЂ.
        server = getattr(self, "_managed_server", None)
        if server is not None:
            try:
                server.stop()
                released = True
            except Exception:  # noqa: BLE001 - Р·Р°РєСЂРёС‚С‚СЏ РЅРµ РјР°С” РїР°РґР°С‚Рё
                LOG.debug("РљРµСЂРѕРІР°РЅРёР№ СЃРµСЂРІРµСЂ РЅРµ Р·СѓРїРёРЅРёРІСЃСЏ", exc_info=True)
            self._managed_server = None
        # 2. РЎРµСЂРІРµСЂ С–Р· РїР°РЅРµР»С– С…Р°Р±Р°.
        try:
            hub_server = getattr(self.model_hub, "server", None)
            if hub_server is not None:
                hub_server.stop()
                self.model_hub.server = None
                released = True
        except Exception:  # noqa: BLE001
            LOG.debug("РЎРµСЂРІРµСЂ С…Р°Р±Р° РЅРµ Р·СѓРїРёРЅРёРІСЃСЏ", exc_info=True)
        # 3. Р’Р»Р°СЃРЅРёР№ СЂСѓС€С–Р№ Сѓ РїСЂРѕС†РµСЃС–.
        try:
            self.native_runtime.shut_down()
            released = True
        except Exception:  # noqa: BLE001
            LOG.debug("Р’Р»Р°СЃРЅРёР№ СЂСѓС€С–Р№ РЅРµ РІРёРІР°РЅС‚Р°Р¶РёРІСЃСЏ", exc_info=True)
        # 4. Р—Р°Р»РёС€РєРѕРІС– РїСЂРѕС†РµСЃРё РІС–Рґ РїРѕРїРµСЂРµРґРЅС–С… Р·Р°РїСѓСЃРєС–РІ.
        try:
            removed = runtime.cleanup_stale_processes()
            if removed:
                LOG.info("РџСЂРёР±СЂР°РЅРѕ Р·Р°Р»РёС€РєРѕРІРёС… СЂСѓС€С–С—РІ: %s", removed)
                released = True
        except Exception:  # noqa: BLE001
            LOG.debug("РџСЂРёР±РёСЂР°РЅРЅСЏ Р·Р°Р»РёС€РєРѕРІРёС… РїСЂРѕС†РµСЃС–РІ РЅРµ РІРґР°Р»РѕСЃСЊ", exc_info=True)
        if released:
            LOG.info("Р’С–РґРµРѕРїР°Рј'СЏС‚СЊ Р·РІС–Р»СЊРЅРµРЅРѕ: СЂСѓС€С–С— IDE Р·СѓРїРёРЅРµРЅРѕ.")
        return None

    def _editor_event(self, sequence: str) -> None:
        editor = self.tabs.current()
        if not editor:
            return
        try:
            editor.text.event_generate(sequence)
        except tk.TclError:
            pass

    def on_close(self) -> None:
        """Закрити застосунок рівно один раз.

        ``on_close`` викликається і кнопкою «×», і пунктом меню, і
        ``atexit``, і тестами. Другий виклик раніше падав з
        ``TclError: cannot invoke "destroy" command: application has been
        destroyed`` — бо вікно вже знищене, а ми знову чіпаємо Tk. Тепер
        повторний вхід тихо виходить.
        """
        if getattr(self, "_closing", False):
            return
        self._closing = True
        self._remember_layout()
        # РљРѕРЅС‚РµРєСЃС‚ Р°РєС‚РёРІРЅРѕС— СЂРѕР·РјРѕРІРё Р·Р±РµСЂС–РіР°С”РјРѕ РЅР° РґРёСЃРє: С–РЅР°РєС€Рµ РїС–СЃР»СЏ
        # РїРµСЂРµР·Р°РїСѓСЃРєСѓ С‡Р°С‚ РІС–РґРєСЂРёРІР°РІСЃСЏ Р± С–Р· РїРѕРІС–РґРѕРјР»РµРЅРЅСЏРјРё, Р°Р»Рµ Р°РіРµРЅС‚ РЅРµ
        # РїР°Рј'СЏС‚Р°РІ Р±Рё Р¶РѕРґРЅРѕРіРѕ РєСЂРѕРєСѓ РїРѕРїРµСЂРµРґРЅСЊРѕС— СЂРѕР±РѕС‚Рё.
        try:
            self._save_chat_context(self._active_chat_id())
        except Exception:  # noqa: BLE001 - Р·Р°РєСЂРёС‚С‚СЏ РЅРµ РјР°С” РїР°РґР°С‚Рё
            LOG.debug("РљРѕРЅС‚РµРєСЃС‚ С‡Р°С‚Сѓ РЅРµ Р·Р±РµСЂРµР¶РµРЅРѕ", exc_info=True)
        # РђРІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј РјР°С” Р·Р°РІРµСЂС€РёС‚РёСЃСЊ РєРѕСЂРµРєС‚РЅРѕ: С„Р°Р№Р» РґРѕРїРёСЃСѓС”С‚СЊСЃСЏ Р№
        # Р·Р±РµСЂС–РіР°С”С‚СЊСЃСЏ, Р·Р°РґР°С‡С– Р°РіРµРЅС‚Р° Р·РЅС–РјР°СЋС‚СЊСЃСЏ Р· С‡РµСЂРіРё. Р†РЅР°РєС€Рµ РЅР°СЃС‚СѓРїРЅРёР№
        # Р·Р°РїСѓСЃРє РїРѕС‡РёРЅР°РІСЃСЏ Р± С–Р· В«РѕР±С–СЂРІР°РЅРѕС—В» РїСЂР°РІРєРё.
        try:
            if self.autonomous_engine.active:
                self._save_all_silently()
                self.autonomous_engine.confirm_stop(
                    reason="РђРІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј РІРёРјРєРЅРµРЅРѕ СЂР°Р·РѕРј С–Р· Р·Р°СЃС‚РѕСЃСѓРЅРєРѕРј.")
        except Exception:  # noqa: BLE001 - Р·Р°РєСЂРёС‚С‚СЏ РЅРµ РјР°С” РїР°РґР°С‚Рё
            LOG.debug("РќРµ РІРґР°Р»РѕСЃСЊ РєРѕСЂРµРєС‚РЅРѕ Р·Р°РІРµСЂС€РёС‚Рё Р°РІС‚РѕРЅРѕРјРЅРёР№ СЂРµР¶РёРј", exc_info=True)
        try:
            self.autonomous_engine.queue.save()
        except Exception:  # noqa: BLE001
            pass
        # Р’РёРєРѕРЅР°РІРµС†СЊ РїР»Р°РЅСѓ РјР°С” Р»РёС€РёС‚Рё С‡РµСЂРіСѓ РІ СѓР·РіРѕРґР¶РµРЅРѕРјСѓ СЃС‚Р°РЅС–: Р°РєС‚РёРІРЅРёР№
        # РєСЂРѕРє СЃС‚Р°С” В«РїСЂРёР·СѓРїРёРЅРµРЅРѕВ», Р° РЅРµ В«РІРёСЃРёС‚СЊВ» Сѓ queue.json. РџС–СЃР»СЏ
        # РЅР°СЃС‚СѓРїРЅРѕРіРѕ Р·Р°РїСѓСЃРєСѓ РєРѕСЂРёСЃС‚СѓРІР°С‡ РЅР°С‚РёСЃРЅРµ В«РџСЂРѕРґРѕРІР¶РёС‚РёВ» Р№ РїС–РґРµ РґР°Р»С–.
        try:
            if self.executor.current is not None:
                self.executor.stop(reason="IDE Р·Р°РєСЂРёС‚Рѕ РїС–Рґ С‡Р°СЃ РІРёРєРѕРЅР°РЅРЅСЏ РєСЂРѕРєСѓ")
            else:
                self.task_queue.save()
        except Exception:  # noqa: BLE001 - Р·Р°РєСЂРёС‚С‚СЏ РЅРµ РјР°С” РїР°РґР°С‚Рё
            LOG.debug("Р§РµСЂРіСѓ РЅРµ РІРґР°Р»РѕСЃСЊ Р·Р±РµСЂРµРіС‚Рё РїС–Рґ С‡Р°СЃ Р·Р°РєСЂРёС‚С‚СЏ", exc_info=True)
        try:
            self.live_preview.on_close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.app.on_close()
        except Exception:  # noqa: BLE001
            pass
        # Р’Р»Р°СЃРЅРёР№ СЂСѓС€С–Р№: РјРѕРґРµР»СЊ РјР°С” Р±СѓС‚Рё РІРёРІР°РЅС‚Р°Р¶РµРЅР°, С–РЅР°РєС€Рµ РїСЂРѕС†РµСЃ
        # Р·Р°РІРёСЃР°С” РЅР° Р·Р°РєСЂРёС‚С‚С–, С‚СЂРёРјР°СЋС‡Рё РіС–РіР°Р±Р°Р№С‚Рё VRAM.
        #
        # РќР°Р»Р°С€С‚СѓРІР°РЅРЅСЏ ``engine.native_unload_on_exit`` Р РђРќР†РЁР• Р·Р±РµСЂС–РіР°Р»РѕСЃСЊ,
        # Р°Р»Рµ РЅС–РґРµ РЅРµ С‡РёС‚Р°Р»РѕСЃСЊ: РІРёРІР°РЅС‚Р°Р¶РµРЅРЅСЏ Р±СѓР»Рѕ Р±РµР·СѓРјРѕРІРЅРёРј. РўРµРїРµСЂ Р№РѕРіРѕ
        # РїРѕРІР°Р¶Р°С”РјРѕ вЂ” РІРѕРЅРѕ РїРѕС‚СЂС–Р±РЅРµ С‚РёРј, С…С‚Рѕ С‚СЂРёРјР°С” РјРѕРґРµР»СЊ В«С‚РµРїР»РѕСЋВ» РјС–Р¶
        # Р·Р°РїСѓСЃРєР°РјРё (РѕРєСЂРµРјРёР№ СЂСѓС€С–Р№ Р»РёС€Р°С”С‚СЊСЃСЏ Р¶РёРІРёРј).
        if getattr(self.settings.engine, "native_unload_on_exit", True):
            try:
                self.native_runtime.shut_down()
            except Exception:  # noqa: BLE001
                LOG.debug("Р СѓС€С–Р№ РЅРµ РІРёРІР°РЅС‚Р°Р¶РёРІСЃСЏ РїСЂРё Р·Р°РєСЂРёС‚С‚С–", exc_info=True)
        else:
            LOG.info("РњРѕРґРµР»СЊ Р»РёС€РµРЅР° Р·Р°РІР°РЅС‚Р°Р¶РµРЅРѕСЋ (native_unload_on_exit=False)")
        try:
            if self.memory is not None:
                self.memory.close()
        except Exception:  # noqa: BLE001
            LOG.debug("РџР°Рј'СЏС‚СЊ РЅРµ Р·Р°РєСЂРёР»Р°СЃСЊ РєРѕСЂРµРєС‚РЅРѕ", exc_info=True)
        # РЎРєР°СЃСѓРІР°С‚Рё РІС–РґРєР»Р°РґРµРЅС– С†РёРєР»Рё, С‰РѕР± РЅРµ СЃРёРїР°Р»РёСЃСЊ В«invalid command nameВ».
        for job in (self._ui_after, self._queue_pump_after, self._resize_after,
                    self._probe_after, self._idle_after, self._autonomous_after):
            if job:
                try:
                    self.after_cancel(job)
                except (tk.TclError, ValueError):
                    pass
        # Р’С–РґРєР»Р°РґРµРЅС– РїРµСЂРµСЂР°С…СѓРЅРєРё СЃР°С€С–РІ: РІРѕРЅРё РїР»Р°РЅСѓСЋС‚СЊСЃСЏ РЅР° 60/240/600 РјСЃ С–
        # РЅР° СЃРµСЂС–СЋ РїРѕРІС‚РѕСЂС–РІ, С‚РѕР¶ Р±РµР· С†СЊРѕРіРѕ С†РёРєР»Сѓ Tk РґСЂСѓРєСѓРІР°РІ
        # В«invalid command name ..._apply_sash_positionsВ» СѓР¶Рµ РїС–СЃР»СЏ destroy.
        for job in list(getattr(self, "_sash_jobs", [])):
            try:
                self.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
        self._sash_jobs = []
        if self._probe is not None:
            try:
                self._probe.cancel()
            except Exception:  # noqa: BLE001
                pass
        for card in (self._model_selector, self._mode_menu):
            if card is not None:
                try:
                    card.destroy()
                except tk.TclError:
                    pass
        # ``cancel_probe`` Р¶РёРІРµ РІ ``chat_panel.ModelBar``, Р° ``ModelBar``
        # РЅС–РґРµ РЅРµ СЃС‚РІРѕСЂСЋС”С‚СЊСЃСЏ вЂ” С‚РѕР±С‚Рѕ РЅР° ``ChatPanel`` С‚Р°РєРѕРіРѕ РјРµС‚РѕРґСѓ РЅРµРјР°С”
        # (РїРµСЂРµРІС–СЂРµРЅРѕ: ``hasattr(ChatPanel, "cancel_probe") is False``).
        # Р’РёРєР»РёРє С‡РµСЂРµР· getattr Р±СѓРІ РіР°СЂР°РЅС‚РѕРІР°РЅРёРј no-op. РЁСѓРєР°С”РјРѕ РјРµС‚РѕРґ С‚Р°Рј,
        # РґРµ РІС–РЅ СЃРїСЂР°РІРґС– С”: СЃРїРµСЂС€Сѓ РІ РїР°РЅРµР»С–, РїРѕС‚С–Рј Сѓ С—С— СЂСЏРґРєСѓ РјРѕРґРµР»С–.
        for owner in (self.chat, getattr(self.chat, "model_bar", None),
                      getattr(self, "model_bar", None)):
            cancel = getattr(owner, "cancel_probe", None) if owner is not None else None
            if cancel is not None:
                try:
                    cancel()
                except (tk.TclError, AttributeError, RuntimeError):
                    pass
                break
        # Р—СѓРїРёРЅРёС‚Рё СЃРїС–РЅРµСЂ С– С‚Р°Р№РјРµСЂРё С‡Р°С‚Сѓ.
        try:
            stop_spin = getattr(self.chat, "_stop_spinner", None)
            if stop_spin is not None:
                stop_spin()
            cancel_events = getattr(self.chat, "cancel_events", None)
            if cancel_events is not None:
                cancel_events()
        except Exception:  # noqa: BLE001
            pass
        # РўР°Р№РјРµСЂРё РїР°РЅРµР»РµР№: Сѓ РєРѕР¶РЅРѕС— РІР»Р°СЃРЅР° РЅР°Р·РІР° РїРѕР»СЏ (_after, _drain_job,
        # _poll_jobвЂ¦). Р‘РµР· С†СЊРѕРіРѕ Р·Р°РїР»Р°РЅРѕРІР°РЅС– РІРёРєР»РёРєРё Р»РёС€Р°СЋС‚СЊСЃСЏ РІ Tcl С–
        # СЃРїСЂР°С†СЊРѕРІСѓСЋС‚СЊ РџР†РЎР›РЇ destroy вЂ” Tk РґСЂСѓРєСѓС” В«invalid command nameВ»
        # С– Р·Р°РєСЂРёС‚С‚СЏ РїР°РґР°С” Р· В«application has been destroyedВ». РЎР°РјРµ С‚Р°Рє
        # РїР°РґР°РІ tests/live_every_button.py: 77 РЅР°С‚РёСЃРєР°РЅСЊ РїСЂРѕС…РѕРґРёР»Рё, Р°
        # Р·Р°РєСЂРёС‚С‚СЏ Р»Р°РјР°Р»РѕСЃСЊ.
        cancelled = 0
        for widget in list(getattr(self, "_side_widgets", {}).values()) + [
                self.chat, self.chat.stage_strip, self.chat.queue_strip,
                self.terminal, self.context]:
            try:
                cancelled += widgets.cancel_after(widget)
            except Exception:  # noqa: BLE001 - Р·РЅСЏС‚С‚СЏ С‚Р°Р№РјРµСЂР° РЅРµ РјР°С” РІР°Р»РёС‚Рё РІРёС…С–Рґ
                LOG.debug("РќРµ РІРґР°Р»РѕСЃСЊ Р·РЅСЏС‚Рё С‚Р°Р№РјРµСЂ РІС–РґР¶РµС‚Р°", exc_info=True)
        if cancelled:
            LOG.debug("Р—РЅСЏС‚Рѕ С‚Р°Р№РјРµСЂС–РІ РїР°РЅРµР»РµР№: %s", cancelled)
        # Р—СѓРїРёРЅРёС‚Рё СЃРїС–Р»СЊРЅРёР№ С‚С–РєРµСЂ Р°РЅС–РјР°С†С–С— В«РЎРїСЂР°РІВ» вЂ” С–РЅР°РєС€Рµ РїС–СЃР»СЏ Р·Р°РєСЂРёС‚С‚СЏ
        # РІС–РєРЅР° Р»РёС€Р°С”С‚СЊСЃСЏ С‚Р°Р№РјРµСЂ, С‰Рѕ СЃРјРёРєР°С” Р·РЅРёС‰РµРЅС– РІС–РґР¶РµС‚Рё.
        try:
            pulse.forget_ticker(self)
        except Exception:  # noqa: BLE001
            pass
        if not self.tabs.close_all():
            # РљРѕСЂРёСЃС‚СѓРІР°С‡ РІС–РґРјРѕРІРёРІСЃСЏ Р·Р°РєСЂРёРІР°С‚Рё РЅРµР·Р±РµСЂРµР¶РµРЅС– С„Р°Р№Р»Рё вЂ” РІС–РєРЅРѕ
            # Р»РёС€Р°С”С‚СЊСЃСЏ. РњРѕРґРµР»СЊ РќР• Р·СѓРїРёРЅСЏС”РјРѕ: СЂРѕР±РѕС‚Р° РїСЂРѕРґРѕРІР¶СѓС”С‚СЊСЃСЏ. РђР»Рµ
            # СЏРєС‰Рѕ РІС–РЅ СѓСЃРµ Р¶ Р·Р°РєСЂРёС” РїСЂРѕРіСЂР°РјСѓ С–РЅР°РєС€Рµ (РґРёСЃРїРµС‚С‡РµСЂ Р·Р°РґР°С‡),
            # СЃРїСЂР°С†СЋС” ``atexit``-С…СѓРє, Р·Р°СЂРµС”СЃС‚СЂРѕРІР°РЅРёР№ Сѓ РєРѕРЅСЃС‚СЂСѓРєС‚РѕСЂС–.
            return
        # в”Ђв”Ђ Р’Р†Р”Р•РћРљРђР РўРђ вЂ” РџР•Р РЁРРњ Р”Р†Р›РћРњ в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
        #
        # РќР°РІС–С‰Рѕ СЃР°РјРµ С‚СѓС‚. ``llama-server`` С‚СЂРёРјР°С” 8вЂ“11 Р“Р‘ VRAM. РЇРєС‰Рѕ Р№РѕРіРѕ РЅРµ
        # Р·СѓРїРёРЅРёС‚Рё, РєРѕСЂРёСЃС‚СѓРІР°С‡ Р·Р°РєСЂРёРІР°С” IDE, Р° РІС–РґРµРѕРєР°СЂС‚Р° Р»РёС€Р°С”С‚СЊСЃСЏ Р·Р°Р№РЅСЏС‚РѕСЋ:
        # С–РіСЂРё РЅРµ Р·Р°РїСѓСЃРєР°СЋС‚СЊСЃСЏ (В«С‰РѕСЃСЊ РіСЂСѓР·РёС‚СЊ РІС–РґРµРѕРєР°СЂС‚СѓВ»).
        #
        # Р Р°РЅС–С€Рµ Р·СѓРїРёРЅРєР° СЃС‚РѕСЏР»Р° РІ РєС–РЅС†С– ``on_close`` С– РјРѕРіР»Р° РќР• Р’РРљРћРќРђРўРРЎР¬:
        # Р±СѓРґСЊ-СЏРєРёР№ РІРёРЅСЏС‚РѕРє РІРёС‰Рµ (Р° С—С… С‚СѓС‚ РґРµСЃСЏС‚РєРё, РєРѕР¶РµРЅ Сѓ СЃРІРѕС”РјСѓ try) Р°Р±Рѕ
        # РґРѕСЃС‚СЂРѕРєРѕРІРёР№ ``return`` Р»РёС€Р°РІ РїСЂРѕС†РµСЃ Р¶РёРІРёРј. РўРµРїРµСЂ Р·РІС–Р»СЊРЅСЏС”РјРѕ РїР°Рј'СЏС‚СЊ
        # РґРѕ Р·Р±РµСЂРµР¶РµРЅРЅСЏ СЃС‚Р°РЅСѓ: РЅР°РІС–С‚СЊ СЏРєС‰Рѕ РїРѕРґР°Р»СЊС€Рµ Р·Р°РєСЂРёС‚С‚СЏ РІРїР°РґРµ, VRAM СѓР¶Рµ
        # РІС–Р»СЊРЅР°.
        self._release_model_now()
        save_session({"tabs": [str(p) for p in self.tabs.all_paths()]})
        self.settings.save()
        self.task_queue.save()
        try:
            self.agent.cancel()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.terminal.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            # РќР°РіР»СЏРґР°С‡ РјР°С” СЃРїРёРЅРёС‚РёСЃСЊ Р”Рћ Р·СѓРїРёРЅРєРё СЃРµСЂРІРµСЂС–РІ: С–РЅР°РєС€Рµ РІС–РЅ
            # РїРѕР±Р°С‡РёС‚СЊ РјРµСЂС‚РІС– СЃРµСЂРІРµСЂРё Р№ РїРѕС‡РЅРµ С—С… РїРµСЂРµР·Р°РїСѓСЃРєР°С‚Рё РїС–Рґ С‡Р°СЃ РІРёС…РѕРґСѓ.
            self.mcp_watcher.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            threading.Thread(target=self.mcp_manager.stop_all, daemon=True).start()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.model_hub.on_close()
            if self.model_hub.server is not None:
                self.model_hub.server.stop()
        except Exception:  # noqa: BLE001
            pass
        # РќРµ Р»РёС€Р°С”РјРѕ В«СЃРёСЂС–С‚СЃСЊРєРёР№В» llama-server, СЏРєРёР№ С‚СЂРёРјР°С” РіС–РіР°Р±Р°Р№С‚Рё РІ РїР°Рј'СЏС‚С–.
        # (РћСЃРЅРѕРІРЅРµ Р·РІС–Р»СЊРЅРµРЅРЅСЏ РІР¶Рµ РІС–РґР±СѓР»РѕСЃСЊ РЅР° РїРѕС‡Р°С‚РєСѓ вЂ” ``_release_model_now``;
        # С‚СѓС‚ РїРѕРІС‚РѕСЂРЅР°, С–РґРµРјРїРѕС‚РµРЅС‚РЅР° СЃРїСЂРѕР±Р°, СЏРєС‰Рѕ С‰РѕСЃСЊ РїС–РґРЅСЏР»РѕСЃСЊ Р·Р°РЅРѕРІРѕ.)
        self._release_model_now()
        if self._queue_pump_after is not None:
            try:
                self.after_cancel(self._queue_pump_after)
            except (tk.TclError, ValueError):
                pass
        try:
            self.destroy()
        except tk.TclError:
            # Вікно вже знищене (подвійний закрив, закриття з atexit).
            LOG.debug("Вікно вже знищене до destroy()")


def launch(settings: Settings) -> int:
    """Р—Р°РїСѓСЃС‚РёС‚Рё Р·Р°СЃС‚РѕСЃСѓРЅРѕРє С– РїРѕРІРµСЂРЅСѓС‚Рё РєРѕРґ РІРёС…РѕРґСѓ."""
    app = BlackChpokIDE(settings)
    app.mainloop()
    return 0
