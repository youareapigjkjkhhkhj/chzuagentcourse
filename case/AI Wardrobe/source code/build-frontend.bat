@echo off
setlocal enabledelayedexpansion
rem ============================================================
rem  Kaleido frontend packaging script (portable)
rem  - Locates the project relative to THIS script's directory.
rem  - Requires: Node 18+, pnpm 8.x
rem  - Output:   <script dir>\deploy-output\frontend\
rem ============================================================

set "SCRIPT_DIR=%~dp0"
set "FRONTEND_DIR=%SCRIPT_DIR%frontend"
set "TEMPLATE_DIR=%SCRIPT_DIR%deploy-templates"
set "OUT_DIR=%SCRIPT_DIR%deploy-output\frontend"

if not exist "%FRONTEND_DIR%\package.json" (
    echo [ERROR] frontend\package.json not found next to this script.
    exit /b 1
)

rem ---- 1. prerequisite check --------------------------------
where node >nul 2>nul || (echo [ERROR] Node not found. Install Node 18+. & exit /b 1)
where pnpm >nul 2>nul || (
    echo [ERROR] pnpm not found. Install it with: npm install -g pnpm
    exit /b 1
)
for /f "tokens=*" %%v in ('node -v') do echo [INFO] Node %%v
for /f "tokens=*" %%v in ('pnpm -v') do echo [INFO] pnpm %%v

rem ---- 2. production env fix: disable mock -------------------
set "ENVPRO=%FRONTEND_DIR%\.env.pro"
if exist "%ENVPRO%" (
    findstr /c:"VITE_USE_MOCK=true" "%ENVPRO%" >nul 2>nul
    if not errorlevel 1 (
        powershell -NoProfile -Command "$f='%ENVPRO%'; $t=[System.IO.File]::ReadAllText($f); $t=$t.Replace('VITE_USE_MOCK=true','VITE_USE_MOCK=false'); [System.IO.File]::WriteAllText($f,$t)"
        echo [FIX]   .env.pro VITE_USE_MOCK=true -^> false
    ) else (
        echo [OK]    .env.pro VITE_USE_MOCK already false
    )
)

rem ---- 3. install & build ------------------------------------
cd /d "%FRONTEND_DIR%"
echo [INFO]  pnpm install ...
call pnpm install
if errorlevel 1 (echo [ERROR] pnpm install FAILED. & exit /b 1)

echo [INFO]  pnpm run build:pro ...
call pnpm run build:pro
if errorlevel 1 (echo [ERROR] frontend build FAILED. & exit /b 1)

if not exist "%FRONTEND_DIR%\dist-pro" (
    echo [ERROR] dist-pro not generated. Check build output.
    exit /b 1
)

rem ---- 4. collect artifacts ----------------------------------
if exist "%OUT_DIR%" rmdir /s /q "%OUT_DIR%"
mkdir "%OUT_DIR%" 2>nul
xcopy "%FRONTEND_DIR%\dist-pro" "%OUT_DIR%\dist-pro\" /e /i /q >nul
copy /y "%TEMPLATE_DIR%\frontend-Dockerfile" "%OUT_DIR%\Dockerfile" >nul
copy /y "%TEMPLATE_DIR%\nginx.conf" "%OUT_DIR%\nginx.conf" >nul

echo.
echo ============================================================
echo  Frontend packaging DONE. dist-pro + Dockerfile + nginx.conf:
echo    %OUT_DIR%
echo  Next: upload to server /opt/kaleido/frontend and build
echo        image (DEPLOY.md section 6.2)
echo ============================================================
endlocal
