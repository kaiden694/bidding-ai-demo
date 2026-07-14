"""
通用知识库模型
- 区别于历史标书/合同案例知识库（KnowledgeBase）
- 承载企业资料、政策法规、行业标准、内部规范等通用文档
- 向量化供前台/后台/AI 助手检索
"""
import enum
import uuid
from typing import Optional, List

from pgvector.sqlalchemy import Vector
from sqlalchemy import String, Text, ForeignKey, Enum, JSON, Integer, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.core.database import Base
from app.models.base import UUIDPKMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin


class GeneralDocCategory(str, enum.Enum):
    """通用知识库分类"""
    COMPANY = "company"          # 企业资料（介绍/资质汇总/制度）
    POLICY = "policy"            # 政策法规
    STANDARD = "standard"        # 行业标准/国标
    REGULATION = "regulation"    # 内部规范/制度
    FAQ = "faq"                  # 常见问题
    OTHER = "other"


class GeneralKnowledgeBase(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin):
    """通用知识库（分类/版本/可见范围）
    可见范围区分前台可见 / 后台可见，支撑前台后台权限分层
    """
    __tablename__ = "general_knowledge_base"

    name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[GeneralDocCategory] = mapped_column(
        Enum(GeneralDocCategory, name="general_doc_category"), default=GeneralDocCategory.OTHER, index=True
    )
    source_doc_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("document.id"))
    # 可见范围: front（前台）/ back（后台）/ all（全部）
    visibility: Mapped[str] = mapped_column(String(16), default="all", index=True)
    # 标签（业务侧自定义）
    tags: Mapped[Optional[List[str]]] = mapped_column(JSON)
    version: Mapped[str] = mapped_column(String(32), default="1.0")
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)

    chunks = relationship("GeneralKnowledgeChunk", back_populates="knowledge_base", cascade="all, delete-orphan")


class GeneralKnowledgeChunk(Base, UUIDPKMixin, TimestampMixin):
    """通用知识库切块（向量化）"""
    __tablename__ = "general_knowledge_chunk"

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("general_knowledge_base.id"), nullable=False, index=True
    )
    source_doc_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("document.id"))
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[Optional[int]] = mapped_column(Integer)
    section: Mapped[Optional[str]] = mapped_column(String(256))
    table_ref: Mapped[Optional[str]] = mapped_column(String(128))
    chunk_type: Mapped[Optional[str]] = mapped_column(String(32))
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)

    embedding: Mapped[Optional[list]] = mapped_column(Vector(settings.EMBEDDING_DIM))

    knowledge_base = relationship("GeneralKnowledgeBase", back_populates="chunks")
