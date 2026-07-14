"""
文档与知识库切块模型（pgvector 向量存储）
"""
import enum
import uuid
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import String, Text, Integer, ForeignKey, Enum, JSON, Float, Index, Boolean
from sqlalchemy.dialects.postgresql import UUID, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.models.base import UUIDPKMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin
from app.core.database import Base


class DocumentType(str, enum.Enum):
    """文档类型"""
    TENDER = "tender"               # 招标文件
    BID = "bid"                     # 标书
    SPEC = "spec"                  # 规格书
    CONTRACT = "contract"           # 合同
    QUALIFICATION = "qualification" # 资质证书
    ATTACHMENT = "attachment"       # 附件
    KNOWLEDGE = "knowledge"         # 知识库文档
    OTHER = "other"


class DocParseStatus(str, enum.Enum):
    PENDING = "pending"
    PARSING = "parsing"
    DONE = "done"
    FAILED = "failed"


class Document(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin):
    """原始文档"""
    __tablename__ = "document"

    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("project.id"), index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    doc_type: Mapped[DocumentType] = mapped_column(
        Enum(DocumentType, name="document_type"), default=DocumentType.OTHER, index=True
    )
    file_key: Mapped[str] = mapped_column(String(512), nullable=False)  # MinIO 对象 key
    file_size: Mapped[Optional[int]] = mapped_column(Integer)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128))
    page_count: Mapped[Optional[int]] = mapped_column(Integer)
    parse_status: Mapped[DocParseStatus] = mapped_column(
        Enum(DocParseStatus, name="doc_parse_status"), default=DocParseStatus.PENDING, index=True
    )
    parse_error: Mapped[Optional[str]] = mapped_column(Text)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)  # 去重

    project = relationship("Project", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base, UUIDPKMixin, TimestampMixin):
    """文档切块（向量存储 + 全文检索）
    每条结论引用 chunk_id + 页码 + 表格定位，形成证据链
    """
    __tablename__ = "document_chunk"

    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("document.id"), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)  # 块序号
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[Optional[int]] = mapped_column(Integer)
    section: Mapped[Optional[str]] = mapped_column(String(256))  # 章节
    table_ref: Mapped[Optional[str]] = mapped_column(String(128))  # 表格定位
    chunk_type: Mapped[Optional[str]] = mapped_column(String(32))  # text / table / heading
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)

    # 向量列（pgvector）
    embedding: Mapped[Optional[list]] = mapped_column(Vector(settings.EMBEDDING_DIM))

    # 全文检索（tsvector，Phase 1 暂用 ILIKE/pg_trgm，Phase 2 优化）
    # tsv: Mapped[Optional[str]] = mapped_column(TSVECTOR)

    document = relationship("Document", back_populates="chunks")

    __table_args__ = (
        Index("ix_document_chunk_doc_idx", "document_id", "chunk_index"),
    )


# 知识库切块（与文档切块分离，便于知识库管理）
class KnowledgeChunk(Base, UUIDPKMixin, TimestampMixin):
    """历史知识库切块（专家经验/范本/历史标书片段）"""
    __tablename__ = "knowledge_chunk"

    knowledge_base_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("knowledge_base.id"), index=True)
    source_doc_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("document.id"))
    title: Mapped[Optional[str]] = mapped_column(String(256), index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(64), index=True)  # 标书/合同/经验/范本
    tags: Mapped[Optional[dict]] = mapped_column(JSON)  # 业务标签
    page_number: Mapped[Optional[int]] = mapped_column(Integer)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)

    embedding: Mapped[Optional[list]] = mapped_column(Vector(settings.EMBEDDING_DIM))

    knowledge_base = relationship("KnowledgeBase", back_populates="chunks")


class KnowledgeBase(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin):
    """知识库（分类/版本）"""
    __tablename__ = "knowledge_base"

    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(32), default="1.0")
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    # 标签（业务侧自定义）
    tags: Mapped[Optional[list]] = mapped_column(JSON)
    # 元数据：导入/重建进度等
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)

    chunks = relationship("KnowledgeChunk", back_populates="knowledge_base")
