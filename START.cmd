@echo off
setlocal
title Niveku - DigiWorldExplorer_Bot
color 0E
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Bot.ps1"
set "exit_code=%ERRORLEVEL%"
echo.
pause
exit /b %exit_code%
