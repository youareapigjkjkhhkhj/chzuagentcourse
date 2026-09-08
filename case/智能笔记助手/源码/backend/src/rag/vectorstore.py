"""FAISS 向量库管理：构建 / 加载 / 增量 / 检索 / 删除。

重要兼容性说明（Windows + 中文路径）：
    FAISS 底层的 C++ `fopen` 无法处理含非 ASCII（如中文）字符的绝对路径，
    会报 "could not open ... for writing: No such file or directory"。
    本项目目录含中文（如「智能笔记助手」），因此 save/load 采用
    `os.chdir` + 相对文件名（纯 ASCII）的方式绕过该限制，数据仍落在
    项目内的 VECTOR_DIR。配合线程锁，可在 Flask 多线程下安全使用。
"""
import os
import threading
from pathlib import Path
from langchain_community.vectorstores import FAISS
from src.config import settings
from src.rag.embeddings import get_embeddings

# 保护 chdir 的全局锁，避免多线程下切换工作目录互相干扰
_CHdir_LOCK = threading.Lock()


class VectorStoreManager:
    """对 FAISS 本地索引的读写封装，统一处理持久化路径。"""

    def __init__(self):
        self.embeddings = get_embeddings()
        self.folder = settings.VECTOR_DIR
        self.name = settings.FAISS_INDEX_NAME

    def index_file(self) -> Path:
        return self.folder / f"{self.name}.faiss"

    def exists(self) -> bool:
        """索引是否已构建。"""
        return self.index_file().exists()

    def _in_folder(self, fn):
        """在目标目录内以相对名执行 FAISS 的保存/加载，规避中文绝对路径问题。"""
        self.folder.mkdir(parents=True, exist_ok=True)
        prev = os.getcwd()
        _CHdir_LOCK.acquire()
        try:
            os.chdir(self.folder)
            return fn(".", self.name)
        finally:
            os.chdir(prev)
            _CHdir_LOCK.release()

    def build(self, documents):
        """从零构建索引（覆盖旧索引）。"""
        vs = FAISS.from_documents(documents, self.embeddings)
        self._in_folder(vs.save_local)
        return vs

    def load(self):
        """加载已持久化的索引。"""
        return self._in_folder(
            lambda d, n: FAISS.load_local(
                d,
                self.embeddings,
                index_name=n,
                allow_dangerous_deserialization=True,
            )
        )

    def add(self, documents):
        """增量写入（已存在则追加，否则新建）。"""
        if self.exists():
            vs = self.load()
            vs.add_documents(documents)
        else:
            vs = FAISS.from_documents(documents, self.embeddings)
        self._in_folder(vs.save_local)
        return vs

    def similarity_search(self, query, k=None):
        """返回 [(Document, score), ...]，score 越小越相似。"""
        vs = self.load()
        return vs.similarity_search_with_score(query, k=k or settings.TOP_K)

    def delete(self):
        """删除索引文件（笔记变更 / 删除后需重建）。"""
        for suffix in (".faiss", ".pkl"):
            p = self.folder / f"{self.name}{suffix}"
            if p.exists():
                p.unlink()
