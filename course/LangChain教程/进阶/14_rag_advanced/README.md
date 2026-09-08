# 14 - RAG Advanced：混合检索（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量（如 `chunks`、`ensemble_retriever`），跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` / `test.py` 是等价的脚本版本，本手册不修改它们。
> - **在线 / 离线说明**：
>   - 本模块检索链路（Chroma + BM25 + 混合检索）**全部可离线运行**，不需要任何 API Key；
>   - 仅最后的【单元格 8】RAG Agent 需要在线模型（function calling）。
> - **LangChain 1.0 注意**：`EnsembleRetriever` 已移至 `langchain-classic` 包，
>   正确导入：`from langchain_classic.retrievers import EnsembleRetriever`
>   （旧写法 `from langchain.retrievers import ...` 已废弃）。

## 学习目标

基础 RAG 只用向量搜索的局限：精确匹配差（专有名词、版本号）、关键词弱（代码/配置）、鲁棒性低。

**混合检索 = 向量搜索 + BM25 = 语义理解 + 精确匹配**

1. 向量检索器与 BM25 检索器的差异
2. `EnsembleRetriever` 用 RRF 算法融合结果
3. 权重调优与检索质量评估

## 0. 准备工作

```bash
pip install -U langchain langchain-groq python-dotenv
pip install -U langchain-community langchain-text-splitters langchain-huggingface sentence-transformers
pip install -U chromadb rank_bm25 langchain-classic
```

---

## 单元格 1：初始化模型（仅【单元格 8】用到）

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

> 只想学混合检索的话，到【单元格 7】为止都不需要 model。

---

## 单元格 2：加载并分割文档

```python
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

loader = TextLoader("data/langchain_guide.txt", encoding="utf-8")
documents = loader.load()

splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
chunks = splitter.split_documents(documents)

print(f"加载 {len(documents)} 个文档，分割成 {len(chunks)} 个块")
```

---

## 单元格 3：向量检索器（语义）

```python
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

vectorstore = Chroma.from_documents(
    documents=chunks,
    embedding=embeddings,
    persist_directory="./chroma_db_adv",
)

vector_retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

results = vector_retriever.invoke("LangChain 的主要功能")
print(results[0].page_content[:150])
```

向量检索优势：懂语义和同义词；劣势：专有名词、版本号这类精确匹配弱。

---

## 单元格 4：BM25 检索器（关键词）

```python
from langchain_community.retrievers import BM25Retriever

bm25_retriever = BM25Retriever.from_documents(chunks)
bm25_retriever.k = 3

results = bm25_retriever.invoke("langchain>=1.0.0")
print(results[0].page_content[:150])
```

BM25 原理：基于词频计算重要性。优势：精确匹配强、速度快、无需嵌入；
劣势：完全不理解语义，换个说法就搜不到。

---

## 单元格 5：对比实验——同一批查询，两种检索器

直观感受两者互补：

```python
queries = [
    "LangChain 的主要功能",     # 语义型查询
    "langchain>=1.0.0",          # 精确匹配
    "@tool def search",          # 代码片段
]

for q in queries:
    print("=" * 60)
    print("查询:", q)

    print("\n[向量检索]")
    for d in vector_retriever.invoke(q)[:2]:
        print("  -", d.page_content[:60].replace("\n", " "))

    print("[BM25]")
    for d in bm25_retriever.invoke(q)[:2]:
        print("  -", d.page_content[:60].replace("\n", " "))
```

| 查询类型 | 示例 | 向量 | BM25 | 混合 |
|---------|------|------|------|------|
| 语义查询 | "LangChain 的主要功能" | 好 | 差 | 好 |
| 精确匹配 | "langchain>=1.0.0" | 差 | 好 | 好 |
| 代码查询 | "@tool def search" | 差 | 好 | 好 |

---

## 单元格 6：EnsembleRetriever——混合检索

RRF (Reciprocal Rank Fusion) 融合多个排名：

```
RRF 得分 = w1 / (k + rank_bm25) + w2 / (k + rank_vector)
其中 k 通常取 60，w1/w2 是权重
```

```python
from langchain_classic.retrievers import EnsembleRetriever

ensemble_retriever = EnsembleRetriever(
    retrievers=[bm25_retriever, vector_retriever],
    weights=[0.4, 0.6],   # BM25 40% + 向量 60%，稍偏向语义
)

results = ensemble_retriever.invoke("langchain>=1.0.0")
print(results[0].page_content[:150])
```

权重配置指南：

| 场景 | weights (BM25, 向量) |
|------|---------------------|
| 平衡（默认推荐） | `[0.5, 0.5]` |
| 技术文档，偏语义 | `[0.4, 0.6]` |
| 代码库 / 配置，偏精确 | `[0.6, 0.4]` |
| 纯对话语料，强语义 | `[0.3, 0.7]` |

调优流程：收集 10~20 个典型查询 → 测试不同权重 → 对比前 3 个结果的相关性 → 选最优。

---

## 单元格 7：检索质量评估

用简单函数量化"有没有检回预期内容"：

```python
def evaluate_retrieval(retriever, query, expected_content):
    """检查检索结果中是否包含预期内容"""
    results = retriever.invoke(query)
    for doc in results:
        if expected_content in doc.page_content:
            return True
    return False


test_cases = [
    ("LangChain 核心组件有哪些", "LangChain"),
    ("如何使用 @tool 定义工具", "@tool"),
    ("LangChain 1.0 有什么新特性", "1.0"),
]

passed = 0
for query, expected in test_cases:
    ok = evaluate_retrieval(ensemble_retriever, query, expected)
    passed += ok
    print(f"[{'通过' if ok else '未命中'}] {query}")

print(f"\n通过率: {passed}/{len(test_cases)}")
```

生产建议定期跑这样的评估集，监控检索质量变化。

---

## 单元格 8：RAG Agent（需在线）

把混合检索器封装成工具：

```python
from langchain.agents import create_agent
from langchain_core.tools import tool


@tool
def search_docs(query: str) -> str:
    """
    在文档库中搜索相关信息（混合检索：语义 + 关键词）

    参数:
        query: 搜索关键词或问题
    """
    docs = ensemble_retriever.invoke(query)
    return "\n\n".join(doc.page_content for doc in docs)


hybrid_rag_agent = create_agent(
    model=model,
    tools=[search_docs],
    system_prompt="你是助手。回答前先使用 search_docs 搜索资料，再基于结果回答。",
)

resp = hybrid_rag_agent.invoke({
    "messages": [{"role": "user", "content": "LangChain 1.0 有哪些重要特性？"}]
})
print(resp["messages"][-1].content)
```

---

## FAQ

### Q1: 混合检索一定比单一检索好吗？

多数情况是，但不绝对。纯对话场景全语义即可；纯代码搜索全精确即可；
查询类型多样、文档含术语和代码时，混合检索收益最大。

### Q2: 混合检索会慢吗？

两个检索器并行执行，总耗时约等于最慢的那个（通常 ~60ms），可接受。

### Q3: Chroma vs Pinecone vs FAISS？

| 特性 | Chroma | Pinecone | FAISS |
|-----|--------|----------|-------|
| 部署 | 本地 | 云端 | 本地 |
| 扩展性 | 小规模 | 大规模 | 中规模 |
| 推荐 | 开发 | 生产 | 高性能离线 |

### Q4: 文档量很大怎么办？

分层检索（BM25 先过滤 top-100 再向量精选）、元数据预过滤、热门查询加缓存。

## 核心要点总结

1. **混合检索 = 向量 + BM25**，语义与精确互补
2. **EnsembleRetriever** + RRF 算法融合排名，LangChain 1.0 从 `langchain_classic` 导入
3. **权重按数据类型调整**，从 [0.5, 0.5] 起步实测优化
4. **建立评估集**持续监控检索质量
5. 检索器封装成工具即可接入 Agent

## 进一步学习

- 重排序（Reranking）：CrossEncoder 对候选精排
- 查询优化：Query Rewriting、HyDE
- 元数据过滤：按时间、分类先过滤再检索
