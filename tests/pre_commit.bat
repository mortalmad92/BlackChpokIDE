@echo off
rem ============================================================================
rem  Fast pre-commit check for BlackChpok IDE.
rem
rem  Steps (about 20 seconds):
rem    1. compile the package   - catches syntax errors;
rem    2. code style            - tabs, trailing spaces, bare except;
rem    3. core selftest         - tools, models, storages;
rem    4. unit tests            - logic regressions.
rem
rem  The full run (with GUI) stays in CI and in tests\run_all.py - here we
rem  only do the fast group so committing stays quick.
rem
rem  Enable as a git hook:
rem      copy tests\pre_commit.bat .git\hooks\pre-commit
rem
rem  Run manually:  tests\pre_commit.bat
rem
rem  NOTE: comments are ASCII on purpose - cmd.exe with cp866 garbles
rem  Cyrillic inside .bat files and breaks parsing.
rem ============================================================================

setlocal enableextensions
chcp 65001 >nul
rem Repo root = parent of this script's folder, resolved BEFORE changing dir.
for %%I in ("%~dp0..") do set "REPO=%%~fI"
cd /d "%REPO%"

if not exist "%REPO%\.venv\Scripts\python.exe" (
  echo ERROR: run install.bat first
  exit /b 1
)

set "PY=%REPO%\.venv\Scripts\python.exe"
set "PYTHONIOENCODING=utf-8"
set "BLACKCHPOK_HOME=%REPO%\.buildtmp\pre-commit"
rem Guard against recursion: the test suite runs this hook too.
set "BCHPOK_PRE_COMMIT=1"
set "FAILED=0"

echo [1/4] Compile package...
"%PY%" -m compileall -q blackchpok_ide
if errorlevel 1 (
  echo   FAIL: syntax errors
  set "FAILED=1"
) else (
  echo   OK
)

echo [2/4] Code style...
"%PY%" tests\check_style.py
if errorlevel 1 set "FAILED=1"

echo [3/4] Core selftest...
"%PY%" main.py --selftest >nul 2>&1
if errorlevel 1 (
  echo   FAIL: selftest
  set "FAILED=1"
) else (
  echo   OK
)

echo [4/4] Unit tests...
rem BCHPOK_SKIP_TESTS=1 lets the quality-gate test run this hook without
rem starting the whole suite again (which would include that same test).
if "%BCHPOK_SKIP_TESTS%"=="1" (
  echo   SKIPPED ^(BCHPOK_SKIP_TESTS=1^)
) else (
  "%PY%" -m unittest discover -s tests >nul 2>&1
  if errorlevel 1 (
    echo   FAIL: tests - run: python -m unittest discover -s tests -v
    set "FAILED=1"
  ) else (
    echo   OK
  )
)

echo.
if "%FAILED%"=="1" (
  echo ============================================
  echo   COMMIT BLOCKED: fix the problems above.
  echo   Use --no-verify only for a deliberate WIP commit.
  echo ============================================
  exit /b 1
)

echo ============================================
echo   All fast checks passed.
echo ============================================
exit /b 0
