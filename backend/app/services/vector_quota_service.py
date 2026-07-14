"""向量块数配额服务（P3-15 T15.2）

参考 lib-v0.2 pgvector_store.enforce_vector_chunk_quota：
- 企业向量块数套餐上限（覆盖所有 *Chunk 表）
- 超限时阻止新增并返回 409 Conflict（不阻断源数据写入，仅阻断派生向量块）

设计原则（v1.2 §13 AI 优先）：
- 配额配置走 ExpertRule 可演化知识资产（category="vector_quota"），
  而非硬编码到代码或环境变量
- 默认套餐 fallback（small/medium/large）仅用于首次启动
- 计数覆盖 4 张派生表：document_chunk / knowledge_chunk /
  general_knowledge_chunk / product_chunk
- 校验在写入流程的入口处（KnowledgeService._import_single_file /
  EmbeddingService.embed_*_chunks）调用，避免单条逐次校验

使用示例：
    from app.services.vector_quota_service import (
        get_vector_quota_service, VectorQuotaError,
    )
    service = get_vector_quota_service()
    try:
        service.enforce_quota(session, planned_count=100)
    except VectorQuotaError as e:
        # API 层捕获后返回 409
        raise HTTPException(409, detail=e.to_dict())
"""
import uuid
from typing import Optional

from loguru import logger
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentChunk, KnowledgeChunk
from app.models.general_knowledge import GeneralKnowledgeChunk
from app.models.product import ProductChunk


# ============================================================
# 默认套餐上限（首次启动 / 未配置 ExpertRule 时使用）
# 设计依据：4 张表合计，按企业规模分级
# ============================================================
_DEFAULT_TIERS = {
    "small": 50_000,    # 小型：5 万块
    "medium": 200_000,  # 中型：20 万块
    "large": 1_000_000,  # 大型：100 万块
}
_DEFAULT_TIER = "medium"


class VectorQuotaError(Exception):
    """向量块数配额超限异常（409 Conflict）

    属性：
    - limit: 套餐上限
    - current: 当前已用块数
    - planned: 本次计划新增
    - projected: 投影后总数（current + planned）
    - tier: 套餐等级（small/medium/large/custom）
    """

    status_code = 409
    error_code = "vector_quota_exceeded"

    def __init__(
        self,
        *,
        limit: int,
        current: int,
        planned: int,
        projected: int,
        tier: str = "custom",
        tenant_id: Optional[uuid.UUID] = None,
        org_id: Optional[uuid.UUID] = None,
    ):
        self.limit = limit
        self.current = current
        self.planned = planned
        self.projected = projected
        self.tier = tier
        self.tenant_id = tenant_id
        self.org_id = org_id
        message = (
            f"企业向量块数已达套餐上限（tier={tier}, limit={limit}）："
            f"current={current} + planned={planned} = projected={projected} > limit={limit}"
        )
        super().__init__(message)

    def to_dict(self) -> dict:
        return {
            "error": self.error_code,
            "message": str(self),
            "status_code": self.status_code,
            "limit": self.limit,
            "current": self.current,
            "planned": self.planned,
            "projected": self.projected,
            "tier": self.tier,
            "tenant_id": str(self.tenant_id) if self.tenant_id else None,
            "org_id": str(self.org_id) if self.org_id else None,
        }


class VectorQuotaService:
    """向量块数配额服务"""

    EXPERT_CATEGORY = "vector_quota"
    EXPERT_KEY_DEFAULT = "default_limit"
    EXPERT_KEY_TENANT = "tenant_limit"  # 可选：按租户覆盖

    # ============================================================
    # 配额查询
    # ============================================================
    async def get_quota_status(
        self,
        session: AsyncSession,
        *,
        tenant_id: Optional[uuid.UUID] = None,
        org_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """查询当前配额状态

        返回 {used, limit, available, tier, projected_after(planned)}
        """
        used = await self.count_all_chunks(session)
        limit, tier = await self._resolve_limit(session, tenant_id, org_id)
        available = max(0, limit - used)
        return {
            "used": used,
            "limit": limit,
            "available": available,
            "tier": tier,
            "tenant_id": str(tenant_id) if tenant_id else None,
            "org_id": str(org_id) if org_id else None,
            "is_exceeded": used >= limit,
        }

    # ============================================================
    # 配额校验（写入流程入口调用）
    # ============================================================
    async def enforce_quota(
        self,
        session: AsyncSession,
        *,
        planned_count: int,
        tenant_id: Optional[uuid.UUID] = None,
        org_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """校验配额：若 current + planned > limit，抛出 VectorQuotaError

        返回 projection dict（不含异常情况）：
        {current, planned, projected, limit, tier, allowed: True}
        """
        try:
            planned = max(0, int(planned_count or 0))
        except (TypeError, ValueError):
            planned = 0

        current = await self.count_all_chunks(session)
        limit, tier = await self._resolve_limit(session, tenant_id, org_id)
        projected = current + planned

        projection = {
            "current": current,
            "planned": planned,
            "projected": projected,
            "limit": limit,
            "tier": tier,
            "allowed": projected <= limit,
        }

        if limit is not None and projected > limit:
            raise VectorQuotaError(
                limit=limit,
                current=current,
                planned=planned,
                projected=projected,
                tier=tier,
                tenant_id=tenant_id,
                org_id=org_id,
            )
        return projection

    # ============================================================
    # 块数统计（4 张派生表合计）
    # ============================================================
    async def count_all_chunks(self, session: AsyncSession) -> int:
        """统计所有派生表的总块数

        覆盖：
        - document_chunk（招标/标书/合同/规格等文档切块）
        - knowledge_chunk（历史标书/合同/经验/范本知识库切块）
        - general_knowledge_chunk（企业资料/政策法规/行业标准切块）
        - product_chunk（产品资料切块）
        """
        total = 0
        for model in (DocumentChunk, KnowledgeChunk, GeneralKnowledgeChunk, ProductChunk):
            try:
                stmt = select(func.count(model.id))
                # 软删除兼容：仅 KnowledgeBase/GeneralKnowledgeBase 有 is_deleted，
                # chunk 表无软删除字段，因此直接 count
                count = (await session.execute(stmt)).scalar() or 0
                total += int(count)
            except Exception as e:
                logger.warning(
                    f"[VectorQuota] 统计 {model.__tablename__} 块数失败（不阻断）: {e}"
                )
        return total

    # ============================================================
    # 配置解析（AI-first：走 ExpertRule 可演化）
    # ============================================================
    async def _resolve_limit(
        self,
        session: AsyncSession,
        tenant_id: Optional[uuid.UUID],
        org_id: Optional[uuid.UUID],
    ) -> tuple[Optional[int], str]:
        """解析当前配额上限

        优先级：
        1. ExpertRule(category=vector_quota, key=tenant_limit)（按租户覆盖，需指定 tenant_id）
        2. ExpertRule(category=vector_quota, key=default_limit)（全局默认）
        3. _DEFAULT_TIERS[_DEFAULT_TIER] fallback

        返回 (limit, tier_name)；limit=None 表示不限制
        """
        try:
            from app.services.expert_scope_service import get_expert_scope_service
            scope_service = get_expert_scope_service()

            # 1. 租户覆盖（如有）
            if tenant_id is not None:
                rule = await scope_service.get_rule(
                    session,
                    key=self.EXPERT_KEY_TENANT,
                    tenant_id=tenant_id,
                    org_id=org_id,
                    category=self.EXPERT_CATEGORY,
                )
                if rule and rule.value:
                    limit = self._normalize_limit(rule.value.get("limit"))
                    if limit is not None:
                        return limit, rule.value.get("tier") or "custom"

            # 2. 全局默认（如有）
            rule = await scope_service.get_rule(
                session,
                key=self.EXPERT_KEY_DEFAULT,
                tenant_id=tenant_id,
                org_id=org_id,
                category=self.EXPERT_CATEGORY,
            )
            if rule and rule.value:
                limit = self._normalize_limit(rule.value.get("limit"))
                if limit is not None:
                    return limit, rule.value.get("tier") or "custom"

        except Exception as e:
            logger.warning(
                f"[VectorQuota] ExpertRule 查询失败，回退默认套餐: {e}"
            )

        # 3. 默认 fallback
        return _DEFAULT_TIERS[_DEFAULT_TIER], _DEFAULT_TIER

    @staticmethod
    def _normalize_limit(value) -> Optional[int]:
        """规范化上限值（None / 非数字 / 负数 → None 表示不限制）"""
        if value is None or value == "":
            return None
        try:
            limit = int(value)
        except (TypeError, ValueError):
            return None
        return limit if limit >= 0 else None

    # ============================================================
    # 配置管理（管理员设置配额）
    # ============================================================
    async def set_default_limit(
        self,
        session: AsyncSession,
        *,
        limit: int,
        tier: str = "custom",
        created_by: Optional[uuid.UUID] = None,
    ) -> None:
        """设置全局默认配额（写入 ExpertRule，AI-first 可演化）

        - limit: 新的上限值（>=0；0 表示禁止新增）
        - tier: 套餐等级标签（small/medium/large/custom）
        """
        from app.models.expert_knowledge import ExpertScope
        from app.services.expert_scope_service import get_expert_scope_service
        scope_service = get_expert_scope_service()

        await scope_service.upsert_rule(
            session,
            key=self.EXPERT_KEY_DEFAULT,
            value={"limit": max(0, int(limit)), "tier": tier},
            category=self.EXPERT_CATEGORY,
            scope=ExpertScope.GLOBAL,
            description=f"向量块数默认上限（tier={tier}）",
            created_by=created_by,
        )
        await session.commit()
        logger.info(
            f"[VectorQuota] 默认配额已更新 → limit={limit}, tier={tier}"
        )

    async def set_tenant_limit(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        limit: int,
        tier: str = "custom",
        org_id: Optional[uuid.UUID] = None,
        created_by: Optional[uuid.UUID] = None,
    ) -> None:
        """设置租户级配额覆盖（写入 ExpertRule，AI-first 可演化）

        - tenant_id: 必填，指定覆盖的租户
        - limit: 新的上限值
        - tier: 套餐等级标签
        """
        from app.models.expert_knowledge import ExpertScope
        from app.services.expert_scope_service import get_expert_scope_service
        scope_service = get_expert_scope_service()

        await scope_service.upsert_rule(
            session,
            key=self.EXPERT_KEY_TENANT,
            value={"limit": max(0, int(limit)), "tier": tier},
            category=self.EXPERT_CATEGORY,
            scope=ExpertScope.TENANT,
            tenant_id=tenant_id,
            org_id=org_id,
            description=f"租户 {tenant_id} 向量块数上限覆盖（tier={tier}）",
            created_by=created_by,
        )
        await session.commit()
        logger.info(
            f"[VectorQuota] 租户 {tenant_id} 配额已覆盖 → limit={limit}, tier={tier}"
        )


# ============================================================
# 单例
# ============================================================
_service: Optional[VectorQuotaService] = None


def get_vector_quota_service() -> VectorQuotaService:
    global _service
    if _service is None:
        _service = VectorQuotaService()
    return _service
