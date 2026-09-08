# 12 - Flows 工作流

本篇目标：掌握 **Flows**——CrewAI 的事件驱动工作流引擎。Flows 是 AI 应用的"骨架"，负责管理状态、控制执行顺序、编排多个 Crew。

## 12.1 什么是 Flows？

**CrewAI Flows** 简化 AI 工作流的创建和管理。Flows 允许开发者：

- **组合多个 Crew 和任务**，构建复杂自动化
- **简化工作流创建**：轻松链式串联多个 Crew 和任务
- **状态管理**：在不同任务之间管理和共享状态
- **事件驱动架构**：基于事件模型构建动态响应式工作流
- **灵活控制流**：实现条件逻辑、循环和分支

## 12.2 核心概念

```
Flow = 事件驱动 + 状态管理 + 方法编排
```

- **Flow 实例**：每个 Flow 实例自动获得唯一 UUID 标识（在 state 中）
- **状态**：贯穿整个 Flow 执行的数据存储
- **装饰器**：`@start()`、`@listen()`、`@router()` 控制方法触发

## 12.3 快速入门：第一个 Flow

```python
from crewai.flow import Flow, listen, start
from pydantic import BaseModel

class MyFlowState(BaseModel):
    city: str = ""
    fun_fact: str = ""

class CityFunFactFlow(Flow[MyFlowState]):

    @start()
    def generate_city(self):
        print("Step 1: Generating a city...")
        self.state.city = "Tokyo, Japan"
        return self.state.city

    @listen(generate_city)
    def generate_fun_fact(self, city):
        print(f"Step 2: Generating fun fact about {city}...")
        self.state.fun_fact = f"A fun fact about {city}: It has 14 million residents."
        return self.state.fun_fact

# 运行
flow = CityFunFactFlow()
flow.kickoff()
```

执行过程：
1. `generate_city` 是起点（`@start()`）
2. `generate_fun_fact` 监听 `generate_city` 的输出
3. 状态在 Flow 实例中自动持久化（唯一 UUID 在 state 中）

## 12.4 核心装饰器

### `@start()` — 起始步骤

```python
@start()
def first_step(self):
    self.state.data = "初始化数据"
    return self.state.data
```

一个 Flow 可以有多个 `@start()` 方法（并行起始）。

### `@listen()` — 监听步骤

```python
# 监听指定方法
@listen(first_step)
def second_step(self, result):
    print(f"收到: {result}")
    return "processed"

# 监听多个方法
@listen(first_step, another_start)
def combined_step(self, results):
    # results 是多方法输出的元组
    print(results)
    return "done"
```

### `@router()` — 条件路由

```python
from crewai.flow import router

@router(previous_step)
def route_by_result(self, result):
    if "error" in result:
        return "handle_error"
    elif "success" in result:
        return "handle_success"
    else:
        return "default"

# 路由到不同方法（不需要 @listen 的自动触发）
@listen("handle_error")
def error_handler(self, result):
    print(f"处理错误: {result}")

@listen("handle_success")
def success_handler(self, result):
    print(f"处理成功: {result}")
```

## 12.5 状态管理

Flow 使用 Pydantic BaseModel 定义状态：

```python
from pydantic import BaseModel
from typing import List, Dict, Any

class ResearchFlowState(BaseModel):
    topic: str = ""
    sources: List[str] = []
    findings: Dict[str, Any] = {}
    report: str = ""
    status: str = "pending"
```

状态贯穿整个 Flow，可以在任何方法中读写：

```python
class ResearchFlow(Flow[ResearchFlowState]):

    @start()
    def gather_sources(self):
        self.state.topic = "AI Agents"
        self.state.sources = ["source1.com", "source2.com"]
        return self.state.sources

    @listen(gather_sources)
    def analyze(self, sources):
        # 读取状态
        print(self.state.topic)
        # 更新状态
        self.state.status = "analyzing"
        self.state.findings = {"key": "value"}
        return "analysis done"
```

## 12.6 在 Flow 中调用 Crew

Flow 最常见的用途就是协调多个 Crew：

```python
from crewai.flow import Flow, start, listen
from crewai import Crew, Agent, Task
from pydantic import BaseModel

class ContentFlowState(BaseModel):
    topic: str = ""
    research_output: str = ""
    article: str = ""

class ContentFlow(Flow[ContentFlowState]):

    @start()
    def set_topic(self):
        self.state.topic = "AI 在医疗中的应用"
        return self.state.topic

    @listen(set_topic)
    def research_crew(self, topic):
        researcher = Agent(
            role="研究员",
            goal=f"研究 {topic} 的最新进展",
            backstory="资深医疗AI分析师",
        )
        research_task = Task(
            description=f"研究 {topic}",
            expected_output="5个关键发现",
            agent=researcher,
        )
        crew = Crew(
            agents=[researcher],
            tasks=[research_task],
        )
        self.state.research_output = crew.kickoff().raw
        return self.state.research_output

    @listen(research_crew)
    def write_crew(self, research):
        writer = Agent(
            role="作家",
            goal="撰写专业文章",
            backstory="资深技术作家",
        )
        write_task = Task(
            description=f"基于以下研究写文章，研究内容：{research}",
            expected_output="一篇300字专业文章",
            agent=writer,
        )
        crew = Crew(
            agents=[writer],
            tasks=[write_task],
        )
        self.state.article = crew.kickoff().raw
        return self.state.article
```

## 12.7 高级功能

### 条件逻辑（router）

```python
@router(process_data)
def decide_next(self, data):
    quality = analyze_quality(data)
    if quality > 0.8:
        return "high_quality"
    return "needs_review"
```

### 循环

```python
class LoopFlow(Flow):
    iteration = 0

    @start()
    def begin(self):
        return "start"

    @listen(begin)
    def step_loop(self, _):
        self.iteration += 1
        if self.iteration < 5:
            # 自己监听自己实现循环
            return self.step_loop(_)
        return "loop done"
```

### 路由 + 条件（完整模式）

```python
from crewai.flow import Flow, router, start, listen
from pydantic import BaseModel

class ECommerceFlowState(BaseModel):
    order_id: str = ""
    order_status: str = ""

class ECommerceFlow(Flow[ECommerceFlowState]):

    @start()
    def create_order(self):
        self.state.order_id = "ORD-2026-001"
        return self.state.order_id

    @listen(create_order)
    def validate_order(self, order_id):
        # 模拟验证
        self.state.order_status = "valid"
        return "valid"  # 或 "invalid"

    @router(validate_order)
    def route_by_status(self, _):
        if self.state.order_status == "valid":
            return "process_payment"
        return "reject_order"

    # 分支路径（不依赖 @listen 自动触发）
    # ...实际用 @listen 处理
```

## 12.8 与 Crew 的区别

| 维度 | Flows | Crews |
|------|-------|-------|
| 定位 | 工作流骨架 | 工作单元 |
| 控制 | 精确、事件驱动 | 自治、协作 |
| 状态 | 明确管理 | 隐式传递 |
| 执行顺序 | 开发者控制 | Agent/Manager 编排 |
| 适用 | 复杂多步骤 AI 应用 | 单个多智能体任务 |

> 最佳实践：**两者都用**。Flow 决定顺序，Crew 内的 Agent 做具体工作。

## 关键 API 速查

| API | 用途 |
|-----|------|
| `class MyFlow(Flow[StateModel])` | 定义 Flow |
| `@start()` | 起始步骤 |
| `@listen(method)` | 监听上一步输出 |
| `@router(method)` | 条件路由 |
| `flow.kickoff()` | 启动 Flow |
| `self.state.xxx` | 读写状态 |
| `self.remember()` / `self.recall()` | Flow 内置记忆 |

## 下一步

→ [13-LLM配置.md](13-LLM配置.md)：配置不同类型的 LLM 提供商。
