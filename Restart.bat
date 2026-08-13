@echo off
setlocal

rem Keep this wrapper short-lived. The restart worker must outlive the server
rem process that invoked this file through a node tool call.
cd /d "%~dp0"
set "WORKSPACE_ROOT=%CD%"

if not "%~1"=="" (
    echo [ERROR] Restart.bat does not accept arguments.
    endlocal & exit /b 2
)

echo [INFO] Delegating AgentPark restart to an independent worker...
powershell -NoProfile -ExecutionPolicy Bypass -File "%WORKSPACE_ROOT%\scripts\launch_restart_worker.ps1" -WorkspaceRoot "%WORKSPACE_ROOT%"
set "EXIT_CODE=%errorlevel%"

if not "%EXIT_CODE%"=="0" echo [ERROR] Failed to launch the independent AgentPark restart worker.
endlocal & exit /b %EXIT_CODE%
