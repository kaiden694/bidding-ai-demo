"""
协作评论模型（Phase 3 T6）

- Comment: 评论主体（支持嵌套回复，parent_id 自引用）
- Mention: @提及记录（评论中 @username 触发，配合 NotificationService 发送站内信）

设计要点：
- entity_type + entity_id 多态关联（contract/document/comparison/qualification/project），
  不加 FK，避免跨表强耦合
- parent_id 自引用支持无限层级嵌套回复
- AI 分析结果（ai_sentiment / ai_keywords）可选字段，不阻塞评论创建
- 软删除（is_deleted=True），不级联删除回复
"""
import enum
import uuid
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, Enum, JSON, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import UUIDPKMixin, TimestampMixin, SoftDeleteMixin


class CommentEntityType(str, enum.Enum):
    """评论关联实体类型（多态）"""
    CONTRACT = "contract"          # 合同
    DOCUMENT = "document"          # 文档
    COMPARISON = "comparison"      # 参数偏离比对
    QUALIFICATION = "qualification"  # 资质
    PROJECT = "project"            # 项目


class Comment(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin):
    """协作评论（支持嵌套回复）

    - entity_type + entity_id: 多态关联，可指向 contract/document/comparison/...
    - parent_id: 自引用 FK，构成评论树（无限层级）
    - author_id: 评论作者（FK → user.id）
    - ai_sentiment / ai_keywords: AI 分析结果（可选，不阻塞创建）
    """
    __tablename__ = "comment"

    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id"), index=True
    )
    entity_type: Mapped[CommentEntityType] = mapped_column(
        Enum(CommentEntityType), index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("comment.id"), index=True
    )

    # AI 分析结果（可选，由 comment_service.analyze_comment 异步写入）
    ai_sentiment: Mapped[Optional[str]] = mapped_column(String(32))  # positive/neutral/negative
    ai_keywords: Mapped[Optional[list]] = mapped_column(JSON)  # 提取的关键问题
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)

    # 自引用关系：parent（多对一）+ replies（一对多）
    parent = relationship(
        "Comment", remote_side="Comment.id", back_populates="replies"
    )
    replies = relationship(
        "Comment", back_populates="parent", order_by="Comment.created_at"
    )


class Mention(Base, UUIDPKMixin, TimestampMixin):
    """@提及记录

    每条评论中每个 @username 对应一条 Mention 记录。
    is_notified 标记是否已发送站内信（避免重复通知）。
    """
    __tablename__ = "mention"

    comment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("comment.id"), nullable=False, index=True
    )
    mentioned_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True
    )
    is_notified: Mapped[bool] = mapped_column(Boolean, default=False)
