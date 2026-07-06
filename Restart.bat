@echo off
setlocal

rem Switch to the script directory to ensure relative paths work.
cd /d "%~dp0"
set "WORKSPACE_ROOT=%CD%"

echo [INFO] Restarting AgentPark...

powershell -NoProfile -ExecutionPolicy Bypass -File "%WORKSPACE_ROOT%\scripts\restart_agentpark.ps1" -WorkspaceRoot "%WORKSPACE_ROOT%"
if errorlevel 1 (
    echo [ERROR] Failed to stop the previous AgentPark server instance.
    pause
    exit /b 1
)

echo [INFO] Checking repository before startup...
powershell -NoProfile -ExecutionPolicy Bypass -File "%WORKSPACE_ROOT%\scripts\sync_before_restart.ps1" -WorkspaceRoot "%WORKSPACE_ROOT%"
if errorlevel 1 (
    echo [WARN] Repository update did not complete. Continuing startup.
)

echo [INFO] Starting AgentPark through build_and_run.bat...
set "AGENTPARK_NO_PAUSE=1"
call "%WORKSPACE_ROOT%\build_and_run.bat" %*
set "EXIT_CODE=%errorlevel%"

endlocal & exit /b %EXIT_CODE%
