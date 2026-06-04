@echo off
setlocal

rem Switch to the script directory to ensure relative paths work
cd /d "%~dp0"
set "PYTHON_EXE="
call :select_python "%LocalAppData%\Programs\Python\Python314\python.exe"
if not defined PYTHON_EXE call :select_python "%UserProfile%\Miniconda3\python.exe"
if not defined PYTHON_EXE call :select_python "%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined PYTHON_EXE call :select_python "%LocalAppData%\Programs\Python\Python311\python.exe"
if not defined PYTHON_EXE call :select_python "python"

if not defined PYTHON_EXE (
    echo [ERROR] Could not find a Python interpreter with pip available.
    echo [ERROR] Install Python with pip, or update build_and_run.bat with the Python path for this machine.
    pause
    exit /b 1
)

echo [INFO] Using Python: %PYTHON_EXE%

echo [INFO] Starting WebUI Build Process...

rem Navigate to webui directory
cd webui
echo [INFO] Current working directory: %cd%

rem Optional: Ensure dependencies are installed if node_modules is missing
if not exist "node_modules" (
    echo [INFO] node_modules not found. Running npm install...
    call npm install
)

echo [INFO] Compiling WebUI...
call npm run build

if %errorlevel% neq 0 (
    echo [ERROR] WebUI build failed with error code %errorlevel%
    pause
    exit /b %errorlevel%
)

echo [INFO] WebUI build successful.

rem Return to root directory
cd ..

echo [INFO] Installing/updating Python dependencies...
"%PYTHON_EXE%" -m pip install -e .

if %errorlevel% neq 0 (
    echo [ERROR] Python dependency install failed with error code %errorlevel%
    pause
    exit /b %errorlevel%
)

echo [INFO] Starting AITools server...

"%PYTHON_EXE%" -m src.fast_api

endlocal
pause

exit /b 0

:select_python
set "CANDIDATE=%~1"
if "%CANDIDATE%"=="" exit /b 0
if not "%CANDIDATE%"=="python" if not exist "%CANDIDATE%" exit /b 0
"%CANDIDATE%" -m pip --version >nul 2>nul
if errorlevel 1 exit /b 0
set "PYTHON_EXE=%CANDIDATE%"
exit /b 0
