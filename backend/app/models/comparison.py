"""
参数偏离比对模型
"""
import enum
import uuid
from typing import Optional, List

from sqlalchemy import String, Text, ForeignKey, Enum, JSON, Float, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import UUIDPKMixin, TimestampMixin, CreatedByMixin
from app.core.database import Base


class ComparisonVerdict(str, enum.Enum):
    """比对结论"""
    MATCH = "match"           # 一致
    DEVIATION = "deviation"   # 偏离
    MISSING = "missing"       # 缺失
    EXTRA = "extra"           # 多余
    NEED_CONFIRM = "need_confirm"  # 待确认（语义近似需补证）


class ComparisonTask(Base, UUIDPKMixin, TimestampMixin, CreatedByMixin):
    """参数偏离比对任务
    支持两种选型方式：
    - 规格书文档比对：tender_doc_id + spec_doc_id
    - 产品中心选型比对：tender_doc_id + product_id（直接用产品 specs 作为响应方）
    """
    __tablename__ = "comparison_task"

    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("project.id"), index=True)
    tender_doc_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("document.id"))  # 招标文件
    spec_doc_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("document.id"))   # 规格书
    product_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("product.id"))    # 产品选型
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)  # pending/running/done/failed
    progress: Mapped[Optional[float]] = mapped_column(Float, default=0)
    report_key: Mapped[Optional[str]] = mapped_column(String(512))  # 报告 MinIO key
    summary: Mapped[Optional[dict]] = mapped_column(JSON)  # 统计：一致/偏离/缺失数量
    error: Mapped[Optional[str]] = mapped_column(Text)

    results = relationship("ComparisonResult", back_populates="task", cascade="all, delete-orphan")


class ComparisonResult(Base, UUIDPKMixin, TimestampMixin):
    """单条参数比对结果（绑定证据链）"""
    __tablename__ = "comparison_result"

    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("comparison_task.id"), nullable=False, index=True)
    param_name: Mapped[str] = mapped_column(String(256), nullable=False)
    tender_value: Mapped[Optional[str]] = mapped_column(Text)  # 招标文件中的要求
    spec_value: Mapped[Optional[str]] = mapped_column(Text)    # 规格书中的响应
    verdict: Mapped[ComparisonVerdict] = mapped_column(
        Enum(ComparisonVerdict, name="comparison_verdict"), index=True
    )
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    reason: Mapped[Optional[str]] = mapped_column(Text)  # 判断理由
    # 证据链：招标侧 + 规格侧原文引用
    tender_evidence: Mapped[Optional[dict]] = mapped_column(JSON)
    spec_evidence: Mapped[Optional[dict]] = mapped_column(JSON)
    # 证据链：关联 evidence_span 表（不加 FK，避免跨模块强耦合）
    evidence_span_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), index=True)
    # 废标风险标记（P2-11 T11.4）：
    # - True 表示该参数对应招标文件的"废标条款"（is_disqualifying=true 且 verdict != match）
    # - False / None 表示普通参数或已一致
    is_disqualifying: Mapped[Optional[bool]] = mapped_column(Boolean, default=False, index=True)

    task = relationship("ComparisonTask", back_populates="results")
