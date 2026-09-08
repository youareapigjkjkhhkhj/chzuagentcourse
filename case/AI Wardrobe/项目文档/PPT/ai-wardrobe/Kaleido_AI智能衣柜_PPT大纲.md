# Kaleido AI 智能衣柜（ai-wardrobe）· 技术架构详解 PPT 大纲

> 风格：瑞士简报 / Swiss Grid 极简（16:9、Arial、白底近黑 + 瑞士红单强调），与 Agentic 时代讲座同一设计语言。
> 规模：**39 页**。生成路线：`swiss-lecture-style` skill（独立生成器）→ SVG → 质量门禁（0 error）→ PPTX。
> 事实口径：**所有技术主张以代码为准**（版本以 `pom.xml`、端口以 `doc/nacos/*-dev.yml`），正文后附「佐证索引」表（file:line），封面页不写 README 宣传性数字。
> 交付物：`E:\workbuddy-study\study\PPT\ai-wardrobe\` 下大纲 + deck 数据 + 最终 `Kaleido_AI智能衣柜_技术架构详解.pptx`（暂定名）。

---

## 目录（7 个板块）

| # | 板块 | 页号 | 内容 |
|---|---|---|---|
| 01 | 项目背景与总览 | P03–P05 | 定位、功能全景、业务模块地图 |
| 02 | 总体架构 | P06–P10 | 系统架构、服务拓扑、工程结构、DDD+CQRS、端到端旅程 |
| 03 | 技术栈总览 | P11–P13 | 版本矩阵、核心框架、选型理由 |
| 04 | 公共模块与基础设施深潜 | P14–P22 | 21 个 starters、Nacos、网关鉴权、Dubbo、MQ、缓存、锁、数据层、存储矩阵 |
| 05 | 稳定性专题（限流/熔断/幂等/可靠消息） | P23–P29 | 四道防线、限流原理、自研注解、Sentinel、幂等与锁、MQ 可靠性、端到端可靠性旅程 |
| 06 | 业务域与 AI 深潜 | P30–P36 | 服装域、图片责任链、向量同步、Agent 装配、AI 推荐链路、辅助业务域、AI 第二路线 |
| 07 | 现状边界与路线 | P37–P39 | 诚实现状盘点、Roadmap、总结收束 |

---

## 01 · 项目背景与总览（P03–P05）

### P03 项目定位：为什么做 Kaleido（two）
- 左卡「一个真实的工程命题」：衣柜管理软件普遍停留在"记录"层——录入、分类、查询（事实锚：本项目功能域）。
- 右卡「AI 时代的机会」：LLM/向量库/多模态成熟，穿搭可以升级为"数据 + 向量 + 生成式"体验。
- 副标（banner）：「把传统衣柜管理升级为智能化、个性化穿搭体验」——README.md:26,47。
- 页型：two + 底部来源行。

### P04 核心功能全景（cards + banner，3 卡）
- 服装资产管理：服装/衣橱/位置/批量导入/图片元数据（wardrobe 域，见佐证）。
- 智能搭配：AI 穿搭方案、风格推荐（recommend→ai→wardrobe 链路）。
- 激励体系 + AI 助手：金币账本与邀请返利、会话式穿搭咨询（coin 域 / ai 域）。
- banner 金句：一次穿搭推荐 = 微服务 × AI × 异步事件的完整协作。

### P05 业务模块地图（diagram 自绘）
- 图：业务功能（App 端服装/穿搭/偏好/金币/助手，管理端 RBAC/Agent/工作流）→ 对应服务模块（wardrobe/user/tag/coin/ai/recommend/admin…）。
- 佐证：README.md:28-41 功能描述 ↔ `kaleido-biz/pom.xml:17-29` 模块清单对照呈现。

## 02 · 总体架构（P06–P10）

### P06 系统架构分层图（diagram 自绘，重点页）
- 纵向分层：接入层（管理端前端 Vue3/Element Plus、未来 App）→ API 网关（Gateway 9010）→ 服务层（auth/user/wardrobe/tag/coin/recommend/ai/notice/admin/message…）→ 公共支撑（kaleido-common 21 starters）→ 基础设施（MySQL 分片/MongoDB/Redis/Milvus/MinIO/RabbitMQ/Nacos）。
- 佐证：doc/nacos 端口表、doc/sql 数据库清单、images/系统架构.jpg 为作者原图（本图按代码事实重绘）。

### P07 服务拓扑与事件流总图（diagram 自绘）
- 15 个可运行 Java 服务（含端口徽标）+ 2 个前端（admin-frontend、interview fronted）。
- 三类边：Dubbo RPC（实线）、RabbitMQ 事件（虚线）、Sa-Token 会话校验（网关进）。
- 佐证：pom.xml:21-28、kaleido-biz/pom.xml:17-29、doc/nacos/*-dev.yml 端口。

### P08 工程结构：目录即架构（cards / matrix）
- 顶层 6 模块 + biz 11 服务 + common 21 starters 的分层卡片；每服务源码规模（wardrobe 114 文件、admin 95、ai 90…）。
- 矩阵：模块 × 角色 × 依赖的 common starters。
- 佐证：目录树 + 各模块 `find src/main/java -name *.java | wc -l`。

### P09 架构风格：DDD + CQRS + 整洁架构（two）
- 左卡 DDD 分层：trigger（接口层=controller/rpc/listener/job）→ application(command/query) → domain(aggregate/entity/service) → infrastructure(dao/repository/component) → types。
- 右卡 CQRS：命令与查询分离（wardrobe/application/command vs query 目录实证），读写路径各自演进。
- 佐证：kaleido-wardrobe 包树（application/command、domain/clothing/model/aggregate、infrastructure/dao、trigger/controller）。

### P10 端到端旅程：一次「AI 推荐穿搭」怎么走完（diagram 时序，重点页）
- 泳道式编号流：用户 POST /recommend → recommend（coin 余额校验 + 扣费 + 落推荐记录）→ Dubbo 调 ai.executeOutfitRecommendWorkflow → ai 异步执行（向量检索 + LLM 生成）→ 发 MQ outfit-recommend-completed → recommend 消费 → Dubbo 调 wardrobe 创建穿搭 → 状态 COMPLETED。
- 佐证：RecommendCommandService.java:77-113、OutfitRecommendCompletedEventListener.java:53、WorkflowEventPublisherImpl.java:46-49。

## 03 · 技术栈总览（P11–P13）

### P11 版本矩阵（matrix，信息密度页）
- 行=技术族（框架/微服务生态/数据/中间件/工具），列=技术 | 版本 | 在项目中干什么。
- 事实源：pom.xml 属性（Spring Boot 3.5.6、Cloud 2025.0.0、SCA 2025.0.0.0、Spring AI 1.1.2、Dubbo 3.3.0、Sentinel 1.8.7、Seata 1.8.0、XXL-Job 3.3.2、ShardingSphere 5.5.2、Redisson 3.52.0、JetCache 2.7.8、MyBatis-Plus 3.5.9、Sa-Token 1.44.0、Dynamic-TP 1.2.2-x、MinIO 8.6.0、langchain4j 1.11.0、MapStruct 1.6.3、Smart-doc 2.7.7、Druid 1.2.24…）。

### P12 核心框架（cards + banner）
- Java 21（编译目标）+ Spring Boot 3.5.6 + Spring Cloud 2025.0.0 + Spring Cloud Alibaba 2025.0.0.0 + Spring AI 1.1.2：每框架 1 卡（是什么 + 本项目的角色）。
- banner：「全家桶的每一环都能在本仓库找到落点——不是 Demo，是拼装好的系统」。

### P13 选型理由：为什么是它（matrix 或 two）
- 网关 Gateway vs Zuul；注册/配置 Nacos vs Eureka/Consul；RPC Dubbo vs OpenFeign/HTTP（本仓库全量 Dubbo，无 Feign——grep 证据）；缓存 JetCache(Caffeine+Redis) vs 纯 Redis；限流 Sentinel vs 自研注解 vs 网关级；AI 侧 Spring AI vs langchain4j（仓库两条路线并存）。
- 每个选择配「事实 + 一句话理由（按代码证据推断，标注推断）」。

## 04 · 公共模块与基础设施深潜（P14–P22）

### P14 公共模块总览（matrix）
- 21 个 starters 按五类矩阵：Web/横切（web/aop）、数据（ds/cache/file）、分布式（nacos/rpc/mq/distribute/lock/limiter/sentinel/seata/dynamic-tp/job）、认证（sa-token）、工具（base/api/doc/sms/monitor）。
- 事实：kaleido-common/pom.xml:16-38；标注 3 个纯依赖壳（nacos/seata/sentinel 0 个 Java 类）与 dynamic-tp/job 自动配置 imports 错配（客观事实，作为"工程待办"）。

### P15 Nacos：注册 + 配置中心（diagram）
- 原理图：服务启动→注册心跳→消费者从 Nacos 拉取实例列表→配置变更推送（Apollo 同族简介一句话）。
- 项目用法：namespace 双隔离（kaleido/dubbo，README.md:263-270）；bootstrap 以 classpath:nacos.yml 引入（kaleido-nacos/src/main/resources/nacos.yml:4-13）；配置按 ${NACOS_HOST} 注入（init_env.bat）。

### P16 网关与鉴权：Spring Cloud Gateway + Sa-Token（diagram，重点页）
- 图左：9 条路由（lb:// 服务，doc/nacos/kaleido-gateway-dev.yml:20-71）；图右：SaReactorFilter→DynamicStrategyFactory（AntPathMatcher+Caffeine 缓存）→LoginCheckStrategy 三实现（Public/User/Admin）。
- 双 token 体系：kaleido-admin-token vs kaleido-user-token（kaleido-sa-token/StpUtilConfig.java:9-28）。
- 佐证：kaleido-gateway/.../config/SaTokenConfig.java:44-60、auth/strategy/*.java。

### P17 Dubbo RPC：服务间同步调用（diagram）
- 原理简述：provider 注册→consumer 直连/集群容错/超时；本项目协议细节。
- 项目用法：kaleido-api 契约库（128 个接口/DTO，@DubboService 在接口或实现上）→ 各服务 @DubboReference；DubboExceptionFilter 统一 Result（rpc/filter/DubboExceptionFilter.java:22-24）；registry=nacos group=dubbo。
- 事实：30+ 处注解、服务注册表 Nacos（doc/nacos/kaleido-rpc.yml）。

### P18 RabbitMQ 事件总线（diagram，重点页）
- 事件流总图：4 条 topic（auth-change / user-registered / outfit-recommend-completed / clothing-event，doc/nacos/kaleido-mq.yml:11-15）× 4 个 @RabbitListener 消费方 + EventPublisher 抽象（默认交换机直发，kaleido-mq/event/EventPublisher.java:14-31）+ BaseEvent 消息信封（id/timestamp/data）。
- 用途句：解耦用户注册→金币返利、服装→向量同步、AI 完成→推荐回执、权限变更→缓存失效。

### P19 多级缓存：Caffeine + Redis + JetCache（diagram）
- 链路图：读（L1 Caffeine→L2 Redis→DB，回填双写）/ 写（删缓存 + 2s 延迟删除 DelayDeleteService）。
- JetCache @Cached 注解开启（RedisAutoConfiguration:15-18）、RedissonService 能力清单（bucket/queue/map/lock/semaphore/bloomfilter）。
- 佐证：kaleido-cache 源码、doc/nacos/kaleido-cache.yml（database 11）。

### P20 分布式锁：Redisson + 自研注解 @DistributedLock（diagram）
- 原理：RLock（可重入/公平/读写/Multi 四型映射，kaleido-lock/DistributedLockService.java:33-50）+ Redisson 看门狗续期（简述真实机制）+ 释放。
- 项目用法：SpEL key（如 'coin:stream:'+#userId）+ wait/lease；coin 服务 7 处、recommend 1 处（grep 共 8）。
- banner：为什么锁要注解化——调用点即文档。

### P21 数据访问层：MyBatis-Plus + ShardingSphere（diagram）
- 分片算法图：CustomShardingAlgorithm 2 库 4 表（totalTables=8、库=val%8/4、表=val%8%4，ds 模块 CustomShardingAlgorithm.java:28-42）；URL=jdbc:shardingsphere:classpath:sharding.yaml。
- MP 三拦截器（乐观锁/防全表/分页，DataSourceAutoConfiguration.java:49-63）+ BasePO 审计字段自动填充；Druid 连接池。
- 佐证：kaleido-ds 源码 + doc/nacos/kaleido-ds.yml + doc/sql（kaleido_0/kaleido_1 双库 39 表）。

### P22 存储矩阵（matrix）
- MySQL（结构化主数据，分片）｜MongoDB（AI 会话/记忆，ai 模块 MongoChatMemory）｜Milvus（服装向量 1536 维，kaleido_collection）｜Redis（缓存/锁/限流/布隆）｜MinIO（图片/文件，含预签名 URL）。
- 每行：存什么 / 用在哪（file:line） / 技术要点一句。

## 05 · 稳定性专题（P23–P29）

### P23 稳定性四道防线总览（cards + banner）
- 防线 1 限流（Sentinel + @RateLimit 双层）｜防线 2 熔断降级（Sentinel degrade，Nacos 规则）｜防线 3 幂等与分布式锁（coin bizId + @DistributedLock）｜防线 4 可靠消息（落库 + MQ + 定时重试）。
- banner：每道防线都有「注解/配置 + 代码落点」，对应到具体接口。

### P24 限流原理：令牌桶 / 滑动窗口 / 漏桶（diagram，原理页）
- 三算法对比示意（填充曲线/窗口计数），适用场景标注。
- 页脚：本项目的两种落地=Sentinel（流控规则，集群视角）+ Redisson 令牌桶注解（单键精确限流）。

### P25 自研注解限流 @RateLimit 剖析（diagram，重点页）
- 调用链图：业务方法 @RateLimit(key=SpEL,limit,window) → RateLimitAspect(@Around) → RateLimitService（RedissonClient.getRateLimiter → trySetRate(OVERALL) → tryAcquire）→ Redis。
- 两个真实用例标注：短信验证码 1 次/60s（SmsController.java:46）、创建推荐 5 次/60s（RecommendCommandService.java:75）。
- 佐证：kaleido-limiter 全部 5 个类。

### P26 Sentinel：流控与熔断降级（diagram，原理页）
- 左：资源-规则-插槽链执行模型（简述）；右：熔断状态机 CLOSED→OPEN（触发）→HALF_OPEN（探测）→CLOSED + 慢调用比例/异常比例概念。
- 项目集成：3 个 @SentinelResource（SmsController/ClothingController/RecommendCommandService）+ blockHandler/fallback 本地方法；规则由 Nacos 下发（flow/degrade JSON，${app}-sentinel-flow.json）。
- 佐证：三个 @SentinelResource 位置、doc/nacos/kaleido-sentinel.yml:8-33、kaleido-web 全局异常处理器对 BlockException 的兜底（WebAutoConfiguration/GlobalExceptionHandler）。

### P27 幂等与账本安全：coin 的锁 + bizId 设计（diagram 或 two）
- 规则：所有出入账携带 bizType+bizId 幂等唯一（CoinStream/domain），账户聚合+流水实体。
- @DistributedLock 7 处覆盖 init/reward/deduct 等（CoinCommandService.java:35,54,73,92,111,137,164）；邀请返利幂等 existsByBizTypeAndBizId（CoinDomainServiceImpl.java:72）。
- 真实金额来源：实时 Dubbo 读 admin 字典（INITIAL_BALANCE=100、INVITE_REWARD=100…）。

### P28 可靠消息：message 模块 + XXL-Job 重试（two）
- 左卡：MqMessageAggregate 状态机（CREATE→COMPLETED/FAILED）消息留痕（kaleido-message）。
- 右卡：通知重试闭环 NoticeRetryJob（XXL-Job + Dynamic-TP 并行重发 + 状态回写，NoticeRetryJob.java:44-130）。
- 诚实标注：message 模块当前无业务方引用（IRpcMqMessageService 未见消费者）——作为"已铺轨道待接线"。

### P29 端到端可靠性旅程复盘（diagram 时序复盘，重点页）
- 复用 P10 旅程，逐节点叠加防线标注：入口（Sentinel 流控）→ 扣费（分布式锁+幂等）→ AI 异步（MQ 解耦）→ 完成回执（消息可靠性+状态机）→ 失败（重试/终态）。
- 结论句：单点失败不阻断主流程，这是事件驱动架构的核心收益。

## 06 · 业务域与 AI 深潜（P30–P36）

### P30 服装域建模（diagram 领域模型图）
- 四聚合：ClothingAggregate（含 ClothingImage 实体、10 张图上限、primary 逻辑）/ OutfitAggregate（wearCount/lastWornDate）/ LocationAggregate / BrandAggregate + 聚合行为（changeLocation/addImages/setAsPrimaryImage…）。
- 佐证：wardrobe/domain/clothing|location|outfit 目录。

### P31 服装图片责任链（diagram，重点页）
- 链：ValidationHandler（空值/顺序/isPrimary 默认）→ MetadataExtractionHandler（MinIO 读宽高/mime/大小）→ ImageOptimizationHandler（>1MB 标压缩、非 webp 标转格式）→ 收尾 ImageConversionContext 策略转领域 DTO。
- 装配证据：ImageProcessingChainBuilder.java:56-58（add 顺序）、62（setNext）。
- **诚实标注**：压缩/转格式当前为**模拟估算**（ImageOptimizationHandler.java:58-82 注释"模拟压缩处理"）——链路预留了真实实现位。
- 复用：同一链路服务 Clothing/Location/Outfit 三类图（策略模式按 DomainType）。

### P32 领域事件与向量同步（diagram）
- 服装 CREATE/UPDATE/DELETE → ClothingEventPublisherImpl → MQ clothing-event → kaleido-ai ClothingEventListener → ClothingVectorService → Milvus 增量更新。
- 佐证：ClothingEventPublisherImpl.java:99,121、ClothingEventListener.java:34-75、ClothingDocumentRepositoryImpl.java:45(add)。

### P33 Agent 工厂与装配（diagram，AI 重点页）
- 左侧 Agent 配置入 DB（t_ai_agent/t_ai_agent_tool 表、AgentAggregate 聚合、默认 deepseek-v3/0.70/2000）；
- 右侧 AgentFactory 注册中心（Caffeine、system_default、懒加载注册注销刷新）→ AgentChatClientArmory 按需组 ChatClient：
  模型（OpenAI 兼容 base-url/api-key/model 环境变量注入 → deepseek-v3）→ Advisor（记忆 advisor / RAG advisor）→ 工具（MEMORY→MessageChatMemoryAdvisor；VECTOR_STORE→RAG；MCP→McpSyncClient + SyncMcpToolCallbackProvider）。
- 佐证：AgentFactory.java、AgentChatClientArmory.java:64-278、ChatServiceImpl.java:73-99。

### P34 AI 智能穿搭推荐：内容链路（diagram，重点页）
- 时序：prompt → recommend → ai OutfitRecommendWorkflowExecutor(OUTFIT_RECOMMEND) → 检索用户服装向量（Milvus similaritySearch topK=100 / 阈值 0.0，按 userId+clothingId filter）→ LLM 生成搭配 JSON → 发布完成事件 → 回写。
- 佐证：OutfitRecommendWorkflowExecutor.java:28,55、ClothingDocumentRepositoryImpl.java:66,94、VectorStoreConfig.java:20,32。

### P35 辅助业务域速览（cards）
- user：档案/冻结/邀请码 + 布隆过滤器防注册抖动（BloomFilterInitializer）；tag：标签类型×实体类型匹配校验 + 多对多关联（TagDomainServiceImpl）；coin：账本/返利/扣费（P27 展开）；notice：类型策略工厂（SMS/Email/WeChat）+ 模板渲染 + 重试。
- 诚实标注：Email/WeChat 适配器当前 TODO 占位；SMS 走 kaleido-sms（方法体 TODO 阿里云，实际为桩返回）。

### P36 AI 第二路线与实验模块（cards）
- langchain4j-demo：chat/@AiService/流式/工具/Redis 记忆/RAG(Naive+Milvus)/进阶控制器十余个（demo 模块全景）。
- interview：AI 面试助手——意图路由（6 agent）+ Tika 简历解析 + Milvus 简历/知识库 RAG + 7 个面试 @Tool + SSE 前端。
- kaleido-mcp：Spring AI MCP Server（sync/webflux，WeatherService@McpTool），被 kaleido-ai 以 SSE client 消费（baseUri localhost:9021）。
- ai-langchain4j：langchain4j 版服务壳（仅启动类，依赖齐备）。
- 小结：一条主线（Spring AI）+ 一条对照线（langchain4j），仓库即技术试验场。

## 07 · 现状边界与路线（P37–P39）

### P37 诚实现状盘点（matrix）
- 行=模块/能力，列=状态（已实现/占位/未接线/待办）：
  - 已实现：认证（短信码）、RBAC 管理端、服装/穿搭/位置聚合、图片责任链骨架、Dubbo/MQ/限流/锁、金币账本、AI Agent 装配 + RAG + 向量同步、推荐异步闭环。
  - 占位/TODO：Seata 未激活（仅一处注释 @GlobalTransactional）、SMS/Email/WeChat 适配器桩、图片压缩为模拟、admin 前端业务页未建、数据看板未实现、message 模块未接线、dynamic-tp/job 自动配置 imports 错配。
  - 佐证列全带 file:line。

### P38 Roadmap（timeline，4 节点）
- 阶段 1 工程化补全（Seata 接线/适配器真实现/压缩真实化/imports 修正）→ 阶段 2 业务深化（推荐算法升级、看板、批量导入完善）→ 阶段 3 体验与生态（App/小程序端、MCP 工具扩充、Agent 市场化）。
- 每节点 2-3 条可验收动作（建议性质，标注"规划建议"非现状）。

### P39 总结与行动号召（toc recap，如 lecture P22）
- 一句话：Kaleido = 15 个服务 × 21 个公共模块，把"AI 穿搭"做成了一套可运行的微服务样板。
- 一架构：网关(Nacos/Sa-Token) → Dubbo/MQ → DDD 服务 → 向量/AI。
- 一栈：Boot3.5/Cloud2025/SpringAI/Milvus/Sentinel/Redisson 全落点。
- 一专题：限流熔断幂等可靠消息 = 稳定性四道防线。
- 一收获：DDD+CQRS 不是文档概念，在这仓库里有完整目录结构对应。
- 一行动：读代码从 kaleido-wardrobe 服装域 + kaleido-ai Agent 装配两处入手。

---

## 页型与自绘示意图清单

- 标准页型：cover×1、toc×2（框架目录+总结）、cards/banner×~7、two×4、matrix×5、timeline×1 → 约 20 页。
- **diagram 自绘 ×~19**：系统架构分层、服务拓扑、端到端旅程、网关鉴权、Dubbo 流、MQ 事件流、缓存链路、分片算法、限流三算法、@RateLimit 剖析、Sentinel 原理、幂等账本、可靠性复盘、服装领域模型、图片责任链、向量同步、Agent 装配、AI 推荐链路（每页按"安全区 64..1216×170..650、调色板受限、bounds 精确覆盖"绘制）。
- 版式密度原则：无大面积留白；关键页配 5-15 个元素；图页必配一句结论。

## 佐证索引（正文 file:line 摘录，供 QA 交叉核对）

| 主张 | 佐证 |
|---|---|
| 版本矩阵 | pom.xml:35-76（属性定义） |
| 顶层模块 6 / biz 11 / common 21 | pom.xml:21-28；kaleido-biz/pom.xml:17-29；kaleido-common/pom.xml:16-38 |
| 双命名空间 | README.md:263-270；nacos.yml:4-13 |
| 网关 9 路由 / 9010 | doc/nacos/kaleido-gateway-dev.yml:20-71,3 |
| Sa-Token 双 token/网关策略 | kaleido-sa-token/StpUtilConfig.java:9-28；gateway SaTokenConfig.java:44-60 |
| 无 Feign、全量 Dubbo | 全仓 grep @FeignClient 无命中；@DubboService/@DubboReference 30+ 处 |
| MQ 4 topic/4 监听 | doc/nacos/kaleido-mq.yml:11-15；4 个 @RabbitListener 类 |
| @RateLimit 自研（Redisson 令牌桶） | kaleido-limiter/RateLimitService.java:33-38；两个用例 |
| @SentinelResource ×3 + Nacos 规则 | SmsController.java:40、ClothingController.java:46、RecommendCommandService.java:69；kaleido-sentinel.yml:8-33 |
| @DistributedLock ×8 | CoinCommandService.java:35..164、RecommendCommandService.java:76 |
| 图片责任链顺序 / 模拟压缩 | ImageProcessingChainBuilder.java:56-62；ImageOptimizationHandler.java:58-82 |
| Milvus 向量库 | ClothingDocumentRepositoryImpl.java:32,66；ChatServiceImpl.java:41；kaleido-ai-dev.yml:41-53 |
| AI 模型/供应商（硅基流动默认） | init_env.bat:20-23；kaleido-ai-dev.yml:16-23；AgentChatClientArmory.java:96-153 |
| 推荐异步闭环 | RecommendCommandService.java:77-113；OutfitRecommendCompletedEventListener.java:53 |
| 分片 2 库 4 表 | kaleido-ds/CustomShardingAlgorithm.java:28-42 |

> 说明：所有标注"模拟/TODO/占位"的项均为如实呈现，不做美化；PPT 内对规划类内容明确标注"规划建议"。
