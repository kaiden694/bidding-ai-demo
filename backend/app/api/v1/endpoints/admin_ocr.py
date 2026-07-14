"""OCR 提供商管理 + 健康检查端点

挂载在 /admin 前缀下：
- GET    /admin/ocr-providers          列出所有 provider
- POST   /admin/ocr-providers          创建 provider（is_active=True 时自动停用其他）
- PUT    /admin/ocr-providers/{id}      更新 provider
- DELETE /admin/ocr-providers/{id}      删除 provider
- GET    /admin/ocr-providers/active    当前生效的 provider
- POST   /admin/ocr-providers/{id}/health-check  手动健康检查
"""
import time
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.models.ocr_provider import OCRProvider, OCRProviderType
from app.schemas.ocr_provider import (
    OCRHealthCheckResult,
    OCRProviderCreate,
    OCRProviderOut,
    OCRProviderUpdate,
)

router = APIRouter()


# ============================================================
# 健康检查（按 provider_type 分发）
# ============================================================
def _build_mineru_url(base_url: str, suffix: str) -> str:
    """智能拼接 MinerU API URL：自动处理 /api/v4 前缀重复问题

    - base_url=https://mineru.net         → https://mineru.net/api/v4{suffix}
    - base_url=https://mineru.net/api/v4  → https://mineru.net/api/v4{suffix}
    """
    base = base_url.rstrip("/")
    if not base.endswith("/api/v4"):
        base = f"{base}/api/v4"
    return f"{base}{suffix}"


async def _health_check_mineru(provider: OCRProvider) -> tuple[bool, str | None, int]:
    """MinerU 健康检查：用一个伪 task_id 探测 token 有效性

    MinerU API 没有"列出任务"端点，查询任务必须带 task_id。
    用一个不存在的 task_id 调用查询端点：
    - HTTP 200 + 业务错误（如 task not found）→ token 有效，认证通过
    - HTTP 401 → token 无效（user authenticate failed）
    """
    start = time.monotonic()
    try:
        url = _build_mineru_url(provider.base_url, "/extract/task/health-check-probe")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {provider.api_key}"},
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            if resp.status_code == 200:
                # 200 表示认证通过（业务错误如 task not found 也算健康）
                return True, None, latency_ms
            if resp.status_code == 401:
                try:
                    msg = resp.json().get("msg", "user authenticate failed")
                except Exception:
                    msg = resp.text[:200]
                return False, f"token 无效：{msg}", latency_ms
            if resp.status_code == 404:
                return False, f"base_url 错误（404）：{url}", latency_ms
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}", latency_ms
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        return False, f"{type(e).__name__}: {e}", latency_ms


async def _health_check_paddleocr(provider: OCRProvider) -> tuple[bool, str | None, int]:
    """PaddleOCR 健康检查：用 API Key + Secret Key 换 access_token 验证"""
    meta = provider.metadata_json or {}
    secret_key = meta.get("secret_key", "")
    if not secret_key:
        return False, "PaddleOCR 需要 secret_key（存于 metadata_json）", 0

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://aip.baidubce.com/oauth/2.0/token",
                params={
                    "grant_type": "client_credentials",
                    "client_id": provider.api_key,
                    "client_secret": secret_key,
                },
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("access_token"):
                    return True, None, latency_ms
                return False, f"未获取到 access_token：{data.get('error', '未知错误')}", latency_ms
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}", latency_ms
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        return False, f"{type(e).__name__}: {e}", latency_ms


async def _health_check_local(provider: OCRProvider) -> tuple[bool, str | None, int]:
    """本地 rapidocr 健康检查：验证库可导入"""
    start = time.monotonic()
    try:
        import importlib
        importlib.import_module("rapidocr_onnxruntime")
        latency_ms = int((time.monotonic() - start) * 1000)
        return True, None, latency_ms
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        return False, f"rapidocr 未安装：{e}", latency_ms


async def _health_check_other(provider: OCRProvider) -> tuple[bool, str | None, int]:
    """通用健康检查：GET base_url 验证连通性"""
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(provider.base_url)
            latency_ms = int((time.monotonic() - start) * 1000)
            if resp.status_code < 500:
                return True, None, latency_ms
            return False, f"HTTP {resp.status_code}", latency_ms
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        return False, f"{type(e).__name__}: {e}", latency_ms


_HEALTH_CHECKERS = {
    OCRProviderType.MINERU: _health_check_mineru,
    OCRProviderType.PADDLEOCR: _health_check_paddleocr,
    OCRProviderType.LOCAL: _health_check_local,
    OCRProviderType.OTHER: _health_check_other,
}


# ============================================================
# 端点
# ============================================================
@router.get(
    "/ocr-providers",
    response_model=list[OCRProviderOut],
    dependencies=[Depends(require_permission("system:config"))],
)
async def list_providers(db: AsyncSession = Depends(get_db)):
    """列出所有 OCR 提供商"""
    stmt = select(OCRProvider).order_by(OCRProvider.created_at.asc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get(
    "/ocr-providers/active",
    response_model=dict,
    dependencies=[Depends(require_permission("system:config"))],
)
async def active_provider(db: AsyncSession = Depends(get_db)):
    """当前生效的 provider（从 DB 读取）"""
    stmt = select(OCRProvider).where(OCRProvider.is_active == True).limit(1)  # noqa: E712
    provider = (await db.execute(stmt)).scalars().first()
    if provider is None:
        return {"is_active": False, "name": None}
    return {
        "is_active": True,
        "id": str(provider.id),
        "name": provider.name,
        "provider_type": provider.provider_type.value if provider.provider_type else None,
        "base_url": provider.base_url,
        "model": provider.model,
        "is_healthy": provider.is_healthy,
        "consecutive_failures": provider.consecutive_failures,
    }


@router.post(
    "/ocr-providers",
    response_model=OCRProviderOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("system:config"))],
)
async def create_provider(
    payload: OCRProviderCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建 OCR 提供商（is_active=True 时自动停用其他）"""
    existing = await db.execute(
        select(OCRProvider).where(OCRProvider.name == payload.name)
    )
    if existing.scalars().first() is not None:
        raise HTTPException(400, f"provider name 已存在: {payload.name}")

    # 校验 provider_type
    try:
        ptype = OCRProviderType(payload.provider_type)
    except ValueError:
        raise HTTPException(400, f"不支持的 provider_type: {payload.provider_type}")

    provider = OCRProvider(
        name=payload.name,
        provider_type=ptype,
        base_url=payload.base_url,
        api_key=payload.api_key,
        model=payload.model,
        is_active=payload.is_active,
        metadata_json=payload.metadata_json,
    )

    if payload.is_active:
        await db.execute(
            update(OCRProvider)
            .where(OCRProvider.is_active == True)  # noqa: E712
            .values(is_active=False)
        )

    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return provider


@router.put(
    "/ocr-providers/{provider_id}",
    response_model=OCRProviderOut,
    dependencies=[Depends(require_permission("system:config"))],
)
async def update_provider(
    provider_id: uuid.UUID,
    payload: OCRProviderUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新 OCR 提供商"""
    provider = await db.get(OCRProvider, provider_id)
    if provider is None:
        raise HTTPException(404, "provider 不存在")

    data = payload.model_dump(exclude_unset=True)

    if "name" in data and data["name"] != provider.name:
        existing = await db.execute(
            select(OCRProvider).where(OCRProvider.name == data["name"])
        )
        if existing.scalars().first() is not None:
            raise HTTPException(400, f"provider name 已存在: {data['name']}")

    if "provider_type" in data and data["provider_type"]:
        try:
            data["provider_type"] = OCRProviderType(data["provider_type"])
        except ValueError:
            raise HTTPException(400, f"不支持的 provider_type: {data['provider_type']}")

    if data.get("is_active") is True:
        await db.execute(
            update(OCRProvider)
            .where(
                OCRProvider.is_active == True,  # noqa: E712
                OCRProvider.id != provider_id,
            )
            .values(is_active=False)
        )

    for k, v in data.items():
        setattr(provider, k, v)
    await db.commit()
    await db.refresh(provider)
    return provider


@router.delete(
    "/ocr-providers/{provider_id}",
    status_code=204,
    dependencies=[Depends(require_permission("system:config"))],
)
async def delete_provider(
    provider_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """删除 OCR 提供商"""
    provider = await db.get(OCRProvider, provider_id)
    if provider is None:
        raise HTTPException(404, "provider 不存在")
    await db.delete(provider)
    await db.commit()


@router.post(
    "/ocr-providers/{provider_id}/health-check",
    response_model=OCRHealthCheckResult,
    dependencies=[Depends(require_permission("system:config"))],
)
async def trigger_health_check(
    provider_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """手动触发健康检查（按 provider_type 分发不同检查逻辑）"""
    provider = await db.get(OCRProvider, provider_id)
    if provider is None:
        raise HTTPException(404, "provider 不存在")

    checker = _HEALTH_CHECKERS.get(provider.provider_type, _health_check_other)
    is_healthy, error, latency_ms = await checker(provider)

    # 更新 DB
    provider.is_healthy = is_healthy
    provider.last_check_at = datetime.now(timezone.utc)
    provider.consecutive_failures = 0 if is_healthy else provider.consecutive_failures + 1
    await db.commit()
    await db.refresh(provider)

    return OCRHealthCheckResult(
        id=str(provider.id),
        name=provider.name,
        provider_type=provider.provider_type.value if provider.provider_type else "other",
        is_healthy=is_healthy,
        latency_ms=latency_ms,
        error=error,
        last_check_at=provider.last_check_at.isoformat() if provider.last_check_at else None,
    )
