@echo off
setlocal
title MDEC Docket Manager - Setup
cd /d "%~dp0"

echo ============================================================
echo   MDEC Docket Manager - Setup
echo ============================================================
echo.
echo This will:
echo   1. install the Python packages the app needs
echo   2. download the private browser it uses (~130 MB, once)
echo   3. put a "MDEC Docket Manager" icon on your Desktop
echo      and in the Start Menu
echo.
echo Nothing is installed system-wide and nothing is sent anywhere.
echo.
pause

where python >nul 2>&1
if errorlevel 1 (
  echo.
  echo [X] Python was not found.
  echo.
  echo     Install Python 3.11 or newer from https://www.python.org/downloads/
  echo     and be sure to tick "Add python.exe to PATH" during setup.
  echo     Then run this again.
  echo.
  pause
  exit /b 1
)

echo.
echo [1/4] Checking Python version...
python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"
if errorlevel 1 (
  echo.
  echo [X] Python 3.11 or newer is required.
  python --version
  echo.
  pause
  exit /b 1
)
python --version

echo.
echo [2/4] Installing Python packages...
python -m pip install --upgrade --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo.
  echo [X] Package install failed. You are probably offline, or behind a proxy
  echo     that blocks pypi.org. Fix the connection and run this again.
  echo.
  pause
  exit /b 1
)
echo     done.

echo.
echo [3/4] Downloading the private browser (skipped if already present)...
python -m playwright install chromium
if errorlevel 1 (
  echo.
  echo [!] The browser download failed. The app is installed, but checks will
  echo     not work until this succeeds. Re-run this installer when back online.
  echo.
)

echo.
echo [4/4] Creating the icon and shortcuts...
python tools\make_icon.py
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\make_shortcuts.ps1"
if errorlevel 1 (
  echo.
  echo [X] Could not create the shortcuts.
  echo.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   Done.
echo ============================================================
echo.
echo Open "MDEC Docket Manager" from your Desktop or Start Menu.
echo.
echo First run: Settings - Cases - add your case number and pick a
echo folder, then "Open portal window" and sign in.
echo.
choice /C YN /N /M "Open the app now? [Y/N] "
if errorlevel 2 goto :done
start "" "%~dp0MDEC Docket Manager.pyw"

:done
endlocal
