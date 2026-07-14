"""
语义反馈闭环模型

- FeedbackRecord: 比对/合同审查的专家修正记录，向量化后供后续召回形成 few-shot
- QualificationAlert: 资质预警记录（定时任务扫描写入）

设计要点（v1.2 §13 AI 优先）：
- 修正理由（correction_reason）通过 Embedding 向量化，作为可演化的知识资产
- 比对/审查服务通过向量召回相似历史修正，作为 LLM Prompt 的 few-shot 示例
- 不写硬规则映射，全部走语义召回
"""
import enum
import uuid
from datetime import date
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import String, Text, Date, ForeignKey, Enum, JSON, Float, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.database import Base
from app.models.base import UUIDPKMixin, TimestampMixin


class FeedbackTargetType(str, enum.Enum):
    """反馈目标类型"""
    COMPARISON = "comparison"   # 参数偏离比对
    CONTRACT = "contract"        # 合同风险审查


class FeedbackRecord(Base, UUIDPKMixin, TimestampMixin):
    """专家修正记录（向量化修正理由，供后续召回形成 few-shot）

    使用场景：
    - 比对结果被专家纠正：target_type=comparison, target_id=ComparisonResult.id
      original_verdict=deviation, corrected_verdict=match, reason="两侧数值在容差范围内"
    - 合同风险被专家纠正：target_type=contract, target_id=ContractRisk.id
      original_verdict=high, corrected_verdict=low, reason="该条款属于行业惯例，非实际风险"
    """
    __tablename__ = "feedback_record"

    target_type: Mapped[FeedbackTargetType] = mapped_column(
        Enum(FeedbackTargetType, name="feedback_target_type"), index=True
    )
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)  # 不加 FK，避免跨表强耦合
    # 业务上下文键：用于召回时按相同参数/条款聚合
    # - comparison: param_name
    # - contract: clause_type / risk_dimension
    context_key: Mapped[Optional[str]] = mapped_column(String(256), index=True)
    # 上下文文本（参数名+值，或条款片段），与 correction_reason 一起向量化
    context_text: Mapped[Optional[str]] = mapped_column(Text)
    original_verdict: Mapped[str] = mapped_column(String(64), nullable=False)
    corrected_verdict: Mapped[str] = mapped_column(String(64), nullable=False)
    correction_reason: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), index=True)
    # 修正理由 + 上下文的向量（用于语义召回相似历史修正）
    embedding: Mapped[Optional[list]] = mapped_column(Vector(settings.EMBEDDING_DIM))
    # 是否启用（被采纳的修正才进入召回库）
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)
    # === 校准缓存相关字段（v1.2 §13 校准缓存覆盖）===
    # feedback_type: calibration/structure_recognition/product_name/judgment_calibration，兼容旧数据 NULL
    feedback_type: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    # 校准判定结果（match/deviation/missing/extra/need_confirm）
    judgment: Mapped[Optional[str]] = mapped_column(String(64))
    # 校准置信度
    calibration_confidence: Mapped[Optional[float]] = mapped_column(Float)
    # 校准范围（param_name 或 clause_type）
    calibration_scope: Mapped[Optional[str]] = mapped_column(String(128), index=True)


class QualificationAlert(Base, UUIDPKMixin, TimestampMixin):
    """资质预警记录（定时任务每日扫描写入）

    - 同一资质同一天仅生成一条预警（unique: qualification_id + alert_date）
    - severity: warning(≤30天) / critical(≤7天) / expired(已过期)
    """
    __tablename__ = "qualification_alert"

    qualification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("qualification.id"), nullable=False, index=True
    )
    alert_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    expire_date: Mapped[Optional[date]] = mapped_column(Date)
    days_remaining: Mapped[int] = mapped_column(nullable=False)  # 负值表示已过期天数
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # warning/critical/expired
    notified: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否已通知（Phase 3 接通知中心）
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)
