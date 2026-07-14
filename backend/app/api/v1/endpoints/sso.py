"""SSO/OIDC 单点登录端点（Phase 3 T5）

路由（采用全路径，prefix=""）：
- 公开端点（无需认证）：
  - GET  /auth/sso/providers          列出可用的 SSO 提供商
  - GET  /auth/sso/login              获取 IdP 授权页 URL
  - GET  /auth/sso/callback           OIDC 回调（code 换 token）
  - POST /auth/sso/callback           OIDC 回调（POST 方式，便于 SPA）
- 管理端点（require_permission("system:config")）：
  - GET    /admin/sso-config          列出所有 SSO 配置
  - POST   /admin/sso-config          创建 SSO 配置
  - GET    /admin/sso-config/{id}     获取单个 SSO 配置
  - PUT    /admin/sso-config/{id}      更新 SSO 配置
  - DELETE /admin/sso-config/{id}      删除 SSO 配置
  - POST   /admin/sso-config/{id}/discover  手动触发 discovery
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.schemas.sso import (
    SSOCallbackRequest,
    SSOConfigCreate,
    SSOConfigOut,
    SSOConfigUpdate,
    SSODiscoverResult,
    SSOLoginResponse,
    SSOProviderPublic,
    SSOTokenResponse,
)
from app.services.sso_service import get_sso_service

router = APIRouter()


# ============================================================
# 公开端点：SSO 登录流程
# ============================================================
@router.get(
    "/auth/sso/providers",
    response_model=list[SSOProviderPublic],
)
async def list_sso_providers(db: AsyncSession = Depends(get_db)):
    """列出启用的 SSO 提供商（公开，仅返回 name + display_name）"""
    service = get_sso_service()
    configs = await service.list_active_providers(db)
    return [
        SSOProviderPublic(provider_name=c.provider_name, display_name=c.display_name)
        for c in configs
    ]


@router.get(
    "/auth/sso/login",
    response_model=SSOLoginResponse,
)
async def sso_login(
    provider: str = Query(..., description="SSO 提供商名称"),
    redirect_uri: Optional[str] = Query(None, description="覆盖配置中的回调地址"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """获取 IdP 授权页 URL（前端跳转到此 URL 完成 IdP 登录）"""
    service = get_sso_service()
    user_ip = request.client.host if request and request.client else None
    try:
        result = await service.get_authorization_url(
            db, provider, redirect_uri=redirect_uri, user_ip=user_ip
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return SSOLoginResponse(**result)


@router.get(
    "/auth/sso/callback",
    response_model=SSOTokenResponse,
)
async def sso_callback_get(
    code: str = Query(..., description="OIDC authorization code"),
    state: str = Query(..., description="OIDC state（防 CSRF）"),
    provider: Optional[str] = Query(None, description="SSO 提供商名称（若 state 中已含则可省略）"),
    db: AsyncSession = Depends(get_db),
):
    """OIDC 回调（GET 方式，IdP 重定向回来时使用）"""
    return await _handle_sso_callback(db, provider, code, state)


@router.post(
    "/auth/sso/callback",
    response_model=SSOTokenResponse,
)
async def sso_callback_post(
    payload: SSOCallbackRequest,
    db: AsyncSession = Depends(get_db),
):
    """OIDC 回调（POST 方式，便于 SPA 主动提交 code）"""
    return await _handle_sso_callback(db, payload.provider_name, payload.code, payload.state)


async def _handle_sso_callback(
    db: AsyncSession, provider_name: Optional[str], code: str, state: str
) -> SSOTokenResponse:
    """统一处理 OIDC 回调"""
    service = get_sso_service()
    try:
        result = await service.handle_callback(db, provider_name, code, state)
    except PermissionError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
    except ValueError as e:
        # 区分 IdP 不可达与普通参数错误
        msg = str(e)
        if "无法连接" in msg or "IdP" in msg:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"IdP 调用失败: {msg}")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, msg)
    return SSOTokenResponse(**result)


# ============================================================
# 管理端点：SSO 配置 CRUD
# 注意：固定路径（/sso-config）必须在动态路径 /sso-config/{id} 之前声明
# ============================================================
@router.get(
    "/admin/sso-config",
    response_model=list[SSOConfigOut],
    dependencies=[Depends(require_permission("system:config"))],
)
async def list_sso_configs(db: AsyncSession = Depends(get_db)):
    """列出所有 SSO 配置（client_secret 脱敏输出）"""
    service = get_sso_service()
    return await service.list_configs(db)


@router.post(
    "/admin/sso-config",
    response_model=SSOConfigOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("system:config"))],
)
async def create_sso_config(
    payload: SSOConfigCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建 SSO 配置"""
    service = get_sso_service()
    try:
        config = await service.create_config(db, payload)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return config


@router.get(
    "/admin/sso-config/{config_id}",
    response_model=SSOConfigOut,
    dependencies=[Depends(require_permission("system:config"))],
)
async def get_sso_config(config_id: str, db: AsyncSession = Depends(get_db)):
    """获取单个 SSO 配置"""
    service = get_sso_service()
    config = await service.get_config_by_id(db, config_id)
    if config is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "SSO 配置不存在")
    return config


@router.put(
    "/admin/sso-config/{config_id}",
    response_model=SSOConfigOut,
    dependencies=[Depends(require_permission("system:config"))],
)
async def update_sso_config(
    config_id: str,
    payload: SSOConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新 SSO 配置"""
    service = get_sso_service()
    try:
        config = await service.update_config(db, config_id, payload)
    except ValueError as e:
        msg = str(e)
        if "不存在" in msg:
            raise HTTPException(status.HTTP_404_NOT_FOUND, msg)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, msg)
    return config


@router.delete(
    "/admin/sso-config/{config_id}",
    status_code=204,
    dependencies=[Depends(require_permission("system:config"))],
)
async def delete_sso_config(config_id: str, db: AsyncSession = Depends(get_db)):
    """删除 SSO 配置（物理删除；UserSSOLink 保留以避免破坏历史关联）"""
    service = get_sso_service()
    try:
        await service.delete_config(db, config_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))


@router.post(
    "/admin/sso-config/{config_id}/discover",
    response_model=SSODiscoverResult,
    dependencies=[Depends(require_permission("system:config"))],
)
async def trigger_discovery(config_id: str, db: AsyncSession = Depends(get_db)):
    """手动触发 OIDC discovery（更新端点缓存）"""
    service = get_sso_service()
    config = await service.get_config_by_id(db, config_id)
    if config is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "SSO 配置不存在")
    try:
        doc = await service.discover_endpoints(db, config)
    except ValueError as e:
        # 返回 502 表示上游 IdP 不可达
        return SSODiscoverResult(
            provider_name=config.provider_name,
            issuer=config.issuer,
            success=False,
            error=str(e),
        )
    return SSODiscoverResult(
        provider_name=config.provider_name,
        issuer=config.issuer,
        authorization_endpoint=doc.get("authorization_endpoint"),
        token_endpoint=doc.get("token_endpoint"),
        userinfo_endpoint=doc.get("userinfo_endpoint"),
        success=True,
    )
