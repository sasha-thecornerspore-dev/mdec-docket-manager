@echo off
setlocal
title MDEC Docket Manager - Uninstall
cd /d "%~dp0"

echo ============================================================
echo   MDEC Docket Manager - Uninstall
echo ============================================================
echo.
echo This removes the Desktop and Start Menu shortcuts.
echo.
echo It does NOT delete:
echo   - your downloaded court documents
echo   - your cases, notes, and analyses (%%APPDATA%%\MDECDocketManager)
echo   - saved passwords (Windows Credential Manager)
echo   - this folder
echo.
echo How to remove those is in docs\INSTALL.md under "Uninstall".
echo.
pause

powershell -NoProfile -ExecutionPolicy Bypass -File "tools\make_shortcuts.ps1" -Remove
echo.
pause
endlocal
