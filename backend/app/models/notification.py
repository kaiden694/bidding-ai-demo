"""
站内信 + 邮件 + 待办任务模型（Phase 3 T2）

- Notification: 站内信
- TodoTask: 待办任务（状态变更可自动生成）
- EmailLog: 邮件发送记录

设计要点（v1.2 §13 AI 优先）：
- 待办自动生成规则可配置（见 todo_rule.py），不硬编码 if-else
- 邮件发送为异步、非阻塞，开发环境仅记录不实际发送
"""
import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, DateTime, Boolean, ForeignKey, Enum, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import UUIDPKMixin, TimestampMixin
from app.core.database import Base


class NotificationType(str, enum.Enum):
    """站内信类型"""
    TODO_CREATED = "todo_created"
    TODO_DUE_REMINDER = "todo_due_reminder"
    STATUS_CHANGED = "status_changed"
    MENTION = "mention"
    SYSTEM = "system"


class Notification(Base, UUIDPKMixin, TimestampMixin):
    """站内信"""
    __tablename__ = "notification"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    type: Mapped[NotificationType] = mapped_column(Enum(NotificationType), default=NotificationType.SYSTEM)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(default=False, index=True)
    related_project_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), index=True)
    related_entity_type: Mapped[Optional[str]] = mapped_column(String(64))  # todo/comment/contract/...
    related_entity_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))


class TodoStatus(str, enum.Enum):
    """待办状态"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class TodoTask(Base, UUIDPKMixin, TimestampMixin):
    """待办任务"""
    __tablename__ = "todo_task"
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("project.id"), index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    assignee_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), index=True)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[TodoStatus] = mapped_column(Enum(TodoStatus), default=TodoStatus.PENDING, index=True)
    source: Mapped[str] = mapped_column(String(32), default="manual")  # manual / auto
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)


class EmailLog(Base, UUIDPKMixin, TimestampMixin):
    """邮件发送记录"""
    __tablename__ = "email_log"
    to_address: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(256), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending/sent/failed
    error: Mapped[Optional[str]] = mapped_column(Text)
    related_entity_type: Mapped[Optional[str]] = mapped_column(String(64))
    related_entity_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
