"""LLM 提供商管理 + 健康检查 + 用量统计端点（Phase 3 T3）

权限点：system:config（已存在于 base_data.py DEFAULT_PERMISSIONS）

挂载在 /admin 前缀下，对外暴露：
- GET    /admin/llm-providers          列出所有 provider（DB 配置）
- POST   /admin/llm-providers          创建 provider
- PUT    /admin/llm-providers/{id}      更新 provider
- DELETE /admin/llm-providers/{id}      删除 provider（物理删除）
- GET    /admin/llm-providers/health    健康状态概览（内存缓存 + DB）
- POST   /admin/llm-providers/{id}/health-check  手动触发单个 provider 健康检查
- GET    /admin/llm-usage/stats        用量统计
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm.client import get_llm_client
from app.api.deps import require_permission
from app.core.config import settings
from app.core.database import get_db
from app.models.llm_provider import LLMProvider
from app.schemas.llm_provider import (
    LLMHealthCheckResult,
    LLMProviderCreate,
    LLMProviderOut,
    LLMProviderStatusOut,
    LLMProviderUpdate,
    LLMUsageStatsOut,
)

router = APIRouter()


# ============================================================
# Provider CRUD
# 注意：固定路径（/llm-providers、/llm-providers/health、/llm-usage/stats）
# 必须在动态路径 /llm-providers/{id} 之前声明，避免被 {id} 捕获。
# ============================================================
@router.get(
    "/llm-providers",
    response_model=list[LLMProviderOut],
    dependencies=[Depends(require_permission("system:config"))],
)
async def list_providers(db: AsyncSession = Depends(get_db)):
    """列出所有 LLM 提供商配置"""
    stmt = select(LLMProvider).order_by(LLMProvider.created_at.asc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post(
    "/llm-providers",
    response_model=LLMProviderOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("system:config"))],
)
async def create_provider(
    payload: LLMProviderCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建 LLM 提供商（创建后自动热加载到 LLMClient 内存缓存）"""
    existing = await db.execute(select(LLMProvider).where(LLMProvider.name == payload.name))
    if existing.scalars().first() is not None:
        raise HTTPException(400, f"provider name 已存在: {payload.name}")

    provider = LLMProvider(**payload.model_dump())
    db.add(provider)
    await db.commit()
    await db.refresh(provider)

    # 热加载到内存
    get_llm_client().reload_providers()
    return provider


@router.put(
    "/llm-providers/{provider_id}",
    response_model=LLMProviderOut,
    dependencies=[Depends(require_permission("system:config"))],
)
async def update_provider(
    provider_id: str,
    payload: LLMProviderUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新 LLM 提供商配置"""
    try:
        pid = uuid.UUID(provider_id)
    except ValueError:
        raise HTTPException(400, "无效的 provider id")

    provider = await db.get(LLMProvider, pid)
    if provider is None:
        raise HTTPException(404, "provider 不存在")

    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] != provider.name:
        existing = await db.execute(select(LLMProvider).where(LLMProvider.name == data["name"]))
        if existing.scalars().first() is not None:
            raise HTTPException(400, f"provider name 已存在: {data['name']}")

    for k, v in data.items():
        setattr(provider, k, v)
    await db.commit()
    await db.refresh(provider)

    # 热加载到内存
    get_llm_client().reload_providers()
    return provider


@router.delete(
    "/llm-providers/{provider_id}",
    status_code=204,
    dependencies=[Depends(require_permission("system:config"))],
)
async def delete_provider(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除 LLM 提供商（物理删除；用量日志保留以供统计）"""
    try:
        pid = uuid.UUID(provider_id)
    except ValueError:
        raise HTTPException(400, "无效的 provider id")

    provider = await db.get(LLMProvider, pid)
    if provider is None:
        raise HTTPException(404, "provider 不存在")

    await db.delete(provider)
    await db.commit()

    # 热加载到内存
    get_llm_client().reload_providers()


# ============================================================
# 健康状态概览 + 手动健康检查
# 注意：/health 必须在 /{provider_id} 之前注册（已在本文件中靠前定义动态路由前的位置）
# ============================================================
@router.get(
    "/llm-providers/health",
    response_model=list[LLMProviderStatusOut],
    dependencies=[Depends(require_permission("system:config"))],
)
async def providers_health_overview():
    """LLM provider 运行时健康状态概览（来自 LLMClient 内存缓存，含熔断信息）"""
    return get_llm_client().list_providers_status()


@router.post(
    "/llm-providers/{provider_id}/health-check",
    response_model=LLMHealthCheckResult,
    dependencies=[Depends(require_permission("system:config"))],
)
async def trigger_single_health_check(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
):
    """手动触发单个 provider 健康检查（GET /models，不消耗 token）

    直接基于 DB 配置 ping，不依赖内存缓存（即便 is_active=False 也可检查）
    """
    try:
        pid = uuid.UUID(provider_id)
    except ValueError:
        raise HTTPException(400, "无效的 provider id")

    provider = await db.get(LLMProvider, pid)
    if provider is None:
        raise HTTPException(404, "provider 不存在")

    is_healthy = False
    error = None
    try:
        client = AsyncOpenAI(
            base_url=provider.base_url,
            api_key=provider.api_key,
            timeout=settings.LLM_TIMEOUT,
        )
        await client.models.list()
        is_healthy = True
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    # 更新 DB
    provider.is_healthy = is_healthy
    provider.last_check_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(provider)

    # 热加载到内存（让 LLMClient 感知最新健康状态）
    get_llm_client().reload_providers()

    return LLMHealthCheckResult(
        id=str(provider.id),
        name=provider.name,
        is_healthy=is_healthy,
        error=error,
        last_check_at=provider.last_check_at.isoformat() if provider.last_check_at else None,
    )


# ============================================================
# 用量统计
# ============================================================
@router.get(
    "/llm-usage/stats",
    response_model=LLMUsageStatsOut,
    dependencies=[Depends(require_permission("system:config"))],
)
async def llm_usage_stats(days: int = 7):
    """LLM 用量统计（按 provider 分组，最近 N 天）"""
    if days < 1 or days > 365:
        raise HTTPException(400, "days 取值范围 1~365")
    return await get_llm_client().get_usage_stats(days=days)
