from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

# Absolute path to backend/ - ensures .env is found regardless of cwd
_BASE = Path(__file__).resolve().parent.parent
_ENV_FILE = (_BASE / ".env").resolve()

class Settings(BaseSettings):
    """
    Safe configuration loader for all environment variables.
    """
    GROQ_API_KEY: str = ""
    OPENWEATHER_API_KEY: str = ""
    # llama-3.1-70b-versatile decommissioned Jan 2025 → llama-3.3-70b-versatile
    TEXT_MODEL_NAME: str = "llama-3.3-70b-versatile"
    # llama-3.2-vision-preview deprecated Apr 2025 → meta-llama/llama-4-scout-17b-16e-instruct
    VISION_MODEL_NAME: str = "meta-llama/llama-4-scout-17b-16e-instruct"

    # LangSmith observability (optional)
    # Use LANGSMITH_API_KEY (preferred) or LANGCHAIN_API_KEY - get key from smith.langchain.com
    LANGCHAIN_TRACING_V2: str = "false"
    LANGCHAIN_API_KEY: str = ""
    LANGSMITH_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "agrigpt"
    LANGSMITH_PROJECT: str = "agrigpt"

    # Pinecone (optional - falls back to FAISS if not set)
    PINECONE_API_KEY: str = ""
    PINECONE_INDEX_NAME: str = "agrigpt-subsidies"
    PINECONE_ENVIRONMENT: str = ""

    # Redis (optional - for persistent chat memory; falls back to in-memory if unset)
    REDIS_URL: str = ""

    DEBUG: bool = False

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


settings = Settings()


def langsmith_api_key() -> str:
    """LangSmith API key from LANGSMITH_API_KEY or LANGCHAIN_API_KEY (get from smith.langchain.com)."""
    return str(settings.LANGSMITH_API_KEY or settings.LANGCHAIN_API_KEY or "").strip()


def langsmith_enabled() -> bool:
    """True if LangSmith tracing should be enabled."""
    v = str(settings.LANGCHAIN_TRACING_V2 or "").strip().lower()
    key = langsmith_api_key()
    return v in ("true", "1", "yes") and bool(key)


if not settings.GROQ_API_KEY:
    print(" WARNING: GROQ_API_KEY is missing. Image/text models may fail.")
else:
    k = settings.GROQ_API_KEY.strip()
    print(f" [CONFIG] GROQ_API_KEY loaded ({len(k)} chars): {k[:8]}...{k[-4:] if len(k) > 12 else '...'}")

if not settings.TEXT_MODEL_NAME:
    print(" WARNING: TEXT_MODEL_NAME missing → using fallback.")

if not settings.VISION_MODEL_NAME:
    print(" WARNING: VISION_MODEL_NAME missing → using fallback.")

if not settings.OPENWEATHER_API_KEY:
    print(" WARNING: OPENWEATHER_API_KEY missing.")
