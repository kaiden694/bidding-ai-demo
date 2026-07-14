"""
LLM 提供商配置 + 用量日志（Phase 3 T3：多 LLM 负载均衡）

设计要点：
- LLMProvider 支持运行时增删（无需重启），通过 LLMClient.reload_providers() 热加载
- api_key 在生产环境应加密存储（此处保留明文列以便开发期快速调试）
- 熔断器：连续失败 >= 3 次进入熔断期（circuit_breaker_until > now 期间跳过）
- LLMUsageLog 每次调用异步写入，不阻塞主响应
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Integer, Boolean, ForeignKey, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDPKMixin, TimestampMixin


class LLMProvider(Base, UUIDPKMixin, TimestampMixin):
    """LLM 提供商配置（支持运行时增删，无需重启）"""
    __tablename__ = "llm_provider"

    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # 唯一标识
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    api_key: Mapped[str] = mapped_column(String(512), nullable=False)  # 生产应加密
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, default=1)  # 负载权重
    is_healthy: Mapped[bool] = mapped_column(Boolean, default=True)
    last_check_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # 是否启用
    # 健康检查统计
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    # 熔断状态（circuit_breaker_until > now 时跳过该 provider）
    circuit_breaker_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # 元数据
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)


class LLMUsageLog(Base, UUIDPKMixin, TimestampMixin):
    """LLM 用量日志（每次 chat/chat_stream 调用异步写入）"""
    __tablename__ = "llm_usage_log"

    provider_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("llm_provider.id"), index=True
    )
    provider_name: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    model: Mapped[Optional[str]] = mapped_column(String(128))
    # 请求信息
    messages_count: Mapped[Optional[int]] = mapped_column(Integer)
    tokens_in: Mapped[Optional[int]] = mapped_column(Integer)
    tokens_out: Mapped[Optional[int]] = mapped_column(Integer)
    # 性能
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[Optional[str]] = mapped_column(Text)
    # 请求类型（chat/chat_stream/embedding）
    request_type: Mapped[Optional[str]] = mapped_column(String(32), index=True)

    __table_args__ = (
        Index("ix_llm_usage_log_created_at", "created_at"),
    )
