@echo off
echo ========================================
echo LLM Wiki知识管理平台 - 开发环境启动
echo ========================================

echo.
echo 1. 启动Docker基础服务...
docker-compose -f docker-compose.dev.yml up -d mysql redis milvus

echo.
echo 2. 等待数据库启动...
timeout /t 15 /nobreak

echo.
echo 3. 启动后端服务...
cd backend

REM 检查虚拟环境是否存在
if not exist ".venv" (
    echo 创建Python虚拟环境...
    python -m venv .venv
)

REM 激活虚拟环境
call .venv\Scripts\activate

REM 安装依赖
echo 安装Python依赖...
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

REM 启动Flask
echo 启动Flask服务...
start "Flask Backend" python run.py

cd ..

echo.
echo 4. 启动前端服务...
cd frontend

REM 检查node_modules是否存在
if not exist "node_modules" (
    echo 安装前端依赖...
    call npm install --registry=https://registry.npmmirror.com
)

REM 启动开发服务器
echo 启动前端开发服务器...
start "Vue Frontend" npm run dev

cd ..

echo.
echo ========================================
echo 开发环境启动完成！
echo ========================================
echo.
echo 前端访问地址: http://localhost:3000
echo 后端API地址: http://localhost:5000/api/v1
echo.
echo 默认管理员账户: admin / admin123456
echo.
echo 按任意键退出...
pause > nul