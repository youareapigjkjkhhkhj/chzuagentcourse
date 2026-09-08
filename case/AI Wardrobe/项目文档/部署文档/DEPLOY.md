# Kaleido AI 智能衣柜 · 部署手册

本文档描述系统生产环境的全容器化部署流程：基础设施、后端微服务、前端均以 Docker 容器运行。

网关（9010）为唯一对外暴露的后端入口，前端经 Nginx 反向代理访问网关。

## 执行顺序总览

严格按以下顺序执行，每步完成后再进行下一步：

| 序号 | 操作 | 在哪台机器 | 对应章节 |
|---|---|---|---|
| 1 | 部署前配置修改（repackage、数据源地址） | 打包机（Windows 开发机） | 第 3 节 |
| 2 | 后端打包 + 前端打包 | 打包机 | 第 4、5 节 |
| 3 | 构建应用镜像（后端 11 个 + 前端 1 个） | 打包机或服务器 | 第 6 节 |
| 4 | 离线镜像导出/导入（服务器不通外网时必做） | 联网机 → 服务器 | 第 12 节 |
| 5 | 上传部署目录到 `/opt/kaleido/`，固定网络名 | 服务器 | 第 7.1 节 |
| 6 | 修改 `SEATA_IP` 后启动基础设施 compose | 服务器 | 第 7.2、7.3 节 |
| 7 | Nacos 建命名空间 + 导入配置 | 服务器 | 第 7.4 节 |
| 8 | 创建 `.env` 并启动应用服务 compose | 服务器 | 第 8、9 节 |
| 9 | 按验证清单逐项检查 | 服务器 | 第 10 节 |

> 打包机与部署服务器为同一台机器时（如 `192.168.52.133` 本身可联网），第 3、4 步
> 合并为直接在该机构建；第 12 节可跳过。

---

## 1. 系统组成

### 1.1 后端服务

| 服务 | 端口 | 说明 |
|---|---|---|
| kaleido-gateway | 9010 | API 网关，对外暴露 |
| kaleido-auth | 9011 | 认证授权 |
| kaleido-user | 9012 | 用户服务 |
| kaleido-admin | 9013 | 管理后台 |
| kaleido-notice | 9014 | 通知服务 |
| kaleido-wardrobe | 9017 | 衣柜核心服务 |
| kaleido-coin | 9018 | 金币服务 |
| kaleido-tag | 9019 | 标签服务 |
| kaleido-ai | 9020 | AI 服务 |
| kaleido-recommend | 9029 | 推荐服务 |
| kaleido-message | 9030 | 消息服务 |

服务间通过 Dubbo 通信（随机端口，经 Nacos 服务发现），无需在防火墙开放额外端口。

### 1.2 基础设施

| 组件 | 版本 | 端口 |
|---|---|---|
| Nacos | 2.2.3 | 8848 / 9848 |
| MySQL | 8.0 | 3306 |
| Redis | 7.2 | 6379 |
| MongoDB | 7.0 | 27017 |
| RabbitMQ | 3.12 | 5672 / 15672 |
| Milvus | 2.5 | 19530 |
| MinIO | 2024-05 | 9000 / 9001 |
| Seata | 1.8.0 | 8091 |
| XXL-Job Admin | 2.4.1 | 9090 |
| Sentinel Dashboard | 1.8.6 | 8858 |
| Elasticsearch / Logstash / Kibana | 7.17 | 9200 / 4560 / 5601 |
| SkyWalking OAP / UI | 9.7.0 | 11800 / 12800 / 8080 |
| Prometheus / Grafana | 2.54 / 10.2 | 9090 / 4000 |

---

## 2. 环境要求

| 项目 | 要求 |
|---|---|
| 服务器内存 | ≥ 16 GB |
| 磁盘 | ≥ 60 GB |
| Docker / Compose | Docker 24+，Compose v2 |
| 打包机 JDK | 21 |
| 打包机 Maven | 3.8+ |
| 前端打包 Node / pnpm | 18+ / 8.x |
| 外网访问 | 需能访问 AI 模型服务（默认 `https://api.siliconflow.cn`） |

---

## 3. 部署前配置修改

以下两项修改在打包前完成，否则服务无法启动。

### 3.1 开启可执行 jar 打包

在以下 11 个服务模块的 `pom.xml` 中，`<build><plugins>` 内添加 spring-boot-maven-plugin 打包配置：

模块清单：`kaleido-gateway`、`kaleido-auth`、`kaleido-admin`、`kaleido-notice`、
`kaleido-biz/kaleido-user`、`kaleido-biz/kaleido-wardrobe`、`kaleido-biz/kaleido-ai`、
`kaleido-biz/kaleido-tag`、`kaleido-biz/kaleido-coin`、`kaleido-biz/kaleido-message`、
`kaleido-biz/kaleido-recommend`

```xml
<plugin>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-maven-plugin</artifactId>
</plugin>
```

说明：父 pom 继承自 `spring-boot-starter-parent:3.5.6`，其 pluginManagement 已绑定
`repackage` 目标并管理插件版本，子模块声明插件即可，无需再写 `<executions>`。
该配置仅添加到上述服务模块，不得添加到 `kaleido-common` 下的公共模块。

> 打包脚本 `source code/build-backend.bat`（Windows）或 `build-backend.sh`
> （Linux/macOS）已内置本节与 3.2 节的修改、依赖校验与产物收集，推荐直接执行脚本。

### 3.2 修改数据源地址

编辑 `kaleido-common/kaleido-ds/src/main/resources/sharding.yaml`，将两个数据源的
`url` 中 `127.0.0.1` 改为 `mysql`（容器网络服务名）：

```bash
sed -i 's|jdbc:mysql://127.0.0.1:3306/kaleido_|jdbc:mysql://mysql:3306/kaleido_|g' \
  kaleido-common/kaleido-ds/src/main/resources/sharding.yaml
```

修改后两个数据源分别为：

```
jdbc:mysql://mysql:3306/kaleido_0?useUnicode=true&characterEncoding=utf-8&useSSL=false&serverTimezone=Asia/Shanghai&allowPublicKeyRetrieval=true
jdbc:mysql://mysql:3306/kaleido_1?useUnicode=true&characterEncoding=utf-8&useSSL=false&serverTimezone=Asia/Shanghai&allowPublicKeyRetrieval=true
```

---

## 4. 后端打包

在 `backend` 目录执行：

```bash
mvn clean package -DskipTests -pl \
  kaleido-gateway,kaleido-auth,kaleido-admin,kaleido-notice,\
  kaleido-biz/kaleido-user,kaleido-biz/kaleido-wardrobe,kaleido-biz/kaleido-ai,\
  kaleido-biz/kaleido-tag,kaleido-biz/kaleido-coin,kaleido-biz/kaleido-message,\
  kaleido-biz/kaleido-recommend \
  -am
```

收集产物（jar 命名格式 `<模块名>-1.0.0.jar`）：

```bash
mkdir -p deploy/backend/jars
for m in kaleido-gateway kaleido-auth kaleido-admin kaleido-notice; do
  cp $m/target/$m-1.0.0.jar deploy/backend/jars/
done
for m in user wardrobe ai tag coin message recommend; do
  cp kaleido-biz/kaleido-$m/target/kaleido-$m-1.0.0.jar deploy/backend/jars/
done
```

---

## 5. 前端打包

在 `frontend` 目录执行：

```bash
pnpm install
pnpm run build:pro
```

产物输出至 `dist-pro/`。

构建前确认 `.env.pro` 中以下配置：

| 配置项 | 生产建议值 |
|---|---|
| VITE_USE_MOCK | false |
| VITE_USE_BUNDLE_ANALYZER | false |
| VITE_SOURCEMAP | false |

---

## 6. 镜像构建

### 6.1 后端镜像

`deploy/backend/Dockerfile`：

```dockerfile
FROM eclipse-temurin:21-jre

WORKDIR /app

ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

ARG JAR
COPY jars/${JAR} app.jar

ENV JAVA_OPTS="-Xms256m -Xmx512m"
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar app.jar"]
```

构建 11 个服务镜像：

```bash
cd deploy/backend
for s in gateway auth admin notice user wardrobe ai tag coin message recommend; do
  docker build --build-arg JAR=kaleido-$s-1.0.0.jar -t kaleido/$s:1.0.0 .
done
```

### 6.2 前端镜像

`deploy/frontend/Dockerfile`：

```dockerfile
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY dist-pro/ /usr/share/nginx/html
EXPOSE 80
```

`deploy/frontend/nginx.conf`：

```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location ~ ^/kaleido-(auth|user|notice|admin|wardrobe|tag|coin|ai|message|recommend|mcp|file)/ {
        proxy_pass http://gateway:9010;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

构建：

```bash
docker build -t kaleido/frontend:1.0.0 .
```

---

## 7. 基础设施部署

### 7.1 服务器标准部署目录

统一部署根目录为 `/opt/kaleido/`，结构如下：

```
mkdir -p /opt/kaleido/

/opt/kaleido/
├── infra/                            # 基础设施
│   ├── docker-compose.yml            # 由 dev-ops/docker-compose.yml 上传
│   ├── mysql/                        # my.cnf 与初始化 SQL
│   ├── redis/                        # redis.conf
│   ├── rabbitmq/                     # enabled_plugins
│   ├── elasticsearch/
│   ├── logstash/
│   ├── kibana/
│   ├── prometheus/
│   ├── grafana/
│   └── volumes/                      # Milvus/MinIO/etcd 数据卷，运行时自动生成
├── services/                         # 应用服务
│   ├── docker-compose.services.yml
│   └── .env                          # 环境变量（见第 8 节）
├── backend/
│   ├── Dockerfile
│   └── jars/                         # 11 个服务 jar
├── frontend/
│   ├── Dockerfile
│   ├── nginx.conf
│   └── dist-pro/                     # 前端构建产物
├── nacos/
│   └── nacos_config_export.zip       # Nacos 配置导入包
└── images/                           # 离线镜像 tar 包（见第 12 节）


#!/bin/bash
set -e

BASE="/opt/kaleido"

mkdir -p ${BASE}/{infra,services,backend,frontend,nacos,images}

# infra 子目录
mkdir -p ${BASE}/infra/{mysql,redis,rabbitmq,elasticsearch,logstash,kibana,prometheus,grafana,volumes}

# services
# services下面只需要目录，docker-compose.services.yml、.env 后续手动放置

# backend
mkdir -p ${BASE}/backend/jars

# frontend
mkdir -p ${BASE}/frontend/dist-pro

echo "目录结构创建完成：${BASE}"
tree -L 3 ${BASE} || ls -la ${BASE}

```

上传命令（打包机 → 服务器）：

```bash
scp -r deploy/* root@192.168.52.133:/opt/kaleido/
```

注意：`infra/` 下的 `mysql/`、`redis/` 等配置目录必须与 `docker-compose.yml` 位于同一级，
compose 通过相对路径挂载这些文件。

随附的 `docker-compose.yml` 已内置以下网络声明（网络名固定为 `kaleido-env-network`，
且 Milvus / etcd / MinIO 三个容器已加入该网络，供应用容器按服务名访问）：

```yaml
networks:
  kaleido-env-network:
    driver: bridge
    name: kaleido-env-network
```

应用服务编排文件 `docker-compose.services.yml` 位于 `部署文档/` 根目录，
上传至服务器 `/opt/kaleido/services/` 使用。

### 7.2 启动前配置

随附的 `docker-compose.yml` 中 seata 的 `SEATA_IP` 已预设为 `192.168.52.133`。
如服务器 IP 不同，启动前需修改（否则 Seata 客户端无法建立连接）：

```yaml
- SEATA_IP=192.168.52.133
```

### 7.3 启动基础设施

先在服务器上创建数据目录并授权。ES、Grafana、MongoDB、Prometheus 容器均以非 root 用户运行
（uid 实测分别为 1000、472、1000、65534；MongoDB 社区镜像不同版本 uid 有差异，可用
`docker run --rm --entrypoint sh mongodb/mongodb-community-server:latest -c "id mongodb"`
核实），目录不存在时 Docker 会以 root 创建，导致容器因 `Permission denied` 反复重启：

```bash
mkdir -p elasticsearch/data mongodb/data mongodb/log grafana/data prometheus/data
chown -R 1000:1000 elasticsearch
chown -R 472:472 grafana
chown -R 1000:1000 mongodb
chown -R 65534:65534 prometheus
```

```bash
cd /opt/kaleido/infra
docker compose -f docker-compose.yml up -d
```

首次启动说明：

- MySQL 自动执行 `mysql/sql/` 下的初始化脚本，自动创建 `kaleido_0`、`kaleido_1`、
  `nacos_config`、`xxl_job`、`seata` 等数据库，无需手动建库。
- 初始化脚本仅在 MySQL 数据卷为空时执行一次；如需重新初始化，删除数据卷后重启。
- Milvus、Elasticsearch 健康检查约需 90 秒，启动后执行以下命令确认状态：

```bash
docker-compose -f docker-compose.yml ps
```

### 7.4 Nacos 初始化

1. 访问 `http://192.168.52.133:8848/nacos`，账号密码 nacos / nacos。
2. 创建两个命名空间（命名空间 ID 必须与下表完全一致）：

| 命名空间名称 | 命名空间 ID |
|---|---|
| kaleido | `30d71fbd-2d24-4757-81f4-679d26f0ed93` |
| dubbo | `aa3a3ee8-fb98-43e5-b3da-11b368d88c21` |

3. 切换至 `kaleido` 命名空间 → 配置列表 → 导入配置，选择 `nacos_config_export.zip`。
4. 确认配置列表加载了 `kaleido-gateway-dev.yml` 等全部配置。

---

## 8. 环境变量配置

在 `deploy/services/` 目录创建 `.env` 文件，内容如下。所有服务容器通过该文件注入配置。

```bash
# ===== Nacos =====
NACOS_HOST=nacos
NACOS_PORT=8848
NACOS_NAMESPACE=30d71fbd-2d24-4757-81f4-679d26f0ed93
NACOS_DUBBO_NAMESPACE=aa3a3ee8-fb98-43e5-b3da-11b368d88c21

# ===== Seata =====
SEATA_HOST=seata
SEATA_GROUPLIST_PORT=8091

# ===== Sentinel =====
SENTINEL_HOST=sentinel
SENTINEL_DASHBOARD_PORT=8858
SENTINEL_TRANSPORT_PORT=8719

# ===== SkyWalking =====
SKYWALKING_OAP=skywalking-oap:11800

# ===== AI 模型服务 =====
AI_BASE_URL=https://api.siliconflow.cn
AI_API_KEY=<替换为实际 Key>
CHAT_MODEL=deepseek-ai/DeepSeek-V3
EMBEDDING_MODEL=BAAI/bge-m3

# ===== Milvus =====
MILVUS_HOST=standalone
MILVUS_PORT=19530
MILVUS_USERNAME=root
MILVUS_PASSWORD=Milvus

# ===== MongoDB =====
MONGODB_HOST=mongodb
MONGODB_PORT=27017
MONGODB_USERNAME=root
MONGODB_PASSWORD=kaleido123

# ===== MinIO =====
minio_endpoint=http://minio:9000
minio_fileHost=http://192.168.52.133:9000
minio_accessKey=minioadmin
minio_secretKey=minioadmin

# ===== RabbitMQ =====
rabbitmq_address=rabbitmq
rabbitmq_port=5672
rabbitmq_username=admin
rabbitmq_password=kaleido123

# ===== XXL-Job =====
xxl_job.accessToken=default_token
xxl_job.admin.address=xxl-job-admin:9090
xxl_job.executor.appName=kaleido-job-executor
xxl_job.executor.port=9999

# ===== Redis =====
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=kaleido123
```

配置项说明：

| 配置 | 约束 |
|---|---|
| minio_accessKey / minio_secretKey | 必须与 docker-compose.yml 中 MINIO_ACCESS_KEY / MINIO_SECRET_KEY 一致 |
| minio_fileHost | 使用服务器实际 IP 或域名，客户端需能直接访问（该地址写入返回的文件 URL） |
| xxl_job.admin.address | 必须为容器网络内地址 `xxl-job-admin:9090`，不可使用宿主机映射端口 |
| MILVUS_PASSWORD | Milvus 默认账号 root / Milvus |
| AI_API_KEY | 生产环境通过运维下发，不得提交至代码仓库 |

---

## 9. 应用服务部署

### 9.1 编排文件

`deploy/docker-compose.services.yml`：

```yaml
name: kaleido-services

x-common: &common
  restart: always
  env_file: .env
  networks:
    - kaleido-env-network
  depends_on:
    nacos-init:
      condition: service_completed_successfully

services:
  nacos-init:
    image: curlimages/curl:latest
    networks:
      - kaleido-env-network
    command: >
      sh -c "until curl -sf http://nacos:8848/nacos/v1/console/health/readiness;
      do echo waiting-nacos; sleep 5; done"

  gateway:
    <<: *common
    image: kaleido/gateway:1.0.0
    container_name: kaleido-gateway
    ports:
      - "9010:9010"

  auth:
    <<: *common
    image: kaleido/auth:1.0.0
    container_name: kaleido-auth

  user:
    <<: *common
    image: kaleido/user:1.0.0
    container_name: kaleido-user

  admin:
    <<: *common
    image: kaleido/admin:1.0.0
    container_name: kaleido-admin

  notice:
    <<: *common
    image: kaleido/notice:1.0.0
    container_name: kaleido-notice

  wardrobe:
    <<: *common
    image: kaleido/wardrobe:1.0.0
    container_name: kaleido-wardrobe

  coin:
    <<: *common
    image: kaleido/coin:1.0.0
    container_name: kaleido-coin

  tag:
    <<: *common
    image: kaleido/tag:1.0.0
    container_name: kaleido-tag

  ai:
    <<: *common
    image: kaleido/ai:1.0.0
    container_name: kaleido-ai

  message:
    <<: *common
    image: kaleido/message:1.0.0
    container_name: kaleido-message

  recommend:
    <<: *common
    image: kaleido/recommend:1.0.0
    container_name: kaleido-recommend

  frontend:
    <<: *common
    image: kaleido/frontend:1.0.0
    container_name: kaleido-frontend
    ports:
      - "80:80"

networks:
  kaleido-env-network:
    external: true
```

说明：`kaleido-env-network` 为基础设施 compose 创建的网络，通过 `external: true` 复用，
使应用容器可以直接以服务名访问 Nacos、MySQL、Redis 等组件。基础设施 compose 已按第 7.1 节
通过 `name: kaleido-env-network` 固定网络名称；如名称仍不一致，执行
`docker network ls | grep kaleido` 查询后替换。

### 9.2 启动

```bash
cd /opt/kaleido/services
docker-compose -f docker-compose.services.yml up -d
```

---

## 10. 验证

### 10.1 验证清单

| 检查项 | 方法 | 预期结果 |
|---|---|---|
| 基础设施状态 | `docker compose -f docker-compose.yml ps` | 关键容器 Up（healthy） |
| Nacos 服务列表（kaleido 命名空间） | http://192.168.52.133:8848/nacos | 11 个 kaleido-* 服务已注册 |
| Nacos 服务列表（dubbo 命名空间） | 同上，切换命名空间 | Dubbo provider 已注册 |
| 网关连通 | `curl http://192.168.52.133:9010/kaleido-auth/actuator/health` | 返回健康状态 |
| 前端页面 | http://192.168.52.133/ | 页面正常打开 |
| Milvus | `curl http://192.168.52.133:9091/healthz` | OK |
| RabbitMQ 控制台 | http://192.168.52.133:15672 | admin / kaleido123 |
| XXL-Job 控制台 | http://192.168.52.133:9090/xxl-job-admin | 执行器自动注册 |
| Sentinel 控制台 | http://192.168.52.133:8858 | sentinel / sentinel |
| Kibana 日志 | http://192.168.52.133:5601 | 业务日志可查询 |

### 10.2 日志查看

```bash
docker logs -f kaleido-gateway
docker logs -f kaleido-ai
```

### 10.3 访问账号

**业务系统登录**（无密码体系，手机号 + 短信验证码）：

| 项 | 值 |
|---|---|
| 管理端手机号 | `13066668888` 或 `13266668888`（SQL 预置于 `t_admin` 表） |
| 用户端 | 无预置账号，任意手机号走注册流程 |
| 验证码 | 短信发送为空实现（`SmsService.sendSmsMsg` 待集成短信平台），验证码存于 Redis |

在前端点击发送验证码后，于服务器执行以下命令获取验证码：

```bash
# 查看全部验证码 key（admin=管理端，user=用户端）
docker exec redis redis-cli -a kaleido123 keys 'kaleido:verify_code:*'

# 读取验证码（key 以第 1 条命令的实际输出为准）
docker exec redis redis-cli -a kaleido123 get 'kaleido:verify_code:sms:admin:13066668888'
```

备选：验证码同时渲染在 `t_notice` 表 `content` 字段，可查最近一条记录。

**中间件控制台**：

| 控制台 | 地址 | 账号 / 密码 |
|---|---|---|
| Nacos | `http://192.168.52.133:8848/nacos` | nacos / nacos |
| RabbitMQ | `http://192.168.52.133:15672` | admin / kaleido123 |
| XXL-Job | `http://192.168.52.133:9099/xxl-job-admin` | admin / 123456 |
| Sentinel | `http://192.168.52.133:8858` | sentinel / sentinel |
| MinIO 控制台 | `http://192.168.52.133:9001` | minioadmin / minioadmin |
| MySQL | `192.168.52.133:3306` | root / kaleido123 |
| Redis | `192.168.52.133:6379` | 密码 kaleido123 |
| MongoDB | `192.168.52.133:27017` | root / kaleido123 |

---

## 11. 常见问题

| 现象 | 排查方向 |
|---|---|
| 服务反复重启，报 Nacos 连接失败 | 确认 `.env` 中 NACOS_HOST 为 `nacos`，且两个 compose 使用同一网络 |
| 启动报 `no main manifest attribute` | 第 3.1 节 repackage 配置未添加，重新打包 |
| 启动报 ShardingSphere / 数据源错误 | 第 3.2 节 sharding.yaml 未修改，重新打包 |
| 文件上传返回 403 | MinIO 密钥不一致，核对第 8 节配置项说明 |
| 定时任务不执行 | xxl_job.admin.address 未使用容器内地址，核对第 8 节 |
| AI 对话报错 | AI_API_KEY 未配置或服务器无法访问模型服务 |
| Dubbo 调用无 provider | Nacos 中 dubbo 命名空间 ID 与 NACOS_DUBBO_NAMESPACE 不一致 |
| 前端可访问但接口 404 | Nginx 反代规则与网关路由前缀不匹配，核对第 6.2 节 |

---

## 12. 附录：离线镜像导入

无外网环境时，在联网机器导出镜像后拷贝至服务器导入。

### 12.1 需要导出的镜像清单

基础设施镜像（与 `docker-compose.yml` 一致，共 18 个）：

| 镜像 | 版本 |
|---|---|
| nacos/nacos-server | v2.2.3-slim |
| mysql | 8.0.32 |
| redis | 7.2-alpine |
| mongodb/mongodb-community-server | latest |
| rabbitmq | 3.12.9 |
| xuxueli/xxl-job-admin | 2.4.1 |
| quay.io/prometheus/prometheus | v2.54.1 |
| grafana/grafana | 10.2.0 |
| apache/skywalking-oap-server | 9.7.0 |
| apache/skywalking-ui | 9.7.0 |
| bladex/sentinel-dashboard | 1.8.6 |
| seataio/seata-server | 1.8.0 |
| quay.io/coreos/etcd | v3.5.18 |
| minio/minio | RELEASE.2024-05-28T17-19-04Z |
| milvusdb/milvus | v2.5.26 |
| elasticsearch | 7.17.28 |
| logstash | 7.17.28 |
| kibana | 7.17.28 |

构建基础镜像（应用镜像在服务器上构建时需要，共 3 个）：

| 镜像 | 用途 |
|---|---|
| eclipse-temurin:21-jre | 后端服务运行时 |
| nginx:alpine | 前端托管 |
| curlimages/curl:latest | 服务编排中的启动等待任务 |

### 12.2 导出（联网机器执行）

```bash
IMAGES=(
  nacos/nacos-server:v2.2.3-slim
  mysql:8.0.32
  redis:7.2-alpine
  mongodb/mongodb-community-server:latest
  rabbitmq:3.12.9
  xuxueli/xxl-job-admin:2.4.1
  quay.io/prometheus/prometheus:v2.54.1
  grafana/grafana:10.2.0
  apache/skywalking-oap-server:9.7.0
  apache/skywalking-ui:9.7.0
  bladex/sentinel-dashboard:1.8.6
  seataio/seata-server:1.8.0
  quay.io/coreos/etcd:v3.5.18
  minio/minio:RELEASE.2024-05-28T17-19-04Z
  milvusdb/milvus:v2.5.26
  elasticsearch:7.17.28
  logstash:7.17.28
  kibana:7.17.28
  eclipse-temurin:21-jre
  nginx:alpine
  curlimages/curl:latest
)

for img in "${IMAGES[@]}"; do
  docker pull "$img" || { echo "PULL FAILED: $img, retrying..."; docker pull "$img" || exit 1; }
done

# 校验：全部镜像存在于本地后才允许导出，防止遗漏导致 compose 起不来
MISSING=0
for img in "${IMAGES[@]}"; do
  docker image inspect "$img" >/dev/null 2>&1 || { echo "MISSING: $img"; MISSING=1; }
done
[ "$MISSING" -eq 0 ] || { echo "存在缺失镜像，禁止导出，请重新 pull"; exit 1; }

docker save -o kaleido-images.tar "${IMAGES[@]}"
```

> 注意：网络抖动会导致单个镜像 pull 超时（如 `bladex/sentinel-dashboard:1.8.6` 曾出现
> `Client.Timeout exceeded`），此时后续 `docker save` 会报 `reference does not exist`。
> 上方脚本已加入重试与导出前校验；手工操作时必须确认 21 个镜像全部
> `docker images` 可见后再执行 save。

### 12.3 导入（部署服务器执行）

```bash
cd /opt/kaleido/images
docker load -i kaleido-images.tar
docker images   # 核对镜像标签与 docker-compose.yml 声明一致
```

导入后核对镜像标签与 `docker-compose.yml` 中声明一致；不一致时修改 compose 的
`image` 字段以匹配实际版本，不得使用 `docker tag` 修改镜像标签。

---

## 13. 上线安全检查

| 检查项 | 要求 |
|---|---|
| 默认口令 | 更换 MySQL、Redis、MongoDB、RabbitMQ、MinIO、Nacos 的默认口令，同步更新 `.env` 与相关配置 |
| 网关 CORS | 修改 Nacos 中 `kaleido-gateway-dev.yml` 的 allowedOrigins，限制为前端实际域名 |
| AI API Key | 通过运维渠道下发，不落代码仓库 |
| Nacos Token | 更换 NACOS_AUTH_TOKEN 为随机 Base64 串 |
| 端口暴露 | 仅开放 80、9010 及必要控制台端口，数据库类端口不对公网开放 |
| 短信验证码 | 接入真实短信平台（`kaleido-sms` 的 `SmsService.sendSmsMsg` 当前为空实现），避免验证码明文存于 Redis 导致任意手机号可登录 |

容器因宿主机目录权限反复重启（Permission denied）时：

```bash
cd /opt/kaleido/infra
mkdir -p grafana/data mongodb/data mongodb/log prometheus/data
chown -R 472:472 grafana        # Grafana 官方镜像以 uid 472 运行
chown -R 1000:1000 mongodb      # MongoDB 社区镜像实测以 uid 1000 运行
chown -R 65534:65534 prometheus # Prometheus 官方镜像以 uid 65534 (nobody) 运行
docker compose -f docker-compose.yml up -d --force-recreate grafana mongodb prometheus
```

