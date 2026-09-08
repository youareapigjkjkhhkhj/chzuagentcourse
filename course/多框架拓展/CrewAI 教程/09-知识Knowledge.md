# 09 - 知识 Knowledge

本篇目标：理解 CrewAI 的 **Knowledge（知识）系统**——如何让 AI Agent 在任务中访问和利用外部信息源，如同给 Agent 一个"参考图书馆"。

## 9.1 什么是 Knowledge？

**Knowledge 是 CrewAI 强大的外部信息接入系统**，允许 Agent 在执行任务时查询和使用外部数据源。

可以把 Knowledge 想象成：**给 Agent 配一本可随时查阅的百科全书**。

## 9.2 支持的 Knowledge 来源

CrewAI 内置支持以下知识源：

| 类型 | 使用方式 |
|------|----------|
| 文本文件 | `TextFileKnowledgeSource` |
| PDF | `PDFKnowledgeSource` |
| CSV | `CSVKnowledgeSource` |
| Excel | `ExcelKnowledgeSource` |
| JSON | `JSONKnowledgeSource` |
| 字符串 | 直接传入字符串文本 |

## 9.3 快速开始

### 基本字符串知识

```python
from crewai import Agent
from crewai.knowledge.source.string_knowledge_source import StringKnowledgeSource

content = "关键概念：CrewAI 是一个多智能体协作框架。"

knowledge_source = StringKnowledgeSource(
    content=content,
    metadata={"description": "CrewAI 概念介绍"}
)

agent = Agent(
    role="CrewAI 专家",
    goal="回答关于 CrewAI 的问题",
    backstory="你是一个 CrewAI 资深专家",
    knowledge={"sources": [knowledge_source]},
)
```

### 文件知识（PDF）

```python
from crewai.knowledge.source.pdf_knowledge_source import PDFKnowledgeSource

pdf_source = PDFKnowledgeSource(
    file_path="knowledge/crewai_guide.pdf",
    chunk_size=1000,        # 分块大小（可选）
    chunk_overlap=200,      # 分块重叠（可选）
)

agent = Agent(
    role="文档助手",
    goal="回答关于文档内容的问题",
    backstory="文档解析专家",
    knowledge={"sources": [pdf_source]},
)
```

### 网页内容知识

```python
from crewai.knowledge.source.string_knowledge_source import StringKnowledgeSource

web_content = """
从网页抓取的内容...
"""

source = StringKnowledgeSource(
    content=web_content,
    metadata={"source": "example.com"}
)
```

## 9.4 Vector Store（RAG 客户端配置）

CrewAI 暴露了**供应商中立的 RAG 客户端抽象**，用于向量存储：

**支持的 Vector Store**：ChromaDB（默认）、Qdrant

```python
# 更换为 Qdrant
from crewai.utilities import set_embeddings_provider

config = {
    "provider": "qdrant",
    "config": {
        "collection_name": "my_knowledge",
        "host": "localhost",
        "port": 6333,
    }
}

set_embeddings_provider(**config)
```

> 这个 RAG 客户端与 Knowledge 的内置存储**相互独立**——当需要直接控制向量存储或自定义检索管道时使用它。

## 9.5 Agent vs Crew 知识：完整指南

### Agent 级知识（独立）

```python
agent1 = Agent(
    role="Python 专家",
    goal="回答 Python 问题",
    backstory="Python 资深开发者",
    knowledge=[
        # 可以直接传 knowledge sources 列表
        StringKnowledgeSource("Python 3.12 新增特性..."),
    ],
)

agent2 = Agent(
    role="Java 专家",
    goal="回答 Java 问题",
    backstory="Java 资深开发者",
    knowledge=[
        StringKnowledgeSource("Java 21 新特性..."),
    ],
)
```

### Crew 级知识（共享）

```python
from crewai import Crew

crew = Crew(
    agents=[agent1, agent2],
    tasks=[task1, task2],
    knowledge={
        "sources": [
            StringKnowledgeSource("公司内部项目规范文档..."),
            PDFKnowledgeSource(file_path="docs/company_handlebook.pdf"),
        ],
        "collection_name": "company_knowledge",
    },
)
```

### 两级知识同时使用

```python
crew = Crew(
    agents=[agent1, agent2],
    tasks=[...],
    knowledge={
        "sources": [
            CrewLevelSource(...),  # Crew 级共享
        ],
    },
)

# Agent 也可以有自己的知识
agent1 = Agent(
    ...,
    knowledge=[AgentLevelSource(...)],  # Agent 级独立
)
```

> **存储独立性**：每个知识级别使用独立的存储集合。

## 9.6 Knowledge 初始化流程

调用 `crew.kickoff()` 时，知识系统的初始化顺序：

1. **Crew 级知识**先加载到共享集合
2. **Agent 级知识**加载到各自独立的集合
3. 每个 Agent 在任务执行时自动查询自己的知识 + Crew 共享知识

## 9.7 Knowledge 配置参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `sources` | `List[BaseKnowledgeSource]` | 知识源列表（PDF/CSV/Excel/JSON/文本/字符串） |
| `collection_name` | `str` | 存储集合名，默认为 `"knowledge"` |
| `storage` | `Optional[KnowledgeStorage]` | 自定义存储配置，不提供则默认创建 |

## 9.8 完整示例：多 Agent 知识隔离

```python
from crewai import Agent, Crew, Task
from crewai.knowledge.source.string_knowledge_source import StringKnowledgeSource

# Agent 1 专属知识
python_knowledge = StringKnowledgeSource(
    content="Python 3.12 的 pattern matching 语法非常强大。"
)

# Agent 2 专属知识
ai_knowledge = StringKnowledgeSource(
    content="Transformer 架构是当前大模型的基础。"
)

# Crew 共享知识
company_knowledge = StringKnowledgeSource(
    content="公司规定所有代码必须通过 CI 才能合并。"
)

python_agent = Agent(
    role="Python 开发者",
    goal="用 Python 解决问题",
    backstory="熟练的 Python 工程师",
    knowledge=[python_knowledge],
)

ai_agent = Agent(
    role="AI 研究员",
    goal="分析最新 AI 技术",
    backstory="资深 AI 分析师",
    knowledge=[ai_knowledge],
)

crew = Crew(
    agents=[python_agent, ai_agent],
    tasks=[...],
    knowledge={
        "sources": [company_knowledge],
        "collection_name": "company",
    },
)

result = crew.kickoff()
```

## 关键 API 速查

| API | 用途 |
|-----|------|
| `TextFileKnowledgeSource(file_path=...)` | 文本文件知识源 |
| `PDFKnowledgeSource(file_path=...)` | PDF 知识源 |
| `CSVKnowledgeSource(file_path=...)` | CSV 知识源 |
| `ExcelKnowledgeSource(file_path=...)` | Excel 知识源 |
| `JSONKnowledgeSource(file_path=...)` | JSON 知识源 |
| `StringKnowledgeSource(content=...)` | 字符串知识源 |
| `Agent(knowledge=...)` | Agent 级知识 |
| `Crew(knowledge={...})` | Crew 级共享知识 |
| `collection_name` | 存储集合名 |

## 下一步

→ [10-技能Skills.md](10-技能Skills.md)：用 SKILL.md 给 Agent 注入领域专业知识。
