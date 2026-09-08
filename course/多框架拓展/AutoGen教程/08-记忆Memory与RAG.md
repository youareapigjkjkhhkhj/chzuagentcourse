# 08 - 记忆 Memory 与 RAG

本篇目标：为 Agent 注入**记忆**——从简单的用户偏好列表，到基于向量库的文档 RAG 问答。

## 8.1 前置准备

```bash
pip install -U "autogen-agentchat" "autogen-ext[openai]"
# 向量记忆（ChromaDB）
pip install -U "autogen-ext[chromadb]"
# 文档抓取示例用到
pip install aiofiles aiohttp
```

## 8.2 Memory 协议

`autogen_core.memory.Memory` 定义统一接口：

| 方法 | 作用 |
|------|------|
| `add(content: MemoryContent)` | 写入一条记忆/文档块 |
| `query(...)` | 检索相关记忆，返回 `List[MemoryContent]` |
| `update_context(model_context)` | **把检索结果注入模型上下文**（Agent 内部自动调用） |
| `clear()` | 清空 |
| `close()` | 释放资源 |

配套类型：

```python
from autogen_core.memory import MemoryContent, MemoryMimeType

MemoryContent(
    content="The weather should be in metric units",
    mime_type=MemoryMimeType.TEXT,
    metadata={"category": "preferences", "type": "units"},
)
```

## 8.3 ListMemory（内置简单记忆）

按时间顺序维护记忆，把全部内容拼进上下文。适合少量用户偏好。

```python
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.ui import Console
from autogen_core.memory import ListMemory, MemoryContent, MemoryMimeType
from autogen_ext.models.openai import OpenAIChatCompletionClient


async def get_weather(city: str, units: str = "imperial") -> str:
    if units == "imperial":
        return f"The weather in {city} is 73 °F and Sunny."
    elif units == "metric":
        return f"The weather in {city} is 23 °C and Sunny."
    return f"Sorry, I don't know the weather in {city}."


user_memory = ListMemory()
await user_memory.add(MemoryContent(content="The weather should be in metric units", mime_type=MemoryMimeType.TEXT))
await user_memory.add(MemoryContent(content="Meal recipe must be vegan", mime_type=MemoryMimeType.TEXT))

assistant_agent = AssistantAgent(
    name="assistant_agent",
    model_client=OpenAIChatCompletionClient(model="gpt-4o-2024-08-06"),
    tools=[get_weather],
    memory=[user_memory],          # ← 挂载记忆
)

await Console(assistant_agent.run_stream(task="What is the weather in New York?"))
```

运行时会先输出 `MemoryQueryEvent`（检索到的记忆），随后 Agent 自动使用 `metric` 单位调用工具，返回 `23 °C`。

### 注入效果（调试）

```python
await assistant_agent._model_context.get_messages()
```

可见检索结果被格式化为 `SystemMessage` 插入上下文：

```text
SystemMessage(content='\nRelevant memory content (in chronological order):\n1. The weather should be in metric units\n2. Meal recipe must be vegan\n')
```

## 8.4 向量记忆：ChromaDBVectorMemory

适合规模化知识库（按语义相似度检索 top-k）。

```python
import tempfile

from autogen_core.memory import MemoryContent, MemoryMimeType
from autogen_ext.memory.chromadb import (
    ChromaDBVectorMemory,
    PersistentChromaDBVectorMemoryConfig,
    SentenceTransformerEmbeddingFunctionConfig,
)

with tempfile.TemporaryDirectory() as tmpdir:
    chroma_user_memory = ChromaDBVectorMemory(
        config=PersistentChromaDBVectorMemoryConfig(
            collection_name="preferences",
            persistence_path=tmpdir,
            k=2,                    # 返回 top 2
            score_threshold=0.4,    # 最小相似度
            embedding_function_config=SentenceTransformerEmbeddingFunctionConfig(
                model_name="all-MiniLM-L6-v2"
            ),
        )
    )

    await chroma_user_memory.add(
        MemoryContent(content="The weather should be in metric units",
                      mime_type=MemoryMimeType.TEXT,
                      metadata={"category": "preferences", "type": "units"})
    )
    # ... 同样挂载到 AssistantAgent(memory=[chroma_user_memory])
    await chroma_user_memory.close()
```

## 8.5 其他记忆后端

| 实现 | 位置 | 适用 |
|------|------|------|
| `ListMemory` | `autogen_core.memory` | 少量用户偏好、快速演示 |
| `ChromaDBVectorMemory` | `autogen_ext.memory.chromadb` | 本地/嵌入式向量库 |
| `RedisMemory` | `autogen_ext.memory.redis` | 分布式、需要 Redis 栈 |
| `Mem0Memory` | `autogen_ext.memory.mem0` | Mem0.ai（云端 `is_cloud=True` / 本地 `False`），长期记忆管理 |

Redis 示例：

```python
from autogen_ext.memory.redis import RedisMemory, RedisMemoryConfig

redis_memory = RedisMemory(
    config=RedisMemoryConfig(
        redis_url="redis://localhost:6379",
        index_name="chat_history",
        prefix="memory",
    )
)
```

Mem0 示例：

```python
from autogen_ext.memory.mem0 import Mem0Memory

mem0_memory = Mem0Memory(is_cloud=True, limit=5)   # 最多检索 5 条
```

## 8.6 完整 RAG：索引 + 检索

### 步骤 1：文档索引器

```python
import re
from typing import List

import aiofiles
import aiohttp
from autogen_core.memory import Memory, MemoryContent, MemoryMimeType


class SimpleDocumentIndexer:
    """Basic document indexer for AutoGen Memory."""

    def __init__(self, memory: Memory, chunk_size: int = 1500) -> None:
        self.memory = memory
        self.chunk_size = chunk_size

    async def _fetch_content(self, source: str) -> str:
        if source.startswith(("http://", "https://")):
            async with aiohttp.ClientSession() as session:
                async with session.get(source) as response:
                    return await response.text()
        async with aiofiles.open(source, "r", encoding="utf-8") as f:
            return await f.read()

    def _strip_html(self, text: str) -> str:
        text = re.sub(r"<[^>]*>", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _split_text(self, text: str) -> List[str]:
        return [text[i:i + self.chunk_size].strip() for i in range(0, len(text), self.chunk_size)]

    async def index_documents(self, sources: List[str]) -> int:
        total_chunks = 0
        for source in sources:
            try:
                content = await self._fetch_content(source)
                if "<" in content and ">" in content:
                    content = self._strip_html(content)
                chunks = self._split_text(content)
                for i, chunk in enumerate(chunks):
                    await self.memory.add(
                        MemoryContent(
                            content=chunk,
                            mime_type=MemoryMimeType.TEXT,
                            metadata={"source": source, "chunk_index": i},
                        )
                    )
                total_chunks += len(chunks)
            except Exception as e:
                print(f"Error indexing {source}: {str(e)}")
        return total_chunks
```

### 步骤 2：建库 + 问答

```python
import os
from pathlib import Path

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.ui import Console
from autogen_ext.memory.chromadb import ChromaDBVectorMemory, PersistentChromaDBVectorMemoryConfig
from autogen_ext.models.openai import OpenAIChatCompletionClient

rag_memory = ChromaDBVectorMemory(
    config=PersistentChromaDBVectorMemoryConfig(
        collection_name="autogen_docs",
        persistence_path=os.path.join(str(Path.home()), ".chromadb_autogen"),
        k=3,
        score_threshold=0.4,
    )
)

await rag_memory.clear()   # 重新索引前清空

indexer = SimpleDocumentIndexer(memory=rag_memory)
chunks = await indexer.index_documents([
    "https://raw.githubusercontent.com/microsoft/autogen/main/README.md",
    "https://microsoft.github.io/autogen/dev/user-guide/agentchat-user-guide/tutorial/agents.html",
    "https://microsoft.github.io/autogen/dev/user-guide/agentchat-user-guide/tutorial/teams.html",
])
print(f"Indexed {chunks} chunks")

rag_assistant = AssistantAgent(
    name="rag_assistant",
    model_client=OpenAIChatCompletionClient(model="gpt-4o"),
    memory=[rag_memory],
)

await Console(rag_assistant.run_stream(task="What is AgentChat?"))
await rag_memory.close()
```

## 8.7 两种模式对比

| | ListMemory | 向量记忆（RAG） |
|--|-----------|----------------|
| 检索方式 | 全量/按时间顺序 | 语义相似度 top-k + 分数阈值 |
| 注入形式 | `SystemMessage`（Relevant memory content…） | 检索到的文档块 |
| 适用 | 少量用户偏好 | 大规模知识库问答 |

## 8.8 生产建议（官方）

1. 使用更精细的切分（chunking）策略（按段落/标题，而非定长硬切）。
2. 增加**元数据过滤**（按来源、时间、权限）。
3. 自定义检索打分与重排。
4. 针对领域优化 embedding 模型。

## 关键 API 速查

| API | 说明 |
|-----|------|
| `MemoryContent(content=, mime_type=, metadata=)` | 记忆条目 |
| `MemoryMimeType.TEXT` | 文本类型 |
| `await memory.add(...)` / `query(...)` / `clear()` / `close()` | 记忆操作 |
| `AssistantAgent(memory=[...])` | 挂载多个记忆 |
| `MemoryQueryEvent` | 检索事件（Console 可见） |
| `assistant._model_context.get_messages()` | 调试注入效果 |

## 注意事项

- 记忆是**注入上下文**实现的（占 token），不是"免费"的；`k` 与 `score_threshold` 要调到合适。
- `update_context` 由 Agent 内部调用，一般无需手写。
- 向量记忆记得 `close()`。

## 下一步

→ [09-团队Teams.md](09-团队Teams.md)：多个 Agent 组队协作。
