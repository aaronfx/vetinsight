@echo off
setlocal
pushd "%~dp0backend"
".venv\Scripts\python.exe" -m app.manage_admin
set "setupExitCode=%errorlevel%"
popd
pause
exit /b %setupExitCode%
