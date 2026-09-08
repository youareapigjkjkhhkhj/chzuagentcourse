# 11 - 规划 Planning

本篇目标：理解 CrewAI 的 **Planning（规划）** 特性——让 Crew 在每次迭代前使用 AgentPlanner 制定逐步执行计划。

## 11.1 概述

**Planning 功能为 Crew 增添规划能力**。启用后，在每次 Crew 迭代前：

1. 所有 Crew 信息发送给 **AgentPlanner**
2. AgentPlanner 将任务**逐步规划**
3. 该计划被**添加到每个 Task 描述中**

> 一句话：让 Agent 在动手前先想好怎么做。

## 11.2 启用 Planning

极简——只需在 Crew 中添加 `planning=True`：

```python
from crewai import Crew, Process

crew = Crew(
    agents=[researcher, writer],
    tasks=[task1, task2],
    process=Process.sequential,
    planning=True,   # ← 启用规划
)
```

> 从这里开始，Crew 将启用规划，任务在每次迭代前都会被规划。

## 11.3 指定规划 LLM

可以指定用于规划任务的 LLM：

```python
from crewai import Crew

crew = Crew(
    agents=[researcher, writer],
    tasks=[task1, task2],
    planning=True,
    planning_llm="openai/gpt-4o",  # 指定规划用模型
)
```

## 11.4 规划输出示例

运行基础案例时，你会看到类似输出——这是 AgentPlanner 生成的**逐步规划**，会注入到 Agent 的任务描述中：

```
=== Agent Planner ===
Planning for the upcoming iteration...

1. Research Phase
   - 搜索关于 AI agents 的最新资料
   - 收集关键论文和行业报告
   
2. Analysis Phase  
   - 分析收集到的资料
   - 识别核心趋势和见解
   
3. Report Phase
   - 撰写结构化研究报告
   - 校对和格式化输出
```

## 11.5 Planning 的工作原理

```
Crew.kickoff()
    │
    ├── 第 1 次迭代开始
    │     │
    │     ├── AgentPlanner 接收所有 Crew 信息
    │     ├── 生成逐步执行计划
    │     └── 计划注入到每个 Task 描述
    │
    ├── Agent 执行任务（携带规划指令）
    │     └── 输出结果
    │
    ├── 第 2 次迭代开始
    │     ├── AgentPlanner 再次规划（基于上次结果优化）
    │     └── ...
    │
    └── 最终输出
```

## 11.6 配置方式（JSONC）

在 `crew.jsonc` 中启用：

```jsonc
{
  "agents": ["researcher", "writer"],
  "tasks": [...],
  "process": "sequential",
  "planning": true,
  "planning_llm": "openai/gpt-4o"
}
```

## 11.7 何时使用 Planning？

**建议使用 Planning 的场景**：
- 复杂多步骤任务需要系统化分解
- 任务目标不够明确，需要先规划再执行
- 需要确保 Agent 按逻辑顺序推进
- 多 Agent 团队需要协调不同角色的工作

**可能不需要的场景**：
- 简单直接的单步骤任务
- 任务顺序已经由 Process 明确控制
- 规划会显著增加 LLM 调用成本

## 关键 API 速查

| API | 用途 |
|-----|------|
| `Crew(planning=True)` | 启用规划 |
| `Crew(planning_llm="gpt-4o")` | 指定规划 LLM |
| JSONC：`"planning": true` | JSONC 配置启用 |

## 下一步

→ [12-Flows工作流.md](12-Flows工作流.md)：用事件驱动工作流编排多个 Crew。
