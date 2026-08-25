@echo off
setlocal
title Niveku - DigiWorldExplorer_Bot Installer
color 0E
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup.ps1"
set "exit_code=%ERRORLEVEL%"
echo.
if not "%exit_code%"=="0" echo Instalacion fallida. Lee README.md, seccion Solucion de problemas.
pause
exit /b %exit_code%
