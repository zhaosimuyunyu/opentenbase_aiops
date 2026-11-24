"""Configuration management"""
import os
import re
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    """Application configuration"""

    # Database
    DB_HOST: str = os.getenv("DB_HOST", "otb-node1")
    DB_PORT: int = int(os.getenv("DB_PORT", "11003"))
    DB_USER: str = os.getenv("DB_USER", "opentenbase")
    DB_NAME: str = os.getenv("DB_NAME", "postgres")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")  # 可选，容器内 Unix socket 可能不需要
    DB_TYPE: str = os.getenv("DB_TYPE", "postgresql")  # 参考 AgentX

    # DeepSeek API (OpenAI-compatible)
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_API_BASE: str = os.getenv(
        "DEEPSEEK_API_BASE",
        "https://api.deepseek.com/v1"
    )
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    # Application
    APP_HOST: str = os.getenv("APP_HOST", "0.0.0.0")
    APP_PORT: int = int(os.getenv("APP_PORT", "8080"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    AIOPS_APPROVAL_TOKEN: str = os.getenv("AIOPS_APPROVAL_TOKEN", "")
    AIOPS_APPROVER_ID: str = os.getenv("AIOPS_APPROVER_ID", "local-operator")
    AIOPS_AUTO_AUDIT_ENABLED: bool = (
        os.getenv("AIOPS_AUTO_AUDIT_ENABLED", "false").lower()
        in {"1", "true", "yes", "on"}
    )
    AIOPS_AUTO_AUDIT_INTERVAL_SECONDS: int = max(
        60, int(os.getenv("AIOPS_AUTO_AUDIT_INTERVAL_SECONDS", "900"))
    )
    AIOPS_AUTO_AUDIT_TABLE = os.getenv("AIOPS_AUTO_AUDIT_TABLE", "").strip() or None
    if AIOPS_AUTO_AUDIT_TABLE and not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", AIOPS_AUTO_AUDIT_TABLE
    ):
        raise ValueError("AIOPS_AUTO_AUDIT_TABLE must use schema.table format")

    # Vector Store
    CHROMA_PERSIST_DIRECTORY: str = os.getenv(
        "CHROMA_PERSIST_DIRECTORY",
        "./data/embeddings"
    )

    # SiliconFlow Embeddings (BGE-M3)
    EMBEDDING_API_KEY: str = os.getenv("EMBEDDING_API_KEY", "")
    EMBEDDING_API_BASE: str = os.getenv(
        "EMBEDDING_API_BASE",
        "https://api.siliconflow.cn/v1"
    )
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    EMBEDDING_DIMENSION: int = int(os.getenv("EMBEDDING_DIMENSION", "1024"))

    # Monitoring
    HEALTH_CHECK_INTERVAL: int = int(os.getenv("HEALTH_CHECK_INTERVAL", "60"))
    SLOW_QUERY_THRESHOLD_MS: int = int(
        os.getenv("SLOW_QUERY_THRESHOLD_MS", "1000")
    )

    @classmethod
    def get_db_connection_string(cls) -> str:
        """Get PostgreSQL connection string"""
        password_part = f":{cls.DB_PASSWORD}" if cls.DB_PASSWORD else ""
        return (
            f"postgresql://{cls.DB_USER}{password_part}"
            f"@{cls.DB_HOST}:{cls.DB_PORT}/{cls.DB_NAME}"
        )

    @classmethod
    def validate(cls) -> bool:
        """Validate required configuration"""
        required = [
            cls.DB_HOST,
            cls.DB_USER,
            cls.DEEPSEEK_API_KEY
        ]
        return all(required)
