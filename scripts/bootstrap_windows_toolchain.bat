@echo off

call :detect_python
if not defined PYTHON_EXE (
    echo [INFO] Python was not found. Installing Python 3.12 with winget...
    call :install_python
    if errorlevel 1 exit /b 1
    call :detect_python
)
if not defined PYTHON_EXE (
    echo [ERROR] Python installation completed, but no usable Python with pip was found.
    echo [ERROR] Download Python from: https://www.python.org/downloads/windows/
    exit /b 1
)

if /I "%~1"=="python-only" goto bootstrap_complete

call :ensure_node_toolchain
if errorlevel 1 exit /b 1

call :ensure_setuptools
if errorlevel 1 exit /b 1

:bootstrap_complete
set "AGENTPARK_BOOTSTRAP_CANDIDATE="
set "AGENTPARK_NODE_TOOLCHAIN_READY="
exit /b 0

:detect_python
set "PYTHON_EXE="
call :select_python "%LocalAppData%\Programs\Python\Python314\python.exe"
if not defined PYTHON_EXE call :select_python "%UserProfile%\Miniconda3\python.exe"
if not defined PYTHON_EXE call :select_python "%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined PYTHON_EXE call :select_python "%ProgramFiles%\Python312\python.exe"
if not defined PYTHON_EXE call :select_python "%LocalAppData%\Programs\Python\Python311\python.exe"
if not defined PYTHON_EXE call :select_python "%ProgramFiles%\Python311\python.exe"
if not defined PYTHON_EXE call :select_python "python"
exit /b 0

:select_python
set "AGENTPARK_BOOTSTRAP_CANDIDATE=%~1"
if "%AGENTPARK_BOOTSTRAP_CANDIDATE%"=="" exit /b 0
if not "%AGENTPARK_BOOTSTRAP_CANDIDATE%"=="python" if not exist "%AGENTPARK_BOOTSTRAP_CANDIDATE%" exit /b 0
"%AGENTPARK_BOOTSTRAP_CANDIDATE%" --version >nul 2>nul
if errorlevel 1 exit /b 0
"%AGENTPARK_BOOTSTRAP_CANDIDATE%" -m pip --version >nul 2>nul
if errorlevel 1 (
    echo [INFO] Python found without pip: %AGENTPARK_BOOTSTRAP_CANDIDATE%
    echo [INFO] Bootstrapping pip with ensurepip...
    "%AGENTPARK_BOOTSTRAP_CANDIDATE%" -m ensurepip --upgrade
    if errorlevel 1 exit /b 0
    "%AGENTPARK_BOOTSTRAP_CANDIDATE%" -m pip --version >nul 2>nul
    if errorlevel 1 exit /b 0
)
set "PYTHON_EXE=%AGENTPARK_BOOTSTRAP_CANDIDATE%"
exit /b 0

:install_python
where winget >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python is missing and winget is not available for automatic installation.
    echo [ERROR] Install Python 3.12 from: https://www.python.org/downloads/windows/
    exit /b 1
)
winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity
if errorlevel 1 (
    echo [ERROR] Automatic Python 3.12 installation failed.
    echo [ERROR] Install Python manually from: https://www.python.org/downloads/windows/
    exit /b 1
)
exit /b 0

:ensure_node_toolchain
call :detect_node_toolchain
if defined AGENTPARK_NODE_TOOLCHAIN_READY (
    echo [INFO] Node.js and npm detected.
    exit /b 0
)
where winget >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Node.js or npm is missing and winget is not available for automatic installation.
    echo [ERROR] Install Node.js LTS from: https://nodejs.org/en/download
    exit /b 1
)
echo [INFO] Node.js or npm was not found. Installing Node.js LTS with winget...
winget install --id OpenJS.NodeJS.LTS -e --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity
if errorlevel 1 (
    echo [ERROR] Automatic Node.js LTS installation failed.
    echo [ERROR] Install Node.js manually from: https://nodejs.org/en/download
    exit /b 1
)
call :detect_node_toolchain
if not defined AGENTPARK_NODE_TOOLCHAIN_READY (
    echo [ERROR] Node.js installation completed, but node or npm is still unavailable.
    echo [ERROR] Restart Windows or install Node.js manually from: https://nodejs.org/en/download
    exit /b 1
)
echo [INFO] Node.js and npm installed successfully.
exit /b 0

:detect_node_toolchain
set "AGENTPARK_NODE_TOOLCHAIN_READY="
if exist "%ProgramFiles%\nodejs\node.exe" if exist "%ProgramFiles%\nodejs\npm.cmd" set "PATH=%ProgramFiles%\nodejs;%PATH%"
if exist "%LocalAppData%\Programs\nodejs\node.exe" if exist "%LocalAppData%\Programs\nodejs\npm.cmd" set "PATH=%LocalAppData%\Programs\nodejs;%PATH%"
where node >nul 2>nul
if errorlevel 1 exit /b 0
node --version >nul 2>nul
if errorlevel 1 exit /b 0
where npm >nul 2>nul
if errorlevel 1 exit /b 0
call npm --version >nul 2>nul
if errorlevel 1 exit /b 0
set "AGENTPARK_NODE_TOOLCHAIN_READY=1"
exit /b 0

:ensure_setuptools
"%PYTHON_EXE%" -c "from importlib.metadata import version; raise SystemExit(0 if int(version('setuptools').split('.')[0]) >= 64 else 1)" >nul 2>nul
if not errorlevel 1 (
    echo [INFO] Python build dependency already available: setuptools^>=64
    exit /b 0
)
echo [INFO] Installing Python build dependency: setuptools^>=64
"%PYTHON_EXE%" -m pip install "setuptools>=64"
if errorlevel 1 (
    echo [ERROR] Failed to install setuptools^>=64.
    exit /b 1
)
exit /b 0
