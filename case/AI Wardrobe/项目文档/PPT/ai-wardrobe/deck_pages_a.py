# -*- coding: utf-8 -*-
"""deck_pages_a.py —— P01-P12（封面/目录/背景/总体架构/技术栈）"""
PAGES_A = [
    # ---------- P01 cover ----------
    {"type": "cover", "kicker": "PROJECT BRIEF · 微服务 × AI × DDD · 2026",
     "title": "Kaleido AI 智能衣柜",
     "subtitle": ["技术架构详解：15 个服务 · 21 个公共 starter · DDD+CQRS 微服务样板",
                  "所有版本与调用关系以 pom.xml / doc/nacos 源码为准 —— 无宣传口径"],
     "footer_left": "ai-wardrobe 技术简报", "footer_right": "2026-09"},

    # ---------- P02 框架目录（带子节） ----------
    {"type": "toc", "title": "本讲框架", "page": 2, "sections": [
        ("01", "背景与总览", ["定位 · 为什么做", "功能 · 全景", "地图 · 业务→服务"]),
        ("02", "总体架构", ["分层 · 系统架构", "拓扑 · 15 服务", "风格 · DDD+CQRS", "旅程 · 一次 AI 推荐"]),
        ("03", "技术栈", ["矩阵 · 版本真相", "框架 · 核心四件套", "选型 · 为什么"]),
        ("04", "基础设施", ["公共 · 21 starters", "Nacos · 网关 · Dubbo", "MQ · 缓存 · 锁", "数据层 · 存储"]),
        ("05", "稳定性", ["四道防线", "限流原理与实现", "熔断降级 · Sentinel", "幂等 · 可靠消息"]),
        ("06", "业务域与 AI", ["服装域 · 图片链", "向量同步 · Agent", "AI 推荐链路 · 实验模块"]),
        ("07", "现状与路线", ["诚实现状盘点", "Roadmap", "总结收束"])]},
    # ---------- P03 背景 two ----------
    {"type": "two", "kicker": "01 · 定位", "title": "为什么做 Kaleido：两个事实对照",
     "left": {"title": "传统衣柜管理软件的三个天花板", "items": [
         ("止于记录", "录入 · 分类 · 查询，数据只是台账"),
         ("搭配靠人脑", "换季穿搭没有数据与审美依据"),
         ("无留存无闭环", "缺少激励、助手与反馈回路")]},
     "right": {"title": "AI 时代把问题重新定义为机会", "items": [
         ("LLM 会对话", "把穿搭建议变成会话式服务"),
         ("向量库会检索", "按语义从衣橱召回「合身」单品"),
         ("工程栈已成熟", "微服务 × AI 全家桶可组装成系统")]}},
    # ---------- P04 核心功能全景 cards+banner ----------
    {"type": "cards", "kicker": "01 · 功能", "title": "核心功能全景（三根支柱）",
     "rows": [[
         {"title": "服装资产数字化", "body": ["服装/穿搭/位置/品牌四聚合", "图片入库 + 元数据化", "标签体系多维组织"]},
         {"title": "AI 智能搭配", "body": ["推荐记录 + 异步工作流", "向量检索召回衣橱单品", "LLM 生成方案落地 Outfit"]},
         {"title": "激励体系 + 助手", "body": ["金币账本 + 邀请返利", "按行为扣费", "AI 会话穿搭咨询"]}]],
     "banner": {"headline": "核心价值：把衣柜管理升级为智能、个性化的穿搭体验",
                "body": ["一次真实请求 = 网关 × 认证 × RPC × 事件 × 向量 × LLM 的完整协作（对应 README.md:26-47）"]}},
    # ---------- P05 业务模块地图 diagram ----------
    {"type": "diagram", "diagram": "dg_bizmap", "kicker": "01 · 地图",
     "title": "业务功能 ↔ 服务模块映射", "bounds": "100 170 1080 480"},
    # ---------- P06 系统架构 diagram ----------
    {"type": "diagram", "diagram": "dg_arch", "kicker": "02 · 架构",
     "title": "系统架构分层总览", "bounds": "100 170 1080 480"},
    # ---------- P07 服务拓扑 diagram ----------
    {"type": "diagram", "diagram": "dg_topology", "kicker": "02 · 拓扑",
     "title": "服务拓扑与三类通信（RPC / 事件 / 会话）", "bounds": "100 170 1080 480"},
    # ---------- P08 工程规模 cards+banner ----------
    {"type": "cards", "kicker": "02 · 结构", "title": "工程规模：目录即架构",
     "rows": [[
         {"title": "可运行应用 15 个", "body": ["网关/认证/通知/管理端 ×4", "业务服务 ×11（含 AI 三件套）", "端口 9010-9030"]},
         {"title": "公共 starter 21 个", "body": ["Web/数据/分布式/认证/工具", "高可用组件全覆盖", "纯依赖壳 3 个（见 P37）"]},
         {"title": "RPC 契约库 1 个", "body": ["kaleido-api 128 接口/DTO", "admin 29 · wardrobe 26 · ai 23", "服务间只依赖契约"]}]],
     "banner": {"headline": "规模口径全部以 pom.xml <modules> 与源码统计为准",
                "body": ["顶层 6 模块（pom.xml:21-28）｜ biz 11 个（kaleido-biz/pom.xml:17-29）｜ common 21 个（kaleido-common/pom.xml:16-38）"]}},
    # ---------- P09 DDD+CQRS two ----------
    {"type": "two", "kicker": "02 · 风格", "title": "架构风格：DDD + CQRS + 整洁架构",
     "left": {"title": "四层结构（wardrobe 实例）", "items": [
         ("trigger", "controller / rpc / listener / job —— 接口层"),
         ("application", "command 与 query 分离（CQRS）"),
         ("domain", "aggregate / entity / service / adapter"),
         ("infrastructure", "dao / repository / component / config")]},
     "right": {"title": "为什么值得这样做", "items": [
         ("依赖倒置", "领域不依赖技术实现，只依赖接口"),
         ("命令查询分离", "读模型/写模型可独立演进与测试"),
         ("代价", "文件多样板多——以模块化换取"),
         ("仓库实证", "wardrobe 114 / admin 95 / ai 90 文件")]}},
    # ---------- P10 端到端旅程 diagram ----------
    {"type": "diagram", "diagram": "dg_journey", "kicker": "02 · 旅程",
     "title": "端到端旅程：一次「AI 推荐穿搭」的七个节点", "bounds": "100 170 1080 480"},
    # ---------- P11 版本矩阵 matrix ----------
    {"type": "matrix", "kicker": "03 · 技术栈", "title": "版本真相：一份依赖矩阵（pom.xml）",
     "headers": ["技术", "版本 / 出处", "在项目里的角色"],
     "rows": [
         ["Java 21", "编译目标 21（pom.xml:31-32）", "Boot 3.5.6 全家桶基础"],
         ["Spring Cloud 2025.0.0", "pom.xml:35", "gateway / loadbalancer"],
         ["Spring Cloud Alibaba 2025.0.0.0", "pom.xml:36", "nacos / sentinel / seata 组件"],
         ["Spring AI 1.1.2", "pom.xml:38", "kaleido-ai 主实现"],
         ["Dubbo 3.3.0", "pom.xml:65", "服务间同步 RPC"],
         ["Sentinel 1.8.7", "pom.xml（SCA 管理）", "流控 + 熔断降级"],
         ["Seata 1.8.0", "SCA 管理", "分布式事务（未激活）"],
         ["MyBatis-Plus 3.5.9", "pom.xml:46", "ORM + 拦截器"],
         ["ShardingSphere 5.5.2", "pom.xml:74", "2 库 4 表分片"],
         ["Redisson 3.52 / JetCache 2.7.8", "pom.xml:42,44", "缓存/锁/限流"],
         ["MongoDB 7+ / Milvus 2.4+", "docker-compose 中间件", "会话记忆 / 服装向量"],
         ["Sa-Token 1.44 / MapStruct 1.6.3 / Smart-doc 2.7.7", "pom.xml:67-69", "认证 / 映射 / 文档"]]},
    # ---------- P12 核心框架 cards+banner ----------
    {"type": "cards", "kicker": "03 · 框架", "title": "核心框架：技术全家桶的四块基石",
     "rows": [[
         {"title": "Java 21", "body": ["编译目标 21", "record/switch 等新语法", "LTS 长期支持"]},
         {"title": "Spring Boot 3.5.6", "body": ["应用骨架与自动配置", "starter 体系贯穿 21 模块", "webflux/webmvc 双形态"]},
         {"title": "Cloud + SCA 2025", "body": ["注册/配置/网关", "sentinel/seata 数据源", "命名空间化管理"]},
         {"title": "Spring AI 1.1.2", "body": ["ChatClient 装配", "向量库/MCP/记忆", "OpenAI 兼容层"]}]],
     "banner": {"headline": "关系图：Boot 是底座，Cloud/SCA 管分布式，Spring AI 接智能",
                "body": ["AI 通过标准 OpenAI 兼容 API 对接（base-url/api-key 由环境变量注入，见 P33）"],
                "source": "版本源：pom.xml:35-38"}},
    ]
