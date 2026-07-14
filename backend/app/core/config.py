"""
集中式配置：从环境变量加载，pydantic-settings 校验
"""
from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- 应用 ----
    APP_NAME: str = "smart-bidding-ai-workbench"
    APP_ENV: str = "dev"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_LOG_LEVEL: str = "INFO"

    # ---- 安全 ----
    SECRET_KEY: str = "dev-only-change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_EXPIRE_MINUTES: int = 120
    JWT_REFRESH_EXPIRE_DAYS: int = 7
    # 字段级加密密钥（AES-256-GCM，base64 编码的 32 字节）
    # 生产环境必须配置；未配置时从 SECRET_KEY 派生（仅开发可用）
    ENCRYPTION_KEY: str = ""

    # ---- PostgreSQL ----
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "sbaw"
    POSTGRES_USER: str = "sbaw"
    POSTGRES_PASSWORD: str = "sbaw_change_me"
    POSTGRES_POOL_SIZE: int = 10
    POSTGRES_MAX_OVERFLOW: int = 20

    # ---- Redis ----
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0

    # ---- MinIO ----
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minio"
    MINIO_SECRET_KEY: str = "minio_change_me"
    MINIO_BUCKET: str = "sbaw-files"
    MINIO_SECURE: bool = False

    # ---- LLM (OpenAI 兼容) ----
    LLM_BASE_URL: str = "http://localhost:8000/v1"
    LLM_API_KEY: str = "not-required-for-local"
    LLM_MODEL: str = "qwen2.5-14b-instruct"
    LLM_TIMEOUT: int = 120
    LLM_MAX_RETRIES: int = 3
    LLM_FALLBACK_MODELS: str = ""

    # ---- Embedding ----
    EMBEDDING_BASE_URL: str = "http://localhost:8000/v1"
    EMBEDDING_API_KEY: str = "not-required-for-local"
    EMBEDDING_MODEL: str = "bge-m3"
    EMBEDDING_DIM: int = 1024

    # ---- Reranker ----
    RERANKER_MODEL: str = "bge-reranker-v2-m3"
    RERANKER_TOP_K: int = 5

    # ---- RAG ----
    RAG_CHUNK_SIZE: int = 512
    RAG_CHUNK_OVERLAP: int = 64
    RAG_RETRIEVE_TOP_K: int = 20

    # ---- Celery ----
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ---- CORS ----
    CORS_ORIGINS: str = "http://localhost:5173"

    # ---- OpenTelemetry ----
    # 默认 false：dev 环境禁用，避免未装依赖时报错；生产环境置 true
    OTEL_ENABLED: bool = False
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://otel-collector:4317"
    OTEL_SERVICE_NAME: str = "sbaw-backend"

    # ---- 派生属性 ----
    @property
    def CORS_ORIGINS_LIST(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def LLM_FALLBACK_MODELS_LIST(self) -> List[str]:
        return [m.strip() for m in self.LLM_FALLBACK_MODELS.split(",") if m.strip()]

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def SYNC_DATABASE_URL(self) -> str:
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def REDIS_URL(self) -> str:
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
