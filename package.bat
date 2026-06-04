@echo off
setlocal
cd /d "%~dp0"
set PYTHONHOME=
set PYTHONPATH=
set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python314\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

echo [INFO] Building WebUI...
pushd webui
if not exist "node_modules" (
  call npm.cmd install
  if errorlevel 1 goto :fail_webui
)
call npm.cmd run build
if errorlevel 1 goto :fail_webui
popd

echo [INFO] Packaging server executable...
if exist "dist\AITools.exe" del /f /q "dist\AITools.exe" >nul 2>nul
"%PYTHON_EXE%" -m PyInstaller --noconfirm --onefile --name AITools --add-data "webui\dist;webui\dist" --collect-submodules src --collect-submodules fastapi --collect-submodules uvicorn --exclude-module flask src\fast_api.py
if errorlevel 1 goto :fail
if not exist "dist\AITools.exe" goto :fail

call :mirror_dir "config" "dist\config"
if errorlevel 1 goto :fail
call :mirror_dir "functions" "dist\functions"
if errorlevel 1 goto :fail
call :mirror_dir "nodes" "dist\nodes"
if errorlevel 1 goto :fail

echo [INFO] Package complete: dist\AITools.exe
endlocal
exit /b 0

:mirror_dir
set "SRC=%~1"
set "DST=%~2"
if not exist "%SRC%" (
  echo [ERROR] Missing source directory: %SRC%
  exit /b 1
)
echo [INFO] Copying %SRC% to %DST%...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$src = Resolve-Path '%SRC%';" ^
  "$dst = '%DST%';" ^
  "if (Test-Path $dst) { Remove-Item -Recurse -Force $dst };" ^
  "New-Item -ItemType Directory -Force -Path $dst | Out-Null;" ^
  "Copy-Item -Path (Join-Path $src '*') -Destination $dst -Recurse -Force -Exclude '__pycache__','*.pyc'"
if errorlevel 1 (
  echo [ERROR] Failed to copy %SRC% to %DST%
  exit /b 1
)
exit /b 0

:fail_webui
popd

:fail
endlocal
exit /b 1
