# 06 - 流程 Process

本篇目标：理解 CrewAI 中 **Process（执行流程）** 的两种实现——Sequential 和 Hierarchical，以及如何选择。

## 6.1 概述

**Process** 定义了 Crew 中任务的执行策略。CrewAI 提供两种主要实现：

| 方式 | 特点 | 适用场景 |
|------|------|----------|
| **Sequential** | 按顺序一个接一个执行 | 流水线式任务，前一步输出是后一步输入 |
| **Hierarchical** | Manager 分派任务 | 复杂任务需要智能调度和分配 |

## 6.2 Sequential Process（顺序流程）

**顺序执行**模拟团队按既定顺序工作：任务按照定义的顺序依次执行，**前一个任务的输出作为后一个任务的上下文**。

```python
from crewai import Crew, Process

crew = Crew(
    agents=[researcher, writer],
    tasks=[task1, task2, task3],
    process=Process.sequential,
)
```

### 如何自定义任务上下文

通过 Task 的 `context` 参数，指定哪些任务的输出作为上下文：

```python
from crewai import Task

task3 = Task(
    description="总结前两个任务的结果",
    expected_output="一份综合摘要",
    agent=writer,
    context=[task1, task2],  # 只使用 task1 和 task2 的输出作为上下文
)
```

### 顺序流程的执行链

```
task1 输出 ──► task2 输入 ──► task2 输出 ──► task3 输入 ──► 最终结果
```

## 6.3 Hierarchical Process（层级流程）

**层级执行**模仿公司组织架构：

- 需要一个 **Manager Agent**（通过 `manager_llm` 或 `manager_agent` 指定）
- Manager 负责规划、委派和验证任务
- 任务**不预先分配**——Manager 根据 Agent 能力动态分配
- Manager 审查输出，评估任务完成度

```python
from crewai import Crew, Process

crew = Crew(
    agents=[researcher, analyst, writer],
    tasks=[research_task, report_task, publish_task],
    process=Process.hierarchical,
    manager_llm="openai/gpt-4o",  # 必须指定 Manager LLM 或 Manager Agent
)
```

或使用自定义 Manager Agent：

```python
manager = Agent(
    role="项目经理",
    goal="分配并监督团队任务，确保高质量产出",
    backstory="经验丰富的 AI 项目负责人",
    allow_delegation=True,  # 必须允许委派
)

crew = Crew(
    agents=[researcher, analyst, writer],
    tasks=[...],
    process=Process.hierarchical,
    manager_agent=manager,
)
```

### Manager 的工作流程

```
Manager Agent
    │
    ├── 1. 理解任务目标
    ├── 2. 将任务分解为子步骤
    ├── 3. 根据 Agent 能力分派任务
    │      └── researcher ──► 研究任务
    │      └── analyst    ──► 分析任务
    │      └── writer     ──► 写作任务
    ├── 4. 审查各 Agent 输出
    └── 5. 评估完成度，汇总结果
```

## 6.4 Process Class 详解

`Process` 是枚举类型（Enum），保证类型安全：

```python
from crewai import Process

print(Process.sequential)     # Process.sequential
print(Process.hierarchical)   # Process.hierarchical
print(Process.sequential.value)  # 'sequential'
```

## 6.5 如何选择？

### 选 Sequential 当：

- 任务有明确的先后依赖关系
- 流程固定，不需要动态调度
- 团队小（2-4 个 Agent）
- 需要精细控制上下文传递

### 选 Hierarchical 当：

- 任务分配需要智能决策
- 有大量 Agent，需要 Director 统一调度
- 任务不确定，需要 Manager 动态分解
- 需要集中化审查和质量控制

## 6.6 注意事项

> ⚠️ **重要**：创建 Crew 前确保 `agents` 和 `tasks` 已定义。
> 层级模式必须提供 `manager_llm` 或 `manager_agent`，否则会报错。

## 关键 API 速查

| API | 用途 |
|-----|------|
| `Process.sequential` | 顺序执行 |
| `Process.hierarchical` | 层级执行 |
| `Crew(process=..., manager_llm=...)` | 设置流程类型 |
| `Task(context=[...])` | 自定义上下文依赖 |

## 下一步

→ [07-工具Tools.md](07-工具Tools.md)：给 Agent 装"手脚"——工具系统。
