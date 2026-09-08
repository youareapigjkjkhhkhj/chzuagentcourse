"""文档加载器：支持 .txt / .md(.markdown) / .pdf，并补全来源元数据。"""
from pathlib import Path
from langchain_community.document_loaders import TextLoader, PyPDFLoader
from src.config import settings

SUPPORTED_EXT = {".txt", ".md", ".markdown", ".pdf"}


def is_supported(filename: str) -> bool:
    """判断文件扩展名是否被支持。"""
    return Path(filename).suffix.lower() in SUPPORTED_EXT


def load_document(path: str):
    """加载单个笔记文件为 LangChain Document 列表。

    统一写入 metadata["source"] / ["note_id"]，供检索溯源使用。
    """
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        loader = PyPDFLoader(path)
    elif ext in (".txt", ".md", ".markdown"):
        loader = TextLoader(path, encoding="utf-8", autodetect_encoding=True)
    else:
        raise ValueError(f"不支持的文件类型: {ext}（仅支持 {sorted(SUPPORTED_EXT)}）")

    docs = loader.load()
    name = Path(path).name
    for d in docs:
        d.metadata["source"] = name
        d.metadata["note_id"] = name
    return docs
