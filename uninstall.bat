@echo off
setlocal EnableExtensions

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

echo [INFO] Removing AgentPark context menu entries...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $paths=@('HKCU:\Software\Classes\*\shell\AgentPark','HKCU:\Software\Classes\Directory\shell\AgentPark','HKCU:\Software\Classes\Directory\Background\shell\AgentPark'); foreach ($path in $paths) { if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force } }; $classes='HKCU:\Software\Classes'; if (Test-Path -LiteralPath $classes) { $stale=@(Get-ChildItem -LiteralPath $classes -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.PSChildName -eq 'AgentPark' -and $_.Name.EndsWith('\shell\AgentPark', [System.StringComparison]::OrdinalIgnoreCase) } | Select-Object -ExpandProperty PSPath); foreach ($path in $stale) { Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue } }"
if errorlevel 1 (
    echo [ERROR] Failed to remove AgentPark context menu entries.
    exit /b %errorlevel%
)

echo [INFO] AgentPark context menu entries removed.
exit /b 0
