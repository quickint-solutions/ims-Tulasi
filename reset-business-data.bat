@echo off
REM Dry-run by default. Pass "confirm" as the first argument to delete data.
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "PYTHON=.venv\Scripts\python.exe"
) else (
  set "PYTHON=python"
)

if /I "%~1"=="confirm" (
  echo.
  echo WARNING: This will delete inventory/module data from the configured database.
  echo A backup will be created first by the Django command.
  echo.
  "%PYTHON%" manage.py reset_business_data --confirm
) else (
  echo.
  echo Dry run only. No data will be deleted.
  echo To actually reset data, run: reset-business-data.bat confirm
  echo.
  "%PYTHON%" manage.py reset_business_data --dry-run
)

if errorlevel 1 (
  echo.
  echo Reset command failed. Review the error above.
  exit /b 1
)

endlocal
