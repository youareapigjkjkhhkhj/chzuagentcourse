@echo off

cd /d "%~dp0"

if not exist "node_modules\electron-builder" (
    call npm install --save-dev electron-builder
)

echo Building portable exe...
echo.

call npm run build
if errorlevel 1 (
    echo Build failed
    pause
    exit /b 1
)

call npm run dist:win:portable

echo.
echo Done! Output in release folder
pause
