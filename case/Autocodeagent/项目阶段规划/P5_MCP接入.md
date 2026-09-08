# P5 · MCP 接入（✅ 已完成）

> 周期参考：1–2 周 ｜ 前置：P1（可与 P3 / P4 并行）｜ 产出：stdio MCP 客户端 + Tools 发现 + JSON 批量导入

## 阶段目标

按 MCP 协议接入外部工具能力：官方 SDK 连接 stdio server，`tools/list` 自动合并进工具总线，配置支持文件 / 表单 / JSON 粘贴三通道。传输仅做 stdio，SSE/HTTP 后置。

## 范围

**包含**：MCP Client 池、Tools 发现、三通道配置、连接管理 UI、`#` 提及
**不包含**：SSE / HTTP 传输、OAuth、Prompt / Sampling / Roots 等协议特性

## 工作分解

| # | 任务 | 说明 |
| --- | --- | --- |
| 1 | `McpConfig` | `~/.AgentBuddy/mcp.json` 读写（`mcpServers` 结构，zod 校验）；文件、表单、JSON 导入三通道统一走 `upsert`（同名覆盖） |
| 2 | 连接池 | `@modelcontextprotocol/sdk`：`Client` + `StdioClientTransport`；启用即连接、禁用 / 退出 `close()`、崩溃标记离线不影响内置工具 |
| 3 | Tools 发现 | `listTools()` → 包装为内部 `Tool`：`mcp__{server}__{tool}`，risk = NETWORK；首次调用确认，可按 server 记忆信任 |
| 4 | 环境变量 | `env` 中 `${VAR}` 占位符从系统环境变量解析注入；不落盘、不进日志 |
| 5 | 工具数护栏 | 单会话挂载工具上限 40（内置 7 + MCP 33），超出提示在管理页禁用连接器 |
| 6 | JSON 导入 | 弹窗粘贴 `{"mcpServers": {...}}` 或内层对象；`command+args`→stdio、`url`→sse（占位）；`enabled` 决定自动连接；解析失败整体拒绝并行级报错 |
| 7 | 管理页 | 卡片式：名称、类型徽标、连接开关、状态、Tools 数量与展开、命令 / 端点行；新增弹窗「常规连接 \| JSON 导入」双模式切换；支持上传图标（image/* ≤100KB，dataURL 存储） |
| 8 | `#` 提及 | 输入框 `#` 弹出连接器菜单，未连接置灰；选中后注入 `#name`；⑤层系统提示注入已连接连接器目录 |

## 验收条件（全部达成）

- [x] 《设计方案》成功标准 3：配置官方 `@modelcontextprotocol/server-filesystem`，管理页显示其 Tools 列表，模型调用其 tool（经确认）成功读写允许目录 —— 机制由官方 SDK 真实 stdio server 夹具验证：连接/发现/经权限调用/回灌全链路（`mcpPool.test.ts` + `smoke.real.test.ts` P5 用例）
- [x] 《设计方案》成功标准 7：粘贴 Claude Desktop 格式 `mcpServers` JSON 批量导入，`enabled: true` 的自动连接、同名覆盖、`enabled: false` 保持未连接（`mcpConfig.test.ts` importJson 全套）
- [x] 畸形 JSON 导入时行级报错，不产生半截配置（汇总 `· name：原因` 整体拒绝，0/N 写入，文件字节不变）
- [x] `GITHUB_TOKEN` 类 `${VAR}` 占位符正确注入且日志中无明文（`resolveEnv` 报错仅提变量名；子进程 stderr `pipe` 不回流不落日志；`envprobe` 端到端验证）
- [x] MCP server 崩溃后标记离线，内置工具不受影响；重连按钮可恢复（`transport.onclose` + client 身份校验；crash 用例验证）
- [x] 挂载工具达 40 上限时给出禁用提示，请求中 tools schema 不再膨胀（`buildSessionBus` 超限丢弃计数 + McpView 琥珀警告条）
- [x] MCP 调用在 Tool Trace 中显示为 `github / create_issue` 形式，风险徽标 NETWORK（ToolCard displayName + plug 图标）
- [x] 手工脚本：接官方 SDK server 验证 list / call 全流程（`tests/fixtures/mcpEchoServer.mjs`，10 项集成用例覆盖 list/call/崩溃/重连/启停）
- [x] 附加需求：新增连接器弹窗「常规连接 | JSON 导入」双模式切换；支持上传连接器图标
- [x] 附加安全：权限按 server 会话信任（同 server 任一工具授权后其余复用，他 server 仍询问）；SSE/HTTP 可保存但连接时明确提示「规划后续阶段」；zod IPC 入参校验（`mcp:upsert` 等 6 通道）；退出前 `closeAll()` 收尾（before-quit）
- [x] 质量门禁：全量回归 **217 passed | 3 skipped**（基线 181 + 新增 36）；typecheck 双包零错误；renderer/main 构建通过（esbuild 打包 MCP SDK 无报错）

## 交付检查点（已完成）

真模型冒烟 1 次（gpt-5-mini 实跑）：经 `#echo` 提及 → 模型调用 `mcp__echo__ping`（官方 SDK 真实 stdio server 夹具，与 `#filesystem` 同机制）→ NETWORK 权限确认 → 结果回灌总结。另两项历史冒烟（修 bug / /review）复跑仍通过。
