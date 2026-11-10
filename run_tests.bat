@echo off
setlocal enableextensions
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo ПОМИЛКА: спочатку запусти install.bat
  pause
  exit /b 1
)

echo ============================================
echo   BlackChpok IDE - перевірка проєкту
echo ============================================
echo.

".venv\Scripts\python.exe" "%~dp0tests\run_all.py" %*
set "CODE=%errorlevel%"
echo.
if "%CODE%"=="0" (echo УСІ ПЕРЕВІРКИ ПРОЙДЕНО) else (echo Є ПОМИЛКИ - див. вивід вище)
pause
exit /b %CODE%
