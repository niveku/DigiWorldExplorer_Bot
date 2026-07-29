@echo off
setlocal
title RobinTh0r - DigiWorldExplorer_Bot DEBUG
color 0E
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Bot.ps1" -DebugMode
set "exit_code=%ERRORLEVEL%"
echo.
pause
exit /b %exit_code%