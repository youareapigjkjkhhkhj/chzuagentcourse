# EduAgentX 一键部署镜像（P5-A11 / §6）
#
# 干净机器上 `docker compose up -d`，三分钟内 http://host:5000 可用。
#
# 两段构建：前端在 node 阶段打出来，产物塞进运行镜像。最终镜像里没有 node、
# 没有 node_modules —— 它只是把 `frontend/dist` 交给后端托管（common/site.py）。
#
# 运行镜像里**没有 Chromium**：三种产物里最像浏览器的那个（PDF）走的是
# PyMuPDF 的 Story 排版（services/exports/pdf.py 的头注释写了为什么），
# 中文字库用的是 PyMuPDF 自带的那份。P5 §8 风险表里「镜像大 / 中文字体缺失」
# 这两条因此都不成立，代价是 PDF 的 CSS 只支持一个子集。

# --- 1. 前端产物 ---
FROM node:20-alpine AS webbuild
WORKDIR /build
# 先只拷清单再装依赖：源码变了不会让这一层缓存失效
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- 2. 运行时 ---
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production \
    FLASK_APP=app:create_app()

# 上面那个 FLASK_APP 是给 `docker compose exec app flask <子命令>` 用的：
# 带括号的工厂写法没法靠自动发现（Flask 只自动找 `app` / `wsgi` 变量），
# 而运维手册里让运维敲的就是这些短命令 —— 少了它每条命令都得自己补
# `--app "app:create_app()"`，那正是「照着文档敲却敲不通」的来源。

# gosu：入口脚本要以 root 修一次挂载目录的属主，然后**降权**到 app 用户跑。
# 没有它就只能整个容器跑 root，而 P5-F3 要的是非 root。
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

# 依赖单独一层：改代码不会重新下载依赖
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# 后端代码。`.env` 与 `data/` 由 .dockerignore 挡在外面（P5-F3）：
# 凭据进镜像 = 镜像一被推走，那把 Key 就跟着走了；数据则走卷。
COPY backend/ /app/backend/
# 前端产物由后端托管：FRONTEND_DIST 的缺省值是 PROJECT_ROOT/frontend/dist，
# 而 PROJECT_ROOT 就是 /app，所以这里放到 /app/frontend/dist 即可，不用再配变量。
COPY --from=webbuild /build/dist /app/frontend/dist

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app \
    && mkdir -p /app/backend/data \
    && chown -R app:app /app

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# 健康检查用 python 而不是 curl：镜像里已经有一个解释器了，
# 为一次 GET 再装一个二进制包不值得。compose 里那条 healthcheck 与它同源。
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import sys,urllib.request; \
u=urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=4); \
sys.exit(0 if u.status == 200 else 1)"

EXPOSE 5000

# 入口脚本会先跑迁移（见 docker/entrypoint.sh），再 exec gunicorn。
# 不给 CMD 传 shell 形式：exec 形式才能让 gunicorn 直接收到信号，
# `docker stop` 才会走优雅退出而不是等 10 秒后 SIGKILL。
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["gunicorn", "-c", "/app/backend/gunicorn.conf.py", "app:create_app()"]
