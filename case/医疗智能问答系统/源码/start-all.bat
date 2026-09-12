@echo off
chcp 65001 >nul
setlocal

REM ============================================================
REM  医疗智能问答系统 - 一键启动前后端
REM  用法：双击本文件，或在 cmd 中执行 start-all.bat
REM  后端 Flask -> http://localhost:5000
REM  前端 Vite  -> http://localhost:3000
REM ============================================================

if /i "%~1"=="backend"  goto :run_backend
if /i "%~1"=="frontend" goto :run_frontend

set "BACKEND=%~dp0backend"
set "FRONTEND=%~dp0frotend"
set "PY=%BACKEND%\.venv\Scripts\python.exe"

echo ============================================
echo   医疗智能问答系统 - 启动中
echo ============================================
echo.

if not exist "%PY%" (
    echo [错误] 未找到后端虚拟环境：
    echo        %PY%
    echo        请先执行：cd backend ^&^& python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist "%FRONTEND%\node_modules" (
    echo [提示] 前端依赖未安装，正在执行 pnpm install ...
    pushd "%FRONTEND%"
    call pnpm install
    popd
    if errorlevel 1 (
        echo [错误] pnpm install 失败，请检查网络或 pnpm 环境。
        pause
        exit /b 1
    )
)

echo [检查] 端口占用情况 ...
netstat -ano | findstr ":5000 " | findstr "LISTENING" >nul 2>&1 && echo    [!] 端口 5000 已被占用，后端可能启动失败
netstat -ano | findstr ":3000 " | findstr "LISTENING" >nul 2>&1 && echo    [!] 端口 3000 已被占用，前端可能启动失败

echo.
echo [启动] 后端 Flask  -^>  http://localhost:5000
start "医疗问答-后端" "%~f0" backend

echo [启动] 前端 Vite   -^>  http://localhost:3000
start "医疗问答-前端" "%~f0" frontend

echo.
echo 两个服务已在新窗口启动，关闭对应窗口即可停止。
echo 后端首次需要加载 6 个模型，请等待日志出现「模型加载完成」后再访问前端。
echo.
pause
goto :eof


:run_backend
cd /d "%~dp0backend"
echo [后端] 工作目录: %CD%
echo [后端] 启动 Flask ...
echo.
".venv\Scripts\python.exe" run.py
echo.
echo [后端] 进程已退出，退出码: %errorlevel%
pause
goto :eof


:run_frontend
cd /d "%~dp0frotend"
echo [前端] 工作目录: %CD%
echo [前端] 启动 Vite ...
echo.
call pnpm dev
echo.
echo [前端] 进程已退出，退出码: %errorlevel%
pause
goto :eof
