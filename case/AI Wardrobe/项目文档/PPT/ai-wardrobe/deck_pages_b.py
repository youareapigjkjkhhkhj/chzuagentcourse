# -*- coding: utf-8 -*-
"""deck_pages_b.py —— P13-P22（选型矩阵 / 公共模块与基础设施深潜）"""
PAGES_B = [
    # ---------- P13 选型理由 matrix ----------
    {"type": "matrix", "kicker": "03 · 选型", "title": "为什么选它：关键选型对照",
     "headers": ["关注点", "选型", "替代方案 & 取舍"],
     "rows": [
         ["API 网关", "Spring Cloud Gateway（WebFlux）", "Zuul 已停维；WebFlux 适配 Sa-Token Reactor 鉴权"],
         ["注册/配置", "Nacos 2.3", "Eureka 无配置中心；双 namespace 隔离主配置与 Dubbo"],
         ["服务间 RPC", "Dubbo 3.3（契约库优先）", "全仓无 OpenFeign/HTTP 直连 —— kaleido-api 契约独立演进"],
         ["缓存策略", "JetCache：Caffeine + Redis", "纯 Redis 网络开销高；两级缓存保热点读"],
         ["限流/熔断", "Sentinel + 自研 @RateLimit", "规则可 Nacos 下发；注解细粒度到用户/手机号"],
         ["AI 接入", "Spring AI 1.1.2", "仓库另留 langchain4j-demo 做双实现对照"]]},
    # ---------- P14 公共模块总览 matrix ----------
    {"type": "matrix", "kicker": "04 · 公共", "title": "kaleido-common：21 个 starter 五类盘点",
     "headers": ["分类", "starter 模块", "封装 / 职责"],
     "rows": [
         ["Web 横切", "web · aop", "全局异常/JACKSON；AOP 代理与空返回检查"],
         ["数据", "ds · cache · file", "MP+ShardingSphere 分片；Redis/Redisson/JetCache；MinIO"],
         ["分布式协作", "nacos · rpc · mq", "注册配置壳；Dubbo 开关+异常过滤；MQ 事件抽象"],
         ["高可用", "lock · limiter · sentinel · seata · distribute · dynamic-tp · job", "锁/限流注解；Sentinel/Seata 壳；雪花 ID；动态线程池；XXL-Job"],
         ["认证与工具", "sa-token · base · api · doc · sms · monitor", "双 StpLogic；Result/异常；128 契约接口；smart-doc；短信桩；Micrometer"]]},
    # ---------- P15 Nacos diagram ----------
    {"type": "diagram", "diagram": "dg_nacos", "kicker": "04 · 基础设施",
     "title": "Nacos：服务注册 + 配置中心", "bounds": "100 170 1080 480"},
    # ---------- P16 网关与鉴权 diagram ----------
    {"type": "diagram", "diagram": "dg_gateway", "kicker": "04 · 基础设施",
     "title": "Spring Cloud Gateway + Sa-Token：一次请求的鉴权路径", "bounds": "100 170 1080 490"},
    # ---------- P17 Dubbo diagram ----------
    {"type": "diagram", "diagram": "dg_dubbo", "kicker": "04 · 基础设施",
     "title": "Dubbo RPC：契约库 + 注册发现 + 统一异常", "bounds": "100 170 1080 480"},
    # ---------- P18 RabbitMQ diagram ----------
    {"type": "diagram", "diagram": "dg_mq", "kicker": "04 · 基础设施",
     "title": "RabbitMQ 事件总线：4 条 topic × 4 个消费者", "bounds": "100 170 1080 500"},
    # ---------- P19 多级缓存 diagram ----------
    {"type": "diagram", "diagram": "dg_cache", "kicker": "04 · 基础设施",
     "title": "多级缓存：Caffeine(L1) + Redis(L2) + 延迟删除", "bounds": "100 170 1080 480"},
    # ---------- P20 分布式锁 diagram ----------
    {"type": "diagram", "diagram": "dg_lock", "kicker": "04 · 基础设施",
     "title": "分布式锁：自研注解 @DistributedLock + Redisson", "bounds": "100 170 1080 480"},
    # ---------- P21 数据访问层 diagram ----------
    {"type": "diagram", "diagram": "dg_ds", "kicker": "04 · 基础设施",
     "title": "数据访问层：MyBatis-Plus × ShardingSphere 分片", "bounds": "100 170 1080 480"},
    # ---------- P22 存储矩阵 matrix ----------
    {"type": "matrix", "kicker": "04 · 存储", "title": "存储矩阵：什么数据放在哪里",
     "headers": ["存储", "存什么", "接入点 / 要点"],
     "rows": [
         ["MySQL 8.4", "业务主数据（分片）", "ShardingSphere 2 库 4 表；Druid；MP"],
         ["MongoDB 7+", "AI 会话 / 对话记忆", "MongoChatMemoryRepository（ai 会话域）"],
         ["Milvus 2.4+", "服装文档向量（1536 维）", "MilvusVectorStore；collection=kaleido_collection"],
         ["Redis 6+", "缓存 / 锁 / 限流 / 布隆 / 会话", "JetCache + Redisson + sa-token-redis"],
         ["Caffeine", "进程内一级缓存", "@Cached 注解的 L1 层"],
         ["MinIO", "图片 / 文件（预签名 URL）", "IMinIOService putObject / uploadObject"]]},
]
