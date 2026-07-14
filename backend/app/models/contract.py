"""
合同与风险扫描模型
"""
import enum
import uuid
from typing import Optional, List

from sqlalchemy import String, Text, Date, ForeignKey, Enum, JSON, Float
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import UUIDPKMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin
from app.core.database import Base


class RiskLevel(str, enum.Enum):
    """风险等级"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ReviewStatus(str, enum.Enum):
    PENDING = "pending"
    REVIEWING = "reviewing"
    CONFIRMED = "confirmed"     # 法务确认
    REJECTED = "rejected"       # 驳回
    RESOLVED = "resolved"        # 已处置


class Contract(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin):
    """合同"""
    __tablename__ = "contract"

    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("project.id"), index=True)
    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("document.id"))
    title: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    counterparty: Mapped[Optional[str]] = mapped_column(String(128))  # 相对方
    sign_date: Mapped[Optional[any]] = mapped_column(Date)
    effective_date: Mapped[Optional[any]] = mapped_column(Date)
    expire_date: Mapped[Optional[any]] = mapped_column(Date)
    amount: Mapped[Optional[float]] = mapped_column()
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="review_status"), default=ReviewStatus.PENDING, index=True
    )
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)

    project = relationship("Project", back_populates="contracts")
    risks = relationship("ContractRisk", back_populates="contract", cascade="all, delete-orphan")


class ContractRisk(Base, UUIDPKMixin, TimestampMixin):
    """合同风险扫描结果（每条绑定证据链）"""
    __tablename__ = "contract_risk"

    contract_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("contract.id"), nullable=False, index=True)
    rule_code: Mapped[Optional[str]] = mapped_column(String(64), index=True)  # 规则编码
    rule_source: Mapped[Optional[str]] = mapped_column(String(32))  # rule_engine / llm
    category: Mapped[Optional[str]] = mapped_column(String(64), index=True)  # 付款/交付/违约/效期/资质
    level: Mapped[RiskLevel] = mapped_column(Enum(RiskLevel, name="risk_level"), index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    suggestion: Mapped[Optional[str]] = mapped_column(Text)  # 修改建议
    confidence: Mapped[Optional[float]] = mapped_column(Float)  # 置信度 0-1
    is_confirmed: Mapped[bool] = mapped_column(default=False)  # 法务是否确认
    # 证据链：引用的 chunk_id 列表 + 页码 + 原文片段
    evidence: Mapped[Optional[dict]] = mapped_column(JSON)  # [{chunk_id, page, section, snippet}]
    # 证据链：关联 evidence_span 表（不加 FK，避免跨模块强耦合）
    evidence_span_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), index=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)

    contract = relationship("Contract", back_populates="risks")
