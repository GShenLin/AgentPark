@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Clears diagnostic logs and disposable run artifacts under the active memories root.
rem Node memory, archives, runtime state, configuration, and user-created assets are preserved.
cd /d "%~dp0"

set "MEMORIES_ROOT=%CD%\memories"
set "DRY_RUN=0"

:parse_args
if "%~1"=="" goto args_parsed
if /I "%~1"=="--root" (
    if "%~2"=="" (
        echo [ERROR] --root requires a directory path.
        exit /b 2
    )
    set "MEMORIES_ROOT=%~2"
    shift
    shift
    goto parse_args
)
if /I "%~1"=="--dry-run" set "DRY_RUN=1"
if /I "%~1"=="/dry-run" set "DRY_RUN=1"
shift
goto parse_args

:args_parsed
for %%I in ("%MEMORIES_ROOT%") do set "MEMORIES_ROOT=%%~fI"
if not exist "%MEMORIES_ROOT%\" (
    echo [ERROR] memories folder does not exist: "%MEMORIES_ROOT%"
    exit /b 2
)
for %%I in ("%MEMORIES_ROOT%\..") do set "PARENT_ROOT=%%~fI"
if /I "%PARENT_ROOT%"=="%MEMORIES_ROOT%" (
    echo [ERROR] refusing to clear logs from a filesystem root: "%MEMORIES_ROOT%"
    exit /b 2
)

set /a MATCHED=0
set /a DELETED=0
set /a FAILED=0

call :scan_pattern "runtime_events.jsonl"
call :scan_pattern "runtime_events.jsonl.lock"
call :scan_pattern "runtime.events.jsonl"
call :scan_pattern "runtime.events.jsonl.lock"
call :scan_pattern "runner.events.jsonl"
call :scan_pattern "runner.events.jsonl.lock"
call :scan_pattern "responses_payloads.jsonl"
call :scan_pattern "responses_payloads.jsonl.*.bak"
call :scan_node_files
call :scan_pattern "log.txt"
call :scan_http_debug
call :scan_named_directories "tasks"
call :scan_named_directories "tool_artifacts"

if "%DRY_RUN%"=="1" (
    echo Dry run complete. Matched !MATCHED! log files.
    exit /b 0
)

echo Cleared !DELETED! log files. Failed !FAILED! files. Matched !MATCHED! files.
if !FAILED! GTR 0 exit /b 1
exit /b 0

:scan_pattern
echo [SCAN] %~1
for /R "%MEMORIES_ROOT%" %%F in (%~1) do (
    if exist "%%~fF" if not exist "%%~fF\" call :process_file "%%~fF"
)
exit /b 0

:scan_node_files
echo [SCAN] node runtime history
for /D %%G in ("%MEMORIES_ROOT%\*") do (
    for /D %%N in ("%%~fG\*") do (
        for %%L in (
            "context_artifacts.jsonl"
            "context_artifacts.jsonl.lock"
            "agent_context_history.json"
            "agent_turn_context.json"
            "analysis_verification.json"
            "analysis_report.md"
            "analysis_report_appendix.md"
            "task_direction.json"
            "task_direction.json.lock"
        ) do (
            if exist "%%~fN\%%~L" call :process_file "%%~fN\%%~L"
        )
    )
)
exit /b 0

:scan_http_debug
set "DEBUG_ROOT=%MEMORIES_ROOT%\_http_debug"
echo [SCAN] _http_debug
if not exist "%DEBUG_ROOT%\" exit /b 0
for /R "%DEBUG_ROOT%" %%F in (*) do (
    if exist "%%~fF" if not exist "%%~fF\" call :process_file "%%~fF"
)
if "%DRY_RUN%"=="0" rmdir /S /Q "%DEBUG_ROOT%" 2>nul
exit /b 0

:scan_named_directories
echo [SCAN] %~1 directories
for /D /R "%MEMORIES_ROOT%" %%D in (%~1) do (
    if exist "%%~fD\" call :process_directory "%%~fD"
)
exit /b 0

:process_directory
for /R "%~1" %%F in (*) do (
    if exist "%%~fF" if not exist "%%~fF\" call :process_file "%%~fF"
)
if "%DRY_RUN%"=="0" (
    rmdir /S /Q "%~1" 2>nul
    if exist "%~1\" (
        set /a FAILED+=1
        echo [ERROR] Failed to delete directory: %~1
    )
)
exit /b 0

:process_file
set /a MATCHED+=1
if "%DRY_RUN%"=="1" exit /b 0
del /F /Q /A "%~1" >nul 2>&1
if errorlevel 1 (
    set /a FAILED+=1
    echo [ERROR] Failed to delete: %~1
) else (
    set /a DELETED+=1
)
exit /b 0
