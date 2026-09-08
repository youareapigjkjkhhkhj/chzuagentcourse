# LangChain 配置说明

## 版本信息

本项目使用 LangChain 1.0+ 稳定版本：

- `langchain>=1.0.0` - 核心框架
- `langchain-openai>=0.2.0` - OpenAI 集成
- `langchain-milvus>=0.3.0` - Milvus 向量存储（独立集成包）
- `pymilvus>=2.6.0,<3.0` - Milvus Python 客户端（langchain-milvus 0.3.x 要求）
- `langgraph>=0.2.0` - 有状态的多步工作流

> **注意**：`langchain-community` 已被官方弃用（sunset），且其 0.4.x 版本已**移除 Milvus 类**。本项目向量存储使用独立包 `langchain-milvus`，**请勿**再从 `langchain_community.vectorstores` 导入 Milvus。

## 主要变化 (1.0+)

### 1. 导入路径变化

```python
# 旧版本
from langchain.chat_models import ChatOpenAI
from langchain.embeddings import OpenAIEmbeddings

# 新版本 (1.0+)
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
```

### 2. LCEL (LangChain Expression Language)

```python
# 新版本推荐使用 LCEL
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

prompt = PromptTemplate.from_template("...")
chain = prompt | llm | StrOutputParser()
result = chain.invoke({"question": "..."})
```

### 3. 文档类型

```python
# 新版本使用 langchain_core
from langchain_core.documents import Document
```

## 环境变量配置

```bash
# .env 文件
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=https://api.chatanywhere.tech
OPENAI_MODEL=gpt-5-mini
EMBEDDING_MODEL=text-embedding-3-small
```

## 运行测试

```bash
cd backend
python test_langchain.py
```

## 常见问题

### 1. 导入错误

如果遇到导入错误，请确保安装了正确的包：

```bash
pip install langchain langchain-openai langchain-community langgraph -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 2. API 连接问题

确保 `.env` 文件中的配置正确，特别是：
- `OPENAI_API_KEY` - 有效的 API 密钥
- `OPENAI_BASE_URL` - API 基础 URL

### 3. Milvus 连接问题

Milvus 连接通过 `.env` 配置（可指向本地或远程向量数据库）：

```bash
# .env
MILVUS_HOST=172.16.2.125    # Milvus 服务地址（远程可填 IP）
MILVUS_PORT=19530
MILVUS_COLLECTION=wiki_embeddings
```

- `get_vector_store()` 使用 `langchain-milvus` 的 `Milvus` 类，连接参数为 **uri 格式**（`http://host:port`）。
- **依赖 pymilvus ORM 全局连接**：`ai_service.py` 中同时执行 `connections.connect("default", uri=...)`，因为 langchain-milvus 内部部分路径（集合已存在时）依赖 `Collection(using="default")`。
- 若遇到 `ConnectionNotExistException: should create connection first`，说明 pymilvus 2.6 的 MilvusClient 内部连接未注册到 ORM —— 已通过在 `langchain_milvus/vectorstores/milvus.py` 中将 `self.alias` 固定为 `"default"` 修复（`milvus.py:398`）。
- 文档创建/更新/删除时，`document_service.py` 会自动调用 `AIService.process_document_for_embedding()` / `remove_document_embeddings()` 同步向量，无需手动写入。