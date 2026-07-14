"""
招投标项目模型 + 10 状态机
"""
import enum
import uuid
from datetime import date
from typing import Optional, List

from sqlalchemy import String, Text, Date, ForeignKey, Enum, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import UUIDPKMixin, TimestampMixin, SoftDeleteMixin, TenantMixin, CreatedByMixin
from app.core.database import Base


class ProjectStatus(str, enum.Enum):
    """招投标 10 状态机"""
    PREPARATION = "preparation"          # 筹备
    APPROVED = "approved"                # 立项
    FILE_PARSING = "file_parsing"        # 文件解析
    PLAN_DESIGN = "plan_design"          # 方案规划
    BID_DRAFTING = "bid_drafting"        # 标书起草
    INTERNAL_REVIEW = "internal_review" # 内审
    SUBMITTED = "submitted"              # 投递
    EVALUATION = "evaluation"            # 评标
    AWARDED = "awarded"                  # 中标
    LOST = "lost"                        # 落标
    ARCHIVED = "archived"                # 归档


class Project(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin):
    """招投标项目"""
    __tablename__ = "project"

    name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    code: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True)
    client: Mapped[Optional[str]] = mapped_column(String(128))  # 甲方
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"), default=ProjectStatus.PREPARATION, index=True
    )
    bid_deadline: Mapped[Optional[date]] = mapped_column(Date)
    contract_amount: Mapped[Optional[float]] = mapped_column()
    industry: Mapped[Optional[str]] = mapped_column(String(64))  # 行业（插件化）
    description: Mapped[Optional[str]] = mapped_column(Text)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)  # 扩展字段

    documents = relationship("Document", back_populates="project", cascade="all, delete-orphan")
    contracts = relationship("Contract", back_populates="project", cascade="all, delete-orphan")
    milestones = relationship("Milestone", back_populates="project", cascade="all, delete-orphan")


class Milestone(Base, UUIDPKMixin, TimestampMixin):
    """里程碑/待办"""
    __tablename__ = "milestone"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("project.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    due_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    is_done: Mapped[bool] = mapped_column(default=False)
    assignee_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"))

    project = relationship("Project", back_populates="milestones")
