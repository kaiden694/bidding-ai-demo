"""认证端点：登录 / 刷新 / 登出 / 当前用户"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_user_permissions, require_admin
from app.core.casbin import get_enforcer
from app.core.database import get_db
from app.core.security import (
    verify_password, create_access_token, create_refresh_token,
    decode_token, hash_password,
)
from app.models.user import User
from app.schemas.user import (
    LoginRequest, TokenResponse, RefreshRequest, UserInfoResponse,
)

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    """用户名密码登录，返回 access_token + refresh_token + 权限点"""
    stmt = select(User).where(User.username == payload.username, User.is_deleted == False)  # noqa: E712
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "用户已禁用")

    access = create_access_token(str(user.id), {"username": user.username, "is_admin": user.is_admin})
    refresh = create_refresh_token(str(user.id))

    # 获取权限点列表
    if user.is_admin:
        from app.db.base_data import DEFAULT_PERMISSIONS
        perms = [code for code, _, _, _ in DEFAULT_PERMISSIONS]
    else:
        enforcer = get_enforcer()
        perms = enforcer.get_user_permissions(str(user.id))

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        user_id=str(user.id),
        username=user.username,
        full_name=user.full_name,
        is_admin=user.is_admin,
        permissions=perms,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(payload: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """refresh_token 换新 access_token"""
    token_payload = decode_token(payload.refresh_token)
    if not token_payload or token_payload.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh_token 无效")
    user_id = token_payload.get("sub")
    user = await db.get(User, uuid.UUID(user_id))
    if not user or not user.is_active or user.is_deleted:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在或已禁用")

    access = create_access_token(str(user.id), {"username": user.username, "is_admin": user.is_admin})
    new_refresh = create_refresh_token(str(user.id))

    if user.is_admin:
        from app.db.base_data import DEFAULT_PERMISSIONS
        perms = [code for code, _, _, _ in DEFAULT_PERMISSIONS]
    else:
        enforcer = get_enforcer()
        perms = enforcer.get_user_permissions(str(user.id))

    return TokenResponse(
        access_token=access,
        refresh_token=new_refresh,
        user_id=str(user.id),
        username=user.username,
        full_name=user.full_name,
        is_admin=user.is_admin,
        permissions=perms,
    )


@router.post("/logout")
async def logout():
    """登出（Phase 2 占位：JWT 无状态，前端清除 token 即可；Phase 3 接入 Redis 黑名单）"""
    return {"message": "已登出"}


@router.get("/me", response_model=UserInfoResponse)
async def me(
    current_user: User = Depends(get_current_user),
    perms: list[str] = Depends(get_user_permissions),
):
    """获取当前用户信息 + 权限点列表"""
    return UserInfoResponse(
        user_id=str(current_user.id),
        username=current_user.username,
        full_name=current_user.full_name,
        is_admin=current_user.is_admin,
        role_id=str(current_user.role_id) if current_user.role_id else None,
        organization_id=str(current_user.organization_id) if current_user.organization_id else None,
        permissions=perms,
    )


@router.post("/register", response_model=UserInfoResponse)
async def register(
    username: str,
    password: str,
    full_name: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """管理员创建新用户（仅 admin 角色）"""
    existing = await db.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已存在")
    user = User(
        username=username,
        hashed_password=hash_password(password),
        full_name=full_name,
        is_active=True,
        is_admin=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserInfoResponse(
        user_id=str(user.id),
        username=user.username,
        full_name=user.full_name,
        is_admin=user.is_admin,
        permissions=[],
    )
