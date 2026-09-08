# 13 - LLM 配置

本篇目标：掌握 CrewAI 中 **LLM（大语言模型）** 的配置方法——如何接入不同提供商、设置环境变量、使用流式输出。

## 13.1 什么是 LLM？

**LLM 是 CrewAI Agent 的核心智能**。它们使 Agent 能够：
- 理解上下文
- 做决策
- 生成类人响应

## 13.2 配置 LLM 的三种方式

### 方式一：环境变量（最简单）

在 `.env` 文件或环境中设置：

```env
OPENAI_API_KEY=sk-xxx
```

CrewAI 默认使用 OpenAI 的 **gpt-4o-mini**（或在 `crewai create` 时配置）。

### 方式二：通过 LLM 类（推荐）

```python
from crewai import LLM

llm = LLM(
    model="gpt-4o",
    temperature=0.7,
    max_tokens=4096,
)

agent = Agent(
    role="研究员",
    goal="研究最新AI",
    backstory="资深分析师",
    llm=llm,
)
```

### 方式三：直接字符串

```python
agent = Agent(
    role="研究员",
    goal="研究最新AI",
    backstory="资深分析师",
    llm="openai/gpt-4o",       # 格式：提供商/模型
)
```

## 13.3 多提供商配置

CrewAI 通过提供商的**原生 SDK** 集成，支持多种模型提供商：

| 提供商 | 格式 | 环境变量 | 示例模型 |
|--------|------|----------|----------|
| OpenAI | `openai/gpt-4o` | `OPENAI_API_KEY` | gpt-4o, gpt-4o-mini |
| Anthropic | `anthropic/claude-3-5-sonnet` | `ANTHROPIC_API_KEY` | claude-3-5-sonnet |
| Google Gemini | `gemini/gemini-1.5-pro` | `GEMINI_API_KEY` | gemini-1.5-pro |
| DeepSeek | `deepseek/deepseek-chat` | `DEEPSEEK_API_KEY` | deepseek-chat |
| Azure OpenAI | `azure/gpt-4o` | `AZURE_OPENAI_API_KEY` | 自定义 |
| AWS Bedrock | `bedrock/...` | 凭证链 | Claude 等 |
| Ollama（本地） | `ollama/llama3.1:8b` | 无 | llama3.1 |

### 常见提供商示例

```python
# OpenAI
openai_llm = LLM(model="gpt-4o")

# Anthropic Claude
claude_llm = LLM(
    model="anthropic/claude-3-5-sonnet-20241022",
    temperature=0.3,
)

# Google Gemini
gemini_llm = LLM(
    model="gemini/gemini-1.5-pro",
    api_key="GEMINI_API_KEY",  # 或从环境读取
)

# DeepSeek（中文场景常用）
deepseek_llm = LLM(
    model="deepseek/deepseek-chat",
    api_key="sk-deepseek-xxx",
)

# Ollama（本地推理）
ollama_llm = LLM(
    model="ollama/llama3.1:8b",
    base_url="http://localhost:11434",
)
```

## 13.4 Agent 与 Crew 的不同 LLM

```python
# 不同 Agent 用不同 LLM
researcher = Agent(
    role="研究员",
    goal="搜索资料",
    backstory="资深分析师",
    llm="openai/gpt-4o",          # 强大模型做复杂分析
)

writer = Agent(
    role="作家",
    goal="撰写内容",
    backstory="内容创作者",
    llm="openai/gpt-4o-mini",     # 轻量模型节省成本
)

# Crew 使用同一 LLM
crew = Crew(
    agents=[researcher, writer],
    tasks=[...],
    manager_llm="openai/gpt-4o",   # 层级模式 Manager 的 LLM
    function_calling_llm="openai/gpt-4o-mini",  # 工具调用专用轻量模型
)
```

## 13.5 LLM 参数详解

```python
llm = LLM(
    # 基本
    model="gpt-4o",                    # 模型 ID
    api_key="sk-xxx",                  # API 密钥（默认读环境变量）
    base_url="https://api.openai.com", # 自定义端点
    
    # 生成参数
    temperature=0.7,                   # 随机性（0-1）
    top_p=0.9,                         # 核采样
    max_tokens=4096,                   # 最大生成 token
    timeout=120,                       # 超时（秒）
    max_retries=3,                     # 重试次数
    
    # 高级
    seed=None,                         # 随机种子
    frequency_penalty=0.0,             # 频率惩罚
    presence_penalty=0.0,              # 存在惩罚
    stop=None,                         # 停止词列表
    stream=False,                      # 流式输出
)
```

## 13.6 函数调用 LLM（Function Calling LLM）

**`function_calling_llm`** 是 Agent 用于工具调用的专用 LLM：

```python
agent = Agent(
    role="数据分析师",
    goal="分析并回复数据查询",
    backstory="数据分析专家",
    llm="openai/gpt-4o",
    function_calling_llm="openai/gpt-4o-mini",  # 轻量模型做工具调用，降低成本
)
```

当 Agent 需要调用工具时，会使用 `function_calling_llm` 进行工具选择。若未指定，默认使用 Agent 的 `llm`。

## 13.7 流式输出（Streaming）

CrewAI 支持从 LLM **流式输出响应**，实时接收生成内容：

```python
from crewai import LLM

# 启用流式
streaming_llm = LLM(
    model="gpt-4o",
    stream=True,
)

agent = Agent(
    role="写作助手",
    goal="实时输出文章",
    backstory="高效写作助手",
    llm=streaming_llm,
)
```

启用后，响应按 chunk 传递，提供更响应式的用户体验。

### Crew 级流式

```python
crew = Crew(
    agents=[agent],
    tasks=[task],
    stream=True,   # Crew 级流式输出
)
```

### Flow 级流式

```python
class StreamingFlow(Flow):
    @start()
    def generate(self):
        # 通过 crew.kickoff 触发流式
        for chunk in self.crew_instance.kickoff_stream():
            yield chunk
```

### 流式事件

CrewAI 为流式输出中的每个 chunk 发出事件。所有 LLM 事件**包含 Agent 和 Task 信息**，允许你跟踪和过滤：

```python
# 事件中包含:
# - 当前 Agent
# - 当前 Task
# - LLM 生成的 chunk
```

## 关键 API 速查

| API | 用途 |
|-----|------|
| `LLM(model=..., temperature=...)` | 创建 LLM 实例 |
| `"openai/gpt-4o"` | 字符串格式指定模型 |
| `llm=llm_obj` | Agent 指定 LLM |
| `manager_llm` | 层级模式的 Manager LLM |
| `function_calling_llm` | 工具调用专用 LLM |
| `LLM(model=..., stream=True)` | 启用流式 |
| `Crew(stream=True)` | Crew 级流式输出 |

## 下一步

→ [14-CLI命令行.md](14-CLI命令行.md)：掌握 CrewAI CLI 的全部命令。
