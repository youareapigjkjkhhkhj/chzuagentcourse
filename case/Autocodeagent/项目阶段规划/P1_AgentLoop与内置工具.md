# P1 · Agent Loop 与内置工具

> 周期参考：1–2 周 ｜ 前置：P0 ｜ 产出：「计划→执行→验证→修复→前进」的真实闭环

## 阶段目标

让模型第一次真正操作本机文件与命令。这是整个产品的核心阶段：Agent Loop、6 个内置工具、Ask 权限、上下文截断、进程管理一次到位。

## 范围

**包含**：Orchestrator、Tool Bus、6 内置工具、Permission Gate（Ask 模式）、workspace jail、checkpoint 快照 v1、进程管理、Compaction 截断版
**不包含**：Diff 审阅 UI（P2）、Auto/Plan 模式（P3）、Skills / MCP

## 工作分解

| # | 任务 | 说明 |
| --- | --- | --- |
| 1 | `Tool` 接口与 Tool Bus | 统一 `name / description / inputSchema / risk / assessRisk / execute`；schema 导出供 function calling |
| 2 | 6 内置工具 | `read`（≤2000 行、行号格式）、`glob`、`grep`、`write`、`edit`（精确 str_replace）、`bash`（EXEC，超时默认 120s） |
| 3 | workspace jail | 所有 FS 操作经 `resolveWithinWorkspace()`，逃出工作区直接拒绝；`read` 时刻 mtime 记录，`edit` 前新鲜度校验 |
| 4 | Orchestrator | `runTurn` 主循环：maxTurns=20、`tool_calls` 按 index 累积后一次性 parse、同消息内独立调用并发执行、同参连败 2 次熔断、事件发射（onToolStart / onToolResult） |
| 5 | Permission Gate v1 | Ask 模式：READ 自动，WRITE/EXEC/NETWORK/DANGEROUS 逐次询问；拒绝结果结构化回灌模型 |
| 6 | `process` 模块 | bash 统一走 `run()`：cwd 强制工作区、超时、输出 ≤20KB 截断、平台化杀树（Windows `taskkill /T /F`、POSIX 进程组 kill） |
| 7 | checkpoint v1 | WRITE/EXEC 前打快照（git 仓库 `git stash create --include-untracked`，非 git 复制受影响文件） |
| 8 | 上下文截断版 | token 预算 = 上限 − 8k；超限先把旧工具结果正文替换为占位摘要（保留首 10 行）；`read` / `bash` 源头限流 |
| 9 | Tool Trace UI | 中栏按回合呈现：AI 回复 → 工具卡片流（name、入参摘要、结果、耗时）→ AI 总结 |

## 验收条件

- [ ] 真实模型跑通：「分析本项目并修复 X 问题」→ grep/read 定位 → edit 修改 → bash 跑测试 → 测试失败后自行再改 → 完成
- [ ] 工作区外路径（如 `../../etc/passwd`）读写全部被拒绝并记录
- [ ] `edit` 前文件被外部修改 → 拒绝执行并提示重新 `read`
- [ ] 运行长命令时点停止：整棵进程树被杀死，无残留 `node` 进程
- [ ] WRITE/EXEC 每次弹出确认，拒绝后模型换路而非卡死
- [ ] 连续 20 轮上限触发时报「达到 maxTurns」，无死循环烧钱
- [ ] 长会话（≥30 轮工具调用）不撞上下文上限，旧工具结果被占位摘要替换
- [ ] 单测：`resolveWithinWorkspace` 逃逸用例、edit 替换、`tool_calls` 分片拼接、权限 Ask 决策

## 交付检查点

mock-LLM 集成测试：read → edit → bash 一轮全绿 + 真模型冒烟 1 次完整修 bug 流程。
