# BlackChpok IDE 3.0.0

**English** | [Українська](README_UK.md)

**Local Autonomous AI Development Environment (2026)** powered by hybrid intelligence (`Local LLM + Cloud Gemini`), long-term **NEUROMESH** memory, built-in **Live Preview** browser, and cross-platform support for **Windows and Linux**.

---

## Key Features

- **Hybrid Coding Pipeline (`NEUROMESH -> Gemini Architect 2026 -> Local Coder`)**: Run GGUF models locally (`llama.cpp` / CUDA / Vulkan / CPU) while leveraging Google Gemini for architectural planning.
- **Infinite Session & Auto-Compaction (`NEUROMESH + RAG`)**: Automatically frees context window space and archives completed steps into long-term project memory.
- **Autonomous & Night Shift Modes**: Self-directed project analysis, idea generation (local, Gemini, or web), task queue control, and incremental code evolution.
- **Built-in `Live Preview` & CLI Terminal**: Adaptive dark browser theme, persistent GitHub session, isolated `.venv` management, and dependency installation.
- **Smart GitHub Sync & Confirmation**: Strict 1-chat = 1-workspace isolation, meaningful repository naming, and user confirmation before creating/publishing repositories.
- **Bilingual UI & Agent (`UA / EN`)**: Instant switching between Ukrainian and English for menus, chat actions, and agent responses.

---

## Installation & Quick Start

### Windows
```bat
git clone https://github.com/mortalmad92/BlackChpokIDE.git
cd BlackChpokIDE
install.bat
run_ide.bat        :: Launch IDE
build_exe.bat      :: Build portable dist\BlackChpok\BlackChpok.exe
```

### Linux (Ubuntu / Debian / Arch)
```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-tk git
git clone https://github.com/mortalmad92/BlackChpokIDE.git
cd BlackChpokIDE
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

---

## Testing & CI

```bash
python tests/check_style.py
python main.py --selftest
python -m unittest discover -s tests
```
