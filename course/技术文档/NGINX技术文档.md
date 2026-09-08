# NGINX 技术文档

---

## 目录

1. [NGINX 概述与核心架构](#1-nginx-概述与核心架构)
2. [安装与目录结构](#2-安装与目录结构)
3. [配置文件体系与指令上下文](#3-配置文件体系与指令上下文)
4. [Location 匹配规则详解](#4-location-匹配规则详解)
5. [静态资源服务](#5-静态资源服务)
6. [反向代理](#6-反向代理)
7. [负载均衡](#7-负载均衡)
8. [缓存系统](#8-缓存系统)
9. [HTTPS / SSL / TLS 配置](#9-https--ssl--tls-配置)
10. [安全防护](#10-安全防护)
11. [性能优化](#11-性能优化)
12. [Stream 模块与四层代理](#12-stream-模块与四层代理)
13. [OpenResty 与 Lua 扩展](#13-openresty-与-lua-扩展)
14. [高可用方案（Keepalived）](#14-高可用方案keepalived)
15. [日志与监控](#15-日志与监控)
16. [运维与故障排查](#16-运维与故障排查)
17. [生产环境检查清单](#17-生产环境检查清单)

---

## 1. NGINX 概述与核心架构

### 1.1 什么是 NGINX

NGINX（发音 "engine-x"）是一款高性能的开源 Web 服务器、反向代理服务器和负载均衡器。由 Igor Sysoev 于 2004 年首次发布，以高并发、低内存占用和模块化设计著称。

**核心角色**:

| 角色 | 说明 |
|------|------|
| Web 服务器 | 直接响应静态文件请求（HTML/CSS/JS/图片等） |
| 反向代理 | 接收客户端请求，转发至后端服务器（Tomcat/Node.js/PHP-FPM 等） |
| 负载均衡器 | 通过轮询、IP 哈希等算法将流量分发到多个后端 |
| API 网关 | 结合 Lua/OpenResty 实现动态路由、认证、限流 |
| 流媒体服务器 | 支持 MP4/FLV/HLS 流媒体分发 |

### 1.2 核心架构：Master-Worker 进程模型

NGINX 采用 **多进程（master-worker）+ 单线程事件驱动** 的架构，这是其高性能的核心。

```
                    ┌──────────────────────────┐
                    │     Master Process       │
                    │  (root 权限，管理进程)     │
                    │  • 读取/解析配置文件        │
                    │  • 绑定监听端口            │
                    │  • 创建/管理 Worker 进程   │
                    │  • 接收信号(reload/stop)  │
                    │  • 不直接处理请求          │
                    └────────────┬─────────────┘
                                 │ fork()
            ┌────────────────────┼────────────────────┐
            │                    │                     │
  ┌─────────▼─────────┐ ┌───────▼─────────┐ ┌────────▼────────┐
  │   Worker Process 1 │ │  Worker Process 2 │ │ Worker Process N │
  │   (普通用户权限)    │ │  (普通用户权限)    │ │ (普通用户权限)    │
  │                    │ │                   │ │                  │
  │  ┌───────────────┐ │ │  ┌──────────────┐ │ │                  │
  │  │ Event Loop    │ │ │  │ Event Loop   │ │ │      ...         │
  │  │ (epoll/kqueue)│ │ │  │ (epoll)      │ │ │                  │
  │  └───────┬───────┘ │ │  └──────┬───────┘ │ │                  │
  │          │         │ │         │         │ │                  │
  │   处理数千并发连接   │ │  处理数千并发连接  │ │                  │
  └────────────────────┘ └───────────────────┘ └──────────────────┘
            │                    │                     │
            ▼                    ▼                     ▼
       ┌─────────────────────────────────────────────────┐
       │              共享内存 (Shared Memory)             │
       │  • 连接池  • 缓存元数据  • SSL 会话  • 锁         │
       └─────────────────────────────────────────────────┘
```

**Master 进程职责**:

| 职责 | 说明 |
|------|------|
| 启动与初始化 | 读取配置文件、绑定端口、创建共享内存 |
| 派生 Worker | 使用 `fork()` 创建多个子进程 |
| 监控与管理 | 接收信号（reload/stop），控制 Worker 生死 |
| 不参与请求处理 | 完全脱离业务逻辑，保证稳定性 |

**Worker 进程职责**:

| 职责 | 说明 |
|------|------|
| 处理网络请求 | 接收客户端连接、解析 HTTP、转发后端 |
| 事件驱动循环 | 基于 epoll 监听 socket 事件 |
| 非阻塞 I/O | 所有读写操作都不阻塞主线程 |
| 独立内存空间 | 各 Worker 之间不共享堆内存（避免锁） |

> **关键设计思想**: 不用多线程 → 避免线程切换开销和锁竞争；用多进程 + 单线程 → 每个进程专注一件事，无上下文干扰。

### 1.3 事件驱动模型：异步非阻塞 I/O

```
[事件循环开始]
       │
       ▼
  等待事件发生 (epoll_wait)  ◄───── 监控数千个连接的 I/O 状态
       │
       ├── 有新连接到来? ──→ accept() ──→ 加入监听队列
       │
       ├── 有数据可读?   ──→ recv()   ──→ 解析 HTTP 请求
       │
       ├── 需访问后端?   ──→ connect()──→ 发送请求(非阻塞)
       │
       ├── 后端返回?     ──→ recv()   ──→ 构造响应
       │
       ├── 可发送响应?   ──→ send()   ──→ 写回客户端
       │
       └── 连接关闭?     ──→ 释放资源 ──→ 等待下一次事件
```

**关键技术**:

- **epoll 机制（Linux）**: 高效的 I/O 事件通知机制，支持水平触发和边缘触发。单次 `epoll_wait` 调用可返回多个就绪事件，时间复杂度 O(1)
- **事件多路复用**: 单个 Worker 进程可同时监控数千个连接的 I/O 状态
- **非阻塞操作**: I/O 操作不阻塞进程，等待期间可处理其他连接

**不同平台的事件模型**:

| 平台 | 事件模型 | 说明 |
|------|---------|------|
| Linux | epoll | 最常用，高性能 |
| BSD/macOS | kqueue | 类似 epoll |
| Windows | IOCP | 性能较低，仅用于开发 |
| 通用 | select/poll | 性能较差，不推荐 |

**单线程事件驱动模型的优势**:

| 优势 | 说明 |
|------|------|
| 无锁设计 | 单线程内处理所有事件，无需加锁，消除锁竞争 |
| 避免线程上下文切换 | 线程切换约消耗 1μs，高并发下累积成显著开销 |
| 内存占用极低 | 不为每个连接创建独立线程和栈空间（每线程默认 1MB 栈） |
| 代码简洁 | 避免多线程同步问题，简化并发处理逻辑 |

### 1.4 NGINX vs Apache 性能对比

| 特性 | NGINX | Apache (prefork) |
|------|-------|-------------------|
| 并发模型 | 事件驱动（单线程多连接） | 多进程模型（一个连接一个进程） |
| 内存占用 | 低（约 2-10MB/Worker） | 高（约 20-30MB/进程） |
| 最大并发连接 | 理论无上限（受系统限制） | 数千（受内存限制） |
| 静态资源处理 | 零拷贝（sendfile） | 常规文件 I/O |
| 上下文切换开销 | 极低 | 高 |
| 适用场景 | 高并发 Web 服务、反向代理 | 动态内容较多的中小型网站 |

> 在相同硬件条件下（4 核 8GB 服务器），NGINX 可支持 **10 万+ 并发连接**，而 Apache 通常在 1 万连接时出现性能瓶颈。

### 1.5 模块化架构

NGINX 的功能由各种模块组成，采用模块化设计：

```
┌─────────────────────────────────────────────────────┐
│                    NGINX Core                       │
├──────────┬──────────┬──────────┬──────────┬─────────┤
│  HTTP    │  Stream  │  Mail    │  Event   │  SSL    │
│  Module  │  Module  │  Module  │  Module  │  Module │
├──────────┼──────────┼──────────┼──────────┼─────────┤
│ 反向代理  │ TCP/UDP  │ SMTP/    │ epoll/   │ TLS/SSL │
│ 负载均衡  │ 四层代理  │ IMAP/    │ kqueue   │ 加密    │
│ 缓存      │          │ POP3     │          │         │
│ Rewrite  │          │          │          │         │
│ Gzip     │          │          │          │         │
│ FastCGI  │          │          │          │         │
│ ...      │          │          │          │         │
├──────────┴──────────┴──────────┴──────────┴─────────┤
│              第三方扩展模块                           │
│  Lua(OpenResty) | ModSecurity(WAF) | Brotli | ...  │
└─────────────────────────────────────────────────────┘
```

**模块分类**:

- **核心模块**: HTTP、Stream、Mail、Event
- **标准 HTTP 模块**: proxy、upstream、fastcgi、gzip、rewrite、ssl、map、referer、limit_req 等
- **可选 HTTP 模块**: geo、image_filter、xslt、perl 等
- **第三方模块**: Lua（OpenResty）、ModSecurity（WAF）、Brotli 压缩、headers-more 等

---

## 2. 安装与目录结构

### 2.1 安装方式

```bash
# ========== Ubuntu / Debian ==========
sudo apt update
sudo apt install nginx

# ========== CentOS / RHEL ==========
sudo yum install epel-release
sudo yum install nginx

# ========== Docker ==========
docker run -d --name nginx -p 80:80 -p 443:443 nginx:latest

# ========== 源码编译（自定义模块） ==========
wget http://nginx.org/download/nginx-1.25.3.tar.gz
tar -zxvf nginx-1.25.3.tar.gz
cd nginx-1.25.3

./configure \
  --prefix=/usr/local/nginx \
  --with-http_ssl_module \
  --with-http_v2_module \
  --with-http_realip_module \
  --with-http_gzip_static_module \
  --with-stream \
  --with-stream_ssl_module \
  --add-module=/path/to/third-party-module

make && make install
```

### 2.2 目录结构

```
/etc/nginx/
├── nginx.conf              # 主配置文件
├── mime.types              # MIME 类型映射
├── fastcgi_params          # FastCGI 参数
├── proxy_params            # 代理参数
├── scgi_params             # SCGI 参数
├── uwsgi_params            # uWSGI 参数
├── snippets/               # 配置片段（可 include）
│   ├── ssl.conf            # SSL 通用配置
│   └── security-headers.conf
├── sites-available/        # 可用站点配置（Debian 系）
│   ├── default
│   └── example.com
├── sites-enabled/          # 已启用站点（软链接）
│   └── default -> /etc/nginx/sites-available/default
├── conf.d/                 # 额外配置目录（RHEL 系）
│   ├── default.conf
│   └── example.com.conf
└── modules/                # 动态模块

/var/log/nginx/
├── access.log              # 访问日志
└── error.log               # 错误日志

/var/www/html/              # 默认网站根目录

/usr/share/nginx/html/      # Docker 默认根目录

/var/cache/nginx/           # 缓存目录

/var/run/nginx.pid          # PID 文件
```

### 2.3 常用命令

```bash
nginx -t              # 测试配置语法
nginx -T              # 测试并打印完整配置
nginx -s reload       # 平滑重载配置（不中断服务）
nginx -s stop         # 快速停止
nginx -s quit         # 优雅停止（等待请求处理完毕）
nginx -s reopen       # 重新打开日志文件
nginx -V              # 查看版本和编译参数
nginx -c /path/to/conf # 指定配置文件

# systemd 管理
systemctl start nginx
systemctl stop nginx
systemctl restart nginx
systemctl reload nginx
systemctl status nginx
systemctl enable nginx   # 开机自启
```

---

## 3. 配置文件体系与指令上下文

### 3.1 配置文件层级结构

NGINX 配置文件采用嵌套的上下文结构，指令的作用域由其所在的上下文决定：

```
nginx.conf
│
├── main (全局上下文)
│   ├── worker_processes auto;
│   ├── worker_rlimit_nofile 65535;
│   │
│   ├── events { } (事件上下文)
│   │   └── worker_connections 10240;
│   │
│   ├── http { } (HTTP 上下文)
│   │   ├── upstream { } (上游服务器组)
│   │   ├── server { } (虚拟主机)
│   │   │   └── location { } (URL 路由)
│   │   │       └── location { } (嵌套 location)
│   │   └── ...
│   │
│   ├── stream { } (Stream 上下文 - 四层代理)
│   │   ├── upstream { }
│   │   └── server { }
│   │
│   └── mail { } (邮件代理上下文)
```

### 3.2 完整配置模板

```nginx
# ==================== 全局上下文 ====================
user nginx;                          # 运行用户
worker_processes auto;               # Worker 进程数（auto = CPU 核心数）
worker_cpu_affinity auto;            # CPU 亲和性自动绑定
worker_rlimit_nofile 65535;          # 每个 Worker 最大文件描述符
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

# ==================== 事件上下文 ====================
events {
    use epoll;                       # 事件模型（Linux 用 epoll）
    worker_connections 10240;        # 每个 Worker 最大连接数
    multi_accept on;                 # 一次接受多个新连接
    accept_mutex on;                 # Worker 间互斥锁（低负载时开启）
}

# ==================== HTTP 上下文 ====================
http {
    include       mime.types;        # MIME 类型映射
    default_type  application/octet-stream;

    # --- 日志格式 ---
    log_format main '$remote_addr - $remote_user [$time_local] '
                    '"$request" $status $body_bytes_sent '
                    '"$http_referer" "$http_user_agent" '
                    '$request_time $upstream_response_time';

    access_log /var/log/nginx/access.log main;

    # --- 核心性能参数 ---
    sendfile        on;              # 零拷贝传输
    tcp_nopush      on;              # 数据包合并
    tcp_nodelay     on;              # 禁用 Nagle 算法
    keepalive_timeout  65;           # 长连接超时
    keepalive_requests 1000;         # 单连接最大请求数
    client_max_body_size 10m;        # 最大请求体大小
    client_body_buffer_size 128k;    # 请求体缓冲区
    client_header_buffer_size 1k;    # 请求头缓冲区
    large_client_header_buffers 4 4k;

    # --- Gzip 压缩 ---
    gzip on;
    gzip_min_length 1024;
    gzip_comp_level 6;
    gzip_types text/plain text/css application/json application/javascript
               text/xml application/xml application/xml+rss text/javascript;

    # --- 文件缓存 ---
    open_file_cache max=200000 inactive=20s;
    open_file_cache_valid 30s;
    open_file_cache_min_uses 2;
    open_file_cache_errors on;

    # --- 限流区域定义 ---
    limit_req_zone $binary_remote_addr zone=general:10m rate=10r/s;
    limit_conn_zone $binary_remote_addr zone=conn_limit:10m;

    # --- 代理缓存路径 ---
    proxy_cache_path /var/cache/nginx/proxy levels=1:2
        keys_zone=app_cache:10m max_size=1g inactive=60m use_temp_path=off;

    # ==================== 上游服务器组 ====================
    upstream backend {
        server 192.168.1.101:8080 weight=3 max_fails=3 fail_timeout=30s;
        server 192.168.1.102:8080 weight=2 max_fails=3 fail_timeout=30s;
        server 192.168.1.103:8080 backup;
        keepalive 32;
    }

    # ==================== 虚拟主机 ====================
    server {
        listen 80;
        server_name example.com www.example.com;
        return 301 https://$host$request_uri;   # HTTP 强制跳转 HTTPS
    }

    server {
        listen 443 ssl http2;
        server_name example.com www.example.com;

        # SSL 配置
        ssl_certificate     /etc/nginx/ssl/example.com.crt;
        ssl_certificate_key /etc/nginx/ssl/example.com.key;
        ssl_protocols       TLSv1.2 TLSv1.3;
        ssl_ciphers         'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';
        ssl_session_cache   shared:SSL:10m;
        ssl_session_timeout 1d;

        # 安全头
        add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
        add_header X-Frame-Options "SAMEORIGIN" always;
        add_header X-Content-Type-Options "nosniff" always;

        # 根目录静态资源
        root /var/www/example.com;
        index index.html index.htm;

        # ==================== Location 路由 ====================
        # 精确匹配首页
        location = / {
            try_files $uri $uri/ /index.html;
        }

        # 静态资源（长缓存）
        location ~* \.(jpg|jpeg|png|gif|ico|css|js|svg|woff2?)$ {
            expires 30d;
            add_header Cache-Control "public, immutable";
            access_log off;
        }

        # API 反向代理
        location /api/ {
            limit_req zone=general burst=20 nodelay;
            proxy_pass http://backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_connect_timeout 5s;
            proxy_read_timeout 60s;
        }

        # WebSocket 支持
        location /ws/ {
            proxy_pass http://backend;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_read_timeout 3600s;
        }

        # 健康检查端点
        location = /health {
            access_log off;
            return 200 "OK";
            add_header Content-Type text/plain;
        }

        # 禁止访问隐藏文件
        location ~ /\. {
            deny all;
            access_log off;
            log_not_found off;
        }
    }
}
```

### 3.3 指令继承规则

```
http {
    # 在 http 层定义的指令，被所有 server 和 location 继承
    client_max_body_size 10m;

    server {
        # server 层可以覆盖 http 层的值
        client_max_body_size 20m;

        location /upload {
            # location 层可以覆盖 server 层的值
            client_max_body_size 100m;
        }

        location /api {
            # 继承 server 层的 20m
        }
    }
}
```

> **注意**: 部分指令（如 `proxy_set_header`）如果在一个 location 中重新定义，会**完全覆盖**而非合并父级的值。需要重新声明所有必要的 header。

---

## 4. Location 匹配规则详解

### 4.1 五种 Location 修饰符

Location 的匹配**不是按配置顺序**，而是按**修饰符优先级**匹配：

| 优先级 | 修饰符 | 名称 | 匹配行为 | 示例 |
|--------|--------|------|---------|------|
| 1（最高） | `=` | 精确匹配 | 完全匹配 URI，匹配后停止搜索 | `location = /favicon.ico` |
| 2 | `^~` | 前缀匹配停止 | 最长前缀匹配，匹配后**不再检查正则** | `location ^~ /static/` |
| 3 | `~` | 区分大小写正则 | 正则匹配，区分大小写 | `location ~ \.php$` |
| 3 | `~*` | 不区分大小写正则 | 正则匹配，不区分大小写 | `location ~* \.(jpg|png)$` |
| 4（最低） | 无 | 前缀匹配 | 前缀匹配，匹配后继续搜索正则 | `location /api` |

### 4.2 匹配算法完整流程

```
请求到达 /static/css/main.css
       │
       ▼
  ┌────────────────────────────┐
  │ Step 1: 检查所有 = 精确匹配  │  → 找到 location = /static/css/main.css?
  └────────────┬───────────────┘  → 是：直接使用，停止搜索
               │ 否
               ▼
  ┌────────────────────────────┐
  │ Step 2: 检查所有前缀匹配     │  → 找到最长的前缀匹配
  │ 记录最长前缀匹配            │     location /static/ ← 最长匹配
  └────────────┬───────────────┘
               │
               ▼
  ┌────────────────────────────┐
  │ Step 3: 最长前缀是否为 ^~?  │  → 是：停止正则搜索，使用此前缀
  └────────────┬───────────────┘  → 否：继续
               │
               ▼
  ┌────────────────────────────┐
  │ Step 4: 按配置顺序检查正则   │  → location ~* \.css$
  │ 找到第一个匹配的正则即停止   │     匹配！使用此正则 location
  └────────────┬───────────────┘
               │ 没有正则匹配
               ▼
  ┌────────────────────────────┐
  │ Step 5: 使用 Step 2 记录的   │  → 使用 location /static/
  │ 最长前缀匹配                │
  └────────────────────────────┘
```

### 4.3 配置示例与解析

```nginx
server {
    # 1. 精确匹配 - 仅匹配 URI "/"，最高优先级
    location = / {
        proxy_pass http://backend;
    }

    # 2. 前缀匹配停止 - 匹配 /static/ 开头，不检查后续正则
    location ^~ /static/ {
        root /var/www;
        expires 7d;
    }

    # 3. 区分大小写正则 - 匹配 .php 结尾
    location ~ \.php$ {
        fastcgi_pass unix:/var/run/php/php8.1-fpm.sock;
        fastcgi_index index.php;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    }

    # 4. 不区分大小写正则 - 匹配图片文件
    location ~* \.(jpg|jpeg|png|gif|ico|css|js|svg|woff2?)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
        access_log off;
    }

    # 5. 普通前缀匹配 - 兜底
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 6. 禁止访问隐藏文件（正则）
    location ~ /\. {
        deny all;
        log_not_found off;
    }
}
```

### 4.4 root vs alias

```nginx
# root: 将 URI 拼接到 root 路径后
# 请求 /static/img/logo.png → /var/www/static/img/logo.png
location /static/ {
    root /var/www;
}

# alias: 将匹配部分替换为 alias 路径
# 请求 /static/img/logo.png → /var/www/img/logo.png （注意结尾的 /）
location /static/ {
    alias /var/www/;
}

# root 适合：URI 路径与文件系统路径一致
# alias 适合：URI 路径与文件系统路径不一致（路径映射）
```

### 4.5 try_files 指令

```nginx
# 按顺序尝试文件/目录，全部不存在则 fallback
location / {
    # 1. 尝试 $uri 文件
    # 2. 尝试 $uri/ 目录
    # 3. fallback 到 /index.html
    try_files $uri $uri/ /index.html;
}

# SPA 单页应用路由
location / {
    try_files $uri $uri/ /index.html;
}

# 不存在时返回 404
location /images/ {
    try_files $uri =404;
}

# 内部重定向
location / {
    try_files $uri $uri/ @drupal;
}

location @drupal {
    fastcgi_pass ...;
}
```

### 4.6 rewrite 指令

```nginx
# rewrite regex replacement [flag]
# flag:
#   last     - 重写后重新搜索 location（内部重定向）
#   break    - 重写后不再搜索后续 rewrite，但仍用当前 location
#   redirect - 返回 302 临时重定向
#   permanent - 返回 301 永久重定向

server {
    # HTTP → HTTPS 永久重定向
    rewrite ^(.*)$ https://$host$1 permanent;

    # 旧路径 → 新路径
    rewrite ^/old/(.*)$ /new/$1 permanent;

    # 隐藏 .php 扩展名
    rewrite ^/api/(.*)$ /api/$1.php last;

    # 图片重写 + 变量捕获
    rewrite '^/images/([a-z]{2})/([a-z0-9]{5})/(.*)\.(png|jpg|gif)$' /data?file=$3.$4;
    set $image_file $3;
    set $image_type $4;

    # 开启 rewrite 日志（调试用）
    rewrite_log on;
}
```

### 4.7 内部重定向触发

以下指令会触发内部重定向，重新搜索 location：

| 指令 | 说明 |
|------|------|
| `index` | 访问目录时查找 index 文件 |
| `try_files` | fallback 到指定 URI |
| `rewrite ... last` | 重写后重新搜索 |
| `error_page` | 错误时重定向到指定 URI |

---

## 5. 静态资源服务

### 5.1 基础静态服务配置

```nginx
server {
    listen 80;
    server_name static.example.com;
    root /var/www/static;
    index index.html;

    # sendfile 零拷贝传输
    sendfile on;
    sendfile_max_chunk 128k;

    # 主 location
    location / {
        try_files $uri $uri/ =404;
    }

    # 图片 - 长缓存
    location ~* \.(jpg|jpeg|png|gif|webp|avif|svg|ico)$ {
        expires 365d;
        add_header Cache-Control "public, immutable";
        access_log off;

        # 文件描述符缓存
        open_file_cache max=10000 inactive=30s;
        open_file_cache_valid 60s;
        open_file_cache_min_uses 2;
        open_file_cache_errors on;
    }

    # CSS/JS - 中等缓存
    location ~* \.(css|js)$ {
        expires 30d;
        add_header Cache-Control "public";
        access_log off;
    }

    # 字体文件
    location ~* \.(woff|woff2|ttf|eot|otf)$ {
        expires 365d;
        add_header Cache-Control "public, immutable";
        add_header Access-Control-Allow-Origin "*";
        access_log off;
    }

    # 禁止访问源文件
    location ~* \.(scss|less|map)$ {
        deny all;
    }
}
```

### 5.2 大文件下载优化

```nginx
location /download/ {
    root /var/www/files;

    # 启用 sendfile 和 tcp_nopush（大文件场景）
    sendfile on;
    tcp_nopush on;

    # 限速下载（保护带宽）
    limit_rate 1m;                    # 限速 1MB/s
    limit_rate_after 10m;             # 前 10MB 不限速

    # 大文件支持
    client_max_body_size 0;           # 不限制请求体大小
    client_body_buffer_size 512k;
    proxy_max_temp_file_size 0;       # 不使用临时文件

    # 防盗链
    valid_referers none blocked server_names *.example.com example.com;
    if ($invalid_referer) {
        return 403;
    }
}
```

### 5.3 目录列表（文件服务器）

```nginx
location /files/ {
    root /var/www;
    autoindex on;                     # 开启目录列表
    autoindex_exact_size off;         # 显示可读文件大小
    autoindex_localtime on;           # 显示本地时间
    autoindex_format html;            # 格式: html | xml | json | jsonp
}
```

---

## 6. 反向代理

### 6.1 基础反向代理

```nginx
server {
    listen 80;
    server_name api.example.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
    }
}
```

### 6.2 完整反向代理配置

```nginx
server {
    listen 80;
    server_name api.example.com;

    location /api/ {
        # ==================== 代理目标 ====================
        proxy_pass http://backend;

        # ==================== 代理请求头 ====================
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;

        # ==================== 超时设置 ====================
        proxy_connect_timeout 5s;       # 与后端建立连接超时
        proxy_send_timeout 60s;         # 向后端发送请求超时
        proxy_read_timeout 60s;         # 读取后端响应超时

        # ==================== 缓冲区设置 ====================
        proxy_buffering on;             # 启用响应缓冲
        proxy_buffer_size 16k;          # 响应头缓冲区
        proxy_buffers 8 32k;            # 响应体缓冲区
        proxy_busy_buffers_size 64k;    # 忙碌缓冲区大小
        proxy_temp_file_write_size 128k; # 临时文件写入大小

        # ==================== HTTP 版本 ====================
        proxy_http_version 1.1;         # 使用 HTTP/1.1（支持长连接）

        # ==================== 长连接到后端 ====================
        proxy_set_header Connection ""; # 清除 Connection 头，启用长连接

        # ==================== 错误处理 ====================
        proxy_next_upstream error timeout http_502 http_503 http_504;
        proxy_next_upstream_tries 3;    # 最多尝试 3 个后端
        proxy_next_upstream_timeout 10s; # 总超时时间

        # ==================== 重定向处理 ====================
        proxy_redirect off;             # 不修改后端返回的 Location 头

        # ==================== 限流 ====================
        limit_req zone=general burst=20 nodelay;
    }
}
```

### 6.3 WebSocket 代理

```nginx
# WebSocket 需要特殊处理 Upgrade 和 Connection 头
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80;

    location /ws/ {
        proxy_pass http://backend;

        # WebSocket 必须使用 HTTP/1.1
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        # WebSocket 连接通常长时，增大超时
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;

        # 标准代理头
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 6.4 gRPC 代理

```nginx
server {
    listen 80 http2;

    location /grpc/ {
        grpc_pass grpc://backend:9090;      # 明文 gRPC
        # grpc_pass grpcs://backend:9090;   # TLS gRPC

        grpc_set_header Host $host;
        grpc_set_header X-Real-IP $remote_addr;
        grpc_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        grpc_read_timeout 300s;
        grpc_connect_timeout 5s;
    }
}
```

### 6.5 proxy_pass 路径规则

```nginx
# 规则1: proxy_pass 不带 URI（不带路径），原样转发
# 请求: /api/users/123
# 转发: http://backend/api/users/123
location /api/ {
    proxy_pass http://backend;
}

# 规则2: proxy_pass 带 URI，替换匹配的 location 前缀
# 请求: /api/users/123
# 转发: http://backend/users/123
location /api/ {
    proxy_pass http://backend/;
}

# 规则3: proxy_pass 带路径前缀
# 请求: /api/users/123
# 转发: http://backend/v2/users/123
location /api/ {
    proxy_pass http://backend/v2/;
}

# 规则4: 使用正则 location 时，proxy_pass 不能带 URI
location ~ ^/api/(.*)$ {
    proxy_pass http://backend;  # 不能写 http://backend/$1（用 rewrite 实现）
    # 如需重写路径:
    # rewrite ^/api/(.*)$ /$1 break;
    # proxy_pass http://backend;
}
```

### 6.6 获取客户端真实 IP

```nginx
# 当 NGINX 在其他代理后面时，获取真实客户端 IP
# 需要编译 --with-http_realip_module

server {
    # 信任的代理 IP
    set_real_ip_from 10.0.0.0/8;
    set_real_ip_from 172.16.0.0/12;
    set_real_ip_from 192.168.0.0/16;

    # 从哪个头获取真实 IP
    real_ip_header X-Forwarded-For;
    # 或 real_ip_header X-Real-IP;

    # 递归去除可信代理 IP
    real_ip_recursive on;
}
```

---

## 7. 负载均衡

### 7.1 负载均衡架构

```
                    客户端请求
                        │
                        ▼
              ┌─────────────────┐
              │   NGINX (LB)    │
              │  调度算法选择后端  │
              └────────┬────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
        ▼              ▼              ▼
  ┌──────────┐  ┌──────────┐  ┌──────────┐
  │ Backend1 │  │ Backend2 │  │ Backend3 │
  │  weight=3│  │  weight=2│  │  backup  │
  └──────────┘  └──────────┘  └──────────┘
```

### 7.2 负载均衡算法

#### 轮询（Round Robin）— 默认

```nginx
upstream backend {
    server 192.168.1.101:8080;
    server 192.168.1.102:8080;
    server 192.168.1.103:8080;
}
# 请求分配: A → B → C → A → B → C → ...
```

#### 加权轮询（Weighted Round Robin）

```nginx
upstream backend {
    server 192.168.1.101:8080 weight=3;   # 3/5 的请求
    server 192.168.1.102:8080 weight=2;   # 2/5 的请求
}
# 请求分配: A → A → B → A → B → A → A → B → ...
```

#### IP 哈希（IP Hash）— 会话保持

```nginx
upstream backend {
    ip_hash;                               # 相同客户端 IP 固定到同一后端
    server 192.168.1.101:8080;
    server 192.168.1.102:8080;
    server 192.168.1.103:8080;
}
# 适用场景: 需要会话保持（Session 粘滞），避免使用 Session 共享
```

#### 最少连接（Least Connections）

```nginx
upstream backend {
    least_conn;                            # 优先分配给当前连接数最少的后端
    server 192.168.1.101:8080;
    server 192.168.1.102:8080;
    server 192.168.1.103:8080;
}
# 适用场景: 请求处理时间差异较大的场景
```

#### 一致性哈希（Consistent Hash）— 需第三方模块

```nginx
# 需要 ngx_http_upstream_consistent_hash 模块
upstream backend {
    consistent_hash $request_uri;          # 基于请求 URI 的一致性哈希
    server 192.168.1.101:8080;
    server 192.168.1.102:8080;
    server 192.168.1.103:8080;
}
# 优势: 某台后端下线时，只有部分请求需要重新分配，而非全部
```

#### 通用哈希（Generic Hash）

```nginx
upstream backend {
    hash $request_uri consistent;          # 基于 URI 哈希，consistent 开启一致性
    server 192.168.1.101:8080;
    server 192.168.1.102:8080;
}
```

### 7.3 服务器状态参数

```nginx
upstream backend {
    server 192.168.1.101:8080 weight=3 max_fails=3 fail_timeout=30s;
    server 192.168.1.102:8080 weight=2 max_fails=3 fail_timeout=30s;
    server 192.168.1.103:8080 backup;       # 备用服务器，其他全部故障才启用
    server 192.168.1.104:8080 down;         # 标记为下线，不参与负载
    server 192.168.1.105:8080 max_conns=100; # 最大并发连接数
    keepalive 32;                           # 长连接缓存数
    keepalive_requests 100;                 # 每个长连接最大请求数
    keepalive_timeout 60s;                  # 长连接超时
}
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `weight=N` | 权重 | 1 |
| `max_fails=N` | 允许失败次数 | 1 |
| `fail_timeout=T` | 失败后的暂停时间 | 10s |
| `backup` | 备用服务器 | - |
| `down` | 标记下线 | - |
| `max_conns=N` | 最大并发连接 | 0（不限） |
| `slow_start=T` | 慢启动时间（仅 Plus） | 0 |
| `resolve` | 动态解析域名（仅 Plus） | - |

### 7.4 健康检查

#### 被动健康检查（开源版内置）

```nginx
upstream backend {
    # 被动检查: 请求失败时自动标记不可用
    server 192.168.1.101:8080 max_fails=3 fail_timeout=30s;
    server 192.168.1.102:8080 max_fails=3 fail_timeout=30s;
}

server {
    location / {
        proxy_pass http://backend;
        # 出现以下情况时，将请求转发给下一个后端
        proxy_next_upstream error timeout http_502 http_503 http_504;
    }
}
```

#### 主动健康检查（NGINX Plus 或第三方模块）

```nginx
# NGINX Plus 主动健康检查
upstream backend {
    zone backend 64k;
    server 192.168.1.101:8080;
    server 192.168.1.102:8080;

    # 主动健康检查
    health_check interval=10s fails=3 passes=2;
    health_check uri=/health;
}

# 第三方模块 nginx_upstream_check_module
upstream backend {
    server 192.168.1.101:8080;
    server 192.168.1.102:8080;
    check interval=3000 rise=2 fall=3 timeout=1000 type=http;
    check_http_send "GET /health HTTP/1.0\r\n\r\n";
    check_http_expect_alive http_2xx http_3xx;
}
```

### 7.5 负载均衡算法选型

| 算法 | 适用场景 | 优点 | 缺点 |
|------|---------|------|------|
| 轮询 | 服务器性能相近 | 简单公平 | 不考虑实际负载 |
| 加权轮询 | 服务器性能不同 | 性能强的多处理 | 不考虑实时连接 |
| IP 哈希 | 需要会话保持 | 简单实现粘滞 | 后端扩缩容影响大 |
| 最少连接 | 长连接场景 | 动态均衡 | 计算开销略大 |
| 一致性哈希 | 缓存场景 | 节点变动影响小 | 需第三方模块 |
| Fair（第三方） | 延迟敏感 | 响应快的多处理 | 需第三方模块 |

---

## 8. 缓存系统

### 8.1 缓存分层架构

```
┌─────────────────────────────────────────────────────────┐
│                    客户端浏览器                           │
│         Cache-Control / Expires / ETag                  │
└────────────────────────┬────────────────────────────────┘
                         │ 缓存未命中
                         ▼
┌─────────────────────────────────────────────────────────┐
│                    CDN 边缘节点                          │
│              proxy_cache (边缘缓存)                       │
└────────────────────────┬────────────────────────────────┘
                         │ 缓存未命中
                         ▼
┌─────────────────────────────────────────────────────────┐
│                   NGINX 反向代理                          │
│        proxy_cache / fastcgi_cache (服务端缓存)           │
└────────────────────────┬────────────────────────────────┘
                         │ 缓存未命中
                         ▼
┌─────────────────────────────────────────────────────────┐
│              后端应用 / FastCGI / 数据库                  │
└─────────────────────────────────────────────────────────┘
```

### 8.2 proxy_cache（代理缓存）

```nginx
http {
    # ==================== 定义缓存区域 ====================
    proxy_cache_path /var/cache/nginx/proxy
        levels=1:2                        # 两级子目录
        keys_zone=app_cache:10m           # 内存区域名和大小（10m 约存 8 万条 key）
        max_size=1g                       # 磁盘缓存最大大小
        inactive=60m                      # 60 分钟未访问自动删除
        use_temp_path=off;                # 直接写入缓存目录，避免额外 I/O

    # 缓存键（决定缓存粒度）
    proxy_cache_key "$scheme$request_method$host$request_uri";

    server {
        listen 80;

        location / {
            proxy_pass http://backend;

            # ==================== 启用缓存 ====================
            proxy_cache app_cache;

            # 不同状态码的缓存时间
            proxy_cache_valid 200 302 10m;
            proxy_cache_valid 404 1m;
            proxy_cache_valid any 5m;

            # 缓存行为
            proxy_cache_use_stale error timeout updating
                http_500 http_502 http_503 http_504;   # 后端故障时使用旧缓存
            proxy_cache_revalidate on;                  # 条件请求验证缓存
            proxy_cache_lock on;                        # 缓存锁定（防缓存击穿）
            proxy_cache_lock_timeout 5s;                # 锁等待超时
            proxy_cache_background_update on;           # 后台更新过期缓存
            proxy_cache_max_range_offset 0;             # 禁用 Range 请求缓存

            # 缓存跳过条件
            proxy_cache_bypass $http_authorization;     # 带 Auth 头不缓存
            proxy_no_cache $http_authorization;         # 带 Auth 头不写入缓存

            # 显示缓存状态
            add_header X-Cache-Status $upstream_cache_status;
            # HIT: 缓存命中 | MISS: 未命中 | EXPIRED: 已过期
            # STALE: 使用旧缓存 | UPDATING: 正在更新 | REVALIDATED: 已验证
            # BYPASS: 跳过缓存 | MISS: 未命中
        }
    }
}
```

### 8.3 fastcgi_cache（FastCGI 缓存）

```nginx
http {
    fastcgi_cache_path /var/cache/nginx/fastcgi
        levels=1:2
        keys_zone=php_cache:100m
        max_size=2g
        inactive=30m
        use_temp_path=off;

    fastcgi_cache_key "$scheme$request_method$host$request_uri";

    server {
        location ~ \.php$ {
            fastcgi_pass unix:/var/run/php/php8.1-fpm.sock;
            fastcgi_index index.php;
            include fastcgi_params;
            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;

            # 启用 FastCGI 缓存
            fastcgi_cache php_cache;
            fastcgi_cache_valid 200 301 302 10m;
            fastcgi_cache_valid 404 1m;
            fastcgi_cache_use_stale error timeout updating invalid_header http_500;

            # 跳过缓存条件
            set $skip_cache 0;
            if ($request_method = POST) { set $skip_cache 1; }
            if ($query_string != "") { set $skip_cache 1; }
            if ($http_cookie ~* "wordpress_logged_in|comment_author") {
                set $skip_cache 1;
            }

            fastcgi_cache_bypass $skip_cache;
            fastcgi_no_cache $skip_cache;

            add_header X-FastCGI-Cache $upstream_cache_status;
        }
    }
}
```

### 8.4 浏览器缓存控制

```nginx
server {
    # 强缓存（Cache-Control + Expires）
    location ~* \.(jpg|jpeg|png|gif|webp|avif|svg|ico|woff2?)$ {
        expires 365d;
        add_header Cache-Control "public, immutable";
        access_log off;
    }

    # 协商缓存（ETag + Last-Modified）
    location ~* \.(css|js)$ {
        # expires 1d;  →  Cache-Control: max-age=86400
        # 带版本号的静态资源用强缓存，不带版本号用协商缓存
        add_header Cache-Control "public, must-revalidate";
        etag on;
        access_log off;
    }

    # HTML 文件 - 短缓存 + 协商
    location ~* \.html$ {
        add_header Cache-Control "no-cache, must-revalidate";
        etag on;
    }

    # API - 不缓存
    location /api/ {
        add_header Cache-Control "no-store, no-cache, must-revalidate";
        add_header Pragma "no-cache";
        proxy_pass http://backend;
    }
}
```

### 8.5 缓存清理

```nginx
# 方法1: 使用 ngx_cache_purge 第三方模块
location ~ /purge(/.*) {
    allow 127.0.0.1;                     # 仅允许本地清理
    allow 10.0.0.0/8;
    deny all;
    proxy_cache_purge app_cache "$scheme$request_method$host$1$is_args$args";
}

# 方法2: 删除缓存文件
# find /var/cache/nginx/proxy -type f -delete
# 或按 URL 匹配删除:
# grep -rl "特定URL" /var/cache/nginx/proxy | xargs rm -f

# 方法3: 重新加载配置（不清理缓存，但重建索引）
# nginx -s reload
```

### 8.6 CDN 边缘缓存配置

```nginx
http {
    # CDN 缓存区域
    proxy_cache_path /var/cache/nginx/cdn-static
        levels=1:2
        keys_zone=cdn_static:100m
        max_size=10g
        inactive=7d
        use_temp_path=off;

    proxy_cache_path /var/cache/nginx/cdn-dynamic
        levels=1:2
        keys_zone=cdn_dynamic:50m
        max_size=2g
        inactive=24h
        use_temp_path=off;

    # 源站服务器组
    upstream origin_servers {
        server origin1.example.com:80 weight=3;
        server origin2.example.com:80 weight=2;
        server origin3.example.com:80 backup;
        keepalive 32;
    }

    # CDN 日志格式
    log_format cdn_log '$remote_addr - [$time_local] '
        '"$request" $status $body_bytes_sent '
        'cache="$upstream_cache_status" '
        'origin="$upstream_addr" '
        'rt=$request_time urt="$upstream_response_time"';

    server {
        listen 80;
        server_name cdn.example.com *.cdn.example.com;
        access_log /var/log/nginx/cdn-access.log cdn_log;

        # 图片 - 长缓存
        location ~* \.(jpg|jpeg|png|gif|ico|svg|webp|avif)$ {
            proxy_pass http://origin_servers;
            proxy_cache cdn_static;
            proxy_cache_valid 200 302 7d;
            proxy_cache_valid 404 1h;
            proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
            proxy_cache_revalidate on;
            proxy_cache_lock on;
            proxy_cache_lock_timeout 5s;

            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-CDN-Edge $server_name;

            add_header X-Cache-Status $upstream_cache_status always;
            expires 30d;
            add_header Cache-Control "public, immutable";
        }

        # CSS/JS - 中等缓存
        location ~* \.(css|js)$ {
            proxy_pass http://origin_servers;
            proxy_cache cdn_static;
            proxy_cache_valid 200 24h;
            proxy_cache_valid 404 1h;
            proxy_set_header Host $host;
            add_header X-Cache-Status $upstream_cache_status always;
            expires 1d;
            add_header Cache-Control "public";
        }

        # API 动态内容 - 短缓存
        location /api/ {
            proxy_pass http://origin_servers;
            proxy_cache cdn_dynamic;
            proxy_cache_valid 200 302 10m;
            proxy_cache_valid 404 1m;
            proxy_set_header Host $host;
            add_header X-Cache-Status $upstream_cache_status always;
        }
    }
}
```

---

## 9. HTTPS / SSL / TLS 配置

### 9.1 基础 HTTPS 配置

```nginx
server {
    listen 443 ssl http2;
    server_name example.com www.example.com;

    # 证书和私钥
    ssl_certificate     /etc/nginx/ssl/example.com.crt;    # 含证书链的完整证书
    ssl_certificate_key /etc/nginx/ssl/example.com.key;    # 私钥

    # TLS 协议版本（仅启用安全版本）
    ssl_protocols TLSv1.2 TLSv1.3;

    # 加密套件
    ssl_prefer_server_ciphers on;
    ssl_ciphers 'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256';

    # 会话缓存（提升握手性能）
    ssl_session_cache shared:SSL:50m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;                     # 禁用 Session Tickets（安全考虑）

    # OCSP Stapling（减少证书验证延迟）
    ssl_stapling on;
    ssl_stapling_verify on;
    ssl_trusted_certificate /etc/nginx/ssl/ca-bundle.crt;
    resolver 1.1.1.1 8.8.8.8 valid=300s;
    resolver_timeout 5s;

    # DH 参数
    ssl_dhparam /etc/nginx/ssl/dhparam.pem;

    root /var/www/example.com;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }
}

# HTTP 强制跳转 HTTPS
server {
    listen 80;
    server_name example.com www.example.com;
    return 301 https://$host$request_uri;
}
```

### 9.2 安全响应头

```nginx
server {
    listen 443 ssl http2;

    # HSTS - 强制浏览器使用 HTTPS（防止降级攻击）
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;

    # 防止点击劫持
    add_header X-Frame-Options "SAMEORIGIN" always;

    # 防止 MIME 类型嗅探
    add_header X-Content-Type-Options "nosniff" always;

    # XSS 过滤
    add_header X-XSS-Protection "1; mode=block" always;

    # 引用来源策略
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # 权限策略
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;

    # 内容安全策略（CSP）
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self'; connect-src 'self'; frame-ancestors 'self';" always;
}
```

### 9.3 Let's Encrypt 自动证书

```bash
# 1. 安装 Certbot
sudo apt update
sudo apt install certbot python3-certbot-nginx -y

# 2. 申请证书（自动修改 Nginx 配置）
sudo certbot --nginx -d example.com -d www.example.com

# 3. 测试自动续期
sudo certbot renew --dry-run

# 4. 设置自动续期 Cron
echo "0 3 * * * certbot renew --quiet && systemctl reload nginx" | sudo crontab -

# 证书存储位置: /etc/letsencrypt/live/example.com/
# - fullchain.pem (完整证书链)
# - privkey.pem (私钥)
```

### 9.4 多域名 SSL 配置

```nginx
# 方法1: SNI 多证书（推荐）
server {
    listen 443 ssl http2;
    server_name site1.com;
    ssl_certificate     /etc/ssl/site1.com.crt;
    ssl_certificate_key /etc/ssl/site1.com.key;
    # ...
}

server {
    listen 443 ssl http2;
    server_name site2.com;
    ssl_certificate     /etc/ssl/site2.com.crt;
    ssl_certificate_key /etc/ssl/site2.com.key;
    # ...
}

# 方法2: 通配符证书
server {
    listen 443 ssl http2;
    server_name *.example.com;
    ssl_certificate     /etc/ssl/wildcard.example.com.crt;
    ssl_certificate_key /etc/ssl/wildcard.example.com.key;
    # ...
}
```

### 9.5 TLS 性能优化

```nginx
# TLS 1.3 0-RTT（零往返时间）
ssl_early_data on;
# 注意: 0-RTT 有重放攻击风险，仅对幂等请求安全

# 会话恢复
ssl_session_cache shared:SSL:50m;    # 1MB 可存约 4000 个会话
ssl_session_timeout 1d;

# OCSP Stapling（减少客户端验证延迟）
ssl_stapling on;
ssl_stapling_verify on;

# 禁用 TLS 压缩（防止 CRIME 攻击）
# gzip off; （在 SSL 上下文中）

# 使用 ECDSA 证书（比 RSA 更快）
# ECC 256 位 ≈ RSA 3072 位安全性，但握手更快
```

### 9.6 SSL 配置验证

```bash
# 检查证书信息
openssl x509 -in example.com.crt -text -noout

# 验证证书和私钥是否匹配
openssl x509 -noout -modulus -in example.com.crt | openssl md5
openssl rsa -noout -modulus -in example.com.key | openssl md5
# 两个 MD5 值应该相同

# 测试 SSL 连接
openssl s_client -connect example.com:443 -servername example.com

# 检查证书链
openssl s_client -connect example.com:443 -showcerts

# 生成 DH 参数
openssl dhparam -out /etc/nginx/ssl/dhparam.pem 2048
# 生产环境建议 2048 位（或 4096 位更安全但更慢）
```

---

## 10. 安全防护

### 10.1 安全加固配置

```nginx
server {
    # 隐藏 NGINX 版本号
    server_tokens off;

    # 安全头（见 9.2 节）
    # ...

    # 限制请求方法
    if ($request_method !~ ^(GET|HEAD|POST|PUT|DELETE|OPTIONS)$ ) {
        return 405;
    }

    # 禁止访问敏感文件
    location ~ /\. {
        deny all;                        # 隐藏文件（如 .git, .env）
        access_log off;
        log_not_found off;
    }

    location ~* \.(bak|backup|old|orig|save|swo|swp|tmp|sql|log)$ {
        deny all;                        # 备份/临时文件
        access_log off;
        log_not_found off;
    }

    # 阻止常见攻击模式
    location ~* "(eval\(|javascript:|vbscript:|onload=)" {
        deny all;
    }

    # 限制请求体大小
    client_max_body_size 10m;
    client_body_buffer_size 128k;
    client_header_buffer_size 1k;
    large_client_header_buffers 2 1k;

    # 安全超时设置
    client_body_timeout 12;              # 请求体超时
    client_header_timeout 12;            # 请求头超时
    keepalive_timeout 15;                # 长连接超时
    send_timeout 10;                     # 响应发送超时

    # 缓冲区溢出保护
    client_body_buffer_size 1K;
    client_header_buffer_size 1k;
    large_client_header_buffers 2 1k;
}
```

### 10.2 速率限制（Rate Limiting）

```nginx
http {
    # ==================== 限流区域定义 ====================
    # 按客户端 IP 限制请求速率
    limit_req_zone $binary_remote_addr zone=general:10m rate=10r/s;     # 通用: 10 请求/秒
    limit_req_zone $binary_remote_addr zone=login:10m rate=1r/s;        # 登录: 1 请求/秒
    limit_req_zone $binary_remote_addr zone=api:10m rate=20r/s;         # API: 20 请求/秒
    limit_req_zone $binary_remote_addr zone=downloads:10m rate=5r/s;    # 下载: 5 请求/秒

    # 按客户端 IP 限制并发连接数
    limit_conn_zone $binary_remote_addr zone=conn_limit:10m;            # 每个IP最大连接数
    limit_conn_zone $server_name zone=perserver:10m;                    # 每个服务器最大连接数

    server {
        # ==================== 连接数限制 ====================
        limit_conn conn_limit 10;           # 每个 IP 最多 10 个并发连接
        limit_conn perserver 1000;          # 服务器最大 1000 并发连接

        # 通用限流
        limit_req zone=general burst=20 nodelay;
        limit_req_status 429;               # 超限返回 429

        # 登录接口 - 严格限流
        location ~ ^/(admin|login|wp-login|wp-admin) {
            limit_req zone=login burst=3 nodelay;
            # IP 白名单（可选）
            # allow 192.168.1.0/24;
            # deny all;
            proxy_pass http://backend;
        }

        # API 接口
        location /api/ {
            limit_req zone=api burst=20 nodelay;
            proxy_pass http://backend;
        }

        # 文件下载
        location /download/ {
            limit_req zone=downloads burst=5 nodelay;
            limit_rate 1m;                  # 限速 1MB/s
            proxy_pass http://backend;
        }
    }
}
```

**limit_req 参数说明**:

```
limit_req zone=NAME burst=N [nodelay | delay=N];

- zone:     引用的限流区域名
- burst:    允许的突发请求数（排队等待）
- nodelay:  突发请求立即处理（不排队等待）
- delay=N:  前 N 个突发请求立即处理，后续排队

# 示例: rate=10r/s, burst=20, nodelay
# → 每秒最多处理 10 个请求，允许瞬时 20 个额外请求立即处理
# → 第 31 个请求返回 429
```

### 10.3 访问控制

```nginx
# IP 白名单/黑名单
location /admin {
    allow 192.168.1.0/24;        # 允许内网
    allow 10.0.0.0/8;
    allow 203.0.113.100;         # 允许特定 IP
    deny all;                    # 拒绝其他所有
    proxy_pass http://backend;
}

# 基于地理位置（需 GeoIP 模块）
geoip_country /usr/share/GeoIP/GeoIP.dat;

map $geoip_country_code $allowed_country {
    default no;
    CN yes;                      # 仅允许中国 IP
    US yes;
}

server {
    location / {
        if ($allowed_country = no) {
            return 403;
        }
        proxy_pass http://backend;
    }
}

# 基本认证
location /admin {
    auth_basic "Restricted";
    auth_basic_user_file /etc/nginx/.htpasswd;
    proxy_pass http://backend;
}

# 生成密码文件
# htpasswd -c /etc/nginx/.htpasswd username
```

### 10.4 WAF（Web 应用防火墙）

```nginx
# 使用 ModSecurity 模块
# 需编译 ngx_http_modsecurity_module

load_module modules/ngx_http_modsecurity_module.so;

http {
    modsecurity on;
    modsecurity_rules_file /etc/nginx/modsec/modsecurity.conf;

    server {
        # 全局启用 ModSecurity
        modsecurity on;

        # 引入 OWASP Core Rule Set (CRS)
        modsecurity_rules_file /etc/nginx/modsec/modsecurity.conf;

        location / {
            modsecurity on;
            proxy_pass http://backend;
        }

        # 静态资源跳过 WAF（性能优化）
        location ~* \.(jpg|png|css|js)$ {
            modsecurity off;
            expires 30d;
        }
    }
}

# modsecurity.conf 示例
# SecRuleEngine On
# Include /etc/nginx/modsec/crs-setup.conf
# Include /usr/share/modsecurity-crs/rules/*.conf

# 自定义规则示例:
# 阻止 SQL 注入
# SecRule ARGS "@rx (?i)(union|select|insert|delete|drop|update)" "id:1001,deny,status:403"
# 阻止 XSS
# SecRule ARGS "@rx (?i)<script" "id:1002,deny,status:403"
# Log4j 虚拟补丁
# SecRule ARGS "@rx (?i:jndi:ldap://)" "id:999998,phase:2,block,msg:'Log4j RCE Attack'"
```

### 10.5 DDoS 防护策略

```nginx
http {
    # 1. 连接数限制
    limit_conn_zone $binary_remote_addr zone=addr:10m;

    # 2. 请求速率限制
    limit_req_zone $binary_remote_addr zone=req_limit:10m rate=10r/s;

    # 3. 连接超时（对付 Slowloris 慢速攻击）
    client_body_timeout 5s;
    client_header_timeout 5s;

    server {
        # 4. 限制每个 IP 的并发连接
        limit_conn addr 10;

        # 5. 请求体大小限制
        client_max_body_size 1m;

        # 6. 限制请求头数量和大小
        client_header_buffer_size 1k;
        large_client_header_buffers 2 1k;

        # 7. 限流
        limit_req zone=req_limit burst=20 nodelay;

        # 8. 返回 444（无响应关闭连接，节省资源）
        location = /favicon.ico {
            access_log off;
            log_not_found off;
            return 204;
        }

        # 9. 屏蔽恶意 User-Agent
        if ($http_user_agent ~* (curl|wget|python|scrapy|bot)) {
            return 403;
        }

        # 10. 屏蔽特定路径扫描
        location ~ ^/(phpmyadmin|wp-admin|wp-login|\.env|\.git) {
            return 444;
        }
    }
}
```

---

## 11. 性能优化

### 11.1 Worker 进程优化

```nginx
# ==================== 全局配置 ====================
# Worker 进程数 = CPU 核心数（auto 自动检测）
worker_processes auto;

# CPU 亲和性（自动绑定 CPU 核心，减少上下文切换）
worker_cpu_affinity auto;

# 每个 Worker 最大文件描述符数（需配合系统 ulimit）
worker_rlimit_nofile 100000;

# Worker 优雅关闭超时
worker_shutdown_timeout 10s;

events {
    # 事件模型
    use epoll;                       # Linux 最佳选择

    # 每个 Worker 最大连接数
    worker_connections 10240;        # 建议 10240-65535

    # 一次接受多个新连接
    multi_accept on;                 # 高并发开启

    # Worker 互斥锁（低负载开启，高负载关闭）
    # accept_mutex on;               # 默认 off（高并发时关闭减少锁竞争）
}
```

**worker_connections 计算公式**:

```
最大并发连接数 = worker_processes × worker_connections

注意:
- 作为反向代理时，每个客户端连接会占用 2 个连接（客户端 + 后端）
- 所以有效并发 = worker_processes × worker_connections / 2
- 还需减去 Keepalive 连接等开销

示例: 4 核 CPU × 10240 connections / 2 = 20480 有效并发连接
```

### 11.2 网络与 I/O 优化

```nginx
http {
    # ==================== 零拷贝传输 ====================
    sendfile on;                     # 静态文件零拷贝（kernel → socket）
    sendfile_max_chunk 128k;         # 每次传输最大块

    # ==================== TCP 优化 ====================
    tcp_nopush on;                   # 配合 sendfile，合并数据包（减少网络包数量）
    tcp_nodelay on;                  # 禁用 Nagle 算法（减少小包延迟）
    # tcp_nopush 和 tcp_nodelay 可以同时开启
    # sendfile on 时 tcp_nopush 生效，发送完毕后 tcp_nodelay 生效

    # ==================== Keepalive ====================
    keepalive_timeout 65;            # 长连接超时
    keepalive_requests 1000;         # 单个长连接最大请求数
    keepalive_disable msie6;         # 禁用 IE6 的 keepalive

    # ==================== 超时控制 ====================
    reset_timedout_connection on;    # 关闭超时连接，释放资源
    client_body_timeout 12;          # 请求体读取超时
    client_header_timeout 12;        # 请求头读取超时
    send_timeout 10;                 # 响应发送超时

    # ==================== 缓冲区优化 ====================
    client_body_buffer_size 16K;     # 请求体缓冲区
    client_header_buffer_size 1k;    # 请求头缓冲区
    client_max_body_size 8m;         # 最大请求体
    large_client_header_buffers 4 8k; # 大请求头缓冲区

    # ==================== 输出缓冲 ====================
    output_buffers 1 32k;
    postpone_output 1460;            # 延迟发送，凑满一个 MSS 再发
}
```

### 11.3 Gzip 压缩

```nginx
http {
    gzip on;
    gzip_vary on;                    # 添加 Vary: Accept-Encoding 头
    gzip_min_length 1024;            # 小于 1KB 不压缩
    gzip_comp_level 6;               # 压缩级别 1-9（6 平衡性能和压缩率）
    gzip_proxied any;                # 对代理请求也压缩

    # 压缩的 MIME 类型
    gzip_types
        text/plain
        text/css
        text/xml
        text/javascript
        application/json
        application/javascript
        application/x-javascript
        application/xml
        application/xml+rss
        application/atom+xml
        application/ld+json
        application/manifest+json
        application/xhtml+xml
        application/rss+xml
        image/svg+xml
        font/eot
        font/otf
        font/ttf;

    # 禁用对 IE6 的压缩
    gzip_disable "MSIE [1-6]\.";
}
```

### 11.4 Brotli 压缩（更高效）

```nginx
# 需要 ngx_brotli 模块
load_module modules/ngx_http_brotli_filter_module.so;
load_module modules/ngx_http_brotli_static_module.so;

http {
    # Brotli 压缩（比 Gzip 压缩率高 15-20%）
    brotli on;
    brotli_comp_level 6;             # 压缩级别 0-11
    brotli_min_length 1024;
    brotli_types text/plain text/css application/json application/javascript
                 text/xml application/xml image/svg+xml;

    # Brotli 静态文件（预压缩的 .br 文件）
    brotli_static on;
}
```

### 11.5 文件描述符缓存

```nginx
http {
    # 文件描述符缓存（大幅提升静态文件性能）
    open_file_cache max=200000 inactive=20s;
    open_file_cache_valid 30s;       # 缓存验证间隔
    open_file_cache_min_uses 2;      # 最少访问次数才缓存
    open_file_cache_errors on;       # 缓存文件不存在等错误
}
```

### 11.6 系统内核参数优化

```bash
# /etc/sysctl.conf

# ==================== 文件描述符 ====================
fs.file-max = 1000000               # 系统最大文件描述符

# ==================== 网络参数 ====================
# TCP 连接队列
net.core.somaxconn = 65535          # 监听队列最大长度
net.core.netdev_max_backlog = 65535 # 网卡收包队列

# TCP 连接复用
net.ipv4.tcp_tw_reuse = 1           # 允许 TIME_WAIT 状态的 socket 重新使用
# net.ipv4.tcp_tw_recycle = 0       # 已废弃，不要开启（NAT 环境有问题）

# TCP keepalive
net.ipv4.tcp_keepalive_time = 600   # keepalive 探测间隔
net.ipv4.tcp_keepalive_intvl = 30   # 探测消息间隔
net.ipv4.tcp_keepalive_probes = 3   # 探测次数

# TCP 缓冲区
net.ipv4.tcp_rmem = 4096 87380 16777216   # TCP 读缓冲区
net.ipv4.tcp_wmem = 4096 65536 16777216   # TCP 写缓冲区
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216

# 端口范围
net.ipv4.ip_local_port_range = 1024 65535  # 本地端口范围

# SYN Flood 防护
net.ipv4.tcp_syncookies = 1         # 启用 SYN Cookies
net.ipv4.tcp_max_syn_backlog = 65535 # SYN 队列长度

# ==================== 应用配置 ====================
# /etc/security/limits.conf
# nginx soft nofile 65535
# nginx hard nofile 65535
# * soft nproc 65535
# * hard nproc 65535

# 生效
sysctl -p
```

### 11.7 性能调优清单

| 优化方向 | 关键配置 | 性能提升 |
|---------|---------|---------|
| 进程配置 | `worker_processes = CPU 核心数` + `worker_cpu_affinity` | 10-30% |
| 连接管理 | `worker_connections = 10240+` + `keepalive_timeout = 60s` | 30-50% |
| 事件驱动 | `use epoll` + `multi_accept on` | 10-20% |
| 静态资源 | `sendfile on` + `gzip on` + 浏览器缓存 | 50-80% |
| 网络优化 | `tcp_nopush on` + `tcp_nodelay on` + 系统参数 | 20-40% |
| 文件缓存 | `open_file_cache` | 10-20% |
| SSL 优化 | TLS 1.3 + Session Cache + OCSP Stapling | 20-30% |

### 11.8 性能监控指标

```
需监控的关键指标:
├── 连接数
│   ├── 活跃连接数 (Active connections)
│   ├── 等待连接数 (Waiting)
│   ├── 读取连接数 (Reading)
│   └── 写入连接数 (Writing)
├── 请求
│   ├── 每秒请求数 (RPS)
│   ├── 每秒处理请求数
│   └── 总请求数
├── 响应时间
│   ├── 请求处理时间 ($request_time)
│   └── 后端响应时间 ($upstream_response_time)
├── 状态码分布
│   ├── 2xx 比例
│   ├── 4xx 比例
│   └── 5xx 比例
└── 资源使用
    ├── CPU 使用率（应 < 80%）
    ├── 内存使用量
    └── 磁盘 I/O
```

---

## 12. Stream 模块与四层代理

### 12.1 Stream 模块概述

NGINX 自 1.9.0 版本引入 Stream 模块，支持 **四层（传输层）TCP/UDP 代理与负载均衡**。与七层 HTTP 代理不同，Stream 模块不解析应用层协议，直接转发原始数据流。

```
四层代理 vs 七层代理:

  四层 (Stream)                        七层 (HTTP)
  ┌──────────┐                        ┌──────────┐
  │  Client   │                        │  Client   │
  └────┬─────┘                        └────┬─────┘
       │ TCP/UDP                            │ HTTP
  ┌────▼─────┐                        ┌────▼─────┐
  │ NGINX LB  │ 不解析协议内容          │ NGINX LB  │ 解析 HTTP 头/URL
  │ (转发字节) │                        │ (智能路由) │
  └────┬─────┘                        └────┬─────┘
       │                                     │
  ┌────▼─────┐                        ┌────▼─────┐
  │ Backend   │                        │ Backend   │
  └──────────┘                        └──────────┘

  适用: MySQL/Redis/DNS/游戏            适用: Web/API/微服务
  性能: 更高（不解析应用层）             功能: 更强（基于 URL/Header 路由）
```

### 12.2 基础 TCP 代理

```nginx
# stream 块与 http 块平级，不能嵌套在 http 内
stream {
    # TCP 端口转发
    server {
        listen 3307;                           # 监听端口
        proxy_pass 192.168.1.100:3306;         # 转发目标

        proxy_connect_timeout 5s;              # 连接超时
        proxy_timeout 300s;                    # 空闲超时
        proxy_buffer_size 16k;                 # 缓冲区大小
    }
}
```

### 12.3 TCP 负载均衡

```nginx
stream {
    upstream mysql_cluster {
        # 负载均衡算法
        least_conn;                            # 最少连接

        server 192.168.1.101:3306 weight=3 max_fails=3 fail_timeout=30s;
        server 192.168.1.102:3306 weight=2 max_fails=3 fail_timeout=30s;
        server 192.168.1.103:3306 backup;
    }

    server {
        listen 3306;
        proxy_pass mysql_cluster;

        proxy_connect_timeout 5s;
        proxy_timeout 300s;
    }
}
```

### 12.4 UDP 负载均衡

```nginx
stream {
    upstream dns_servers {
        # 一致性哈希（DNS 查询需要会话保持）
        hash $remote_addr consistent;

        server 192.168.1.101:53;
        server 192.168.1.102:53;
    }

    server {
        listen 53 udp;                         # UDP 协议
        proxy_pass dns_servers;

        proxy_timeout 3s;
        proxy_responses 1;                     # 期望响应数据包数
        proxy_buffer_size 16k;
    }
}
```

### 12.5 Redis 四层代理

```nginx
stream {
    upstream redis_cluster {
        least_conn;
        server 192.168.1.101:6379 max_fails=3 fail_timeout=10s;
        server 192.168.1.102:6380 max_fails=3 fail_timeout=10s;
    }

    server {
        listen 6379;
        proxy_pass redis_cluster;

        proxy_connect_timeout 1s;
        proxy_timeout 300s;

        # 日志
        access_log /var/log/nginx/redis_access.log;
        error_log /var/log/nginx/redis_error.log warn;
    }
}
```

### 12.6 Stream 模块负载均衡算法

| 算法 | 配置 | 说明 |
|------|------|------|
| 轮询（默认） | 无需配置 | 按顺序分配 |
| 最少连接 | `least_conn;` | 分配给连接最少的后端 |
| IP 哈希 | `ip_hash;` | 相同 IP 固定后端 |
| 通用哈希 | `hash $remote_addr consistent;` | 自定义哈希键 + 一致性 |
| 随机 | `random;` 或 `random two;` | 随机分配 |

### 12.7 Stream SSL 终止

```nginx
stream {
    server {
        listen 443 ssl;
        ssl_certificate     /etc/nginx/ssl/example.com.crt;
        ssl_certificate_key /etc/nginx/ssl/example.com.key;
        ssl_protocols       TLSv1.2 TLSv1.3;

        proxy_pass backend:8443;
    }
}
```

### 12.8 Stream 适用场景

| 场景 | 协议 | 说明 |
|------|------|------|
| MySQL 代理 | TCP | 读写分离、连接池 |
| Redis 代理 | TCP | 集群入口、负载均衡 |
| DNS 代理 | UDP | DNS 负载均衡 |
| 游戏服务器 | TCP/UDP | 游戏网关 |
| MQTT 代理 | TCP | IoT 消息代理 |
| RDP 远程桌面 | TCP | 远程桌面网关 |
| 邮件代理 | TCP | SMTP/IMAP/POP3 |

> **不适用场景**: 需要修改应用层协议内容、基于 HTTP 头的路由、URL 重写、WAF 功能。

---

## 13. OpenResty 与 Lua 扩展

### 13.1 OpenResty 概述

OpenResty 是基于 NGINX 和 LuaJIT 的高性能 Web 平台，通过将 Lua 嵌入 NGINX Worker 进程，实现强大的可编程能力。

```
┌─────────────────────────────────────┐
│           OpenResty 架构             │
├─────────────────────────────────────┤
│                                     │
│   ┌─────────────────────────────┐   │
│   │      NGINX (C 底层)         │   │
│   │  ┌───────────────────────┐  │   │
│   │  │   LuaJIT (Lua 引擎)   │  │   │
│   │  │  ┌─────────────────┐  │  │   │
│   │  │  │  Lua 脚本/库    │  │  │   │
│   │  │  │  resty.redis    │  │  │   │
│   │  │  │  resty.mysql    │  │  │   │
│   │  │  │  resty.http     │  │  │   │
│   │  │  └─────────────────┘  │  │   │
│   │  └───────────────────────┘  │   │
│   └─────────────────────────────┘   │
│                                     │
│   每个 Worker 进程内嵌一个 Lua VM    │
│   每个请求独占一个 Lua 协程           │
│   所有 I/O 操作非阻塞                │
└─────────────────────────────────────┘
```

### 13.2 Nginx 11 个处理阶段与 Lua 指令

```
NGINX 请求处理阶段:
┌─────────────────────────────────────────────────┐
│ 1. post-read          → set_by_lua*             │
│ 2. server-rewrite     → rewrite_by_lua*         │
│ 3. find-config         │                        │
│ 4. rewrite             → rewrite_by_lua*        │
│ 5. post-rewrite         │                       │
│ 6. preaccess           → access_by_lua*         │
│ 7. access              → access_by_lua*         │
│ 8. post-access          │                       │
│ 9. precontent           → content_by_lua*       │
│ 10. content            → content_by_lua*        │
│ 11. log                → log_by_lua*            │
│                        → header_filter_by_lua*  │
│                        → body_filter_by_lua*    │
│                        → balancer_by_lua*       │
└─────────────────────────────────────────────────┘
```

| OpenResty 指令 | 阶段 | 典型用途 |
|----------------|------|---------|
| `init_by_lua*` | Worker 启动 | 初始化全局变量、预加载模块 |
| `init_worker_by_lua*` | Worker 初始化 | 定时任务、健康检查 |
| `set_by_lua*` | rewrite | 变量计算 |
| `rewrite_by_lua*` | rewrite | URL 重写、路由匹配 |
| `access_by_lua*` | access | 认证、鉴权、限流、黑白名单 |
| `content_by_lua*` | content | 生成响应内容（API 网关核心） |
| `header_filter_by_lua*` | header filter | 修改响应头（CORS、追踪 ID） |
| `body_filter_by_lua*` | body filter | 修改响应体 |
| `log_by_lua*` | log | 日志记录、监控上报 |
| `balancer_by_lua*` | balancer | 动态负载均衡、故障转移 |

### 13.3 基础 Lua 示例

```nginx
http {
    # 初始化全局配置
    init_by_lua_block {
        -- 加载全局模块
        config = require("config")
        -- 预编译正则
        uuid_regex = ngx.re.compile("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", "i")
    }

    # Worker 定时任务
    init_worker_by_lua_block {
        local handler = function()
            -- 定时从 Redis 拉取配置
            local redis = require "resty.redis"
            local red = redis:new()
            -- ...
        end
        local ok, err = ngx.timer.every(10, handler)  -- 每 10 秒执行
    }

    server {
        listen 80;

        # Hello World
        location /hello {
            content_by_lua_block {
                ngx.say("Hello, OpenResty!")
                ngx.say("Client IP: ", ngx.var.remote_addr)
                ngx.say("Request URI: ", ngx.var.request_uri)
            }
        }

        # API 路由
        location /api/ {
            access_by_lua_block {
                -- 认证检查
                local token = ngx.req.get_headers()["Authorization"]
                if not token then
                    ngx.exit(401)
                end

                -- 从 Redis 验证 Token
                local redis = require "resty.redis"
                local red = redis:new()
                local ok, err = red:connect("127.0.0.1", 6379)
                if not ok then
                    ngx.log(ngx.ERR, "redis connect failed: ", err)
                    ngx.exit(500)
                end

                local user_id, err = red:get("token:" .. token)
                if not user_id or user_id == ngx.null then
                    ngx.exit(401)
                end

                -- 传递用户 ID 到后端
                ngx.req.set_header("X-User-Id", user_id)

                -- 连接放回连接池
                red:set_keepalive(10000, 100)
            }

            proxy_pass http://backend;
        }

        # 动态限流
        location /api/v1/ {
            access_by_lua_block {
                local limit_req = require "resty.limit.req"
                -- 限制: 每秒 10 个请求，允许突发 5 个
                local lim, err = limit_req.new("limit_req_zone", 10, 5)
                if not lim then
                    ngx.log(ngx.ERR, "failed to create limiter: ", err)
                    return ngx.exit(500)
                end

                local key = ngx.var.binary_remote_addr
                local delay, err = lim:incoming(key, true)
                if not delay then
                    if err == "rejected" then
                        return ngx.exit(429)
                    end
                    return ngx.exit(500)
                end

                if delay >= 0.001 then
                    ngx.sleep(delay)
                end
            }

            proxy_pass http://backend;
        }

        # 响应头修改（添加 CORS 和追踪 ID）
        header_filter_by_lua_block {
            ngx.header["Access-Control-Allow-Origin"] = "*"
            ngx.header["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            ngx.header["X-Request-Id"] = ngx.var.request_id or ngx.now()
        }

        # 日志记录
        log_by_lua_block {
            local metrics = require "metrics"
            metrics.record({
                method = ngx.req.get_method(),
                uri = ngx.var.uri,
                status = ngx.status,
                latency = ngx.now() - ngx.req.start_time(),
                upstream_time = ngx.var.upstream_response_time
            })
        }
    }
}
```

### 13.4 动态路由（API 网关核心）

```nginx
http {
    # 共享内存字典（Worker 间共享数据）
    lua_shared_dict routes 10m;

    init_worker_by_lua_file conf/init_routes.lua;

    server {
        listen 80;
        server_name api.example.com;

        location / {
            access_by_lua_file conf/auth.lua;
            content_by_lua_file conf/router.lua;
            log_by_lua_file conf/logger.lua;
        }
    }
}
```

```lua
-- conf/router.lua
-- 从 Redis 获取路由规则，实现毫秒级配置更新

local redis = require "resty.redis"
local red = redis:new()
red:set_timeout(1000)

local ok, err = red:connect("127.0.0.1", 6379)
if not ok then
    ngx.log(ngx.ERR, "redis connect failed: ", err)
    return ngx.exit(500)
end

-- 从 Redis 获取路由规则
local route_key = "api_gateway:routes:" .. ngx.var.host .. ngx.var.uri
local route_json, err = red:get(route_key)
if not route_json or route_json == ngx.null then
    -- 尝试通配匹配
    route_json = red:get("api_gateway:routes:" .. ngx.var.host .. "/*")
end

if not route_json or route_json == ngx.null then
    ngx.exit(404)
end

local cjson = require "cjson"
local route = cjson.decode(route_json)

-- 动态路由匹配
if ngx.re.match(ngx.var.request_uri, route.pattern, "jo") then
    -- 设置后端地址
    ngx.var.backend = route.backend

    -- 执行代理
    local balancer = require "ngx.balancer"
    local ok, err = balancer.set_current_peer(route.backend_host, route.backend_port)
    if not ok then
        ngx.log(ngx.ERR, "failed to set peer: ", err)
        return ngx.exit(502)
    end

    -- 连接放回连接池
    red:set_keepalive(10000, 100)

    -- 使用 proxy_pass 转发
    -- 注意: balancer_by_lua_block 配合 proxy_pass 使用
end
```

### 13.5 共享内存字典

```nginx
http {
    # 定义共享内存
    lua_shared_dict my_cache 10m;          # 10MB 缓存
    lua_shared_dict my_limit 5m;           # 限流计数器
    lua_shared_dict my_config 1m;          # 配置缓存

    server {
        location /cache {
            content_by_lua_block {
                local dict = ngx.shared.my_cache

                -- 写入缓存
                dict:set("key", "value", 60)  -- 60秒过期

                -- 读取缓存
                local val = dict:get("key")
                if val then
                    ngx.say("Cache HIT: ", val)
                else
                    ngx.say("Cache MISS")
                end

                -- 删除缓存
                -- dict:delete("key")

                -- 自增
                dict:incr("counter", 1)
            }
        }
    }
}
```

### 13.6 OpenResty 性能优势

| 特性 | 说明 |
|------|------|
| LuaJIT | 性能接近 C，远高于 Python/Node.js |
| 协程 | 自动管理，实现非阻塞 I/O |
| 共享内存 | Worker 间共享数据，无需锁 |
| cosocket | 协程套接字，非阻塞网络 I/O |
| 热更新 | Lua 脚本运行时加载，无需重启 |

> OpenResty 广泛用于 API 网关（如 Kong、APISIX）、动态 CDN、WAF、微服务代理等场景。在 1000 并发下平均响应时间可 < 50ms。

---

## 14. 高可用方案（Keepalived）

### 14.1 架构概述

单节点 NGINX 存在单点故障风险。通过 **NGINX + Keepalived** 实现 VIP（虚拟 IP）自动漂移，当主节点故障时，备用节点自动接管。

```
                    ┌──────────────────────────┐
                    │      客户端请求            │
                    │     访问 VIP: 192.168.1.200│
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │     VRRP 虚拟路由          │
                    │   VIP: 192.168.1.200      │
                    └────────────┬─────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │ VRRP Master      │ VRRP Backup      │
              ▼                  │                  ▼
  ┌────────────────────┐         │     ┌────────────────────┐
  │   Node-01 (主)      │         │     │   Node-02 (备)      │
  │   192.168.1.11     │◄────────┘     │   192.168.1.12     │
  │   Nginx + Keepalived│   心跳检测     │   Nginx + Keepalived│
  │   priority=100     │   (VRRP)      │   priority=90      │
  └────────┬───────────┘               └────────┬───────────┘
           │                                      │
           ▼                                      ▼
  ┌─────────────────────────────────────────────────────────┐
  │              后端服务器集群                                │
  │   192.168.1.21  192.168.1.22  192.168.1.23              │
  └─────────────────────────────────────────────────────────┘
```

### 14.2 主备模式配置

```bash
# 环境信息
# Node-01 (主): 192.168.1.11
# Node-02 (备): 192.168.1.12
# VIP:          192.168.1.200
```

**Node-01（主节点）Keepalived 配置**:

```bash
# /etc/keepalived/keepalived.conf

global_defs {
    router_id NGINX_MASTER              # 唯一标识
}

# Nginx 健康检查脚本
vrrp_script chk_nginx {
    script "/usr/bin/killall -0 nginx"  # 检测 nginx 进程
    interval 2                           # 每 2 秒检测
    weight -20                           # 失败时优先级 -20
}

vrrp_instance VI_1 {
    state MASTER                         # 主节点
    interface eth0                       # 网卡名称
    virtual_router_id 51                 # 虚拟路由 ID（主备必须相同）
    priority 100                         # 优先级（主 > 备）
    advert_int 1                         # 心跳间隔

    authentication {
        auth_type PASS
        auth_pass 1111                   # 认证密码（主备必须相同）
    }

    virtual_ipaddress {
        192.168.1.200                    # VIP
    }

    track_script {
        chk_nginx                        # 关联健康检查脚本
    }

    # 故障切换通知脚本
    notify_master "/etc/keepalived/notify.sh master"
    notify_backup "/etc/keepalived/notify.sh backup"
    notify_fault  "/etc/keepalived/notify.sh fault"
}
```

**Node-02（备节点）Keepalived 配置**:

```bash
# /etc/keepalived/keepalived.conf

global_defs {
    router_id NGINX_BACKUP
}

vrrp_script chk_nginx {
    script "/usr/bin/killall -0 nginx"
    interval 2
    weight -20
}

vrrp_instance VI_1 {
    state BACKUP                         # 备节点
    interface eth0
    virtual_router_id 51                 # 与主节点相同
    priority 90                          # 低于主节点
    advert_int 1

    authentication {
        auth_type PASS
        auth_pass 1111
    }

    virtual_ipaddress {
        192.168.1.200
    }

    track_script {
        chk_nginx
    }
}
```

### 14.3 双主模式（互为主备）

双主模式使用两个 VIP，两台节点互为主备，同时提供服务，提高资源利用率。

```bash
# Node-01 配置
vrrp_instance VI_1 {
    state MASTER
    interface eth0
    virtual_router_id 51
    priority 100
    virtual_ipaddress {
        192.168.1.200                    # VIP1 - Node-01 为主
    }
    track_script { chk_nginx }
}

vrrp_instance VI_2 {
    state BACKUP
    interface eth0
    virtual_router_id 52
    priority 90
    virtual_ipaddress {
        192.168.1.201                    # VIP2 - Node-01 为备
    }
    track_script { chk_nginx }
}

# Node-02 配置
vrrp_instance VI_1 {
    state BACKUP
    interface eth0
    virtual_router_id 51
    priority 90
    virtual_ipaddress {
        192.168.1.200
    }
    track_script { chk_nginx }
}

vrrp_instance VI_2 {
    state MASTER
    interface eth0
    virtual_router_id 52
    priority 100
    virtual_ipaddress {
        192.168.1.201
    }
    track_script { chk_nginx }
}

# DNS 轮询:
# example.com → 192.168.1.200
# example.com → 192.168.1.201
```

### 14.4 健康检查脚本

```bash
#!/bin/bash
# /etc/keepalived/check_nginx.sh

if [ -f /var/run/nginx.pid ]; then
    nginx_pid=$(cat /var/run/nginx.pid)
    if kill -0 $nginx_pid 2>/dev/null; then
        # 检查 Nginx 是否正常响应
        if curl -s -o /dev/null http://127.0.0.1/health; then
            exit 0
        fi
    fi
fi

# Nginx 不在运行，尝试重启
systemctl restart nginx
sleep 2

# 再次检查
if curl -s -o /dev/null http://127.0.0.1/health; then
    exit 0
else
    exit 1
fi
```

### 14.5 Keepalived 注意事项

| 事项 | 说明 |
|------|------|
| 防火墙 | 放行 VRRP 协议（协议号 112） |
| 网络隔离 | 心跳线与业务网络隔离 |
| 脑裂问题 | 配置 `vrrp_skip_check_adv_addr`，使用串口心跳线 |
| 公有云 | 部分公有云不支持 VRRP（组播），需使用云负载均衡或单播 |
| 配置同步 | 主备节点的 Nginx 配置必须一致（使用 Ansible/Git 同步） |
| VIP 仲裁 | 3 节点 Keepalived 集群可避免脑裂 |

---

## 15. 日志与监控

### 15.1 日志格式配置

```nginx
http {
    # ==================== 标准日志格式 ====================
    log_format main '$remote_addr - $remote_user [$time_local] '
                    '"$request" $status $body_bytes_sent '
                    '"$http_referer" "$http_user_agent" '
                    '$request_time $upstream_response_time';

    # ==================== JSON 日志格式（推荐 ELK 使用） ====================
    log_format json_analytics escape=json '{'
        '"msec":"$msec",'
        '"remote_addr":"$remote_addr",'
        '"remote_user":"$remote_user",'
        '"time_local":"$time_local",'
        '"request":"$request",'
        '"method":"$request_method",'
        '"uri":"$request_uri",'
        '"status":$status,'
        '"body_bytes_sent":$body_bytes_sent,'
        '"http_referer":"$http_referer",'
        '"http_user_agent":"$http_user_agent",'
        '"request_time":$request_time,'
        '"upstream_response_time":"$upstream_response_time",'
        '"upstream_addr":"$upstream_addr",'
        '"upstream_status":"$upstream_status",'
        '"connection":$connection,'
        '"connection_requests":$connection_requests,'
        '"ssl_protocol":"$ssl_protocol",'
        '"ssl_cipher":"$ssl_cipher",'
        '"x_forwarded_for":"$http_x_forwarded_for"'
    '}';

    # ==================== 使用日志格式 ====================
    access_log /var/log/nginx/access.log json_analytics buffer=32k flush=5m;
    error_log  /var/log/nginx/error.log warn;

    # ==================== 详细日志格式（包含更多字段） ====================
    log_format detailed '$remote_addr - $remote_user [$time_local] '
        '"$request" $status $body_bytes_sent '
        '"$http_referer" "$http_user_agent" '
        '$request_time $upstream_response_time '
        '$connection $connection_requests '
        '$ssl_protocol $ssl_cipher '
        '$pipe $request_length $bytes_sent '
        '$server_name $host $request_id';

    server {
        # 按域名分日志
        access_log /var/log/nginx/$host.access.log main;

        # 特定 location 不记录日志
        location ~* \.(jpg|jpeg|png|gif|ico|css|js)$ {
            access_log off;
        }

        # 健康检查不记录日志
        location = /health {
            access_log off;
            return 200 "OK";
        }
    }
}
```

### 15.2 日志切割（logrotate）

```
# /etc/logrotate.d/nginx

/var/log/nginx/*.log {
    daily                               # 每天切割
    missingok                           # 日志不存在不报错
    rotate 30                           # 保留 30 天
    compress                            # 压缩旧日志
    delaycompress                       # 延迟压缩（保留最近一个未压缩）
    notifempty                          # 空文件不切割
    create 0640 www-data adm            # 创建新日志文件的权限
    sharedscripts                       # 脚本只执行一次
    postrotate
        if [ -f /var/run/nginx.pid ]; then
            kill -USR1 `cat /var/run/nginx.pid`    # 通知 Nginx 重新打开日志
        fi
    endscript
}
```

### 15.3 日志分析命令

```bash
# ==================== 基础统计 ====================
# 总请求数
wc -l /var/log/nginx/access.log

# 状态码分布
awk '{print $9}' access.log | sort | uniq -c | sort -nr

# Top 10 请求 IP
awk '{print $1}' access.log | sort | uniq -c | sort -nr | head -10

# Top 10 请求 URL
awk '{print $7}' access.log | sort | uniq -c | sort -nr | head -10

# Top 10 User-Agent
awk -F'"' '{print $6}' access.log | sort | uniq -c | sort -nr | head -10

# ==================== 性能分析 ====================
# Top 10 最慢请求
awk '{print $10, $7}' access.log | sort -nr | head -10

# 请求时间分布
awk '{if($10<0.1) fast++; else if($10<1) medium++; else if($10<3) slow++; else very_slow++}
END{printf "fast(<0.1s): %d\nmedium(0.1-1s): %d\nslow(1-3s): %d\nvery_slow(>3s): %d\n", fast, medium, slow, very_slow}'
access.log

# ==================== 错误分析 ====================
# 4xx/5xx 错误统计
awk '$9 >= 400 {print $9, $7}' access.log | sort | uniq -c | sort -nr | head -20

# 实时错误率监控
tail -f access.log | awk '{
    total++;
    if($9 >= 400) errors++;
    if(total % 100 == 0) {
        printf "Error rate: %.2f%% (total: %d, errors: %d)\n", (errors/total)*100, total, errors;
    }
}'

# ==================== 流量分析 ====================
# 每小时流量统计
awk '{split($4, a, ":"); print a[2]}' access.log | sort | uniq -c

# 带宽使用
awk '{sum+=$10} END {printf "Total bandwidth: %.2f MB\n", sum/1024/1024}' access.log

# ==================== 安全分析 ====================
# 检测可疑爬虫
awk '{ip[$1]++; ua[$12]++} END {
    for(i in ip) if(ip[i] > 1000) printf "Suspicious IP: %s (%d)\n", i, ip[i];
    for(i in ua) if(ua[i] > 500) printf "Suspicious UA: %s (%d)\n", i, ua[i];
}' access.log

# SQL 注入检测
grep -iE "union|select|insert|delete|drop|update.*set" access.log | awk '{print $7}' | sort | uniq -c
```

### 15.4 GoAccess 实时分析

```bash
# 安装 GoAccess
apt-get install goaccess      # Debian/Ubuntu
yum install goaccess          # CentOS/RHEL

# 实时终端分析
goaccess /var/log/nginx/access.log -a

# 生成 HTML 报表（实时更新）
goaccess /var/log/nginx/access.log -a -o /var/www/html/report.html --real-time-html

# 使用自定义日志格式
goaccess access.log --log-format='%h %^[%d:%t %^] "%r" %s %b "%R" "%u" %T %^' \
    --date-format='%d/%b/%Y' --time-format='%H:%M:%S'
```

### 15.5 ELK Stack 集成

```yaml
# /etc/filebeat/filebeat.yml
filebeat.inputs:
  - type: log
    enabled: true
    paths:
      - /var/log/nginx/access.log
    fields:
      type: nginx-access
    fields_under_root: true

  - type: log
    enabled: true
    paths:
      - /var/log/nginx/error.log
    fields:
      type: nginx-error
    fields_under_root: true

output.logstash:
  hosts: ["logstash:5044"]

# Logstash 配置 (nginx.conf)
input {
  beats {
    port => 5044
  }
}

filter {
  if [type] == "nginx-access" {
    json {
      source => "message"
    }
    date {
      match => ["time_local", "dd/MMM/yyyy:HH:mm:ss Z"]
    }
  }
}

output {
  elasticsearch {
    hosts => ["elasticsearch:9200"]
    index => "nginx-%{+YYYY.MM.dd}"
  }
}
```

### 15.6 Prometheus + Grafana 监控

```nginx
# 方法1: 使用 nginx-prometheus-exporter（开源版）
# NGINX 配置 stub_status
server {
    listen 127.0.0.1:8080;
    location /stub_status {
        stub_status;
        access_log off;
        allow 127.0.0.1;
        deny all;
    }
}

# 方法2: 使用 lua-resty-prometheus（OpenResty）
http {
    lua_shared_dict prometheus_metrics 10m;

    init_by_lua_block {
        prometheus = require("prometheus").init("prometheus_metrics")
        metric_requests = prometheus:counter(
            "nginx_http_requests_total",
            "Number of HTTP requests",
            {"host", "status", "method"}
        )
        metric_latency = prometheus:histogram(
            "nginx_http_request_duration_seconds",
            "HTTP request latency",
            {"host"},
            {0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10}
        )
    }

    server {
        # 暴露指标
        location /metrics {
            content_by_lua_block {
                metric_requests:inc(1, {ngx.var.host, tostring(ngx.status), ngx.req.get_method()})
                metric_latency:observe(ngx.now() - ngx.req.start_time(), {ngx.var.host})
                prometheus:collect()
            }
        }

        # 在 log 阶段记录
        log_by_lua_block {
            metric_requests:inc(1, {ngx.var.host, tostring(ngx.status), ngx.req.get_method()})
            metric_latency:observe(ngx.now() - ngx.req.start_time(), {ngx.var.host})
        }
    }
}
```

---

## 16. 运维与故障排查

### 16.1 NGINX 信号机制

| 信号 | 命令 | 说明 |
|------|------|------|
| TERM/QUIT | `nginx -s stop` | 快速停止 |
| QUIT | `nginx -s quit` | 优雅停止（等待请求处理完） |
| HUP | `nginx -s reload` | 重载配置（平滑重启） |
| USR1 | `nginx -s reopen` | 重新打开日志文件 |
| USR2 | - | 平滑升级二进制文件 |
| WINCH | - | 优雅停止 Worker（用于升级） |

### 16.2 平滑升级

```bash
# 1. 备份旧二进制文件
cp /usr/sbin/nginx /usr/sbin/nginx.old

# 2. 替换为新二进制文件
cp /path/to/new/nginx /usr/sbin/nginx

# 3. 发送 USR2 信号（启动新的 Master）
kill -USR2 $(cat /var/run/nginx.pid)

# 4. 旧 Master 的 PID 文件重命名为 .oldbin
# 新 Master 和旧 Master 同时运行

# 5. 发送 WINCH 信号给旧 Master（优雅停止旧 Worker）
kill -WINCH $(cat /var/run/nginx.pid.oldbin)

# 6. 确认新版本正常后，退出旧 Master
kill -QUIT $(cat /var/run/nginx.pid.oldbin)

# 回滚:
# kill -HUP $(cat /var/run/nginx.pid.oldbin)  # 恢复旧 Worker
# kill -QUIT $(cat /var/run/nginx.pid)        # 停止新 Master
```

### 16.3 常见问题排查

#### 问题1: 502 Bad Gateway

```
原因:
├── 后端服务未启动或崩溃
├── 后端服务端口错误
├── 后端服务超时
├── SELinux 阻止连接
└── 后端连接数已满

排查:
# 1. 检查后端是否可达
curl http://backend:8080/health

# 2. 检查 Nginx 错误日志
tail -f /var/log/nginx/error.log | grep 502

# 3. 检查 SELinux
getenforce
# 如果是 Enforcing: setsebool -P httpd_can_network_connect 1

# 4. 检查后端连接数
ss -tunap | grep 8080 | wc -l

解决:
# 增大超时时间
proxy_connect_timeout 10s;
proxy_read_timeout 120s;

# 增大 keepalive
upstream backend {
    keepalive 64;
    keepalive_requests 1000;
    keepalive_timeout 60s;
}
```

#### 问题2: 504 Gateway Timeout

```
原因: 后端响应超时

解决:
proxy_connect_timeout 10s;
proxy_send_timeout 120s;
proxy_read_timeout 120s;

# 或针对特定长请求接口
location /api/upload {
    proxy_read_timeout 300s;
    proxy_pass http://backend;
}
```

#### 问题3: 413 Request Entity Too Large

```
原因: 请求体超过限制

解决:
client_max_body_size 100m;   # 调大限制
```

#### 问题4: 429 Too Many Requests

```
原因: 限流触发

解决:
# 调整限流参数
limit_req zone=general burst=50 nodelay;  # 增大 burst

# 或排除特定 IP
limit_req zone=general burst=20 nodelay;
limit_req_dry_run on;  # 干跑模式（仅记录日志不拦截）
```

#### 问题5: 连接数上不去

```
原因:
├── 系统文件描述符限制
├── worker_connections 设置过小
├── 系统端口范围不足
└── 内存不足

排查:
# 检查文件描述符
ulimit -n
cat /proc/$(cat /var/run/nginx.pid)/limits | grep "Max open files"

# 检查当前连接数
ss -tunap | grep nginx | wc -l

# 检查端口范围
sysctl net.ipv4.ip_local_port_range

解决:
# /etc/security/limits.conf
nginx soft nofile 65535
nginx hard nofile 65535

# nginx.conf
worker_rlimit_nofile 100000;
events { worker_connections 10240; }

# /etc/sysctl.conf
net.ipv4.ip_local_port_range = 1024 65535
```

#### 问题6: 502/503 间歇性出现

```
原因: 后端健康检查 + 请求分配到不健康节点

排查:
# 查看 upstream 错误
grep "upstream" /var/log/nginx/error.log

解决:
# 调整健康检查参数
server 192.168.1.101:8080 max_fails=3 fail_timeout=30s;

# 配置 proxy_next_upstream
proxy_next_upstream error timeout http_502 http_503 http_504;
proxy_next_upstream_tries 3;
proxy_next_upstream_timeout 10s;
```

#### 问题7: 内存泄漏

```
原因: 模块 bug 或连接池配置不当

排查:
# 监控 Nginx 内存使用
ps aux | grep nginx
top -p $(cat /var/run/nginx.pid)

# 查看 Nginx 内部状态
curl http://127.0.0.1:8080/stub_status

解决:
# 升级 Nginx 版本
# 调整连接池参数
# 定期重载（临时方案）
# 0 3 * * * nginx -s reload
```

#### 问题8: location 匹配不生效

```
原因: 不理解 location 优先级

排查:
# 检查匹配优先级
# = > ^~ > ~ / ~* > 无修饰符

# 使用 nginx -T 打印完整配置
nginx -T | grep location

# 添加 debug 日志
error_log /var/log/nginx/error.log debug;
```

#### 问题9: HTTPS 证书问题

```
# 证书链不完整
# 解决: 合并中间证书
cat intermediate.crt >> example.com.crt

# 私钥不匹配
openssl x509 -noout -modulus -in example.com.crt | openssl md5
openssl rsa -noout -modulus -in example.com.key | openssl md5
# 两个值应相同

# 证书过期
openssl s_client -connect example.com:443 -servername example.com 2>/dev/null | openssl x509 -noout -dates
```

#### 问题10: 性能突然下降

```
排查:
# 1. 检查 CPU 使用率
top -p $(pgrep -d ',' nginx)

# 2. 检查连接状态
ss -tunap | grep nginx | awk '{print $1}' | sort | uniq -c

# 3. 检查慢请求
awk '$10 > 1' /var/log/nginx/access.log | tail -20

# 4. 检查正则匹配效率
# 复杂正则可能消耗大量 CPU
# 使用 ^~ 前缀匹配避免不必要的正则检查

# 5. 检查 Gzip 压缩级别
# 过高的 gzip_comp_level 消耗 CPU
```

### 16.4 stub_status 状态查看

```nginx
server {
    listen 127.0.0.1:8080;
    location /stub_status {
        stub_status;
        access_log off;
        allow 127.0.0.1;
        deny all;
    }
}
```

```
# curl http://127.0.0.1:8080/stub_status
Active connections: 15
server accepts handled requests
 8456 8456 32891
Reading: 0 Writing: 3 Waiting: 12
```

| 指标 | 说明 |
|------|------|
| Active connections | 当前活跃连接数 |
| accepts | 已接受的连接总数 |
| handled | 已处理的连接总数 |
| requests | 已处理的请求总数 |
| Reading | 正在读取请求头的连接数 |
| Writing | 正在返回响应的连接数 |
| Waiting | 空闲等待中的连接数（Keepalive） |

---

## 17. 生产环境检查清单

### 17.1 配置安全检查

- [ ] `server_tokens off;` — 隐藏版本号
- [ ] HTTPS 强制跳转 — HTTP 301 → HTTPS
- [ ] TLS 仅启用 1.2/1.3 — 禁用不安全版本
- [ ] 安全响应头已配置 — HSTS / X-Frame-Options / X-Content-Type-Options 等
- [ ] 证书有效且未过期 — 自动续期已配置
- [ ] 限流已配置 — limit_req / limit_conn
- [ ] 请求体大小限制 — client_max_body_size
- [ ] 敏感文件已禁止访问 — .git / .env / 备份文件
- [ ] 防盗链已配置 — valid_referers
- [ ] 访问控制已配置 — 管理后台 IP 白名单

### 17.2 性能优化检查

- [ ] `worker_processes auto;` — 匹配 CPU 核心数
- [ ] `worker_connections 10240+;` — 足够的并发连接
- [ ] `worker_rlimit_nofile 65535+;` — 文件描述符限制
- [ ] `sendfile on;` — 零拷贝传输
- [ ] `tcp_nopush on;` + `tcp_nodelay on;` — TCP 优化
- [ ] `keepalive_timeout 65;` — 长连接
- [ ] `gzip on;` — 压缩已启用
- [ ] `open_file_cache` — 文件缓存已配置
- [ ] 代理缓存已配置 — proxy_cache
- [ ] 静态资源缓存头已设置 — expires
- [ ] 系统内核参数已优化 — sysctl
- [ ] ulimit 已调整 — /etc/security/limits.conf

### 17.3 高可用检查

- [ ] Keepalived 已部署 — 主备/双主模式
- [ ] 健康检查脚本已配置 — chk_nginx
- [ ] VIP 漂移已测试 — 手动停止 Nginx 验证
- [ ] 配置同步机制已建立 — Ansible/Git
- [ ] 后端健康检查已配置 — max_fails/fail_timeout
- [ ] 故障切换通知已配置 — notify 脚本

### 17.4 监控运维检查

- [ ] 日志格式已定义 — JSON 格式便于分析
- [ ] 日志切割已配置 — logrotate
- [ ] 监控告警已部署 — Prometheus/Grafana
- [ ] 关键指标已监控 — 连接数/状态码/响应时间
- [ ] 日志分析平台已集成 — ELK/Loki
- [ ] 告警阈值已设置 — 5xx 错误率/响应时间
- [ ] 备份策略已建立 — 配置文件定期备份
- [ ] 应急预案已编写 — 常见故障处理流程

### 17.5 常用调试技巧

```bash
# 测试配置
nginx -t
nginx -T  # 打印完整配置（含 include）

# 查看实际加载的模块
nginx -V 2>&1

# 查看连接状态
ss -tunap | grep nginx

# 实时监控日志
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log

# 测试单个请求
curl -v -H "Host: example.com" http://127.0.0.1/

# 测试 SSL
openssl s_client -connect example.com:443 -servername example.com

# 压力测试
ab -n 10000 -c 100 https://example.com/
wrk -t12 -c400 -d30s https://example.com/

# 查看进程状态
ps aux | grep nginx
top -H -p $(cat /var/run/nginx.pid)

# 查看系统限制
ulimit -a
cat /proc/$(cat /var/run/nginx.pid)/limits

# 网络连接分析
netstat -an | grep :80 | awk '{print $6}' | sort | uniq -c | sort -nr
```

---

## 附录

### A. NGINX 版本演进

| 版本 | 年份 | 关键特性 |
|------|------|---------|
| 1.0 | 2011 | 正式发布 |
| 1.9 | 2015 | Stream 模块（四层代理） |
| 1.11 | 2016 | HTTP/2 支持、动态模块 |
| 1.13 | 2017 | TLS 1.3 早期支持 |
| 1.19 | 2020 | TLS 1.3 正式支持 |
| 1.21 | 2021 | HTTP/3 早期实验 |
| 1.25 | 2023 | HTTP/3 (QUIC) 正式支持 |

### B. NGINX vs NGINX Plus

| 特性 | NGINX 开源版 | NGINX Plus |
|------|-------------|------------|
| 负载均衡 | ✅ | ✅ |
| 反向代理 | ✅ | ✅ |
| 静态服务 | ✅ | ✅ |
| 主动健康检查 | ❌ | ✅ |
| 动态配置 API | ❌ | ✅ |
| 会话持久性 | 仅 ip_hash | Cookie/Route/Learn |
| 实时监控仪表盘 | ❌ | ✅ |
| JWT 认证 | ❌ | ✅ |
| 高级缓存管理 | ❌ | ✅ Purge API |
| 商业支持 | ❌ | ✅ |

### C. 参考资源

- NGINX 官方文档: https://nginx.org/en/docs/
- NGINX 管理指南: https://docs.nginx.com/nginx/admin-guide/
- OpenResty 项目: https://openresty.org/
- ModSecurity WAF: https://github.com/SpiderLabs/ModSecurity-nginx
- OWASP CRS: https://github.com/coreruleset/coreruleset
- SSL 配置生成: https://ssl-config.mozilla.org/
- NGINX Config 生成器: https://www.digitalocean.com/community/tools/nginx

---

> **文档版本**: 2025 | **参考来源**: NGINX 官方文档 + 25 篇网络技术资料
>
> 本文档覆盖 NGINX 从核心架构到生产运维的全链路知识，包含 17 个章节、100+ 配置示例和 10+ 故障排查方案。
