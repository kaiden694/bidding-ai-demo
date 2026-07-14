"""
语义反馈闭环服务

设计要点（v1.2 §13 AI 优先）：
- record_feedback(): 记录专家修正 + 向量化修正理由入库
- recall_similar_feedback(): 向量召回相似历史修正，作为 LLM Prompt 的 few-shot 示例
- 不写硬规则映射，全部走语义召回
- 准确率统计基于历史修正数据，不做硬编码阈值
"""
import uuid
from typing import List, Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embedding.client import get_embedding_client
from app.models.feedback import FeedbackRecord, FeedbackTargetType


# 召回相似修正的最大条数（few-shot 上限）
_RECALL_TOP_K = 3


class FeedbackService:
    """语义反馈闭环服务"""

    def __init__(self):
        self._embedding_client = get_embedding_client()

    async def record_feedback(
        self,
        session: AsyncSession,
        *,
        target_type: FeedbackTargetType,
        target_id: uuid.UUID,
        original_verdict: str,
        corrected_verdict: str,
        correction_reason: str,
        context_key: Optional[str] = None,
        context_text: Optional[str] = None,
        corrected_by: Optional[uuid.UUID] = None,
        metadata: Optional[dict] = None,
    ) -> FeedbackRecord:
        """记录专家修正 + 向量化修正理由

        - 修正理由 + 上下文文本拼接后向量化，便于后续语义召回
        - 同一 target 的新修正默认会让旧修正失效（is_active=False），
          保证召回库中每个 target 仅保留最新一条修正
        """
        # 旧修正置为失效
        existing = await session.execute(
            select(FeedbackRecord).where(
                FeedbackRecord.target_type == target_type,
                FeedbackRecord.target_id == target_id,
                FeedbackRecord.is_active.is_(True),
            )
        )
        for old in existing.scalars().all():
            old.is_active = False

        # 向量化：上下文 + 修正理由
        embed_text = self._build_embed_text(context_text, correction_reason)
        embedding = await self._safe_embed(embed_text)

        record = FeedbackRecord(
            target_type=target_type,
            target_id=target_id,
            context_key=context_key,
            context_text=context_text,
            original_verdict=original_verdict,
            corrected_verdict=corrected_verdict,
            correction_reason=correction_reason,
            corrected_by=corrected_by,
            embedding=embedding,
            is_active=True,
            metadata_json=metadata,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record

    async def recall_similar_feedback(
        self,
        session: AsyncSession,
        *,
        target_type: FeedbackTargetType,
        query_text: str,
        context_key: Optional[str] = None,
        top_k: int = _RECALL_TOP_K,
    ) -> List[FeedbackRecord]:
        """向量召回相似历史修正（用于 LLM Prompt few-shot）

        - 同一 target_type 内做向量相似度召回
        - context_key 非空时优先召回相同参数/条款的修正（精确匹配优先）
        - 仅召回 is_active=True 的记录
        - 召回失败（embedding 服务不可用）时返回空列表，不阻断主流程
        """
        try:
            query_vec = await self._embedding_client.embed_one(query_text)
        except Exception:
            return []

        # 优先：相同 context_key 的精确修正
        if context_key:
            stmt_exact = (
                select(FeedbackRecord)
                .where(
                    FeedbackRecord.target_type == target_type,
                    FeedbackRecord.is_active.is_(True),
                    FeedbackRecord.context_key == context_key,
                )
                .order_by(FeedbackRecord.created_at.desc())
                .limit(top_k)
            )
            exact_result = await session.execute(stmt_exact)
            exact_records = list(exact_result.scalars().all())
            if len(exact_records) >= top_k:
                return exact_records

        # 兜底：向量相似召回
        stmt = (
            select(FeedbackRecord)
            .where(
                FeedbackRecord.target_type == target_type,
                FeedbackRecord.is_active.is_(True),
                FeedbackRecord.embedding.is_not(None),
            )
            .order_by(FeedbackRecord.embedding.cosine_distance(query_vec))
            .limit(top_k)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_stats(
        self,
        session: AsyncSession,
        target_type: Optional[FeedbackTargetType] = None,
    ) -> dict:
        """统计反馈闭环指标

        - total: 总修正数
        - active: 当前生效的修正数
        - by_target_type: 按目标类型分组
        - correction_rate: 修正采纳率（active / total）
        """
        base_filter = []
        if target_type:
            base_filter.append(FeedbackRecord.target_type == target_type)

        total_stmt = select(func.count(FeedbackRecord.id)).where(*base_filter) if base_filter \
            else select(func.count(FeedbackRecord.id))
        total = (await session.execute(total_stmt)).scalar() or 0

        active_filter = list(base_filter) + [FeedbackRecord.is_active.is_(True)]
        active_stmt = select(func.count(FeedbackRecord.id)).where(*active_filter)
        active = (await session.execute(active_stmt)).scalar() or 0

        # 按目标类型分组统计
        group_stmt = (
            select(
                FeedbackRecord.target_type,
                func.count(FeedbackRecord.id),
            )
            .group_by(FeedbackRecord.target_type)
        )
        if base_filter:
            group_stmt = group_stmt.where(*base_filter)
        group_result = await session.execute(group_stmt)
        by_target_type = {
            (row[0].value if hasattr(row[0], "value") else str(row[0])): row[1]
            for row in group_result.all()
        }

        return {
            "total": total,
            "active": active,
            "by_target_type": by_target_type,
            "correction_rate": (active / total) if total > 0 else 0.0,
        }

    @staticmethod
    def _build_embed_text(context_text: Optional[str], reason: str) -> str:
        """拼接向量化文本：上下文 + 修正理由"""
        parts = []
        if context_text:
            parts.append(context_text.strip())
        parts.append(reason.strip())
        return "\n".join(parts)

    async def _safe_embed(self, text: str) -> Optional[list]:
        """安全向量化：失败时返回 None（修正记录仍写入，仅缺向量）"""
        if not text.strip():
            return None
        try:
            return await self._embedding_client.embed_one(text)
        except Exception:
            return None

    # ============================================================
    # Few-Shot 注入（P3-13）
    # ============================================================
    async def add_structure_feedback(
        self,
        session: AsyncSession,
        *,
        raw_text: str,
        correction: str,
        comment: Optional[str] = None,
        corrected_by: Optional[uuid.UUID] = None,
        scope: Optional[str] = None,
    ) -> FeedbackRecord:
        """录入结构识别反馈（feedback_type=structure_recognition）

        - raw_text: 原始文本（被错误识别为某种结构）
        - correction: 正确的结构（如 "这是表格不是段落" / "正确章节是技术规格"）
        - comment: 专家补充说明
        - scope: 文档类别或结构类型（如 "tender" / "table" / "heading"）
        """
        context_text = f"原文：{raw_text[:500]}"
        correction_reason = correction + (f"\n备注：{comment}" if comment else "")
        embedding = await self._safe_embed(
            self._build_embed_text(context_text, correction_reason)
        )
        record = FeedbackRecord(
            target_type=FeedbackTargetType.COMPARISON,  # 复用 comparison 类型（结构识别无独立类型）
            target_id=uuid.uuid4(),  # 占位（结构识别不绑定具体实体）
            context_key=scope or "structure",
            context_text=context_text,
            original_verdict="(误识别)",
            corrected_verdict=correction,
            correction_reason=correction_reason,
            corrected_by=corrected_by,
            embedding=embedding,
            is_active=True,
            feedback_type="structure_recognition",
            judgment=correction,
            calibration_scope=scope,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record

    async def get_structure_examples(
        self,
        session: AsyncSession,
        scope: Optional[str] = None,
        top_k: int = 3,
    ) -> List[FeedbackRecord]:
        """返回最近 N 条结构识别 Few-Shot 范例"""
        stmt = (
            select(FeedbackRecord)
            .where(
                FeedbackRecord.is_active.is_(True),
                FeedbackRecord.feedback_type == "structure_recognition",
            )
            .order_by(FeedbackRecord.created_at.desc())
            .limit(top_k)
        )
        if scope:
            stmt = stmt.where(FeedbackRecord.calibration_scope == scope)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def add_product_name_feedback(
        self,
        session: AsyncSession,
        *,
        raw_text: str,
        corrected_name: str,
        original_name: Optional[str] = None,
        corrected_by: Optional[uuid.UUID] = None,
    ) -> FeedbackRecord:
        """录入产品名识别反馈（feedback_type=product_name）

        - raw_text: 原始文档片段（含产品名）
        - corrected_name: 专家校正后的正确产品名
        - original_name: LLM 原识别的产品名（可能为空）
        """
        context_text = f"原文片段——{raw_text[:500]}"
        correction_reason = f"正确产品名：{corrected_name}"
        if original_name:
            correction_reason = f"原识别：{original_name}\n{correction_reason}"
        embedding = await self._safe_embed(
            self._build_embed_text(context_text, correction_reason)
        )
        record = FeedbackRecord(
            target_type=FeedbackTargetType.COMPARISON,
            target_id=uuid.uuid4(),
            context_key="product_name",
            context_text=context_text,
            original_verdict=original_name or "(未识别)",
            corrected_verdict=corrected_name,
            correction_reason=correction_reason,
            corrected_by=corrected_by,
            embedding=embedding,
            is_active=True,
            feedback_type="product_name",
            judgment=corrected_name,
            calibration_scope="product_name",
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record

    async def get_known_product_names(
        self,
        session: AsyncSession,
        top_k: int = 100,
    ) -> List[str]:
        """返回已知产品白名单（历史反馈中校正过的产品名去重）"""
        stmt = (
            select(FeedbackRecord.corrected_verdict)
            .where(
                FeedbackRecord.is_active.is_(True),
                FeedbackRecord.feedback_type == "product_name",
            )
            .distinct()
            .limit(top_k)
        )
        result = await session.execute(stmt)
        return [
            name for name in result.scalars().all()
            if name and name.strip() and not name.startswith("(")
        ]

    async def get_product_name_examples(
        self,
        session: AsyncSession,
        top_k: int = 3,
    ) -> List[FeedbackRecord]:
        """返回最近 N 条产品名识别 Few-Shot 范例"""
        stmt = (
            select(FeedbackRecord)
            .where(
                FeedbackRecord.is_active.is_(True),
                FeedbackRecord.feedback_type == "product_name",
            )
            .order_by(FeedbackRecord.created_at.desc())
            .limit(top_k)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


_feedback_service: Optional[FeedbackService] = None


def get_feedback_service() -> FeedbackService:
    global _feedback_service
    if _feedback_service is None:
        _feedback_service = FeedbackService()
    return _feedback_service
