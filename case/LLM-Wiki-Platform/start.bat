@echo off
echo ========================================
echo LLM Wiki知识管理平台 - 启动脚本
echo ========================================

echo.
echo 1. 检查Docker是否安装...
docker --version
if %errorlevel% neq 0 (
    echo 错误: 请先安装Docker
    pause
    exit /b 1
)

echo.
echo 2. 启动Docker服务...
docker-compose up -d

echo.
echo 3. 等待服务启动...
timeout /t 30 /nobreak

echo.
echo 4. 服务状态...
docker-compose ps

echo.
echo ========================================
echo 服务启动完成！
echo ========================================
echo.
echo 前端访问地址: http://localhost
echo 后端API地址: http://localhost:5000/api/v1
echo.
echo 默认管理员账户: admin / admin123456
echo.
echo 按任意键退出...
pause > nul