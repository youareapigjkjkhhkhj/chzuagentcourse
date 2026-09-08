# 13 - RAG Basics：RAG 基础（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量（如 `chunks`、`vectorstore`），跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` / `demo.py` / `test.py` 是等价的脚本版本，本手册不修改它们。
> - **在线 / 离线说明**：
>   - 检索链路（加载、分割、嵌入、向量库、相似度搜索）**全部可离线运行**——嵌入模型在本地跑，首次运行会自动下载；
>   - 向量库二选一：【单元格 5A】Chroma 本地方案（零配置，推荐入门）/【单元格 5B】Pinecone 云方案（需 `PINECONE_API_KEY`）；
>   - 仅最后的【单元格 7】RAG Agent 需要在线模型（function calling）。

## 学习目标

**RAG = 检索增强生成**，让 LLM 能访问外部知识，解决训练数据过期、私有数据不可见、幻觉三大问题。

```
离线：文档 → 分割 → 嵌入 → 存入向量库
在线：用户查询 → 检索相关文档 → 提供给 LLM → 生成答案
```

1. Document Loaders 文档加载
2. Text Splitters 文本分割
3. Embeddings 向量嵌入（本地 HuggingFace 模型）
4. Vector Stores 向量存储与相似度检索
5. 把检索器封装成工具，构建 RAG Agent

## 0. 准备工作

```bash
# 基础依赖
pip install -U langchain langchain-groq python-dotenv
pip install -U langchain-community langchain-text-splitters langchain-huggingface sentence-transformers

# 向量库二选一
pip install -U chromadb                                  # 本地方案（推荐入门）
pip install -U pinecone-client langchain-pinecone        # 云方案
```

云方案用户：把 `.env.example` 复制为 `.env`，填入 `GROQ_API_KEY` 和 `PINECONE_API_KEY`
（Pinecone 免费层：1 个 serverless 索引 + 10 GB，无需信用卡）。

---

## 单元格 1：初始化模型（仅【单元格 7】用到）

### 单元格 1A：在线版

```python
import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

load_dotenv()

model = init_chat_model(
    "groq:llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0,
    max_tokens=500,
)

print("模型就绪")
```

### 单元格 1B：离线版

```python
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
from langchain_huggingface import ChatHuggingFace, HuggingFacePipeline

model_id = "Qwen/Qwen2.5-0.5B-Instruct"
tokenizer = AutoTokenizer.from_pretrained(model_id)
hf_model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=torch.float32, device_map="cpu")
pipe = pipeline(
    "text-generation", model=hf_model, tokenizer=tokenizer,
    max_new_tokens=128, do_sample=True, temperature=0.7, top_p=0.8,
)
model = ChatHuggingFace(llm=HuggingFacePipeline(pipeline=pipe))

print("模型就绪（本地）")
```

> 只想学检索链路的话，本模块到【单元格 6】为止都不需要 model，
> 可以直接跳过单元格 1 从单元格 2 开始。

---

## 单元格 2：文档加载

```python
from langchain_community.document_loaders import TextLoader

loader = TextLoader("data/langchain_intro.txt", encoding="utf-8")
documents = loader.load()

print(f"加载了 {len(documents)} 个文档")
print(documents[0].page_content[:200])
# Document 对象包含 page_content（文本）和 metadata（元数据）
```

常用 Loaders：`TextLoader` 文本 / `PyPDFLoader` PDF / `WebBaseLoader` 网页 / `CSVLoader` CSV。

---

## 单元格 3：文本分割

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,      # 每块最大字符数
    chunk_overlap=50,    # 相邻块重叠，防止信息被截断
    separators=["\n\n", "\n", "。", " ", ""],   # 分割优先级：段落 > 句子 > 字符
)

chunks = splitter.split_documents(documents)

print(f"分割成 {len(chunks)} 个块")
print(chunks[0].page_content[:100])
```

为什么要分割：LLM 有 token 上限；小块检索更精准；降低成本。
参考配置：通用 500/50；长文档 1000/200；短问答对 200/20。

---

## 单元格 4：向量嵌入（本地运行）

首次运行会下载嵌入模型（约 90MB），之后完全离线：

```python
from langchain_huggingface import HuggingFaceEmbeddings

embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

vector = embeddings.embed_query("什么是 RAG?")
print(f"向量维度: {len(vector)}")     # 384 维
print(vector[:5])                     # 就是 384 个浮点数
```

免费模型选择：`all-MiniLM-L6-v2`（384 维，快）；`all-mpnet-base-v2`（768 维，更准更慢）。

---

## 单元格 5：存入向量库（5A / 5B 二选一）

两者都会定义出用法相同的 `vectorstore`，后续单元格不用改。

### 单元格 5A：Chroma 本地方案（零配置，推荐）

```python
from langchain_community.vectorstores import Chroma

vectorstore = Chroma.from_documents(
    documents=chunks,
    embedding=embeddings,
    persist_directory="./chroma_db",   # 本地持久化目录
)

print("本地向量库构建完成")
```

### 单元格 5B：Pinecone 云方案（需 PINECONE_API_KEY）

```python
import time
from pinecone import Pinecone, ServerlessSpec
from langchain_pinecone import PineconeVectorStore

pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
INDEX_NAME = "langchain-course"

try:
    pc.create_index(
        name=INDEX_NAME,
        dimension=384,        # 必须与嵌入模型维度一致！
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1"),   # 免费区域
    )
    time.sleep(10)            # 等待索引就绪
except Exception as e:
    print("索引可能已存在，直接复用:", e)

vectorstore = PineconeVectorStore.from_documents(
    documents=chunks,
    embedding=embeddings,
    index_name=INDEX_NAME,
)

print("云端向量库构建完成")
```

> 注意：dimension 必须与嵌入模型匹配——`all-MiniLM-L6-v2` 是 384，
> OpenAI text-embedding-3-small 是 1536，不匹配会报错。

---

## 单元格 6：相似度检索

```python
docs = vectorstore.similarity_search("什么是 RAG？", k=3)

for i, d in enumerate(docs, 1):
    print(f"--- 结果 {i} ---")
    print(d.page_content[:120])

# 换个问题试试
docs2 = vectorstore.similarity_search("LangChain 有哪些核心组件？", k=2)
print(docs2[0].page_content[:120])
```

k 的选择：简单问题 k=1~3；需要全面信息 k=5~10（注意 token 成本）。

---

## 单元格 7：RAG 问答 Agent（需在线）

把检索器封装成工具，交给 Agent 自动调用：

```python
from langchain.agents import create_agent
from langchain_core.tools import tool


@tool
def search_kb(query: str) -> str:
    """
    搜索知识库并返回最相关的文档内容

    参数:
        query: 搜索关键词或问题
    """
    docs = vectorstore.similarity_search(query, k=3)
    return "\n\n".join(doc.page_content for doc in docs)


rag_agent = create_agent(
    model=model,
    tools=[search_kb],
    system_prompt="你是知识库助手。回答前先使用 search_kb 工具检索资料，再基于检索结果回答。",
)

resp = rag_agent.invoke({
    "messages": [{"role": "user", "content": "LangChain 的核心组件有哪些？"}]
})
print(resp["messages"][-1].content)
```

> 已知问题：Groq 处理中文工具参数偶发 `tool_use_failed` 错误（约 70-80% 成功率）。
> 重试通常可成功；追求稳定可用英文提问或换 GPT-4o-mini / Claude。

---

## FAQ

### Q1: 为什么用 HuggingFace 而不是 OpenAI 嵌入？

完全免费、本地运行、支持离线，精度对多数场景足够。追求更高精度且愿意付费时再用 OpenAI。

### Q2: Chroma 和 Pinecone 怎么选？

开发学习用 Chroma（零配置、全本地）；生产/大规模用 Pinecone（云端托管、易扩展）。

### Q3: 检索结果不准怎么办？

调整 chunk_size / overlap；提高 k；换更强的嵌入模型；进阶技巧见下一模块（混合检索、重排序）。

## 核心要点

1. 加载 → 分割 → 嵌入 → 入库 → 检索 → 生成，六步标准流程
2. 嵌入模型本地运行，维度必须与向量库配置一致
3. Chroma 本地零配置，Pinecone 云端免费层够学习用
4. 检索器封装成 `@tool` 即可接入 Agent

## 下一步

**14_rag_advanced** —— 混合检索（向量 + BM25）、权重调优、检索评估
