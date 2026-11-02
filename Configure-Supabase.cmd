@echo off
setlocal
pushd "%~dp0backend"
".venv\Scripts\python.exe" -m app.configure_cloud
set "configExitCode=%errorlevel%"
popd
if not "%configExitCode%"=="0" pause
exit /b %configExitCode%
