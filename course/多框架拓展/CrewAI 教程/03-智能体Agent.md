# 03 - 智能体 Agent

本篇目标：深入理解 CrewAI 中的 **Agent**——自主 AI 单元的核心概念、全部属性、多种创建方式及常见使用模式。

## 3.1 什么是 Agent？

在 CrewAI 中，**Agent 是自主工作单元**，能够：

- 执行特定任务
- 基于角色和目标做决策
- 使用工具完成任务
- 与其他 Agent 沟通协作
- 维持交互记忆
- 允许时委派任务给其他 Agent

## 3.2 Agent 的全部属性

```python
from crewai import Agent

agent = Agent(
    # === 必填：定义 Agent 人格 ===
    role="高级数据分析师",              # 角色
    goal="准确分析数据并给出洞察",       # 目标
    backstory="你是一位有十年经验的数据专家",  # 背景故事

    # === 模型相关（可选）===
    llm="openai/gpt-4o",              # 主 LLM
    function_calling_llm=None,        # 工具调用的专用 LLM

    # === 工具相关 ===
    tools=[],                          # 工具列表
    allow_delegation=False,            # 是否允许委派任务

    # === 记忆与缓存 ===
    memory=True,                       # 是否启用记忆
    cache=True,                        # 是否启用缓存

    # === 行为控制 ===
    verbose=True,                      # 是否输出详细日志
    max_iter=25,                       # 最大迭代次数
    max_rpm=None,                      # 每分钟最大请求数
    max_execution_time=None,           # 最大执行时间（秒）
    use_system_prompt=True,            # 是否使用系统提示词

    # === 安全与守卫 ===
    guardrail=None,                    # 回应护栏（防止异常输出）

    # === 回调 ===
    step_callback=None,                # 每一步完成回调

    # === 规划配置 ===
    planning_config=None,              # 规划 LLM 配置

    # === 能力开关 ===
    respect_context_window=True,       # 是否尊重上下文窗口
    code_execution_mode="safe",        # 代码执行模式："safe"/"unsafe"/"disabled"
    embedder=None,                     # 自定义 Embedder 配置
)
```

## 3.3 创建 Agent 的三种方式

### 方式一：JSONC 配置（推荐）

创建 `agents/researcher.jsonc`：

```jsonc
{
  "name": "researcher",
  "role": "Senior Research Analyst",
  "goal": "Conduct in-depth research on latest AI developments",
  "backstory": "You are a lead analyst at a top tech research firm.",
  "tools": ["serper_dev_tool"],
  "verbose": true,
  "allow_delegation": false,
  "memory": true,
  "settings": {
    "max_iter": 10,
    "max_rpm": 30
  }
}
```

然后在 `crew.jsonc` 中引用：

```jsonc
{
  "agents": ["researcher"],
  ...
}
```

### 方式二：经典 YAML（--classic）

在 `config/agents.yaml` 中定义：

```yaml
researcher:
  role: "高级研究分析师"
  goal: "深入研究 AI 最新进展"
  backstory: "你是顶尖科技研究公司的首席分析师"
  tools:
    - serper_dev_tool
  verbose: true
  allow_delegation: false
```

配合 `crew.py` 中的 `@CrewBase` 装饰器：

```python
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

@CrewBase
class MyCrew:
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def researcher(self) -> Agent:
        return Agent(
            config=self.agents_config["researcher"],
            verbose=True,
            tools=[SerperDevTool()],
        )
```

### 方式三：直接代码定义

```python
from crewai import Agent

researcher = Agent(
    role="Senior Research Analyst",
    goal="Uncover cutting-edge developments in AI",
    backstory="You are a lead analyst at a top tech research firm.",
    verbose=True,
    tools=[SerperDevTool()],
)
```

## 3.4 关键参数详解

### `role`（角色）

Agent 的身份定位，影响 prompt 构建和任务执行风格。
例：`"客服专员"`、`"Python 开发者"`、`"财务分析师"`。

### `goal`（目标）

Agent 要达成的核心目标，用于引导决策。
例：`"解决用户的每个技术问题"`。

### `backstory`（背景故事）

给 Agent 一个丰富的人设设定，让输出更自然。
例：`"你曾在微软担任高级架构师，精通分布式系统设计"`。

### `llm`（大语言模型）

指定 Agent 使用的 AI 模型。支持多种格式：

```python
# 字符串格式
llm="openai/gpt-4o"
llm="anthropic/claude-3-5-sonnet-20241022"
llm="gemini/gemini-1.5-pro"

# LLM 对象格式
from crewai import LLM
llm=LLM(model="gpt-4o", temperature=0.7)
```

### `allow_delegation`（允许委派）

Agent 能否将子任务委派给团队中其他 Agent：

```python
Agent(..., allow_delegation=True)  # 可以委派
Agent(..., allow_delegation=False) # 不能委派（默认）
```

### `verbose`（详细模式）

```python
Agent(..., verbose=True)  # 输出每一步的详细日志
```

### `guardrail`（护栏）

防止 Agent 输出异常或越界内容：

```python
def guardrail_output(result):
    # 检查结果并返回 (bool, modified_result)
    if "sensitive" in result:
        return False, result  # (is_valid, corrected_output)
    return True, result

Agent(..., guardrail=guardrail_output)
```

## 3.5 Agent Capabilities（Agent 能力）

CrewAI Agent 支持多种内置能力（Agent Capabilities）：

- **工具调用**：通过 `tools` 使用外部功能
- **委派**：`allow_delegation=True` 时向其他 Agent 分派任务
- **代码执行**：通过 `code_execution_mode` 控制代码运行（safe/unsafe/disabled）
- **多模态输入**：通过 files 参数接受图片、PDF、音频等
- **记忆**：`memory=True` 保留历史交互
- **规划**：配合 Crew 的 `planning=True` 获得逐步规划能力

## 3.6 常见使用模式

### 基础研究 Agent

```python
research_agent = Agent(
    role="Research Analyst",
    goal="Find comprehensive information on {topic}",
    backstory="You are a thorough researcher known for detailed analysis.",
    tools=[SerperDevTool()],
    verbose=True,
)
```

### 代码开发 Agent

```python
developer = Agent(
    role="Senior Python Developer",
    goal="Write production-ready, well-tested Python code",
    backstory="You are an expert Python engineer who writes clean, maintainable code.",
    tools=[FileWriteTool(), CodeInterpreterTool()],
    code_execution_mode="safe",
    allow_delegation=False,
)
```

### 标注 LLM 参数嵌套在 settings 中

JSONC 方式支持将行为参数放入 `settings`（优先于顶层）：

```jsonc
{
  "name": "writer",
  "role": "技术作家",
  "goal": "写出清晰易懂的技术文档",
  "backstory": "资深技术写作专家",
  "settings": {
    "verbose": true,
    "max_iter": 5,
    "max_rpm": 20,
    "memory": true,
    "allow_delegation": false
  }
}
```

## 关键 API 速查

| 参数 | 用途 |
|------|------|
| `role` | 必填，Agent 角色 |
| `goal` | 必填，Agent 目标 |
| `backstory` | 必填，Agent 人格背景 |
| `llm` | 模型（默认 gpt-4o） |
| `tools` | 工具列表 |
| `allow_delegation` | 是否允许委派任务 |
| `max_iter` | 最大迭代数（防死循环） |
| `max_rpm` | 每分钟最大请求数（限流） |
| `verbose` | 详细日志 |
| `memory` | 是否启用记忆 |
| `guardrail` | 检查输出合法性 |

## 下一步

→ [04-任务Task.md](04-任务Task.md)：了解 Agent 执行的"任务"单元。
