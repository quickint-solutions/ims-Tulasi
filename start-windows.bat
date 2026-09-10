@echo off
REM ===================================================================
REM  Spares Inventory Management System
REM  Starts the system on this PC and shares it on your local network.
REM  First run installs everything; later runs just start the server.
REM ===================================================================
setlocal
cd /d "%~dp0"
title Spares Inventory - server

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo  Python was not found on this PC.
  echo.
  echo  1. Download Python 3.11 or newer from https://www.python.org/downloads/
  echo  2. During setup, TICK "Add python.exe to PATH"
  echo  3. Run this file again
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo  First run - setting up. This takes a couple of minutes.
  echo.
  python -m venv .venv
  if errorlevel 1 goto :fail
  call ".venv\Scripts\activate.bat"
  python -m pip install --upgrade pip --quiet
  echo  Installing components...
  pip install -r requirements.txt --quiet
  if errorlevel 1 goto :fail
) else (
  call ".venv\Scripts\activate.bat"
)

REM Creates .env on the first run only; never overwrites your edits.
python manage.py init_local_env --port 8000
if errorlevel 1 goto :fail

python manage.py migrate --noinput
if errorlevel 1 goto :fail

python manage.py collectstatic --noinput >nul
if errorlevel 1 goto :fail

python manage.py seed_defaults
if errorlevel 1 goto :fail

REM Asks for a username and password the very first time only.
python manage.py ensure_admin
if errorlevel 1 goto :fail

python manage.py serve_lan --port 8000 --no-migrate
echo.
echo  The server has stopped. Close this window, or run the file again to restart.
pause
goto :eof

:fail
echo.
echo  Setup failed. Scroll up to see the error, and send it over if it is unclear.
echo.
pause
exit /b 1
