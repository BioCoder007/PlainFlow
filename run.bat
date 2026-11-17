@echo off
rem Starts PlainFlow. The first run sets everything up (about a minute); later runs start at once.
cd /d "%~dp0"

set PY=python
where py >nul 2>nul && set PY=py -3
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.11 or newer from https://www.python.org/downloads/
  echo During setup, tick "Add python.exe to PATH". Then run this file again.
  pause
  exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
  echo PlainFlow needs Python 3.11 or newer.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up PlainFlow. This takes about a minute.
  %PY% -m venv .venv
  if errorlevel 1 goto failed
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
  if errorlevel 1 goto failed
)

".venv\Scripts\python.exe" main.py %*
if errorlevel 1 pause
exit /b 0

:failed
echo Setup failed. Check your internet connection and run this file again.
pause
exit /b 1
