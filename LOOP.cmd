@echo off
setlocal
title Niveku - Loops de pantalla
color 0B
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Loop.ps1" %*
set "exit_code=%ERRORLEVEL%"
echo.
pause
exit /b %exit_code%
