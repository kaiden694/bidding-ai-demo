"""
AI 助手会话模型
- 会话（多轮对话）
- 消息（含 RAG 证据）
- 区分前台/后台 scope
"""
import enum
import uuid
from typing import Optional, List

from sqlalchemy import String, Text, ForeignKey, Enum, JSON, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPKMixin, TimestampMixin, SoftDeleteMixin


class AssistantScope(str, enum.Enum):
    """助手服务范围：区分前台/后台"""
    FRONT = "front"   # 前台用户（招投标/合同业务咨询）
    BACK = "back"      # 后台用户（管理/配置咨询）
    ALL = "all"        # 全部知识库可见


class AssistantConversation(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin):
    """助手会话"""
    __tablename__ = "assistant_conversation"

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    scope: Mapped[AssistantScope] = mapped_column(
        Enum(AssistantScope, name="assistant_scope"), default=AssistantScope.ALL, index=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), index=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)

    messages = relationship("AssistantMessage", back_populates="conversation", cascade="all, delete-orphan")


class AssistantMessage(Base, UUIDPKMixin, TimestampMixin):
    """助手消息（含 RAG 证据）"""
    __tablename__ = "assistant_message"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assistant_conversation.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)  # user / assistant / system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # RAG 召回的证据（仅 assistant 消息有）
    evidence: Mapped[Optional[List[dict]]] = mapped_column(JSON)
    # 使用的 token 数（成本追踪）
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)

    conversation = relationship("AssistantConversation", back_populates="messages")
