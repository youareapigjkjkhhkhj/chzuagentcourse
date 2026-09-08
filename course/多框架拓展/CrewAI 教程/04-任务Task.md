# 04 - 任务 Task

本篇目标：理解 CrewAI 中 **Task** 的概念——Agent 执行的具体工作单元，包括定义方式、属性详解、执行流程、条件任务。

## 4.1 什么是 Task？

**Task 是分配给 Agent 完成的特定工作单元**。每个 Task 提供执行所需的完整信息：描述、负责的 Agent、所需工具、输出格式等。

Task 可以是**协作式**的——允许多个 Agent 协同工作，通过 Crew 的 Process 编排。

## 4.2 任务执行流程

Task 有**两种执行方式**：

| 方式 | 特点 |
|------|------|
| **顺序执行（Sequential）** | Task 按定义顺序一个接一个执行 |
| **层级执行（Hierarchical）** | Task 由 Manager Agent 根据 Agent 角色和专长分配 |

执行流程在创建 Crew 时通过 `process` 属性定义。

## 4.3 Task 属性

```python
from crewai import Task

task = Task(
    # === 必填 ===
    description="深入研究AI最新进展并撰写报告",   # 任务描述
    expected_output="一份结构化报告，包含5个要点",   # 期望输出

    # === 可选 ===
    name="research_ai",                          # 任务名称
    agent=researcher,                            # 负责的 Agent
    context=[teacher_task],                      # 上下文（引用的前置任务）
    output_file="output/report.md",              # 输出到文件
    output_json="output/result.json",            # 输出为 JSON
    output_pydantic=MyModel,                     # 输出为 Pydantic 模型
    tools=[SerperDevTool()],                     # 任务级工具
    human_input=True,                            # 是否请求人工输入确认
    async_execution=False,                       # 是否异步执行
    guardrail=guardrail_func,                    # 任务护栏
    markdown=True,                               # 输出为 Markdown
    input_files=[],                              # 输入文件
    max_iter=10,                                 # 最大迭代数
    callback=None,                               # 完成后回调
)
```

## 4.4 三种创建 Task 的方式

### 方式一：JSONC 配置（推荐）

在 `crew.jsonc` 中定义任务：

```jsonc
{
  "agents": ["researcher", "writer"],
  "tasks": [
    {
      "name": "research_ai",
      "description": "研究「{topic}」的最新进展",
      "expected_output": "包含 5 个要点的结构化摘要",
      "agent": "researcher",
      "output_file": "output/research.md"
    },
    {
      "name": "write_report",
      "description": "根据研究结果撰写完整报告",
      "expected_output": "500字的专业分析报告",
      "agent": "writer",
      "context": ["research_ai"],
      "output_file": "output/report.md"
    }
  ]
}
```

> **关键规则**：
> - 必须包含 `description` 和 `expected_output`
> - `agent` 必须与 agents/ 中定义的 Agent 名称匹配
> - `context` 是前置任务名的列表；**不支持前向引用**
> - 可用 `"type": "ConditionalTask"` 定义条件任务（配合 `condition` 字段）

### 方式二：经典 YAML

在 `config/tasks.yaml` 中定义：

```yaml
research_ai:
  description: >
    研究「{topic}」的最新进展
  expected_output: >
    包含5个要点的结构化摘要
  agent: researcher
  output_file: output/research.md

write_report:
  description: >
    根据研究结果撰写完整报告
  expected_output: >
    500字的专业分析报告
  agent: writer
  context:
    - research_ai
  output_file: output/report.md
```

### 方式三：直接代码定义

```python
from crewai import Task

research_task = Task(
    description="研究AI最新进展",
    expected_output="5个要点的摘要",
    agent=researcher,
    output_file="output/research.md",
)

write_task = Task(
    description="撰写完整报告",
    expected_output="500字专业分析报告",
    agent=writer,
    context=[research_task],   # 引用前置任务作为上下文
    output_file="output/report.md",
)
```

## 4.5 关键参数详解

### `context`（任务上下文）

前一个任务的输出作为后一个任务的上下文。这是**顺序执行的核心机制**：

```python
write_task = Task(
    description="基于研究撰写报告",
    expected_output="专业报告",
    agent=writer,
    context=[research_task],  # 将 research_task 的输出注入报告任务
)
```

### `human_input`（人工输入）

```python
task = Task(
    description="...",
    expected_output="...",
    human_input=True,  # 执行前请求人工确认
)
```

### `output_file`（输出到文件）

```python
task = Task(
    description="...",
    expected_output="...",
    output_file="output/report.md",  # 自动将结果写入文件
)
```

### `output_json` / `output_pydantic`（结构化输出）

```python
from pydantic import BaseModel

class ResearchReport(BaseModel):
    title: str
    key_points: list[str]
    summary: str

task = Task(
    description="研究AI最新进展",
    expected_output="结构化JSON报告",
    output_pydantic=ResearchReport,  # 输出为 Pydantic 模型
)
```

### `guardrail`（护栏）

```python
def task_guardrail(result):
    if len(result) < 10:
        return False, "Output too short, please expand."
    return True, result

task = Task(..., guardrail=task_guardrail)
```

### `async_execution`（异步执行）

```python
task = Task(
    description="...",
    expected_output="...",
    async_execution=True,  # 不阻塞后续任务
)
```

### `ConditionalTask`（条件任务）

```jsonc
{
  "name": "conditional_step",
  "type": "ConditionalTask",
  "description": "如果满足条件则执行此任务",
  "expected_output": "...",
  "agent": "writer",
  "condition": "if result.quality > 0.8"
}
```

## 4.6 任务执行流程详解

```
Crew.kickoff()
    │
    ├── Sequential 模式
    │     Task1 ──► Task2 ──► Task3
    │     (输出作  (输出作  (最终输出)
    │      为上下文 为上下文)
    │
    └── Hierarchical 模式
          Manager Agent
          ├── 规划分解任务
          ├── 委派给合适 Agent
          ├── 验证输出
          └── 汇报结果
```

## 关键 API 速查

| 参数 | 用途 | 必填 |
|------|------|------|
| `description` | 任务描述 | ✅ |
| `expected_output` | 期望输出格式 | ✅ |
| `agent` | 执行 Agent | 视配置而定 |
| `context` | 前置任务上下文 | 可选 |
| `output_file` | 输出文件路径 | 可选 |
| `output_json` | 输出 JSON 文件 | 可选 |
| `output_pydantic` | Pydantic 模型输出 | 可选 |
| `tools` | 任务级工具 | 可选 |
| `human_input` | 请求人工确认 | 可选 |
| `async_execution` | 异步执行 | 可选 |

## 下一步

→ [05-Crew团队.md](05-Crew团队.md)：如何把 Agent 和 Task 组织成 Crew 团队。
