# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_all

ROOT = Path(SPECPATH).resolve()

hiddenimports = [
    "tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox",
    "tkinter.simpledialog", "tkinter.font",
    "sqlite3", "urllib.request", "urllib.error", "urllib.parse",
    "json", "queue", "threading", "subprocess", "zipfile",
    "webbrowser", "ctypes", "ctypes.wintypes", "shutil", "concurrent.futures",
    "pygments", "pygments.lexers", "pygments.styles",
]

if sys.platform == "win32":
    hiddenimports.append("winreg")

for optional in ("vibe_router", "rag_engine", "agent_tools", "night_shift", "PIL", "numpy", "webview"):
    try:
        __import__(optional)
        hiddenimports.append(optional)
    except Exception:
        pass

hiddenimports += collect_submodules("blackchpok_ide")

datas = []
for folder_name in ("assets", "skills", "docs"):
    src_dir = ROOT / folder_name
    if src_dir.is_dir():
        datas.append((str(src_dir), folder_name))

for root_file in ("README.md", "README_UK.md", "agent_tools.py", "rag_engine.py", "night_shift.py"):
    rf = ROOT / root_file
    if rf.is_file():
        datas.append((str(rf), "."))

binaries = []
for pkg in ("PIL", "pygments"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

excludes = [
    "matplotlib", "scipy", "PySide6", "PyQt5", "PyQt6",
    "playwright", "pymupdf", "fitz", "pikepdf", "pypdf", "docx",
    "pytest", "IPython", "notebook",
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
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
    [],
    exclude_binaries=True,
    name="BlackChpok",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "icon.ico") if (ROOT / "assets" / "icon.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="BlackChpok",
)
