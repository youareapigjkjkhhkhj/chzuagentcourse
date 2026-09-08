"""嵌入模型封装：统一使用 OpenAI 兼容接口 + text-embedding-3-small。"""
from langchain_openai import OpenAIEmbeddings
from src.config import settings


def get_embeddings() -> OpenAIEmbeddings:
    """构造嵌入模型客户端。

    向量模型固定为 text-embedding-3-small（1536 维）。
    通过 OPENAI_BASE_URL 指向兼容 OpenAI 协议的代理服务。
    """
    return OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL,
        api_key=settings.OPENAI_API_KEY,
        openai_api_base=settings.OPENAI_BASE_URL,
    )
