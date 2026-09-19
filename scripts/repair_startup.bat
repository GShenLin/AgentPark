@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
rem Recovery only needs Python; a broken Node toolchain must not block diagnosis.
call "%~dp0bootstrap_windows_toolchain.bat" python-only
if errorlevel 1 exit /b 1
"%PYTHON_EXE%" -m src.startup_repair --workspace-root "%CD%" --failure-log "%~1"
exit /b %errorlevel%
