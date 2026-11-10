@echo off
setlocal enableextensions
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   BlackChpok IDE - збірка .exe
echo ============================================
echo.

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [1/5] .venv не знайдено - створюю...
  where py >nul 2>nul
  if %errorlevel%==0 (
    py -m venv .venv
  ) else (
    python -m venv .venv
  )
)
if not exist "%PY%" (
  echo ПОМИЛКА: потрібен Python 3.11+ ^(python.org^).
  pause
  exit /b 1
)

echo [1/5] Перевіряю PyInstaller...
"%PY%" -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
  echo       встановлюю pyinstaller...
  "%PY%" -m pip install --upgrade pip
  "%PY%" -m pip install pyinstaller
  if errorlevel 1 (
    echo       pip не зміг - пробую вбудований завантажувач wheel
    "%PY%" "%~dp0tools\fetch_wheels.py" pyinstaller altgraph pefile pywin32-ctypes setuptools
  )
)
"%PY%" -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
  echo ПОМИЛКА: PyInstaller недоступний. Див. BUILD_UK.md, розділ "Якщо немає мережі".
  pause
  exit /b 1
)

echo [2/5] Самоперевірка коду...
"%PY%" "%~dp0main.py" --selftest
if errorlevel 1 (
  echo ПОМИЛКА: самоперевірка не пройдена.
  pause
  exit /b 1
)

echo.
echo [3/5] Іконка...
if not exist "%~dp0assets\icon.ico" (
  "%PY%" "%~dp0tools\make_icon.py"
)

echo.
echo [4/5] Чищу попередні артефакти...
if exist "%~dp0build" rmdir /s /q "%~dp0build"
if exist "%~dp0dist" rmdir /s /q "%~dp0dist"

echo.
echo [5/5] Збираю BlackChpok.exe (це може зайняти 1-3 хвилини)...
"%PY%" -m PyInstaller --noconfirm --clean "%~dp0BlackChpokIDE.spec"
if errorlevel 1 (
  echo.
  echo ПОМИЛКА збірки. Повний лог - вище.
  pause
  exit /b 1
)

if not exist "%~dp0dist\BlackChpok.exe" (
  echo ПОМИЛКА: dist\BlackChpok.exe не створено.
  pause
  exit /b 1
)

echo.
echo ============================================
echo   ГОТОВО: dist\BlackChpok.exe
echo ============================================
for %%F in ("%~dp0dist\BlackChpok.exe") do echo   Розмір: %%~zF байт
echo.
echo   Запуск: dist\BlackChpok.exe "C:\шлях\до\проєкту"
echo   Перевірка без вікна: dist\BlackChpok.exe --selftest
echo.
pause
