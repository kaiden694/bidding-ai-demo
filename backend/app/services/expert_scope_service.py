"""专家知识多租户 scope 服务（P3-14）

参考 lib-v0.2 expert_rule_service.py 的多租户隔离设计：
- _scoped_id(tenant_id, org_id, raw_id)：SHA1 指纹后取后 12 位（跨租户去重）
- _apply_scope(stmt, tenant_id, org_id)：联合过滤（global 可见 + tenant + org）
- _apply_owned_scope(stmt, tenant_id, org_id)：仅返回当前租户自有数据
- migrate_existing_data：迁移脚本（现有 ExpertRule 填充默认 tenant_id）

设计原则：
- AI-first：scope 仅用于数据隔离，不影响判定逻辑
- global scope 默认对所有租户可见（无需 tenant_id）
- 缺省 tenant_id 视为全局数据（兼容历史数据）
"""
import hashlib
import uuid
from typing import Optional, Any

from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.models.expert_knowledge import ExpertRule, ExpertScope


class ExpertScopeService:
    """专家知识多租户 scope 服务"""

    # ============================================================
    # _scoped_id：tenant_id+org_id+raw_id 指纹后取后 12 位
    # ============================================================
    @staticmethod
    def scoped_id(
        tenant_id: Optional[uuid.UUID], org_id: Optional[uuid.UUID], raw_id: str,
    ) -> str:
        """生成跨租户去重的指纹 ID

        用法：
            fingerprint = ExpertScopeService.scoped_id(tenant_id, org_id, raw_id)
            # 用于 ExpertRule.metadata_json._scoped_id 字段

        实现：SHA1(tenant_id|org_id|raw_id) 取后 12 位
        """
        raw = f"{tenant_id or ''}|{org_id or ''}|{raw_id or ''}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[-12:]

    # ============================================================
    # _apply_scope：联合过滤（global 可见 + tenant + org）
    # ============================================================
    @staticmethod
    def apply_scope(
        stmt, tenant_id: Optional[uuid.UUID], org_id: Optional[uuid.UUID] = None,
    ):
        """应用可见范围过滤

        - global scope：所有租户可见（无 tenant_id 过滤）
        - tenant scope：tenant_id 必须匹配
        - org scope：tenant_id + org_id 必须同时匹配

        返回过滤后的 stmt
        """
        conditions = [
            # global 可见（无需 tenant_id）
            ExpertRule.scope == ExpertScope.GLOBAL,
            # 或 tenant 内可见
            and_(
                ExpertRule.scope == ExpertScope.TENANT,
                ExpertRule.tenant_id == tenant_id,
            ) if tenant_id else False,
        ]
        if tenant_id and org_id:
            conditions.append(
                and_(
                    ExpertRule.scope == ExpertScope.ORG,
                    ExpertRule.tenant_id == tenant_id,
                    ExpertRule.org_id == org_id,
                )
            )
        # 兼容历史数据：scope 为 NULL 或 tenant_id 为 NULL → 视为 global
        conditions.append(ExpertRule.scope.is_(None))
        conditions.append(ExpertRule.tenant_id.is_(None))

        return stmt.where(or_(*[c for c in conditions if c is not False]))

    # ============================================================
    # _apply_owned_scope：仅返回当前租户自有数据
    # ============================================================
    @staticmethod
    def apply_owned_scope(
        stmt, tenant_id: Optional[uuid.UUID], org_id: Optional[uuid.UUID] = None,
    ):
        """仅返回当前租户/组织自有的 ExpertRule

        与 apply_scope 的区别：apply_scope 包含 global 可见数据，
        apply_owned_scope 只返回自己创建的数据（用于"我的规则"列表）
        """
        conditions = []
        if tenant_id:
            conditions.append(ExpertRule.tenant_id == tenant_id)
            if org_id:
                conditions.append(
                    or_(ExpertRule.org_id == org_id, ExpertRule.org_id.is_(None))
                )
        else:
            # 无 tenant_id 视为查询全局数据
            conditions.append(ExpertRule.tenant_id.is_(None))

        return stmt.where(and_(*conditions))

    # ============================================================
    # 迁移脚本：现有数据填充默认 tenant_id
    # ============================================================
    @staticmethod
    async def migrate_existing_data(
        session: AsyncSession,
        default_tenant_id: Optional[uuid.UUID] = None,
        default_org_id: Optional[uuid.UUID] = None,
    ) -> int:
        """迁移脚本：为现有 ExpertRule 填充默认 tenant_id 与 scope

        - 无 tenant_id 的现有数据 → 填充 default_tenant_id（如果提供）
          否则视为 global（scope=GLOBAL）
        - 已有 tenant_id 但 scope=NULL 的数据 → 填充 scope=TENANT
        - 返回更新的行数
        """
        try:
            # 查找需要迁移的数据
            stmt = select(ExpertRule).where(
                or_(ExpertRule.scope.is_(None), ExpertRule.tenant_id.is_(None))
            )
            result = await session.execute(stmt)
            to_migrate = list(result.scalars().all())

            if not to_migrate:
                return 0

            updated = 0
            for rule in to_migrate:
                if rule.tenant_id is None and default_tenant_id:
                    rule.tenant_id = default_tenant_id
                    rule.org_id = rule.org_id or default_org_id
                    rule.scope = ExpertScope.TENANT
                elif rule.tenant_id is None:
                    # 无 default_tenant_id → 视为 global
                    rule.scope = ExpertScope.GLOBAL
                elif rule.scope is None:
                    rule.scope = ExpertScope.TENANT
                updated += 1

            await session.commit()
            logger.info(f"[ExpertScope] 迁移完成：{updated} 条 ExpertRule 已填充默认 scope")
            return updated
        except Exception as e:
            logger.error(f"[ExpertScope] 迁移失败: {e}")
            await session.rollback()
            return 0

    # ============================================================
    # CRUD（带 scope 隔离）
    # ============================================================
    @staticmethod
    async def get_rule(
        session: AsyncSession, key: str,
        tenant_id: Optional[uuid.UUID] = None,
        org_id: Optional[uuid.UUID] = None,
        category: Optional[str] = None,
    ) -> Optional[ExpertRule]:
        """按 key 获取规则（应用 scope 过滤，优先返回租户自有，再回退到 global）"""
        stmt = select(ExpertRule).where(
            ExpertRule.key == key,
            ExpertRule.is_active.is_(True),
            ExpertRule.is_deleted.is_(False),
        )
        if category:
            stmt = stmt.where(ExpertRule.category == category)
        stmt = ExpertScopeService.apply_scope(stmt, tenant_id, org_id)
        # 优先 tenant/org（按 created_at 倒序），global 在最后
        stmt = stmt.order_by(
            ExpertRule.scope != ExpertScope.GLOBAL,  # False (0) 排前
            ExpertRule.created_at.desc(),
        ).limit(1)
        result = await session.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def list_rules(
        session: AsyncSession,
        tenant_id: Optional[uuid.UUID] = None,
        org_id: Optional[uuid.UUID] = None,
        category: Optional[str] = None,
        include_global: bool = True,
    ) -> list[ExpertRule]:
        """列出规则（应用 scope 过滤）

        - include_global=True（默认）：包含 global scope 的规则
        - include_global=False：仅返回当前租户自有（apply_owned_scope）
        """
        stmt = select(ExpertRule).where(
            ExpertRule.is_active.is_(True),
            ExpertRule.is_deleted.is_(False),
        )
        if category:
            stmt = stmt.where(ExpertRule.category == category)
        if include_global:
            stmt = ExpertScopeService.apply_scope(stmt, tenant_id, org_id)
        else:
            stmt = ExpertScopeService.apply_owned_scope(stmt, tenant_id, org_id)
        stmt = stmt.order_by(ExpertRule.created_at.desc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def upsert_rule(
        session: AsyncSession, *,
        key: str, value: Optional[dict] = None,
        text_value: Optional[str] = None,
        category: str = "general",
        description: Optional[str] = None,
        tenant_id: Optional[uuid.UUID] = None,
        org_id: Optional[uuid.UUID] = None,
        scope: ExpertScope = ExpertScope.TENANT,
        created_by: Optional[uuid.UUID] = None,
    ) -> ExpertRule:
        """创建或更新规则（同 key 在 scope 三元组内覆盖）

        自动生成 _scoped_id 写入 metadata_json 用于跨租户去重
        """
        # 查找现有规则（同一 scope + tenant + org + key）
        stmt = select(ExpertRule).where(
            ExpertRule.key == key,
            ExpertRule.scope == scope,
            ExpertRule.tenant_id == tenant_id if tenant_id else ExpertRule.tenant_id.is_(None),
            ExpertRule.org_id == org_id if org_id else ExpertRule.org_id.is_(None),
            ExpertRule.is_deleted.is_(False),
        )
        result = await session.execute(stmt)
        existing = result.scalars().first()

        # 生成 _scoped_id
        raw_id = f"{category}:{key}"
        scoped_id = ExpertScopeService.scoped_id(tenant_id, org_id, raw_id)

        if existing:
            # 更新现有规则
            existing.value = value
            existing.text_value = text_value
            existing.description = description or existing.description
            existing.category = category
            meta = existing.metadata_json or {}
            meta["_scoped_id"] = scoped_id
            existing.metadata_json = meta
            await session.flush()
            return existing

        # 创建新规则
        rule = ExpertRule(
            tenant_id=tenant_id,
            org_id=org_id,
            scope=scope,
            category=category,
            key=key,
            value=value,
            text_value=text_value,
            description=description,
            is_active=True,
            created_by=created_by,
            metadata_json={"_scoped_id": scoped_id},
        )
        session.add(rule)
        await session.flush()
        return rule


# 单例
_service: Optional[ExpertScopeService] = None


def get_expert_scope_service() -> ExpertScopeService:
    global _service
    if _service is None:
        _service = ExpertScopeService()
    return _service
