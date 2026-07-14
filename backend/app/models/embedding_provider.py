"""
Embedding 提供商配置（支持运行时增删，OpenAI 兼容接口）

设计要点：
- 与 LLMProvider 类似，支持运行时增删（无需重启），通过 EmbeddingClient.reload_providers() 热加载
- api_key 在生产环境应加密存储（此处保留明文列以便开发期快速调试）
- 同一时刻仅一个 provider 生效（is_active=True），更新时自动停用其他
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Integer, Boolean, DateTime, Index
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDPKMixin, TimestampMixin


class EmbeddingProvider(Base, UUIDPKMixin, TimestampMixin):
    """Embedding 提供商配置（支持运行时增删，无需重启）

    兼容 OpenAI /v1/embeddings 接口规范
    """
    __tablename__ = "embedding_provider"

    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # 唯一标识
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)  # 如 https://api.openai.com/v1
    api_key: Mapped[str] = mapped_column(String(512), nullable=False)  # 生产应加密
    model: Mapped[str] = mapped_column(String(128), nullable=False)  # 如 text-embedding-3-small / bge-m3
    dim: Mapped[int] = mapped_column(Integer, default=1024, nullable=False)  # 向量维度
    # 是否启用（同一时刻仅一个生效，更新时自动停用其他）
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # 健康检查
    is_healthy: Mapped[bool] = mapped_column(Boolean, default=True)
    last_check_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    # 元数据（可存可选参数如 encoding_format 等）
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)

    __table_args__ = (
        Index("ix_embedding_provider_active", "is_active"),
    )
