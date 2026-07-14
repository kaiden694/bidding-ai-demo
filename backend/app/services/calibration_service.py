"""校准缓存服务：相似度 > 阈值直接采用历史判定，跳过 LLM

参考 lib-v0.2 ai_comparator.py 的 _find_similar_calibrations：
- 用 pgvector ANN 召回 Top-K 历史校准
- 相似度 > 阈值（默认 0.90）直接采用历史判定
- 阈值作为 ExpertMemory 可调经验值（key=calibration_threshold）

AI-first 原则：校准是可演进知识资产，不是硬规则
"""
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embedding.client import get_embedding_client
from app.models.feedback import FeedbackRecord, FeedbackTargetType

# 默认校准阈值（可被 ExpertMemory 覆盖）
_DEFAULT_CALIBRATION_THRESHOLD = 0.90
_DEFAULT_TOP_K = 5


class CalibrationService:
    """校准缓存服务"""

    def __init__(self):
        # EmbeddingService 仅提供 DB 批量回写能力，单条向量化走 embedding client
        # （与 feedback_service.py 保持一致的依赖方式）
        self._embedding_client = get_embedding_client()
        self._threshold = _DEFAULT_CALIBRATION_THRESHOLD
        # TODO: 从 ExpertMemory 加载可调阈值（key=calibration_threshold）

    async def find_calibration(
        self,
        session: AsyncSession,
        query_text: str,
        scope: Optional[str] = None,
        top_k: int = _DEFAULT_TOP_K,
    ) -> Optional[dict]:
        """查找历史校准

        返回 None 表示无匹配校准（需走 LLM）
        返回 dict 表示命中校准：
        {
            "judgment": "match",
            "confidence": 0.95,
            "reason": "历史校准理由",
            "similarity": 0.92,
            "source_feedback_id": "uuid",
        }
        """
        if not query_text or not query_text.strip():
            return None

        # 生成查询向量（失败则回退到 LLM 路径，不阻断主流程）
        try:
            query_embedding = await self._embedding_client.embed_one(query_text)
        except Exception:
            return None

        # pgvector ANN 召回（cosine distance）
        # 使用 <=> cosine distance，相似度 = 1 - distance
        stmt = (
            select(
                FeedbackRecord,
                FeedbackRecord.embedding.cosine_distance(query_embedding).label("distance"),
            )
            .where(
                FeedbackRecord.is_active.is_(True),
                FeedbackRecord.feedback_type == "calibration",
                FeedbackRecord.embedding.is_not(None),
            )
            .order_by("distance")
            .limit(top_k)
        )
        if scope:
            stmt = stmt.where(FeedbackRecord.calibration_scope == scope)

        result = await session.execute(stmt)
        rows = result.all()

        for record, distance in rows:
            similarity = 1.0 - float(distance)
            if similarity >= self._threshold:
                return {
                    "judgment": record.judgment or record.corrected_verdict,
                    "confidence": max(record.calibration_confidence or 0.85, similarity),
                    "reason": record.correction_reason or "历史校准匹配",
                    "similarity": similarity,
                    "source_feedback_id": str(record.id),
                }
        return None

    async def record_calibration(
        self,
        session: AsyncSession,
        target_id: uuid.UUID,
        context_text: str,
        judgment: str,
        original_verdict: str,
        reason: str,
        scope: Optional[str] = None,
        confidence: float = 0.9,
        corrected_by: Optional[uuid.UUID] = None,
    ) -> FeedbackRecord:
        """记录新校准（比对完成后调用，作为未来校准源）"""
        # 生成 embedding（失败时仍写入记录，仅缺向量，与 feedback_service 一致）
        embedding = None
        try:
            embed_text = "\n".join(
                part.strip()
                for part in [scope or "", context_text or "", reason or ""]
                if part and part.strip()
            )
            if embed_text:
                embedding = await self._embedding_client.embed_one(embed_text)
        except Exception:
            pass

        record = FeedbackRecord(
            target_type=FeedbackTargetType.COMPARISON,
            target_id=target_id,
            context_key=scope,
            context_text=context_text,
            original_verdict=original_verdict,
            corrected_verdict=judgment,
            correction_reason=reason,
            corrected_by=corrected_by,
            embedding=embedding,
            is_active=True,
            feedback_type="calibration",
            judgment=judgment,
            calibration_confidence=confidence,
            calibration_scope=scope,
        )
        session.add(record)
        await session.flush()
        return record

    def set_threshold(self, threshold: float):
        """设置校准阈值（运行时可调）"""
        self._threshold = max(0.0, min(1.0, float(threshold)))

    @property
    def threshold(self) -> float:
        return self._threshold


_calibration_service: Optional[CalibrationService] = None


def get_calibration_service() -> CalibrationService:
    global _calibration_service
    if _calibration_service is None:
        _calibration_service = CalibrationService()
    return _calibration_service
