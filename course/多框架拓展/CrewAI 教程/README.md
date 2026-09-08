# CrewAI 教程

> CrewAI 是领先的开源**多智能体编排框架**，通过 **Crews**（协作者团队）和 **Flows**（事件驱动工作流）构建生产级 AI 应用。本教程按官方文档（docs.crewai.com）的 building blocks 顺序拆分知识点，每篇独立成档、代码均可逐步运行。

## 哲学：CrewAI 是什么？

CrewAI 的两大核心支柱：

| 组件 | 作用 | 类比 |
|------|------|------|
| **Flows** | 事件驱动的工作流骨架，管理状态与执行顺序 | 应用的"骨架" |
| **Crews** | 角色扮演的自主智能体团队，协作完成特定任务 | 应用中的"工作单元" |

一句话理解：**Flow 决定"什么时候做什么"，Crew 决定"每个任务由谁来做"**。

## 环境要求

- **Python 3.10+**
- 包管理器：`uv`（官方推荐，也可用 `pip`）
- 任意模型厂商 API Key：OpenAI / Anthropic / Gemini / DeepSeek / Ollama（本地）
- 可选工具：Serper.dev API Key（用于网络搜索工具）

## 教程顺序（官方 Concepts 心智模型）

| # | 文件 | 知识点 |
|---|------|--------|
| 1 | `01-安装与环境配置.md` | `uv` 安装、CrewAI CLI、环境变量、项目脚手架 |
| 2 | `02-快速开始.md` | 第一个 Flow + Crew，JSONC 配置 vs 代码定义 |
| 3 | `03-智能体Agent.md` | `Agent` 类、托管参数（role/goal/backstory）、Agent Capabilities |
| 4 | `04-任务Task.md` | `Task` 类、顺序/层级执行、任务上下文、条件任务 |
| 5 | `05-Crew团队.md` | `Crew` 类、JSONC 配置、代码定义、运行方式 |
| 6 | `06-流程Process.md` | Sequential / Hierarchical 两种执行策略 |
| 7 | `07-工具Tools.md` | `crewai-tools` 扩展包、内置工具、自定义工具 |
| 8 | `08-记忆Memory.md` | 统一 Memory 类、层次化 Scopes、与 Crew/Agent/Flow 集成 |
| 9 | `09-知识Knowledge.md` | 外部知识源（PDF/CSV/Excel/JSON/文本）、Agent vs Crew 级知识 |
| 10 | `10-技能Skills.md` | SKILL.md 文件、领域专家指令、Skills + Tools 模式 |
| 11 | `11-规划Planning.md` | `planning=True`、AgentPlanner、任务逐步规划 |
| 12 | `12-Flows工作流.md` | 事件驱动、状态管理、条件逻辑、循环、路由 |
| 13 | `13-LLM配置.md` | 多提供商接入、函数调用 LLM、流式输出 |
| 14 | `14-CLI命令行.md` | `crewai create/run/train/test/replay` 等命令 |
| 15 | `15-测试与训练.md` | `crewai test` 性能指标、`crewai train` 人工反馈训练 |
| 16 | `16-文件处理Files.md` | 多模态文件输入（图片/PDF/音频/视频）、文件优先级 |
| 17 | `17-MCP集成.md` | MCP 服务器作为 Agent 工具、DSL 配置、协议支持 |

## 两种项目配置方式

CrewAI v1.15+ 推荐使用 **JSONC 配置驱动**（新项目默认），同时兼容经典 **YAML/装饰器** 方式：

```
# JSONC 方式（推荐）
crewai create crew my_crew
#   → agents/*.jsonc（每个 agent 一个文件）
#   → crew.jsonc（crew 级设置 + 任务定义）

# 经典 YAML 方式
crewai create crew my_crew --classic
#   → crew.py（@CrewBase 装饰器）
#   → config/agents.yaml + config/tasks.yaml
```

## 官方资源

- 官方文档：[docs.crewai.com](https://docs.crewai.com/)
- GitHub：[crewAIInc/crewAI](https://github.com/crewAIInc/crewAI)
- 社区：[community.crewai.com](https://community.crewai.com/)
- 烹饪书：[Examples & Cookbooks](https://docs.crewai.com/en/examples/cookbooks)
