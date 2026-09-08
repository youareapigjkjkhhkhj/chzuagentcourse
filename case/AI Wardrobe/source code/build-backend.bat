@echo off
setlocal enabledelayedexpansion
rem ============================================================
rem  Kaleido backend packaging script (portable)
rem  - Locates the project relative to THIS script's directory,
rem    no hardcoded paths. Works on any machine.
rem  - Requires: JDK 21, Maven 3.8+ on PATH (or JAVA_HOME/M2_HOME)
rem  - Output:   <script dir>\deploy-output\backend\
rem ============================================================

set "SCRIPT_DIR=%~dp0"
set "BACKEND_DIR=%SCRIPT_DIR%backend"
set "TEMPLATE_DIR=%SCRIPT_DIR%deploy-templates"
set "OUT_DIR=%SCRIPT_DIR%deploy-output\backend"

if not exist "%BACKEND_DIR%\pom.xml" (
    echo [ERROR] backend\pom.xml not found next to this script.
    echo         Keep this script inside "source code" directory.
    exit /b 1
)

rem ---- 1. prerequisite check --------------------------------
where mvn >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Maven not found on PATH. Install Maven 3.8+ first.
    exit /b 1
)
where java >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Java not found on PATH. Install JDK 21 first.
    exit /b 1
)
echo [INFO] Using:
call mvn -v | findstr /i "Apache Maven"
java -version 2>&1 | findstr /i "version"

rem ---- 2. production fix: sharding.yaml datasource host ------
rem 127.0.0.1 only works in dev; containers must reach "mysql"
set "SHARD=%BACKEND_DIR%\kaleido-common\kaleido-ds\src\main\resources\sharding.yaml"
findstr /c:"jdbc:mysql://127.0.0.1:3306/kaleido_" "%SHARD%" >nul 2>nul
if not errorlevel 1 (
    powershell -NoProfile -Command "$f='%SHARD%'; $t=[System.IO.File]::ReadAllText($f); $t=$t.Replace('jdbc:mysql://127.0.0.1:3306/kaleido_','jdbc:mysql://mysql:3306/kaleido_'); [System.IO.File]::WriteAllText($f,$t)"
    echo [FIX]   sharding.yaml datasource 127.0.0.1 -^> mysql (production mode)
) else (
    echo [OK]    sharding.yaml already points to mysql
)

rem ---- 3. verify spring-boot plugin declared in all 11 poms --
rem (root pom inherits spring-boot-starter-parent, which already
rem  binds the repackage goal; declaring the plugin is enough)
set "MISSING=0"
for %%m in (gateway auth admin notice) do (
    findstr /c:"spring-boot-maven-plugin" "%BACKEND_DIR%\kaleido-%%m\pom.xml" >nul 2>nul || (
        echo [ERROR] spring-boot-maven-plugin missing in kaleido-%%m\pom.xml
        set "MISSING=1"
    )
)
for %%m in (user wardrobe ai tag coin message recommend) do (
    findstr /c:"spring-boot-maven-plugin" "%BACKEND_DIR%\kaleido-biz\kaleido-%%m\pom.xml" >nul 2>nul || (
        echo [ERROR] spring-boot-maven-plugin missing in kaleido-biz\kaleido-%%m\pom.xml
        set "MISSING=1"
    )
)
if "%MISSING%"=="1" (
    echo [ERROR] Declare spring-boot-maven-plugin in the 11 service poms first
    echo         (see DEPLOY.md section 3.1), then re-run this script.
    exit /b 1
)
echo [OK]    spring-boot plugin declared in all 11 service poms

rem ---- 4. maven package ---------------------------------------
cd /d "%BACKEND_DIR%"
echo [INFO]  mvn clean package starting (skip tests) ...
call mvn clean package -DskipTests -pl ^
 kaleido-gateway,kaleido-auth,kaleido-admin,kaleido-notice,^
 kaleido-biz/kaleido-user,kaleido-biz/kaleido-wardrobe,kaleido-biz/kaleido-ai,^
 kaleido-biz/kaleido-tag,kaleido-biz/kaleido-coin,kaleido-biz/kaleido-message,^
 kaleido-biz/kaleido-recommend -am
if errorlevel 1 (
    echo [ERROR] Maven build FAILED.
    exit /b 1
)

rem ---- 5. collect jars ----------------------------------------
if exist "%OUT_DIR%\jars" rmdir /s /q "%OUT_DIR%\jars"
mkdir "%OUT_DIR%\jars" 2>nul
set "COPIED=0"
for %%m in (gateway auth admin notice) do (
    copy /y "%BACKEND_DIR%\kaleido-%%m\target\kaleido-%%m-1.0.0.jar" "%OUT_DIR%\jars\" >nul && set /a COPIED+=1
)
for %%m in (user wardrobe ai tag coin message recommend) do (
    copy /y "%BACKEND_DIR%\kaleido-biz\kaleido-%%m\target\kaleido-%%m-1.0.0.jar" "%OUT_DIR%\jars\" >nul && set /a COPIED+=1
)
if not "%COPIED%"=="11" (
    echo [ERROR] Expected 11 jars, copied %COPIED%. Check build output.
    exit /b 1
)

rem ---- 5.1 self-check: jars must point to mysql, never 127.0.0.1 ----
findstr /c:"jdbc:mysql://127.0.0.1:3306/kaleido_" "%BACKEND_DIR%\kaleido-common\kaleido-ds\target\classes\sharding.yaml" >nul 2>nul
if not errorlevel 1 (
    echo [ERROR] Built jars still contain 127.0.0.1:3306 datasource - they will fail inside containers.
    echo         This script was bypassed or the patch failed. Re-run THIS script, not plain mvn package.
    exit /b 1
)
echo [OK]    built jars datasource points to mysql:3306

rem ---- 6. ship Dockerfile -------------------------------------
copy /y "%TEMPLATE_DIR%\backend-Dockerfile" "%OUT_DIR%\Dockerfile" >nul

echo.
echo ============================================================
echo  Backend packaging DONE. 11 jars + Dockerfile at:
echo    %OUT_DIR%
echo  Next: upload this folder to server /opt/kaleido/backend
echo        and build images (DEPLOY.md section 6.1)
echo ============================================================
endlocal
