# 项目一：RAG 检索增强生成系统（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量，跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` 是等价的脚本版本，本手册不修改它。

## 项目目标

构建一个完整的 RAG 系统：文档加载 → 分块 → 向量化 → 检索 → 生成回答。

## 0. 准备工作

```bash
pip install -U langchain langchain-groq langchain-community langchain-text-splitters langchain-huggingface sentence-transformers chromadb python-dotenv
```

---

## 单元格 1：初始化模型

```python
import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

load_dotenv()

model = init_chat_model(
    "groq:llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.1,
    max_tokens=1000,
)

print("模型就绪")
```

---

## 单元格 2：创建示例文档

```python
from langchain_core.documents import Document

docs = [
    Document(page_content="LangChain 1.0 是一个用于构建 LLM 应用的框架。核心组件包括 LangChain-Core（基础抽象）、LangChain（链式调用）、LangGraph（状态图工作流）。LangChain 1.0 于 2025 年发布，提供了全新的模块化架构。", metadata={"source": "langchain_intro.txt"}),
    Document(page_content="RAG（检索增强生成）是一种让 LLM 访问外部知识的技术。基本流程：加载文档 → 分割文本 → 向量嵌入 → 存入向量库 → 检索相关文档 → 提供给 LLM 生成回答。RAG 可以解决 LLM 训练数据过期和私有数据不可见的问题。", metadata={"source": "rag_guide.txt"}),
    Document(page_content="LangGraph 是 LangChain 生态中用于构建状态化多步骤 AI 工作流的框架。核心概念包括 State（状态）、Node（节点）、Edge（边）。LangGraph 特别适合构建复杂的 Agent 系统和多 Agent 协作场景。", metadata={"source": "langgraph_intro.txt"}),
    Document(page_content="Embedding（嵌入）是将文本转换为向量的过程。常用的嵌入模型包括 OpenAI 的 text-embedding-3-small、HuggingFace 的 all-MiniLM-L6-v2。向量维度通常为384到1536维。", metadata={"source": "embedding_guide.txt"}),
    Document(page_content="Chroma 是一个轻量级的开源向量数据库，适合开发和学习。支持持久化存储、相似度搜索和 MMR（最大边际相关性）检索。安装命令：pip install chromadb。", metadata={"source": "chroma_guide.txt"}),
]

print(f"创建了 {len(docs)} 个文档")
```

---

## 单元格 3：文本分割

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=50,
    separators=["\n\n", "\n", "。", " ", ""],
)

chunks = splitter.split_documents(docs)
print(f"分割为 {len(chunks)} 个块")
for i, c in enumerate(chunks):
    print(f"  块{i+1}: {len(c.page_content)} 字 | {c.page_content[:40]}...")
```

---

## 单元格 4：向量嵌入 + Chroma

```python
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")

vectorstore = Chroma.from_documents(
    documents=chunks,
    embedding=embeddings,
    persist_directory="./rag_chroma_db",
)

retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
print("向量库构建完成")
```

---

## 单元格 5：检索测试

```python
query = "什么是 RAG？"
results = retriever.invoke(query)

print(f"查询: {query}")
print(f"检索到 {len(results)} 个结果:")
for i, d in enumerate(results):
    print(f"\n  结果 {i+1} ({d.metadata['source']}):")
    print(f"    {d.page_content[:100]}...")
```

---

## 单元格 6：生成回答

```python
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

def rag_generate(query, docs):
    context = "\n\n".join(d.page_content for d in docs)
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是知识库助手。基于以下上下文回答问题。如果上下文中没有相关信息，请说明。\n\n上下文：\n{context}"),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{question}")
    ])
    chain = prompt | model
    response = chain.invoke({"context": context, "question": query, "chat_history": []})
    return response.content

answer = rag_generate("什么是 RAG？", results)
print(f"问题: 什么是 RAG？")
print(f"回答: {answer}")
```

---

## 单元格 7：来源追踪

```python
def rag_with_sources(query, docs):
    answer = rag_generate(query, docs)
    sources = [{"content": d.page_content[:80], "source": d.metadata["source"]} for d in docs]
    return {"answer": answer, "sources": sources}

result = rag_with_sources("LangGraph 是什么？", retriever.invoke("LangGraph 是什么？"))

print("回答:", result["answer"])
print("\n来源:")
for s in result["sources"]:
    print(f"  - [{s['source']}] {s['content']}...")
```

---

## 单元格 8：置信度评估

```python
def rag_with_confidence(query, docs):
    answer = rag_generate(query, docs)
    # 简单置信度：基于检索结果数量和重叠度
    confidence = min(len(docs) / 3.0, 1.0)
    sources = [d.metadata["source"] for d in docs]
    return {"answer": answer, "confidence": confidence, "sources": sources}

result = rag_with_confidence("如何安装 Chroma？", retriever.invoke("如何安装 Chroma？"))

print(f"回答: {result['answer']}")
print(f"置信度: {result['confidence']:.0%}")
print(f"来源: {result['sources']}")
```

---

## 单元格 9：对话式 RAG（带历史）

```python
chat_history = []

def chat_with_rag(question):
    global chat_history
    docs = retriever.invoke(question)
    answer = rag_generate(question, docs)
    chat_history.append({"role": "user", "content": question})
    chat_history.append({"role": "assistant", "content": answer})
    return answer

print("对话式 RAG（输入 'quit' 退出）：\n")

# 模拟对话
for q in ["什么是 LangChain？", "它和 LangGraph 有什么关系？"]:
    print(f"用户: {q}")
    print(f"AI: {chat_with_rag(q)}\n")
```

---

## 核心要点

1. 完整 RAG 流程：加载 → 分割 → 嵌入 → 入库 → 检索 → 生成
2. 来源追踪：每个回答附带引用来源
3. 置信度评估：基于检索质量给出可信度评分
4. 对话历史：`chat_history` 列表维护多轮上下文

## 进阶优化方向

- **混合检索**（向量 + BM25）
- **重排序**（Reranking）
- **查询改写**（HyDE）
- **元数据过滤**

## 下一步

**02_multi_agent_support** —— 多智能体客服系统
