"""权限管理端点"""
from typing import List
from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.models.user import Permission
from app.schemas.user import PermissionOut, PermissionGrouped

router = APIRouter()


@router.get("", response_model=List[PermissionOut], dependencies=[Depends(require_permission("role:view"))])
async def list_permissions(db: AsyncSession = Depends(get_db)):
    """所有权限点列表"""
    result = await db.execute(select(Permission).order_by(Permission.module, Permission.code))
    return result.scalars().all()


@router.get("/grouped", response_model=List[PermissionGrouped], dependencies=[Depends(require_permission("role:view"))])
async def list_permissions_grouped(db: AsyncSession = Depends(get_db)):
    """按模块分组的权限点"""
    result = await db.execute(select(Permission).order_by(Permission.module, Permission.code))
    perms = result.scalars().all()
    grouped = defaultdict(list)
    for p in perms:
        grouped[p.module].append(PermissionOut.model_validate(p, from_attributes=True))
    return [PermissionGrouped(module=mod, permissions=perms_list) for mod, perms_list in grouped.items()]
