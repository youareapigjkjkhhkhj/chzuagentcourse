"""文本切分：面向中文笔记的递归字符切分。"""
from langchain_text_splitters import RecursiveCharacterTextSplitter
from src.config import settings


def get_splitter(chunk_size=None, chunk_overlap=None) -> RecursiveCharacterTextSplitter:
    """构造递归字符切分器。

    分隔符优先按 Markdown 标题 / 段落 / 中文标点断句，保证语义完整。
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size or settings.CHUNK_SIZE,
        chunk_overlap=chunk_overlap or settings.CHUNK_OVERLAP,
        separators=[
            "\n## ", "\n### ", "\n\n", "\n",
            "。", "！", "？", "；", "，",
            ". ", " ", "",
        ],
        keep_separator=True,
    )


def split_documents(documents, chunk_size=None, chunk_overlap=None):
    """将加载后的文档切分为适合检索的 chunk。"""
    return get_splitter(chunk_size, chunk_overlap).split_documents(documents)
