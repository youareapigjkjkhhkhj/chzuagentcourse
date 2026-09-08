# 07 - 工具 Tools

本篇目标：理解 CrewAI 的 **工具（Tools）** 系统——Agent 如何获取外部能力（搜索、文件操作、代码执行、协作等）。

## 7.1 什么是 Tool？

**Tool 是 Agent 可以用来执行各种操作的技能或函数**。包括：

- 网页搜索
- 数据分析
- 文件读写
- 代码执行
- 与其他 Agent 协作

工具可以来自 CrewAI Toolkit、LangChain Tools，或自定义开发。

## 7.2 工具的关键特性

| 特性 | 说明 |
|------|------|
| **实用性** | 用于网页搜索、数据分析、内容生成、Agent 协作 |
| **集成性** | 无缝集成到 Agent 工作流 |
| **可定制** | 可自定义或使用现有工具 |
| **错误处理** | 内置健壮的错误处理机制 |
| **缓存机制** | 智能缓存，优化性能，减少冗余操作 |
| **异步支持** | 同步和异步工具均支持 |
| **类型化输出** | 可选 Pydantic 模型，给 Agent 清晰的 JSON 字段 |

## 7.3 安装

```bash
# 安装 CrewAI 扩展工具包
pip install crewai-tools
```

## 7.4 使用内置工具

```python
from crewai_tools import (
    SerperDevTool,        # Google 搜索（需 SERPER_API_KEY）
    ScrapeWebsiteTool,    # 网页内容抓取
    EXASearchTool,        # EXA 搜索
    FileReadTool,         # 文件读取
    FileWriteTool,        # 文件写入
    DirectoryReadTool,    # 目录列表
    MDXSearchTool,        # MDX 搜索
)

agent = Agent(
    role="研究员",
    goal="找到有用的信息",
    backstory="资深分析师",
    tools=[
        SerperDevTool(),
        ScrapeWebsiteTool(),
    ],
)
```

### 单独使用工具

```python
# 直接调用工具
serper_tool = SerperDevTool()
response = serper_tool.run(search_query="AI agents 2026")
print(response)
```

## 7.5 常用内置工具一览

| 工具 | 用途 |
|------|------|
| `SerperDevTool` | Google 搜索引擎（需 API Key） |
| `ScrapeWebsiteTool` | 抓取网页内容 |
| `EXASearchTool` | EXA 搜索 |
| `FileReadTool` | 读取文件 |
| `FileWriteTool` | 写入文件 |
| `DirectoryReadTool` | 列出目录内容 |
| `CodeInterpreterTool` | 执行 Python/Markdown 代码 |
| `DALL-E Tool` | 生成图片 |
| `HumanInputTool` | 获取人工输入 |
| `FirecrawlSearchTool` | Firecrawl 搜索 |
| `FirecrawlCrawlTool` | Firecrawl 爬取 |
| `FirecrawlScrapeTool` | Firecrawl 抓取 |
| `TXTSearchTool` | 文本搜索 |

## 7.6 自定义 Tool

### 方法一：`@tool` 装饰器

```python
from crewai.tools import tool

@tool("Calculator")
def calculator(equation: str) -> str:
    """执行数学计算。
    Args:
        equation: 数学表达式，如 "2*3+4"
    Returns:
        计算结果
    """
    return str(eval(equation))

# 使用
agent = Agent(
    role="计算员",
    goal="准确计算",
    backstory="数学专家",
    tools=[calculator],
)
```

### 方法二：继承 `BaseTool` 类

```python
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

class MyToolInput(BaseModel):
    query: str = Field(description="搜索查询")

class MyCustomTool(BaseTool):
    name: str = "My Custom Tool"
    description: str = "Clear description of what this tool does."
    args_schema: type[BaseModel] = MyToolInput

    def _run(self, query: str) -> str:
        """实际的工具逻辑"""
        # 在这里执行你的业务逻辑
        return f"处理查询: {query}"

my_tool = MyCustomTool()
```

## 7.7 工具的缓存机制

CrewAI 工具默认支持缓存，可有效减少重复请求：

```python
# 使用 cache_function 自定义缓存行为
def my_cache_function(result):
    """决定是否缓存结果"""
    if "error" in result:
        return False
    return True

agent = Agent(
    tools=[MyTool(cache_function=my_cache_function)],
)
```

## 7.8 工具的错误处理

所有工具内置错误处理能力，Agent 能优雅地管理异常并继续任务：

```python
class RobustTool(BaseTool):
    name: str = "RobustTool"
    description: str = "带错误处理的工具"

    def _run(self, arg: str) -> str:
        try:
            # 业务逻辑
            result = do_something(arg)
            return result
        except Exception as e:
            return f"工具执行失败: {str(e)}，已优雅处理。"
```

## 7.9 类型化输出（Typed Output）

使用 Pydantic 模型定义工具的干净 JSON 输出：

```python
from pydantic import BaseModel, Field
from typing import List

class SearchResult(BaseModel):
    title: str = Field(description="搜索结果的标题")
    url: str = Field(description="搜索结果的 URL")
    snippet: str = Field(description="搜索结果的摘要")

class SearchResponse(BaseModel):
    results: List[SearchResult]

class TypedSearchTool(BaseTool):
    name: str = "TypedSearch"
    description: str = "返回结构化搜索结果的工具"

    def _run(self, query: str) -> dict:
        # 实际搜索逻辑
        return SearchResponse(
            results=[SearchResult(title=t, url=u, snippet=s)]
        ).model_dump()
```

Agent 可获得清晰的 JSON 字段，直接 Python 调用仍然得到正常返回值。

## 7.10 工具与协作

CrewAI 工具还包含**协作工具**，允许 Agent 向其他 Agent 委派任务：

```python
# 委派工具示例
from crewai_tools import TaskDelegationTool

researcher = Agent(
    role="研究员",
    goal="完成研究任务",
    backstory="前线分析师",
    tools=[TaskDelegationTool()],  # 允许委派
    allow_delegation=True,          # 必须同时开启委派开关
)
```

## 关键 API 速查

| API | 用途 |
|-----|------|
| `@tool("name")` | 快速创建自定义工具 |
| `class MyTool(BaseTool)` | 创建复杂工具（带类型化输入） |
| `SerperDevTool()` | Google 搜索 |
| `ScrapeWebsiteTool()` | 网页抓取 |
| `FileReadTool()` | 文件读取 |
| `agent.tools=[...]` | 给 Agent 挂载工具 |
| `task.tools=[...]` | 任务级工具覆盖 |

## 下一步

→ [08-记忆Memory.md](08-记忆Memory.md)：让 Agent 记住重要的交互信息。
