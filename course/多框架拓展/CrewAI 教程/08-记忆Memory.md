# 08 - 记忆 Memory

本篇目标：理解 CrewAI 统一的 **Memory（记忆）系统**——如何让 Agent 跨任务记住关键信息，以及四种使用方式、层次化作用域。

## 8.1 概述

CrewAI 提供统一的记忆系统——**单个 `Memory` 类**取代了以前的短期记忆、长期记忆、实体记忆和外部记忆，提供简洁智能的 API。

**核心能力**：
- 使用 LLM 在保存时分析内容（推断作用域、类别和重要性）
- 支持**自适应深度召回**，综合评分融合语义相似度、近期度和重要性
- 可在四种场景中使用：独立脚本、Crew、Agent、Flows

## 8.2 快速开始

```python
from crewai.memory import Memory

# 创建记忆实例
memory = Memory()

# 保存内容（LLM 自动分析作用域、类别和重要性）
memory.save(
    content="团队决定使用 Python 构建这个项目",
    metadata={"type": "decision"}
)

# 召回内容（自适应深度召回）
results = memory.recall(
    query="我们选择哪种语言？",
    n=3
)

# 提取记忆（获取原始事实列表）
facts = memory.extract_memories()
```

## 8.3 四种使用方式

### 方式一：独立使用（Standalone）

在脚本、Notebook、CLI 工具中作为独立知识库使用——无需 Agent 或 Crew：

```python
from crewai.memory import Memory

memory = Memory()

memory.save("Python 3.12 是当前稳定版本")
memory.save("CrewAI 是开源框架")

results = memory.recall("最新的 Python 版本是多少？")
print(results)
```

### 方式二：配合 Crew

在 Crew 中使用共享记忆：

```python
from crewai import Crew, Agent, Task

crew = Crew(
    agents=[agent1, agent2],
    tasks=[task1, task2],
    memory=True,  # 启用默认记忆
    # 或传入自定义 Memory 实例：
    # memory=Memory()
)
```

当 `memory=True` 时：
- Crew 创建默认 `Memory()` 并自动传递 embedding 配置
- 所有 Agent **共享** Crew 的记忆（除非 Agent 自己有单独的）
- 无自定义 Embedder 时使用 OpenAI `text-embedding-3-large` 嵌入

**执行时自动行为**：
- **每个任务后**：自动从任务输出中提取离散事实并存储
- **每个任务前**：Agent 从记忆召回相关上下文并注入任务 prompt

### 方式三：配合 Agent（作用域视图）

Agent 可以使用 Crew 的共享记忆（默认），或接收**作用域视图**获得私人上下文：

```python
from crewai import Agent, Crew, Task
from crewai.memory import Memory

# 共享记忆
researcher = Agent(
    role="研究员",
    goal="收集信息",
    backstory="数据分析专家",
    memory=True,  # 使用 Crew 的共享记忆
)

# 私有记忆（作用域隔离）
writer = Agent(
    role="作家",
    goal="撰写报告",
    backstory="技术写作专家",
    memory=True,
    # 每个 Agent 可以有自己的专用 Memory 实例
)
```

典型模式：**研究员**将发现存入私有记忆，**作家**从共享 Crew 记忆读取：

```python
crew = Crew(
    agents=[researcher, writer],
    tasks=[research_task, write_task],
    memory=True,
)

# 结果：
# - researcher 的研究发现存入共享记忆
# - writer 从共享记忆读取上下文
# - 各自的任务输出不会污染对方的私人记忆（如果有）
```

### 方式四：配合 Flow

每个 Flow 内置记忆支持。使用 `self.remember()`、`self.recall()`、`self.extract_memories()`：

```python
from crewai.flow import Flow, start, listen

class MyFlow(Flow):

    @start()
    def step1(self):
        self.remember(
            "用户偏好使用简洁风格",
            metadata={"source": "conversation"}
        )
        return "step1 done"

    @listen(step1)
    def step2(self):
        # 在 flow 的任何方法中回忆
        memories = self.recall("用户偏好")
        print(memories)
        return "step2 done"

    @listen(step2)
    def step3(self):
        facts = self.extract_memories()
        return facts
```

## 8.4 层次化作用域（Hierarchical Scopes）

### 什么是 Scope？

**记忆按层次化树组织，类似文件系统**。每个作用域是一个路径：

- `/`（根）
- `/project/alpha`
- `/agent/researcher/findings`

### 作用域的作用

**上下文相关记忆**——在某个作用域内召回时，只搜索该分支，提高精度和性能：

```python
# 在某作用域内保存
memory.save(
    "研究结论",
    scopes=["/project/alpha/research"]
)

# 在同一作用域召回
results = memory.recall(
    "结论是什么？",
    scopes=["/project/alpha/research"]
)
```

### 如何推断作用域

保存内容时，Memory 使用 LLM 自动推断适当的作用域、类别和重要性，也可以手动指定。

## 8.5 Embedding 配置

```python
from crewai.memory import Memory

# 自定义 Embedder
memory = Memory(
    embedder={
        "provider": "openai",
        "model": "text-embedding-3-small",
        "config": {"api_key": "sk-xxx"},
    }
)

# 或使用 crew 配置
crew = Crew(
    memory=Memory(),
    embedder={
        "provider": "openai",
        "model": "text-embedding-3-large",
    },
)
```

## 8.6 与 Agent 的 Guardrail 结合

当 Agent 使用 `guardrail` 时，记忆保存会在护栏通过后自动进行，避免存储无效信息。

## 关键 API 速查

| API | 用途 |
|-----|------|
| `Memory()` | 创建统一记忆实例 |
| `memory.save(content, metadata, scopes)` | 保存内容 |
| `memory.recall(query, n)` | 自适应深度召回 |
| `memory.extract_memories()` | 获取提取的原始事实 |
| `Crew(memory=True)` | Crew 级共享记忆 |
| `Agent(memory=True)` | Agent 级记忆 |
| `self.remember()` / `self.recall()` | Flow 内置记忆 |
| `scopes=["/project/alpha"]` | 作用域隔离 |

## 下一步

→ [09-知识Knowledge.md](09-知识Knowledge.md)：给 Agent 挂载外部知识源（RAG）。
