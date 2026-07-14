"""语义反馈闭环端点（T5.4）

- POST /feedback: 记录专家修正（比对/审查结论被纠正）
- GET /feedback/stats: 反馈统计（修正率、按目标类型分组）
- POST /feedback/recall: 召回相似历史修正（供调试，主流程在 service 内调用）
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.models.feedback import FeedbackTargetType
from app.models.user import User
from app.schemas.feedback import (
    FeedbackRecordOut,
    FeedbackRecordRequest,
    FeedbackStatsOut,
    RecallRequest,
)
from app.services.feedback_service import get_feedback_service

router = APIRouter()


@router.post("", response_model=FeedbackRecordOut, status_code=201)
async def record_feedback(
    payload: FeedbackRecordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("feedback:create")),
):
    """记录专家修正（向量化修正理由，进入召回库供后续 LLM few-shot）"""
    service = get_feedback_service()
    record = await service.record_feedback(
        db,
        target_type=payload.target_type,
        target_id=payload.target_id,
        original_verdict=payload.original_verdict,
        corrected_verdict=payload.corrected_verdict,
        correction_reason=payload.correction_reason,
        context_key=payload.context_key,
        context_text=payload.context_text,
        corrected_by=current_user.id,
        metadata=payload.metadata,
    )
    return record


@router.get("/stats", response_model=FeedbackStatsOut)
async def get_stats(
    target_type: Optional[FeedbackTargetType] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("feedback:view")),
):
    """反馈闭环统计：修正率、按目标类型分组"""
    service = get_feedback_service()
    return await service.get_stats(db, target_type=target_type)


@router.post("/recall")
async def recall(
    payload: RecallRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("feedback:view")),
):
    """召回相似历史修正（供前端调试，主流程在 service 内自动调用）

    返回结构：{items: [{target_id, original_verdict, corrected_verdict, reason, context_key, score}]}
    """
    service = get_feedback_service()
    records = await service.recall_similar_feedback(
        db,
        target_type=payload.target_type,
        query_text=payload.query_text,
        context_key=payload.context_key,
        top_k=payload.top_k,
    )
    return {
        "items": [
            {
                "id": str(r.id),
                "target_id": str(r.target_id),
                "context_key": r.context_key,
                "context_text": (r.context_text or "")[:200],
                "original_verdict": r.original_verdict,
                "corrected_verdict": r.corrected_verdict,
                "correction_reason": r.correction_reason,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ]
    }
