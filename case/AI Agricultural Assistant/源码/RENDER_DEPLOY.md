# AgriGPT – Render 云部署指南（中文）

> 说明：本项目日常开发以**本地开发**为主（本地运行或 `docker-compose up`，见 `README.md` 与实训 12）。
> 本文档是**可选的云部署参考**：当需要把系统发布到公网演示时，可按本文在 Render 免费托管后端与前端。
> 该方案为无 Redis 的内存版部署（免费层限制）。

在 Render 上部署后端与前端，实现公网可访问的 AgriGPT。

---

## 前置准备

| 项目 | 说明 |
| --- | --- |
| GitHub 账号 | 代码需推送到 GitHub 仓库（把 `源码/` 目录作为仓库内容，或整个项目推送） |
| Render 账号 | [render.com](https://render.com) 注册（可用 GitHub 登录），免费额度 |
| Groq API Key | 从 console.groq.com 获取 |

---

## 第一部分：后端（API）

### 步骤 1：创建后端服务

1. 打开 [render.com](https://render.com) 并登录
2. 进入 **Dashboard**（仪表盘）
3. 点击 **New +** → 选择 **Web Service**（Web 服务）

### 步骤 2：连接代码仓库

1. 若未连接过：点 **Connect account** → 选择 **GitHub** → 授权
2. 找到项目仓库并点击 **Connect**（连接）

### 步骤 3：后端基础设置

| 配置项 | 值 |
| --- | --- |
| **Name**（名称） | `agrigpt-api` |
| **Region**（区域） | Oregon（美西）或最近的区域 |
| **Branch**（分支） | `main` |

### 步骤 4：运行时设置（选 Python 原生，避免 Docker 报错）

1. **Runtime**（运行时）设为 **Python 3**（不要选 Docker）
2. **Root Directory**（根目录）：
   - 仓库根目录直接包含 `backend/` → 留空
   - 推送的是整个实训项目文件夹 → 填 `源码`
3. **Build Command**（构建命令）：

   ```text
   pip install -r backend/requirements.txt
   ```

4. **Start Command**（启动命令）：

   ```text
   PYTHONPATH=. uvicorn backend.main:app --host 0.0.0.0 --port $PORT
   ```

### 步骤 5：实例规格

选择 **Free**（免费）。免费额度约每月 750 小时；服务闲置 15 分钟后会休眠。

### 步骤 6：环境变量

点击 **Advanced** → **Add Environment Variable**（添加环境变量）：

必填：

| Key | Value |
| --- | --- |
| `GROQ_API_KEY` | 你的 Groq API Key（console.groq.com 获取） |

可选：

| Key | Value |
| --- | --- |
| `OPENWEATHER_API_KEY` | OpenWeather Key（启用天气功能） |

### 步骤 7：部署与验证

1. 点击 **Create Web Service** 开始部署
2. 等待构建完成（约 5–10 分钟）
3. 部署成功后记下服务地址（如 `https://agrigpt-api.onrender.com`）
4. 验证健康检查：

   ```bash
   curl https://agrigpt-api.onrender.com/health
   ```

   返回示例：

   ```json
   {
     "status": "OK",
     "service": "AgriGPT Backend",
     "llm": "groq",
     "model": "llama-3.3-70b-versatile"
   }
   ```

---

## 第二部分：前端（静态站点）

### 步骤 8：创建前端服务

1. 在 Dashboard 点击 **New +** → 选择 **Static Site**（静态站点）
2. 选择同一个代码仓库并 **Connect**

### 步骤 9：前端设置

| 配置项 | 值 |
| --- | --- |
| **Name**（名称） | `agrigpt` |
| **Branch**（分支） | `main` |
| **Root Directory**（根目录） | `frontend`（若代码嵌套在 `源码/` 下则填 `源码/frontend`） |

### 步骤 10：构建与发布

| 配置项 | 值 |
| --- | --- |
| **Build Command**（构建命令） | `npm install && npm run build` |
| **Publish Directory**（发布目录） | `dist` |

### 步骤 11：环境变量（重要）

展开 **Environment** / **Environment Variables**，添加：

| Key | Value |
| --- | --- |
| `VITE_API_BASE_URL` | `https://YOUR-BACKEND-URL.onrender.com` |

把 `YOUR-BACKEND-URL` 替换为步骤 7 得到的后端地址（如 `https://agrigpt-api.onrender.com`，**末尾不带斜杠**）。

> 不配置该变量时，前端默认请求 `http://localhost:8000`，在公网访问时会失败。

### 步骤 12：部署与验证

1. 点击 **Create Static Site**
2. 等待构建（约 2–3 分钟）
3. 记下前端地址（如 `https://agrigpt.onrender.com`）
4. 浏览器打开前端地址，发一条文本提问验证（如"小麦该施什么肥？"）
5. 若后端处于休眠，首次请求约需 1 分钟唤醒；之后会恢复正常速度

---

## 本地开发方式（推荐日常使用）

云部署仅用于发布演示，日常开发请优先使用本地方式：

**方式一：本地分进程开发**

```powershell
# 终端 1：后端
cd 源码
uvicorn backend.main:app --reload        # http://localhost:8000

# 终端 2：前端
cd 源码/frontend
npm install
npm run dev                              # http://localhost:8080
```

**方式二：容器一键启动**

```powershell
cd 源码
docker-compose up --build                # 前端 http://localhost:3000
```

本地开发需要 `.env`（从 `backend/env.example` 复制，详见实训 01）。

---

## 总结

| 服务 | 类型 | 示例地址 |
| --- | --- | --- |
| 后端 | Web Service（Python 3） | `https://agrigpt-api.onrender.com` |
| 前端 | Static Site | `https://agrigpt.onrender.com` |

**免费层限制**：后端闲置 15 分钟休眠，首次请求约 1 分钟唤醒；前端不休眠。

## 常见问题

| 问题 | 解决 |
| --- | --- |
| 部署失败：`backend/requirements.txt` 找不到 | 检查 Root Directory 是否与仓库结构匹配（见步骤 4/步骤 9） |
| 前端页面能打开但提问报错 | 确认 `VITE_API_BASE_URL` 已配置且末尾无斜杠 |
| 首次请求很慢 | 免费后端休眠唤醒所致，等待约 1 分钟 |
| 上传文件超限 | 免费实例有请求体限制，压缩图片后重试 |
