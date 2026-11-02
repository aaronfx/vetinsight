@echo off
setlocal
pushd "%~dp0backend"
".venv\Scripts\python.exe" -m app.migrate_cloud %*
set "migrationExitCode=%errorlevel%"
popd
if not "%migrationExitCode%"=="0" pause
exit /b %migrationExitCode%
