@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Switch to the script directory to ensure relative paths work
cd /d "%~dp0"
set "AITOOLS_LAUNCH_MODE=cli_web"
set "AITOOLS_CLI_ARGS=chat"
set "AITOOLS_RESTART_EXIT_CODE=43"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if /I "%~1"=="server" (
    set "AITOOLS_LAUNCH_MODE=server"
    set "AITOOLS_CLI_ARGS="
)
if /I "%~1"=="web" (
    set "AITOOLS_LAUNCH_MODE=server"
    set "AITOOLS_CLI_ARGS="
)
if /I "%~1"=="cli-only" (
    set "AITOOLS_LAUNCH_MODE=cli_only"
    if "%~2"=="" (
        set "AITOOLS_CLI_ARGS=chat"
    ) else if /I "%~2"=="chat" (
        set "AITOOLS_CLI_ARGS=%2 %3 %4 %5 %6 %7 %8 %9"
    ) else if /I "%~2"=="doctor" (
        set "AITOOLS_CLI_ARGS=%2 %3 %4 %5 %6 %7 %8 %9"
    ) else if /I "%~2"=="capabilities" (
        set "AITOOLS_CLI_ARGS=%2 %3 %4 %5 %6 %7 %8 %9"
    ) else if /I "%~2"=="config" (
        set "AITOOLS_CLI_ARGS=%2 %3 %4 %5 %6 %7 %8 %9"
    ) else (
        set "AITOOLS_CLI_ARGS=chat %2 %3 %4 %5 %6 %7 %8 %9"
    )
)
if /I "%~1"=="cli" (
    set "AITOOLS_LAUNCH_MODE=cli_web"
    if "%~2"=="" (
        set "AITOOLS_CLI_ARGS=chat"
    ) else if /I "%~2"=="chat" (
        set "AITOOLS_CLI_ARGS=%2 %3 %4 %5 %6 %7 %8 %9"
    ) else if /I "%~2"=="doctor" (
        set "AITOOLS_CLI_ARGS=%2 %3 %4 %5 %6 %7 %8 %9"
    ) else if /I "%~2"=="capabilities" (
        set "AITOOLS_CLI_ARGS=%2 %3 %4 %5 %6 %7 %8 %9"
    ) else if /I "%~2"=="config" (
        set "AITOOLS_CLI_ARGS=%2 %3 %4 %5 %6 %7 %8 %9"
    ) else (
        set "AITOOLS_CLI_ARGS=chat %2 %3 %4 %5 %6 %7 %8 %9"
    )
)
if /I "%~1"=="chat" (
    set "AITOOLS_LAUNCH_MODE=cli_web"
    set "AITOOLS_CLI_ARGS=chat %2 %3 %4 %5 %6 %7 %8 %9"
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
call :ensure_rg

echo [INFO] Starting WebUI Build Process...

rem Navigate to webui directory
cd webui
echo [INFO] Current working directory: %cd%

echo [INFO] Installing/updating WebUI dependencies...
call npm install

if %errorlevel% neq 0 (
    echo [ERROR] WebUI dependency install failed with error code %errorlevel%
    call :maybe_pause
    exit /b %errorlevel%
)

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
"%PYTHON_EXE%" -m pip install -e .

if %errorlevel% neq 0 (
    echo [ERROR] Python dependency install failed with error code %errorlevel%
    call :maybe_pause
    exit /b %errorlevel%
)

if /I "%AITOOLS_LAUNCH_MODE%"=="cli_web" (
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

if /I "%AITOOLS_LAUNCH_MODE%"=="cli_web" (
    if not defined AITOOLS_CLI_ARGS set "AITOOLS_CLI_ARGS=chat"
    echo [INFO] Starting AITools CLI: python -m src.cli !AITOOLS_CLI_ARGS!
    "%PYTHON_EXE%" -m src.cli !AITOOLS_CLI_ARGS!
    set "AITOOLS_CLI_EXIT=!errorlevel!"
    if "!AITOOLS_CLI_EXIT!"=="%AITOOLS_RESTART_EXIT_CODE%" (
        echo [INFO] Restart requested by companion CLI; exiting without pause.
        exit /b 0
    )
    call :maybe_pause
    exit /b !AITOOLS_CLI_EXIT!
)

if /I "%AITOOLS_LAUNCH_MODE%"=="cli_only" (
    if not defined AITOOLS_CLI_ARGS set "AITOOLS_CLI_ARGS=chat"
    echo [INFO] Starting AITools CLI: python -m src.cli !AITOOLS_CLI_ARGS!
    "%PYTHON_EXE%" -m src.cli !AITOOLS_CLI_ARGS!
    set "AITOOLS_CLI_EXIT=!errorlevel!"
    if "!AITOOLS_CLI_EXIT!"=="%AITOOLS_RESTART_EXIT_CODE%" (
        echo [INFO] Restart requested by companion CLI; exiting without pause.
        exit /b 0
    )
    call :maybe_pause
    exit /b !AITOOLS_CLI_EXIT!
)

echo [INFO] Starting AITools server...

"%PYTHON_EXE%" -m src.fast_api --workspace-root "%cd%"

call :maybe_pause
endlocal

exit /b 0

:maybe_pause
if /I "%AITOOLS_NO_PAUSE%"=="1" exit /b 0
pause
exit /b 0

:start_background_server
if not exist ".runtime" mkdir ".runtime"
set "AITOOLS_WEB_STDOUT=%cd%\.runtime\aitools-server.log"
set "AITOOLS_WEB_STDERR=%cd%\.runtime\aitools-server.err.log"
set "AITOOLS_WORKSPACE_ROOT=%cd%"
set "AITOOLS_PYTHON_EXE=%PYTHON_EXE%"
echo [INFO] Starting AITools web server in background. Logs:
echo [INFO]   %AITOOLS_WEB_STDOUT%
echo [INFO]   %AITOOLS_WEB_STDERR%
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $python=$env:AITOOLS_PYTHON_EXE; $root=$env:AITOOLS_WORKSPACE_ROOT; $stdout=$env:AITOOLS_WEB_STDOUT; $stderr=$env:AITOOLS_WEB_STDERR; $launcher=(Get-CimInstance Win32_Process -Filter ('ProcessId=' + $PID)).ParentProcessId; $env:AITOOLS_EXIT_WHEN_PID_EXITS=[string]$launcher; $arguments=@('-m','src.fast_api','--workspace-root',$root); Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr"
if errorlevel 1 (
    echo [ERROR] Failed to start AITools web server in background.
    exit /b %errorlevel%
)
echo [INFO] Web server process launched.
exit /b 0

:stop_existing_workspace_processes
if not exist "scripts\restart_aitools.ps1" exit /b 0
echo [INFO] Stopping existing AITools processes for this workspace...
powershell -NoProfile -ExecutionPolicy Bypass -File "%cd%\scripts\restart_aitools.ps1" -WorkspaceRoot "%cd%"
if errorlevel 1 (
    echo [ERROR] Failed to stop existing AITools processes.
    exit /b %errorlevel%
)
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
