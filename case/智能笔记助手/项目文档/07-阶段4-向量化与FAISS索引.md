# 阶段 4 · 向量化与 FAISS 索引（embedding + 持久化 + 建库）

> 本阶段目标：把阶段 3 切好的 chunk 用 `text-embedding-3-small` 转成向量，存入 **FAISS** 并持久化到磁盘。引入 `embeddings.py` 与 `vectorstore.py`（含 Windows 中文路径修复），并通过 `note_service.build_index()` 串起「加载→切分→入库」全链路。**本阶段结束，你拥有了一个可持久化、可重复加载的本地向量知识库。**

---

## 4.1 目标

- 嵌入模型固定 `text-embedding-3-small`（1536 维），走 `OPENAI_BASE_URL` 兼容代理。
- FAISS 索引支持：从零构建、持久化保存、加载、增量、相似度检索、删除。
- **解决 Windows 中文路径坑**：FAISS 底层 C++ `fopen` 无法处理含中文的绝对路径，用 `os.chdir` + 相对名 + 线程锁绕过。
- **可运行验证**：`build_index()` 触发真实嵌入调用，打印 `note_count / chunk_count / vector_count`；磁盘生成 `faiss_index.faiss` + `.pkl`。

---

## 4.2 前置

- 阶段 1：`settings`（含 `EMBEDDING_MODEL`、`VECTOR_DIR`、`FAISS_INDEX_NAME`）。
- 阶段 2：`load_document()`、`note_service` 列表能力。
- 阶段 3：`split_documents()`。

---

## 4.3 核心代码

### 4.3.1 嵌入封装 `src/rag/embeddings.py`

```python
# 源码/backend/src/rag/embeddings.py:1-16（全）
"""嵌入模型封装：统一使用 OpenAI 兼容接口 + text-embedding-3-small。"""
from langchain_openai import OpenAIEmbeddings
from src.config import settings


def get_embeddings() -> OpenAIEmbeddings:
    """构造嵌入模型客户端。

    向量模型固定为 text-embedding-3-small（1536 维）。
    通过 OPENAI_BASE_URL 指向兼容 OpenAI 协议的代理服务。
    """
    return OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL,        # 行 13 → text-embedding-3-small
        api_key=settings.OPENAI_API_KEY,
        openai_api_base=settings.OPENAI_BASE_URL,  # 行 15 → 代理地址
    )
```

### 4.3.2 FAISS 管理 `src/rag/vectorstore.py`（重点：中文路径修复）

```python
# 源码/backend/src/rag/vectorstore.py:10-86（节选关键）
import os, threading
from pathlib import Path
from langchain_community.vectorstores import FAISS
from src.config import settings
from src.rag.embeddings import get_embeddings

_Chdir_LOCK = threading.Lock()                # 行 18 保护 chdir 的全局锁

class VectorStoreManager:
    def __init__(self):
        self.embeddings = get_embeddings()
        self.folder = settings.VECTOR_DIR      # 行 26
        self.name = settings.FAISS_INDEX_NAME   # 行 27

    def exists(self) -> bool:                  # 行 32
        return self.index_file().exists()

    def _in_folder(self, fn):                  # 行 36 ★ 中文路径修复核心
        self.folder.mkdir(parents=True, exist_ok=True)
        prev = os.getcwd()
        _Chdir_LOCK.acquire()
        try:
            os.chdir(self.folder)              # 进入向量目录
            return fn(".", self.name)          # 用相对名（纯 ASCII）读写
        finally:
            os.chdir(prev)                     # 行 45 还原工作目录
            _Chdir_LOCK.release()

    def build(self, documents):                # 行 48
        vs = FAISS.from_documents(documents, self.embeddings)
        self._in_folder(vs.save_local)         # 行 51 经修复后保存
        return vs

    def load(self):                            # 行 54
        return self._in_folder(
            lambda d, n: FAISS.load_local(d, self.embeddings, index_name=n,
                                          allow_dangerous_deserialization=True))

    def add(self, documents):                  # 行 65 增量写入
        if self.exists():
            vs = self.load(); vs.add_documents(documents)
        else:
            vs = FAISS.from_documents(documents, self.embeddings)
        self._in_folder(vs.save_local)
        return vs

    def similarity_search(self, query, k=None):   # 行 75
        vs = self.load()
        return vs.similarity_search_with_score(query, k=k or settings.TOP_K)

    def delete(self):                          # 行 80
        for suffix in (".faiss", ".pkl"):
            p = self.folder / f"{self.name}{suffix}"
            if p.exists(): p.unlink()
```

> **为什么必须这样写**：项目目录含中文（如「智能笔记助手」），FAISS 的 `save_local`/`load_local` 在 Windows 上把绝对路径传给 C++ `fopen`，中文路径会报 `could not open ... for writing: No such file or directory`。`os.chdir` 进目录后用相对名 `.` 写盘即可绕过。配全局锁，保证 Flask 多线程下不会互相把工作目录改乱。

### 4.3.3 建库编排 `note_service.build_index()` / `index_status()`

```python
# 源码/backend/src/services/note_service.py:72-101（节选）
def build_index() -> dict:                    # 行 72
    """全量重建 FAISS 索引：清空旧索引 -> 加载全部笔记 -> 切分 -> 入库。"""
    VectorStoreManager().delete()
    docs = []
    note_count = 0
    for meta in list_notes():
        note_count += 1
        docs.extend(load_document(str(settings.NOTES_DIR / meta["id"])))
    if not docs:
        raise RuntimeError("没有可索引的笔记，请先上传。")
    chunks = split_documents(docs)             # 阶段 3
    vs = VectorStoreManager().build(chunks)    # 阶段 4
    return {"note_count": note_count, "chunk_count": len(chunks),
            "vector_count": vs.index.ntotal}

def index_status() -> dict:                   # 行 91
    mgr = VectorStoreManager()
    notes = list_notes()
    status = {"indexed": mgr.exists(), "note_count": len(notes)}
    if mgr.exists():
        try:
            status["vector_count"] = mgr.load().index.ntotal
        except Exception:
            status["vector_count"] = None
    return status
```

---

## 4.4 实操步骤（构建知识库）

```bash
cd 智能笔记助手/源码/backend
PYTHONPATH=. .venv/Scripts/python.exe -c "
from src.services.note_service import build_index, index_status
print('构建结果:', build_index())
print('索引状态:', index_status())
"
```

> ⚠️ 此步会**真实调用嵌入 API**（`text-embedding-3-small`）。若代理返回 429 频率限制，请稍后重试，不影响代码正确性。

---

## 4.5 可运行验证（本阶段 checkpoint）

期望输出：

```
构建结果: {'note_count': 1, 'chunk_count': 1, 'vector_count': 1}
索引状态: {'indexed': True, 'note_count': 1, 'vector_count': 1}
```

并检查磁盘产物：

```bash
ls data/vector_store/
# faiss_index.faiss   faiss_index.pkl
```

**✅ 阶段 4 通过标准**：`build_index()` 返回非空 `vector_count`；`data/vector_store/` 下生成 `.faiss` 与 `.pkl`；`index_status()["indexed"]` 为 `True`。

---

## 4.6 本阶段产物

```
src/rag/embeddings.py     # ★ 新增：text-embedding-3-small 封装
src/rag/vectorstore.py    # ★ 新增：FAISS 管理（含中文路径修复）
# note_service.build_index/index_status 补齐（阶段 2 文件扩充）
data/vector_store/        # ★ 生成：faiss_index.faiss / .pkl
```

> 阶段 5 将用这个索引做「检索 + 大模型问答」。

---

## 4.7 下一步

→ [阶段 5 · 检索与问答链 →](./08-阶段5-检索与问答链.md)
