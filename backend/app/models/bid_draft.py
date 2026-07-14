"""
标书起草辅助模块（Phase 3 T4）

- BidTemplate：标书模板（含变量占位符 {variable}）
- BidDraft：标书草稿（按章节组织，可记录 AI 生成内容与引用证据）
"""
import enum
import uuid
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, Enum, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import (
    UUIDPKMixin,
    TimestampMixin,
    SoftDeleteMixin,
    CreatedByMixin,
)


class BidTemplateCategory(str, enum.Enum):
    """标书模板分类"""
    TECHNICAL = "technical"          # 技术方案
    COMMERCIAL = "commercial"        # 商务条款
    QUALIFICATION = "qualification"  # 资质清单
    PROJECT_CASE = "project_case"   # 项目案例
    OTHER = "other"


class BidTemplate(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin):
    """标书模板

    content 内可使用 {variable} 形式的占位符；
    variables 字段记录占位符元信息（名称/描述/默认值），便于前端渲染表单。
    """
    __tablename__ = "bid_template"

    name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    category: Mapped[BidTemplateCategory] = mapped_column(
        Enum(BidTemplateCategory),
        default=BidTemplateCategory.OTHER,
        index=True,
    )
    description: Mapped[Optional[str]] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)  # 模板内容（含变量占位符 {variable}）
    variables: Mapped[Optional[list]] = mapped_column(JSON)  # 变量列表 [{name, description, default}]
    is_active: Mapped[bool] = mapped_column(default=True)
    industry: Mapped[Optional[str]] = mapped_column(String(64), index=True)  # 行业适用


class BidDraftStatus(str, enum.Enum):
    """标书草稿状态"""
    DRAFT = "draft"            # 草稿中
    IN_REVIEW = "in_review"   # 内审中
    FINALIZED = "finalized"   # 已定稿


class BidDraft(Base, UUIDPKMixin, TimestampMixin, CreatedByMixin):
    """标书草稿

    sections 结构示例：
    [
        {
            "title": "技术方案",
            "content": "...",
            "ai_generated": true,
            "source_chunks": [
                {"chunk_id": "...", "content": "...", "page_number": 1}
            ]
        }
    ]
    """
    __tablename__ = "bid_draft"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("project.id"),
        nullable=False,
        index=True,
    )
    template_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bid_template.id"),
    )
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[BidDraftStatus] = mapped_column(
        Enum(BidDraftStatus),
        default=BidDraftStatus.DRAFT,
    )
    sections: Mapped[Optional[list]] = mapped_column(JSON)  # [{title, content, ai_generated, source_chunks[]}]
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)

    # 关联
    project = relationship("Project")
    template = relationship("BidTemplate")
