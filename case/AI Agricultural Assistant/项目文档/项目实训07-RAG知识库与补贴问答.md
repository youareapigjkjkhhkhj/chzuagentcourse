# 项目实训07｜RAG 知识库与补贴问答

> **训练目标**：掌握 RAG（检索增强生成）全链路：知识库构建 → 向量检索 → LCEL 生成链 → 幻觉护栏。
> **预计时长**：8 学时 ｜ **前置条件**：实训 06 完成
> **本次交付物**：`data/subsidies.json`、`services/rag_service.py`、`services/rag_chain.py`、`core/guardrails.py`、`agents/subsidy_agent.py`

---

## 一、知识点

### 1. 为什么补贴问答必须用 RAG

政策类问答的红线是**不可编造**。直接问 LLM 必然产生幻觉（虚构政策名、金额）。RAG 的思路：

```
用户问题 ──嵌入──▶ 向量相似度检索 ──▶ Top-K 政策文档
                                          │
        LLM 生成 ◀── "只允许依据以下官方信息回答" ◀──┘
```

### 2. 关键概念速查

| 概念 | 本项目实现 |
|------|-----------|
| 嵌入模型（Embedding） | `sentence-transformers/all-MiniLM-L12-v2`（384 维，CPU 可跑） |
| 向量库 | FAISS（本地）；可选升级 Pinecone（云端） |
| 相似度阈值 | FAISS 距离 > 0.7 视为不相关，丢弃 |
| 生成链 | LCEL：`prompt | llm | StrOutputParser`（可被 LangSmith 追踪） |
| 护栏 | 生成后校验：回答中的政策名必须来自检索结果 |

### 3. 单例 + 懒加载

嵌入模型加载约需数秒，绝不能每个请求加载一次。`RAG` 用 `__new__` 单例 + 启动时一次性建库。

---

## 二、操作步骤

### 步骤 1：准备知识库 `backend/data/subsidies.json`

示例收录 2 条（完整源码含多条；**可替换为你所在地区的真实惠农政策**，字段结构不变）：

```json
[
  {
    "id": "pm_kisan",
    "scheme_name": "Pradhan Mantri Kisan Samman Nidhi (PM-KISAN)",
    "government_level": "Central",
    "eligibility": "All land-holding farmer families (subject to some exclusions and conditions).",
    "benefits": "Rs.6,000 per year, delivered in three equal instalments of Rs.2,000 each.",
    "application_steps": "Register online via the official portal or through Common Service Centres (CSCs). Provide landholding and bank account details.",
    "documents": "Aadhaar Card, Land Ownership Papers, Bank Account Details.",
    "notes": "Institutional land-holders often not eligible.",
    "link_to_apply": "https://pmkisan.gov.in/"
  },
  {
    "id": "pmksy_per_drop_more_crop",
    "scheme_name": "Pradhan Mantri Krishi Sinchai Yojana (PMKSY) - Per Drop More Crop",
    "government_level": "Central & State",
    "eligibility": "Farmers of all categories; small & marginal farmers given priority.",
    "benefits": "Support/subsidy for irrigation infrastructure, micro-irrigation systems.",
    "application_steps": "Apply via state agriculture department portal; submit project/installation proposal.",
    "documents": "Land records, Aadhaar, Bank passbook, Quotation from registered vendor.",
    "notes": "State-wise terms (subsidy percentage, eligible area) may vary.",
    "link_to_apply": "https://mimi.icar.gov.in/"
  }
]
```

### 步骤 2：实现向量检索服务 `backend/services/rag_service.py`

```python
import json
import os
from typing import List, Dict
import unicodedata
import re

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

from backend.core.config import settings

DATA_PATH = os.path.join(os.path.dirname(__file__), "../data/subsidies.json")
VECTOR_DB_PATH = os.path.join(os.path.dirname(__file__), "../data/faiss_index")

# HuggingFace MiniLM dimension for Pinecone
EMBEDDING_DIM = 384


def _clean_query(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def _load_subsidy_documents() -> List[Document]:
    """Load subsidy documents from JSON."""
    if not os.path.exists(DATA_PATH):
        return []

    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[RAG] Failed to load subsidies.json: {e}")
        return []

    if not isinstance(raw_data, list):
        print("[RAG] subsidies.json must be a JSON array")
        return []

    documents: List[Document] = []
    for item in raw_data:
        scheme_name = item.get("scheme_name", "Unknown Scheme")
        eligibility = item.get("eligibility", "Not Provided")
        benefits = item.get("benefits", "Not Provided")
        notes = item.get("notes", "")

        content = (
            f"Scheme: {scheme_name}\n"
            f"Eligibility: {eligibility}\n"
            f"Benefits: {benefits}\n"
            f"Notes: {notes}\n"
        )
        documents.append(Document(page_content=content, metadata=item))

    return documents


class RAG:
    """
    RAG singleton for subsidy retrieval.
    Supports FAISS (default) or Pinecone when PINECONE_API_KEY is set.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RAG, cls).__new__(cls)
            cls._instance.initialize()
        return cls._instance

    def initialize(self):
        self.embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L12-v2"
        )

        self.vector_store = None
        self._use_pinecone = bool(
            settings.PINECONE_API_KEY and settings.PINECONE_INDEX_NAME
        )

        if self._use_pinecone:
            self._init_pinecone()
        else:
            self._init_faiss()

    def _init_pinecone(self):
        """Initialize Pinecone vector store."""
        try:
            from pinecone import Pinecone
            from langchain_pinecone import PineconeVectorStore

            pc = Pinecone(api_key=settings.PINECONE_API_KEY)
            index_name = settings.PINECONE_INDEX_NAME

            if index_name not in [idx.name for idx in pc.list_indexes()]:
                print(f"[RAG] Pinecone index '{index_name}' not found. Falling back to FAISS.")
                self._use_pinecone = False
                self._init_faiss()
                return

            self.vector_store = PineconeVectorStore.from_existing_index(
                index_name=index_name,
                embedding=self.embeddings,
            )
            print("[RAG] Using Pinecone vector store.")
        except Exception as e:
            print(f"[RAG] Pinecone init failed: {e}. Falling back to FAISS.")
            self._use_pinecone = False
            self._init_faiss()

    def _init_faiss(self):
        """Initialize FAISS vector store."""
        if os.path.exists(VECTOR_DB_PATH):
            try:
                print("[RAG] Loading existing FAISS index...")
                self.vector_store = FAISS.load_local(
                    VECTOR_DB_PATH,
                    self.embeddings,
                    allow_dangerous_deserialization=True,
                )
                print("[RAG] FAISS index loaded.")
                return
            except Exception as e:
                print(f"[RAG] Failed to load FAISS index: {e}. Rebuilding...")
                try:
                    import shutil
                    shutil.rmtree(VECTOR_DB_PATH)
                except Exception:
                    pass

        docs = _load_subsidy_documents()
        if not docs:
            print(f"[RAG] subsidies.json not found at: {DATA_PATH}")
            return

        print("[RAG] Building FAISS index...")
        self.vector_store = FAISS.from_documents(docs, self.embeddings)
        self.vector_store.save_local(VECTOR_DB_PATH)
        print("[RAG] FAISS index built and saved.")

    def retrieve(self, query: str, k: int = 2) -> List[Dict[str, str]]:
        if not query or not query.strip():
            return []

        query_clean = _clean_query(query.strip() + " india agriculture subsidy")

        if not self.vector_store:
            print("[RAG] Vector store not loaded.")
            return []

        try:
            if self._use_pinecone:
                docs = self.vector_store.similarity_search(query_clean, k=k)
                docs_with_scores = [(doc, 0.0) for doc in docs]
            else:
                docs_with_scores = self.vector_store.similarity_search_with_score(
                    query_clean, k=k
                )
        except Exception as e:
            print(f"[RAG] Retrieval error: {e}")
            return []

        results: List[Dict[str, str]] = []

        for item in docs_with_scores:
            doc, score = item if len(item) == 2 else (item[0], 0.0)

            if not self._use_pinecone and score > 0.7:
                continue

            meta = doc.metadata if isinstance(doc.metadata, dict) else {}
            results.append({
                "scheme_name": str(meta.get("scheme_name", "Unknown Scheme")),
                "eligibility": str(meta.get("eligibility", "Not Provided")),
                "benefits": str(meta.get("benefits", "Not Provided")),
                "application_steps": str(meta.get("application_steps", "")),
                "documents": str(meta.get("documents", "")),
                "notes": str(meta.get("notes", "")),
            })

        return results


rag_service = RAG()
```

**设计要点**：

1. **查询扩词**：`+ " india agriculture subsidy"` 把口语提问拉向政策语料空间，提高召回；
2. **阈值过滤**：FAISS 返回的是 L2 距离（越小越相似），>0.7 视为无关——**宁可回答"没查到"，不可强行凑答案**；
3. **持久化索引**：`save_local` / `load_local` 避免每次启动重建；
4. `allow_dangerous_deserialization=True` 只用于加载自己生成的索引文件（企业场景需评审）。

> 首次运行会从 HuggingFace 下载嵌入模型（约 100MB）；国内网络可设置 `HF_ENDPOINT=https://hf-mirror.com`。

### 步骤 3：追加补贴生成提示词并实现 LCEL 链

在 `langchain_prompts.py` 追加：

```python
# Subsidy RAG prompt - used in LCEL chain
SUBSIDY_RAG_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are AgriGPT SubsidyAgent. Explain Indian agricultural subsidy schemes using ONLY verified official information below.
Do not invent schemes, eligibility, benefits, or application rules. If information is missing, state that clearly.
Present in simple, farmer-friendly language. Avoid legal jargon.
Do not provide advice beyond explaining what the scheme offers and how to apply."""),
    ("human", """Previous context: {chat_history}

Farmer question: {query}

Official information: {context}
"""),
])
```

创建 `backend/services/rag_chain.py`：

```python
"""
LCEL RAG chain for SubsidyAgent - composable, LangSmith-traced pipeline.
Single retrieve, then prompt | llm | parse for full trace.
"""
from __future__ import annotations

from typing import List, Optional

from langchain_core.output_parsers import StrOutputParser

from backend.core.llm_client import get_llm
from backend.core.langchain_prompts import SUBSIDY_RAG_PROMPT
from backend.services.rag_service import rag_service
from backend.core.config import settings
from backend.core.token_tracker import token_tracker


def _format_subsidy_docs(docs: List[dict]) -> str:
    """Convert retrieved subsidy dicts to context string."""
    if not docs:
        return "No verified government scheme information was found for this query."
    parts = []
    for i, d in enumerate(docs, 1):
        parts.append(
            f"Scheme information {i}: "
            f"Scheme name: {d.get('scheme_name', 'Not specified')}. "
            f"Eligibility: {d.get('eligibility', 'Not specified')}. "
            f"Benefits: {d.get('benefits', 'Not specified')}. "
            f"Application steps: {d.get('application_steps', 'Not specified')}. "
            f"Required documents: {d.get('documents', 'Not specified')}. "
            f"Additional notes: {d.get('notes', 'Not specified')}. "
        )
    return " ".join(parts)


_SUBSIDY_CHAIN = None


def _get_subsidy_chain():
    """Cached LCEL chain: prompt | llm | parse."""
    global _SUBSIDY_CHAIN
    if _SUBSIDY_CHAIN is None:
        _SUBSIDY_CHAIN = (
            SUBSIDY_RAG_PROMPT
            | get_llm()
            | StrOutputParser()
        )
    return _SUBSIDY_CHAIN


def invoke_subsidy_rag_chain(
    query: str,
    chat_history: str = "None",
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> tuple[str, list[dict]]:
    """
    Invoke the RAG chain. Returns (response, retrieved_docs) for guardrails.
    Single retrieve, then LCEL chain for traceability.
    """
    docs = rag_service.retrieve(query, k=2)
    context = _format_subsidy_docs(docs)

    inputs = {
        "query": query,
        "chat_history": chat_history or "None",
        "context": context,
    }

    chain = _get_subsidy_chain()
    raw = chain.invoke(inputs)
    response = str(raw).strip() if raw is not None else ""

    if request_id or session_id:
        approx_in = (len(str(inputs)) + 500) // 4
        approx_out = len(response) // 4
        token_tracker.record(
            input_tokens=approx_in,
            output_tokens=approx_out,
            model=settings.TEXT_MODEL_NAME,
            request_id=request_id,
            session_id=session_id,
        )

    return response, docs
```

> **LCEL 的价值**：`prompt | llm | parser` 每一步在 LangSmith 中是独立 span，出问题可精确定位是"检索没召回"还是"生成没遵循"。

### 步骤 4：实现幻觉护栏 `backend/core/guardrails.py`

```python
"""
Guardrails for SubsidyAgent: ensure responses are grounded in retrieved docs.
Hallucination detection - flag responses that cite schemes not in retrieved data.
"""
from __future__ import annotations

from typing import List


def get_retrieved_scheme_names(retrieved_docs: List[dict]) -> set:
    """Extract scheme names from retrieved documents."""
    names = set()
    for doc in retrieved_docs:
        name = doc.get("scheme_name", "").strip()
        if name and name.lower() != "unknown scheme":
            names.add(name.lower())
            # Also add shortened/partial matches for flexible comparison
            words = name.lower().split()
            if len(words) > 1:
                names.add(" ".join(words[:2]))  # e.g. "Pradhan Mantri"
    return names


def detect_subsidy_hallucination(
    response: str,
    retrieved_docs: List[dict],
) -> tuple[bool, str]:
    """
    Check if the response mentions scheme names not present in retrieved docs.
    Returns (is_hallucinated, safe_response).
    If hallucination detected, appends a disclaimer.
    """
    response = str(response or "")
    if not retrieved_docs:
        # No docs = LLM should say "no information found"
        safe_phrases = [
            "no verified", "no information", "not found", "not available",
            "not listed", "contact the", "check with", "no specific scheme"
        ]
        if any(phrase in response.lower() for phrase in safe_phrases):
            return False, response
        disclaimer = (
            "\n\n*Note: This information could not be verified against official records. "
            "Please confirm with your local agriculture office.*"
        )
        return True, response + disclaimer

    valid_names = get_retrieved_scheme_names(retrieved_docs)
    response_lower = response.lower()

    # Check if response primarily references retrieved schemes
    for name in valid_names:
        if name in response_lower or any(w in response_lower for w in name.split()[:2]):
            # At least one retrieved scheme is mentioned - likely grounded
            return False, response

    # Response mentions schemes but none match retrieved - add disclaimer
    scheme_words = {"yojana", "scheme", "nidhi", "bima", "kisan", "pm-", "subsidy"}
    if any(w in response_lower for w in scheme_words) and len(response) > 100:
        disclaimer = (
            "\n\n*Please verify details with the official portal or agriculture department.*"
        )
        return True, response + disclaimer

    return False, response
```

> **护栏思想**：无法 100% 消灭幻觉时，就做**检测 + 显式声明**，把不确定性暴露给用户，而不是假装确定。

### 步骤 5：实现补贴专家 `backend/agents/subsidy_agent.py`

```python
"""SubsidyAgent - uses LCEL RAG chain for traced, composable pipeline."""
from __future__ import annotations

import unicodedata

from backend.agents.agri_agent_base import AgriAgentBase
from backend.services.rag_chain import invoke_subsidy_rag_chain
from backend.core.guardrails import detect_subsidy_hallucination


class SubsidyAgent(AgriAgentBase):
    """
    SubsidyAgent:
    Handles government schemes and agricultural subsidy information.
    Uses LCEL RAG chain - LangSmith-traced, composable pipeline.
    Guardrails ensure responses are grounded in retrieved docs.
    """

    name = "SubsidyAgent"

    def _sanitize_query(self, text: str) -> str:
        if not text:
            return ""
        text = unicodedata.normalize("NFKC", text)
        text = text.replace("\x00", "").replace("\u200c", "")
        return text.strip()

    def handle_query(self, query: str = None, image_path: str = None,
                     chat_history: str = None, request_id: str = None,
                     session_id: str = None, **kwargs) -> str:

        if not query or not query.strip():
            response = (
                "Please ask about a specific agricultural subsidy or government scheme. "
                "For example, drip irrigation subsidy, PM-Kisan eligibility, or equipment support schemes."
            )
            return self.respond_and_record("", response, image_path)

        query_clean = self._sanitize_query(query)

        try:
            result, retrieved_docs = invoke_subsidy_rag_chain(
                query=query_clean,
                chat_history=chat_history or "None",
                request_id=request_id,
                session_id=session_id,
            )
        except Exception:
            result = "Subsidy information could not be generated at this time."
            retrieved_docs = []

        # Guardrails: verify response is grounded in retrieved docs
        _, safe_result = detect_subsidy_hallucination(result, retrieved_docs)

        return self.respond_and_record(query_clean, safe_result, image_path)
```

> 放开 `langchain_tools.py` 中 `SubsidyAgent` 的注册，至此六大 Agent 全部就位。

### 步骤 6：验证

```powershell
curl.exe -X POST http://localhost:8000/ask/text `
  -F "query=How can I get the PM-Kisan benefit? What documents do I need?"
```

预期：回答只包含库中政策内容（金额 6000/年、所需证件等）。

幻觉对抗测试：

```powershell
curl.exe -X POST http://localhost:8000/ask/text `
  -F "query=Tell me about the Super Farmer Gold Bonus Yojana 2099"
```

预期：回答"未找到相关信息"，或附加 `*Note: This information could not be verified...*` 免责声明。

观察启动日志：首次 `[RAG] Building FAISS index...` → 之后 `[RAG] FAISS index loaded.`。

---

## 三、验收标准

| # | 检查项 | 通过标准 |
|---|--------|----------|
| 1 | 库内政策提问 | 回答内容与 `subsidies.json` 一致，无编造 |
| 2 | 库外虚构政策 | 明确说"未找到"或出现免责声明 |
| 3 | `data/faiss_index/` | 首次启动生成，二次启动走加载分支 |
| 4 | 检索日志 | 控制台可见 `[RAG]` 相关输出 |
| 5 | 更换 `subsidies.json` 并删除 `faiss_index/` | 重启后新政策可被检索（理解重建机制） |

---

## 四、常见问题排查

| 现象 | 原因与解决 |
|------|-----------|
| 首次启动卡在下载模型 | 设置 `HF_ENDPOINT=https://hf-mirror.com` 后重启 |
| 所有提问都"未找到" | 阈值 0.7 过严或查询扩词与语料语言不一致——用 `similarity_search_with_score` 打印距离调参 |
| `FAISS.load_local` 报错 | 嵌入模型版本变更后旧索引不兼容——删除 `faiss_index/` 重建 |
| 回答带 `:contentReference` 乱码 | 语料本身含脏数据，清洗 `subsidies.json` |

---

## 五、拓展任务（选做）

1. **本地化改造**（推荐）：把知识库替换为你家乡所在省份的 3~5 项真实惠农政策，完成检索调优；
2. 实现 `scripts/populate_pinecone.py`：把同一份数据灌入 Pinecone（需要免费云账号），体会云端向量库；
3. 给护栏加单元测试：构造"回答提及库外政策名"的用例，断言返回 `(True, ...+免责声明)`。

> **下一节预告**：实训 08 为系统装上"记忆"——Redis 会话管理与天气服务。
