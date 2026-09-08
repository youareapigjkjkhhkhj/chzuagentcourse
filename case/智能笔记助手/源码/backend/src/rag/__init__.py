"""RAG 核心子模块：加载 / 切分 / 嵌入 / 向量库 / 问答链。"""
from src.rag.embeddings import get_embeddings
from src.rag.loader import load_document, is_supported
from src.rag.splitter import split_documents, get_splitter
from src.rag.vectorstore import VectorStoreManager
from src.rag.chain import get_llm, build_prompt, format_docs, PROMPT_TEMPLATE

__all__ = [
    "get_embeddings",
    "load_document",
    "is_supported",
    "split_documents",
    "get_splitter",
    "VectorStoreManager",
    "get_llm",
    "build_prompt",
    "format_docs",
    "PROMPT_TEMPLATE",
]
