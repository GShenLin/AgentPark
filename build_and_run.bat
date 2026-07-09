@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Switch to the script directory to ensure relative paths work
cd /d "%~dp0"
set "AGENTPARK_WORKSPACE_ROOT=%cd%"
echo [INFO] Checking repository before startup...
powershell -NoProfile -ExecutionPolicy Bypass -File "%AGENTPARK_WORKSPACE_ROOT%\scripts\sync_before_restart.ps1" -WorkspaceRoot "%AGENTPARK_WORKSPACE_ROOT%"
if errorlevel 1 (
    echo [WARN] Repository update did not complete. Continuing startup.
)

if not exist "%AGENTPARK_WORKSPACE_ROOT%\.runtime" mkdir "%AGENTPARK_WORKSPACE_ROOT%\.runtime"
set "AGENTPARK_DEPENDENCY_UPDATE_LOG=%AGENTPARK_WORKSPACE_ROOT%\.runtime\dependency-update.log"
>>"%AGENTPARK_DEPENDENCY_UPDATE_LOG%" echo.
>>"%AGENTPARK_DEPENDENCY_UPDATE_LOG%" echo ===== AgentPark dependency update session %date% %time% =====
set "AGENTPARK_LAUNCH_MODE=cli_web"
set "AGENTPARK_CLI_ARGS=chat"
set "AGENTPARK_RESTART_EXIT_CODE=43"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if /I "%~1"=="server" (
    set "AGENTPARK_LAUNCH_MODE=server"
    set "AGENTPARK_CLI_ARGS="
)
if /I "%~1"=="web" (
    set "AGENTPARK_LAUNCH_MODE=server"
    set "AGENTPARK_CLI_ARGS="
)
if /I "%~1"=="cli-only" (
    set "AGENTPARK_LAUNCH_MODE=cli_only"
    if "%~2"=="" (
        set "AGENTPARK_CLI_ARGS=chat"
    ) else if /I "%~2"=="chat" (
        set "AGENTPARK_CLI_ARGS=%2 %3 %4 %5 %6 %7 %8 %9"
    ) else if /I "%~2"=="doctor" (
        set "AGENTPARK_CLI_ARGS=%2 %3 %4 %5 %6 %7 %8 %9"
    ) else if /I "%~2"=="capabilities" (
        set "AGENTPARK_CLI_ARGS=%2 %3 %4 %5 %6 %7 %8 %9"
    ) else if /I "%~2"=="config" (
        set "AGENTPARK_CLI_ARGS=%2 %3 %4 %5 %6 %7 %8 %9"
    ) else (
        set "AGENTPARK_CLI_ARGS=chat %2 %3 %4 %5 %6 %7 %8 %9"
    )
)
if /I "%~1"=="cli" (
    set "AGENTPARK_LAUNCH_MODE=cli_web"
    if "%~2"=="" (
        set "AGENTPARK_CLI_ARGS=chat"
    ) else if /I "%~2"=="chat" (
        set "AGENTPARK_CLI_ARGS=%2 %3 %4 %5 %6 %7 %8 %9"
    ) else if /I "%~2"=="doctor" (
        set "AGENTPARK_CLI_ARGS=%2 %3 %4 %5 %6 %7 %8 %9"
    ) else if /I "%~2"=="capabilities" (
        set "AGENTPARK_CLI_ARGS=%2 %3 %4 %5 %6 %7 %8 %9"
    ) else if /I "%~2"=="config" (
        set "AGENTPARK_CLI_ARGS=%2 %3 %4 %5 %6 %7 %8 %9"
    ) else (
        set "AGENTPARK_CLI_ARGS=chat %2 %3 %4 %5 %6 %7 %8 %9"
    )
)
if /I "%~1"=="chat" (
    set "AGENTPARK_LAUNCH_MODE=cli_web"
    set "AGENTPARK_CLI_ARGS=chat %2 %3 %4 %5 %6 %7 %8 %9"
)
if /I "%~1"=="ask-here" (
    set "AGENTPARK_LAUNCH_MODE=ask_here"
    set "AGENTPARK_ASK_HERE_PATH=%~2"
    set "AGENTPARK_NO_PAUSE=1"
)
set "PYTHON_EXE="
call :select_python "%LocalAppData%\Programs\Python\Python314\python.exe"
if not defined PYTHON_EXE call :select_python "%UserProfile%\Miniconda3\python.exe"
if not defined PYTHON_EXE call :select_python "%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined PYTHON_EXE call :select_python "%LocalAppData%\Programs\Python\Python311\python.exe"
if not defined PYTHON_EXE call :select_python "python"

if not defined PYTHON_EXE (
    echo [ERROR] Could not find a Python interpreter with pip available.
    echo [ERROR] Install Python with pip, or update build_and_run.bat with the Python path for this machine.
    call :maybe_pause
    exit /b 1
)

echo [INFO] Using Python: %PYTHON_EXE%

if /I "%AGENTPARK_LAUNCH_MODE%"=="ask_here" (
    call :handle_ask_here
    set "AGENTPARK_ASK_HERE_EXIT=!errorlevel!"
    call :maybe_pause
    exit /b !AGENTPARK_ASK_HERE_EXIT!
)

call :ensure_rg
call :register_folder_context_menu

echo [INFO] Starting WebUI Build Process...

rem Navigate to webui directory
cd webui
echo [INFO] Current working directory: %cd%

echo [INFO] Installing/updating WebUI dependencies...
set "AGENTPARK_UPDATE_COMMAND=npm install"
call :run_optional_dependency_update "WebUI dependency update"

echo [INFO] Compiling WebUI...
call npm run build

if %errorlevel% neq 0 (
    echo [ERROR] WebUI build failed with error code %errorlevel%
    call :maybe_pause
    exit /b %errorlevel%
)

echo [INFO] WebUI build successful.

rem Return to root directory
cd ..

echo [INFO] Installing/updating Python dependencies...
set "AGENTPARK_UPDATE_COMMAND="%PYTHON_EXE%" -m pip install -e ."
call :run_optional_dependency_update "Python dependency update"

if exist "desktop\pet\package.json" (
    echo [INFO] Installing/updating Desktop pet dependencies...
    pushd desktop\pet
    set "AGENTPARK_UPDATE_COMMAND=npm install"
    call :run_optional_dependency_update "Desktop pet dependency update"
    popd
) else (
    echo [WARN] Desktop pet package not found: desktop\pet\package.json
)

if /I "%AGENTPARK_LAUNCH_MODE%"=="cli_web" (
    call :stop_existing_workspace_processes
    if errorlevel 1 (
        call :maybe_pause
        exit /b %errorlevel%
    )
    call :start_background_server
    if errorlevel 1 (
        call :maybe_pause
        exit /b %errorlevel%
    )
)

if /I "%AGENTPARK_LAUNCH_MODE%"=="cli_web" (
    if not defined AGENTPARK_CLI_ARGS set "AGENTPARK_CLI_ARGS=chat"
    echo [INFO] Starting AgentPark CLI: python -m src.cli !AGENTPARK_CLI_ARGS!
    "%PYTHON_EXE%" -m src.cli !AGENTPARK_CLI_ARGS!
    set "AGENTPARK_CLI_EXIT=!errorlevel!"
    if "!AGENTPARK_CLI_EXIT!"=="%AGENTPARK_RESTART_EXIT_CODE%" (
        echo [INFO] Restart requested by companion CLI; exiting without pause.
        exit /b 0
    )
    call :maybe_pause
    exit /b !AGENTPARK_CLI_EXIT!
)

if /I "%AGENTPARK_LAUNCH_MODE%"=="cli_only" (
    if not defined AGENTPARK_CLI_ARGS set "AGENTPARK_CLI_ARGS=chat"
    echo [INFO] Starting AgentPark CLI: python -m src.cli !AGENTPARK_CLI_ARGS!
    "%PYTHON_EXE%" -m src.cli !AGENTPARK_CLI_ARGS!
    set "AGENTPARK_CLI_EXIT=!errorlevel!"
    if "!AGENTPARK_CLI_EXIT!"=="%AGENTPARK_RESTART_EXIT_CODE%" (
        echo [INFO] Restart requested by companion CLI; exiting without pause.
        exit /b 0
    )
    call :maybe_pause
    exit /b !AGENTPARK_CLI_EXIT!
)

echo [INFO] Starting AgentPark server...

"%PYTHON_EXE%" -m src.fast_api --workspace-root "%cd%"

call :maybe_pause
endlocal

exit /b 0

:maybe_pause
if /I "%AGENTPARK_NO_PAUSE%"=="1" exit /b 0
pause
exit /b 0

:run_optional_dependency_update
set "AGENTPARK_UPDATE_LABEL=%~1"
set "AGENTPARK_UPDATE_TEMP=%TEMP%\agentpark-dependency-update-%RANDOM%-%RANDOM%.log"
echo [INFO] Running !AGENTPARK_UPDATE_LABEL!: !AGENTPARK_UPDATE_COMMAND!
>>"%AGENTPARK_DEPENDENCY_UPDATE_LOG%" echo.
>>"%AGENTPARK_DEPENDENCY_UPDATE_LOG%" echo ----- !AGENTPARK_UPDATE_LABEL! -----
>>"%AGENTPARK_DEPENDENCY_UPDATE_LOG%" echo [INFO] cwd=%cd%
>>"%AGENTPARK_DEPENDENCY_UPDATE_LOG%" echo [INFO] command=!AGENTPARK_UPDATE_COMMAND!
cmd /d /s /c "!AGENTPARK_UPDATE_COMMAND!" > "!AGENTPARK_UPDATE_TEMP!" 2>&1
set "AGENTPARK_UPDATE_EXIT=!errorlevel!"
if exist "!AGENTPARK_UPDATE_TEMP!" (
    type "!AGENTPARK_UPDATE_TEMP!"
    type "!AGENTPARK_UPDATE_TEMP!" >> "%AGENTPARK_DEPENDENCY_UPDATE_LOG%"
)
if not "!AGENTPARK_UPDATE_EXIT!"=="0" (
    echo [WARN] !AGENTPARK_UPDATE_LABEL! failed with error code !AGENTPARK_UPDATE_EXIT!.
    echo [WARN] Dependency update output was printed above and saved to:
    echo [WARN]   %AGENTPARK_DEPENDENCY_UPDATE_LOG%
    echo [WARN] Continuing startup because existing installed packages may still be usable.
    >>"%AGENTPARK_DEPENDENCY_UPDATE_LOG%" echo [WARN] !AGENTPARK_UPDATE_LABEL! failed with error code !AGENTPARK_UPDATE_EXIT!.
    >>"%AGENTPARK_DEPENDENCY_UPDATE_LOG%" echo [WARN] Continuing startup because existing installed packages may still be usable.
    if exist "!AGENTPARK_UPDATE_TEMP!" del /q "!AGENTPARK_UPDATE_TEMP!" >nul 2>nul
    exit /b 0
)
echo [INFO] !AGENTPARK_UPDATE_LABEL! completed successfully.
>>"%AGENTPARK_DEPENDENCY_UPDATE_LOG%" echo [INFO] !AGENTPARK_UPDATE_LABEL! completed successfully.
if exist "!AGENTPARK_UPDATE_TEMP!" del /q "!AGENTPARK_UPDATE_TEMP!" >nul 2>nul
exit /b 0

:start_background_server
if not exist ".runtime" mkdir ".runtime"
set "AGENTPARK_WEB_STDOUT=%cd%\.runtime\agentpark-server.log"
set "AGENTPARK_WEB_STDERR=%cd%\.runtime\agentpark-server.err.log"
set "AGENTPARK_WORKSPACE_ROOT=%cd%"
set "AGENTPARK_PYTHON_EXE=%PYTHON_EXE%"
echo [INFO] Starting AgentPark web server in background. Logs:
echo [INFO]   %AGENTPARK_WEB_STDOUT%
echo [INFO]   %AGENTPARK_WEB_STDERR%
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $python=$env:AGENTPARK_PYTHON_EXE; $root=$env:AGENTPARK_WORKSPACE_ROOT; $stdout=$env:AGENTPARK_WEB_STDOUT; $stderr=$env:AGENTPARK_WEB_STDERR; $launcher=(Get-CimInstance Win32_Process -Filter ('ProcessId=' + $PID)).ParentProcessId; $env:AGENTPARK_EXIT_WHEN_PID_EXITS=[string]$launcher; $arguments=@('-m','src.fast_api','--workspace-root',$root); Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr"
if errorlevel 1 (
    echo [ERROR] Failed to start AgentPark web server in background.
    exit /b %errorlevel%
)
echo [INFO] Web server process launched.
exit /b 0

:stop_existing_workspace_processes
if not exist "scripts\restart_agentpark.ps1" exit /b 0
echo [INFO] Stopping existing AgentPark processes for this workspace...
powershell -NoProfile -ExecutionPolicy Bypass -File "%cd%\scripts\restart_agentpark.ps1" -WorkspaceRoot "%cd%"
if errorlevel 1 (
    echo [ERROR] Failed to stop existing AgentPark processes.
    exit /b %errorlevel%
)
exit /b 0

:handle_ask_here
if not defined AGENTPARK_ASK_HERE_PATH (
    echo [ERROR] Ask Here requires a folder path.
    exit /b 1
)
if not exist "%AGENTPARK_ASK_HERE_PATH%\." (
    echo [ERROR] Ask Here folder path does not exist: "%AGENTPARK_ASK_HERE_PATH%"
    exit /b 1
)
"%PYTHON_EXE%" -m src.ask_here_launcher ping >nul 2>nul
if errorlevel 1 (
    echo [INFO] AgentPark server is not running; starting it now...
    call :start_background_server
    if errorlevel 1 exit /b %errorlevel%
    "%PYTHON_EXE%" -m src.ask_here_launcher wait --timeout 35
    if errorlevel 1 exit /b %errorlevel%
)
"%PYTHON_EXE%" -m src.ask_here_launcher dispatch --path "%AGENTPARK_ASK_HERE_PATH%"
exit /b %errorlevel%

:register_folder_context_menu
if not exist "scripts\register_folder_context_menu.ps1" exit /b 0
powershell -NoProfile -ExecutionPolicy Bypass -File "%cd%\scripts\register_folder_context_menu.ps1" -WorkspaceRoot "%cd%"
if errorlevel 1 (
    echo [WARN] Failed to register AgentPark folder context menu.
    exit /b 0
)
echo [INFO] AgentPark folder context menu registered.
exit /b 0

:ensure_rg
where rg >nul 2>nul
if not errorlevel 1 (
    echo [INFO] ripgrep detected: rg
    exit /b 0
)

echo [WARN] ripgrep ^(rg^) not found in PATH. Shell rg commands will be unavailable.
where winget >nul 2>nul
if errorlevel 1 (
    echo [WARN] winget not found. Install ripgrep manually: winget install BurntSushi.ripgrep.MSVC
    exit /b 0
)

echo [INFO] Installing ripgrep via winget...
winget install --id BurntSushi.ripgrep.MSVC -e --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo [WARN] ripgrep install failed. Install manually: winget install BurntSushi.ripgrep.MSVC
    exit /b 0
)

where rg >nul 2>nul
if errorlevel 1 (
    echo [WARN] ripgrep installed, but PATH may require a new terminal before rg is available.
) else (
    echo [INFO] ripgrep installed successfully.
)
exit /b 0

:select_python
set "CANDIDATE=%~1"
if "%CANDIDATE%"=="" exit /b 0
if not "%CANDIDATE%"=="python" if not exist "%CANDIDATE%" exit /b 0
"%CANDIDATE%" -m pip --version >nul 2>nul
if errorlevel 1 exit /b 0
set "PYTHON_EXE=%CANDIDATE%"
exit /b 0
