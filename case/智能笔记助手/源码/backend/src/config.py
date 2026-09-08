"""全局配置：从 .env 读取，提供绝对路径，避免工作目录依赖。"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载项目根目录（backend/）下的 .env
load_dotenv()

# config.py 位于 backend/src/，上溯两级得到 backend/ 作为项目根
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA = BASE_DIR / "data"


class Settings:
    """集中式配置对象，所有模块统一从此处取值。"""

    def __init__(self):
        # ---- 项目根（backend/）----
        self.BASE_DIR = BASE_DIR

        # ---- 大模型 ----
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
        self.OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-5-mini")
        self.EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

        # ---- 服务 ----
        self.APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
        self.APP_PORT = int(os.getenv("APP_PORT", "5000"))
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

        # ---- 路径（绝对化，避免 cwd 依赖）----
        self.DATA_DIR = Path(os.getenv("DATA_DIR", str(DEFAULT_DATA)))
        self.NOTES_DIR = Path(os.getenv("NOTES_DIR", str(DEFAULT_DATA / "notes")))
        self.VECTOR_DIR = Path(os.getenv("VECTOR_DIR", str(DEFAULT_DATA / "vector_store")))
        self.FAISS_INDEX_NAME = os.getenv("FAISS_INDEX_NAME", "faiss_index")

        # ---- RAG 参数 ----
        self.CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
        self.CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "120"))
        self.TOP_K = int(os.getenv("TOP_K", "4"))

        # ---- 自动建目录 ----
        self.NOTES_DIR.mkdir(parents=True, exist_ok=True)
        self.VECTOR_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
