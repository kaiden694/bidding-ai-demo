"""组织管理端点（树形）"""
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.models.user import Organization
from app.schemas.user import (
    OrganizationCreate, OrganizationUpdate, OrganizationOut, OrganizationTreeNode,
)

router = APIRouter()


@router.get("", response_model=list[OrganizationOut], dependencies=[Depends(require_permission("organization:view"))])
async def list_organizations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Organization).where(Organization.is_deleted == False).order_by(Organization.sort_order)  # noqa: E712
    )
    return result.scalars().all()


@router.get("/tree", response_model=list[OrganizationTreeNode], dependencies=[Depends(require_permission("organization:view"))])
async def get_organization_tree(db: AsyncSession = Depends(get_db)):
    """获取组织树

    注意：不能用 OrganizationTreeNode.model_validate(o, from_attributes=True)
    因为它会触发 children 关系的 lazy-load，在 async 上下文中报 MissingGreenlet。
    这里手动提取基本字段构建 node，children 初始化为空列表，再按 parent_id 手动组装。
    """
    result = await db.execute(
        select(Organization).where(Organization.is_deleted == False).order_by(Organization.sort_order)  # noqa: E712
    )
    all_orgs = result.scalars().all()
    # 手动构建 node，避免触发 children lazy-load
    org_map = {
        o.id: OrganizationTreeNode(
            id=o.id,
            name=o.name,
            code=o.code,
            parent_id=o.parent_id,
            sort_order=o.sort_order,
            created_at=o.created_at,
            children=[],
        )
        for o in all_orgs
    }
    roots = []
    for o in all_orgs:
        node = org_map[o.id]
        if o.parent_id and o.parent_id in org_map:
            org_map[o.parent_id].children.append(node)
        else:
            roots.append(node)
    return roots


@router.post("", response_model=OrganizationOut, status_code=201, dependencies=[Depends(require_permission("organization:create"))])
async def create_organization(payload: OrganizationCreate, db: AsyncSession = Depends(get_db)):
    # code 唯一性
    existing = await db.execute(select(Organization).where(Organization.code == payload.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "组织 code 已存在")
    # 防环路：parent_id 必须存在且不能是自己
    if payload.parent_id:
        if str(payload.parent_id) == str(payload.parent_id):  # 占位，实际创建时无 id
            pass
        parent = await db.get(Organization, payload.parent_id)
        if not parent or parent.is_deleted:
            raise HTTPException(400, "父组织不存在")
    org = Organization(
        name=payload.name,
        code=payload.code,
        parent_id=payload.parent_id,
        sort_order=payload.sort_order,
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


@router.put("/{org_id}", response_model=OrganizationOut, dependencies=[Depends(require_permission("organization:update"))])
async def update_organization(org_id: str, payload: OrganizationUpdate, db: AsyncSession = Depends(get_db)):
    org = await db.get(Organization, uuid.UUID(org_id))
    if not org or org.is_deleted:
        raise HTTPException(404, "组织不存在")
    data = payload.model_dump(exclude_unset=True)
    # 防环路：parent_id 不能是自己或自己的后代
    if "parent_id" in data and data["parent_id"]:
        new_parent_id = data["parent_id"]
        if str(new_parent_id) == str(org.id):
            raise HTTPException(400, "不能将自己设为父组织")
        # 检查后代环路：遍历新 parent 的祖先链
        current = await db.get(Organization, new_parent_id)
        while current and current.parent_id:
            if str(current.parent_id) == str(org.id):
                raise HTTPException(400, "检测到环路：目标父组织是当前组织的后代")
            current = await db.get(Organization, current.parent_id)
    for field, value in data.items():
        setattr(org, field, value)
    await db.commit()
    await db.refresh(org)
    return org


@router.delete("/{org_id}", dependencies=[Depends(require_permission("organization:delete"))])
async def delete_organization(org_id: str, db: AsyncSession = Depends(get_db)):
    org = await db.get(Organization, uuid.UUID(org_id))
    if not org:
        raise HTTPException(404, "组织不存在")
    org.is_deleted = True
    await db.commit()
    return {"message": "组织已删除"}
