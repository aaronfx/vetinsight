@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Start-VetInsight.ps1" %*
set "startupExitCode=%errorlevel%"
if not "%startupExitCode%"=="0" pause
exit /b %startupExitCode%
