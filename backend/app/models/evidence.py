"""
证据链四件套模型：SourceFile → DocumentPage → ExtractionRun → EvidenceSpan
实现完整的证据链追溯：原文页码、复核、审计
"""
import uuid
from typing import Optional

from sqlalchemy import String, Text, Integer, Float, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import UUIDPKMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin
from app.core.database import Base
from app.core.config import settings


class EvidenceSourceFile(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin):
    """源文件定位（domain + source_table + source_id 三元组定位源记录）
    domain: params/materials/contracts/expert/bidding/enterprise
    source_id 不加 FK，避免与各业务表强耦合
    """
    __tablename__ = "evidence_source_file"

    domain: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_table: Mapped[str] = mapped_column(String(128), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(512))
    file_key: Mapped[Optional[str]] = mapped_column(String(512))  # MinIO key
    mime_type: Mapped[Optional[str]] = mapped_column(String(128))
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)

    pages = relationship("EvidenceDocumentPage", back_populates="source_file", cascade="all, delete-orphan")
    extraction_runs = relationship("EvidenceExtractionRun", back_populates="source_file", cascade="all, delete-orphan")
    spans = relationship("EvidenceSpan", back_populates="source_file", cascade="all, delete-orphan")


class EvidenceDocumentPage(Base, UUIDPKMixin, TimestampMixin):
    """文档页（原文按页切片，供证据片段引用页码）"""
    __tablename__ = "evidence_document_page"

    source_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_source_file.id"), nullable=False, index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    char_offset_start: Mapped[Optional[int]] = mapped_column(Integer)
    char_offset_end: Mapped[Optional[int]] = mapped_column(Integer)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)

    source_file = relationship("EvidenceSourceFile", back_populates="pages")


class EvidenceExtractionRun(Base, UUIDPKMixin, TimestampMixin, CreatedByMixin):
    """LLM 提取过程追溯（记录用哪个模型/prompt 版本/parser 提取出证据）"""
    __tablename__ = "evidence_extraction_run"

    source_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_source_file.id"), nullable=False, index=True
    )
    extractor_type: Mapped[str] = mapped_column(String(64), nullable=False)  # llm/regex/ocr/manual
    model_name: Mapped[Optional[str]] = mapped_column(String(128))
    prompt_hash: Mapped[Optional[str]] = mapped_column(String(64))  # prompt 内容 SHA256 前 16 位
    parser_version: Mapped[Optional[str]] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="done", index=True)  # running/done/failed
    error: Mapped[Optional[str]] = mapped_column(Text)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)

    source_file = relationship("EvidenceSourceFile", back_populates="extraction_runs")
    spans = relationship("EvidenceSpan", back_populates="extraction_run")


class EvidenceSpan(Base, UUIDPKMixin, TimestampMixin):
    """证据片段（原文引用 + 字段命中 + 复核状态）"""
    __tablename__ = "evidence_span"

    source_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_source_file.id"), nullable=False, index=True
    )
    extraction_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_extraction_run.id"), index=True
    )
    page_number: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    quote_text: Mapped[str] = mapped_column(Text, nullable=False)  # 原文引用
    char_offset_start: Mapped[Optional[int]] = mapped_column(Integer)
    char_offset_end: Mapped[Optional[int]] = mapped_column(Integer)
    field_name: Mapped[Optional[str]] = mapped_column(String(128), index=True)  # 命中字段名 voltage/contract_amount
    confidence: Mapped[Optional[float]] = mapped_column(Float, default=0.8)
    review_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)  # pending/approved/rejected
    review_history: Mapped[Optional[dict]] = mapped_column(JSON)  # 最多 20 条复核记录
    reviewed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), index=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)

    source_file = relationship("EvidenceSourceFile", back_populates="spans")
    extraction_run = relationship("EvidenceExtractionRun", back_populates="spans")
