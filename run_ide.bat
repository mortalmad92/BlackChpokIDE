@echo off
setlocal enableextensions
chcp 65001 >nul
cd /d "%~dp0"

rem Запуск BlackChpok IDE з вихідного коду через .venv
if not exist ".venv\Scripts\python.exe" (
  echo .venv не знайдено - запускаю install.bat
  call install.bat
)

if not exist ".venv\Scripts\python.exe" (
  echo ПОМИЛКА: потрібен Python 3.11+ ^(python.org^)
  pause
  exit /b 1
)

rem Перший аргумент - папка проєкту (необов'язково)
set "WORKSPACE=%~1"
if "%WORKSPACE%"=="" set "WORKSPACE=%CD%"

echo Запуск BlackChpok IDE: %WORKSPACE%
".venv\Scripts\python.exe" "%~dp0main.py" "%WORKSPACE%"
if errorlevel 1 (
  echo.
  echo Застосунок завершився з помилкою. Журнал: %APPDATA%\BlackChpokIDE\ide.log
  pause
)
