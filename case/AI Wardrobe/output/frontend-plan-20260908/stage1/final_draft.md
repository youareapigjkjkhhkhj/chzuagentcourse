# Kaleido AI 智能衣柜 · 前端实现规划与方案

> 版本：v1.0 ｜ 日期：2026-09-08 ｜ 面向对象：前端实现团队成员
> 配套资料：《项目完整性审计报告.md》（后端接口实测）、《衣柜系统前端原型.html》（页面交互原型）

## 一、项目背景与现状

### 1.1 项目定位

Kaleido AI 智能衣柜是一个基于 Spring Boot 3 / Spring Cloud 微服务架构的智能衣柜管理系统，后端已完成 11 个微服务（网关、认证、通知、管理后台、用户、衣柜、AI、标签、金币、消息、推荐），覆盖 39 张数据库表，并集成了 Spring AI + Milvus 向量检索的 AI 搭配推荐能力。当前核心诉求：**后端已完善，前端需要由团队成员按本方案补齐，使前端功能与后端真实接口一一对应。**

### 1.2 前端现状盘点（代码实测结论）

| 模块 | 现状 | 结论 |
|---|---|---|
| 管理端框架 | vue-element-plus-admin 模板壳，Vue 3 + TypeScript + Element Plus | 已就绪，可直接开发 |
| 登录页 | 已接真实接口：手机号 + 短信验证码（POST /kaleido-auth/public/admin/login） | 已完成，勿改动核心逻辑 |
| 授权管理四页（用户/角色/菜单/部门） | 页面存在，但 API 层全部调用 /mock/* 演示数据 | 需接线改造 |
| 工作台 Dashboard | 图表数据全部来自 /mock/* | 需接真实数据 |
| 用户端（C 端） | 完全不存在，无任何页面 | 需从零新建 |
| AI 对话界面 | 不存在 | 需新建（后端能力已就绪） |

### 1.3 本方案的目标

1. 管理端：把模板壳的演示页面改造为调用真实后端接口的功能页面；
2. 用户端：新建一套面向 C 端用户的页面（衣柜管理、穿搭、收纳、AI 助手）；
3. 统一请求规范：所有页面遵循同一套响应解析、鉴权、错误处理约定；
4. 分工到人、里程碑到周，可按模块并行开发。

## 二、技术栈与开发环境约定

### 2.1 技术栈

| 项 | 选型 | 说明 |
|---|---|---|
| 框架 | Vue 3 + TypeScript | 沿用现有前端工程，不引入新框架 |
| UI 组件库 | Element Plus | 管理端已内置；用户端建议同样使用，保持一致 |
| 状态管理 | Pinia | 现有工程已配置 |
| HTTP | axios（封装于 src/axios） | 统一走现有 service 封装 |
| 构建 | Vite + pnpm | 构建命令 pnpm build:pro |

### 2.2 环境与联调约定

| 项 | 值 |
|---|---|
| 网关基址 | http://192.168.52.133:9010（服务器联调） |
| 本地联调 | 基础中间件用 docker compose，后端服务可在 IDE 启动 |
| 鉴权请求头 | kaleido-admin-token: <登录返回的 token>（sa-token 体系） |
| 统一响应壳 | { code: 'SUCCESS', success: true, msg, data }，code 为字符串 |
| 登录测试账号 | 手机号 13066668888 / 13266668888，验证码从短信接口响应中直接获取（短信为空实现，验证码回显在响应 data.code 字段） |
| 参考原型 | 《衣柜系统前端原型.html》中每个页面已标注接口对接卡 |

## 三、通用技术规范（全员必须遵守）

### 3.1 请求与响应处理

1. 所有请求必须走 src/axios 统一封装，禁止在组件内直接 new axios 实例；
2. 响应拦截器已适配 Result 壳：success 为 true 时返回 data，为 false 时统一 ElMessage.error(msg)；
3. 401 / token 失效统一走 userStore.logout()，不逐页处理；
4. 后端列表类接口（衣物、位置、品牌等）当前为全量返回、无分页，前端做客户端筛选与分页组件包裹，**禁止自行假设后端有 page/size 参数**。

### 3.2 字典驱动原则

衣物类型（typeCode）、颜色（colorCode）、季节（seasonCode）等枚举值存储在后端字典表 t_dict 中，**所有下拉框必须先调字典接口动态渲染，禁止在前端硬编码枚举**。新增字典项由管理端字典管理页维护。

### 3.3 文件上传两步走

图片上传遵循固定流程：第一步调 POST /admin/public/file/upload（multipart）获取文件 path；第二步将 path 放入业务表单的 images 数组提交。images 数组元素结构：{ path, isMain, imageOrder, description }，首图必须标记 isMain: true。

### 3.4 AI 流式响应消费（重点难点）

AI 聊天接口返回 Flux<String>（SSE 流式文本），**不能使用普通 axios**。标准实现：

```typescript
const res = await fetch(baseURL + '/ai/agent/{agentId}/chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'kaleido-admin-token': token },
  body: JSON.stringify({ message, conversationId })
})
const reader = res.body!.getReader()
const decoder = new TextDecoder()
// 循环 read() → decoder.decode(value, { stream: true }) → 追加渲染
```

要求实现打字机效果，中途断流需有错误提示与重试入口。

### 3.5 鉴权与路由

1. 用户端与管理端共用登录体系，登录成功后 token 存 Pinia + localStorage；
2. 路由守卫：无 token 访问业务页一律重定向登录页（permission.ts 已有基础，按需扩展）；
3. dynamicRouter 已关闭（走前端静态路由），新增页面在 src/router 静态注册。

## 四、任务分解与分工（核心章节）

任务按模块 M1-M9 拆分，每个模块包含页面、接口、验收标准与预估工作量。工作量单位为"人日"，供排期参考。

### M1 请求层收尾与公共组件（1 人日，基础依赖，最先完成）

| 项 | 内容 |
|---|---|
| 范围 | axios 拦截器补齐（统一错误码表、断网提示）；封装 useDict 字典 hook、useUpload 上传 hook、SseChat 流式聊天 hook |
| 验收 | 任意页面可通过 useDict('CLOTHING_TYPE') 拿到字典数组；上传 hook 返回 path；流式 hook 可逐字渲染 |
| 备注 | 本模块是后续所有模块的地基，完成后其他模块才能并行 |

### M2 管理端 · 用户管理（2 人日）

| 项 | 内容 |
|---|---|
| 页面 | 用户列表（分页表格）、用户详情、冻结/解冻 |
| 接口 | GET /admin/user/page；GET /admin/user/{userId}；GET /admin/user/by-telephone/{telephone}；PUT /admin/user/{userId}/freeze；PUT /admin/user/{userId}/unfreeze；DELETE /admin/user/{userId} |
| 改造点 | 将 src/api 下调用 /mock/* 的用户接口替换为上表真实路径，字段按后端 DTO 映射 |
| 验收 | 列表能加载真实用户数据；冻结后状态标签即时变更；按手机号可查到对应用户 |

### M3 管理端 · 角色与权限 RBAC（3 人日）

| 项 | 内容 |
|---|---|
| 页面 | 角色列表、角色创建/编辑、权限分配弹窗（树形勾选）、权限树管理页 |
| 接口 | GET /role/list；POST /role；PUT /role/{roleId}；DELETE /role/{roleId}；POST /role/{roleId}/permissions；GET /permission/tree；POST /permission；PUT /permission/{permissionId}；DELETE /permission/{permissionId} |
| 改造点 | 现有角色页数据源为 /mock/role/table，需整页替换；权限树用 Element Plus Tree 组件渲染 GET /permission/tree 的返回 |
| 验收 | 创建角色后可在列表看到；给角色勾选权限保存后，重新打开回显正确 |

### M4 管理端 · 字典与通知模板（2 人日）

| 项 | 内容 |
|---|---|
| 页面 | 字典管理（按 typeCode 分组列表 + 增删改）、通知模板管理（列表 + 编辑） |
| 接口 | POST /dict；PUT /dict/{typeCode}/{dictCode}；DELETE /dict/{typeCode}/{dictCode}；GET /dict/page；GET /admin/notice/{id}；GET /admin/notice/target/{target}；POST /admin/notice/page；POST /admin/notice/template |
| 验收 | 新增字典项后，衣物类型下拉框（M6）能立即出现新选项（验证字典驱动闭环） |

### M5 管理端 · Agent 管理（2 人日）

| 项 | 内容 |
|---|---|
| 页面 | Agent 列表（名称/模型/温度/maxTokens/状态）、Agent 创建/编辑表单、工具挂载管理 |
| 接口 | POST /admin/ai/agent；PUT /admin/ai/agent/{agentId}；PUT /admin/ai/agent/{agentId}/enable；PUT /admin/ai/agent/{agentId}/disable；POST /admin/ai/agent/{agentId}/tools；DELETE /admin/ai/agent/{agentId}/tools/{toolCode}；GET /admin/ai/agent/{agentId}；GET /admin/ai/agent/by-code/{code} |
| 字段 | AgentInfoResponse：agentId / code / name / description / systemPrompt / modelName / temperature / maxTokens / status / tools |
| 验收 | 创建一个 Agent 后，用户端 AI 助手（M8）的 Agent 下拉中能看到并可用 |

### M6 用户端 · 我的衣柜（4 人日，用户端最重模块）

| 项 | 内容 |
|---|---|
| 页面 | 衣物卡片墙（图片 + 名称 + 类型/颜色/季节标签 + 穿着次数进度条）、衣物详情抽屉、添加/编辑衣物表单、删除确认 |
| 接口 | GET /wardrobe/clothing/list；GET /wardrobe/clothing/{clothingId}；POST /wardrobe/clothing；PUT /wardrobe/clothing/{clothingId}；DELETE /wardrobe/clothing/{clothingId}；POST /wardrobe/clothing/{clothingId}/tags/{tagId}；DELETE /wardrobe/clothing/{clothingId}/tags/{tagId} |
| 关键实现 | 1. 卡片主图取 images 中 isMain=true 的 path；2. 表单的类型/颜色/季节/品牌/位置下拉分别来自字典、GET /wardrobe/brand、GET /wardrobe/location；3. 图片走两步上传（规范 3.3）；4. 价格字段 BigDecimal，前端用数字输入框限制两位小数 |
| DTO | ClothingInfoResponse：clothingId / name / typeCode / colorCode / seasonCode / brandId / brandName / size / purchaseDate / price / description / currentLocationId / currentLocationName / wearCount / lastWornDate / images |
| 验收 | 添加一件带 3 张图的衣物，卡片墙主图正确；编辑后列表即时刷新；删除有二次确认 |

### M7 用户端 · 搭配与收纳位置（3 人日）

| 项 | 内容 |
|---|---|
| 页面 | 搭配列表（方案卡片：含衣物缩略图组合）、创建搭配（多选衣物）、穿着记录时间线；收纳位置列表/表单（位置 + 图片） |
| 接口 | GET /wardrobe/outfits/list；GET /wardrobe/outfits/{outfitId}；GET /wardrobe/outfits/{outfitId}/records；POST /wardrobe/outfits；PUT /wardrobe/outfits/{outfitId}；DELETE /wardrobe/outfits/{outfitId}；POST /wardrobe/outfits/{outfitId}/wear；GET /wardrobe/location；POST /wardrobe/location；PUT /wardrobe/location/{locationId}；DELETE /wardrobe/location/{locationId} |
| 关键实现 | 记录穿着（POST /{outfitId}/wear）成功后本地立即 wearCount +1；OutfitInfoResponse.clothings 内嵌 ClothingInfo 数组，卡片直接渲染 |
| 验收 | 创建一个含 3 件衣物的搭配并点击"今日穿这套"，wearCount 与最近穿着日期更新；位置增删改正常 |

### M8 用户端 · AI 穿搭助手（4 人日，技术含量最高）

| 项 | 内容 |
|---|---|
| 页面 | 会话列表侧栏（新建/重命名/删除）、聊天主界面（流式气泡）、Agent 选择器 |
| 接口 | GET /ai/agent；POST /ai/agent/{agentId}/chat（Flux 流式）；POST /ai/agent/chat（默认 Agent）；POST /ai/conversation；GET /ai/conversation；PUT /ai/conversation/{conversationId}/title；DELETE /ai/conversation/{conversationId} |
| 关键实现 | 1. 严格按规范 3.4 实现流式消费与打字机效果；2. 新建会话先 POST /ai/conversation 拿 conversationId，后续 chat 请求携带；3. 会话消息历史从 ConversationInfoResponse.messages 渲染；4. Agent 下拉展示 modelName 与描述 |
| 验收 | 输入"明天 20 度怎么穿"能收到流式回复；切换会话历史完整；新建会话、重命名、删除全通 |
| 依赖 | **部署侧需先补 kaleido-ai 环境变量（AI_BASE_URL / CHAT_MODEL / EMBEDDING_MODEL 与真实 API Key），否则接口必然报错**——开工前由后端负责人确认 |

### M9 工作台聚合与收尾（2 人日）

| 项 | 内容 |
|---|---|
| 页面 | 工作台统计卡片（衣物/搭配/位置/Agent 数量）、常穿衣物 Top 榜、快捷入口 |
| 接口 | 复用 GET /wardrobe/clothing/list、/outfits/list、/location、/ai/agent 前端聚合计算（后端暂无统计接口） |
| 验收 | 四张统计卡数字与实际列表条数一致 |

## 五、里程碑与排期建议（总计约 23 人日）

| 阶段 | 时间 | 内容 | 里程碑 |
|---|---|---|---|
| 第 1 周 | Day 1-2 | M1 公共层 + M2 用户管理 | 公共 hook 就绪，管理端第一个真实页面跑通 |
| 第 1-2 周 | Day 3-7 | M3 RBAC + M4 字典通知 + M5 Agent 管理（可 2-3 人并行） | 管理端全部接真实接口，/mock 引用清零 |
| 第 2-3 周 | Day 8-11 | M6 衣柜（与 M7 收纳位置并行） | 用户端核心 CRUD 跑通 |
| 第 3 周 | Day 12-15 | M7 搭配 + M8 AI 助手 | AI 流式对话全链路可演示 |
| 第 3 周末 | Day 16-17 | M9 工作台 + 联调回归 + UI 走查 | 整体可演示版本 v1.0 |

并行建议：管理端线（M2→M3/M4/M5）与用户端线（M6→M7→M8）由不同同学负责，M1 由最有经验的成员完成并第一时间共享 hook 代码。

## 六、验收标准（整体）

1. 全局搜索 src/api 目录，`/mock/` 引用数量为 0（登录相关已完成的两个真实接口除外）；
2. 所有列表页数据均来自后端真实接口，断开后端时页面有明确的错误提示而非空白；
3. 管理端四页（用户/角色/权限/字典）增删改查全部可用且数据持久化（刷新后仍在）；
4. 用户端完成"添加衣物 → 入柜 → 创建搭配 → 记录穿着 → AI 推荐穿搭"的完整业务闭环演示；
5. AI 对话有流式打字机效果，断流有重试；
6. `pnpm build:pro` 构建零报错，产物可部署到 192.168.52.133。

## 七、风险与注意事项

| 风险 | 影响 | 对策 |
|---|---|---|
| kaleido-ai 缺模型环境变量与 API Key | M8 全部接口报错 | 开工前由后端负责人在 docker compose 注入并验证 curl 通 |
| 短信为空实现 | 验证码仅从接口响应获取 | 登录页保留"验证码回显提示"，演示时向观看者说明 |
| 列表接口无分页 | 数据量大时首屏慢 | 前端分页组件 + 客户端筛选；后续可提需求让后端补分页 |
| Dashboard 统计无后端接口 | M9 只能前端聚合 | 按本方案前端聚合实现；统计接口列为二期后端需求 |
| mock 文件残留 | 误导后续开发 | 验收前删除 src/api 中所有 /mock 引用与 mock 目录内已废弃文件 |
| 多人并行冲突 | 合并困难 | M1 定好的 hook 与 api 目录结构即契约，模块按目录隔离（每人只改自己的模块目录） |

## 八、附录：全套真实接口速查

| 模块 | 方法与路径 | 用途 |
|---|---|---|
| 认证 | POST /kaleido-auth/public/admin/login ｜ POST /kaleido-auth/public/sms/verify-code | 登录 ｜ 发验证码 |
| 衣柜 | GET /wardrobe/clothing/list ｜ GET /wardrobe/clothing/{id} ｜ POST /wardrobe/clothing ｜ PUT、DELETE /wardrobe/clothing/{id} ｜ POST、DELETE /wardrobe/clothing/{id}/tags/{tagId} | 衣物 CRUD 与标签 |
| 搭配 | GET /wardrobe/outfits/list ｜ GET /wardrobe/outfits/{id} ｜ GET /wardrobe/outfits/{id}/records ｜ POST /wardrobe/outfits ｜ PUT、DELETE /wardrobe/outfits/{id} ｜ POST /wardrobe/outfits/{id}/wear | 搭配与穿着记录 |
| 位置 | GET /wardrobe/location ｜ POST /wardrobe/location ｜ PUT、DELETE /wardrobe/location/{id} ｜ POST、DELETE /wardrobe/location/{id}/tags/{tagId} | 收纳位置 |
| 品牌 | GET /wardrobe/brand ｜ GET /wardrobe/brand/{brandId} | 品牌下拉数据源 |
| AI | GET /ai/agent ｜ POST /ai/agent/{agentId}/chat（流式） ｜ POST /ai/agent/chat ｜ POST /ai/conversation ｜ GET /ai/conversation ｜ PUT /ai/conversation/{id}/title ｜ DELETE /ai/conversation/{id} ｜ GET /ai/workflow/{id} ｜ POST /ai/workflow/execute ｜ GET /ai/workflow/executions/my | AI 对话与工作流 |
| 管理-用户 | GET /admin/user/page ｜ GET /admin/user/{id} ｜ GET /admin/user/by-telephone/{tel} ｜ PUT /admin/user/{id}/freeze、/unfreeze ｜ DELETE /admin/user/{id} | 用户管理 |
| 管理-RBAC | GET /role/list ｜ POST /role ｜ PUT、DELETE /role/{id} ｜ POST /role/{id}/permissions ｜ GET /permission/tree ｜ POST /permission ｜ PUT、DELETE /permission/{id} | 角色权限 |
| 管理-Agent | POST /admin/ai/agent ｜ PUT /admin/ai/agent/{id} ｜ PUT /admin/ai/agent/{id}/enable、/disable ｜ POST /admin/ai/agent/{id}/tools ｜ DELETE /admin/ai/agent/{id}/tools/{toolCode} | Agent 配置 |
| 管理-其他 | POST /admin/public/file/upload ｜ POST /dict ｜ PUT、DELETE /dict/{typeCode}/{dictCode} ｜ GET /dict/page ｜ POST /admin/notice/page ｜ POST /admin/notice/template | 文件 ｜ 字典 ｜ 通知 |

> 接口出入参的完整字段以 kaleido-common/kaleido-api 模块下的 Command/Response 类为准；页面布局参考《衣柜系统前端原型.html》。
