@echo off
rem =====================================================================
rem  双击这个文件 = 起后端 :5000 + 前端 :5173，等两个都能连上再开浏览器。
rem
rem  它自己不做启动逻辑，只是找到 Git Bash 转交给 scripts\dev.sh ——
rem  启动、等就绪、Ctrl+C 收摊都只有那一份实现（README 第 4 节）。
rem  想看 --force 之类的参数：在 Git Bash 里直接 bash scripts/dev.sh。
rem =====================================================================
chcp 65001 >nul
setlocal
title EduAgentX 开发服务（后端 5000 + 前端 5173）

set "ROOT=%~dp0"
set "ROOT=%ROOT:\=/%"

set "BASH="
for %%P in (
  "%ProgramFiles%\Git\bin\bash.exe"
  "%ProgramFiles(x86)%\Git\bin\bash.exe"
  "%LocalAppData%\Programs\Git\bin\bash.exe"
) do if not defined BASH if exist %%P set "BASH=%%~fP"

if not defined BASH (
  for /f "delims=" %%B in ('where bash 2^>nul') do if not defined BASH set "BASH=%%B"
)

if not defined BASH (
  echo 找不到 Git Bash。
  echo   装一个 Git for Windows：https://git-scm.com/download/win
  echo   或者改用 PowerShell 入口：.\scripts\dev.ps1
  echo.
  pause
  exit /b 1
)

"%BASH%" -lc "exec bash '%ROOT%scripts/dev.sh' %*"
set "CODE=%ERRORLEVEL%"

rem 起不来时别让窗口一闪而过 —— 双击的人得看到报错才知道出了什么事。
rem 130 与 C000013A 都是 Ctrl+C 正常收摊，那两种情况不用拦。
if "%CODE%"=="0" goto done
if "%CODE%"=="130" goto done
if "%CODE%"=="-1073741510" goto done
echo.
echo 启动脚本退出（返回码 %CODE%），原因在上面。
pause

:done
endlocal
