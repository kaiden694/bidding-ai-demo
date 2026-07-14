"""公司主数据端点：CRUD + 按类型筛选

供产品中心、资质台账共用，支持公司维度筛选（自营/合作/竞品）。
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.models.company import Company, CompanyType
from app.models.user import User
from app.schemas.company import (
    CompanyCreate, CompanyUpdate, CompanyOut, CompanyBriefOut,
)

router = APIRouter()

# 公司类型中文标签（前端友好）
_COMPANY_TYPE_LABELS = {
    CompanyType.SELF: "本公司",
    CompanyType.PARTNER: "合作公司",
    CompanyType.COMPETITOR: "竞品公司",
    CompanyType.OTHER: "其他",
}


def _to_out(row: Company) -> CompanyOut:
    """附加 company_type_label"""
    return CompanyOut(
        id=row.id,
        name=row.name,
        short_name=row.short_name,
        code=row.code,
        company_type=row.company_type,
        company_type_label=_COMPANY_TYPE_LABELS.get(row.company_type, "其他"),
        description=row.description,
        metadata_json=row.metadata_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=list[CompanyOut])
async def list_companies(
    company_type: Optional[CompanyType] = None,
    keyword: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("system:config")),
):
    """列出公司（支持按类型筛选 + 名称/编码模糊搜索）

    权限：system:config（系统配置）
    """
    stmt = select(Company).where(Company.is_deleted == False)  # noqa: E712
    if company_type is not None:
        stmt = stmt.where(Company.company_type == company_type)
    if keyword:
        kw = f"%{keyword.strip()}%"
        stmt = stmt.where(
            or_(
                Company.name.ilike(kw),
                Company.short_name.ilike(kw),
                Company.code.ilike(kw),
            )
        )
    stmt = stmt.order_by(
        # 本公司优先排序，然后按名称
        Company.company_type != CompanyType.SELF,
        Company.name,
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_to_out(r) for r in rows]


@router.get("/brief", response_model=list[CompanyBriefOut])
async def list_companies_brief(
    company_type: Optional[CompanyType] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("product:view")),
):
    """精简列表（用于下拉选择器）

    权限降级到 product:view（产品/资质录入时需要选公司）
    """
    stmt = select(Company).where(
        Company.is_deleted == False,  # noqa: E712
    )
    if company_type is not None:
        stmt = stmt.where(Company.company_type == company_type)
    stmt = stmt.order_by(
        Company.company_type != CompanyType.SELF,
        Company.name,
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{company_id}", response_model=CompanyOut)
async def get_company(
    company_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("system:config")),
):
    stmt = select(Company).where(
        Company.id == company_id,
        Company.is_deleted == False,  # noqa: E712
    )
    row = (await db.execute(stmt)).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="公司不存在")
    return _to_out(row)


@router.post("", response_model=CompanyOut, status_code=201)
async def create_company(
    payload: CompanyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("system:config")),
):
    # code 唯一性校验
    if payload.code:
        exists = await db.execute(
            select(Company).where(
                Company.code == payload.code,
                Company.is_deleted == False,  # noqa: E712
            )
        )
        if exists.scalars().first():
            raise HTTPException(status_code=400, detail=f"公司编码「{payload.code}」已存在")

    company = Company(
        name=payload.name,
        short_name=payload.short_name,
        code=payload.code,
        company_type=payload.company_type,
        description=payload.description,
        metadata_json=payload.metadata_json,
        created_by=current_user.id,
    )
    db.add(company)
    await db.commit()
    await db.refresh(company)
    return _to_out(company)


@router.put("/{company_id}", response_model=CompanyOut)
async def update_company(
    company_id: uuid.UUID,
    payload: CompanyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("system:config")),
):
    stmt = select(Company).where(
        Company.id == company_id,
        Company.is_deleted == False,  # noqa: E712
    )
    company = (await db.execute(stmt)).scalars().first()
    if company is None:
        raise HTTPException(status_code=404, detail="公司不存在")

    data = payload.model_dump(exclude_unset=True)
    # code 唯一性校验
    if data.get("code"):
        exists = await db.execute(
            select(Company).where(
                Company.code == data["code"],
                Company.id != company_id,
                Company.is_deleted == False,  # noqa: E712
            )
        )
        if exists.scalars().first():
            raise HTTPException(status_code=400, detail=f"公司编码「{data['code']}」已存在")

    for k, v in data.items():
        setattr(company, k, v)

    await db.commit()
    await db.refresh(company)
    return _to_out(company)


@router.delete("/{company_id}", status_code=204)
async def delete_company(
    company_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("system:config")),
):
    stmt = select(Company).where(
        Company.id == company_id,
        Company.is_deleted == False,  # noqa: E712
    )
    company = (await db.execute(stmt)).scalars().first()
    if company is None:
        raise HTTPException(status_code=404, detail="公司不存在")

    # 软删除
    from datetime import datetime, timezone
    company.is_deleted = True
    company.deleted_at = datetime.now(timezone.utc)
    await db.commit()
