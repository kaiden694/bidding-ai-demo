"""
审计日志模型（不可篡改，所有写操作记录）
"""
import uuid
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, JSON, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import UUIDPKMixin, TimestampMixin
from app.core.database import Base


class AuditLog(Base, UUIDPKMixin, TimestampMixin):
    """操作审计日志"""
    __tablename__ = "audit_log"

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), index=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # create/update/delete/login...
    resource: Mapped[Optional[str]] = mapped_column(String(64), index=True)      # project/contract/document...
    resource_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    ip: Mapped[Optional[str]] = mapped_column(String(64))
    user_agent: Mapped[Optional[str]] = mapped_column(String(256))
    before_value: Mapped[Optional[dict]] = mapped_column(JSON)  # 变更前
    after_value: Mapped[Optional[dict]] = mapped_column(JSON)   # 变更后
    detail: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[Optional[str]] = mapped_column(String(32), default="success")  # success/failed
