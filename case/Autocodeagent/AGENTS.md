---
name: agentbuddy-development
description: AgentBuddy 专属开发规范。用于所有 AgentBuddy 项目的代码设计、开发、重构、修复和新增功能。核心目标是保持架构清晰、代码简单、模块职责单一、避免过度设计和代码臃肿。
---

# AgentBuddy 开发规范

## 1. 核心原则

AgentBuddy 是个人本地 Agentic Coding 工作台。

开发必须遵循以下优先级：

1. **正确性**
2. **安全性**
3. **简单可读**
4. **职责清晰**
5. **最小修改**
6. **复用已有能力**
7. **必要时再抽象**
8. **避免过度设计**

核心原则：

> 能简单解决的问题，不要复杂化。

> 能修改已有模块，不要无意义地创建新模块。

> 能复用已有代码，不要重复实现。

> 当前需求不需要的能力，不要提前实现。

---

# 2. 开发前必须先理解项目

涉及代码修改时，必须先进行项目侦察，不允许直接开始写代码。

至少完成：

1. 查看项目目录结构。
2. 定位与需求相关的模块。
3. 阅读相关代码。
4. 理解现有模块之间的调用关系。
5. 判断功能应该属于哪个已有模块。
6. 确定最小修改范围。
7. 检查是否已经存在可复用的函数、服务、组件或类型。
8. 再开始修改。

如果无法判断现有架构，应优先阅读代码，而不是直接创建新的抽象。

---

# 3. 架构原则

AgentBuddy 当前采用：

```text
Electron
├── Renderer
│   └── Vue 3 + TypeScript
│
├── Preload
│   └── 白名单 IPC
│
└── Main
    └── agent-core
        ├── orchestrator
        ├── context
        ├── permission
        ├── toolbus
        ├── tools
        ├── skills
        ├── checkpoint
        ├── mcp
        ├── llm
        ├── usage
        └── store
```

必须保持以下边界：

### Renderer

负责：

- UI
- 用户交互
- 状态展示
- Stream 渲染
- Tool Trace
- Diff 展示
- Permission UI

Renderer 不允许直接访问：

- Node.js API
- 文件系统
- child_process
- Shell
- 密钥
- MCP 子进程
- 本地敏感数据

所有能力必须通过：

```text
Renderer
  ↓
Preload
  ↓
IPC
  ↓
Main
```

---

# 4. agent-core 模块边界

## orchestrator

只负责：

- Agent Loop
- Turn 管理
- Abort
- Timeout
- Agent 生命周期
- 事件发射

不要在 orchestrator 中堆积：

- 文件操作逻辑
- MCP 逻辑
- 权限规则
- UI 逻辑
- Git 逻辑
- 具体业务逻辑

---

## context

负责：

- 上下文组装
- Token Budget
- 历史消息管理
- 工具结果截断
- Compaction
- Context 注入

不要在 context 中执行工具。

---

## permission

负责：

- 风险判断
- 权限矩阵
- 用户确认
- 会话级授权

任何工具执行都必须经过 Permission Gate。

禁止工具绕过 Permission Gate。

---

## toolbus

负责：

- Tool 注册
- Tool 查询
- Tool Schema
- Tool 分发

不要在 ToolBus 中实现具体工具业务。

---

## tools

每个工具负责一个明确能力。

例如：

```text
read
glob
grep
write
edit
bash
todo
```

工具必须遵循统一 Tool 接口。

禁止为每个工具设计完全不同的调用方式。

---

## checkpoint

负责：

- 修改前快照
- ChangeSet
- Restore
- Diff 与撤销关联

必须考虑：

```text
modified
created
deleted
renamed
```

不能只考虑修改已有文件。

---

## mcp

负责：

- MCP Server 配置
- 生命周期
- 连接
- tools/list
- tools/call
- Server 状态

MCP 不应直接侵入 Agent Loop。

Agent 只通过 ToolBus 使用 MCP Tool。

---

## llm

负责：

- LLM API
- Streaming
- Tool Calls
- Abort
- Retry
- Usage

不同模型厂商的数据必须在 Adapter 层归一化。

---

# 5. 代码规模控制

AgentBuddy 强调“小而清晰”的代码。

默认参考标准：

| 对象 | 建议上限 | 超过后 |
|---|---:|---|
| 普通 TS 文件 | 300 行 | 检查是否需要拆分 |
| TS 文件 | 400 行 | 原则上应拆分 |
| TS 文件 | 500 行 | 原则上禁止继续堆积 |
| Vue Component | 300 行 | 检查拆分 |
| 函数 | 50 行 | 检查拆分 |
| 函数 | 80 行 | 原则上必须拆分 |
| 单个 Class | 300 行 | 检查职责 |
| 单个模块 | 单一职责 | 多职责必须拆分 |

以上是**设计警戒线，不是机械规则**。

例如：

```text
types.ts
```

即使 500 行，也可能合理。

但：

```text
agent.ts
```

如果达到 500 行并同时负责：

- Agent Loop
- Context
- Permission
- Tool
- MCP
- Logging

则必须拆分。

判断标准优先于行数。

---

# 6. 什么时候必须拆分代码

出现以下任意情况，应考虑拆分：

### 6.1 一个文件出现多个明显职责

例如：

```text
mcp.ts
├── 配置
├── Server 连接
├── Tool 注册
├── UI 状态
└── JSON 导入
```

应拆分为职责明确的模块。

---

### 6.2 一个函数承担多个阶段

例如：

```text
loadProject()
```

同时：

```text
读取文件
解析配置
初始化 MCP
创建 Session
加载 Skill
发送 UI 事件
```

必须拆分。

---

### 6.3 需要大量注释才能解释代码

如果代码必须写大量：

```text
// 这里先这样做，因为……
// 如果……
// 然后……
```

才能理解，优先考虑重新设计。

目标：

> 让代码结构本身表达意图。

---

### 6.4 出现大量 if/else

如果一个函数出现大量：

```ts
if (...)
else if (...)
else if (...)
else if (...)
```

应判断是否存在：

- Strategy
- Map
- Handler
- Adapter
- 独立函数

但禁止为了消灭 if/else 而过度设计。

---

# 7. 禁止过度抽象

不要为了“看起来高级”而创建：

```text
AbstractXXX
BaseXXX
XXXFactory
XXXManager
XXXService
XXXRegistry
XXXProvider
XXXStrategy
```

除非确实存在多个实现或明确的扩展需求。

例如当前只有：

```text
OpenAI Compatible API
```

不要为了未来可能存在的 10 个 Provider，提前创建复杂 Provider Framework。

优先：

```text
简单 Adapter
```

等出现真实需求后再抽象。

---

# 8. 禁止无意义创建文件

新增文件前必须回答：

1. 为什么不能放入现有模块？
2. 新文件是否承担独立职责？
3. 是否会被多个地方复用？
4. 是否能够降低复杂度？

如果只是几十行一次性逻辑，不要为了“模块化”强行创建新文件。

---

# 9. 禁止巨型文件

以下文件禁止成为“垃圾桶”：

```text
utils.ts
helpers.ts
common.ts
index.ts
agent.ts
manager.ts
service.ts
types.ts
```

尤其禁止：

```text
utils.ts
```

不断添加：

```text
formatX()
parseY()
handleZ()
checkA()
convertB()
```

应该按照领域拆分：

```text
utils/
├── path.ts
├── token.ts
├── json.ts
└── process.ts
```

---

# 10. 优先复用已有能力

新增功能前必须搜索：

```text
已有函数
已有类型
已有组件
已有 Tool
已有 IPC
已有 Service
已有状态
已有工具类
```

禁止重复实现。

例如已有：

```ts
resolveWithinWorkspace()
```

禁止再次创建：

```ts
isValidWorkspacePath()
checkWorkspacePath()
validateFilePath()
```

除非职责确实不同。

---

# 11. 最小修改原则

修复 Bug 时：

> 只修改解决问题所需要的代码。

禁止：

```text
修一个 Bug
↓
顺便重构整个模块
↓
修改 20 个文件
↓
新增 5 个抽象
```

除非当前代码确实已经阻碍修复。

优先：

```text
定位问题
↓
最小修复
↓
测试
↓
完成
```

---

# 12. 新功能开发原则

新增功能必须优先判断：

```text
是否可以扩展现有模块？
        ↓
可以 → 修改现有模块
        ↓
不可以
        ↓
是否需要独立职责？
        ↓
需要 → 新模块
```

不要：

```text
一个需求
↓
Controller
Service
Manager
Factory
Adapter
Repository
```

个人本地应用优先保持简单。

---

# 13. Agent Loop 开发约束

Agent Loop 是核心基础设施。

必须保持：

```text
User
 ↓
Context
 ↓
LLM
 ↓
Tool Calls
 ↓
Permission
 ↓
Tool Execute
 ↓
Tool Result
 ↓
LLM
 ↓
...
```

不得将具体业务逻辑硬编码进 Loop。

例如禁止：

```ts
if (tool.name === 'read') {
   ...
}

if (tool.name === 'bash') {
   ...
}

if (tool.name === 'mcp') {
   ...
}
```

应该通过：

```text
ToolBus
```

统一处理。

---

# 14. Permission 是硬边界

任何：

```text
WRITE
EXEC
NETWORK
DANGEROUS
```

操作必须进入 Permission Gate。

禁止：

```text
UI → Tool → execute()
```

绕过：

```text
Permission
```

正确：

```text
Agent
 ↓
ToolBus
 ↓
Permission
 ↓
Tool
 ↓
Execute
```

---

# 15. 文件操作安全

所有工作区文件路径必须经过：

```text
resolveWithinWorkspace()
```

禁止访问工作区之外的路径。

必须防止：

```text
../
../../
绝对路径逃逸
符号链接逃逸
```

如果无法确认路径安全：

> 拒绝执行，而不是猜测。

---

# 16. Bash 执行规范

Bash 是高风险能力。

必须具备：

- Workspace cwd
- Timeout
- Abort
- stdout 限制
- stderr 限制
- 进程终止
- 危险命令检测
- Permission Gate

危险命令必须升级风险。

例如：

```text
rm -rf
sudo
git reset --hard
git push --force
npm publish
DROP TABLE
```

风险检测是安全辅助机制，不得作为唯一安全边界。

---

# 17. Streaming 处理规范

LLM Streaming 中：

```text
tool_calls
```

必须按照：

```text
index
 ↓
累积 arguments
 ↓
完整结束
 ↓
JSON.parse
```

禁止对每一个 SSE chunk 直接 JSON.parse。

---

# 18. 状态与事件

Agent Core 与 Renderer 之间优先使用事件驱动：

```text
onStreamToken
onPlanStep
onToolStart
onToolResult
onPermissionRequest
onDiffReady
onDone
onError
```

不要让 Renderer 主动轮询 Agent 状态作为主要通信方式。

---

# 19. 错误处理

错误必须：

```text
可识别
可恢复
可展示
```

不要：

```ts
catch (e) {
   console.log(e)
}
```

然后静默失败。

工具失败应尽可能结构化返回：

```text
ToolResult
├── ok
├── text
├── error
└── metadata
```

Agent 可以根据工具错误重新决策。

---

# 20. 日志规范

日志必须：

- 有明确模块
- 有错误上下文
- 不记录 API Key
- 不记录完整敏感环境变量
- 不打印无意义的大段数据

禁止：

```text
console.log(JSON.stringify(entireContext))
```

禁止输出：

```text
API Key
Token
密码
MCP Secret
```

---

# 21. 第三方依赖控制

新增 npm 依赖前必须先检查：

1. 项目是否已有类似能力。
2. Node/Electron 是否原生支持。
3. 是否可以用现有依赖实现。
4. 该依赖是否真正必要。

原则：

> 少一个依赖，就少一个维护点。

不要为了几十行功能引入大型依赖。

---

# 22. Vue 开发规范

组件保持单一职责。

推荐：

```text
ChatPanel
ToolTrace
PermissionCard
DiffViewer
McpServerCard
UsageOverview
```

不要创建：

```text
App.vue
```

然后把整个应用所有业务逻辑塞进去。

组件内部：

```text
UI
 ↓
emit / composable
 ↓
IPC
```

复杂逻辑优先抽到：

```text
composables/
services/
stores/
```

但不要为了几十行逻辑机械抽象。

---

# 23. TypeScript 规范

优先：

```ts
type
interface
unknown
```

谨慎使用：

```ts
any
```

禁止为了快速通过 TypeScript：

```ts
as any
```

如果必须使用，应说明原因。

公共接口必须有明确类型。

IPC payload 必须使用 Zod 校验。

---

# 24. 修改前后的 Diff 原则

任何代码修改都应尽量：

```text
小
准
可回滚
```

避免一次修改大量无关格式。

禁止：

```text
修一个 Bug
↓
顺便格式化整个项目
↓
产生 3000 行 Diff
```

Diff 应该让开发者能够快速回答：

> “这次修改到底改变了什么？”

---

# 25. 测试原则

新增功能必须至少验证：

```text
正常情况
异常情况
边界情况
```

涉及核心模块时必须补测试。

重点模块：

```text
Permission
resolveWithinWorkspace
edit
Checkpoint
Agent Loop
Tool Call Streaming
MCP
```

修改已有代码后：

```text
先跑相关测试
↓
再跑整体测试
```

---

# 26. 开发完成后的强制自检

完成任务后必须主动检查：

### 架构

- 是否破坏模块边界？
- 是否增加不必要的依赖？
- 是否产生新的重复逻辑？
- 是否出现职责混乱？

### 代码

- 是否存在巨型函数？
- 是否存在巨型文件？
- 是否可以进一步简化？
- 是否有重复代码？
- 是否有无意义抽象？

### 安全

- 是否绕过 Permission？
- 是否存在路径逃逸？
- 是否存在 Shell 风险？
- 是否可能泄露 Key？

### 测试

- 是否验证正常流程？
- 是否验证异常流程？
- 是否验证边界条件？

### Diff

- 是否修改了无关代码？
- 是否产生大面积格式变化？
- 是否需要拆分？

---

# 27. 复杂度检查

每完成一个中大型功能，都必须问自己：

```text
这个功能能不能更简单？

有没有创建不必要的文件？

有没有创建不必要的类？

有没有创建不必要的抽象？

有没有重复实现已有能力？

有没有把业务逻辑塞进错误的模块？

有没有为了未来需求提前设计？

有没有超过合理代码规模？

如果删除 30% 的代码，功能还能不能成立？
```

如果可以删除且不影响功能：

> 优先删除。

---

# 28. 优先选择简单方案

当存在多个实现方案时：

```text
方案 A：100 行 + 3 个抽象
方案 B：50 行 + 1 个模块
```

如果两者都满足需求：

> 优先方案 B。

当存在：

```text
第三方库
vs
已有能力 + 30 行代码
```

如果已有能力足够：

> 优先已有能力。

---

# 29. 不提前实现未来需求

禁止因为：

```text
以后可能支持……
未来可能需要……
后面可能接……
```

提前加入复杂代码。

当前 MVP 只实现当前需求。

架构需要：

```text
预留合理接口
```

但不需要：

```text
提前实现完整系统
```

例如：

```text
当前 MCP 只支持 stdio
```

不需要为了未来 SSE/HTTP 提前实现完整 HTTP MCP。

---

# 30. MVP 原则

AgentBuddy MVP 的目标不是：

> 功能最多。

而是：

> 用最少的代码形成稳定的 Agentic Coding 闭环。

核心闭环：

```text
Chat
 ↓
Agent Loop
 ↓
Read
 ↓
Analyze
 ↓
Edit
 ↓
Diff
 ↓
Permission
 ↓
Bash
 ↓
Test
 ↓
Result
```

优先保证这个闭环稳定。

其他能力：

```text
Skills
MCP
Usage
Plan
Compaction
LSP
SubAgent
```

按照实际需求逐步增加。

---

# 31. 最重要的规则

如果本规范与“快速堆功能”发生冲突：

> 优先保持架构清晰和代码简单。

如果本规范与实际需求发生冲突：

> 先理解需求，再选择最小、最安全、最容易维护的实现。

如果无法确定：

> 不要猜测，不要大规模修改，先检查现有代码和架构。

最终目标：

```text
少代码
低耦合
低复杂度
职责清晰
容易理解
容易修改
容易回滚
容易测试
```

**AgentBuddy 不追求代码多，而追求每一行代码都有必要。**