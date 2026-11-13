@echo off
setlocal
pushd "%~dp0" || exit /b 1
set "PYTHONDONTWRITEBYTECODE=1"
call npm run dev
set "launchExitCode=%errorlevel%"
popd
if not "%launchExitCode%"=="0" pause
exit /b %launchExitCode%
