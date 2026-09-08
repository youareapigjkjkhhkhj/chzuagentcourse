# 16 - 文件处理 Files

本篇目标：掌握 CrewAI 的 **多模态文件输入**能力——如何向 Agent 传递图片、PDF、音频、视频等文件，以及文件优先级规则。

## 16.1 概述

CrewAI 原生支持**多模态文件输入**，允许直接向 Agent 传递：

- 图片（Images）
- PDF 文档
- 音频
- 视频
- 文本文件

文件会根据各 LLM 提供商的 API 要求**自动格式化**。

## 16.2 支持的文件类型

| 类型 | 类 | 说明 |
|------|-----|------|
| 图片 | `ImageFile` | JPG、PNG、GIF 等 |
| PDF | `PDFFile` | PDF 文档 |
| 音频 | `AudioFile` | MP3、WAV 等 |
| 视频 | `VideoFile` | MP4 等 |
| 文本 | `TextFile` | 任意文本文件 |
| 泛型 | `File` | 自动检测类型 |

## 16.3 文件来源

`source` 参数支持多种输入类型，自动检测适当的处理方式：

### 从路径

```python
from crewai import File

file = File(
    key="report",
    source="/path/to/report.pdf",
)
```

### 从 URL

```python
from crewai import File

file = File(
    key="image",
    source="https://example.com/image.png",
)
```

### 从 Bytes

```python
from crewai import File

with open("image.jpg", "rb") as f:
    data = f.read()

file = File(
    key="image",
    source=data,  # bytes 数据
    content_type="image/jpeg",
)
```

## 16.4 在四个层级使用文件

**文件可以在多个层级传递，更具体的层级优先。**

### 配合 Crew

```python
from crewai import Crew, File

crew = Crew(
    agents=[analyst],
    tasks=[analyze_task],
    files=[
        File(key="chart", source="/path/to/chart.png"),
        File(key="dataset", source="/path/to/data.csv"),
    ],
)
```

### 配合 Task

```python
from crewai import Task, File

task = Task(
    description="分析附带的图表并撰写报告",
    expected_output="详细分析报告",
    agent=analyst,
    files=[
        File(key="chart", source="/path/to/chart.png"),
    ],
)
```

### 配合 Flow

```python
from crewai.flow import Flow, start
from crewai import File

class FileFlow(Flow):

    @start()
    def analyze(self):
        files = [File(key="pdf", source="/path/to/doc.pdf")]
        # files 自动传递给 crew
        result = self.my_crew.kickoff(files=files)
        return result
```

### 配合独立 Agent

```python
from crewai import Agent, File

agent = Agent(
    role="文档解析器",
    goal="解析并总结文档",
    backstory="文档分析专家",
    files=[File(key="doc", source="/path/to/doc.pdf")],
)
```

## 16.5 文件优先级规则

当文件在多个层级同时传递时，**更具体的级别覆盖更宽泛的级别**。

```
Flow  →  Crew  →  Task  →  最具体
```

例如，如果 Flow 和 Task 都定义了名为 `"chart"` 的文件，**Task 的版本被使用**：

```python
# Flow 层
files=[File(key="chart", source="flow_chart.png")]

# Task 层（覆盖 Flow 层）
task = Task(
    description="...",
    files=[File(key="chart", source="task_chart.png")],
)
# ← task_chart.png 被使用
```

## 16.6 提供商支持

不同提供商支持不同的文件类型。CrewAI **自动格式化**文件为各提供商兼容格式。

## 16.7 文件传输方式

CrewAI 自动选择最优方法向提供商发送文件。

## 16.8 文件处理模式

控制文件超出提供商限制时的处理方式：

```python
from crewai import File

file = File(
    key="large_image",
    source="/path/to/large.jpg",
    mode="resize",       # 自动调整以适配限制
    # 或 mode="truncate"  # 截断
)
```

## 16.9 提供商限制

### OpenAI

| 类型 | 限制 |
|------|------|
| 图片 | 最大 20 MB，每个请求最多 10 张 |
| PDF | 最大 32 MB，最多 100 页 |
| 音频 | 最大 25 MB，最长 25 分钟 |

### Anthropic

| 类型 | 限制 |
|------|------|
| 图片 | 最大 5 MB，最大 8000×8000 像素，最多 100 张 |
| PDF | 最大 32 MB，最多 100 页 |

### Google Gemini

| 类型 | 限制 |
|------|------|
| 图片 | 最大 100 MB |
| PDF | 最大 50 MB |
| 音频 | 最大 100 MB，最长 9.5 小时 |
| 视频 | 最大 2 GB，最长 1 小时 |

### AWS Bedrock

| 类型 | 限制 |
|------|------|
| 图片 | 最大 4.5 MB，最大 8000×8000 像素 |
| PDF | 最大 3.75 MB，最多 100 页 |

## 16.10 在 Prompts 中引用文件

在任务描述中使用文件的 key 名来引用：

```python
task = Task(
    description=(
        "请分析图表 {{chart}} 中的数据变化趋势，"
        "并结合 {{dataset}} 中的数据撰写一份周报。"
    ),
    expected_output="包含数据趋势的完整周报",
    agent=analyst,
    files=[
        File(key="chart", source="/path/to/chart.png"),
        File(key="dataset", source="/path/to/data.csv"),
    ],
)
```

## 关键 API 速查

| API | 用途 |
|-----|------|
| `File(key="xx", source=path)` | 创建文件对象 |
| `Crew(files=[...])` | Crew 级文件 |
| `Task(files=[...])` | Task 级文件 |
| `Flow` 传递 | 自动继承到 Crew |
| `Agent(files=[...])` | 独立 Agent 文件 |
| `{{key}}` | 在 prompt 中引用文件 |

## 下一步

→ [17-MCP集成.md](17-MCP集成.md)：通过 MCP 协议接入外部工具服务器。
