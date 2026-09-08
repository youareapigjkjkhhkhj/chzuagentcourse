import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


class Config:
    NEBIUS_API_KEY: Optional[str] = os.environ.get("NEBIUS_API_KEY")
    DATABASE_URL: str = os.environ.get(
        "DATABASE_URL", "postgresql://user:password@localhost:5432/erp_simulation"
    )
    CLICKHOUSE_HOST: str = os.environ.get("CLICKHOUSE_HOST", "localhost")
    CLICKHOUSE_PORT: int = int(os.environ.get("CLICKHOUSE_PORT", "8123"))
    CLICKHOUSE_USER: str = os.environ.get("CLICKHOUSE_USER", "default")
    CLICKHOUSE_PASSWORD: str = os.environ.get("CLICKHOUSE_PASSWORD", "")
    CLICKHOUSE_DATABASE: str = os.environ.get("CLICKHOUSE_DATABASE", "supply_chain")
    MLFLOW_TRACKING_URI: str = os.environ.get(
        "MLFLOW_TRACKING_URI", "sqlite:///mlflow.db"
    )
    MLFLOW_EXPERIMENT_NAME: str = os.environ.get(
        "MLFLOW_EXPERIMENT_NAME", "supply-chain-orchestrator"
    )
    LLM_MODEL: str = "MiniMaxAI/MiniMax-M2.5"
    LLM_BASE_URL: str = "https://api.tokenfactory.us-central1.nebius.com/v1/"

    @classmethod
    def validate(cls) -> bool:
        if not cls.NEBIUS_API_KEY:
            raise ValueError("NEBIUS_API_KEY environment variable is not set")
        return True


config = Config()
