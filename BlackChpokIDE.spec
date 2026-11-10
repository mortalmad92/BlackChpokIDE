# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec для BlackChpok IDE.

Збірка:      pyinstaller --noconfirm --clean BlackChpokIDE.spec
Або:         build_exe.bat
Результат:   dist/BlackChpok.exe   (один файл, без консолі)
"""

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve()

# Модулі, які агент імпортує динамічно або через рядки
hiddenimports = [
    "tkinter",
    "tkinter.ttk",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinter.simpledialog",
    "tkinter.font",
    "blackchpok_ide",
    "blackchpok_ide.agent",
    "blackchpok_ide.agent_tools",
    "blackchpok_ide.app_control",
    "blackchpok_ide.chat_panel",
    "blackchpok_ide.config",
    "blackchpok_ide.ast_index",
    "blackchpok_ide.cloud_agents",
    "blackchpok_ide.command_menu",
    "blackchpok_ide.effort",
    "blackchpok_ide.context_panel",
    "blackchpok_ide.conversation",
    "blackchpok_ide.layout",
    "blackchpok_ide.live_preview",
    "blackchpok_ide.model_caps",
    "blackchpok_ide.model_menu",
    "blackchpok_ide.intent_engine",
    "blackchpok_ide.memory_bridge",
    "blackchpok_ide.message_parts",
    "blackchpok_ide.model_profile",
    "blackchpok_ide.planning",
    "blackchpok_ide.response_engine",
    "blackchpok_ide.tool_orchestrator",
    "blackchpok_ide.tool_specs",
    "blackchpok_ide.trace_store",
    "blackchpok_ide.browser_panel",
    "blackchpok_ide.preview_panel",
    "blackchpok_ide.pulse",
    "blackchpok_ide.chat_list_panel",
    "blackchpok_ide.work_log",
    "blackchpok_ide.voice",
    "blackchpok_ide.web_server",
    "blackchpok_ide.voice_panel",
    "blackchpok_ide.permissions",
    "blackchpok_ide.social",
    "blackchpok_ide.slash_commands",
    "blackchpok_ide.tool_router",
    "blackchpok_ide.editor",
    "blackchpok_ide.file_tree",
    "blackchpok_ide.first_run",
    "blackchpok_ide.hardware",
    "blackchpok_ide.llm_client",
    "blackchpok_ide.main_window",
    "blackchpok_ide.markdown_view",
    "blackchpok_ide.mcp_client",
    "blackchpok_ide.mcp_panel",
    "blackchpok_ide.model_hub",
    "blackchpok_ide.model_hub_panel",
    "blackchpok_ide.offline",
    "blackchpok_ide.outline_panel",
    "blackchpok_ide.palette",
    "blackchpok_ide.queue_engine",
    "blackchpok_ide.queue_panel",
    "blackchpok_ide.runtime",
    "blackchpok_ide.settings_dialog",
    "blackchpok_ide.shell_session",
    "blackchpok_ide.skills",
    "blackchpok_ide.skills_panel",
    "blackchpok_ide.syntax",
    "blackchpok_ide.tabs",
    "blackchpok_ide.terminal",
    "blackchpok_ide.theme",
    "blackchpok_ide.widgets",
    "blackchpok_ide.workspace",
    "ast",
    "py_compile",
    "sqlite3",
    "urllib.request",
    "urllib.error",
    "urllib.parse",
    "json",
    "queue",
    "threading",
    "subprocess",
    "zipfile",
    "webbrowser",
    "ctypes",
    "shutil",
    "concurrent.futures",
    # живий термінал завершує нащадків через WinAPI
    "ctypes.wintypes",
]

# Модулі Windows, які імпортуються лише за потреби
if sys.platform == "win32":
    hiddenimports.append("winreg")

# Необов'язкові модулі репозиторію: якщо є — підключаємо, нема — пропускаємо
for optional in ("vibe_router", "rag_engine", "agent_tools", "night_shift"):
    try:
        __import__(optional)
        hiddenimports.append(optional)
    except Exception:
        pass

hiddenimports += collect_submodules("blackchpok_ide")

datas = [
    (str(ROOT / "assets" / "icon.ico"), "assets"),
    (str(ROOT / "assets" / "icon.png"), "assets"),
    (str(ROOT / "README_UK.md"), "."),
]
datas = [(src, dst) for src, dst in datas if Path(src).exists()]

excludes = [
    "numpy", "pandas", "matplotlib", "scipy", "PySide6", "PyQt5", "PyQt6",
    "playwright", "pymupdf", "fitz", "pikepdf", "pypdf", "docx", "PIL.ImageQt",
    "pytest", "IPython", "notebook", "setuptools", "distutils",
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="BlackChpok",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "icon.ico") if (ROOT / "assets" / "icon.ico").exists() else None,
    version=None,
)
