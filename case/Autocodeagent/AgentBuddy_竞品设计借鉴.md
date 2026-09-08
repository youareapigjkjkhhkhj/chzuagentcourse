# AgentBuddy 竞品设计借鉴

> 调研对象：Claude Code、OpenCode (SST)、Codex CLI、Aider、Gemini CLI。
> 信息来源：2026 年公开资料（arXiv 2604.14228 Claude Code 设计空间分析、官方文档转述、社区深度拆解等），检索时间 2026-09-04。
> 用法：每个借鉴点都标注了映射到 AgentBuddy 的哪个现有模块，以及与《AgentBuddy_功能优化与设计建议.md》中 P0/P1 项的关系。

---

## 一、五家产品核心设计一览

| 维度 | Claude Code | OpenCode (SST) | Codex CLI | Aider | Gemini CLI |
|---|---|---|---|---|---|
| 架构 | 单体分层（memory/hooks/skills/subagents/MCP 各一层） | **client-server**（本地 server + TUI/桌面/IDE/CI 多客户端） | Rust 单二进制 | 终端结对编程 | ReAct 循环 + 原生 MCP |
| 权限模型 | 权限模式 + Auto Mode（小模型分类器预审每个动作） | 双代理切换（Plan 只读 / Build 全权） | **沙箱与审批双拨盘分离**（OS 级沙箱 × 审批策略互相独立） | Git commit 粒度兜底 | chat/agent 双模式权限 |
| 上下文管理 | /compact + /context 命令，压缩前 hook、压缩后重广播运行态 | ~95% 阈值自动 compact 成新会话 | /compact、/fork 分叉、/side 侧问 | RepoMap（tree-sitter 符号索引） | 1M token 大窗 + 按需探索 |
| 子代理 | Agent 工具派发：Explore/Plan/general-purpose + 用户自定义 .claude/agents/*.md，独立上下文、独立工具集、只回摘要 | task 子代理 + 多子代理并行 | guardian 子代理（预审待执行操作） | 无 | 无 |
| 扩展生态 | 插件市场（skills+agents+hooks+MCP 一键打包安装） | 插件化 + 多模型 75+ | /plugins + tool search | Git 深度绑定 | MCP 既是 client 也是 server |
| 典型差异化 | 交互式结对 + 完整生命周期钩子 | 开源免费、会话跨端持久化 | **"能做什么"和"何时问你"分离** | 编辑外科手术级精确（editblock 唯一性校验） | 大上下文 + 联网搜索原生 |

---

## 二、值得借鉴的设计 → 映射到 AgentBuddy

### ★ 借鉴 1：Tool Search 按需检索工具（解 40 上限的业界正解）

**业界做法**：Codex CLI 2026 起默认启用 tool search——大型 MCP server 的工具 schema 不再全量塞进上下文窗口，模型按需检索（来源：techriseups Codex 指南）。

**映射 AgentBuddy**：`chatService.ts:145-154` 现在的方案是"40 上限 + 超出丢弃 + 仅 logger.warn"，这正是业界已经淘汰的做法。AgentBuddy 的 skills 已经是"目录渐进披露 + use_skill 自取"（context.ts:81-85），**把同一模式复制到 MCP 工具**：
- 系统提示只注入"连接器目录"（已有，⑤层）
- 新增一个 `search_tools` 元工具：模型按任务关键词检索全量 MCP 工具的 schema
- 40 上限从"硬丢弃"变成"默认不展开"，被丢的工具不再消失

这一条直接把《功能优化与设计建议》P1-1 从"加提示"升级为"换方案"，且与现有 skills 架构同构，改动集中在 toolbus + context。

### ★ 借鉴 2：Compaction 的完整闭环（Claude Code 细节）

**业界做法**（arXiv 2604.14228）：
- 压缩前触发 PreCompact hook，允许注入自定义指令
- 压缩后**重新广播运行态**（当前 todo、已启用技能、后台子代理状态）——因为压缩丢的是消息，不是状态
- 提供 /compact（手动触发）与 /context（查看当前占用）命令，用户可控

**映射 AgentBuddy**：P1-3 的 compaction 设计时补三点：
1. 丢弃消息组后，除了插提示，还要把 `onTodos` 的最新 todo 清单重新注入（todo 状态在 sessionStore 里已有，天然可重放）
2. 加 `/compact` 手动命令 + 系统提示里报告当前 token 占用百分比（estimateTokens 修正后即得）
3. 压缩摘要生成用小模型（呼应"单模型架构"问题的辅助任务路由）

### ★ 借鉴 3：子代理 = 专家的下一步（Claude Code Agent 工具 + OpenCode 双代理）

**业界做法**：Claude Code 的 Agent 工具沿三个轴派发——路由（内置 Explore/Plan/general-purpose 或自定义）、隔离（独立上下文/独立 worktree）、生命周期（同步/异步后台）。关键设计约束：**子代理默认不继承父对话历史，必须自包含 prompt，返回只有一份摘要**——避免上下文爆炸。自定义子代理就是一个 md 文件：正文=人设，frontmatter=工具白名单/模型/权限模式/maxTurns。

**映射 AgentBuddy**：这与现有 Expert（persona + tools 绑定 + skills 绑定，experts.ts）**几乎同构**，只差执行模型：
- 现状：专家是"换人设的会话"（chatService.ts:136-143）
- 借鉴后：专家升级为"可被派发的子代理"——orchestrator 加一个内部委派（子 turn 带独立 messages 数组，只把最终摘要写回主对话）
- 权限：子代理经同一 PermissionGate，但可继承专家的更严工具白名单（bus 构建已支持，chatService.ts:151）
- 落地顺序：先做同步委派（`@专家名 任务描述` → 新 turn → 摘要回灌），异步/并行放最后

### ★ 借鉴 4：沙箱与审批双拨盘（Codex 的核心洞察）

**业界做法**：Codex 把"能做什么"（OS 级沙箱：macOS Seatbelt / Linux Landlock+seccomp / Windows restricted token）与"何时问你"（审批策略）拆成两个独立设置——松审批 + 紧沙箱也是安全的。2026 年 4 月还加了 guardian 子代理预审待执行操作，替代"无脑自动放行"。

**映射 AgentBuddy**：现有边界是"Permission Gate + workspace jail"（risk.ts:3-4 自述），bash 命令本身仍能读到工作区外的文件（jail 只约束 fs 工具的 resolvePath）。分级借鉴：
- 短期（修 P0-1 时顺手）：Auto 模式借鉴"分类器预审"思想——在白名单之外，用规则/小模型对命令做二次分类，风险命令降级回 Ask
- 长期：Electron 主进程可考虑接入 OS 级机制（Windows Job Object / macOS sandbox-exec）包住 process.run，把"能做什么"真正从模型自觉中解放出来

### ★ 借鉴 5：编辑外科手术校验（Aider editblock）

**业界做法**：Aider 应用每次编辑前**先验证原代码块在文件中唯一存在**，不唯一即拒绝，杜绝"改错位置"和"越改越多"。

**映射 AgentBuddy**：fsWrite/edit（fsWrite.ts）若当前是整文件覆盖或字符串替换，建议补唯一性校验：匹配到 0 处或多处都返回结构化错误让模型修正。成本低，收益直接体现在 Diff 干净度上。

### ★ 借鉴 6：Hooks 生命周期钩子（Claude Code）

**业界做法**：~20 个生命周期事件（PreToolUse / PostToolUse / PreCompact / SessionStart / PermissionRequest…）触发用户定义的确定性脚本——"模型管例外，钩子管规则"。

**映射 AgentBuddy**：orchestrator 已有 onRecord / onUsage / onTodos 等内部回调（TurnDeps，orchestrator.ts:47-55），就是 hooks 的雏形。设计用户可配置版：`{dataDir}/hooks.json` 映射事件 → 本地命令，PreToolUse 的返回可拦截工具调用（正好与 Permission Gate 叠加，不绕过 §14 硬边界）。这条与"Skill 安全准入与治理"的项目主题高度契合，答辩可讲。

### 借鉴 7：轻量项（顺手做）

| 业界做法 | 来源 | 映射 AgentBuddy |
|---|---|---|
| /fork 会话分叉、/side 侧问不进主对话 | Codex slash 命令 | 呼应 Checkpoint 时间旅行设计；侧问可用独立小上下文 |
| 后台任务 run_in_background + 轮询 | Claude Code | bash 目前同步阻塞 turn（orchestrator.ts:253），长构建可后台化 |
| Headless one-shot：`claude -p` / `codex exec` 进 CI | 各家 | AgentBuddy 加 CLI 一次性模式，personal 自动化场景可用 |
| 会话跨端持久化 / 断线恢复摘要 | OpenCode / Claude Code away summary | sessionStore 已持久化，补"离开后回来给段摘要" |
| LSP diagnostics 工具 | OpenCode | edit 后自动取诊断错误回灌模型，比跑测试便宜得多 |
| RepoMap 符号索引 | Aider | 远期；优先级低于记忆与 compaction |

---

## 三、对照结论：哪些之前的建议需要修正

| 原建议 | 修正 |
|---|---|
| P1-1 MCP 40 上限"加 UI 提示" | 升级为借鉴 1：tool search 按需检索，业界已验证的正解 |
| P1-3 compaction"小模型摘要" | 补借鉴 2：压缩后重放 todo 状态 + /compact /context 命令化 |
| 专家团 2.0"@专家转交" | 升级为借鉴 3：对齐 Claude Code 子代理协议（自包含 prompt、只回摘要、独立工具白名单），架构上可直接长在 Expert 上 |
| 长期"OS 级沙箱"想法 | 得到业界背书（Codex 双拨盘 + guardian 预审），且"分类器预审"可作为 Auto 模式的中间态先落地 |

**总体判断**：AgentBuddy 的骨架（工具统一接口、权限矩阵、渐进披露、checkpoint）与 2026 年业界主流设计高度同向，没有方向性错误；差距集中在 **tool search、compaction 闭环、子代理执行模型** 三个点，而这三个点恰好都能长在现有模块上。

---

## 参考来源

1. Dive into Claude Code: The Design Space of Today's and Future AI Agent Systems（arXiv:2604.14228 转述）— claude-wiki.com
2. Claude Code Guide 2026: 25 Features — marktechpost.com（2026-06-14）
3. opencode (SST) — aiwiki.ai；OpenCode deep dive — github.com/lilyzhng/SofaGenius PR#92（2026-03-27）
4. Codex CLI Prompting Guide — sureprompts.com；Codex CLI Cheatsheet — shipyard.build；Codex CLI Review 2026 — dev.to
5. A Comparative Analysis of AI Coding Assistants — vancsj.github.io；Gemini CLI Analysis — aisignal.dev
