"""角色管理端点"""
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_permission
from app.core.cache import invalidate_cache
from app.core.casbin import get_enforcer
from app.core.database import get_db
from app.models.user import Role, Permission, role_permission
from app.schemas.user import RoleCreate, RoleUpdate, RoleOut, RolePermissionsUpdate

router = APIRouter()


@router.get("", response_model=list[RoleOut], dependencies=[Depends(require_permission("role:view"))])
async def list_roles(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Role).order_by(Role.created_at))
    return result.scalars().all()


@router.post("", response_model=RoleOut, status_code=201, dependencies=[Depends(require_permission("role:create"))])
async def create_role(payload: RoleCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Role).where(Role.code == payload.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "角色 code 已存在")
    role = Role(code=payload.code, name=payload.name, description=payload.description, is_system=False)
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return role


@router.put("/{role_id}", response_model=RoleOut, dependencies=[Depends(require_permission("role:update"))])
async def update_role(role_id: str, payload: RoleUpdate, db: AsyncSession = Depends(get_db)):
    role = await db.get(Role, uuid.UUID(role_id))
    if not role:
        raise HTTPException(404, "角色不存在")
    if role.is_system:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "系统角色不可修改 code")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(role, field, value)
    await db.commit()
    await db.refresh(role)
    return role


@router.delete("/{role_id}", dependencies=[Depends(require_permission("role:update"))])
async def delete_role(role_id: str, db: AsyncSession = Depends(get_db)):
    """删除自定义角色（系统角色不可删除）"""
    role = await db.get(Role, uuid.UUID(role_id))
    if not role:
        raise HTTPException(404, "角色不存在")
    if role.is_system:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "系统角色不可删除")
    # Role 表无 is_deleted 字段，直接物理删除（仅自定义角色允许）
    await db.delete(role)
    await db.commit()
    return {"message": "角色已删除"}


@router.put("/{role_id}/permissions", dependencies=[Depends(require_permission("role:assign_permissions"))])
async def assign_permissions(role_id: str, payload: RolePermissionsUpdate, db: AsyncSession = Depends(get_db)):
    """分配权限给角色

    缓存失效：角色权限变更后，相关用户的权限点缓存需立即失效
    （@cached(ttl=300) 装饰的 get_user_permissions 会读取旧值）
    """
    role = await db.get(Role, uuid.UUID(role_id))
    if not role:
        raise HTTPException(404, "角色不存在")
    # 清除旧关联
    await db.execute(
        role_permission.delete().where(role_permission.c.role_id == role.id)
    )
    # 新增关联
    for perm_id in payload.permission_ids:
        await db.execute(
            role_permission.insert().values(role_id=role.id, permission_id=perm_id)
        )
    await db.commit()
    # 重载 Casbin 策略
    get_enforcer().reload()
    # 失效用户权限点缓存（角色权限变更影响该角色下所有用户）
    invalidated = await invalidate_cache("user_permissions:*")
    return {
        "message": f"已为角色 {role.code} 分配 {len(payload.permission_ids)} 个权限",
        "cache_invalidated": invalidated,
    }


@router.get("/{role_id}/permissions", dependencies=[Depends(require_permission("role:view"))])
async def get_role_permissions(role_id: str, db: AsyncSession = Depends(get_db)):
    """获取角色的权限点列表"""
    role = await db.get(Role, uuid.UUID(role_id))
    if not role:
        raise HTTPException(404, "角色不存在")
    stmt = (
        select(Permission)
        .join(role_permission, role_permission.c.permission_id == Permission.id)
        .where(role_permission.c.role_id == role.id)
    )
    result = await db.execute(stmt)
    perms = result.scalars().all()
    return [{"id": str(p.id), "code": p.code, "name": p.name, "module": p.module} for p in perms]
