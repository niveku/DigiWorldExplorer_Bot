@echo off
setlocal
title Niveku - DigiWorldExplorer_Bot CHECK
color 0E
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Check-Setup.ps1"
set "exit_code=%ERRORLEVEL%"
echo.
pause
exit /b %exit_code%
