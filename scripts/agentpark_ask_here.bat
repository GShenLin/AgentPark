@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0\.."
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if not exist ".runtime" mkdir ".runtime"
set "AITOOLS_ASK_HERE_LOG=%cd%\.runtime\agentpark-ask-here.log"
call :log "start script=%~f0 arg1=%~1 cwd=%cd%"

set "AITOOLS_ASK_HERE_PATH=%~1"
if not defined AITOOLS_ASK_HERE_PATH (
    call :log "error missing-target-path"
    echo [ERROR] Ask Here requires a target path.
    exit /b 1
)
if not exist "%AITOOLS_ASK_HERE_PATH%" (
    call :log "error target-path-does-not-exist path=%AITOOLS_ASK_HERE_PATH%"
    echo [ERROR] Ask Here target path does not exist: "%AITOOLS_ASK_HERE_PATH%"
    exit /b 1
)
call :log "target-path-ok path=%AITOOLS_ASK_HERE_PATH%"

set "PYTHON_EXE="
call :select_python "%LocalAppData%\Programs\Python\Python314\python.exe"
if not defined PYTHON_EXE call :select_python "%UserProfile%\Miniconda3\python.exe"
if not defined PYTHON_EXE call :select_python "%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined PYTHON_EXE call :select_python "%LocalAppData%\Programs\Python\Python311\python.exe"
if not defined PYTHON_EXE call :select_python "python"

if not defined PYTHON_EXE (
    call :log "error python-not-found"
    echo [ERROR] Could not find a Python interpreter with pip available.
    exit /b 1
)
call :log "python-selected path=%PYTHON_EXE%"

"%PYTHON_EXE%" -m src.ask_here_launcher ping >nul 2>nul
set "AITOOLS_ASK_HERE_PING_EXIT=%errorlevel%"
call :log "ping-exit code=%AITOOLS_ASK_HERE_PING_EXIT%"
if not "%AITOOLS_ASK_HERE_PING_EXIT%"=="0" (
    call :log "server-not-ready starting-background-server"
    call :start_background_server
    set "AITOOLS_ASK_HERE_START_EXIT=%errorlevel%"
    call :log "start-background-server-exit code=!AITOOLS_ASK_HERE_START_EXIT!"
    if not "!AITOOLS_ASK_HERE_START_EXIT!"=="0" exit /b !AITOOLS_ASK_HERE_START_EXIT!
    "%PYTHON_EXE%" -m src.ask_here_launcher wait --timeout 35
    set "AITOOLS_ASK_HERE_WAIT_EXIT=%errorlevel%"
    call :log "wait-exit code=!AITOOLS_ASK_HERE_WAIT_EXIT!"
    if not "!AITOOLS_ASK_HERE_WAIT_EXIT!"=="0" exit /b !AITOOLS_ASK_HERE_WAIT_EXIT!
)
if "%AITOOLS_ASK_HERE_PING_EXIT%"=="0" (
    call :log "server-ready no-start-needed"
)

"%PYTHON_EXE%" -m src.ask_here_launcher dispatch --path "%AITOOLS_ASK_HERE_PATH%"
set "AITOOLS_ASK_HERE_DISPATCH_EXIT=%errorlevel%"
call :log "dispatch-exit code=%AITOOLS_ASK_HERE_DISPATCH_EXIT%"
exit /b %AITOOLS_ASK_HERE_DISPATCH_EXIT%

:start_background_server
set "AITOOLS_WEB_STDOUT=%cd%\.runtime\aitools-server.log"
set "AITOOLS_WEB_STDERR=%cd%\.runtime\aitools-server.err.log"
set "AITOOLS_WORKSPACE_ROOT=%cd%"
set "AITOOLS_PYTHON_EXE=%PYTHON_EXE%"
call :log "start-background-server stdout=%AITOOLS_WEB_STDOUT% stderr=%AITOOLS_WEB_STDERR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $python=$env:AITOOLS_PYTHON_EXE; $root=$env:AITOOLS_WORKSPACE_ROOT; $stdout=$env:AITOOLS_WEB_STDOUT; $stderr=$env:AITOOLS_WEB_STDERR; $env:AGENTPARK_RESTORE_DESKTOP_PETS='1'; $arguments=@('-m','src.fast_api','--workspace-root',$root); Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr"
if errorlevel 1 (
    call :log "error start-background-server-failed code=%errorlevel%"
    echo [ERROR] Failed to start AgentPark web server in background.
    exit /b %errorlevel%
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

:log
>>"%AITOOLS_ASK_HERE_LOG%" echo [%time%] %~1
exit /b 0
