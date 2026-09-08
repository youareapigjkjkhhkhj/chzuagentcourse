@echo off

cd /d "%~dp0"

echo ============================================
echo   AgentBuddy Build Tool
echo ============================================
echo.

if not exist "package.json" (
    echo [ERROR] package.json not found
    pause
    exit /b 1
)

echo [1/4] Building...
call npm run build
if errorlevel 1 (
    echo [ERROR] Build failed
    pause
    exit /b 1
)

echo [2/4] Packaging portable EXE...
set ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/
call npx electron-builder --win portable
if errorlevel 1 (
    echo [ERROR] Package failed
    pause
    exit /b 1
)

echo [3/4] Copying exe...
if exist "release2\AgentBuddy.exe" (
    copy /y "release2\AgentBuddy.exe" "release\AgentBuddy.exe" >nul 2>&1
    mkdir release 2>nul
    copy /y "release2\AgentBuddy.exe" "release\AgentBuddy.exe" >nul
)

echo [4/4] Done!
echo.
echo ============================================
echo   Output: release\AgentBuddy.exe
echo   (also in release2\AgentBuddy.exe)
echo ============================================
echo.
pause