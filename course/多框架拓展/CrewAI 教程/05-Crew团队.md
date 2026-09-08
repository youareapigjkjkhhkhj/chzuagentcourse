# 05 - Crew 团队

本篇目标：理解 **Crew**——CrewAI 中最核心的协作单元，是将多个 Agent 组织和编排起来完成一组任务的方式。

## 5.1 什么是 Crew？

**Crew 是协作式 Agent 团队**，共同完成一组任务。每个 Crew 定义：

- 任务执行策略
- Agent 协作方式
- 整体工作流

**一句话**：Agent 是"员工"，Task 是"工作"，Crew 是"团队和组织方式"。

## 5.2 Crew 属性

```python
from crewai import Crew

crew = Crew(
    # === 必填 ===
    agents=[agent1, agent2],           # Agent 列表
    tasks=[task1, task2],              # Task 列表

    # === 执行策略 ===
    process="sequential",               # "sequential" 或 "hierarchical"
    manager_llm="openai/gpt-4o",       # 层级模式下 Manager 的 LLM
    manager_agent=manager_agent,       # 或使用自定义 Manager Agent

    # === 行为控制 ===
    verbose=True,                       # 详细日志
    memory=True,                        # 启用记忆
    cache=True,                         # 启用缓存
    max_rpm=100,                        # 每分钟最大请求数

    # === 规划 ===
    planning=True,                     # 启用规划
    planning_llm="openai/gpt-4o",      # 规划 LLM

    # === 其他 ===
    function_calling_llm=None,          # 工具调用 LLM
    output_log_file="output.log",      # 日志文件
    stream=False,                       # 流式输出
    before_kickoff_callbacks=[],       # kickoff 前回调
    after_kickoff_callbacks=[],        # kickoff 后回调
)
```

## 5.3 创建 Crew 的三种方式

### 方式一：JSONC 配置（推荐）

创建 `crew.jsonc`：

```jsonc
{
  "agents": ["researcher", "writer"],
  "tasks": [
    {
      "name": "research",
      "description": "研究 {topic} 的最新进展",
      "expected_output": "5点摘要",
      "agent": "researcher"
    },
    {
      "name": "write",
      "description": "撰写报告",
      "expected_output": "完整报告",
      "agent": "writer",
      "context": ["research"]
    }
  ],
  "process": "sequential",
  "verbose": true,
  "memory": true,
  "cache": true,
  "planning": false,
  "max_rpm": 100,
  "output_log_file": "logs/crew.log"
}
```

运行：

```bash
crewai run
```

`crewai run` 自动检测 `crew.jsonc`，加载引用的 Agent 文件，提示缺失的占位值，然后启动。

**层级模式配置**：

```jsonc
{
  "agents": ["researcher", "writer", "manager"],
  "tasks": [...],
  "process": "hierarchical",
  "manager_llm": "openai/gpt-4o",
  // 或
  "manager_agent": "manager"
}
```

> `manager_agent` 可以引用 `agents/manager.jsonc`，且该文件**不必**列在顶层 `agents` 数组中。

**Python 回调与自定义类**使用：

```jsonc
{
  "before_kickoff_callbacks": [
    {"python": "my_module.my_callback"}
  ]
}
```

**自定义工具**：

```jsonc
{
  "tools": ["custom:my_tool"]
  // 运行时加载 tools/my_tool.py
}
```

### 方式二：经典 YAML + Decorator

`crew.py`：

```python
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

@CrewBase
class ContentCrew:
    """内容创作团队"""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def researcher(self) -> Agent:
        return Agent(
            config=self.agents_config["researcher"],
            verbose=True,
            tools=[SerperDevTool()],
        )

    @agent
    def writer(self) -> Agent:
        return Agent(
            config=self.agents_config["writer"],
            verbose=True,
        )

    @task
    def research(self) -> Task:
        return Task(
            config=self.tasks_config["research"],
        )

    @task
    def write(self) -> Task:
        return Task(
            config=self.tasks_config["write"],
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )
```

### 方式三：直接代码定义

```python
from crewai import Agent, Crew, Task

researcher = Agent(
    role="研究员",
    goal="搜索最新AI技术",
    backstory="资深分析师",
    tools=[SerperDevTool()],
)
writer = Agent(
    role="作家",
    goal="撰写清晰报告",
    backstory="资深技术写作专家",
)

research_task = Task(
    description="研究AI最新进展",
    expected_output="5点摘要",
    agent=researcher,
)
write_task = Task(
    description="撰写报告",
    expected_output="完整报告",
    agent=writer,
    context=[research_task],
)

crew = Crew(
    agents=[researcher, writer],
    tasks=[research_task, write_task],
    process="sequential",
    verbose=True,
)

# 执行
result = crew.kickoff()
print(result)
```

## 5.4 Crew 的执行方法

### `kickoff()` — 启动

```python
# 基础使用
result = crew.kickoff()

# 带输入参数（填充模板中的变量）
result = crew.kickoff(inputs={
    "topic": "多模态AI",
    "deadline": "2026年9月"
})
```

### `kickoff_for_each()` — 批量

为每个输入项执行一次 Crew：

```python
results = crew.kickoff_for_each(
    inputs=[
        {"topic": "Transformer"},
        {"topic": "MoE"},
        {"topic": "RAG"},
    ]
)
```

### `replay()` — 重放

从特定任务重新执行：

```python
crew.replay(task_id="research_ai")
```

### `train()` — 训练

```python
crew.train(
    n_iterations=5,
    filename="trained_agents_data.pkl",
    inputs={"topic": "AI"},
)
```

## 5.5 完整示例：内容创作团队

```python
from crewai import Agent, Crew, Task, Process

# --- Agents ---
researcher = Agent(
    role="Research Analyst",
    goal="Find the latest developments in {topic}",
    backstory="A meticulous analyst with deep industry knowledge.",
    tools=[SerperDevTool()],
    verbose=True,
)

content_writer = Agent(
    role="Content Strategist",
    goal="Transform research into engaging content",
    backstory="A creative writer who excels at making complex topics accessible.",
    verbose=True,
)

editor = Agent(
    role="Senior Editor",
    goal="Review and polish the final content",
    backstory="An experienced editor with an eye for quality and accuracy.",
    verbose=True,
)

# --- Tasks ---
research_task = Task(
    description=f"Research latest developments in {{topic}}",
    expected_output="A comprehensive summary with 5 key points.",
    agent=researcher,
)

write_task = Task(
    description="Write a compelling article based on the research",
    expected_output="An engaging 1000-word article.",
    agent=content_writer,
    context=[research_task],
)

edit_task = Task(
    description="Review and polish the article for publication",
    expected_output="A publication-ready article with no errors.",
    agent=editor,
    context=[write_task],
)

# --- Crew ---
content_crew = Crew(
    agents=[researcher, content_writer, editor],
    tasks=[research_task, write_task, edit_task],
    process=Process.sequential,
    verbose=True,
)

# --- Run ---
result = content_crew.kickoff(inputs={"topic": "AGI"})
```

## 5.6 Crew 级别的高级设置

| 属性 | 用途 |
|------|------|
| `process` | 顺序 / 层级执行 |
| `manager_llm` | 层级模式的 Manager LLM |
| `manager_agent` | 自定义 Manager Agent |
| `planning` | 启用 AgentPlanner |
| `planning_llm` | 规划用的 LLM |
| `memory` | Crew 级共享记忆 |
| `cache` | 结果缓存（跨运行） |
| `verbose` | 详细日志 |
| `max_rpm` | 限流 |
| `output_log_file` | 日志文件 |
| `stream` | 流式输出 |
| `function_calling_llm` | 工具调用专用 LLM |
| `before/after_kickoff_callbacks` | 生命周期回调 |

## 下一步

→ [06-流程Process.md](06-流程Process.md)：深入理解顺序 vs 层级两种执行策略。
