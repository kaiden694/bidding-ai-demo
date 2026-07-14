"""FastAPI 依赖：认证 + 权限校验 + 项目级数据隔离

Phase 2 升级：
- 移除"匿名管理员放行"逻辑（生产模式不允许）
- get_current_user：解析 JWT → 返回 User（含 role + permissions）
- require_permission(code)：依赖工厂，校验权限点
- get_project_scope：返回用户可访问的 project_id 列表
"""
import uuid
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cached
from app.core.casbin import get_enforcer
from app.core.database import get_db
from app.core.security import decode_token
from app.models.project import Project
from app.models.user import User


async def get_current_user(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """从 JWT 解析当前用户（生产模式：必须携带有效 token）"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未认证")
    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token 无效或已过期")
    user_id = payload.get("sub")
    user = await db.get(User, uuid.UUID(user_id))
    if not user or not user.is_active or user.is_deleted:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在或已禁用")
    return user


def require_permission(perm_code: str):
    """权限校验依赖工厂

    用法：
        @router.post("/...", dependencies=[Depends(require_permission("contract:review"))])
        或
        async def endpoint(user: User = Depends(require_permission("contract:review"))):
    """
    async def _check_permission(
        current_user: User = Depends(get_current_user),
    ) -> User:
        # 管理员放行
        if current_user.is_admin:
            return current_user
        # Casbin 权限校验
        enforcer = get_enforcer()
        if not enforcer.check(str(current_user.id), perm_code):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"权限不足：缺少权限点 [{perm_code}]",
            )
        return current_user

    return _check_permission


@cached(ttl=300, key_prefix="user_permissions")
async def get_user_permissions(current_user: User = Depends(get_current_user)) -> list[str]:
    """获取当前用户的权限点列表

    缓存策略：
    - 权限点列表缓存 5 分钟（Redis 不可用时降级直执行）
    - cache key 由用户对象 id 派生（_serialize_arg 取 User.id）
    - 角色权限变更时需调用 invalidate_cache("user_permissions:*") 失效
    """
    if current_user.is_admin:
        # 管理员拥有所有权限
        from app.db.base_data import DEFAULT_PERMISSIONS
        return [code for code, _, _, _ in DEFAULT_PERMISSIONS]
    enforcer = get_enforcer()
    return enforcer.get_user_permissions(str(current_user.id))


async def get_project_scope(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Optional[list[uuid.UUID]]:
    """获取用户可访问的 project_id 列表

    Phase 2 实现：
    - 管理员：返回 None（不过滤，可访问所有项目）
    - 非管理员：返回用户创建的项目 ID 列表（基于 Project.created_by）
    - TODO Phase 3: 引入 project_member 表实现多角色协作
    """
    if current_user.is_admin:
        return None  # 管理员无限制

    # Phase 2: 用户可访问自己创建的项目
    stmt = select(Project.id).where(
        Project.created_by == current_user.id,
        Project.is_deleted == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    return [row[0] for row in result.all()]


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """要求管理员权限"""
    if not current_user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return current_user
