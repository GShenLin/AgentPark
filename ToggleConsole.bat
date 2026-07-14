@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\agentpark_console_window.ps1" -WorkspaceRoot "%CD%" -Action Toggle
if errorlevel 1 (
    echo.
    echo [ERROR] Unable to toggle the AgentPark console window.
    pause
    exit /b 1
)

endlocal
exit /b 0
