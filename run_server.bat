@echo off
setlocal enableextensions
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo ERROR: .venv не знайдено. Спочатку запусти install.bat
  pause
  exit /b 1
)

rem === Змінні середовища для ручного запуску ===
rem (MCP-клієнт передає їх сам, тут — для тесту з провідника)
set "MCP_WORKSPACE=%~dp0"
set "MCP_LOG_LEVEL=INFO"
set "MCP_LLM_BACKEND=auto"
set "MCP_LMSTUDIO_URL=http://127.0.0.1:1234/v1"
set "MCP_LMSTUDIO_MODEL=qwen2.5-coder-14b-instruct"
set "MCP_LMSTUDIO_API_KEY=lm-studio"
set "MCP_OLLAMA_URL=http://127.0.0.1:11434"
set "MCP_OLLAMA_MODEL=qwen2.5-coder:14b"
set "MCP_DB_PATH=%~dp0.mcp_rag\memoria_infinita.db"
set "MCP_NUM_CTX=16384"
set "MCP_NUM_THREAD=8"
set "MCP_TEMPERATURE=0.15"

rem Embeddings (якщо маєш налаштовані в LM Studio)
rem set "MCP_RAG_EMBEDDINGS_URL=http://127.0.0.1:1234/v1/embeddings"
rem set "MCP_RAG_EMBEDDINGS_MODEL=text-embedding-nomic-embed-text-v1.5"

echo === Starting MCP server (stdio) ===
echo Workspace: %MCP_WORKSPACE%
echo LM Studio: %MCP_LMSTUDIO_URL%
echo Ollama:    %MCP_OLLAMA_URL%
echo.
echo Server will wait for JSON-RPC on stdin. Ctrl+C to stop.
echo.
".venv\Scripts\python.exe" "%~dp0server.py"
pause