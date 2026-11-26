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
    AIOPS_REPAIR_DB_USER: str = os.getenv("AIOPS_REPAIR_DB_USER", "")
    AIOPS_REPAIR_DB_PASSWORD: str = os.getenv("AIOPS_REPAIR_DB_PASSWORD", "")
    AIOPS_REPAIR_FUNCTION_ENABLED: bool = (
        os.getenv("AIOPS_REPAIR_FUNCTION_ENABLED", "false").lower()
        in {"1", "true", "yes", "on"}
    )
    AIOPS_REPAIR_FUNCTION_SCHEMA: str = os.getenv("AIOPS_REPAIR_FUNCTION_SCHEMA", "aiops_admin")
    AIOPS_REPAIR_FUNCTION_NAME: str = os.getenv("AIOPS_REPAIR_FUNCTION_NAME", "analyze_table")
    AIOPS_CANCEL_QUERY_ENABLED: bool = (
        os.getenv("AIOPS_CANCEL_QUERY_ENABLED", "false").lower()
        in {"1", "true", "yes", "on"}
    )
    AIOPS_AUTO_REPAIR_ENABLED: bool = (
        os.getenv("AIOPS_AUTO_REPAIR_ENABLED", "false").lower()
        in {"1", "true", "yes", "on"}
    )
    AIOPS_AUTO_REPAIR_TARGETS = tuple(dict.fromkeys(
        part.strip() for part in os.getenv("AIOPS_AUTO_REPAIR_TARGETS", "").split(",")
        if part.strip()
    ))
    for target in AIOPS_AUTO_REPAIR_TARGETS:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", target):
            raise ValueError("AIOPS_AUTO_REPAIR_TARGETS must contain comma-separated schema.table names")

    @property
    def audit_target(self):
        return {"host": self.DB_HOST, "port": self.DB_PORT, "database": self.DB_NAME}

    # DeepSeek API (OpenAI-compatible)
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_API_BASE: str = os.getenv(
        "DEEPSEEK_API_BASE",
        "https://api.deepseek.com/v1"
    )
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    AIOPS_SAFETY_REVIEW_MODEL: str = os.getenv("AIOPS_SAFETY_REVIEW_MODEL", "")
    AIOPS_SAFETY_REVIEW_API_KEY: str = os.getenv("AIOPS_SAFETY_REVIEW_API_KEY", "")
    AIOPS_SAFETY_REVIEW_API_BASE: str = os.getenv("AIOPS_SAFETY_REVIEW_API_BASE", "")
    AIOPS_SAFETY_REVIEW_PROVIDER: str = os.getenv("AIOPS_SAFETY_REVIEW_PROVIDER", "")
    DEEPSEEK_TIMEOUT_SECONDS: float = float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "45"))
    AIOPS_AI_AUDIT_TIMEOUT_SECONDS: float = max(
        10.0, float(os.getenv("AIOPS_AI_AUDIT_TIMEOUT_SECONDS", "120"))
    )
    AIOPS_HEALTH_AUDIT_HTTP_TIMEOUT_SECONDS: float = float(
        os.getenv("AIOPS_HEALTH_AUDIT_HTTP_TIMEOUT_SECONDS", "210")
    )
    AIOPS_COLLECTION_STATEMENT_TIMEOUT_MS: int = max(
        250, int(os.getenv("AIOPS_COLLECTION_STATEMENT_TIMEOUT_MS", "2500"))
    )
    AIOPS_COLLECTION_LOCK_TIMEOUT_MS: int = max(
        100, int(os.getenv("AIOPS_COLLECTION_LOCK_TIMEOUT_MS", "750"))
    )
    AIOPS_PG_CLEAN_MIN_AGE_SECONDS: int = max(
        1, int(os.getenv("AIOPS_PG_CLEAN_MIN_AGE_SECONDS", "10"))
    )

    # Application
    APP_HOST: str = os.getenv("APP_HOST", "0.0.0.0")
    APP_PORT: int = int(os.getenv("APP_PORT", "8080"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    AIOPS_APPROVAL_TOKEN: str = os.getenv("AIOPS_APPROVAL_TOKEN", "")
    AIOPS_APPROVER_TOKENS: str = os.getenv("AIOPS_APPROVER_TOKENS", "")
    AIOPS_APPROVER_ID: str = os.getenv("AIOPS_APPROVER_ID", "local-operator")
    AIOPS_AUTO_AUDIT_ENABLED: bool = (
        os.getenv("AIOPS_AUTO_AUDIT_ENABLED", "false").lower()
        in {"1", "true", "yes", "on"}
    )
    AIOPS_AUTO_AUDIT_INTERVAL_SECONDS: int = max(
        60, int(os.getenv("AIOPS_AUTO_AUDIT_INTERVAL_SECONDS", "900"))
    )
    AIOPS_AUTO_AUDIT_RETRY_MAX_SECONDS: int = max(
        60, int(os.getenv("AIOPS_AUTO_AUDIT_RETRY_MAX_SECONDS", "3600"))
    )
    AIOPS_AUTO_AUDIT_TABLE = os.getenv("AIOPS_AUTO_AUDIT_TABLE", "").strip() or None
    AIOPS_DATA_NODE_TABLE_LIMIT = int(os.getenv("AIOPS_DATA_NODE_TABLE_LIMIT", "200"))
    AIOPS_SLOW_QUERY_LOG_LOOKBACK_SECONDS = max(
        60, int(os.getenv("AIOPS_SLOW_QUERY_LOG_LOOKBACK_SECONDS", "900"))
    )
    AIOPS_DISTRIBUTED_ENABLED: bool = (
        os.getenv("AIOPS_DISTRIBUTED_ENABLED", "true").lower()
        in {"1", "true", "yes", "on"}
    )
    if AIOPS_DATA_NODE_TABLE_LIMIT < 1:
        raise ValueError("AIOPS_DATA_NODE_TABLE_LIMIT must be positive")
    AIOPS_AUTO_AUDIT_TARGETS = tuple(dict.fromkeys(
        part.strip() for part in AIOPS_AUTO_AUDIT_TABLE.split(",")
    )) if AIOPS_AUTO_AUDIT_TABLE else (None,)
    for target in AIOPS_AUTO_AUDIT_TARGETS:
        if target is not None and not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", target
        ):
            raise ValueError("AIOPS_AUTO_AUDIT_TABLE must contain comma-separated schema.table names")
    if AIOPS_AUTO_REPAIR_ENABLED:
        if not AIOPS_AUTO_REPAIR_TARGETS:
            raise ValueError("AIOPS_AUTO_REPAIR_TARGETS is required when automatic repair is enabled")
        if not AIOPS_REPAIR_FUNCTION_ENABLED:
            raise ValueError("Automatic repair requires the administrator repair function")
        if not AIOPS_REPAIR_DB_USER or AIOPS_REPAIR_DB_USER == DB_USER:
            raise ValueError("Automatic repair requires a separate non-superuser repair account")

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
