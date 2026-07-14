"""Embedding 提供商管理 + 健康检查端点

挂载在 /admin 前缀下，对外暴露：
- GET    /admin/embedding-providers          列出所有 provider
- POST   /admin/embedding-providers          创建 provider（is_active=True 时自动停用其他）
- PUT    /admin/embedding-providers/{id}      更新 provider
- DELETE /admin/embedding-providers/{id}      删除 provider
- GET    /admin/embedding-providers/active    当前生效的 provider（内存缓存）
- POST   /admin/embedding-providers/{id}/health-check  手动健康检查
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embedding.client import get_embedding_client
from app.api.deps import require_permission
from app.core.database import get_db
from app.models.embedding_provider import EmbeddingProvider
from app.schemas.embedding_provider import (
    EmbeddingHealthCheckResult,
    EmbeddingProviderCreate,
    EmbeddingProviderOut,
    EmbeddingProviderUpdate,
)

router = APIRouter()


# ============================================================
# 固定路径必须在动态路径前
# ============================================================
@router.get(
    "/embedding-providers",
    response_model=list[EmbeddingProviderOut],
    dependencies=[Depends(require_permission("system:config"))],
)
async def list_providers(db: AsyncSession = Depends(get_db)):
    """列出所有 Embedding 提供商"""
    stmt = select(EmbeddingProvider).order_by(EmbeddingProvider.created_at.asc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get(
    "/embedding-providers/active",
    response_model=dict,
    dependencies=[Depends(require_permission("system:config"))],
)
async def active_provider():
    """当前生效的 provider（来自内存缓存）"""
    return get_embedding_client().get_status()


@router.post(
    "/embedding-providers",
    response_model=EmbeddingProviderOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("system:config"))],
)
async def create_provider(
    payload: EmbeddingProviderCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建 Embedding 提供商

    若 is_active=True，自动停用其他所有 provider（同一时刻仅一个生效）
    """
    existing = await db.execute(
        select(EmbeddingProvider).where(EmbeddingProvider.name == payload.name)
    )
    if existing.scalars().first() is not None:
        raise HTTPException(400, f"provider name 已存在: {payload.name}")

    provider = EmbeddingProvider(**payload.model_dump())

    # 若启用当前 provider，先停用其他
    if payload.is_active:
        await db.execute(
            update(EmbeddingProvider)
            .where(EmbeddingProvider.is_active == True)  # noqa: E712
            .values(is_active=False)
        )

    db.add(provider)
    await db.commit()
    await db.refresh(provider)

    # 热加载
    get_embedding_client().reload_providers()
    return provider


@router.put(
    "/embedding-providers/{provider_id}",
    response_model=EmbeddingProviderOut,
    dependencies=[Depends(require_permission("system:config"))],
)
async def update_provider(
    provider_id: uuid.UUID,
    payload: EmbeddingProviderUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新 Embedding 提供商"""
    provider = await db.get(EmbeddingProvider, provider_id)
    if provider is None:
        raise HTTPException(404, "provider 不存在")

    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] != provider.name:
        existing = await db.execute(
            select(EmbeddingProvider).where(EmbeddingProvider.name == data["name"])
        )
        if existing.scalars().first() is not None:
            raise HTTPException(400, f"provider name 已存在: {data['name']}")

    # 若启用当前 provider，先停用其他
    if data.get("is_active") is True:
        await db.execute(
            update(EmbeddingProvider)
            .where(
                EmbeddingProvider.is_active == True,  # noqa: E712
                EmbeddingProvider.id != provider_id,
            )
            .values(is_active=False)
        )

    for k, v in data.items():
        setattr(provider, k, v)
    await db.commit()
    await db.refresh(provider)

    # 热加载
    get_embedding_client().reload_providers()
    return provider


@router.delete(
    "/embedding-providers/{provider_id}",
    status_code=204,
    dependencies=[Depends(require_permission("system:config"))],
)
async def delete_provider(
    provider_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """删除 Embedding 提供商"""
    provider = await db.get(EmbeddingProvider, provider_id)
    if provider is None:
        raise HTTPException(404, "provider 不存在")
    await db.delete(provider)
    await db.commit()

    # 热加载
    get_embedding_client().reload_providers()


@router.post(
    "/embedding-providers/{provider_id}/health-check",
    response_model=EmbeddingHealthCheckResult,
    dependencies=[Depends(require_permission("system:config"))],
)
async def trigger_health_check(
    provider_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """手动触发健康检查（embed "ping"，消耗极少 token）

    直接基于 DB 配置 ping，不依赖内存缓存。
    """
    from openai import AsyncOpenAI

    provider = await db.get(EmbeddingProvider, provider_id)
    if provider is None:
        raise HTTPException(404, "provider 不存在")

    is_healthy = False
    error = None
    latency_ms = None
    import time
    start = time.monotonic()
    try:
        client = AsyncOpenAI(
            base_url=provider.base_url,
            api_key=provider.api_key,
            timeout=30,
        )
        resp = await client.embeddings.create(
            input=["ping"], model=provider.model
        )
        # 校验返回维度
        actual_dim = len(resp.data[0].embedding) if resp.data else 0
        if actual_dim != provider.dim:
            error = f"维度不匹配：期望 {provider.dim}，实际 {actual_dim}"
        else:
            is_healthy = True
        latency_ms = int((time.monotonic() - start) * 1000)
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        error = f"{type(e).__name__}: {e}"

    # 更新 DB
    provider.is_healthy = is_healthy
    provider.last_check_at = datetime.now(timezone.utc)
    provider.consecutive_failures = 0 if is_healthy else provider.consecutive_failures + 1
    await db.commit()
    await db.refresh(provider)

    # 热加载
    get_embedding_client().reload_providers()

    return EmbeddingHealthCheckResult(
        id=str(provider.id),
        name=provider.name,
        is_healthy=is_healthy,
        dim=provider.dim,
        latency_ms=latency_ms,
        error=error,
        last_check_at=provider.last_check_at.isoformat() if provider.last_check_at else None,
    )
