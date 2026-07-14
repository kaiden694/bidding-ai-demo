"""语义反馈闭环 Schema"""
import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from app.models.feedback import FeedbackTargetType


class FeedbackRecordRequest(BaseModel):
    """记录专家修正（参数偏离比对 / 合同风险审查 结论被专家纠正）"""
    target_type: FeedbackTargetType
    target_id: uuid.UUID
    context_key: Optional[str] = None  # comparison: param_name; contract: clause_type/risk_dimension
    context_text: Optional[str] = None  # 参数名+值 或 条款片段（与 reason 一起向量化）
    original_verdict: str
    corrected_verdict: str
    correction_reason: str
    metadata: Optional[dict] = None


class FeedbackRecordOut(BaseModel):
    id: uuid.UUID
    target_type: FeedbackTargetType
    target_id: uuid.UUID
    context_key: Optional[str]
    context_text: Optional[str]
    original_verdict: str
    corrected_verdict: str
    correction_reason: str
    corrected_by: Optional[uuid.UUID]
    is_active: bool
    metadata_json: Optional[dict] = None
    created_at: datetime

    class Config:
        from_attributes = True


class FeedbackStatsOut(BaseModel):
    total: int
    active: int
    by_target_type: dict
    correction_rate: float


class RecallRequest(BaseModel):
    """召回相似历史修正（用于 LLM Prompt few-shot，主要供内部 service 调用）"""
    target_type: FeedbackTargetType
    query_text: str
    context_key: Optional[str] = None
    top_k: int = 3
