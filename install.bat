@echo off
setlocal enableextensions
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   BlackChpok AI - встановлення
echo ============================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
  py -m venv .venv
) else (
  python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
  echo ПОМИЛКА: потрібен Python 3.11+ з python.org ^(галочка "Add to PATH" і "tcl/tk"^).
  pause
  exit /b 1
)

echo [1/3] Оновлюю pip...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip

echo.
echo [2/3] Ставлю залежності MCP-сервера...
call ".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo УВАГА: частина залежностей не стала. IDE працює без них:
  echo   - tkinter входить у Python;
  echo   - клиент моделі написаний на стандартній бібліотеці;
  echo   - необхідні лише для server.py (MCP-сервер).
  echo Спробуй ще раз пізніше: ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

echo.
echo [3/3] Перевіряю IDE...
".venv\Scripts\python.exe" "%~dp0main.py" --selftest

echo.
echo ============================================
echo   ГОТОВО
echo ============================================
echo   IDE (з коду):      run_ide.bat
echo   IDE (.exe):        build_exe.bat  ->  dist\BlackChpok.exe
echo   Тести:             run_tests.bat
echo   MCP-сервер:        run_server.bat (вручну) або конфіг вашого MCP-клієнта
echo.
pause
