@echo off
setlocal

rem Switch to the script directory to ensure relative paths work.
cd /d "%~dp0"
set "WORKSPACE_ROOT=%CD%"

echo [INFO] Restarting AITools...

powershell -NoProfile -ExecutionPolicy Bypass -File "%WORKSPACE_ROOT%\scripts\restart_aitools.ps1" -WorkspaceRoot "%WORKSPACE_ROOT%"
if errorlevel 1 (
    echo [ERROR] Failed to stop the previous AITools server instance.
    pause
    exit /b 1
)

echo [INFO] Updating repository with git pull --rebase...
git pull --rebase
if errorlevel 1 (
    echo [WARN] Failed to update repository with git pull --rebase.
    echo [WARN] Continuing startup with the current local workspace.
)

echo [INFO] Starting AITools through build_and_run.bat...
set "AITOOLS_NO_PAUSE=1"
call "%WORKSPACE_ROOT%\build_and_run.bat" %*
set "EXIT_CODE=%errorlevel%"

endlocal & exit /b %EXIT_CODE%
