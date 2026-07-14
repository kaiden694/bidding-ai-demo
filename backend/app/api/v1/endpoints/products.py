"""产品中心端点：分类管理 + 产品 CRUD + 关联资质/检测报告 + 语义检索"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.models.product import ProductCategory, Product
from app.models.company import Company
from app.models.qualification import Qualification
from app.models.document import Document
from app.models.user import User
from app.schemas.product import (
    ProductCategoryCreate, ProductCategoryOut,
    ProductCreate, ProductOut,
)

router = APIRouter()


# ---------------- 产品分类 ----------------
@router.post("/categories", response_model=ProductCategoryOut, status_code=201)
async def create_category(
    payload: ProductCategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("product:create")),
):
    cat = ProductCategory(**payload.model_dump())
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return cat


@router.get("/categories", response_model=list[ProductCategoryOut])
async def list_categories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("product:view")),
):
    stmt = select(ProductCategory).where(ProductCategory.is_deleted == False).order_by(ProductCategory.sort_order)
    result = await db.execute(stmt)
    return result.scalars().all()


# ---------------- 产品 ----------------
@router.post("", response_model=ProductOut, status_code=201)
async def create_product(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("product:create")),
):
    product = Product(
        name=payload.name,
        code=payload.code,
        category_id=payload.category_id,
        company_id=payload.company_id,
        model=payload.model,
        brand=payload.brand,
        manufacturer=payload.manufacturer,
        description=payload.description,
        specs=[s.model_dump() for s in payload.specs] if payload.specs else None,
        intro_doc_id=payload.intro_doc_id,
        created_by=current_user.id,
    )
    # 关联资质
    if payload.qualification_ids:
        quals = (await db.execute(select(Qualification).where(Qualification.id.in_(payload.qualification_ids)))).scalars().all()
        product.qualifications = quals
    # 关联检测报告
    if payload.test_report_ids:
        docs = (await db.execute(select(Document).where(Document.id.in_(payload.test_report_ids)))).scalars().all()
        product.test_reports = docs
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


@router.get("", response_model=list[ProductOut])
async def list_products(
    category_id: Optional[str] = None,
    company_id: Optional[str] = None,
    keyword: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("product:view")),
):
    """列出产品（支持按分类、公司、关键字筛选）"""
    stmt = (
        select(Product, Company)
        .outerjoin(Company, Product.company_id == Company.id)
        .where(Product.is_deleted == False)
    )
    if category_id:
        stmt = stmt.where(Product.category_id == uuid.UUID(category_id))
    if company_id:
        stmt = stmt.where(Product.company_id == uuid.UUID(company_id))
    if keyword:
        stmt = stmt.where(Product.name.ilike(f"%{keyword}%"))
    stmt = stmt.order_by(Product.sort_order, Product.created_at.desc())
    result = await db.execute(stmt)
    rows = result.all()
    # 附加 company_name / company_type
    out = []
    for product, company in rows:
        item = ProductOut(
            id=product.id,
            name=product.name,
            code=product.code,
            category_id=product.category_id,
            company_id=product.company_id,
            company_name=company.name if company else None,
            company_type=company.company_type.value if company else None,
            model=product.model,
            brand=product.brand,
            manufacturer=product.manufacturer,
            description=product.description,
            specs=product.specs,
            is_published=product.is_published,
            created_at=product.created_at,
        )
        out.append(item)
    return out


@router.get("/{product_id}", response_model=ProductOut)
async def get_product(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("product:view")),
):
    product = await db.get(Product, uuid.UUID(product_id))
    if not product:
        raise HTTPException(404, "产品不存在")
    return product


@router.post("/{product_id}/publish", response_model=ProductOut)
async def publish_product(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("product:publish")),
):
    """产品上架（供比对选型使用）"""
    product = await db.get(Product, uuid.UUID(product_id))
    if not product:
        raise HTTPException(404, "产品不存在")
    product.is_published = True
    await db.commit()
    await db.refresh(product)
    return product


@router.post("/search")
async def search_products(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("product:view")),
):
    """产品语义检索（基于产品资料向量库，供比对选型推荐）"""
    # TODO Phase 1: 简化版关键词检索；Phase 2: 向量召回
    keyword = payload.get("query", "")
    stmt = select(Product).where(Product.is_deleted == False, Product.is_published == True)
    if keyword:
        stmt = stmt.where(Product.name.ilike(f"%{keyword}%"))
    result = await db.execute(stmt)
    return {"results": [{"id": str(p.id), "name": p.name, "code": p.code, "specs": p.specs} for p in result.scalars().all()]}
