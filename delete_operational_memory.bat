@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Deletes every operational_memory.json file under the configured memories folder.
cd /d "%~dp0"

set "MEMORIES_ROOT=%CD%\memories"
set "TARGET_NAME=operational_memory.json"
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

if not exist "%MEMORIES_ROOT%\" (
    echo [ERROR] memories folder does not exist: "%MEMORIES_ROOT%"
    exit /b 2
)

set /a MATCHED=0
set /a DELETED=0
set /a FAILED=0

for /R "%MEMORIES_ROOT%" %%F in (%TARGET_NAME%) do (
    if exist "%%F" (
        set /a MATCHED+=1
        if "!DRY_RUN!"=="1" (
            echo [DRY-RUN] Would delete: %%F
        ) else (
            echo Deleting: %%F
            del /F /Q "%%F"
            if errorlevel 1 (
                set /a FAILED+=1
                echo [ERROR] Failed to delete: %%F
            ) else (
                set /a DELETED+=1
            )
        )
    )
)

if "%DRY_RUN%"=="1" (
    echo Dry run complete. Matched !MATCHED! files.
    exit /b 0
)

echo Deleted !DELETED! files. Failed !FAILED! files. Matched !MATCHED! files.
if !FAILED! GTR 0 exit /b 1
exit /b 0
