@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

echo ==================================================
echo   交互输入测试脚本 v1.0 (Batch)
echo ==================================================
echo.

REM 测试1: 普通文本输入
set "name="
set /p "name=[1/4] 请输入你的名字: "
echo     你好, !name!
echo.

REM 测试2: YES/NO 确认
set "ans="
set /p "ans=[2/4] 是否继续测试? (yes/no): "
set "ans=!ans: =!"
if /i "!ans!"=="yes" goto continue_test
if /i "!ans!"=="y" goto continue_test
echo     收到，测试中止。
exit /b 0

:continue_test
echo     继续测试...
echo.

REM 测试3: 数字输入
:numloop
set "numstr="
set /p "numstr=[3/4] 请输入一个 1-10 的数字: "
set "numstr=!numstr: =!"
echo(!numstr!| findstr /r "^[1-9]$ ^10$" >nul
if errorlevel 1 goto numbad
set /a square=!numstr! * !numstr!
echo     你输入的数字平方是: !square!
goto numdone

:numbad
echo     数字无效，请重试。
goto numloop

:numdone
echo.

REM 测试4: 倒计时 (可测试 Ctrl+C)
echo [4/4] 倒计时 10 秒，可以按 Ctrl+C 中断...
for /L %%i in (10,-1,1) do (
    echo     倒计时: %%i...
    timeout /t 1 /nobreak >nul
)

echo.
echo ==================================================
echo   所有测试通过!
echo ==================================================
