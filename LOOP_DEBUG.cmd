@echo off
setlocal
title Niveku - Loops de pantalla DEBUG
color 0E
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Loop.ps1" -DebugMode %*
set "exit_code=%ERRORLEVEL%"
echo.
pause
exit /b %exit_code%
