"""
项目状态机模型（Phase 3 T1）

- ProjectStatusTransition: 状态变更记录（审计）
- ProjectStatusRule: 可配置转移矩阵（from_status -> to_status）

设计要点：
- 状态转移校验是硬规则（确定性边界），由 ProjectStatusRule 配置
- AI 推荐仅作为辅助（非强制），不写入转移矩阵
"""
import uuid
from typing import Optional

from sqlalchemy import String, Text, Boolean, ForeignKey, Enum, JSON, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import UUIDPKMixin, TimestampMixin
from app.models.project import ProjectStatus
from app.core.database import Base


class ProjectStatusTransition(Base, UUIDPKMixin, TimestampMixin):
    """项目状态变更记录（不可篡改，用于审计追溯）

    每次项目状态流转均落库一条记录，包含：
    - from_status / to_status：流转前后状态
    - transition_by：操作人
    - reason：变更原因（可选）
    - ai_suggestion：是否采纳了 AI 推荐的下一状态
    - metadata_json：扩展字段（如 AI 推荐的置信度、备选状态等）
    """
    __tablename__ = "project_status_transition"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id"), nullable=False, index=True
    )
    from_status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"), nullable=False
    )
    to_status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"), nullable=False
    )
    transition_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id"), nullable=True, index=True
    )
    reason: Mapped[Optional[str]] = mapped_column(Text)
    ai_suggestion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)

    project = relationship("Project", backref="status_transitions")


class ProjectStatusRule(Base, UUIDPKMixin, TimestampMixin):
    """项目状态转移规则（可配置转移矩阵）

    一条记录表示一个允许的转移：from_status -> to_status
    - is_active=False 可临时禁用某条转移（不删除数据）
    - (from_status, to_status) 唯一约束，避免重复规则
    """
    __tablename__ = "project_status_rule"
    __table_args__ = (
        UniqueConstraint("from_status", "to_status", name="uq_status_rule_from_to"),
    )

    from_status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"), nullable=False, index=True
    )
    to_status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"), nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(String(256))
