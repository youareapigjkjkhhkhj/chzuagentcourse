# -*- coding: utf-8 -*-
"""deck_pages_d.py —— P30-P39（业务域与 AI 深潜 / 现状边界与路线）"""
PAGES_D = [
    # ---------- P30 服装域模型 diagram ----------
    {"type": "diagram", "diagram": "dg_domain", "kicker": "06 · 服装域",
     "title": "服装域领域模型：四大聚合与分层", "bounds": "100 170 1080 480"},
    # ---------- P31 图片责任链 diagram ----------
    {"type": "diagram", "diagram": "dg_chain", "kicker": "06 · 服装域",
     "title": "服装图片处理：模板方法 + 责任链 + 策略", "bounds": "100 170 1080 500"},
    # ---------- P32 向量同步 diagram ----------
    {"type": "diagram", "diagram": "dg_vectorsync", "kicker": "06 · AI",
     "title": "领域事件驱动向量同步：服装 → Milvus", "bounds": "100 170 1080 480"},
    # ---------- P33 Agent 装配 diagram ----------
    {"type": "diagram", "diagram": "dg_agent", "kicker": "06 · AI",
     "title": "Agent 即配置：注册中心 + Armory 装配 ChatClient", "bounds": "100 170 1080 500"},
    # ---------- P34 AI 推荐内容链路 diagram ----------
    {"type": "diagram", "diagram": "dg_aireco", "kicker": "06 · AI",
     "title": "智能穿搭推荐的内容链路（RAG 落地）", "bounds": "100 170 1080 500"},
    # ---------- P35 辅助业务域 cards ----------
    {"type": "cards", "kicker": "06 · 辅助域", "title": "辅助业务域速览",
     "rows": [[
         {"title": "kaleido-user", "body": ["用户档案与行为流水", "邀请码 / 冻结", "布隆过滤器防注册抖动"]},
         {"title": "kaleido-tag", "body": ["自定义标签体系", "类型×实体类型匹配校验", "多对多关联"]},
         {"title": "kaleido-notice", "body": ["SMS/Email/WeChat 三类", "通知模板渲染 + 落库", "失败定时重试"]},
         {"title": "kaleido-coin", "body": ["账户 + 流水账本", "邀请返利（幂等）", "按行为扣费"]}]],
     "banner": {"headline": "诚实标注：SMS/Email/WeChat 适配器当前为占位实现（TODO），业务主链路已通",
                "body": ["kaleido-sms 的 SmsService 方法体为 TODO 桩返回成功 —— 属「待接入第三方」而非「已上线渠道」"]}},
    # ---------- P36 AI 第二路线 cards ----------
    {"type": "cards", "kicker": "06 · 实验", "title": "AI 第二路线与实验模块（langchain4j）",
     "rows": [[
         {"title": "langchain4j-demo", "body": ["Chat / @AiService / 流式", "工具调用 · Redis 记忆", "Naive/Milvus RAG 对照"]},
         {"title": "kaleido-interview", "body": ["AI 面试助手（SSE）", "意图路由 6 Agent", "Tika 简历解析 + RAG"]},
         {"title": "kaleido-mcp", "body": ["Spring AI MCP Server", "WeatherService @McpTool", "被 kaleido-ai SSE 消费"]},
         {"title": "ai-langchain4j", "body": ["langchain4j 版服务壳", "依赖齐备", "业务代码待实现"]}]],
     "banner": {"headline": "一条主线（Spring AI）+ 一条对照线（langchain4j）——仓库即技术试验场",
                "body": ["版本：langchain4j 1.11.0（pom.xml:39）；语言与工具生态细节见各模块 pom"]}},
    # ---------- P37 诚实现状盘点 matrix ----------
    {"type": "matrix", "kicker": "07 · 现状", "title": "诚实现状盘点：已实现 / 占位 / 未接线 / 规划",
     "headers": ["模块 / 能力", "状态", "依据（file:line）"],
     "rows": [
         ["短信码注册登录", "已实现", "auth UserAuthCommandService.java:49-98"],
         ["RBAC 管理端", "已实现", "admin：Admin/Role/Permission 三级聚合"],
         ["服装/穿搭/位置聚合", "已实现", "wardrobe domain/clothing|outfit|location"],
         ["图片责任链骨架", "已实现", "ImageProcessingChainBuilder.java:56-62"],
         ["AI Agent 装配 + RAG", "已实现", "AgentChatClientArmory.java:64-278"],
         ["推荐异步闭环", "已实现", "RecommendCommandService.java:77-113"],
         ["金币账本与返利", "已实现", "CoinDomainServiceImpl.java:33-96"],
         ["Seata 分布式事务", "占位（未激活）", "@GlobalTransactional 仅注释（Recommend:68）"],
         ["SMS/Email/WeChat", "占位（TODO）", "kaleido-sms SmsService.java:22-26"],
         ["图片压缩/转格式", "模拟估算", "ImageOptimizationHandler.java:58-82"],
         ["message 模块接线", "未接线", "全仓未见 IRpcMqMessageService 消费方"],
         ["admin 前端业务页", "未建设", "views 仅模板页（见前端盘点）"],
         ["dynamic-tp/job imports", "配置错配（待修）", "两个 AutoConfiguration.imports 内容交叉"],
         ["数据看板 / App 端", "规划建议", "README 愿景项，仓库暂无实现"]]},
    # ---------- P38 Roadmap timeline ----------
    {"type": "timeline", "kicker": "07 · 路线", "title": "Roadmap（规划建议，非现状）",
     "points": [
         {"year": "阶段 1 · 工程化补全", "label": ["接线 Seata 与真实渠道适配器", "图片压缩真实化 · imports 修正", "message 模块接入业务"]},
         {"year": "阶段 2 · 业务深化", "label": ["推荐算法升级（排序/多路召回）", "管理端看板与运营页", "批量导入与图片增强"]},
         {"year": "阶段 3 · 体验与生态", "label": ["App/小程序端接入网关", "MCP 工具扩充", "Agent 资产化与分享"]},
         {"year": "持续 · 社区化", "label": ["补测试与 CI/CD", "文档与 API 示例沉淀", "MIT 开源生态共建"]}],
     "source": "说明：以上为基于代码现状的规划建议；每项均可在仓库找到对应的『已铺轨道』。"},
    # ---------- P39 总结收束 toc recap ----------
    {"type": "toc", "title": "总结与行动号召", "page": 39, "sections": [
        ("一句话", "Kaleido 把 AI 穿搭做成了一套可运行的微服务样板"),
        ("一架构", "网关(Sa-Token) → Dubbo/MQ → DDD 服务 → 向量/AI"),
        ("一栈", "Boot3.5/Cloud2025/SpringAI/Milvus/Redis"),
        ("一专题", "限流熔断幂等可靠消息 = 稳定性四道防线"),
        ("一收获", "DDD+CQRS 在这仓库有完整目录对应"),
        ("一行动", "读代码：wardrobe 服装域 + ai Agent 装配")]},
]
